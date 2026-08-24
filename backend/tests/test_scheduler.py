import time

from app import models, redis_client
from app.scheduler.job_manager import create_and_enqueue_job
from app.scheduler.lease_manager import claim_next_job


def test_fifo_order_for_equal_priority(db_session, project, worker):
    j1 = create_and_enqueue_job(db_session, project, commit_sha="a", branch=None, trigger="manual")
    time.sleep(0.01)
    j2 = create_and_enqueue_job(db_session, project, commit_sha="b", branch=None, trigger="manual")

    first = claim_next_job(db_session, worker)
    assert first.job_id == j1.id

    second_worker = models.Worker(name="w2")
    db_session.add(second_worker)
    db_session.commit()
    second = claim_next_job(db_session, second_worker)
    assert second.job_id == j2.id


def test_higher_priority_scheduled_first(db_session, project, worker):
    low = create_and_enqueue_job(db_session, project, commit_sha="a", branch=None,
                                  trigger="manual", priority=0)
    time.sleep(0.01)
    high = create_and_enqueue_job(db_session, project, commit_sha="b", branch=None,
                                   trigger="manual", priority=10)

    claimed = claim_next_job(db_session, worker)
    assert claimed.job_id == high.id  # despite being enqueued second


def test_empty_queue_returns_none(db_session, worker):
    assert claim_next_job(db_session, worker) is None


def test_concurrent_workers_never_double_claim_same_job(db_session, project):
    """Two workers racing to claim from the queue must never end up both
    holding the same job - Redis's atomic ZPOPMIN enforces this."""
    create_and_enqueue_job(db_session, project, commit_sha="a", branch=None, trigger="manual")

    w1 = models.Worker(name="w1")
    w2 = models.Worker(name="w2")
    db_session.add_all([w1, w2])
    db_session.commit()

    a1 = claim_next_job(db_session, w1)
    a2 = claim_next_job(db_session, w2)

    assert a1 is not None
    assert a2 is None  # queue only had one job
