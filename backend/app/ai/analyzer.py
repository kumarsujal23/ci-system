"""
AI Failure Analyzer orchestrator.

Invariants this module enforces:
  1. AI analysis is triggered ONLY after a job attempt is already recorded
     as FAILED or INFRA_ERROR - it never influences the CI verdict itself.
  2. Every LLM response is validated through FailureAnalysisResult
     (Pydantic). A response that fails validation, times out, or the
     provider being unreachable all result in an AIAnalysis row with
     status="invalid" or "unavailable" - never a crash, never a silent
     fabrication, and never a change to the job's pass/fail status.
  3. The provider is fully swappable via get_provider() / CI_AI_PROVIDER.
  4. This module never modifies source code or executes suggested fixes -
     it only records a suggestion for a human to read on the dashboard.
"""
from __future__ import annotations
import json
import logging

from pydantic import ValidationError
from sqlalchemy.orm import Session

from app import models
from app.config import get_settings
from app.ai.schemas import FailureAnalysisRequest, FailureAnalysisResult
from app.ai.context_extractor import truncate_log, build_source_context
from app.ai.providers.base import LLMProvider, LLMProviderError

logger = logging.getLogger("ci.ai")
settings = get_settings()


def get_provider() -> LLMProvider:
    """Factory - the single place provider selection happens. Add a new
    provider by implementing LLMProvider and adding a branch here (or,
    for a fully config-driven setup, a registry dict keyed by name)."""
    if settings.ai_provider == "anthropic":
        from app.ai.providers.anthropic_provider import AnthropicProvider
        return AnthropicProvider()
    if settings.ai_provider == "mock":
        from app.ai.providers.mock_provider import MockProvider
        return MockProvider()
    raise LLMProviderError(f"unknown AI provider configured: {settings.ai_provider!r}")


def analyze_attempt(db: Session, attempt: models.JobAttempt, repo_checkout_path: str | None = None) -> models.AIAnalysis:
    """Entry point called by the API after a failed attempt is recorded.
    Always returns an AIAnalysis row (creating one if needed) - it degrades
    to status="unavailable"/"invalid" rather than raising, so a caller that
    forgets to catch exceptions still can't break job processing."""
    existing = attempt.ai_analysis
    if existing is not None:
        return existing

    analysis = models.AIAnalysis(attempt_id=attempt.id, status="pending")
    db.add(analysis)
    db.flush()

    job = db.get(models.Job, attempt.job_id)
    project = db.get(models.Project, job.project_id)

    log_excerpt = truncate_log(attempt.logs or "")
    source_context = []
    if repo_checkout_path:
        source_context = build_source_context(repo_checkout_path, log_excerpt)

    request = FailureAnalysisRequest(
        project_name=project.name,
        commit_sha=job.commit_sha,
        failed_step=attempt.failed_step,
        exit_code=attempt.exit_code or -1,
        log_excerpt=log_excerpt,
        source_context=source_context,
    )

    try:
        provider = get_provider()
    except LLMProviderError as e:
        _mark_unavailable(analysis, str(e))
        db.commit()
        return analysis

    analysis.provider = provider.name
    analysis.model = settings.ai_model

    try:
        raw_response = provider.analyze(request)
    except LLMProviderError as e:
        logger.warning("AI provider call failed for attempt %s: %s", attempt.id, e)
        _mark_unavailable(analysis, str(e))
        db.commit()
        return analysis

    try:
        parsed = _parse_and_validate(raw_response)
    except (json.JSONDecodeError, ValidationError) as e:
        logger.warning("AI response failed validation for attempt %s: %s", attempt.id, e)
        analysis.status = "invalid"
        analysis.raw_response = raw_response[:4000]
        analysis.error_message = f"response failed schema validation: {e}"
        db.commit()
        return analysis

    from datetime import datetime, timezone
    analysis.status = "completed"
    analysis.failure_category = parsed.failure_category
    analysis.root_cause = parsed.root_cause
    analysis.explanation = parsed.explanation
    analysis.suggested_fix = parsed.suggested_fix
    analysis.confidence = parsed.confidence
    analysis.raw_response = raw_response[:4000]
    analysis.completed_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(analysis)
    return analysis


def _parse_and_validate(raw_response: str) -> FailureAnalysisResult:
    cleaned = raw_response.strip()
    # Be tolerant of models that wrap JSON in markdown fences despite
    # instructions not to - strip fences before parsing, but never accept
    # anything that isn't valid JSON matching our schema after that.
    if cleaned.startswith("```"):
        cleaned = cleaned.strip("`")
        if cleaned.startswith("json"):
            cleaned = cleaned[4:]
    data = json.loads(cleaned)
    return FailureAnalysisResult(**data)


def _mark_unavailable(analysis: models.AIAnalysis, message: str) -> None:
    analysis.status = "unavailable"
    analysis.error_message = message
