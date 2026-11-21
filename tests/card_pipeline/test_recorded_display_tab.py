"""Read-only recorded board tabs on the monthly/year/undated card projections."""
import json
import sqlite3

from app.card_destination import display_destination
from webapp import card_transactions as ct

TRANSACTIONS_SQL = """
CREATE TABLE transactions (
    transaction_id TEXT PRIMARY KEY,
    source_hash TEXT NOT NULL,
    batch_id TEXT NOT NULL,
    issuer TEXT NOT NULL,
    card_tail TEXT NOT NULL,
    card_kind TEXT NOT NULL,
    transaction_direction TEXT NOT NULL,
    transaction_kind TEXT NOT NULL,
    approval_number TEXT NOT NULL,
    original_approval_number TEXT NOT NULL,
    approval_date TEXT NOT NULL,
    posting_date TEXT NOT NULL,
    merchant TEXT NOT NULL,
    merchant_normalized TEXT NOT NULL,
    amount_krw INTEGER,
    foreign_amount TEXT NOT NULL DEFAULT '',
    foreign_currency TEXT NOT NULL DEFAULT '',
    description_raw TEXT NOT NULL DEFAULT '',
    row_index INTEGER NOT NULL,
    raw_row_json TEXT NOT NULL,
    duplicate_of TEXT,
    conflict_reason TEXT NOT NULL DEFAULT '',
    parse_error TEXT NOT NULL DEFAULT '',
    classification_state TEXT NOT NULL DEFAULT 'needs_review',
    classification_source TEXT NOT NULL DEFAULT '',
    classification_basis TEXT NOT NULL DEFAULT '',
    item TEXT NOT NULL DEFAULT '',
    description TEXT NOT NULL DEFAULT '',
    display_tab_id TEXT NOT NULL DEFAULT '',
    trip_id TEXT NOT NULL DEFAULT '',
    revision INTEGER NOT NULL DEFAULT 1,
    decided_at TEXT,
    created_at TEXT NOT NULL
)
"""


def _add_transaction(conn, transaction_id, *, approval_date="2026-03-05", display_tab_id="",
                     trip_id="", direction="debit"):
    conn.execute(
        "INSERT INTO transactions (transaction_id, source_hash, batch_id, issuer, card_tail,"
        " card_kind, transaction_direction, transaction_kind, approval_number,"
        " original_approval_number, approval_date, posting_date, merchant, merchant_normalized,"
        " row_index, raw_row_json, display_tab_id, trip_id, classification_source, created_at)"
        " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (transaction_id, 'h-' + transaction_id, 'b1', 'CARD', '1234', 'credit', direction,
         'debit', 'A' + transaction_id, 'A' + transaction_id, approval_date, approval_date,
         'MERCHANT', 'merchant', 1, '{}', display_tab_id, trip_id, 'inference', '2026-01-01'))


def _make_db(tmp_path, *, name='card.sqlite', with_board=True, board_columns=('row_id', 'row_kind', 'display_tab_id',
                                                                             'payload_json'),
             board_rows=(), overrides=None, transactions=()):
    path = tmp_path / name
    conn = sqlite3.connect(str(path))
    conn.executescript(TRANSACTIONS_SQL)
    if with_board:
        conn.execute('CREATE TABLE board_rows (' + ', '.join(board_columns) + ')')
    if overrides is not None:
        conn.execute('CREATE TABLE board_manual_overrides (row_id TEXT, field TEXT)')
    for item in transactions:
        _add_transaction(conn, **item)
    if with_board:
        columns = ', '.join(board_columns)
        conn.executemany(f'INSERT INTO board_rows ({columns}) VALUES ('
                         + ','.join('?' for _ in board_columns) + ')', board_rows)
    if overrides is not None:
        conn.executemany('INSERT INTO board_manual_overrides VALUES (?,?)', overrides)
    conn.commit()
    conn.close()
    return path


def test_month_year_and_undated_attach_the_recorded_board_tab(tmp_path):
    recorded_payload = json.dumps({'display_tab_id': 'quarter:2026:2'}, sort_keys=True)
    path = _make_db(
        tmp_path,
        transactions=[
            {'transaction_id': 'TX-REC', 'display_tab_id': 'trip-old', 'trip_id': 'trip-old'},
            {'transaction_id': 'TX-Q', 'display_tab_id': 'unclassified'},
            {'transaction_id': 'TX-NONE', 'display_tab_id': 'trip-2', 'trip_id': 'trip-2'},
            {'transaction_id': 'TX-UND', 'approval_date': '', 'display_tab_id': '', 'trip_id': ''},
        ],
        board_rows=[
            ('card-TX-REC', 'expense', 'trip-recorded', recorded_payload),
            ('card-TX-Q', 'expense', 'quarter:2026:2', recorded_payload),
        ],
    )
    month = {item['transaction_id']: item for item in ct.list_for_month(path, 2026, 3)['items']}
    assert month['TX-REC']['recorded_display_tab_id'] == 'trip-recorded'
    assert month['TX-Q']['recorded_display_tab_id'] == 'quarter:2026:2'
    assert month['TX-NONE']['recorded_display_tab_id'] is None

    # The day view and the single-transaction detail share the same read path.
    day = {item['transaction_id']: item for item in ct.list_for_day(path, day='2026-03-05')['items']}
    assert day['TX-REC']['recorded_display_tab_id'] == 'trip-recorded'
    detail = ct.transaction_detail('TX-REC', path)
    assert detail['recorded_display_tab_id'] == 'trip-recorded'

    year = {item['transaction_id']: item for item in ct.search_for_year(path, 2026)['items']}
    assert year['TX-REC']['recorded_display_tab_id'] == 'trip-recorded'
    assert year['TX-NONE']['recorded_display_tab_id'] is None

    undated = {item['transaction_id']: item for item in ct.undated_list(path, 2026)['items']}
    assert undated['TX-UND']['recorded_display_tab_id'] is None


def test_a_real_manual_display_correction_outranks_the_recorded_column(tmp_path):
    payload = json.dumps({'display_tab_id': 'trip-manual'})
    path = _make_db(
        tmp_path,
        transactions=[{'transaction_id': 'TX-MAN'}],
        board_rows=[('card-TX-MAN', 'expense', 'trip-column', payload)],
        overrides=[('card-TX-MAN', 'display_tab_id')],
    )
    item = ct.list_for_month(path, 2026, 3)['items'][0]
    assert item['recorded_display_tab_id'] == 'trip-manual'


def test_missing_or_old_board_tables_contribute_no_recorded_tab(tmp_path):
    no_board = _make_db(tmp_path, name='no-board.sqlite', with_board=False,
                        transactions=[{'transaction_id': 'TX-1'}])
    assert ct.list_for_month(no_board, 2026, 3)['items'][0]['recorded_display_tab_id'] is None

    old_columns = _make_db(tmp_path, name='old-columns.sqlite',
                           board_columns=('row_id', 'row_kind', 'payload_json'),
                           board_rows=[('card-TX-1', 'expense', '{}')],
                           transactions=[{'transaction_id': 'TX-1'}])
    assert ct.list_for_month(old_columns, 2026, 3)['items'][0]['recorded_display_tab_id'] is None


def test_recorded_lookups_stay_a_single_query(tmp_path, monkeypatch):
    path = _make_db(
        tmp_path,
        transactions=[{'transaction_id': 'TX-%d' % n} for n in range(5)],
        board_rows=[('card-TX-%d' % n, 'expense', 'trip-%d' % n, '{}') for n in range(5)],
    )
    executed = []
    original_connect = ct._connect

    def traced(db_path):
        conn = original_connect(db_path)
        conn.set_trace_callback(executed.append)
        return conn

    monkeypatch.setattr(ct, '_connect', traced)
    items = ct.list_for_month(path, 2026, 3)['items']
    assert len(items) == 5
    board_queries = [sql for sql in executed if 'FROM board_rows' in sql]
    assert len(board_queries) == 1, board_queries


def test_display_destination_prefers_the_recorded_tab_without_breaking_others():
    trip_names = {'trip-old': '합성 여행'}
    assert display_destination({'recorded_display_tab_id': 'quarter:2026:1',
                                'display_tab_id': 'trip-old'}, trip_names) == '2026년 1분기 기타비용'
    assert display_destination({'recorded_display_tab_id': 'trip-old',
                                'display_tab_id': 'other', 'trip_id': 'trip-old'}, trip_names) == '합성 여행'
    # No recorded tab: the stored attribution and existing fallbacks are unchanged.
    assert display_destination({'display_tab_id': 'trip-old', 'trip_id': 'trip-old'}, trip_names) == '합성 여행'
    assert display_destination({'recorded_display_tab_id': '', 'display_tab_id': 'trip-old'},
                               trip_names) == '합성 여행'
    assert display_destination({'recorded_display_tab_id': 'trip-unknown', 'approval_date': '2026-05-01'}) \
        == '2026년 2분기 기타비용'
