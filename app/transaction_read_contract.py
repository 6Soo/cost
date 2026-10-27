"""Static TypedDict shapes for the batch read API.

These declarations describe the structures returned by ``review.get_batch``;
they are not runtime validators or immutable snapshots. Nullable database
columns are nullable in value type while emitted keys remain required. raw_row remains ``Any`` to preserve
the existing JSON-decoded source shape, and classification state/count keys
remain open to unknown strings. This module performs no conversion or I/O.
"""
from typing import Any, Dict, List, Optional, TypeAlias, TypedDict


class RowIdentityRead(TypedDict):
    transaction_id: str
    source_hash: str
    row_index: int


class RowSourceFactsRead(TypedDict):
    issuer: str
    card_tail: str
    card_kind: str
    transaction_direction: str
    transaction_kind: str
    approval_number: str
    original_approval_number: str
    approval_date: str
    posting_date: str
    merchant: str
    merchant_normalized: str
    amount_krw: Optional[int]
    foreign_amount: str
    foreign_currency: str
    description_raw: str
    raw_row: Any


class RowIntegrityRead(TypedDict):
    duplicate_of: Optional[str]
    conflict_reason: str
    parse_error: str


class RowClassificationRead(TypedDict):
    classification_state: str
    classification_source: str
    classification_basis: str


class RowDecisionRead(TypedDict):
    item: str
    description: str
    display_tab_id: str
    trip_id: str
    revision: int
    decided: bool
    decided_at: Optional[str]


class TransactionRowRead(RowIdentityRead, RowSourceFactsRead, RowIntegrityRead,
                         RowClassificationRead, RowDecisionRead):
    """One dictionary returned by ``review._row_dict``."""


# _counts always emits needs_review/classified/total, plus arbitrary stored states.
# A closed TypedDict would incorrectly restrict those additional state keys.
BatchCountsRead: TypeAlias = Dict[str, int]


class BatchSummaryRead(TypedDict):
    batch_id: str
    filename: str
    content_sha256: str
    byte_size: int
    parser: str
    received_at: str
    parsed_at: Optional[str]
    row_count: int
    error_count: int
    status: str
    counts: BatchCountsRead


class BatchRead(TypedDict):
    batch_id: str
    summary: BatchSummaryRead
    rows: List[TransactionRowRead]
