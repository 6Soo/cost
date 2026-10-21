"""오염된 레거시 공급자 이름은 원문을 보존하되 예약 판단에서 제외한다."""

import sqlite3
import threading

from webapp import ota_catalog


def test_legacy_mail_title_provider_cannot_duplicate_trip_or_override_its_stay(tmp_path, monkeypatch):
    db_path = tmp_path / 'unified.sqlite'
    db_path.touch()
    mail_path = tmp_path / 'mail'
    mail_path.mkdir()

    corrupted = [
        {'provider': 'Gmail Trip.com 예약 안내', 'booking_number': 'same-booking',
         'label': 'old candidate', 'product_type': 'lodging',
         'service_start_on': '2026-06-01', 'service_end_on': '2026-06-05',
         'status': 'confirmed', 'trips': []},
        {'provider': 'Gmail Trip.com 카드 사용', 'booking_number': 'orphan',
         'label': 'old unverified candidate', 'product_type': 'lodging',
         'service_start_on': '2026-07-01', 'service_end_on': '2026-07-05',
         'status': 'confirmed', 'trips': []},
    ]
    monkeypatch.setattr(ota_catalog, '_read_database', lambda path: corrupted)
    monkeypatch.setattr(ota_catalog.ota_payments, '_mail_events', lambda *a, **k: [
        {'provider': 'trip', 'booking_ref': 'same-booking', 'item': '숙박비',
         'service_period': {'starts_on': '2026-06-01', 'ends_on': '2026-06-03'},
         'reservation_status': 'confirmed'},
    ])

    class Board:
        _lock = threading.RLock()
        conn = sqlite3.connect(':memory:')

    Board.conn.executescript('CREATE TABLE board_rows(display_tab_id TEXT, row_kind TEXT, payload_json TEXT);'
                             'CREATE TABLE trip_tabs(tab_id TEXT, display_key TEXT, deleted INTEGER);')
    try:
        warnings = []
        rows = ota_catalog._rows_from_sources(Board(), {
            'portal_databases': [db_path], 'mail_directories': [mail_path]
        }, warnings)
        assert set(rows) == {('trip', 'same-booking')}
        assert rows[('trip', 'same-booking')]['periods'] == {('2026-06-01', '2026-06-03')}
        assert 'old candidate' not in rows[('trip', 'same-booking')]['labels']
        assert len(warnings) == 1 and '2건' in warnings[0]
    finally:
        Board.conn.close()
