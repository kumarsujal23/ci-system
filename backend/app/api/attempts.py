from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app import models, schemas, redis_client
from app.database import get_db
from app.scheduler import lease_manager
from app.ai.analyzer import analyze_attempt

router = APIRouter(prefix="/api/attempts", tags=["attempts"])


class LogChunkIn(BaseModel):
    lease_token: str
    chunk: str


class RenewIn(BaseModel):
    lease_token: str


@router.post("/{attempt_id}/logs")
def append_log(attempt_id: str, payload: LogChunkIn, db: Session = Depends(get_db)):
    attempt = db.get(models.JobAttempt, attempt_id)
    if (
        not attempt
        or attempt.lease_token != payload.lease_token
        or attempt.status not in (models.AttemptStatus.LEASED, models.AttemptStatus.RUNNING)
    ):
        raise HTTPException(409, "stale or invalid lease - attempt likely reassigned")
    attempt.logs = (attempt.logs or "") + payload.chunk
    db.commit()
    # Fan out to any connected WebSocket viewers in real time.
    redis_client.publish_log(attempt_id, payload.chunk)
    return {"ok": True}


@router.get("/{attempt_id}/logs", response_class=PlainTextResponse)
def get_logs(attempt_id: str, db: Session = Depends(get_db)):
    """REST fallback for stored attempt logs. The canonical live view is via
    WebSocket (/ws/attempts/{id}/logs), but this endpoint lets API clients
    and scripts fetch the full persisted log without a WebSocket connection."""
    attempt = db.get(models.JobAttempt, attempt_id)
    if not attempt:
        raise HTTPException(404, "attempt not found")
    return attempt.logs or ""


@router.post("/{attempt_id}/renew")
def renew(attempt_id: str, payload: RenewIn, db: Session = Depends(get_db)):
    ok = lease_manager.renew_lease(db, attempt_id, payload.lease_token)
    if not ok:
        raise HTTPException(409, "lease renewal rejected - already reassigned or terminal")
    lease_manager.mark_running(db, attempt_id, payload.lease_token)
    return {"ok": True}


@router.post("/{attempt_id}/complete", response_model=schemas.JobAttemptOut)
def complete(attempt_id: str, payload: schemas.AttemptReport,
             background_tasks: BackgroundTasks, db: Session = Depends(get_db)):
    if payload.logs_tail:
        attempt_check = db.get(models.JobAttempt, attempt_id)
        if attempt_check and attempt_check.lease_token == payload.lease_token:
            attempt_check.logs = (attempt_check.logs or "") + payload.logs_tail
            db.commit()

    result = lease_manager.complete_attempt(
        db, attempt_id, payload.lease_token,
        exit_code=payload.exit_code,
        is_permanent_failure=payload.is_permanent_failure,
        failed_step=payload.failed_step,
    )
    if result is None:
        raise HTTPException(409, "stale lease - attempt already reassigned, report ignored")
    attempt, requeued = result

    redis_client.publish_status(attempt.job_id, {
        "attempt_id": attempt.id,
        "status": attempt.status.value,
        "requeued": requeued,
    })

    # Trigger AI analysis as a background task so a slow LLM call (up to
    # ai_timeout_seconds) never adds latency to the worker's completion report.
    # The CI pass/fail verdict is already finalized above and is completely
    # unaffected by whatever happens in the background task.
    if attempt.status in (models.AttemptStatus.FAILED, models.AttemptStatus.INFRA_ERROR):
        background_tasks.add_task(_run_analysis, attempt.id)

    return attempt


def _run_analysis(attempt_id: str) -> None:
    """Background task: analyze a failed attempt. Runs after the HTTP response
    is sent, so a slow or unavailable LLM never blocks the worker's report."""
    from app.database import SessionLocal
    db = SessionLocal()
    try:
        attempt = db.get(models.JobAttempt, attempt_id)
        if attempt:
            try:
                analyze_attempt(db, attempt)
            except Exception:
                pass  # Absolute last-resort guard: AI must never affect CI correctness.
    finally:
        db.close()
