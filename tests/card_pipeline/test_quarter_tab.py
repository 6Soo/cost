import sqlite3

import pytest

from app import quarter_tab


class FakeStore:
    def __init__(self):
        import threading
        self.lock = threading.RLock()
        self.conn = sqlite3.connect(':memory:', isolation_level=None)
        self.conn.executescript("""
            CREATE TABLE transactions(transaction_id TEXT PRIMARY KEY, batch_id TEXT, source_hash TEXT,
              merchant TEXT, approval_date TEXT, posting_date TEXT, amount_krw INTEGER,
              transaction_direction TEXT, card_tail TEXT, item TEXT, display_tab_id TEXT, trip_id TEXT,
              user_confirmed INTEGER DEFAULT 0, duplicate_of TEXT, classification_state TEXT);
            CREATE TABLE ledger_entries(transaction_id TEXT NOT NULL UNIQUE, batch_id TEXT NOT NULL, item TEXT NOT NULL,
              description TEXT NOT NULL, display_tab_id TEXT NOT NULL, trip_id TEXT NOT NULL DEFAULT '',
              amount_krw INTEGER, merchant TEXT NOT NULL, occurred_on TEXT NOT NULL,
              transaction_direction TEXT NOT NULL, source_hash TEXT NOT NULL, committed_at TEXT NOT NULL);
        """)
        self.changes = []

    def log_change(self, kind, subject, detail):
        self.changes.append((kind, subject))


def add(store, tid, day, amount, tab='unclassified', confirmed=0):
    store.conn.execute("INSERT INTO transactions(transaction_id,batch_id,source_hash,merchant,approval_date,amount_krw,"
                       "transaction_direction,card_tail,item,display_tab_id,trip_id,user_confirmed,duplicate_of,classification_state)"
                       " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                       (tid, 'b1', 'h-' + tid, 'SHOP', day, amount, 'purchase', '3820', '분기 기타비용', tab, '',
                        confirmed, None, 'classified'))


def test_rows_are_placed_on_their_quarter_tab_by_approval_date_and_confirmed_once():
    store = FakeStore()
    add(store, 'a', '2026-05-03', 1000)
    add(store, 'b', '2026-08-20', 2000)
    add(store, 'c', '2026-10-02', 3000)
    placed = quarter_tab.assign_unassigned(store.conn)
    assert placed == {'quarter:2026:2': 1, 'quarter:2026:3': 1, 'quarter:2026:4': 1}
    assert [r['transaction_id'] for r in quarter_tab.pending_rows(store.conn, 'quarter:2026:3')] == ['b']

    result = quarter_tab.confirm_tab(store, 'quarter:2026:3')
    assert result == {'tab': 'quarter:2026:3', 'booked': 1, 'skipped': 0}
    assert store.conn.execute("SELECT COUNT(*) FROM ledger_entries").fetchone()[0] == 1
    assert store.conn.execute("SELECT user_confirmed FROM transactions WHERE transaction_id='b'").fetchone()[0] == 1

    again = quarter_tab.confirm_tab(store, 'quarter:2026:3')
    assert again['booked'] == 0
    assert store.conn.execute("SELECT COUNT(*) FROM ledger_entries").fetchone()[0] == 1


def test_an_invalid_tab_is_refused():
    with pytest.raises(quarter_tab.QuarterError):
        quarter_tab.confirm_tab(FakeStore(), 'quarter:2026:9')


def test_only_a_batch_collected_after_activation_is_recorded_and_older_rows_wait(monkeypatch):
    store = FakeStore()
    store.conn.executescript("""
        CREATE TABLE import_batches(batch_id TEXT PRIMARY KEY, received_at TEXT);
        CREATE TABLE import_batch_rows(batch_id TEXT, transaction_id TEXT);
        INSERT INTO import_batches VALUES ('old', '2026-10-09T14:00:00+00:00'), ('new', '2026-10-14T01:00:00+00:00');
    """)
    add(store, 'legacy', '2026-09-02', 5000)
    add(store, 'fresh', '2026-10-14', 7000)
    store.conn.executemany("INSERT INTO import_batch_rows VALUES (?,?)", [('old', 'legacy'), ('new', 'fresh')])
    quarter_tab.assign_unassigned(store.conn)
    monkeypatch.setenv('WEBLEDGER_AUTO_RECORD_SINCE', '2026-10-13T15:00:00+00:00')
    assert quarter_tab.book_batch(store, 'old') == 0
    assert quarter_tab.book_batch(store, 'new') == 1
    booked = store.conn.execute("SELECT transaction_id FROM ledger_entries").fetchall()
    assert booked == [('fresh',)]
    assert store.conn.execute("SELECT user_confirmed FROM transactions WHERE transaction_id='legacy'").fetchone()[0] == 0
