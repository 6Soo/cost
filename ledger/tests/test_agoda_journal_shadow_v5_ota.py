from __future__ import annotations

import json
import sqlite3
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from ledger.domain.direct_trip_schedule_authority import file_sha256
from tools import build_agoda_journal_shadow_v5_ota as builder


def _row(
    *,
    payment_id: object = 1,
    booking_id: object = 7,
    amount_krw: object = 12_500,
    booking_number: str = "REAL-BOOKING-7",
    status: str = "candidate_review",
) -> dict[str, object]:
    return {
        "rule_id": "draft-rule",
        "payment_id": payment_id,
        "booking_id": booking_id,
        "booking_number": booking_number,
        "allocation_target": "UNASSIGNED",
        "target_match_status": status,
        "amount_krw": amount_krw,
        "service_start_on": "2026-08-10",
        "service_end_on": "2026-08-12",
        "occurred_on": "2026-08-01",
        "merchant": "Agoda",
    }


def _make_inputs(
    tmp_path: Path,
    *,
    rows: list[dict[str, object]] | None = None,
    booking_rows: list[tuple[int, str]] | None = None,
    input_dir: Path | None = None,
    wal: bool = False,
) -> tuple[Path, Path, Path, list[dict[str, object]]]:
    if rows is None:
        rows = [{**_row(), "booking_number": None}]
    if booking_rows is None:
        booking_rows = [(7, "REAL-BOOKING-7")]
    base_dir = input_dir or tmp_path
    base_dir.mkdir(parents=True, exist_ok=True)
    draft_db = base_dir / "draft.sqlite"
    draft_audit = base_dir / "draft.audit.json"
    source_db = base_dir / "source.sqlite"

    draft = sqlite3.connect(draft_db)
    if wal:
        draft.execute("PRAGMA journal_mode=WAL")
    draft.execute(
        """CREATE TABLE draft_rows(
          rule_id TEXT,
          payment_id,
          booking_id,
          allocation_target TEXT,
          target_match_status TEXT,
          amount_krw,
          service_start_on TEXT,
          service_end_on TEXT,
          occurred_on TEXT,
          merchant TEXT
        )"""
    )
    for row in rows:
        draft.execute(
            """INSERT INTO draft_rows(
              rule_id,payment_id,booking_id,allocation_target,target_match_status,
              amount_krw,service_start_on,service_end_on,occurred_on,merchant)
            VALUES (?,?,?,?,?,?,?,?,?,?)""",
            tuple(row.get(key) for key in (
                "rule_id", "payment_id", "booking_id", "allocation_target",
                "target_match_status", "amount_krw", "service_start_on",
                "service_end_on", "occurred_on", "merchant",
            )),
        )
    draft.commit()
    draft.close()

    source = sqlite3.connect(source_db)
    if wal:
        source.execute("PRAGMA journal_mode=WAL")
    source.execute(
        "CREATE TABLE bookings(id INTEGER, booking_number TEXT)"
    )
    source.executemany(
        "INSERT INTO bookings(id,booking_number) VALUES (?,?)", booking_rows
    )
    source.commit()
    source.close()

    audit = {
        "artifact_kind": "agoda_accounting_draft_v3_ota_extended",
        "database_sha256": file_sha256(draft_db),
        "input_database_sha256": file_sha256(source_db),
        "row_count": len(rows),
        "total_amount_krw": sum(row["amount_krw"] for row in rows),
    }
    draft_audit.write_text(
        json.dumps(audit, sort_keys=True), encoding="utf-8"
    )
    return draft_db, draft_audit, source_db, rows


def _cli_args(
    draft_db: Path,
    draft_audit: Path,
    source_db: Path,
    out_db: Path,
    out_audit: Path,
) -> list[str]:
    return [
        sys.executable,
        str(ROOT / "tools" / "build_agoda_journal_shadow_v5_ota.py"),
        "--draft-db", str(draft_db),
        "--draft-audit", str(draft_audit),
        "--source-db", str(source_db),
        "--out-db", str(out_db),
        "--out-audit", str(out_audit),
    ]


def _run_main(
    draft_db: Path,
    draft_audit: Path,
    source_db: Path,
    out_db: Path,
    out_audit: Path,
) -> int:
    return builder.main([
        "--draft-db", str(draft_db),
        "--draft-audit", str(draft_audit),
        "--source-db", str(source_db),
        "--out-db", str(out_db),
        "--out-audit", str(out_audit),
    ])


@pytest.mark.parametrize(
    ("amount", "expected"),
    [
        (-1, "non_positive_purchase_requires_independent_lifecycle_authority"),
        (0, "non_positive_purchase_requires_independent_lifecycle_authority"),
        (True, "amount_krw_must_be_strict_integer"),
        (100.0, "amount_krw_must_be_strict_integer"),
        (100.5, "amount_krw_must_be_strict_integer"),
    ],
)
def test_amount_validation_rejects_sign_and_coercion(
    amount: object, expected: str
) -> None:
    with pytest.raises(ValueError, match=expected):
        builder.build_batches_and_lines([_row(amount_krw=amount)])


def test_duplicate_payment_ids_are_rejected_before_materialization() -> None:
    rows = [_row(payment_id=1), _row(payment_id=1, booking_id=8)]
    with pytest.raises(ValueError, match="duplicate_payment_id"):
        builder.build_batches_and_lines(rows)


@pytest.mark.parametrize(
    "field,value,expected",
    [
        ("booking_number", "", "booking_number_missing_or_invalid"),
        ("occurred_on", None, "occurred_on_missing_or_invalid"),
        ("service_start_on", "2026-02-30", "service_start_on_missing_or_invalid"),
        ("payment_id", 1.0, "payment_id_must_be_strict_integer"),
        ("booking_id", True, "booking_id_must_be_strict_integer"),
    ],
)
def test_bad_identifiers_and_dates_are_rejected(
    field: str, value: object, expected: str
) -> None:
    row = _row()
    row[field] = value
    with pytest.raises(ValueError, match=expected):
        builder.build_batches_and_lines([row])


def test_positive_purchase_has_one_batch_two_balanced_lines_and_real_booking() -> None:
    batches, lines = builder.build_batches_and_lines([_row()])

    assert len(batches) == 1
    assert len(lines) == 2
    batch = batches[0]
    assert batch["amount_krw"] == 12_500
    assert batch["booking_number"] == "REAL-BOOKING-7"
    assert batch["posting_eligible"] == 0
    assert batch["authoritative_posting"] == 0
    assert batch["external_posting"] == 0
    assert {line["side"] for line in lines} == {"debit", "credit"}
    assert {line["amount_krw"] for line in lines} == {12_500}
    assert batch["target_match_status"] == "candidate_review"


def test_audit_requires_matching_digest_and_actual_totals(tmp_path: Path) -> None:
    draft_db, draft_audit, source_db, _ = _make_inputs(tmp_path)
    del source_db
    audit = json.loads(draft_audit.read_text(encoding="utf-8"))

    audit.pop("database_sha256")
    draft_audit.write_text(json.dumps(audit), encoding="utf-8")
    with pytest.raises(ValueError, match="v5_audit_database_sha256_missing"):
        builder._load_audit(draft_audit, draft_db)

    audit["database_sha256"] = "0" * 64
    draft_audit.write_text(json.dumps(audit), encoding="utf-8")
    with pytest.raises(ValueError, match="v5_audit_database_sha256_mismatch"):
        builder._load_audit(draft_audit, draft_db)

    audit["database_sha256"] = file_sha256(draft_db)
    audit["row_count"] = 99
    draft_audit.write_text(json.dumps(audit), encoding="utf-8")
    with pytest.raises(ValueError, match="v5_audit_row_count_mismatch"):
        builder._load_audit(draft_audit, draft_db)

    audit["row_count"] = 1
    audit["total_amount_krw"] = 99
    draft_audit.write_text(json.dumps(audit), encoding="utf-8")
    with pytest.raises(ValueError, match="v5_audit_total_amount_krw_mismatch"):
        builder._load_audit(draft_audit, draft_db)


def test_explicit_output_database_digest_alias_is_supported(tmp_path: Path) -> None:
    draft_db, draft_audit, _, _ = _make_inputs(tmp_path)
    audit = json.loads(draft_audit.read_text(encoding="utf-8"))
    digest = audit.pop("database_sha256")
    audit["output_database_sha256"] = digest
    draft_audit.write_text(json.dumps(audit), encoding="utf-8")
    _, actual = builder._load_audit(draft_audit, draft_db)
    assert actual == digest


def test_cli_rejects_stale_source_hash_without_outputs(tmp_path: Path) -> None:
    draft_db, draft_audit, source_db, _ = _make_inputs(tmp_path)
    audit = json.loads(draft_audit.read_text(encoding="utf-8"))
    audit["input_database_sha256"] = "0" * 64
    draft_audit.write_text(json.dumps(audit), encoding="utf-8")
    out_db = tmp_path / "out.sqlite"
    out_audit = tmp_path / "out.audit.json"

    result = subprocess.run(
        _cli_args(draft_db, draft_audit, source_db, out_db, out_audit),
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0
    assert "v5_audit_input_database_sha256_mismatch" in result.stderr
    assert not out_db.exists()
    assert not out_audit.exists()


@pytest.mark.parametrize("input_kind", ["draft", "source"])
@pytest.mark.parametrize("suffix", ["-wal", "-shm", "-journal"])
def test_cli_rejects_sqlite_sidecars_without_changing_bytes(
    tmp_path: Path, input_kind: str, suffix: str
) -> None:
    draft_db, draft_audit, source_db, _ = _make_inputs(tmp_path)
    input_db = draft_db if input_kind == "draft" else source_db
    sidecar = input_db.with_name(input_db.name + suffix)
    sidecar.write_bytes(b"unsealed input")
    before = {
        path: path.read_bytes()
        for path in (draft_db, draft_audit, source_db, sidecar)
    }
    out_db = tmp_path / "out.sqlite"
    out_audit = tmp_path / "out.audit.json"

    with pytest.raises(ValueError, match="sqlite_input_unsealed"):
        builder.main([
            "--draft-db", str(draft_db),
            "--draft-audit", str(draft_audit),
            "--source-db", str(source_db),
            "--out-db", str(out_db),
            "--out-audit", str(out_audit),
        ])
    assert {path: path.read_bytes() for path in before} == before
    assert not out_db.exists()
    assert not out_audit.exists()


@pytest.mark.parametrize(
    ("booking_rows", "expected"),
    [
        ([], "source_booking_missing"),
        ([(7, "REAL-BOOKING-7"), (7, "OTHER-BOOKING-7")], "source_booking_ambiguous"),
    ],
)
def test_cli_rejects_missing_or_ambiguous_source_booking(
    tmp_path: Path,
    booking_rows: list[tuple[int, str]],
    expected: str,
) -> None:
    draft_db, draft_audit, source_db, _ = _make_inputs(
        tmp_path, booking_rows=booking_rows
    )
    out_db = tmp_path / "out.sqlite"
    out_audit = tmp_path / "out.audit.json"
    with pytest.raises(ValueError, match=expected):
        builder.main([
            "--draft-db", str(draft_db),
            "--draft-audit", str(draft_audit),
            "--source-db", str(source_db),
            "--out-db", str(out_db),
            "--out-audit", str(out_audit),
        ])
    assert not out_db.exists()
    assert not out_audit.exists()


def test_cli_success_preserves_inputs_and_records_final_hash(tmp_path: Path) -> None:
    draft_db, draft_audit, source_db, _ = _make_inputs(tmp_path)
    before_run = datetime.now(timezone.utc)
    before = {
        path: path.read_bytes()
        for path in (draft_db, draft_audit, source_db)
    }
    out_db = tmp_path / "out.sqlite"
    out_audit = tmp_path / "out.audit.json"

    result = subprocess.run(
        _cli_args(draft_db, draft_audit, source_db, out_db, out_audit),
        cwd=ROOT,
        capture_output=True,
    )
    after_run = datetime.now(timezone.utc)
    assert result.returncode == 0, result.stderr
    assert out_db.exists()
    assert out_audit.exists()
    assert {path: path.read_bytes() for path in before} == before

    output_audit = json.loads(out_audit.read_text(encoding="utf-8"))
    assert output_audit["database_sha256"] == file_sha256(out_db)
    assert output_audit["audit_db_sha256"] == file_sha256(out_db)
    assert output_audit["batches"] == 1
    assert output_audit["lines"] == 2
    assert output_audit["semantic_schema_version"] == builder.SEMANTIC_SCHEMA_VERSION
    assert output_audit["semantic_sha256"] == builder._stable_semantic_sha256(out_db)

    check = sqlite3.connect(out_db)
    try:
        batch = check.execute(
            "SELECT payment_id,booking_id,booking_number,amount_krw,"
            "posting_eligible,authoritative_posting,external_posting "
            "FROM direct_agoda_journal_shadow_v3_batches"
        ).fetchone()
        lines = check.execute(
            "SELECT side,amount_krw FROM direct_agoda_journal_shadow_v3_lines "
            "ORDER BY line_no"
        ).fetchall()
        created_at = check.execute(
            "SELECT created_at FROM direct_agoda_journal_shadow_v3_manifest"
        ).fetchone()[0]
    finally:
        check.close()
    assert batch == (1, 7, "REAL-BOOKING-7", 12_500, 0, 0, 0)
    assert lines == [("debit", 12_500), ("credit", 12_500)]
    created = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
    assert before_run <= created <= after_run


def test_cli_wal_inputs_do_not_gain_sidecars_or_change_hashes(
    tmp_path: Path,
) -> None:
    input_dir = tmp_path / "inputs"
    draft_db, draft_audit, source_db, _ = _make_inputs(
        tmp_path, input_dir=input_dir, wal=True
    )
    before_files = sorted(
        path.relative_to(input_dir).as_posix()
        for path in input_dir.rglob("*")
    )
    before_hashes = {
        path: file_sha256(path) for path in (draft_db, draft_audit, source_db)
    }
    output_dir = tmp_path / "outputs"
    output_dir.mkdir()
    out_db = output_dir / "out.sqlite"
    out_audit = output_dir / "out.audit.json"

    result = subprocess.run(
        _cli_args(draft_db, draft_audit, source_db, out_db, out_audit),
        cwd=ROOT,
        capture_output=True,
    )
    assert result.returncode == 0, result.stderr
    after_files = sorted(
        path.relative_to(input_dir).as_posix()
        for path in input_dir.rglob("*")
    )
    assert after_files == before_files
    assert {
        path: file_sha256(path) for path in (draft_db, draft_audit, source_db)
    } == before_hashes


@pytest.mark.parametrize("output_kind", ["db", "audit"])
def test_broken_output_symlink_is_rejected_without_creating_target(
    tmp_path: Path, output_kind: str
) -> None:
    draft_db, draft_audit, source_db, _ = _make_inputs(tmp_path)
    out_db = tmp_path / "out.sqlite"
    out_audit = tmp_path / "out.audit.json"
    output_path = out_db if output_kind == "db" else out_audit
    missing_target = tmp_path / f"missing-{output_kind}-target"
    output_path.symlink_to(missing_target)

    with pytest.raises(FileExistsError, match="refusing_to_overwrite"):
        builder.main([
            "--draft-db", str(draft_db),
            "--draft-audit", str(draft_audit),
            "--source-db", str(source_db),
            "--out-db", str(out_db),
            "--out-audit", str(out_audit),
        ])
    assert output_path.is_symlink()
    assert not missing_target.exists()


def test_output_input_and_hardlink_collisions_do_not_change_input(tmp_path: Path) -> None:
    draft_db, draft_audit, source_db, _ = _make_inputs(tmp_path)
    before = draft_db.read_bytes()
    with pytest.raises(ValueError, match="output_input_path_collision"):
        builder.main([
            "--draft-db", str(draft_db),
            "--draft-audit", str(draft_audit),
            "--source-db", str(source_db),
            "--out-db", str(draft_db),
            "--out-audit", str(tmp_path / "out.audit.json"),
        ])
    assert draft_db.read_bytes() == before

    hardlink = tmp_path / "hardlink.sqlite"
    hardlink.hardlink_to(draft_db)
    with pytest.raises(ValueError, match="output_input_path_collision"):
        builder.main([
            "--draft-db", str(draft_db),
            "--draft-audit", str(draft_audit),
            "--source-db", str(source_db),
            "--out-db", str(hardlink),
            "--out-audit", str(tmp_path / "hardlink.audit.json"),
        ])
    assert draft_db.read_bytes() == before


def test_preexisting_output_is_preserved(tmp_path: Path) -> None:
    draft_db, draft_audit, source_db, _ = _make_inputs(tmp_path)
    out_db = tmp_path / "out.sqlite"
    out_audit = tmp_path / "out.audit.json"
    sentinel = b"keep this output"
    out_db.write_bytes(sentinel)

    with pytest.raises(FileExistsError, match="refusing_to_overwrite"):
        builder.main([
            "--draft-db", str(draft_db),
            "--draft-audit", str(draft_audit),
            "--source-db", str(source_db),
            "--out-db", str(out_db),
            "--out-audit", str(out_audit),
        ])
    assert out_db.read_bytes() == sentinel
    assert not out_audit.exists()


def test_second_publish_failure_rolls_back_only_own_output(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    draft_db, draft_audit, source_db, _ = _make_inputs(tmp_path)
    out_db = tmp_path / "out.sqlite"
    out_audit = tmp_path / "out.audit.json"
    original_publish = builder._publish_exclusive
    calls = 0

    def fail_second(staged: Path, output: Path) -> tuple[int, int]:
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError("injected_second_publish_failure")
        return original_publish(staged, output)

    monkeypatch.setattr(builder, "_publish_exclusive", fail_second)
    with pytest.raises(OSError, match="injected_second_publish_failure"):
        builder.main([
            "--draft-db", str(draft_db),
            "--draft-audit", str(draft_audit),
            "--source-db", str(source_db),
            "--out-db", str(out_db),
            "--out-audit", str(out_audit),
        ])
    assert not out_db.exists()
    assert not out_audit.exists()
    assert not list(tmp_path.glob(f".{out_db.name}.*.tmp"))
    assert not list(tmp_path.glob(f".{out_audit.name}.*.tmp"))


def test_semantic_digest_is_path_and_row_order_independent(tmp_path: Path) -> None:
    rows = [
        {**_row(payment_id=1, booking_id=7, amount_krw=12_500), "booking_number": None},
        {**_row(payment_id=2, booking_id=8, amount_krw=33_000), "booking_number": None},
    ]
    booking_rows = [(7, "REAL-BOOKING-7"), (8, "REAL-BOOKING-8")]
    left = _make_inputs(
        tmp_path,
        rows=rows,
        booking_rows=booking_rows,
        input_dir=tmp_path / "left" / "inputs",
    )
    right = _make_inputs(
        tmp_path,
        rows=list(reversed(rows)),
        booking_rows=booking_rows,
        input_dir=tmp_path / "right" / "inputs",
    )
    left_output = tmp_path / "left" / "outputs"
    right_output = tmp_path / "right" / "outputs"
    left_output.mkdir()
    right_output.mkdir()
    left_db = left_output / "shadow.sqlite"
    left_audit = left_output / "shadow.audit.json"
    right_db = right_output / "shadow.sqlite"
    right_audit = right_output / "shadow.audit.json"
    left_draft, left_draft_audit, left_source, _ = left
    right_draft, right_draft_audit, right_source, _ = right

    _run_main(left_draft, left_draft_audit, left_source, left_db, left_audit)
    _run_main(right_draft, right_draft_audit, right_source, right_db, right_audit)

    left_raw = json.loads(left_audit.read_text(encoding="utf-8"))
    right_raw = json.loads(right_audit.read_text(encoding="utf-8"))
    assert left_raw["semantic_schema_version"] == builder.SEMANTIC_SCHEMA_VERSION
    assert left_raw["semantic_sha256"] == right_raw["semantic_sha256"]
    assert left_raw["batches"] == right_raw["batches"] == 2
    assert left_raw["lines"] == right_raw["lines"] == 4
    assert left_raw["total_amount_krw"] == right_raw["total_amount_krw"] == 45_500
    assert builder._stable_semantic_sha256(left_db) == left_raw["semantic_sha256"]
    assert builder._stable_semantic_sha256(right_db) == right_raw["semantic_sha256"]


@pytest.mark.parametrize(
    "changed_field",
    ["amount_krw", "booking_number", "travel", "assigned_target"],
)
def test_semantic_digest_changes_for_one_business_field(
    tmp_path: Path, changed_field: str
) -> None:
    base_row = {**_row(), "booking_number": None}
    changed_row = dict(base_row)
    base_booking_rows = [(7, "REAL-BOOKING-7")]
    changed_booking_rows = base_booking_rows
    if changed_field == "amount_krw":
        changed_row["amount_krw"] = 12_501
    elif changed_field == "booking_number":
        changed_booking_rows = [(7, "CHANGED-BOOKING-7")]
    elif changed_field == "travel":
        changed_row["service_start_on"] = "2026-08-11"
    else:
        base_row["target_match_status"] = "bound_unique"
        changed_row["target_match_status"] = "bound_unique"
        base_row["allocation_target"] = "TARGET-A"
        changed_row["allocation_target"] = "TARGET-B"

    base = _make_inputs(
        tmp_path,
        rows=[base_row],
        booking_rows=base_booking_rows,
        input_dir=tmp_path / "base" / "inputs",
    )
    changed = _make_inputs(
        tmp_path,
        rows=[changed_row],
        booking_rows=changed_booking_rows,
        input_dir=tmp_path / "changed" / "inputs",
    )
    base_output = tmp_path / "base" / "outputs"
    changed_output = tmp_path / "changed" / "outputs"
    base_output.mkdir()
    changed_output.mkdir()
    base_db = base_output / "shadow.sqlite"
    base_audit = base_output / "shadow.audit.json"
    changed_db = changed_output / "shadow.sqlite"
    changed_audit = changed_output / "shadow.audit.json"
    base_draft, base_draft_audit, base_source, _ = base
    changed_draft, changed_draft_audit, changed_source, _ = changed

    _run_main(base_draft, base_draft_audit, base_source, base_db, base_audit)
    _run_main(
        changed_draft,
        changed_draft_audit,
        changed_source,
        changed_db,
        changed_audit,
    )

    base_raw = json.loads(base_audit.read_text(encoding="utf-8"))
    changed_raw = json.loads(changed_audit.read_text(encoding="utf-8"))
    assert base_raw["semantic_schema_version"] == changed_raw[
        "semantic_schema_version"
    ] == builder.SEMANTIC_SCHEMA_VERSION
    assert base_raw["semantic_sha256"] != changed_raw["semantic_sha256"]
    if changed_field == "assigned_target":
        base_check = sqlite3.connect(base_db)
        changed_check = sqlite3.connect(changed_db)
        try:
            assert base_check.execute(
                "SELECT assigned_target "
                "FROM direct_agoda_journal_shadow_v3_batches"
            ).fetchone()[0] == "TARGET-A"
            assert changed_check.execute(
                "SELECT assigned_target "
                "FROM direct_agoda_journal_shadow_v3_batches"
            ).fetchone()[0] == "TARGET-B"
        finally:
            base_check.close()
            changed_check.close()


def test_same_output_retry_is_rejected_without_mutating_any_file(
    tmp_path: Path,
) -> None:
    draft_db, draft_audit, source_db, _ = _make_inputs(tmp_path)
    out_db = tmp_path / "out.sqlite"
    out_audit = tmp_path / "out.audit.json"
    _run_main(draft_db, draft_audit, source_db, out_db, out_audit)
    before = {
        path: path.read_bytes()
        for path in (draft_db, draft_audit, source_db, out_db, out_audit)
    }

    with pytest.raises(FileExistsError, match="refusing_to_overwrite"):
        _run_main(draft_db, draft_audit, source_db, out_db, out_audit)

    assert {path: path.read_bytes() for path in before} == before


@pytest.mark.parametrize(
    "table",
    [
        "direct_agoda_journal_shadow_v3_batches",
        "direct_agoda_journal_shadow_v3_lines",
    ],
)
def test_semantic_schema_contract_rejects_new_column(
    tmp_path: Path, table: str
) -> None:
    draft_db, draft_audit, source_db, _ = _make_inputs(tmp_path)
    out_db = tmp_path / "out.sqlite"
    out_audit = tmp_path / "out.audit.json"
    _run_main(draft_db, draft_audit, source_db, out_db, out_audit)

    db = sqlite3.connect(out_db)
    try:
        db.execute(f"ALTER TABLE {table} ADD COLUMN new_business_field TEXT")
        db.commit()
    finally:
        db.close()

    with pytest.raises(ValueError, match="semantic_schema_mismatch"):
        builder._stable_semantic_sha256(out_db)
