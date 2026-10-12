import json
import sqlite3

import pytest

from webapp import ota_catalog
from webapp.ledger_store import LedgerStore


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
    monkeypatch.setattr(ota_catalog, 'PAGE_SIZE', 1)
    query = {'sort': ['asc'], 'q': ['합성'], 'month': ['2026-11']}
    result = ota_catalog.catalog(board, query, sources=sources)
    assert result['total'] == 1 and result['rows'][0]['booking_ref'] == 'BOOK-1'
    result = ota_catalog.catalog(board, {'page': ['2'], 'sort': ['asc']}, sources=sources)
    assert result['page'] == 2 and len(result['rows']) == 1
    query = {'q': ["<script>alert('x')</script>"]}
    markup = ota_catalog.render_html(ota_catalog.catalog(board, query, sources=sources), query)
    assert query['q'][0] not in markup and '&lt;script&gt;' in markup
    assert 'OTA 전체 내역' in markup and 'OTA 미배정 내역' in markup
    assert ota_catalog.catalog(board, {'provider': ["' OR 1=1"]}, sources=sources)['total'] == 0


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
