"""Admit two Minatoya charges as an unordered authenticated-portal group."""
from __future__ import annotations

import json
import subprocess
import tempfile
from pathlib import Path

from ledger.domain import direct_manual_group_taxonomy_evidence as r36
from ledger.domain import direct_q2_safe_group_admission as q2
from ledger.domain import direct_q2_yakushima_portal_admission as yakushima
from ledger.domain.direct_lineage_annex import REPOSITORY_ROOT

ARTIFACT_TYPE = "q2-minatoya-authenticated-portal-group-v1"
RULE_VERSION = "q2-portal-trip-axis-jpy-tolerance-unordered-v1"
SELECTED_SET_SHA256 = "8c839c3a275dc6846d47508dc7c494b39918f3ec466bbf3b00182a75ea890eb1"
BOOKING = "1723193688"


def _portal(repo: Path = Path(REPOSITORY_ROOT)) -> dict:
    try:
        result = subprocess.run(["git", "show", f"{yakushima.PORTAL_COMMIT}:{yakushima.PORTAL_PATH}"],
                                cwd=repo, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=10)
    except (OSError, subprocess.SubprocessError) as exc:
        raise ValueError("q2_minatoya_portal_object_unavailable") from exc
    if yakushima._sha(result.stdout) != yakushima.PORTAL_FILE_SHA256:
        raise ValueError("q2_minatoya_portal_file_pin_invalid")
    records = json.loads(result.stdout).get("records", [])
    matches = [row for row in records if row.get("booking_number") == BOOKING]
    if len(matches) != 1:
        raise ValueError("q2_minatoya_portal_cardinality_invalid")
    row = matches[0]
    expected = {"card_last4": "8835", "currency": "JPY", "foreign_amount": "12069",
                "provider": "agoda", "service_start_on": "2026-10-11",
                "service_end_on": "2026-10-12", "source_channel": "authenticated_booking_portal",
                "status": "confirmed"}
    if any(row.get(key) != value for key, value in expected.items()) or row.get("extraction_sources") != ["authenticated_portal_dom"]:
        raise ValueError("q2_minatoya_portal_fact_invalid")
    return row


def _live(ledger_dir: Path = Path(REPOSITORY_ROOT) / "ledger") -> tuple[dict, list[dict]]:
    upstream = yakushima.build_q2_yakushima_portal_admission(ledger_dir=ledger_dir)["manifest"]
    if (upstream["accepted_union"], upstream["global_residual"],
            upstream["selected_event_set_sha256"]) != (1558, 3770, yakushima.SELECTED_SET_SHA256):
        raise ValueError("q2_minatoya_upstream_invalid")
    portal = _portal()
    with tempfile.TemporaryDirectory(prefix="q2-minatoya-") as directory:
        context = r36._context(ledger_dir, Path(directory))
        try:
            events = list(context["events"])
        finally:
            context["db"].close()
    matches = [event for event in events if
               (event["source_system"], event["occurred_on"], int(event["signed_amount_krw"]),
                event["foreign_amount"], event["currency"], event["card4"], event["merchant"],
                event["transaction_type"], event["event_role"]) ==
               ("KBO", "2026-06-26", 116935, "11885", "JPY", "8835", "AGODA.COM",
                "purchase", "single")]
    keys = {event["direct_event_key"] for event in matches}
    if len(matches) != 2 or len({event["current_source_key"] for event in matches}) != 2 or q2._setsha(keys) != SELECTED_SET_SHA256:
        raise ValueError("q2_minatoya_current_group_invalid")
    portal_jpy = int(portal["foreign_amount"]); card_jpy = int(matches[0]["foreign_amount"])
    difference_bps = abs(portal_jpy - card_jpy) * 10000 // portal_jpy
    if difference_bps > 200:
        raise ValueError("q2_minatoya_jpy_tolerance_invalid")
    proposals = [{"event_key_sha256": q2._sha(event["direct_event_key"].encode()),
                  "current_event_sha256": event["current_event_sha256"],
                  "current_source_sha256": event["current_source_sha256"],
                  "portal_record_sha256": q2._sha(q2._json(portal)), "account": "숙박비",
                  "cost_type": "여행원가", "vat_tag": "불공제_해외",
                  "trip_target": "1010_도쿠시마", "atomic_group_count": 2,
                  "booking_bijection_asserted": False, "jpy_difference_bps": difference_bps}
                 for event in matches]
    manifest = {"artifact_type": ARTIFACT_TYPE, "rule_version": RULE_VERSION,
                "selected_event_set_sha256": SELECTED_SET_SHA256,
                "full_classification_delta": 2, "accepted_union": 1560, "global_residual": 3768,
                "booking_bijection_asserted": False, "card_event_count": 2, "portal_booking_count": 1,
                "jpy_difference_bps": difference_bps, "jpy_tolerance_bps": 200,
                "authority_status": "unattested", "posting_status": "blocked",
                "database_applied": False, "contains_sensitive_raw_values": False}
    return manifest, proposals


def build_q2_minatoya_portal_admission(*, ledger_dir: Path = Path(REPOSITORY_ROOT) / "ledger") -> dict:
    manifest, proposals = _live(ledger_dir)
    return {"manifest": manifest, "proposals": proposals}
