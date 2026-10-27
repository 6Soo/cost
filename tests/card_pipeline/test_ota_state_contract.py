"""Synthetic immutable OTA state adapter contract tests; no runtime I/O."""
from copy import deepcopy
from dataclasses import replace
from datetime import datetime, timedelta, tzinfo
from decimal import Decimal

import pytest

from app.ota_state_contract import (
    CardPaymentVerificationAxis,
    CoreLinkEvidenceAxis,
    OtaIdentityAxis,
    OtaReservationAxis,
    OtaReservationAxis,
    OtaStateView,
    ReservationLinkView,
)
from app.transaction_contract import FieldSlot, UnsupportedValueError


def event(**changes):
    value = {
        'ota_event_id': 'agoda:mail:00001234',
        'provider': 'agoda',
        'booking_ref': 'BOOK-0007',
        'payment_event_id': None,
        'payment_id': 'PAY-0008',
        'source_ids': ['mail:00001234'],
        'identity_source_ids': ['mail:00001234'],
        'source_digest': 'digest-a',
        'source_digests': ['digest-a'],
        'event_type': 'charge',
        'paid_on': '2026-10-01',
        'amount': '120.00',
        'currency': 'USD',
        'amount_krw': None,
        'payment_status': 'paid',
        'evidence_status': 'paid_verified',
        'reservation_status': 'observed',
        'refund_status': 'none_displayed',
        'service_period': {'starts_on': '2026-10-03', 'ends_on': '2026-10-04'},
    }
    value.update(changes)
    return value


def test_event_mapping_roundtrip_preserves_identity_source_amount_and_currency():
    source = event(ota_event_id='000001', booking_ref='0000007', amount='0.00',
                   amount_krw=0, currency='JPY', source_ids=['mail:0001', 'portal:02'])
    view = OtaStateView.from_mapping(source, kind='event')
    assert view.to_mapping() == source
    assert view.identity.values['ota_event_id'].to_value() == '000001'
    assert view.event.values['amount'].to_value() == '0.00'
    assert view.event.values['amount_krw'].to_value() == 0
    assert view.event.values['currency'].to_value() == 'JPY'


def test_payment_status_reservation_relation_and_refund_evidence_are_independent():
    source = event(
        status='MATCHED_AUTO', transaction_id='card:0009', inferred_link=True,
        individual_payment_evidence=True,
        allocation_basis='source_exact',
        reservation_link={
            'status': 'USER_CONFIRMED', 'transaction_id': 'card:0009',
            'basis': 'owner decision', 'amount_status': 'MISMATCH',
            'payment_verified': False, 'revision': 0,
        },
        refund_status='refund_pending',
    )
    view = OtaStateView.from_mapping(source, kind='result')
    assert view.to_mapping() == source
    assert view.card_payment.values['status'].to_value() == 'MATCHED_AUTO'
    relation = view.reservation_relation
    assert relation is not None
    assert relation.values['status'].to_value() == 'USER_CONFIRMED'
    assert relation.values['amount_status'].to_value() == 'MISMATCH'
    assert relation.values['payment_verified'].to_value() is False
    assert view.refund.values['refund_status'].to_value() == 'refund_pending'
    assert 'ledger_posted' not in view.to_mapping()
    assert 'refund_completed' not in view.to_mapping()


def test_explicit_result_kind_does_not_infer_snapshot_from_extra_keys_or_event_id():
    source = {
        'status': 'MATCHED_USER',
        'results': [{'status': 'unrelated'}],
        'data': {'status': 'also unrelated'},
    }
    view = OtaStateView.from_mapping(source, kind='result')
    assert view.card_payment.values['status'].to_value() == 'MATCHED_USER'
    assert view.extras_mapping() == {'results': source['results'], 'data': source['data']}
    assert view.to_mapping() == source

    event_view = OtaStateView.from_mapping({'status': 'unobserved'}, kind='event')
    assert event_view.extras_mapping() == {'status': 'unobserved'}


def test_public_reservation_axes_preserve_unknown_fields_losslessly():
    relation_input = {'status': 'STALE', 'future_relation': {'items': [1]}}
    relation = ReservationLinkView(relation_input)
    relation_input['future_relation']['items'].append(2)
    assert relation.to_mapping() == {'status': 'STALE', 'future_relation': {'items': [1]}}

    axis_input = {'reservation_link': {'status': 'INFERRED'}, 'future_axis': {'v': [3]}}
    axis = OtaReservationAxis(axis_input)
    axis_input['future_axis']['v'].append(4)
    assert axis.to_mapping() == {
        'reservation_link': {'status': 'INFERRED'}, 'future_axis': {'v': [3]}}


@pytest.mark.parametrize('changes', [
    {'status': 'MATCHED_USER', 'inferred_link': False},
    {'status': 'MATCHED_AUTO', 'inferred_link': False,
     'individual_payment_evidence': True, 'allocation_basis': 'exact_evidence'},
    {'status': 'MATCHED_AUTO', 'inferred_link': True, 'inference_basis': 'raw basis'},
    {'status': 'MATCHED_AUTO', 'individual_payment_evidence': False,
     'allocation_basis': 'frozen_user_confirmed_order', 'group_count': {'ota': 2, 'cards': 2}},
])
def test_manual_inferred_exact_and_group_only_result_values_are_not_reinterpreted(changes):
    source = event(**changes)
    view = OtaStateView.from_mapping(source, kind='result')
    assert view.to_mapping() == source
    for key, value in changes.items():
        if key in view.card_payment.values:
            assert view.card_payment.values[key].to_value() == value


def test_cancellation_stale_and_unknown_status_values_roundtrip():
    source = event(event_type='refund', reservation_status='cancelled',
                   refund_status='refund_requested', status='future_match_state',
                   reservation_link={'status': 'STALE', 'amount_status': 'UNKNOWN',
                                     'payment_verified': False, 'source_digest': 'old'})
    view = OtaStateView.from_mapping(source, kind='event')
    assert view.to_mapping() == source
    assert view.refund.values['refund_status'].to_value() == 'refund_requested'
    assert view.reservation_relation.values['status'].to_value() == 'STALE'
    assert view.extras_mapping()['status'] == 'future_match_state'


def test_absent_refund_state_and_present_none_remain_distinct():
    source_without_refund = event()
    del source_without_refund['refund_status']
    absent = OtaStateView.from_mapping(source_without_refund, kind='event')
    present_none = OtaStateView.from_mapping(event(refund_status=None), kind='event')
    assert not absent.refund.values['refund_status'].present
    assert present_none.refund.values['refund_status'].present
    assert present_none.refund.values['refund_status'].to_value() is None
    assert 'refund_status' not in absent.to_mapping()
    assert present_none.to_mapping()['refund_status'] is None


def test_snapshot_and_core_link_axes_keep_raw_values_separate_from_ledger():
    source = {
        'generation': 0, 'enabled': True, 'fresh': False, 'status': 'stale',
        'results': [{'ota_event_id': 'event-1', 'status': 'MATCHED_AUTO'}],
        'data': {'events': [event()], 'links': {}},
        'unknown_projection': {'value': [1, 2]},
    }
    view = OtaStateView.from_mapping(source, kind='snapshot')
    assert view.to_mapping() == source
    assert view.snapshot.values['status'].to_value() == 'stale'
    assert view.internal_record.to_mapping() == {}
    projection = OtaStateView.from_mapping({'core_link': True}, kind='projection')
    assert projection.core_link_evidence.values['core_link'].to_value() is True
    assert projection.internal_record.to_mapping() == {}
    assert 'ledger_posted' not in projection.to_mapping()
    assert 'refund_completed' not in projection.to_mapping()
    assert view.extras_mapping() == {'unknown_projection': {'value': [1, 2]}}


def test_nested_alias_mutations_and_public_axis_constructors_are_isolated():
    source = event(source_ids=['source-a'], reservation_link={
        'status': 'INFERRED', 'evidence': {'items': ['original']}})
    expected = deepcopy(source)
    view = OtaStateView.from_mapping(source, kind='event')
    source['reservation_link']['evidence']['items'].append('input mutation')
    output = view.to_mapping()
    assert output == expected
    output['reservation_link']['evidence']['items'].append('output mutation')
    assert view.to_mapping() == expected
    with pytest.raises(TypeError):
        view.identity.values['source_ids'].value[0] = 'blocked'

    raw_axis = {'status': {'nested': [1]}}
    axis = CardPaymentVerificationAxis(raw_axis)
    raw_axis['status']['nested'].append(2)
    assert axis.values['status'].to_value() == {'nested': [1]}
    direct = OtaIdentityAxis({'ota_event_id': FieldSlot(True, {'id': ['original']})})
    with pytest.raises(TypeError):
        direct.values['ota_event_id'].value['id'][0] = 'blocked'

    relation_source = {'status': 'INFERRED', 'event': {'ids': ['event-a']}}
    relation = ReservationLinkView(relation_source)
    relation_source['event']['ids'].append('mutated')
    assert relation.to_mapping() == {'status': 'INFERRED', 'event': {'ids': ['event-a']}}

    base = OtaStateView.from_mapping(event(), kind='event')
    direct_extras = {'mutable_extra': {'items': ['before']}}
    direct = OtaStateView(
        identity=base.identity, event=base.event, reservation=base.reservation,
        card_payment=base.card_payment, travel=base.travel,
        internal_record=base.internal_record, core_link_evidence=base.core_link_evidence,
        refund=base.refund,
        snapshot=base.snapshot, extras=direct_extras,
    )
    direct_extras['mutable_extra']['items'].append('after')
    assert direct.extras_mapping() == {'mutable_extra': {'items': ['before']}}


def test_amount_decimal_and_supported_field_slot_domain_roundtrip():
    source = event(amount=Decimal('12.3400'), amount_krw=-1,
                   currency='KRW', opaque_bytes=bytearray(b'raw'))
    view = OtaStateView.from_mapping(source, kind='event')
    result = view.to_mapping()
    assert result == source
    result['opaque_bytes'][0] = ord('x')
    assert view.to_mapping()['opaque_bytes'] == bytearray(b'raw')
    slot = FieldSlot(True, Decimal('1.00'))
    assert slot.to_value() == Decimal('1.00')


def test_unsupported_nested_value_is_rejected_without_private_helper_use():
    cyclic = {}
    cyclic['self'] = cyclic
    with pytest.raises(UnsupportedValueError, match='cyclic containers'):
        OtaStateView.from_mapping(event(extra=cyclic), kind='event')


def test_exact_string_keys_and_supported_value_guards_are_reused():
    class StringKey(str):
        pass

    source = event()
    source[StringKey('extension')] = 'value'
    with pytest.raises(UnsupportedValueError, match='mapping keys must be exact str'):
        OtaStateView.from_mapping(source, kind='event')

    class MutableTimezone(tzinfo):
        def utcoffset(self, value):
            return timedelta(0)

        def dst(self, value):
            return timedelta(0)

    with pytest.raises(UnsupportedValueError, match='unsupported value type'):
        OtaStateView.from_mapping(event(extra=datetime(
            2026, 10, 1, tzinfo=MutableTimezone())), kind='event')
    with pytest.raises(UnsupportedValueError, match='unsupported value type'):
        OtaStateView.from_mapping(event(extra=object()), kind='event')


def test_direct_view_preserves_unknown_fields_in_reservation_axis():
    base = OtaStateView.from_mapping({}, kind='result')
    source = {'reservation_link': None, 'future_relation_fact': {'items': [1]}}
    view = replace(base, reservation=OtaReservationAxis(source))
    expected = deepcopy(source)
    source['future_relation_fact']['items'].append(2)
    assert view.to_mapping() == expected
