# -*- coding: utf-8 -*-
"""Reconcile the three KB card channels against a verified SQLite snapshot.

This is a one-off operator audit. It never opens the source databases for writes,
never sends source rows anywhere, and never records a ledger entry. Only aggregate
counts, hashes, and safety results are written to the JSON report.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sqlite3
import sys
import tempfile
import threading
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app import Pipeline, parse_card_file
from app.import_card import ParseError
from app.review import content_key, source_hash_of, transaction_identity, _plain_number
from app import source_links
from webapp.card_flow import CardFlow


EXPECTED = {
    "approval": 2124,
    "domestic_acquired": 1016,
    "overseas_acquired": 764,
}
CHANNEL_FILES = {
    "approval": "kb-approval-20260401-20261004.xls",
    "domestic_acquired": "kb-domestic-acquired-20260401-20261004.xls",
    "overseas_acquired": "kb-overseas-acquired-20260401-20261004.xls",
}
ALLOWED_CHANGED_TABLES = {
    "transactions", "import_batches", "import_batch_rows", "change_log",
    "approval_evidence", "approval_batch_rows", "sqlite_sequence",
}
PROTECTED_TABLES = {
    "ledger_entries", "review_decisions", "transaction_review_holds",
}


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _json_cell(value):
    if isinstance(value, bytes):
        return {"blob_sha256": _sha(value), "byte_length": len(value)}
    return value


def _row_hash(row) -> str:
    encoded = json.dumps([_json_cell(value) for value in row], ensure_ascii=False,
                         sort_keys=True, separators=(",", ":")).encode("utf-8")
    return _sha(encoded)


def _tables(conn) -> list[str]:
    return [row[0] for row in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name")]


def _snapshot_table(conn, table: str) -> dict:
    info = conn.execute(f'PRAGMA table_info("{table}")').fetchall()
    columns = [row[1] for row in info]
    pk = [row[1] for row in sorted((row for row in info if row[5]), key=lambda row: row[5])]
    rows = conn.execute(f'SELECT * FROM "{table}"').fetchall()
    if pk:
        positions = [columns.index(name) for name in pk]
        keyed = {}
        for row in rows:
            key = json.dumps([_json_cell(row[index]) for index in positions],
                             ensure_ascii=False, separators=(",", ":"))
            keyed[key] = _row_hash(row)
        ordered = sorted((key, digest) for key, digest in keyed.items())
        digest = _sha(json.dumps(ordered, ensure_ascii=False, separators=(",", ":")).encode())
        return {"count": len(rows), "digest": digest, "pk": pk, "keyed": keyed}
    hashes = sorted(_row_hash(row) for row in rows)
    digest = _sha(json.dumps(hashes, separators=(",", ":")).encode())
    return {"count": len(rows), "digest": digest, "pk": [], "hashes": hashes}


def _snapshot_db(conn) -> dict:
    return {table: _snapshot_table(conn, table) for table in _tables(conn)}


def _table_diff(before: dict | None, after: dict | None) -> dict:
    if before is None:
        return {"before": 0, "after": after["count"], "added": after["count"],
                "removed": 0, "changed": 0, "same": False}
    if after is None:
        return {"before": before["count"], "after": 0, "added": 0,
                "removed": before["count"], "changed": 0, "same": False}
    if before["pk"] and before["pk"] == after["pk"]:
        left, right = before["keyed"], after["keyed"]
        removed = len(left.keys() - right.keys())
        added = len(right.keys() - left.keys())
        changed = sum(left[key] != right[key] for key in left.keys() & right.keys())
        same = removed == added == changed == 0
    else:
        left, right = Counter(before.get("hashes", [])), Counter(after.get("hashes", []))
        removed = sum((left - right).values())
        added = sum((right - left).values())
        changed = 0
        same = removed == added == 0
    return {"before": before["count"], "after": after["count"],
            "added": added, "removed": removed, "changed": changed, "same": same}


def _copy_database(source_conn, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    dest = sqlite3.connect(str(destination), timeout=30, isolation_level=None)
    try:
        source_conn.backup(dest, pages=256, sleep=0.05)
        result = dest.execute("PRAGMA quick_check").fetchone()[0]
        if result != "ok":
            raise RuntimeError(f"snapshot quick_check failed: {result}")
    finally:
        dest.close()


def _read_only(path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(path.as_uri() + "?mode=ro", uri=True,
                           timeout=30, isolation_level=None)
    conn.execute("PRAGMA query_only=ON")
    conn.execute("PRAGMA busy_timeout=30000")
    return conn


def _db_row_key(row: tuple) -> tuple:
    return (row[0] or "", row[1] or "", row[2] or "", row[3] or "",
            row[4] or "", row[5] or "", row[6] or "",
            "" if row[7] is None else str(row[7]), row[8] or "",
            _plain_number(row[9]))


def _kind_category(row) -> str:
    if row.transaction_direction == "cancellation" or any(
            marker in str(row.transaction_kind or "").casefold()
            for marker in ("취소", "cancel", "refund")):
        return "cancel"
    label = (str(row.transaction_kind or "") + " " + str(row.description_raw or "")).casefold()
    if any(marker in label for marker in (
            "현금서비스", "단기카드대출", "장기카드대출", "리버설", "cash service", "cash advance")):
        return "special"
    if row.parse_error:
        return "parse_issue"
    return "purchase_or_other"


def _legacy_warning_rows(conn, rows, batch_id: str) -> int:
    count = 0
    for row in rows:
        if row.approval_number:
            continue
        found = conn.execute(
            "SELECT 1 FROM transactions WHERE batch_id<>? AND issuer=? AND card_tail=? AND approval_date=?"
            " AND merchant_normalized=? LIMIT 1",
            (batch_id, row.issuer, row.card_tail, row.approval_date, row.merchant_normalized)).fetchone()
        count += bool(found)
    return count


def _warning_candidates(conn, rows, batch_id: str) -> int:
    count = 0
    for row in rows:
        if row.approval_number or row.amount_krw is None:
            continue
        found = conn.execute(
            "SELECT 1 FROM transactions WHERE batch_id<>? AND issuer=? AND card_tail=? AND transaction_direction=?"
            " AND posting_date=? AND approval_date=? AND amount_krw=? AND foreign_currency=?"
            " AND merchant_normalized<>? AND approval_number='' LIMIT 1",
            (batch_id, row.issuer, row.card_tail, row.transaction_direction, row.posting_date,
             row.approval_date, row.amount_krw, row.foreign_currency, row.merchant_normalized)).fetchone()
        count += bool(found)
    return count


def _input_report(path: Path, channel: str, data: bytes, parsed, baseline_conn) -> dict:
    batch_id = "batch-" + _sha(data)[:24]
    counts = Counter(_kind_category(row) for row in parsed.rows)
    kind_counts = Counter(str(row.transaction_kind or "(blank)") for row in parsed.rows)
    duplicate_groups = Counter(content_key(row) for row in parsed.rows
                               if not row.approval_number and not row.original_approval_number)
    multi_groups = sum(count > 1 for count in duplicate_groups.values())
    existing = 0
    new_candidate = 0
    identity_conflicts = 0
    category_existing = {}
    category_new = {}
    if channel == "approval":
        existing = 0
        new_candidate = 0
    elif channel == "overseas_acquired":
        existing_groups = Counter()
        for item in baseline_conn.execute(
                "SELECT issuer, card_tail, transaction_direction, transaction_kind, posting_date,"
                " approval_date, merchant_normalized, amount_krw, foreign_currency, foreign_amount"
                " FROM transactions WHERE approval_number='' AND original_approval_number=''"
                " AND parse_error='' AND transaction_id NOT LIKE '%:conflict:%'"):
            key = _db_row_key(item)
            existing_groups[key] += 1
        source_groups = Counter(content_key(row) for row in parsed.rows
                                if not row.approval_number and not row.original_approval_number
                                and not row.parse_error and row.amount_krw is not None)
        existing = sum(min(count, existing_groups[key]) for key, count in source_groups.items())
        new_candidate = sum(max(0, count - existing_groups[key]) for key, count in source_groups.items())
        source_by_category = Counter(_kind_category(row) for row in parsed.rows
                                     if not row.parse_error and row.amount_krw is not None)
        for category, count in source_by_category.items():
            # Content keys include direction and transaction kind, so each category is
            # compared against its own source rows rather than a combined total.
            matching = 0
            for key, source_count in source_groups.items():
                representative = next((row for row in parsed.rows if content_key(row) == key), None)
                if representative is not None and _kind_category(representative) == category:
                    matching += min(source_count, existing_groups[key])
            category_existing[category] = matching
            category_new[category] = count - matching
        for row in parsed.rows:
            if row.approval_number or row.original_approval_number:
                continue
            if row.parse_error:
                continue
            if _warning_candidates(baseline_conn, [row], batch_id):
                identity_conflicts += 1
    else:
        known = {r[0]: r[1] for r in baseline_conn.execute(
            "SELECT transaction_id, source_hash FROM transactions")}
        occurrences = Counter()
        for row in parsed.rows:
            transaction_id = transaction_identity(row)
            if not row.approval_number and not row.original_approval_number:
                key = content_key(row)
                occurrence = occurrences[key]
                occurrences[key] += 1
                transaction_id = transaction_identity(row, occurrence)
            if transaction_id in known:
                if known[transaction_id] == source_hash_of(row):
                    existing += 1
                    category_existing[_kind_category(row)] = category_existing.get(_kind_category(row), 0) + 1
                else:
                    identity_conflicts += 1
            else:
                new_candidate += 1
                category_new[_kind_category(row)] = category_new.get(_kind_category(row), 0) + 1
    return {
        "file": path.name,
        "sha256": _sha(data),
        "byte_length": len(data),
        "channel": parsed.channel,
        "expected_channel": channel,
        "expected_rows": EXPECTED[channel],
        "rows": len(parsed.rows),
        "expected_row_count_match": len(parsed.rows) == EXPECTED[channel],
        "parse_issue_count": len(parsed.issues),
        "parse_issue_kinds": dict(Counter(issue.get("error", "unknown") for issue in parsed.issues)),
        "row_kind_counts": dict(counts),
        "transaction_kind_counts": dict(sorted(kind_counts.items())),
        "existing_rows_by_current_identity_or_multiset": existing,
        "new_row_candidates_by_current_identity_or_multiset": new_candidate,
        "existing_rows_by_kind": dict(sorted(category_existing.items())),
        "new_rows_by_kind": dict(sorted(category_new.items())),
        "identity_or_near_match_rows": identity_conflicts,
        "keyless_multirow_groups": multi_groups,
        "legacy_warning_rows_on_same_initial_db": (
            _legacy_warning_rows(baseline_conn, parsed.rows, batch_id)
            if channel == "overseas_acquired" else None),
        "current_near_match_warning_candidates_on_same_initial_db": (
            _warning_candidates(baseline_conn, parsed.rows, batch_id)
            if channel == "overseas_acquired" else None),
    }


def _semantic_snapshot(conn) -> dict:
    ignored = {
        "transactions": {"created_at"},
        "import_batches": {"received_at", "parsed_at"},
        "approval_evidence": {"created_at"},
        "change_log": {"at", "entry_id"},
    }
    result = {}
    for table in _tables(conn):
        if table in {"change_log", "sqlite_sequence"}:
            continue
        columns = [row[1] for row in conn.execute(f'PRAGMA table_info("{table}")')]
        excluded = ignored.get(table, set())
        keep = [index for index, col in enumerate(columns) if col not in excluded]
        rows = conn.execute(f'SELECT * FROM "{table}"').fetchall()
        row_hashes = sorted(_row_hash(tuple(row[i] for i in keep)) for row in rows)
        result[table] = {"count": len(rows), "digest": _sha(json.dumps(row_hashes).encode())}
    return result


def _protection_report(before: dict, after: dict) -> dict:
    diffs = {table: _table_diff(before.get(table), after.get(table))
             for table in sorted(set(before) | set(after))}
    transactions = diffs.get("transactions", {})
    unexpected = {name: diff for name, diff in diffs.items()
                  if name not in ALLOWED_CHANGED_TABLES and not diff["same"]}
    return {
        "table_changes": {name: diff for name, diff in diffs.items() if not diff["same"]},
        "unexpected_table_changes": unexpected,
        "existing_transaction_ids_before": before.get("transactions", {}).get("count", 0),
        "existing_transaction_ids_missing": transactions.get("removed", 0),
        "existing_transaction_rows_changed": transactions.get("changed", 0),
        "new_transaction_rows": transactions.get("added", 0),
        "ledger_entries_unchanged": diffs.get("ledger_entries", {}).get("same", False),
        "user_decisions_unchanged": diffs.get("review_decisions", {}).get("same", False),
        "refund_holds_unchanged": diffs.get("transaction_review_holds", {}).get("same", False),
    }


def _receive_order(database: Path, inputs: dict, order: list[str]) -> dict:
    conn = sqlite3.connect(str(database), timeout=30, isolation_level=None)
    conn.execute("PRAGMA busy_timeout=30000")
    board = SimpleNamespace(conn=conn, _lock=threading.RLock())
    flow = CardFlow(board)
    receipts = {}
    try:
        for channel in order:
            path, data, _parsed = inputs[channel]
            result = flow.pipeline.receive(data, path.name)
            receipts[channel] = {
                "batch_id": result.get("batch_id"),
                "reused": bool(result.get("reused")),
                "channel": result.get("channel"),
                "row_count": result.get("row_count"),
                "inserted": result.get("inserted"),
                "already_present": result.get("already_present"),
                "matched_by_content": result.get("matched_by_content"),
                "approval_stored": result.get("approval_stored"),
                "conflicts": result.get("conflicts"),
                "unresolved": result.get("unresolved"),
                "issue_count": len(result.get("issues", [])),
            }
        final_links = source_links.reconcile(flow.pipeline.store)
        final_audit = source_links.audit(conn)
        before_repeat = _semantic_snapshot(conn)
        repeat = {}
        for channel in order:
            path, data, _parsed = inputs[channel]
            result = flow.pipeline.receive(data, path.name)
            repeat[channel] = bool(result.get("reused"))
        after_repeat = _semantic_snapshot(conn)
        return {
            "receipts": receipts,
            "final_link_summary": final_links,
            "approval_audit": final_audit,
            "reupload_reused_all": all(repeat.values()),
            "reupload_states": repeat,
            "reupload_semantics_unchanged": before_repeat == after_repeat,
            "semantic_snapshot": after_repeat,
        }
    finally:
        conn.close()


def _link_validation(conn) -> dict:
    if not conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='approval_evidence'").fetchone():
        return {"approval_evidence_table_exists": False, "linked_rows": 0,
                "invalid_links": None, "multiple_approvals_per_transaction": None}
    linked = conn.execute(
        "SELECT approval_key, card_tail, card_kind, approval_date, foreign_amount,"
        " linked_transaction_id FROM approval_evidence WHERE linked_transaction_id IS NOT NULL").fetchall()
    invalid = 0
    missing = 0
    for key, card, kind, approved, foreign, txid in linked:
        tx = conn.execute(
            "SELECT card_tail, approval_number, approval_date, raw_row_json"
            " FROM transactions WHERE transaction_id=?", (txid,)).fetchone()
        if tx is None:
            missing += 1
            continue
        if tx[0] != card:
            invalid += 1
        if kind == "국내":
            approval_number = conn.execute(
                "SELECT approval_number FROM approval_evidence WHERE approval_key=?", (key,)).fetchone()[0]
            if tx[1] != approval_number or tx[2] != approved:
                invalid += 1
        else:
            acquired_usd = source_links._overseas_usd(tx[3])
            if tx[2] != approved or acquired_usd != source_links._usd(foreign):
                invalid += 1
    many_to_one = conn.execute(
        "SELECT COUNT(*) FROM (SELECT linked_transaction_id FROM approval_evidence"
        " WHERE linked_transaction_id IS NOT NULL GROUP BY linked_transaction_id HAVING COUNT(*)>1)"
    ).fetchone()[0]
    approval_transaction_rows = conn.execute(
        "SELECT COUNT(*) FROM transactions WHERE batch_id IN"
        " (SELECT batch_id FROM import_batches WHERE parser LIKE '%:approval')").fetchone()[0]
    return {
        "approval_evidence_table_exists": True,
        "approval_source_rows": conn.execute(
            "SELECT COUNT(*) FROM approval_batch_rows").fetchone()[0],
        "distinct_approval_evidence": conn.execute(
            "SELECT COUNT(*) FROM approval_evidence").fetchone()[0],
        "linked_rows": len(linked),
        "links_to_missing_transactions": missing,
        "invalid_card_date_or_amount_links": invalid,
        "multiple_approvals_per_transaction_groups": many_to_one,
        "approval_rows_created_as_transactions": approval_transaction_rows,
        "approval_rows_created_as_ledger_entries": conn.execute(
            "SELECT COUNT(*) FROM ledger_entries WHERE transaction_id IN"
            " (SELECT transaction_id FROM transactions WHERE batch_id IN"
            " (SELECT batch_id FROM import_batches WHERE parser LIKE '%:approval'))").fetchone()[0],
        "states": source_links.audit(conn).get("states", {}),
    }


def _open_and_snapshot(path: Path) -> tuple[sqlite3.Connection, dict, dict]:
    conn = _read_only(path)
    integrity = conn.execute("PRAGMA quick_check").fetchone()[0]
    if integrity != "ok":
        conn.close()
        raise RuntimeError(f"source database quick_check failed: {integrity}")
    return conn, _snapshot_db(conn), {
        "absolute_path": str(path.resolve()),
        "size_bytes": path.stat().st_size,
        "modified_utc": datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).isoformat(),
        "journal_mode": conn.execute("PRAGMA journal_mode").fetchone()[0],
        "quick_check": integrity,
        "data_version": conn.execute("PRAGMA data_version").fetchone()[0],
    }


def run(args) -> dict:
    source = Path(args.source_db).resolve(strict=True)
    ota_source = Path(args.ota_review_db).resolve(strict=True)
    input_dir = Path(args.input_dir).resolve(strict=True)
    output = Path(args.output).resolve()
    inputs = {}
    source_conn = ota_conn = None
    scratch = None
    try:
        source_conn, baseline, source_info = _open_and_snapshot(source)
        ota_conn, ota_before, ota_info = _open_and_snapshot(ota_source)
        required = {"transactions", "import_batches", "import_batch_rows", "ledger_entries",
                    "review_decisions", "transaction_review_holds"}
        missing = required - set(baseline)
        if missing:
            raise RuntimeError("source database missing required tables: " + ",".join(sorted(missing)))
        initial_ids = baseline["transactions"]["count"]
        initial_ledger = source_conn.execute(
            "SELECT COUNT(*), COALESCE(SUM(amount_krw),0) FROM ledger_entries").fetchone()
        source_info["baseline_counts"] = {
            "transactions": initial_ids,
            "ledger_entries": initial_ledger[0],
            "ledger_amount_krw": initial_ledger[1],
            "review_decisions": baseline["review_decisions"]["count"],
            "transaction_review_holds": baseline["transaction_review_holds"]["count"],
            "import_batches": baseline["import_batches"]["count"],
        }
        ota_info["protected_tables"] = {
            name: state["count"] for name, state in ota_before.items()
            if name.startswith("ota_review_")}

        parsed_report = {}
        for channel, filename in CHANNEL_FILES.items():
            path = input_dir / filename
            if not path.is_file():
                raise FileNotFoundError(f"KB input missing: {path}")
            data = path.read_bytes()
            parsed = parse_card_file(data, filename, use_cache=True)
            if parsed.channel != channel:
                raise RuntimeError(f"unexpected channel for {filename}: {parsed.channel}")
            inputs[channel] = (path, data, parsed)
            parsed_report[channel] = _input_report(path, channel, data, parsed, source_conn)

        temp_parent = Path(tempfile.gettempdir()).resolve()
        scratch = Path(tempfile.mkdtemp(prefix="cost-kb-three-channel-", dir=str(temp_parent))).resolve()
        if scratch.parent != temp_parent or not scratch.name.startswith("cost-kb-three-channel-"):
            raise RuntimeError("unsafe temporary path")
        base = scratch / "verified-source-snapshot.sqlite"
        _copy_database(source_conn, base)
        snapshot_conn = sqlite3.connect(str(base), timeout=30, isolation_level=None)
        try:
            snapshot_counts = {
                table: snapshot_conn.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0]
                for table in ("transactions", "ledger_entries", "review_decisions", "transaction_review_holds")}
            if snapshot_counts != {key: source_info["baseline_counts"][key] for key in snapshot_counts}:
                raise RuntimeError("snapshot row counts differ from read-only source")
        finally:
            snapshot_conn.close()

        clones = {}
        for name, order in (("approval_domestic_overseas", ["approval", "domestic_acquired", "overseas_acquired"]),
                            ("overseas_domestic_approval", ["overseas_acquired", "domestic_acquired", "approval"])):
            clone = scratch / (name + ".sqlite")
            base_conn = sqlite3.connect(str(base), timeout=30, isolation_level=None)
            try:
                _copy_database(base_conn, clone)
            finally:
                base_conn.close()
            clones[name] = _receive_order(clone, inputs, order)
            after_conn = sqlite3.connect(str(clone), timeout=30, isolation_level=None)
            try:
                clone_tables = _snapshot_db(after_conn)
                clones[name]["protection"] = _protection_report(baseline, clone_tables)
                clones[name]["link_validation"] = _link_validation(after_conn)
                counts = after_conn.execute(
                    "SELECT COUNT(*), COALESCE(SUM(amount_krw),0) FROM ledger_entries").fetchone()
                clones[name]["ledger_after"] = {"rows": counts[0], "amount_krw": counts[1]}
            finally:
                after_conn.close()

        semantic_equal = clones["approval_domestic_overseas"]["semantic_snapshot"] == \
            clones["overseas_domestic_approval"]["semantic_snapshot"]
        before_repeat_equal = all(value["reupload_semantics_unchanged"] for value in clones.values())
        protection_ok = all(
            value["protection"]["existing_transaction_ids_missing"] == 0
            and value["protection"]["existing_transaction_rows_changed"] == 0
            and value["protection"]["ledger_entries_unchanged"]
            and value["protection"]["user_decisions_unchanged"]
            and value["protection"]["refund_holds_unchanged"]
            and not value["protection"]["unexpected_table_changes"]
            and value["ledger_after"] == {"rows": initial_ledger[0], "amount_krw": initial_ledger[1]}
            for value in clones.values())
        links_ok = all(
            value["link_validation"].get("approval_rows_created_as_transactions") == 0
            and value["link_validation"].get("approval_rows_created_as_ledger_entries") == 0
            and value["link_validation"].get("links_to_missing_transactions") == 0
            and value["link_validation"].get("invalid_card_date_or_amount_links") == 0
            and value["link_validation"].get("multiple_approvals_per_transaction_groups") == 0
            for value in clones.values())
        approval_cost_rows = max(value["link_validation"].get("approval_rows_created_as_ledger_entries", 0)
                                 for value in clones.values())
        invalid_link_per_run = max(value["link_validation"].get("invalid_card_date_or_amount_links", 0)
                                    for value in clones.values())

        source_after_data_version = source_conn.execute("PRAGMA data_version").fetchone()[0]
        ota_after = _snapshot_db(ota_conn)
        ota_after_data_version = ota_conn.execute("PRAGMA data_version").fetchone()[0]
        ota_unchanged = {k: v["digest"] for k, v in ota_before.items()} == \
            {k: v["digest"] for k, v in ota_after.items()}
        input_counts_ok = all(row["expected_row_count_match"] for row in parsed_report.values())
        warnings = parsed_report["overseas_acquired"]
        overseas_new_cost_rows = sum(warnings["new_rows_by_kind"].get(kind, 0)
                                     for kind in ("purchase_or_other", "special"))
        route_source = Path(__file__).resolve().parents[1] / "webapp" / "card_flow.py"
        route_text = route_source.read_text(encoding="utf-8")
        route_receive_verified = ("if parsed.path == '/api/imports':" in route_text
                                  and "flow.pipeline.receive(raw," in route_text)
        return {
            "schema_version": 1,
            "created_at_utc": datetime.now(timezone.utc).isoformat(),
            "status": "safe" if all((protection_ok, links_ok, semantic_equal,
                                       before_repeat_equal, ota_unchanged, input_counts_ok,
                                       overseas_new_cost_rows == 0, route_receive_verified,
                                       source_after_data_version == source_info["data_version"],
                                       ota_after_data_version == ota_info["data_version"])) else "hold",
            "processing_path": {
                "class": "webapp.card_flow.CardFlow",
                "method": "CardFlow.pipeline.receive",
                "http_upload_route_uses_same_receive_call": route_receive_verified,
                "http_request_sent": False,
                "performed_classification_or_ledger_commit": False,
            },
            "source_database": source_info,
            "sqlite_snapshot": {
                "created_from_read_only_connection": True,
                "wal_aware_backup_api": True,
                "quick_check": "ok",
                "counts_match_source": True,
                "scratch_directory": str(scratch),
            },
            "ota_review_database": {
                **ota_info,
                "data_version_unchanged": ota_after_data_version == ota_info["data_version"],
                "table_rows_unchanged": ota_unchanged,
            },
            "inputs": parsed_report,
            "historical_warning_comparison": {
                "previously_reported_warning_rows": 709,
                "legacy_predicate_rows_on_current_initial_db": warnings["legacy_warning_rows_on_same_initial_db"],
                "current_near_match_candidates_on_same_initial_db": warnings["current_near_match_warning_candidates_on_same_initial_db"],
                "same_initial_db_comparison_available": True,
                "direct_comparison_to_historical_execution": False,
                "historical_comparison_reason": "기존 709건 실행의 DB 지문과 입력 SHA-256이 보존되지 않아 그 실행과 직접 대조할 수 없습니다.",
            },
            "runs": {
                "order_independent": semantic_equal,
                "same_files_reused_without_semantic_change": before_repeat_equal,
                "first_order": {k: v for k, v in clones["approval_domestic_overseas"].items()
                                if k != "semantic_snapshot"},
                "reverse_order": {k: v for k, v in clones["overseas_domestic_approval"].items()
                                  if k != "semantic_snapshot"},
            },
            "safety": {
                "protected_db_tables_unchanged": protection_ok,
                "ota_exact_manual_links_unchanged": ota_unchanged,
                "approval_rows_created_as_costs": approval_cost_rows,
                "invalid_links_per_run": invalid_link_per_run,
                "invalid_links_across_both_runs": sum(v["link_validation"].get("invalid_card_date_or_amount_links", 0)
                                                       for v in clones.values()),
                "all_expected_input_row_counts_match": input_counts_ok,
                "new_overseas_purchase_or_special_rows": overseas_new_cost_rows,
            },
        }
    finally:
        if source_conn is not None:
            source_conn.close()
        if ota_conn is not None:
            ota_conn.close()
        if scratch is not None:
            temp_parent = Path(tempfile.gettempdir()).resolve()
            if scratch.parent == temp_parent and scratch.name.startswith("cost-kb-three-channel-"):
                shutil.rmtree(scratch)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-db", required=True, help="현재 확인한 운영 DB 경로. 읽기 전용으로 엽니다.")
    parser.add_argument("--ota-review-db", required=True, help="읽기 전용으로 보호 상태를 확인할 OTA 검토 DB")
    parser.add_argument("--input-dir", required=True, help="KB XLS 세 파일이 있는 폴더")
    parser.add_argument("--output", default=str(ROOT / "outputs" / "kb-three-channel-reconcile-result.json"))
    args = parser.parse_args(argv)
    try:
        result = run(args)
        output = Path(args.output).resolve()
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(json.dumps({"status": result["status"], "output": str(output),
                          "inputs": {k: {"rows": v["rows"], "issues": v["parse_issue_count"],
                                         "kind_counts": v["row_kind_counts"]}
                                     for k, v in result["inputs"].items()},
                          "order_independent": result["runs"]["order_independent"],
                          "reupload_idempotent": result["runs"]["same_files_reused_without_semantic_change"],
                          "protection_ok": result["safety"]["protected_db_tables_unchanged"],
                          "links_ok": result["safety"]["invalid_links_per_run"] == 0},
                         ensure_ascii=False, indent=2))
        return 0 if result["status"] == "safe" else 2
    except Exception as exc:
        print(json.dumps({"status": "error", "error_type": type(exc).__name__,
                          "message": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
