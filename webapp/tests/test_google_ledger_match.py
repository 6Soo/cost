from unittest.mock import patch

from webapp import ledger_board, ledger_design, google_ledger_page


def test_exact_amount_and_one_matching_field_create_display_candidates():
    web = [
        {'row_id': 'date', 'amount_krw': 120000, 'occurred_on': '2026-10-01'},
        {'row_id': 'merchant', 'amount_krw': 120000, 'source_merchant': 'Cafe  A'},
        {'row_id': 'category', 'amount_krw': 120000, 'item': '교통비'},
        {'row_id': 'reservation', 'amount_krw': 120000, 'reservation_no': 'ABC-123'},
        {'row_id': 'amount-only', 'amount_krw': 120000},
        {'row_id': 'negative', 'amount_krw': -120000, 'occurred_on': '2026-10-01'},
        {'row_id': 'other-trip', 'amount_krw': 120000, 'occurred_on': '2026-10-02'},
    ]
    google = [
        {'amount': 120000, 'date': '2026-10-01'},
        {'amount': '120,000원', 'payee': 'cafe A'},
        {'amount': 120000, 'category': '교통비'},
        {'amount': 120000, 'reservation': 'ABC-123'},
        {'amount': 120000},
        {'amount': -120000, 'date': '2026-10-01'},
    ]
    result = ledger_design._google_expense_matches(google, web)
    assert result == {
        0: {'reasons': ['날짜'], 'multiple': False},
        1: {'reasons': ['가맹점'], 'multiple': False},
        2: {'reasons': ['분류'], 'multiple': False},
        3: {'reasons': ['예약번호'], 'multiple': False},
        5: {'reasons': ['날짜'], 'multiple': False},
    }


def test_many_to_many_candidates_are_all_marked_ambiguous():
    web = [{'row_id': 'a', 'amount_krw': 500, 'item': '식비'},
           {'row_id': 'b', 'amount_krw': 500, 'item': '식비'}]
    google = [{'amount': 500, 'category': '식비'}, {'amount': 500, 'category': '식비'}]
    result = ledger_design._google_expense_matches(google, web)
    assert result[0]['multiple'] and result[1]['multiple']
    assert result[0]['reasons'] == ['분류']


def test_annotation_reads_only_selected_fresh_source_and_is_owner_only(monkeypatch):
    rows = [{'row_id': 'web-a', 'amount_krw': 900, 'occurred_on': '2026-10-03'}]
    preview = {'source_available': True,
               'sheet_rows': [{'amount_krw': 900, 'date': '2026-10-03', 'currency': 'KRW'}],
               'results': [{'transaction_id': 'web-a', 'status': 'NEW_EXPENSE', 'basis': []}]}
    with patch.object(ledger_board, 'current_role', return_value='owner'):
        annotations = ledger_design._google_match_annotations('trip-syn', rows, preview)
        assert annotations['web-a']['display_candidate'] is True
        assert annotations['web-a']['reasons'] == ['날짜']
        assert annotations['web-a']['status'] == 'NEW_EXPENSE'
        assert ledger_design._google_match_annotations('trip-syn', rows, {**preview, 'source_available': False}) == {}
    with patch.object(ledger_board, 'current_role', return_value='viewer'):
        assert ledger_design._google_match_annotations('trip-syn', rows, preview) == {}


def test_display_candidate_does_not_change_copy_status_and_is_visible_on_both_layouts():
    row = {'row_id': 'web-a', 'amount_krw': 900, 'occurred_on': '2026-10-03'}
    preview = {'source_available': True,
               'sheet_rows': [{'amount_krw': 900, 'date': '2026-10-03', 'currency': 'KRW'},
                              {'amount_krw': 900, 'date': '2026-10-03', 'currency': 'KRW'}],
               'results': [{'transaction_id': 'web-a', 'status': 'NEW_EXPENSE', 'basis': []}]}
    with patch.object(ledger_board, 'current_role', return_value='owner'):
        annotations = ledger_design._google_match_annotations('trip-syn', [row], preview)
    assert annotations['web-a']['multiple'] is True
    assert preview['results'][0]['status'] == 'NEW_EXPENSE'
    desktop = ledger_design._table_html([row], kind='expense', selected='', unclassified=False,
                                        match_annotations=annotations)
    mobile = ledger_design._mobile_html([], [row], selected='', unclassified=False,
                                       match_annotations=annotations)
    # Desktop keeps the visible candidate marker and the ambiguity hint.
    assert 'google-match-candidate' in desktop
    assert 'Google 장부 대조 후보' in desktop
    assert '복수 후보' in desktop
    # wave3 rebuild (8cd0e58b) moved the mobile hint into an sr-only span exposing
    # the row's match label; the display candidate never changes the copy status.
    assert "class='list-row li'" in mobile
    assert "<span class='sr'>복사 가능</span>" in mobile


def test_filtered_view_retains_ambiguity_against_other_expenses():
    rows = [{'row_id': key, 'amount_krw': 900, 'occurred_on': '2026-10-03'}
            for key in ('visible', 'filtered-out')]
    preview = {'source_available': True,
               'sheet_rows': [{'amount_krw': 900, 'date': '2026-10-03'}],
               'results': [{'transaction_id': 'visible', 'status': 'NEW_EXPENSE', 'basis': []}]}
    with patch.object(ledger_board, 'current_role', return_value='owner'):
        result = ledger_design._google_match_annotations('trip-syn', rows[:1], preview, rows)
    assert result['visible']['multiple'] is True


def test_copy_conflict_is_not_claimed_as_multiple_display_candidates():
    row = {'row_id': 'a', 'amount_krw': 900, 'occurred_on': '2026-10-03'}
    preview = {'source_available': True, 'sheet_rows': [{'amount_krw': 900, 'date': '2026-10-03'}],
               'results': [{'transaction_id': 'a', 'status': 'REVIEW_CONFLICT', 'basis': []}]}
    with patch.object(ledger_board, 'current_role', return_value='owner'):
        annotations = ledger_design._google_match_annotations('trip-syn', [row], preview)
    markup = ledger_design._table_html([row], kind='expense', selected='', unclassified=False,
                                       match_annotations=annotations)
    assert '중복 확인 필요' in markup
    assert 'Google 장부 대조 후보: 금액+날짜' in markup
    assert '복수 후보' not in markup


def test_web_transaction_row_exposes_bold_candidate_and_reason_accessibly():
    html = ledger_design._table_html(
        [{'row_id': 'web-syn', 'amount_krw': 900, 'occurred_on': '2026-10-03'}],
        kind='expense', selected='', unclassified=False,
        match_annotations={'web-syn': {'reasons': ['날짜'], 'multiple': False}})
    assert 'class="google-match-candidate"' in html
    assert 'Google 장부 대조 후보: 금액+날짜' in html
    assert "aria-describedby='google-match-web-syn'" in html
    mobile = ledger_design._mobile_html(
        [], [{'row_id': 'web-syn', 'amount_krw': 900, 'occurred_on': '2026-10-03'}],
        selected='', unclassified=False,
        match_annotations={'web-syn': {'reasons': ['날짜'], 'multiple': False}})
    # wave3 rebuild (8cd0e58b): mobile exposes the reason in an sr-only span instead
    # of a visible candidate class; the desktop bold marker above is unchanged.
    assert "class='list-row li'" in mobile
    assert "<span class='sr'>금액+날짜</span>" in mobile
