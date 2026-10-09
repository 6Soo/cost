# -*- coding: utf-8 -*-
"""Derive refund-to-original links from raw card fields. Nothing here writes.

A cancellation row names the approval it cancels in `original_approval_number`.
The link exists only when exactly one purchase has that approval number on the
same issuer and card. Both source rows keep their own amounts; the net is derived
from them and never stored over either.
"""

from __future__ import annotations

__all__ = ["refund_group", "refund_links"]

_CLEAN = "duplicate_of IS NULL AND conflict_reason='' AND parse_error=''"


def refund_group(conn, original_id: str) -> list:
    """The original followed by every clean cancellation that names its approval."""
    found = conn.execute("SELECT issuer, card_tail, approval_number FROM transactions"
                         " WHERE transaction_id=?", (original_id,)).fetchone()
    if found is None:
        return [original_id]
    issuer, tail, original_no = found
    siblings = conn.execute("SELECT transaction_id FROM transactions WHERE transaction_direction='cancellation'"
                            f" AND issuer=? AND card_tail=? AND original_approval_number=? AND amount_krw<0 AND {_CLEAN}"
                            " ORDER BY transaction_id", (issuer, tail, original_no)).fetchall()
    return [original_id] + [tid for (tid,) in siblings]


def refund_links(conn, transaction_ids) -> dict:
    """{refund_transaction_id: link} for cancellation rows among the ids."""
    ids = [str(i) for i in transaction_ids]
    if not ids:
        return {}
    marks = ",".join("?" * len(ids))
    refunds = conn.execute(
        "SELECT transaction_id, issuer, card_tail, original_approval_number FROM transactions"
        f" WHERE transaction_id IN ({marks}) AND transaction_direction='cancellation'"
        f" AND original_approval_number!='' AND amount_krw<0 AND {_CLEAN}", ids).fetchall()
    if not refunds:
        return {}
    numbers = sorted({original_no for _, _, _, original_no in refunds})
    marks = ",".join("?" * len(numbers))
    # One scan for all candidates; a scan per refund made the card pages crawl.
    candidates = conn.execute(
        "SELECT transaction_id, transaction_direction, issuer, card_tail, approval_number,"
        " original_approval_number, amount_krw FROM transactions"
        f" WHERE (approval_number IN ({marks}) OR original_approval_number IN ({marks})) AND {_CLEAN}",
        numbers + numbers).fetchall()
    purchases, cancels = {}, {}
    for tid, direction, issuer_, tail_, approval, original, amount in candidates:
        if direction == 'purchase' and amount > 0:
            purchases.setdefault((issuer_, tail_, approval), []).append((tid, amount))
        elif direction == 'cancellation' and original and amount < 0:
            cancels.setdefault((issuer_, tail_, original), []).append((tid, amount))
    links = {}
    for refund_id, issuer, tail, original_no in refunds:
        originals = purchases.get((issuer, tail, original_no), [])
        if len(originals) != 1:
            continue
        original_id, gross = originals[0]
        siblings = cancels.get((issuer, tail, original_no), [])
        refund_total = sum(amount for _, amount in siblings)
        own = next(amount for tid, amount in siblings if tid == refund_id)
        net = gross + refund_total
        links[refund_id] = {
            "original_id": original_id, "gross_krw": gross, "refund_krw": own,
            "refunds_total_krw": refund_total, "net_krw": net,
            "status": "excess" if net < 0 else ("full" if net == 0 else "partial"),
            "refund_count": len(siblings),
        }
    return links
