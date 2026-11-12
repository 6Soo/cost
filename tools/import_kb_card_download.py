# -*- coding: utf-8 -*-
"""Preview or import a saved KB card collection run through the existing receive path.

Consumes the run folder produced by tools/collect_kb_card.mjs (manifest.json +
preserved originals). File validation reuses the production upload preflight
(app.card_preflight.validate_upload) and the existing card parser; duplicate
handling and the import itself are the existing Pipeline.receive path (content
idempotency, identity dedup, keyless multiset matching, conflict protection).
This tool adds no new import logic.

Preview rehearses receive on a scratch copy of the target database and never
writes the target. --apply additionally requires the real single-writer gate
(the WebLedger writer tasks are not Running and the routed Board port has no
listener, same check as tools/complete_card_classification.py) plus a fresh
backup (<1h, source state matched) with a separate verified restore, then
receives through the same path. receive() commits per file, so a failed
post-write check auto-restores the fresh backup instead of one outer
transaction. Imported batches are queued for P1 classification exactly like
the web upload (queue_batch); ledger commits and Google writes are never
performed here. Reports carry aggregates only, never source rows.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sqlite3
import sys
import tempfile
import threading
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app import Pipeline
from app.card_preflight import validate_upload
from app.db import Store, StoreError
from app.import_card import ParseError, parse_card_file

MANIFEST_SCHEMA = "cost.kb-card-collection-manifest.v1"
REPORT_SCHEMA = "cost.kb-card-download-import.v1"
EXPECTED_CHANNELS = {
    "국민 기업카드 국내 매입": "domestic_acquired",
    "국민 기업카드 해외 매입": "overseas_acquired",
}
PROTECTED_TABLES = ("ledger_entries", "review_decisions", "transaction_review_holds")
APPEND_TABLES = ("import_batches", "import_batch_rows", "approval_evidence",
                 "approval_batch_rows", "change_log")
PLAN_KEYS = ("inserted", "already_present", "matched_by_content", "conflicts",
             "unresolved", "row_count")


class ImportBoundaryError(Exception):
    def __init__(self, code: str, message: str = "", detail: dict | None = None):
        super().__init__(message or code)
        self.code = code
        self.message = message or code
        self.detail = detail or {}


def _sha256(data) -> str:
    if isinstance(data, str):
        data = data.encode("utf-8")
    return hashlib.sha256(data).hexdigest()


def _row_hash(row) -> str:
    cells = [{"sha256": _sha256(value), "bytes": len(value)}
             if isinstance(value, bytes) else value for value in row]
    return _sha256(json.dumps(cells, ensure_ascii=False, sort_keys=True,
                              separators=(",", ":")))


def _read_only(path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(Path(path).resolve().as_uri() + "?mode=ro", uri=True,
                           timeout=30, isolation_level=None)
    conn.execute("PRAGMA query_only=ON")
    conn.execute("PRAGMA busy_timeout=30000")
    return conn


def _table_names(conn) -> set:
    return {row[0] for row in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")}


def protection_snapshot(conn) -> dict:
    """Hash-only state of the rows receive must never alter. No raw text leaves."""
    columns = [row[1] for row in conn.execute('PRAGMA table_info("transactions")')]
    id_index = columns.index("transaction_id")
    transactions = {}
    for row in conn.execute("SELECT * FROM transactions"):
        transactions[row[id_index]] = _row_hash(row)
    approval_source = {}
    names = _table_names(conn)
    if "approval_evidence" in names:
        approval_source = {key: source_hash for key, source_hash in conn.execute(
            "SELECT approval_key, source_hash FROM approval_evidence")}
    protected = {}
    for table in PROTECTED_TABLES:
        if table not in names:
            continue
        hashes = sorted(_row_hash(row) for row in conn.execute(f'SELECT * FROM "{table}"'))
        protected[table] = {"count": len(hashes), "digest": _sha256(json.dumps(hashes))}
    append_counts = {table: conn.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0]
                     for table in APPEND_TABLES if table in names}
    return {"transactions": transactions, "approval_source": approval_source,
            "protected": protected, "append_counts": append_counts}


def protection_report(before: dict, after: dict) -> dict:
    b_tx, a_tx = before["transactions"], after["transactions"]
    missing = sum(1 for key in b_tx if key not in a_tx)
    changed = sum(1 for key in b_tx if key in a_tx and b_tx[key] != a_tx[key])
    added = sum(1 for key in a_tx if key not in b_tx)
    b_ap, a_ap = before["approval_source"], after["approval_source"]
    approval_missing = sum(1 for key in b_ap if key not in a_ap)
    approval_changed = sum(1 for key in b_ap if key in a_ap and b_ap[key] != a_ap[key])
    protected_unchanged = before["protected"] == after["protected"]
    ok = (missing == changed == approval_missing == approval_changed == 0
          and protected_unchanged)
    return {"existing_transaction_rows_missing": missing,
            "existing_transaction_rows_changed": changed,
            "new_transaction_rows": added,
            "approval_source_rows_missing": approval_missing,
            "approval_source_rows_changed": approval_changed,
            "protected_tables_unchanged": protected_unchanged,
            "ok": ok}


def load_run(run_dir: Path):
    manifest_path = run_dir / "manifest.json"
    if not manifest_path.is_file():
        raise ImportBoundaryError("MANIFEST_REQUIRED",
                                  "run folder has no manifest.json; import consumes a collect_kb_card.mjs run")
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        raise ImportBoundaryError("MANIFEST_UNREADABLE", "manifest.json is not readable JSON") from None
    if manifest.get("schemaVersion") != MANIFEST_SCHEMA:
        raise ImportBoundaryError("MANIFEST_SCHEMA", "unexpected manifest schemaVersion")
    entries, no_data = [], []
    for row in manifest.get("rows", []):
        source = row.get("source")
        if source not in EXPECTED_CHANNELS:
            raise ImportBoundaryError("UNKNOWN_SOURCE", "manifest row has an unsupported KB source")
        verification = (row.get("verification") or {}).get("status")
        if verification == "no_data":
            no_data.append({"source": source, "query": row.get("query")})
            continue
        if verification != "ok":
            raise ImportBoundaryError("COLLECTION_NOT_VERIFIED",
                                      f"{source}: collection verification is {verification!r}, not ok")
        if (row.get("countCheck") or {}).get("status") != "MATCHED":
            raise ImportBoundaryError("COLLECTION_COUNT_NOT_VERIFIED",
                                      f"{source}: screen/parser count was not MATCHED at collection")
        if (row.get("parserVerification") or {}).get("status") != "PARSER_VERIFICATION_OK":
            raise ImportBoundaryError("COLLECTION_PARSER_NOT_VERIFIED",
                                      f"{source}: parser verification did not succeed at collection")
        if not (row.get("file") or {}).get("savedPath"):
            raise ImportBoundaryError("FILE_MISSING_IN_MANIFEST", f"{source}: no preserved file recorded")
        entries.append({"row": row, "source": source})
    return manifest, entries, no_data


def verify_file(run_dir: Path, entry: dict) -> dict:
    """Independent re-verification of one preserved file. Existing parser/preflight only."""
    row = entry["row"]
    meta = row["file"]
    path = Path(meta["savedPath"]).resolve()
    try:
        path.relative_to(run_dir)
    except ValueError:
        raise ImportBoundaryError("FILE_OUTSIDE_RUN_DIR", "preserved file is outside the run folder") from None
    if not path.is_file():
        raise ImportBoundaryError("FILE_MISSING", "preserved file is missing from the run folder")
    content = path.read_bytes()
    sha = _sha256(content)
    if sha != meta.get("sha256"):
        raise ImportBoundaryError("FILE_HASH_MISMATCH", "preserved file bytes differ from the manifest SHA256")
    if len(content) != meta.get("bytes"):
        raise ImportBoundaryError("FILE_SIZE_MISMATCH", "preserved file size differs from the manifest")
    filename = path.name
    try:
        validate_upload(content, filename)
        parsed = parse_card_file(content, filename, use_cache=False)
    except (StoreError, ParseError) as exc:
        raise ImportBoundaryError("FORMAT_INVALID", f"{filename}: {exc.code}") from None
    expected = EXPECTED_CHANNELS[entry["source"]]
    if parsed.channel != expected:
        raise ImportBoundaryError("CHANNEL_MISMATCH",
                                  f"{filename}: parsed channel {parsed.channel!r}, expected {expected!r}")
    if parsed.issues or any(r.parse_error for r in parsed.rows):
        raise ImportBoundaryError("PARSE_ISSUES", f"{filename}: {len(parsed.issues)} parse issues")
    screen_count = (row.get("summary") or {}).get("pageTotalCount")
    if not isinstance(screen_count, int) or screen_count != len(parsed.rows):
        raise ImportBoundaryError("COUNT_MISMATCH",
                                  f"{filename}: parser rows {len(parsed.rows)} != screen count {screen_count!r}")
    return {"content": content, "filename": filename,
            "report": {"filename": filename, "source": entry["source"], "sha256": sha,
                       "bytes": len(content), "channel": parsed.channel,
                       "rows": len(parsed.rows), "parse_issues": 0,
                       "screen_count": screen_count, "count_check": "MATCHED"}}


def receipt_summary(result: dict) -> dict:
    return {"batch_id": result.get("batch_id"), "reused": bool(result.get("reused")),
            "channel": result.get("channel"),
            **{key: result.get(key, 0) for key in PLAN_KEYS}}


def backup_database(source_path: Path, target_path: Path) -> None:
    if target_path.exists():
        raise ImportBoundaryError("BACKUP_EXISTS", "refusing to overwrite an existing backup")
    target_path.parent.mkdir(parents=True, exist_ok=True)
    source = _read_only(source_path)
    dest = sqlite3.connect(str(target_path), timeout=30, isolation_level=None)
    try:
        source.backup(dest)
        # Self-contained offline copy: a WAL backup otherwise recreates -wal/-shm
        # files during read-only verification. Never change the source.
        if dest.execute("PRAGMA journal_mode=DELETE").fetchone()[0] != "delete":
            raise ImportBoundaryError("BACKUP_JOURNAL_MODE_FAILED")
        if dest.execute("PRAGMA quick_check").fetchone()[0] != "ok":
            raise ImportBoundaryError("BACKUP_INTEGRITY_FAILED")
    finally:
        dest.close()
        source.close()


def _table_counts(conn) -> dict:
    return {table: conn.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0]
            for table in sorted(_table_names(conn))}


def _transactions_digest(conn) -> str:
    hashes = sorted(_row_hash(row) for row in conn.execute("SELECT * FROM transactions"))
    return _sha256(json.dumps(hashes, separators=(",", ":")))


def verify_restore(source_path: Path, backup_path: Path, work_dir: Path) -> dict:
    """Restore the fresh backup into a separate file and compare against the source."""
    restore = work_dir / "restore-verification.sqlite"
    if restore.exists():
        raise ImportBoundaryError("SCRATCH_EXISTS", "restore verification scratch already exists")
    shutil.copyfile(backup_path, restore)
    source = _read_only(source_path)
    restored = _read_only(restore)
    try:
        if restored.execute("PRAGMA quick_check").fetchone()[0] != "ok":
            raise ImportBoundaryError("RESTORE_INTEGRITY_FAILED")
        source_counts, restore_counts = _table_counts(source), _table_counts(restored)
        if source_counts != restore_counts:
            raise ImportBoundaryError("RESTORE_COUNTS_DIFFER", "restored table counts differ from the source")
        if _transactions_digest(source) != _transactions_digest(restored):
            raise ImportBoundaryError("RESTORE_CONTENT_DIFFERS", "restored transactions differ from the source")
        return {"quick_check": "ok", "table_counts_match": True,
                "transactions_digest_match": True, "tables": len(source_counts)}
    finally:
        restored.close()
        source.close()


def rehearse(db_path: Path, files: list, work_dir: Path, label: str) -> dict:
    """Receive on a scratch copy of the target; the target stays read-only."""
    ro = _read_only(db_path)
    try:
        if ro.execute("PRAGMA quick_check").fetchone()[0] != "ok":
            raise ImportBoundaryError("SOURCE_INTEGRITY_FAILED")
        before = protection_snapshot(ro)
    finally:
        ro.close()
    Store.require_existing_schema(db_path)
    clone = work_dir / f"{label}.sqlite"
    if clone.exists():
        raise ImportBoundaryError("SCRATCH_EXISTS", "rehearsal scratch already exists")
    backup_database(db_path, clone)
    conn = sqlite3.connect(str(clone), timeout=30, isolation_level=None)
    conn.execute("PRAGMA busy_timeout=30000")
    try:
        if conn.execute("PRAGMA quick_check").fetchone()[0] != "ok":
            raise ImportBoundaryError("CLONE_INTEGRITY_FAILED")
        if conn.execute("SELECT COUNT(*) FROM transactions").fetchone()[0] != len(before["transactions"]):
            raise ImportBoundaryError("CLONE_COUNTS_DIFFER")
        pipe = Pipeline(Store(conn, schema_policy="require"))
        receipts = [receipt_summary(pipe.receive(f["content"], f["filename"])) for f in files]
        protection = protection_report(before, protection_snapshot(conn))
        repeat_before = protection_snapshot(conn)
        repeats = [pipe.receive(f["content"], f["filename"]) for f in files]
        idempotent = (all(r.get("reused") for r in repeats)
                      and repeat_before == protection_snapshot(conn))
        return {"before": before, "receipts": receipts, "protection": protection,
                "reupload_idempotent": idempotent,
                "safe": protection["ok"] and idempotent}
    finally:
        conn.close()


def kb_last_dates(conn) -> dict:
    """Read-only aggregate for the next collection's --last-use-date (no raw rows)."""
    result = {}
    for label, condition in (("domestic", "card_kind='국내'"),
                             ("overseas", "card_kind='해외'"), ("all", "1=1")):
        use, posting = conn.execute(
            f"SELECT MAX(approval_date), MAX(posting_date) FROM transactions"
            f" WHERE issuer='국민' AND {condition}").fetchone()
        result[label] = {"last_use_date": use or None, "last_posting_date": posting or None}
    return result


def run_preview(db_path: Path, files: list, work_dir: Path) -> dict:
    ro = _read_only(db_path)
    try:
        version_before = ro.execute("PRAGMA data_version").fetchone()[0]
        last_dates = kb_last_dates(ro)
    finally:
        ro.close()
    rehearsal = rehearse(db_path, files, work_dir, "preview")
    ro = _read_only(db_path)
    try:
        version_after = ro.execute("PRAGMA data_version").fetchone()[0]
    finally:
        ro.close()
    rehearsal["source_data_version_unchanged"] = version_before == version_after
    rehearsal["safe"] = rehearsal["safe"] and version_before == version_after
    rehearsal["kb_last_dates"] = last_dates
    return rehearsal


def _writers_offline(port: int) -> None:
    """Seam over the shared gate; synthetic tests patch this, never real tasks."""
    from tools.complete_card_classification import require_writers_offline
    try:
        require_writers_offline(port)
    except ValueError:
        raise ImportBoundaryError("WRITERS_NOT_OFFLINE",
                                  "WebLedger writer tasks are running or the Board port has a listener") from None


def require_writers_offline_gate(host_root: Path) -> int:
    """Route-file port + the same writers-offline check as require_offline_backup."""
    route_path = host_root / "config" / "ledger-route.json"
    try:
        route = json.loads(route_path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        raise ImportBoundaryError("ROUTE_REQUIRED",
                                  "config/ledger-route.json is missing or unreadable under --host-root") from None
    port = route.get("port")
    if not isinstance(port, int) or isinstance(port, bool) or port not in (8751, 8752):
        raise ImportBoundaryError("ROUTE_PORT_INVALID", "ledger-route.json port must be 8751 or 8752")
    _writers_offline(port)
    return port


def require_fresh_backup(db_path: Path, backup_path: Path, recorded_at: datetime) -> dict:
    """Freshness + source-state evidence, same rules as require_offline_backup."""
    age = (datetime.now(timezone.utc) - recorded_at).total_seconds()
    if not 0 <= age < 3600:
        raise ImportBoundaryError("BACKUP_NOT_FRESH", "backup evidence is older than one hour")
    from tools.verify_operational_backup_restore import database_state
    if database_state(backup_path) != database_state(db_path):
        raise ImportBoundaryError("BACKUP_SOURCE_CHANGED", "target changed after the fresh backup was taken")
    return {"recorded_at": recorded_at.isoformat(), "age_seconds": round(age, 3),
            "fresh": True, "source_state_matched": True}


def restore_from_backup(backup_path: Path, db_path: Path) -> dict:
    """Auto-restore the fresh backup after a failed post-write check.

    receive() commits per file, so the backup is the rollback point instead of
    one outer transaction. Verification failure is reported, not raised: the
    original failure code survives and the playbook's manual copy is the
    fallback. The caller must close every target connection first.
    """
    evidence = {"backup": str(backup_path), "restored": False, "verified": False}
    try:
        source = _read_only(backup_path)
        dest = sqlite3.connect(str(db_path), timeout=30, isolation_level=None)
        try:
            source.backup(dest)
            integrity_ok = dest.execute("PRAGMA quick_check").fetchone()[0] == "ok"
        finally:
            dest.close()
            source.close()
        if not integrity_ok:
            evidence["error"] = "RESTORE_INTEGRITY_FAILED"
            return evidence
        evidence["restored"] = True
        from tools.verify_operational_backup_restore import database_state
        evidence["verified"] = database_state(backup_path) == database_state(db_path)
        if not evidence["verified"]:
            evidence["error"] = "RESTORE_STATE_MISMATCH"
    except (OSError, sqlite3.Error) as exc:
        evidence["error"] = type(exc).__name__
    return evidence


def queue_imported_batches(conn, batch_ids: list) -> dict:
    """Same follow-up as the web upload: queue_batch into the durable queue.

    The queue lives in the requests table, so it works while the server is
    stopped; the Board's CardCompletionWorker resumes it at the next start.
    """
    from webapp.card_completion_worker import queue_batch
    board = SimpleNamespace(conn=conn, _lock=threading.RLock())
    queued = []
    for batch_id in batch_ids:
        if not batch_id:
            continue
        queue_batch(board, batch_id)
        queued.append(batch_id)
    return {"queued_batches": queued, "count": len(queued),
            "scope": "card_completion_job", "resume": "SERVER_RESTART"}


def run_apply(db_path: Path, files: list, backup_dir: Path, work_dir: Path,
              host_root: Path) -> dict:
    port = require_writers_offline_gate(host_root)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    backup_path = backup_dir / f"board-kb-import-{stamp}.sqlite"
    recorded_at = datetime.now(timezone.utc)
    backup_database(db_path, backup_path)
    restore = verify_restore(db_path, backup_path, work_dir)
    backup_evidence = require_fresh_backup(db_path, backup_path, recorded_at)
    rehearsal = rehearse(backup_path, files, work_dir, "apply-rehearsal")
    if not rehearsal["safe"]:
        raise ImportBoundaryError("REHEARSAL_HOLD", "rehearsal on the fresh backup was not safe; nothing written")
    store = Store.open(str(db_path), schema_policy="require")
    wrote = False
    try:
        conn = store.conn
        # Write lock across the freshness compare: no writer can slip between
        # the snapshot and receive. receive manages its own transactions.
        conn.execute("BEGIN IMMEDIATE")
        try:
            current = protection_snapshot(conn)
        finally:
            conn.execute("ROLLBACK")
        if current != rehearsal["before"]:
            raise ImportBoundaryError("PLAN_CHANGED",
                                      "target changed since the fresh backup; single-writer boundary violated")
        pipe = Pipeline(store)
        wrote = True
        receipts = [receipt_summary(pipe.receive(f["content"], f["filename"])) for f in files]
        for actual, expected in zip(receipts, rehearsal["receipts"]):
            if {key: actual[key] for key in PLAN_KEYS} != {key: expected[key] for key in PLAN_KEYS}:
                raise ImportBoundaryError("PLAN_CHANGED", "receive result differs from the rehearsal plan")
        protection = protection_report(current, protection_snapshot(conn))
        if not protection["ok"]:
            raise ImportBoundaryError("PROTECTION_FAILED", "post-write protection check failed")
        repeat_before = protection_snapshot(conn)
        repeats = [pipe.receive(f["content"], f["filename"]) for f in files]
        idempotent = (all(r.get("reused") for r in repeats)
                      and repeat_before == protection_snapshot(conn))
        if not idempotent:
            raise ImportBoundaryError("PROTECTION_FAILED", "re-receive was not a no-op")
        queue = queue_imported_batches(conn, [r["batch_id"] for r in receipts])
        last_dates = kb_last_dates(conn)
        return {"ok": True, "backup": str(backup_path), "restore": restore,
                "gate": {"writers_offline": True, "route_port": port},
                "backup_evidence": backup_evidence,
                "rehearsal": {key: value for key, value in rehearsal.items() if key != "before"},
                "receipts": receipts, "protection": protection,
                "reupload_idempotent": idempotent, "queue": queue,
                "kb_last_dates": last_dates}
    except BaseException as exc:
        if not wrote:
            raise
        store.close()
        restored = restore_from_backup(backup_path, db_path)
        detail = {"restored": restored, "backup": str(backup_path)}
        if isinstance(exc, ImportBoundaryError):
            exc.detail = detail
            raise
        code = exc.code if isinstance(exc, StoreError) else "APPLY_FAILED_RESTORED"
        raise ImportBoundaryError(code, str(exc) or type(exc).__name__, detail=detail) from None
    finally:
        store.close()


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", required=True, help="collect_kb_card.mjs run folder (manifest.json + originals)")
    parser.add_argument("--db", required=True, help="target board.sqlite; preview opens it read-only")
    parser.add_argument("--apply", action="store_true", help="write through the existing receive path")
    parser.add_argument("--backup-dir", help="protected folder for the fresh backup (required with --apply)")
    parser.add_argument("--host-root", type=Path, default=Path("D:/WebLedgerHost"),
                        help="host root whose config/ledger-route.json selects the Board port for the writers-offline gate")
    parser.add_argument("--work-dir", help="protected scratch folder; default is a temporary folder removed at exit")
    parser.add_argument("--output", help="also write the JSON report to this path")
    args = parser.parse_args(argv)

    report = {"schema": REPORT_SCHEMA, "mode": "apply" if args.apply else "preview",
              "generated_at": datetime.now(timezone.utc).isoformat(),
              "run_dir": str(Path(args.run_dir).resolve()),
              "db": str(Path(args.db).resolve()),
              "boundaries": {"classification": "NOT_RUN", "ledger_commit": "NOT_RUN",
                             "google": "NOT_RUN", "login_automation": "NONE"}}
    scratch = None
    try:
        if args.apply and not args.backup_dir:
            raise ImportBoundaryError("BACKUP_DIR_REQUIRED", "--apply requires --backup-dir")
        db_path = Path(args.db).resolve()
        if not db_path.is_file():
            raise ImportBoundaryError("DB_NOT_FOUND", "target database file does not exist")
        run_dir = Path(args.run_dir).resolve()
        _manifest, entries, no_data = load_run(run_dir)
        report["no_data_sources"] = no_data
        files = [verify_file(run_dir, entry) for entry in entries]
        report["files"] = [f["report"] for f in files]
        if args.work_dir:
            work_dir = Path(args.work_dir).resolve()
            work_dir.mkdir(parents=True, exist_ok=True)
        else:
            scratch = tempfile.mkdtemp(prefix="cost-kb-import-")
            work_dir = Path(scratch)
        if not files:
            if args.apply:
                raise ImportBoundaryError("NOTHING_TO_IMPORT", "run folder has no verified files to import")
            report["status"] = "safe"
            report["rehearsal"] = {"status": "NOT_RUN", "reason": "no files to import"}
            report["apply"] = {"status": "NOT_RUN"}
        elif args.apply:
            outcome = run_apply(db_path, files, Path(args.backup_dir).resolve(), work_dir,
                                args.host_root.resolve())
            for file_report, receipt in zip(report["files"], outcome["receipts"]):
                file_report["receipt"] = receipt
            report["rehearsal"] = outcome["rehearsal"]
            report["apply"] = {"status": "DONE" if outcome["ok"] else "FAILED",
                               "backup": outcome["backup"], "restore": outcome["restore"],
                               "gate": outcome["gate"], "backup_evidence": outcome["backup_evidence"],
                               "protection": outcome["protection"],
                               "reupload_idempotent": outcome["reupload_idempotent"],
                               "queue": outcome["queue"], "kb_last_dates": outcome["kb_last_dates"]}
            report["boundaries"]["classification"] = "QUEUED"
            report["status"] = "safe" if outcome["ok"] else "hold"
        else:
            rehearsal = run_preview(db_path, files, work_dir)
            for file_report, receipt in zip(report["files"], rehearsal["receipts"]):
                file_report["receipt"] = receipt
            report["rehearsal"] = {key: value for key, value in rehearsal.items() if key != "before"}
            report["apply"] = {"status": "NOT_RUN"}
            report["status"] = "safe" if rehearsal["safe"] else "hold"
    except ImportBoundaryError as exc:
        report["status"] = "error"
        report["error"] = {"code": exc.code, "message": exc.message}
        if args.apply:
            report["apply"] = {"status": "FAILED", **exc.detail}
    except StoreError as exc:
        report["status"] = "error"
        report["error"] = {"code": exc.code, "message": exc.message}
    except Exception as exc:
        report["status"] = "error"
        report["error"] = {"code": "INTERNAL_ERROR", "error_type": type(exc).__name__}
    finally:
        if scratch is not None:
            shutil.rmtree(scratch, ignore_errors=True)

    body = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        output = Path(args.output).resolve()
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(body, encoding="utf-8")
    sys.stdout.write(body)
    return 0 if report["status"] == "safe" else 2


if __name__ == "__main__":
    raise SystemExit(main())
