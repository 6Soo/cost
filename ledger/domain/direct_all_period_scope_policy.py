"""Enforce the user-owned all-period, lossless direct-event scope policy."""
from __future__ import annotations

import hashlib
import json
import tempfile
from collections import Counter
from pathlib import Path

from ledger.domain import direct_manual_group_taxonomy_evidence as r36
from ledger.domain import direct_all_period_minatoya_portal_admission as minatoya
from ledger.domain import direct_all_period_manual_frontier_lodging_admission as frontier_lodging
from ledger.domain import direct_all_period_manual_frontier_agoda_airfare_admission as frontier_airfare
from ledger.domain.direct_lineage_annex import REPOSITORY_ROOT

ARTIFACT_TYPE = "all-period-lossless-scope-policy-v1"
RULE_VERSION = "p25-all-period-no-quarter-exclusion-v1"
EXPECTED_PERIOD_COUNTS = {
    "2025-Q2": 25, "2025-Q3": 922, "2025-Q4": 1383,
    "2026-Q1": 1322, "2026-Q2": 1401, "2026-Q3": 275,
}


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _quarter(date: str) -> str:
    year, month = map(int, date[:7].split("-"))
    return f"{year}-Q{(month - 1) // 3 + 1}"


def build_all_period_scope_policy(*, ledger_dir: Path = Path(REPOSITORY_ROOT) / "ledger") -> dict:
    if ledger_dir.resolve() != (Path(REPOSITORY_ROOT) / "ledger").resolve():
        raise ValueError("all_period_noncanonical_ledger")
    upstream = minatoya.build_all_period_minatoya_portal_admission(ledger_dir=ledger_dir)["manifest"]
    if (upstream["accepted_union"], upstream["global_residual"],
            upstream["selected_event_set_sha256"]) != (1560, 3768, minatoya.SELECTED_SET_SHA256):
        raise ValueError("all_period_upstream_invalid")
    frontier = frontier_lodging.build_manual_frontier_lodging_admission(
        ledger_dir=ledger_dir)["manifest"]
    if (frontier["selected_count"], frontier["selected_event_set_sha256"]) != (
            6, frontier_lodging.SELECTED_SET_SHA256):
        raise ValueError("all_period_frontier_lodging_upstream_invalid")
    airfare = frontier_airfare.build_manual_frontier_agoda_airfare_admission(
        ledger_dir=ledger_dir)["manifest"]
    if (airfare["selected_count"], airfare["selected_event_set_sha256"]) != (
            2, frontier_airfare.SELECTED_SET_SHA256):
        raise ValueError("all_period_frontier_airfare_upstream_invalid")
    with tempfile.TemporaryDirectory(prefix="all-period-") as directory:
        context = r36._context(ledger_dir, Path(directory))
        try:
            events = list(context["events"])
            event_set_sha256 = context["current_event_set_sha256"]
            decision_scope_sha256 = context["decision_scope_sha256"]
        finally:
            context["db"].close()
    keys = [event["direct_event_key"] for event in events]
    periods = dict(sorted(Counter(_quarter(event["occurred_on"]) for event in events).items()))
    if len(events) != 5328 or len(set(keys)) != 5328 or periods != EXPECTED_PERIOD_COUNTS:
        raise ValueError("all_period_complete_scope_invalid")
    if sum(periods.values()) != len(events):
        raise ValueError("all_period_partition_invalid")
    contract = {"policy": "all periods retained; quarter is reporting metadata only",
                "event_count": len(events), "period_counts": periods,
                "excluded_by_period_count": 0, "quarter_filter_allowed": False,
                "delete_unclassified_allowed": False,
                "cross_period_relation_retention_required": True}
    return {**contract, "artifact_type": ARTIFACT_TYPE, "rule_version": RULE_VERSION,
            "policy_sha256": _sha((json.dumps(contract, ensure_ascii=False, sort_keys=True,
                separators=(",", ":")) + "\n").encode()),
            "current_event_set_sha256": event_set_sha256,
            "decision_scope_sha256": decision_scope_sha256,
            "accepted_union": 1568, "global_residual": 3760,
            "database_applied": False, "posting_status": "blocked"}
