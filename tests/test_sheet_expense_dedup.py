from copy import deepcopy

import pytest

from app.sheet_expense_dedup import reconcile


def cost(**overrides):
    row = {'transaction_id': 'cost-1', 'trip_id': 'trip-a', 'date': '2026-05-02',
           'approval_date': '2026-05-02', 'merchant': 'Cafe North', 'item': '식비',
           'description': 'coffee', 'amount_krw': 12000, 'currency': 'KRW',
           'transaction_direction': 'purchase', 'card_tail': '1234',
           'issuer': 'Bank A', 'approval_number': 'AUTH-1'}
    row.update(overrides)
    return row


def manual(**overrides):
    row = {'trip_id': 'trip-a', 'sheet_id': 'sheet-a', 'source': 'manual',
           'row_number': 12, 'date': '2026-05-02', 'payee': 'Cafe North',
           'category': '식비', 'description': 'coffee', 'amount_krw': 12000,
           'currency': 'KRW', 'transaction_direction': 'purchase',
           'card_tail': '1234', 'issuer': 'Bank A', 'approval_number': 'AUTH-1'}
    row.update(overrides)
    return row


def test_unique_approval_match_and_manual_values_are_only_reported():
    source = [manual()]
    before = deepcopy(source)
    out = reconcile([cost()], source, trip_id='trip-a')
    result = out['results'][0]
    assert result['status'] == 'MATCHED_MANUAL'
    assert result['basis'] == ['approval_number']
    assert result['row_number'] == 12
    assert source == before
    assert out['counts']['MATCHED_MANUAL'] == 1


def test_exact_composite_match_without_approval_number_is_allowed():
    out = reconcile([cost(approval_number='')],
                    [manual(approval_number='')], trip_id='trip-a')
    assert out['results'][0]['status'] == 'MATCHED_MANUAL'
    assert out['results'][0]['basis'] == ['amount_date_merchant']


def test_merchant_only_or_multiple_candidates_are_held():
    result = reconcile([cost(approval_number='')],
                       [manual(approval_number='', date='2026-05-03')],
                       trip_id='trip-a')['results'][0]
    assert result['status'] == 'REVIEW_CONFLICT'
    duplicated = reconcile([cost(approval_number='')],
                           [manual(approval_number=''), manual(approval_number='',
                            row_number=13, source='second')], trip_id='trip-a')['results'][0]
    assert duplicated['status'] == 'REVIEW_CONFLICT'


@pytest.mark.parametrize('change', [
    {'trip_id': 'trip-b'}, {'amount_krw': 12001}, {'currency': 'USD'},
    {'transaction_direction': 'refund'}, {'card_tail': '9999'},
])
def test_identity_core_conflict_never_matches(change):
    out = reconcile([cost()], [manual(**change)], trip_id='trip-a')
    assert out['results'][0]['status'] == 'REVIEW_CONFLICT'


def test_same_source_identity_on_another_trip_is_held():
    result = reconcile([cost()], [manual(trip_id='trip-b')],
                       trip_id='trip-a')['results'][0]
    assert result['status'] == 'REVIEW_CONFLICT'
    assert result['reason'] == 'TRANSACTION_ON_DIFFERENT_TRIP'


def test_approval_number_does_not_cross_card_identity():
    result = reconcile([cost(card_tail='1234')],
                       [manual(approval_number='AUTH-1', card_tail='9999')],
                       trip_id='trip-a')['results'][0]
    assert result['status'] == 'REVIEW_CONFLICT'


def test_unrelated_same_day_row_does_not_block_strong_unique_match():
    unrelated = manual(approval_number='AUTH-OTHER', payee='Different Shop',
                       row_number=13)
    result = reconcile([cost()], [manual(), unrelated], trip_id='trip-a')['results'][0]
    assert result['status'] == 'MATCHED_MANUAL'
    assert result['basis'] == ['approval_number']


def test_occurred_on_aliases_sheet_date_on_valid_calendar_day():
    result = reconcile([cost(approval_number='', date='', occurred_on='2026-05-02')],
                       [manual(approval_number='')], trip_id='trip-a')['results'][0]
    assert result['status'] == 'MATCHED_MANUAL'


def test_invalid_dates_do_not_count_as_date_identity():
    result = reconcile([cost(approval_number='', date='2026-99-99', approval_date='')],
                       [manual(approval_number='', date='2026-99-99')],
                       trip_id='trip-a')['results'][0]
    assert result['status'] == 'REVIEW_CONFLICT'


def test_stable_id_does_not_override_explicit_card_conflict():
    row = manual(transaction_id='cost-1', stable_id='cost-1', card_tail='9999')
    result = reconcile([cost()], [row], trip_id='trip-a')['results'][0]
    assert result['status'] == 'REVIEW_CONFLICT'


def test_explicit_cash_or_points_evidence_cannot_match_card_cost():
    for evidence in ('cash', 'points', '합산 결제', '분할 결제'):
        result = reconcile([cost()], [manual(evidence=evidence)],
                           trip_id='trip-a')['results'][0]
        assert result['status'] == 'REVIEW_CONFLICT'
    both_marked = reconcile([cost(evidence='cash')], [manual(evidence='cash')],
                            trip_id='trip-a')['results'][0]
    assert both_marked['status'] == 'REVIEW_CONFLICT'


def test_unrelated_same_day_expense_does_not_block_composite_match():
    result = reconcile([cost(approval_number='')],
                       [manual(approval_number=''),
                        manual(approval_number='', payee='Other merchant',
                               row_number=13, source='second')],
                       trip_id='trip-a')['results'][0]
    assert result['status'] == 'MATCHED_MANUAL'


def test_existing_link_index_blocks_row_occupied_outside_cost_subset():
    sheet = manual(stable_id='sheet-row-occupied')
    first = reconcile([cost()], [sheet], trip_id='trip-a')['results'][0]
    links = {
        'other-cost-not-in-this-batch': {
            'sheet_row_key': first['sheet_row_key'],
            'sheet_fingerprint': first['sheet_fingerprint'],
        }
    }
    result = reconcile([cost()], [sheet], trip_id='trip-a',
                        existing_links=links)['results'][0]
    assert result['status'] == 'REVIEW_CONFLICT'
    assert result['reason'] == 'SHEET_ROW_OCCUPIED_BY_EXISTING_LINK'


def test_result_contains_full_trip_sheet_source_boundary_and_override_provenance():
    matched = reconcile([cost()], [manual()], trip_id='trip-a',
                        source_metadata={'sheet_id': 'sheet-a', 'source': 'read-snapshot'})['results'][0]
    assert (matched['trip_id'], matched['sheet_id'], matched['source']) == (
        'trip-a', 'sheet-a', 'manual')
    assert matched['manual_override'] is False
    unavailable = reconcile([cost()], [], trip_id='trip-a', source_available=False,
                            source_metadata={'sheet_id': 'sheet-a', 'source': 'snapshot'})['results'][0]
    assert (unavailable['trip_id'], unavailable['sheet_id'], unavailable['source']) == (
        'trip-a', 'sheet-a', 'snapshot')


def test_prior_user_manual_link_is_flagged_separately_from_auto_match():
    sheet = manual(stable_id='sheet-row-7')
    first = reconcile([cost()], [sheet], trip_id='trip-a')['results'][0]
    link = {'cost-1': {'sheet_row_key': first['sheet_row_key'],
                       'sheet_fingerprint': first['sheet_fingerprint'],
                       'manual_override': True}}
    result = reconcile([cost()], [sheet], trip_id='trip-a',
                       existing_links=link)['results'][0]
    assert result['status'] == 'MATCHED_EXISTING'
    assert result['manual_override'] is True


def test_prior_manual_link_wins_reverse_row_claim_conflict():
    sheet = manual(stable_id='sheet-row-7')
    first = reconcile([cost()], [sheet], trip_id='trip-a')['results'][0]
    link = {'cost-1': {'sheet_row_key': first['sheet_row_key'],
                       'sheet_fingerprint': first['sheet_fingerprint'],
                       'manual_override': True}}
    result = reconcile([cost(transaction_id='cost-1'),
                        cost(transaction_id='cost-2')], [sheet], trip_id='trip-a',
                       existing_links=link)['results']
    assert result[0]['status'] == 'MATCHED_EXISTING'
    assert result[0]['manual_override'] is True
    assert result[1]['status'] == 'REVIEW_CONFLICT'


def test_content_differences_are_reported_without_mutating_sheet_row():
    row = manual(category='교통비', description='edited manually')
    before = deepcopy(row)
    result = reconcile([cost()], [row], trip_id='trip-a')['results'][0]
    assert result['status'] == 'MATCHED_MANUAL'
    assert result['differences']['category'] == {'manual': '교통비', 'cost': '식비'}
    assert result['differences']['description']['manual'] == 'edited manually'
    assert row == before


def test_existing_link_is_revalidated_by_fingerprint_and_key():
    sheet = manual(stable_id='sheet-row-7')
    first = reconcile([cost()], [sheet], trip_id='trip-a')['results'][0]
    link = {'cost-1': {'sheet_row_key': first['sheet_row_key'],
                       'sheet_fingerprint': first['sheet_fingerprint']}}
    assert reconcile([cost()], [sheet], trip_id='trip-a',
                     existing_links=link)['results'][0]['status'] == 'MATCHED_EXISTING'
    moved_or_edited = dict(sheet, description='changed')
    assert reconcile([cost()], [moved_or_edited], trip_id='trip-a',
                     existing_links=link)['results'][0]['reason'] == 'EXISTING_LINK_STALE'


def test_single_manual_row_cannot_be_claimed_by_two_cost_rows():
    rows = [cost(transaction_id='cost-1'), cost(transaction_id='cost-2')]
    out = reconcile(rows, [manual()], trip_id='trip-a')
    assert [r['status'] for r in out['results']] == ['REVIEW_CONFLICT'] * 2
    assert out['counts']['REVIEW_CONFLICT'] == 2


def test_source_unavailable_blocks_all_cost_rows():
    out = reconcile([cost(), cost(transaction_id='cost-2')], [],
                    trip_id='trip-a', source_available=False)
    assert [r['status'] for r in out['results']] == ['SOURCE_UNAVAILABLE'] * 2


def test_row_number_is_not_the_sheet_key():
    one, two = manual(stable_id='row-a'), manual(stable_id='row-b')
    result = reconcile([cost(approval_number='')], [one, two],
                       trip_id='trip-a')['results'][0]
    assert result['sheet_row_key'] == ''  # ambiguous candidates produce no selected key
    assert one['row_number'] == two['row_number']
