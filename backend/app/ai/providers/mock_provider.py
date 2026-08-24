"""
Deterministic mock provider. Used as the default so the whole system runs
out of the box (docker compose up) with zero API keys configured, and used
in tests to exercise the analyzer/validation pipeline without network calls
or nondeterminism. It applies simple keyword heuristics over the log text -
it is not meant to be "smart", only to demonstrate the pipeline end-to-end.
"""
from __future__ import annotations
import json

from app.ai.providers.base import LLMProvider
from app.ai.schemas import FailureAnalysisRequest

_RULES = [
    (("ModuleNotFoundError", "No module named", "Cannot find module", "ImportError"),
     "dependency_error",
     "A required dependency is missing or not installed in the build image.",
     "Add the missing package to the project's dependency manifest "
     "(requirements.txt / package.json) and ensure the install step runs "
     "before the failing step."),
    (("AssertionError", "assert ", "FAILED", "test_"),
     "test_failure",
     "One or more test assertions did not hold for the code under test.",
     "Inspect the failing assertion and the function it exercises; the "
     "test expectation and the implementation have diverged."),
    (("SyntaxError", "error: expected", "compilation failed", "cannot find symbol"),
     "compile_error",
     "The code does not compile/parse as written.",
     "Review the referenced file and line for a syntax or type error "
     "introduced in this commit."),
    (("timed out", "timeout", "DeadlineExceeded"),
     "timeout",
     "A step exceeded its allotted execution time.",
     "Profile the slow step; consider raising the pipeline timeout or "
     "optimizing/parallelizing the operation."),
]


class MockProvider(LLMProvider):
    name = "mock"

    def analyze(self, request: FailureAnalysisRequest) -> str:
        log = request.log_excerpt
        for keywords, category, cause, fix in _RULES:
            if any(k in log for k in keywords):
                return json.dumps({
                    "failure_category": category,
                    "root_cause": cause,
                    "explanation": (
                        f"The '{request.failed_step or 'build'}' step exited with code "
                        f"{request.exit_code}. Log content matched patterns typically "
                        f"associated with a {category.replace('_', ' ')}."
                    ),
                    "suggested_fix": fix,
                    "confidence": 0.55,
                })
        return json.dumps({
            "failure_category": "unknown",
            "root_cause": "Unable to confidently determine the root cause from available logs.",
            "explanation": (
                f"The '{request.failed_step or 'build'}' step exited with code "
                f"{request.exit_code} but the log did not match any recognizable failure "
                f"pattern."
            ),
            "suggested_fix": "Review the full job log manually; consider adding more "
                             "verbose logging to the failing step.",
            "confidence": 0.2,
        })
