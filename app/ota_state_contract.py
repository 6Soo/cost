"""Immutable, lossless DTO views for observed OTA event/result/snapshot mappings.

Source evidence: ota_payments emits event fields such as ``ota_event_id``,
``source_ids``, ``event_type``, ``payment_status``, ``evidence_status`` and
``refund_status``; its results use ``status`` for card-payment matching plus
``inferred_link``, ``individual_payment_evidence`` and ``allocation_basis``.
ota_review keeps a separate ``reservation_link`` with its own status,
``amount_status`` and ``payment_verified``. ota_core_projection consumes
canonical snapshots and emits ``core_link`` facts (see
``app/ota_core_projection.py:296-308``); core_link is a card/OTA projection
signal, not an internal ledger record. Payment results are produced separately
in ``app/ota_payments.py``. The caller declares mapping kind; key presence
never selects semantics. MATCHED_* is a payment matching result,
reservation_link.status is a relation state, and snapshot.status is freshness
metadata. No match, relation, evidence, core-link, or freshness value
establishes a ledger posting or bank refund.

This module only snapshots mappings. It never reconciles, infers, aggregates,
assigns travel, posts a ledger entry, or confirms a refund.
"""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, ClassVar

from app.transaction_contract import FieldSlot, UnsupportedValueError


def _field_slots(source: Mapping[str, Any], keys: tuple[str, ...] = ()) -> Mapping[str, FieldSlot]:
    if not isinstance(source, Mapping):
        raise TypeError('fields must be a mapping')
    if any(type(key) is not str for key in source):
        raise UnsupportedValueError('mapping keys must be exact str')
    values = {
        key: source[key] if type(source.get(key)) is FieldSlot else FieldSlot.from_mapping(source, key)
        for key in keys
    }
    values.update({key: value if type(value) is FieldSlot else FieldSlot(True, value)
                   for key, value in source.items() if key not in values})
    return MappingProxyType(values)


def _axis_mapping(values: Mapping[str, FieldSlot]) -> dict[str, Any]:
    result = {}
    for key, slot in values.items():
        if type(key) is not str:
            raise UnsupportedValueError('mapping keys must be exact str')
        safe_slot = slot if type(slot) is FieldSlot else FieldSlot(True, slot)
        if safe_slot.present:
            result[key] = safe_slot.to_value()
    return result


@dataclass(frozen=True)
class _FieldAxis:
    values: Mapping[str, FieldSlot]
    FIELDS: ClassVar[tuple[str, ...]] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, 'values', _field_slots(self.values, self.FIELDS))

    def to_mapping(self) -> dict[str, Any]:
        return _axis_mapping(self.values)


@dataclass(frozen=True)
class OtaIdentityAxis(_FieldAxis):
    FIELDS: ClassVar[tuple[str, ...]] = (
        'ota_event_id', 'event_id', 'provider', 'booking_ref', 'payment_id',
        'payment_event_id', 'source_ids', 'identity_source_ids', 'source_digest',
        'source_digests', 'source_sha256', 'source_binding_ids',
    )


@dataclass(frozen=True)
class OtaEventAxis(_FieldAxis):
    FIELDS: ClassVar[tuple[str, ...]] = (
        'event_type', 'paid_on', 'paid_on_semantics', 'scheduled_for', 'amount',
        'currency', 'amount_krw', 'card_last4', 'card_issuer', 'item',
        'reservation_status', 'payment_status', 'evidence_status', 'evidence_kind',
        'source_inventory', 'authorization_number', 'approval_number',
    )


@dataclass(frozen=True)
class ReservationRelationAxis(_FieldAxis):
    FIELDS: ClassVar[tuple[str, ...]] = (
        'status', 'transaction_id', 'basis', 'amount_status', 'payment_verified',
        'revision', 'event', 'transaction',
    )


@dataclass(frozen=True)
class OtaReservationAxis(_FieldAxis):
    FIELDS: ClassVar[tuple[str, ...]] = ('reservation_link',)


@dataclass(frozen=True)
class CardPaymentVerificationAxis(_FieldAxis):
    FIELDS: ClassVar[tuple[str, ...]] = (
        'status', 'transaction_id', 'candidates', 'reason', 'inferred_link',
        'inference_basis', 'payment_date_verified', 'individual_payment_evidence',
        'allocation_basis', 'group_count', 'reserved_card_ids',
    )


@dataclass(frozen=True)
class TravelAttributionAxis(_FieldAxis):
    FIELDS: ClassVar[tuple[str, ...]] = (
        'service_period', 'period', 'trip_id', 'trip_tab_id', 'trip_code',
    )


@dataclass(frozen=True)
class InternalRecordAxis(_FieldAxis):
    FIELDS: ClassVar[tuple[str, ...]] = ()


@dataclass(frozen=True)
class CoreLinkEvidenceAxis(_FieldAxis):
    FIELDS: ClassVar[tuple[str, ...]] = ('core_link',)


@dataclass(frozen=True)
class RefundEvidenceAxis(_FieldAxis):
    FIELDS: ClassVar[tuple[str, ...]] = ('refund_status',)


@dataclass(frozen=True)
class SnapshotAxis(_FieldAxis):
    FIELDS: ClassVar[tuple[str, ...]] = ('generation', 'fresh', 'enabled', 'status', 'results', 'data')


@dataclass(frozen=True)
class ReservationLinkView:
    """The nested reservation relation; its status is not card payment status."""

    values: Mapping[str, FieldSlot]

    def __post_init__(self) -> None:
        object.__setattr__(self, 'values', _field_slots(self.values, ReservationRelationAxis.FIELDS))

    @classmethod
    def from_mapping(cls, source: Mapping[str, Any]) -> ReservationLinkView:
        return cls(_field_slots(source, ReservationRelationAxis.FIELDS))

    def to_mapping(self) -> dict[str, Any]:
        return _axis_mapping(self.values)


@dataclass(frozen=True)
class OtaStateView:
    identity: OtaIdentityAxis
    event: OtaEventAxis
    reservation: OtaReservationAxis
    card_payment: CardPaymentVerificationAxis
    travel: TravelAttributionAxis
    internal_record: InternalRecordAxis
    core_link_evidence: CoreLinkEvidenceAxis
    refund: RefundEvidenceAxis
    snapshot: SnapshotAxis
    extras: Mapping[str, FieldSlot]

    IDENTITY_FIELDS: ClassVar[tuple[str, ...]] = OtaIdentityAxis.FIELDS
    EVENT_FIELDS: ClassVar[tuple[str, ...]] = OtaEventAxis.FIELDS
    RESERVATION_FIELDS: ClassVar[tuple[str, ...]] = OtaReservationAxis.FIELDS
    PAYMENT_FIELDS: ClassVar[tuple[str, ...]] = CardPaymentVerificationAxis.FIELDS
    TRAVEL_FIELDS: ClassVar[tuple[str, ...]] = TravelAttributionAxis.FIELDS
    INTERNAL_FIELDS: ClassVar[tuple[str, ...]] = InternalRecordAxis.FIELDS
    REFUND_FIELDS: ClassVar[tuple[str, ...]] = RefundEvidenceAxis.FIELDS
    SNAPSHOT_FIELDS: ClassVar[tuple[str, ...]] = SnapshotAxis.FIELDS
    CORE_LINK_FIELDS: ClassVar[tuple[str, ...]] = CoreLinkEvidenceAxis.FIELDS

    def __post_init__(self) -> None:
        required = (
            ('identity', OtaIdentityAxis), ('event', OtaEventAxis),
            ('reservation', OtaReservationAxis),
            ('card_payment', CardPaymentVerificationAxis),
            ('travel', TravelAttributionAxis), ('internal_record', InternalRecordAxis),
            ('core_link_evidence', CoreLinkEvidenceAxis),
            ('refund', RefundEvidenceAxis), ('snapshot', SnapshotAxis),
        )
        if any(type(getattr(self, name)) is not expected for name, expected in required):
            raise TypeError('OTA axes must use their declared DTO type')
        object.__setattr__(self, 'extras', _field_slots(self.extras))

    @classmethod
    def from_mapping(cls, source: Mapping[str, Any], *, kind: str) -> OtaStateView:
        if kind not in ('event', 'result', 'snapshot', 'projection'):
            raise ValueError("kind must be event, result, snapshot, or projection")
        if not isinstance(source, Mapping):
            raise TypeError('source must be a mapping')
        if any(type(key) is not str for key in source):
            raise UnsupportedValueError('mapping keys must be exact str')
        identity_fields = cls.IDENTITY_FIELDS if kind in ('event', 'result', 'projection') else ()
        event_fields = cls.EVENT_FIELDS if kind in ('event', 'result', 'projection') else ()
        reservation_fields = cls.RESERVATION_FIELDS if kind in ('event', 'result') else ()
        payment_fields = cls.PAYMENT_FIELDS if kind == 'result' else (
            tuple(key for key in cls.PAYMENT_FIELDS if key not in ('status', 'transaction_id', 'candidates', 'reason'))
            if kind == 'projection' else ()
        )
        travel_fields = cls.TRAVEL_FIELDS if kind in ('event', 'result', 'projection') else ()
        internal_fields = cls.INTERNAL_FIELDS
        core_link_fields = cls.CORE_LINK_FIELDS if kind == 'projection' else ()
        refund_fields = cls.REFUND_FIELDS if kind in ('event', 'result', 'projection') else ()
        snapshot_fields = cls.SNAPSHOT_FIELDS if kind == 'snapshot' else ()
        groups = (identity_fields, event_fields, reservation_fields, payment_fields,
                  travel_fields, internal_fields, core_link_fields, refund_fields, snapshot_fields)
        known = {key for group in groups for key in group}

        def axis(axis_type: type, keys: tuple[str, ...]) -> Any:
            return axis_type({key: source[key] for key in keys if key in source})

        result = cls(
            identity=axis(OtaIdentityAxis, identity_fields),
            event=axis(OtaEventAxis, event_fields),
            reservation=axis(OtaReservationAxis, reservation_fields),
            card_payment=axis(CardPaymentVerificationAxis, payment_fields),
            travel=axis(TravelAttributionAxis, travel_fields),
            internal_record=axis(InternalRecordAxis, internal_fields),
            core_link_evidence=axis(CoreLinkEvidenceAxis, core_link_fields),
            refund=axis(RefundEvidenceAxis, refund_fields),
            snapshot=axis(SnapshotAxis, snapshot_fields),
            extras={key: value for key, value in source.items() if key not in known},
        )
        return result

    @property
    def reservation_link(self) -> FieldSlot:
        return self.reservation.values['reservation_link']

    @property
    def reservation_relation(self) -> ReservationLinkView | None:
        if not self.reservation_link.present:
            return None
        value = self.reservation_link.to_value()
        return ReservationLinkView.from_mapping(value) if isinstance(value, Mapping) else None

    def to_mapping(self) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for axis in (self.identity, self.event, self.card_payment, self.travel,
                     self.internal_record, self.core_link_evidence, self.refund, self.snapshot):
            result.update(axis.to_mapping())
        result.update(self.reservation.to_mapping())
        result.update(self.extras_mapping())
        return result

    def extras_mapping(self) -> dict[str, Any]:
        return _axis_mapping(self.extras)
