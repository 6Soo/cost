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
    snapshot = {'trips': [], 'sources': {}}
    payload = {'trips': [{'key': 'trip-key', 'chosen_source': 'main', 'review': [],
                          'copies': {'main': {'layout': 'rev', 'expense': {'verified': True}}}}],
              'sources': {'main': {'status': 'ok', 'stale': False}}}
    with patch.object(ledger_board, 'current_role', return_value='owner'), \
            patch.object(google_ledger_page, 'enabled', return_value=True), \
            patch.object(google_ledger_page, 'snapshot_path', return_value='synthetic-snapshot'), \
            patch.object(google_ledger_page, 'rows_path', return_value='synthetic-rows'), \
            patch.object(google_ledger_page, 'load_mapping', return_value={'trip-key': 'trip-syn'}), \
            patch.object(google_ledger_page.google_authority, 'load_consistent', return_value=(snapshot, {})), \
            patch.object(google_ledger_page, 'owner_payload', return_value=payload), \
            patch.object(google_ledger_page, 'load_choices', return_value={'choices': {'trip-key': 'main'}}), \
            patch.object(google_ledger_page, 'owner_rows', return_value={
                'expense': [{'amount': 900, 'date': '2026-10-03'}]}):
        annotations = ledger_design._google_match_annotations('trip-syn', rows)
    assert annotations == {'web-a': {'reasons': ['날짜'], 'multiple': False}}
    with patch.object(ledger_board, 'current_role', return_value='viewer'):
        assert ledger_design._google_match_annotations('trip-syn', rows) == {}


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
    assert "class='li google-match-candidate'" in mobile
    assert 'Google 장부 대조 후보: 금액+날짜' in mobile
