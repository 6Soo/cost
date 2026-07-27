"""Shared workbook summary scope and reconciliation helpers."""
from __future__ import annotations

from collections.abc import Iterable, Mapping


SUMMARY_EXTRA_BUCKETS = (
    "기타비용",
    "여행_미배정",
    "취소환불",
    "전기예약_환불",
)


def scoped_summary_total(
    rows: Iterable[Mapping[str, object]],
    included_buckets: Iterable[str],
) -> tuple[int, int]:
    """Return amount and row count over exactly the same bucket scope."""
    scope = set(included_buckets)
    selected = [row for row in rows if str(row.get("bucket") or "") in scope]
    total = sum(int(round(float(row.get("krw_f") or 0))) for row in selected)
    return total, len(selected)
