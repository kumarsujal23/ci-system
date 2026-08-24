"""
Thin wrapper around Redis used for:
  - FIFO/priority job queue (sorted set: score = -priority, then enqueue time)
  - Pub/Sub channels for live log streaming and status updates
  - Ephemeral worker heartbeats (heartbeats are also mirrored to Postgres,
    Redis is just the low-latency path; Postgres remains the source of truth
    for "is this worker dead" decisions made by the reaper)

Redis is intentionally kept out of the durability path: if Redis is flushed,
the worst case is queued jobs need to be re-enqueued from Postgres (jobs in
QUEUED status with no live attempt), not silent data loss of CI history.
"""
import json
import redis
from app.config import get_settings

settings = get_settings()
_pool = redis.ConnectionPool.from_url(settings.redis_url, decode_responses=True)


def get_redis() -> redis.Redis:
    return redis.Redis(connection_pool=_pool)


QUEUE_KEY = "ci:queue"


def enqueue(job_id: str, priority: int, enqueued_at_ts: float) -> None:
    r = get_redis()
    # Higher priority first; within same priority, FIFO by enqueue timestamp.
    score = (-priority * 10**13) + enqueued_at_ts
    r.zadd(QUEUE_KEY, {job_id: score})


def dequeue_one() -> str | None:
    """Atomically pop the highest-priority/oldest job id, or None if empty."""
    r = get_redis()
    popped = r.zpopmin(QUEUE_KEY, 1)
    if not popped:
        return None
    job_id, _score = popped[0]
    return job_id


def requeue(job_id: str, priority: int, enqueued_at_ts: float) -> None:
    enqueue(job_id, priority, enqueued_at_ts)


def queue_length() -> int:
    return get_redis().zcard(QUEUE_KEY)


def publish_log(attempt_id: str, chunk: str) -> None:
    r = get_redis()
    r.publish(f"{settings.log_channel_prefix}{attempt_id}", chunk)


def publish_status(job_id: str, payload: dict) -> None:
    r = get_redis()
    r.publish(f"{settings.status_channel_prefix}{job_id}", json.dumps(payload))
