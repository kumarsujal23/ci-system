"""
Structured contract for the AI Failure Analyzer. The LLM is instructed to
return exactly this JSON shape; the response is parsed and *validated*
through this Pydantic model before it's trusted anywhere in the system.
Anything that doesn't validate is treated as an unavailable/invalid analysis
(the CI job's own pass/fail result is never affected by this)."""
from __future__ import annotations
from typing import Literal
from pydantic import BaseModel, Field, field_validator

FailureCategoryLiteral = Literal[
    "compile_error",
    "test_failure",
    "dependency_error",
    "timeout",
    "infra_error",
    "configuration_error",
    "flaky_test",
    "unknown",
]


class FailureAnalysisRequest(BaseModel):
    """What we send the LLM - built by context_extractor.py."""
    project_name: str
    commit_sha: str
    failed_step: str | None
    exit_code: int
    log_excerpt: str
    source_context: list["SourceSnippet"] = Field(default_factory=list)


class SourceSnippet(BaseModel):
    path: str
    content: str
    reason: str  # why this file was selected (e.g. "mentioned in traceback")


class FailureAnalysisResult(BaseModel):
    """What we require back from the LLM. Extra fields are ignored; missing
    required fields cause validation to fail and the analysis to be marked
    invalid rather than guessed at."""
    failure_category: FailureCategoryLiteral
    root_cause: str = Field(..., min_length=1, max_length=2000)
    explanation: str = Field(..., min_length=1, max_length=4000)
    suggested_fix: str = Field(..., min_length=1, max_length=2000)
    confidence: float = Field(..., ge=0.0, le=1.0)

    @field_validator("confidence")
    @classmethod
    def clamp_confidence(cls, v: float) -> float:
        return max(0.0, min(1.0, v))


FailureAnalysisRequest.model_rebuild()
