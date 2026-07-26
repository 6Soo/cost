"""Re-apply canonical card facts to previously classified rows.

Classification files are projections and can outlive a later, more complete card
ingest.  A workbook reference is therefore only accepted when it is unique and
its date and signed amount still agree with the classified payment.
"""
from __future__ import annotations

import re
from collections import defaultdict
from typing import Iterable


def _amount(value: object) -> int:
    try:
        return int(round(float(str(value or "0").replace(",", ""))))
    except ValueError:
        return 0


def _date(value: object) -> str:
    text = str(value or "").strip().replace(".", "-").replace("/", "-")
    match = re.fullmatch(r"(\d{2}|\d{4})-(\d{1,2})-(\d{1,2})", text)
    if not match:
        return text[:10]
    year = match[1] if len(match[1]) == 4 else f"20{match[1]}"
    return f"{year}-{int(match[2]):02d}-{int(match[3]):02d}"


def _digits(value: object) -> str:
    return re.sub(r"\D", "", str(value or ""))


def _cancelled(row: dict[str, str], *, master: bool = False) -> bool:
    if master:
        return "취소" in str(row.get("취소여부") or "")
    return (
        str(row.get("cancel") or "").strip().lower() == "true"
        or "취소" in str(row.get("status") or "")
        or _amount(row.get("krw")) < 0
    )


def enrich_from_master(
    classified_rows: Iterable[dict[str, str]],
    master_rows: Iterable[dict[str, str]],
) -> dict[str, object]:
    """Update merchant facts in place and return an auditable summary.

    This does not classify a payment and does not use fuzzy matching.  It only
    follows the explicit ``워크북참조`` relation, then rechecks date and amount.
    """
    master_rows = list(master_rows)
    by_reference: dict[str, list[dict[str, str]]] = defaultdict(list)
    for master in master_rows:
        reference = str(master.get("워크북참조") or "").strip()
        if reference and str(master.get("기록여부") or "").strip().upper() == "Y":
            by_reference[reference].append(master)

    approval_counts: dict[tuple[str, str], int] = defaultdict(int)
    for master in master_rows:
        approval = _digits(master.get("승인번호"))
        if approval:
            approval_counts[(str(master.get("카드사") or ""), approval)] += 1

    updated: list[dict[str, str]] = []
    conflicts: list[dict[str, object]] = []
    unresolved: list[dict[str, object]] = []
    for row in classified_rows:
        uid = str(row.get("uid") or "").strip()
        candidates = by_reference.get(uid, [])
        if not candidates:
            continue
        if len(candidates) != 1:
            conflicts.append(
                {
                    "uid": uid,
                    "reason": "master_reference_not_unique",
                    "candidate_count": len(candidates),
                }
            )
            continue
        master = candidates[0]
        same_role = _cancelled(master, master=True) == _cancelled(row)
        exact_domestic = (
            _date(master.get("승인일")) == _date(row.get("use_date"))
            and abs(_amount(master.get("원화금액"))) == abs(_amount(row.get("krw")))
            and same_role
        )
        exact_kbo_posting = (
            str(row.get("src") or "") == "KBO"
            and not str(master.get("승인일") or "").strip()
            and _date(master.get("매입일")) == _date(row.get("post_date"))
            and str(master.get("카드4") or "") == str(row.get("card4") or "")
            and str(master.get("통화") or "") == str(row.get("currency") or "")
            and abs(_amount(master.get("현지금액"))) == abs(_amount(row.get("foreign")))
            and abs(_amount(master.get("원화금액"))) == abs(_amount(row.get("krw")))
            and same_role
        )
        approval = _digits(master.get("승인번호"))
        exact_hana_approval = (
            str(row.get("src") or "") == "HAN"
            and _date(master.get("승인일")) == _date(row.get("use_date"))
            and str(master.get("카드4") or "") == str(row.get("card4") or "")
            and approval
            and approval == _digits(row.get("appr"))
            and approval_counts[(str(master.get("카드사") or ""), approval)] == 1
            and same_role
        )
        if not (exact_domestic or exact_kbo_posting or exact_hana_approval):
            unresolved.append(
                {
                    "uid": uid,
                    "reason": "master_reference_facts_do_not_safely_reconcile",
                }
            )
            continue
        canonical_merchant = str(master.get("가맹점") or "").strip()
        if not canonical_merchant or canonical_merchant == str(row.get("merchant") or ""):
            continue
        previous = str(row.get("merchant") or "")
        row["merchant"] = canonical_merchant
        updated.append(
            {
                "uid": uid,
                "field": "merchant",
                "previous": previous,
                "current": canonical_merchant,
                "source_key": str(master.get("거래키") or ""),
            }
        )
    return {"updated": updated, "conflicts": conflicts, "unresolved": unresolved}
