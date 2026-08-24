"""
Lease + retry logic.

Contract:
  - A worker claims a queued job -> gets a JobAttempt with a lease_token and
    lease_expires_at. The worker must renew the lease (via heartbeat) or
    finish before it expires.
  - If a worker dies mid-job, no one calls back. The *reaper* (run by the
    scheduler loop) periodically scans for attempts whose lease has expired
    and whose worker is not heartbeating, and requeues the job for another
    attempt.
  - This gives at-least-once execution: the same commands might run twice if
    a worker dies after finishing but before reporting. We do not claim
    exactly-once.
  - Permanent failures (compile/test failures) are never retried - only
    infra-classified failures (worker died, docker error, lease expiry) count
    against the retry budget, with exponential backoff.
"""
from __future__ import annotations
import secrets
import time
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from app import models
from app.config import get_settings
from app import redis_client

settings = get_settings()


def now() -> datetime:
    return datetime.now(timezone.utc)


def backoff_seconds(attempt_number: int) -> float:
    """Exponential backoff with a cap: base * 2^(n-1), capped."""
    delay = settings.retry_backoff_base_seconds * (2 ** (attempt_number - 1))
    return min(delay, settings.retry_backoff_max_seconds)


def create_first_attempt(db: Session, job: models.Job) -> models.JobAttempt:
    attempt = models.JobAttempt(
        job_id=job.id,
        attempt_number=1,
        status=models.AttemptStatus.LEASED,
    )
    db.add(attempt)
    db.flush()
    return attempt


def claim_next_job(db: Session, worker: models.Worker) -> models.JobAttempt | None:
    """Pop a job id from the Redis queue and materialize/lease its attempt.
    Returns None if the queue is empty or the popped job is no longer valid
    (e.g. was cancelled) — caller should retry claiming."""
    if worker.status != models.WorkerStatus.ONLINE:
        return None

    job_id = redis_client.dequeue_one()
    if job_id is None:
        return None

    job = db.get(models.Job, job_id)
    if job is None or job.status not in (models.JobStatus.QUEUED,):
        return None  # stale queue entry; drop it

    # Find the most recent attempt (created when enqueued/retried) that is
    # still awaiting a worker.
    attempt = (
        db.query(models.JobAttempt)
        .filter(models.JobAttempt.job_id == job.id)
        .order_by(models.JobAttempt.attempt_number.desc())
        .first()
    )
    if attempt is None:
        attempt = create_first_attempt(db, job)

    lease_token = secrets.token_urlsafe(24)
    attempt.worker_id = worker.id
    attempt.status = models.AttemptStatus.LEASED
    attempt.lease_token = lease_token
    attempt.lease_expires_at = now() + timedelta(seconds=settings.job_lease_seconds)
    attempt.started_at = now()

    job.status = models.JobStatus.RUNNING
    db.commit()
    db.refresh(attempt)
    return attempt


def renew_lease(db: Session, attempt_id: str, lease_token: str) -> bool:
    attempt = db.get(models.JobAttempt, attempt_id)
    if attempt is None or attempt.lease_token != lease_token:
        return False
    if attempt.status not in (models.AttemptStatus.LEASED, models.AttemptStatus.RUNNING):
        return False
    attempt.lease_expires_at = now() + timedelta(seconds=settings.job_lease_seconds)
    db.commit()
    return True


def mark_running(db: Session, attempt_id: str, lease_token: str) -> bool:
    attempt = db.get(models.JobAttempt, attempt_id)
    if attempt is None or attempt.lease_token != lease_token:
        return False
    attempt.status = models.AttemptStatus.RUNNING
    db.commit()
    return True


def complete_attempt(
    db: Session,
    attempt_id: str,
    lease_token: str,
    *,
    exit_code: int,
    is_permanent_failure: bool,
    failed_step: str | None,
) -> tuple[models.JobAttempt, bool] | None:
    """Report a finished attempt. Returns (attempt, requeued) or None if the
    lease token is stale (attempt already reassigned to someone else - the
    late report is simply ignored, which is the correct at-least-once
    behavior: whichever report arrives while the lease is still valid wins)."""
    attempt = db.get(models.JobAttempt, attempt_id)
    lease_expires_at = attempt.lease_expires_at if attempt else None
    if lease_expires_at and lease_expires_at.tzinfo is None:
        lease_expires_at = lease_expires_at.replace(tzinfo=timezone.utc)
    if (
        attempt is None
        or attempt.lease_token != lease_token
        or attempt.status not in (models.AttemptStatus.LEASED, models.AttemptStatus.RUNNING)
        or not lease_expires_at
        or lease_expires_at < now()
    ):
        return None

    job = db.get(models.Job, attempt.job_id)
    attempt.finished_at = now()
    attempt.exit_code = exit_code
    attempt.failed_step = failed_step
    attempt.is_permanent_failure = is_permanent_failure

    requeued = False
    if exit_code == 0:
        attempt.status = models.AttemptStatus.SUCCEEDED
        job.status = models.JobStatus.SUCCEEDED
    elif is_permanent_failure:
        # Compile/test failures are real signal - never retried.
        attempt.status = models.AttemptStatus.FAILED
        job.status = models.JobStatus.FAILED
    else:
        # Infrastructure-classified failure - eligible for bounded retry.
        attempt.status = models.AttemptStatus.INFRA_ERROR
        requeued = _maybe_retry(db, job, attempt)

    db.commit()
    db.refresh(attempt)
    return attempt, requeued


def _maybe_retry(db: Session, job: models.Job, failed_attempt: models.JobAttempt) -> bool:
    if failed_attempt.attempt_number >= settings.max_job_attempts:
        job.status = models.JobStatus.ERRORED
        return False

    next_attempt = models.JobAttempt(
        job_id=job.id,
        attempt_number=failed_attempt.attempt_number + 1,
        status=models.AttemptStatus.LEASED,
    )
    # next_attempt is materialized now but only becomes claimable once its
    # backoff delay elapses; we encode that by delaying the re-enqueue.
    db.add(next_attempt)
    db.flush()
    next_attempt.next_retry_at = now() + timedelta(
        seconds=backoff_seconds(failed_attempt.attempt_number)
    )
    job.status = models.JobStatus.QUEUED
    db.flush()
    _schedule_delayed_requeue(job.id, next_attempt.next_retry_at, job.priority)
    return True


def _schedule_delayed_requeue(job_id: str, ready_at: datetime, priority: int) -> None:
    """Push into a Redis-backed delay set; the reaper loop promotes jobs
    whose delay has elapsed into the live queue."""
    r = redis_client.get_redis()
    r.zadd("ci:delayed_queue", {f"{job_id}:{priority}": ready_at.timestamp()})


def promote_delayed_jobs(db: Session) -> int:
    """Move jobs whose retry backoff has elapsed from the delay set into the
    live queue. Called periodically by the scheduler loop."""
    r = redis_client.get_redis()
    cutoff = time.time()
    ready = r.zrangebyscore("ci:delayed_queue", 0, cutoff)
    promoted = 0
    for entry in ready:
        job_id, _, priority = entry.rpartition(":")
        redis_client.enqueue(job_id, int(priority), time.time())
        r.zrem("ci:delayed_queue", entry)
        promoted += 1
    return promoted


def reap_expired_leases(db: Session) -> int:
    """Find attempts whose lease expired without completion (worker likely
    dead) and requeue the job. This is the core dead-worker-recovery path."""
    expired = (
        db.query(models.JobAttempt)
        .filter(
            models.JobAttempt.status.in_(
                [models.AttemptStatus.LEASED, models.AttemptStatus.RUNNING]
            ),
            models.JobAttempt.lease_expires_at < now(),
        )
        .all()
    )
    count = 0
    for attempt in expired:
        job = db.get(models.Job, attempt.job_id)
        attempt.status = models.AttemptStatus.INFRA_ERROR
        attempt.finished_at = now()
        attempt.failed_step = attempt.failed_step or "lease_expired"
        requeued = _maybe_retry(db, job, attempt)
        if not requeued:
            job.status = models.JobStatus.ERRORED
        count += 1
    if count:
        db.commit()
    return count


def reap_dead_workers(db: Session) -> int:
    """Mark workers with stale heartbeats as DEAD. Their in-flight attempts
    are then naturally caught by reap_expired_leases once the lease elapses
    (leases are short by design, typically shorter than the dead-worker
    threshold, so this mostly matters for observability / immediate
    re-queueing rather than being strictly required for correctness)."""
    threshold = now() - timedelta(seconds=settings.worker_dead_after_seconds)
    stale = (
        db.query(models.Worker)
        .filter(
            models.Worker.status == models.WorkerStatus.ONLINE,
            models.Worker.last_heartbeat_at < threshold,
        )
        .all()
    )
    for worker in stale:
        worker.status = models.WorkerStatus.DEAD
        # Immediately expire any leases this worker holds so jobs don't wait
        # out the full lease timeout unnecessarily.
        for attempt in (
            db.query(models.JobAttempt)
            .filter(
                models.JobAttempt.worker_id == worker.id,
                models.JobAttempt.status.in_(
                    [models.AttemptStatus.LEASED, models.AttemptStatus.RUNNING]
                ),
            )
            .all()
        ):
            attempt.lease_expires_at = now()
    if stale:
        db.commit()
    return len(stale)
