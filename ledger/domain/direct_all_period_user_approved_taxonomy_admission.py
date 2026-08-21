"""Retain the prior user-taxonomy subset as candidate hints.

These hints do not confirm any axis.  VAT is excluded from the active contract,
and no trip, posting, deletion, or identity change is authorized.
"""
from __future__ import annotations

import csv
import io
import tempfile
from collections import Counter
from pathlib import Path

from ledger.domain import direct_all_period_residual_census as census
from ledger.domain import direct_manual_group_taxonomy_evidence as r36
from ledger.domain import direct_merchant_taxonomy_support as taxonomy
from ledger.domain.direct_lineage_annex import REPOSITORY_ROOT


ARTIFACT_TYPE = "all-period-user-approved-taxonomy-admission-v1"
RULE_VERSION = "user-approval-2026-08-03-partial-taxonomy-no-trip-v1"
EXPECTED_SELECTED_COUNT = 116
EXPECTED_AXIS_COUNTS = {
    ("숙박비", "여행원가"): 38,
    ("여행자보험", "여행원가"): 36,
    ("교통비", "여행원가"): 19,
    ("주유비", "여행원가"): 11,
    ("통행료", "여행원가"): 9,
    ("렌터카", "여행원가"): 3,
}


def build_user_approved_taxonomy_admission(
    *, ledger_dir: Path = Path(REPOSITORY_ROOT) / "ledger"
) -> dict:
    manifest, files = taxonomy._build(ledger_dir, taxonomy.DEFAULT_MANUAL_CSV)
    rows = list(csv.DictReader(io.StringIO(files["proposals.csv"].decode())))
    with tempfile.TemporaryDirectory(prefix="user-approved-taxonomy-") as directory:
        context = r36._context(ledger_dir, Path(directory))
        try:
            universe = {event["direct_event_key"]: event for event in context["events"]}
        finally:
            context["db"].close()
    if len(universe) != 5328:
        raise ValueError("user_taxonomy_universe_drift")
    already_admitted = census._selected_additions(universe)
    _r36_manifest, r36_files = r36._build(ledger_dir, r36.DEFAULT_MANUAL_CSV)
    already_admitted |= {
        row["direct_event_key"] for row in csv.DictReader(
            io.StringIO(r36_files["classifications.csv"].decode()))
    }
    selected = [
        row for row in rows
        if row["direct_event_key"] not in already_admitted
        and row["account"] != "식비" and bool(row["vat_tag"])
    ]
    axes = Counter(
        (row["account"], row["cost_type"])
        for row in selected
    )
    if len(selected) != EXPECTED_SELECTED_COUNT or dict(axes) != EXPECTED_AXIS_COUNTS:
        raise ValueError(f"user_taxonomy_selected_set_drift:{len(selected)}:{dict(axes)}")
    selected_keys = {row["direct_event_key"] for row in selected}
    if len(selected_keys) != EXPECTED_SELECTED_COUNT:
        raise ValueError("user_taxonomy_selected_key_duplicate")
    return {
        "manifest": {
            "artifact_type": ARTIFACT_TYPE,
            "rule_version": RULE_VERSION,
            "source_taxonomy_package_set_sha256": manifest["package_set_sha256"],
            "source_residual_set_sha256": census.EXPECTED_RESIDUAL_SET_SHA256,
            "selected_event_set_sha256": taxonomy._event_set_sha(selected_keys),
            "selected_count": EXPECTED_SELECTED_COUNT,
            "candidate_axis_count": EXPECTED_SELECTED_COUNT * 2,
            "axis_counts": [
                {"account": key[0], "cost_type": key[1], "count": count}
                for key, count in sorted(axes.items())
            ],
            "excluded_ambiguous_count": 125,
            "excluded_reasons": {"convenience_store_multi_purpose": 124,
                                 "klook_product_and_vat_unresolved": 1},
            "trip_assignment_count": 0,
            "full_classification_delta": 0,
            "posting_status": "blocked",
            "database_applied": False,
            "authority_status": "candidate_only", "gate5_credit": 0,
            "excluded_dimensions": ["vat_tag"],
            "all_source_events_retained": True,
        },
        "candidates": [
            {"direct_event_key": row["direct_event_key"],
             "current_event_sha256": row["current_event_sha256"],
             "account": row["account"], "cost_type": row["cost_type"],
             "trip_target": None,
             "candidate_status": "withheld_pending_independent_evidence",
             "posting_status": "blocked"}
            for row in sorted(selected, key=lambda item: item["direct_event_key"])
        ],
    }
