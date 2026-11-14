# -*- coding: utf-8 -*-
"""Derive refund-to-original links from raw card fields. Nothing here writes.

A cancellation row names the approval it cancels in `original_approval_number`.
That reference identifies a link when exactly one purchase has that approval
number on the same issuer and card; it is not a prerequisite. Overseas statements carry no approval numbers, so a
cancellation without one is paired by merchant, card, foreign currency and foreign
amount instead (config/refund-pairing.json). Identical rows pair in date order, one
purchase for one cancellation; a cancellation left over stays unpaired. The KRW
difference (rate or fee) stays in the net. Both source rows keep their own amounts;
the net is derived from them and never stored over either.
"""

from __future__ import annotations

import json
import threading
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import date
from decimal import Decimal, InvalidOperation
from functools import lru_cache
from pathlib import Path

__all__ = ["count_held_cancellations", "refund_group", "refund_links", "refund_review_originals"]

_CLEAN = "duplicate_of IS NULL AND conflict_reason='' AND parse_error=''"
_CONFIG = Path(__file__).resolve().parents[1] / "config" / "refund-pairing.json"
_READ_ANALYSIS = ContextVar('refund_read_analysis', default=None)
# The last analysis of committed data; a commit anywhere or a local write moves its key.
_COMMITTED = {}
_COMMITTED_LOCK = threading.Lock()


@contextmanager
def read_only_scope():
    """Reuse global refund evidence within one display, including uncommitted reads."""
    token = _READ_ANALYSIS.set({})
    try:
        yield
    finally:
        _READ_ANALYSIS.reset(token)


def _read_analysis(conn):
    memo = _READ_ANALYSIS.get()
    # Also discard display evidence after a local write or another connection's commit.
    key = (conn, conn.total_changes, conn.execute('PRAGMA data_version').fetchone()[0])
    if memo is not None:
        if key not in memo:
            memo[key] = _analyse(conn)
        return memo[key]
    if conn.in_transaction:
        # Uncommitted evidence can be rolled back without moving the key, so it is never kept.
        return _analyse(conn)
    with _COMMITTED_LOCK:
        if key in _COMMITTED:
            return _COMMITTED[key]
    result = _analyse(conn)
    with _COMMITTED_LOCK:
        _COMMITTED.clear()
        _COMMITTED[key] = result
    return result


def _analyse(conn):
    """(links, held, extra): Python derivation, or the Rust core's when WEBLEDGER_LINKS_PRODUCER=rust (extra is None for Python)."""
    from . import core_links
    if core_links.selected() == 'rust':
        # A costcore error propagates on purpose: falling back would let two producers disagree unnoticed.
        return core_links.analyse(conn)
    return (*_analyse_python(conn), None)


def _analyse_python(conn):
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
    taken.update(link['original_id'] for link in foreign.values())
    inferred = _amount_inferred_links(conn, taken, occupied_refunds=set(numbered) | set(foreign))
    return {**numbered, **foreign, **inferred}, held


@lru_cache(maxsize=1)
def _settings() -> dict:
    value = json.loads(_CONFIG.read_text(encoding="utf-8"))
    if value.get("schema_version") != "refund-pairing-v1":
        raise ValueError("REFUND_PAIRING_SCHEMA_INVALID")
    return value["foreign_amount_pairing"]


def refund_group(conn, original_id: str) -> list:
    """The original and all linked cancellations, including display-only inference."""
    siblings = {tid for tid, link in _read_analysis(conn)[0].items()
                if link['original_id'] == original_id}
    return [original_id] + sorted(siblings)


def refund_links(conn, transaction_ids) -> dict:
    """{refund_transaction_id: link} for cancellation rows among the ids."""
    ids = [str(i) for i in transaction_ids]
    if not ids:
        return {}
    wanted = set(ids)
    return {tid: dict(link) for tid, link in _read_analysis(conn)[0].items() if tid in wanted}


def is_numbered_partial(link) -> bool:
    """A partial refund tied to exactly one original by approval number (RFND-004), never inferred."""
    return (not link.get('inferred') and 'basis' not in link
            and link.get('status') == 'partial' and link.get('net_krw', 0) > 0)


def partial_group_exclusion(conn, original_id: str) -> str:
    """Why a numbered partial group must not be extended across files ('' when allowed).

    PROC-072 completed periods come first; an errored, duplicate or conflicted
    cancel of the same original (dropped from the net) holds the whole group.
    """
    extra = _read_analysis(conn)[2]
    if extra is not None:
        # Only linked originals are judged by the Rust core; every caller passes one from a link.
        if original_id not in extra['group_exclusions']:
            raise RuntimeError('CORE_LINKS_ORIGINAL_NOT_LINKED')
        return extra['group_exclusions'][original_id]
    from .closed_period import completed_period
    for tid in refund_group(conn, original_id):
        row = conn.execute(
            "SELECT approval_date, posting_date FROM transactions WHERE transaction_id=?", (tid,)).fetchone()
        if row and completed_period({'approval_date': row[0], 'posting_date': row[1]}):
            return 'completed_period'
    unclean = conn.execute(
        "SELECT 1 FROM transactions o JOIN transactions c ON c.issuer=o.issuer AND c.card_tail=o.card_tail"
        " AND c.transaction_direction='cancellation'"
        " AND TRIM(COALESCE(c.original_approval_number,''),char(9)||char(10)||char(11)||char(12)||char(13)||' ')"
        "   =TRIM(COALESCE(o.approval_number,''),char(9)||char(10)||char(11)||char(12)||char(13)||' ')"
        " WHERE o.transaction_id=? AND (c.duplicate_of IS NOT NULL OR COALESCE(c.conflict_reason,'')!=''"
        " OR COALESCE(c.parse_error,'')!='') LIMIT 1", (original_id,)).fetchone()
    return 'unclean_member' if unclean else ''


def refund_original_links(conn, transaction_ids) -> dict:
    """{original_transaction_id: one confirmed link} for requested originals."""
    wanted = {str(i) for i in transaction_ids}
    if not wanted:
        return {}
    links = _read_analysis(conn)[0]
    return {link['original_id']: dict(link) for link in links.values()
            if link['original_id'] in wanted}


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
        " original_approval_number, amount_krw, duplicate_of, conflict_reason, parse_error FROM transactions"
        f" WHERE (TRIM(COALESCE(approval_number,''),char(9)||char(10)||char(11)||char(12)||char(13)||' ') IN ({marks})"
        f" OR TRIM(COALESCE(original_approval_number,''),char(9)||char(10)||char(11)||char(12)||char(13)||' ') IN ({marks}))",
        numbers + numbers
    ).fetchall()
    purchases, cancels = {}, {}
    for tid, direction, issuer_, tail_, approval, original, amount, duplicate, conflict, error in candidates:
        clean = duplicate is None and not conflict and not error
        if direction == 'purchase' and amount > 0 and str(approval or '').strip(" \t\n\v\f\r"):
            purchases.setdefault((issuer_, tail_, str(approval).strip(" \t\n\v\f\r")), []).append((tid, amount, clean))
        elif clean and direction == 'cancellation' and original and amount < 0:
            cancels.setdefault((issuer_, tail_, str(original).strip(" \t\n\v\f\r")), []).append((tid, amount))
    links = {}
    for refund_id, issuer, tail, original_no in refunds:
        if not issuer or not tail:
            continue
        key = (issuer, tail, str(original_no).strip(" \t\n\v\f\r"))
        originals = purchases.get(key, [])
        if len(originals) != 1:
            continue
        original_id, gross, clean = originals[0]
        if not clean:
            continue
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


def _foreign_pool(conn, taken, *, include_protected=False) -> tuple:
    """Purchases and cancellations that can pair by foreign amount, keyed by card, merchant, currency and amount."""
    rows = conn.execute(
        "SELECT transaction_id, transaction_direction, issuer, card_tail, merchant_normalized, amount_krw,"
        " foreign_amount, foreign_currency, COALESCE(NULLIF(approval_date,''),posting_date), original_approval_number"
        f" FROM transactions WHERE {'1=1' if include_protected else _CLEAN} AND COALESCE(foreign_currency,'')!='' AND COALESCE(foreign_amount,'')!=''"
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


def kakao_refund_candidates(conn, requested=None) -> dict:
    """Compatibility view of the same inference used by links, groups and UI."""
    return {tid: dict(link) for tid, link in _read_analysis(conn)[0].items()
            if link.get('basis') == 'kakao_same_card_exact_amount'
            and (requested is None or tid in requested)}


def _kakao_refund_candidates(conn) -> dict:
    return kakao_refund_candidates(conn)



def _kakao_merchant_family(merchant):
    """Bound taxi spelling variants; other Kakao services require identical labels."""
    import re
    compact = re.sub(r'[^0-9a-z가-힣]', '', str(merchant or '').casefold())
    if (compact.startswith(('카카오t', '카카오택시', '카카오모빌리티택시'))
            and not any(word in compact for word in ('대리', '주차', '바이크', '퀵'))):
        return '카카오택시'
    return compact


def _kakao_amount_links(conn, taken, requested=None, *, occupied_refunds=()):
    return {tid: link for tid, link in _amount_inferred_links(
        conn, taken, requested, occupied_refunds=occupied_refunds).items()
        if link['basis'] == 'kakao_same_card_exact_amount'}


def _amount_inferred_links(conn, taken, requested=None, *, occupied_refunds=()):
    """Accepted exact-KRW pairing with bidirectional global uniqueness.

    Identical merchants require the same use date. Kakao taxi spelling variants
    may use the existing 14-day window. An original approval reference is not
    required for this pairing; it is never proof of an actual cash refund.
    A purchase must not be consumed by
    approval-number/foreign pairing. All possible edges participate in uniqueness
    checks, including an ambiguous refund and an already consumed original.
    A conflicted source cannot make its clean competitor look unique.
    """
    rows = conn.execute(
        "SELECT transaction_id,transaction_direction,issuer,card_tail,merchant,"
        " amount_krw,COALESCE(NULLIF(approval_date,''),posting_date),original_approval_number,"
        " duplicate_of,conflict_reason,parse_error,foreign_currency,foreign_amount,merchant_normalized"
        " FROM transactions WHERE "
        " ((transaction_direction='purchase' AND amount_krw>0) OR"
        " (transaction_direction='cancellation' AND amount_krw<0"
        " AND TRIM(COALESCE(original_approval_number,''),char(9)||char(10)||char(11)||char(12)||char(13)||' ')=''))"
    ).fetchall()
    purchases, refunds = {}, []
    for (tid, direction, issuer, tail, merchant, amount, raw_day, original,
         duplicate, conflict, error, currency, foreign, normalized) in rows:
        if not issuer or not tail or not merchant:
            continue
        when = _day(raw_day)
        if when is None:
            continue
        clean = duplicate is None and not conflict and not error and not currency and not foreign
        entry = (tid, issuer, tail, abs(amount), when, merchant, clean,
                 str(normalized or merchant).strip())
        if direction == 'purchase':
            purchases.setdefault((issuer, tail, abs(amount)), []).append(entry)
        elif direction == 'cancellation':
            refunds.append(entry)
    candidates, collisions = {}, {}
    for refund in refunds:
        rid, issuer, tail, amount, when, merchant, clean, normalized = refund
        # Keep every candidate, including dirty/occupied rows: they must still
        # defeat uniqueness. Index only exact card and amount, never merchant
        # families, dates or cleanliness, which participate in later guards.
        matches = [p for p in purchases.get((issuer, tail, amount), ())
                   if ((0 <= (when - p[4]).days <= 14
                         and '카카오' in merchant and '카카오' in p[5])
                        or (when == p[4] and normalized == p[7]))]
        for purchase in matches:
            collisions[purchase[0]] = collisions.get(purchase[0], 0) + 1
        if len(matches) == 1 and clean:
            purchase = matches[0]
            kakao = '카카오' in merchant and '카카오' in purchase[5]
            if kakao and _kakao_merchant_family(purchase[5]) != _kakao_merchant_family(merchant):
                continue
            candidates[rid] = (purchase, 'kakao_same_card_exact_amount_inferred' if kakao
                               else 'same_card_merchant_day_exact_amount_inferred')
    links = {}
    for refund_id, (purchase, basis) in candidates.items():
        original_id, _, _, gross, _, merchant, clean, _ = purchase
        if (not clean or original_id in taken or refund_id in occupied_refunds
                or collisions[original_id] != 1
                or (requested is not None and refund_id not in requested)):
            continue
        links[refund_id] = {
            'original_id': original_id, 'gross_krw': gross, 'refund_krw': -gross,
            'refunds_total_krw': -gross, 'net_krw': 0,
            'status': 'full', 'refund_count': 1,
            'basis': basis.removesuffix('_inferred'),
            'matching_source': 'automatic', 'inferred': False,
        }
    return links


def count_held_cancellations(conn) -> dict:
    """{cancellation_id: counts} for identical cancellations left over while identical purchases exist.

    Among identical rows the purchase a cancellation undoes is unknown, so these are not recorded one by one. They wait
    as a count group until the statement's counts are checked."""
    return {tid: dict(counts) for tid, counts in _read_analysis(conn)[1].items()}


def refund_review_originals(conn):
    """Protect actual links and unresolved amount/date candidates, never a whole merchant.

    This is a read-only queue boundary, not a new pairing or refund decision.
    Ambiguous candidates remain visible without being promoted to links.
    """
    extra = _read_analysis(conn)[2]
    if extra is not None:
        return list(extra['review_originals'])
    refund_ids = [row[0] for row in conn.execute(
        "SELECT transaction_id FROM transactions WHERE transaction_direction IN ('cancellation','refund')")]
    links = refund_links(conn, refund_ids)
    protected = {link['original_id'] for link in links.values()}
    # A reference stays protected even when duplicate originals prevent a link.
    protected.update(row[0] for row in conn.execute(
        "SELECT p.transaction_id FROM transactions p JOIN transactions c"
        " ON c.issuer=p.issuer AND c.card_tail=p.card_tail"
        " AND TRIM(c.original_approval_number,char(9)||char(10)||char(11)||char(12)||char(13)||' ')=TRIM(p.approval_number,char(9)||char(10)||char(11)||char(12)||char(13)||' ')"
        " WHERE p.transaction_direction='purchase' AND COALESCE(TRIM(p.approval_number,char(9)||char(10)||char(11)||char(12)||char(13)||' '),'')!=''"
        " AND (c.transaction_direction IN ('cancellation','refund') OR c.amount_krw<0)"))
    purchases, refunds = _foreign_pool(conn, set(), include_protected=True)
    window = int(_settings()['max_days_after_purchase'])
    for key, candidates in purchases.items():
        for tid, _amount, day in candidates:
            if any(0 <= (refund_day - day).days <= window for rid, _, refund_day in refunds.get(key, ())
                   if rid not in links):
                protected.add(tid)
    # Domestic ambiguous exact-amount candidates retain the existing same-day
    # rule and the bounded Kakao taxi window, including dirty source competitors.
    rows = conn.execute(
        "SELECT p.transaction_id,p.merchant,c.merchant,p.merchant_normalized,c.merchant_normalized,"
        " COALESCE(NULLIF(p.approval_date,''),p.posting_date),"
        " COALESCE(NULLIF(c.approval_date,''),c.posting_date),c.transaction_id"
        " FROM transactions p JOIN transactions c ON p.issuer=c.issuer AND p.card_tail=c.card_tail"
        " AND p.amount_krw=-c.amount_krw WHERE p.transaction_direction='purchase' AND p.amount_krw>0"
        " AND c.transaction_direction IN ('cancellation','refund')"
        " AND COALESCE(TRIM(c.original_approval_number),'')=''"
        " AND COALESCE(p.foreign_currency,'')='' AND COALESCE(c.foreign_currency,'')=''"
        " AND COALESCE(p.foreign_amount,'')='' AND COALESCE(c.foreign_amount,'')=''").fetchall()
    for tid, merchant, refund_merchant, normalized, refund_normalized, day, refund_day, rid in rows:
        if rid in links:
            continue
        start, end = _day(day), _day(refund_day)
        if start and end and ((start == end and normalized and normalized == refund_normalized)
                or ('카카오' in str(merchant) and '카카오' in str(refund_merchant) and 0 <= (end-start).days <= 14)):
            protected.add(tid)
    return sorted(protected)
