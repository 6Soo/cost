//! 투영 쓰기(설계 §3.3)가 건드릴 수 있는 열의 허용 목록.
//! 원천 열(금액·부호·ID·원문)은 어떤 목록에도 없다. 쓰기 SQL은 이 목록에서만 만든다.

/// `transactions` 판정 열(`app/automatic_classification.py:16-17`)과 개정 번호.
pub const TRANSACTIONS_WRITE: &[&str] = &[
    "classification_state",
    "classification_source",
    "classification_basis",
    "item",
    "description",
    "display_tab_id",
    "trip_id",
    "revision",
];

/// `ledger_entries`는 빈 항목·빈 귀속만 채운다(`:570-573`).
pub const LEDGER_ENTRIES_WRITE: &[&str] = &["item", "display_tab_id", "trip_id"];

/// 화면 행 payload 동기화(`:577-597`).
pub const BOARD_ROWS_WRITE: &[&str] = &["payload_json", "display_tab_id", "revision"];

/// 원천 열. 투영 쓰기 목록과 겹치면 안 된다.
pub const SOURCE_COLUMNS: &[&str] = &[
    "transaction_id",
    "source_hash",
    "batch_id",
    "issuer",
    "card_tail",
    "card_kind",
    "transaction_direction",
    "transaction_kind",
    "approval_number",
    "original_approval_number",
    "approval_date",
    "posting_date",
    "merchant",
    "merchant_normalized",
    "amount_krw",
    "foreign_amount",
    "foreign_currency",
    "description_raw",
    "row_index",
    "raw_row_json",
    "duplicate_of",
    "conflict_reason",
    "parse_error",
    "created_at",
    "occurred_on",
    "committed_at",
    "decided_at",
    "row_id",
    "row_kind",
];

/// 쓰기 SQL의 `SET` 절을 허용 목록에서 만든다.
pub fn set_clause(columns: &[&str]) -> String {
    columns
        .iter()
        .map(|c| format!("{c}=?"))
        .collect::<Vec<_>>()
        .join(",")
}
