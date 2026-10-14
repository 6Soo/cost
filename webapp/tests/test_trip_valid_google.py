import json
from types import SimpleNamespace

import pytest

from app import google_authority
from webapp import card_flow


def _flow(trip):
    return SimpleNamespace(board=SimpleNamespace(get_trip=lambda tab_id: trip if tab_id == trip['tab_id'] else None))


def _trip(**changes):
    return dict({'tab_id': 'trip-a', 'display_key': '1005_경주', 'starts_on': '2026-10-05', 'ends_on': '2026-10-08',
                 'deleted': False, 'archived': False}, **changes)


@pytest.fixture
def google(tmp_path, monkeypatch):
    path = tmp_path / 'snapshot.json'
    monkeypatch.setenv('WEBLEDGER_GOOGLE_LEDGER_SNAPSHOT', str(path))
    monkeypatch.delenv('WEBLEDGER_TRIP_AUTHORITY', raising=False)
    card_flow._GOOGLE_PERIOD_CACHE.clear()

    def write(period, mapping=None):
        trips = [{'key': '1005_경주', 'period': period}]
        path.write_text(json.dumps({'schema': google_authority.SCHEMA, 'trips': trips}), encoding='utf-8')
        path.with_name('google-tab-mapping.json').write_text(
            json.dumps({'1005_경주': 'trip-a'} if mapping is None else mapping), encoding='utf-8')
    return write


def test_a_trip_whose_period_matches_its_linked_google_tab_is_verified(google):
    google({'starts_on': '2026-10-05', 'ends_on': '2026-10-08', 'flags': []})
    assert card_flow.CardFlow.trip_valid(_flow(_trip()), 'trip-a')


def test_a_period_that_differs_from_the_google_tab_is_not_verified(google):
    google({'starts_on': '2026-10-05', 'ends_on': '2026-10-09', 'flags': []})
    assert not card_flow.CardFlow.trip_valid(_flow(_trip()), 'trip-a')


def test_an_end_set_to_the_day_before_the_next_trip_verifies_a_trip(google):
    google({'starts_on': '2026-10-05', 'ends_on': '2026-10-08', 'flags': ['PERIOD_END_FROM_NEXT_TRIP']})
    assert card_flow.CardFlow.trip_valid(_flow(_trip()), 'trip-a')


def test_a_trip_without_any_end_is_not_verified(google):
    google({'starts_on': '2026-10-05', 'ends_on': None, 'flags': ['PERIOD_END_MISSING']})
    assert not card_flow.CardFlow.trip_valid(_flow(_trip(ends_on='')), 'trip-a')


def test_a_boundary_day_purchase_goes_to_the_trip_with_the_larger_net(google, monkeypatch):
    monkeypatch.setattr(card_flow, '_google_nets', lambda: {'trip-a': 100, 'trip-b': 900})
    trips = [_trip(tab_id='trip-a', starts_on='2026-09-24', ends_on='2026-09-27', destination='야마구치'),
             _trip(tab_id='trip-b', starts_on='2026-09-27', ends_on='2026-10-01', destination='북큐슈')]
    flow = SimpleNamespace(board=SimpleNamespace(list_trips=lambda: trips), trip_valid=lambda tab: True)
    monkeypatch.setattr('app.rules.merchant_country', lambda tx: 'JP')
    assert card_flow.CardFlow.retail_trip(flow, {'approval_date': '2026-09-27'}, 'JP') == 'trip-b'
    monkeypatch.setattr(card_flow, '_google_nets', lambda: {'trip-a': 900, 'trip-b': 100})
    del flow._retail_trips
    assert card_flow.CardFlow.retail_trip(flow, {'approval_date': '2026-09-27'}, 'JP') == 'trip-a'


def test_an_unlinked_or_deleted_trip_is_not_verified(google):
    google({'starts_on': '2026-10-05', 'ends_on': '2026-10-08', 'flags': []}, mapping={})
    assert not card_flow.CardFlow.trip_valid(_flow(_trip()), 'trip-a')
    google({'starts_on': '2026-10-05', 'ends_on': '2026-10-08', 'flags': []})
    assert not card_flow.CardFlow.trip_valid(_flow(_trip(deleted=True)), 'trip-a')


def _workbook(path, title):
    from openpyxl import Workbook
    book = Workbook()
    book.active.title = '0712_몽골'
    book.active['C2'] = title
    book.save(path)
    return path.read_bytes()


def _record(path, data):
    import hashlib
    from datetime import date
    return SimpleNamespace(source_locator=f'{path}#0712_몽골!C2', trip_code='0712_몽골',
                           source_sha256=hashlib.sha256(data).hexdigest(), event_year=2026,
                           starts_on=date(2026, 7, 12), ends_on=date(2026, 7, 16))


def test_the_original_title_alone_verifies_a_sheet_that_left_the_current_workbook(tmp_path):
    data = _workbook(tmp_path / 'original.xlsx', '2026년 7월 매출 확인자료_몽골_0712_0716')
    record = _record(tmp_path / 'original.xlsx', data)
    assert card_flow._unchanged_workbook_schedule(record, None, {})
    from openpyxl import Workbook
    other = tmp_path / 'current.xlsx'
    Workbook().save(other)
    assert not card_flow._unchanged_workbook_schedule(record, other.read_bytes(), {})


def test_an_original_title_with_another_period_does_not_verify(tmp_path):
    data = _workbook(tmp_path / 'original.xlsx', '2026년 7월 매출 확인자료_몽골_0712_0720')
    assert not card_flow._unchanged_workbook_schedule(_record(tmp_path / 'original.xlsx', data), None, {})
