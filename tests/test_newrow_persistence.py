"""Synthetic SQLite tests only — no production data touched.

Coverage: validation, insertion, idempotency (retry-safe), audit log,
conflict on changed content, preservation of other tables (manual/financial
stand-in), explicit failure semantics.
"""
import sqlite3, pytest, tempfile, os
from app.newrow_persistence import NewRowPersist, PersistenceValidationError, PersistenceConflictError, PersistenceAuditError

def test_persist_new_validated_rows_and_retry_idempotent(tmp_path):
    db = str(tmp_path / "synthetic_newrows.sqlite")
    p = NewRowPersist(db)
    rows = [{"row_id": "r1", "kind": "newcard", "content": {"a": 1}}]
    # First insert
    res = p.persist(rows, audit_subject="test-ins")
    assert res["inserted"] == ["r1"]
    assert res["skipped"] == []
    # Retry with same content -> idempotent skip, no duplicate, audit recorded again
    res2 = p.persist(rows, audit_subject="test-ins")
    assert res2["skipped"] == ["r1"]
    assert res2["inserted"] == []
    # Audit present
    conn = sqlite3.connect(db)
    audits = conn.execute("SELECT action, status FROM audit_log WHERE subject=?", ("test-ins",)).fetchall()
    assert len(audits) >= 2
    conn.close()

def test_persist_rejects_invalid_rows(tmp_path):
    db = str(tmp_path / "fail.sqlite")
    p = NewRowPersist(db)
    with pytest.raises(PersistenceValidationError):
        p.persist([{"row_id": "x"}])  # missing kind + content
    with pytest.raises(PersistenceValidationError):
        p.persist("notlist")

def test_persist_conflict_on_changed_content(tmp_path):
    db = str(tmp_path / "conflict.sqlite")
    p = NewRowPersist(db)
    p.persist([{"row_id": "r1", "kind": "k", "content": 1}], audit_subject="conf")
    with pytest.raises(PersistenceConflictError):
        p.persist([{"row_id": "r1", "kind": "k", "content": 2}], audit_subject="conf")

def test_persist_does_not_touch_existing_manual_financial_tables(tmp_path):
    """Preserve existing/manual/financial stand-in table."""
    db = str(tmp_path / "preserve.sqlite")
    conn = sqlite3.connect(db)
    conn.execute("CREATE TABLE manual_records (id INTEGER PRIMARY KEY, amount REAL)")
    conn.execute("INSERT INTO manual_records VALUES (1, 100.0)")
    conn.commit(); conn.close()
    p = NewRowPersist(db)
    p.persist([{"row_id": "n1", "kind": "new", "content": "v"}], audit_subject="pres")
    conn = sqlite3.connect(db)
    row = conn.execute("SELECT amount FROM manual_records WHERE id=1").fetchone()
    assert row[0] == 100.0
    # New table present
    new_rows = conn.execute("SELECT row_id FROM persisted_rows").fetchall()
    assert new_rows == [("n1",)]
    conn.close()

def test_persist_explicit_failure_on_bad_db_path(tmp_path):
    with pytest.raises(PersistenceValidationError):
        NewRowPersist("")
