"""Read-only diagnostic queries for card refund merchant candidates and Kakao statement inventory.

Extracts database query boundaries from webapp.card_flow:
- refund_merchant_candidates_readonly: 14-day bounded same-card earlier purchases comparison
- kakao_merchant_inventory_readonly: owner-facing diagnostic inventory grouped by merchant and direction

This module is strictly read-only and independent of UI presentation:
- NO financial writes or link mutations
- NO new matching rules or financial decisions
- Pure SQLite connection execution with required merchant_key_fn callback injection
"""
from __future__ import annotations

from datetime import date, timedelta
import re
from typing import Any, Callable


def _get_connection(db_or_conn: Any):
    """Extract connection from store/board or return connection as-is."""
    return getattr(db_or_conn, "conn", db_or_conn)


def refund_merchant_candidates_readonly(
    conn: Any,
    tid: str,
    *,
    merchant_key_fn: Callable[[object], str],
    max_rows: int = 10,
) -> tuple[tuple | None, list[tuple], int]:
    """Read-only Kakao taxi alias evidence; same card, bounded time, no auto-link."""
    c = _get_connection(conn)

    refund = c.execute(
        "SELECT issuer,card_tail,merchant,COALESCE(NULLIF(approval_date,''),posting_date),amount_krw,approval_number,"
        "original_approval_number FROM transactions WHERE transaction_id=?", (tid,)
    ).fetchone()
    if not refund:
        return None, [], 0
    issuer, tail, merchant, approval_day, amount, approval, original = refund
    key = merchant_key_fn(merchant)
    if not (issuer and tail and approval_day and key):
        return refund, [], 0
    try:
        day = date.fromisoformat(str(approval_day)[:10])
    except ValueError:
        return refund, [], 0
    # Up to 14 days of earlier purchases. The window is a diagnostic
    # restriction, not evidence that a match outside this window is impossible.
    from_day = (day - timedelta(days=14)).isoformat()
    rows = c.execute(
        "SELECT transaction_id,batch_id,merchant,COALESCE(NULLIF(approval_date,''),posting_date),amount_krw,"
        "approval_number,duplicate_of,conflict_reason,parse_error "
        "FROM transactions WHERE issuer=? AND card_tail=? "
        "AND transaction_direction='purchase' AND amount_krw>0 "
        "AND ((substr(COALESCE(NULLIF(approval_date,''),posting_date),1,10)>=? "
        "AND substr(COALESCE(NULLIF(approval_date,''),posting_date),1,10)<=?) "
        "OR (?!='' AND TRIM(approval_number)=?)) "
        "ORDER BY approval_date DESC,transaction_id",
        (issuer, tail, from_day, day.isoformat(), str(original or '').strip(), str(original or '').strip()),
    )
    # Kakao T taxi charges sometimes appear under a UPay settlement label.
    # UPay is a *comparison candidate*, never a verified taxi identity or
    # authority to write a money link. Same card and time are required above.
    def upay_review_only(name):
        compact = re.sub(r"[^0-9a-z가-힣]", "", str(name or "").casefold())
        return (compact.startswith("유페이") and
                ("일반결제" in compact or "택시" in compact or "승인" in compact))

    # Issuer original approval reference outranks any merchant spelling.
    candidates = [
        row for row in rows
        if merchant_key_fn(row[2]) == key
        or (key == "카카오택시" and upay_review_only(row[2]))
        or (original and row[5] and str(original).strip() == str(row[5]).strip())
    ]
    def rank(row):
        same_approval = bool(original and row[5] and str(original) == str(row[5]))
        same_amount = row[4] == abs(amount or 0)
        same_day = str(row[3])[:10] == day.isoformat()
        healthy = not (row[6] or row[7] or row[8])
        # Exact amount is more actionable than mere day proximity, but both
        # are just *review* evidence without an issuer authorization reference.
        return (same_approval, healthy, same_amount, same_day, str(row[3]))
    candidates.sort(key=rank, reverse=True)
    return refund, candidates[:max_rows], len(candidates)


def kakao_merchant_inventory_readonly(
    conn: Any,
    *,
    merchant_key_fn: Callable[[object], str],
) -> list[dict[str, Any]]:
    """All currently stored Kakao-labeled rows, grouped without personal/card IDs.

    This is an owner-facing diagnostic inventory, NOT a matching or rule table.
    """
    c = _get_connection(conn)

    rows = c.execute(
        "SELECT merchant,transaction_direction,COUNT(*) FROM transactions "
        "WHERE merchant LIKE '%카카오%' OR lower(merchant) LIKE '%kakao%' "
        "OR merchant LIKE '%유페이%' "
        "GROUP BY merchant,transaction_direction ORDER BY merchant,transaction_direction"
    ).fetchall()
    return [{"merchant": name, "direction": direction, "count": int(count),
             "family": merchant_key_fn(name)}
            for name, direction, count in rows]
