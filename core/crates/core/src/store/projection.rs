//! `board.sqlite` 읽기 전용 투영. `tools/p2_batch/scope.py:26-54` `read_projection`과 같은 열을 읽는다.
//! `mode=ro`로 열고 `query_only=ON`을 걸며, 짧은 읽기 트랜잭션 하나로 일관되게 읽고 곧 닫는다.

use std::path::Path;
use std::time::{Duration, Instant};

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

/// `(테이블, 열 목록)` — `read_projection`의 보조 테이블 순서와 같다.
pub const AUX_TABLES: &[(&str, &str)] = &[
    ("trip_tabs", "tab_id,display_key,starts_on,ends_on,deleted"),
    ("review_decisions", "transaction_id,item,display_tab_id"),
    ("board_manual_overrides", "row_id,field"),
    (
        "transaction_review_holds",
        "transaction_id,source_hash,kind",
    ),
    (
        "transaction_company_exclusions",
        "transaction_id,source_hash,excluded",
    ),
    ("board_rows", "row_id,payload_json"),
    ("ledger_entries", "transaction_id,trip_id,display_tab_id"),
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

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct TripTabRow {
    pub tab_id: String,
    pub display_key: String,
    pub starts_on: String,
    pub ends_on: String,
    pub deleted: i64,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct ReviewDecisionRow {
    pub transaction_id: String,
    pub item: String,
    pub display_tab_id: String,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct ManualOverrideRow {
    pub row_id: String,
    pub field: String,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct ReviewHoldRow {
    pub transaction_id: String,
    pub source_hash: String,
    pub kind: String,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct CompanyExclusionRow {
    pub transaction_id: String,
    pub source_hash: String,
    pub excluded: i64,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct BoardRow {
    pub row_id: String,
    pub payload_json: String,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct LedgerEntryRow {
    pub transaction_id: String,
    pub trip_id: String,
    pub display_tab_id: String,
}

#[derive(Debug, Clone, PartialEq)]
pub struct Projection {
    pub transactions: Vec<TxnRow>,
    pub trip_tabs: Vec<TripTabRow>,
    pub review_decisions: Vec<ReviewDecisionRow>,
    pub board_manual_overrides: Vec<ManualOverrideRow>,
    pub transaction_review_holds: Vec<ReviewHoldRow>,
    pub transaction_company_exclusions: Vec<CompanyExclusionRow>,
    pub board_rows: Vec<BoardRow>,
    pub ledger_entries: Vec<LedgerEntryRow>,
    pub allowed_items: Vec<String>,
    pub closed_provenance_review: Vec<String>,
    pub read_seconds: f64,
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
    let started = Instant::now();
    let conn = open_board_readonly(path)?;
    conn.execute_batch("BEGIN")?;
    let result = read_inside(&conn);
    let rollback = conn.execute_batch("ROLLBACK");
    let mut projection = match (result, rollback) {
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
    projection.read_seconds = (started.elapsed().as_secs_f64() * 1000.0).round() / 1000.0;
    Ok(projection)
}

fn read_inside(conn: &Connection) -> Result<Projection, StoreError> {
    let transactions = collect(
        conn,
        &format!("SELECT {} FROM transactions", TRANSACTION_FIELDS.join(",")),
        txn_row,
    )?;
    let aux = |table: &str| -> String {
        let columns = AUX_TABLES
            .iter()
            .find(|(t, _)| *t == table)
            .map(|(_, c)| *c)
            .unwrap_or("");
        format!("SELECT {columns} FROM {table}")
    };
    let trip_tabs = collect(conn, &aux("trip_tabs"), |r| {
        Ok(TripTabRow {
            tab_id: r.get(0)?,
            display_key: r.get(1)?,
            starts_on: r.get(2)?,
            ends_on: r.get(3)?,
            deleted: r.get(4)?,
        })
    })?;
    let review_decisions = collect(
        conn,
        &format!(
            "{} d WHERE {}",
            aux("review_decisions"),
            active_decision_sql(conn)?
        ),
        |r| {
            Ok(ReviewDecisionRow {
                transaction_id: r.get(0)?,
                item: r.get(1)?,
                display_tab_id: r.get(2)?,
            })
        },
    )?;
    let board_manual_overrides = collect(conn, &aux("board_manual_overrides"), |r| {
        Ok(ManualOverrideRow {
            row_id: r.get(0)?,
            field: r.get(1)?,
        })
    })?;
    let transaction_review_holds = collect(conn, &aux("transaction_review_holds"), |r| {
        Ok(ReviewHoldRow {
            transaction_id: r.get(0)?,
            source_hash: r.get(1)?,
            kind: r.get(2)?,
        })
    })?;
    let transaction_company_exclusions =
        collect(conn, &aux("transaction_company_exclusions"), |r| {
            Ok(CompanyExclusionRow {
                transaction_id: r.get(0)?,
                source_hash: r.get(1)?,
                excluded: r.get(2)?,
            })
        })?;
    let board_rows = collect(conn, &aux("board_rows"), |r| {
        Ok(BoardRow {
            row_id: r.get(0)?,
            payload_json: r.get(1)?,
        })
    })?;
    let ledger_entries = collect(conn, &aux("ledger_entries"), |r| {
        Ok(LedgerEntryRow {
            transaction_id: r.get(0)?,
            trip_id: r.get(1)?,
            display_tab_id: r.get(2)?,
        })
    })?;
    let mut allowed_items: Vec<String> = collect(conn, ALLOWED_ITEMS_SQL, |r| r.get(0))?;
    allowed_items.sort();
    Ok(Projection {
        transactions,
        trip_tabs,
        review_decisions,
        board_manual_overrides,
        transaction_review_holds,
        transaction_company_exclusions,
        board_rows,
        ledger_entries,
        allowed_items,
        closed_provenance_review: closed_review_ids(conn)?,
        read_seconds: 0.0,
    })
}
