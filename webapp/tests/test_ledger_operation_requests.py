"""Synthetic tests for the unified owner-profile/receipt-apply request journal.

Covers both physical formats (legacy two tables, unified one table plus two
compatibility views), the offline conversion tool's write-free preview, its
100% fidelity check, common source validation (shape/NULL/duplicate), its
refusals (sidecars, busy writer, existing backup, production paths/aliases),
rollback with backup preservation, and the idempotency contracts: first
apply, replay, same-id/different-input conflict with atomic rollback, and
domain separation of one shared request id. Everything is tmp_path synthetic;
no production store, port, or original is touched.
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import sqlite3
from pathlib import Path

import pytest

from tools import merge_ledger_operation_requests as merge_tool
from webapp.ledger_operation_requests import (
    OWNER_PROFILE_DOMAIN,
    RECEIPT_APPLY_DOMAIN,
    UNIFIED_TABLE_SQL,
    insert_operation_request,
    request_journal_shape,
)
from webapp.ledger_store import LedgerStore, SaveError
from webapp.ledger_store_schema import SCHEMA_SQL, _ensure_receipt_apply_tables

HASH1 = hashlib.sha256(b"synthetic-plan-1").hexdigest()
HASH2 = hashlib.sha256(b"synthetic-plan-2").hexdigest()
HASH3 = hashlib.sha256(b"synthetic-plan-3").hexdigest()


@pytest.fixture(autouse=True)
def _clean_production_env(monkeypatch):
    for name in ("WEBLEDGER_DATA_ROOT", "WEBLEDGER_DB", "WEBLEDGER_DATA_DB"):
        monkeypatch.delenv(name, raising=False)


def _receipt_plan(tab_id, candidate_id):
    image_sha256 = hashlib.sha256(candidate_id.encode("utf-8")).hexdigest()
    source_identity = "synthetic-source-" + candidate_id
    return [{
        "kind": "expense",
        "candidate_id": candidate_id,
        "source_identity": source_identity,
        "image_sha256": image_sha256,
        "revision": 1,
        "merchant": "합성 식당",
        "fields": {"display_tab_id": tab_id, "occurred_on": "2026-10-12",
                   "amount_krw": 12000, "item": "식비",
                   "description": "합성 영수증 비용", "evidence_type": "영수증",
                   "pay_method": "현금", "memo": ""},
        "source_json": {"image_sha256": image_sha256,
                        "source_identity": source_identity, "ordinal": 0,
                        "merchant": "합성 식당", "date": "2026-10-12",
                        "amount": 12000, "currency": "KRW", "payment": "cash",
                        "trip_id": tab_id},
    }]


def _no_prepare(store):
    raise AssertionError("prepare must not run on a replayed request")


def _populated_db(tmp_path):
    """A legacy-format synthetic board with two profile requests and one apply."""
    db_path = tmp_path / "board.sqlite"
    store = LedgerStore(db_path, seed_demo=True)
    try:
        tab = store.conn.execute("SELECT tab_id FROM trip_tabs LIMIT 1").fetchone()[0]
        profile = store.save_owner_profile(
            expected_revision=0, client_request_id="prof-1",
            company_name="합성 회사", assignee_name="합성 담당")
        store.save_owner_profile(expected_revision=1, client_request_id="prof-2",
                                 assignee_name="합성 담당2")
        body = store.apply_receipt_batch(
            request_id="receipt-req-1", request_hash=HASH1,
            prepare=lambda s: _receipt_plan(tab, "cand-synth-1"))
    finally:
        store.close()
    return {"path": db_path, "tab": tab, "profile": profile, "receipt": body}


def _convert(db_path, capsys):
    assert merge_tool.main(["--db", str(db_path), "--apply"]) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "APPLIED"


def _raw_sql(db_path, script):
    conn = sqlite3.connect(str(db_path))
    try:
        conn.executescript(script)
    finally:
        conn.close()


def _object_types(db_path):
    conn = sqlite3.connect(str(db_path))
    try:
        return dict(conn.execute(
            "SELECT name, type FROM sqlite_master WHERE name IN"
            " ('owner_profile_requests','receipt_apply_requests',"
            "'ledger_operation_requests')"))
    finally:
        conn.close()


def _journal_snapshot(db_path):
    conn = sqlite3.connect(str(db_path))
    try:
        owner = {row[0]: row[1:] for row in conn.execute(
            "SELECT client_request_id, input_digest, result_json, created_at"
            " FROM owner_profile_requests")}
        receipt = {row[0]: row[1:] for row in conn.execute(
            "SELECT request_id, request_hash, result_json, created_at"
            " FROM receipt_apply_requests")}
        board = dict(conn.execute("SELECT row_id, payload_json FROM board_rows"))
        profile = conn.execute(
            "SELECT company_name, assignee_name, revision FROM owner_profile"
            " WHERE profile_id='owner'").fetchone()
        counts = {name: conn.execute(f'SELECT COUNT(*) FROM "{name}"').fetchone()[0]
                  for name in ("board_rows", "board_revisions", "owner_profile_history",
                               "receipt_apply_sources", "trip_tabs", "ledger_outbox")}
        return {"owner": owner, "receipt": receipt, "board": board,
                "profile": profile, "counts": counts}
    finally:
        conn.close()


def _unified_rows(db_path):
    conn = sqlite3.connect(str(db_path))
    try:
        return {(row[0], row[1]): row[2:] for row in conn.execute(
            "SELECT domain, request_id, input_digest, result_json, created_at"
            " FROM ledger_operation_requests")}
    finally:
        conn.close()


def _sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_legacy_init_keeps_two_tables_and_creates_no_unified_table(tmp_path):
    store = LedgerStore(tmp_path / "legacy.sqlite", seed_demo=False)
    try:
        assert request_journal_shape(store.conn) == "legacy"
        assert not store._request_journal_unified
    finally:
        store.close()
    types = _object_types(tmp_path / "legacy.sqlite")
    assert types == {"owner_profile_requests": "table",
                     "receipt_apply_requests": "table"}


def test_legacy_owner_profile_first_save_replay_and_conflict(tmp_path):
    store = LedgerStore(tmp_path / "legacy.sqlite", seed_demo=True)
    try:
        first = store.save_owner_profile(expected_revision=0, client_request_id="p1",
                                         company_name="합성 회사", assignee_name="합성 담당")
        assert first["outcome"] == "saved" and first["revision"] == 1
        replay = store.save_owner_profile(expected_revision=0, client_request_id="p1",
                                          company_name="합성 회사", assignee_name="합성 담당")
        assert replay == first
        with pytest.raises(SaveError) as exc:
            store.save_owner_profile(expected_revision=1, client_request_id="p1",
                                     company_name="다른 회사")
        assert exc.value.code == "EDIT_CONFLICT"
        assert store.owner_profile()["revision"] == 1
        assert store.conn.execute(
            "SELECT COUNT(*) FROM owner_profile_requests").fetchone()[0] == 1
        assert store.conn.execute(
            "SELECT COUNT(*) FROM owner_profile_history").fetchone()[0] == 1
    finally:
        store.close()


def test_legacy_receipt_first_apply_replay_and_conflict(tmp_path):
    store = LedgerStore(tmp_path / "legacy.sqlite", seed_demo=True)
    try:
        tab = store.conn.execute("SELECT tab_id FROM trip_tabs LIMIT 1").fetchone()[0]
        first = store.apply_receipt_batch(
            request_id="r1", request_hash=HASH1,
            prepare=lambda s: _receipt_plan(tab, "cand-legacy-1"))
        assert first["outcome"] == "applied"
        replay = store.apply_receipt_batch(request_id="r1", request_hash=HASH1,
                                           prepare=_no_prepare)
        assert replay == first
        with pytest.raises(SaveError) as exc:
            store.apply_receipt_batch(
                request_id="r1", request_hash=HASH2,
                prepare=lambda s: _receipt_plan(tab, "cand-legacy-2"))
        assert exc.value.code == "REQUEST_ID_REUSED"
        assert store.conn.execute(
            "SELECT COUNT(*) FROM board_rows WHERE row_id LIKE 'rcpt-%'").fetchone()[0] == 1
        assert store.conn.execute(
            "SELECT COUNT(*) FROM receipt_apply_sources").fetchone()[0] == 1
        assert store.conn.execute(
            "SELECT COUNT(*) FROM receipt_apply_requests").fetchone()[0] == 1
    finally:
        store.close()


def test_merge_dry_run_is_write_free_and_leaves_copy_unchanged(tmp_path, capsys):
    fixture = _populated_db(tmp_path)
    db_path = fixture["path"]
    before = _journal_snapshot(db_path)
    before_hash = _sha256(db_path)
    assert merge_tool.main(["--db", str(db_path)]) == 0
    assert json.loads(capsys.readouterr().out) == {
        "status": "PREVIEW", "owner_profile_requests": 2, "receipt_apply_requests": 1}
    assert _sha256(db_path) == before_hash
    assert _journal_snapshot(db_path) == before
    assert _object_types(db_path) == {
        "owner_profile_requests": "table", "receipt_apply_requests": "table"}
    for suffix in ("-wal", "-shm", "-journal"):
        assert not os.path.lexists(str(db_path) + suffix)
    assert not (tmp_path / "board.sqlite.pre-merge-backup").exists()


def test_merge_apply_converts_with_full_fidelity(tmp_path, capsys):
    fixture = _populated_db(tmp_path)
    before = _journal_snapshot(fixture["path"])
    assert merge_tool.main(["--db", str(fixture["path"]), "--apply"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out == {"status": "APPLIED", "owner_profile_requests": 2,
                   "receipt_apply_requests": 1}

    assert _object_types(fixture["path"]) == {
        "owner_profile_requests": "view", "receipt_apply_requests": "view",
        "ledger_operation_requests": "table"}
    expected = {(OWNER_PROFILE_DOMAIN, key): value
                for key, value in before["owner"].items()}
    expected.update({(RECEIPT_APPLY_DOMAIN, key): value
                     for key, value in before["receipt"].items()})
    assert _unified_rows(fixture["path"]) == expected

    after = _journal_snapshot(fixture["path"])
    assert after["owner"] == before["owner"]
    assert after["receipt"] == before["receipt"]
    assert after["board"] == before["board"]
    assert after["profile"] == before["profile"]
    assert after["counts"] == before["counts"]
    assert (tmp_path / "board.sqlite.pre-merge-backup").is_file()


def test_unified_reopen_replays_and_never_recreates_legacy_tables(tmp_path, capsys):
    fixture = _populated_db(tmp_path)
    _convert(fixture["path"], capsys)
    store = LedgerStore(fixture["path"], seed_demo=False)
    try:
        assert store._request_journal_unified
        replay = store.save_owner_profile(
            expected_revision=0, client_request_id="prof-1",
            company_name="합성 회사", assignee_name="합성 담당")
        assert replay == fixture["profile"]
        assert store.apply_receipt_batch(
            request_id="receipt-req-1", request_hash=HASH1,
            prepare=_no_prepare) == fixture["receipt"]

        saved = store.save_owner_profile(expected_revision=2, client_request_id="prof-3",
                                         company_name="합성 회사2")
        assert saved["outcome"] == "saved" and saved["revision"] == 3
        applied = store.apply_receipt_batch(
            request_id="receipt-req-2", request_hash=HASH2,
            prepare=lambda s: _receipt_plan(fixture["tab"], "cand-synth-2"))
        assert applied["outcome"] == "applied"
        assert store.apply_receipt_batch(
            request_id="receipt-req-2", request_hash=HASH2,
            prepare=_no_prepare) == applied
        assert store.conn.execute(
            "SELECT COUNT(*) FROM ledger_operation_requests").fetchone()[0] == 5
        assert store.conn.execute(
            "SELECT COUNT(*) FROM board_rows WHERE row_id LIKE 'rcpt-%'").fetchone()[0] == 2
    finally:
        store.close()
    assert _object_types(fixture["path"]) == {
        "owner_profile_requests": "view", "receipt_apply_requests": "view",
        "ledger_operation_requests": "table"}


def test_same_request_id_in_both_domains_stays_separate(tmp_path, capsys):
    fixture = _populated_db(tmp_path)
    _convert(fixture["path"], capsys)
    store = LedgerStore(fixture["path"], seed_demo=False)
    try:
        profile = store.save_owner_profile(expected_revision=2, client_request_id="shared-id",
                                           assignee_name="공유 담당")
        receipt = store.apply_receipt_batch(
            request_id="shared-id", request_hash=HASH3,
            prepare=lambda s: _receipt_plan(fixture["tab"], "cand-shared"))
        assert profile["outcome"] == "saved"
        assert receipt["outcome"] == "applied"
        assert store.save_owner_profile(expected_revision=2, client_request_id="shared-id",
                                        assignee_name="공유 담당") == profile
        assert store.apply_receipt_batch(request_id="shared-id", request_hash=HASH3,
                                         prepare=_no_prepare) == receipt
        rows = store.conn.execute(
            "SELECT domain FROM ledger_operation_requests WHERE request_id='shared-id'"
        ).fetchall()
        assert sorted(row[0] for row in rows) == [OWNER_PROFILE_DOMAIN, RECEIPT_APPLY_DOMAIN]
    finally:
        store.close()


def test_unified_conflicts_roll_back_atomically(tmp_path, capsys):
    fixture = _populated_db(tmp_path)
    _convert(fixture["path"], capsys)
    store = LedgerStore(fixture["path"], seed_demo=False)
    try:
        counts = {name: store.conn.execute(
            f'SELECT COUNT(*) FROM "{name}"').fetchone()[0]
            for name in ("board_rows", "board_revisions", "receipt_apply_sources",
                         "owner_profile_history", "ledger_operation_requests")}
        with pytest.raises(SaveError) as exc:
            store.apply_receipt_batch(
                request_id="receipt-req-1", request_hash="f" * 64,
                prepare=lambda s: _receipt_plan(fixture["tab"], "cand-conflict"))
        assert exc.value.code == "REQUEST_ID_REUSED"
        with pytest.raises(SaveError) as exc:
            store.save_owner_profile(expected_revision=2, client_request_id="prof-1",
                                     company_name="다른 회사")
        assert exc.value.code == "EDIT_CONFLICT"
        for name, want in counts.items():
            assert store.conn.execute(
                f'SELECT COUNT(*) FROM "{name}"').fetchone()[0] == want
        assert store.owner_profile()["revision"] == 2
        assert not store.conn.in_transaction
    finally:
        store.close()


def test_merge_refuses_empty_journals_with_no_data(tmp_path, capsys):
    db_path = tmp_path / "empty.sqlite"
    store = LedgerStore(db_path, seed_demo=False)
    store.close()
    for extra in ([], ["--apply"]):
        assert merge_tool.main(["--db", str(db_path), *extra]) == 2
        assert json.loads(capsys.readouterr().out)["reason"] == "NO_DATA"
    assert _object_types(db_path) == {"owner_profile_requests": "table",
                                      "receipt_apply_requests": "table"}
    assert not (tmp_path / "empty.sqlite.pre-merge-backup").exists()


def test_merge_refuses_second_run_already_unified(tmp_path, capsys):
    fixture = _populated_db(tmp_path)
    _convert(fixture["path"], capsys)
    for extra in (["--apply"], []):
        assert merge_tool.main(["--db", str(fixture["path"]), *extra]) == 2
        assert json.loads(capsys.readouterr().out)["reason"] == "ALREADY_UNIFIED"


def test_merge_refuses_production_paths_and_aliases(tmp_path, capsys, monkeypatch):
    fixture = _populated_db(tmp_path)
    db_path = fixture["path"]

    alias = tmp_path / "hardlink-alias.sqlite"
    os.link(db_path, alias)
    assert merge_tool.main(["--db", str(alias)]) == 2
    assert json.loads(capsys.readouterr().out)["reason"] == "PATH_REFUSED"

    link = tmp_path / "symlink-alias.sqlite"
    try:
        os.symlink(db_path, link)
    except OSError:
        link = None  # symlink privilege unavailable; hardlink already covered aliases
    if link is not None:
        assert merge_tool.main(["--db", str(link)]) == 2
        assert json.loads(capsys.readouterr().out)["reason"] == "PATH_REFUSED"

    monkeypatch.setenv("WEBLEDGER_DB", str(db_path))
    assert merge_tool.main(["--db", str(db_path)]) == 2
    assert json.loads(capsys.readouterr().out)["reason"] == "PATH_REFUSED"
    monkeypatch.delenv("WEBLEDGER_DB")

    prod = tmp_path / "prod-root"
    prod.mkdir()
    copy = prod / "board.sqlite"
    shutil.copy2(db_path, copy)
    monkeypatch.setenv("WEBLEDGER_DATA_ROOT", str(prod))
    assert merge_tool.main(["--db", str(copy), "--apply"]) == 2
    assert json.loads(capsys.readouterr().out)["reason"] == "PATH_REFUSED"
    assert _object_types(copy) == {"owner_profile_requests": "table",
                                   "receipt_apply_requests": "table"}
    assert _object_types(db_path) == {"owner_profile_requests": "table",
                                      "receipt_apply_requests": "table"}


@pytest.mark.parametrize("suffix", ["-wal", "-shm", "-journal"])
def test_merge_refuses_sidecars_without_touching_bytes(tmp_path, capsys, suffix):
    fixture = _populated_db(tmp_path)
    db_path = fixture["path"]
    before_hash = _sha256(db_path)
    sidecar = Path(str(db_path) + suffix)
    sidecar.write_bytes(b"synthetic sidecar")
    try:
        for extra in ([], ["--apply"]):
            assert merge_tool.main(["--db", str(db_path), *extra]) == 2
            assert json.loads(capsys.readouterr().out)["reason"] == "SIDECAR_PRESENT"
        assert _sha256(db_path) == before_hash
        assert sidecar.read_bytes() == b"synthetic sidecar"
        assert not (tmp_path / "board.sqlite.pre-merge-backup").exists()
    finally:
        sidecar.unlink()


def test_merge_refuses_busy_wal_writer_without_change(tmp_path, capsys):
    fixture = _populated_db(tmp_path)
    db_path = fixture["path"]
    before = _journal_snapshot(db_path)
    holder = sqlite3.connect(str(db_path))
    try:
        holder.execute("BEGIN IMMEDIATE")
        # An active WAL writer owns -wal/-shm, so the byte-preservation guard
        # refuses before the tool opens the file at all.
        assert merge_tool.main(["--db", str(db_path), "--apply"]) == 2
        assert json.loads(capsys.readouterr().out)["reason"] == "SIDECAR_PRESENT"
    finally:
        holder.rollback()
        holder.close()
    assert _journal_snapshot(db_path) == before
    assert _object_types(db_path) == {"owner_profile_requests": "table",
                                      "receipt_apply_requests": "table"}
    assert not (tmp_path / "board.sqlite.pre-merge-backup").exists()


def test_merge_refuses_locked_writer_db_busy(tmp_path, capsys):
    fixture = _populated_db(tmp_path)
    db_path = fixture["path"]
    # Rollback-journal mode: a RESERVED lock holder creates no sidecar until it
    # writes a page, so the tool reaches BEGIN IMMEDIATE and must refuse busy.
    _raw_sql(db_path, "PRAGMA journal_mode=DELETE;")
    before = _journal_snapshot(db_path)
    holder = sqlite3.connect(str(db_path))
    try:
        holder.execute("BEGIN IMMEDIATE")
        assert merge_tool.main(["--db", str(db_path), "--apply"]) == 2
        assert json.loads(capsys.readouterr().out)["reason"] == "DB_BUSY"
    finally:
        holder.rollback()
        holder.close()
    assert _journal_snapshot(db_path) == before
    assert _object_types(db_path) == {"owner_profile_requests": "table",
                                      "receipt_apply_requests": "table"}
    assert not (tmp_path / "board.sqlite.pre-merge-backup").exists()


def test_merge_refuses_null_source_field(tmp_path, capsys):
    fixture = _populated_db(tmp_path)
    # The legacy column is NOT NULL, so a NULL field can only exist in a
    # hand-corrupted copy: rebuild the table without constraints, then inject.
    _raw_sql(fixture["path"], """
        CREATE TABLE owner_profile_requests_null AS SELECT * FROM owner_profile_requests;
        DROP TABLE owner_profile_requests;
        ALTER TABLE owner_profile_requests_null RENAME TO owner_profile_requests;
        UPDATE owner_profile_requests SET input_digest=NULL WHERE client_request_id='prof-1';
    """)
    for extra in ([], ["--apply"]):
        assert merge_tool.main(["--db", str(fixture["path"]), *extra]) == 2
        assert json.loads(capsys.readouterr().out)["reason"] == "SOURCE_INVALID"
    assert _object_types(fixture["path"]) == {
        "owner_profile_requests": "table", "receipt_apply_requests": "table"}
    assert not (tmp_path / "board.sqlite.pre-merge-backup").exists()


def test_merge_refuses_duplicate_source_key(tmp_path, capsys):
    fixture = _populated_db(tmp_path)
    _raw_sql(fixture["path"], """
        CREATE TABLE owner_profile_requests_dup AS SELECT * FROM owner_profile_requests;
        DROP TABLE owner_profile_requests;
        ALTER TABLE owner_profile_requests_dup RENAME TO owner_profile_requests;
        INSERT INTO owner_profile_requests
            SELECT * FROM owner_profile_requests WHERE client_request_id='prof-1';
    """)
    for extra in ([], ["--apply"]):
        assert merge_tool.main(["--db", str(fixture["path"]), *extra]) == 2
        assert json.loads(capsys.readouterr().out)["reason"] == "SOURCE_INVALID"
    assert not (tmp_path / "board.sqlite.pre-merge-backup").exists()


def test_mixed_shape_fails_closed_in_tool_and_store(tmp_path, capsys):
    fixture = _populated_db(tmp_path)
    _raw_sql(fixture["path"], UNIFIED_TABLE_SQL)
    for extra in ([], ["--apply"]):
        assert merge_tool.main(["--db", str(fixture["path"]), *extra]) == 2
        assert json.loads(capsys.readouterr().out)["reason"] == "LEGACY_SHAPE"
    with pytest.raises(RuntimeError):
        LedgerStore(fixture["path"], seed_demo=False)


def test_unified_missing_view_fails_closed(tmp_path, capsys):
    fixture = _populated_db(tmp_path)
    _convert(fixture["path"], capsys)
    _raw_sql(fixture["path"], "DROP VIEW owner_profile_requests;")
    assert merge_tool.main(["--db", str(fixture["path"])]) == 2
    assert json.loads(capsys.readouterr().out)["reason"] == "LEGACY_SHAPE"
    with pytest.raises(RuntimeError):
        LedgerStore(fixture["path"], seed_demo=False)


def test_merge_refuses_existing_protected_backup(tmp_path, capsys):
    fixture = _populated_db(tmp_path)
    backup = tmp_path / "board.sqlite.pre-merge-backup"
    backup.write_bytes(b"previous protected backup")
    before = _journal_snapshot(fixture["path"])
    assert merge_tool.main(["--db", str(fixture["path"]), "--apply"]) == 2
    assert json.loads(capsys.readouterr().out)["reason"] == "BACKUP_EXISTS"
    assert backup.read_bytes() == b"previous protected backup"
    assert _journal_snapshot(fixture["path"]) == before


def test_merge_failure_rolls_back_and_preserves_backup(tmp_path, capsys, monkeypatch):
    fixture = _populated_db(tmp_path)
    before = _journal_snapshot(fixture["path"])
    original_bytes = fixture["path"].read_bytes()
    original = merge_tool.insert_operation_request
    calls = {"n": 0}

    def failing_insert(conn, **kwargs):
        calls["n"] += 1
        if calls["n"] == 2:
            raise RuntimeError("synthetic merge failure")
        return original(conn, **kwargs)

    monkeypatch.setattr(merge_tool, "insert_operation_request", failing_insert)
    assert merge_tool.main(["--db", str(fixture["path"]), "--apply"]) == 2
    out = json.loads(capsys.readouterr().out)
    assert out["reason"] == "INTERNAL_ERROR"
    assert "backup_restored" not in out
    assert calls["n"] == 2
    backup = tmp_path / "board.sqlite.pre-merge-backup"
    assert backup.is_file()
    assert backup.read_bytes() == original_bytes
    assert _journal_snapshot(fixture["path"]) == before
    assert _object_types(fixture["path"]) == {
        "owner_profile_requests": "table", "receipt_apply_requests": "table"}


def test_insert_helper_keeps_external_transaction_invariant():
    conn = sqlite3.connect(":memory:")
    try:
        conn.executescript(SCHEMA_SQL)
        _ensure_receipt_apply_tables(conn)
        for domain, unified in ((OWNER_PROFILE_DOMAIN, False),
                                (RECEIPT_APPLY_DOMAIN, False),
                                (OWNER_PROFILE_DOMAIN, True),
                                (RECEIPT_APPLY_DOMAIN, True)):
            if unified:
                conn.execute(UNIFIED_TABLE_SQL)
            table = ("ledger_operation_requests" if unified
                     else "owner_profile_requests" if domain == OWNER_PROFILE_DOMAIN
                     else "receipt_apply_requests")
            conn.execute("BEGIN")
            insert_operation_request(
                conn, unified=unified, domain=domain, request_id="txn-1",
                input_digest="d" * 64, result_json="{}",
                created_at="2026-11-20T00:00:00+00:00")
            assert conn.in_transaction
            conn.execute("ROLLBACK")
            assert conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] == 0
            conn.execute("BEGIN")
            insert_operation_request(
                conn, unified=unified, domain=domain, request_id="txn-1",
                input_digest="d" * 64, result_json="{}",
                created_at="2026-11-20T00:00:00+00:00")
            conn.execute("COMMIT")
            assert conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] == 1
            conn.execute("DELETE FROM " + table)
            conn.commit()
        with pytest.raises(ValueError):
            insert_operation_request(
                conn, unified=False, domain="unknown", request_id="x",
                input_digest="d", result_json="{}", created_at="t")
    finally:
        conn.close()


def test_unified_duplicate_key_conflict_rolls_back_whole_transaction():
    conn = sqlite3.connect(":memory:")
    try:
        conn.execute(UNIFIED_TABLE_SQL)
        conn.execute("BEGIN")
        insert_operation_request(
            conn, unified=True, domain=OWNER_PROFILE_DOMAIN, request_id="dup",
            input_digest="d" * 64, result_json="{}",
            created_at="2026-11-20T00:00:00+00:00")
        insert_operation_request(
            conn, unified=True, domain=RECEIPT_APPLY_DOMAIN, request_id="dup",
            input_digest="e" * 64, result_json="{}",
            created_at="2026-11-20T00:00:00+00:00")
        with pytest.raises(sqlite3.IntegrityError):
            insert_operation_request(
                conn, unified=True, domain=OWNER_PROFILE_DOMAIN, request_id="dup",
                input_digest="f" * 64, result_json="{}",
                created_at="2026-11-20T00:00:00+00:00")
        conn.execute("ROLLBACK")
        assert conn.execute(
            "SELECT COUNT(*) FROM ledger_operation_requests").fetchone()[0] == 0
    finally:
        conn.close()
