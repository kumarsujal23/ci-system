import json

import pytest
from pydantic import ValidationError

from app import models
from app.ai.analyzer import analyze_attempt, _parse_and_validate
from app.ai.providers.base import LLMProvider, LLMProviderError
from app.ai.schemas import FailureAnalysisResult
from app.scheduler.job_manager import create_and_enqueue_job
from app.scheduler.lease_manager import claim_next_job, complete_attempt


def _make_failed_attempt(db, project, worker, permanent=True):
    create_and_enqueue_job(db, project, commit_sha="a", branch=None, trigger="manual")
    attempt = claim_next_job(db, worker)
    attempt.logs = "Traceback (most recent call last):\nAssertionError: expected 1 got 2\n"
    db.commit()
    result, _ = complete_attempt(
        db, attempt.id, attempt.lease_token,
        exit_code=1, is_permanent_failure=permanent, failed_step="test",
    )
    return result


class _ValidJSONProvider(LLMProvider):
    name = "test-valid"

    def analyze(self, request):
        return json.dumps({
            "failure_category": "test_failure",
            "root_cause": "assertion mismatch",
            "explanation": "the test expected a different value",
            "suggested_fix": "update the assertion or fix the implementation",
            "confidence": 0.8,
        })


class _MalformedJSONProvider(LLMProvider):
    name = "test-malformed"

    def analyze(self, request):
        return "this is not json at all {broken"


class _MissingFieldsProvider(LLMProvider):
    name = "test-missing-fields"

    def analyze(self, request):
        return json.dumps({"failure_category": "test_failure"})  # missing required fields


class _UnavailableProvider(LLMProvider):
    name = "test-unavailable"

    def analyze(self, request):
        raise LLMProviderError("simulated timeout")


def test_valid_response_is_parsed_and_stored(db_session, project, worker, monkeypatch):
    attempt = _make_failed_attempt(db_session, project, worker)
    monkeypatch.setattr("app.ai.analyzer.get_provider", lambda: _ValidJSONProvider())

    analysis = analyze_attempt(db_session, attempt)
    assert analysis.status == "completed"
    assert analysis.failure_category == "test_failure"
    assert analysis.confidence == 0.8


def test_malformed_json_marked_invalid_not_crashed(db_session, project, worker, monkeypatch):
    attempt = _make_failed_attempt(db_session, project, worker)
    monkeypatch.setattr("app.ai.analyzer.get_provider", lambda: _MalformedJSONProvider())

    analysis = analyze_attempt(db_session, attempt)
    assert analysis.status == "invalid"
    assert analysis.error_message is not None
    # Job's own verdict is completely unaffected by the AI failure.
    job = db_session.get(models.Job, attempt.job_id)
    assert job.status == models.JobStatus.FAILED


def test_missing_required_fields_marked_invalid(db_session, project, worker, monkeypatch):
    attempt = _make_failed_attempt(db_session, project, worker)
    monkeypatch.setattr("app.ai.analyzer.get_provider", lambda: _MissingFieldsProvider())

    analysis = analyze_attempt(db_session, attempt)
    assert analysis.status == "invalid"


def test_provider_unavailable_marked_unavailable(db_session, project, worker, monkeypatch):
    attempt = _make_failed_attempt(db_session, project, worker)
    monkeypatch.setattr("app.ai.analyzer.get_provider", lambda: _UnavailableProvider())

    analysis = analyze_attempt(db_session, attempt)
    assert analysis.status == "unavailable"
    assert "simulated timeout" in analysis.error_message


def test_confidence_out_of_range_rejected():
    with pytest.raises(ValidationError):
        FailureAnalysisResult(
            failure_category="test_failure",
            root_cause="x", explanation="y", suggested_fix="z",
            confidence=1.5,
        )


def test_unknown_category_rejected():
    with pytest.raises(ValidationError):
        FailureAnalysisResult(
            failure_category="not_a_real_category",
            root_cause="x", explanation="y", suggested_fix="z",
            confidence=0.5,
        )


def test_analysis_reused_not_recreated(db_session, project, worker, monkeypatch):
    attempt = _make_failed_attempt(db_session, project, worker)
    monkeypatch.setattr("app.ai.analyzer.get_provider", lambda: _ValidJSONProvider())

    first = analyze_attempt(db_session, attempt)
    second = analyze_attempt(db_session, attempt)
    assert first.id == second.id


def test_markdown_fenced_response_is_tolerated():
    fenced = "```json\n" + json.dumps({
        "failure_category": "compile_error",
        "root_cause": "syntax error",
        "explanation": "a bracket was left unclosed",
        "suggested_fix": "close the bracket",
        "confidence": 0.6,
    }) + "\n```"
    result = _parse_and_validate(fenced)
    assert result.failure_category == "compile_error"
