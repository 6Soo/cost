# -*- coding: utf-8 -*-
"""Derive refund-to-original links from raw card fields. Nothing here writes.

A cancellation row names the approval it cancels in `original_approval_number`.
The link exists only when exactly one purchase has that approval number on the
same issuer and card. Overseas statements carry no approval numbers, so a
cancellation without one is paired by merchant, card, foreign currency and foreign
amount instead (config/refund-pairing.json). Identical rows pair in date order, one
purchase for one cancellation; a cancellation left over stays unpaired. The KRW
difference (rate or fee) stays in the net. Both source rows keep their own amounts;
the net is derived from them and never stored over either.
"""

from __future__ import annotations

import json
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import date
from decimal import Decimal, InvalidOperation
from functools import lru_cache
from pathlib import Path

__all__ = ["count_held_cancellations", "refund_group", "refund_links"]

_CLEAN = "duplicate_of IS NULL AND conflict_reason='' AND parse_error=''"
_CONFIG = Path(__file__).resolve().parents[1] / "config" / "refund-pairing.json"
_READ_ANALYSIS = ContextVar('refund_read_analysis', default=None)


@contextmanager
def read_only_scope():
    """Reuse global refund evidence within one display, never across requests."""
    token = _READ_ANALYSIS.set({})
    try:
        yield
    finally:
        _READ_ANALYSIS.reset(token)


def _read_analysis(conn):
    memo = _READ_ANALYSIS.get()
    if memo is None:
        return None
    # Also discard display evidence after a local write or another connection's commit.
    key = (conn, conn.total_changes, conn.execute('PRAGMA data_version').fetchone()[0])
    if key not in memo:
        numbered = _number_links(conn)
        taken = {link['original_id'] for link in numbered.values()}
        foreign = _foreign_links(conn, taken)
        held = {}
        if _settings().get('enabled'):
            purchases, cancels = _foreign_pool(conn, taken)
            for group, refunds in cancels.items():
                if purchases.get(group):
                    for tid, _amount, _when in refunds:
                        if tid not in foreign:
                            held[tid] = {'purchases': len(purchases[group]),
                                         'cancellations': len(refunds)}
        memo[key] = ({**numbered, **foreign}, held)
    return memo[key]


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
    # Use the same global uniqueness gate for group membership and row links.
    numbered = _number_links(conn)
    siblings = {tid for tid, link in numbered.items() if link["original_id"] == original_id}
    taken = {link["original_id"] for link in numbered.values()}
    siblings.update(refund_id for refund_id, link in _foreign_links(conn, taken).items()
                    if link["original_id"] == original_id)
    return [original_id] + sorted(siblings)


def refund_links(conn, transaction_ids) -> dict:
    """{refund_transaction_id: link} for cancellation rows among the ids."""
    ids = [str(i) for i in transaction_ids]
    if not ids:
        return {}
    analysis = _read_analysis(conn)
    if analysis is not None:
        wanted = set(ids)
        return {tid: dict(link) for tid, link in analysis[0].items() if tid in wanted}
    links = _number_links(conn, ids)
    taken = {link["original_id"] for link in _number_links(conn).values()}
    links.update(_foreign_links(conn, taken, set(ids)))
    return links


def _number_links(conn, transaction_ids=None) -> dict:
    """Link all clean cancellations to exactly one verified purchase by card and approval.

    Card feeds occasionally pad an approval reference with outer whitespace.
    Normalize only that padding, never fuzzy-match or change a digit. All clean
    original purchases participate in ambiguity detection before linking.
    """
    if transaction_ids is None:
        refunds = conn.execute(
            "SELECT transaction_id, issuer, card_tail, original_approval_number FROM transactions"
            f" WHERE transaction_direction='cancellation' AND TRIM(COALESCE(original_approval_number,''),char(9)||char(10)||char(11)||char(12)||char(13)||' ')!=''"
            f" AND amount_krw<0 AND {_CLEAN}"
        ).fetchall()
    else:
        ids = [str(i) for i in transaction_ids]
        if not ids:
            return {}
        marks = ",".join("?" * len(ids))
        refunds = conn.execute(
            "SELECT transaction_id, issuer, card_tail, original_approval_number FROM transactions"
            f" WHERE transaction_id IN ({marks}) AND transaction_direction='cancellation'"
            f" AND TRIM(COALESCE(original_approval_number,''),char(9)||char(10)||char(11)||char(12)||char(13)||' ')!='' AND amount_krw<0 AND {_CLEAN}", ids
        ).fetchall()
    if not refunds:
        return {}
    numbers = sorted({str(original_no).strip(" \t\n\v\f\r") for _, _, _, original_no in refunds})
    marks = ",".join("?" * len(numbers))
    candidates = conn.execute(
        "SELECT transaction_id, transaction_direction, issuer, card_tail, approval_number,"
        " original_approval_number, amount_krw FROM transactions"
        f" WHERE (TRIM(COALESCE(approval_number,''),char(9)||char(10)||char(11)||char(12)||char(13)||' ') IN ({marks})"
        f" OR TRIM(COALESCE(original_approval_number,''),char(9)||char(10)||char(11)||char(12)||char(13)||' ') IN ({marks})) AND {_CLEAN}",
        numbers + numbers
    ).fetchall()
    purchases, cancels = {}, {}
    for tid, direction, issuer_, tail_, approval, original, amount in candidates:
        if direction == 'purchase' and amount > 0 and str(approval or '').strip(" \t\n\v\f\r"):
            purchases.setdefault((issuer_, tail_, str(approval).strip(" \t\n\v\f\r")), []).append((tid, amount))
        elif direction == 'cancellation' and original and amount < 0:
            cancels.setdefault((issuer_, tail_, str(original).strip(" \t\n\v\f\r")), []).append((tid, amount))
    links = {}
    for refund_id, issuer, tail, original_no in refunds:
        key = (issuer, tail, str(original_no).strip(" \t\n\v\f\r"))
        originals = purchases.get(key, [])
        if len(originals) != 1:
            continue
        original_id, gross = originals[0]
        siblings = cancels.get(key, [])
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


def _foreign_pool(conn, taken) -> tuple:
    """Purchases and cancellations that can pair by foreign amount, keyed by card, merchant, currency and amount."""
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
            if tid not in taken:
                purchases.setdefault(key, []).append((tid, amount, when))
        elif not original:
            cancels.setdefault(key, []).append((tid, amount, when))
    return purchases, cancels


def _foreign_links(conn, taken, requested=None) -> dict:
    """{refund_transaction_id: link} for cancellations without an approval number, paired by foreign amount.

    Purchases and cancellations with the same card, merchant, currency and foreign amount pair in date order, one
    purchase for one cancellation: each cancellation takes the earliest open purchase that is not later than it and
    within the window. The rows are identical, so the order changes no total. A cancellation with no open purchase
    stays unpaired. `taken` holds purchases already paired by approval number; a pair never uses one of them."""
    settings = _settings()
    if not settings.get("enabled"):
        return {}
    window = int(settings["max_days_after_purchase"])
    purchases, cancels = _foreign_pool(conn, taken)

    links = {}
    for key, refunds in cancels.items():
        open_purchases = sorted(purchases.get(key, []), key=lambda p: (p[2], p[0]))
        for refund_id, refund_amount, refund_when in sorted(refunds, key=lambda r: (r[2], r[0])):
            match = next((p for p in open_purchases if 0 <= (refund_when - p[2]).days <= window), None)
            if match is None:
                continue
            open_purchases.remove(match)
            if requested is not None and refund_id not in requested:
                continue
            original_id, gross, _ = match
            net = gross + refund_amount
            links[refund_id] = {
                "original_id": original_id, "gross_krw": gross, "refund_krw": refund_amount,
                "refunds_total_krw": refund_amount, "net_krw": net,
                "status": "full" if net == 0 else "partial", "refund_count": 1,
                "basis": "merchant_card_foreign_amount",
            }
    return links


def count_held_cancellations(conn) -> dict:
    """{cancellation_id: counts} for identical cancellations left over while identical purchases exist.

    Among identical rows the purchase a cancellation undoes is unknown, so these are not recorded one by one. They wait
    as a count group until the statement's counts are checked."""
    analysis = _read_analysis(conn)
    if analysis is not None:
        return {tid: dict(counts) for tid, counts in analysis[1].items()}
    settings = _settings()
    if not settings.get("enabled"):
        return {}
    taken = {link["original_id"] for link in _number_links(conn).values()}
    purchases, cancels = _foreign_pool(conn, taken)
    paired = _foreign_links(conn, taken)
    held = {}
    for key, refunds in cancels.items():
        if not purchases.get(key):
            continue
        for refund_id, _amount, _when in refunds:
            if refund_id not in paired:
                held[refund_id] = {"purchases": len(purchases[key]), "cancellations": len(refunds)}
    return held
