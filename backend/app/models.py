"""
SQLAlchemy models — the durable system of record.

Design notes:
- `Job` represents *intent to run a pipeline once* (one queue entry / one commit).
- `JobAttempt` represents one execution try of that job. A job can have many
  attempts (retries on infra failure, requeue after a dead worker). This
  separation is what lets us implement bounded retries + at-least-once
  execution without conflating "the job" with "one worker's run of it".
- Lease fields live on JobAttempt because a lease is owned by a single
  worker's single attempt, not by the job as a whole.
"""
import enum
import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    Column, String, Integer, Float, DateTime, ForeignKey, Text, Enum, Boolean, JSON, Index
)
from sqlalchemy.orm import relationship

from app.database import Base


def _uuid() -> str:
    return str(uuid.uuid4())


def now() -> datetime:
    return datetime.now(timezone.utc)


class JobStatus(str, enum.Enum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"           # permanent failure (e.g. test/compile failure) - not retried
    ERRORED = "errored"         # infra failure, retries exhausted
    CANCELLED = "cancelled"


class AttemptStatus(str, enum.Enum):
    LEASED = "leased"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"          # permanent failure (job's own commands failed)
    INFRA_ERROR = "infra_error"  # worker died / docker error / lease expired
    CANCELLED = "cancelled"


class WorkerStatus(str, enum.Enum):
    ONLINE = "online"
    OFFLINE = "offline"          # graceful shutdown
    DEAD = "dead"                 # missed heartbeats, reaped by scheduler


class FailureCategory(str, enum.Enum):
    COMPILE_ERROR = "compile_error"
    TEST_FAILURE = "test_failure"
    DEPENDENCY_ERROR = "dependency_error"
    TIMEOUT = "timeout"
    INFRA_ERROR = "infra_error"
    CONFIGURATION_ERROR = "configuration_error"
    FLAKY_TEST = "flaky_test"
    UNKNOWN = "unknown"


class Project(Base):
    __tablename__ = "projects"

    id = Column(String, primary_key=True, default=_uuid)
    name = Column(String, nullable=False)
    repo_url = Column(String, nullable=False)
    default_branch = Column(String, default="main")
    pipeline_yaml = Column(Text, nullable=False)  # raw YAML pipeline config
    webhook_token = Column(String, default=_uuid)  # used to validate inbound webhooks
    created_at = Column(DateTime(timezone=True), default=now)

    jobs = relationship("Job", back_populates="project", cascade="all, delete-orphan")


class Job(Base):
    __tablename__ = "jobs"

    id = Column(String, primary_key=True, default=_uuid)
    project_id = Column(String, ForeignKey("projects.id"), nullable=False)
    commit_sha = Column(String, nullable=False)
    branch = Column(String, default="main")
    trigger = Column(String, default="manual")  # manual | webhook
    status = Column(Enum(JobStatus), default=JobStatus.QUEUED, nullable=False)
    priority = Column(Integer, default=0)  # higher = scheduled sooner
    pipeline_snapshot = Column(Text, nullable=False)  # YAML pinned at enqueue time
    created_at = Column(DateTime(timezone=True), default=now)
    updated_at = Column(DateTime(timezone=True), default=now, onupdate=now)

    project = relationship("Project", back_populates="jobs")
    attempts = relationship(
        "JobAttempt", back_populates="job", cascade="all, delete-orphan",
        order_by="JobAttempt.attempt_number",
    )


class JobAttempt(Base):
    __tablename__ = "job_attempts"

    id = Column(String, primary_key=True, default=_uuid)
    job_id = Column(String, ForeignKey("jobs.id"), nullable=False)
    attempt_number = Column(Integer, nullable=False)  # 1-indexed
    status = Column(Enum(AttemptStatus), default=AttemptStatus.LEASED, nullable=False)

    worker_id = Column(String, ForeignKey("workers.id"), nullable=True)
    lease_token = Column(String, nullable=True)          # opaque token proving ownership
    lease_expires_at = Column(DateTime(timezone=True), nullable=True)

    started_at = Column(DateTime(timezone=True), nullable=True)
    finished_at = Column(DateTime(timezone=True), nullable=True)

    exit_code = Column(Integer, nullable=True)
    failed_step = Column(String, nullable=True)
    is_permanent_failure = Column(Boolean, default=False)  # test/compile failure -> no retry
    logs = Column(Text, default="")  # full captured log text (also streamed live via pubsub)

    next_retry_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), default=now)

    job = relationship("Job", back_populates="attempts")
    worker = relationship("Worker", back_populates="attempts")
    ai_analysis = relationship(
        "AIAnalysis", back_populates="attempt", uselist=False, cascade="all, delete-orphan"
    )


# Indexes on hot reaper query paths.
# ix_attempts_reaper: scanned every reaper_interval_seconds to find expired leases.
# ix_attempts_job_id: used by reap_dead_workers, reconcile, and attempt listing.
Index("ix_attempts_reaper", JobAttempt.status, JobAttempt.lease_expires_at)
Index("ix_attempts_job_id", JobAttempt.job_id)


class Worker(Base):
    __tablename__ = "workers"

    id = Column(String, primary_key=True, default=_uuid)
    name = Column(String, nullable=False)
    status = Column(Enum(WorkerStatus), default=WorkerStatus.ONLINE, nullable=False)
    last_heartbeat_at = Column(DateTime(timezone=True), default=now)
    registered_at = Column(DateTime(timezone=True), default=now)
    capacity = Column(Integer, default=1)  # concurrent jobs this worker can run
    meta = Column(JSON, default=dict)      # hostname, docker version, etc.

    attempts = relationship("JobAttempt", back_populates="worker")


class AIAnalysis(Base):
    __tablename__ = "ai_analyses"

    id = Column(String, primary_key=True, default=_uuid)
    attempt_id = Column(String, ForeignKey("job_attempts.id"), nullable=False, unique=True)

    status = Column(String, default="pending")  # pending | completed | unavailable | invalid
    provider = Column(String, nullable=True)
    model = Column(String, nullable=True)

    failure_category = Column(String, nullable=True)
    root_cause = Column(Text, nullable=True)
    explanation = Column(Text, nullable=True)
    suggested_fix = Column(Text, nullable=True)
    confidence = Column(Float, nullable=True)

    raw_response = Column(Text, nullable=True)  # for debugging invalid/partial responses
    error_message = Column(Text, nullable=True)

    created_at = Column(DateTime(timezone=True), default=now)
    completed_at = Column(DateTime(timezone=True), nullable=True)

    attempt = relationship("JobAttempt", back_populates="ai_analysis")
