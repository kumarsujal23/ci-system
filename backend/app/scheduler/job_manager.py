"""
Job creation / enqueue. Separated from the API layer so both the REST
endpoint and the webhook handler share identical logic.
"""
import time
from sqlalchemy.orm import Session

from app import models, redis_client
from app.pipeline import parse_pipeline, PipelineParseError


def create_and_enqueue_job(
    db: Session,
    project: models.Project,
    *,
    commit_sha: str,
    branch: str | None,
    trigger: str,
    priority: int = 0,
) -> models.Job:
    # Validate the pipeline before accepting the job - fail fast rather than
    # accepting a job a worker can never execute.
    parse_pipeline(project.pipeline_yaml)  # raises PipelineParseError if invalid

    job = models.Job(
        project_id=project.id,
        commit_sha=commit_sha,
        branch=branch or project.default_branch,
        trigger=trigger,
        status=models.JobStatus.QUEUED,
        priority=priority,
        pipeline_snapshot=project.pipeline_yaml,  # pin the config used for this run
    )
    db.add(job)
    db.flush()

    from app.scheduler.lease_manager import create_first_attempt
    create_first_attempt(db, job)
    db.commit()
    db.refresh(job)

    redis_client.enqueue(job.id, priority, time.time())
    return job
