import json
import sqlite3

import pytest

from webapp import ota_catalog
from webapp.ledger_store import LedgerStore


def test_catalog_build_computes_unchanged_trip_boundaries_once(data, monkeypatch):
    board, sources = data
    calls = []
    original = ota_catalog.handover_days
    monkeypatch.setattr(ota_catalog, 'handover_days', lambda trips: (calls.append(1), original(trips))[1])
    result = ota_catalog._build_index(board, sources)
    assert len(result['entries']) == 3
    assert len(calls) == 1


def test_stale_catalog_keeps_rows_labeled_while_refresh_is_requested(data, monkeypatch):
    board, sources = data
    expected = ota_catalog.catalog(board, {}, sources=sources)
    changes = board.conn.total_changes
    monkeypatch.setattr(ota_catalog, '_signature', lambda *_: 'changed-key')
    monkeypatch.setattr(ota_catalog, '_build_index', lambda *_: pytest.fail('list GET rebuilt inline'))
    requests = []
    monkeypatch.setattr(ota_catalog, '_start_rebuild', lambda *args: requests.append(args))
    current = ota_catalog.catalog(board, {}, sources=sources, allow_stale=True)
    assert requests and current['refresh_state'] != 'ready'
    assert current['rows'] == expected['rows']
    assert '이전 자료를 표시합니다' in ota_catalog.render_html(current, {})
    assert board.conn.total_changes == changes


def source_database(path):
    conn = sqlite3.connect(path)
    conn.executescript('''
        CREATE TABLE bookings(id INTEGER PRIMARY KEY, provider TEXT, booking_number TEXT,
          product_type TEXT, label TEXT, service_start_on TEXT, service_end_on TEXT, status TEXT);
        CREATE TABLE allocation_targets(id INTEGER PRIMARY KEY, target_type TEXT, code TEXT, name TEXT);
        CREATE TABLE booking_target_links(booking_id INTEGER, target_id INTEGER, link_status TEXT);
    ''')
    conn.executemany('INSERT INTO bookings VALUES (?,?,?,?,?,?,?,?)', [
        (1, 'agoda', 'BOOK-1', 'lodging', '합성 호텔', '2026-11-01', '2026-11-03', 'confirmed'),
        (2, 'agoda', 'BOOK-2', 'lodging', '합성 취소 호텔', '2026-10-01', '2026-10-02', 'cancelled'),
        (3, 'trip', 'BOOK-1', 'flight', '합성 항공', '', '', 'unknown'),
    ])
    conn.execute("INSERT INTO allocation_targets VALUES (1,'trip','trip-alpha','합성 여행')")
    conn.execute("INSERT INTO booking_target_links VALUES (1,1,'confirmed')")
    conn.execute("INSERT INTO booking_target_links VALUES (2,1,'proposed')")
    conn.commit()
    conn.close()


@pytest.fixture
def data(tmp_path, monkeypatch):
    monkeypatch.delenv('WEBLEDGER_REVIEW_CONFIG', raising=False)
    monkeypatch.delenv('WEBLEDGER_OTA_SOURCES_JSON', raising=False)
    board = LedgerStore(tmp_path / 'board.sqlite', seed_demo=False)
    path = tmp_path / 'ota.sqlite'
    source_database(path)
    sources = {'portal_databases': [path], 'mail_directories': [], 'missing': []}
    yield board, sources
    board.close()


def test_all_and_unassigned_include_cancelled_unpaid_and_do_not_write(data):
    board, sources = data
    before = board.conn.total_changes
    raw = sources['portal_databases'][0].read_bytes()
    result = ota_catalog.catalog(board, {}, sources=sources)
    assert result['total'] == 3 and result['unassigned_count'] == 2
    pending = ota_catalog.catalog(board, {'state': ['unassigned']}, sources=sources)
    assert {(r['provider'], r['booking_ref']) for r in pending['rows']} == {
        ('agoda', 'BOOK-2'), ('trip', 'BOOK-1')}
    assert sources['portal_databases'][0].read_bytes() == raw
    assert board.conn.total_changes == before


def test_inferred_link_displays_card_use_date_and_keeps_ota_payment_date_unknown(data, monkeypatch):
    board, sources = data
    entry = ota_catalog._entry(board, sources, 'agoda', 'BOOK-1')
    entry['card_matches'] = [{'transaction_id': 'synthetic', 'merchant': 'AGODA', 'paid_on': '',
                              'paid_amount_krw': 35000, 'inferred_link': True}]
    monkeypatch.setattr(ota_catalog, '_card_states', lambda *_: {
        'synthetic': {'day': '2026-10-01', 'decided': False, 'state': 'needs_review'}})
    before = board.conn.total_changes
    markup = ota_catalog.render_detail(board, entry, csrf='synthetic')
    assert '카드 이용일' in markup
    assert '추론 연결 · 아고다 결제일 미확인' in markup
    assert '2026-10-01' in markup and '35,000원' in markup
    assert entry['card_matches'][0]['paid_on'] == ''
    assert board.conn.total_changes == before


def test_core_ordered_pairs_reach_booking_screen_without_promoting_exact(data, monkeypatch):
    from types import SimpleNamespace
    from webapp import ota_payment_review
    board, sources = data
    core = {'events': [], 'transactions': [], 'results': []}
    for number in (1, 2):
        core['events'].append({'ota_event_id': str(number), 'provider': 'trip',
                               'booking_ref': f'BOOK-{number}', 'paid_on': '2026-09-23'})
        core['transactions'].append({'transaction_id': f'card-{number}', 'source_hash': f'hash-{number}',
            'merchant': 'TRIP.COM', 'amount_krw': 90121, 'transaction_direction': 'purchase'})
        core['results'].append({'ota_event_id': str(number), 'transaction_id': f'card-{number}',
            'status': 'MATCHED_AUTO', 'allocation_basis': 'auto_stable_order'})
    current = {'key': 'synthetic', 'generation': 1, 'data': core}
    state = {'fresh': True}
    monkeypatch.setattr(ota_payment_review, 'enabled', lambda: True)
    monkeypatch.setattr(ota_payment_review, 'snapshot_service', lambda _: SimpleNamespace(
        held=lambda: (current, state['fresh'])))
    flow = SimpleNamespace(board=board, _ota_report=lambda: {'matches': []},
                           _canonical_snapshot_report=lambda _: {'matches': []})
    before = board.conn.total_changes
    live, _, error = ota_catalog._card_matches(flow)
    assert not error and len(live) == 2
    assert live['trip', 'BOOK-1'][0]['transaction_id'] == 'card-1'
    assert live['trip', 'BOOK-2'][0]['transaction_id'] == 'card-2'
    assert all(not card['inferred_link'] for cards in live.values() for card in cards)
    entry = ota_catalog._entry(board, sources, 'trip', 'BOOK-1')
    entry['card_matches'] = live['trip', 'BOOK-1']
    markup = ota_catalog.render_detail(board, entry, csrf='synthetic')
    assert '90,121원' in markup
    assert '반복 거래 순서 배정 · 개별 결제 근거 미확인' in markup
    ready_signature = ota_catalog._signature(board, sources)
    state['fresh'] = False
    assert ota_catalog._card_matches(flow) == ({}, {}, True)
    assert ota_catalog._signature(board, sources) != ready_signature
    assert board.conn.total_changes == before


def test_core_display_preserves_occupied_cards_and_rejects_holds_or_conflicts():
    from copy import deepcopy
    old = [{'transaction_id': 'occupied', 'provider': 'agoda', 'booking_ref': 'OLD'}]
    data = {'events': [], 'transactions': [], 'results': []}
    for tid, status in [('occupied', 'MATCHED_AUTO'), ('partial', 'HOLD_PARTIAL_GROUP'),
                        ('changed', 'MATCHED_USER'), ('missing', 'MATCHED_AUTO'),
                        ('double', 'MATCHED_AUTO'), ('double', 'MATCHED_AUTO')]:
        eid = str(len(data['events']))
        data['events'].append({'ota_event_id': eid, 'provider': 'trip', 'booking_ref': 'NEW-' + eid})
        data['transactions'].append({'transaction_id': tid})
        data['results'].append({'ota_event_id': eid, 'status': status, 'transaction_id': tid,
                                'evidence_changed': tid == 'changed'})
    data['transactions'] = [c for c in data['transactions'] if c['transaction_id'] != 'missing']
    original = deepcopy(data)
    assert ota_catalog._with_core_card_matches(old, data) == old
    assert data == original


def test_exact_provider_identity_merging_and_conflicting_sources(data, tmp_path):
    board, sources = data
    second = tmp_path / 'second.sqlite'
    source_database(second)
    conn = sqlite3.connect(second)
    conn.execute("UPDATE bookings SET service_start_on='2026-12-01' WHERE id=1")
    conn.commit()
    conn.close()
    sources['portal_databases'].append(second)
    result = ota_catalog.catalog(board, {}, sources=sources)
    assert result['total'] == 3
    row = next(r for r in result['rows'] if r['provider'] == 'agoda' and r['booking_ref'] == 'BOOK-1')
    assert row['conflict'] and '2026-11-01' in row['period'] and '2026-12-01' in row['period']
    assert ota_catalog.catalog(board, {'month': ['2026-12']}, sources=sources)['total'] == 1


def test_search_month_sort_pagination_and_html_escape(data, monkeypatch):
    board, sources = data
    assert [r['starts_on'] for r in ota_catalog.catalog(board, {}, sources=sources)['rows']] == ['2026-10-01', '2026-11-01', '']
    assert [r['starts_on'] for r in ota_catalog.catalog(board, {'sort':['desc']}, sources=sources)['rows']] == ['2026-11-01', '2026-10-01', '']
    monkeypatch.setattr(ota_catalog, 'PAGE_SIZE', 1)
    query = {'sort': ['asc'], 'q': ['합성'], 'month': ['2026-11']}
    result = ota_catalog.catalog(board, query, sources=sources)
    assert result['total'] == 1 and result['rows'][0]['booking_ref'] == 'BOOK-1'
    result = ota_catalog.catalog(board, {'page': ['2'], 'sort': ['asc']}, sources=sources)
    assert result['page'] == 2 and len(result['rows']) == 1
    query = {'q': ["<script>alert('x')</script>"]}
    markup = ota_catalog.render_html(ota_catalog.catalog(board, query, sources=sources), query)
    assert query['q'][0] not in markup and '&lt;script&gt;' in markup
    assert '<h1>OTA 내역</h1>' in markup
    assert '전체 예약</a>' in markup and '여행 미배정</a>' in markup
    assert ota_catalog.catalog(board, {'provider': ["' OR 1=1"]}, sources=sources)['total'] == 0


def test_row_status_and_trip_badges_keep_text_without_combining_states(data):
    board, sources = data
    result = ota_catalog.catalog(board, {}, sources=sources)
    markup = ota_catalog.render_html(result, {})
    assert 'ota-badge trip ok' in markup and '합성 여행' in markup
    assert 'ota-badge trip idle' in markup and '여행 미배정' in markup
    assert 'ota-badge ok' in markup and '예약 확정' in markup
    assert 'ota-badge bad' in markup and '취소' in markup
    assert 'ota-badge idle' in markup and '미확인' in markup
    combined = {'rows': [{'provider': 'agoda', 'booking_ref': 'X1', 'label': '합성',
                          'period': '2026-11-01 ~ 2026-11-02', 'status': '예약 확정 / 취소',
                          'conflict': False, 'trips': []}],
                'all_count': 1, 'unassigned_count': 1, 'total': 1, 'page': 1,
                'pages': 1, 'months': [], 'providers': ['agoda'], 'warnings': []}
    combined_markup = ota_catalog.render_html(combined, {})
    assert '예약 확정 / 취소' in combined_markup
    assert combined_markup.count("<span class='ota-badge") == 1


def test_source_failure_is_visible_and_paths_are_private(data, tmp_path):
    board, sources = data
    broken = tmp_path / 'private-name.sqlite'
    broken.write_text('broken', encoding='utf-8')
    sources['portal_databases'].append(broken)
    result = ota_catalog.catalog(board, {}, sources=sources)
    assert result['total'] == 3 and result['warnings']
    markup = ota_catalog.render_html(result, {})
    assert str(broken) not in markup and '일부 자료를 읽지 못했습니다' in markup
    missing = tmp_path / 'not-created.sqlite'
    ota_catalog.catalog(board, {}, sources={'portal_databases': [missing], 'mail_directories': [], 'missing': []})
    assert not missing.exists()


def test_saved_board_link_is_provider_safe_and_current(data):
    board, sources = data
    board.conn.execute("INSERT INTO trip_tabs(tab_id,display_key) VALUES ('trip-board','합성 현재 여행')")
    for row_id, ref in [('one', 'BOOK-2'), ('ambiguous', 'BOOK-1')]:
        payload = json.dumps({'reservation_no': ref})
        board.conn.execute('INSERT INTO board_rows VALUES (?,?,?,?,?)',
                           (row_id, 'expense', 'trip-board', 1, payload))
    board.conn.commit()
    result = ota_catalog.catalog(board, {}, sources=sources)
    rows = {(r['provider'], r['booking_ref']): r for r in result['rows']}
    assert rows['agoda', 'BOOK-2']['trips'][0]['name'] == '합성 현재 여행'
    assert rows['trip', 'BOOK-1']['trips'] == []
    board.conn.execute("UPDATE board_rows SET display_tab_id='unclassified' WHERE row_id='one'")
    board.conn.commit()
    result = ota_catalog.catalog(board, {'state': ['unassigned']}, sources=sources)
    assert any(r['booking_ref'] == 'BOOK-2' for r in result['rows'])


def test_mail_bookings_are_merged_without_creating_payment_or_reservation_rows(data, tmp_path):
    from tests.card_pipeline.test_booking_mail import message
    board, sources = data
    maildir = tmp_path / 'mail'
    maildir.mkdir()
    mail = message('예약번호: BOOK12345\n총 금액 30,000원',
                   subject='[Trip.com] 결제 완료 안내', identity='synthetic-mail')
    (maildir / 'gmail-test.json').write_text(json.dumps({'responses': [mail]}), encoding='utf-8')
    sources['mail_directories'] = [maildir]
    before = board.conn.total_changes
    result = ota_catalog.catalog(board, {}, sources=sources)
    assert ('trip', 'BOOK12345') in {(r['provider'], r['booking_ref']) for r in result['rows']}
    assert result['all_count'] == 4 and not result['warnings']
    assert board.conn.total_changes == before


def test_multiple_mail_directories_reuse_one_parse_across_filter_requests(data, tmp_path, monkeypatch):
    from app import ota_payments
    from tests.card_pipeline.test_booking_mail import message
    board, sources = data
    mail = message('예약번호: BOOK12345\n총 금액 30,000원',
                   subject='[Trip.com] 결제 완료 안내', identity='shared-synthetic-mail')
    directories = [tmp_path / 'one', tmp_path / 'two']
    for directory in directories:
        directory.mkdir()
        (directory / 'gmail-test.json').write_text(json.dumps({'responses': [mail]}), encoding='utf-8')
    sources['mail_directories'] = directories
    original = ota_payments._parse_mail_events
    parses = []
    def parse(paths):
        parses.append(paths)
        return original(paths)
    monkeypatch.setattr(ota_payments, '_MAIL_EVENT_MEMO', {})
    monkeypatch.setattr(ota_payments, '_parse_mail_events', parse)
    def no_payment_reconciliation(*args):
        raise AssertionError('예약 목록에서 결제 이벤트를 재대사하면 안 됩니다')
    monkeypatch.setattr(ota_payments, '_merge_proven_duplicate_payments', no_payment_reconciliation)
    first = ota_catalog.catalog(board, {}, sources=sources)
    second = ota_catalog.catalog(board, {'state': ['unassigned']}, sources=sources)
    assert first['all_count'] == second['all_count'] == 4
    assert len(parses) == 1


def test_card_review_workbook_is_not_an_ota_database(data, tmp_path, monkeypatch):
    import hashlib
    board, sources = data
    from tests.card_pipeline.fixtures import make_xlsx, domestic_row
    snapshot = tmp_path / 'card-review.xlsx'
    snapshot.write_bytes(make_xlsx([domestic_row(merchant='합성 상점', amount=1000, approval='SYN-OTA')]))
    config = tmp_path / 'review.json'
    config.write_text(json.dumps({
        'snapshot_path': str(snapshot), 'snapshot_sha256': hashlib.sha256(snapshot.read_bytes()).hexdigest(),
        'review_path': str(tmp_path / 'review.csv'), 'review_sha256': 'a' * 64,
        'master_path': str(tmp_path / 'master.csv'), 'master_sha256': 'a' * 64,
        'decisions_db_path': str(tmp_path / 'choices.sqlite'),
    }), encoding='utf-8')
    monkeypatch.setenv('WEBLEDGER_REVIEW_CONFIG', str(config))
    result = ota_catalog.catalog(board, {}, sources=sources)
    assert result['all_count'] == 3 and result['warnings'] == []
    assert str(snapshot) not in json.dumps(result)
