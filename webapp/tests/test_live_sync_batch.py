"""Polling preserves the exact old token and permission scope with bounded SQL."""
import sqlite3
from types import SimpleNamespace

from webapp import live_sync


def legacy_token(conn, tabs, unclassified):
    parts = ['v1']
    for tab in sorted(set(tabs)):
        trip = conn.execute('SELECT tab_id, display_key, starts_on, ends_on, archived, deleted, revision FROM trip_tabs WHERE tab_id=?', (tab,)).fetchone()
        parts.append(('trip', trip))
        parts.extend(('row', tab, row) for row in conn.execute('SELECT row_id, revision FROM board_rows WHERE display_tab_id=? ORDER BY row_id', (tab,)))
        parts.extend(('alloc', tab, row) for row in conn.execute('SELECT allocation_id, source_row_id, amount_krw, active, source_revision, display_tab_id FROM income_allocations WHERE display_tab_id=? ORDER BY allocation_id', (tab,)))
    if unclassified:
        parts.extend(('unclassified', row) for row in conn.execute('SELECT row_id, revision FROM board_rows WHERE display_tab_id IS NULL ORDER BY row_id'))
    return live_sync._digest(parts)


def test_batched_tokens_preserve_revisions_scope_order_and_query_budget():
    conn = sqlite3.connect(':memory:')
    conn.executescript('''
      CREATE TABLE trip_tabs(tab_id TEXT,display_key TEXT,starts_on TEXT,ends_on TEXT,archived INT,deleted INT,revision INT);
      CREATE TABLE board_rows(row_id TEXT,revision INT,display_tab_id TEXT);
      CREATE TABLE income_allocations(allocation_id TEXT,source_row_id TEXT,amount_krw INT,active INT,source_revision INT,display_tab_id TEXT);
    ''')
    tabs = [f'trip-{i:04}' for i in range(1001)]
    conn.executemany('INSERT INTO trip_tabs VALUES(?,?,NULL,NULL,0,0,1)', ((t,t) for t in reversed(tabs)))
    conn.executemany('INSERT INTO board_rows VALUES(?,1,?)', ((t+'-row',t) for t in reversed(tabs)))
    conn.executemany('INSERT INTO income_allocations VALUES(?,?,?, ?,1,?)', ((t+'-alloc',t+'-row',-17,i%2,t) for i,t in enumerate(reversed(tabs))))
    conn.execute("INSERT INTO board_rows VALUES('unassigned',2,NULL)")
    store = SimpleNamespace(conn=conn)
    for selected, unclassified in (([],False),(tabs[:1],False),(tabs[:61],True),(tabs+['missing'],True)):
        expected = legacy_token(conn, selected, unclassified)
        queries = []
        conn.set_trace_callback(queries.append)
        actual = live_sync.scope_token(store, selected, include_unclassified=unclassified)
        conn.set_trace_callback(None)
        assert actual == expected
        assert len(queries) == 3*((len(selected)+499)//500)+int(unclassified)
    before = live_sync.viewer_token(store, tabs[:1])
    conn.execute('UPDATE board_rows SET revision=revision+1 WHERE display_tab_id=?',(tabs[-1],))
    assert live_sync.viewer_token(store,tabs[:1]) == before
    conn.execute('UPDATE board_rows SET revision=revision+1 WHERE display_tab_id=?',(tabs[0],))
    assert live_sync.viewer_token(store,tabs[:1]) != before
    conn.close()
