"""Read-only source-completeness gates for projection review.

The functions in this module intentionally do not mutate a projection and do
not create a replacement ``source_event_id``.  They are used by dry-runs and
tests to make source loss visible before a workbook can be treated as closed.
"""
from __future__ import annotations

import re
from collections import Counter, defaultdict
from typing import Iterable, Mapping


# Approved P6 inventory.  These are floors, not today's expected total: a
# source can grow append-only, but a loss in one source cannot be masked by
# growth in another source.
HISTORICAL_SOURCE_RECORD_FLOORS = {
    "cards": 5_237,
    "manual": 1_379,
    "ota": 1_720,
}


def source_inventory_gate(
    source_summaries: Mapping[str, Mapping[str, object]],
    *,
    direct_records: int,
    floors: Mapping[str, int] = HISTORICAL_SOURCE_RECORD_FLOORS,
) -> dict[str, object]:
    """Reconcile current source totals and enforce independent floors."""
    actual = {
        name: int(source_summaries.get(name, {}).get("records") or 0)
        for name in floors
    }
    # Receipt batches are a fourth append-only direct source.  They have no
    # historical floor yet, but their manifest and physical receipt records
    # must still reconcile to the durable direct-source inventory.
    if "receipts" in source_summaries:
        actual["receipts"] = int(
            source_summaries.get("receipts", {}).get("records") or 0
        )
    expected_direct_records = sum(actual.values())
    below_floor = {
        name: {"actual": actual[name], "floor": floor}
        for name, floor in floors.items()
        if actual[name] < floor
    }
    return {
        "actual": actual,
        "expected_direct_records": expected_direct_records,
        "direct_records": int(direct_records),
        "direct_records_reconciled": int(direct_records) == expected_direct_records,
        "below_historical_floor": below_floor,
        "passed": not below_floor
        and int(direct_records) == expected_direct_records,
    }


def _text(value: object) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _event_key(row: Mapping[str, object]) -> str:
    """Return the explicit source event ID, or a clearly-labelled fallback.

    A legacy display UID is useful to *observe* a disappearance, but is never
    promoted to a stable source event identifier.
    """
    explicit = _text(row.get("source_event_id"))
    if explicit:
        return explicit
    uid = _text(row.get("uid"))
    return f"legacy_uid:{uid}" if uid else "legacy_uid:<missing>"


def _identity_quality(row: Mapping[str, object]) -> str:
    return "explicit" if _text(row.get("source_event_id")) else "legacy_uid_fallback"


def _rekey_candidate_key(row: Mapping[str, object]) -> tuple[str, ...] | None:
    """A strict, review-only signature for positional UID churn.

    It includes amount and date in addition to approval number.  Rows lacking
    an approval number have no rekey heuristic at all: merchant/date/amount is
    insufficient to call them a candidate.  Even a unique approval candidate
    is not a source-event match unless an explicit source_event_id proves it.
    """
    source = _text(row.get("src"))
    approval = re.sub(r"\D", "", _text(row.get("appr")))
    amount = _text(row.get("krw")).replace(",", "")
    occurred_on = _text(row.get("use_date"))
    if not approval:
        return None
    return ("approval", source, approval, amount, occurred_on)


def _unproven_structural_key(row: Mapping[str, object]) -> tuple[str, ...]:
    """Return a diagnostic-only key for rows that lack an approval number."""
    return (
        "structure",
        _text(row.get("src")),
        _text(row.get("krw")).replace(",", ""),
        _text(row.get("use_date")),
        _text(row.get("merchant")).upper(),
    )


def source_loss_gate(
    baseline_rows: Iterable[Mapping[str, object]],
    current_rows: Iterable[Mapping[str, object]],
    *,
    reviewed_display_uid_aliases: Mapping[str, str] | None = None,
) -> dict[str, object]:
    """Diff a projected snapshot without auto-resolving UID changes.

    ``rekey_candidates`` remain an identity-review queue.  Only rows with no
    current structural candidate enter ``closure_blocking_queue`` as actually
    absent events.  Both queues block a clean close: a candidate cannot become
    an automatic match merely because its display UID changed.
    """
    # A display UID alias explains legacy renumbering to a reviewer.  It is
    # intentionally not accepted as source identity and cannot clear a close
    # blocker; only an explicit source_event_id can do that.
    aliases = dict(reviewed_display_uid_aliases or {})
    baseline = list(baseline_rows)
    current = list(current_rows)
    current_by_event = {_event_key(row): row for row in current}
    current_by_candidate: dict[tuple[str, ...], list[Mapping[str, object]]] = (
        defaultdict(list)
    )
    current_by_structure: dict[tuple[str, ...], list[Mapping[str, object]]] = (
        defaultdict(list)
    )
    for row in current:
        candidate_key = _rekey_candidate_key(row)
        if candidate_key is not None:
            current_by_candidate[candidate_key].append(row)
        current_by_structure[_unproven_structural_key(row)].append(row)

    missing = [row for row in baseline if _event_key(row) not in current_by_event]
    added = [row for row in current if _event_key(row) not in {_event_key(r) for r in baseline}]
    rekey_candidates: list[dict[str, object]] = []
    closure_blocking_queue: list[dict[str, object]] = []
    unproven_structural_candidates: list[dict[str, object]] = []
    reviewed_aliases: list[dict[str, object]] = []
    for row in missing:
        candidate_key = _rekey_candidate_key(row)
        candidates = current_by_candidate[candidate_key] if candidate_key else []
        base_item = {
            "source_event_id": _event_key(row),
            "uid": _text(row.get("uid")),
            "src": _text(row.get("src")),
            "approval_number": re.sub(r"\D", "", _text(row.get("appr"))),
            "amount_krw": _text(row.get("krw")),
            "occurred_on": _text(row.get("use_date")),
            "identity_quality": _identity_quality(row),
        }
        alias_uid = aliases.get(base_item["uid"])
        if alias_uid:
            reviewed_aliases.append(
                base_item
                | {
                    "candidate_uid": alias_uid,
                    "status": "display_uid_alias_not_source_identity",
                }
            )
        if len(candidates) == 1:
            # Deliberately report, never equate.  The candidate has no bearing
            # on source-event coverage until a stable source ID is supplied.
            rekey_candidates.append(
                base_item
                | {
                    "candidate_uid": _text(candidates[0].get("uid")),
                    "candidate_source_event_id": _event_key(candidates[0]),
                    "status": "requires_explicit_source_event_id",
                }
            )
        else:
            structural_candidates = (
                current_by_structure[_unproven_structural_key(row)]
                if candidate_key is None
                else []
            )
            if len(structural_candidates) == 1:
                unproven_structural_candidates.append(
                    base_item
                    | {
                        "candidate_uid": _text(structural_candidates[0].get("uid")),
                        "status": "not_a_source_event_match",
                    }
                )
            closure_blocking_queue.append(
                base_item
                | {
                    "status": "source_event_absent",
                    "approval_candidate_count": len(candidates),
                    "unproven_structural_candidate_count": len(structural_candidates),
                }
            )

    return {
        "baseline_rows": len(baseline),
        "current_rows": len(current),
        "missing_source_event_ids": len(missing),
        "added_source_event_ids": len(added),
        "net_row_delta": len(current) - len(baseline),
        "identity_quality": dict(
            sorted(Counter(_identity_quality(row) for row in baseline + current).items())
        ),
        "rekey_candidates": rekey_candidates,
        "unproven_structural_candidates": unproven_structural_candidates,
        "reviewed_display_uid_aliases": reviewed_aliases,
        "closure_blocking_queue": closure_blocking_queue,
        "closure_blocked": bool(rekey_candidates or closure_blocking_queue),
    }
