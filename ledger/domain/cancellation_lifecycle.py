"""Helpers for compressed zero-net card cancellation lifecycles."""
from __future__ import annotations

from collections.abc import Iterable, Mapping


_CANCELLATION_MARKERS = ("취소", "환불", "cancel", "refund")


def zero_net_cancellation_approvals(
    rows: Iterable[Mapping[str, object]],
) -> set[tuple[str, str]]:
    """Return source/approval keys already represented as a zero-net row."""
    keys: set[tuple[str, str]] = set()
    for row in rows:
        try:
            amount = int(round(float(row.get("krw") or 0)))
        except (TypeError, ValueError):
            continue
        status = str(row.get("status") or "").lower()
        cancelled = str(row.get("cancel") or "").lower() in {"true", "1", "yes"}
        if amount != 0 or not (
            cancelled or any(marker in status for marker in _CANCELLATION_MARKERS)
        ):
            continue
        source = str(row.get("src") or "").strip().upper()
        approval = str(row.get("appr") or "").strip().lstrip("0")
        if source and approval:
            keys.add((source, approval))
    return keys
