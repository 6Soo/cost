import pytest

from app.toyoko_reservation_links import infer_links


def event(identity, *, group=False, status='confirmed'):
    return {'ota_event_id': identity, 'provider': 'toyoko', 'event_type': 'reservation',
            'reservation_status': status, 'reservation_group_only': group,
            'hotel_name': '토요코인 울산삼산동',
            'service_period': {'starts_on': '2026-10-01', 'ends_on': '2026-10-03'},
            'amount': '37000', 'currency': 'KRW'}


def candidate(identity, amount='MATCH'):
    return {'transaction_id': identity, 'basis': 'RESERVATION_NATIVE_AMOUNT',
            'amount_status': amount, 'stay_date_status': 'MATCH', 'resolution_allowed': False}


def test_only_mutually_unique_matching_candidates_are_inferred():
    result = infer_links([event('e')], {'e': {'candidates': [candidate('c')]}})
    assert result['e'] == {'status': 'INFERRED', 'transaction_id': 'c',
                           'basis': 'RESERVATION_NATIVE_AMOUNT', 'amount_status': 'MATCH',
                           'payment_verified': False}
    assert infer_links([event('e')], {'e': {'candidates': [candidate('c'), candidate('d')]}})['e']['status'] == 'NEEDS_REVIEW'


def test_unknown_amount_can_infer_low_but_mismatch_and_groups_cannot():
    unknown = candidate('c', 'UNKNOWN')
    assert infer_links([event('e')], {'e': {'candidates': [unknown]}})['e']['amount_status'] == 'UNKNOWN'
    assert infer_links([event('e')], {'e': {'candidates': [candidate('c', 'MISMATCH')]}})['e']['status'] == 'NEEDS_REVIEW'
    assert infer_links([event('g', group=True)], {'g': {'candidates': [candidate('c')]}})['g']['status'] == 'NEEDS_REVIEW'


def test_reservation_store_is_lazy_separate_idempotent_and_stale_safe(tmp_path):
    from app.ota_review import OtaReviewStore
    store = OtaReviewStore(tmp_path / 'review.sqlite')
    assert not (tmp_path / 'review.sqlite').exists()
    assert store.reservation_links() == {}
    assert not (tmp_path / 'review.sqlite').exists()
    preview = store.reservation_preview(event('e'), {'transaction_id': 'c'}, allocations={})
    saved = store.confirm_reservation(event('e'), {'transaction_id': 'c'}, preview['preview_digest'],
        expected_revision=0, request_id='r1', request_digest='d1', user='owner', allocations={})
    assert saved['status'] == 'USER_CONFIRMED'
    assert store.confirm_reservation(event('e'), {'transaction_id': 'c'}, 'ignored',
        expected_revision=0, request_id='r1', request_digest='d1', user='owner', allocations={}) == saved
    with pytest.raises(ValueError, match='REQUEST_ID_REUSED'):
        store.confirm_reservation(event('e'), {'transaction_id': 'c'}, 'ignored',
            expected_revision=0, request_id='r1', request_digest='different', user='owner', allocations={})
    with pytest.raises(ValueError, match='STALE'):
        store.confirm_reservation(event('e'), {'transaction_id': 'c'}, 'stale',
            expected_revision=0, request_id='r2', request_digest='d2', user='owner', allocations={})
    store.close()
    reopened = OtaReviewStore(tmp_path / 'review.sqlite')
    try:
        relation = reopened.reservation_links()['e']
        assert relation['transaction_id'] == 'c'
        assert relation['event']['amount'] == '37000'
        with pytest.raises(ValueError, match='STALE'):
            reopened.confirm_reservation(event('e'), {'transaction_id': 'c'},
                reopened.reservation_preview(event('e'), {'transaction_id': 'c'})['preview_digest'],
                expected_revision=0, request_id='r3', request_digest='d3', user='owner', allocations={})
        with pytest.raises(ValueError, match='CARD_ALREADY_OCCUPIED'):
            reopened.confirm_reservation(event('other'), {'transaction_id': 'c'},
                reopened.reservation_preview(event('other'), {'transaction_id': 'c'})['preview_digest'],
                expected_revision=0, request_id='r4', request_digest='d4', user='owner', allocations={})
    finally:
        reopened.close()
