"""Synthetic adapter boundary tests; no database or runtime service is used."""
from copy import deepcopy
from datetime import date, datetime, time, timedelta, timezone, tzinfo
from decimal import Decimal

import pytest

from app.transaction_contract import (
    FieldSlot,
    IdentityAxis,
    TransactionStateView,
    UnsupportedValueError,
)


def _purchase(**updates):
    row = {
        'transaction_id': 'issuer:00001234:purchase:01',
        'source_hash': 'source-hash-a',
        'batch_id': 'batch-a',
        'issuer': 'issuer',
        'card_tail': '0042',
        'card_kind': 'corporate',
        'row_index': 1,
        'transaction_direction': 'purchase',
        'transaction_kind': '승인',
        'approval_number': '00001234',
        'original_approval_number': '',
        'approval_date': '2026-10-27',
        'posting_date': '2026-10-28',
        'merchant': 'synthetic merchant',
        'merchant_normalized': 'synthetic merchant',
        'amount_krw': 1000,
        'foreign_amount': '',
        'foreign_currency': '',
        'description_raw': '',
        'raw_row_json': '{}',
        'duplicate_of': None,
        'conflict_reason': '',
        'parse_error': '',
        'classification_state': 'classified',
        'classification_source': 'rule',
        'classification_basis': 'existing rule evidence',
        'item': 'lodging',
        'description': '',
        'display_tab_id': 'trip-tab-existing',
        'trip_id': 'trip-existing',
        'revision': 3,
        'created_at': '2026-10-28T01:02:03Z',
    }
    row.update(updates)
    return row


def test_purchase_with_multiple_partial_cancellations_roundtrips_losslessly():
    purchase = _purchase()
    refund_one = _purchase(
        transaction_id='issuer:cancel:0001', transaction_direction='cancellation',
        transaction_kind='부분취소', approval_number='00007890',
        original_approval_number='00001234', amount_krw=-300,
        classification_state='needs_review', classification_source='',
        trip_id='', display_tab_id='',
    )
    refund_two = _purchase(
        transaction_id='issuer:cancel:0002', transaction_direction='cancellation',
        transaction_kind='부분취소', approval_number='00007891',
        original_approval_number='00001234', amount_krw=-800,
        classification_state='needs_review', classification_source='',
        trip_id='', display_tab_id='',
    )
    for snapshot in (purchase, refund_one, refund_two):
        assert TransactionStateView.from_mapping(snapshot).to_mapping() == snapshot


def test_over_refund_and_hold_flags_are_preserved_without_policy_calculation():
    first = _purchase(transaction_direction='cancellation', amount_krw=-700,
                      original_approval_number='00001234', review_hold={'kind': 'user_hold'})
    second = _purchase(transaction_direction='cancellation', amount_krw=-700,
                       original_approval_number='00001234', review_hold={'kind': 'refund_pending'})
    for row in (first, second):
        assert TransactionStateView.from_mapping(row).to_mapping() == row
    # The adapter deliberately does not aggregate refunds or decide eligibility.


def test_duplicate_and_conflict_flags_remain_independent_raw_values():
    row = _purchase(duplicate_of='issuer:prior:0001', conflict_reason='source drift',
                    parse_error='amount parse warning', classification_state='needs_review')
    assert TransactionStateView.from_mapping(row).to_mapping() == row


def test_inferred_and_user_decision_axes_do_not_invent_trip_assignment():
    inferred = _purchase(classification_source='AUTO_INFERRED', trip_id='', display_tab_id='')
    decided = _purchase(classification_source='user_decision', decided=True,
                        decided_at='2026-10-28T01:02:03Z', trip_id='trip-manual')
    inferred_view = TransactionStateView.from_mapping(inferred)
    decided_view = TransactionStateView.from_mapping(decided)
    assert inferred_view.to_mapping() == inferred
    assert decided_view.to_mapping() == decided
    assert inferred_view.classification.values['trip_id'].to_value() == ''
    assert not inferred_view.user_decision.values['decided'].present
    assert decided_view.user_decision.values['decided'].to_value() is True


def test_unknown_state_and_extra_fields_roundtrip_without_coercion():
    row = _purchase(classification_state='future_unrecognized_state',
                    vendor_extension={'opaque': [1, None, 'x']}, unknown_flag=False)
    view = TransactionStateView.from_mapping(row)
    assert view.to_mapping() == row
    assert view.classification.values['classification_state'].to_value() == 'future_unrecognized_state'
    assert set(view.extras) == {'vendor_extension', 'unknown_flag'}


def test_missing_none_zero_negative_and_leading_zero_values_are_distinct():
    row = {
        'transaction_id': '000000', 'approval_number': '00001234',
        'original_approval_number': None, 'amount_krw': 0,
        'foreign_amount': '-0.25', 'foreign_currency': 'USD',
        'revision': 0,
    }
    view = TransactionStateView.from_mapping(row)
    assert view.to_mapping() == row
    assert not view.identity.values['issuer'].present
    assert view.source.values['original_approval_number'].present
    assert view.source.values['original_approval_number'].to_value() is None
    assert view.source.values['amount_krw'].to_value() == 0
    assert view.source.values['foreign_amount'].to_value() == '-0.25'
    assert view.identity.values['transaction_id'].to_value() == '000000'


def test_input_and_output_mutations_cannot_change_dto_snapshot():
    source = _purchase(raw_row={'cells': ['original']}, extension=[{'value': 1}])
    expected = deepcopy(source)
    view = TransactionStateView.from_mapping(source)
    source['raw_row']['cells'].append('mutated input')
    source['extension'][0]['value'] = 99
    first = view.to_mapping()
    assert first == expected
    first['raw_row']['cells'].append('mutated output')
    first['extension'][0]['value'] = 100
    assert view.to_mapping() == expected
    with pytest.raises(TypeError):
        view.source.values['raw_row'].value['cells'] = 'forbidden'
    with pytest.raises(TypeError):
        view.extras['extension'].value[0]['value'] = 'forbidden'


def test_bytearray_and_direct_field_slot_are_immutable_and_lossless():
    source_bytes = bytearray(b'abc')
    original = {'blob': source_bytes, 'extension': {'nested': [1]}}
    slot = FieldSlot(True, {'nested': [1]})
    view = TransactionStateView.from_mapping(original)
    source_bytes[0] = ord('z')
    assert view.to_mapping() == {'blob': bytearray(b'abc'), 'extension': {'nested': [1]}}
    output = view.to_mapping()
    output['blob'][0] = ord('x')
    assert view.to_mapping()['blob'] == bytearray(b'abc')
    with pytest.raises(TypeError):
        slot.value['nested'][0] = 2
    slot_output = slot.to_value()
    slot_output['nested'].append(2)
    assert slot.to_value() == {'nested': [1]}


def test_decimal_and_dates_are_immutable_supported_values():
    row = _purchase(extra_amount=Decimal('1.2300'), effective_date=date(2026, 10, 28),
                    effective_datetime=datetime(2026, 10, 28, tzinfo=timezone.utc),
                    effective_time=time(1, 2, tzinfo=timezone.utc),
                    elapsed=timedelta(seconds=1))
    assert TransactionStateView.from_mapping(row).to_mapping() == row


def test_custom_values_and_cycles_fail_with_generic_safe_errors():
    class MutableExtension:
        pass

    custom = MutableExtension()
    with pytest.raises(UnsupportedValueError) as unsupported:
        TransactionStateView.from_mapping(_purchase(extra=custom))
    assert str(unsupported.value) == 'unsupported value type'
    assert type(custom).__name__ not in str(unsupported.value)

    cyclic = []
    cyclic.append(cyclic)
    with pytest.raises(UnsupportedValueError, match='cyclic containers'):
        TransactionStateView.from_mapping(_purchase(raw_row=cyclic))


def test_public_axis_and_transaction_constructors_snapshot_mutable_mappings():
    raw_axis = {'custom': {'nested': [1]}}
    axis = IdentityAxis(raw_axis)
    raw_axis['custom']['nested'].append(2)
    assert axis.values['custom'].to_value() == {'nested': [1]}

    base = TransactionStateView.from_mapping(_purchase())
    raw_extras = {'direct_extra': {'values': [1]}}
    direct = TransactionStateView(
        identity=base.identity,
        source=base.source,
        integrity=base.integrity,
        classification=base.classification,
        user_decision=base.user_decision,
        revision=base.revision,
        extras=raw_extras,
    )
    raw_extras['direct_extra']['values'].append(2)
    assert direct.extras['direct_extra'].to_value() == {'values': [1]}
    exposed = direct.to_mapping()
    exposed['direct_extra']['values'].append(3)
    assert direct.to_mapping()['direct_extra'] == {'values': [1]}


def test_non_exact_string_mapping_keys_are_rejected_without_type_disclosure():
    class MutableStringKey(str):
        pass

    key = MutableStringKey('extension')
    row = _purchase()
    row[key] = 'value'
    with pytest.raises(UnsupportedValueError) as error:
        TransactionStateView.from_mapping(row)
    assert str(error.value) == 'mapping keys must be exact str'
    assert type(key).__name__ not in str(error.value)


def test_mutable_custom_tzinfo_is_rejected_for_datetime_and_time():
    class MutableTimezone(tzinfo):
        def __init__(self):
            self.offset = timedelta(hours=1)

        def utcoffset(self, value):
            return self.offset

        def dst(self, value):
            return timedelta(0)

    custom_timezone = MutableTimezone()
    for value in (datetime(2026, 10, 28, tzinfo=custom_timezone),
                  time(1, 2, tzinfo=custom_timezone)):
        with pytest.raises(UnsupportedValueError) as error:
            FieldSlot(True, value)
        assert str(error.value) == 'unsupported value type'
        assert type(custom_timezone).__name__ not in str(error.value)
