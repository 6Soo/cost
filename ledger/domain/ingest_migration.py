"""One-to-one migration from approval-less legacy card rows."""
from __future__ import annotations

import re
from collections import defaultdict


def _amount(value: object) -> int:
    try:
        return int(round(float(str(value or "0").replace(",", ""))))
    except ValueError:
        return 0


def _merchant(value: object) -> str:
    return re.sub(r"[^0-9A-Z가-힣]", "", str(value or "").upper())


def _key(row: dict[str, str]) -> tuple[object, ...]:
    amount = _amount(row.get("원화금액")) or _amount(row.get("현지금액"))
    return (
        row.get("출처"),
        str(row.get("카드4") or "")[-4:],
        str(row.get("승인일") or row.get("매입일") or "")[:10],
        abs(amount),
        _merchant(row.get("가맹점")),
        "refund" if "취소" in str(row.get("취소여부") or "") or amount < 0 else "purchase",
    )


def balanced_legacy_enrichment_pairs(
    existing_rows: list[dict[str, str]],
    incoming_rows: list[dict[str, str]],
) -> dict[str, str]:
    """Map incoming key→legacy key only when structural group counts agree."""
    old_groups: dict[tuple[object, ...], list[dict[str, str]]] = defaultdict(list)
    new_groups: dict[tuple[object, ...], list[dict[str, str]]] = defaultdict(list)
    for row in existing_rows:
        if not str(row.get("승인번호") or "").strip():
            old_groups[_key(row)].append(row)
    for row in incoming_rows:
        if str(row.get("승인번호") or "").strip():
            new_groups[_key(row)].append(row)
    result: dict[str, str] = {}
    for key, incoming in new_groups.items():
        existing = old_groups.get(key, [])
        if not existing or len(existing) != len(incoming):
            continue
        for new, old in zip(
            sorted(incoming, key=lambda row: str(row.get("거래키") or "")),
            sorted(existing, key=lambda row: str(row.get("거래키") or "")),
        ):
            result[str(new.get("거래키") or "")] = str(old.get("거래키") or "")
    return result
