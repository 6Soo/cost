"""Synthetic-only quarter pack integration and read-only boundary tests."""
import json
import sqlite3

import pytest

from tools.quarter_review import pack
from tools.quarter_review import priority


def trip(key='q3', start='2026-06-30'):
    return dict(tab_id=key, display_key=key, starts_on=start, ends_on='2026-07-05', deleted=0, tab_kind='trip')


def expense(key, amount, tab='q3', source='rule', item='식비', **extra):
    return dict(transaction_id=key, amount_krw=amount, trip_id=tab, display_tab_id=tab,
                approval_date='2026-04-10', posting_date='', transaction_direction='purchase' if amount > 0 else 'refund',
                classification_source=source, classification_state='classified', classification_basis='',
                item=item, merchant='synthetic', decided_at=None, **extra)


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


def test_pack_missing_income_and_net_refund(tmp_path):
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


def test_synthetic_db_pack_aggregation(tmp_path):
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


def test_priority_matches_review_contract_and_drops_reasonless_rows():
    rows = [
        dict(row_id='plain', amount_krw=999999, source='rule', item='식비'),
        dict(row_id='generic', amount_krw=100000, source='rule', item='기타경비'),
        dict(row_id='inferred', amount_krw=200000, source='inference', item='식비'),
        dict(row_id='manual', amount_krw=900000, source='user_decision', item='기타경비'),
    ]
    result = priority.prioritize(rows)
    assert [row['row_id'] for row in result] == ['inferred', 'generic']
    assert result[0]['review_reasons'] == ['추론 귀속']
    assert result[0]['review_score'] == 30  # 20 + two 100,000-won steps


def test_pack_has_reason_counts_and_no_owner_review_sheet(tmp_path):
    d = data([expense(f'a{i}', 100000, source='inference') for i in range(55)] +
             [expense('plain', 999999, source='rule')])
    summary = pack.build_pack(d, 2026, 3, tmp_path, {'q3': 1})
    assert summary['review_rows'] == 55 and summary['reasons']['추론 귀속'] == 55
    import openpyxl
    book = openpyxl.load_workbook(tmp_path / 'review-pack.xlsx', read_only=True)
    # Owner decision 2026-11-13: the workbook carries results only; the per-row
    # review list is the AI reviewer's input and stays in review-list.csv.
    assert book.sheetnames[0] == '여행별 손익'
    assert '먼저 볼 50건' not in book.sheetnames
    import csv
    with (tmp_path / 'review-list.csv').open(encoding='utf-8-sig', newline='') as f:
        assert len(list(csv.reader(f))) == 56


def test_notes_explain_counts_without_guessing_unknown_sources(tmp_path):
    d = data([expense('a', 10, source='ai_inference'),
              expense('b', -5, source='refund_original'),
              expense('c', 1, conflict_reason='synthetic'),
              expense('pending', 1, tab='', source='user_decision')])
    d['transactions'][-1]['approval_date'] = '2026-07-01'
    d['board_projected'] = [dict(row_id='card-b', row_kind='expense', display_tab_id='refunds',
                                 item='식비', amount_krw=-5),
                            dict(row_id='man-unknown', row_kind='expense', display_tab_id='q3',
                                 item='식비', amount_krw=7)]
    summary = pack.build_pack(d, 2026, 3, tmp_path, income_reasons={'q3': '비표준 양식'},
                              google_at='2026-11-12', basis_note='준비 비용 귀속 폐지 반영 전')
    assert summary['diagnostics']['unknown_sources'] == {'비카드 수기 지출 출처 기록 없음': 1}
    assert summary['diagnostics']['projection'] == {'환불 건(화면은 취소·환불 묶음)': 1}
    assert summary['diagnostics']['excluded'] == {'duplicate': 0, 'conflict': 1, 'invalid': 0, 'company_excluded': 0}
    notes = (tmp_path / 'notes.md').read_text(encoding='utf-8')
    assert len(notes.splitlines()) == 10
    for text in ('AI 판정 1건', '출처 미확인 1건', '수동 출처·항목은 있으나 여행 미배정 1건',
                 '원본 충돌 1건', '비표준 양식', 'AI 검수자', '반영 전', 'Google 수입 조회 2026-11-12'):
        assert text in notes
    assert summary['service_date_unknown'] is None
    assert '이용일 미확인' not in summary['reasons']


def test_trip_totals_keep_missing_income_blank_and_escape_text():
    import csv, io
    from tools.quarter_review.render import render_trip_summary_csv
    values = [dict(trip='=unsafe', income=100, expense=20, profit=80, expense_count=1, review_count=1),
              dict(trip='missing', income=None, expense=-5, profit=None, expense_count=2, review_count=0)]
    rows = list(csv.reader(io.StringIO(render_trip_summary_csv(values))))
    assert rows[-1][:8] == ['합계', '', '', '', '15', '', '3', '1']
    assert rows[1][0] != '=unsafe'
    complete = list(csv.reader(io.StringIO(render_trip_summary_csv(values[:1]))))
    assert complete[-1][3:6] == ['100', '20', '80']


def test_priority_ordering_tiebreak_and_amount_bonus_cap():
    rows = [
        dict(row_id='b', amount_krw=200000, source='inference', item='식비'),
        dict(row_id='a', amount_krw=200000, source='inference', item='식비'),
        dict(row_id='c', amount_krw=-900000, source='inference', item='식비'),
        dict(row_id='d', amount_krw=100000, source='ai_inference', item='식비'),
    ]
    result = priority.prioritize(rows)
    assert [r['row_id'] for r in result] == ['c', 'd', 'a', 'b']
    assert result[0]['review_score'] == 60  # 20 + capped 40 (9 steps would be 45)


def test_priority_uncertainty_and_recent_auto_change_reasons():
    uncertain = dict(row_id='u', amount_krw=0, source='rule', item='식비',
                     classification_basis='AUTO_TRIP_INFERRED · 불확실성: 예약 근거 부족')
    recent = dict(row_id='r', amount_krw=0, source='rule', item='식비', recent_auto_change=True)
    both = dict(row_id='b', amount_krw=0, source='ai_inference', item='식비', recent_auto_change=True)
    assert priority.review_reasons(uncertain) == ['불확실성 기록']
    assert priority.review_score(uncertain) == 10
    assert priority.review_reasons(recent) == ['최근 자동 변경']
    assert priority.review_score(recent) == 35
    assert priority.review_reasons(both) == ['최근 자동 변경', 'AI 판정']
    assert priority.review_score(both) == 65


def test_trip_summary_counts_reasons_per_trip(tmp_path):
    d = data([expense('a', 100000, source='ai_inference'),
              expense('b', 100000, source='inference'),
              expense('g', 100000, source='rule', item='기타경비'),
              expense('plain', 100000, source='rule'),
              expense('m', 100000, source='user_decision')])
    pack.build_pack(d, 2026, 3, tmp_path, {'q3': 1})
    import csv
    with (tmp_path / 'trips.csv').open(encoding='utf-8-sig', newline='') as f:
        rows = list(csv.reader(f))
    assert rows[1][6] == '5'  # 지출건수에는 수동·사유 없는 행도 포함
    assert rows[1][7] == '3'  # 검수필요건수는 사유 있는 행만
    assert rows[1][8] == 'AI 판정 1건 · 추론 귀속 1건 · 포괄 항목 1건'


def test_quarter_sheet_name_and_recent_cutoff_follow_arguments(tmp_path):
    q4 = dict(tab_id='q4', display_key='q4', starts_on='2026-10-01', ends_on='2026-10-05', deleted=0, tab_kind='trip')
    d = dict(transactions=[expense('a', 100000, tab='q4', source='ai_inference')],
             trip_tabs=[q4], board_projected=[], board_rows=[],
             change_log=[dict(at='2026-11-11T00:00:00Z', kind='card.classification_corrected', subject='a',
                              detail_json=json.dumps({'after': {'classification_source': 'ai_inference'}}))],
             manual_ids=set(), read_at='2026-11-13T00:00:00+09:00')
    summary = pack.build_pack(d, 2026, 4, tmp_path / 'default')
    assert summary['reasons'].get('최근 자동 변경') == 1
    import openpyxl
    book = openpyxl.load_workbook(tmp_path / 'default/review-pack.xlsx', read_only=True)
    assert '4분기 기타비용' in book.sheetnames
    later = pack.build_pack(d, 2026, 4, tmp_path / 'later', recent_since='2026-11-12')
    assert '최근 자동 변경' not in later['reasons']


def test_trip_sheet_notes_quarter_other_review_gap():
    import csv, io
    from tools.quarter_review.render import render_trip_summary_csv
    values = [dict(trip='t', income=100, expense=20, profit=80, expense_count=1, review_count=3)]
    rows = list(csv.reader(io.StringIO(render_trip_summary_csv(values, full_review_count=5))))
    assert rows[-2][0] == '합계' and rows[-2][7] == '3'
    assert rows[-1][0] == '안내'
    assert '2건은 분기 기타비용' in rows[-1][8] and '5건' in rows[-1][8]
    plain = list(csv.reader(io.StringIO(render_trip_summary_csv(values))))
    assert plain[-1][0] == '합계'
