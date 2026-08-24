import pytest

from app.pipeline import parse_pipeline, PipelineParseError
from app.worker.docker_executor import DockerExecutor


def test_parse_valid_pipeline():
    yaml_text = """
    image: python:3.11-slim
    timeout_seconds: 120
    steps:
      - name: install
        run: pip install -r requirements.txt
      - name: test
        run: pytest -q
    """
    pipeline = parse_pipeline(yaml_text)
    assert pipeline.image == "python:3.11-slim"
    assert len(pipeline.steps) == 2
    assert pipeline.steps[0].name == "install"


def test_parse_rejects_empty_steps():
    with pytest.raises(PipelineParseError):
        parse_pipeline("image: python:3.11-slim\nsteps: []\n")


def test_parse_rejects_invalid_yaml():
    with pytest.raises(PipelineParseError):
        parse_pipeline("image: [unterminated")


def test_parse_rejects_missing_image():
    with pytest.raises(PipelineParseError):
        parse_pipeline("steps:\n  - name: test\n    run: echo hi\n")


class _FakeExecApi:
    """Fakes the subset of docker's low-level API used by DockerExecutor,
    so pipeline execution logic can be tested without a real Docker daemon."""

    def __init__(self, script_exit_codes):
        self.script_exit_codes = script_exit_codes
        self._call_index = 0

    def exec_create(self, container_id, cmd):
        self._call_index += 1
        return {"Id": f"exec-{self._call_index}"}

    def exec_start(self, exec_id, stream=True, demux=False):
        idx = int(exec_id.split("-")[1]) - 1
        code = self.script_exit_codes[idx]
        yield f"running step {idx}\n".encode()
        self._last_code = code

    def exec_inspect(self, exec_id):
        idx = int(exec_id.split("-")[1]) - 1
        return {"ExitCode": self.script_exit_codes[idx]}


class _FakeContainer:
    def __init__(self, client):
        self.id = "fake-container"
        self.client = client

    def kill(self):
        pass

    def remove(self, force=True):
        pass


class _FakeContainers:
    def __init__(self, client):
        self._client = client

    def run(self, image, **kwargs):
        return _FakeContainer(self._client)


class _FakeImages:
    def pull(self, image):
        return None


class _FakeDockerClient:
    def __init__(self, script_exit_codes):
        self.api = _FakeExecApi(script_exit_codes)
        self.containers = _FakeContainers(self)
        self.images = _FakeImages()


# Note on exec ordering: DockerExecutor always runs its own internal
# "checkout" exec (git clone/checkout) BEFORE iterating the pipeline's
# user-declared steps. So exec index 0 is always the internal checkout,
# and declared steps occupy index 1, 2, 3... in order.


def test_successful_pipeline_execution():
    pipeline = parse_pipeline("""
    image: alpine
    steps:
      - name: install
        run: noop
      - name: build
        run: make
    """)
    # idx0=internal checkout, idx1=install, idx2=build -> all succeed
    client = _FakeDockerClient(script_exit_codes=[0, 0, 0])
    executor = DockerExecutor(client=client)
    logs = []
    result = executor.run_pipeline(pipeline, "https://x/repo.git", "abc123", logs.append)
    assert result.exit_code == 0
    assert result.failed_step is None
    assert result.is_permanent_failure is False


def test_failing_step_is_permanent_failure_not_infra():
    pipeline = parse_pipeline("""
    image: alpine
    steps:
      - name: install
        run: noop
      - name: test
        run: pytest
    """)
    # idx0=internal checkout ok, idx1=install ok, idx2=test fails
    client = _FakeDockerClient(script_exit_codes=[0, 0, 1])
    executor = DockerExecutor(client=client)
    logs = []
    result = executor.run_pipeline(pipeline, "https://x/repo.git", "abc123", logs.append)
    assert result.exit_code == 1
    assert result.failed_step == "test"
    assert result.is_permanent_failure is True  # must NOT be retried by the scheduler


def test_checkout_failure_is_infra_not_permanent():
    pipeline = parse_pipeline("""
    image: alpine
    steps:
      - name: test
        run: pytest
    """)
    # idx0=internal checkout fails -> test step never runs
    client = _FakeDockerClient(script_exit_codes=[1, 0])
    executor = DockerExecutor(client=client)
    logs = []
    result = executor.run_pipeline(pipeline, "https://x/repo.git", "abc123", logs.append)
    assert result.failed_step == "checkout"
    assert result.is_permanent_failure is False  # infra-classified, eligible for retry


def test_allow_failure_step_does_not_fail_pipeline():
    pipeline = parse_pipeline("""
    image: alpine
    steps:
      - name: lint
        run: eslint .
        allow_failure: true
      - name: build
        run: make
    """)
    # idx0=internal checkout ok, idx1=lint fails (allowed), idx2=build ok
    client = _FakeDockerClient(script_exit_codes=[0, 1, 0])
    executor = DockerExecutor(client=client)
    logs = []
    result = executor.run_pipeline(pipeline, "https://x/repo.git", "abc123", logs.append)
    assert result.exit_code == 0
    assert result.failed_step is None
