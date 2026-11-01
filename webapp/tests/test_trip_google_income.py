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
    assert '/api/google-ledger/source?trip=trip-syn' in body and '수입 1,000원' in body
    assert '/google-ledger/rows?' not in body
    assert 'target=\'_blank\'' in body and "rel='noopener noreferrer'" in body
    assert 'INCOME-NAME' not in page.trip_income_html('other-trip')
    assert '연결되지 않았습니다' in page.trip_income_html('other-trip')


@pytest.mark.parametrize('amount', [0, -1000, 1000])
@pytest.mark.parametrize('loaded', [False, True])
def test_income_refund_status_uses_total_before_and_after_roster_load(
        income_context, monkeypatch, amount, loaded):
    import copy
    snapshot, _ = income_context
    rows = [{'row': 6, 'date': '2026-10-28', 'name': 'synthetic',
             'deposit': 1000, 'balance': 0, 'extra': amount - 1000, 'amount': amount}]
    before = copy.deepcopy(rows)
    monkeypatch.setattr(page, 'owner_rows', lambda *args: {'income': rows, 'expense': []})
    snapshot['trips'][0]['copies']['main']['income'].update(
        total=amount, row_sum=amount, sheet_total=amount)
    body = page.trip_income_html('trip-syn', participant_state={} if loaded else None)
    assert ('환불완료' in body) == (amount <= 0)
    assert ("data-income-refund-complete='1'" in body) == (amount <= 0)
    assert '보험 미가입을 뜻하지 않음' not in body
    assert rows == before


def test_missing_income_total_is_not_refund_complete():
    assert not page.is_refunded_income({})
    assert not page.is_refunded_income({'amount': None})


def test_income_renders_all_rows_without_next_20_link(income_context, monkeypatch):
    snapshot, _ = income_context
    rows = [
        {'row': index, 'date': f'2026-10-{(index % 28) + 1:02d}',
         'name': f'INCOME-{index}', 'nickname': '', 'deposit': 1000,
         'balance': '', 'extra': '', 'amount': 1000}
        for index in range(25)
    ]
    monkeypatch.setattr(page, 'owner_rows', lambda *args: {'income': rows, 'expense': []})
    snapshot['trips'][0]['copies']['main']['income'].update(
        total=25000, row_sum=25000, sheet_total=25000)

    body = page.trip_income_html('trip-syn')

    assert 'INCOME-0' in body and 'INCOME-24' in body
    assert body.count("<td class='income-person'>") == 25
    assert '다음 수입 20건' not in body


def test_income_does_not_guess_ambiguous_mapping(income_context, monkeypatch):
    _, key = income_context
    monkeypatch.setattr(page, 'load_mapping', lambda *a: {key: 'trip-syn', 'other': 'trip-syn'})
    body = page.trip_income_html('trip-syn')
    assert 'INCOME-NAME' not in body and '1,000원' not in body


def test_income_requires_canonical_copy_and_marks_unverified(income_context, monkeypatch):
    snapshot, _ = income_context
    monkeypatch.setattr(page, 'load_choices', lambda *a: {'choices': {}})
    body = page.trip_income_html('trip-syn')
    assert '사용할 장부 사본' in body and 'INCOME-NAME' not in body
    snapshot['trips'][0]['verified'] = False
    monkeypatch.setattr(page, 'load_choices', lambda *a: {'choices': {}})
    snapshot['trips'][0]['copies']['archive'] = None
    snapshot['trips'][0]['copies']['main']['income']['verified'] = False
    body = page.trip_income_html('trip-syn')
    assert '수입 확인 필요' in body and '확정 수입 1,000원' not in body


def test_verified_income_remains_visible_when_only_expense_block_is_unverified(income_context):
    snapshot, _ = income_context
    snapshot['trips'][0]['copies']['main']['expense']['verified'] = False
    body = page.trip_income_html('trip-syn')
    assert 'INCOME-NAME' in body
    assert '수입 1,000원' in body
    assert '지출 또는 여행 전체 회계 검증은 완료되지 않았습니다' not in body
    assert '순수익' not in body


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
    assert '수입 내역을 불러오지 못했습니다' in body and '0원' not in body


def test_verified_zero_is_distinct_from_unlinked(income_context):
    snapshot, _ = income_context
    copy = snapshot['trips'][0]['copies']['main']
    copy['income'].update(total=0, sheet_total=0, row_sum=0)
    # The ledger rows still hold 1,000원 while the sheet says 0원: that gap is reported, not hidden.
    assert '수입 합계 차이 있음' in page.trip_income_html('trip-syn')
    assert '수입 합계 차이 있음' not in page.trip_income_html('unknown')


def test_source_link_uses_selected_archive_and_quotes_actual_sheet(income_context, monkeypatch):
    from urllib.parse import unquote
    snapshot, key = income_context
    sheet = "Synthetic ' 여행 & 사본"
    snapshot['trips'][0]['copies']['archive']['sheet'] = sheet
    monkeypatch.setattr(page, 'load_choices', lambda *a: {'choices': {key: 'archive'}})
    monkeypatch.setattr(page, 'owner_rows', lambda *a: {'income': [], 'expense': []})
    body = page.trip_income_html('trip-syn')
    assert '/api/google-ledger/source?trip=trip-syn' in body
    # The navigation endpoint resolves the selected copy and exact title at click time.
    assert '/edit#range=' not in body


def test_unverified_income_explains_total_error_without_exposing_rows(income_context, monkeypatch):
    _, key = income_context
    monkeypatch.setattr(page, 'owner_payload', lambda *args: {
        'trips': [{'key': key, 'chosen_source': 'main', 'verified': False,
                   'review': ['TOTAL_MISMATCH', 'TOTAL_RANGE_MISMATCH']}],
        'synced_at': '2026-10-12T19:00:00+09:00'})
    body = page.trip_income_html('trip-syn')
    assert page.REVIEW_LABELS['TOTAL_MISMATCH'] in body
    assert page.REVIEW_LABELS['TOTAL_RANGE_MISMATCH'] in body
    assert 'INCOME-NAME' not in body
    assert '확정 수입 1,000원' not in body


def test_mapping_picker_names_imported_trips_and_preserves_current_trip():
    body = page._owner_controls({'trips': []}, {
        'tabs': [{'tab_id': 'syn', 'display_key': 'Synthetic trip name', 'destination': ''}],
        'viewers': [], 'mapping': {}, 'grants': {}, 'selected_tab': 'syn',
    })
    assert '<option value="syn" selected>Synthetic trip name</option>' in body
    assert '<details id="google-settings" open>' in body


@pytest.mark.parametrize('value,expected', [
    ('2026-10-12T20:00:02.049343+09:00', '2026.10.12 20:00'),
    ('2026-10-12T11:00:02Z', '2026.10.12 20:00'),
    ('2026-10-12T23:30:00-04:00', '2026.10.13 12:30'),
    ('2026-10-12T20:00:00', '대기'),
    ('<script>', '대기'),
    (None, '대기'),
    ('', '대기'),
])
def test_display_time_uses_seoul_minutes_and_safe_fallback(value, expected):
    assert page.format_display_time(value) == expected


def test_is_unconfirmed_income_row():
    # 완전히 빈 템플릿 행
    assert page.is_unconfirmed_income_row({'date': None, 'name': None, 'nickname': None, 'amount': 0})
    assert page.is_unconfirmed_income_row({'date': '', 'name': '', 'nickname': '', 'amount': 0})
    assert page.is_unconfirmed_income_row({'date': '   ', 'name': '  ', 'nickname': ' ', 'amount': 0})
    assert page.is_unconfirmed_income_row({'date': '날짜 미확인', 'name': '이름 미확인', 'nickname': '', 'amount': 0})
    assert page.is_unconfirmed_income_row({'date': '-', 'name': '-', 'nickname': '-', 'amount': 0})

    # 날짜나 이름/닉네임이 있는 실제 수입 행은 미확인이 아님
    assert not page.is_unconfirmed_income_row({'date': '2026-08-06', 'name': '', 'nickname': '', 'amount': 1000})
    assert not page.is_unconfirmed_income_row({'date': '', 'name': '이수원', 'nickname': '', 'amount': 1000})
    assert not page.is_unconfirmed_income_row({'date': '', 'name': '', 'nickname': '닉네임', 'amount': 1000})
    assert not page.is_unconfirmed_income_row({'date': '2026-08-06', 'name': '이수원', 'nickname': '닉네임', 'amount': 1000})


def test_unconfirmed_income_rows_are_hidden_from_trip_income_display(income_context, monkeypatch):
    snapshot, key = income_context
    valid_row = {'row': 6, 'date': '2026-08-06', 'name': '이수원', 'nickname': '',
                 'deposit': 1000000, 'balance': 2960000, 'extra': 0, 'amount': 3960000}
    dummy_rows = [
        {'row': 7, 'date': None, 'name': None, 'nickname': None,
         'deposit': None, 'balance': None, 'extra': None, 'amount': 0},
        {'row': 8, 'date': '', 'name': '', 'nickname': '',
         'deposit': 0, 'balance': 0, 'extra': 0, 'amount': 0},
        {'row': 9, 'date': '   ', 'name': '  ', 'nickname': '',
         'deposit': None, 'balance': None, 'extra': None, 'amount': 0},
    ]
    detail = {'key': key, 'source': 'main', 'income': [valid_row] + dummy_rows, 'expense': []}
    monkeypatch.setattr(page, 'owner_rows', lambda *a: detail)
    snapshot['trips'][0]['copies']['main']['income'].update(
        total=3960000, row_sum=3960000, sheet_total=3960000)

    body = page.trip_income_html('trip-syn')
    assert '이수원' in body
    assert '3,960,000원' in body
    assert '8월6일' in body
    assert '날짜 미확인' not in body
    assert '이름 미확인' not in body
    assert "<td class='income-total'>0원</td>" not in body
    # thead 1행 + tbody 1행 = 총 2개의 <tr> (tfoot은 class='income-foot-row')
    assert body.count('<tr>') == 2
