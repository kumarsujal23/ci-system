"""
Executes a pipeline's steps inside an isolated Docker container.

Security posture:
  - Repository commands are NEVER run on the CI server process. They only
    ever run inside a throwaway container started by the worker.
  - Containers get explicit CPU/memory limits and a wall-clock timeout.
  - Network is disabled by default (pipeline.network == "none") unless a
    pipeline opts into "bridge".
  - The container filesystem is discarded after the run (no persistent
    volumes by default beyond the repo checkout).

This module intentionally has a narrow interface (`run_pipeline`) so it can
be unit-tested with a fake Docker client.
"""
from __future__ import annotations
import shlex
import queue
import threading
import time
from dataclasses import dataclass, field
from typing import Callable, Optional

import docker
from docker.errors import DockerException, ContainerError, ImageNotFound

from app.pipeline import Pipeline, PipelineStep
from app.config import get_settings

LogCallback = Callable[[str], None]
settings = get_settings()


@dataclass
class StepResult:
    name: str
    exit_code: int
    duration_seconds: float


@dataclass
class ExecutionResult:
    exit_code: int
    failed_step: Optional[str]
    is_permanent_failure: bool  # True => a command in the pipeline itself failed (not infra)
    step_results: list[StepResult] = field(default_factory=list)
    infra_error: Optional[str] = None  # set when Docker/daemon itself failed


class DockerExecutor:
    def __init__(self, client: Optional[docker.DockerClient] = None):
        self.client = client or docker.from_env()

    def run_pipeline(
        self,
        pipeline: Pipeline,
        repo_url: str,
        commit_sha: str,
        on_log: LogCallback,
        attempt_id: str = "",
    ) -> ExecutionResult:
        try:
            self.client.images.pull(pipeline.image)
        except (ImageNotFound, DockerException) as e:
            on_log(f"[infra] failed to pull image {pipeline.image}: {e}\n")
            return ExecutionResult(
                exit_code=1, failed_step=None, is_permanent_failure=False,
                infra_error=f"image_pull_failed: {e}",
            )

        # Steps run one at a time (not as one big shell script) so we can
        # report *which* step failed and stream logs per-step.
        return self._run_steps(pipeline, repo_url, commit_sha, on_log, attempt_id)

    def _run_steps(self, pipeline: Pipeline, repo_url, commit_sha, on_log, attempt_id: str = "") -> ExecutionResult:
        container = None
        # Name prefix lets operators identify job containers on the shared Docker host.
        container_name = f"ci-job-{attempt_id[:8]}" if attempt_id else None
        try:
            container = self.client.containers.run(
                pipeline.image,
                command="sleep " + str(pipeline.timeout_seconds + 30),
                detach=True,
                name=container_name,
                network_mode=pipeline.network,
                mem_limit=pipeline.resources.memory,
                nano_cpus=int(pipeline.resources.cpus * 1e9),
                working_dir="/workspace",
            )
        except DockerException as e:
            on_log(f"[infra] failed to start container: {e}\n")
            return ExecutionResult(
                exit_code=1, failed_step=None, is_permanent_failure=False,
                infra_error=f"container_start_failed: {e}",
            )

        step_results: list[StepResult] = []
        deadline = time.monotonic() + pipeline.timeout_seconds
        try:
            checkout_cmd = (
                "if ! command -v git >/dev/null 2>&1; then "
                "if command -v apt-get >/dev/null 2>&1; then "
                "apt-get update -qq && DEBIAN_FRONTEND=noninteractive apt-get install -y -qq git; "
                "elif command -v apk >/dev/null 2>&1; then apk add --no-cache git; "
                "else echo '[infra] job image does not provide a supported package manager to install git' >&2; exit 125; fi; fi && "
                f"git clone --depth {settings.git_clone_depth} -- {shlex.quote(repo_url)} /workspace/repo && "
                f"cd /workspace/repo && git checkout {shlex.quote(commit_sha)}"
            )
            ok, code = self._exec(container, checkout_cmd, on_log, "checkout", deadline)
            if not ok:
                return ExecutionResult(
                    exit_code=code, failed_step="checkout", is_permanent_failure=False,
                    step_results=step_results,
                    infra_error="checkout_failed",
                )

            for step in pipeline.steps:
                start = time.monotonic()
                if time.monotonic() > deadline:
                    on_log(f"[infra] timeout before step '{step.name}'\n")
                    return ExecutionResult(
                        exit_code=124, failed_step=step.name, is_permanent_failure=False,
                        step_results=step_results, infra_error="timeout",
                    )
                cmd = f"cd /workspace/repo && {step.run}"
                on_log(f"\n$ {step.run}\n")
                ok, code = self._exec(container, cmd, on_log, step.name, deadline)
                duration = time.monotonic() - start
                step_results.append(StepResult(step.name, code, duration))
                if not ok:
                    if step.allow_failure:
                        on_log(f"[step '{step.name}' failed but allow_failure=true, continuing]\n")
                        continue
                    # A non-zero exit from a user-defined build/test command
                    # is a PERMANENT failure - it is real signal about the
                    # commit and must never be silently retried.
                    return ExecutionResult(
                        exit_code=code, failed_step=step.name, is_permanent_failure=True,
                        step_results=step_results,
                    )

            return ExecutionResult(exit_code=0, failed_step=None, is_permanent_failure=False,
                                    step_results=step_results)
        finally:
            try:
                container.kill()
            except DockerException:
                pass
            try:
                container.remove(force=True)
            except DockerException:
                pass

    def _exec(self, container, cmd: str, on_log: LogCallback, step_name: str, deadline: float):
        # Use the low-level API directly: exec_create + exec_start(stream=True)
        # gives us both a live log stream AND, after the stream ends, an
        # exec_inspect call that reliably returns the real exit code (the
        # high-level container.exec_run(stream=True) does not expose the
        # exec id needed to look this up).
        api = self.client.api
        try:
            exec_id = api.exec_create(container.id, ["sh", "-c", cmd])["Id"]
            stream = api.exec_start(exec_id, stream=True, demux=False)
            chunks: queue.Queue[bytes | None] = queue.Queue()

            def read_stream():
                try:
                    for chunk in stream:
                        chunks.put(chunk)
                except DockerException as e:
                    chunks.put(f"[infra] exec stream failed: {e}\n".encode())
                finally:
                    chunks.put(None)

            reader = threading.Thread(target=read_stream, daemon=True)
            reader.start()
            while True:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    on_log(f"[infra] step '{step_name}' exceeded pipeline timeout\n")
                    return False, 124
                try:
                    chunk = chunks.get(timeout=min(remaining, 0.25))
                except queue.Empty:
                    continue
                if chunk is None:
                    break
                if chunk:
                    on_log(chunk.decode("utf-8", errors="replace"))
            inspect = api.exec_inspect(exec_id)
            exit_code = inspect.get("ExitCode")
            if exit_code is None:
                exit_code = 1  # daemon didn't report a code; treat as failure
            return exit_code == 0, exit_code
        except DockerException as e:
            on_log(f"[infra] exec failed for step '{step_name}': {e}\n")
            return False, 1
