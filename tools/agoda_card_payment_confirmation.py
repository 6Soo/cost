#!/usr/bin/env python3
"""Create a private, display-only Agoda card/booking confirmation candidate.

The portal staging run proves that a completed Agoda reservation exists.  It
does not, by itself, prove which card paid for it.  This tool therefore
promotes only the already-authorized OTA facts whose card4/currency/foreign
amount match is one-to-one in the current card projection and whose service
period matches the portal staging row.

The tool never mutates the source candidate DB, ledger DB, OTA DB, or user
workbook.  It publishes a new 0600 SQLite copy and a redacted aggregate report
using no-replace hard-link publication.  The resulting ``confirmed`` status
means only "confirmed booking-to-payment relation"; it is not accounting
posting, allocation approval, or release finality.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import sqlite3
import stat
import tempfile
from collections import Counter
from datetime import date
from pathlib import Path
from typing import Any


RULE_ID = "agoda-portal-card-current-unique-service-period-v1"
ARTIFACT_TYPE = "agoda-card-payment-confirmation-candidate-v1"
REDACTION_VERSION = "agoda-card-confirmation-redacted-v1"
EXPECTED_RUN_ID = "agoda-portal-20260815-pages-merged-r3"
EXPECTED_CAPTURE_SET_SHA256 = (
    "13ebe9f5a961c7618173801b307721bd7ba1fe5ece3465411f4ca968f3bf5321"
)
EXPECTED_STAGING_TARGET_COUNT = 311
GENERIC_LINK_STATUS = "proposed"


def _canonical(value: object) -> bytes:
    return (
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
        + "\n"
    ).encode("utf-8")


def _sha_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha_text(value: object) -> str:
    return _sha_bytes(str(value).encode("utf-8"))


def _sha_json(value: object) -> str:
    return _sha_bytes(_canonical(value))


def _sha_path(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _mode(path: Path) -> int:
    return stat.S_IMODE(path.stat().st_mode)


def _require_private_file(path: Path) -> None:
    if path.is_symlink() or not path.is_file() or _mode(path) != 0o600:
        raise ValueError(f"private_file_contract_invalid:{path}")


def _connect_immutable(path: Path) -> sqlite3.Connection:
    return sqlite3.connect(f"file:{path.resolve()}?mode=ro&immutable=1", uri=True)


def _integrity(db: sqlite3.Connection) -> None:
    result = db.execute("PRAGMA integrity_check").fetchone()
    if result != ("ok",):
        raise ValueError("sqlite_integrity_check_failed")


def _table_columns(db: sqlite3.Connection, table: str) -> list[str]:
    return [str(row[1]) for row in db.execute(f'PRAGMA table_info("{table}")')]


def _table_exists(db: sqlite3.Connection, table: str) -> bool:
    return bool(
        db.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)
        ).fetchone()
    )


def _period_dates(value: object) -> tuple[str, str]:
    match = re.fullmatch(r"(\d{2})(\d{2})(?:_(\d{2})(\d{2}))?", str(value or ""))
    if match is None:
        raise ValueError("ota_service_period_invalid")
    try:
        start = date(2026, int(match.group(1)), int(match.group(2)))
        end = date(
            2026,
            int(match.group(3) or match.group(1)),
            int(match.group(4) or match.group(2)),
        )
    except ValueError as exc:
        raise ValueError("ota_service_period_invalid") from exc
    if end < start:
        raise ValueError("ota_service_period_invalid")
    return start.isoformat(), end.isoformat()


def _staging_snapshot(path: Path) -> dict[str, Any]:
    _require_private_file(path)
    db = _connect_immutable(path)
    try:
        _integrity(db)
        required = {
            "run_manifest",
            "merge_manifest",
            "agoda_pages",
            "agoda_completed_bookings",
        }
        if not required <= {
            row[0]
            for row in db.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }:
            raise ValueError("agoda_staging_schema_incomplete")
        run = db.execute(
            "SELECT run_id,captured_pages,target_year FROM run_manifest"
        ).fetchone()
        merge = db.execute(
            "SELECT run_id,capture_set_sha256,target_year_only,source_total_cards,published_rows "
            "FROM merge_manifest"
        ).fetchone()
        pages = db.execute(
            "SELECT COUNT(*),COALESCE(SUM(card_count),0),COALESCE(SUM(target_year_count),0),"
            "COALESCE(SUM(no_service_date_count),0),COALESCE(SUM(duplicate_booking_id_count),0) "
            "FROM agoda_pages"
        ).fetchone()
        bookings = db.execute(
            "SELECT COUNT(*),COUNT(DISTINCT booking_id_sha256),"
            "COALESCE(SUM(is_2026),0),COUNT(DISTINCT page_no) "
            "FROM agoda_completed_bookings"
        ).fetchone()
        if run is None or merge is None:
            raise ValueError("agoda_staging_manifest_missing")
        if (
            str(run[0]) != EXPECTED_RUN_ID
            or int(run[1]) != 13
            or int(run[2]) != 2026
            or str(merge[0]) != EXPECTED_RUN_ID
            or str(merge[1]) != EXPECTED_CAPTURE_SET_SHA256
            or int(merge[2]) != 1
            or int(merge[3]) != 481
            or int(merge[4]) != EXPECTED_STAGING_TARGET_COUNT
            or tuple(int(value) for value in pages)
            != (13, 481, EXPECTED_STAGING_TARGET_COUNT, 0, 0)
            or tuple(int(value) for value in bookings[:3])
            != (EXPECTED_STAGING_TARGET_COUNT, EXPECTED_STAGING_TARGET_COUNT, EXPECTED_STAGING_TARGET_COUNT)
        ):
            raise ValueError("agoda_staging_completeness_invalid")
        rows = db.execute(
            "SELECT row_id,page_no,booking_id,booking_id_sha256,service_start_on,"
            "service_end_on,status,card_sha256 FROM agoda_completed_bookings "
            "ORDER BY row_id"
        ).fetchall()
        result: dict[str, dict[str, Any]] = {}
        for row in rows:
            booking_id = str(row[2])
            if booking_id in result:
                raise ValueError("agoda_staging_booking_id_duplicate")
            if _sha_text(booking_id) != str(row[3]):
                raise ValueError("agoda_staging_booking_hash_invalid")
            if not re.fullmatch(r"2026-\d{2}-\d{2}", str(row[4])) or not re.fullmatch(
                r"2026-\d{2}-\d{2}", str(row[5])
            ):
                raise ValueError("agoda_staging_service_period_invalid")
            result[booking_id] = {
                "row_id": int(row[0]),
                "page_no": int(row[1]),
                "booking_id_sha256": str(row[3]),
                "service_start_on": str(row[4]),
                "service_end_on": str(row[5]),
                "status": str(row[6]),
                "card_sha256": str(row[7]),
            }
        return {
            "run_id": EXPECTED_RUN_ID,
            "capture_set_sha256": EXPECTED_CAPTURE_SET_SHA256,
            "sha256": _sha_path(path),
            "bookings": result,
            "target_count": len(result),
        }
    finally:
        db.close()


def _base_snapshot(path: Path) -> dict[str, Any]:
    if path.is_symlink() or not path.is_file():
        raise ValueError("base_candidate_missing")
    db = _connect_immutable(path)
    try:
        _integrity(db)
        required = {
            "payment_transactions",
            "direct_promotion_evidence",
            "direct_normalized_payments",
            "direct_payment_projection_links",
            "direct_source_records",
            "classification_decisions",
            "bookings",
            "payment_booking_links",
        }
        names = {
            row[0]
            for row in db.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
        if not required <= names:
            raise ValueError("base_candidate_schema_incomplete")
        projection = db.execute(
            "SELECT run_id,status FROM direct_projection_runs ORDER BY created_at DESC LIMIT 1"
        ).fetchone()
        if projection is None:
            raise ValueError("base_projection_run_missing")
        side_effects = {
            "payment_count": int(db.execute("SELECT COUNT(*) FROM payment_transactions").fetchone()[0]),
            "allocation_plan_count": int(db.execute("SELECT COUNT(*) FROM allocation_plans").fetchone()[0]),
            "cost_allocation_count": int(db.execute("SELECT COUNT(*) FROM cost_allocations").fetchone()[0]),
            "journal_count": int(db.execute("SELECT COUNT(*) FROM journal_entries").fetchone()[0]),
            "decision_count": int(db.execute("SELECT COUNT(*) FROM classification_decisions").fetchone()[0]),
            "posting_batch_count": int(db.execute("SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name='direct_accounting_posting_batches'").fetchone()[0]) and int(db.execute("SELECT COUNT(*) FROM direct_accounting_posting_batches").fetchone()[0]),
            "posting_line_count": int(db.execute("SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name='direct_accounting_posting_lines'").fetchone()[0]) and int(db.execute("SELECT COUNT(*) FROM direct_accounting_posting_lines").fetchone()[0]),
            "reversal_count": int(db.execute("SELECT COUNT(*) FROM direct_high_coverage_reversal_inheritance").fetchone()[0]),
        }
        return {
            "sha256": _sha_path(path),
            "projection_run_id": str(projection[0]),
            "projection_status": str(projection[1]),
            "side_effects": side_effects,
        }
    finally:
        db.close()


def _load_authorized_matches(
    db: sqlite3.Connection, staging: dict[str, Any]
) -> list[dict[str, Any]]:
    rows = db.execute(
        """SELECT e.run_id,e.direct_event_key,e.source_key,e.source_sha256,e.fact_sha256,
                  l.payment_id,p.transaction_type,p.amount_krw,s.payload_json
           FROM direct_promotion_evidence e
           JOIN direct_normalized_payments d
             ON d.card_event_id || '#' || d.event_role=e.direct_event_key
           JOIN direct_payment_projection_links l
             ON l.run_id=e.run_id AND l.direct_payment_id=d.id
           JOIN payment_transactions p ON p.id=l.payment_id
           JOIN direct_source_records s
             ON s.source_kind=e.source_kind AND s.source_key=e.source_key
            AND s.source_sha256=e.source_sha256
           WHERE e.evidence_kind='verified_booking'
             AND e.authority_status='verified_external'
             AND e.source_kind='ota_reservation_fact'
           ORDER BY e.direct_event_key"""
    ).fetchall()
    matches: list[dict[str, Any]] = []
    for row in rows:
        payload = json.loads(str(row[8]))
        if payload.get("verification_source") != "agoda_booking_page":
            continue
        booking_number = str(payload.get("booking_id") or "")
        portal = staging["bookings"].get(booking_number)
        if portal is None:
            raise ValueError("authorized_agoda_booking_not_in_portal_staging")
        start_on, end_on = _period_dates(payload.get("period"))
        if (start_on, end_on) != (
            portal["service_start_on"],
            portal["service_end_on"],
        ):
            raise ValueError("ota_portal_service_period_mismatch")
        payment_id = int(row[5])
        axes = db.execute(
            """SELECT COUNT(DISTINCT dimension) FROM classification_decisions
               WHERE target_type='payment' AND target_id=?
                 AND dimension IN ('account','cost_type','allocation_target')
                 AND decision_status='confirmed' AND superseded_by_id IS NULL""",
            (payment_id,),
        ).fetchone()[0]
        if int(axes) != 3 or str(row[6]) != "purchase" or int(row[7]) <= 0:
            raise ValueError("authorized_agoda_payment_not_current_confirmed_purchase")
        matches.append(
            {
                "run_id": str(row[0]),
                "direct_event_key": str(row[1]),
                "source_key_sha256": _sha_text(row[2]),
                "source_sha256": str(row[3]),
                "fact_sha256": str(row[4]),
                "payment_id": payment_id,
                "booking_number": booking_number,
                "booking_id_sha256": portal["booking_id_sha256"],
                "portal_card_sha256": portal["card_sha256"],
                "page_no": portal["page_no"],
                "row_id": portal["row_id"],
                "service_start_on": portal["service_start_on"],
                "service_end_on": portal["service_end_on"],
                "status": portal["status"],
            }
        )
    if len(matches) != 5:
        raise ValueError("authorized_agoda_match_count_invalid")
    if len({item["payment_id"] for item in matches}) != len(matches):
        raise ValueError("authorized_agoda_payment_cardinality_invalid")
    if len({item["booking_number"] for item in matches}) != len(matches):
        raise ValueError("authorized_agoda_booking_cardinality_invalid")
    if db.execute("SELECT COUNT(*) FROM payment_booking_links").fetchone()[0] != 0:
        raise ValueError("base_candidate_has_existing_booking_links")
    return matches


def _create_audit_tables(db: sqlite3.Connection) -> None:
    db.executescript(
        """
        CREATE TABLE IF NOT EXISTS direct_agoda_card_booking_confirmations (
          confirmation_id TEXT PRIMARY KEY,
          confirmation_run_id TEXT NOT NULL,
          payment_id INTEGER NOT NULL UNIQUE REFERENCES payment_transactions(id),
          booking_id INTEGER NOT NULL UNIQUE REFERENCES bookings(id),
          rule_id TEXT NOT NULL,
          relation_status TEXT NOT NULL CHECK(relation_status='confirmed'),
          candidate_only INTEGER NOT NULL CHECK(candidate_only=1),
          publication_status TEXT NOT NULL CHECK(publication_status='private_candidate_only'),
          confidence REAL NOT NULL CHECK(confidence=1.0),
          match_method TEXT NOT NULL,
          ota_source_key_sha256 TEXT NOT NULL CHECK(length(ota_source_key_sha256)=64),
          ota_fact_sha256 TEXT NOT NULL CHECK(length(ota_fact_sha256)=64),
          current_event_key_sha256 TEXT NOT NULL CHECK(length(current_event_key_sha256)=64),
          current_source_sha256 TEXT NOT NULL CHECK(length(current_source_sha256)=64),
          portal_booking_id_sha256 TEXT NOT NULL CHECK(length(portal_booking_id_sha256)=64),
          portal_card_sha256 TEXT NOT NULL CHECK(length(portal_card_sha256)=64),
          staging_db_sha256 TEXT NOT NULL CHECK(length(staging_db_sha256)=64),
          capture_set_sha256 TEXT NOT NULL CHECK(length(capture_set_sha256)=64),
          portal_page_no INTEGER NOT NULL CHECK(portal_page_no>0),
          service_start_on TEXT NOT NULL,
          service_end_on TEXT NOT NULL,
          accounting_side_effects INTEGER NOT NULL CHECK(accounting_side_effects=0),
          posting_side_effects INTEGER NOT NULL CHECK(posting_side_effects=0),
          payload_json TEXT NOT NULL,
          UNIQUE(confirmation_run_id,payment_id),
          UNIQUE(confirmation_run_id,booking_id)
        );
        CREATE TABLE IF NOT EXISTS direct_agoda_card_booking_confirmation_manifests (
          confirmation_run_id TEXT PRIMARY KEY,
          artifact_type TEXT NOT NULL CHECK(artifact_type='agoda-card-payment-confirmation-candidate-v1'),
          rule_id TEXT NOT NULL,
          base_candidate_sha256 TEXT NOT NULL CHECK(length(base_candidate_sha256)=64),
          staging_db_sha256 TEXT NOT NULL CHECK(length(staging_db_sha256)=64),
          capture_set_sha256 TEXT NOT NULL CHECK(length(capture_set_sha256)=64),
          base_projection_run_id TEXT NOT NULL,
          staging_target_count INTEGER NOT NULL CHECK(staging_target_count=311),
          confirmed_relation_count INTEGER NOT NULL CHECK(confirmed_relation_count=5),
          held_relation_count INTEGER NOT NULL CHECK(held_relation_count=306),
          held_nonunique_card_count INTEGER NOT NULL CHECK(held_nonunique_card_count=1),
          held_no_unique_evidence_count INTEGER NOT NULL CHECK(held_no_unique_evidence_count=305),
          membership_sha256 TEXT NOT NULL CHECK(length(membership_sha256)=64),
          policy_sha256 TEXT NOT NULL CHECK(length(policy_sha256)=64),
          report_sha256 TEXT NOT NULL CHECK(length(report_sha256)=64),
          publication_status TEXT NOT NULL CHECK(publication_status='private_candidate_only'),
          payload_json TEXT NOT NULL
        );
        """
    )


def _insert_candidate(
    db: sqlite3.Connection,
    *,
    staging: dict[str, Any],
    base: dict[str, Any],
    matches: list[dict[str, Any]],
    confirmation_run_id: str,
    membership_sha256: str,
) -> None:
    staging_path = str(staging["path"])
    document_sha = str(staging["sha256"])
    db.execute(
        """INSERT OR IGNORE INTO source_documents(source_kind,path,sha256)
           VALUES ('agoda_portal_staging',?,?)""",
        (staging_path, document_sha),
    )
    document_id = int(
        db.execute(
            "SELECT id FROM source_documents WHERE source_kind='agoda_portal_staging' AND path=? AND sha256=?",
            (staging_path, document_sha),
        ).fetchone()[0]
    )
    for item in matches:
        db.execute(
            """INSERT OR IGNORE INTO source_records(
                 document_id,row_number,natural_key,raw_payload)
               VALUES (?,?,?,?)""",
            (
                document_id,
                int(item["row_id"]),
                item["booking_id_sha256"],
                json.dumps(
                    {
                        "source": "agoda_portal_staging",
                        "redaction_version": REDACTION_VERSION,
                        "booking_id_sha256": item["booking_id_sha256"],
                        "page_no": item["page_no"],
                        "service_start_on": item["service_start_on"],
                        "service_end_on": item["service_end_on"],
                        "status": item["status"],
                        "card_sha256": item["portal_card_sha256"],
                        "capture_set_sha256": staging["capture_set_sha256"],
                    },
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                ),
            ),
        )
        source_record_id = int(
            db.execute(
                "SELECT id FROM source_records WHERE document_id=? AND row_number=?",
                (document_id, int(item["row_id"])),
            ).fetchone()[0]
        )
        db.execute(
            """INSERT OR IGNORE INTO bookings(
                 provider,booking_number,product_type,label,service_start_on,
                 service_end_on,status)
               VALUES ('agoda',?,'lodging','Agoda 완료예약',?,?, 'completed')""",
            (
                item["booking_number"],
                item["service_start_on"],
                item["service_end_on"],
            ),
        )
        booking_id = int(
            db.execute(
                "SELECT id FROM bookings WHERE provider='agoda' AND booking_number=?",
                (item["booking_number"],),
            ).fetchone()[0]
        )
        db.execute(
            """INSERT OR IGNORE INTO booking_identifiers(
                 booking_id,provider,identifier,identifier_type,identifier_status,rule_id)
               VALUES (?,'agoda',?,'booking_number','confirmed',?)""",
            (booking_id, item["booking_number"], RULE_ID),
        )
        db.execute(
            """INSERT OR IGNORE INTO booking_provider_reviews(
                 booking_id,proposed_provider,review_status,reason_code,rationale,rule_id)
               VALUES (?,'agoda','confirmed','verified_ota_portal_card_singleton',
                       'OTA 예약·포털 서비스기간·현재 카드의 양방향 단일성 검증',?)""",
            (booking_id, RULE_ID),
        )
        db.execute(
            """INSERT OR IGNORE INTO booking_service_period_evidence(
                 booking_id,start_on,end_on,date_precision,original_text,source_record_id,
                 evidence_status,redaction_version)
               VALUES (?,?,?,'day','agoda portal staging service period',?,
                       'confirmed',?)""",
            (
                booking_id,
                item["service_start_on"],
                item["service_end_on"],
                source_record_id,
                REDACTION_VERSION,
            ),
        )
        existing_payment_link = db.execute(
            """SELECT payment_id,booking_id,link_status FROM payment_booking_links
               WHERE payment_id=? OR booking_id=?""",
            (item["payment_id"], booking_id),
        ).fetchall()
        if existing_payment_link:
            raise ValueError("payment_or_booking_already_linked")
        db.execute(
            """INSERT INTO payment_booking_links(
                 payment_id,booking_id,relation_type,confidence,link_status)
               VALUES (?,?,'pays_for',1.0,'proposed')""",
            (item["payment_id"], booking_id),
        )
        confirmation_id = _sha_json(
            {
                "rule_id": RULE_ID,
                "payment_id": item["payment_id"],
                "booking_id_sha256": item["booking_id_sha256"],
                "ota_fact_sha256": item["fact_sha256"],
                "current_event_key_sha256": _sha_text(item["direct_event_key"]),
                "membership_sha256": membership_sha256,
            }
        )
        db.execute(
            """INSERT INTO direct_agoda_card_booking_confirmations(
                 confirmation_id,confirmation_run_id,payment_id,booking_id,rule_id,
                 relation_status,candidate_only,publication_status,confidence,match_method,ota_source_key_sha256,
                 ota_fact_sha256,current_event_key_sha256,current_source_sha256,
                 portal_booking_id_sha256,portal_card_sha256,staging_db_sha256,
                 capture_set_sha256,portal_page_no,service_start_on,service_end_on,
                 accounting_side_effects,posting_side_effects,payload_json)
               VALUES (?,?,?,?,?,'confirmed',1,'private_candidate_only',1.0,
                       'ota-card4-currency-foreign-amount-bidirectional-singleton',
                       ?,?,?,?,?,?,?,?,?,?,?,0,0,?)""",
            (
                confirmation_id,
                confirmation_run_id,
                item["payment_id"],
                booking_id,
                RULE_ID,
                item["source_key_sha256"],
                item["fact_sha256"],
                _sha_text(item["direct_event_key"]),
                item["source_sha256"],
                item["booking_id_sha256"],
                item["portal_card_sha256"],
                staging["sha256"],
                staging["capture_set_sha256"],
                item["page_no"],
                item["service_start_on"],
                item["service_end_on"],
                json.dumps(
                    {
                        "redaction_version": REDACTION_VERSION,
                        "booking_id_sha256": item["booking_id_sha256"],
                        "portal_page_no": item["page_no"],
                        "service_period_source": "agoda_portal_staging",
                        "ota_fact_sha256": item["fact_sha256"],
                        "current_event_key_sha256": _sha_text(item["direct_event_key"]),
                    },
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                ),
            ),
        )


def _side_effect_counts(db: sqlite3.Connection) -> dict[str, int]:
    def count(table: str) -> int:
        if not _table_exists(db, table):
            return 0
        return int(db.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0])

    return {
        "payment_count": count("payment_transactions"),
        "allocation_plan_count": count("allocation_plans"),
        "cost_allocation_count": count("cost_allocations"),
        "journal_count": count("journal_entries"),
        "decision_count": count("classification_decisions"),
        "posting_batch_count": count("direct_accounting_posting_batches"),
        "posting_line_count": count("direct_accounting_posting_lines"),
        "reversal_count": count("direct_high_coverage_reversal_inheritance"),
    }


def _report_payload(
    *,
    base: dict[str, Any],
    staging: dict[str, Any],
    confirmation_run_id: str,
    membership_sha256: str,
    policy_sha256: str,
    output_db: Path,
) -> dict[str, Any]:
    return {
        "artifact_type": ARTIFACT_TYPE,
        "rule_id": RULE_ID,
        "confirmation_run_id": confirmation_run_id,
        "publication_status": "private_candidate_only",
        "base_candidate_sha256": base["sha256"],
        "base_projection_run_id": base["projection_run_id"],
        "staging_db_sha256": staging["sha256"],
        "capture_set_sha256": staging["capture_set_sha256"],
        "staging_target_count": EXPECTED_STAGING_TARGET_COUNT,
        "confirmed_booking_payment_relations": 5,
        "held_booking_relations": 306,
        "held_nonunique_card_relations": 1,
        "held_no_unique_evidence_relations": 305,
        "membership_sha256": membership_sha256,
        "policy_sha256": policy_sha256,
        "output_db": str(output_db),
        "accounting_finality_created": 0,
        "allocation_created": 0,
        "posting_created": 0,
        "journal_created": 0,
        "reversal_inheritance_created": 0,
        "external_posting": False,
        "sensitive_row_values_in_report": False,
    }


def _unlink_if_owned(path: Path, token: tuple[int, int]) -> None:
    """Remove only the regular file inode created by this process."""
    try:
        info = os.lstat(path)
    except FileNotFoundError:
        return
    if not stat.S_ISREG(info.st_mode) or (info.st_dev, info.st_ino) != token:
        return
    path.unlink()


def _publish_noreplace(stage: Path, final: Path) -> tuple[int, int]:
    if os.path.lexists(final):
        raise FileExistsError(f"output_exists:{final}")
    created = False
    stage_info = os.lstat(stage)
    token: tuple[int, int] = (stage_info.st_dev, stage_info.st_ino)
    try:
        os.link(stage, final)
        created = True
        info = os.lstat(final)
        if (info.st_dev, info.st_ino) != token:
            raise RuntimeError("published_inode_changed")
        fd = os.open(final, os.O_RDONLY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)
        os.chmod(final, 0o600)
        dir_fd = os.open(final.parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
        try:
            os.fsync(dir_fd)
        finally:
            os.close(dir_fd)
        return token
    except Exception:
        if created:
            _unlink_if_owned(final, token)
        raise


def build(
    *, base_db: Path, staging_db: Path, output_db: Path, report_path: Path
) -> dict[str, Any]:
    if os.path.lexists(output_db) or os.path.lexists(report_path):
        raise FileExistsError("output_artifact_exists")
    if output_db.parent != report_path.parent:
        raise ValueError("output_parent_mismatch")
    output_db.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    base = _base_snapshot(base_db)
    staging = _staging_snapshot(staging_db)
    staging["path"] = str(staging_db.resolve())
    base_ro = _connect_immutable(base_db)
    try:
        matches = _load_authorized_matches(base_ro, staging)
    finally:
        base_ro.close()
    membership = sorted(
        [
            {
            "payment_id": item["payment_id"],
            "booking_id_sha256": item["booking_id_sha256"],
            "ota_fact_sha256": item["fact_sha256"],
            "current_event_key_sha256": _sha_text(item["direct_event_key"]),
            }
            for item in matches
        ],
        key=lambda item: (item["payment_id"], item["booking_id_sha256"]),
    )
    membership_sha256 = _sha_json(membership)
    policy_sha256 = _sha_json(
        {
            "rule_id": RULE_ID,
            "requires": [
                "verified_booking_evidence",
                "agoda_portal_staging_2026",
                "service_period_exact_match",
                "card4_currency_foreign_amount_bidirectional_singleton",
                "purchase_transaction",
                "confirmed_three_axes_already_present",
            ],
            "forbids": [
                "amount_only_match",
                "date_only_match",
                "nonunique_match",
                "accounting_posting",
                "allocation_mutation",
                "reversal_inheritance",
            ],
        }
    )
    confirmation_run_id = "agoda-card-confirmation-" + membership_sha256[:16]

    stage_dir = Path(tempfile.mkdtemp(prefix=".agoda-card-confirm-", dir=str(output_db.parent)))
    stage_db = stage_dir / output_db.name
    stage_report = stage_dir / report_path.name
    published: dict[Path, tuple[int, int]] = {}
    try:
        shutil.copyfile(base_db, stage_db)
        os.chmod(stage_db, 0o600)
        db = sqlite3.connect(stage_db)
        try:
            db.execute("PRAGMA foreign_keys=ON")
            _integrity(db)
            _create_audit_tables(db)
            before = _side_effect_counts(db)
            if before != base["side_effects"]:
                raise ValueError("base_side_effect_snapshot_changed")
            with db:
                _insert_candidate(
                    db,
                    staging=staging,
                    base=base,
                    matches=matches,
                    confirmation_run_id=confirmation_run_id,
                    membership_sha256=membership_sha256,
                )
                after_links = int(
                    db.execute(
                        "SELECT COUNT(*) FROM payment_booking_links WHERE link_status=?",
                        (GENERIC_LINK_STATUS,),
                    ).fetchone()[0]
                )
                if after_links != 5:
                    raise ValueError("confirmed_link_count_invalid")
                after = _side_effect_counts(db)
                if any(
                    after[name] != before[name]
                    for name in (
                        "payment_count",
                        "allocation_plan_count",
                        "cost_allocation_count",
                        "journal_count",
                        "decision_count",
                        "posting_batch_count",
                        "posting_line_count",
                        "reversal_count",
                    )
                ):
                    raise ValueError("accounting_side_effect_detected")
                report = _report_payload(
                    base=base,
                    staging=staging,
                    confirmation_run_id=confirmation_run_id,
                    membership_sha256=membership_sha256,
                    policy_sha256=policy_sha256,
                    output_db=output_db,
                )
                stage_report.write_bytes(_canonical(report))
                os.chmod(stage_report, 0o600)
                report_sha256 = _sha_path(stage_report)
                db.execute(
                    """INSERT INTO direct_agoda_card_booking_confirmation_manifests(
                         confirmation_run_id,artifact_type,rule_id,base_candidate_sha256,
                         staging_db_sha256,capture_set_sha256,base_projection_run_id,
                         staging_target_count,confirmed_relation_count,held_relation_count,
                         held_nonunique_card_count,held_no_unique_evidence_count,
                         membership_sha256,policy_sha256,report_sha256,publication_status,
                         payload_json)
                       VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (
                        confirmation_run_id,
                        ARTIFACT_TYPE,
                        RULE_ID,
                        base["sha256"],
                        staging["sha256"],
                        staging["capture_set_sha256"],
                        base["projection_run_id"],
                        EXPECTED_STAGING_TARGET_COUNT,
                        5,
                        306,
                        1,
                        305,
                        membership_sha256,
                        policy_sha256,
                        report_sha256,
                        "private_candidate_only",
                        _canonical(report).decode("utf-8"),
                    ),
                )
            db.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            _integrity(db)
        finally:
            db.close()
        with stage_db.open("rb") as stream:
            os.fsync(stream.fileno())
        with stage_report.open("rb") as stream:
            os.fsync(stream.fileno())
        published[output_db] = _publish_noreplace(stage_db, output_db)
        published[report_path] = _publish_noreplace(stage_report, report_path)
        return verify(
            base_db=base_db,
            output_db=output_db,
            staging_db=staging_db,
            report_path=report_path,
        )
    except Exception:
        for path, token in published.items():
            _unlink_if_owned(path, token)
        raise
    finally:
        shutil.rmtree(stage_dir, ignore_errors=True)


def verify(
    *, base_db: Path, output_db: Path, staging_db: Path, report_path: Path
) -> dict[str, Any]:
    base = _base_snapshot(base_db)
    _require_private_file(output_db)
    _require_private_file(report_path)
    staging = _staging_snapshot(staging_db)
    report = json.loads(report_path.read_text(encoding="utf-8"))
    if report.get("artifact_type") != ARTIFACT_TYPE:
        raise ValueError("report_artifact_type_invalid")
    if _sha_path(report_path) != _sha_bytes(_canonical(report)):
        raise ValueError("report_hash_invalid")
    if report.get("base_candidate_sha256") != base["sha256"]:
        raise ValueError("report_base_hash_invalid")
    if report.get("base_projection_run_id") != base["projection_run_id"]:
        raise ValueError("report_base_projection_run_invalid")
    base_ro = _connect_immutable(base_db)
    try:
        matches = _load_authorized_matches(base_ro, staging)
    finally:
        base_ro.close()
    expected_membership = sorted(
        [
            {
                "payment_id": item["payment_id"],
                "booking_id_sha256": item["booking_id_sha256"],
                "ota_fact_sha256": item["fact_sha256"],
                "current_event_key_sha256": _sha_text(item["direct_event_key"]),
            }
            for item in matches
        ],
        key=lambda item: (item["payment_id"], item["booking_id_sha256"]),
    )
    expected_membership_sha256 = _sha_json(expected_membership)
    expected_policy_sha256 = _sha_json(
        {
            "rule_id": RULE_ID,
            "requires": [
                "verified_booking_evidence",
                "agoda_portal_staging_2026",
                "service_period_exact_match",
                "card4_currency_foreign_amount_bidirectional_singleton",
                "purchase_transaction",
                "confirmed_three_axes_already_present",
            ],
            "forbids": [
                "amount_only_match",
                "date_only_match",
                "nonunique_match",
                "accounting_posting",
                "allocation_mutation",
                "reversal_inheritance",
            ],
        }
    )
    expected_confirmation_run_id = "agoda-card-confirmation-" + expected_membership_sha256[:16]
    if (
        report.get("confirmation_run_id") != expected_confirmation_run_id
        or report.get("membership_sha256") != expected_membership_sha256
        or report.get("policy_sha256") != expected_policy_sha256
        or report.get("staging_db_sha256") != staging["sha256"]
        or report.get("capture_set_sha256") != staging["capture_set_sha256"]
    ):
        raise ValueError("report_provenance_hash_invalid")
    db = _connect_immutable(output_db)
    try:
        _integrity(db)
        manifest = db.execute(
            "SELECT confirmation_run_id,artifact_type,rule_id,base_candidate_sha256,"
            "staging_db_sha256,capture_set_sha256,staging_target_count,"
            "confirmed_relation_count,held_relation_count,held_nonunique_card_count,"
            "held_no_unique_evidence_count,membership_sha256,policy_sha256,report_sha256,"
            "publication_status,payload_json FROM direct_agoda_card_booking_confirmation_manifests"
        ).fetchone()
        if manifest is None:
            raise ValueError("confirmation_manifest_missing")
        report_sha = _sha_path(report_path)
        if (
            str(manifest[0]) != expected_confirmation_run_id
            or str(manifest[1]) != ARTIFACT_TYPE
            or str(manifest[2]) != RULE_ID
            or str(manifest[3]) != base["sha256"]
            or str(manifest[4]) != staging["sha256"]
            or str(manifest[5]) != staging["capture_set_sha256"]
            or tuple(int(value) for value in manifest[6:11])
            != (311, 5, 306, 1, 305)
            or str(manifest[11]) != expected_membership_sha256
            or str(manifest[12]) != expected_policy_sha256
            or str(manifest[13]) != report_sha
            or str(manifest[14]) != "private_candidate_only"
        ):
            raise ValueError("confirmation_manifest_mismatch")
        confirmations = db.execute(
            """SELECT payment_id,booking_id,relation_status,confidence,
                      candidate_only,publication_status,accounting_side_effects,
                      posting_side_effects,portal_booking_id_sha256,ota_fact_sha256,
                      current_event_key_sha256
               FROM direct_agoda_card_booking_confirmations
               ORDER BY payment_id"""
        ).fetchall()
        if len(confirmations) != 5 or len({row[0] for row in confirmations}) != 5 or len({row[1] for row in confirmations}) != 5:
            raise ValueError("confirmation_membership_invalid")
        if any(
            row[2:8] != ("confirmed", 1.0, 1, "private_candidate_only", 0, 0)
            for row in confirmations
        ):
            raise ValueError("confirmation_status_or_side_effect_invalid")
        actual_membership = sorted(
            [
                {
                    "payment_id": row[0],
                    "booking_id_sha256": row[8],
                    "ota_fact_sha256": row[9],
                    "current_event_key_sha256": row[10],
                }
                for row in confirmations
            ],
            key=lambda item: (item["payment_id"], item["booking_id_sha256"]),
        )
        if actual_membership != expected_membership:
            raise ValueError("confirmation_membership_hash_invalid")
        if int(
            db.execute(
                "SELECT COUNT(*) FROM payment_booking_links WHERE link_status=?",
                (GENERIC_LINK_STATUS,),
            ).fetchone()[0]
        ) != 5:
            raise ValueError("payment_booking_link_count_invalid")
        if int(db.execute("SELECT COUNT(*) FROM bookings WHERE provider='agoda'").fetchone()[0]) != 5:
            raise ValueError("agoda_booking_count_invalid")
        if int(db.execute("SELECT COUNT(*) FROM booking_service_period_evidence WHERE evidence_status='confirmed'").fetchone()[0]) != 5:
            raise ValueError("service_period_evidence_count_invalid")
        if int(
            db.execute(
                """SELECT COUNT(*) FROM direct_agoda_card_booking_confirmations c
                   LEFT JOIN payment_booking_links l
                     ON l.payment_id=c.payment_id AND l.booking_id=c.booking_id
                    AND l.link_status=?
                   WHERE l.payment_id IS NULL"""
                , (GENERIC_LINK_STATUS,)
            ).fetchone()[0]
        ) != 0:
            raise ValueError("confirmation_link_orphan_invalid")
        if int(
            db.execute(
                """SELECT COUNT(*) FROM payment_booking_links l
                   LEFT JOIN direct_agoda_card_booking_confirmations c
                     ON c.payment_id=l.payment_id AND c.booking_id=l.booking_id
                   WHERE l.link_status=? AND c.payment_id IS NULL""",
                (GENERIC_LINK_STATUS,),
            ).fetchone()[0]
        ) != 0:
            raise ValueError("confirmed_link_untracked_invalid")
        if db.execute(
            """SELECT 1 FROM booking_service_period_evidence
               WHERE evidence_status='confirmed'
               GROUP BY booking_id HAVING COUNT(*) != 1 LIMIT 1"""
        ).fetchone() is not None:
            raise ValueError("service_period_conflict_invalid")
        if _side_effect_counts(db) != base["side_effects"]:
            raise ValueError("accounting_side_effect_snapshot_invalid")
        if int(db.execute("SELECT COUNT(*) FROM journal_entries").fetchone()[0]) != 0:
            raise ValueError("journal_side_effect_detected")
        if report.get("confirmed_booking_payment_relations") != 5 or report.get("held_booking_relations") != 306:
            raise ValueError("report_counts_invalid")
        return {
            "status": "valid",
            "artifact_type": ARTIFACT_TYPE,
            "confirmation_run_id": str(manifest[0]),
            "confirmed_relation_count": 5,
            "held_relation_count": 306,
            "publication_status": "private_candidate_only",
            "output_db_sha256": _sha_path(output_db),
            "report_sha256": report_sha,
            "source_booking_values_emitted": False,
        }
    finally:
        db.close()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    build_parser = sub.add_parser("build")
    build_parser.add_argument("--base-db", type=Path, required=True)
    build_parser.add_argument("--staging-db", type=Path, required=True)
    build_parser.add_argument("--output-db", type=Path, required=True)
    build_parser.add_argument("--report", type=Path, required=True)
    verify_parser = sub.add_parser("verify")
    verify_parser.add_argument("--base-db", type=Path, required=True)
    verify_parser.add_argument("--output-db", type=Path, required=True)
    verify_parser.add_argument("--staging-db", type=Path, required=True)
    verify_parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    try:
        result = (
            build(
                base_db=args.base_db.resolve(strict=True),
                staging_db=args.staging_db.resolve(strict=True),
                output_db=args.output_db,
                report_path=args.report,
            )
            if args.command == "build"
            else verify(
                base_db=args.base_db.resolve(strict=True),
                output_db=args.output_db.resolve(strict=True),
                staging_db=args.staging_db.resolve(strict=True),
                report_path=args.report.resolve(strict=True),
            )
        )
        print(json.dumps(result, ensure_ascii=False, sort_keys=True))
        return 0
    except (OSError, sqlite3.Error, TypeError, ValueError, json.JSONDecodeError) as exc:
        print(json.dumps({"status": "invalid", "error": str(exc)}, ensure_ascii=False, sort_keys=True))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
