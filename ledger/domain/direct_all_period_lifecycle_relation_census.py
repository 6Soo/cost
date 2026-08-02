"""Rebase exact issuer cancellation/refund relations onto the current residual.

Relations are preserved as evidence only.  They do not supply an account, trip,
VAT treatment, posting authority, or a full-classification delta.
"""
from __future__ import annotations

import csv
import io
import tempfile
from collections import Counter
from pathlib import Path

from ledger.domain import direct_manual_group_taxonomy_evidence as r36
from ledger.domain import direct_original_approval_relation as r40
from ledger.domain import direct_trip_cancel_lifecycle_evidence as r44
from ledger.domain import direct_all_period_residual_census as residual_census
from ledger.domain.direct_lineage_annex import REPOSITORY_ROOT

ARTIFACT_TYPE = "all-period-lifecycle-relation-census-v1"
RULE_VERSION = "p25-current-exact-original-approval-relation-v1"
EXPECTED_LINKED_SET_SHA256 = "f0b52d194ab335661052f011b5ad5650972d17d7ebcc1d0ed049e05a4270fdc4"


def build_all_period_lifecycle_relation_census(
        *, ledger_dir: Path = Path(REPOSITORY_ROOT) / "ledger") -> dict:
    if ledger_dir.resolve() != (Path(REPOSITORY_ROOT) / "ledger").resolve():
        raise ValueError("all_period_lifecycle_noncanonical_ledger")
    with tempfile.TemporaryDirectory(prefix="all-period-lifecycle-census-") as directory:
        context = r36._context(ledger_dir, Path(directory))
        try:
            universe = {event["direct_event_key"]: event for event in context["events"]}
        finally:
            context["db"].close()
    accepted_base, _ = r44._accepted_union(ledger_dir)
    accepted = accepted_base | residual_census._selected_additions(universe)
    residual = set(universe) - accepted
    if len(accepted) != 1560 or len(residual) != 3768:
        raise ValueError("all_period_lifecycle_current_state_drift")

    _manifest, files = r40._build(ledger_dir)
    relation_rows = list(csv.DictReader(io.StringIO(files["relations.csv"].decode())))
    hash_to_key = {r40._sha(key.encode()): key for key in universe}
    relations = []
    for row in relation_rows:
        event_key = hash_to_key[row["event_key_sha256"]]
        target_key = hash_to_key[row["target_event_key_sha256"]]
        if event_key in residual:
            relations.append((event_key, target_key))
    linked = {event_key for event_key, _target_key in relations}
    lifecycle = {key for key in residual if universe[key]["transaction_type"] in
                 {"cancellation", "refund"}}
    unlinked = lifecycle - linked
    linked_target_status = Counter(
        "accepted" if target_key in accepted else "residual"
        for _event_key, target_key in relations)
    linked_sources = Counter(universe[key]["source_system"] for key in linked)
    unlinked_sources = Counter(universe[key]["source_system"] for key in unlinked)
    unlinked_types = Counter(universe[key]["transaction_type"] for key in unlinked)
    actual = (len(lifecycle), len(linked), linked_target_status, linked_sources,
              len(unlinked), unlinked_sources, unlinked_types)
    expected = (377, 209, Counter({"residual": 187, "accepted": 22}),
                Counter({"KBD": 128, "HAN": 81}), 168,
                Counter({"KBO": 135, "KBD": 29, "CORP": 4}),
                Counter({"cancellation": 139, "refund": 29}))
    linked_sha256 = residual_census._setsha(linked)
    if actual != expected or linked_sha256 != EXPECTED_LINKED_SET_SHA256:
        raise ValueError(f"all_period_lifecycle_relation_census_drift:{linked_sha256}")
    return {"artifact_type": ARTIFACT_TYPE, "rule_version": RULE_VERSION,
            "lifecycle_residual_count": len(lifecycle),
            "exact_original_approval_linked_count": len(linked),
            "linked_event_set_sha256": linked_sha256,
            "linked_target_status_counts": dict(sorted(linked_target_status.items())),
            "linked_source_counts": dict(sorted(linked_sources.items())),
            "unlinked_count": len(unlinked),
            "unlinked_source_counts": dict(sorted(unlinked_sources.items())),
            "unlinked_transaction_type_counts": dict(sorted(unlinked_types.items())),
            "cross_year_exact_link_count": sum(
                universe[event_key]["occurred_on"][:4] != universe[target_key]["occurred_on"][:4]
                for event_key, target_key in relations),
            "relation_kind": "issuer_original_approval_exact",
            "relation_evidence_preserved": True,
            "full_classification_delta": 0, "database_applied": False,
            "posting_status": "blocked"}
