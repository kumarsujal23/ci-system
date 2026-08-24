"""
The scheduler's background loop. This is NOT what assigns jobs to workers —
workers pull jobs themselves via POST /workers/{id}/claim (a pull model,
which sidesteps the server needing to track per-worker capacity/liveness in
real time to push work). Instead the scheduler loop is a lightweight *reaper*:
it periodically sweeps for dead workers and expired leases and promotes
delayed (backoff) retries back onto the live queue.

Run standalone via `python -m app.scheduler.scheduler` or embedded as an
asyncio task in the FastAPI app's lifespan.
"""
import asyncio
import logging

from app.database import SessionLocal
from app.config import get_settings
from app.scheduler import lease_manager

logger = logging.getLogger("ci.scheduler")
settings = get_settings()


async def reaper_loop(stop_event: asyncio.Event | None = None):
    while stop_event is None or not stop_event.is_set():
        try:
            run_reaper_once()
        except Exception:
            logger.exception("reaper tick failed")
        await asyncio.sleep(settings.reaper_interval_seconds)


def run_reaper_once() -> dict:
    db = SessionLocal()
    try:
        dead_workers = lease_manager.reap_dead_workers(db)
        expired_leases = lease_manager.reap_expired_leases(db)
        promoted = lease_manager.promote_delayed_jobs(db)
        if dead_workers or expired_leases or promoted:
            logger.info(
                "reaper: dead_workers=%s expired_leases=%s promoted=%s",
                dead_workers, expired_leases, promoted,
            )
        return {
            "dead_workers": dead_workers,
            "expired_leases": expired_leases,
            "promoted": promoted,
        }
    finally:
        db.close()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(reaper_loop())
