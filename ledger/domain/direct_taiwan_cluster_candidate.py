"""Build a candidate-only Taiwan trip cluster from current source facts.

The January 2026 Taiwan trip is not present in the active trip schedule.  This
module therefore records a reversible candidate set only.  It deliberately
reads current card evidence and the redacted current OTA mail index; manual
ledgers, retired indexes, and cafe-learning documents are not inputs and can
never receive Gate 5 credit here.
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
import unicodedata
from datetime import date
from typing import Iterable

from ledger.domain.direct_high_coverage_classifier import _load_current
from ledger.domain.direct_geographic_trip_context import is_taiwan_marker


ARTIFACT_TYPE = "current-taiwan-cluster-candidate"
RULE_VERSION = "current-card-taiwan-cluster-candidate-v1"
TARGET_CODE = "0107_대만"
CURRENT_START = date(2026, 1, 7)
CURRENT_END = date(2026, 1, 14)
CURRENT_PERIOD = "0107_0114"
REVERSAL_TYPES = {"cancellation", "refund"}
def _canonical(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def _sha(value: object) -> str:
    return hashlib.sha256(
        value if isinstance(value, bytes) else _canonical(value)
    ).hexdigest()


def _norm(value: object) -> str:
    text = unicodedata.normalize("NFKC", str(value or "")).upper()
    return "".join(char for char in text if char.isalnum())


def _within_current_window(value: object) -> bool:
    try:
        occurred = date.fromisoformat(str(value or ""))
    except ValueError:
        return False
    return CURRENT_START <= occurred <= CURRENT_END


def _is_taiwan_marker(value: object) -> bool:
    return is_taiwan_marker(value)


def _ota_anchor_records(db: sqlite3.Connection) -> list[dict[str, object]]:
    """Return current Agoda date anchors without retaining subject/body text."""
    rows = db.execute(
        """SELECT source_key,payload_json,source_sha256
           FROM direct_source_records
           WHERE source_kind='ota_mail'
           ORDER BY source_key"""
    ).fetchall()
    anchors: list[dict[str, object]] = []
    for source_key, payload_json, source_sha256 in rows:
        try:
            payload = json.loads(str(payload_json))
        except (TypeError, json.JSONDecodeError):
            continue
        if not isinstance(payload, dict):
            continue
        provider = _norm(payload.get("provider"))
        dates = {
            str(value).replace("-", "")
            for value in payload.get("travel_date_candidates", [])
        }
        if provider != "AGODA" or not dates.intersection({"0108", "0109", "0113", "0114"}):
            continue
        anchors.append(
            {
                "source_key": str(source_key),
                "message_id": str(payload.get("message_id") or ""),
                "message_hash": str(payload.get("message_hash") or ""),
                "source_sha256": str(source_sha256),
                "travel_date_candidates": sorted(dates),
            }
        )
    return anchors


def _is_ota_anchor_candidate(
    row: dict[str, object], ota_anchors: Iterable[dict[str, object]],
) -> bool:
    merchant = _norm(row.get("merchant"))
    if "AGODA" not in merchant or "CHERNGYUA" not in merchant:
        return False
    return any(ota_anchors)


def _candidate_row(
    row: dict[str, object], basis: str,
) -> dict[str, object]:
    merchant = str(row.get("merchant") or "")
    return {
        "direct_event_key": str(row.get("direct_event_key") or ""),
        "payment_id": int(row["payment_id"]),
        "current_evidence_id": str(row.get("current_evidence_id") or ""),
        "current_source_kind": str(row.get("source_kind") or ""),
        "current_source_key": str(row.get("source_key") or ""),
        "current_source_sha256": str(row.get("source_sha256") or ""),
        "current_fact_sha256": str(row.get("current_fact_sha256") or ""),
        "observed_on": str(row.get("occurred_on") or ""),
        "amount_krw": int(row.get("amount_krw") or 0),
        "merchant_sha256": _sha(_norm(merchant)),
        "target_code": TARGET_CODE,
        "target_period": CURRENT_PERIOD,
        "match_basis": basis,
        "authority_status": "candidate_only",
        "posting_status": "blocked",
        "confirmed_count": 0,
        "gate5_credit": 0,
        "applied": False,
    }


def build_taiwan_cluster_candidate(
    current_rows: Iterable[dict[str, object]],
    ota_anchors: Iterable[dict[str, object]] = (),
) -> dict[str, object]:
    """Classify current rows into candidate, corroboration-only, or excluded.

    TWD-only rows are intentionally corroboration-only unless the merchant
    itself identifies Taiwan.  That keeps the candidate set fail-closed while
    preserving useful leads for a later independent check.
    """
    anchors = list(ota_anchors)
    candidates: list[dict[str, object]] = []
    corroboration_only: list[dict[str, object]] = []
    excluded_reversals: list[dict[str, object]] = []
    seen: set[str] = set()

    for row in current_rows:
        if str(row.get("source_kind") or "") != "card_raw":
            continue
        event_key = str(row.get("direct_event_key") or row.get("payment_id") or "")
        if event_key in seen:
            raise ValueError(f"taiwan_candidate_duplicate:{event_key}")
        seen.add(event_key)
        if not _within_current_window(row.get("occurred_on")):
            continue
        transaction_type = str(row.get("transaction_type") or "")
        if transaction_type in REVERSAL_TYPES:
            excluded_reversals.append(
                {"direct_event_key": event_key, "payment_id": int(row["payment_id"])}
            )
            continue
        if transaction_type != "purchase":
            continue
        if _is_ota_anchor_candidate(row, anchors):
            candidates.append(_candidate_row(row, "current_card_plus_current_agoda_date_anchor"))
        elif _is_taiwan_marker(row.get("merchant")):
            candidates.append(_candidate_row(row, "current_card_taiwan_marker"))
        elif _norm(row.get("currency")) == "TWD":
            corroboration_only.append(
                {
                    "direct_event_key": event_key,
                    "payment_id": int(row["payment_id"]),
                    "observed_on": str(row.get("occurred_on") or ""),
                    "amount_krw": int(row.get("amount_krw") or 0),
                    "current_source_key": str(row.get("source_key") or ""),
                    "reason": "twd_without_current_taiwan_merchant_marker",
                    "authority_status": "candidate_only",
                    "posting_status": "blocked",
                    "confirmed_count": 0,
                    "gate5_credit": 0,
                    "applied": False,
                }
            )

    event_set = sorted(str(row["direct_event_key"]) for row in candidates)
    candidate_set_sha256 = _sha(event_set)
    manifest = {
        "format_version": 1,
        "artifact_type": ARTIFACT_TYPE,
        "rule_version": RULE_VERSION,
        "target_code": TARGET_CODE,
        "target_period": CURRENT_PERIOD,
        "authority_status": "candidate_only",
        "posting_status": "blocked",
        "confirmed_count": 0,
        "gate5_credit": 0,
        "applied": False,
        "contains_sensitive_raw_values": False,
        "source_policy": {
            "allowed_current_source_kinds": ["card_raw", "ota_mail"],
            "manual_or_learning_sources_used": False,
            "manual_or_learning_sources": [
                "manual_ledger",
                "classifier_training",
                "retired_staff_ota_index",
                "cafe_learning_documents",
            ],
        },
        "counts": {
            "candidate_rows": len(candidates),
            "corroboration_only_twd_rows": len(corroboration_only),
            "excluded_reversal_rows": len(excluded_reversals),
            "ota_anchor_records": len(anchors),
        },
        "candidate_set_sha256": candidate_set_sha256,
        "ota_anchor_set_sha256": _sha(
            sorted(str(item.get("message_hash") or "") for item in anchors)
        ),
    }
    return {
        "manifest": manifest,
        "candidates": candidates,
        "corroboration_only": corroboration_only,
        "excluded_reversals": excluded_reversals,
        "ota_anchors": anchors,
    }


def project_taiwan_cluster_candidate(
    db: sqlite3.Connection, run_id: str,
) -> dict[str, object]:
    """Read the current projection and return an unapplied candidate artifact."""
    current_rows = _load_current(db, run_id)
    result = build_taiwan_cluster_candidate(current_rows, _ota_anchor_records(db))
    if result["manifest"]["gate5_credit"] != 0:
        raise ValueError("taiwan_candidate_gate5_credit_nonzero")
    if result["manifest"]["applied"]:
        raise ValueError("taiwan_candidate_applied")
    return result


def validate_taiwan_cluster_candidate(result: dict[str, object]) -> dict[str, object]:
    """Validate the authority boundary without mutating the database."""
    manifest = result.get("manifest")
    candidates = result.get("candidates")
    if not isinstance(manifest, dict) or not isinstance(candidates, list):
        return {"passed": False, "reason": "artifact_shape_invalid"}
    passed = (
        manifest.get("authority_status") == "candidate_only"
        and manifest.get("posting_status") == "blocked"
        and manifest.get("confirmed_count") == 0
        and manifest.get("gate5_credit") == 0
        and manifest.get("applied") is False
        and all(
            isinstance(row, dict)
            and row.get("authority_status") == "candidate_only"
            and row.get("posting_status") == "blocked"
            and row.get("confirmed_count") == 0
            and row.get("gate5_credit") == 0
            and row.get("applied") is False
            for row in candidates
        )
    )
    return {
        "passed": passed,
        "candidate_count": len(candidates),
        "gate5_credit": manifest.get("gate5_credit"),
        "database_applied": manifest.get("applied"),
    }
