"""Synthetic-only quarter pack integration and read-only boundary tests."""
import json
import sqlite3

import pytest

from tools.quarter_review import pack


def trip(key='q3', start='2026-06-30'):
    return dict(tab_id=key, display_key=key, starts_on=start, ends_on='2026-07-05', deleted=0, tab_kind='trip')


def expense(key, amount, tab='q3', source='rule', **extra):
    return dict(transaction_id=key, amount_krw=amount, trip_id=tab, display_tab_id=tab,
                approval_date='2026-04-10', posting_date='', transaction_direction='purchase' if amount > 0 else 'refund',
                classification_source=source, classification_state='classified', classification_basis='',
                item='식비', merchant='synthetic', decided_at=None, **extra)


def data(rows):
    return dict(transactions=rows, trip_tabs=[trip(), trip('q2', '2026-06-29')],
                board_projected=[], board_rows=[], change_log=[], manual_ids=set(), read_at='2026-11-12T00:00:00+09:00')


def test_boundary_prepayment_refund_and_manual():
    d = data([expense('a', 300000), expense('b', -100000), expense('c', 100, source='user_decision'),
              expense('d', 200, tab='q2'), expense('e', 5, tab='quarter:2026:3')])
    trips, rows, excluded = pack.prepare_rows(d, 2026, 3)
    assert [t['tab_id'] for t in trips] == ['q3']
    assert sum(r['amount_krw'] for r in rows if r['display_tab_id'] == 'q3') == 200100
    assert len(rows) == 4
    assert next(r for r in rows if r['transaction_id'] == 'c')['manual']
    assert excluded['other_trip'] == 1


def test_recent_history_manual_excluded_and_source_labels():
    d = data([expense('a', 100, source='ai_inference'), expense('b', 200, source='manual')])
    d['change_log'] = [dict(at='2026-11-11T00:00:00Z', kind='card.classification_corrected', subject=k,
                            detail_json=json.dumps({'after': {'classification_source': s}}))
                       for k, s in [('a', 'ai_inference'), ('b', 'manual')]]
    _, rows, _ = pack.prepare_rows(d, 2026, 3)
    assert rows[0]['recent_auto_change'] is True
    assert rows[1]['recent_auto_change'] is False
    assert [r['source_label'] for r in rows] == ['AI 판정', '수동']


def test_board_manual_destination_wins_without_changing_card_amount():
    d = data([expense('a', 100, tab='q2')])
    d['board_projected'] = [dict(row_id='card-a', row_kind='expense', display_tab_id='q3', item='식비', amount_krw=999)]
    d['manual_ids'] = {'card-a'}
    d['manual_fields'] = {'card-a': {'display_tab_id'}}
    _, rows, _ = pack.prepare_rows(d, 2026, 3)
    assert len(rows) == 1 and rows[0]['display_tab_id'] == 'q3'
    assert rows[0]['amount_krw'] == 100 and rows[0]['manual']


def test_unassigned_normal_metric_uses_dates_but_excludes_closed_trip():
    d = data([expense('a', 1, tab=''), expense('b', 1, tab='q2'),
              expense('c', 1, tab='', duplicate_of='a')])
    for r in d['transactions']:
        r['approval_date'] = '2026-07-20'
    _, rows, _ = pack.prepare_rows(d, 2026, 3)
    assert pack.undecided_normal(d, 2026, 3, rows) == 1


def test_company_exclusion_is_source_bound():
    d = data([expense('a', 100, source_hash='old'), expense('b', 200, source_hash='new')])
    d['company_exclusions'] = {('a', 'old'), ('b', 'old')}
    _, rows, excluded = pack.prepare_rows(d, 2026, 3)
    assert [r['transaction_id'] for r in rows] == ['b']
    assert excluded['company_excluded'] == 1


def test_pack_missing_income_and_net_refund(tmp_path, monkeypatch):
    from tools.p2_batch import scope
    monkeypatch.setattr(scope, 'service_warnings', lambda d, r: ({'count': 0}, []))
    d = data([expense('a', 300000, source='ai_inference'), expense('b', -100000), expense('c', 20, source='manual')])
    summary = pack.build_pack(d, 2026, 3, tmp_path)
    assert summary['trips'] == 1 and summary['income_trips'] == 0
    import csv
    with (tmp_path / 'trips.csv').open(encoding='utf-8-sig', newline='') as f:
        rows = list(csv.reader(f))
    assert rows[1][3:6] == ['', '200020', '']
    assert all((tmp_path / name).read_bytes().startswith(b'\xef\xbb\xbf') for name in
               ['trips.csv', 'review-list.csv', 'quarter-other.csv', 'sources.csv'])
    with (tmp_path / 'review-list.csv').open(encoding='utf-8-sig', newline='') as f:
        review = list(csv.reader(f))
    assert all(r[6] != '수동' for r in review[1:])
    assert '수입' in (tmp_path / 'notes.md').read_text(encoding='utf-8')


def test_read_database_is_mode_ro_and_query_only(tmp_path, monkeypatch):
    path = tmp_path / 'synthetic.sqlite'
    with sqlite3.connect(path) as conn:
        conn.executescript('CREATE TABLE transactions(transaction_id TEXT);'
                           'CREATE TABLE trip_tabs(tab_id TEXT);'
                           'CREATE TABLE board_rows(row_id TEXT,row_kind TEXT,display_tab_id TEXT,payload_json TEXT);'
                           'CREATE TABLE change_log(at TEXT,kind TEXT,subject TEXT,detail_json TEXT);')
    before = path.read_bytes()
    connect = sqlite3.connect
    def checked(database, **kwargs):
        assert database.endswith('?mode=ro') and kwargs['uri'] is True
        conn = connect(database, **kwargs)
        with pytest.raises(sqlite3.OperationalError):
            conn.execute('CREATE TABLE forbidden(x)')
        return conn
    monkeypatch.setattr(pack.sqlite3, 'connect', checked)
    assert pack.read_database(path)['transactions'] == []
    assert path.read_bytes() == before


def test_income_missing_is_never_zero(tmp_path):
    values, reasons, stamp = pack.load_income(tmp_path, [trip()])
    assert values == {} and 'q3' in reasons and stamp == ''


@pytest.mark.parametrize('expected,readable', [(100, True), (200, False)])
def test_google_income_validated_against_row_sum(tmp_path, monkeypatch, expected, readable):
    from app import google_authority
    from webapp import google_ledger_page as google
    snapshot = dict(synced_at='2026-11-12', sources={'main': {'status': 'ok', 'stale': False}},
                    trips=[dict(key='synthetic', chosen_source='main', income_total=expected,
                                copies={'main': {'income': {'verified': True}}}, review=[])])
    monkeypatch.setattr(google_authority, 'load_consistent', lambda *a: (snapshot, {}))
    monkeypatch.setattr(google, 'snapshot_for_display', lambda value: value)
    monkeypatch.setattr(google, 'owner_payload', lambda value, choices: value)
    monkeypatch.setattr(google, 'load_mapping', lambda path: {'synthetic': 'q3'})
    monkeypatch.setattr(google, 'load_choices', lambda path: {})
    monkeypatch.setattr(google, 'owner_rows', lambda *a: {'income': [dict(row=8, amount=100, name='', nickname='')]})
    result, reasons, _ = pack.load_income(tmp_path, [trip()])
    assert result == ({'q3': 100} if readable else {})
    assert ('q3' in reasons) is not readable


def test_synthetic_db_pack_aggregation(tmp_path, monkeypatch):
    from tools.p2_batch import scope
    monkeypatch.setattr(scope, 'service_warnings', lambda d, r: ({'count': 0}, []))
    path = tmp_path / 'synthetic.sqlite'
    with sqlite3.connect(path) as conn:
        for table, rows in [('transactions', [expense('a', 100), expense('b', -40), expense('c', 3, source='manual')]),
                            ('trip_tabs', [trip()])]:
            columns = rows[0]
            definitions = ','.join(k + (' INTEGER' if isinstance(v, int) else ' TEXT') for k, v in columns.items())
            conn.execute('CREATE TABLE ' + table + '(' + definitions + ')')
            conn.executemany('INSERT INTO ' + table + ' VALUES (' + ','.join('?' for _ in columns) + ')',
                             [tuple(row.values()) for row in rows])
        conn.executescript('CREATE TABLE board_rows(row_id TEXT,row_kind TEXT,display_tab_id TEXT,payload_json TEXT);'
                           'CREATE TABLE change_log(at TEXT,kind TEXT,subject TEXT,detail_json TEXT);')
    before = path.read_bytes()
    result = pack.build_pack(pack.read_database(path), 2026, 3, tmp_path / 'out', {'q3': 200})
    assert result['expense_rows'] == 3 and result['income_trips'] == 1
    import csv
    with (tmp_path / 'out/trips.csv').open(encoding='utf-8-sig', newline='') as f:
        values = list(csv.reader(f))[1]
    assert values[3:6] == ['200', '63', '137']
    assert path.read_bytes() == before
