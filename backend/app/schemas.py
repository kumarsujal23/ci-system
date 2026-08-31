"""Pydantic request/response schemas for the REST + WebSocket API."""
from __future__ import annotations
from datetime import datetime
from typing import Optional, Any
from pydantic import BaseModel, Field, ConfigDict


class ProjectCreate(BaseModel):
    name: str
    repo_url: str
    default_branch: str = "main"
    pipeline_yaml: str = Field(..., description="YAML pipeline definition (steps, image, timeout, etc.)")


class ProjectOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    name: str
    repo_url: str
    default_branch: str
    pipeline_yaml: str
    webhook_token: str
    created_at: datetime


class JobCreate(BaseModel):
    commit_sha: str = "HEAD"
    branch: Optional[str] = None
    priority: int = 0


class PipelineUpdate(BaseModel):
    pipeline_yaml: str = Field(..., description="Updated YAML pipeline definition")


class JobAttemptOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    attempt_number: int
    status: str
    worker_id: Optional[str]
    started_at: Optional[datetime]
    finished_at: Optional[datetime]
    exit_code: Optional[int]
    failed_step: Optional[str]
    is_permanent_failure: bool


class JobOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    project_id: str
    commit_sha: str
    branch: str
    trigger: str
    status: str
    priority: int
    created_at: datetime
    updated_at: datetime
    attempts: list[JobAttemptOut] = []


class WorkerRegister(BaseModel):
    name: str
    capacity: int = 1
    meta: dict[str, Any] = {}


class WorkerOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    name: str
    status: str
    capacity: int
    last_heartbeat_at: datetime
    registered_at: datetime


class LeaseClaim(BaseModel):
    """Response given to a worker that successfully claims a queued job."""
    attempt_id: str
    job_id: str
    attempt_number: int
    lease_token: str
    lease_expires_at: datetime
    pipeline_yaml: str
    commit_sha: str
    repo_url: str


class HeartbeatIn(BaseModel):
    worker_id: str


class AttemptReport(BaseModel):
    """Worker -> server report of an attempt's outcome. Must include the
    lease_token to prove ownership (a worker whose lease already expired
    and was reassigned cannot corrupt a newer attempt's state)."""
    lease_token: str
    exit_code: int
    failed_step: Optional[str] = None
    is_permanent_failure: bool = False
    logs_tail: Optional[str] = None  # final chunk, full log already streamed


class AIAnalysisOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    status: str
    provider: Optional[str]
    model: Optional[str]
    failure_category: Optional[str]
    root_cause: Optional[str]
    explanation: Optional[str]
    suggested_fix: Optional[str]
    confidence: Optional[float]
    error_message: Optional[str]
    created_at: datetime
    completed_at: Optional[datetime]
