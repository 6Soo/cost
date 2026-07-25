"""레거시 분류 projection이 카드 정본의 물리 거래 수를 초과하지 않게 하는 가드."""
from __future__ import annotations

import csv
import re
from collections import Counter, defaultdict
from decimal import Decimal, InvalidOperation
from pathlib import Path


def _decimal(value: object) -> str:
    try:
        return str(Decimal(str(value or "0").replace(",", "")).normalize())
    except InvalidOperation:
        return "0"


def _merchant(value: object) -> str:
    return re.sub(r"[^A-Z0-9]", "", str(value or "").upper())


def _fingerprint(row: dict[str, str], *, master: bool) -> tuple[str, ...]:
    if master:
        return (
            row.get("카드4", ""),
            row.get("매입일", ""),
            _merchant(row.get("가맹점")),
            _decimal(row.get("현지금액")),
            _decimal(row.get("원화금액")),
        )
    return (
        row.get("card4", ""),
        row.get("post_date", ""),
        _merchant(row.get("merchant")),
        _decimal(row.get("foreign")),
        _decimal(row.get("krw")),
    )


def remove_kbo_source_excess(
    rows: list[dict[str, str]], master_path: Path
) -> tuple[list[dict[str, str]], list[str]]:
    """국민 해외 projection 수가 카드 정본 수보다 많으면 근거가 약한 초과행을 제거한다.

    동일금액 다객실처럼 카드 정본에도 여러 행인 거래는 정본 건수만큼 모두 보존한다.
    정본에 없는 키는 이 함수가 판단하지 않는다.
    """
    with master_path.open(encoding="utf-8-sig", newline="") as stream:
        master_rows = list(csv.DictReader(stream))
    source_counts = Counter(
        _fingerprint(row, master=True)
        for row in master_rows
        if row.get("카드사") == "국민" and row.get("구분") == "해외"
    )
    projected: dict[tuple[str, ...], list[dict[str, str]]] = defaultdict(list)
    for row in rows:
        if row.get("src") == "KBO":
            projected[_fingerprint(row, master=False)].append(row)

    confidence_rank = {"상": 3, "중": 2, "하": 1}
    removed: set[str] = set()
    for key, candidates in projected.items():
        allowed = source_counts.get(key)
        if not allowed or len(candidates) <= allowed:
            continue
        candidates.sort(
            key=lambda row: (
                confidence_rank.get(row.get("confidence", ""), 0),
                confidence_rank.get(row.get("tax_conf", ""), 0),
                bool(row.get("note")),
                row.get("uid", ""),
            ),
            reverse=True,
        )
        removed.update(row.get("uid", "") for row in candidates[allowed:])
    return [row for row in rows if row.get("uid") not in removed], sorted(removed)
