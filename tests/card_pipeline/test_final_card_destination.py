"""Final card destinations are readable without a human work queue or writes."""
import copy

import pytest

from app.card_destination import display_destination, observed_quarter
from webapp.card_actions import next_action


@pytest.mark.parametrize('legacy', ['unclassified', '', None])
def test_legacy_normal_row_has_payment_quarter_without_source_mutation(legacy):
    row = dict(batch_id='synthetic', transaction_id='one', amount_krw=12345,
               approval_date='2026-11-08', posting_date='2026-12-01',
               item='', display_tab_id=legacy, classification_state='needs_review')
    before = copy.deepcopy(row)
    assert display_destination(row) == '2026년 4분기 기타비용'
    action = next_action(row)
    assert not action['required'] and not action['state_label']
    assert '/my-actions' not in action['href']
    assert row == before


def test_real_trip_and_explicit_quarter_preserve_existing_destination():
    row = dict(trip_id='REAL', display_tab_id='REAL', approval_date='2026-11-08')
    assert display_destination(row, {'REAL':'합성 여행'}) == '합성 여행'
    row.update(display_tab_id='quarter:2026:2',trip_id='')
    assert display_destination(row) == '2026년 2분기 기타비용'


@pytest.mark.parametrize('date', ['', 'not-a-date', '2026-02-31'])
def test_unreadable_date_never_invents_current_quarter_or_requests_human(date):
    row = dict(batch_id='b',transaction_id='t',approval_date=date,parse_error='synthetic source error')
    assert observed_quarter(row) is None
    assert display_destination(row) == '기타비용'
    action = next_action(row)
    assert not action['required'] and action['status'] == '원본 오류'
    assert '/my-actions' not in action['href']


def test_source_error_never_turns_a_date_into_a_quarter_destination():
    row = dict(approval_date='2026-11-08', parse_error='amount could not be parsed')
    assert observed_quarter(row) is None
    assert display_destination(row) == '기타비용'


def test_missing_payment_date_uses_actual_posting_date():
    assert observed_quarter({'posting_date':'2026-04-02'}) == ('quarter:2026:2','2026년 2분기 기타비용')


def test_refund_and_duplicate_remain_financial_facts_not_human_tasks():
    row = dict(batch_id='b', transaction_id='t', duplicate_of='original')
    assert next_action(row)['status'] == '중복 제외'
    row.pop('duplicate_of')
    action = next_action(row, {'blocked':'refund_exceeds_original'})
    assert action['status'] == '환불 금액 불일치' and not action['required']
    assert 'refund' in action['protection']


def test_manual_blank_destination_stays_unchanged_while_display_is_other_cost():
    row=dict(trip_id='',display_tab_id='',approval_date='2026-04-02',
             classification_source='user_decision',decided_at='historical decision',
             classification_basis='original manual fact',amount_krw=12345)
    before=copy.deepcopy(row)
    assert display_destination(row) == '2026년 2분기 기타비용'
    assert row == before
