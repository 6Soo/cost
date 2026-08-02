"""Admit the final two manual-frontier Agoda airfare payments as one group."""
from __future__ import annotations

import csv
import hashlib
import json
import tempfile
from pathlib import Path

from ledger.domain import direct_manual_group_taxonomy_evidence as r36
from ledger.domain.direct_lineage_annex import REPOSITORY_ROOT


ARTIFACT_TYPE = "all-period-manual-frontier-agoda-airfare-admission-v1"
RULE_VERSION = "manual-card-ota-mail-airfare-atomic-group-v1"
MANUAL_PATH = Path(REPOSITORY_ROOT) / "ledger/data/manual_v4.csv"
MANUAL_SHA256 = "80bd2fbae815e51f286a5bca2639d14971abbcc88fc2e9e4ece8b5ae3ee165a6"
OTA_PATH = Path(REPOSITORY_ROOT) / "ledger/data/ota_mail_index.json"
OTA_SHA256 = "db258948ff2240b682d579422c4de3edbc5079e6425a8fd7c0a224f57c40cb11"
SELECTED_SET_SHA256 = "cb644e7fa0c44abad2c2e58dd0e659b62d1d362234bb722682965a69ad3d8a41"
MESSAGE_HASHES = {
    "c28f665692d3458ca9f1cbacfaa377ebd075b8511b2f8de8539292fe64bb2f1a",
    "4ec4bd14569b714c2c5a0b521ba5d9e5a26f214200b1e12f12545fca539f2729",
}


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def build_manual_frontier_agoda_airfare_admission(
        *, ledger_dir: Path = Path(REPOSITORY_ROOT) / "ledger") -> dict:
    if ledger_dir.resolve() != (Path(REPOSITORY_ROOT) / "ledger").resolve():
        raise ValueError("manual_frontier_airfare_noncanonical_ledger")
    manual_raw = MANUAL_PATH.read_bytes(); ota_raw = OTA_PATH.read_bytes()
    if _sha(manual_raw) != MANUAL_SHA256 or _sha(ota_raw) != OTA_SHA256:
        raise ValueError("manual_frontier_airfare_input_drift")
    manual = list(csv.DictReader(manual_raw.decode().splitlines()))
    manual_rows = [row for row in manual if
                   (row["tab"], row["date"], row["item"], row["card"],
                    int(float(row["amount"]))) ==
                   ("0924_야마구치", "26.02.20", "아고다_후쿠오카", "국민", 542370)
                   and row["desc"].startswith("항공_0924_0927_")]
    if len(manual_rows) != 2 or {row["desc"].removeprefix("항공_0924_0927_")
                                 for row in manual_rows} != {"정용숙", "박희경"}:
        raise ValueError("manual_frontier_airfare_manual_group_drift")
    messages = [row for row in json.loads(ota_raw).get("records", [])
                if row.get("messageHash") in MESSAGE_HASHES]
    expected_subjects = {"9/24~27 인천-후쿠오카 왕복 예약정보 -박희경",
                         "9/24~27 인천-후쿠오카 왕복 예약정보 -정용숙"}
    if (len(messages) != 2 or {row.get("subject") for row in messages} != expected_subjects
            or {row.get("provider") for row in messages} != {"agoda"}
            or {tuple(row.get("travelDates", [])) for row in messages} != {("0220", "0924", "0927")}
            or len({tuple(row.get("pnrs", [])) for row in messages}) != 2):
        raise ValueError("manual_frontier_airfare_ota_group_drift")
    with tempfile.TemporaryDirectory(prefix="manual-frontier-airfare-") as directory:
        context = r36._context(ledger_dir, Path(directory))
        try:
            matches = [event for event in context["events"] if
                       (event["source_system"], event["occurred_on"],
                        int(event["signed_amount_krw"]), event["card4"], event["merchant"],
                        event["transaction_type"], event["event_role"]) ==
                       ("KBD", "2026-02-20", 542370, "4886", "AGODA_NICE-Agoda",
                        "purchase", "single")]
            current_event_set_sha256 = context["current_event_set_sha256"]
            decision_scope_sha256 = context["decision_scope_sha256"]
        finally:
            context["db"].close()
    keys = {event["direct_event_key"] for event in matches}
    if len(matches) != 2 or r36._event_set_sha(keys) != SELECTED_SET_SHA256:
        raise ValueError("manual_frontier_airfare_card_group_drift")
    evidence_sha = _sha(("\n".join(sorted(MESSAGE_HASHES)) + "\n").encode())
    decisions = [{
        "direct_event_key": event["direct_event_key"],
        "current_event_sha256": event["current_event_sha256"],
        "current_source_sha256": event["current_source_sha256"],
        "ota_message_group_sha256": evidence_sha,
        "account": "항공료", "cost_type": "여행원가",
        "vat_tag": "불공제_해외", "trip_target": "0924_야마구치",
        "decision_status": "confirmed", "posting_status": "blocked",
        "individual_card_to_passenger_bijection_asserted": False,
    } for event in matches]
    return {"manifest": {
        "artifact_type": ARTIFACT_TYPE, "rule_version": RULE_VERSION,
        "selected_event_set_sha256": SELECTED_SET_SHA256, "selected_count": 2,
        "axis_decision_count": 8, "card_event_count": 2, "ota_message_count": 2,
        "individual_card_to_passenger_bijection_asserted": False,
        "current_event_set_sha256": current_event_set_sha256,
        "decision_scope_sha256": decision_scope_sha256,
        "manual_sha256": MANUAL_SHA256, "ota_sha256": OTA_SHA256,
        "posting_status": "blocked", "database_applied": False,
        "all_source_events_retained": True,
    }, "decisions": sorted(decisions, key=lambda row: row["direct_event_key"])}
