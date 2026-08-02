"""Rebuild the current all-period residual and its evidence partitions.

This module is census-only.  It does not classify, publish, or delete events.
"""
from __future__ import annotations

import csv
import io
import tempfile
from collections import Counter
from pathlib import Path

from ledger.domain import direct_agoda_customer_service_evidence as r49
from ledger.domain import direct_kb_confirmation_evidence as r45
from ledger.domain import direct_manual_group_taxonomy_evidence as r36
from ledger.domain import direct_merchant_taxonomy_support as r34
from ledger.domain import direct_trip_cancel_lifecycle_evidence as r44
from ledger.domain import direct_all_period_corp_void_admission as voids
from ledger.domain import direct_all_period_manual_duplicate_collapse_admission as duplicates
from ledger.domain import direct_all_period_remaining_cancellation_admission as cancellations
from ledger.domain import direct_all_period_safe_group_admission as safe
from ledger.domain.direct_lineage_annex import REPOSITORY_ROOT

ARTIFACT_TYPE = "all-period-residual-census-v1"
RULE_VERSION = "p25-current-evidence-partition-v1"
EXPECTED_RESIDUAL_SET_SHA256 = "1a259893425431595d63e3ab5891f66e8a4042056f0eab399c5500183d073b7d"
EXPECTED_COUNTS = {"accepted": 1560, "residual": 3768, "manual_frontier": 8,
                   "merchant_taxonomy_only": 241, "broad_no_direct_axes": 3519}


def _setsha(values: set[str]) -> str:
    return r36._event_set_sha(values)


def _selected_additions(universe: dict[str, dict]) -> set[str]:
    selected = set(r45.EVENTS) | {r49.TARGET_EVENT} | set(r44.EVENTS)
    selected |= safe._later_selected(universe)
    for group in safe.GROUPS:
        source, date, amount, card4, merchant, count, *_ = group
        matches = {key for key, event in universe.items() if
                   (event["source_system"], event["occurred_on"],
                    int(event["signed_amount_krw"]), event["card4"], event["merchant"],
                    event["transaction_type"], event["event_role"]) ==
                   (source, date, amount, card4, merchant, "purchase", "single")}
        if len(matches) != count:
            raise ValueError("all_period_census_safe_group_drift")
        selected |= matches
    selected |= {key for key, event in universe.items()
                 if voids._digits(event.get("approval_number")) in voids.TARGETS
                 and event.get("source_system") == "CORP"}
    selected |= {cancellations.HAN_CANCEL_KEY} | cancellations.KBO_REFUND_KEYS
    for source, date, amount, card4, merchant, *_ in duplicates.TARGETS:
        matches = {key for key, event in universe.items() if
                   (event["source_system"], event["occurred_on"],
                    int(event["signed_amount_krw"]), event["card4"], event["merchant"],
                    event["transaction_type"], event["event_role"]) ==
                   (source, date, amount, card4, merchant, "purchase", "single")}
        if len(matches) != 1:
            raise ValueError("all_period_census_duplicate_group_drift")
        selected |= matches
    portal_signatures = (
        ("KBO", "2026-05-26", 1150385, "118800", "JPY", "8835", "AGODA.COM YAKUSHIMA"),
        ("KBO", "2026-06-26", 116935, "11885", "JPY", "8835", "AGODA.COM"),
    )
    for signature in portal_signatures:
        matches = {key for key, event in universe.items() if
                   (event["source_system"], event["occurred_on"],
                    int(event["signed_amount_krw"]), event["foreign_amount"],
                    event["currency"], event["card4"], event["merchant"]) == signature}
        if len(matches) != 2:
            raise ValueError("all_period_census_portal_group_drift")
        selected |= matches
    if len(selected) != 32:
        raise ValueError("all_period_census_addition_count_drift")
    return selected


def _counter(events: list[dict], field: str) -> dict[str, int]:
    return dict(sorted(Counter(str(event[field]) for event in events).items()))


def build_all_period_residual_census(
        *, ledger_dir: Path = Path(REPOSITORY_ROOT) / "ledger") -> dict:
    if ledger_dir.resolve() != (Path(REPOSITORY_ROOT) / "ledger").resolve():
        raise ValueError("all_period_census_noncanonical_ledger")
    with tempfile.TemporaryDirectory(prefix="all-period-residual-census-") as directory:
        context = r36._context(ledger_dir, Path(directory))
        try:
            universe = {event["direct_event_key"]: event for event in context["events"]}
            current_event_set_sha256 = context["current_event_set_sha256"]
            decision_scope_sha256 = context["decision_scope_sha256"]
        finally:
            context["db"].close()
    if len(universe) != 5328:
        raise ValueError("all_period_census_universe_drift")
    accepted_base, _ = r44._accepted_union(ledger_dir)
    additions = _selected_additions(universe)
    if len(accepted_base) != 1528 or accepted_base & additions:
        raise ValueError("all_period_census_accepted_overlap")
    accepted = accepted_base | additions
    residual = set(universe) - accepted
    if len(residual) != 3768 or _setsha(residual) != EXPECTED_RESIDUAL_SET_SHA256:
        raise ValueError("all_period_census_residual_drift")

    _manifest36, files36 = r36._build(ledger_dir, r36.DEFAULT_MANUAL_CSV)
    manual_frontier = {row["direct_event_key"] for row in csv.DictReader(
        io.StringIO(files36["bucket_support.csv"].decode()))} & residual
    _manifest34, files34 = r34._build(ledger_dir, r36.DEFAULT_MANUAL_CSV)
    taxonomy_rows = list(csv.DictReader(io.StringIO(files34["proposals.csv"].decode())))
    taxonomy_by_event = {row["direct_event_key"]: row for row in taxonomy_rows}
    merchant_taxonomy = set(taxonomy_by_event) & residual
    broad = residual - manual_frontier - merchant_taxonomy
    actual = {"accepted": len(accepted), "residual": len(residual),
              "manual_frontier": len(manual_frontier),
              "merchant_taxonomy_only": len(merchant_taxonomy),
              "broad_no_direct_axes": len(broad)}
    if actual != EXPECTED_COUNTS or manual_frontier & merchant_taxonomy:
        raise ValueError("all_period_census_partition_drift")

    axes = Counter((taxonomy_by_event[key]["account"], taxonomy_by_event[key]["cost_type"],
                    taxonomy_by_event[key]["vat_tag"] or "<missing>")
                   for key in merchant_taxonomy)
    axis_counts = [{"account": axis[0], "cost_type": axis[1], "vat_tag": axis[2], "count": count}
                   for axis, count in sorted(axes.items(), key=lambda item: (-item[1], item[0]))]
    partition_sets = {"manual_frontier": manual_frontier,
                      "merchant_taxonomy_only": merchant_taxonomy,
                      "broad_no_direct_axes": broad}
    partitions = {}
    for name, keys in partition_sets.items():
        events = [universe[key] for key in keys]
        partitions[name] = {"count": len(keys), "set_sha256": _setsha(keys),
                            "source_counts": _counter(events, "source_system"),
                            "transaction_type_counts": _counter(events, "transaction_type"),
                            "year_counts": dict(sorted(Counter(
                                event["occurred_on"][:4] for event in events).items()))}
    return {"artifact_type": ARTIFACT_TYPE, "rule_version": RULE_VERSION,
            "event_count": len(universe), "accepted_count": len(accepted),
            "residual_count": len(residual), "residual_set_sha256": _setsha(residual),
            "excluded_by_period_count": 0, "partition_counts": actual,
            "partitions": partitions, "merchant_taxonomy_axis_counts": axis_counts,
            "merchant_taxonomy_bucket_missing_count": len(merchant_taxonomy),
            "current_event_set_sha256": current_event_set_sha256,
            "decision_scope_sha256": decision_scope_sha256,
            "database_applied": False, "posting_status": "blocked"}
