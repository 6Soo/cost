"""Date/amount evidence may replace absent identity, never contradictory evidence."""
import pytest

from app.ota_payments import match_ota_payment_events, pair_check, search_card_candidates
from tests.card_pipeline.test_ota_payments import card, event


def payment(identity='payment', **changes):
    return event(identity, card_last4=None, card_issuer=None, payment_id=None, **changes)


@pytest.mark.parametrize('provider', ['trip', 'agoda', 'booking', 'klook'])
def test_same_day_amount_connects_without_card_or_merchant_hint(provider):
    source = payment(provider=provider)
    row = card()
    assert pair_check(source, row) is None
    result = match_ota_payment_events([source], [row])[0]
    assert result['status'] == 'MATCHED_AUTO'
    assert result['transaction_id'] == row['transaction_id']
    assert search_card_candidates(source, [row])['candidates'][0]['resolution_allowed']
    assert source['card_last4'] is None  # Do not fabricate an observation in the source.


def test_two_equal_bookings_and_distinct_approvals_connect_once_each_stably():
    sources = [payment('one', provider='trip', booking_ref='BOOK1'),
               payment('two', provider='trip', booking_ref='BOOK2')]
    rows = [card('one', approval_number='00002'), card('two', approval_number='00001')]
    first = match_ota_payment_events(sources, rows)
    second = match_ota_payment_events(list(reversed(sources)), list(reversed(rows)))
    assert all(r['status'] == 'MATCHED_AUTO' for r in first)
    assert {r['transaction_id'] for r in first} == {'one', 'two'}
    assert {r['ota_event_id']: r['transaction_id'] for r in first} == {
        r['ota_event_id']: r['transaction_id'] for r in second}


@pytest.mark.parametrize('changes', [
    {'approval_date': '2026-08-02'}, {'amount_krw': 30001},
    {'transaction_direction': 'refund'}, {'duplicate_of': 'original'},
    {'parse_error': 'invalid'}, {'conflict_reason': 'conflict'},
    {'merchant': 'Agoda', 'merchant_normalized': 'agoda'},
])
def test_missing_identity_does_not_override_mismatch_or_row_protection(changes):
    source = payment(provider='trip')
    row = card(**changes)
    assert pair_check(source, row) is not None
    assert not match_ota_payment_events([source], [row])[0].get('transaction_id')


def test_explicit_card_conflict_still_blocks():
    source = event(provider='trip', card_last4='9876')
    assert pair_check(source, card()) == 'card_identity'


@pytest.mark.parametrize('changes', [
    {'paid_on': None}, {'payment_status': 'scheduled', 'evidence_status': 'scheduled'},
    {'evidence_status': 'evidence_conflict'},
    {'currency': 'JPY', 'amount': '9737', 'amount_krw': None},
])
def test_missing_date_or_unverified_payment_or_currency_cannot_be_invented(changes):
    source = payment(provider='trip', **changes)
    assert not match_ota_payment_events([source], [card()])[0].get('transaction_id')


def test_existing_link_reserves_card_and_partial_repeated_group_stays_unallocated():
    sources = [payment('one', provider='trip', booking_ref='BOOK1'),
               payment('two', provider='trip', booking_ref='BOOK2')]
    assert all(not r.get('transaction_id') for r in match_ota_payment_events(sources, [card()]))
    result = match_ota_payment_events([sources[0]], [card()], existing_links={'other': 'card-a'})
    assert not result[0].get('transaction_id')


def test_manual_foreign_payment_confirmation_preserves_original_amount_and_no_auto_fx(tmp_path):
    from app.ota_review import OtaReviewStore
    source = payment(provider='trip', currency='JPY', amount='9737', amount_krw=None)
    row = card(amount_krw=85621)
    assert not match_ota_payment_events([source], [row])[0].get('transaction_id')
    store = OtaReviewStore(tmp_path / 'review.sqlite')
    try:
        preview = store.preview(source, row)
        result = store.confirm(source, row, preview['preview_digest'],
            request_id='owner-foreign', user='owner', allocations={})
        assert result['status'] == 'MATCHED_USER'
        saved = store.event_snapshots()['payment']
        assert saved['amount'] == '9737' and saved['currency'] == 'JPY'
        assert saved['amount_krw'] is None and saved['card_last4'] is None
        assert store.active_rules() == []
        assert match_ota_payment_events([source], [row], existing_links=store.links())[0]['status'] == 'MATCHED_USER'
    finally:
        store.close()


@pytest.mark.parametrize('amount', [None, '', 'NaN', 'Infinity', '0', '-1', 'not-money'])
def test_manual_foreign_confirmation_requires_valid_source_amount(tmp_path, amount):
    from app.ota_review import OtaReviewStore
    source = payment(provider='trip', currency='JPY', amount=amount, amount_krw=None)
    store = OtaReviewStore(tmp_path / 'review.sqlite')
    try:
        preview = store.preview(source, card())
        with pytest.raises(ValueError, match='VERIFIED_PAYMENT_REQUIRED'):
            store.confirm(source, card(), preview['preview_digest'],
                request_id='invalid-foreign', user='owner', allocations={})
        assert store.links() == {}
    finally:
        store.close()
