"""
Anthropic-backed provider. Swappable with any other provider that implements
LLMProvider - this file has zero references anywhere else in the analyzer;
app/ai/analyzer.py only imports it behind the get_provider() factory.
"""
from __future__ import annotations
import json

import anthropic

from app.ai.providers.base import LLMProvider, LLMProviderError
from app.ai.schemas import FailureAnalysisRequest
from app.config import get_settings

settings = get_settings()

SYSTEM_PROMPT = """You are a CI failure analysis assistant. You will be given
a failed build/test step, its exit code, a log excerpt, and possibly a few
relevant source file snippets referenced by the failure.

Respond with ONLY a single JSON object (no markdown fences, no prose before
or after) with exactly these fields:
{
  "failure_category": one of "compile_error", "test_failure",
      "dependency_error", "timeout", "infra_error", "configuration_error",
      "flaky_test", "unknown",
  "root_cause": short string describing the most likely root cause,
  "explanation": a few sentences explaining your reasoning,
  "suggested_fix": a concrete, actionable suggestion,
  "confidence": a float between 0.0 and 1.0
}

You are a diagnostic aid, not an autonomous agent - you must not claim
certainty you don't have, and you must not attempt to modify any code.
If the log is ambiguous, say so honestly and lower your confidence."""


class AnthropicProvider(LLMProvider):
    name = "anthropic"

    def __init__(self):
        if not settings.ai_api_key:
            raise LLMProviderError("CI_AI_API_KEY is not configured")
        self.client = anthropic.Anthropic(api_key=settings.ai_api_key)

    def analyze(self, request: FailureAnalysisRequest) -> str:
        user_content = self._build_prompt(request)
        try:
            response = self.client.messages.create(
                model=settings.ai_model,
                max_tokens=1200,
                system=SYSTEM_PROMPT,
                messages=[{"role": "user", "content": user_content}],
                timeout=settings.ai_timeout_seconds,
            )
        except anthropic.APIError as e:
            raise LLMProviderError(f"Anthropic API error: {e}") from e
        except Exception as e:  # network errors, timeouts, etc.
            raise LLMProviderError(f"provider call failed: {e}") from e

        text_blocks = [b.text for b in response.content if getattr(b, "type", None) == "text"]
        if not text_blocks:
            raise LLMProviderError("provider returned no text content")
        return "\n".join(text_blocks)

    def _build_prompt(self, request: FailureAnalysisRequest) -> str:
        parts = [
            f"Project: {request.project_name}",
            f"Commit: {request.commit_sha}",
            f"Failed step: {request.failed_step or 'unknown'}",
            f"Exit code: {request.exit_code}",
            "\n--- Log excerpt ---\n" + request.log_excerpt,
        ]
        if request.source_context:
            parts.append("\n--- Relevant source context ---")
            for snippet in request.source_context:
                parts.append(f"\n# {snippet.path} ({snippet.reason})\n{snippet.content}")
        return "\n".join(parts)


def _validate_json_shape(raw: str) -> dict:
    """Helper used by tests to assert the provider at least returns JSON,
    independent of the Pydantic validation layer in analyzer.py."""
    return json.loads(raw)
