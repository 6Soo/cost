"""Shared fail-closed policy for legacy Agoda browser entry points.

Agoda collection in this workspace is owned by the Paseo IAB browser tool.
The older Windows UIA/CDP command-line programs must not silently create an
Edge session or click a page control on their own.
"""

from __future__ import annotations

import json
from typing import Any


PASEO_IAB_ONLY_FAILURE = "PASEO_IAB_ONLY"
PASEO_IAB_ONLY_MESSAGE = (
    "Agoda collection is disabled in this legacy entry point; "
    "use the Paseo IAB browser tool so session ownership and safe controls "
    "remain explicit."
)


def legacy_browser_block(entrypoint: str) -> int:
    """Emit a stable machine-readable block result and return an exit code."""

    result: dict[str, Any] = {
        "status": "BLOCKED",
        "failure_code": PASEO_IAB_ONLY_FAILURE,
        "entrypoint": entrypoint,
        "message": PASEO_IAB_ONLY_MESSAGE,
    }
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 2
