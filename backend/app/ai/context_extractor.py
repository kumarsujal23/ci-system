"""
Selects a small, relevant slice of source context to send to the LLM instead
of the entire repository.

Strategy (deliberately simple and explainable, not "send everything and let
the model figure it out"):
  1. Parse the log for file paths that appear in tracebacks / compiler
     errors / test failure output (language-agnostic regexes for common
     patterns: Python tracebacks, pytest assertion locations, generic
     "path:line" compiler diagnostics).
  2. De-duplicate and cap the number of files and bytes per file.
  3. Read those files from the checked-out repo working directory on the
     worker's filesystem (the same clone used to run the pipeline).

If nothing can be matched, source_context is simply empty and the LLM is
asked to reason from the log alone - the analyzer degrades gracefully.
"""
from __future__ import annotations
import os
import re
from pathlib import Path

from app.config import get_settings
from app.ai.schemas import SourceSnippet

settings = get_settings()

# Matches things like:
#   File "app/foo.py", line 42, in bar         (Python traceback)
#   app/foo.py:42: AssertionError               (pytest short form)
#   src/foo.c:10:5: error: ...                  (gcc/clang diagnostics)
_PATH_PATTERNS = [
    re.compile(r'File "([^"]+\.py)", line (\d+)'),
    re.compile(r'([\w./\-]+\.(?:py|js|ts|tsx|jsx|go|rs|java|c|cpp|h))[:\s]+(\d+)'),
]


def extract_referenced_paths(log_text: str, max_paths: int) -> list[str]:
    found: list[str] = []
    for pattern in _PATH_PATTERNS:
        for match in pattern.finditer(log_text):
            path = match.group(1).lstrip("./")
            if path not in found:
                found.append(path)
            if len(found) >= max_paths:
                return found
    return found


def build_source_context(repo_root: str | Path, log_text: str) -> list[SourceSnippet]:
    repo_root = Path(repo_root)
    paths = extract_referenced_paths(log_text, settings.ai_max_source_files)
    snippets: list[SourceSnippet] = []
    for rel_path in paths:
        full_path = (repo_root / rel_path).resolve()
        try:
            # Guard against path traversal outside the repo checkout.
            full_path.relative_to(repo_root.resolve())
        except ValueError:
            continue
        if not full_path.is_file():
            continue
        try:
            content = full_path.read_text(errors="replace")
        except OSError:
            continue
        snippets.append(SourceSnippet(
            path=rel_path,
            content=content[: settings.ai_max_file_chars],
            reason="referenced in failure log",
        ))
    return snippets


def truncate_log(log_text: str) -> str:
    max_chars = settings.ai_max_log_chars
    if len(log_text) <= max_chars:
        return log_text
    # Keep the tail - the actual failure is almost always near the end.
    return "...[truncated]...\n" + log_text[-max_chars:]
