"""Build an isolated, fail-closed candidate from direct card sources only."""
from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import os
import sqlite3
import subprocess
import tempfile
import uuid
from collections import defaultdict
from datetime import date
from pathlib import Path
from typing import Iterable

from ledger import cardindex
from ledger.domain.direct_sources import import_all
from ledger.domain.direct_structural_rule_admission import (
    admission_manifest,
    normalize_admitted_rule_paths,
    paths_for_package,
)
from ledger.domain.ledger_db import connect, initialize
from ledger.domain.source_adapters import (
    adapt_ota_record,
    adapt_pg_record,
    adapt_service_mail_record,
)
from ledger.domain.transition_gates_v2 import (
    PARSER_BUNDLE_VERSION,
    REQUIRED_INPUTS,
    SCHEMA_VERSION,
    build_gate_report,
    candidate_semantic_sha256,
    gate_report_sha256,
    input_manifest_sha256,
)


HERE = Path(__file__).resolve().parent
REPOSITORY_ROOT = HERE.parents[1]
SCHEMA = HERE / "direct_projection_schema.sql"
RUNTIME_CODE_PATHS = (
    Path("ledger/cardindex.py"),
    Path("ledger/domain/han_normalizer.py"),
    Path("ledger/domain/han_master_candidate.py"),
    Path("ledger/domain/han_master_authority.json"),
    Path("ledger/domain/direct_lineage_annex.py"),
    Path("ledger/domain/schema.sql"),
    Path("ledger/domain/decision_integrity.py"),
    Path("ledger/domain/source_adapters.py"),
    Path("ledger/domain/direct_sources.py"),
    Path("ledger/domain/agoda_booking_evidence.py"),
    Path("ledger/domain/ledger_db.py"),
    Path("ledger/domain/direct_projection_schema.sql"),
    Path("ledger/domain/direct_projection.py"),
    Path("ledger/domain/direct_independent_evidence.py"),
    Path("ledger/domain/direct_current_cancellation_settlement.py"),
    Path("ledger/domain/direct_verified_ota_lodging.py"),
    Path("ledger/domain/direct_geographic_trip_context.py"),
    Path("ledger/domain/direct_gmail_payment_evidence.py"),
    Path("ledger/domain/direct_pg_payment_evidence.py"),
    Path("ledger/domain/direct_current_owner_decision.py"),
    Path("ledger/domain/direct_taiwan_cluster_candidate.py"),
    Path("ledger/domain/direct_ota_reservation_authority.py"),
    Path("ledger/domain/direct_high_coverage_classifier.py"),
    Path("ledger/domain/direct_2025_cost_accounting.py"),
    Path("ledger/domain/direct_2025_payment_terminal.py"),
    Path("ledger/domain/direct_structural_rule_admission.py"),
    Path("ledger/domain/direct_trip_cluster_registry.py"),
    Path("ledger/domain/direct_validated_purchase_classifier.py"),
    Path("ledger/domain/transition_gates_v2.py"),
    Path("ledger/domain/p07_manifest.py"),
    Path("ledger/domain/direct_owner_review.py"),
)


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _canonical_json_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _relative_file(path: Path, repository_root: Path) -> tuple[Path, str]:
    root = repository_root.resolve()
    resolved = path.resolve(strict=True)
    try:
        relative = resolved.relative_to(root)
    except ValueError as exc:
        raise ValueError(f"source_outside_repository:{resolved}") from exc
    if not resolved.is_file():
        raise ValueError(f"source_not_file:{relative.as_posix()}")
    return resolved, relative.as_posix()


def _key_set_sha256(keys: Iterable[str]) -> str:
    ordered = sorted(str(key) for key in keys)
    return _sha256_bytes(("\n".join(ordered) + "\n").encode("utf-8"))


def _read_cards(ledger_dir: Path) -> list[dict[str, object]]:
    return [dict(card) for card in cardindex.build_cards(ledger_dir=ledger_dir)]


def capture_source_snapshots(
    repository_root: Path = REPOSITORY_ROOT,
) -> dict[str, bytes]:
    """Capture every declared input once before any parser sees it."""
    root = repository_root.resolve()
    snapshots: dict[str, bytes] = {}
    for spec in REQUIRED_INPUTS:
        source_kind = str(spec["source_kind"])
        resolved, _ = _relative_file(root / str(spec["relative_path"]), root)
        raw = resolved.read_bytes()
        if not raw:
            raise ValueError(f"source_empty:{spec['relative_path']}")
        snapshots[source_kind] = raw
    if len(snapshots) != len(REQUIRED_INPUTS):
        raise ValueError("source_snapshot_cardinality_invalid")
    return snapshots


def _read_cards_from_snapshots(
    snapshots: dict[str, bytes],
) -> list[dict[str, object]]:
    """Parse card workbooks only from the captured byte snapshots."""
    with tempfile.TemporaryDirectory(prefix="direct-card-snapshot-") as temp_name:
        snapshot_ledger = Path(temp_name)
        card_dir = snapshot_ledger / "newcard" / "conv"
        card_dir.mkdir(parents=True)
        for spec in REQUIRED_INPUTS:
            source_kind = str(spec["source_kind"])
            if not source_kind.startswith("card_raw:"):
                continue
            filename = Path(str(spec["relative_path"])).name
            (card_dir / filename).write_bytes(snapshots[source_kind])
        return [dict(card) for card in cardindex.build_cards(ledger_dir=snapshot_ledger)]


def _card_keys_by_artifact(
    ledger_dir: Path,
    cards: list[dict[str, object]] | None = None,
) -> dict[str, list[str]]:
    by_artifact = {
        spec["source_kind"]: []
        for spec in REQUIRED_INPUTS
        if str(spec["source_kind"]).startswith("card_raw:")
    }
    artifact_for_prefix = {
        str(spec["record_prefix"]).split(":")[-2]: str(spec["source_kind"])
        for spec in REQUIRED_INPUTS
        if str(spec["source_kind"]).startswith("card_raw:")
    }
    for card in cards if cards is not None else _read_cards(ledger_dir):
        raw_record_id = str(card["raw_record_id"])
        artifact = raw_record_id.split(":", 1)[0]
        source_kind = artifact_for_prefix.get(artifact)
        if source_kind is None:
            raise ValueError(f"unexpected_card_parser_input:{artifact}")
        by_artifact[source_kind].append(f"{card['src']}:{raw_record_id}")
    return by_artifact


def _manual_keys(raw: bytes) -> list[str]:
    reader = csv.DictReader(io.StringIO(raw.decode("utf-8-sig"), newline=""))
    if not reader.fieldnames:
        raise ValueError("manual_header_missing")
    rows = list(reader)
    if not rows:
        raise ValueError("manual_source_empty")
    return [f"{row.get('tab')}:{row.get('row')}" for row in rows]


def _classifier_training_keys(raw: bytes) -> list[str]:
    """Inventory historical rows as learning data, never as card evidence."""
    reader = csv.DictReader(io.StringIO(raw.decode("utf-8-sig"), newline=""))
    required = {
        "uid", "src", "use_date", "post_date", "merchant", "bucket",
        "account", "cost_type", "confidence", "tax_conf", "appr", "card4",
    }
    if not reader.fieldnames or not required.issubset(set(reader.fieldnames)):
        raise ValueError("classifier_training_header_invalid")
    rows = list(reader)
    if not rows:
        raise ValueError("classifier_training_source_empty")
    keys = [str(row.get("uid") or "").strip() for row in rows]
    if any(not key for key in keys):
        raise ValueError("classifier_training_uid_missing")
    return keys


def _ota_keys(raw_bytes: bytes) -> list[str]:
    raw = json.loads(raw_bytes.decode("utf-8"))
    rows = raw.get("records", raw) if isinstance(raw, dict) else raw
    if not isinstance(rows, list) or not rows:
        raise ValueError("ota_source_empty")
    keys: list[str] = []
    for index, row in enumerate(rows):
        if not isinstance(row, dict):
            raise ValueError(f"ota_record_not_object:{index}")
        clean = adapt_ota_record(row)
        keys.append(str(clean.get("message_id") or f"row:{index}"))
    return keys


def _pg_keys(raw_bytes: bytes) -> list[str]:
    raw = json.loads(raw_bytes.decode("utf-8"))
    rows = raw.get("records") if isinstance(raw, dict) else None
    if not isinstance(rows, list) or not rows:
        raise ValueError("pg_source_empty")
    keys: list[str] = []
    for index, row in enumerate(rows):
        if not isinstance(row, dict):
            raise ValueError(f"pg_record_not_object:{index}")
        clean = adapt_pg_record(row)
        keys.append(str(clean["message_id"]))
    return keys


def _service_mail_keys(raw_bytes: bytes) -> list[str]:
    raw = json.loads(raw_bytes.decode("utf-8"))
    rows = raw.get("records") if isinstance(raw, dict) else None
    if not isinstance(rows, list) or not rows:
        raise ValueError("service_mail_source_empty")
    keys: list[str] = []
    for index, row in enumerate(rows):
        if not isinstance(row, dict):
            raise ValueError(f"service_mail_record_not_object:{index}")
        clean = adapt_service_mail_record(row)
        keys.append(str(clean["message_id"]))
    return keys


def _trip_keys(raw_bytes: bytes) -> list[str]:
    raw = json.loads(raw_bytes.decode("utf-8"))
    if not isinstance(raw, list) or not raw:
        raise ValueError("trip_schedule_source_empty")
    if any(not isinstance(row, dict) or not isinstance(row.get("tab"), str)
           for row in raw):
        raise ValueError("trip_schedule_source_invalid")
    return [str(row["tab"]) for row in raw]


def _geographic_context_keys(raw_bytes: bytes) -> list[str]:
    from ledger.domain.direct_geographic_trip_context import context_keys

    return context_keys(raw_bytes)


def _lodging_fact_keys(raw_bytes: bytes) -> list[str]:
    from ledger.domain.direct_verified_ota_lodging import (
        validate_lodging_fact_document,
    )
    raw = json.loads(raw_bytes.decode("utf-8"))
    rows = validate_lodging_fact_document(raw)["records"]
    return [str(row["message_id"]) for row in rows]


def _ota_reservation_fact_keys(raw_bytes: bytes) -> list[str]:
    try:
        raw = json.loads(raw_bytes.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("ota_reservation_fact_json_invalid") from exc
    if not isinstance(raw, dict) or not raw:
        raise ValueError("ota_reservation_fact_root_invalid")
    if any(not isinstance(key, str) or not key.strip() for key in raw):
        raise ValueError("ota_reservation_fact_key_invalid")
    if any(not isinstance(value, dict) for value in raw.values()):
        raise ValueError("ota_reservation_fact_row_invalid")
    return [str(key) for key in raw]


def _validate_unique_keys(source_kind: str, keys: list[str]) -> None:
    if not keys:
        raise ValueError(f"parsed_source_empty:{source_kind}")
    if len(keys) != len(set(keys)):
        raise ValueError(f"duplicate_source_key:{source_kind}")


def build_source_inventory(
    ledger_dir: Path,
    repository_root: Path = REPOSITORY_ROOT,
    *,
    cards: list[dict[str, object]] | None = None,
    source_snapshots: dict[str, bytes] | None = None,
) -> list[dict[str, object]]:
    """Inventory and parse the same captured bytes used by source import."""
    root = repository_root.resolve()
    ledger = ledger_dir.resolve(strict=True)
    try:
        ledger.relative_to(root)
    except ValueError as exc:
        raise ValueError(f"ledger_outside_repository:{ledger}") from exc

    snapshots = source_snapshots or capture_source_snapshots(root)
    card_keys = _card_keys_by_artifact(ledger, cards)
    inventory: list[dict[str, object]] = []
    for spec in REQUIRED_INPUTS:
        source_kind = str(spec["source_kind"])
        resolved, relative_path = _relative_file(
            root / str(spec["relative_path"]),
            root,
        )
        raw = snapshots.get(source_kind)
        if raw is None:
            raise ValueError(f"source_snapshot_missing:{source_kind}")
        if not raw:
            raise ValueError(f"source_empty:{relative_path}")
        if source_kind == "manual_ledger":
            keys = _manual_keys(raw)
        elif source_kind == "classifier_training":
            keys = _classifier_training_keys(raw)
        elif source_kind in {"ota_mail", "ota_mail_live"}:
            keys = _ota_keys(raw)
        elif source_kind in {"pg_mail", "pg_mail_supplement"}:
            keys = _pg_keys(raw)
        elif source_kind == "service_mail":
            keys = _service_mail_keys(raw)
        elif source_kind == "trip_schedule":
            keys = _trip_keys(raw)
        elif source_kind == "geographic_trip_context":
            keys = _geographic_context_keys(raw)
        elif source_kind == "ota_lodging_fact":
            keys = _lodging_fact_keys(raw)
        elif source_kind == "ota_reservation_fact":
            keys = _ota_reservation_fact_keys(raw)
        elif source_kind == "current_owner_decision":
            from ledger.domain.direct_current_owner_decision import source_keys
            keys = source_keys(raw)
        else:
            keys = card_keys[source_kind]
        _validate_unique_keys(source_kind, keys)
        lf_hash = None
        if resolved.suffix.lower() != ".xlsx":
            normalized = raw.replace(b"\r\n", b"\n").replace(b"\r", b"\n")
            lf_hash = _sha256_bytes(normalized)
        inventory.append(
            {
                "source_kind": source_kind,
                "relative_path": relative_path,
                "raw_sha256": _sha256_bytes(raw),
                "lf_sha256": lf_hash,
                "byte_count": len(raw),
                "record_count": len(keys),
                "key_set_sha256": _key_set_sha256(keys),
                "parser_version": PARSER_BUNDLE_VERSION,
            }
        )
    inventory.sort(
        key=lambda row: (str(row["source_kind"]), str(row["relative_path"]))
    )
    return inventory


def source_inventory_raw_unchanged(
    inventory: Iterable[dict[str, object]],
    repository_root: Path = REPOSITORY_ROOT,
) -> bool:
    """Recheck immutable input bytes without reparsing every workbook."""
    root = repository_root.resolve()
    for item in inventory:
        try:
            resolved, normalized = _relative_file(
                root / str(item["relative_path"]), root
            )
            raw = resolved.read_bytes()
        except (KeyError, OSError, ValueError):
            return False
        if (
            normalized != str(item["relative_path"])
            or len(raw) != int(item["byte_count"])
            or _sha256_bytes(raw) != str(item["raw_sha256"])
        ):
            return False
    return True


def code_bundle_descriptor(
    repository_root: Path = REPOSITORY_ROOT,
) -> dict[str, object]:
    root = repository_root.resolve()
    files: list[dict[str, str]] = []
    for relative in sorted(RUNTIME_CODE_PATHS, key=lambda path: path.as_posix()):
        resolved, normalized = _relative_file(root / relative, root)
        files.append(
            {
                "relative_path": normalized,
                "raw_sha256": _sha256_bytes(resolved.read_bytes()),
            }
        )
    return {
        "files": files,
        "code_bundle_sha256": _sha256_bytes(_canonical_json_bytes(files)),
    }


def _git_head(repository_root: Path = REPOSITORY_ROOT) -> str:
    return subprocess.check_output(
        ["git", "rev-parse", "HEAD"],
        cwd=repository_root,
        text=True,
    ).strip()


def _apply_schema(db: object) -> None:
    exists=db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='direct_projection_runs'").fetchone()
    if exists:
        _assert_existing_v3_schema(db)
    db.executescript(SCHEMA.read_text(encoding="utf-8"))

def _assert_existing_v3_schema(db:object)->None:
    reference=sqlite3.connect(":memory:")
    try:
        reference.executescript(SCHEMA.read_text(encoding="utf-8"))
        expected={str(x[0]):(str(x[1]),str(x[2])) for x in reference.execute("SELECT name,type,sql FROM sqlite_master WHERE sql IS NOT NULL")}
    finally:reference.close()
    actual_all={str(x[0]):(str(x[1]),str(x[2]),str(x[3])) for x in db.execute("SELECT name,type,sql,tbl_name FROM sqlite_master WHERE sql IS NOT NULL")}
    actual={name:(value[0],value[1]) for name,value in actual_all.items() if name in expected}
    protected={"direct_projection_runs","direct_projection_inputs","direct_payment_projection_links","direct_projection_validations"}
    extras={name for name,value in actual_all.items() if name not in expected and (value[2] in protected or name.startswith("direct_projection"))}
    if actual!=expected or extras:raise ValueError("direct_projection_schema_v3_contract_mismatch")
    versions={str(x[0]) for x in db.execute("SELECT DISTINCT schema_version FROM direct_projection_runs")}
    if versions and versions!={SCHEMA_VERSION}:raise ValueError("direct_projection_schema_version_mismatch")


def _stable_external_key(row: object) -> str:
    identity = {
        "card_event_id": str(row["card_event_id"]),
        "event_role": str(row["event_role"]),
        "source_kind": str(row["source_kind"]),
        "source_key": str(row["source_key"]),
    }
    return "direct:" + _sha256_bytes(_canonical_json_bytes(identity))


def project_card_payments(db: object, run_id: str) -> int:
    """Project card facts and their business fields without legacy matching."""
    conflict = db.execute(
        """SELECT source_kind, source_key FROM direct_source_records
           GROUP BY source_kind, source_key
           HAVING COUNT(DISTINCT source_sha256)>1
           ORDER BY source_kind, source_key LIMIT 1"""
    ).fetchone()
    if conflict:
        raise ValueError(f"source_key_content_conflict:{conflict[0]}:{conflict[1]}")
    rows = db.execute(
        """
        SELECT
            d.id AS direct_payment_id,
            d.event_role,
            d.card_event_id,
            d.amount_krw,
            d.transaction_type,
            s.source_kind,
            s.source_key,
            s.source_sha256,
            e.source_system,
            e.occurred_on,
            e.merchant,
            e.approval_number
        FROM direct_normalized_payments d
        JOIN direct_source_records s ON s.id=d.source_record_id
        JOIN direct_card_events e ON e.source_record_id=d.source_record_id
        WHERE s.source_kind='card_raw'
        ORDER BY s.source_key, d.event_role, d.card_event_id
        """
    ).fetchall()
    if not rows:
        raise ValueError("direct_card_payments_empty")
    for row in rows:
        external_key = _stable_external_key(row)
        fingerprint = _sha256_bytes(
            _canonical_json_bytes(
                {
                    "external_key": external_key,
                    "source_sha256": row["source_sha256"],
                    "source_system": row["source_system"],
                    "occurred_on": row["occurred_on"],
                    "merchant": row["merchant"],
                    "approval_number": row["approval_number"],
                    "amount_krw": row["amount_krw"],
                    "transaction_type": row["transaction_type"],
                }
            )
        )
        cursor = db.execute(
            """
            INSERT INTO payment_transactions(
                external_key, source_event_id, identity_fingerprint,
                source_system, occurred_on, merchant, amount_krw,
                approval_number, transaction_type
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                external_key,
                row["card_event_id"],
                fingerprint,
                row["source_system"],
                row["occurred_on"],
                row["merchant"],
                row["amount_krw"],
                row["approval_number"],
                row["transaction_type"],
            ),
        )
        db.execute(
            """
            INSERT INTO direct_payment_projection_links(
                run_id, direct_payment_id, payment_id
            ) VALUES (?, ?, ?)
            """,
            (run_id, row["direct_payment_id"], cursor.lastrowid),
        )
    return len(rows)


def _approval_digits(value: object) -> str:
    text = str(value or "").strip()
    return text if text and text.isascii() and text.isdigit() and len(text) <= 32 \
        and bool(text.strip("0")) else ""


def _foreign_text(value: object) -> str:
    return str(value or "").strip().lstrip("-")


def project_card_relations(db: object, run_id: str) -> dict[str, int]:
    """Project deterministic relation evidence without claiming classification."""
    rows = db.execute(
        """
        SELECT l.payment_id,p.external_key,p.source_system,p.occurred_on,p.merchant,
               p.approval_number,p.transaction_type,s.payload_json
        FROM direct_payment_projection_links l
        JOIN payment_transactions p ON p.id=l.payment_id
        JOIN direct_normalized_payments d ON d.id=l.direct_payment_id
        JOIN direct_source_records s ON s.id=d.source_record_id
        WHERE l.run_id=? ORDER BY p.external_key
        """, (run_id,)).fetchall()
    if len(rows) != 5328:
        raise ValueError("direct_relation_payment_census_invalid")
    events = []
    for row in rows:
        payload = json.loads(row[7])
        events.append({"payment_id": int(row[0]), "external_key": str(row[1]),
                       "source_system": str(row[2]), "occurred_on": str(row[3]),
                       "merchant": str(row[4]), "approval": row[5],
                       "transaction_type": str(row[6]), "payload": payload})

    purchases = defaultdict(list)
    raw_approvals = defaultdict(set)
    for event in events:
        if event["transaction_type"] != "purchase" or event["source_system"] not in {"HAN", "KBD"}:
            continue
        approval = _approval_digits(event["approval"] or event["payload"].get("appr"))
        card4 = str(event["payload"].get("card4") or "")
        if approval and len(card4) == 4 and card4.isdigit():
            key = (event["source_system"], card4, approval)
            purchases[key].append(event)
            raw_approvals[key].add(str(event["approval"] or event["payload"].get("appr")))
    exact_approval = 0
    for event in events:
        if event["transaction_type"] not in {"cancellation", "refund"} or event["source_system"] not in {"HAN", "KBD"}:
            continue
        original = _approval_digits(event["payload"].get("orig_appr"))
        card4 = str(event["payload"].get("card4") or "")
        targets = purchases.get((event["source_system"], card4, original), [])
        if not original or len(targets) != 1 or len(raw_approvals[(event["source_system"], card4, original)]) != 1:
            continue
        relation_type = "cancels" if event["transaction_type"] == "cancellation" else "refunds"
        db.execute(
            """INSERT INTO transaction_relations(
                 transaction_id,related_transaction_id,relation_type,reference_value,
                 match_method,confidence,relation_status,resolution_code,rationale)
               VALUES (?,?,?,?,?,1.0,'proposed',?,?)""",
            (event["payment_id"], targets[0]["payment_id"], relation_type, original,
             "issuer_card4_original_approval_exact", "exact_unique_original_approval",
             "issuer, card4, and normalized original approval identify one purchase"))
        exact_approval += 1

    kbo_purchases = defaultdict(list)
    kbo_cancellations = defaultdict(list)
    for event in events:
        if event["source_system"] != "KBO":
            continue
        payload = event["payload"]
        key = (str(payload.get("card4") or ""), str(payload.get("currency") or ""),
               _foreign_text(payload.get("foreign")), event["merchant"])
        if event["transaction_type"] == "purchase":
            kbo_purchases[key].append(event)
        elif event["transaction_type"] in {"cancellation", "refund"}:
            kbo_cancellations[key].append(event)
    kbo_singleton = 0
    kbo_atomic_events = 0
    kbo_atomic_groups = 0
    for key in sorted(kbo_cancellations):
        cancellation_rows = kbo_cancellations[key]
        purchase_rows = kbo_purchases[key]
        if not purchase_rows or len(cancellation_rows) != len(purchase_rows):
            continue
        if max(row["occurred_on"] for row in purchase_rows) > min(
                row["occurred_on"] for row in cancellation_rows):
            raise ValueError("direct_relation_kbo_date_order_invalid")
        group_reference = "kbo-group:" + _sha256_bytes(_canonical_json_bytes({
            "key": key, "cancellations": sorted(row["external_key"] for row in cancellation_rows),
            "purchases": sorted(row["external_key"] for row in purchase_rows)}))
        singleton = len(cancellation_rows) == 1
        for event in cancellation_rows:
            relation_type = "cancels" if event["transaction_type"] == "cancellation" else "refunds"
            db.execute(
                """INSERT INTO transaction_relations(
                     transaction_id,related_transaction_id,relation_type,reference_value,
                     match_method,confidence,relation_status,resolution_code,rationale)
                   VALUES (?,?,?,?,?,1.0,'proposed',?,?)""",
                (event["payment_id"], purchase_rows[0]["payment_id"] if singleton else None,
                 relation_type, group_reference,
                 "kbo_card4_currency_foreign_merchant_exact_singleton" if singleton else
                 "kbo_card4_currency_foreign_merchant_unordered_group",
                 "exact_unique_foreign_group" if singleton else "exact_unordered_foreign_group",
                 "individual relation" if singleton else
                 "equal-cardinality group; individual bijection not asserted"))
        if singleton:
            kbo_singleton += 1
        else:
            kbo_atomic_events += len(cancellation_rows)
            kbo_atomic_groups += 1
    return {"exact_original_approval": exact_approval, "kbo_singleton": kbo_singleton,
            "kbo_unordered_events": kbo_atomic_events,
            "kbo_unordered_groups": kbo_atomic_groups,
            "total": exact_approval + kbo_singleton + kbo_atomic_events}


def project_user_approved_taxonomy_decisions(
        db: object, run_id: str, ledger_dir: Path,
        admission: dict[str, object] | None = None) -> dict[str, int]:
    """Legacy/user labels are candidates and cannot be projected directly."""
    raise ValueError("candidate_only_projection_forbidden:user_taxonomy")


def project_manual_frontier_lodging_decisions(
        db: object, run_id: str, ledger_dir: Path,
        admission: dict[str, object] | None = None) -> dict[str, int]:
    """Manual-ledger lodging hints cannot become active decisions."""
    raise ValueError("candidate_only_projection_forbidden:manual_frontier_lodging")


def project_manual_frontier_airfare_decisions(
        db: object, run_id: str, ledger_dir: Path,
        admission: dict[str, object] | None = None) -> dict[str, int]:
    """Manual-ledger airfare hints cannot become active decisions."""
    raise ValueError("candidate_only_projection_forbidden:manual_frontier_airfare")


def project_verified_mutsu_lodging_decisions(
        db: object, run_id: str, ledger_dir: Path,
        admission: dict[str, object] | None = None) -> dict[str, int]:
    """Legacy-bound Mutsu hints require a new direct evidence binding."""
    raise ValueError("candidate_only_projection_forbidden:legacy_bound_mutsu")


def project_verified_kamenoi_lodging_decisions(
        db: object, run_id: str, ledger_dir: Path,
        admission: dict[str, object] | None = None) -> dict[str, int]:
    """Legacy-bound Kamenoi hints require a new direct evidence binding."""
    raise ValueError("candidate_only_projection_forbidden:legacy_bound_kamenoi")


def project_verified_partial_booking_decisions(
        db: object, run_id: str, ledger_dir: Path,
        admission: dict[str, object] | None = None) -> dict[str, int]:
    """Mixed/legacy booking hints cannot become active decisions."""
    raise ValueError("candidate_only_projection_forbidden:mixed_partial_booking")


def project_safe_group_decisions(
        db: object, run_id: str, ledger_dir: Path,
        admission: dict[str, object] | None = None) -> dict[str, int]:
    """Manual-ledger multiset hints cannot become active decisions."""
    raise ValueError("candidate_only_projection_forbidden:manual_exact_group")


def project_historical_carryforward_decisions(
        db: object, run_id: str, ledger_dir: Path,
        admission: dict[str, object] | None = None) -> dict[str, int]:
    """Historical replay is candidate material, never decision authority."""
    raise ValueError("candidate_only_projection_forbidden:historical_replay")


def project_historical_partial_carryforward_decisions(
        db: object, run_id: str, ledger_dir: Path,
        admission: dict[str, object] | None = None) -> dict[str, int]:
    """Partial historical replay is candidate material only."""
    raise ValueError("candidate_only_projection_forbidden:historical_partial_replay")


def project_historical_exact_manual_card_decisions(
        db: object, run_id: str, ledger_dir: Path,
        admission: dict[str, object] | None = None) -> dict[str, int]:
    """Historical/manual-card matches are candidate material only."""
    raise ValueError("candidate_only_projection_forbidden:historical_manual_card")


def project_confirmed_full_axis_allocations(
        db: object,
        run_id: str,
        ledger_dir: Path | None = None,
        admitted_rule_paths: Iterable[str] = (),
    ) -> dict[str, int]:
    """Allocate confirmed payments except structural-rule terminal rows."""
    from ledger.domain.direct_geographic_trip_context import (
        load_allocation_trip_schedule,
        load_verified_trip_target_schedule,
    )
    from ledger.domain.direct_verified_ota_lodging import AUTHORITY_CONTRACT
    from ledger.domain.direct_2025_cost_accounting import (
        ALLOCATION_TARGET as COST_ALLOCATION_TARGET,
        RULE_ID as COST_RULE_ID,
        cost_payment_ids,
    )
    # The normal allocator may only enumerate canonical schedules.  A
    # context-only target (for example 0107_대만) is admitted here only when
    # the same payment already has a typed, independently verified lodging
    # authority.  This keeps historical context from silently becoming a
    # generic allocation target.
    trips = load_allocation_trip_schedule(db)
    admitted_paths = normalize_admitted_rule_paths(admitted_rule_paths)
    cost_payment_id_set = cost_payment_ids(db, run_id)
    verified_ota_context_targets = {
        str(row[0]) for row in db.execute(
            """SELECT DISTINCT allocation_target
               FROM direct_lodging_authorities WHERE run_id=?""",
            (run_id,),
        ).fetchall()
    }
    verified_trips: dict[str, dict[str, object]] | None = None
    rows = db.execute(
        """SELECT p.id,p.amount_krw,p.transaction_type,
                  MAX(hp.rule_path),
                  MAX(CASE WHEN d.dimension='account' THEN d.value END),
                  MAX(CASE WHEN d.dimension='cost_type' THEN d.value END),
                  MAX(CASE WHEN d.dimension='allocation_target' THEN d.value END),
                  MAX(CASE WHEN d.dimension='allocation_target' THEN d.id END),
                  COUNT(*),MIN(d.rule_id),MAX(d.rule_id),
                  MAX(CASE WHEN d.dimension='allocation_target' THEN d.rule_id END)
           FROM direct_payment_projection_links l
           JOIN payment_transactions p ON p.id=l.payment_id
           LEFT JOIN direct_high_coverage_classifier_predictions hp
             ON hp.run_id=l.run_id AND hp.payment_id=p.id
           JOIN current_independently_promoted_decisions d
             ON d.run_id=l.run_id AND d.target_type='payment' AND d.target_id=p.id
           WHERE l.run_id=? AND d.decision_status='confirmed'
             AND d.dimension IN ('account','cost_type','allocation_target')
           GROUP BY p.id,p.amount_krw,p.transaction_type
           HAVING COUNT(*)=3
           ORDER BY p.id""", (run_id,)).fetchall()
    allocations = 0
    nontrip = 0
    for (payment_id, amount, transaction_type, rule_path, account_code, cost_type_code, target_code,
         source_decision_id, decision_count, minimum_rule_id,
         maximum_rule_id, target_rule_id) in rows:
        path_parts = str(rule_path or "").split("|")
        if (
            len(path_parts) > 1
            and path_parts[1] in admitted_paths
            and int(payment_id) not in cost_payment_id_set
        ):
            # Structural admission creates a confirmed terminal disposition,
            # not an allocation plan.  Keep the financial side effects at zero
            # until a separate target/service-period rule is accepted.
            continue
        axis_rule_set = {
            str(row[0]) for row in db.execute(
                """SELECT d.rule_id
                   FROM current_independently_promoted_decisions d
                   WHERE d.run_id=? AND d.target_id=?
                     AND d.target_type='payment'
                     AND d.dimension IN ('account','cost_type','allocation_target')""",
                (run_id, payment_id),
            ).fetchall()
        }
        ota_axis_rules = {
            "ota-reservation-current-card-unique-service-period-v1:" + dimension
            for dimension in ("account", "cost_type", "allocation_target")
        }
        same_rule = bool(minimum_rule_id) and minimum_rule_id == maximum_rule_id
        ota_rule = axis_rule_set == ota_axis_rules
        typed_lodging_rule = axis_rule_set == {AUTHORITY_CONTRACT}
        cost_axis_rules = {
            f"{COST_RULE_ID}:{dimension}"
            for dimension in ("account", "cost_type", "allocation_target")
        }
        cost_rule = axis_rule_set == cost_axis_rules
        if int(decision_count) != 3 or not target_rule_id or not (
            same_rule or ota_rule or cost_rule
        ):
            raise ValueError("direct_full_axis_rule_set_invalid")
        allocation_rule_id = str(
            target_rule_id if ota_rule or cost_rule else minimum_rule_id
        )
        trip = trips.get(str(target_code))
        if (
            trip is None
            and typed_lodging_rule
            and str(target_code) in verified_ota_context_targets
        ):
            if verified_trips is None:
                verified_trips = load_verified_trip_target_schedule(db)
            trip = verified_trips.get(str(target_code))
        if trip is None:
            if str(target_code) not in {
                "취소환불", "기타비용", "여행_미배정", COST_ALLOCATION_TARGET,
            }:
                raise ValueError("direct_full_axis_allocation_target_unknown")
            if str(target_code) == COST_ALLOCATION_TARGET:
                if not cost_rule:
                    raise ValueError("direct_2025_cost_axis_rule_invalid")
                db.execute(
                    """INSERT INTO allocation_targets(target_type,code,name,trip_id)
                       VALUES ('other',?,?,NULL)
                       ON CONFLICT(code) DO UPDATE SET
                         target_type='other',name=excluded.name,trip_id=NULL""",
                    (COST_ALLOCATION_TARGET, COST_ALLOCATION_TARGET),
                )
                target_id = int(db.execute(
                    "SELECT id FROM allocation_targets WHERE code=?",
                    (COST_ALLOCATION_TARGET,),
                ).fetchone()[0])
                plan_id = int(db.execute(
                    """INSERT INTO allocation_plans(
                         payment_id,plan_version,plan_status,confidence,source_decision_id)
                       VALUES (?,1,'confirmed',1.0,?)""",
                    (payment_id, source_decision_id),
                ).lastrowid)
                db.execute(
                    "INSERT INTO cost_allocations(plan_id,target_id,amount_krw) VALUES (?,?,?)",
                    (plan_id, target_id, int(amount)),
                )
                allocations += 1
                nontrip += 1
                continue
            if str(target_code) == "취소환불" and (
                str(account_code) != "비용제외"
                or str(cost_type_code) != "비용제외"
                or allocation_rule_id != "current-card-net-zero-settlement-v1"
            ):
                raise ValueError("direct_cancellation_terminal_axes_invalid")
            outcome = (
                "cancellation_settlement"
                if str(target_code) == "취소환불"
                else "travel_unassigned"
                if str(target_code) == "여행_미배정"
                else "overhead"
            )
            db.execute(
                """
                INSERT INTO allocation_review_cases(
                    payment_id, outcome, reason_code, rationale,
                    review_status, rule_id
                ) VALUES (?, ?, ?, ?, 'confirmed', ?)
                ON CONFLICT(payment_id) DO UPDATE SET
                    outcome=excluded.outcome,
                    reason_code=excluded.reason_code,
                    rationale=excluded.rationale,
                    review_status=excluded.review_status,
                    rule_id=excluded.rule_id,
                    reviewed_at=CURRENT_TIMESTAMP
                """,
                (
                    payment_id,
                    outcome,
                    f"direct_full_axis_{outcome}",
                    (
                        "행사일이 없는 OTA·해외 선결제는 결제일을 행사일로 쓰지 않고 "
                        "여행_미배정으로 자동 종결"
                        if outcome == "travel_unassigned"
                        else "독립 근거로 3개 비용 축이 확정된 비여행 terminal은 배분 없이 종결"
                    ),
                    allocation_rule_id,
                ),
            )
            nontrip += 1
            continue
        signed_reversal = (
            str(transaction_type) in {"cancellation", "refund"}
            and int(amount) < 0
        )
        trip_keys = set(trip)
        valid_trip_keys = {
            frozenset({"tab", "mm", "dd", "region", "window", "starts_on",
                       "ends_on", "service_year", "source_sha256"}),
            frozenset({"tab", "mm", "dd", "region", "window", "starts_on",
                       "ends_on", "service_year", "source_kind", "source_sha256"}),
            frozenset({
                "tab", "event_year", "service_year", "mm", "dd", "region",
                "window", "starts_on", "ends_on", "authority_kind",
                "authority_status", "end_semantics", "source_kind",
                "source_sha256",
            }),
        }
        if (frozenset(trip_keys) not in valid_trip_keys
                or (int(amount) <= 0 and not signed_reversal)):
            raise ValueError("direct_full_axis_allocation_trip_invalid")
        start = date.fromisoformat(str(trip["starts_on"]))
        end = date.fromisoformat(str(trip["ends_on"]))
        db.execute(
            """INSERT INTO trips(code,name,region,starts_on,ends_on,status)
               VALUES (?,?,?,?,?,'planned')
               ON CONFLICT(code) DO UPDATE SET name=excluded.name,region=excluded.region,
                 starts_on=excluded.starts_on,ends_on=excluded.ends_on,
                 status='planned'""",
            (target_code, target_code, trip["region"], start.isoformat(), end.isoformat()))
        trip_id = int(db.execute("SELECT id FROM trips WHERE code=?", (target_code,)).fetchone()[0])
        db.execute(
            """INSERT INTO allocation_targets(target_type,code,name,trip_id)
               VALUES ('trip',?,?,?)
               ON CONFLICT(code) DO UPDATE SET target_type='trip',name=excluded.name,
                 trip_id=excluded.trip_id""", (target_code, target_code, trip_id))
        target_id = int(db.execute(
            "SELECT id FROM allocation_targets WHERE code=?", (target_code,)).fetchone()[0])
        plan_id = int(db.execute(
            """INSERT INTO allocation_plans(
                 payment_id,plan_version,plan_status,confidence,source_decision_id)
               VALUES (?,1,'confirmed',1.0,?)""",
            (payment_id, source_decision_id)).lastrowid)
        db.execute(
            "INSERT INTO cost_allocations(plan_id,target_id,amount_krw) VALUES (?,?,?)",
            (plan_id, target_id, int(amount)))
        allocations += 1
    return {"full_axis_payments": len(rows), "payments": allocations,
            "plans": allocations, "allocations": allocations,
            "nontrip_full_axis_payments": nontrip}


def candidate_semantic_snapshot(db: object, run_id: str) -> str:
    return candidate_semantic_sha256(db, run_id)

def _activate_candidate(db:object,run_id:str,report_hash:str,validation_sha256:str)->None:
    run=db.execute("SELECT input_manifest_sha256,candidate_semantic_sha256,gate_report_sha256 FROM direct_projection_runs WHERE run_id=?",(run_id,)).fetchone()
    if run is None or candidate_semantic_snapshot(db,run_id)!=run[1] or run[2]!=report_hash:
        raise RuntimeError("candidate_activation_revalidation_failed")
    cursor=db.execute("""UPDATE direct_projection_runs SET status='passed',activation_validation_sha256=(
        SELECT validation_sha256 FROM direct_projection_validations WHERE run_id=direct_projection_runs.run_id)
      WHERE run_id=? AND status='building' AND gate_report_sha256=?
        AND EXISTS (SELECT 1 FROM direct_projection_validations v
          WHERE v.run_id=direct_projection_runs.run_id AND v.status='passed'
            AND v.input_manifest_sha256=direct_projection_runs.input_manifest_sha256
            AND v.candidate_semantic_sha256=direct_projection_runs.candidate_semantic_sha256
            AND v.validation_sha256=?)""",(run_id,report_hash,validation_sha256))
    if cursor.rowcount!=1:raise RuntimeError("candidate_activation_precondition_failed")


def _historical_comparators(
    repository_root: Path = REPOSITORY_ROOT,
) -> list[dict[str, object]]:
    root = repository_root.resolve()
    candidates = (
        (
            Path("ledger/baselines/p05_latest_20260725/manifest.json"),
            "legacy_manifest_comparator",
        ),
        (
            Path("ledger/baselines/p6_transition_gate_report.json"),
            "legacy_gate_comparator",
        ),
        (
            Path("ledger/data/classified_v14.csv"),
            "historical_classified_comparator",
        ),
    )
    result: list[dict[str, object]] = []
    for relative, role in candidates:
        resolved, normalized = _relative_file(root / relative, root)
        result.append(
            {
                "relative_path": normalized,
                "role": role,
                "raw_sha256": _sha256_bytes(resolved.read_bytes()),
            }
        )
    return result


def _write_artifact_directory(
    output_dir: Path,
    slug: str,
    report: dict[str, object],
    manifest: dict[str, object],
) -> Path:
    output = output_dir.resolve()
    if output.exists():
        raise FileExistsError(f"output_directory_exists:{output}")
    output.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(
        tempfile.mkdtemp(
            prefix=f".{output.name}-staging-",
            dir=str(output.parent),
        )
    )
    try:
        run_dir = staging / slug
        run_dir.mkdir()
        (run_dir / "gate_report.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        question_queue = _question_queue_payload(report)
        question_queue_bytes = (
            json.dumps(question_queue, ensure_ascii=False, indent=2) + "\n"
        ).encode("utf-8")
        (run_dir / "question_queue.json").write_bytes(question_queue_bytes)
        sealed_manifest = dict(manifest)
        sealed_manifest["question_queue"] = {
            "path": "question_queue.json",
            "raw_sha256": _sha256_bytes(question_queue_bytes),
            "source_gate_report_sha256": question_queue["source_gate_report_sha256"],
        }
        sealed_manifest["manifest_content_sha256"] = _manifest_content_sha256(
            sealed_manifest
        )
        (run_dir / "blocker_manifest.json").write_text(
            json.dumps(sealed_manifest, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        os.replace(staging, output)
        return output / slug
    finally:
        if staging.exists():
            for child in sorted(staging.rglob("*"), reverse=True):
                if child.is_file():
                    child.unlink()
                elif child.is_dir():
                    child.rmdir()
            staging.rmdir()


def _question_queue_payload(report: dict[str, object]) -> dict[str, object]:
    """Return the owner queue first and automatic work as a separate lane."""
    gate5_actual = next(
        (
            gate.get("actual") or {}
            for gate in report.get("gates", [])
            if gate.get("name") == "allocation_and_decision_completeness"
        ),
        {},
    )
    owner_questions = gate5_actual.get("owner_confirmation_question_groups", [])
    travel_questions = gate5_actual.get(
        "travel_unassigned_metadata_question_groups", []
    )
    auto_questions = gate5_actual.get("auto_provisional_question_groups", [])
    structural_rule_requests = gate5_actual.get(
        "structural_rule_requests",
        {
            "contract": "structural-rule-admission-v1",
            "decision_unit": "structural_failure_group",
            "item_level_approval": "forbidden",
            "rule_auto_authorization": False,
            "nonfinal_payment_count": 0,
            "rule_request_group_count": 0,
            "affected_payment_count": 0,
            "overlap_payment_count": 0,
            "coverage_invariant": True,
            "groups": [],
        },
    )
    owner_payment_keys = {
        str(key)
        for group in owner_questions
        if isinstance(group, dict)
        for key in group.get("payment_external_keys", [])
    }
    owner_payment_count = int(
        gate5_actual.get(
            "owner_confirmation_question_payment_count",
            gate5_actual.get("owner_confirmation_payment_count", 0),
        )
    )
    if owner_payment_keys:
        owner_payment_count = len(owner_payment_keys)
    auto_action_count = int(
        gate5_actual.get(
            "auto_provisional_action_count",
            sum(
                int(group.get("payment_count", 0))
                for group in auto_questions
                if isinstance(group, dict)
            ),
        )
    )
    lane_summary = {
        "final_payment_count": int(
            gate5_actual.get("final_count", gate5_actual.get("resolved_count", 0))
        ),
        "nonfinal_payment_count": int(
            gate5_actual.get("nonfinal_count", gate5_actual.get("total_nonfinal_count", 0))
        ),
        "auto_nonfinal_payment_count": int(
            gate5_actual.get("auto_nonfinal_count", 0)
        ),
        "human_question_payment_count": int(
            gate5_actual.get("human_question_payment_count", len(owner_payment_keys))
        ),
        "human_question_group_count": int(
            gate5_actual.get(
                "human_question_group_count",
                int(gate5_actual.get("owner_confirmation_question_group_count", 0))
                + int(gate5_actual.get("travel_unassigned_metadata_question_group_count", 0)),
            )
        ),
        "untriaged_nonfinal_payment_count": int(
            gate5_actual.get("untriaged_nonfinal_count", 0)
        ),
        "lane_partition_invariant": bool(
            gate5_actual.get("lane_partition_invariant", True)
        ),
    }
    return {
        "format_version": 2,
        "source_gate_report_sha256": gate_report_sha256(report),
        "lane_summary": lane_summary,
        # Structural rule requests are a separate authorization channel. They
        # never become one question per payment and do not alter the existing
        # owner/automatic queue ordering.
        "rule_addition_requests": structural_rule_requests,
        "queue_order": [
            "owner_confirmation",
            "travel_unassigned",
            "auto_provisional_summary",
        ],
        "owner_confirmation": {
            "status": "action_required" if owner_questions else "empty",
            "payment_count": owner_payment_count,
            "group_count": gate5_actual.get(
                "owner_confirmation_question_group_count", 0
            ),
            "questions": owner_questions,
        },
        "travel_unassigned": {
            "status": "action_required" if travel_questions else "empty",
            "payment_count": gate5_actual.get(
                "travel_unassigned_metadata_question_count", 0
            ),
            "group_count": gate5_actual.get(
                "travel_unassigned_metadata_question_group_count", 0
            ),
            "questions": travel_questions,
        },
        "auto_provisional_summary": {
            "status": "automatic_processing",
            # The displayed groups are the actionable reservation lane.  The
            # full automatic lane also contains activity placeholders, so its
            # total is exposed separately instead of being mislabeled as the
            # count covered by these groups.
            "payment_count": auto_action_count,
            "automatic_followup_payment_count": auto_action_count,
            "human_question_payment_count": int(
                gate5_actual.get("action_required_count", auto_action_count)
            ),
            "action_required_payment_count": int(
                gate5_actual.get("action_required_count", auto_action_count)
            ),
            "total_auto_provisional_count": int(
                gate5_actual.get("auto_provisional_count", 0)
            ),
            "activity_payment_count": int(
                gate5_actual.get("provisional_activity_count", 0)
            ),
            "total_nonfinal_count": int(
                gate5_actual.get("total_nonfinal_count", 0)
            ),
            "group_count": gate5_actual.get(
                "auto_provisional_question_group_count", 0
            ),
            "detail_group_count": gate5_actual.get(
                "auto_provisional_detail_group_count", 0
            ),
            "groups": auto_questions,
        },
    }


def _atomic_replace_json(path: Path, payload: dict[str, object]) -> None:
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}-",
        suffix=".tmp",
        dir=str(path.parent),
    )
    temporary = Path(temporary_name)
    try:
        sealed=dict(payload);sealed["manifest_content_sha256"]=_manifest_content_sha256(sealed)
        data=(json.dumps(sealed,ensure_ascii=False,indent=2)+"\n").encode()
        view=memoryview(data)
        while view:view=view[os.write(descriptor,view):]
        os.fsync(descriptor);os.close(descriptor);descriptor=-1
        os.replace(temporary, path)
        parent_fd=os.open(path.parent,os.O_RDONLY|getattr(os,"O_DIRECTORY",0))
        try:os.fsync(parent_fd)
        finally:os.close(parent_fd)
    finally:
        if descriptor>=0:os.close(descriptor)
        temporary.unlink(missing_ok=True)

def _manifest_content_sha256(payload:dict[str,object])->str:
    value=dict(payload);value.pop("manifest_content_sha256",None)
    return _sha256_bytes(json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(",",":")).encode())


def _remove_sqlite_artifacts(path: Path) -> None:
    for candidate in (
        path,
        Path(str(path) + "-wal"),
        Path(str(path) + "-shm"),
        Path(str(path) + "-journal"),
    ):
        candidate.unlink(missing_ok=True)

def _seal_private_directory(path:Path,names:tuple[str,...])->None:
    for name in names:
        target=path/name;os.chmod(target,0o400)
        fd=os.open(target,os.O_RDONLY)
        try:os.fsync(fd)
        finally:os.close(fd)
    fd=os.open(path,os.O_RDONLY|getattr(os,"O_DIRECTORY",0))
    try:os.fsync(fd)
    finally:os.close(fd)
    os.chmod(path,0o500)
    parent_fd=os.open(path.parent,os.O_RDONLY|getattr(os,"O_DIRECTORY",0))
    try:os.fsync(parent_fd)
    finally:os.close(parent_fd)


def _remove_new_artifact_directory(path: Path) -> None:
    if not path.exists():
        return
    for child in sorted(path.rglob("*"), reverse=True):
        if child.is_file():
            child.unlink()
        elif child.is_dir():
            child.rmdir()
    path.rmdir()


def _reject_repository_output(
    path: Path,
    repository_root: Path,
    label: str,
) -> None:
    try:
        path.resolve().relative_to(repository_root.resolve())
    except ValueError:
        return
    raise ValueError(f"{label}_inside_repository:{path.resolve()}")


def _normalize_gate_report_readiness(
    report: dict[str, object],
) -> bool:
    """Validate readiness aliases before any artifact can be installed."""
    report.setdefault("release_ready", bool(report.get("passed")))
    report.setdefault("shadow_ready", bool(report.get("passed")))
    report.setdefault(
        "pipeline_status",
        "RELEASE_READY"
        if bool(report["release_ready"])
        else "TRIAGE_PASS"
        if bool(report["shadow_ready"])
        else "BLOCKED",
    )
    release_ready = bool(report["release_ready"])
    shadow_ready = bool(report["shadow_ready"])
    if bool(report.get("passed")) != release_ready:
        raise RuntimeError("gate_report_pass_release_readiness_mismatch")
    if release_ready and not shadow_ready:
        raise RuntimeError("gate_report_release_without_shadow_readiness")
    expected_pipeline_status = (
        "RELEASE_READY"
        if release_ready
        else "TRIAGE_PASS"
        if shadow_ready
        else "BLOCKED"
    )
    if report["pipeline_status"] != expected_pipeline_status:
        raise RuntimeError("gate_report_pipeline_status_mismatch")
    return release_ready


def build_direct_candidate(
    output_db: Path,
    ledger_dir: Path,
    *,
    output_dir: Path,
    manual_path: Path | None = None,
    ota_path: Path | None = None,
    code_commit: str | None = None,
    repository_root: Path = REPOSITORY_ROOT,
    owner_review_output: Path | None = None,
    owner_review_manifest: Path | None = None,
    owner_review_events: Path | None = None,
    han_equality_output:Path|None=None,
    han_authority_sha256:str|None=None,
    structural_rule_package: str = "none",
) -> dict[str, object]:
    """Build a triage report; publish a candidate only when release-ready."""
    admitted_rule_paths = paths_for_package(structural_rule_package)
    root = repository_root.resolve()
    ledger = ledger_dir.resolve(strict=True)
    output_database = output_db.resolve()
    artifact_root = output_dir.resolve()
    _reject_repository_output(output_database, root, "candidate_output")
    _reject_repository_output(artifact_root, root, "artifact_output")
    if owner_review_output is not None:
        owner_target = owner_review_output.resolve()
        _reject_repository_output(owner_target, root, "owner_review_output")
        if owner_target == output_database or output_database in owner_target.parents or owner_target in output_database.parents:
            raise ValueError("owner_review_output_candidate_overlap")
        if owner_target == artifact_root or artifact_root in owner_target.parents or owner_target in artifact_root.parents:
            raise ValueError("owner_review_output_artifact_overlap")
    if output_database.exists():
        raise FileExistsError(f"destination_exists:{output_database}")
    if artifact_root.exists():
        raise FileExistsError(f"output_directory_exists:{artifact_root}")
    if (han_equality_output is None)!=(han_authority_sha256 is None):raise ValueError("han_equality_context_incomplete")
    if han_equality_output is not None:
        _reject_repository_output(han_equality_output.resolve(),root,"han_equality_output")
        if han_equality_output.exists():raise FileExistsError(f"han_equality_output_exists:{han_equality_output}")

    expected_manual = (ledger / "data/manual_v4.csv").resolve(strict=True)
    expected_ota = (ledger / "data/ota_mail_index.json").resolve(strict=True)
    expected_pg_mail = (ledger / "data/pg_mail_index.json").resolve(strict=True)
    expected_pg_mail_supplement = (
        ledger / "data/pg_mail_supplemental_index.json"
    ).resolve(strict=True)
    expected_service_mail = (
        ledger / "data/service_mail_index.json"
    ).resolve(strict=True)
    expected_live_ota = (
        ledger / "data/ota_mail_live_index.json"
    ).resolve(strict=True)
    expected_trip = (ledger / "data/trips.json").resolve(strict=True)
    expected_geographic_context = (
        ledger / "data/current_geographic_trip_context.json"
    ).resolve(strict=True)
    expected_lodging_fact = (
        ledger / "data/ota_lodging_facts_v2.json"
    ).resolve(strict=True)
    expected_reservation = (
        ledger / "data/ota_event_links_verified.json"
    ).resolve(strict=True)
    expected_owner_decision = (
        ledger / "data/current_owner_decisions_v1.json"
    ).resolve(strict=True)
    if manual_path is not None and manual_path.resolve(strict=True) != expected_manual:
        raise ValueError("manual_path_not_in_declared_inventory")
    if ota_path is not None and ota_path.resolve(strict=True) != expected_ota:
        raise ValueError("ota_path_not_in_declared_inventory")

    source_snapshots = capture_source_snapshots(root)
    card_snapshot = _read_cards_from_snapshots(source_snapshots)
    inventory = build_source_inventory(
        ledger, root, cards=card_snapshot, source_snapshots=source_snapshots,
    )
    input_hash = input_manifest_sha256(inventory)
    actual_commit = _git_head(root)
    if code_commit is not None and code_commit != actual_commit:
        raise ValueError(
            f"code_commit_mismatch:expected={actual_commit}:actual={code_commit}"
        )
    bundle = code_bundle_descriptor(root)
    run_id = uuid.uuid4().hex

    output_database.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{output_database.name}-candidate-",
        suffix=".db",
        dir=str(output_database.parent),
    )
    os.close(descriptor)
    temporary_db = Path(temporary_name)
    db = None
    candidate_installed = False
    artifacts_installed = False
    owner_review_installed = False
    # A failed shadow build normally removes its private SQLite file.  Keep it
    # only for an explicit local diagnostic run so row-level evidence can be
    # inspected without changing publication behavior.
    keep_failed_database = os.environ.get(
        "DIRECT_PROJECTION_KEEP_FAILED_DB", ""
    ) == "1"
    activation_pointer_sha256=None
    try:
        db = connect(temporary_db)
        initialize(db)
        _apply_schema(db)
        db.execute(
            """
            INSERT INTO direct_projection_runs(
                run_id, status, schema_version, input_manifest_sha256,
                code_commit, code_bundle_sha256
            ) VALUES (?, 'building', ?, ?, ?, ?)
            """,
            (
                run_id,
                SCHEMA_VERSION,
                input_hash,
                actual_commit,
                bundle["code_bundle_sha256"],
            ),
        )
        for item in inventory:
            db.execute(
                """
                INSERT INTO direct_projection_inputs(
                    run_id, source_kind, relative_path, raw_sha256,
                    lf_sha256, byte_count, key_set_sha256, record_count,
                    parser_version
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    run_id,
                    item["source_kind"],
                    item["relative_path"],
                    item["raw_sha256"],
                    item["lf_sha256"],
                    item["byte_count"],
                    item["key_set_sha256"],
                    item["record_count"],
                    item["parser_version"],
                ),
            )
        import_all(
            db, ledger, expected_manual, expected_ota, cards=card_snapshot,
            source_bytes=source_snapshots, trip_path=expected_trip,
            geographic_context_path=expected_geographic_context,
            lodging_fact_path=expected_lodging_fact,
            reservation_path=expected_reservation,
            owner_decision_path=expected_owner_decision,
            pg_mail_path=expected_pg_mail,
            pg_mail_supplement_path=expected_pg_mail_supplement,
            service_mail_path=expected_service_mail,
            live_ota_path=expected_live_ota,
            # Shadow projection validates card/payment facts; OTA booking
            # materialization belongs to the canonical ingestion pass.
            materialize_agoda_bookings=False,
        )
        from ledger.domain.direct_validated_purchase_classifier import (
            materialize_classifier_training,
            project_validated_purchase_classifier,
            validate_validated_purchase_classifier,
        )
        classifier_training = materialize_classifier_training(
            db, source_snapshots["classifier_training"],
        )
        from ledger.domain.direct_verified_ota_lodging import (
            finalize_lodging_manifest,
            prepare_external_lodging_facts,
            project_verified_lodging_decisions,
            validate_lodging_authorities,
            validate_lodging_manifest,
        )
        prepared_lodging = prepare_external_lodging_facts(db, run_id)
        projected = project_card_payments(db, run_id)
        projected_relations = project_card_relations(db, run_id)
        from ledger.domain.direct_independent_evidence import (
            build_legacy_candidate_audit,
            materialize_current_card_evidence,
        )
        from ledger.domain.direct_current_cancellation_settlement import (
            finalize_cancellation_settlement_manifest,
            project_current_cancellation_settlements,
            validate_cancellation_settlement_authorities,
            validate_cancellation_settlement_manifest,
        )
        from ledger.domain.direct_ota_reservation_authority import (
            project_ota_reservation_authority,
            validate_ota_reservation_authority,
        )
        from ledger.domain.direct_high_coverage_classifier import (
            project_high_coverage_classifier,
            project_high_coverage_provisional_reviews,
            validate_high_coverage_classifier,
        )
        current_evidence = materialize_current_card_evidence(db, run_id)
        legacy_candidate_audit = build_legacy_candidate_audit()
        leaked_decision_count = int(db.execute(
            """SELECT COUNT(*) FROM classification_decisions d
               JOIN direct_payment_projection_links l ON l.payment_id=d.target_id
               WHERE l.run_id=? AND d.target_type='payment'
                 AND d.decision_status IN ('proposed','confirmed','needs_review')""",
            (run_id,),
        ).fetchone()[0])
        if leaked_decision_count != 0:
            raise ValueError("candidate_only_decision_leak")
        db.execute("SAVEPOINT verified_current_authorities")
        try:
            projected_settlement = project_current_cancellation_settlements(
                db, run_id,
            )
            projected_lodging = project_verified_lodging_decisions(db, run_id)
            projected_ota_reservation = project_ota_reservation_authority(
                db, run_id,
            )
            projected_classifier = project_validated_purchase_classifier(
                db, run_id,
            )
            projected_high_coverage = project_high_coverage_classifier(
                db, run_id, admitted_rule_paths,
            )
            projected_high_coverage_provisional = (
                project_high_coverage_provisional_reviews(
                    db, run_id, admitted_rule_paths,
                )
            )
            projected_high_coverage.update(
                projected_high_coverage_provisional
            )
            from ledger.domain.direct_2025_cost_accounting import (
                project_2025_cost_accounting,
                validate_2025_cost_accounting,
            )
            projected_2025_cost = project_2025_cost_accounting(db, run_id)
            projected_allocations = project_confirmed_full_axis_allocations(
                db, run_id, admitted_rule_paths=admitted_rule_paths,
            )
            settlement_validation = validate_cancellation_settlement_authorities(
                db, run_id, require_terminal=True,
            )
            if not settlement_validation["passed"]:
                raise ValueError(
                    "settlement_authority_validation_failed:"
                    + ",".join(
                        str(issue) for issue in settlement_validation["issues"]
                    )
                )
            lodging_validation = validate_lodging_authorities(
                db, run_id, require_allocations=True,
            )
            if not lodging_validation["passed"]:
                raise ValueError(
                    "lodging_authority_validation_failed:"
                    + ",".join(str(issue) for issue in lodging_validation["issues"])
                )
            ota_reservation_validation = validate_ota_reservation_authority(
                db, run_id, require_allocations=True,
            )
            if not ota_reservation_validation["passed"]:
                raise ValueError(
                    "ota_reservation_authority_validation_failed:"
                    + ",".join(
                        str(issue)
                        for issue in ota_reservation_validation["issues"]
                    )
                )
            classifier_validation = validate_validated_purchase_classifier(
                db, run_id, require_allocations=True,
            )
            if not classifier_validation["passed"]:
                raise ValueError(
                    "validated_classifier_validation_failed:"
                    + ",".join(
                        str(issue) for issue in classifier_validation["issues"]
                    )
                )
            high_coverage_validation = validate_high_coverage_classifier(
                db,
                run_id,
                require_allocations=True,
                admitted_rule_paths=admitted_rule_paths,
            )
            if not high_coverage_validation["passed"]:
                raise ValueError(
                    "high_coverage_classifier_validation_failed:"
                    + ",".join(
                        str(issue)
                        for issue in high_coverage_validation["issues"]
                    )
                )
            cost_validation = validate_2025_cost_accounting(db, run_id)
            if not cost_validation["passed"]:
                raise ValueError(
                    "2025_cost_accounting_validation_failed:"
                    + ",".join(
                        str(issue) for issue in cost_validation["issues"]
                    )
                )
            from ledger.domain.direct_2025_payment_terminal import (
                project_2025_payment_terminals,
            )
            projected_2025_terminals = project_2025_payment_terminals(
                db, run_id,
            )
            settlement_manifest = finalize_cancellation_settlement_manifest(
                db, run_id,
            )
            lodging_manifest = finalize_lodging_manifest(db, run_id)
            settlement_manifest_validation = (
                validate_cancellation_settlement_manifest(db, run_id)
            )
            if not settlement_manifest_validation["passed"]:
                raise ValueError(
                    "settlement_manifest_validation_failed:"
                    + ",".join(
                        str(issue)
                        for issue in settlement_manifest_validation["issues"]
                    )
                )
            lodging_manifest_validation = validate_lodging_manifest(db, run_id)
            if not lodging_manifest_validation["passed"]:
                raise ValueError(
                    "lodging_manifest_validation_failed:"
                    + ",".join(
                        str(issue) for issue in lodging_manifest_validation["issues"]
                    )
                )
        except Exception:
            db.execute("ROLLBACK TO verified_current_authorities")
            db.execute("RELEASE verified_current_authorities")
            raise
        else:
            db.execute("RELEASE verified_current_authorities")
        active_decision_count = int(db.execute(
            """SELECT COUNT(*) FROM current_classification_decisions d
               JOIN direct_payment_projection_links l ON l.payment_id=d.target_id
               WHERE l.run_id=? AND d.target_type='payment'
                 AND d.decision_status IN ('proposed','confirmed','needs_review')""",
            (run_id,),
        ).fetchone()[0])
        if active_decision_count != (
            projected_settlement["decisions"] + projected_lodging["decisions"]
            + projected_ota_reservation["decision_count"]
            + projected_classifier["decision_count"]
            + projected_high_coverage["decision_count"]
            + projected_2025_cost["decisions"]
            - projected_2025_cost["superseded_decisions"]
        ):
            raise ValueError("current_authority_active_decision_census_mismatch")
        semantic_hash = candidate_semantic_snapshot(db, run_id)
        db.execute(
            """
            UPDATE direct_projection_runs
            SET candidate_semantic_sha256=?
            WHERE run_id=?
            """,
            (semantic_hash, run_id),
        )
        db.commit()

        han_context=None;han_validation_result=None
        if han_equality_output is not None:
            db.close();db=None
            from ledger.domain.han_master_candidate import build_candidate as build_han_candidate,install_han_equality_validation
            han_context={"directory":han_equality_output,"candidate_db":temporary_db,"run_id":run_id,
              "input_manifest_sha256":input_hash,"candidate_semantic_sha256_expected":semantic_hash,
              "authority_sha256_expected":str(han_authority_sha256),"ledger_dir":ledger,"master_path":ledger/"master_ledger.csv"}
            build_han_candidate(han_equality_output,candidate_db=temporary_db,run_id=run_id,input_manifest_sha256=input_hash,
              candidate_semantic_sha256_expected=semantic_hash,authority_sha256_expected=str(han_authority_sha256),ledger_dir=ledger)
            han_validation_result=install_han_equality_validation(**han_context)

        comparators = _historical_comparators(root)
        expected_provenance = {
            "schema_version": SCHEMA_VERSION,
            "parser_version": PARSER_BUNDLE_VERSION,
            "input_manifest_sha256": input_hash,
            "candidate_semantic_sha256": semantic_hash,
            "code_commit": actual_commit,
            "code_bundle_sha256": bundle["code_bundle_sha256"],
        }
        report = build_gate_report(
            temporary_db,
            run_id,
            repository_root=root,
            expected_provenance=expected_provenance,
            historical_comparators=comparators,
            han_equality_context=han_context,
            require_current_projection_contract=True,
        )
        # Normalize legacy/mocked gate reports before hashing.  ``passed``
        # retains release semantics; the added readiness fields only make the
        # shadow-vs-release distinction explicit.
        release_ready = _normalize_gate_report_readiness(report)
        created_probe=sqlite3.connect(f"file:{temporary_db}?mode=ro&immutable=1",uri=True)
        try:report["run_created_at"]=str(created_probe.execute("SELECT created_at FROM direct_projection_runs WHERE run_id=?",(run_id,)).fetchone()[0])
        finally:created_probe.close()
        if han_validation_result is not None:
            report["han_equality"]={"private_package_path":str(han_equality_output),
              "package_set_sha256":han_validation_result["package_set_sha256"],
              "state":"activated" if bool(report["passed"]) else "private_validated_not_activated"}
        report_hash = gate_report_sha256(report)
        report["gate_report_sha256"] = report_hash
        passed = release_ready
        if db is None:db=connect(temporary_db)
        db.execute(
            """
            UPDATE direct_projection_runs
            SET status=?, gate_report_sha256=?
            WHERE run_id=?
            """,
            ("building" if passed else "failed", report_hash, run_id),
        )
        db.commit()

        manifest = {
            "format_version": 2,
            "run_id": run_id,
            "artifact_state": "pending_activation" if passed else "not_published",
            "cutover_policy": report["cutover_policy"],
            "shadow_ready": bool(report.get("shadow_ready")),
            "release_ready": bool(report.get("release_ready")),
            "pipeline_status": report.get("pipeline_status"),
            "input_manifest_sha256": input_hash,
            "candidate_semantic_sha256": semantic_hash,
            "gate_report_sha256": report_hash,
            "code_commit": actual_commit,
            "code_bundle_sha256": bundle["code_bundle_sha256"],
            "code_bundle": bundle["files"],
            "schema_version": SCHEMA_VERSION,
            "parser_version": PARSER_BUNDLE_VERSION,
            "inputs": inventory,
            "source_scan_policy": {
                "card_workbook_parse_count": 1,
                "activation_recheck": "raw_bytes_only",
            },
            "historical_comparators": comparators,
            "approved_transitions": {
                "provided": 0,
                "mode": "none",
            },
            "projected_relations": projected_relations,
            "classification_policy": {
                "active_dimensions": ["account", "cost_type", "allocation_target"],
                "excluded_dimensions": ["vat_tag"],
                "active_decision_count": active_decision_count,
                "promotion_status": (
                    "settlement_lodging_ota_reservation_and_validated_classifier_promoted"
                ),
                "structural_rule_admission": admission_manifest(
                    admitted_rule_paths
                ),
            },
            "current_card_evidence": current_evidence["manifest"],
            "legacy_candidate_audit": legacy_candidate_audit,
            "classifier_training": classifier_training,
            "projected_classifier": projected_classifier,
            "classifier_validation": classifier_validation,
            "projected_high_coverage": projected_high_coverage,
            "high_coverage_validation": high_coverage_validation,
            "projected_2025_cost_accounting": projected_2025_cost,
            "2025_cost_accounting_validation": cost_validation,
            "projected_2025_payment_terminals": projected_2025_terminals,
            "projected_ota_reservation": projected_ota_reservation,
            "ota_reservation_validation": ota_reservation_validation,
            "projected_settlement": projected_settlement,
            "settlement_authority_validation": settlement_validation,
            "settlement_manifest": {
                "state_sha256": settlement_manifest["state_sha256"],
                "manifest_sha256": settlement_manifest["manifest_sha256"],
                "run_sha256": settlement_manifest["run_sha256"],
            },
            "settlement_manifest_validation": settlement_manifest_validation,
            "prepared_lodging": prepared_lodging,
            "projected_lodging": projected_lodging,
            "lodging_authority_validation": lodging_validation,
            "lodging_manifest": {
                "state_sha256": lodging_manifest["state_sha256"],
                "manifest_sha256": lodging_manifest["manifest_sha256"],
                "run_sha256": lodging_manifest["run_sha256"],
            },
            "lodging_manifest_validation": lodging_manifest_validation,
            "projected_allocations": projected_allocations,
            "failed_gates": [
                str(gate["name"])
                for gate in report["gates"]
                if not bool(gate["passed"])
            ],
            "candidate_payment_count": projected,
            "run_created_at":report["run_created_at"],
            "han_equality":report.get("han_equality"),
        }
        owner_review_result = None
        if owner_review_manifest is not None or owner_review_events is not None:
            if owner_review_manifest is None or owner_review_events is None:
                raise ValueError("owner_review_input_incomplete")
            from ledger.domain.direct_owner_review import load_owner_review
            owner_review_result = load_owner_review(
                owner_review_manifest, owner_review_events, db=db, run_id=run_id,
                report=report, provenance={
                    "source_run_id": run_id, "code_commit": actual_commit,
                    "code_bundle_sha256": bundle["code_bundle_sha256"],
                    "gate_report_sha256": report_hash, "source_inventory": inventory,
                },
            )
        if owner_review_output is not None:
            from ledger.domain.direct_owner_review import build_owner_review, write_owner_review
            owner_review_result = write_owner_review(
                build_owner_review(
                    db, run_id, report,
                    provenance={
                        "code_commit": actual_commit,
                        "code_bundle_sha256": bundle["code_bundle_sha256"],
                        "gate_report_sha256": report_hash,
                        "source_inventory": inventory,
                    },
                ),
                owner_review_output,
                repository_root=root,
            )
            owner_review_installed = True
        slug = f"{run_id}-{semantic_hash[:12]}"

        if passed:
            db.close()
            db = None
            os.replace(temporary_db, output_database)
            candidate_installed = True
            manifest["candidate_db"] = {
                "path": output_database.as_posix(),
                "candidate_semantic_sha256": semantic_hash,
            }
        report_dir = _write_artifact_directory(
            artifact_root,
            slug,
            report,
            manifest,
        )
        artifacts_installed = True
        if passed:
            validation=(report["gates"][3].get("actual") or {}).get("validation")
            if not validation:raise RuntimeError("candidate_activation_validation_missing")
            if han_context is None:raise RuntimeError("candidate_activation_package_context_missing")
            from ledger.domain.han_master_candidate import verify_candidate as verify_han_candidate,_read_regular_nofollow,FILES
            activation_context={**han_context,"candidate_db":output_database}
            verified_package=verify_han_candidate(**activation_context)
            verified_envelope=verified_package["validation_envelope"]
            captured=verified_package["_verified_file_bytes"]
            _seal_private_directory(han_equality_output,FILES)
            activation = connect(output_database)
            try:
                activation.execute("BEGIN IMMEDIATE")
                if {name:_read_regular_nofollow(han_equality_output/name,mode=0o400) for name in FILES}!=captured:
                    raise RuntimeError("candidate_activation_package_changed")
                if any(validation[key]!=verified_envelope[key] for key in verified_envelope):
                    raise RuntimeError("candidate_activation_validation_envelope_mismatch")
                if (not source_inventory_raw_unchanged(inventory, root)
                        or gate_report_sha256(report) != report_hash):
                    raise RuntimeError("candidate_activation_context_changed")
                validation_sha=str(validation["validation_sha256"])
                _activate_candidate(activation,run_id,report_hash,validation_sha)
                activation.commit()
                activation.execute("PRAGMA wal_checkpoint(TRUNCATE)")
                activation.execute("PRAGMA journal_mode=DELETE")
            finally:
                activation.close()
            if any(os.path.lexists(str(output_database)+suffix) for suffix in ("-wal","-shm","-journal")):
                raise RuntimeError("candidate_activation_sidecar_present")
            verify_han_candidate(**{**activation_context,"verification_mode":"activated"})
            os.chmod(output_database,0o400);db_fd=os.open(output_database,os.O_RDONLY)
            try:os.fsync(db_fd)
            finally:os.close(db_fd)
            final_db_sha=_sha256_bytes(output_database.read_bytes())
            manifest["artifact_state"] = "candidate_ready_for_shadow"
            if manifest.get("han_equality"):manifest["han_equality"]["state"]="activated"
            manifest["candidate_db"]["final_seal_sha256"]=final_db_sha
            manifest["candidate_db"]["mode"]="0400"
            # Activation rewrites the blocker manifest after the question
            # queue has already been sealed. Carry that descriptor forward;
            # otherwise the rewrite drops queue provenance and p07 rejects an
            # otherwise valid candidate.
            sealed_manifest = json.loads(
                (report_dir / "blocker_manifest.json").read_text(
                    encoding="utf-8"
                )
            )
            if isinstance(sealed_manifest.get("question_queue"), dict):
                manifest["question_queue"] = sealed_manifest["question_queue"]
            _atomic_replace_json(
                report_dir / "blocker_manifest.json",
                manifest,
            )
            activation_pointer_sha256=_manifest_content_sha256(manifest)
        gate5_actual = next(
            (
                gate.get("actual") or {}
                for gate in report.get("gates", [])
                if gate.get("name") == "allocation_and_decision_completeness"
            ),
            {},
        )
        question_queue = _question_queue_payload(report)
        return {
            "run_id": run_id,
            "passed": passed,
            "shadow_ready": bool(report.get("shadow_ready")),
            "release_ready": bool(report.get("release_ready")),
            "pipeline_status": report.get("pipeline_status"),
            "status": "candidate_ready_for_shadow" if passed else "blocked",
            "cutover_policy": report["cutover_policy"],
            "output_db": output_database.as_posix() if passed else None,
            "report_dir": report_dir.as_posix(),
            "input_manifest_sha256": input_hash,
            "candidate_semantic_sha256": semantic_hash,
            "gate_report_sha256": report_hash,
            "failed_gates": manifest["failed_gates"],
            "owner_review": owner_review_result,
            "owner_confirmation_questions": gate5_actual.get(
                "owner_confirmation_question_groups", []
            ),
            "travel_unassigned_metadata_questions": gate5_actual.get(
                "travel_unassigned_metadata_question_groups", []
            ),
            "auto_provisional_questions": gate5_actual.get(
                "auto_provisional_question_groups", []
            ),
            "question_queue": question_queue,
            "question_queue_counts": {
                "owner_confirmation_groups": gate5_actual.get(
                    "owner_confirmation_question_group_count", 0
                ),
                "owner_confirmation_payments": gate5_actual.get(
                    "owner_confirmation_payment_count",
                    gate5_actual.get("pending_owner_confirmation_count", 0),
                ),
                "relationship_question_groups": gate5_actual.get(
                    "relationship_question_group_count", 0
                ),
                "user_question_groups": gate5_actual.get(
                    "user_question_group_count", 0
                ),
                "user_question_payments": gate5_actual.get(
                    "user_question_payment_count", 0
                ),
                "travel_unassigned_payments": gate5_actual.get(
                    "travel_unassigned_metadata_question_count", 0
                ),
                "travel_unassigned_groups": gate5_actual.get(
                    "travel_unassigned_metadata_question_group_count", 0
                ),
                "auto_provisional_payments": gate5_actual.get(
                    "auto_provisional_count", 0
                ),
                "auto_provisional_groups": gate5_actual.get(
                    "auto_provisional_question_group_count", 0
                ),
                "auto_provisional_detail_groups": gate5_actual.get(
                    "auto_provisional_detail_group_count", 0
                ),
                "final_payments": gate5_actual.get("final_count", 0),
                "nonfinal_payments": gate5_actual.get("nonfinal_count", 0),
                "auto_nonfinal_payments": gate5_actual.get(
                    "auto_nonfinal_count", 0
                ),
                "human_question_payments": gate5_actual.get(
                    "human_question_payment_count", 0
                ),
                "human_question_groups": gate5_actual.get(
                    "human_question_group_count", 0
                ),
                "untriaged_nonfinal_payments": gate5_actual.get(
                    "untriaged_nonfinal_count", 0
                ),
                "lane_partition_invariant": gate5_actual.get(
                    "lane_partition_invariant", False
                ),
            },
            "activation_pointer_sha256":activation_pointer_sha256,
        }
    except Exception:
        if db is not None:
            try:
                db.execute(
                    """
                    UPDATE direct_projection_runs
                    SET status='failed'
                    WHERE run_id=?
                    """,
                    (run_id,),
                )
                db.commit()
            except Exception:
                pass
        if candidate_installed:
            _remove_sqlite_artifacts(output_database)
        # A successfully published diagnostic report is retained on later
        # activation failure; it is the auditable explanation for no cutover.
        if owner_review_installed and owner_review_output is not None:
            _remove_new_artifact_directory(owner_review_output.resolve())
        raise
    finally:
        if db is not None:
            db.close()
        if not keep_failed_database:
            _remove_sqlite_artifacts(temporary_db)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-db", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--ledger-dir", type=Path, required=True)
    parser.add_argument("--manual", type=Path)
    parser.add_argument("--ota", type=Path)
    parser.add_argument("--code-commit")
    parser.add_argument("--owner-review-output", type=Path, help="write an external validation template")
    parser.add_argument("--owner-review-manifest", type=Path)
    parser.add_argument("--owner-review-events", type=Path)
    parser.add_argument(
        "--han-equality-output",
        type=Path,
        help="write the external private HAN equality validation package",
    )
    parser.add_argument(
        "--han-authority-sha256",
        help="approved HAN authority hash; computed from the declared ledger authority when omitted",
    )
    parser.add_argument(
        "--success-level",
        choices=("release", "shadow"),
        default="release",
        help=(
            "process exit criterion; release preserves legacy fail-closed "
            "behavior, while shadow succeeds for a lossless triage report"
        ),
    )
    parser.add_argument(
        "--structural-rule-package",
        choices=("none", "package-b-core", "package-b", "package-c"),
        default="none",
        help=(
            "select a grouped structural-rule exception package; default none "
            "keeps all provisional paths fail-closed"
        ),
    )
    args = parser.parse_args()
    han_authority_sha256 = args.han_authority_sha256
    if args.han_equality_output is not None and han_authority_sha256 is None:
        authority_path = (
            args.ledger_dir / "domain" / "han_master_authority.json"
        ).resolve(strict=True)
        han_authority_sha256 = hashlib.sha256(
            authority_path.read_bytes()
        ).hexdigest()
    result = build_direct_candidate(
        args.output_db,
        args.ledger_dir,
        output_dir=args.output_dir,
        manual_path=args.manual,
        ota_path=args.ota,
        code_commit=args.code_commit,
        owner_review_output=args.owner_review_output,
        owner_review_manifest=args.owner_review_manifest,
        owner_review_events=args.owner_review_events,
        han_equality_output=args.han_equality_output,
        han_authority_sha256=han_authority_sha256,
        structural_rule_package=args.structural_rule_package,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    success = (
        bool(result["shadow_ready"])
        if args.success_level == "shadow"
        else bool(result["passed"])
    )
    return 0 if success else 1


if __name__ == "__main__":
    raise SystemExit(main())
