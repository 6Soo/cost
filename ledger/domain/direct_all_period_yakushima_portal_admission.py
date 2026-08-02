"""Admit two Yakushima charges using repository-preserved authenticated portal evidence."""
from __future__ import annotations

import hashlib
import json
import subprocess
import tempfile
from pathlib import Path

from ledger.domain import direct_manual_group_taxonomy_evidence as r36
from ledger.domain import direct_all_period_manual_duplicate_collapse_admission as duplicate
from ledger.domain import direct_all_period_safe_group_admission as base
from ledger.domain.direct_lineage_annex import REPOSITORY_ROOT

ARTIFACT_TYPE = "all-period-yakushima-authenticated-portal-group-v1"
RULE_VERSION = "all-period-git-preserved-portal-card-multiset-v1"
PORTAL_COMMIT = "61ea7b9"
PORTAL_PATH = "ledger/data/agoda_direct_browser_evidence.json"
PORTAL_FILE_SHA256 = "de9ce5264ee608b6fc1bede2d179c343385120ae13e74fb07fb0354cc9c88cf2"
SELECTED_SET_SHA256 = "5751262cd691a9339a215d32418fd4f7dcc7e070828223f8dee8aa3eb093b822"
BOOKING = "662897867"


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _portal(repo: Path = Path(REPOSITORY_ROOT)) -> dict:
    try:
        result = subprocess.run(["git", "show", f"{PORTAL_COMMIT}:{PORTAL_PATH}"], cwd=repo,
                                check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=10)
    except (OSError, subprocess.SubprocessError) as exc:
        raise ValueError("all_period_yakushima_portal_object_unavailable") from exc
    if _sha(result.stdout) != PORTAL_FILE_SHA256:
        raise ValueError("all_period_yakushima_portal_file_pin_invalid")
    try:
        records = json.loads(result.stdout)["records"]
    except (KeyError, TypeError, json.JSONDecodeError) as exc:
        raise ValueError("all_period_yakushima_portal_schema_invalid") from exc
    matches = [row for row in records if row.get("booking_number") == BOOKING]
    if len(matches) != 1:
        raise ValueError("all_period_yakushima_portal_cardinality_invalid")
    row = matches[0]
    expected = {"card_last4": "8835", "currency": "JPY", "foreign_amount": "118800",
                "provider": "agoda", "service_start_on": "2026-11-27",
                "service_end_on": "2026-11-30", "source_channel": "authenticated_booking_portal",
                "status": "confirmed"}
    if any(row.get(key) != value for key, value in expected.items()) or row.get("extraction_sources") != ["authenticated_portal_dom"]:
        raise ValueError("all_period_yakushima_portal_fact_invalid")
    return row


def _live(ledger_dir: Path = Path(REPOSITORY_ROOT) / "ledger") -> tuple[dict, list[dict]]:
    upstream = duplicate.build_all_period_manual_duplicate_collapse_admission(ledger_dir=ledger_dir)["manifest"]
    if (upstream["accepted_union"], upstream["global_residual"],
            upstream["selected_event_set_sha256"]) != (1556, 3772, duplicate.SELECTED_SET_SHA256):
        raise ValueError("all_period_yakushima_upstream_invalid")
    portal = _portal()
    with tempfile.TemporaryDirectory(prefix="all-period-yakushima-") as directory:
        context = r36._context(ledger_dir, Path(directory))
        try:
            events = list(context["events"])
        finally:
            context["db"].close()
    matches = [event for event in events if
               (event["source_system"], event["occurred_on"], int(event["signed_amount_krw"]),
                event["foreign_amount"], event["currency"], event["card4"], event["merchant"],
                event["transaction_type"], event["event_role"]) ==
               ("KBO", "2026-05-26", 1150385, "118800", "JPY", "8835",
                "AGODA.COM YAKUSHIMA", "purchase", "single")]
    keys = {event["direct_event_key"] for event in matches}
    if len(matches) != 2 or len({event["current_source_key"] for event in matches}) != 2 or base._setsha(keys) != SELECTED_SET_SHA256:
        raise ValueError("all_period_yakushima_current_group_invalid")
    portal_sha = _sha(base._json(portal))
    proposals = [{"event_key_sha256": _sha(event["direct_event_key"].encode()),
                  "current_event_sha256": event["current_event_sha256"],
                  "current_source_sha256": event["current_source_sha256"],
                  "portal_record_sha256": portal_sha, "account": "숙박비",
                  "cost_type": "여행원가", "vat_tag": "불공제_해외",
                  "trip_target": "1127_야쿠시마", "atomic_group_count": 2,
                  "booking_bijection_asserted": False} for event in matches]
    manifest = {"artifact_type": ARTIFACT_TYPE, "rule_version": RULE_VERSION,
                "selected_event_set_sha256": SELECTED_SET_SHA256,
                "full_classification_delta": 2, "accepted_union": 1558, "global_residual": 3770,
                "portal_commit": PORTAL_COMMIT, "portal_file_sha256": PORTAL_FILE_SHA256,
                "booking_bijection_asserted": False, "card_event_count": 2, "portal_booking_count": 1,
                "authority_status": "unattested", "posting_status": "blocked",
                "database_applied": False, "contains_sensitive_raw_values": False}
    return manifest, proposals


def build_all_period_yakushima_portal_admission(*, ledger_dir: Path = Path(REPOSITORY_ROOT) / "ledger") -> dict:
    manifest, proposals = _live(ledger_dir)
    return {"manifest": manifest, "proposals": proposals}
