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


def test_board_rows_tab_index_is_used_and_idempotent():
    from webapp.ledger_store_schema import SCHEMA_SQL
    conn = sqlite3.connect(':memory:')
    try:
        conn.executescript(SCHEMA_SQL)
        conn.executescript(SCHEMA_SQL)
        for i in range(20):
            conn.execute("INSERT INTO board_rows VALUES (?,?,?,?,?)", (f'r{i}', 'expense', f'tab{i % 3}', 1, '{}'))
        sql = "SELECT row_id FROM board_rows WHERE display_tab_id='tab1' ORDER BY row_id"
        text = plan(conn, sql)
        assert 'idx_board_rows_display_tab' in text and 'SCAN' not in text
        assert 'TEMP B-TREE' not in text
        assert conn.execute("SELECT count(*) FROM sqlite_master WHERE name='idx_board_rows_display_tab'").fetchone()[0] == 1
    finally:
        conn.close()


def test_excluded_ids_matches_per_row_excluded(tmp_path):
    from app.closed_period import excluded, excluded_ids
    conn = synthetic_store(tmp_path)
    try:
        trips = [{'trip_id': 'open1', 'starts_on': '2026-07-01', 'ends_on': '2026-07-09'},
                 {'trip_id': 'old1', 'starts_on': '2025-05-01', 'ends_on': '2025-05-09'}]
        cases = [('a', '2025-03-01', 'open1'), ('b', '2026-02-01', 'old1'), ('c', '2026-02-02', 'open1'),
                 ('d', '2026-08-01', 'open1'), ('e', '2025-06-01', 'zzz')]
        conn.execute('DROP TABLE transactions')
        conn.execute('CREATE TABLE transactions(transaction_id,source_hash,approval_date,posting_date,trip_id,display_tab_id)')
        for tid, day, tab in cases:
            conn.execute("INSERT INTO transactions VALUES (?,?,?,?,?,?)", (tid, 'h', day, day, tab, tab))
        conn.execute("INSERT INTO review_decisions(transaction_id,revision,item,description,display_tab_id,note,decided_at) "
                     "VALUES ('c',1,'x','','open1','','t')")
        manual = manual_ids(conn)
        rows = [dict(zip(('transaction_id','source_hash','approval_date','posting_date','trip_id','display_tab_id'), r))
                for r in conn.execute('SELECT * FROM transactions')]
        expected = {r['transaction_id'] for r in rows
                    if excluded(r, trips, manual=r['transaction_id'] in manual)}
        assert excluded_ids(conn, trips) == expected
        assert expected and 'c' not in expected
    finally:
        conn.close()
