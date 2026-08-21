"""Retain reproducible historical/manual card groups as candidate hints.

This is deliberately narrower than the 76-row audit universe.  The 42 selected
rows have an exact current/historical identity and one matching row in the
latest manual ledger.  Lodging and rental-car rows are kept out of this
artifact until booking/service evidence is available (P10).
"""
from __future__ import annotations

import csv
import hashlib
import json
import tempfile
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any

from ledger.domain import direct_manual_group_taxonomy_evidence as r36
from ledger.domain.direct_all_period_historical_replay import (
    EXPECTED_REPLAY_V14_SHA256,
    replay_legacy_classification,
)
from ledger.domain.direct_lineage_annex import REPOSITORY_ROOT


ARTIFACT_TYPE = "all-period-historical-exact-manual-card-candidates-v2"
RULE_VERSION = "reproducible-historical-manual-card-three-axis-candidate-only-v2"
EXPECTED_PAYMENT_COUNT = 42
EXPECTED_CANDIDATE_AXIS_COUNT = 126
EXPECTED_EVENT_SET_SHA256 = (
    "774cf2788be9cc045405eb6139ee91fb5bb0a3445bf97aa2377b4f0f2b25a6ef"
)
EXPECTED_SEMANTIC_SET_SHA256 = (
    "1817166ae29a3fc6a9be95ac7883227d218d11c9a61e43a736f8316b7362d023"
)
EXPECTED_AXIS_COUNTS = {
    "account": 42,
    "allocation_target": 42,
    "cost_type": 42,
}
MANUAL_SHA256 = (
    "80bd2fbae815e51f286a5bca2639d14971abbcc88fc2e9e4ece8b5ae3ee165a6"
)
TRIPS_SHA256 = "0a9fdd6b4835d2cf889391b00e2567977858b77376d3d3071023e81609e51969"
CURRENT_EVENT_SET_SHA256 = "de1660be34fa259e7e4a2fe88d5e45c478c7707637f61cf43c69c33af3abce93"
DECISION_SCOPE_SHA256 = "22459391ce7696e03c62eeaedf3d59b9faec5307baa62fcb578f55cc4b1a1418"

# Frozen from the independent 46-row high/high audit after removing the four
# service-evidence rows (two lodging and two rental-car payments).
SELECTED_UIDS = (
    "CORP-2015", "CORP-2033", "CORP-2023", "CORP-2024", "CORP-2042",
    "HAN-3458", "CORP-2039", "CORP-2036", "CORP-2029", "CORP-2045",
    "HAN-3452", "HAN-3446", "HAN-3441", "CORP-2019", "CORP-2046",
    "CORP-2021", "CORP-2038", "HAN-3450", "HAN-3437", "CORP-2017",
    "CORP-2047", "CORP-2025", "CORP-2028", "CORP-2037", "HAN-3453",
    "HAN-3442", "CORP-2044", "CORP-2035", "HAN-3454", "HAN-3459",
    "CORP-2003", "HAN-3448", "CORP-2020", "CORP-2030", "CORP-2031",
    "CORP-2040", "CORP-2016", "CORP-2022", "CORP-2041", "HAN-3449",
    "CORP-2027", "CORP-2032",
)
SERVICE_EVIDENCE_WITHHELD_UIDS = (
    "CORP-2004", "HAN-3445", "CORP-2018", "HAN-3261",
)
PLACEHOLDERS = {None, "", "확인", "공제후보"}
ISSUERS = {"하나": ("HAN",), "기업": ("CORP",), "국민": ("KBD", "KBO")}


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _json(value: object) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        + "\n"
    ).encode("utf-8")


def _digits(value: object) -> str:
    return "".join(char for char in str(value or "") if char.isdigit())


def _date(value: object) -> str:
    text = str(value or "").strip()
    for fmt in ("%y.%m.%d", "%Y.%m.%d"):
        try:
            return datetime.strptime(text, fmt).date().isoformat()
        except ValueError:
            continue
    return text.replace(".", "-")


def _event_key(row: dict[str, object]) -> tuple[str, str, int, str, str]:
    return (
        str(row.get("source_system") or row.get("src") or ""),
        str(row.get("occurred_on") or row.get("use_date") or ""),
        int(row.get("signed_amount_krw", row.get("_amount", row.get("krw", 0))) or 0),
        _digits(row.get("approval_number", row.get("appr"))),
        _digits(row.get("card4"))[-4:],
    )


def _manual_groups(ledger_dir: Path) -> dict[tuple[str, str, int, str], int]:
    path = ledger_dir / "data/manual_v4.csv"
    raw = path.read_bytes()
    if _sha(raw) != MANUAL_SHA256:
        raise ValueError("historical_exact_manual_card_manual_hash_mismatch")
    groups: Counter[tuple[str, str, int, str]] = Counter()
    with path.open(encoding="utf-8-sig", newline="") as stream:
        for row in csv.DictReader(stream):
            for source in ISSUERS.get(str(row.get("card") or "").strip(), ()):
                try:
                    amount = int(float(row.get("amount") or 0))
                except (TypeError, ValueError) as exc:
                    raise ValueError("historical_exact_manual_card_amount_invalid") from exc
                groups[(source, _date(row.get("date")), amount, str(row.get("tab") or ""))] += 1
    return dict(groups)


def build_historical_exact_manual_card_admission(
        *, ledger_dir: Path = Path(REPOSITORY_ROOT) / "ledger",
        replay: dict[str, Any] | None = None) -> dict[str, object]:
    """Return 42 frozen replay/manual rows as non-authoritative candidates."""
    if ledger_dir.resolve() != (Path(REPOSITORY_ROOT) / "ledger").resolve():
        raise ValueError("historical_exact_manual_card_noncanonical_ledger")

    replay = replay or replay_legacy_classification(ledger_dir)
    if replay.get("sha256") != EXPECTED_REPLAY_V14_SHA256:
        raise ValueError("historical_exact_manual_card_replay_hash_mismatch")
    replay_rows = list(replay.get("rows") or [])
    replay_by_uid = {str(row.get("uid")): row for row in replay_rows}
    if len(replay_by_uid) != len(replay_rows):
        raise ValueError("historical_exact_manual_card_replay_uid_duplicate")

    manual_groups = _manual_groups(ledger_dir)
    trips_path = ledger_dir / "data/trips.json"
    trips_raw = trips_path.read_bytes()
    if _sha(trips_raw) != TRIPS_SHA256:
        raise ValueError("historical_exact_manual_card_trips_hash_mismatch")
    trips = json.loads(trips_raw)
    trip_codes = {str(row.get("tab")) for row in trips}

    with tempfile.TemporaryDirectory(prefix="historical-exact-manual-card-") as directory:
        context = r36._context(ledger_dir, Path(directory))
        db = context["db"]
        try:
            events = list(context["events"])
            if (context["current_event_set_sha256"] != CURRENT_EVENT_SET_SHA256
                    or context["decision_scope_sha256"] != DECISION_SCOPE_SHA256
                    or len(events) != 5328):
                raise ValueError("historical_exact_manual_card_current_context_drift")
            payload_rows = db.execute(
                """SELECT d.card_event_id,d.event_role,s.payload_json
                   FROM direct_payment_projection_links l
                   JOIN direct_normalized_payments d ON d.id=l.direct_payment_id
                   JOIN direct_source_records s ON s.id=d.source_record_id
                   WHERE l.run_id=?""",
                (context["run_id"],),
            ).fetchall()
        finally:
            db.close()

    payload_by_event = {
        f"{row[0]}#{row[1]}": json.loads(row[2]) for row in payload_rows
    }
    current_by_key: dict[tuple[str, str, int, str, str], list[dict[str, object]]] = defaultdict(list)
    for event in events:
        current_by_key[_event_key(event)].append(event)

    historical_by_key: dict[tuple[str, str, int, str, str], list[dict[str, object]]] = defaultdict(list)
    for row in replay_rows:
        signed_amount = int(row.get("krw") or 0)
        if (str(row.get("src")) in {"KBO", "CORP"}
                and str(row.get("cancel")).lower() == "true"):
            signed_amount = -abs(signed_amount)
        normalized = {**row, "_amount": signed_amount}
        historical_by_key[_event_key(normalized)].append(normalized)

    decisions: list[dict[str, object]] = []
    for uid in SELECTED_UIDS:
        historical = replay_by_uid.get(uid)
        if historical is None:
            raise ValueError("historical_exact_manual_card_selected_uid_missing")
        normalized = {**historical, "_amount": int(historical.get("krw") or 0)}
        if (str(historical.get("src")) in {"KBO", "CORP"}
                and str(historical.get("cancel")).lower() == "true"):
            normalized["_amount"] = -abs(int(historical.get("krw") or 0))
        key = _event_key(normalized)
        current = current_by_key.get(key, [])
        if len(current) != 1 or len(historical_by_key.get(key, [])) != 1:
            raise ValueError("historical_exact_manual_card_identity_not_unique")
        event = current[0]
        source = str(event["source_system"])
        if source not in {"HAN", "CORP"} or not _digits(event.get("card4")):
            raise ValueError("historical_exact_manual_card_source_or_card_invalid")
        payload = payload_by_event.get(str(event["direct_event_key"]), {})
        manual_amount = int(payload.get("approval_amount") or event["signed_amount_krw"])
        bucket = str(historical.get("bucket") or "")
        if bucket in PLACEHOLDERS or bucket not in trip_codes:
            raise ValueError("historical_exact_manual_card_bucket_invalid")
        axes = {
            "allocation_target": bucket,
            "account": historical.get("account"),
            "cost_type": historical.get("cost_type"),
        }
        if any(value in PLACEHOLDERS for value in axes.values()):
            raise ValueError("historical_exact_manual_card_axis_placeholder")
        if historical.get("confidence") != "상":
            raise ValueError("historical_exact_manual_card_confidence_drift")
        if manual_groups.get((source, str(event["occurred_on"]), manual_amount, bucket), 0) != 1:
            raise ValueError("historical_exact_manual_card_manual_cardinality_invalid")
        decisions.append({
            "direct_event_key": event["direct_event_key"],
            "historical_uid": uid,
            "current_event_sha256": event["current_event_sha256"],
            "current_source_sha256": event["current_source_sha256"],
            "axes": axes,
            "legacy_trip_target_hint": True,
            "manual_group_cardinality": 1,
            "candidate_status": "withheld_pending_independent_evidence",
            "posting_status": "blocked",
        })

    decisions.sort(key=lambda row: str(row["direct_event_key"]))
    event_keys = {str(row["direct_event_key"]) for row in decisions}
    semantic = [
        {"event": row["direct_event_key"], "uid": row["historical_uid"], "axes": row["axes"]}
        for row in decisions
    ]
    axis_counts = dict(sorted(Counter(
        dimension for row in decisions for dimension in row["axes"]
    ).items()))
    if (len(decisions) != EXPECTED_PAYMENT_COUNT
            or sum(len(row["axes"]) for row in decisions) != EXPECTED_CANDIDATE_AXIS_COUNT
            or set(row["historical_uid"] for row in decisions) != set(SELECTED_UIDS)
            or r36._event_set_sha(event_keys) != EXPECTED_EVENT_SET_SHA256
            or _sha(_json(semantic)) != EXPECTED_SEMANTIC_SET_SHA256
            or axis_counts != EXPECTED_AXIS_COUNTS):
        raise ValueError("historical_exact_manual_card_admission_drift")

    return {
        "manifest": {
            "artifact_type": ARTIFACT_TYPE,
            "rule_version": RULE_VERSION,
            "candidate_count": EXPECTED_PAYMENT_COUNT,
            "legacy_candidate_axis_count": EXPECTED_CANDIDATE_AXIS_COUNT,
            "axis_counts": axis_counts,
            "fully_concrete_payment_count": EXPECTED_PAYMENT_COUNT,
            "legacy_trip_target_hint_count": EXPECTED_PAYMENT_COUNT,
            "service_evidence_withheld_count": len(SERVICE_EVIDENCE_WITHHELD_UIDS),
            "service_evidence_withheld_uids": list(SERVICE_EVIDENCE_WITHHELD_UIDS),
            "event_set_sha256": EXPECTED_EVENT_SET_SHA256,
            "semantic_set_sha256": EXPECTED_SEMANTIC_SET_SHA256,
            "replay_v14_sha256": replay["sha256"],
            "replay_v14_row_count": replay["row_count"],
            "manual_sha256": MANUAL_SHA256,
            "current_event_set_sha256": context["current_event_set_sha256"],
            "decision_scope_sha256": context["decision_scope_sha256"],
            "authority_status": "candidate_only",
            "gate5_credit": 0,
            "active_dimensions": ["account", "cost_type", "allocation_target"],
            "excluded_dimensions": ["vat_tag"],
            "posting_status": "blocked",
            "database_applied": False,
            "all_source_events_retained": True,
        },
        "candidates": decisions,
    }
