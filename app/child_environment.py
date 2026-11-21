"""Shared child-process environment guard for local spawn paths.

A per-call API key or cloud credential inherited into a child process would bill
that account instead of the approved subscription (PROC-013). Callers keep their
own wrapper names; the deny list and the filtering rule live here once.
"""
from __future__ import annotations

import os

DENIED_ENV_PREFIXES = ("ANTHROPIC_", "CLAUDE_CODE_USE_", "OPENAI_API_KEY", "AWS_",
                       "AZURE_", "GOOGLE_APPLICATION_CREDENTIALS")


def child_environment() -> dict[str, str]:
    """The parent environment minus anything that would switch billing accounts."""
    return {
        key: value for key, value in os.environ.items()
        if not key.upper().startswith(DENIED_ENV_PREFIXES)
    }
