"""Batch reads must preserve the manual-correction protection without history indexes."""
import json
import random
import sqlite3

from app.manual_overrides import human_sql, manual_fields, manual_rows


def test_legacy_row_factory_keeps_tuple_membership_for_manual_protection():
    with sqlite3.connect(':memory:') as conn:
        conn.row_factory = sqlite3.Row
        conn.execute('CREATE TABLE board_manual_overrides(row_id TEXT,field TEXT,event_id TEXT)')
        conn.execute('INSERT INTO board_manual_overrides VALUES (?,?,?)', ('card-a', 'item', ''))
        assert ('card-a', 'item') in manual_fields(conn)
        assert manual_rows(conn) == {'card-a'}


def test_legacy_database_keeps_all_overrides():
    with sqlite3.connect(':memory:') as conn:
        conn.execute('CREATE TABLE board_manual_overrides(row_id TEXT,field TEXT,event_id TEXT)')
        conn.executemany('INSERT INTO board_manual_overrides VALUES (?,?,?)',
                         [('card-a', 'item', ''), ('card-b', 'display_tab_id', 'unknown')])
        assert manual_fields(conn) == {('card-a', 'item'), ('card-b', 'display_tab_id')}
        assert manual_rows(conn) == {'card-a', 'card-b'}


def test_batch_read_matches_protection_predicate_without_history_indexes():
    rng = random.Random(9021)
    with sqlite3.connect(':memory:') as conn:
        conn.execute('CREATE TABLE board_manual_overrides(row_id TEXT,field TEXT,event_id TEXT,PRIMARY KEY(row_id,field))')
        conn.execute('CREATE TABLE board_revisions(row_id TEXT,revision INTEGER,event_id TEXT,actor TEXT,prev_json TEXT,new_json TEXT)')
        # Include pending/missing saves, creation-only human fields, later tool
        # overwrites, unrelated human edits, null/missing values and reversions.
        for number in range(150):
            row = f'card-{number}'
            for field in ('item', 'display_tab_id'):
                conn.execute('INSERT INTO board_manual_overrides VALUES (?,?,?)',
                             (row, field, rng.choice(['', 'unknown', 'e1', 'e2', 'e3'])))
            for revision in range(1, 5):
                prev = {k: rng.choice([None, '', 'a', 'b', 1]) for k in ('item', 'display_tab_id')}
                new = dict(prev)
                new[rng.choice(list(prev))] = rng.choice([None, '', 'a', 'b', 1])
                conn.execute('INSERT INTO board_revisions VALUES (?,?,?,?,?,?)',
                             (row, revision, f'e{revision}', rng.choice(['owner', 'owner-chat', 'automatic', 'review-tool', None]),
                              json.dumps(prev), json.dumps(new)))
        expected = set(conn.execute('SELECT o.row_id,o.field FROM board_manual_overrides o WHERE '+human_sql()))
        statements = []
        conn.set_trace_callback(statements.append)
        assert manual_fields(conn) == expected
        assert manual_rows(conn) == {row for row, _ in expected}
        batched = next(sql for sql in statements if sql.startswith('WITH tool_saves'))
        plan = conn.execute('EXPLAIN QUERY PLAN '+batched).fetchall()
        assert not any('CORRELATED' in str(step) for step in plan)
