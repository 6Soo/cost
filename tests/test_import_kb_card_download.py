"""Synthetic verification for tools/import_kb_card_download.py.

Only synthetic files and synthetic SQLite databases are used: no real card
portal, login session, customer data or operational database is touched. The
domestic XLS fixture is the repository's existing synthetic sheet; overseas and
conflict variants are synthetic CSVs. The tool must reuse the existing
parser/preflight/receive path, never write the target during preview, and gate
--apply behind a fresh backup with a verified separate restore.
"""
from __future__ import annotations

import csv
import hashlib
import importlib.util
import io
import json
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app import Pipeline
from app.db import Store
from app.import_card import parse_card_file

SPEC = importlib.util.spec_from_file_location(
    "import_kb_card_download", ROOT / "tools" / "import_kb_card_download.py")
tool = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(tool)

DOMESTIC_XLS = ROOT / "tests" / "card_pipeline" / "data" / "kb-domestic-acquired-synthetic.xls"
DOMESTIC_SOURCE = "국민 기업카드 국내 매입"
OVERSEAS_SOURCE = "국민 기업카드 해외 매입"

OVERSEAS_HEADERS = ["카드사", "카드번호", "거래일", "매입일", "가맹점명",
                    "외화금액", "통화", "원화금액", "구분", "상태"]
OVERSEAS_ROWS = [
    ["국민", "5585-26**-****-3820", "2026.10.05", "2026.10.07", "Synthetic Overseas Hotel",
     "100.00", "USD", "140000", "일시불", "정상"],
    ["국민", "5585-26**-****-3820", "2026.10.05", "2026.10.07", "Synthetic Overseas Hotel",
     "100.00", "USD", "140000", "일시불", "정상"],
    ["국민", "5585-26**-****-3820", "2026.10.06", "2026.10.08", "Synthetic Overseas Hotel",
     "100.00", "USD", "140000", "취소", "취소"],
]
DOMESTIC_CSV_HEADERS = ["카드사", "카드번호", "승인일", "매입일", "가맹점명",
                        "이용금액", "승인번호", "구분", "상태"]


def csv_bytes(headers, rows) -> bytes:
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(headers)
    writer.writerows(rows)
    return buffer.getvalue().encode("utf-8-sig")


def domestic_csv(amount="12000") -> bytes:
    return csv_bytes(DOMESTIC_CSV_HEADERS, [
        ["국민", "5585-26**-****-3820", "2026.10.01", "2026.10.02", "합성편의점",
         amount, "71000001", "일시불", "정상"],
    ])


def make_run(tmp_path, specs, name="run"):
    run_dir = tmp_path / name
    run_dir.mkdir()
    rows = []
    for spec in specs:
        content = spec["content"]
        path = run_dir / spec["filename"]
        path.write_bytes(content)
        try:
            parsed = parse_card_file(content, spec["filename"], use_cache=False)
            row_count, issues = len(parsed.rows), len(parsed.issues)
        except Exception:
            row_count, issues = 0, 0
        row = {
            "source": spec["source"],
            "sourceUrl": "https://biz.kbcard.com/synthetic",
            "query": {"startDate": "2026-10-01", "endDate": "2026-11-12", "postingAxis": "매입일"},
            "summary": {"available": True, "pageTotalCount": row_count},
            "file": {"savedPath": str(path), "bytes": len(content),
                     "sha256": hashlib.sha256(content).hexdigest(), "kind": "xls"},
            "verification": {"status": "ok"},
            "parserVerification": {"status": "PARSER_VERIFICATION_OK",
                                   "rows": row_count, "parse_issues": issues},
            "countCheck": {"status": "MATCHED"},
            "duplicateCheck": {"scope": "file_sha256_only", "status": "NO_FILE_MATCH",
                               "databaseRows": "NOT_RUN"},
        }
        for key, value in (spec.get("overrides") or {}).items():
            if isinstance(value, dict) and isinstance(row.get(key), dict):
                row[key].update(value)
            else:
                row[key] = value
        rows.append(row)
    manifest = {"schemaVersion": "cost.kb-card-collection-manifest.v1",
                "runId": "synthetic", "generatedAt": "2026-11-13T00:00:00.000Z",
                "executionDate": "2026-11-13",
                "requestedSources": sorted({spec["source"] for spec in specs}),
                "rows": rows, "importBoundary": {"status": "NOT_RUN"}}
    (run_dir / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False),
                                           encoding="utf-8")
    return run_dir


def make_db(tmp_path, name="board.sqlite"):
    path = tmp_path / name
    store = Store.open(str(path))
    store.close()
    return path


def seed_receive(db_path, content, filename):
    store = Store.open(str(db_path))
    try:
        return Pipeline(store).receive(content, filename)
    finally:
        store.close()


def read_only(db_path):
    conn = sqlite3.connect(Path(db_path).resolve().as_uri() + "?mode=ro", uri=True)
    conn.execute("PRAGMA query_only=ON")
    return conn


def invoke(capsys, *args):
    code = tool.main(list(args))
    return code, json.loads(capsys.readouterr().out)


def both_files_spec():
    return [
        {"source": DOMESTIC_SOURCE,
         "filename": "kb-domestic-acquired-2026-10-01-2026-11-12.xls",
         "content": DOMESTIC_XLS.read_bytes()},
        {"source": OVERSEAS_SOURCE,
         "filename": "kb-overseas-acquired-2026-10-01-2026-11-12.csv",
         "content": csv_bytes(OVERSEAS_HEADERS, OVERSEAS_ROWS)},
    ]


def test_preview_valid_run_rehearses_and_never_writes_target(tmp_path, capsys):
    run_dir = make_run(tmp_path, both_files_spec())
    db = make_db(tmp_path)
    before = hashlib.sha256(db.read_bytes()).hexdigest()
    code, report = invoke(capsys, "--run-dir", str(run_dir), "--db", str(db))
    assert code == 0
    assert report["status"] == "safe"
    assert report["files"][0]["receipt"]["inserted"] == 3
    assert report["files"][1]["receipt"]["inserted"] == 3
    assert report["files"][0]["count_check"] == "MATCHED"
    assert report["rehearsal"]["protection"]["ok"] is True
    assert report["rehearsal"]["reupload_idempotent"] is True
    assert report["rehearsal"]["source_data_version_unchanged"] is True
    assert report["apply"]["status"] == "NOT_RUN"
    assert report["boundaries"]["ledger_commit"] == "NOT_RUN"
    assert hashlib.sha256(db.read_bytes()).hexdigest() == before
    conn = read_only(db)
    try:
        assert conn.execute("SELECT COUNT(*) FROM transactions").fetchone()[0] == 0
    finally:
        conn.close()


def test_preview_same_transactions_in_new_file_are_duplicates(tmp_path, capsys):
    overseas = csv_bytes(OVERSEAS_HEADERS, OVERSEAS_ROWS)
    db = make_db(tmp_path)
    seed_receive(db, overseas, "kb-overseas-seed.csv")
    # Trailing blank line: different bytes, same economic rows.
    run_dir = make_run(tmp_path, [
        {"source": OVERSEAS_SOURCE, "filename": "kb-overseas-acquired.csv",
         "content": overseas + b"\n"},
    ])
    code, report = invoke(capsys, "--run-dir", str(run_dir), "--db", str(db))
    assert code == 0
    receipt = report["files"][0]["receipt"]
    assert receipt["reused"] is False
    assert receipt["inserted"] == 0
    assert receipt["already_present"] == 3
    assert receipt["matched_by_content"] == 3
    assert report["rehearsal"]["protection"]["ok"] is True


def test_preview_keyless_multiplicity_keeps_real_duplicates(tmp_path, capsys):
    db = make_db(tmp_path)
    one_row = csv_bytes(OVERSEAS_HEADERS, OVERSEAS_ROWS[:1])
    seed_receive(db, one_row, "kb-overseas-seed.csv")
    run_dir = make_run(tmp_path, [
        {"source": OVERSEAS_SOURCE, "filename": "kb-overseas-acquired.csv",
         "content": csv_bytes(OVERSEAS_HEADERS, OVERSEAS_ROWS)},
    ])
    code, report = invoke(capsys, "--run-dir", str(run_dir), "--db", str(db))
    assert code == 0
    receipt = report["files"][0]["receipt"]
    # One of the two identical payments is already recorded; the second real
    # payment and the cancellation stay new.
    assert receipt["already_present"] == 1
    assert receipt["inserted"] == 2
    assert receipt["conflicts"] == 0


def test_preview_conflict_preserves_existing_row(tmp_path, capsys):
    db = make_db(tmp_path)
    seed_receive(db, domestic_csv("12000"), "kb-domestic-seed.csv")
    run_dir = make_run(tmp_path, [
        {"source": DOMESTIC_SOURCE, "filename": "kb-domestic-acquired.csv",
         "content": domestic_csv("13000")},
    ])
    code, report = invoke(capsys, "--run-dir", str(run_dir), "--db", str(db))
    assert code == 0
    receipt = report["files"][0]["receipt"]
    assert receipt["conflicts"] == 1
    assert receipt["inserted"] == 0
    assert report["rehearsal"]["protection"]["existing_transaction_rows_changed"] == 0
    assert report["rehearsal"]["protection"]["ok"] is True
    conn = read_only(db)
    try:
        assert conn.execute(
            "SELECT amount_krw FROM transactions WHERE approval_number='71000001'"
            " AND transaction_id NOT LIKE '%:conflict:%'").fetchone()[0] == 12000
    finally:
        conn.close()


def test_tampered_file_is_rejected(tmp_path, capsys):
    run_dir = make_run(tmp_path, both_files_spec())
    victim = run_dir / "kb-domestic-acquired-2026-10-01-2026-11-12.xls"
    data = bytearray(victim.read_bytes())
    data[-1] ^= 0xFF
    victim.write_bytes(bytes(data))
    db = make_db(tmp_path)
    code, report = invoke(capsys, "--run-dir", str(run_dir), "--db", str(db))
    assert code == 2
    assert report["status"] == "error"
    assert report["error"]["code"] == "FILE_HASH_MISMATCH"


def test_login_html_page_is_rejected(tmp_path, capsys):
    run_dir = make_run(tmp_path, [
        {"source": DOMESTIC_SOURCE, "filename": "kb-domestic-acquired.xls",
         "content": b"<!doctype html><html><body>login required</body></html>"},
    ])
    db = make_db(tmp_path)
    code, report = invoke(capsys, "--run-dir", str(run_dir), "--db", str(db))
    assert code == 2
    assert report["error"]["code"] == "FORMAT_INVALID"


def test_screen_count_mismatch_is_rejected(tmp_path, capsys):
    specs = both_files_spec()
    specs[0]["overrides"] = {"summary": {"pageTotalCount": 99}}
    run_dir = make_run(tmp_path, specs)
    db = make_db(tmp_path)
    code, report = invoke(capsys, "--run-dir", str(run_dir), "--db", str(db))
    assert code == 2
    assert report["error"]["code"] == "COUNT_MISMATCH"


def test_channel_mismatch_is_rejected(tmp_path, capsys):
    run_dir = make_run(tmp_path, [
        {"source": DOMESTIC_SOURCE, "filename": "kb-domestic-acquired.csv",
         "content": csv_bytes(OVERSEAS_HEADERS, OVERSEAS_ROWS)},
    ])
    db = make_db(tmp_path)
    code, report = invoke(capsys, "--run-dir", str(run_dir), "--db", str(db))
    assert code == 2
    assert report["error"]["code"] == "CHANNEL_MISMATCH"


def test_manifest_is_required(tmp_path, capsys):
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    db = make_db(tmp_path)
    code, report = invoke(capsys, "--run-dir", str(run_dir), "--db", str(db))
    assert code == 2
    assert report["error"]["code"] == "MANIFEST_REQUIRED"


def test_failed_collection_row_blocks_import(tmp_path, capsys):
    specs = both_files_spec()
    specs[0]["overrides"] = {"verification": {"status": "failed"}}
    run_dir = make_run(tmp_path, specs)
    db = make_db(tmp_path)
    code, report = invoke(capsys, "--run-dir", str(run_dir), "--db", str(db))
    assert code == 2
    assert report["error"]["code"] == "COLLECTION_NOT_VERIFIED"


def test_unverified_collection_count_blocks_import(tmp_path, capsys):
    specs = both_files_spec()
    specs[0]["overrides"] = {"countCheck": {"status": "NOT_VERIFIED"}}
    run_dir = make_run(tmp_path, specs)
    db = make_db(tmp_path)
    code, report = invoke(capsys, "--run-dir", str(run_dir), "--db", str(db))
    assert code == 2
    assert report["error"]["code"] == "COLLECTION_COUNT_NOT_VERIFIED"


def test_parse_issue_row_is_rejected(tmp_path, capsys):
    run_dir = make_run(tmp_path, [
        {"source": DOMESTIC_SOURCE, "filename": "kb-domestic-acquired.csv",
         "content": domestic_csv("금액알수없음")},
    ])
    db = make_db(tmp_path)
    code, report = invoke(capsys, "--run-dir", str(run_dir), "--db", str(db))
    assert code == 2
    assert report["error"]["code"] == "PARSE_ISSUES"


def test_no_data_rows_are_skipped(tmp_path, capsys):
    specs = both_files_spec()[:1]
    run_dir = make_run(tmp_path, specs)
    manifest_path = run_dir / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["rows"].append({
        "source": OVERSEAS_SOURCE,
        "sourceUrl": "https://biz.kbcard.com/synthetic",
        "query": {"startDate": "2026-10-01", "endDate": "2026-11-12", "postingAxis": "매입일"},
        "summary": {"available": True, "pageTotalCount": 0},
        "file": None,
        "verification": {"status": "no_data", "basis": "조회요약 0건"},
        "parserVerification": None,
    })
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")
    db = make_db(tmp_path)
    code, report = invoke(capsys, "--run-dir", str(run_dir), "--db", str(db))
    assert code == 0
    assert len(report["files"]) == 1
    assert len(report["no_data_sources"]) == 1
    assert report["no_data_sources"][0]["source"] == OVERSEAS_SOURCE


def test_apply_requires_backup_dir_and_single_writer_confirmation(tmp_path, capsys):
    run_dir = make_run(tmp_path, both_files_spec())
    db = make_db(tmp_path)
    before = hashlib.sha256(db.read_bytes()).hexdigest()
    code, report = invoke(capsys, "--run-dir", str(run_dir), "--db", str(db), "--apply")
    assert code == 2
    assert report["error"]["code"] == "BACKUP_DIR_REQUIRED"
    code, report = invoke(capsys, "--run-dir", str(run_dir), "--db", str(db),
                          "--apply", "--backup-dir", str(tmp_path / "backups"))
    assert code == 2
    assert report["error"]["code"] == "SINGLE_WRITER_REQUIRED"
    assert hashlib.sha256(db.read_bytes()).hexdigest() == before


def test_apply_writes_through_receive_and_repeat_apply_is_reused(tmp_path, capsys):
    run_dir = make_run(tmp_path, both_files_spec())
    db = make_db(tmp_path)
    backup_dir = tmp_path / "backups"
    args = ["--run-dir", str(run_dir), "--db", str(db), "--apply",
            "--backup-dir", str(backup_dir), "--confirm-single-writer"]
    code, report = invoke(capsys, *args)
    assert code == 0
    assert report["status"] == "safe"
    assert report["apply"]["status"] == "DONE"
    assert report["apply"]["restore"]["quick_check"] == "ok"
    assert report["apply"]["restore"]["transactions_digest_match"] is True
    assert report["apply"]["protection"]["ok"] is True
    assert report["apply"]["reupload_idempotent"] is True
    assert report["apply"]["kb_last_dates"]["domestic"]["last_use_date"] == "2026-10-02"
    assert len(list(backup_dir.glob("board-kb-import-*.sqlite"))) == 1
    conn = read_only(db)
    try:
        assert conn.execute("SELECT COUNT(*) FROM transactions").fetchone()[0] == 6
    finally:
        conn.close()
    code, report = invoke(capsys, *args)
    assert code == 0
    assert all(f["receipt"]["reused"] for f in report["files"])
    assert report["apply"]["protection"]["new_transaction_rows"] == 0
    assert len(list(backup_dir.glob("board-kb-import-*.sqlite"))) == 2
    conn = read_only(db)
    try:
        assert conn.execute("SELECT COUNT(*) FROM transactions").fetchone()[0] == 6
    finally:
        conn.close()


def test_apply_preserves_manual_decisions_and_ledger(tmp_path, capsys):
    db = make_db(tmp_path)
    seed_receive(db, DOMESTIC_XLS.read_bytes(), "kb-domestic-seed.xls")
    conn = sqlite3.connect(str(db), isolation_level=None)
    tid = conn.execute(
        "SELECT transaction_id FROM transactions ORDER BY row_index LIMIT 1").fetchone()[0]
    conn.execute(
        "UPDATE transactions SET classification_source='user_decision',"
        " classification_state='decided', item='식비', trip_id='trip-synthetic', revision=2"
        " WHERE transaction_id=?", (tid,))
    conn.execute(
        "INSERT INTO review_decisions(transaction_id, revision, item, description,"
        " display_tab_id, note, reuse_rule, decided_at)"
        " VALUES (?,?,?,?,?,?,0,?)",
        (tid, 2, "식비", "synthetic manual decision", "trip-synthetic", "synthetic",
         "2026-11-13T00:00:00+00:00"))
    conn.execute(
        "INSERT INTO ledger_entries(transaction_id, batch_id, item, description,"
        " display_tab_id, trip_id, amount_krw, merchant, occurred_on,"
        " transaction_direction, source_hash, committed_at)"
        " VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
        (tid, "batch-synthetic", "식비", "synthetic ledger row", "trip-synthetic",
         "trip-synthetic", 12000, "합성편의점", "2026-10-01", "purchase",
         "synthetic-hash", "2026-11-13T00:00:00+00:00"))
    before_row = conn.execute(
        "SELECT * FROM transactions WHERE transaction_id=?", (tid,)).fetchone()
    conn.close()
    run_dir = make_run(tmp_path, [
        {"source": OVERSEAS_SOURCE, "filename": "kb-overseas-acquired.csv",
         "content": csv_bytes(OVERSEAS_HEADERS, OVERSEAS_ROWS)},
    ])
    code, report = invoke(capsys, "--run-dir", str(run_dir), "--db", str(db),
                          "--apply", "--backup-dir", str(tmp_path / "backups"),
                          "--confirm-single-writer")
    assert code == 0
    assert report["apply"]["protection"]["existing_transaction_rows_changed"] == 0
    assert report["apply"]["protection"]["protected_tables_unchanged"] is True
    conn = read_only(db)
    try:
        assert conn.execute(
            "SELECT * FROM transactions WHERE transaction_id=?", (tid,)).fetchone() == before_row
        assert conn.execute("SELECT COUNT(*) FROM ledger_entries").fetchone()[0] == 1
        assert conn.execute("SELECT COUNT(*) FROM review_decisions").fetchone()[0] == 1
    finally:
        conn.close()


def test_schema_drift_is_refused_before_rehearsal(tmp_path, capsys):
    run_dir = make_run(tmp_path, both_files_spec())
    db = make_db(tmp_path)
    conn = sqlite3.connect(str(db), isolation_level=None)
    conn.execute("DROP INDEX transactions_batch")
    conn.close()
    code, report = invoke(capsys, "--run-dir", str(run_dir), "--db", str(db))
    assert code == 2
    assert report["error"]["code"] == "SCHEMA_MIGRATION_REQUIRED"
