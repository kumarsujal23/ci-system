"""
Provider interface. Every LLM backend (Anthropic, OpenAI, a local model, a
test double) implements this single method. The analyzer only ever depends
on this abstract interface, so swapping providers is a one-line config
change (`CI_AI_PROVIDER=anthropic|openai|mock`) - see ai/analyzer.py's
`get_provider()` factory.
"""
from __future__ import annotations
from abc import ABC, abstractmethod

from app.ai.schemas import FailureAnalysisRequest


class LLMProviderError(Exception):
    """Raised for any provider-level failure: timeout, network error, auth
    error, rate limit, or a response that isn't even parseable as JSON.
    The analyzer treats every subclass of this identically: analysis
    unavailable, CI result unaffected."""


class LLMProvider(ABC):
    name: str = "base"

    @abstractmethod
    def analyze(self, request: FailureAnalysisRequest) -> str:
        """Return the raw text response from the model (expected to be a
        JSON object matching FailureAnalysisResult). Must raise
        LLMProviderError on any failure rather than returning a malformed
        response silently."""
        raise NotImplementedError
