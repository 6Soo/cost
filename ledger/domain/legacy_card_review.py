"""Review-only guard for legacy projection rows that look like card charges.

This module deliberately returns a review disposition rather than a card event
identifier.  A projection row without explicit source lineage may resemble a
raw-card row by approval number and amount, but that is not authority to claim
the raw event.
"""
from __future__ import annotations

import re
from typing import Iterable, Mapping


def _digits(value: object) -> str:
    return re.sub(r"\D", "", str(value or ""))


def _amount(value: object) -> int:
    try:
        return abs(int(round(float(str(value or "0").replace(",", "")))))
    except ValueError:
        return 0


def _date(value: object) -> str:
    return str(value or "").strip()[:10]


def _merchant(value: object) -> str:
    return re.sub(r"[^0-9A-Z]", "", str(value or "").upper())


def _merchant_matches(left: object, right: object) -> bool:
    a, b = _merchant(left), _merchant(right)
    return bool(a and b and (a in b or b in a or (len(a) >= 8 and a[:8] == b[:8])))


def _cancelled(row: Mapping[str, object]) -> bool:
    return (
        str(row.get("cancel") or "").strip().lower() in {"true", "1", "y", "yes"}
        or str(row.get("cx") or "").strip().lower() in {"true", "1", "y", "yes"}
        or row.get("cancel") is True
        or str(row.get("krw") or row.get("amt") or "").strip().startswith("-")
    )


def _raw_id(card: Mapping[str, object]) -> str:
    return f"{card.get('src') or ''}:{card.get('raw_record_id') or ''}"


def review_legacy_card_claim(
    row: Mapping[str, object], cards: Iterable[Mapping[str, object]],
) -> dict[str, object]:
    """Classify a legacy card-looking row without linking it to a raw event.

    An explicit source event is retained for its caller to validate separately.
    Without it, even one exact raw candidate is *manual review*, never a
    source-event assignment.  The result distinguishes no raw material from a
    conflicting candidate, including opposite approval/cancellation roles.
    """
    explicit = str(row.get("source_event_id") or "").strip()
    if explicit:
        return {"status": "explicit_source_event_present", "source_event_id": explicit}

    source = str(row.get("src") or "").strip()
    approval = _digits(row.get("appr"))
    amount = _amount(row.get("krw"))
    cancelled = _cancelled(row)
    if not source or not amount:
        return {"status": "manual_review_required", "reason": "insufficient_legacy_facts"}

    materialized = list(cards)
    same_source = [card for card in materialized if str(card.get("src") or "") == source]
    same_approval_amount = [
        card
        for card in same_source
        if (not approval or _digits(card.get("appr")) == approval)
        and _amount(card.get("krw", card.get("amt"))) == amount
    ]
    cross_source = [
        card
        for card in materialized
        if approval
        and _digits(card.get("appr")) == approval
        and _amount(card.get("krw", card.get("amt"))) == amount
        and str(card.get("src") or "") != source
    ]
    if not same_approval_amount:
        if cross_source:
            return {
                "status": "source_conflict",
                "candidate_raw_ids": sorted(_raw_id(card) for card in cross_source),
            }
        return {"status": "raw_material_absent"}

    same_role = [card for card in same_approval_amount if _cancelled(card) == cancelled]
    if not same_role:
        return {
            "status": "cancellation_role_conflict",
            "candidate_raw_ids": sorted(_raw_id(card) for card in same_approval_amount),
        }

    exact = [
        card
        for card in same_role
        if _date(card.get("use") or card.get("use_date")) == _date(row.get("use_date"))
        and _merchant_matches(card.get("mer") or card.get("merchant"), row.get("merchant"))
    ]
    if len(exact) == 1:
        return {
            "status": "manual_review_required",
            "reason": "explicit_source_event_id_required",
            "candidate_raw_ids": [_raw_id(exact[0])],
        }

    mismatch_fields: set[str] = set()
    for card in same_role:
        if _date(card.get("use") or card.get("use_date")) != _date(row.get("use_date")):
            mismatch_fields.add("date")
        if not _merchant_matches(card.get("mer") or card.get("merchant"), row.get("merchant")):
            mismatch_fields.add("merchant")
    return {
        "status": "facts_conflict",
        "mismatch_fields": sorted(mismatch_fields),
        "candidate_raw_ids": sorted(_raw_id(card) for card in same_role),
    }
