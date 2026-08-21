"""Retain two Minatoya charges as unresolved amount-mismatch candidates."""
from __future__ import annotations

import json
import subprocess
import tempfile
from pathlib import Path

from ledger.domain import direct_manual_group_taxonomy_evidence as r36
from ledger.domain import direct_all_period_safe_group_admission as base
from ledger.domain import direct_all_period_yakushima_portal_admission as yakushima
from ledger.domain.direct_lineage_annex import REPOSITORY_ROOT

ARTIFACT_TYPE = "all-period-minatoya-amount-mismatch-candidate-v2"
RULE_VERSION = "portal-card-jpy-mismatch-candidate-only-v2"
SELECTED_SET_SHA256 = "8c839c3a275dc6846d47508dc7c494b39918f3ec466bbf3b00182a75ea890eb1"
BOOKING = "1723193688"


def _portal(repo: Path = Path(REPOSITORY_ROOT)) -> dict:
    try:
        result = subprocess.run(["git", "show", f"{yakushima.PORTAL_COMMIT}:{yakushima.PORTAL_PATH}"],
                                cwd=repo, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=10)
    except (OSError, subprocess.SubprocessError) as exc:
        raise ValueError("all_period_minatoya_portal_object_unavailable") from exc
    if yakushima._sha(result.stdout) != yakushima.PORTAL_FILE_SHA256:
        raise ValueError("all_period_minatoya_portal_file_pin_invalid")
    records = json.loads(result.stdout).get("records", [])
    matches = [row for row in records if row.get("booking_number") == BOOKING]
    if len(matches) != 1:
        raise ValueError("all_period_minatoya_portal_cardinality_invalid")
    row = matches[0]
    expected = {"card_last4": "8835", "currency": "JPY", "foreign_amount": "12069",
                "provider": "agoda", "service_start_on": "2026-10-11",
                "service_end_on": "2026-10-12", "source_channel": "authenticated_booking_portal",
                "status": "confirmed"}
    if any(row.get(key) != value for key, value in expected.items()) or row.get("extraction_sources") != ["authenticated_portal_dom"]:
        raise ValueError("all_period_minatoya_portal_fact_invalid")
    return row


def _live(
        ledger_dir: Path = Path(REPOSITORY_ROOT) / "ledger",
        *, current_context: dict[str, object] | None = None) -> tuple[dict, list[dict]]:
    portal = _portal()
    if current_context is None:
        with tempfile.TemporaryDirectory(prefix="all-period-minatoya-") as directory:
            context = r36._context(ledger_dir, Path(directory))
            try:
                events = list(context["events"])
                current_event_set_sha256 = str(context["current_event_set_sha256"])
                decision_scope_sha256 = str(context["decision_scope_sha256"])
            finally:
                context["db"].close()
    else:
        if set(current_context) != {
                "events", "current_event_set_sha256", "decision_scope_sha256"}:
            raise ValueError("all_period_minatoya_current_context_invalid")
        events = list(current_context["events"])
        current_event_set_sha256 = str(current_context["current_event_set_sha256"])
        decision_scope_sha256 = str(current_context["decision_scope_sha256"])
    if len(events) != 5328:
        raise ValueError("all_period_minatoya_current_context_invalid")
    matches = [event for event in events if
               (event["source_system"], event["occurred_on"], int(event["signed_amount_krw"]),
                event["foreign_amount"], event["currency"], event["card4"], event["merchant"],
                event["transaction_type"], event["event_role"]) ==
               ("KBO", "2026-06-26", 116935, "11885", "JPY", "8835", "AGODA.COM",
                "purchase", "single")]
    keys = {event["direct_event_key"] for event in matches}
    if len(matches) != 2 or len({event["current_source_key"] for event in matches}) != 2 or base._setsha(keys) != SELECTED_SET_SHA256:
        raise ValueError("all_period_minatoya_current_group_invalid")
    portal_jpy = int(portal["foreign_amount"]); card_jpy = int(matches[0]["foreign_amount"])
    difference_bps = abs(portal_jpy - card_jpy) * 10000 // portal_jpy
    if difference_bps != 152 or portal_jpy == card_jpy:
        raise ValueError("all_period_minatoya_jpy_difference_drift")
    proposals = [{"event_key_sha256": base._sha(event["direct_event_key"].encode()),
                  "current_event_sha256": event["current_event_sha256"],
                  "current_source_sha256": event["current_source_sha256"],
                  "portal_record_sha256": base._sha(base._json(portal)), "account": "숙박비",
                  "cost_type": "여행원가",
                  "trip_target": "1010_도쿠시마", "atomic_group_count": 2,
                  "booking_bijection_asserted": False, "jpy_difference_bps": difference_bps,
                  "candidate_status": "unresolved",
                  "reason_code": "portal_card_foreign_amount_mismatch"}
                 for event in matches]
    manifest = {"artifact_type": ARTIFACT_TYPE, "rule_version": RULE_VERSION,
                "selected_event_set_sha256": SELECTED_SET_SHA256,
                "candidate_count": 2, "full_classification_delta": 0,
                "gate5_credit": 0, "accepted_union": 1558, "global_residual": 3770,
                "booking_bijection_asserted": False, "card_event_count": 2, "portal_booking_count": 1,
                "observed_jpy_difference_bps": difference_bps,
                "generic_tolerance_allowed": False,
                "match_status": "amount_mismatch_unresolved",
                "authority_status": "candidate_only", "posting_status": "blocked",
                "database_applied": False, "contains_sensitive_raw_values": False,
                "current_event_set_sha256": current_event_set_sha256,
                "decision_scope_sha256": decision_scope_sha256}
    return manifest, proposals


def build_all_period_minatoya_portal_admission(
        *, ledger_dir: Path = Path(REPOSITORY_ROOT) / "ledger",
        current_context: dict[str, object] | None = None) -> dict:
    manifest, proposals = _live(ledger_dir, current_context=current_context)
    return {"manifest": manifest, "proposals": proposals}
