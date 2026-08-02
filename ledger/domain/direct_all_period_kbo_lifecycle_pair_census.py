"""Census exact KBO foreign-amount cancellation groups in the current residual."""
from __future__ import annotations

import tempfile
from collections import Counter, defaultdict
from pathlib import Path

from ledger.domain import direct_manual_group_taxonomy_evidence as r36
from ledger.domain import direct_trip_cancel_lifecycle_evidence as r44
from ledger.domain import direct_all_period_residual_census as residual_census
from ledger.domain.direct_lineage_annex import REPOSITORY_ROOT

ARTIFACT_TYPE = "all-period-kbo-lifecycle-pair-census-v1"
RULE_VERSION = "p25-kbo-card-currency-foreign-merchant-consumptive-group-v1"
EXPECTED_SELECTED_SET_SHA256 = "75dfdaf66934d87d46892f2ecc962dc698108d180e9d688e2a84e088e344b800"


def _group_key(event: dict) -> tuple[str, str, str, str]:
    return (str(event["card4"]), str(event["currency"]),
            str(event["foreign_amount"]).lstrip("-"), str(event["merchant"]))


def build_all_period_kbo_lifecycle_pair_census(
        *, ledger_dir: Path = Path(REPOSITORY_ROOT) / "ledger") -> dict:
    if ledger_dir.resolve() != (Path(REPOSITORY_ROOT) / "ledger").resolve():
        raise ValueError("all_period_kbo_pair_noncanonical_ledger")
    with tempfile.TemporaryDirectory(prefix="all-period-kbo-pair-census-") as directory:
        context = r36._context(ledger_dir, Path(directory))
        try:
            universe = {event["direct_event_key"]: event for event in context["events"]}
        finally:
            context["db"].close()
    accepted_base, _ = r44._accepted_union(ledger_dir)
    accepted = accepted_base | residual_census._selected_additions(universe)
    residual = set(universe) - accepted
    cancellations = [universe[key] for key in residual
                     if universe[key]["source_system"] == "KBO"
                     and universe[key]["transaction_type"] in {"cancellation", "refund"}]
    purchases = [event for event in universe.values()
                 if event["source_system"] == "KBO" and event["transaction_type"] == "purchase"]
    cancellation_groups: dict[tuple, list[dict]] = defaultdict(list)
    purchase_groups: dict[tuple, list[dict]] = defaultdict(list)
    for event in cancellations:
        cancellation_groups[_group_key(event)].append(event)
    for event in purchases:
        purchase_groups[_group_key(event)].append(event)

    cardinalities = Counter()
    selected = set()
    singleton_groups = 0
    unordered_groups = 0
    for key, cancellation_rows in cancellation_groups.items():
        purchase_rows = purchase_groups[key]
        cardinalities[(len(cancellation_rows), len(purchase_rows))] += 1
        if len(cancellation_rows) != len(purchase_rows) or not purchase_rows:
            continue
        if max(row["occurred_on"] for row in purchase_rows) > min(
                row["occurred_on"] for row in cancellation_rows):
            raise ValueError("all_period_kbo_pair_date_order_invalid")
        selected |= {row["direct_event_key"] for row in cancellation_rows}
        if len(cancellation_rows) == 1:
            singleton_groups += 1
        else:
            unordered_groups += 1
    selected_sha256 = residual_census._setsha(selected)
    expected_cardinalities = Counter({(1, 1): 44, (1, 0): 18, (1, 2): 4,
                                     (2, 2): 3, (3, 3): 1, (3, 9): 1,
                                     (4, 0): 1, (9, 9): 1, (11, 2): 1,
                                     (16, 1): 1, (17, 1): 1})
    if (len(cancellations), len(selected), singleton_groups, unordered_groups,
            cardinalities) != (135, 62, 44, 5, expected_cardinalities):
        raise ValueError("all_period_kbo_pair_census_drift")
    if selected_sha256 != EXPECTED_SELECTED_SET_SHA256:
        raise ValueError(f"all_period_kbo_pair_selected_set_drift:{selected_sha256}")
    return {"artifact_type": ARTIFACT_TYPE, "rule_version": RULE_VERSION,
            "kbo_lifecycle_residual_count": len(cancellations),
            "exact_group_linked_event_count": len(selected),
            "exact_singleton_relation_count": singleton_groups,
            "unordered_atomic_group_count": unordered_groups,
            "unlinked_or_cardinality_conflict_count": len(cancellations) - len(selected),
            "selected_event_set_sha256": selected_sha256,
            "individual_bijection_count": singleton_groups,
            "multi_event_bijection_asserted": False,
            "relation_evidence_preserved": True,
            "full_classification_delta": 0, "database_applied": False,
            "posting_status": "blocked"}
