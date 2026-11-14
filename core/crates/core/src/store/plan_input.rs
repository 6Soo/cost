//! `board.sqlite` → `PlanInput` 읽기 전용 어댑터. Python `automatic_classification._read`·`_context`와 같은 열·같은 조건.
//! `mode=ro`·`query_only=ON`으로 열어 짧은 읽기 트랜잭션 하나로 읽고 곧 닫는다. 아무것도 쓰지 않는다.

use std::collections::{BTreeMap, BTreeSet};
use std::path::Path;

use rusqlite::types::ValueRef;
use rusqlite::{Connection, Row as SqlRow};
use serde_json::{Map, Value};

use super::StoreError;
use super::projection::{
    ALLOWED_ITEMS_SQL, active_decision_sql, closed_review_ids, open_board_readonly,
};
use crate::plan::{BoardRow, PlanInput, ROW_COLUMNS, Row};

/// SQLite 값을 Python `sqlite3`가 돌려주는 모양(None·int·float·str)의 JSON으로 옮긴다.
fn cell(value: ValueRef<'_>) -> Value {
    match value {
        ValueRef::Null => Value::Null,
        ValueRef::Integer(i) => Value::from(i),
        ValueRef::Real(f) => serde_json::Number::from_f64(f).map_or(Value::Null, Value::Number),
        ValueRef::Text(t) => Value::String(String::from_utf8_lossy(t).into_owned()),
        ValueRef::Blob(_) => Value::Null,
    }
}

fn map_row(row: &SqlRow<'_>, names: &[&str]) -> rusqlite::Result<Row> {
    let mut out = Map::new();
    for (i, name) in names.iter().enumerate() {
        out.insert((*name).to_owned(), cell(row.get_ref(i)?));
    }
    Ok(out)
}

fn text_of(row: &Row, key: &str) -> String {
    row.get(key)
        .and_then(Value::as_str)
        .unwrap_or_default()
        .to_owned()
}

fn rows(conn: &Connection, sql: &str, names: &[&str]) -> Result<Vec<Row>, StoreError> {
    let mut stmt = conn.prepare(sql)?;
    let found = stmt
        .query_map([], |r| map_row(r, names))?
        .collect::<Result<_, _>>()?;
    Ok(found)
}

fn column_names(conn: &Connection, table: &str) -> Result<BTreeSet<String>, StoreError> {
    let mut stmt = conn.prepare(&format!("PRAGMA table_info({table})"))?;
    let names = stmt
        .query_map([], |r| r.get::<_, String>(1))?
        .collect::<Result<_, _>>()?;
    Ok(names)
}

/// 여행 목록 기본값: `trip_tabs`의 삭제되지 않은 탭(`trip_id`=`tab_id`). `destination` 열이 없는 옛 사본도 읽는다.
fn default_trips(conn: &Connection) -> Result<Vec<Value>, StoreError> {
    let have = column_names(conn, "trip_tabs")?;
    let wanted = [
        "tab_id",
        "display_key",
        "destination",
        "starts_on",
        "ends_on",
    ];
    let names: Vec<&str> = wanted.into_iter().filter(|n| have.contains(*n)).collect();
    let sql = format!("SELECT {} FROM trip_tabs WHERE deleted=0", names.join(","));
    let mut trips = Vec::new();
    for mut trip in rows(conn, &sql, &names)? {
        let tab = trip.get("tab_id").cloned().unwrap_or(Value::Null);
        trip.insert("trip_id".to_owned(), tab);
        trips.push(Value::Object(trip));
    }
    Ok(trips)
}

/// 이미 열린 연결(읽기 트랜잭션 또는 쓰기 트랜잭션 안)에서 계획 입력을 읽는다. 투영 쓰기가 같은 트랜잭션에서 쓴다.
pub fn read_inside(conn: &Connection) -> Result<PlanInput, StoreError> {
    let sql = format!(
        "SELECT {} FROM transactions ORDER BY transaction_id",
        ROW_COLUMNS.join(",")
    );
    let transactions = rows(conn, &sql, &ROW_COLUMNS)?;
    let decisions_sql = format!(
        "SELECT d.transaction_id,d.display_tab_id FROM review_decisions d WHERE {} ORDER BY revision",
        active_decision_sql(conn)?
    );
    let decisions = rows(conn, &decisions_sql, &["t", "tab"])?
        .iter()
        .map(|r| (text_of(r, "t"), text_of(r, "tab")))
        .collect();
    let ids = |sql: &str| -> Result<BTreeSet<String>, StoreError> {
        Ok(rows(conn, sql, &["id"])?
            .iter()
            .map(|r| text_of(r, "id"))
            .collect())
    };
    let ledger = rows(
        conn,
        "SELECT transaction_id,item,description,display_tab_id,trip_id FROM ledger_entries",
        &[
            "transaction_id",
            "item",
            "description",
            "display_tab_id",
            "trip_id",
        ],
    )?
    .into_iter()
    .map(|mut r| {
        (text_of(&r, "transaction_id"), {
            r.remove("transaction_id");
            r
        })
    })
    .collect();
    let boards: BTreeMap<String, BoardRow> = rows(
        conn,
        "SELECT row_id,display_tab_id,payload_json,revision FROM board_rows WHERE row_kind='expense'",
        &["row_id", "display_tab_id", "payload_json", "revision"],
    )?
    .iter()
    .map(|r| {
        let board = BoardRow {
            display_tab_id: text_of(r, "display_tab_id"),
            payload_json: text_of(r, "payload_json"),
            revision: r.get("revision").and_then(Value::as_i64).unwrap_or(0),
        };
        (text_of(r, "row_id"), board)
    })
    .collect();
    let mut allowed_items: Vec<String> = ids(ALLOWED_ITEMS_SQL)?.into_iter().collect();
    allowed_items.sort();
    Ok(PlanInput {
        rows: transactions,
        trips: default_trips(conn)?,
        holds: ids("SELECT transaction_id FROM transaction_review_holds")?,
        excluded: ids(
            "SELECT transaction_id FROM transaction_company_exclusions WHERE excluded=1",
        )?,
        overrides: ids("SELECT row_id FROM board_manual_overrides")?,
        closed_reviews: closed_review_ids(conn)?.into_iter().collect(),
        decisions,
        ledger,
        boards,
        allowed_items,
        ..PlanInput::default()
    })
}

/// 운영 사본을 읽어 `PlanInput`의 DB 쪽 칸을 채운다. `nets`·`evidence`·`selected`·`reconsider`는 호출자가 채운다.
pub fn read_plan_input(path: &Path) -> Result<PlanInput, StoreError> {
    let conn = open_board_readonly(path)?;
    conn.execute_batch("BEGIN")?;
    let result = read_inside(&conn);
    let rollback = conn.execute_batch("ROLLBACK");
    match (result, rollback) {
        (Ok(input), Ok(())) => Ok(input),
        (Ok(_), Err(e)) => Err(e.into()),
        (Err(e), Ok(())) => Err(e),
        (Err(e), Err(r)) => Err(StoreError::ReadFailedRollbackFailed {
            read: Box::new(e),
            rollback: r,
        }),
    }
}
