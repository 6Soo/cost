"""Pure immutable transaction state DTO and lossless mapping adapter.

Field groups follow ``transactions`` in app/db.py and the row projection in
app/review.py: source facts, integrity flags, classification, user decision,
and revision stay independent. Refund links and ledger/hold facts are preserved
only when supplied as mapping extras; this module never derives them. Supported
values are SQL/JSON scalars and nested built-in dict/list/tuple/set containers,
bytearray snapshots, Decimal, exact ``date``/``datetime``/``time``/``timedelta``
values, and exact ``timezone`` or stdlib ``ZoneInfo`` timezone objects. Datetime
and time values may be naive or use only those known immutable timezone types.
Other object types and cyclic containers raise a generic UnsupportedValueError;
the original object and its type name are not included in the error. Transaction
schema columns are projected explicitly; additional runtime projection fields and
future columns remain losslessly available in extras.
"""
from __future__ import annotations

from collections.abc import Iterator, Mapping
from copy import deepcopy
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal
from typing import Any, ClassVar
from zoneinfo import ZoneInfo


@dataclass(frozen=True)
class _FrozenMapping(Mapping):
    entries: tuple[tuple[Any, Any], ...]

    def __getitem__(self, key: Any) -> Any:
        for entry_key, value in self.entries:
            if entry_key == key:
                return value
        raise KeyError(key)

    def __iter__(self) -> Iterator[Any]:
        return (key for key, _ in self.entries)

    def __len__(self) -> int:
        return len(self.entries)


@dataclass(frozen=True)
class _FrozenSequence:
    kind: str
    values: tuple[Any, ...]


@dataclass(frozen=True)
class _FrozenSet:
    kind: str
    values: frozenset[Any]


@dataclass(frozen=True)
class _FrozenByteArray:
    value: bytes


class UnsupportedValueError(ValueError):
    """A value is outside the adapter's immutable, lossless type contract."""


def _freeze(value: Any, active: set[int] | None = None) -> Any:
    supported_immutable = (type(None), bool, int, float, str, bytes,
                           Decimal, date, datetime, time, timedelta, timezone, ZoneInfo)
    if type(value) in supported_immutable:
        if type(value) in (datetime, time):
            tz = value.tzinfo
            if tz is not None and type(tz) not in (timezone, ZoneInfo):
                raise UnsupportedValueError('unsupported value type')
        return deepcopy(value)
    if type(value) is bytearray:
        return _FrozenByteArray(bytes(value))
    if type(value) not in (dict, list, tuple, set, frozenset):
        raise UnsupportedValueError('unsupported value type')
    active = set() if active is None else active
    identity = id(value)
    if identity in active:
        raise UnsupportedValueError('cyclic containers are unsupported')
    active.add(identity)
    try:
        if type(value) is dict:
            return _FrozenMapping(tuple((_freeze(k, active), _freeze(v, active))
                                        for k, v in value.items()))
        if type(value) in (list, tuple):
            kind = 'list' if type(value) is list else 'tuple'
            return _FrozenSequence(kind, tuple(_freeze(v, active) for v in value))
        kind = 'set' if type(value) is set else 'frozenset'
        return _FrozenSet(kind, frozenset(_freeze(v, active) for v in value))
    finally:
        active.remove(identity)


def _thaw(value: Any) -> Any:
    if isinstance(value, _FrozenByteArray):
        return bytearray(value.value)
    if isinstance(value, _FrozenMapping):
        return {_thaw(k): _thaw(v) for k, v in value.entries}
    if isinstance(value, _FrozenSequence):
        values = [_thaw(v) for v in value.values]
        return values if value.kind == 'list' else tuple(values)
    if isinstance(value, _FrozenSet):
        values = {_thaw(v) for v in value.values}
        return values if value.kind == 'set' else frozenset(values)
    return deepcopy(value)


@dataclass(frozen=True)
class FieldSlot:
    """Distinguish an absent mapping key from a present key whose value is None."""

    present: bool
    value: Any = None

    def __post_init__(self) -> None:
        if type(self.present) is not bool:
            raise TypeError('present must be bool')
        if self.present:
            object.__setattr__(self, 'value', _freeze(self.value))
        else:
            object.__setattr__(self, 'value', None)

    @classmethod
    def from_mapping(cls, source: Mapping[str, Any], key: str) -> FieldSlot:
        return cls(key in source, source[key] if key in source else None)

    def to_value(self) -> Any:
        if not self.present:
            raise KeyError('field is absent')
        return _thaw(self.value)


def _freeze_slot_mapping(values: Mapping[str, Any]) -> _FrozenMapping:
    if not isinstance(values, Mapping):
        raise TypeError('axis values must be a mapping')
    entries = []
    for key, value in values.items():
        if type(key) is not str:
            raise UnsupportedValueError('mapping keys must be exact str')
        slot = value if type(value) is FieldSlot else FieldSlot(True, value)
        entries.append((key, slot))
    return _FrozenMapping(tuple(entries))


@dataclass(frozen=True)
class IdentityAxis:
    values: _FrozenMapping

    def __post_init__(self) -> None:
        object.__setattr__(self, 'values', _freeze_slot_mapping(self.values))


@dataclass(frozen=True)
class SourceFactsAxis:
    values: _FrozenMapping

    def __post_init__(self) -> None:
        object.__setattr__(self, 'values', _freeze_slot_mapping(self.values))


@dataclass(frozen=True)
class IntegrityAxis:
    values: _FrozenMapping

    def __post_init__(self) -> None:
        object.__setattr__(self, 'values', _freeze_slot_mapping(self.values))


@dataclass(frozen=True)
class ClassificationAxis:
    values: _FrozenMapping

    def __post_init__(self) -> None:
        object.__setattr__(self, 'values', _freeze_slot_mapping(self.values))


@dataclass(frozen=True)
class UserDecisionAxis:
    values: _FrozenMapping

    def __post_init__(self) -> None:
        object.__setattr__(self, 'values', _freeze_slot_mapping(self.values))


@dataclass(frozen=True)
class TransactionStateView:
    """Immutable, non-interpreting projection of one existing transaction mapping."""

    identity: IdentityAxis
    source: SourceFactsAxis
    integrity: IntegrityAxis
    classification: ClassificationAxis
    user_decision: UserDecisionAxis
    revision: FieldSlot
    extras: _FrozenMapping

    IDENTITY_FIELDS: ClassVar[tuple[str, ...]] = (
        'transaction_id', 'source_hash', 'batch_id', 'issuer', 'card_tail',
        'card_kind', 'row_index',
    )
    SOURCE_FIELDS: ClassVar[tuple[str, ...]] = (
        'transaction_direction', 'transaction_kind', 'approval_number',
        'original_approval_number', 'approval_date', 'posting_date', 'merchant',
        'merchant_normalized', 'amount_krw', 'foreign_amount', 'foreign_currency',
        'description_raw', 'raw_row_json', 'raw_row', 'created_at',
    )
    INTEGRITY_FIELDS: ClassVar[tuple[str, ...]] = (
        'duplicate_of', 'conflict_reason', 'parse_error',
    )
    CLASSIFICATION_FIELDS: ClassVar[tuple[str, ...]] = (
        'classification_state', 'classification_source', 'classification_basis',
        'item', 'description', 'display_tab_id', 'trip_id',
    )
    USER_DECISION_FIELDS: ClassVar[tuple[str, ...]] = ('decided', 'decided_at')

    def __post_init__(self) -> None:
        axes = (('identity', IdentityAxis), ('source', SourceFactsAxis),
                ('integrity', IntegrityAxis), ('classification', ClassificationAxis),
                ('user_decision', UserDecisionAxis))
        for name, expected_type in axes:
            if type(getattr(self, name)) is not expected_type:
                raise TypeError('transaction axes must use their declared DTO type')
        if type(self.revision) is not FieldSlot:
            object.__setattr__(self, 'revision', FieldSlot(True, self.revision))
        object.__setattr__(self, 'extras', _freeze_slot_mapping(self.extras))

    @classmethod
    def from_mapping(cls, source: Mapping[str, Any]) -> TransactionStateView:
        if not isinstance(source, Mapping):
            raise TypeError('source must be a mapping')
        if any(type(key) is not str for key in source):
            raise UnsupportedValueError('mapping keys must be exact str')
        groups = (cls.IDENTITY_FIELDS, cls.SOURCE_FIELDS, cls.INTEGRITY_FIELDS,
                  cls.CLASSIFICATION_FIELDS, cls.USER_DECISION_FIELDS, ('revision',))
        known = {key for group in groups for key in group}

        def axis(keys: tuple[str, ...], axis_type: type) -> Any:
            return axis_type(_FrozenMapping(tuple(
                (key, FieldSlot.from_mapping(source, key)) for key in keys
            )))

        return cls(
            identity=axis(cls.IDENTITY_FIELDS, IdentityAxis),
            source=axis(cls.SOURCE_FIELDS, SourceFactsAxis),
            integrity=axis(cls.INTEGRITY_FIELDS, IntegrityAxis),
            classification=axis(cls.CLASSIFICATION_FIELDS, ClassificationAxis),
            user_decision=axis(cls.USER_DECISION_FIELDS, UserDecisionAxis),
            revision=FieldSlot.from_mapping(source, 'revision'),
            extras=_FrozenMapping(tuple(
                (key, FieldSlot(True, value))
                for key, value in source.items() if key not in known
            )),
        )

    def to_mapping(self) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for group in (self.identity.values, self.source.values, self.integrity.values,
                      self.classification.values, self.user_decision.values,
                      _FrozenMapping((('revision', self.revision),))):
            for key, slot in group.items():
                if slot.present:
                    result[key] = slot.to_value()
        for key, slot in self.extras.items():
            if slot.present:
                result[key] = slot.to_value()
        return result
