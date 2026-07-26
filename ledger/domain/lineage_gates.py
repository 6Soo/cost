"""Small, deterministic safety gates for card-event lineage projections."""
from __future__ import annotations

from collections import Counter
from typing import Iterable


NONPOSTING_SOURCE_DISPOSITIONS = {
    "superseded_duplicate_projection",
    "manual_claimed_card_no_raw",
    "rejected_legacy_projection",
}


def _is_agoda(row: dict[str, object]) -> bool:
    text = " ".join(
        str(row.get(key) or "")
        for key in ("merchant", "note", "bucket", "source_event_alias_of")
    ).upper()
    return "AGODA" in text or "아고다" in text


def unresolved_lineage_rows(
    rows: Iterable[dict[str, object]],
) -> list[dict[str, object]]:
    """Return unresolved rows without inferring identity from a display UID."""
    return [
        row
        for row in rows
        if str(row.get("source_event_id") or "").startswith("legacy:")
        or str(row.get("source_event_disposition") or "") == "raw_card_unresolved"
    ]


def lineage_semantic_counts(rows: Iterable[dict[str, object]]) -> dict[str, object]:
    """Stable dry-run counts; deliberately excludes presentation-order details."""
    materialized = list(rows)
    unresolved = unresolved_lineage_rows(materialized)
    dispositions = Counter(
        str(row.get("source_event_disposition") or "missing") for row in materialized
    )
    return {
        "projection_rows": len(materialized),
        "source_event_ids": len(
            {str(row.get("source_event_id") or "") for row in materialized}
        ),
        "unresolved_total": len(unresolved),
        "unresolved_agoda": sum(_is_agoda(row) for row in unresolved),
        "unresolved_non_agoda": sum(not _is_agoda(row) for row in unresolved),
        "nonposting_rows": sum(
            str(row.get("source_event_disposition") or "")
            in NONPOSTING_SOURCE_DISPOSITIONS
            for row in materialized
        ),
        "dispositions": dict(sorted(dispositions.items())),
    }


def require_zero_non_agoda_unresolved(rows: Iterable[dict[str, object]]) -> None:
    unresolved = [row for row in unresolved_lineage_rows(rows) if not _is_agoda(row)]
    if unresolved:
        examples = ", ".join(str(row.get("uid") or "") for row in unresolved[:10])
        raise RuntimeError(
            "non-Agoda card lineage must be resolved or explicitly dispositioned; "
            f"count={len(unresolved)} examples={examples}"
        )


def require_protected_uids_preserved(
    input_rows: Iterable[dict[str, object]],
    output_rows: Iterable[dict[str, object]],
    protected_uids: Iterable[str],
) -> None:
    before = {str(row.get("uid") or "") for row in input_rows}
    after = {str(row.get("uid") or "") for row in output_rows}
    missing = sorted(uid for uid in protected_uids if uid in before and uid not in after)
    if missing:
        raise RuntimeError("protected source rows were deleted: " + ", ".join(missing))


def require_valid_nonposting_aliases(rows: Iterable[dict[str, object]]) -> None:
    expected = {
        "superseded_duplicate_projection": "projection-alias:",
        "manual_claimed_card_no_raw": "manual-claimed-card-no-raw:",
        "rejected_legacy_projection": "rejected-legacy-projection:",
    }
    invalid: list[str] = []
    for row in rows:
        disposition = str(row.get("source_event_disposition") or "")
        if disposition not in expected:
            continue
        event_id = str(row.get("source_event_id") or "")
        if (
            not event_id.startswith(expected[disposition])
            or str(row.get("source_event_members") or "") != event_id
            or not str(row.get("source_event_alias_of") or "")
        ):
            invalid.append(str(row.get("uid") or event_id))
    if invalid:
        raise RuntimeError("invalid non-posting lineage aliases: " + ", ".join(invalid[:10]))


def require_raw_cancellation_signs(rows: Iterable[dict[str, object]]) -> None:
    """A raw-card cancellation must remain negative in the cost projection."""
    invalid: list[str] = []
    for row in rows:
        if not str(row.get("source_event_id") or "").startswith("card:"):
            continue
        try:
            amount = int(round(float(str(row.get("krw") or "0").replace(",", ""))))
        except ValueError:
            continue
        if not amount:
            continue
        cancelled = str(row.get("cancel") or "").strip().lower() in {
            "true", "1", "y", "yes"
        }
        if cancelled != (amount < 0):
            invalid.append(str(row.get("uid") or row.get("source_event_id") or ""))
    if invalid:
        raise RuntimeError("raw cancellation sign mismatch: " + ", ".join(invalid[:10]))
