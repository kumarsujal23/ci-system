"""
Minimal GitHub webhook receiver for push events. Verifies the payload
against a per-project token (passed as a query param configured in the
GitHub webhook URL) rather than implementing full HMAC signature
verification, to keep the portfolio project's setup simple - the code is
structured so swapping in `X-Hub-Signature-256` HMAC verification is a
localized change in `_verify`.
"""
import hashlib
import hmac

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app import models
from app.database import get_db
from app.pipeline import PipelineParseError
from app.scheduler.job_manager import create_and_enqueue_job

router = APIRouter(prefix="/api/webhooks", tags=["webhooks"])


def _verify(project: models.Project, token: str | None) -> bool:
    if not token:
        return False
    return hmac.compare_digest(token, project.webhook_token)


@router.post("/github/{project_id}")
async def github_webhook(project_id: str, request: Request, token: str | None = None,
                          db: Session = Depends(get_db)):
    project = db.get(models.Project, project_id)
    if not project:
        raise HTTPException(404, "project not found")
    if not _verify(project, token):
        raise HTTPException(401, "invalid or missing webhook token")

    payload = await request.json()
    event = request.headers.get("X-GitHub-Event", "push")
    if event != "push":
        return {"ignored": True, "reason": f"unsupported event type: {event}"}

    commit_sha = payload.get("after") or payload.get("head_commit", {}).get("id")
    ref = payload.get("ref", "")  # e.g. refs/heads/main
    branch = ref.rsplit("/", 1)[-1] if ref else project.default_branch
    if not commit_sha:
        raise HTTPException(400, "push payload missing commit sha")

    try:
        job = create_and_enqueue_job(
            db, project, commit_sha=commit_sha, branch=branch, trigger="webhook",
        )
    except PipelineParseError as e:
        raise HTTPException(422, f"invalid pipeline: {e}")

    return {"job_id": job.id, "status": job.status.value}
