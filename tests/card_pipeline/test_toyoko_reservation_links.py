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
            'branch_status': 'MATCH',
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


def test_auto_inference_requires_proven_branch_and_stay_date_and_counts_mismatch_competitors():
    no_branch = candidate('c'); no_branch['branch_status'] = 'UNKNOWN'
    assert infer_links([event('e')], {'e': {'candidates': [no_branch]}})['e']['status'] == 'NEEDS_REVIEW'
    other_day = candidate('c'); other_day['stay_date_status'] = 'UNKNOWN'
    assert infer_links([event('e')], {'e': {'candidates': [other_day]}})['e']['status'] == 'NEEDS_REVIEW'
    competitor = candidate('d', 'MISMATCH')
    result = infer_links([event('e')], {'e': {'candidates': [candidate('c'), competitor]}})
    assert result['e']['status'] == 'NEEDS_REVIEW'


def test_reservation_store_is_lazy_separate_idempotent_and_stale_safe(tmp_path):
    from app.ota_review import OtaReviewStore
    store = OtaReviewStore(tmp_path / 'review.sqlite')
    assert not (tmp_path / 'review.sqlite').exists()
    assert store.reservation_links() == {}
    assert not (tmp_path / 'review.sqlite').exists()
    preview = store.reservation_preview(event('e'), {'transaction_id': 'c'})
    saved = store.confirm_reservation(event('e'), {'transaction_id': 'c'}, preview['preview_digest'],
        expected_revision=0, request_id='r1', user='owner')
    assert saved['status'] == 'USER_CONFIRMED'
    assert store.confirm_reservation(event('e'), {'transaction_id': 'c'}, preview['preview_digest'],
        expected_revision=0, request_id='r1', user='owner') == saved
    with pytest.raises(ValueError, match='REQUEST_ID_REUSED'):
        store.confirm_reservation(event('e'), {'transaction_id': 'c'}, 'ignored',
            expected_revision=0, request_id='r1', user='owner')
    with pytest.raises(ValueError, match='STALE'):
        store.confirm_reservation(event('e'), {'transaction_id': 'c'}, 'stale',
            expected_revision=0, request_id='r2', user='owner')
    store.close()
    reopened = OtaReviewStore(tmp_path / 'review.sqlite')
    try:
        relation = reopened.reservation_links()['e']
        assert relation['transaction_id'] == 'c'
        assert relation['event']['amount'] == '37000'
        with pytest.raises(ValueError, match='STALE'):
            reopened.confirm_reservation(event('e'), {'transaction_id': 'c'},
                reopened.reservation_preview(event('e'), {'transaction_id': 'c'})['preview_digest'],
                expected_revision=0, request_id='r3', user='owner')
        with pytest.raises(ValueError, match='RESERVATION_CARD_OCCUPIED'):
            reopened.confirm_reservation(event('other'), {'transaction_id': 'c'},
                reopened.reservation_preview(event('other'), {'transaction_id': 'c'})['preview_digest'],
                expected_revision=0, request_id='r4', user='owner')
    finally:
        reopened.close()


def test_reservation_confirmation_rechecks_payment_and_group_occupancy_inside_store(tmp_path):
    from app.ota_review import OtaReviewStore
    path = tmp_path / 'review.sqlite'
    store = OtaReviewStore(path)
    event_a, card_a = event('e'), {'transaction_id': 'c'}
    preview = store.reservation_preview(event_a, card_a)
    store.confirm_reservation(event_a, card_a, preview['preview_digest'], expected_revision=0,
        request_id='reserve-1', user='owner')
    paid_event = {'ota_event_id': 'paid-event', 'provider': 'synthetic', 'event_type': 'charge',
        'paid_on': '2026-10-01', 'amount': 37000, 'currency': 'KRW', 'amount_krw': 37000,
        'payment_status': 'paid', 'evidence_status': 'paid_verified', 'source_digest': 'p'}
    paid_card = {'transaction_id': 'c', 'amount_krw': 37000, 'approval_date': '2026-10-01',
        'transaction_direction': 'purchase'}
    with pytest.raises(ValueError, match='RESERVATION_CARD_OCCUPIED'):
        p = store.preview(paid_event, paid_card)
        store.confirm(paid_event, paid_card, p['preview_digest'], request_id='paid-1', user='owner', allocations={})
    store.close()


def test_relation_digest_ignores_trip_decisions_but_tracks_card_financial_facts():
    from app.toyoko_reservation_links import relation_digest
    original = {'transaction_id': 'card', 'source_hash': 'raw', 'amount_krw': 40000,
                'transaction_direction': 'purchase', 'trip_id': 'trip-A', 'revision': 2}
    assert relation_digest(event('e'), original) == relation_digest(
        event('e'), {**original, 'trip_id': 'trip-B', 'revision': 19, 'decided_at': 'later'})
    assert relation_digest(event('e'), original) != relation_digest(
        event('e'), {**original, 'amount_krw': 1})
