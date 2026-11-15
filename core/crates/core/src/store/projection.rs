//! `board.sqlite` 읽기 전용 투영: `transactions` 원행만 읽는다(`tools/p2_batch/scope.py` `FIELDS`와 같은 열).
//! `mode=ro`로 열고 `query_only=ON`을 걸며, 짧은 읽기 트랜잭션 하나로 일관되게 읽고 곧 닫는다.

use std::path::Path;
use std::time::Duration;

use rusqlite::{Connection, OpenFlags, Row};

use super::error::StoreError;

/// `scope.FIELDS`와 같은 순서·같은 열.
pub const TRANSACTION_FIELDS: &[&str] = &[
    "transaction_id",
    "source_hash",
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
    "raw_row_json",
    "duplicate_of",
    "conflict_reason",
    "parse_error",
    "classification_state",
    "classification_source",
    "classification_basis",
    "item",
    "display_tab_id",
    "trip_id",
    "revision",
    "decided_at",
];

/// `scope.py`의 `allowed_items` 조회와 같은 문장.
pub const ALLOWED_ITEMS_SQL: &str = concat!(
    "SELECT DISTINCT item FROM transactions WHERE COALESCE(item,'')!='' UNION ",
    "SELECT DISTINCT item FROM ledger_entries WHERE COALESCE(item,'')!=''"
);

const RELEASE: &str = "card.dist141_provenance_corrected";
const RESTORE: &str = "card.dist141_provenance_restored";

/// 원천 열은 읽기만 한다. 금액 `amount_krw`는 NULL일 수 있다.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct TxnRow {
    pub transaction_id: String,
    pub source_hash: String,
    pub issuer: String,
    pub card_tail: String,
    pub card_kind: String,
    pub transaction_direction: String,
    pub transaction_kind: String,
    pub approval_number: String,
    pub original_approval_number: String,
    pub approval_date: String,
    pub posting_date: String,
    pub merchant: String,
    pub merchant_normalized: String,
    pub amount_krw: Option<i64>,
    pub foreign_amount: String,
    pub foreign_currency: String,
    pub description_raw: String,
    pub raw_row_json: String,
    pub duplicate_of: Option<String>,
    pub conflict_reason: String,
    pub parse_error: String,
    pub classification_state: String,
    pub classification_source: String,
    pub classification_basis: String,
    pub item: String,
    pub display_tab_id: String,
    pub trip_id: String,
    pub revision: i64,
    pub decided_at: Option<String>,
}

fn txn_row(r: &Row<'_>) -> rusqlite::Result<TxnRow> {
    Ok(TxnRow {
        transaction_id: r.get("transaction_id")?,
        source_hash: r.get("source_hash")?,
        issuer: r.get("issuer")?,
        card_tail: r.get("card_tail")?,
        card_kind: r.get("card_kind")?,
        transaction_direction: r.get("transaction_direction")?,
        transaction_kind: r.get("transaction_kind")?,
        approval_number: r.get("approval_number")?,
        original_approval_number: r.get("original_approval_number")?,
        approval_date: r.get("approval_date")?,
        posting_date: r.get("posting_date")?,
        merchant: r.get("merchant")?,
        merchant_normalized: r.get("merchant_normalized")?,
        amount_krw: r.get("amount_krw")?,
        foreign_amount: r.get("foreign_amount")?,
        foreign_currency: r.get("foreign_currency")?,
        description_raw: r.get("description_raw")?,
        raw_row_json: r.get("raw_row_json")?,
        duplicate_of: r.get("duplicate_of")?,
        conflict_reason: r.get("conflict_reason")?,
        parse_error: r.get("parse_error")?,
        classification_state: r.get("classification_state")?,
        classification_source: r.get("classification_source")?,
        classification_basis: r.get("classification_basis")?,
        item: r.get("item")?,
        display_tab_id: r.get("display_tab_id")?,
        trip_id: r.get("trip_id")?,
        revision: r.get("revision")?,
        decided_at: r.get("decided_at")?,
    })
}

#[derive(Debug, Clone, PartialEq)]
pub struct Projection {
    pub transactions: Vec<TxnRow>,
}

/// 운영 DB를 읽기 전용(`mode=ro`)으로 열고 `query_only=ON`을 건다. 기록 문장은 거부된다.
pub fn open_board_readonly(path: &Path) -> Result<Connection, StoreError> {
    let conn = Connection::open_with_flags(
        path,
        OpenFlags::SQLITE_OPEN_READ_ONLY | OpenFlags::SQLITE_OPEN_NO_MUTEX,
    )?;
    conn.busy_timeout(Duration::from_secs(2))?;
    conn.execute_batch("PRAGMA query_only=ON")?;
    Ok(conn)
}

pub(crate) fn has_change_log(conn: &Connection) -> Result<bool, StoreError> {
    Ok(conn
        .query_row(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='change_log'",
            [],
            |_| Ok(()),
        )
        .is_ok())
}

/// `decision_provenance.active_decision_sql`: 감사 구조가 없으면 모든 결정이 보호된다.
pub(crate) fn active_decision_sql(conn: &Connection) -> Result<String, StoreError> {
    if !has_change_log(conn)? {
        return Ok("1=1".to_owned());
    }
    Ok(format!(
        "NOT EXISTS (
        SELECT 1 FROM change_log p WHERE p.kind='{RELEASE}'
        AND p.subject=d.transaction_id
        AND json_extract(p.detail_json,'$.decision_revision')=d.revision
        AND NOT EXISTS (SELECT 1 FROM change_log r WHERE r.kind='{RESTORE}'
            AND r.subject=p.subject
            AND json_extract(r.detail_json,'$.release_entry_id')=p.entry_id))"
    ))
}

pub(crate) fn closed_review_ids(conn: &Connection) -> Result<Vec<String>, StoreError> {
    if !has_change_log(conn)? {
        return Ok(Vec::new());
    }
    let mut stmt = conn.prepare(&format!(
        "SELECT p.subject FROM change_log p
        WHERE p.kind='{RELEASE}' AND json_extract(p.detail_json,'$.opened')=0
        AND NOT EXISTS (SELECT 1 FROM change_log r WHERE r.kind='{RESTORE}'
        AND r.subject=p.subject AND json_extract(r.detail_json,'$.release_entry_id')=p.entry_id)"
    ))?;
    let mut ids: Vec<String> = stmt
        .query_map([], |r| r.get(0))?
        .collect::<Result<_, _>>()?;
    ids.sort();
    ids.dedup();
    Ok(ids)
}

fn collect<T>(
    conn: &Connection,
    sql: &str,
    f: impl FnMut(&Row<'_>) -> rusqlite::Result<T>,
) -> Result<Vec<T>, StoreError> {
    let mut stmt = conn.prepare(sql)?;
    let rows = stmt.query_map([], f)?.collect::<Result<_, _>>()?;
    Ok(rows)
}

/// 짧은 일관 읽기 한 번. 읽기 트랜잭션은 끝에서 롤백하고 연결은 곧 닫힌다.
pub fn read_projection(path: &Path) -> Result<Projection, StoreError> {
    let conn = open_board_readonly(path)?;
    conn.execute_batch("BEGIN")?;
    let result = read_inside(&conn);
    let rollback = conn.execute_batch("ROLLBACK");
    let projection = match (result, rollback) {
        (Ok(p), Ok(())) => p,
        (Ok(_), Err(e)) => return Err(e.into()),
        (Err(e), Ok(())) => return Err(e),
        (Err(e), Err(r)) => {
            return Err(StoreError::ReadFailedRollbackFailed {
                read: Box::new(e),
                rollback: r,
            });
        }
    };
    Ok(projection)
}

fn read_inside(conn: &Connection) -> Result<Projection, StoreError> {
    let transactions = collect(
        conn,
        &format!("SELECT {} FROM transactions", TRANSACTION_FIELDS.join(",")),
        txn_row,
    )?;
    Ok(Projection { transactions })
}
