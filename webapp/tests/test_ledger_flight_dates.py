"""Synthetic reservation dates: display-only, no payment or source writes."""
from copy import deepcopy

import pytest

from webapp import ledger_design as design
from webapp.read_scope import scoped


@pytest.fixture
def evidence(monkeypatch):
    found = dict(source_digests=['synthetic'], cancellation_status='NONE',
                 legs=[{'departure_on': '2026-06-30'}, {'departure_on': '2026-07-04'}])
    manual = set()
    monkeypatch.setattr(design, '_load_flight_dates', lambda: ({'SYN-REF': found}, manual))
    return found, manual


def row(**values):
    return dict(dict(row_id='card-syn', row_kind='expense', item='항공료',
                     reservation_no='SYN-REF', service_period='', occurred_on='2026-05-29',
                     amount_krw=1200, description='Synthetic airfare', source_merchant='Synthetic'), **values)


def test_departure_dates_reach_desktop_and_mobile_without_changing_payment_date(evidence):
    value = row()
    before = deepcopy(value)
    @scoped
    def render():
        return (design._table_html([value], kind='expense', selected='', unclassified=False),
                design._mobile_html([], [value], selected='', unclassified=False))
    desktop, mobile = render()
    assert '06.30 · 07.04' in desktop and '06.30 · 07.04' in mobile
    assert '2026-05-29' in desktop and '2026-05-29' in mobile
    assert '항공 이용일: 2026-06-30 · 2026-07-04' in desktop
    assert '박' not in design._flight_date_labels(value)[0]
    assert value == before


@pytest.mark.parametrize('flag', ['conflict', 'evidence_missing', 'evidence_changed',
                                  'period_conflict', 'service_period_conflict'])
def test_unsafe_evidence_does_not_supply_dates(evidence, flag):
    evidence[0][flag] = True
    assert design._flight_date_labels(row())[0] == '이용일 미확인'


@pytest.mark.parametrize('status', ['CANCELLED', 'PARTIAL', 'UNKNOWN', None])
def test_cancelled_or_unknown_status_is_not_active_itinerary(evidence, status):
    evidence[0]['cancellation_status'] = status
    assert design._flight_date_labels(row())[0] == '이용일 미확인'


@pytest.mark.parametrize('legs', [[], [{'departure_on': ''}], [{'departure_on': '2026-02-30'}]])
def test_missing_or_invalid_legs_are_not_replaced_by_card_date(evidence, legs):
    evidence[0]['legs'] = legs
    assert design._flight_date_labels(row())[0] == '이용일 미확인'


def test_description_number_is_not_a_booking_relationship(evidence):
    assert design._flight_date_labels(row(reservation_no='', description='예약 SYN-REF'))[0] == '이용일 미확인'


def test_manual_period_and_empty_override_win(evidence):
    evidence[1].add('card-syn')
    assert design._flight_date_labels(row())[0] == '이용일 미확인'
    assert design._flight_date_labels(row(service_period='2026-08-01~2026-08-03'))[0] == '08.01–08.03'
    assert design._flight_date_labels(row(service_period='bad'))[0] == '이용일 미확인'


def test_one_way_and_cross_year_dates_do_not_imply_hotel_nights(evidence):
    evidence[0]['legs'] = [{'departure_on': '2026-12-31'}, {'departure_on': '2027-01-02'}]
    assert design._flight_date_labels(row())[0] == '26.12.31 · 27.01.02'
    evidence[0]['legs'] = [{'departure_on': '2026-12-31'}] * 2
    assert design._flight_date_labels(row())[0] == '12.31'


def test_loader_uses_fresh_snapshot_only_and_never_reconciles(monkeypatch):
    from types import SimpleNamespace
    import sqlite3
    from threading import RLock
    from webapp import ota_payment_review
    conn = sqlite3.connect(':memory:')
    conn.execute('CREATE TABLE board_manual_overrides(row_id TEXT, field TEXT)')
    conn.execute("INSERT INTO board_manual_overrides VALUES ('manual','service_period')")
    state = {'fresh': False}
    service = SimpleNamespace(display_context=lambda: ({'data': {'passengers': {'SYN': {}}}}, state))
    store = SimpleNamespace(conn=conn, _lock=RLock(), _flight_booking_service=service)
    monkeypatch.setattr(design.board, '_active_store', lambda: store)
    monkeypatch.setattr(ota_payment_review, 'enabled', lambda: True)
    changes = conn.total_changes
    assert design._load_flight_dates() == ({}, {'manual'})
    state['fresh'] = True
    assert design._load_flight_dates() == ({'SYN': {}}, {'manual'})
    assert conn.total_changes == changes
    conn.close()
