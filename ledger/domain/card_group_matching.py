"""Exact cardinality matching for repeated card events.

Two genuinely separate card charges can have the same date, merchant and
amount.  They must not be deduplicated.  When the classified projection and
the raw source contain the same number of events for an exact structural key,
the whole group can be consumed without inventing an arbitrary 1:1 choice.
"""
from __future__ import annotations

import hashlib
import json
import re
from collections import defaultdict
from typing import Iterable


def _merchant(value: object) -> str:
    return re.sub(r"[^0-9A-Z가-힣]", "", str(value or "").upper())


def _amount(value: object) -> int:
    try:
        return int(round(float(str(value or "0").replace(",", ""))))
    except (TypeError, ValueError):
        return 0


def _digits(value: object) -> str:
    return re.sub(r"\D", "", str(value or ""))


def _lifecycle_signature(
    row: dict[str, object], *, raw: bool
) -> tuple[str, str, str, str, int, str, str]:
    """Return a cardinality key for an approval/refund source event.

    Raw locators are intentionally not part of the key because an older flat
    projection does not carry them.  Approval and original approval are, so
    same-date/same-amount transactions cannot consume each other.
    """
    amount = int(row.get("amt") or 0) if raw else _amount(row.get("krw"))
    cancelled = (
        bool(row.get("cx"))
        if raw
        else bool(row.get("cancel")) or amount < 0
    )
    source = str(row.get("src") or "")
    approval = _digits(row.get("appr"))
    original = _digits(row.get("orig") if raw else row.get("orig_appr"))
    # KB overseas RAW supplies neither approval nor original-approval. A
    # projection may carry a reviewed KPxxxx group label, but that label is
    # not a card-issued identifier and cannot alter event-set cardinality.
    if source == "KBO" and cancelled:
        approval = ""
        original = ""
    return (
        source,
        str(row.get("use") if raw else row.get("use_date") or "")[:10],
        str(row.get("c4") if raw else row.get("card4") or "")[-4:],
        "refund" if cancelled else "purchase",
        abs(amount),
        approval,
        original,
    )


def lifecycle_event_set_gate(
    projected_rows: Iterable[dict[str, object]],
    raw_cards: Iterable[dict[str, object]],
) -> dict[str, object]:
    """Require the projected approval/refund event multiset to equal RAW.

    This catches both loss of one of two same-amount lifecycle pairs and a
    projection that consumes a single approval event more than once.  It is a
    cardinality proof, not an arbitrary pair assignment.
    """
    projected_rows = list(projected_rows)
    raw_cards = list(raw_cards)
    raw_by_signature: dict[tuple[str, str, str, str, int, str, str], list[str]] = defaultdict(list)
    for card in raw_cards:
        signature = _lifecycle_signature(card, raw=True)
        approval_less_kbo_refund = (
            signature[0] == "KBO" and signature[3] == "refund"
        )
        if signature[4] and (signature[5] or approval_less_kbo_refund):
            raw_by_signature[signature].append(
                f"{card.get('src')}:{card.get('raw_record_id')}"
            )
    projected_counts: dict[tuple[str, str, str, str, int, str, str], int] = defaultdict(int)
    for row in projected_rows:
        signature = _lifecycle_signature(row, raw=False)
        approval_less_kbo_refund = (
            signature[0] == "KBO" and signature[3] == "refund"
        )
        if signature[4] and (signature[5] or approval_less_kbo_refund):
            projected_counts[signature] += 1

    def detail(signature: tuple[str, str, str, str, int, str, str], count: int) -> dict[str, object]:
        source, occurred_on, card4, role, amount, approval, original = signature
        return {
            "source": source, "occurred_on": occurred_on, "card4": card4,
            "role": role, "amount_krw": amount, "approval_number": approval,
            "original_approval_number": original, "count": count,
            "raw_locators": sorted(raw_by_signature.get(signature, [])),
        }

    missing = [
        detail(signature, len(raw_ids) - projected_counts.get(signature, 0))
        for signature, raw_ids in raw_by_signature.items()
        if len(raw_ids) > projected_counts.get(signature, 0)
    ]
    overconsumed = [
        detail(signature, count - len(raw_by_signature.get(signature, [])))
        for signature, count in projected_counts.items()
        if count > len(raw_by_signature.get(signature, []))
    ]
    raw_rows = [dict(card) for card in raw_cards]

    purchases: dict[tuple[str, str], list[dict[str, object]]] = defaultdict(list)
    refunds: dict[tuple[str, str], list[dict[str, object]]] = defaultdict(list)
    sign_errors: list[dict[str, object]] = []
    missing_original_blockers: list[dict[str, object]] = []
    lifecycle_exceptions: list[dict[str, object]] = []

    def outside_window(row: dict[str, object]) -> bool:
        return bool(row.get("outside_source_window")) or str(
            row.get("resolution_code") or ""
        ) == "original_outside_window"

    def kbo_overseas(row: dict[str, object]) -> bool:
        if str(row.get("src") or "") != "KBO":
            return False
        country = str(row.get("country") or "").upper()
        sub = str(row.get("sub") or "")
        currency = str(row.get("cur") or row.get("currency") or "").upper()
        return (
            country not in ("", "KR", "KOR", "KOREA")
            or "해외" in sub
            or "국외" in sub
            or currency not in ("", "KRW")
        )

    for card in raw_rows:
        amount = int(card.get("amt") or 0)
        cancelled = bool(card.get("cx"))
        source = str(card.get("src") or "")
        approval = _digits(card.get("appr"))
        original = _digits(card.get("orig"))
        locator = f"{source}:{card.get('raw_record_id')}"
        if amount <= 0:
            sign_errors.append(
                {"raw_locator": locator, "reason": "raw_amount_not_positive"}
            )
        if cancelled:
            if original:
                refunds[(source, original)].append(card)
            elif outside_window(card):
                lifecycle_exceptions.append(
                    {
                        "raw_locator": locator,
                        "reason": "original_outside_source_window",
                    }
                )
            elif kbo_overseas(card):
                lifecycle_exceptions.append(
                    {
                        "raw_locator": locator,
                        "reason": "kbo_overseas_original_approval_unavailable",
                    }
                )
            else:
                missing_original_blockers.append(
                    {
                        "raw_locator": locator,
                        "reason": "refund_original_approval_missing",
                    }
                )
        elif approval:
            purchases[(source, approval)].append(card)

    projected_sign_errors = []
    for row in projected_rows:
        amount = _amount(row.get("krw"))
        if bool(row.get("cancel")) and amount >= 0:
            projected_sign_errors.append(
                {
                    "uid": str(row.get("uid") or ""),
                    "reason": "cancelled_projection_not_negative",
                }
            )
    sign_errors.extend(projected_sign_errors)

    one_to_many: list[dict[str, object]] = []
    over_refunded: list[dict[str, object]] = []
    for key, refund_rows in refunds.items():
        purchase_rows = purchases.get(key, [])
        refunded = sum(abs(int(row.get("amt") or 0)) for row in refund_rows)
        gross = sum(abs(int(row.get("amt") or 0)) for row in purchase_rows)
        detail_row = {
            "source": key[0],
            "original_approval_number": key[1],
            "purchase_leg_count": len(purchase_rows),
            "refund_leg_count": len(refund_rows),
            "gross_krw": gross,
            "refunded_krw": refunded,
            "residual_krw": gross - refunded if purchase_rows else None,
        }
        if len(refund_rows) > 1:
            one_to_many.append(detail_row)
        if purchase_rows and refunded > gross:
            over_refunded.append(detail_row)
        elif not purchase_rows and not all(outside_window(row) for row in refund_rows):
            missing_original_blockers.append(
                detail_row | {"reason": "original_event_not_in_source_window"}
            )
        elif not purchase_rows:
            lifecycle_exceptions.append(
                detail_row | {"reason": "original_outside_source_window"}
            )

    semantic_blockers = (
        sign_errors + over_refunded + missing_original_blockers
    )
    return {
        "raw_event_count": sum(map(len, raw_by_signature.values())),
        "projected_event_count": sum(projected_counts.values()),
        "missing_raw_events": missing,
        "overconsumed_raw_events": overconsumed,
        "one_to_many_refund_groups": one_to_many,
        "over_refunded_groups": over_refunded,
        "sign_errors": sign_errors,
        "missing_original_blockers": missing_original_blockers,
        "lifecycle_exceptions": lifecycle_exceptions,
        "passed": not missing and not overconsumed and not semantic_blockers,
    }


def _compatible_merchant(left: object, right: object) -> bool:
    a, b = _merchant(left), _merchant(right)
    return bool(
        a
        and b
        and (
            a in b
            or b in a
            or (len(a) >= 8 and len(b) >= 8 and a[:8] == b[:8])
        )
    )


def balanced_exact_card_groups(
    classified_rows: Iterable[dict[str, str]],
    card_rows: Iterable[dict[str, object]],
    source_to_issuer: dict[str, str],
) -> list[dict[str, object]]:
    base_groups: dict[tuple[object, ...], list[dict[str, str]]] = defaultdict(list)
    card_groups: dict[tuple[object, ...], list[dict[str, object]]] = defaultdict(list)

    for row in classified_rows:
        issuer = source_to_issuer.get(str(row.get("src") or ""))
        if not issuer:
            continue
        try:
            amount = int(round(float(str(row.get("krw") or "0").replace(",", ""))))
        except ValueError:
            continue
        key = (
            issuer,
            str(row.get("use_date") or "")[:10],
            abs(amount),
            amount < 0,
            _merchant(row.get("merchant")),
        )
        if amount and key[-1]:
            base_groups[key].append(row)

    for card in card_rows:
        key = (
            str(card.get("co") or ""),
            str(card.get("use") or "")[:10],
            int(card.get("amt") or 0),
            bool(card.get("cx")),
            _merchant(card.get("mer")),
        )
        if key[2] and key[-1]:
            card_groups[key].append(card)

    groups: list[dict[str, object]] = []
    for key, bases in base_groups.items():
        cards = card_groups.get(key, [])
        if cards and len(cards) == len(bases):
            base_ids = sorted(str(base.get("uid") or "") for base in bases)
            raw_ids = sorted(
                f"{card.get('src')}:{card.get('raw_record_id')}" for card in cards
            )
            scope = (
                "multiset_exact"
                if len(cards) > 1 and not any(card.get("appr") for card in cards)
                else "unique_exact"
            )
            digest = hashlib.sha256(
                json.dumps(
                    {"key": key, "base_ids": base_ids, "raw_ids": raw_ids},
                    ensure_ascii=False,
                    sort_keys=True,
                ).encode("utf-8")
            ).hexdigest()[:16]
            groups.append(
                {
                    "group_id": f"card-group:{digest}",
                    "base_ids": base_ids,
                    "raw_ids": raw_ids,
                    "match_scope": scope,
                    "individual_identity_confirmed": scope == "unique_exact",
                }
            )
    return groups


def balanced_exact_card_keys(
    classified_rows: Iterable[dict[str, str]],
    card_rows: Iterable[dict[str, object]],
    source_to_issuer: dict[str, str],
) -> set[str]:
    """Compatibility projection: raw events consumed by balanced groups."""
    return {
        raw_id
        for group in balanced_exact_card_groups(
            classified_rows, card_rows, source_to_issuer
        )
        for raw_id in group["raw_ids"]
    }


def balanced_blank_merchant_card_groups(
    classified_rows: Iterable[dict[str, str]],
    card_rows: Iterable[dict[str, object]],
    source_to_issuer: dict[str, str],
) -> list[dict[str, object]]:
    """Return explicit N:M coverage groups when every raw merchant is blank.

    This is intentionally weaker than ``balanced_exact_card_groups``: it
    proves raw-event cardinality, not an individual merchant assignment.  It
    is allowed only with a known card suffix, exact date/amount/sign, and more
    than one event on each side.  Approval values are never used as a fallback.
    """
    base_groups: dict[tuple[object, ...], list[dict[str, str]]] = defaultdict(list)
    card_groups: dict[tuple[object, ...], list[dict[str, object]]] = defaultdict(list)
    for row in classified_rows:
        issuer = source_to_issuer.get(str(row.get("src") or ""))
        amount = _amount(row.get("krw"))
        card4 = str(row.get("card4") or "")[-4:]
        occurred_on = str(row.get("use_date") or "")[:10]
        if issuer and card4 and occurred_on and amount:
            base_groups[(issuer, card4, occurred_on, abs(amount), amount < 0)].append(row)
    for card in card_rows:
        card4 = str(card.get("c4") or "")[-4:]
        occurred_on = str(card.get("use") or "")[:10]
        amount = int(card.get("amt") or 0)
        if card4 and occurred_on and amount and not _merchant(card.get("mer")):
            card_groups[(str(card.get("co") or ""), card4, occurred_on, amount, bool(card.get("cx")))].append(card)

    groups: list[dict[str, object]] = []
    for key, bases in base_groups.items():
        cards = card_groups.get(key, [])
        if len(bases) <= 1 or len(cards) != len(bases):
            continue
        base_ids = sorted(str(base.get("uid") or "") for base in bases)
        raw_ids = sorted(f"{card.get('src')}:{card.get('raw_record_id')}" for card in cards)
        digest = hashlib.sha256(
            json.dumps({"key": key, "base_ids": base_ids, "raw_ids": raw_ids}, sort_keys=True).encode("utf-8")
        ).hexdigest()[:16]
        groups.append(
            {
                "group_id": f"card-group-blank-merchant:{digest}",
                "base_ids": base_ids,
                "raw_ids": raw_ids,
                "match_scope": "multiset_blank_merchant",
                "individual_identity_confirmed": False,
            }
        )
    return groups


def unique_exact_structural_card_links(
    classified_rows: Iterable[dict[str, str]],
    card_rows: Iterable[dict[str, object]],
    source_to_issuer: dict[str, str],
    used_card_keys: set[str] | None = None,
) -> list[dict[str, str]]:
    """Safely link one row to one raw event without relying on approval.

    Date, issuer, signed amount, and compatible card suffix are all required.
    Merchant must match when raw text is available; a blank raw merchant is
    absence of conflicting evidence, not a guessed merchant match.
    """
    used = used_card_keys or set()
    cards = list(card_rows)
    proposals: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in classified_rows:
        issuer = source_to_issuer.get(str(row.get("src") or ""))
        amount = _amount(row.get("krw"))
        occurred_on = str(row.get("use_date") or "")[:10]
        row_merchant = _merchant(row.get("merchant"))
        row_approval = re.sub(r"\D", "", str(row.get("appr") or ""))
        row_original = re.sub(r"\D", "", str(row.get("orig_appr") or ""))
        if not issuer or not amount or not occurred_on or not row_merchant:
            continue
        candidates=[]
        for card in cards:
            raw_id=f"{card.get('src')}:{card.get('raw_record_id')}"
            raw_merchant=_merchant(card.get("mer"))
            if (
                raw_id not in used
                and str(card.get("co") or "") == issuer
                and str(card.get("use") or "")[:10] == occurred_on
                and int(card.get("amt") or 0) == abs(amount)
                and bool(card.get("cx")) == (amount < 0)
                and (
                    not row_approval
                    or not re.sub(r"\D", "", str(card.get("appr") or ""))
                    or row_approval == re.sub(r"\D", "", str(card.get("appr") or ""))
                )
                and (
                    not row_original
                    or not re.sub(r"\D", "", str(card.get("orig") or ""))
                    or row_original == re.sub(r"\D", "", str(card.get("orig") or ""))
                )
                and (
                    not row.get("card4")
                    or not card.get("c4")
                    or str(row.get("card4"))[-4:] == str(card.get("c4"))[-4:]
                )
                and (not raw_merchant or _compatible_merchant(row.get("merchant"), card.get("mer")))
            ):
                candidates.append(card)
        if len(candidates) == 1:
            raw_id=f"{candidates[0].get('src')}:{candidates[0].get('raw_record_id')}"
            proposals[raw_id].append(
                {"uid": str(row.get("uid") or ""), "raw_id": raw_id, "source_identity": "structural_exact"}
            )
    return [
        proposal
        for proposals_for_raw in proposals.values()
        if len(proposals_for_raw) == 1
        for proposal in proposals_for_raw
    ]


def classify_unresolved_card_lineage(
    classified_rows: Iterable[dict[str, str]],
    card_rows: Iterable[dict[str, object]],
    source_to_issuer: dict[str, str],
    used_card_keys: set[str] | None = None,
) -> dict[str, int]:
    """Explain remaining rows without treating an approval as sufficient proof."""
    used = used_card_keys or set()
    cards = list(card_rows)
    counts: dict[str, int] = defaultdict(int)
    for row in classified_rows:
        issuer=source_to_issuer.get(str(row.get("src") or ""))
        if not issuer:
            counts["manual_or_non_card"] += 1
            continue
        amount=_amount(row.get("krw"))
        occurred_on=str(row.get("use_date") or "")[:10]
        merchant=_merchant(row.get("merchant"))
        if not amount:
            counts["zero_amount_adjustment"] += 1
        elif not occurred_on:
            counts["missing_date"] += 1
        elif not merchant:
            counts["missing_merchant"] += 1
        else:
            candidates=[
                card for card in cards
                if f"{card.get('src')}:{card.get('raw_record_id')}" not in used
                and str(card.get("co") or "") == issuer
                and str(card.get("use") or "")[:10] == occurred_on
                and int(card.get("amt") or 0) == abs(amount)
                and bool(card.get("cx")) == (amount < 0)
                and (
                    not row.get("card4") or not card.get("c4")
                    or str(row.get("card4"))[-4:] == str(card.get("c4"))[-4:]
                )
            ]
            compatible=[
                card for card in candidates
                if not _merchant(card.get("mer")) or _compatible_merchant(row.get("merchant"), card.get("mer"))
            ]
            if len(compatible) > 1:
                counts["ambiguous_exact_structural"] += 1
            elif len(compatible) == 1:
                card=compatible[0]
                approval=re.sub(r"\D", "", str(row.get("appr") or ""))
                original=re.sub(r"\D", "", str(row.get("orig_appr") or ""))
                card_approval=re.sub(r"\D", "", str(card.get("appr") or ""))
                card_original=re.sub(r"\D", "", str(card.get("orig") or ""))
                if (approval and card_approval and approval != card_approval) or (
                    original and card_original and original != card_original
                ):
                    counts["approval_conflict"] += 1
                else:
                    counts["unique_structural_available"] += 1
            elif candidates:
                counts["merchant_conflict"] += 1
            else:
                approval=re.sub(r"\D", "", str(row.get("appr") or ""))
                counts["approval_only_blocked" if approval else "no_exact_raw_event"] += 1
    return dict(sorted(counts.items()))


def unique_approval_card_links(
    classified_rows: Iterable[dict[str, str]],
    card_rows: Iterable[dict[str, object]],
    source_to_issuer: dict[str, str],
    used_card_keys: set[str] | None = None,
) -> list[dict[str, str]]:
    """Link unique approval events; a blank raw merchant is not a conflict."""
    used = used_card_keys or set()
    cards = list(card_rows)
    proposals: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in classified_rows:
        issuer = source_to_issuer.get(str(row.get("src") or ""))
        approval = re.sub(r"\D", "", str(row.get("appr") or ""))
        if not issuer or not approval:
            continue
        try:
            amount = int(round(float(str(row.get("krw") or "0").replace(",", ""))))
        except ValueError:
            continue
        if not amount:
            continue
        candidates = []
        for card in cards:
            raw_id = f"{card.get('src')}:{card.get('raw_record_id')}"
            raw_merchant = _merchant(card.get("mer"))
            row_merchant = _merchant(row.get("merchant"))
            if (
                raw_id not in used
                and str(card.get("co") or "") == issuer
                and re.sub(r"\D", "", str(card.get("appr") or "")) == approval
                and int(card.get("amt") or 0) == abs(amount)
                and bool(card.get("cx")) == (amount < 0)
                and (
                    not row.get("use_date")
                    or str(card.get("use") or "")[:10]
                    == str(row.get("use_date") or "")[:10]
                )
                and (
                    not row.get("card4")
                    or not card.get("c4")
                    or str(row.get("card4"))[-4:] == str(card.get("c4"))[-4:]
                )
                and (
                    not raw_merchant
                    or bool(
                        row_merchant
                        and (
                            raw_merchant in row_merchant
                            or row_merchant in raw_merchant
                        )
                    )
                )
            ):
                candidates.append(card)
        if len(candidates) == 1:
            card = candidates[0]
            raw_id = f"{card.get('src')}:{card.get('raw_record_id')}"
            proposals[raw_id].append(
                {
                    "uid": str(row.get("uid") or ""),
                    "raw_id": raw_id,
                    "source_identity": "direct",
                }
            )
    return [
        proposal
        for raw_proposals in proposals.values()
        if len(raw_proposals) == 1
        for proposal in raw_proposals
    ]


def enrich_unique_card_identifiers(
    classified_rows: Iterable[dict[str, str]],
    card_rows: Iterable[dict[str, object]],
) -> list[dict[str, object]]:
    """Restore approval lineage only from a unique exact structural event."""
    cards = list(card_rows)
    updated: list[dict[str, object]] = []
    for row in classified_rows:
        if row.get("src") != "KBD":
            continue
        try:
            amount = int(round(float(str(row.get("krw") or "0").replace(",", ""))))
        except ValueError:
            continue
        if not amount or (row.get("appr") and (amount > 0 or row.get("orig_appr"))):
            continue
        candidates = [
            card
            for card in cards
            if card.get("src") == "KBD"
            and int(card.get("amt") or 0) == abs(amount)
            and bool(card.get("cx")) == (amount < 0)
            and str(card.get("use") or "")[:10] == str(row.get("use_date") or "")[:10]
            and _merchant(row.get("merchant")) == _merchant(card.get("mer"))
        ]
        if len(candidates) != 1:
            continue
        card = candidates[0]
        before = (row.get("appr"), row.get("orig_appr"))
        row["appr"] = str(card.get("appr") or "")
        row["orig_appr"] = str(card.get("orig") or "")
        updated.append(
            {
                "uid": row.get("uid"),
                "before": before,
                "after": (row["appr"], row["orig_appr"]),
                "source_row": card.get("raw_record_id"),
            }
        )
    return updated
