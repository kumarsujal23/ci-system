from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy.orm import Session

from app import models, schemas, redis_client
from app.database import get_db
from app.scheduler.lease_manager import claim_next_job

router = APIRouter(prefix="/api/workers", tags=["workers"])


@router.post("/register", response_model=schemas.WorkerOut, status_code=201)
def register_worker(payload: schemas.WorkerRegister, db: Session = Depends(get_db)):
    worker = models.Worker(
        name=payload.name,
        capacity=payload.capacity,
        meta=payload.meta,
        status=models.WorkerStatus.ONLINE,
    )
    db.add(worker)
    db.commit()
    db.refresh(worker)
    return worker


@router.get("", response_model=list[schemas.WorkerOut])
def list_workers(db: Session = Depends(get_db)):
    return db.query(models.Worker).order_by(models.Worker.registered_at.desc()).all()


@router.post("/{worker_id}/heartbeat")
def heartbeat(worker_id: str, db: Session = Depends(get_db)):
    worker = db.get(models.Worker, worker_id)
    if not worker:
        raise HTTPException(404, "worker not found")
    worker.last_heartbeat_at = datetime.now(timezone.utc)
    if worker.status == models.WorkerStatus.DEAD:
        # A worker that comes back after being marked dead re-registers as
        # online but should NOT resume any attempt it previously held -
        # that attempt was already reassigned once its lease expired.
        worker.status = models.WorkerStatus.ONLINE
    db.commit()
    return {"ok": True}


@router.post("/{worker_id}/claim", response_model=schemas.LeaseClaim)
def claim_job(worker_id: str, db: Session = Depends(get_db), response: Response = None):
    worker = db.get(models.Worker, worker_id)
    if not worker:
        raise HTTPException(404, "worker not found")

    attempt = claim_next_job(db, worker)
    if attempt is None:
        return Response(status_code=204)

    job = db.get(models.Job, attempt.job_id)
    project = db.get(models.Project, job.project_id)
    return schemas.LeaseClaim(
        attempt_id=attempt.id,
        job_id=job.id,
        attempt_number=attempt.attempt_number,
        lease_token=attempt.lease_token,
        lease_expires_at=attempt.lease_expires_at,
        pipeline_yaml=job.pipeline_snapshot,
        commit_sha=job.commit_sha,
        repo_url=project.repo_url,
    )
