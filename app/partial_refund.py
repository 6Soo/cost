# -*- coding: utf-8 -*-
"""Derive refund-to-original links from raw card fields. Nothing here writes.

A cancellation row names the approval it cancels in `original_approval_number`.
The link exists only when exactly one purchase has that approval number on the
same issuer and card. Both source rows keep their own amounts; the net is derived
from them and never stored over either.
"""

from __future__ import annotations

__all__ = ["refund_links"]

_CLEAN = "duplicate_of IS NULL AND conflict_reason='' AND parse_error=''"


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
    links = {}
    for refund_id, issuer, tail, original_no in refunds:
        originals = conn.execute(
            "SELECT transaction_id, amount_krw FROM transactions WHERE transaction_direction='purchase'"
            f" AND issuer=? AND card_tail=? AND approval_number=? AND amount_krw>0 AND {_CLEAN}",
            (issuer, tail, original_no)).fetchall()
        if len(originals) != 1:
            continue
        original_id, gross = originals[0]
        siblings = conn.execute(
            "SELECT transaction_id, amount_krw FROM transactions WHERE transaction_direction='cancellation'"
            f" AND issuer=? AND card_tail=? AND original_approval_number=? AND amount_krw<0 AND {_CLEAN}",
            (issuer, tail, original_no)).fetchall()
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
