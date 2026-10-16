# -*- coding: utf-8 -*-
"""Derive refund-to-original links from raw card fields. Nothing here writes.

A cancellation row names the approval it cancels in `original_approval_number`.
The link exists only when exactly one purchase has that approval number on the
same issuer and card. Overseas statements carry no approval numbers, so a
cancellation without one is paired by merchant, card, foreign currency and foreign
amount instead (config/refund-pairing.json). That pair needs exactly one purchase
for the cancellation and exactly one cancellation for the purchase. The KRW
difference (rate or fee) stays in the net. Both source rows keep their own amounts;
the net is derived from them and never stored over either.
"""

from __future__ import annotations

import json
from datetime import date
from decimal import Decimal, InvalidOperation
from functools import lru_cache
from pathlib import Path

__all__ = ["refund_group", "refund_links"]

_CLEAN = "duplicate_of IS NULL AND conflict_reason='' AND parse_error=''"
_CONFIG = Path(__file__).resolve().parents[1] / "config" / "refund-pairing.json"


@lru_cache(maxsize=1)
def _settings() -> dict:
    value = json.loads(_CONFIG.read_text(encoding="utf-8"))
    if value.get("schema_version") != "refund-pairing-v1":
        raise ValueError("REFUND_PAIRING_SCHEMA_INVALID")
    return value["foreign_amount_pairing"]


def refund_group(conn, original_id: str) -> list:
    """The original followed by every clean cancellation paired with it by approval number or foreign amount."""
    found = conn.execute("SELECT issuer, card_tail, approval_number FROM transactions"
                         " WHERE transaction_id=?", (original_id,)).fetchone()
    if found is None:
        return [original_id]
    issuer, tail, original_no = found
    siblings = set()
    # An empty approval number names nothing; matching on it would pull in every blank cancellation.
    if original_no:
        siblings.update(tid for (tid,) in conn.execute(
            "SELECT transaction_id FROM transactions WHERE transaction_direction='cancellation'"
            f" AND issuer=? AND card_tail=? AND original_approval_number=? AND amount_krw<0 AND {_CLEAN}",
            (issuer, tail, original_no)).fetchall())
    taken = {link["original_id"] for link in _number_links(conn).values()}
    siblings.update(refund_id for refund_id, link in _foreign_links(conn, taken).items()
                    if link["original_id"] == original_id)
    return [original_id] + sorted(siblings)


def refund_links(conn, transaction_ids) -> dict:
    """{refund_transaction_id: link} for cancellation rows among the ids."""
    ids = [str(i) for i in transaction_ids]
    if not ids:
        return {}
    links = _number_links(conn, ids)
    taken = {link["original_id"] for link in _number_links(conn).values()}
    links.update(_foreign_links(conn, taken, set(ids)))
    return links


def _number_links(conn, transaction_ids=None) -> dict:
    """{refund_transaction_id: link} for cancellations that name an approval number."""
    if transaction_ids is None:
        refunds = conn.execute(
            "SELECT transaction_id, issuer, card_tail, original_approval_number FROM transactions"
            f" WHERE transaction_direction='cancellation' AND original_approval_number!='' AND amount_krw<0 AND {_CLEAN}"
        ).fetchall()
    else:
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


def _foreign_amount(value):
    try:
        amount = Decimal(str(value or "").replace(",", "").strip())
    except (InvalidOperation, ValueError):
        return None
    return abs(amount) if amount.is_finite() and amount != 0 else None


def _day(value):
    try:
        return date.fromisoformat(str(value or "")[:10])
    except ValueError:
        return None


def _foreign_links(conn, taken, requested=None) -> dict:
    """{refund_transaction_id: link} for cancellations without an approval number, paired by foreign amount.

    The pair needs one purchase that fits the cancellation (same card, merchant, currency and foreign amount,
    not later than the cancellation and within the window) and one cancellation that fits that purchase.
    `taken` holds purchases already paired by approval number; a pair never uses one of them."""
    settings = _settings()
    if not settings.get("enabled"):
        return {}
    window = int(settings["max_days_after_purchase"])
    rows = conn.execute(
        "SELECT transaction_id, transaction_direction, issuer, card_tail, merchant_normalized, amount_krw,"
        " foreign_amount, foreign_currency, COALESCE(NULLIF(approval_date,''),posting_date), original_approval_number"
        f" FROM transactions WHERE {_CLEAN} AND COALESCE(foreign_currency,'')!='' AND COALESCE(foreign_amount,'')!=''"
        " AND ((transaction_direction='purchase' AND amount_krw>0)"
        "      OR (transaction_direction='cancellation' AND amount_krw<0 AND COALESCE(original_approval_number,'')=''))"
    ).fetchall()
    purchases, cancels = {}, {}
    for tid, direction, issuer, tail, merchant, amount, foreign, currency, day, original in rows:
        foreign_amount = _foreign_amount(foreign)
        currency = str(currency or "").strip().upper()
        when = _day(day)
        if foreign_amount is None or not currency or not merchant or when is None:
            continue
        key = (issuer, tail, merchant, currency, foreign_amount)
        if direction == "purchase":
            purchases.setdefault(key, []).append((tid, amount, when))
        elif not original:
            cancels.setdefault(key, []).append((tid, amount, when))

    def fits(refund_when, purchase_when):
        return 0 <= (refund_when - purchase_when).days <= window

    links = {}
    for key, refunds in cancels.items():
        for refund_id, refund_amount, refund_when in refunds:
            if requested is not None and refund_id not in requested:
                continue
            options = [p for p in purchases.get(key, []) if fits(refund_when, p[2])]
            if len(options) != 1:
                continue
            original_id, gross, purchase_when = options[0]
            if original_id in taken:
                continue
            if any(other[0] != refund_id and fits(other[2], purchase_when) for other in refunds):
                continue
            net = gross + refund_amount
            links[refund_id] = {
                "original_id": original_id, "gross_krw": gross, "refund_krw": refund_amount,
                "refunds_total_krw": refund_amount, "net_krw": net,
                "status": "full" if net == 0 else "partial", "refund_count": 1,
                "basis": "merchant_card_foreign_amount",
            }
    return links
