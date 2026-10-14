"""사용자 확정 규칙(AGENTS.md)을 지킨다. 이 파일의 테스트를 바꾸려면 사용자의 명시 지시가 필요하다."""
from types import SimpleNamespace

from app import google_authority
from app.reconciliation import card_use_date, ledger_date_for_booking, open_trip_end, stay_trip


def test_owner_rule_a_trip_without_an_end_ends_the_day_before_the_next_trip():
    assert open_trip_end('2026-09-15', '2026-09-16') == '2026-09-15'
    assert open_trip_end('2026-08-30', '2026-09-03') == '2026-09-02'
    assert open_trip_end('2027-03-02', None) is None


def test_owner_rule_the_google_view_closes_open_ends_with_the_next_trip():
    view = [{'key': '0830_변산', 'period': {'starts_on': '2026-08-30', 'ends_on': None, 'flags': ['PERIOD_END_MISSING']}},
            {'key': '0903_양평', 'period': {'starts_on': '2026-09-03', 'ends_on': '2026-09-08', 'flags': []}}]
    google_authority._close_open_ends(view)
    assert view[0]['period']['ends_on'] == '2026-09-02'


def test_owner_rule_an_end_from_the_next_trip_is_a_verified_trip_period(tmp_path, monkeypatch):
    import json
    from webapp import card_flow
    path = tmp_path / 'snapshot.json'
    path.write_text(json.dumps({'schema': google_authority.SCHEMA, 'trips': [{'key': '0830_변산', 'period': {
        'starts_on': '2026-08-30', 'ends_on': '2026-09-02', 'flags': ['PERIOD_END_FROM_NEXT_TRIP']}}]}), encoding='utf-8')
    path.with_name('google-tab-mapping.json').write_text(json.dumps({'0830_변산': 'trip-a'}), encoding='utf-8')
    monkeypatch.setenv('WEBLEDGER_GOOGLE_LEDGER_SNAPSHOT', str(path))
    card_flow._GOOGLE_PERIOD_CACHE.clear()
    trip = {'tab_id': 'trip-a', 'starts_on': '2026-08-30', 'ends_on': '2026-09-02', 'deleted': False, 'archived': False}
    flow = SimpleNamespace(board=SimpleNamespace(get_trip=lambda tab: trip))
    assert card_flow.CardFlow.trip_valid(flow, 'trip-a')


def test_owner_rule_an_end_from_the_next_trip_follows_a_new_next_trip_but_not_an_owner_edit(tmp_path):
    from webapp import google_ledger_page as page
    from webapp.ledger_store import LedgerStore
    board = LedgerStore(tmp_path / 'board.sqlite', seed_demo=False)
    def snap(end):
        return {'trips': [{'key': '0830_변산', 'kind': 'trip', 'period': {
            'year': 2026, 'starts_on': '2026-08-30', 'ends_on': end, 'destination': '변산',
            'flags': ['PERIOD_END_FROM_NEXT_TRIP']}}]}
    page.import_trips(board, snap('2026-09-02'))
    tab = board.list_trips(include_archived=True)[0]
    assert page.import_trips(board, snap('2026-08-31')) == {'end_set': 1}
    tab = board.get_trip(tab['tab_id'])
    assert tab['ends_on'] == '2026-08-31'
    board.save_trip_meta(tab_id=tab['tab_id'], expected_revision=tab['revision'], client_request_id='owner-end',
                         ends_on='2026-09-01', actor='owner')
    assert page.import_trips(board, snap('2026-09-02')) == {'existing': 1}
    assert board.get_trip(tab['tab_id'])['ends_on'] == '2026-09-01'


def test_owner_rule_a_card_row_uses_its_use_date_never_the_posting_date():
    assert card_use_date({'approval_date': '2026-05-07', 'posting_date': '2026-05-09'}) == '2026-05-07'


def test_owner_rule_an_ota_booking_is_dated_by_its_service_date_and_payment_only_as_fallback():
    assert ledger_date_for_booking('2026-09-28', '2026-09-17') == '2026-09-28'
    assert ledger_date_for_booking('', '2026-09-17') == '2026-09-17'
    assert ledger_date_for_booking(None, None) == ''


def test_owner_rule_a_lodging_before_a_trip_with_no_trip_on_its_nights_prepares_for_the_nearest_next_trip():
    trips = [{'tab_id': 'trip-mongolia', 'starts_on': '2026-07-12', 'ends_on': '2026-07-16'},
             {'tab_id': 'trip-golden', 'starts_on': '2026-07-21', 'ends_on': '2026-07-21'}]
    assert stay_trip(trips, '2026-07-18', '2026-07-19')['tab_id'] == 'trip-golden'
    assert stay_trip(trips, '2026-07-18', '2026-07-19', service=True) is None
