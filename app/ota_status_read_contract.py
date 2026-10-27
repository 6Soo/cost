"""Static read shapes for the OTA card-status projection helper.

These TypedDict declarations document fields consumed by
``project_card_ota_statuses``. They are not runtime validators or immutable
snapshots. Optional keys, present-null values, unknown status strings, and the
helper's accepted iterable shapes remain as supplied; no normalization is
performed here. Freshness remains the responsibility of callers that gate the
helper invocation.
"""
from typing import Any, Iterable, Optional, TypedDict


class ReservationRelationRead(TypedDict, total=False):
    transaction_id: Any
    status: Any


class PaymentResultRead(TypedDict, total=False):
    reservation_link: Optional[ReservationRelationRead]
    transaction_id: Any
    allocation_basis: Any
    individual_payment_evidence: Any
    status: Any
    inferred_link: Any
    reserved_card_ids: Any


class CandidateRead(TypedDict, total=False):
    transaction_id: Any


class CandidateSearchRead(TypedDict, total=False):
    reservation_only: Any
    candidates: Optional[Iterable[CandidateRead]]


class CandidateResultRead(TypedDict, total=False):
    candidate_search: Optional[CandidateSearchRead]


class CandidateDataRead(TypedDict, total=False):
    results: Optional[Iterable[CandidateResultRead]]


class OtaStatusSnapshotRead(TypedDict, total=False):
    generation: Any
    results: Optional[Iterable[PaymentResultRead]]
    data: Optional[CandidateDataRead]
