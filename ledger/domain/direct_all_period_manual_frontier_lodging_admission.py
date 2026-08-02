"""Admit six manual-frontier lodging payments with exact live bindings."""
from __future__ import annotations

import csv
import hashlib
import tempfile
from pathlib import Path

from ledger.domain import direct_manual_group_taxonomy_evidence as r36
from ledger.domain.direct_lineage_annex import REPOSITORY_ROOT


ARTIFACT_TYPE = "all-period-manual-frontier-lodging-admission-v1"
RULE_VERSION = "manual-card-exact-lodging-group-v1"
MANUAL_PATH = Path(REPOSITORY_ROOT) / "ledger/data/manual_v4.csv"
MANUAL_SHA256 = "80bd2fbae815e51f286a5bca2639d14971abbcc88fc2e9e4ece8b5ae3ee165a6"
SELECTED_SET_SHA256 = "627c152c2f018a8d65379cbb31c1f7dc1a03546ed40ab39f8fccb163ac807eef"
GROUPS = (
    ("KBD", "2025-11-29", 357076, "4886", "AGODA_NICE-Agoda", 2,
     "0616_레분토&리시리", "아고다_Kitaguni Grand Hotel", "숙박"),
    ("KBD", "2025-11-29", 394663, "4886", "AGODA_NICE-Agoda", 2,
     "0616_레분토&리시리", "아고다_기타구니", "숙박"),
    ("HAN", "2026-02-24", 115097, "6741", "트립닷컴(ARS)_나이스", 2,
     "0924_야마구치", "트립닷컴_이즈미야 로캰 나가토", "숙박_0926_0927"),
)


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _setsha(values: set[str]) -> str:
    return r36._event_set_sha(values)


def build_manual_frontier_lodging_admission(
        *, ledger_dir: Path = Path(REPOSITORY_ROOT) / "ledger") -> dict:
    if ledger_dir.resolve() != (Path(REPOSITORY_ROOT) / "ledger").resolve():
        raise ValueError("manual_frontier_lodging_noncanonical_ledger")
    raw = MANUAL_PATH.read_bytes()
    if _sha(raw) != MANUAL_SHA256:
        raise ValueError("manual_frontier_lodging_manual_drift")
    manual = list(csv.DictReader(raw.decode().splitlines()))
    with tempfile.TemporaryDirectory(prefix="manual-frontier-lodging-") as directory:
        context = r36._context(ledger_dir, Path(directory))
        try:
            events = list(context["events"])
            current_event_set_sha256 = context["current_event_set_sha256"]
            decision_scope_sha256 = context["decision_scope_sha256"]
        finally:
            context["db"].close()
    selected: list[dict] = []
    for source, date, amount, card4, merchant, count, bucket, item, desc in GROUPS:
        manual_rows = [row for row in manual if
                       (row["tab"], row["date"], row["item"], row["desc"],
                        row["card"], int(float(row["amount"]))) ==
                       (bucket, date[2:].replace("-", "."), item, desc,
                        "국민" if source == "KBD" else "하나", amount)]
        matches = [event for event in events if
                   (event["source_system"], event["occurred_on"],
                    int(event["signed_amount_krw"]), event["card4"], event["merchant"],
                    event["transaction_type"], event["event_role"]) ==
                   (source, date, amount, card4, merchant, "purchase", "single")]
        if len(manual_rows) != count or len(matches) != count:
            raise ValueError("manual_frontier_lodging_group_cardinality_drift")
        manual_group_sha = _sha(("\n".join(sorted(
            ",".join(row[field] for field in ("tab", "row", "date", "item", "desc", "card", "amount", "book"))
            for row in manual_rows)) + "\n").encode())
        for event in matches:
            selected.append({
                "direct_event_key": event["direct_event_key"],
                "current_event_sha256": event["current_event_sha256"],
                "current_source_sha256": event["current_source_sha256"],
                "manual_group_sha256": manual_group_sha,
                "account": "숙박비", "cost_type": "여행원가",
                "vat_tag": "불공제_해외", "trip_target": bucket,
                "decision_status": "confirmed", "posting_status": "blocked",
            })
    keys = {row["direct_event_key"] for row in selected}
    if len(selected) != 6 or len(keys) != 6 or _setsha(keys) != SELECTED_SET_SHA256:
        raise ValueError("manual_frontier_lodging_selected_set_drift")
    return {
        "manifest": {
            "artifact_type": ARTIFACT_TYPE, "rule_version": RULE_VERSION,
            "selected_event_set_sha256": SELECTED_SET_SHA256,
            "selected_count": 6, "axis_decision_count": 24,
            "deferred_ambiguous_count": 2,
            "deferred_reason": "agoda_merchant_conflicts_with_manual_airfare_description",
            "current_event_set_sha256": current_event_set_sha256,
            "decision_scope_sha256": decision_scope_sha256,
            "manual_sha256": MANUAL_SHA256, "posting_status": "blocked",
            "database_applied": False, "all_source_events_retained": True,
        },
        "decisions": sorted(selected, key=lambda row: row["direct_event_key"]),
    }
