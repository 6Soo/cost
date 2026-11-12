"""Synthetic verification for tools/import_kb_card_download.py.

Only synthetic files and synthetic SQLite databases are used: no real card
portal, login session, customer data or operational database is touched. The
domestic/overseas XLS fixtures are the repository's synthetic sheets; conflict
variants are synthetic CSVs. The tool must reuse the existing
parser/preflight/receive path, never write the target during preview, and gate
--apply behind the real writers-offline check (patched at the _writers_offline
seam), a fresh backup with a verified separate restore, and auto-restore on a
failed post-write check. Imported batches must land in the durable
classification queue exactly like the web upload.
"""
from __future__ import annotations

import csv
import hashlib
import importlib.util
import io
import json
import sqlite3
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

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
OVERSEAS_XLS = ROOT / "tests" / "fixtures" / "kb-overseas-acquired-synthetic.xls"
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


def gate_host(tmp_path, monkeypatch, port=8752):
    """Synthetic host root: route file + patched seam, never real tasks/ports."""
    host = tmp_path / "host"
    (host / "config").mkdir(parents=True, exist_ok=True)
    (host / "config" / "ledger-route.json").write_text(
        json.dumps({"port": port, "paused": True}), encoding="utf-8")
    calls = []
    monkeypatch.setattr(tool, "_writers_offline", lambda p: calls.append(p))
    return host, calls


def db_state(db_path):
    conn = read_only(db_path)
    try:
        return tool.protection_snapshot(conn), tool._table_counts(conn)
    finally:
        conn.close()


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


def test_apply_requires_backup_dir_and_route_gate(tmp_path, capsys, monkeypatch):
    run_dir = make_run(tmp_path, both_files_spec())
    db = make_db(tmp_path)
    before = db_state(db)
    code, report = invoke(capsys, "--run-dir", str(run_dir), "--db", str(db), "--apply")
    assert code == 2
    assert report["error"]["code"] == "BACKUP_DIR_REQUIRED"
    # No route file under the synthetic host root: refuse before any backup.
    empty_host = tmp_path / "empty-host"
    empty_host.mkdir()
    code, report = invoke(capsys, "--run-dir", str(run_dir), "--db", str(db),
                          "--apply", "--backup-dir", str(tmp_path / "backups"),
                          "--host-root", str(empty_host))
    assert code == 2
    assert report["error"]["code"] == "ROUTE_REQUIRED"
    assert report["apply"]["status"] == "FAILED"
    assert not (tmp_path / "backups").exists()
    assert db_state(db) == before


def test_apply_route_port_must_be_an_operational_board_port(tmp_path, capsys, monkeypatch):
    run_dir = make_run(tmp_path, both_files_spec())
    db = make_db(tmp_path)
    for port in (9999, "8752", None):
        host, calls = gate_host(tmp_path, monkeypatch, port=port)
        code, report = invoke(capsys, "--run-dir", str(run_dir), "--db", str(db),
                              "--apply", "--backup-dir", str(tmp_path / "backups"),
                              "--host-root", str(host))
        assert code == 2
        assert report["error"]["code"] == "ROUTE_PORT_INVALID"
        assert calls == []
        assert not (tmp_path / "backups").exists()


def test_apply_refuses_when_writers_are_not_offline(tmp_path, capsys, monkeypatch):
    run_dir = make_run(tmp_path, both_files_spec())
    db = make_db(tmp_path)
    before = db_state(db)
    host, _calls = gate_host(tmp_path, monkeypatch)

    def refuse(port):
        raise tool.ImportBoundaryError("WRITERS_NOT_OFFLINE")

    monkeypatch.setattr(tool, "_writers_offline", refuse)
    code, report = invoke(capsys, "--run-dir", str(run_dir), "--db", str(db),
                          "--apply", "--backup-dir", str(tmp_path / "backups"),
                          "--host-root", str(host))
    assert code == 2
    assert report["error"]["code"] == "WRITERS_NOT_OFFLINE"
    assert not (tmp_path / "backups").exists()
    assert db_state(db) == before


def test_writers_offline_helper_checks_tasks_and_routed_port(monkeypatch):
    from tools import complete_card_classification as ccc
    captured = {}

    class Result:
        def __init__(self, returncode):
            self.returncode = returncode

    def fake_run(cmd, capture_output=True):
        captured["cmd"] = cmd
        return Result(fake_run.returncode)

    fake_run.returncode = 0
    monkeypatch.setattr(ccc.subprocess, "run", fake_run)
    ccc.require_writers_offline(8752)
    assert captured["cmd"][:3] == ["powershell", "-NoProfile", "-Command"]
    script = captured["cmd"][3]
    assert "WebLedger-Board,WebLedger-SourceRefresh" in script
    assert "-LocalPort 8752" in script
    for returncode in (1, 2):
        fake_run.returncode = returncode
        with pytest.raises(ValueError, match="WRITERS_NOT_OFFLINE"):
            ccc.require_writers_offline(8752)


def test_writers_offline_seam_converts_value_error(monkeypatch):
    from tools import complete_card_classification as ccc

    def refuse(port):
        raise ValueError("WRITERS_NOT_OFFLINE")

    monkeypatch.setattr(ccc, "require_writers_offline", refuse)
    with pytest.raises(tool.ImportBoundaryError) as excinfo:
        tool._writers_offline(8752)
    assert excinfo.value.code == "WRITERS_NOT_OFFLINE"


def test_apply_writes_through_receive_and_repeat_apply_is_reused(tmp_path, capsys, monkeypatch):
    run_dir = make_run(tmp_path, both_files_spec())
    db = make_db(tmp_path)
    backup_dir = tmp_path / "backups"
    host, calls = gate_host(tmp_path, monkeypatch)
    args = ["--run-dir", str(run_dir), "--db", str(db), "--apply",
            "--backup-dir", str(backup_dir), "--host-root", str(host)]
    code, report = invoke(capsys, *args)
    assert code == 0
    assert report["status"] == "safe"
    assert report["apply"]["status"] == "DONE"
    assert calls == [8752]
    assert report["apply"]["gate"] == {"writers_offline": True, "route_port": 8752}
    assert report["apply"]["backup_evidence"]["fresh"] is True
    assert report["apply"]["backup_evidence"]["source_state_matched"] is True
    assert report["apply"]["restore"]["quick_check"] == "ok"
    assert report["apply"]["restore"]["transactions_digest_match"] is True
    assert report["apply"]["protection"]["ok"] is True
    assert report["apply"]["reupload_idempotent"] is True
    assert report["apply"]["queue"]["count"] == 2
    assert report["apply"]["queue"]["resume"] == "SERVER_RESTART"
    assert report["boundaries"]["classification"] == "QUEUED"
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


def test_apply_preserves_manual_decisions_and_ledger(tmp_path, capsys, monkeypatch):
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
    host, _calls = gate_host(tmp_path, monkeypatch)
    code, report = invoke(capsys, "--run-dir", str(run_dir), "--db", str(db),
                          "--apply", "--backup-dir", str(tmp_path / "backups"),
                          "--host-root", str(host))
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


def test_file_outside_run_dir_is_rejected(tmp_path, capsys):
    run_dir = make_run(tmp_path, both_files_spec()[:1])
    manifest_path = run_dir / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    inside = Path(manifest["rows"][0]["file"]["savedPath"])
    outside = tmp_path / "outside.xls"
    inside.rename(outside)
    manifest["rows"][0]["file"]["savedPath"] = str(outside)
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")
    db = make_db(tmp_path)
    code, report = invoke(capsys, "--run-dir", str(run_dir), "--db", str(db))
    assert code == 2
    assert report["error"]["code"] == "FILE_OUTSIDE_RUN_DIR"


def test_backup_refuses_to_overwrite(tmp_path):
    db = make_db(tmp_path)
    target = tmp_path / "backup.sqlite"
    tool.backup_database(db, target)
    with pytest.raises(tool.ImportBoundaryError) as excinfo:
        tool.backup_database(db, target)
    assert excinfo.value.code == "BACKUP_EXISTS"


def test_fresh_backup_evidence_rules(tmp_path):
    db = make_db(tmp_path)
    backup = tmp_path / "backup.sqlite"
    tool.backup_database(db, backup)
    now = datetime.now(timezone.utc)
    evidence = tool.require_fresh_backup(db, backup, now)
    assert evidence["fresh"] is True
    assert evidence["source_state_matched"] is True
    for recorded_at in (now - timedelta(hours=2), now + timedelta(hours=1)):
        with pytest.raises(tool.ImportBoundaryError) as excinfo:
            tool.require_fresh_backup(db, backup, recorded_at)
        assert excinfo.value.code == "BACKUP_NOT_FRESH"
    seed_receive(db, domestic_csv(), "kb-domestic-seed.csv")
    with pytest.raises(tool.ImportBoundaryError) as excinfo:
        tool.require_fresh_backup(db, backup, now)
    assert excinfo.value.code == "BACKUP_SOURCE_CHANGED"


def test_apply_rehearsal_hold_writes_nothing(tmp_path, capsys, monkeypatch):
    run_dir = make_run(tmp_path, both_files_spec())
    db = make_db(tmp_path)
    before = db_state(db)
    host, _calls = gate_host(tmp_path, monkeypatch)
    real_report = tool.protection_report

    def failing_report(before_snap, after_snap):
        result = real_report(before_snap, after_snap)
        result["ok"] = False
        return result

    monkeypatch.setattr(tool, "protection_report", failing_report)
    code, report = invoke(capsys, "--run-dir", str(run_dir), "--db", str(db),
                          "--apply", "--backup-dir", str(tmp_path / "backups"),
                          "--host-root", str(host))
    assert code == 2
    assert report["error"]["code"] == "REHEARSAL_HOLD"
    assert report["apply"]["status"] == "FAILED"
    assert "restored" not in report["apply"]
    assert db_state(db) == before


def test_apply_plan_changed_before_write_does_not_restore(tmp_path, capsys, monkeypatch):
    run_dir = make_run(tmp_path, both_files_spec())
    db = make_db(tmp_path)
    before = db_state(db)
    host, _calls = gate_host(tmp_path, monkeypatch)
    real_rehearse = tool.rehearse

    def stale_rehearse(db_path, files, work_dir, label):
        result = real_rehearse(db_path, files, work_dir, label)
        result["before"]["transactions"]["synthetic-stale"] = "deadbeef"
        return result

    monkeypatch.setattr(tool, "rehearse", stale_rehearse)
    code, report = invoke(capsys, "--run-dir", str(run_dir), "--db", str(db),
                          "--apply", "--backup-dir", str(tmp_path / "backups"),
                          "--host-root", str(host))
    assert code == 2
    assert report["error"]["code"] == "PLAN_CHANGED"
    assert report["apply"]["status"] == "FAILED"
    assert "restored" not in report["apply"]
    assert db_state(db) == before


def test_apply_plan_changed_after_write_auto_restores(tmp_path, capsys, monkeypatch):
    run_dir = make_run(tmp_path, both_files_spec())
    db = make_db(tmp_path)
    before = db_state(db)
    host, _calls = gate_host(tmp_path, monkeypatch)
    real_rehearse = tool.rehearse

    def divergent_rehearse(db_path, files, work_dir, label):
        result = real_rehearse(db_path, files, work_dir, label)
        result["receipts"][0]["inserted"] += 99
        return result

    monkeypatch.setattr(tool, "rehearse", divergent_rehearse)
    code, report = invoke(capsys, "--run-dir", str(run_dir), "--db", str(db),
                          "--apply", "--backup-dir", str(tmp_path / "backups"),
                          "--host-root", str(host))
    assert code == 2
    assert report["error"]["code"] == "PLAN_CHANGED"
    assert report["apply"]["status"] == "FAILED"
    assert report["apply"]["restored"]["restored"] is True
    assert report["apply"]["restored"]["verified"] is True
    assert db_state(db) == before
    conn = read_only(db)
    try:
        assert conn.execute("SELECT COUNT(*) FROM transactions").fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM requests").fetchone()[0] == 0
    finally:
        conn.close()


def test_apply_protection_failure_after_write_auto_restores(tmp_path, capsys, monkeypatch):
    run_dir = make_run(tmp_path, both_files_spec())
    db = make_db(tmp_path)
    before = db_state(db)
    host, _calls = gate_host(tmp_path, monkeypatch)
    real_report = tool.protection_report
    calls = {"n": 0}

    def fail_second_report(before_snap, after_snap):
        calls["n"] += 1
        result = real_report(before_snap, after_snap)
        if calls["n"] >= 2:
            result["ok"] = False
        return result

    monkeypatch.setattr(tool, "protection_report", fail_second_report)
    code, report = invoke(capsys, "--run-dir", str(run_dir), "--db", str(db),
                          "--apply", "--backup-dir", str(tmp_path / "backups"),
                          "--host-root", str(host))
    assert code == 2
    assert report["error"]["code"] == "PROTECTION_FAILED"
    assert report["apply"]["restored"]["restored"] is True
    assert report["apply"]["restored"]["verified"] is True
    assert db_state(db) == before


def test_apply_writers_online_before_restore_skips_restore(tmp_path, capsys, monkeypatch):
    run_dir = make_run(tmp_path, both_files_spec())
    db = make_db(tmp_path)
    host, calls = gate_host(tmp_path, monkeypatch)
    real_rehearse = tool.rehearse

    def divergent_rehearse(db_path, files, work_dir, label):
        result = real_rehearse(db_path, files, work_dir, label)
        result["receipts"][0]["inserted"] += 99
        return result

    monkeypatch.setattr(tool, "rehearse", divergent_rehearse)

    # Gate passes once; the pre-restore re-check sees the server back online.
    def online_again(port):
        calls.append(port)
        if len(calls) >= 2:
            raise tool.ImportBoundaryError("WRITERS_NOT_OFFLINE")

    monkeypatch.setattr(tool, "_writers_offline", online_again)

    def must_not_restore(backup_path, db_path):
        raise AssertionError("auto-restore must not run while writers are online")

    monkeypatch.setattr(tool, "restore_from_backup", must_not_restore)
    code, report = invoke(capsys, "--run-dir", str(run_dir), "--db", str(db),
                          "--apply", "--backup-dir", str(tmp_path / "backups"),
                          "--host-root", str(host))
    assert code == 2
    assert report["error"]["code"] == "WRITERS_ONLINE_RESTORE_BLOCKED"
    assert report["apply"]["status"] == "FAILED"
    assert report["apply"]["restored"]["restored"] is False
    assert report["apply"]["original_error"] == "PLAN_CHANGED"
    assert calls == [8752, 8752]
    # Restore was skipped: the written rows remain for manual recovery.
    conn = read_only(db)
    try:
        assert conn.execute("SELECT COUNT(*) FROM transactions").fetchone()[0] == 6
    finally:
        conn.close()


def test_apply_restore_failure_stops_without_starting_server(tmp_path, capsys, monkeypatch):
    run_dir = make_run(tmp_path, both_files_spec())
    db = make_db(tmp_path)
    host, _calls = gate_host(tmp_path, monkeypatch)
    real_rehearse = tool.rehearse

    def divergent_rehearse(db_path, files, work_dir, label):
        result = real_rehearse(db_path, files, work_dir, label)
        result["receipts"][0]["inserted"] += 99
        return result

    monkeypatch.setattr(tool, "rehearse", divergent_rehearse)

    def failed_restore(backup_path, db_path):
        return {"backup": str(backup_path), "restored": False, "verified": False,
                "error": "RESTORE_INTEGRITY_FAILED"}

    monkeypatch.setattr(tool, "restore_from_backup", failed_restore)
    code, report = invoke(capsys, "--run-dir", str(run_dir), "--db", str(db),
                          "--apply", "--backup-dir", str(tmp_path / "backups"),
                          "--host-root", str(host))
    assert code == 2
    assert report["error"]["code"] == "RESTORE_FAILED_DO_NOT_START_SERVER"
    assert report["apply"]["status"] == "FAILED"
    assert report["apply"]["restored"]["restored"] is False
    assert report["apply"]["restored"]["verified"] is False
    assert report["apply"]["original_error"] == "PLAN_CHANGED"


def test_apply_releases_write_lock_before_receive(tmp_path, capsys, monkeypatch):
    run_dir = make_run(tmp_path, both_files_spec())
    db = make_db(tmp_path)
    host, _calls = gate_host(tmp_path, monkeypatch)
    states = []
    real_pipeline = tool.Pipeline

    class SpyPipeline(real_pipeline):
        def receive(self, content, filename):
            states.append(self.store.conn.in_transaction)
            return super().receive(content, filename)

    monkeypatch.setattr(tool, "Pipeline", SpyPipeline)
    code, report = invoke(capsys, "--run-dir", str(run_dir), "--db", str(db),
                          "--apply", "--backup-dir", str(tmp_path / "backups"),
                          "--host-root", str(host))
    assert code == 0
    assert report["apply"]["status"] == "DONE"
    assert states
    # The BEGIN IMMEDIATE snapshot lock is rolled back before receive: no
    # receive call runs inside an outer transaction.
    assert all(state is False for state in states)


def test_apply_queues_classification_like_web_upload(tmp_path, capsys, monkeypatch):
    run_dir = make_run(tmp_path, both_files_spec())
    db = make_db(tmp_path)
    host, _calls = gate_host(tmp_path, monkeypatch)
    code, report = invoke(capsys, "--run-dir", str(run_dir), "--db", str(db),
                          "--apply", "--backup-dir", str(tmp_path / "backups"),
                          "--host-root", str(host))
    assert code == 0
    batch_ids = [f["receipt"]["batch_id"] for f in report["files"]]
    assert report["apply"]["queue"]["queued_batches"] == batch_ids
    conn = read_only(db)
    try:
        for batch_id in batch_ids:
            row = conn.execute(
                "SELECT response_json FROM requests WHERE request_id=? AND scope=?",
                ("card-completion:" + batch_id, "card_completion_job")).fetchone()
            assert row is not None
            state = json.loads(row[0])
            assert state["pending"] is True
            expected = {r[0] for r in conn.execute(
                "SELECT transaction_id FROM import_batch_rows WHERE batch_id=?", (batch_id,))}
            assert len(expected) == 3
            assert set(state["ids"]) == expected
    finally:
        conn.close()


def test_overseas_xls_fixture_parses_and_imports(tmp_path, capsys):
    run_dir = make_run(tmp_path, [
        {"source": OVERSEAS_SOURCE, "filename": "kb-overseas-acquired.xls",
         "content": OVERSEAS_XLS.read_bytes()},
    ])
    db = make_db(tmp_path)
    code, report = invoke(capsys, "--run-dir", str(run_dir), "--db", str(db))
    assert code == 0
    assert report["files"][0]["channel"] == "overseas_acquired"
    assert report["files"][0]["count_check"] == "MATCHED"
    assert report["files"][0]["receipt"]["inserted"] == 3
    assert report["rehearsal"]["protection"]["ok"] is True


def test_overseas_xls_and_csv_are_same_transactions(tmp_path, capsys):
    db = make_db(tmp_path)
    seed_receive(db, csv_bytes(OVERSEAS_HEADERS, OVERSEAS_ROWS), "kb-overseas-seed.csv")
    run_dir = make_run(tmp_path, [
        {"source": OVERSEAS_SOURCE, "filename": "kb-overseas-acquired.xls",
         "content": OVERSEAS_XLS.read_bytes()},
    ])
    code, report = invoke(capsys, "--run-dir", str(run_dir), "--db", str(db))
    assert code == 0
    receipt = report["files"][0]["receipt"]
    assert receipt["inserted"] == 0
    assert receipt["already_present"] == 3
    assert receipt["matched_by_content"] == 3
