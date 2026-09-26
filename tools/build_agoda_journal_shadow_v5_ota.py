"""Build a balanced, non-posting journal shadow from an OTA draft.

The input is a positive purchase-only draft. Lifecycle events such as
refunds, cancellations, and reversals are outside this builder's authority;
non-positive rows are rejected and require an independent lifecycle authority.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sqlite3
import sys
import tempfile
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import quote


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from ledger.domain.direct_trip_schedule_authority import (
    canonical_json,
    file_sha256,
    sha256_value,
)
from tools.build_agoda_journal_shadow_v3 import (
    BOUND_DEBIT_ACCOUNT,
    CREDIT_ACCOUNT,
    PAYMENT_YEAR_TERMINAL_STATUS,
    UNASSIGNED_TARGET,
    UNRESOLVED_DEBIT_ACCOUNT,
)


RULE_ID = "agoda-linked-lodging-journal-shadow-v5-ota-extended"
RULE_VERSION = "agoda-journal-shadow-v5-ota-extended-rule-v1"
SEMANTIC_SCHEMA_VERSION = "agoda-journal-shadow-v5-ota-extended-semantic-v1"
SHADOW_TABLES = (
    "direct_agoda_journal_shadow_v3_batches",
    "direct_agoda_journal_shadow_v3_lines",
    "direct_agoda_journal_shadow_v3_manifest",
)
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
BATCH_SEMANTIC_COLUMNS = (
    "batch_id",
    "draft_id",
    "payment_id",
    "booking_id",
    "booking_number",
    "payment_lane",
    "payment_year",
    "service_year",
    "target_match_status",
    "assigned_target",
    "suggested_targets_json",
    "target_authority",
    "shadow_cohort",
    "amount_krw",
    "debit_account",
    "credit_account",
    "cost_type",
    "posting_date",
    "posting_status",
    "posting_eligible",
    "authoritative_posting",
    "external_posting",
    "payload_json",
)
LINE_SEMANTIC_COLUMNS = (
    "batch_id",
    "line_no",
    "side",
    "account_code",
    "amount_krw",
    "payment_id",
    "booking_id",
    "assigned_target",
    "payment_lane",
    "posting_date",
    "payload_json",
)
BATCH_DERIVED_HASH_COLUMNS = ("batch_sha256",)
LINE_DERIVED_HASH_COLUMNS = ("line_sha256",)


def _is_existing_path(path: Path) -> bool:
    """Return true for regular paths and broken symlinks alike."""

    return os.path.lexists(str(path))


def _resolved(path: Path) -> Path:
    return path.expanduser().resolve(strict=False)


def _logical_path(path: Path) -> Path:
    return Path(os.path.abspath(os.fspath(path.expanduser())))


def _same_file_or_path(left: Path, right: Path) -> bool:
    if _resolved(left) == _resolved(right):
        return True
    if not (_is_existing_path(left) and _is_existing_path(right)):
        return False
    try:
        return os.path.samefile(str(left), str(right))
    except (FileNotFoundError, OSError):
        try:
            left_stat = os.stat(str(left), follow_symlinks=True)
            right_stat = os.stat(str(right), follow_symlinks=True)
        except OSError:
            return False
        return (
            left_stat.st_dev,
            left_stat.st_ino,
        ) == (
            right_stat.st_dev,
            right_stat.st_ino,
        )


def _validate_paths(
    draft_db: Path,
    draft_audit: Path,
    source_db: Path,
    out_db: Path,
    out_audit: Path,
) -> None:
    for label, path in (
        ("draft_db", draft_db),
        ("draft_audit", draft_audit),
        ("source_db", source_db),
    ):
        if not path.is_file():
            raise FileNotFoundError(f"{label}_not_found:{path}")

    if _same_file_or_path(out_db, out_audit):
        raise ValueError("output_paths_collide")

    inputs = (
        ("draft_db", draft_db),
        ("draft_audit", draft_audit),
        ("source_db", source_db),
    )
    for output_label, output_path in (
        ("out_db", out_db),
        ("out_audit", out_audit),
    ):
        for input_label, input_path in inputs:
            if _same_file_or_path(output_path, input_path):
                raise ValueError(
                    f"output_input_path_collision:{output_label}:{input_label}"
                )

    for label, path in (("out_db", out_db), ("out_audit", out_audit)):
        if _is_existing_path(path):
            raise FileExistsError(f"refusing_to_overwrite:{label}:{path}")


def _sqlite_sidecars(path: Path) -> tuple[Path, Path, Path]:
    return tuple(
        path.with_name(path.name + suffix)
        for suffix in ("-wal", "-shm", "-journal")
    )  # type: ignore[return-value]


def _ensure_sqlite_input_sealed(path: Path) -> None:
    if any(_is_existing_path(sidecar) for sidecar in _sqlite_sidecars(path)):
        raise ValueError("sqlite_input_unsealed")


def _stable_bytes(path: Path, *, sqlite_input: bool = False) -> tuple[bytes, str]:
    if sqlite_input:
        _ensure_sqlite_input_sealed(path)
    before = file_sha256(path)
    data = path.read_bytes()
    read_hash = hashlib.sha256(data).hexdigest()
    after = file_sha256(path)
    if sqlite_input:
        _ensure_sqlite_input_sealed(path)
    if before != read_hash or read_hash != after:
        raise ValueError(f"input_changed_during_read:{path.name}")
    return data, read_hash


def _stable_file_sha256(path: Path, *, sqlite_input: bool = False) -> str:
    return _stable_bytes(path, sqlite_input=sqlite_input)[1]


def _assert_inputs_stable(
    input_hashes: dict[Path, str], sqlite_inputs: set[Path] | None = None
) -> None:
    sqlite_inputs = sqlite_inputs or set()
    for path, expected in input_hashes.items():
        if path in sqlite_inputs:
            _ensure_sqlite_input_sealed(path)
        if not path.is_file() or _stable_file_sha256(
            path, sqlite_input=path in sqlite_inputs
        ) != expected:
            raise ValueError(f"input_not_stable:{path.name}")
        if path in sqlite_inputs:
            _ensure_sqlite_input_sealed(path)


def _sqlite_read_only_uri(path: Path) -> str:
    uri_path = quote(path.resolve().as_posix(), safe="/:")
    return f"file:{uri_path}?mode=ro&immutable=1"


def _open_read_only(path: Path) -> sqlite3.Connection:
    _ensure_sqlite_input_sealed(path)
    try:
        db = sqlite3.connect(_sqlite_read_only_uri(path), uri=True)
    except sqlite3.Error as exc:
        raise ValueError(f"sqlite_read_only_open_failed:{path.name}") from exc
    try:
        db.execute("PRAGMA query_only=ON")
        if int(db.execute("PRAGMA query_only").fetchone()[0]) != 1:
            raise ValueError("sqlite_query_only_not_enabled")
    except Exception:
        db.close()
        raise
    db.row_factory = sqlite3.Row
    return db


def _semantic_value(value: object, field: str) -> object:
    if not isinstance(value, str):
        raise ValueError(f"semantic_field_invalid:{field}")
    try:
        parsed = json.loads(value)
    except (TypeError, json.JSONDecodeError) as exc:
        raise ValueError(f"semantic_json_invalid:{field}") from exc
    if field == "payload_json" and not isinstance(parsed, dict):
        raise ValueError(f"semantic_json_invalid:{field}")
    if field == "suggested_targets_json" and not isinstance(parsed, list):
        raise ValueError(f"semantic_json_invalid:{field}")
    return parsed


def _semantic_row(row: sqlite3.Row, columns: tuple[str, ...]) -> dict[str, Any]:
    projected: dict[str, Any] = {}
    for column in columns:
        value = row[column]
        if column.endswith("_json"):
            value = _semantic_value(value, column)
        projected[column] = value
    return projected


def _assert_semantic_schema(db: sqlite3.Connection) -> None:
    expected_columns = {
        "direct_agoda_journal_shadow_v3_batches": (
            set(BATCH_SEMANTIC_COLUMNS) | set(BATCH_DERIVED_HASH_COLUMNS)
        ),
        "direct_agoda_journal_shadow_v3_lines": (
            set(LINE_SEMANTIC_COLUMNS) | set(LINE_DERIVED_HASH_COLUMNS)
        ),
    }
    for table, expected in expected_columns.items():
        try:
            actual = {
                str(row[1])
                for row in db.execute(f'PRAGMA table_info("{table}")')
            }
        except sqlite3.Error as exc:
            raise ValueError("semantic_schema_mismatch") from exc
        if actual != expected:
            raise ValueError("semantic_schema_mismatch")


def semantic_snapshot(db: sqlite3.Connection) -> dict[str, Any]:
    _assert_semantic_schema(db)
    batch_columns = ",".join(BATCH_SEMANTIC_COLUMNS)
    line_columns = ",".join(LINE_SEMANTIC_COLUMNS)
    try:
        batch_rows = db.execute(
            "SELECT " + batch_columns
            + " FROM direct_agoda_journal_shadow_v3_batches"
        ).fetchall()
        line_rows = db.execute(
            "SELECT " + line_columns
            + " FROM direct_agoda_journal_shadow_v3_lines"
        ).fetchall()
    except (sqlite3.Error, IndexError, KeyError) as exc:
        raise ValueError("semantic_fields_missing") from exc

    batches = [
        _semantic_row(row, BATCH_SEMANTIC_COLUMNS) for row in batch_rows
    ]
    lines = [_semantic_row(row, LINE_SEMANTIC_COLUMNS) for row in line_rows]
    return {
        "semantic_schema_version": SEMANTIC_SCHEMA_VERSION,
        "rule_id": RULE_ID,
        "rule_version": RULE_VERSION,
        "batches": sorted(batches, key=canonical_json),
        "lines": sorted(lines, key=canonical_json),
    }


def semantic_sha256(db: sqlite3.Connection) -> str:
    return sha256_value(semantic_snapshot(db))


def _stable_semantic_sha256(path: Path) -> str:
    before = _stable_file_sha256(path, sqlite_input=True)
    db = _open_read_only(path)
    try:
        digest = semantic_sha256(db)
    finally:
        db.close()
    after = _stable_file_sha256(path, sqlite_input=True)
    if before != after:
        raise ValueError(f"semantic_database_not_stable:{path.name}")
    return digest


def _valid_sha256(value: object) -> bool:
    return isinstance(value, str) and SHA256_RE.fullmatch(value) is not None


def _strict_int(value: object, field: str) -> int:
    if type(value) is not int:
        raise ValueError(f"{field}_must_be_strict_integer")
    return int(value)


def _positive_identifier(value: object, field: str) -> int:
    result = _strict_int(value, field)
    if result <= 0:
        raise ValueError(f"{field}_must_be_positive")
    return result


def _purchase_amount(value: object) -> int:
    amount = _strict_int(value, "amount_krw")
    if amount <= 0:
        raise ValueError(
            "non_positive_purchase_requires_independent_lifecycle_authority"
        )
    return amount


def _nonempty_identifier(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field}_missing_or_invalid")
    if "\n" in value or "\r" in value:
        raise ValueError(f"{field}_missing_or_invalid")
    return value


def _iso_date(value: object, field: str) -> str:
    if not isinstance(value, str) or DATE_RE.fullmatch(value) is None:
        raise ValueError(f"{field}_missing_or_invalid")
    try:
        date.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(f"{field}_missing_or_invalid") from exc
    return value


def _validate_row_identifiers(row: dict[str, Any]) -> tuple[int, int]:
    try:
        payment_id = _positive_identifier(row["payment_id"], "payment_id")
        booking_id = _positive_identifier(row["booking_id"], "booking_id")
    except KeyError as exc:
        raise ValueError(f"{exc.args[0]}_missing_or_invalid") from exc
    return payment_id, booking_id


def _validate_rows(draft_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    seen_payment_ids: set[int] = set()
    for row in draft_rows:
        if not isinstance(row, dict):
            raise ValueError("draft_row_invalid")
        payment_id, booking_id = _validate_row_identifiers(row)
        if payment_id in seen_payment_ids:
            raise ValueError("duplicate_payment_id")
        seen_payment_ids.add(payment_id)

        try:
            amount = _purchase_amount(row["amount_krw"])
            booking_number = _nonempty_identifier(
                row["booking_number"], "booking_number"
            )
            status = _nonempty_identifier(
                row["target_match_status"], "target_match_status"
            )
            allocation_target = _nonempty_identifier(
                row["allocation_target"], "allocation_target"
            )
            occurred_on = _iso_date(row["occurred_on"], "occurred_on")
            service_start_on = _iso_date(
                row["service_start_on"], "service_start_on"
            )
            service_end_on = _iso_date(row["service_end_on"], "service_end_on")
        except KeyError as exc:
            raise ValueError(f"{exc.args[0]}_missing_or_invalid") from exc

        normalized.append(
            {
                **row,
                "payment_id": payment_id,
                "booking_id": booking_id,
                "amount_krw": amount,
                "booking_number": booking_number,
                "target_match_status": status,
                "allocation_target": allocation_target,
                "occurred_on": occurred_on,
                "service_start_on": service_start_on,
                "service_end_on": service_end_on,
            }
        )
    return normalized


def _draft_totals(database: Path) -> tuple[int, int]:
    db = _open_read_only(database)
    try:
        try:
            row = db.execute(
                "SELECT COUNT(*), COALESCE(SUM(amount_krw), 0) "
                "FROM draft_rows"
            ).fetchone()
        except sqlite3.Error as exc:
            raise ValueError("draft_rows_table_invalid") from exc
        return int(row[0]), row[1]
    finally:
        db.close()


def _audit_digest(raw: dict[str, Any]) -> str:
    values: list[str] = []
    for key in ("database_sha256", "output_database_sha256"):
        if key in raw:
            value = raw[key]
            if not _valid_sha256(value):
                raise ValueError("v5_audit_database_sha256_invalid")
            values.append(value)
    if not values:
        raise ValueError("v5_audit_database_sha256_missing")
    if len(set(values)) != 1:
        raise ValueError("v5_audit_database_sha256_conflicting")
    return values[0]


def _load_audit_snapshot(
    path: Path, database: Path
) -> tuple[dict[str, Any], str, str]:
    _ensure_sqlite_input_sealed(database)
    data, audit_file_sha256 = _stable_bytes(path)
    try:
        raw = json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("v5_audit_invalid") from exc
    if not isinstance(raw, dict):
        raise ValueError("v5_audit_invalid")
    if raw.get("artifact_kind") != "agoda_accounting_draft_v3_ota_extended":
        raise ValueError("v5_audit_artifact_kind_invalid")
    declared_digest = _audit_digest(raw)
    database_sha256 = _stable_file_sha256(database, sqlite_input=True)
    if declared_digest != database_sha256:
        raise ValueError("v5_audit_database_sha256_mismatch")

    if "row_count" not in raw:
        raise ValueError("v5_audit_row_count_missing")
    if type(raw["row_count"]) is not int or raw["row_count"] < 0:
        raise ValueError("v5_audit_row_count_invalid")
    if "total_amount_krw" not in raw:
        raise ValueError("v5_audit_total_amount_krw_missing")
    if type(raw["total_amount_krw"]) is not int:
        raise ValueError("v5_audit_total_amount_krw_invalid")

    actual_row_count, actual_total = _draft_totals(database)
    if raw["row_count"] != actual_row_count:
        raise ValueError("v5_audit_row_count_mismatch")
    if raw["total_amount_krw"] != actual_total:
        raise ValueError("v5_audit_total_amount_krw_mismatch")
    if _stable_file_sha256(database, sqlite_input=True) != database_sha256:
        raise ValueError(f"input_not_stable:{database.name}")
    return raw, database_sha256, audit_file_sha256


def _load_audit(path: Path, database: Path) -> tuple[dict[str, Any], str]:
    raw, database_sha256, _ = _load_audit_snapshot(path, database)
    return raw, database_sha256


def create_tables(db: sqlite3.Connection) -> None:
    db.executescript(
        """
        CREATE TABLE IF NOT EXISTS direct_agoda_journal_shadow_v3_batches(
          batch_id TEXT PRIMARY KEY CHECK(length(batch_id)=64),
          draft_id TEXT NOT NULL,
          payment_id INTEGER NOT NULL,
          booking_id INTEGER NOT NULL,
          booking_number TEXT NOT NULL,
          payment_lane TEXT NOT NULL,
          payment_year INTEGER NOT NULL,
          service_year INTEGER NOT NULL,
          target_match_status TEXT NOT NULL,
          assigned_target TEXT NOT NULL,
          suggested_targets_json TEXT NOT NULL,
          target_authority TEXT NOT NULL,
          shadow_cohort TEXT NOT NULL CHECK(shadow_cohort IN (
            'target_bound','target_unresolved','payment_year_terminal'
          )),
          amount_krw INTEGER NOT NULL CHECK(amount_krw>0),
          debit_account TEXT NOT NULL CHECK(debit_account IN ('숙박비','미확정여행원가')),
          credit_account TEXT NOT NULL CHECK(credit_account='법인카드미지급금'),
          cost_type TEXT NOT NULL CHECK(cost_type='여행원가'),
          posting_date TEXT NOT NULL,
          posting_status TEXT NOT NULL CHECK(posting_status='shadow_only'),
          posting_eligible INTEGER NOT NULL CHECK(posting_eligible=0),
          authoritative_posting INTEGER NOT NULL CHECK(authoritative_posting=0),
          external_posting INTEGER NOT NULL CHECK(external_posting=0),
          batch_sha256 TEXT NOT NULL UNIQUE CHECK(length(batch_sha256)=64),
          payload_json TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS direct_agoda_journal_shadow_v3_lines(
          batch_id TEXT NOT NULL,
          line_no INTEGER NOT NULL CHECK(line_no IN (1,2)),
          side TEXT NOT NULL CHECK(side IN ('debit','credit')),
          account_code TEXT NOT NULL,
          amount_krw INTEGER NOT NULL CHECK(amount_krw>0),
          payment_id INTEGER NOT NULL,
          booking_id INTEGER NOT NULL,
          assigned_target TEXT NOT NULL,
          payment_lane TEXT NOT NULL,
          posting_date TEXT NOT NULL,
          line_sha256 TEXT NOT NULL UNIQUE CHECK(length(line_sha256)=64),
          payload_json TEXT NOT NULL,
          PRIMARY KEY(batch_id,line_no)
        );

        CREATE TABLE IF NOT EXISTS direct_agoda_journal_shadow_v3_manifest(
          manifest_id TEXT PRIMARY KEY CHECK(length(manifest_id)=64),
          rule_id TEXT NOT NULL,
          draft_database_sha256 TEXT NOT NULL,
          source_database_sha256 TEXT NOT NULL,
          input_audit_sha256 TEXT NOT NULL,
          shadow_database_sha256 TEXT NOT NULL UNIQUE,
          created_at TEXT NOT NULL,
          cohort_counts_json TEXT NOT NULL,
          payload_json TEXT NOT NULL
        );
        """
    )


def _cohort(status: str) -> str:
    if status == "bound_unique":
        return "target_bound"
    if status == PAYMENT_YEAR_TERMINAL_STATUS:
        return "payment_year_terminal"
    return "target_unresolved"


def _debit_account(status: str) -> str:
    if status == "bound_unique":
        return BOUND_DEBIT_ACCOUNT
    return UNRESOLVED_DEBIT_ACCOUNT


def _assigned_target(status: str, target: str) -> str:
    if status == "bound_unique":
        return target
    return UNASSIGNED_TARGET


def build_batches_and_lines(
    draft_rows: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    normalized_rows = _validate_rows(draft_rows)
    batches: list[dict[str, Any]] = []
    lines: list[dict[str, Any]] = []
    for row in normalized_rows:
        amount = row["amount_krw"]
        status = row["target_match_status"]
        cohort = _cohort(status)
        debit_account = _debit_account(status)
        assigned_target = _assigned_target(status, row["allocation_target"])
        payment_lane = "ota_extended_v5"
        payment_year = int(row["occurred_on"][:4])
        service_year = int(row["service_start_on"][:4])
        target_authority = (
            "explicit_trip_registry" if cohort == "target_bound"
            else "payment_year_terminal" if cohort == "payment_year_terminal"
            else "unresolved"
        )
        payload = {
            "rule_id": RULE_ID,
            "draft_id": RULE_ID,
            "payment_id": row["payment_id"],
            "booking_id": row["booking_id"],
            "booking_number": row["booking_number"],
            "payment_lane": payment_lane,
            "payment_year": payment_year,
            "service_year": service_year,
            "target_match_status": status,
            "assigned_target": assigned_target,
            "suggested_targets": [row["allocation_target"]],
            "target_authority": target_authority,
            "shadow_cohort": cohort,
            "amount_krw": amount,
            "debit_account": debit_account,
            "credit_account": CREDIT_ACCOUNT,
            "cost_type": "여행원가",
            "posting_date": row["occurred_on"],
            "posting_status": "shadow_only",
            "posting_eligible": 0,
            "authoritative_posting": 0,
            "external_posting": 0,
            "merchant": row.get("merchant", "") or "",
            "service_start_on": row["service_start_on"],
            "service_end_on": row["service_end_on"],
        }
        batch_id = sha256_value(payload)
        batch = {
            **payload,
            "batch_id": batch_id,
            "batch_sha256": batch_id,
            "payload_json": canonical_json(payload),
        }
        batches.append(batch)
        for line_no, side, account in (
            (1, "debit", debit_account), (2, "credit", CREDIT_ACCOUNT)
        ):
            line_payload = {
                "rule_id": RULE_ID,
                "batch_id": batch_id,
                "line_no": line_no,
                "side": side,
                "account_code": account,
                "amount_krw": amount,
                "payment_id": row["payment_id"],
                "booking_id": row["booking_id"],
                "assigned_target": assigned_target,
                "payment_lane": payment_lane,
                "posting_date": row["occurred_on"],
                "posting_status": "shadow_only",
            }
            line_sha256 = sha256_value(line_payload)
            lines.append(
                {
                    **line_payload,
                    "line_sha256": line_sha256,
                    "payload_json": canonical_json(line_payload),
                }
            )
    _validate_built_rows(normalized_rows, batches, lines)
    return batches, lines


def _validate_built_rows(
    draft_rows: list[dict[str, Any]],
    batches: list[dict[str, Any]],
    lines: list[dict[str, Any]],
) -> dict[str, int]:
    if len(batches) != len(draft_rows) or len(lines) != len(draft_rows) * 2:
        raise ValueError("shadow_cardinality_invalid")
    if len({row["payment_id"] for row in draft_rows}) != len(draft_rows):
        raise ValueError("duplicate_payment_id")
    if len({row["batch_id"] for row in batches}) != len(batches):
        raise ValueError("duplicate_batch_id")
    if len({row["line_sha256"] for row in lines}) != len(lines):
        raise ValueError("duplicate_line_id")

    source_by_payment = {row["payment_id"]: row for row in draft_rows}
    batches_by_payment: dict[int, dict[str, Any]] = {}
    lines_by_batch: dict[str, list[dict[str, Any]]] = {}
    for batch in batches:
        payment_id = batch.get("payment_id")
        if payment_id in batches_by_payment:
            raise ValueError("duplicate_payment_id")
        batches_by_payment[payment_id] = batch
        if (
            batch.get("amount_krw", 0) <= 0
            or batch.get("posting_eligible") != 0
            or batch.get("authoritative_posting") != 0
            or batch.get("external_posting") != 0
            or batch.get("posting_status") != "shadow_only"
        ):
            raise ValueError("shadow_posting_state_invalid")
        if not _valid_sha256(batch.get("batch_sha256")):
            raise ValueError("batch_hash_invalid")
    for line in lines:
        lines_by_batch.setdefault(line["batch_id"], []).append(line)

    total = 0
    for payment_id, source in source_by_payment.items():
        batch = batches_by_payment.get(payment_id)
        if batch is None:
            raise ValueError("shadow_payment_missing")
        if (
            batch["amount_krw"] != source["amount_krw"]
            or batch["booking_id"] != source["booking_id"]
            or batch["booking_number"] != source["booking_number"]
        ):
            raise ValueError("shadow_payment_conservation_failed")
        payment_lines = lines_by_batch.get(batch["batch_id"], [])
        if len(payment_lines) != 2 or {
            line["line_no"] for line in payment_lines
        } != {1, 2}:
            raise ValueError("shadow_line_cardinality_invalid")
        if {line["side"] for line in payment_lines} != {"debit", "credit"}:
            raise ValueError("shadow_balance_invalid")
        for line in payment_lines:
            if (
                line["payment_id"] != payment_id
                or line["booking_id"] != source["booking_id"]
                or line["amount_krw"] != source["amount_krw"]
                or line["posting_status"] != "shadow_only"
            ):
                raise ValueError("shadow_line_conservation_failed")
            if not _valid_sha256(line.get("line_sha256")):
                raise ValueError("line_hash_invalid")
        debit_total = sum(
            line["amount_krw"] for line in payment_lines if line["side"] == "debit"
        )
        credit_total = sum(
            line["amount_krw"] for line in payment_lines if line["side"] == "credit"
        )
        if debit_total != credit_total or debit_total != source["amount_krw"]:
            raise ValueError("shadow_balance_invalid")
        total += source["amount_krw"]

    if sum(batch["amount_krw"] for batch in batches) != total:
        raise ValueError("shadow_total_conservation_failed")
    return {
        "batch_count": len(batches),
        "line_count": len(lines),
        "total_amount_krw": total,
    }


def materialize(
    db: sqlite3.Connection,
    batches: list[dict[str, Any]],
    lines: list[dict[str, Any]],
) -> None:
    for row in batches:
        if type(row.get("amount_krw")) is not int or row["amount_krw"] <= 0:
            raise ValueError(
                "non_positive_purchase_requires_independent_lifecycle_authority"
            )
        db.execute(
            """INSERT INTO direct_agoda_journal_shadow_v3_batches(
              batch_id,draft_id,payment_id,booking_id,booking_number,payment_lane,
              payment_year,service_year,target_match_status,assigned_target,
              suggested_targets_json,target_authority,shadow_cohort,amount_krw,
              debit_account,credit_account,cost_type,posting_date,posting_status,
              posting_eligible,authoritative_posting,external_posting,batch_sha256,
              payload_json)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                row["batch_id"], row["draft_id"], row["payment_id"], row["booking_id"],
                row["booking_number"], row["payment_lane"], row["payment_year"],
                row["service_year"], row["target_match_status"], row["assigned_target"],
                canonical_json(row["suggested_targets"]), row["target_authority"],
                row["shadow_cohort"], row["amount_krw"], row["debit_account"],
                CREDIT_ACCOUNT, "여행원가", row["posting_date"], "shadow_only", 0, 0, 0,
                row["batch_sha256"], row["payload_json"],
            ),
        )
    for row in lines:
        db.execute(
            """INSERT INTO direct_agoda_journal_shadow_v3_lines(
              batch_id,line_no,side,account_code,amount_krw,payment_id,booking_id,
              assigned_target,payment_lane,posting_date,line_sha256,payload_json)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                row["batch_id"], row["line_no"], row["side"], row["account_code"],
                row["amount_krw"], row["payment_id"], row["booking_id"],
                row["assigned_target"], row["payment_lane"], row["posting_date"],
                row["line_sha256"], row["payload_json"],
            ),
        )


def _database_path(db: sqlite3.Connection) -> Path:
    row = db.execute("PRAGMA database_list").fetchone()
    if row is None or not row[2]:
        raise ValueError("shadow_database_path_unavailable")
    return Path(str(row[2]))


def build_manifest(
    db: sqlite3.Connection,
    source_database_sha256: str,
    input_audit_sha256: str,
    draft_database_sha256: str,
) -> dict[str, Any]:
    cur = db.cursor()
    cohort_counts: dict[str, int] = {}
    for cohort in ("target_bound", "target_unresolved", "payment_year_terminal"):
        cur.execute(
            "SELECT COUNT(*) FROM direct_agoda_journal_shadow_v3_batches "
            "WHERE shadow_cohort=?",
            (cohort,),
        )
        cohort_counts[cohort] = int(cur.fetchone()[0])
    cur.execute("SELECT COUNT(*) FROM direct_agoda_journal_shadow_v3_batches")
    batch_count = int(cur.fetchone()[0])
    cur.execute(
        "SELECT COALESCE(SUM(amount_krw),0) "
        "FROM direct_agoda_journal_shadow_v3_batches"
    )
    total_krw = int(cur.fetchone()[0])
    # This legacy field is necessarily calculated before its own manifest row
    # exists, so it is not the whole-file digest. The output audit has that
    # final digest.
    pre_manifest_sha256 = file_sha256(_database_path(db))
    payload = {
        "rule_id": RULE_ID,
        "draft_database_sha256": draft_database_sha256,
        "source_database_sha256": source_database_sha256,
        "input_audit_sha256": input_audit_sha256,
        "shadow_database_sha256": pre_manifest_sha256,
        "cohort_counts": cohort_counts,
        "batch_count": batch_count,
        "total_krw": total_krw,
    }
    manifest_id = sha256_value(payload)
    created_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    db.execute(
        """INSERT INTO direct_agoda_journal_shadow_v3_manifest(
          manifest_id,rule_id,draft_database_sha256,source_database_sha256,
          input_audit_sha256,shadow_database_sha256,created_at,
          cohort_counts_json,payload_json)
        VALUES (?,?,?,?,?,?,?,?,?)""",
        (
            manifest_id, RULE_ID, draft_database_sha256, source_database_sha256,
            input_audit_sha256, pre_manifest_sha256,
            created_at, canonical_json(cohort_counts),
            canonical_json(payload),
        ),
    )
    return payload


def _load_draft_rows(path: Path) -> list[dict[str, Any]]:
    db = _open_read_only(path)
    try:
        try:
            rows = db.execute("SELECT * FROM draft_rows").fetchall()
        except sqlite3.Error as exc:
            raise ValueError("draft_rows_table_invalid") from exc
        return [dict(row) for row in rows]
    finally:
        db.close()


def _load_booking_numbers(
    path: Path,
    draft_rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    payment_ids: set[int] = set()
    booking_ids: set[int] = set()
    for row in draft_rows:
        if not isinstance(row, dict):
            raise ValueError("draft_row_invalid")
        payment_id, booking_id = _validate_row_identifiers(row)
        if payment_id in payment_ids:
            raise ValueError("duplicate_payment_id")
        payment_ids.add(payment_id)
        booking_ids.add(booking_id)

    source = _open_read_only(path)
    try:
        try:
            source.execute("SELECT 1 FROM bookings LIMIT 1").fetchone()
        except sqlite3.Error as exc:
            raise ValueError("source_bookings_table_invalid") from exc
        booking_numbers: dict[int, str] = {}
        for booking_id in sorted(booking_ids):
            rows = source.execute(
                "SELECT booking_number FROM bookings WHERE id=?",
                (booking_id,),
            ).fetchall()
            if not rows:
                raise ValueError("source_booking_missing")
            if len(rows) != 1:
                raise ValueError("source_booking_ambiguous")
            booking_numbers[booking_id] = _nonempty_identifier(
                rows[0][0], "booking_number"
            )
    finally:
        source.close()

    enriched: list[dict[str, Any]] = []
    for row in draft_rows:
        _, booking_id = _validate_row_identifiers(row)
        source_booking_number = booking_numbers[booking_id]
        if "booking_number" in row:
            draft_booking_number = _nonempty_identifier(
                row["booking_number"], "booking_number"
            )
            if draft_booking_number != source_booking_number:
                raise ValueError("booking_number_mismatch")
        enriched.append({**row, "booking_number": source_booking_number})
    return enriched


def _validate_shadow_database(
    path: Path,
    expected_rows: list[dict[str, Any]],
    expected_batches: list[dict[str, Any]],
    expected_lines: list[dict[str, Any]],
) -> dict[str, Any]:
    db = _open_read_only(path)
    try:
        table_names = {
            str(row[0])
            for row in db.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
        if any(table not in table_names for table in SHADOW_TABLES):
            raise ValueError("shadow_tables_missing")
        if db.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise ValueError("shadow_integrity_failed")
        if db.execute("PRAGMA foreign_key_check").fetchall():
            raise ValueError("shadow_foreign_key_failed")
        batches = [
            dict(row)
            for row in db.execute(
                "SELECT * FROM direct_agoda_journal_shadow_v3_batches "
                "ORDER BY payment_id"
            )
        ]
        lines = [
            dict(row)
            for row in db.execute(
                "SELECT * FROM direct_agoda_journal_shadow_v3_lines "
                "ORDER BY payment_id,batch_id,line_no"
            )
        ]
        manifests = db.execute(
            "SELECT * FROM direct_agoda_journal_shadow_v3_manifest"
        ).fetchall()
        if len(manifests) != 1:
            raise ValueError("shadow_manifest_cardinality_invalid")
        if len(batches) != len(expected_rows) or len(lines) != len(expected_rows) * 2:
            raise ValueError("shadow_cardinality_invalid")
        if [row["payment_id"] for row in batches] != [
            row["payment_id"]
            for row in sorted(expected_batches, key=lambda item: item["payment_id"])
        ]:
            raise ValueError("shadow_payment_order_invalid")
        if len({row["payment_id"] for row in batches}) != len(batches):
            raise ValueError("duplicate_payment_id")
        if len({row["batch_id"] for row in batches}) != len(batches):
            raise ValueError("duplicate_batch_id")
        if len({row["line_sha256"] for row in lines}) != len(lines):
            raise ValueError("duplicate_line_id")
        expected_by_payment = {
            row["payment_id"]: row for row in expected_rows
        }
        actual_by_payment = {
            row["payment_id"]: row for row in batches
        }
        if set(actual_by_payment) != set(expected_by_payment):
            raise ValueError("shadow_payment_scope_invalid")
        lines_by_batch: dict[str, list[dict[str, Any]]] = {}
        for line in lines:
            lines_by_batch.setdefault(line["batch_id"], []).append(line)
        if set(lines_by_batch) != {row["batch_id"] for row in batches}:
            raise ValueError("shadow_line_scope_invalid")
        for payment_id, expected in expected_by_payment.items():
            actual = actual_by_payment[payment_id]
            if (
                actual["amount_krw"] != expected["amount_krw"]
                or actual["booking_id"] != expected["booking_id"]
                or actual["booking_number"] != expected["booking_number"]
            ):
                raise ValueError("shadow_payment_conservation_failed")
            actual_lines = lines_by_batch[actual["batch_id"]]
            if len(actual_lines) != 2 or {
                line["line_no"] for line in actual_lines
            } != {1, 2}:
                raise ValueError("shadow_line_cardinality_invalid")
            if {line["side"] for line in actual_lines} != {"debit", "credit"}:
                raise ValueError("shadow_balance_invalid")
            for line in actual_lines:
                try:
                    line_payload = json.loads(line["payload_json"])
                except (TypeError, json.JSONDecodeError) as exc:
                    raise ValueError("shadow_line_payload_invalid") from exc
                if (
                    line["payment_id"] != payment_id
                    or line["booking_id"] != expected["booking_id"]
                    or line["amount_krw"] != expected["amount_krw"]
                    or line_payload.get("posting_status") != "shadow_only"
                ):
                    raise ValueError("shadow_line_conservation_failed")
        _validate_built_rows(expected_rows, expected_batches, expected_lines)
        if sum(row["amount_krw"] for row in batches) != sum(
            row["amount_krw"] for row in expected_batches
        ):
            raise ValueError("shadow_total_conservation_failed")
        for row in batches:
            if any(
                row[key] != 0
                for key in (
                    "posting_eligible",
                    "authoritative_posting",
                    "external_posting",
                )
            ):
                raise ValueError("shadow_posting_state_invalid")
        debit_total = sum(
            row["amount_krw"] for row in lines if row["side"] == "debit"
        )
        credit_total = sum(
            row["amount_krw"] for row in lines if row["side"] == "credit"
        )
        if debit_total != credit_total:
            raise ValueError("shadow_balance_invalid")
        return {
            "batches": len(batches),
            "lines": len(lines),
            "manifest_count": len(manifests),
            "total_amount_krw": sum(row["amount_krw"] for row in batches),
        }
    finally:
        db.close()


def _make_temp_file(directory: Path, output_name: str) -> tuple[Path, tuple[int, int]]:
    fd, name = tempfile.mkstemp(
        prefix=f".{output_name}.", suffix=".tmp", dir=str(directory)
    )
    os.close(fd)
    path = Path(name)
    stat = os.stat(path, follow_symlinks=False)
    return path, (stat.st_dev, stat.st_ino)


def _owned_identity(path: Path) -> tuple[int, int] | None:
    try:
        stat = os.stat(path, follow_symlinks=False)
    except OSError:
        return None
    return stat.st_dev, stat.st_ino


def _cleanup_owned(path: Path, identity: tuple[int, int]) -> None:
    if _owned_identity(path) != identity:
        return
    try:
        os.unlink(path)
    except FileNotFoundError:
        return


def _publish_exclusive(staged: Path, output: Path) -> tuple[int, int]:
    if _is_existing_path(output):
        raise FileExistsError(f"refusing_to_overwrite:{output}")
    try:
        os.link(str(staged), str(output))
    except FileExistsError as exc:
        raise FileExistsError(f"refusing_to_overwrite:{output}") from exc
    identity = _owned_identity(output)
    if identity is None:
        raise OSError(f"published_output_stat_failed:{output}")
    return identity


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    text = json.dumps(
        payload, ensure_ascii=False, indent=2, sort_keys=True
    ) + "\n"
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        handle.write(text)
        handle.flush()
        os.fsync(handle.fileno())


def _build_output_audit(
    *,
    audit: dict[str, Any],
    manifest: dict[str, Any],
    source_database_sha256: str,
    draft_database_sha256: str,
    input_audit_sha256: str,
    shadow_database_sha256: str,
    validation: dict[str, Any],
    cohort_rows: list[tuple[str, int]],
) -> dict[str, Any]:
    cohorts = {str(key): int(value) for key, value in cohort_rows}
    return {
        "artifact_kind": "agoda_journal_shadow_v5_ota_extended_audit",
        "artifact_version": "v1",
        "rule_id": RULE_ID,
        "database_sha256": shadow_database_sha256,
        "audit_db_sha256": shadow_database_sha256,
        "draft_database_sha256": draft_database_sha256,
        "source_database_sha256": source_database_sha256,
        "input_database_sha256": source_database_sha256,
        "input_audit_sha256": input_audit_sha256,
        "manifest": manifest,
        "cohorts": cohorts,
        "batches": validation["batches"],
        "lines": validation["lines"],
        "total_amount_krw": validation["total_amount_krw"],
        "semantic_schema_version": validation["semantic_schema_version"],
        "semantic_sha256": validation["semantic_sha256"],
        "integrity_check": [["ok"]],
        "foreign_key_check": [],
        "posting_eligible": 0,
        "authority": {
            "purchase_only": True,
            "lifecycle_authority": "independent_required_for_non_positive_rows",
            "candidate_status_is_posting_permission": False,
            "journal_entries_written": 0,
            "authoritative_posting_written": False,
        },
        "input_draft_audit": {
            "artifact_kind": audit["artifact_kind"],
            "row_count": audit["row_count"],
            "total_amount_krw": audit["total_amount_krw"],
        },
    }


def _validate_output_audit(
    path: Path,
    shadow_database_sha256: str,
    shadow_database_path: Path,
) -> None:
    data, _ = _stable_bytes(path)
    try:
        raw = json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("output_audit_invalid") from exc
    if not isinstance(raw, dict):
        raise ValueError("output_audit_invalid")
    if raw.get("database_sha256") != shadow_database_sha256:
        raise ValueError("output_audit_database_sha256_mismatch")
    if raw.get("audit_db_sha256") != shadow_database_sha256:
        raise ValueError("output_audit_alias_database_sha256_mismatch")
    if _stable_file_sha256(shadow_database_path, sqlite_input=True) != shadow_database_sha256:
        raise ValueError("output_database_sha256_mismatch")
    if raw.get("semantic_schema_version") != SEMANTIC_SCHEMA_VERSION:
        raise ValueError("output_audit_semantic_schema_version_mismatch")
    if raw.get("semantic_sha256") != _stable_semantic_sha256(
        shadow_database_path
    ):
        raise ValueError("output_audit_semantic_sha256_mismatch")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--draft-db",
        default=r"C:\AX\cost\outputs\agoda-card-accounting-draft-v5-ota-extended.sqlite",
        help="Path to the OTA draft sqlite",
    )
    parser.add_argument(
        "--draft-audit",
        default=r"C:\AX\cost\outputs\agoda-card-accounting-draft-v5-ota-extended.audit.json",
        help="Path to the OTA draft audit json",
    )
    parser.add_argument(
        "--source-db",
        default=r"C:\AX\cost\outputs\agoda-card-link-candidate-v5-20260826.sqlite",
        help="Path to the candidate source sqlite",
    )
    parser.add_argument(
        "--out-db",
        default=r"C:\AX\cost\outputs\agoda-card-journal-shadow-v5-ota-extended.sqlite",
        help="Path to output shadow sqlite",
    )
    parser.add_argument(
        "--out-audit",
        default=r"C:\AX\cost\outputs\agoda-card-journal-shadow-v5-ota-extended.audit.json",
        help="Path to output audit json",
    )
    args = parser.parse_args(argv)

    draft_db = _resolved(Path(args.draft_db))
    draft_audit = _resolved(Path(args.draft_audit))
    source_db = _resolved(Path(args.source_db))
    out_db = _logical_path(Path(args.out_db))
    out_audit = _logical_path(Path(args.out_audit))
    _validate_paths(draft_db, draft_audit, source_db, out_db, out_audit)
    out_db = _resolved(out_db)
    out_audit = _resolved(out_audit)
    _ensure_sqlite_input_sealed(draft_db)
    _ensure_sqlite_input_sealed(source_db)

    audit, draft_database_sha256, input_audit_sha256 = _load_audit_snapshot(
        draft_audit, draft_db
    )
    source_database_sha256 = _stable_file_sha256(source_db, sqlite_input=True)
    input_database_sha256 = audit.get("input_database_sha256")
    if not _valid_sha256(input_database_sha256):
        raise ValueError("v5_audit_input_database_sha256_missing_or_invalid")
    if input_database_sha256 != source_database_sha256:
        raise ValueError("v5_audit_input_database_sha256_mismatch")
    input_hashes = {
        draft_db: draft_database_sha256,
        draft_audit: input_audit_sha256,
        source_db: source_database_sha256,
    }

    draft_rows = _load_draft_rows(draft_db)
    if len(draft_rows) != audit["row_count"]:
        raise ValueError("draft_row_count_drift")
    draft_rows = _load_booking_numbers(source_db, draft_rows)
    batches, lines = build_batches_and_lines(draft_rows)
    _assert_inputs_stable(input_hashes, {draft_db, source_db})
    print(f"loaded draft_rows: {len(draft_rows)}건")
    print(f"built shadow: {len(batches)} batches, {len(lines)} lines")

    staged_paths: list[tuple[Path, tuple[int, int]]] = []
    published: list[tuple[Path, tuple[int, int]]] = []
    try:
        staged_db, staged_db_identity = _make_temp_file(out_db.parent, out_db.name)
        staged_paths.append((staged_db, staged_db_identity))
        out = sqlite3.connect(str(staged_db))
        try:
            out.execute("PRAGMA journal_mode=DELETE")
            out.execute("PRAGMA synchronous=FULL")
            create_tables(out)
            materialize(out, batches, lines)
            out.commit()
            manifest = build_manifest(
                out,
                source_database_sha256=source_database_sha256,
                input_audit_sha256=input_audit_sha256,
                draft_database_sha256=draft_database_sha256,
            )
            out.commit()
        finally:
            out.close()

        shadow_database_sha256 = _stable_file_sha256(staged_db)
        validation = _validate_shadow_database(
            staged_db, draft_rows, batches, lines
        )
        validation["semantic_schema_version"] = SEMANTIC_SCHEMA_VERSION
        validation["semantic_sha256"] = _stable_semantic_sha256(staged_db)
        staged_audit, staged_audit_identity = _make_temp_file(
            out_audit.parent, out_audit.name
        )
        staged_paths.append((staged_audit, staged_audit_identity))
        check = sqlite3.connect(str(staged_db))
        try:
            cohort_rows = check.execute(
                "SELECT shadow_cohort, COUNT(*) "
                "FROM direct_agoda_journal_shadow_v3_batches "
                "GROUP BY shadow_cohort"
            ).fetchall()
        finally:
            check.close()
        output_audit = _build_output_audit(
            audit=audit,
            manifest=manifest,
            source_database_sha256=source_database_sha256,
            draft_database_sha256=draft_database_sha256,
            input_audit_sha256=input_audit_sha256,
            shadow_database_sha256=shadow_database_sha256,
            validation=validation,
            cohort_rows=cohort_rows,
        )
        _write_json(staged_audit, output_audit)
        _validate_output_audit(staged_audit, shadow_database_sha256, staged_db)
        _assert_inputs_stable(input_hashes, {draft_db, source_db})

        published.append((out_db, _publish_exclusive(staged_db, out_db)))
        try:
            published.append((out_audit, _publish_exclusive(staged_audit, out_audit)))
        except Exception:
            for published_path, identity in reversed(published):
                _cleanup_owned(published_path, identity)
            published.clear()
            raise
    finally:
        for staged_path, identity in staged_paths:
            _cleanup_owned(staged_path, identity)

    print(f"created: {out_db} ({out_db.stat().st_size / 1024:.0f} KB)")
    print(f"audit:   {out_audit}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
