from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session, joinedload

from app import models, schemas
from app.database import get_db
from app.pipeline import PipelineParseError
from app.scheduler.job_manager import create_and_enqueue_job
from app.ai.analyzer import analyze_attempt

router = APIRouter(tags=["jobs"])


@router.post("/api/projects/{project_id}/jobs", response_model=schemas.JobOut, status_code=201)
def trigger_job(project_id: str, payload: schemas.JobCreate, db: Session = Depends(get_db)):
    project = db.get(models.Project, project_id)
    if not project:
        raise HTTPException(404, "project not found")
    try:
        job = create_and_enqueue_job(
            db, project,
            commit_sha=payload.commit_sha,
            branch=payload.branch,
            trigger="manual",
            priority=payload.priority,
        )
    except PipelineParseError as e:
        raise HTTPException(422, f"invalid pipeline: {e}")
    return job


@router.get("/api/jobs/{job_id}", response_model=schemas.JobOut)
def get_job(job_id: str, db: Session = Depends(get_db)):
    job = (
        db.query(models.Job)
        .options(joinedload(models.Job.attempts))
        .filter(models.Job.id == job_id)
        .first()
    )
    if not job:
        raise HTTPException(404, "job not found")
    return job


@router.get("/api/projects/{project_id}/jobs", response_model=list[schemas.JobOut])
def list_jobs(project_id: str, db: Session = Depends(get_db)):
    return (
        db.query(models.Job)
        .options(joinedload(models.Job.attempts))
        .filter(models.Job.project_id == project_id)
        .order_by(models.Job.created_at.desc())
        .limit(100)
        .all()
    )


@router.get("/api/jobs", response_model=list[schemas.JobOut])
def list_all_jobs(db: Session = Depends(get_db)):
    return (
        db.query(models.Job)
        .options(joinedload(models.Job.attempts))
        .order_by(models.Job.created_at.desc())
        .limit(200)
        .all()
    )


@router.get("/api/attempts/{attempt_id}/analysis", response_model=schemas.AIAnalysisOut)
def get_attempt_analysis(attempt_id: str, db: Session = Depends(get_db)):
    attempt = db.get(models.JobAttempt, attempt_id)
    if not attempt:
        raise HTTPException(404, "attempt not found")
    if not attempt.ai_analysis:
        raise HTTPException(404, "no analysis yet for this attempt")
    return attempt.ai_analysis


@router.post("/api/attempts/{attempt_id}/analyze", response_model=schemas.AIAnalysisOut)
def trigger_analysis(attempt_id: str, db: Session = Depends(get_db)):
    """Manually (re)trigger AI analysis for a failed attempt. Normally this
    is invoked automatically when an attempt completes as failed (see
    api/attempts.py), but exposing it lets the dashboard offer a
    're-analyze' button independent of CI execution."""
    attempt = db.get(models.JobAttempt, attempt_id)
    if not attempt:
        raise HTTPException(404, "attempt not found")
    if attempt.status not in (models.AttemptStatus.FAILED, models.AttemptStatus.INFRA_ERROR):
        raise HTTPException(400, "analysis is only available for failed attempts")
    return analyze_attempt(db, attempt)
