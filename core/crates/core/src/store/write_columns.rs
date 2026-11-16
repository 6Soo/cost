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

/// 투영 쓰기가 낼 수 있는 `UPDATE` 문장의 전부. 열 이름은 위 목록에서만 오므로 목록 밖 열을 쓰는 문장은 만들 수 없다.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Write {
    /// 판정 열 7개를 쓰고 `revision`을 올린다. `WHERE transaction_id=? AND revision=?`
    Transactions,
    /// 장부 행의 빈 항목·빈(또는 미분류) 귀속만 채운다. `WHERE transaction_id=?`
    LedgerFill,
    /// 예약 이용기간 교정: 장부 행 귀속을 덮어쓴다. `WHERE transaction_id=?`
    LedgerCorrect,
    /// Google 수기 귀속 교정: 파생 분기 항목도 같은 투영에 반영한다.
    LedgerGoogleCorrect,
    /// 화면 행 payload·귀속 동기화. `WHERE row_id=?`
    Board,
}

impl Write {
    pub fn sql(self) -> String {
        match self {
            Self::Transactions => {
                let set: Vec<String> = TRANSACTIONS_WRITE.iter().map(|c| bump_or_set(c)).collect();
                format!(
                    "UPDATE transactions SET {} WHERE transaction_id=? AND revision=?",
                    set.join(",")
                )
            }
            Self::LedgerFill => {
                let set: Vec<String> = LEDGER_ENTRIES_WRITE
                    .iter()
                    .map(|c| match *c {
                        "item" => format!("{c}=CASE WHEN COALESCE({c},'')='' THEN ? ELSE {c} END"),
                        _ => format!(
                            "{c}=CASE WHEN COALESCE({c},'') IN ('','unclassified') THEN ? ELSE {c} END"
                        ),
                    })
                    .collect();
                format!(
                    "UPDATE ledger_entries SET {} WHERE transaction_id=?",
                    set.join(",")
                )
            }
            Self::LedgerCorrect => {
                let cols: Vec<&str> = LEDGER_ENTRIES_WRITE
                    .iter()
                    .copied()
                    .filter(|c| *c != "item")
                    .collect();
                format!(
                    "UPDATE ledger_entries SET {} WHERE transaction_id=?",
                    set_clause(&cols)
                )
            }
            Self::LedgerGoogleCorrect => format!(
                "UPDATE ledger_entries SET {} WHERE transaction_id=?",
                set_clause(LEDGER_ENTRIES_WRITE)
            ),
            Self::Board => {
                let set: Vec<String> = BOARD_ROWS_WRITE.iter().map(|c| bump_or_set(c)).collect();
                format!("UPDATE board_rows SET {} WHERE row_id=?", set.join(","))
            }
        }
    }
}

fn bump_or_set(column: &str) -> String {
    if column == "revision" {
        "revision=revision+1".to_owned()
    } else {
        format!("{column}=?")
    }
}
