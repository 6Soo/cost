from types import SimpleNamespace

import pytest

from webapp import google_ledger_page as page, ledger_board as board
from webapp.tests.test_google_canonical_workflow import healthy_snapshot
from webapp.tests.test_google_ledger_page import rows_doc


@pytest.fixture
def income_context(tmp_path, monkeypatch):
    path = tmp_path / 'snapshot.json'
    monkeypatch.setenv('WEBLEDGER_GOOGLE_LEDGER_SNAPSHOT', str(path))
    monkeypatch.setenv('WEBLEDGER_GOOGLE_LEDGER_ROWS', str(tmp_path / 'rows.json'))
    snapshot = healthy_snapshot()
    key = snapshot['trips'][0]['key']
    monkeypatch.setattr(page.google_authority, 'load_consistent', lambda *a: (snapshot, rows_doc()['sources']))
    monkeypatch.setattr(page, 'snapshot_for_display', lambda data: data)
    monkeypatch.setattr(page, 'load_choices', lambda *a: {'choices': {key: 'main'}})
    monkeypatch.setattr(page, 'load_mapping', lambda *a: {key: 'trip-syn'})
    monkeypatch.setattr(page, 'load_grants', lambda *a: {'grants': {'viewer-syn': [key]}})
    monkeypatch.setattr(board, 'current_role', lambda: 'owner')
    return snapshot, key


def test_income_connects_only_explicit_trip_and_preserves_rows(income_context):
    body = page.trip_income_html('trip-syn')
    assert '1,000원' in body and 'INCOME-NAME' in body
    assert '예약금' in body and '잔금' in body and '추가금' in body
    assert 'source=main' in body and 'Google 확정 수입' in body
    assert 'INCOME-NAME' not in page.trip_income_html('other-trip')
    assert '미연결' in page.trip_income_html('other-trip')


def test_income_does_not_guess_ambiguous_mapping(income_context, monkeypatch):
    _, key = income_context
    monkeypatch.setattr(page, 'load_mapping', lambda *a: {key: 'trip-syn', 'other': 'trip-syn'})
    body = page.trip_income_html('trip-syn')
    assert 'INCOME-NAME' not in body and '1,000원' not in body


def test_income_requires_canonical_copy_and_marks_unverified(income_context, monkeypatch):
    snapshot, _ = income_context
    monkeypatch.setattr(page, 'load_choices', lambda *a: {'choices': {}})
    body = page.trip_income_html('trip-syn')
    assert '최종 장부 선택' in body and 'INCOME-NAME' not in body
    snapshot['trips'][0]['verified'] = False
    monkeypatch.setattr(page, 'load_choices', lambda *a: {'choices': {}})
    snapshot['trips'][0]['copies']['archive'] = None
    body = page.trip_income_html('trip-syn')
    assert '확인 필요' in body and 'Google 확정 수입 1,000원' not in body


def test_viewer_income_checks_both_grant_and_current_trip_access(income_context, monkeypatch):
    monkeypatch.setattr(board, 'current_role', lambda: 'viewer')
    monkeypatch.setattr(board, 'current_request_session', lambda: SimpleNamespace(user_id='viewer-syn'))
    monkeypatch.setattr(board, 'viewer_visible_tabs', lambda session: {'trip-syn'})
    assert 'INCOME-NAME' in page.trip_income_html('trip-syn')
    monkeypatch.setattr(page, 'load_grants', lambda *a: {'grants': {}})
    assert 'INCOME-NAME' not in page.trip_income_html('trip-syn')
    assert '1,000원' not in page.trip_income_html('trip-syn')
    monkeypatch.setattr(page, 'load_grants', lambda *a: {'grants': {'viewer-syn': [income_context[1]]}})
    monkeypatch.setattr(board, 'viewer_visible_tabs', lambda session: set())
    assert 'INCOME-NAME' not in page.trip_income_html('trip-syn')
    monkeypatch.setattr(board, 'current_request_session', lambda: None)
    assert 'INCOME-NAME' not in page.trip_income_html('trip-syn')


def test_missing_rows_and_unavailable_snapshot_never_display_zero(income_context, monkeypatch):
    def unavailable(*args):
        raise page.google_authority.SnapshotError('TEST_UNAVAILABLE')
    monkeypatch.setattr(page.google_authority, 'load_consistent', unavailable)
    body = page.trip_income_html('trip-syn')
    assert '조회 불가' in body and '0원' not in body


def test_verified_zero_is_distinct_from_unlinked(income_context):
    snapshot, _ = income_context
    copy = snapshot['trips'][0]['copies']['main']
    copy['income'].update(total=0, sheet_total=0, row_sum=0)
    assert 'Google 확정 수입 0원' in page.trip_income_html('trip-syn')
    assert 'Google 확정 수입 0원' not in page.trip_income_html('unknown')


def test_unverified_income_explains_total_error_without_exposing_rows(income_context, monkeypatch):
    _, key = income_context
    monkeypatch.setattr(page, 'owner_payload', lambda *args: {
        'trips': [{'key': key, 'chosen_source': 'main', 'verified': False,
                   'review': ['TOTAL_MISMATCH', 'TOTAL_RANGE_MISMATCH']}],
        'synced_at': '2026-10-12T19:00:00+09:00'})
    body = page.trip_income_html('trip-syn')
    assert '확인 필요 이유' in body
    assert page.REVIEW_LABELS['TOTAL_MISMATCH'] in body
    assert page.REVIEW_LABELS['TOTAL_RANGE_MISMATCH'] in body
    assert 'INCOME-NAME' not in body
    assert 'Google 확정 수입' not in body


def test_mapping_picker_names_imported_trips_and_preserves_current_trip():
    body = page._owner_controls({'trips': []}, {
        'tabs': [{'tab_id': 'syn', 'display_key': 'Synthetic trip name', 'destination': ''}],
        'viewers': [], 'mapping': {}, 'grants': {}, 'selected_tab': 'syn',
    })
    assert '<option value="syn" selected>Synthetic trip name</option>' in body
    assert '<details id="google-settings" open>' in body
