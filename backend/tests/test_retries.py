from app import models
from app.config import get_settings
from app.scheduler.job_manager import create_and_enqueue_job
from app.scheduler.lease_manager import claim_next_job, complete_attempt, backoff_seconds

settings = get_settings()


def _fail_infra(db, attempt):
    return complete_attempt(
        db, attempt.id, attempt.lease_token,
        exit_code=1, is_permanent_failure=False, failed_step="checkout",
    )


def test_permanent_failure_is_never_retried(db_session, project, worker):
    job = create_and_enqueue_job(db_session, project, commit_sha="a", branch=None, trigger="manual")
    attempt = claim_next_job(db_session, worker)

    result = complete_attempt(
        db_session, attempt.id, attempt.lease_token,
        exit_code=1, is_permanent_failure=True, failed_step="test",
    )
    attempt, requeued = result
    assert requeued is False
    assert attempt.status == models.AttemptStatus.FAILED

    db_session.refresh(job)
    assert job.status == models.JobStatus.FAILED

    attempts = db_session.query(models.JobAttempt).filter_by(job_id=job.id).all()
    assert len(attempts) == 1  # no retry attempt created


def test_infra_failure_retried_up_to_max_attempts(db_session, project, worker):
    job = create_and_enqueue_job(db_session, project, commit_sha="a", branch=None, trigger="manual")

    for expected_attempt_number in range(1, settings.max_job_attempts + 1):
        attempt = claim_next_job(db_session, worker)
        assert attempt is not None, f"expected a claimable attempt #{expected_attempt_number}"
        assert attempt.attempt_number == expected_attempt_number

        _, requeued = _fail_infra(db_session, attempt)

        # promote it back onto the live queue immediately (bypassing real
        # backoff wait, which is exercised separately) so the loop can claim
        # the next attempt in the test.
        if requeued:
            from app import redis_client
            import time as _t
            r = redis_client.get_redis()
            r.zrem("ci:delayed_queue", *[k for k in r.zrange("ci:delayed_queue", 0, -1)])
            redis_client.enqueue(job.id, job.priority, _t.time())

    db_session.refresh(job)
    assert job.status == models.JobStatus.ERRORED

    attempts = db_session.query(models.JobAttempt).filter_by(job_id=job.id).all()
    assert len(attempts) == settings.max_job_attempts
    assert all(a.status == models.AttemptStatus.INFRA_ERROR for a in attempts)
    # No further attempt should be claimable - budget exhausted.
    assert claim_next_job(db_session, worker) is None


def test_backoff_grows_and_is_capped():
    delays = [backoff_seconds(n) for n in range(1, 10)]
    assert delays == sorted(delays)  # monotonically non-decreasing
    assert delays[-1] <= settings.retry_backoff_max_seconds
    assert delays[0] == settings.retry_backoff_base_seconds
