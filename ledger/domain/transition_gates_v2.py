"""Run-scoped, fail-closed gates for the isolated direct candidate."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sqlite3
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Iterable
from ledger.domain.decision_integrity import decision_integrity


HERE = Path(__file__).resolve().parent
REPOSITORY_ROOT = HERE.parents[1]
SCHEMA_VERSION = "p07-direct-v2"
PARSER_BUNDLE_VERSION = "direct-source-v3"
REQUIRED_INPUTS = (
    {
        "source_kind": "card_raw:A_20260720",
        "relative_path": "ledger/newcard/conv/A_20260720.xlsx",
        "db_source_kind": "card_raw",
        "record_prefix": "CORP:A_20260720:",
    },
    {
        "source_kind": "card_raw:E",
        "relative_path": "ledger/newcard/conv/E.xlsx",
        "db_source_kind": "card_raw",
        "record_prefix": "KBO:E:",
    },
    {
        "source_kind": "card_raw:F",
        "relative_path": "ledger/newcard/conv/F.xlsx",
        "db_source_kind": "card_raw",
        "record_prefix": "KBD:F:",
    },
    {
        "source_kind": "card_raw:G",
        "relative_path": "ledger/newcard/conv/G.xlsx",
        "db_source_kind": "card_raw",
        "record_prefix": "HAN:G:",
    },
    {
        "source_kind": "card_raw:H",
        "relative_path": "ledger/newcard/conv/H.xlsx",
        "db_source_kind": "card_raw",
        "record_prefix": "HAN:H:",
    },
    {
        "source_kind": "manual_ledger",
        "relative_path": "ledger/data/manual_v4.csv",
        "db_source_kind": "manual_ledger",
        "record_prefix": None,
    },
    {
        "source_kind": "ota_mail",
        "relative_path": "ledger/data/ota_mail_index.json",
        "db_source_kind": "ota_mail",
        "record_prefix": None,
    },
)
GATE_NAMES = (
    "source_provenance",
    "event_projection_cardinality",
    "legacy_leakage",
    "amount_sign_and_relations",
    "allocation_and_decision_completeness",
    "semantic_regression",
    "report_freshness",
)
APPROVAL_REQUIRED_FIELDS = {
    "transition_id",
    "rule_id",
    "direct_event_keys",
    "before_event_sha256",
    "after_event_sha256",
    "evidence_set_sha256",
    "before_semantic_sha256",
    "after_semantic_sha256",
    "approved_by",
    "approved_at",
    "approval_source",
    "approval_source_sha256",
    "source_run_id",
}


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _canonical_json_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _key_set_sha256(keys: Iterable[str]) -> str:
    return _sha256_bytes(
        ("\n".join(sorted(str(key) for key in keys)) + "\n").encode("utf-8")
    )


def input_manifest_sha256(inventory: Iterable[dict[str, object]]) -> str:
    ordered = sorted(
        (dict(item) for item in inventory),
        key=lambda row: (str(row["source_kind"]), str(row["relative_path"])),
    )
    return _sha256_bytes(_canonical_json_bytes(ordered))


def candidate_semantic_sha256(db: object, run_id: str) -> str:
    rows = db.execute(
        """
        SELECT
            p.external_key,
            p.source_event_id,
            p.identity_fingerprint,
            p.source_system,
            p.occurred_on,
            p.merchant,
            p.approval_number,
            p.amount_krw,
            p.transaction_type,
            d.card_event_id,
            d.event_role,
            s.source_kind,
            s.source_key,
            s.source_sha256
        FROM direct_payment_projection_links l
        JOIN payment_transactions p ON p.id=l.payment_id
        JOIN direct_normalized_payments d ON d.id=l.direct_payment_id
        JOIN direct_source_records s ON s.id=d.source_record_id
        WHERE l.run_id=?
        ORDER BY p.external_key
        """,
        (run_id,),
    ).fetchall()
    return _sha256_bytes(
        _canonical_json_bytes([list(row) for row in rows])
    )


def gate_report_sha256(report: dict[str, object]) -> str:
    payload = dict(report)
    payload.pop("gate_report_sha256", None)
    return _sha256_bytes(_canonical_json_bytes(payload))


def _validate_sha256(value: object, field: str, index: int) -> str:
    if not isinstance(value, str) or re.fullmatch(r"[0-9a-f]{64}", value) is None:
        raise ValueError(f"approval_hash_invalid:{index}:{field}")
    return value


def _validate_rfc3339_with_timezone(
    value: object, field: str, index: int
) -> str:
    if (
        not isinstance(value, str)
        or re.fullmatch(
            r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}"
            r"(?:\.\d+)?(?:Z|[+-](?:[01]\d|2[0-3]):[0-5]\d)",
            value,
        ) is None
    ):
        raise ValueError(f"approval_timestamp_invalid:{index}:{field}")
    try:
        parsed = datetime.fromisoformat(
            value[:-1] + "+00:00" if value.endswith("Z") else value
        )
    except ValueError as exc:
        raise ValueError(f"approval_timestamp_invalid:{index}:{field}") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"approval_timestamp_invalid:{index}:{field}")
    if value.endswith("-00:00"):
        raise ValueError(f"approval_timestamp_invalid:{index}:{field}")
    return value


def validate_approved_transitions(
    approvals: Iterable[dict[str, object]] | None,
    *,
    expected_source_run_id: str | None = None,
    expected_after_semantic_sha256: str | None = None,
) -> list[dict[str, object]]:
    if approvals is None:
        return []
    validated: list[dict[str, object]] = []
    transition_ids: set[str] = set()
    event_keys_seen: set[str] = set()
    for index, raw in enumerate(approvals):
        if not isinstance(raw, dict):
            raise ValueError(f"approval_not_object:{index}")
        missing = sorted(APPROVAL_REQUIRED_FIELDS - set(raw))
        if missing:
            raise ValueError(
                f"approval_missing_event_lineage:{index}:{','.join(missing)}"
            )
        event_keys = raw["direct_event_keys"]
        if not isinstance(event_keys, list) or len(event_keys) != 1:
            raise ValueError(f"approval_event_keys_invalid:{index}")
        if (
            not isinstance(event_keys[0], str)
            or re.fullmatch(
                r"card:[0-9a-f]{64}#(single|approval|cancellation)",
                event_keys[0],
            ) is None
        ):
            raise ValueError(f"approval_event_keys_invalid:{index}")
        for field in (
            "before_event_sha256",
            "after_event_sha256",
            "evidence_set_sha256",
            "before_semantic_sha256",
            "after_semantic_sha256",
            "approval_source_sha256",
        ):
            _validate_sha256(raw[field], field, index)
        _validate_sha256(raw["transition_id"], "transition_id", index)
        for field in ("rule_id", "approved_by", "approval_source", "source_run_id"):
            if not isinstance(raw[field], str) or not raw[field].strip():
                raise ValueError(f"approval_field_invalid:{index}:{field}")
        _validate_rfc3339_with_timezone(raw["approved_at"], "approved_at", index)
        if raw.get("supersedes_approval_id") is not None:
            raise ValueError(f"approval_supersession_unsupported:{index}")
        if raw.get("supersedes") is not None:
            raise ValueError(f"approval_supersedes_field_invalid:{index}")
        if raw["transition_id"] in transition_ids:
            raise ValueError(f"approval_duplicate_transition:{index}")
        if event_keys[0] in event_keys_seen:
            raise ValueError(f"approval_duplicate_event:{index}")
        if (
            expected_source_run_id is not None
            and raw["source_run_id"] != expected_source_run_id
        ):
            raise ValueError(f"approval_source_run_mismatch:{index}")
        if (
            expected_after_semantic_sha256 is not None
            and raw["after_semantic_sha256"] != expected_after_semantic_sha256
        ):
            raise ValueError(f"approval_after_semantic_mismatch:{index}")
        transition_ids.add(raw["transition_id"])
        event_keys_seen.add(event_keys[0])
        validated.append(dict(raw))
    return validated


def _load_comparable_baseline(
    descriptor: dict[str, object],
    repository_root: Path,
) -> tuple[dict[str, object], dict[str, object]]:
    required = {"relative_path", "role", "raw_sha256"}
    missing = sorted(required - set(descriptor))
    if missing:
        raise ValueError(f"baseline_missing_provenance:{','.join(missing)}")
    if descriptor["role"] != "direct_semantic_baseline":
        raise ValueError("baseline_role_invalid")
    root = repository_root.resolve()
    candidate = (root / str(descriptor["relative_path"])).resolve()
    try:
        relative_path = candidate.relative_to(root).as_posix()
    except ValueError as exc:
        raise ValueError("baseline_path_escape") from exc
    if not candidate.is_file():
        raise ValueError("baseline_missing")
    raw = candidate.read_bytes()
    actual_hash = _sha256_bytes(raw)
    if descriptor["raw_sha256"] != actual_hash:
        raise ValueError("baseline_hash_mismatch")
    try:
        payload = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("baseline_json_invalid") from exc
    if not isinstance(payload, dict):
        raise ValueError("baseline_payload_not_object")
    return payload, {
        "relative_path": relative_path,
        "role": "direct_semantic_baseline",
        "raw_sha256": actual_hash,
    }


_DIRECT_EVENT_BASELINE_SCOPE = "direct-event-role-v1"
_DIRECT_EVENT_KEY_PATTERN = re.compile(
    r"^card:[0-9a-f]{64}#(single|approval|cancellation)$"
)
_SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")


def _event_set_sha256(events: Iterable[tuple[str, str]]) -> str:
    canonical = "".join(
        f"{key} {event_hash}\n"
        for key, event_hash in sorted(events)
    ).encode("utf-8")
    return _sha256_bytes(canonical)


def _decision_scope_sha256(keys: Iterable[str]) -> str:
    canonical = ("\n".join(sorted(keys)) + "\n").encode("utf-8")
    return _sha256_bytes(canonical)


def _direct_event_semantic_hash(payload: dict[str, object]) -> str:
    return _sha256_bytes(
        json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    )


def _current_direct_event_hashes(
    db: object,
    run_id: str,
) -> tuple[dict[str, str], str, str]:
    rows = db.execute(
        """
        SELECT
            d.card_event_id,
            d.event_role,
            p.external_key,
            p.source_event_id,
            p.identity_fingerprint,
            p.source_system,
            p.occurred_on,
            p.merchant,
            p.approval_number,
            p.amount_krw,
            p.transaction_type,
            s.source_kind,
            s.source_key,
            s.source_sha256
        FROM direct_payment_projection_links l
        JOIN payment_transactions p ON p.id=l.payment_id
        JOIN direct_normalized_payments d ON d.id=l.direct_payment_id
        JOIN direct_source_records s ON s.id=d.source_record_id
        WHERE l.run_id=?
        ORDER BY d.card_event_id, d.event_role
        """,
        (run_id,),
    ).fetchall()
    event_hashes: dict[str, str] = {}
    for row in rows:
        key = f"{row[0]}#{row[1]}"
        if not _DIRECT_EVENT_KEY_PATTERN.fullmatch(key):
            raise ValueError("baseline_current_event_key_invalid")
        if key in event_hashes:
            raise ValueError("baseline_current_event_key_duplicate")
        payload = {
            "direct_event_key": key,
            "external_key": row[2],
            "source_event_id": row[3],
            "identity_fingerprint": row[4],
            "source_system": row[5],
            "occurred_on": row[6],
            "merchant": row[7],
            "approval_number": row[8],
            "amount_krw": int(row[9]),
            "transaction_type": row[10],
            "card_event_id": row[0],
            "event_role": row[1],
            "source_kind": row[11],
            "source_key": row[12],
            "source_sha256": row[13],
        }
        event_hashes[key] = _direct_event_semantic_hash(payload)
    return event_hashes, _event_set_sha256(event_hashes.items()), _decision_scope_sha256(
        event_hashes
    )


def _validate_event_baseline(
    payload: dict[str, object],
    *,
    run_id: str,
) -> tuple[dict[str, object], dict[str, str]]:
    format_version = payload.get("format_version")
    if type(format_version) is not int or format_version != 1:
        raise ValueError("baseline_format_version_invalid")
    if payload.get("event_scope") != _DIRECT_EVENT_BASELINE_SCOPE:
        raise ValueError("baseline_event_scope_invalid")
    if payload.get("parser_version") != PARSER_BUNDLE_VERSION:
        raise ValueError("baseline_parser_version_invalid")
    required = (
        "parser_version", "source_run_id", "input_manifest_sha256",
        "decision_scope_sha256", "candidate_semantic_sha256",
        "event_set_sha256", "events",
    )
    missing = [field for field in required if not payload.get(field)]
    if missing:
        raise ValueError(f"baseline_missing_field:{','.join(missing)}")
    if not isinstance(payload["source_run_id"], str) or not payload["source_run_id"].strip():
        raise ValueError("baseline_source_run_invalid")
    for field in (
        "input_manifest_sha256", "decision_scope_sha256",
        "candidate_semantic_sha256", "event_set_sha256",
    ):
        if not isinstance(payload[field], str) or not _SHA256_PATTERN.fullmatch(payload[field]):
            raise ValueError(f"baseline_hash_invalid:{field}")
    events = payload["events"]
    if not isinstance(events, list) or not events:
        raise ValueError("baseline_events_invalid")
    baseline_hashes: dict[str, str] = {}
    for index, event in enumerate(events):
        if not isinstance(event, dict) or set(event) != {"direct_event_key", "event_sha256"}:
            raise ValueError(f"baseline_event_invalid:{index}")
        key = event["direct_event_key"]
        event_hash = event["event_sha256"]
        if not isinstance(key, str) or not _DIRECT_EVENT_KEY_PATTERN.fullmatch(key):
            raise ValueError(f"baseline_event_key_invalid:{index}")
        if not isinstance(event_hash, str) or not _SHA256_PATTERN.fullmatch(event_hash):
            raise ValueError(f"baseline_event_hash_invalid:{index}")
        if key in baseline_hashes:
            raise ValueError("baseline_event_key_duplicate")
        baseline_hashes[key] = event_hash
    baseline_scope_hash = _decision_scope_sha256(baseline_hashes)
    if payload["decision_scope_sha256"] != baseline_scope_hash:
        raise ValueError("baseline_decision_scope_hash_mismatch")
    if _event_set_sha256(baseline_hashes.items()) != payload["event_set_sha256"]:
        raise ValueError("baseline_event_set_hash_mismatch")
    return payload, baseline_hashes


def _gate(
    number: int,
    name: str,
    passed: bool,
    *,
    reason: str,
    actual: object,
) -> dict[str, object]:
    return {
        "gate": number,
        "name": name,
        "passed": bool(passed),
        "reason": reason,
        "actual": actual,
    }


def _input_rows(db: object, run_id: str) -> list[dict[str, object]]:
    columns = (
        "source_kind",
        "relative_path",
        "raw_sha256",
        "lf_sha256",
        "byte_count",
        "key_set_sha256",
        "record_count",
        "parser_version",
    )
    rows = db.execute(
        """
        SELECT
            source_kind, relative_path, raw_sha256, lf_sha256,
            byte_count, key_set_sha256, record_count, parser_version
        FROM direct_projection_inputs
        WHERE run_id=?
        ORDER BY source_kind, relative_path
        """,
        (run_id,),
    ).fetchall()
    return [dict(zip(columns, row)) for row in rows]


def _actual_source_keys(
    db: object,
    spec: dict[str, object],
) -> list[str]:
    db_kind = str(spec["db_source_kind"])
    prefix = spec["record_prefix"]
    if prefix is None:
        rows = db.execute(
            """
            SELECT source_key
            FROM direct_source_records
            WHERE source_kind=?
            ORDER BY source_key
            """,
            (db_kind,),
        ).fetchall()
    else:
        rows = db.execute(
            """
            SELECT source_key
            FROM direct_source_records
            WHERE source_kind=? AND source_key LIKE ?
            ORDER BY source_key
            """,
            (db_kind, f"{prefix}%"),
        ).fetchall()
    return [str(row[0]) for row in rows]


def _source_provenance_gate(
    db: object,
    run_id: str,
    run: dict[str, object],
    repository_root: Path,
) -> dict[str, object]:
    inputs = _input_rows(db, run_id)
    required = {
        (str(spec["source_kind"]), str(spec["relative_path"])): spec
        for spec in REQUIRED_INPUTS
    }
    actual_pairs = {
        (str(item["source_kind"]), str(item["relative_path"]))
        for item in inputs
    }
    expected_pairs = set(required)
    issues: list[dict[str, object]] = []
    root = repository_root.resolve()
    for item in inputs:
        pair = (str(item["source_kind"]), str(item["relative_path"]))
        spec = required.get(pair)
        if spec is None:
            issues.append({"reason": "unexpected_input", "input": pair})
            continue
        candidate = (root / str(item["relative_path"])).resolve()
        try:
            candidate.relative_to(root)
        except ValueError:
            issues.append({"reason": "source_path_escape", "input": pair})
            continue
        if not candidate.is_file():
            issues.append({"reason": "source_missing", "input": pair})
            continue
        raw = candidate.read_bytes()
        expected_lf = None
        if candidate.suffix.lower() != ".xlsx":
            normalized = raw.replace(b"\r\n", b"\n").replace(b"\r", b"\n")
            expected_lf = _sha256_bytes(normalized)
        keys = _actual_source_keys(db, spec)
        checks = {
            "raw_sha256": _sha256_bytes(raw),
            "lf_sha256": expected_lf,
            "byte_count": len(raw),
            "record_count": len(keys),
            "key_set_sha256": _key_set_sha256(keys),
            "parser_version": PARSER_BUNDLE_VERSION,
        }
        for field, expected in checks.items():
            if item[field] != expected:
                issues.append(
                    {
                        "reason": f"source_{field}_mismatch",
                        "input": pair,
                        "expected": expected,
                        "actual": item[field],
                    }
                )
    conflicts = db.execute(
        """
        SELECT source_kind, source_key
        FROM direct_source_records
        GROUP BY source_kind, source_key
        HAVING COUNT(DISTINCT source_sha256)>1
        ORDER BY source_kind, source_key
        """
    ).fetchall()
    if conflicts:
        issues.append(
            {
                "reason": "source_key_content_conflict",
                "count": len(conflicts),
                "sample": [list(row) for row in conflicts[:10]],
            }
        )
    recalculated_manifest = input_manifest_sha256(inputs)
    if recalculated_manifest != run["input_manifest_sha256"]:
        issues.append(
            {
                "reason": "input_manifest_hash_mismatch",
                "expected": recalculated_manifest,
                "actual": run["input_manifest_sha256"],
            }
        )
    missing = sorted(expected_pairs - actual_pairs)
    extra = sorted(actual_pairs - expected_pairs)
    if missing:
        issues.append({"reason": "required_input_missing", "inputs": missing})
    if extra:
        issues.append({"reason": "unexpected_input_set", "inputs": extra})
    passed = not issues and len(inputs) == len(REQUIRED_INPUTS)
    return _gate(
        1,
        GATE_NAMES[0],
        passed,
        reason="ok" if passed else str(issues[0]["reason"]),
        actual={
            "physical_input_count": len(inputs),
            "issues": issues,
        },
    )


def _projection_cardinality_gate(
    db: object,
    run_id: str,
) -> dict[str, object]:
    direct_count = int(
        db.execute(
            """
            SELECT COUNT(*)
            FROM direct_normalized_payments d
            JOIN direct_source_records s ON s.id=d.source_record_id
            WHERE s.source_kind='card_raw'
            """
        ).fetchone()[0]
    )
    link_count = int(
        db.execute(
            """
            SELECT COUNT(*)
            FROM direct_payment_projection_links
            WHERE run_id=?
            """,
            (run_id,),
        ).fetchone()[0]
    )
    unmatched = db.execute(
        """
        SELECT d.card_event_id, d.event_role, s.source_key
        FROM direct_normalized_payments d
        JOIN direct_source_records s ON s.id=d.source_record_id
        LEFT JOIN direct_payment_projection_links l
          ON l.direct_payment_id=d.id AND l.run_id=?
        WHERE s.source_kind='card_raw' AND l.payment_id IS NULL
        ORDER BY d.card_event_id, d.event_role
        """,
        (run_id,),
    ).fetchall()
    collisions = db.execute(
        """
        SELECT e.card_event_id, s.source_key
        FROM direct_card_events e
        JOIN direct_source_records s ON s.id=e.source_record_id
        WHERE e.identity_status='collision'
        ORDER BY e.card_event_id, s.source_key
        """
    ).fetchall()
    fallbacks = db.execute(
        """
        SELECT e.card_event_id, s.source_key, e.identity_status
        FROM direct_card_events e
        JOIN direct_source_records s ON s.id=e.source_record_id
        WHERE e.identity_status='legacy_fallback'
        ORDER BY e.card_event_id, s.source_key
        """
    ).fetchall()
    duplicates = db.execute(
        """
        SELECT d.card_event_id, d.event_role, COUNT(*)
        FROM direct_normalized_payments d
        JOIN direct_source_records s ON s.id=d.source_record_id
        WHERE s.source_kind='card_raw'
        GROUP BY d.card_event_id, d.event_role
        HAVING COUNT(*)>1
        ORDER BY d.card_event_id, d.event_role
        """
    ).fetchall()
    mismatches = db.execute(
        """
        SELECT p.external_key
        FROM direct_payment_projection_links l
        JOIN direct_normalized_payments d ON d.id=l.direct_payment_id
        JOIN direct_card_events e ON e.source_record_id=d.source_record_id
        JOIN payment_transactions p ON p.id=l.payment_id
        WHERE l.run_id=?
          AND (
            p.source_event_id<>d.card_event_id
            OR p.amount_krw<>d.amount_krw
            OR p.transaction_type<>d.transaction_type
            OR p.source_system<>e.source_system
            OR COALESCE(p.occurred_on, '')<>COALESCE(e.occurred_on, '')
            OR COALESCE(p.merchant, '')<>COALESCE(e.merchant, '')
            OR COALESCE(p.approval_number, '')<>COALESCE(e.approval_number, '')
          )
        ORDER BY p.external_key
        """
        ,
        (run_id,),
    ).fetchall()
    passed = (
        direct_count > 0
        and direct_count == link_count
        and not unmatched
        and not collisions
        and not fallbacks
        and not duplicates
        and not mismatches
    )
    if collisions:
        reason = "identity_collision"
    elif fallbacks:
        reason = "identity_not_unique"
    elif unmatched:
        reason = "unmatched_direct_payment"
    elif duplicates:
        reason = "duplicate_direct_event_identity"
    elif mismatches:
        reason = "projection_business_field_mismatch"
    elif direct_count != link_count:
        reason = "projection_cardinality_mismatch"
    elif direct_count == 0:
        reason = "direct_payment_set_empty"
    else:
        reason = "ok"
    return _gate(
        2,
        GATE_NAMES[1],
        passed,
        reason=reason,
        actual={
            "direct_payments": direct_count,
            "projection_links": link_count,
            "unmatched_count": len(unmatched),
            "unmatched_sample": [list(row) for row in unmatched[:10]],
            "collision_count": len(collisions),
            "collision_sample": [list(row) for row in collisions[:10]],
            "fallback_count": len(fallbacks),
            "fallback_sample": [list(row) for row in fallbacks[:10]],
            "duplicate_event_count": len(duplicates),
            "business_mismatch_count": len(mismatches),
        },
    )


def _legacy_leakage_gate(db: object, run_id: str) -> dict[str, object]:
    linked_non_card = int(
        db.execute(
            """
            SELECT COUNT(*)
            FROM direct_payment_projection_links l
            JOIN direct_normalized_payments d ON d.id=l.direct_payment_id
            JOIN direct_source_records s ON s.id=d.source_record_id
            WHERE l.run_id=? AND s.source_kind<>'card_raw'
            """,
            (run_id,),
        ).fetchone()[0]
    )
    unlinked_payments = db.execute(
        """
        SELECT p.external_key
        FROM payment_transactions p
        LEFT JOIN direct_payment_projection_links l
          ON l.payment_id=p.id AND l.run_id=?
        WHERE l.payment_id IS NULL
        ORDER BY p.external_key
        """,
        (run_id,),
    ).fetchall()
    legacy_lineage = db.execute(
        """
        SELECT p.external_key
        FROM direct_payment_projection_links l
        JOIN payment_transactions p ON p.id=l.payment_id
        JOIN transaction_sources ts ON ts.transaction_id=p.id
        WHERE l.run_id=?
        ORDER BY p.external_key
        """,
        (run_id,),
    ).fetchall()
    integrity = decision_integrity(db)
    passed = (
        not linked_non_card and not unlinked_payments and not legacy_lineage
        and integrity["orphan_count"] == 0
        and not integrity["allocation_target_binding_unconfirmed"]
        and integrity["invalid_target_type_count"] == 0
    )
    if linked_non_card:
        reason = "non_card_direct_source_linked"
    elif unlinked_payments:
        reason = "unlinked_legacy_payment"
    elif legacy_lineage:
        reason = "legacy_source_record_lineage"
    elif integrity["invalid_target_type_count"]:
        reason = "classification_decision_target_type_invalid"
    elif integrity["orphan_count"]:
        reason = "classification_decision_target_orphan"
    elif integrity["allocation_target_binding_unconfirmed"]:
        reason = "allocation_target_binding_unconfirmed"
    else:
        reason = "ok"
    return _gate(
        3,
        GATE_NAMES[2],
        passed,
        reason=reason,
        actual={
            "linked_non_card": linked_non_card,
            "unlinked_payment_count": len(unlinked_payments),
            "unlinked_payment_sample": [
                str(row[0]) for row in unlinked_payments[:10]
            ],
            "legacy_lineage_count": len(legacy_lineage),
            "decision_integrity": integrity,
        },
    )


def _amount_relation_gate(db: object) -> dict[str, object]:
    sign_issues = db.execute(
        """
        SELECT d.card_event_id, d.event_role, d.amount_krw,
               d.transaction_type, s.source_key
        FROM direct_normalized_payments d
        JOIN direct_source_records s ON s.id=d.source_record_id
        WHERE s.source_kind='card_raw'
          AND (
            (d.transaction_type='purchase' AND d.amount_krw<=0)
            OR (
              d.transaction_type IN ('refund','cancellation')
              AND d.amount_krw>=0
            )
          )
        ORDER BY d.card_event_id, d.event_role
        """
    ).fetchall()
    split_issues = db.execute(
        """
        SELECT s.source_key
        FROM direct_source_records s
        JOIN direct_normalized_payments d ON d.source_record_id=s.id
        WHERE s.source_kind='card_raw' AND d.event_role<>'single'
        GROUP BY s.id, s.source_key
        HAVING
          SUM(CASE WHEN d.event_role='approval' AND d.amount_krw>0
                   THEN 1 ELSE 0 END)<>1
          OR
          SUM(CASE WHEN d.event_role='cancellation' AND d.amount_krw<0
                   THEN 1 ELSE 0 END)<>1
        ORDER BY s.source_key
        """
    ).fetchall()
    passed = not sign_issues and not split_issues
    reason = (
        "positive_cancellation_or_invalid_sign"
        if sign_issues
        else "hana_split_pair_invalid"
        if split_issues
        else "ok"
    )
    return _gate(
        4,
        GATE_NAMES[3],
        passed,
        reason=reason,
        actual={
            "sign_issue_count": len(sign_issues),
            "sign_issue_sample": [list(row) for row in sign_issues[:10]],
            "hana_split_issue_count": len(split_issues),
            "hana_split_issue_sample": [
                str(row[0]) for row in split_issues[:10]
            ],
        },
    )


_DIRECT_EVENT_ROLE_SCOPE_FORMAT = "direct-event-role-scope-v1"
_DIRECT_EVENT_ROLE_PATTERN = re.compile(
    r"^card:[0-9a-f]{64}#(single|approval|cancellation)$"
)


def _direct_event_role_scope(rows: Iterable[dict[str, object]]) -> dict[str, object]:
    keys: list[str] = []
    counts_by_source: dict[str, int] = {}
    counts_by_role: dict[str, int] = {}
    counts_by_type: dict[str, int] = {}
    for row in rows:
        key = f"{row['card_event_id']}#{row['event_role']}"
        keys.append(key)
        source = str(row["source_system"])
        role = str(row["event_role"])
        transaction_type = str(row["transaction_type"])
        counts_by_source[source] = counts_by_source.get(source, 0) + 1
        counts_by_role[role] = counts_by_role.get(role, 0) + 1
        counts_by_type[transaction_type] = counts_by_type.get(transaction_type, 0) + 1
    ordered = sorted(keys)
    canonical = ("\n".join(ordered) + "\n").encode("utf-8")
    invalid = [
        key for key in ordered
        if _DIRECT_EVENT_ROLE_PATTERN.fullmatch(key) is None
    ]
    frequencies: dict[str, int] = {}
    for key in ordered:
        frequencies[key] = frequencies.get(key, 0) + 1
    duplicate_keys = sorted(
        key for key, count in frequencies.items() if count > 1
    )
    return {
        "decision_scope_format": _DIRECT_EVENT_ROLE_SCOPE_FORMAT,
        "decision_scope_sha256": _sha256_bytes(canonical),
        "decision_scope_count": len(ordered),
        "decision_scope_unique_count": len(frequencies),
        "decision_scope_invalid_count": len(invalid),
        "decision_scope_invalid_sample": invalid[:10],
        "decision_scope_duplicate_count": sum(
            frequencies[key] - 1 for key in duplicate_keys
        ),
        "decision_scope_duplicate_sample": duplicate_keys[:10],
        "unresolved_direct_event_key_sample": ordered[:10],
        "counts_by_source_system": dict(sorted(counts_by_source.items())),
        "counts_by_event_role": dict(sorted(counts_by_role.items())),
        "counts_by_transaction_type": dict(sorted(counts_by_type.items())),
    }


def _allocation_decision_gate(
    db: object,
    run_id: str,
) -> dict[str, object]:
    payments = db.execute(
        """
        SELECT
            p.external_key,
            d.card_event_id,
            d.event_role,
            e.source_system,
            d.transaction_type
        FROM direct_payment_projection_links l
        JOIN payment_transactions p ON p.id=l.payment_id
        JOIN direct_normalized_payments d ON d.id=l.direct_payment_id
        JOIN direct_card_events e ON e.source_record_id=d.source_record_id
        WHERE l.run_id=?
        ORDER BY p.external_key
        """,
        (run_id,),
    ).fetchall()
    unresolved = len(payments)
    scope = _direct_event_role_scope(
        [
            {
                "external_key": row[0],
                "card_event_id": row[1],
                "event_role": row[2],
                "source_system": row[3],
                "transaction_type": row[4],
            }
            for row in payments
        ]
    )
    return _gate(
        5,
        GATE_NAMES[4],
        False,
        reason="direct_allocation_decision_unimplemented",
        actual={
            "candidate_payment_count": unresolved,
            "resolved_count": 0,
            "unresolved_count": unresolved,
            "unresolved_event_key_sample": [
                str(row[0]) for row in payments[:10]
            ],
            **scope,
            "requirements_status": "direct_decision_contract_unavailable",
        },
    )


def _semantic_regression_gate(
    db: object,
    run_id: str,
    stored_hash: str | None,
    *,
    approved_transitions: Iterable[dict[str, object]] | None,
    comparable_baseline: dict[str, object] | None,
    historical_comparators: list[dict[str, object]],
    repository_root: Path,
) -> dict[str, object]:
    recomputed = candidate_semantic_sha256(db, run_id)
    integrity_ok = bool(stored_hash and stored_hash == recomputed)
    try:
        approvals = validate_approved_transitions(
            approved_transitions,
            expected_source_run_id=run_id,
            expected_after_semantic_sha256=recomputed,
        )
    except ValueError as exc:
        return _gate(
            6,
            GATE_NAMES[5],
            False,
            reason=str(exc),
            actual={
                "integrity_ok": integrity_ok,
                "approvals_provided": 0,
                "approval_mode": "invalid",
                "baseline_status": "not_evaluated",
                "diagnostic_comparators": historical_comparators,
            },
        )
    baseline_descriptor: dict[str, object] | None = None
    baseline_payload: dict[str, object] | None = None
    baseline_error: str | None = None
    current_event_error: str | None = None
    current_event_hashes: dict[str, str] = {}
    current_event_set_hash: str | None = None
    current_scope_hash: str | None = None
    try:
        (
            current_event_hashes,
            current_event_set_hash,
            current_scope_hash,
        ) = _current_direct_event_hashes(db, run_id)
    except ValueError as exc:
        current_event_error = str(exc)
    if current_event_error is None and comparable_baseline is not None:
        try:
            baseline_payload, baseline_descriptor = _load_comparable_baseline(
                comparable_baseline,
                repository_root,
            )
            if baseline_payload is not None:
                baseline_payload, baseline_hashes = _validate_event_baseline(
                    baseline_payload,
                    run_id=run_id,
                )
        except ValueError as exc:
            baseline_error = str(exc)
    if not integrity_ok:
        reason = "candidate_semantic_hash_mismatch"
        baseline_status = "not_evaluated"
        passed = False
    elif current_event_error is not None:
        reason = current_event_error
        baseline_status = "not_evaluated"
        passed = False
    elif comparable_baseline is None:
        reason = "direct_baseline_unavailable"
        baseline_status = "unavailable"
        passed = False
    elif baseline_error is not None:
        reason = baseline_error
        baseline_status = "invalid"
        passed = False
    else:
        assert baseline_payload is not None
        current_keys = set(current_event_hashes)
        baseline_keys = set(baseline_hashes)
        unchanged = sorted(
            key for key in current_keys & baseline_keys
            if current_event_hashes[key] == baseline_hashes[key]
        )
        changed = sorted(
            key for key in current_keys & baseline_keys
            if current_event_hashes[key] != baseline_hashes[key]
        )
        added = sorted(current_keys - baseline_keys)
        removed = sorted(baseline_keys - current_keys)
        diff_actual = {
            "unchanged_count": len(unchanged),
            "unchanged_sample": unchanged[:10],
            "changed_count": len(changed),
            "changed_sample": changed[:10],
            "added_count": len(added),
            "added_sample": added[:10],
            "removed_count": len(removed),
            "removed_sample": removed[:10],
            "current_event_set_sha256": current_event_set_hash,
            "baseline_event_set_sha256": baseline_payload["event_set_sha256"],
            "baseline_source_run_id": baseline_payload["source_run_id"],
            "baseline_input_manifest_sha256": baseline_payload["input_manifest_sha256"],
            "baseline_decision_scope_sha256": baseline_payload["decision_scope_sha256"],
        }
        passed = False
        reason = "direct_baseline_authority_unavailable"
        baseline_status = "diff_computed_unapproved"
    return _gate(
        6,
        GATE_NAMES[5],
        passed,
        reason=reason,
        actual={
            "integrity_ok": integrity_ok,
            "stored_candidate_semantic_sha256": stored_hash,
            "recomputed_candidate_semantic_sha256": recomputed,
            "approvals_provided": len(approvals),
            "approval_mode": "none" if not approvals else "event_level",
            "baseline_status": baseline_status,
            "baseline_descriptor": baseline_descriptor,
            "diagnostic_comparators": historical_comparators,
            "current_event_set_sha256": current_event_set_hash,
            "current_decision_scope_sha256": current_scope_hash,
            **(diff_actual if "diff_actual" in locals() else {}),
        },
    )


def _report_freshness_gate(
    db: object,
    run: dict[str, object],
    expected: dict[str, object],
) -> dict[str, object]:
    checks = {
        "status": (run["status"], "building"),
        "schema_version": (
            run["schema_version"],
            expected["schema_version"],
        ),
        "input_manifest_sha256": (
            run["input_manifest_sha256"],
            expected["input_manifest_sha256"],
        ),
        "candidate_semantic_sha256": (
            run["candidate_semantic_sha256"],
            expected["candidate_semantic_sha256"],
        ),
        "code_commit": (run["code_commit"], expected["code_commit"]),
        "code_bundle_sha256": (
            run["code_bundle_sha256"],
            expected["code_bundle_sha256"],
        ),
        "gate_report_sha256": (run["gate_report_sha256"], None),
    }
    parser_versions = {
        str(row[0])
        for row in db.execute(
            """
            SELECT DISTINCT parser_version
            FROM direct_projection_inputs
            WHERE run_id=?
            """,
            (run["run_id"],),
        ).fetchall()
    }
    checks["parser_version"] = (
        sorted(parser_versions),
        [expected["parser_version"]],
    )
    mismatches = {
        field: {"actual": actual, "expected": wanted}
        for field, (actual, wanted) in checks.items()
        if actual != wanted
    }
    passed = not mismatches
    return _gate(
        7,
        GATE_NAMES[6],
        passed,
        reason="ok" if passed else "run_provenance_stale",
        actual={
            "evaluation_status": run["status"],
            "mismatches": mismatches,
        },
    )


def build_gate_report(
    db_path: Path,
    run_id: str,
    *,
    repository_root: Path = REPOSITORY_ROOT,
    expected_provenance: dict[str, object] | None = None,
    historical_comparators: list[dict[str, object]] | None = None,
    approved_transitions: Iterable[dict[str, object]] | None = None,
    comparable_baseline: dict[str, object] | None = None,
) -> dict[str, object]:
    db = sqlite3.connect(db_path)
    db.execute("PRAGMA foreign_keys = ON")
    try:
        columns = (
            "run_id",
            "status",
            "schema_version",
            "input_manifest_sha256",
            "candidate_semantic_sha256",
            "gate_report_sha256",
            "code_commit",
            "code_bundle_sha256",
        )
        raw_run = db.execute(
            """
            SELECT
                run_id, status, schema_version, input_manifest_sha256,
                candidate_semantic_sha256, gate_report_sha256,
                code_commit, code_bundle_sha256
            FROM direct_projection_runs
            WHERE run_id=?
            """,
            (run_id,),
        ).fetchone()
        if raw_run is None:
            raise ValueError("run_id_not_found")
        run = dict(zip(columns, raw_run))
        expected = expected_provenance or {
            "schema_version": run["schema_version"],
            "parser_version": PARSER_BUNDLE_VERSION,
            "input_manifest_sha256": run["input_manifest_sha256"],
            "candidate_semantic_sha256": run["candidate_semantic_sha256"],
            "code_commit": run["code_commit"],
            "code_bundle_sha256": run["code_bundle_sha256"],
        }
        comparators = historical_comparators or []
        gates = [
            _source_provenance_gate(
                db,
                run_id,
                run,
                repository_root,
            ),
            _projection_cardinality_gate(db, run_id),
            _legacy_leakage_gate(db, run_id),
            _amount_relation_gate(db),
            _allocation_decision_gate(db, run_id),
            _semantic_regression_gate(
                db,
                run_id,
                run["candidate_semantic_sha256"],
                approved_transitions=approved_transitions,
                comparable_baseline=comparable_baseline,
                historical_comparators=comparators,
                repository_root=repository_root,
            ),
            _report_freshness_gate(db, run, expected),
        ]
        return {
            "format_version": 2,
            "run_id": run_id,
            "input_manifest_sha256": run["input_manifest_sha256"],
            "candidate_semantic_sha256": run["candidate_semantic_sha256"],
            "code_commit": run["code_commit"],
            "code_bundle_sha256": run["code_bundle_sha256"],
            "schema_version": run["schema_version"],
            "parser_version": PARSER_BUNDLE_VERSION,
            "passed": all(bool(gate["passed"]) for gate in gates),
            "gates": gates,
            "cutover_policy": (
                "candidate_ready_for_shadow"
                if all(bool(gate["passed"]) for gate in gates)
                else "legacy_path_remains_authoritative"
            ),
        }
    except Exception as exc:
        gates = [
            _gate(
                number,
                name,
                False,
                reason=str(exc),
                actual=None,
            )
            for number, name in enumerate(GATE_NAMES, start=1)
        ]
        return {
            "format_version": 2,
            "run_id": run_id,
            "passed": False,
            "gates": gates,
            "cutover_policy": "legacy_path_remains_authoritative",
        }
    finally:
        db.close()


def _atomic_write_json(path: Path, payload: dict[str, object]) -> None:
    if path.exists():
        raise FileExistsError(f"output_exists:{path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}-",
        suffix=".tmp",
        dir=str(path.parent),
    )
    os.close(descriptor)
    temporary = Path(temporary_name)
    try:
        temporary.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = build_gate_report(args.db, args.run_id)
    report["gate_report_sha256"] = gate_report_sha256(report)
    _atomic_write_json(args.output, report)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
