"""All-period admission for exact latest-manual/current-card multiset groups."""
from __future__ import annotations

import hashlib
import tempfile
from pathlib import Path

from ledger.domain import direct_all_period_safe_group_admission as source
from ledger.domain import direct_manual_group_taxonomy_evidence as r36
from ledger.domain.direct_lineage_annex import REPOSITORY_ROOT


ARTIFACT_TYPE = "all-period-exact-manual-card-group-admission-v1"
RULE_VERSION = "p25-exact-current-card-latest-manual-multiset-v1"
SELECTED_SET_SHA256 = source.SELECTED_SET_SHA256
EXPECTED_PAYMENT_COUNT = 5
EXPECTED_CANDIDATE_AXIS_COUNT = 15


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def build_exact_manual_group_admission(
        *, ledger_dir: Path = Path(REPOSITORY_ROOT) / "ledger") -> dict:
    if ledger_dir.resolve() != (Path(REPOSITORY_ROOT) / "ledger").resolve():
        raise ValueError("exact_manual_group_noncanonical_ledger")
    manual = source._manual_groups()
    with tempfile.TemporaryDirectory(prefix="all-period-exact-manual-group-") as directory:
        context = r36._context(ledger_dir, Path(directory))
        try:
            events = list(context["events"])
            current_event_set_sha256 = context["current_event_set_sha256"]
            decision_scope_sha256 = context["decision_scope_sha256"]
        finally:
            context["db"].close()
    universe = {event["direct_event_key"]: event for event in events}
    if len(universe) != 5328:
        raise ValueError("exact_manual_group_current_census_invalid")
    selected: set[str] = set()
    proposals: list[dict[str, object]] = []
    for group in source.GROUPS:
        source_name, occurred_on, amount, card4, merchant, count, tab, _item, account, cost_type, vat = group
        matches = {
            key for key, event in universe.items()
            if (event["source_system"], event["occurred_on"], int(event["signed_amount_krw"]),
                event["card4"], event["merchant"], event["transaction_type"], event["event_role"])
            == (source_name, occurred_on, amount, card4, merchant, "purchase", "single")
        }
        if len(matches) != count:
            raise ValueError("exact_manual_group_current_cardinality_invalid")
        selected |= matches
        manual_rows = manual[group[:6]]
        if len(manual_rows) != count:
            raise ValueError("exact_manual_group_manual_cardinality_invalid")
        manual_sha = _sha(("\n".join(sorted(
            ",".join(row[field] for field in ("tab", "row", "date", "item", "desc", "card", "amount", "book"))
            for row in manual_rows)) + "\n").encode())
        group_sha = _sha((f"{source_name}|{occurred_on}|{amount}|{card4}|{merchant}|{count}|{tab}|{manual_sha}").encode())
        for key in sorted(matches):
            event = universe[key]
            proposals.append({
                "event_key_sha256": _sha(key.encode()),
                "direct_event_key": key,
                "current_event_sha256": event["current_event_sha256"],
                "current_source_sha256": event["current_source_sha256"],
                "manual_group_sha256": manual_sha,
                "group_sha256": group_sha,
                "account": account, "cost_type": cost_type,
                "trip_target": tab,
                "candidate_status": "withheld_pending_independent_evidence",
            })
    if len(selected) != EXPECTED_PAYMENT_COUNT or r36._event_set_sha(selected) != SELECTED_SET_SHA256:
        raise ValueError("exact_manual_group_selected_set_invalid")
    return {
        "manifest": {
            "artifact_type": ARTIFACT_TYPE, "rule_version": RULE_VERSION,
            "selected_event_set_sha256": SELECTED_SET_SHA256,
            "selected_count": EXPECTED_PAYMENT_COUNT,
            "candidate_axis_count": EXPECTED_CANDIDATE_AXIS_COUNT,
            "manual_sha256": source.MANUAL_SHA256,
            "current_event_set_sha256": current_event_set_sha256,
            "decision_scope_sha256": decision_scope_sha256,
            "authority_status": "candidate_only", "gate5_credit": 0,
            "excluded_dimensions": ["vat_tag"],
            "posting_status": "blocked", "database_applied": False,
            "all_source_events_retained": True,
        },
        "proposals": sorted(proposals, key=lambda row: str(row["direct_event_key"])),
    }
