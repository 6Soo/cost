import pytest

from webapp import google_ledger_page as page


def trip(tab='a', name='1005_Synthetic', year=2026):
    return {'tab_id': tab, 'display_key': name, 'event_year': year,
            'starts_on': f'{year}-10-05', 'deleted': False, 'tab_kind': 'trip'}


def snapshot(*names):
    return {'trips': [{'key': name} for name in names]}


def test_auto_links_unique_names_preserving_existing_manual_links():
    result = page.auto_mapping_candidates(snapshot('1005_Synthetic', '1010_Other'),
                                          [trip(), trip('b', '1010_Other')], {'manual': 'b'})
    assert result == {'1005_Synthetic': 'a'}


@pytest.mark.parametrize('tabs,names', [
    ([trip(), trip('b')], ['1005_Synthetic']),
    ([trip()], ['1005_Synthetic', '1005_Synthetic의 사본']),
    ([trip(name='1005_Synthetic extra')], ['1005_Synthetic']),
    ([trip(), trip('b', year=2027)], ['1005_Synthetic']),
    ([trip(name='0206_하쿠산', year=2026)], ['0206_하쿠산']),
])
def test_ambiguous_names_and_known_year_conflicts_are_not_guessed(tabs, names):
    assert page.auto_mapping_candidates(snapshot(*names), tabs, {}) == {}


def test_known_2027_trip_matches_only_correct_year():
    t = trip(name='0206_하쿠산', year=2027)
    t['starts_on'] = '2027-02-06'
    assert page.auto_mapping_candidates(snapshot('0206_하쿠산'), [t], {}) == {'0206_하쿠산': 'a'}


def test_auto_apply_is_idempotent_and_failed_replace_preserves_settings(tmp_path, monkeypatch):
    path = tmp_path / 'snapshot.json'
    data = snapshot('1005_Synthetic')
    monkeypatch.setattr(page.os, 'replace', lambda *a: (_ for _ in ()).throw(OSError('disk failure')))
    with pytest.raises(OSError):
        page.auto_link_trips(path, data, [trip()])
    assert page.load_mapping(path) == {}
    monkeypatch.undo()
    assert page.auto_link_trips(path, data, [trip()]) == 1
    assert page.auto_link_trips(path, data, [trip()]) == 0
    assert page.load_mapping(path) == {'1005_Synthetic': 'a'}


def test_auto_route_requires_csrf_and_returns_saved_count(tmp_path, monkeypatch):
    from types import SimpleNamespace
    from urllib.parse import urlparse
    from webapp import ledger_board
    from webapp.tests.test_google_ledger_page import FakeHandler
    path = tmp_path / 'snapshot.json'
    monkeypatch.setenv('WEBLEDGER_GOOGLE_LEDGER_SNAPSHOT', str(path))
    monkeypatch.setenv('WEBLEDGER_GOOGLE_LEDGER_ROWS', str(tmp_path / 'rows.json'))
    monkeypatch.setattr(page.google_authority, 'load_consistent', lambda *a: (snapshot('1005_Synthetic'), {}))
    monkeypatch.setattr(ledger_board, '_active_store', lambda: SimpleNamespace(list_trips=lambda **kw: [trip()]))
    handler = FakeHandler()
    page.dispatch(handler, urlparse('/api/google-ledger/auto-mapping'), is_owner=True, csrf='token', raw=b'{}')
    assert handler.sent[0][1] == 403
    handler = FakeHandler('token')
    page.dispatch(handler, urlparse('/api/google-ledger/auto-mapping'), is_owner=True, csrf='token', raw=b'{}')
    assert handler.sent[0] == ('json', 200, {'code': 'OK', 'linked': 1})


def test_import_creates_trips_from_the_sheet_top_and_leaves_an_end_empty_only_when_no_next_trip_exists(tmp_path):
    from webapp.ledger_store import LedgerStore
    board = LedgerStore(tmp_path / 'board.sqlite', seed_demo=False)
    snap = {'trips': [
        {'key': '0630_오제', 'kind': 'trip', 'period': {'year': 2026, 'starts_on': '2026-06-30',
                                                         'ends_on': '2026-07-04', 'destination': '오제'}},
        {'key': '0712_몽골', 'kind': 'trip', 'period': {'year': 2026, 'starts_on': '2026-07-12',
                                                         'ends_on': None, 'destination': ''}},
        {'key': '0506_0610_유럽', 'kind': 'trip', 'period': {'year': 2026, 'starts_on': '2026-05-06',
                                                             'ends_on': '2026-06-10', 'destination': '유럽'}},
        {'key': '0801_한티', 'kind': 'trip', 'period': {'year': None, 'starts_on': None,
                                                     'ends_on': None, 'destination': ''}},
        {'key': '1005_Q', 'kind': 'quarter', 'period': {}},
    ]}
    assert page.import_trips(board, snap) == {'created': 3, 'held': 1}
    tabs = {t['display_key']: t for t in board.list_trips(include_archived=True)}
    assert tabs['0630_오제']['ends_on'] == '2026-07-04' and tabs['0630_오제']['destination'] == '오제'
    assert tabs['0712_몽골']['ends_on'] in ('', None)
    assert tabs['0506_0610_유럽']['destination'] == '유럽'
    assert page.import_trips(board, snap)['held'] == 1
    assert len(board.list_trips(include_archived=True)) == 3


def test_import_then_auto_link_connects_the_new_tabs_to_their_google_keys(tmp_path):
    from webapp.ledger_store import LedgerStore
    board = LedgerStore(tmp_path / 'board.sqlite', seed_demo=False)
    snapshot_path = tmp_path / 'snapshot.json'
    snap = {'trips': [{'key': '0630_오제', 'kind': 'trip', 'period': {
        'year': 2026, 'starts_on': '2026-06-30', 'ends_on': '2026-07-04', 'destination': '오제'}}]}
    page.import_trips(board, snap)
    assert page.auto_link_trips(snapshot_path, snap, board.list_trips(include_archived=True)) == 1
    tab = next(t['tab_id'] for t in board.list_trips(include_archived=True) if t['display_key'] == '0630_오제')
    assert page.load_mapping(snapshot_path) == {'0630_오제': tab}


def test_import_reuses_a_tab_with_the_same_display_name(tmp_path):
    from webapp.ledger_store import LedgerStore
    board = LedgerStore(tmp_path / 'board.sqlite', seed_demo=False)
    board.create_trip(starts_on='2026-06-20', destination='묘코고원', display_key='0620_묘코',
                      client_request_id='manual-0620')
    snap = {'trips': [{'key': '0620_묘코', 'kind': 'trip', 'period': {
        'year': 2026, 'starts_on': '2026-06-20', 'ends_on': '2026-06-25', 'destination': ''}}]}
    assert page.import_trips(board, snap) == {'end_set': 1}
    assert len(board.list_trips(include_archived=True)) == 1


def test_import_fills_the_blank_end_of_an_existing_tab_once(tmp_path):
    from webapp.ledger_store import LedgerStore, SaveError
    board = LedgerStore(tmp_path / 'board.sqlite', seed_demo=False)
    tab = board.create_trip(starts_on='2026-09-15', destination='길상사', display_key='0915_길상사',
                            client_request_id='blank-end')['tab_id']
    snap = {'trips': [{'key': '0915_길상사', 'kind': 'trip', 'period': {
        'year': 2026, 'starts_on': '2026-09-15', 'ends_on': '2026-09-15', 'destination': ''}}]}
    assert page.import_trips(board, snap) == {'end_set': 1}
    assert board.get_trip(tab)['ends_on'] == '2026-09-15'
    assert page.import_trips(board, snap) == {'existing': 1}
    with pytest.raises(SaveError):
        board.save_trip_meta(tab_id=tab, expected_revision=board.get_trip(tab)['revision'],
                             client_request_id='too-early', ends_on='2026-09-01')
