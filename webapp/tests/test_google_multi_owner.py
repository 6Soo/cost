"""Synthetic regression coverage for owner isolated Google ledger access and mapping."""

import json
import datetime as dt
from types import SimpleNamespace

import pytest

from app import google_authority as ga
from webapp import google_ledger_page as page


ANDRE_KEY = 'andre::2027::1022_Synthetic'
ASLAN_KEY = '1022_Synthetic'


def _copy(amount=100):
    block = {'total': amount, 'verified': True}
    return {'sheet': '1022_Synthetic', 'layout': 'rev', 'flags': [],
            'income': dict(block), 'expense': dict(block)}


def _trip(key, owner, copies, *, closure='unknown', flags=None):
    source = next(iter(copies))
    return {'key': key, 'sheet': '1022_Synthetic', 'owner_id': owner,
            'canonical_source': source, 'copies': copies, 'closure': closure,
            'closure_current': False, 'income_total': 100, 'expense_total': 100,
            'net': 0, 'verified': True, 'review': list(flags or []), 'kind': 'trip'}


def test_source_registry_labels_and_qualified_trip_helpers():
    assert page.source_label('main') == '아슬란 메인 장부'
    assert page.source_label('archive') == '아슬란 보관 장부'
    assert page.source_label('andre_main') == '안드레 메인 장부'
    assert page.source_owner_id('andre_main') == 'andre'
    assert page.trip_owner_id(ANDRE_KEY) == 'andre'
    assert page.trip_sheet(ANDRE_KEY) == '1022_Synthetic'
    assert page.trip_owner_id(ASLAN_KEY) == 'aslan'


def test_private_rows_and_income_name_index_use_raw_sheet_and_enforce_owner():
    rows = {
        'main': {'trips': {'1022_Synthetic': {'income': [{'row': 6, 'cells': {'B': '2027-10-22', 'C': 'Synthetic Aslan'}, 'amount': 11}], 'expense': []}},
                 'income_names': {'1022_Synthetic': {'available': True, 'income': [{'name': 'Synthetic Aslan'}]}}},
        'andre_main': {'trips': {'1022_Synthetic': {'income': [{'row': 6, 'cells': {'B': '2027-10-22', 'C': 'Synthetic Andre'}, 'amount': 22}], 'expense': []}},
                       'income_names': {'1022_Synthetic': {'available': True, 'income': [{'name': 'Synthetic Andre'}]}}},
    }
    assert page.owner_rows(rows, ANDRE_KEY, 'andre_main')['income'][0]['amount'] == 22
    assert page.owner_rows(rows, ASLAN_KEY, 'main')['income'][0]['amount'] == 11
    assert page.owner_income_names(rows, ANDRE_KEY, 'andre_main')['rows'][0]['name'] == 'Synthetic Andre'
    with pytest.raises(ValueError, match='SOURCE_OWNER_MISMATCH'):
        page.owner_rows(rows, ANDRE_KEY, 'main')
    with pytest.raises(ValueError, match='SOURCE_OWNER_MISMATCH'):
        page.owner_income_names(rows, ASLAN_KEY, 'andre_main')


def test_andre_single_copy_is_selected_and_unknown_closure_does_not_block_verified_figures():
    trip = _trip(ANDRE_KEY, 'andre', {'andre_main': _copy(700)})
    sources = {'main': {'status': 'ok'}, 'archive': {'status': 'ok'},
               'andre_main': {'status': 'ok', 'stale': False}}
    resolved = page._trip_for_owner(trip, {}, sources)
    assert resolved['chosen_source'] == 'andre_main'
    assert resolved['verified'] is True and resolved['income_total'] == 700
    assert resolved['blocked_by'] == []


def test_andre_income_detail_uses_andre_source_label_and_raw_sheet(tmp_path, monkeypatch):
    from webapp import ledger_board, participant_trip_panel

    stamp = dt.datetime.now(ga.KST).isoformat()
    copy = _copy(700)
    copy['sheet'] = '1022_Synthetic'
    trip = _trip(ANDRE_KEY, 'andre', {'andre_main': copy})
    trip.update(income_total=700, verified=True, review=[])
    snapshot = {'synced_at': stamp, 'rows_generation': 'synthetic-generation',
                'sources': {'main': {'status': 'ok', 'stale': False, 'last_ok_at': stamp},
                            'archive': {'status': 'ok', 'stale': False, 'last_ok_at': stamp},
                            'andre_main': {'status': 'ok', 'stale': False, 'last_ok_at': stamp}},
                'trips': [trip]}
    rows = {'andre_main': {'trips': {'1022_Synthetic': {'income': [
        {'row': 6, 'cells': {'B': '2027-10-22', 'C': 'Synthetic Andre', 'D': '',
                             'E': 700, 'F': 0, 'G': 0}, 'amount': 700}], 'expense': []}}}}
    monkeypatch.setenv('WEBLEDGER_GOOGLE_LEDGER_SNAPSHOT', str(tmp_path / 'snapshot.json'))
    monkeypatch.setenv('WEBLEDGER_GOOGLE_LEDGER_ROWS', str(tmp_path / 'rows.json'))
    monkeypatch.setattr(page, 'load_mapping', lambda *args: {ANDRE_KEY: 'andre-tab'})
    monkeypatch.setattr(page, 'load_choices', lambda *args: {'choices': {}})
    monkeypatch.setattr(page, '_load_consistent_measured', lambda *args: (snapshot, rows))
    monkeypatch.setattr(page, 'snapshot_for_display', lambda value: value)
    monkeypatch.setattr(ledger_board, 'current_role', lambda: 'owner')
    attached = {}
    def attach(entries, **kwargs):
        attached.update(kwargs)
        return entries
    monkeypatch.setattr(participant_trip_panel, 'attach_row_refs', attach)
    body = page.trip_income_html('andre-tab')
    assert '안드레 메인 장부' in body
    assert '1022_Synthetic' in body
    assert 'andre%3A%3A2027%3A%3A' not in body
    assert attached == {'source': 'andre_main', 'sheet': '1022_Synthetic'}


def test_source_failure_is_scoped_to_its_owner():
    aslan = _trip(ASLAN_KEY, 'aslan', {'main': _copy(300)})
    aslan.update(closure='open', closure_current=True)
    andre = _trip(ANDRE_KEY, 'andre', {'andre_main': _copy(700)})
    sources = {'main': {'status': 'ok', 'stale': False},
               'archive': {'status': 'ok', 'stale': False},
               'andre_main': {'status': 'error', 'stale': True}}
    assert page._trip_for_owner(aslan, {'1022_Synthetic': 'main'}, sources)['verified'] is True
    assert page._trip_for_owner(andre, {}, sources)['verified'] is False


def test_andre_mapping_does_not_reuse_another_years_same_title():
    source = _trip(ANDRE_KEY, 'andre', {'andre_main': _copy()})
    target = {'tab_id': 'wrong-year', 'display_key': '1022_Synthetic',
              'owner_id': 'andre', 'starts_on': '2026-10-22', 'event_year': 2026}
    assert page.auto_mapping_candidates({'trips': [source]}, [target], {}) == {}


def test_manual_choice_rejects_cross_owner_sources_and_accepts_andre_main(tmp_path):
    path = tmp_path / 'snapshot.json'
    with pytest.raises(ValueError, match='CHOICE_OWNER_MISMATCH'):
        page.record_choice(path, key=ANDRE_KEY, source='archive', at='synthetic-time')
    with pytest.raises(ValueError, match='CHOICE_OWNER_MISMATCH'):
        page.record_choice(path, key=ASLAN_KEY, source='andre_main', at='synthetic-time')
    result = page.record_choice(path, key=ANDRE_KEY, source='andre_main', at='synthetic-time')
    assert result['choices'][ANDRE_KEY] == 'andre_main'
    assert page.load_choices(path)['choices'][ANDRE_KEY] == 'andre_main'


def test_load_choices_rejects_persisted_cross_owner_choice(tmp_path):
    path = tmp_path / 'snapshot.json'
    page.choice_path(path).write_text(json.dumps({'choices': {ANDRE_KEY: 'archive'}, 'history': []}), encoding='utf-8')
    with pytest.raises(ga.SnapshotError, match='SETTINGS_UNAVAILABLE'):
        page.load_choices(path)


@pytest.mark.parametrize(('key', 'source', 'copies', 'expected'), [
    (ANDRE_KEY, 'andre_main', {'andre_main': _copy()}, 'OK'),
    (ANDRE_KEY, 'archive', {'andre_main': _copy()}, 'CHOICE_COPY_UNAVAILABLE'),
    (ASLAN_KEY, 'andre_main', {'main': _copy()}, 'CHOICE_COPY_UNAVAILABLE'),
])
def test_choice_dispatch_validates_copy_owner_and_accepts_andre(tmp_path, monkeypatch,
                                                                 key, source, copies, expected):
    path = tmp_path / 'snapshot.json'
    monkeypatch.setattr(page, 'ROUTES', ('/api/google-ledger/choice',))
    monkeypatch.setattr(page, 'enabled', lambda: True)
    monkeypatch.setattr(page, '_snapshot_path', lambda: path)
    monkeypatch.setattr(page, '_rows_path', lambda: tmp_path / 'rows.json')
    owner = 'andre' if key.startswith('andre::') else 'aslan'
    trip = _trip(key, owner, copies)
    monkeypatch.setattr(page, '_load_consistent_measured',
                        lambda *args: ({'trips': [trip], 'sources': {}}, {}))

    class Handler:
        headers = {'X-CSRF-Token': 'synthetic-csrf'}
        sent = None

        def _send_json(self, body, status=200):
            self.sent = (body, status)

    handler = Handler()
    body = json.dumps({'key': key, 'source': source}).encode()
    assert page.dispatch(handler, SimpleNamespace(path='/api/google-ledger/choice'),
                         is_owner=True, raw=body, csrf='synthetic-csrf') is True
    assert handler.sent[0]['code'] == expected


def test_auto_mapping_is_owner_scoped_and_tracks_immutable_source_key():
    snapshot = {'trips': [
        {'key': ASLAN_KEY, 'sheet': '1022_Synthetic', 'owner_id': 'aslan',
         'period': {'year': 2027, 'starts_on': '2027-10-22'}},
        {'key': ANDRE_KEY, 'sheet': '1022_Synthetic', 'owner_id': 'andre',
         'period': {'year': 2027, 'starts_on': '2027-10-22'}},
    ]}
    tabs = [
        {'tab_id': 'aslan-tab', 'display_key': '1022_Synthetic', 'owner_id': 'aslan',
         'starts_on': '2027-10-22', 'event_year': 2027},
        {'tab_id': 'andre-tab', 'display_key': 'User renamed Andre trip', 'owner_id': 'andre',
         'source_trip_key': ANDRE_KEY, 'starts_on': '2027-10-22', 'event_year': 2027},
        {'tab_id': 'wrong-owner', 'display_key': '1022_Synthetic', 'owner_id': 'andre',
         'starts_on': '2027-10-22', 'event_year': 2027},
    ]
    assert page.auto_mapping_candidates(snapshot, tabs, {}) == {
        ASLAN_KEY: 'aslan-tab', ANDRE_KEY: 'andre-tab'}


def test_known_aslan_year_override_does_not_apply_to_andre():
    key = 'andre::2026::0206_하쿠산'
    snapshot = {'trips': [{'key': key, 'sheet': '0206_하쿠산', 'owner_id': 'andre',
                          'period': {'year': 2026, 'starts_on': '2026-02-06'}}]}
    tabs = [{'tab_id': 'andre-2026', 'display_key': '0206_하쿠산', 'owner_id': 'andre',
             'starts_on': '2026-02-06', 'event_year': 2026}]
    assert page.auto_mapping_candidates(snapshot, tabs, {}) == {key: 'andre-2026'}


def test_import_uses_raw_destination_and_reuses_manually_renamed_source_trip():
    class Board:
        def __init__(self):
            self.created = []

        def list_trips(self, include_archived=False):
            return [{'tab_id': 'andre-tab', 'display_key': 'Renamed by user',
                     'owner_id': 'andre', 'source_trip_key': ANDRE_KEY,
                     'ends_on': '', 'revision': 1}]

        def save_trip_meta(self, **kwargs):
            raise AssertionError('unexpected end-date write')

        def create_trip(self, **kwargs):
            self.created.append(kwargs)
            return {'outcome': 'created'}

    board = Board()
    result = page.import_trips(board, {'trips': [
        {'key': ANDRE_KEY, 'sheet': '1022_Synthetic', 'owner_id': 'andre',
         'kind': 'trip', 'period': {'year': 2027, 'starts_on': '2027-10-22', 'ends_on': None, 'flags': []}}
    ]})
    assert result == {'existing': 1}
    assert board.created == []

    class EmptyBoard(Board):
        def list_trips(self, include_archived=False):
            return []

    new_board = EmptyBoard()
    page.import_trips(new_board, {'trips': [
        {'key': ANDRE_KEY, 'sheet': '1022_Synthetic', 'owner_id': 'andre',
         'kind': 'trip', 'period': {'year': 2027, 'starts_on': '2027-10-22', 'ends_on': None, 'flags': []}}
    ]})
    created, = new_board.created
    assert created['display_key'] == ANDRE_KEY
    assert created['destination'] == 'Synthetic'
