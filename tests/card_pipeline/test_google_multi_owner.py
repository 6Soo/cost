from app.google_authority import (
    SOURCE_REGISTRY, SPREADSHEET_IDS, build_trip_view, source_label,
    source_owner_id, trip_owner_id, trip_sheet,
)


def _trip(title, year, start, *, end=None):
    return {
        'sheet': title, 'copy_name': False, 'layout': 'rev', 'flags': [],
        'verified': True, 'income': {'total': 10}, 'expense': {'total': 2},
        'net': 8, 'period': {'year': year, 'starts_on': start, 'ends_on': end,
                            'flags': ['PERIOD_END_MISSING'] if end is None else []},
    }


def test_registry_and_helpers_keep_aslan_keys_compatible():
    assert SPREADSHEET_IDS['andre_main'] == '1giIJZDYIL-RBwVy_-yDhElAmsV0pUgkCxBcEa3Wr87Y'
    assert SOURCE_REGISTRY['andre_main']['owner_id'] == 'andre'
    assert source_owner_id('main') == 'aslan'
    assert source_label('main') == '아슬란 메인 장부'
    assert source_label('archive') == '아슬란 보관 장부'
    assert source_label('andre_main') == '안드레 메인 장부'
    assert trip_sheet('2026_Same') == '2026_Same'
    assert trip_sheet('andre::2026::2026_Same') == '2026_Same'
    assert trip_owner_id('2026_Same') == 'aslan'
    assert trip_owner_id('andre::2026::2026_Same') == 'andre'


def test_identical_titles_are_separate_and_andre_archive_is_unknown():
    sources = {
        'main': {'status': 'ok', 'last_ok_at': 'now', 'trips': [_trip('2026_Same', 2026, '2026-01-01')]},
        'archive': {'status': 'ok', 'last_ok_at': 'now', 'trips': []},
        'andre_main': {'status': 'ok', 'last_ok_at': 'now', 'trips': [_trip('2026_Same', 2026, '2026-01-02')]},
    }
    view = build_trip_view(sources)
    assert {t['key'] for t in view} == {'2026_Same', 'andre::2026::2026_Same'}
    andre = next(t for t in view if t['owner_id'] == 'andre')
    assert andre['closure'] == 'unknown'
    assert andre['owner_name'] == '김동언' and andre['owner_alias'] == '안드레'
    assert andre['copies']['andre_main']['sheet'] == '2026_Same'


def test_open_end_inference_does_not_cross_owners_or_years():
    sources = {
        'main': {'status': 'ok', 'last_ok_at': 'now', 'trips': [
            _trip('2026_A', 2026, '2026-01-01'), _trip('2027_B', 2027, '2027-01-01')]},
        'archive': {'status': 'ok', 'last_ok_at': 'now', 'trips': []},
        'andre_main': {'status': 'ok', 'last_ok_at': 'now', 'trips': [_trip('2026_C', 2026, '2026-02-01')]},
    }
    view = build_trip_view(sources)
    aslan_2026 = next(t for t in view if t['key'] == '2026_A')
    assert aslan_2026['period']['ends_on'] is None
    andre = next(t for t in view if t['owner_id'] == 'andre')
    assert andre['period']['ends_on'] is None


def test_same_owner_and_title_in_different_years_stays_separate():
    sources = {
        'main': {'status': 'ok', 'last_ok_at': 'now', 'trips': []},
        'archive': {'status': 'ok', 'last_ok_at': 'now', 'trips': []},
        'andre_main': {'status': 'ok', 'last_ok_at': 'now', 'trips': [
            _trip('2026_Same', 2026, '2026-01-01'),
            _trip('2026_Same', 2027, '2027-01-01')]},
    }
    view = build_trip_view(sources)
    assert {t['key'] for t in view} == {'andre::2026::2026_Same', 'andre::2027::2026_Same'}


def test_malformed_andre_qualified_key_is_rejected():
    import pytest

    for key in ('andre::', 'andre::2026', 'andre::nope::Title'):
        with pytest.raises(ValueError, match='INVALID_QUALIFIED_TRIP_KEY'):
            trip_owner_id(key)
    with pytest.raises(ValueError, match='INVALID_QUALIFIED_TRIP_KEY'):
        trip_sheet('andre::2026')


def test_aslan_title_year_conflict_keeps_legacy_key_and_blocks_figures():
    sources = {
        'main': {'status': 'ok', 'last_ok_at': 'now', 'trips': [
            _trip('Same', 2026, '2026-01-01'), _trip('Same', 2027, '2027-01-01')]},
        'archive': {'status': 'ok', 'last_ok_at': 'now', 'trips': []},
        'andre_main': {'status': 'ok', 'last_ok_at': 'now', 'trips': []},
    }
    view = build_trip_view(sources)
    assert len(view) == 1 and view[0]['key'] == 'Same'
    assert 'PERIOD_YEAR_CONFLICT' in view[0]['review']
    assert view[0]['income_total'] is None and view[0]['verified'] is False


def test_andre_missing_year_uses_valid_qualified_key_but_is_unusable():
    sources = {
        'main': {'status': 'ok', 'last_ok_at': 'now', 'trips': []},
        'archive': {'status': 'ok', 'last_ok_at': 'now', 'trips': []},
        'andre_main': {'status': 'ok', 'last_ok_at': 'now', 'trips': [_trip('NoYear', None, None)]},
    }
    trip, = build_trip_view(sources)
    assert trip['key'] == 'andre::0000::NoYear'
    assert trip_owner_id(trip['key']) == 'andre'
    assert 'PERIOD_YEAR_MISSING' in trip['review']
    assert trip['income_total'] is None and trip['verified'] is False
