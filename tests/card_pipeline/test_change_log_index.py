import sqlite3

from app import db
from app.closed_period import manual_ids
from app.decision_provenance import RELEASE, RESTORE, active_decision_sql

INDEX = 'idx_change_log_kind_subject'


def synthetic_store(tmp_path):
    conn = sqlite3.connect(tmp_path / 'idx.sqlite', isolation_level=None)
    db.Store(conn)
    conn.execute('CREATE TABLE IF NOT EXISTS board_manual_overrides(row_id TEXT)')
    return conn


def plan(conn, sql):
    return ' | '.join(r[3] for r in conn.execute('EXPLAIN QUERY PLAN ' + sql))


def test_index_created_idempotently_with_exact_name(tmp_path):
    conn = synthetic_store(tmp_path)
    try:
        def index_sql():
            return conn.execute("SELECT sql FROM sqlite_master WHERE name=?", (INDEX,)).fetchall()
        before = index_sql()
        assert len(before) == 1
        db.Store(conn).ensure_schema()
        assert index_sql() == before
        assert db.Store.schema_differences(conn) == []
    finally:
        conn.close()


def test_manual_ids_plan_uses_index_and_result_is_unchanged(tmp_path):
    conn = synthetic_store(tmp_path)
    try:
        for i in range(30):
            conn.execute("INSERT INTO review_decisions(transaction_id,revision,item,description,display_tab_id,note,decided_at) "
                         "VALUES (?,1,'x','','trip:a','','t')", (f't{i}',))
            conn.execute("INSERT INTO change_log(at,kind,subject,detail_json) VALUES (?,?,?,?)",
                         ('t', 'other', f't{i}', '{}'))
        conn.execute("INSERT INTO change_log(at,kind,subject,detail_json) VALUES (?,?,?,?)",
                     ('t', RELEASE, 't1', '{"decision_revision":1}'))
        conn.execute("INSERT INTO change_log(at,kind,subject,detail_json) VALUES (?,?,?,?)",
                     ('t', RELEASE, 't2', '{"decision_revision":1}'))
        conn.execute("INSERT INTO change_log(at,kind,subject,detail_json) VALUES (?,?,?,?)",
                     ('t', RESTORE, 't2', '{"release_entry_id":%d}' % 32))
        expected = {f't{i}' for i in range(30)} - {'t1'}
        entry = conn.execute("SELECT entry_id FROM change_log WHERE kind=? AND subject='t2'", (RELEASE,)).fetchone()[0]
        conn.execute("UPDATE change_log SET detail_json=? WHERE kind=?", ('{"release_entry_id":%d}' % entry, RESTORE))
        assert manual_ids(conn) == expected
        sql = ("SELECT d.transaction_id FROM review_decisions d WHERE "
               + active_decision_sql(conn=conn))
        text = plan(conn, sql)
        assert INDEX in text
        assert 'SCAN p' not in text and 'SCAN change_log' not in text
        # Same result when the index is absent.
        conn.execute(f'DROP INDEX {INDEX}')
        assert manual_ids(conn) == expected
    finally:
        conn.close()
