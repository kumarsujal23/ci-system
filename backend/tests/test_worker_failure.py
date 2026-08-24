from datetime import datetime, timedelta, timezone

from app import models
from app.scheduler.job_manager import create_and_enqueue_job
from app.scheduler.lease_manager import claim_next_job, reap_expired_leases, reap_dead_workers
from app.config import get_settings

settings = get_settings()


def test_lease_expiry_requeues_job(db_session, project, worker):
    job = create_and_enqueue_job(db_session, project, commit_sha="a", branch=None, trigger="manual")
    attempt = claim_next_job(db_session, worker)
    assert attempt.attempt_number == 1

    # Simulate the worker dying: force the lease into the past.
    attempt.lease_expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
    db_session.commit()

    reaped = reap_expired_leases(db_session)
    assert reaped == 1

    db_session.refresh(job)
    assert job.status == models.JobStatus.QUEUED

    # A second attempt should now exist, ready to be claimed once its
    # backoff delay elapses (we don't wait here - just assert it exists).
    attempts = (
        db_session.query(models.JobAttempt)
        .filter(models.JobAttempt.job_id == job.id)
        .order_by(models.JobAttempt.attempt_number)
        .all()
    )
    assert len(attempts) == 2
    assert attempts[0].status == models.AttemptStatus.INFRA_ERROR
    assert attempts[1].attempt_number == 2


def test_dead_worker_heartbeat_detection(db_session, worker):
    worker.last_heartbeat_at = datetime.now(timezone.utc) - timedelta(
        seconds=settings.worker_dead_after_seconds + 5
    )
    db_session.commit()

    reaped = reap_dead_workers(db_session)
    assert reaped == 1
    db_session.refresh(worker)
    assert worker.status == models.WorkerStatus.DEAD


def test_dead_worker_lease_immediately_expired(db_session, project, worker):
    create_and_enqueue_job(db_session, project, commit_sha="a", branch=None, trigger="manual")
    attempt = claim_next_job(db_session, worker)

    worker.last_heartbeat_at = datetime.now(timezone.utc) - timedelta(
        seconds=settings.worker_dead_after_seconds + 5
    )
    db_session.commit()

    reap_dead_workers(db_session)
    db_session.refresh(attempt)
    # Lease should be force-expired (<=now), not left at its original TTL.
    # (SQLite in tests drops tzinfo on round-trip, so compare naively.)
    now_naive = datetime.now(timezone.utc).replace(tzinfo=None)
    lease_expires = attempt.lease_expires_at
    if lease_expires.tzinfo is not None:
        lease_expires = lease_expires.astimezone(timezone.utc).replace(tzinfo=None)
    assert lease_expires <= now_naive


def test_late_completion_report_after_reassignment_is_ignored(db_session, project, worker):
    """A worker that was presumed dead and whose job was reassigned must
    not be able to corrupt the new attempt's state by reporting late."""
    from app.scheduler.lease_manager import complete_attempt

    job = create_and_enqueue_job(db_session, project, commit_sha="a", branch=None, trigger="manual")
    attempt = claim_next_job(db_session, worker)
    old_token = attempt.lease_token

    # Force expiry and reap -> job requeued, new attempt created.
    attempt.lease_expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
    db_session.commit()
    reap_expired_leases(db_session)

    # The original (zombie) worker now reports completion using its stale token.
    result = complete_attempt(
        db_session, attempt.id, old_token,
        exit_code=0, is_permanent_failure=False, failed_step=None,
    )
    # The old attempt is terminal after reaping, so its token must no longer
    # be accepted even though the token value itself was not replaced.
    assert result is None
    db_session.refresh(job)
    attempts = (
        db_session.query(models.JobAttempt)
        .filter(models.JobAttempt.job_id == job.id)
        .order_by(models.JobAttempt.attempt_number)
        .all()
    )
    assert attempts[0].status == models.AttemptStatus.INFRA_ERROR
    assert len(attempts) == 2  # attempt 2 (the requeue) is untouched by it
