"""Decision-authoritative OTA reporting helpers.

The legacy verified-link JSON is an evidence inventory, not a decision log.
Reporting therefore reads only the current append-only match decision for each
payment and keeps unprocessed rows distinct from actual conflicts.
"""
from __future__ import annotations

import json
import sqlite3
from collections import defaultdict
from typing import Mapping


MATCHER_PROVIDERS = {"agoda", "booking"}
UNASSIGNED_TRAVEL_BUCKETS = {"", "여행_미배정", "미청구_예약확정"}
STATUS_PRIORITY = {
    "conflict": 60,
    "confirmed_strong": 50,
    "confirmed_manual": 40,
    "unmatched": 20,
    "proposed": 10,
}


def current_payment_decision_states(
    db: sqlite3.Connection,
) -> dict[str, dict[str, object]]:
    """Return the highest-authority current match decision per payment.

    A payment can appear in both a legacy proposal and a direct-evidence
    decision.  Confirmed direct/manual decisions take precedence, followed by
    conflicts, unmatched evidence and proposals.  The selected row always
    retains its actor and decision ID so the report cannot promote JSON
    membership to a confirmation.
    """
    candidates: dict[str, list[dict[str, object]]] = defaultdict(list)
    for row in db.execute(
        """
        SELECT payment.external_key, decision.status, projection.group_key,
               projection.provider, decision.decision_id, decision.actor,
               decision.reason_code, decision.decided_at
        FROM current_match_group_projection projection
        JOIN match_group_payments member
          ON member.group_id=projection.group_id
        JOIN payment_transactions payment ON payment.id=member.payment_id
        JOIN current_match_decisions decision
          ON decision.group_id=projection.group_id
        """
    ).fetchall():
        item = dict(row)
        item["status"] = str(item.get("status") or "proposed")
        candidates[str(row["external_key"])].append(item)

    selected: dict[str, dict[str, object]] = {}
    for external_key, rows in candidates.items():
        rows.sort(
            key=lambda item: (
                STATUS_PRIORITY.get(str(item["status"]), 0),
                str(item.get("decided_at") or ""),
                str(item.get("decision_id") or ""),
            ),
            reverse=True,
        )
        selected[external_key] = rows[0]
        selected[external_key]["concurrent_states"] = sorted(
            {str(item["status"]) for item in rows}
        )
    return selected


def classify_payment_state(
    external_key: str,
    provider: str,
    decisions: Mapping[str, Mapping[str, object]],
) -> dict[str, object]:
    """Map one OTA payment to a mutually-exclusive, auditable report state."""
    current = decisions.get(external_key)
    if current:
        status = str(current.get("status") or "proposed")
        if status in {"confirmed_strong", "confirmed_manual"}:
            disposition = "confirmed"
            review_complete = True
        elif status == "conflict":
            disposition = "hold"
            review_complete = False
        else:
            disposition = "pending"
            review_complete = False
        evidence_disposition = {
            "confirmed": "direct_link_confirmed",
            "hold": "direct_link_conflict",
            "pending": "direct_link_unproven",
        }[disposition]
        return {
            "state": status,
            "disposition": disposition,
            "evidence_state": status,
            "evidence_disposition": evidence_disposition,
            "reason_code": str(current.get("reason_code") or status),
            "decision_id": str(current.get("decision_id") or ""),
            "decision_actor": str(current.get("actor") or ""),
            "concurrent_states": list(
                current.get("concurrent_states") or [status]
            ),
            "review_complete": review_complete,
        }

    if provider not in MATCHER_PROVIDERS:
        state = "not_investigated_no_matcher"
        reason = "provider_matcher_not_implemented"
    else:
        state = "not_investigated_pending"
        reason = "no_current_payment_decision"
    return {
        "state": state,
        "disposition": "pending",
        "evidence_state": state,
        "evidence_disposition": "direct_link_unproven",
        "reason_code": reason,
        "decision_id": "",
        "decision_actor": "",
        "concurrent_states": [],
        "review_complete": False,
    }


def classify_accounting_state(row: Mapping[str, object]) -> dict[str, object]:
    """Describe accounting completeness independently from OTA link evidence."""
    bucket = str(row.get("bucket") or "").strip()
    assigned = bucket not in UNASSIGNED_TRAVEL_BUCKETS
    return {
        "accounting_state": "classified" if assigned else "travel_unassigned",
        "filing_state": "included_in_canonical",
        "accounting_review_complete": assigned,
    }


def direct_evidence_inventory(db: sqlite3.Connection) -> dict[str, dict[str, object]]:
    """Count indexed and direct evidence separately from payment decisions."""
    inventory: dict[str, dict[str, object]] = defaultdict(
        lambda: {
            "raw_source_records": 0,
            "unique_message_records": 0,
            "raw_direct_charge_records": 0,
            "direct_charge_records": 0,
            "raw_authenticated_portal_records": 0,
            "authenticated_portal_records": 0,
            "portal_missing_record_type_records": 0,
            "portal_charge_records": 0,
            "portal_charge_missing_foreign_amount_records": 0,
            "portal_display_only_records": 0,
            "portal_currency_counts": {},
            "matched_payment_members": 0,
            "matcher_implemented": False,
        }
    )
    unique_messages: dict[str, set[str]] = defaultdict(set)
    unique_charges: dict[str, set[str]] = defaultdict(set)
    unique_portal: dict[str, dict[str, dict[str, object]]] = defaultdict(dict)
    for row in db.execute(
        """
        SELECT id, source_kind, source_key, payload_json
        FROM direct_source_records
        WHERE source_kind IN ('ota_mail', 'ota_authenticated_portal')
        """
    ).fetchall():
        try:
            payload = json.loads(row["payload_json"])
        except (TypeError, json.JSONDecodeError):
            payload = {}
        provider = str(payload.get("provider") or "unknown").lower()
        provider = {
            "booking.com": "booking",
            "trip.com": "trip",
        }.get(provider, provider)
        inventory[provider]["raw_source_records"] = (
            int(inventory[provider]["raw_source_records"]) + 1
        )
        source_channel = str(payload.get("source_channel") or "").lower()
        record_type = str(payload.get("record_type") or "").lower()
        message_id = str(payload.get("message_id") or "")
        if message_id:
            unique_messages[provider].add(message_id)
        if record_type == "charge" and source_channel in {
            "mail",
            "authenticated_booking_portal",
        }:
            inventory[provider]["raw_direct_charge_records"] = (
                int(inventory[provider]["raw_direct_charge_records"]) + 1
            )
            if message_id:
                unique_charges[provider].add(message_id)
        if source_channel == "authenticated_booking_portal":
            inventory[provider]["raw_authenticated_portal_records"] = (
                int(inventory[provider]["raw_authenticated_portal_records"]) + 1
            )
            portal_key = message_id or str(row["source_key"]) or f"id:{row['id']}"
            unique_portal[provider].setdefault(portal_key, payload)

    for provider in inventory:
        inventory[provider]["unique_message_records"] = len(
            unique_messages[provider]
        )
        inventory[provider]["direct_charge_records"] = len(
            unique_charges[provider]
        )
        inventory[provider]["authenticated_portal_records"] = len(
            unique_portal[provider]
        )
        currency_counts: dict[str, int] = defaultdict(int)
        for payload in unique_portal[provider].values():
            record_type = str(payload.get("record_type") or "").lower()
            currency = str(payload.get("currency") or "missing").upper()
            foreign_amount = payload.get("foreign_amount")
            display_amount = payload.get("booking_display_amount")
            if not record_type:
                inventory[provider]["portal_missing_record_type_records"] += 1
            if record_type == "charge":
                inventory[provider]["portal_charge_records"] += 1
                if foreign_amount in {None, ""}:
                    inventory[provider][
                        "portal_charge_missing_foreign_amount_records"
                    ] += 1
            if display_amount not in {None, ""} and foreign_amount in {None, ""}:
                inventory[provider]["portal_display_only_records"] += 1
            currency_counts[currency] += 1
        inventory[provider]["portal_currency_counts"] = dict(
            sorted(currency_counts.items())
        )

    for row in db.execute(
        """
        SELECT LOWER(COALESCE(projection.provider, 'unknown')) AS provider,
               COUNT(DISTINCT member.payment_id) AS payment_count
        FROM current_match_group_projection projection
        JOIN match_group_payments member
          ON member.group_id=projection.group_id
        WHERE projection.group_key NOT LIKE 'legacy-link:%'
        GROUP BY LOWER(COALESCE(projection.provider, 'unknown'))
        """
    ).fetchall():
        provider = {
            "booking.com": "booking",
            "trip.com": "trip",
        }.get(str(row["provider"]), str(row["provider"]))
        inventory[provider]["matched_payment_members"] += int(row["payment_count"])
    for provider in inventory:
        inventory[provider]["matcher_implemented"] = provider in MATCHER_PROVIDERS
    return dict(sorted(inventory.items()))
