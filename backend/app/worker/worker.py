"""
The Worker agent. Runs as an independent process (one per `docker compose
up --scale worker=N`). Polls the CI server for jobs, executes them via
DockerExecutor, streams logs back over HTTP as they're produced (server
fans them out over Redis Pub/Sub -> WebSocket), and reports the outcome.

Fault-tolerance notes:
  - The worker never talks to Postgres directly; it only talks to the
    server's HTTP API. This keeps the server as the sole arbiter of state
    and lets the worker be dumb and disposable.
  - If the worker process dies mid-job, the server's lease will expire and
    the reaper requeues the job - no special handling needed here.
  - The worker renews its lease AND sends heartbeats on a separate,
    independent timer so a slow build step doesn't accidentally starve the
    heartbeat and get itself falsely marked dead.
"""
from __future__ import annotations
import logging
import os
import threading
import time
import uuid

import httpx

from app.pipeline import parse_pipeline
from app.worker.docker_executor import DockerExecutor

logger = logging.getLogger("ci.worker")

SERVER_URL = os.environ.get("CI_SERVER_URL", "http://ci-server:8000")
WORKER_NAME = os.environ.get("CI_WORKER_NAME", f"worker-{uuid.uuid4().hex[:8]}")
POLL_INTERVAL = float(os.environ.get("CI_WORKER_POLL_INTERVAL", "2"))
HEARTBEAT_INTERVAL = float(os.environ.get("CI_WORKER_HEARTBEAT_INTERVAL", "5"))


class Worker:
    def __init__(self):
        self.client = httpx.Client(base_url=SERVER_URL, timeout=30.0)
        self.worker_id: str | None = None
        self.executor = DockerExecutor()
        self._stop = threading.Event()

    def register(self):
        while not self._stop.is_set():
            try:
                resp = self.client.post("/api/workers/register", json={
                    "name": WORKER_NAME, "capacity": 1, "meta": {"pid": os.getpid()},
                })
                resp.raise_for_status()
                self.worker_id = resp.json()["id"]
                logger.info("registered as worker_id=%s name=%s", self.worker_id, WORKER_NAME)
                return
            except httpx.HTTPError as e:
                logger.warning("registration failed, retrying: %s", e)
                self._stop.wait(POLL_INTERVAL)

    def _heartbeat_loop(self):
        while not self._stop.is_set():
            try:
                self.client.post(f"/api/workers/{self.worker_id}/heartbeat")
            except httpx.HTTPError:
                logger.warning("heartbeat failed (server unreachable)")
            time.sleep(HEARTBEAT_INTERVAL)

    def run_forever(self):
        self.register()
        hb_thread = threading.Thread(target=self._heartbeat_loop, daemon=True)
        hb_thread.start()

        logger.info("polling for jobs every %ss", POLL_INTERVAL)
        while not self._stop.is_set():
            try:
                claimed = self._try_claim()
                if claimed:
                    self._execute(claimed)
                else:
                    time.sleep(POLL_INTERVAL)
            except httpx.HTTPError as e:
                logger.warning("server unreachable, retrying: %s", e)
                time.sleep(POLL_INTERVAL)

    def _try_claim(self) -> dict | None:
        resp = self.client.post(f"/api/workers/{self.worker_id}/claim")
        if resp.status_code == 204:
            return None
        resp.raise_for_status()
        return resp.json()

    def _execute(self, lease: dict):
        attempt_id = lease["attempt_id"]
        lease_token = lease["lease_token"]
        logger.info("claimed attempt %s (job %s)", attempt_id, lease["job_id"])

        try:
            pipeline = parse_pipeline(lease["pipeline_yaml"])
        except Exception as e:
            self._report(attempt_id, lease_token, exit_code=1,
                          failed_step="pipeline_parse", is_permanent_failure=True,
                          logs_tail=f"pipeline config invalid: {e}")
            return

        log_buffer: list[str] = []

        def on_log(chunk: str):
            log_buffer.append(chunk)
            try:
                self.client.post(
                    f"/api/attempts/{attempt_id}/logs",
                    json={"lease_token": lease_token, "chunk": chunk},
                )
            except httpx.HTTPError:
                pass  # best-effort live streaming; full log still sent on completion

        # Lease renewal runs alongside execution so long builds don't expire.
        renew_stop = threading.Event()

        def renew_loop():
            while not renew_stop.is_set():
                try:
                    self.client.post(
                        f"/api/attempts/{attempt_id}/renew",
                        json={"lease_token": lease_token},
                    )
                except httpx.HTTPError:
                    pass
                renew_stop.wait(HEARTBEAT_INTERVAL)

        renew_thread = threading.Thread(target=renew_loop, daemon=True)
        renew_thread.start()

        try:
            result = self.executor.run_pipeline(
                pipeline, lease["repo_url"], lease["commit_sha"], on_log,
            )
        finally:
            renew_stop.set()

        self._report(
            attempt_id, lease_token,
            exit_code=result.exit_code,
            failed_step=result.failed_step,
            is_permanent_failure=result.is_permanent_failure,
            logs_tail="".join(log_buffer[-50:]),
        )

    def _report(self, attempt_id, lease_token, *, exit_code, failed_step,
                is_permanent_failure, logs_tail):
        try:
            self.client.post(
                f"/api/attempts/{attempt_id}/complete",
                json={
                    "lease_token": lease_token,
                    "exit_code": exit_code,
                    "failed_step": failed_step,
                    "is_permanent_failure": is_permanent_failure,
                    "logs_tail": logs_tail,
                },
            )
        except httpx.HTTPError as e:
            # If this fails, the lease will simply expire server-side and
            # the job gets requeued - correct at-least-once behavior.
            logger.error("failed to report attempt completion: %s", e)

    def stop(self):
        self._stop.set()


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    Worker().run_forever()


if __name__ == "__main__":
    main()
