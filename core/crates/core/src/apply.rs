//! 투영 쓰기(M3 U11). 원본: `app/automatic_classification.py`의 `apply`(`:550-617`).
//!
//! 한 `BEGIN IMMEDIATE` 트랜잭션에서 계획을 다시 만들어 미리보기 digest와 대조하고(다르면 `CLASSIFICATION_PREVIEW_STALE`),
//! 거래 판정 열·장부 행 빈 칸·화면 행 payload와 이력·change_log만 쓴다. 쓰는 열은 `store::write_columns`의 고정 목록뿐이며
//! 금액·부호·ID·원문 같은 원천 열을 쓰는 문장은 [`Write`]로 만들 수 없다. 운영 DB 경로 거부는 호출자(CLI)가 한다.

use std::collections::{BTreeMap, BTreeSet};
use std::path::Path;
use std::time::Duration;

use rusqlite::types::Value as Sql;
use rusqlite::{
    Connection, OpenFlags, OptionalExtension, Transaction, TransactionBehavior, params,
};
use serde_json::{Map, Value, json};
use thiserror::Error;

use crate::digest::python_json;
use crate::domain::{Decision, Judgement};
use crate::period::{PeriodEvidence, changed_since, current_digests};
use crate::pipeline::overlay_context;
use crate::plan::{Links, Outcome, PlanInput, PlanResult, Target, plan_with_periods};
use crate::store::decisions::{projection, save_decision, stored_digests_in};
use crate::store::write_columns::Write;
use crate::store::{StoreError, latest_version, read_plan_input_in};

#[derive(Debug, Error)]
pub enum ApplyError {
    #[error("CLASSIFICATION_PREVIEW_STALE")]
    PreviewStale,
    #[error("PLAN_FAILED")]
    PlanFailed,
    #[error("BOARD_PAYLOAD_INVALID")]
    PayloadInvalid,
    #[error("CORE_SCHEMA_MISMATCH")]
    CoreSchemaMismatch,
    #[error("저장 계층 오류: {0}")]
    Store(#[from] StoreError),
    #[error("sqlite 오류: {0}")]
    Sqlite(#[from] rusqlite::Error),
}

pub struct ApplyRequest<'a> {
    /// 미리보기에서 받은 digest.
    pub expected_digest: &'a str,
    pub transaction_ids: Option<&'a [String]>,
    pub reconsider: bool,
    /// `trips`·`nets`·`evidence`(`plan`과 같은 모양).
    pub context: &'a Value,
    /// change_log·이력의 시각(`utc_now()`와 같은 `YYYY-MM-DDTHH:MM:SS+00:00`).
    pub now: &'a str,
    /// 화면 열이 이미 계획과 같은데 `decisions`가 없는 거래에 판정만 저장한다(중단 복구).
    pub backfill: bool,
}

/// 쓰기 연결: 있는 파일만 연다(만들지 않는다). Python `Store.open`과 같은 대기 시간.
pub fn open_board_writable(path: &Path) -> Result<Connection, StoreError> {
    let conn = Connection::open_with_flags(
        path,
        OpenFlags::SQLITE_OPEN_READ_WRITE | OpenFlags::SQLITE_OPEN_NO_MUTEX,
    )?;
    conn.busy_timeout(Duration::from_secs(10))?;
    conn.execute_batch("PRAGMA foreign_keys=ON")?;
    Ok(conn)
}

/// SQLite의 UTC 현재 시각을 Python `utc_now()` 형식으로.
pub fn utc_now(conn: &Connection) -> Result<String, StoreError> {
    Ok(conn.query_row(
        "SELECT strftime('%Y-%m-%dT%H:%M:%S+00:00','now')",
        [],
        |r| r.get(0),
    )?)
}

/// 한 번의 쓰기 결과. `summary`는 Python `apply`가 돌려주는 계획 요약과 같다.
#[derive(Debug, Clone, PartialEq)]
pub struct ApplyOutcome {
    pub summary: Value,
    /// 화면 열을 실제로 쓴 거래 수.
    pub written: usize,
    /// 판정이 `Protected`·`Preserved`라 게시하지 않은 목표 수.
    pub skipped_unjudged: usize,
    /// 저장된 판정에서 도출한 화면 열이 계획 값과 달라 쓰지 않은 목표 수(차이는 그림자·known-diffs 대상).
    pub skipped_mismatch: usize,
    /// `backfill`로 `decisions`만 채운 거래 수(화면 열은 이미 계획과 같았다).
    pub backfilled: usize,
}

/// `board.sqlite` 연결에 `core.sqlite`를 `core`로 붙인다(스키마가 최신이어야 한다). 두 파일은 같은 트랜잭션에서 쓴다.
fn attach_core(conn: &Connection, core: &Path) -> Result<(), ApplyError> {
    conn.execute(
        "ATTACH DATABASE ? AS core",
        [core.to_string_lossy().as_ref()],
    )?;
    let found: Option<u32> =
        conn.query_row("SELECT MAX(version) FROM core.schema_meta", [], |r| {
            r.get(0)
        })?;
    if found != Some(latest_version()) {
        return Err(ApplyError::CoreSchemaMismatch);
    }
    Ok(())
}

/// 계획을 다시 만들어 digest가 같을 때만 쓴다.
///
/// 순서: ① `BEGIN IMMEDIATE`(board) ② 계획·digest 대조 ③ 목표마다 savepoint 안에서 `core.decisions`(+이력)에 판정 저장 →
/// 저장된 행에서 화면 열 도출 → `transactions`·`ledger_entries`·`board_rows`·이력 쓰기 ④ 커밋.
/// 운영에서 board.sqlite는 WAL, core.sqlite는 롤백 저널이라 `ATTACH` 한 트랜잭션이어도 파일별로 커밋되며 **board가 먼저**
/// 커밋된다. 두 커밋 사이에 중단되면 화면 열은 채워졌는데 `decisions`가 없는 거래가 남는다. 이 거래는 이제 계획의
/// 목표가 아니므로 그냥 다시 실행해서는 채워지지 않는다. 복구는 `backfill`(`costcore apply --backfill-decisions`): 화면 열이
/// 계획과 같고 `decisions`가 없는 거래에 판정만 저장한다. 또는 작성자를 Python으로 되돌린다.
/// 이용기간 근거 digest가 저장값과 달라진 거래(`context.periods`가 바뀜·판정 함수 버전 변경)는 화면 열이 같아도 판정을
/// 다시 저장한다(저장된 판정이 이미 있을 때만; 없는 거래는 `backfill`일 때). 같은 입력으로 다시 실행하면 쓰기는 0건이다.
/// `links`는 환불 짝 연결(2차 전환 전에는 Python 어댑터 결과)이며 트랜잭션 밖에서 미리 받은 값이다.
pub fn apply(
    conn: &mut Connection,
    core: &Path,
    request: &ApplyRequest<'_>,
    links: &dyn Links,
) -> Result<ApplyOutcome, ApplyError> {
    attach_core(conn, core)?;
    let tx = conn.transaction_with_behavior(TransactionBehavior::Immediate)?;
    let mut input = read_plan_input_in(&tx)?;
    overlay_context(
        &mut input,
        request.context,
        request.transaction_ids,
        request.reconsider,
    );
    let facts: BTreeMap<String, Value> = request.context["periods"]
        .as_object()
        .map(|m| m.iter().map(|(k, v)| (k.clone(), v.clone())).collect())
        .unwrap_or_default();
    let current = current_digests(
        input.rows.iter().filter_map(|r| {
            let tid = r.get("transaction_id")?.as_str()?;
            let board = input.boards.get(&format!("card-{tid}"));
            Some((tid, board.map(|b| b.payload_json.as_str())))
        }),
        &facts,
    );
    let stored = stored_digests_in(&tx, "core")?;
    let periods = PeriodEvidence {
        facts,
        changed: changed_since(&stored, &current).into_iter().collect(),
    };
    let result = plan_with_periods(&input, links, &periods).map_err(|_| ApplyError::PlanFailed)?;
    if result.digest != request.expected_digest {
        return Err(ApplyError::PreviewStale);
    }
    let request_id = format!("apply-{}", &result.digest[..24]);
    let (mut written, mut skipped_unjudged, mut skipped_mismatch) = (0, 0, 0);
    for target in &result.targets {
        let decision = result
            .outcomes
            .iter()
            .find_map(|(id, outcome)| match outcome {
                Outcome::Judged(Judgement::Decided(d)) if *id == target.id => Some(d),
                _ => None,
            });
        let Some(decision) = decision else {
            skipped_unjudged += 1;
            continue;
        };
        tx.execute_batch("SAVEPOINT target")?;
        let done = write_target(
            &tx,
            &input,
            target,
            decision,
            &result,
            &request_id,
            &current,
            request.now,
        )?;
        if done {
            tx.execute_batch("RELEASE target")?;
            written += 1;
        } else {
            tx.execute_batch("ROLLBACK TO target; RELEASE target")?;
            skipped_mismatch += 1;
        }
    }
    let mut backfilled = 0;
    let targeted: BTreeSet<&str> = result.targets.iter().map(|t| t.id.as_str()).collect();
    for (tid, outcome) in &result.outcomes {
        let Outcome::Judged(Judgement::Decided(decision)) = outcome else {
            continue;
        };
        if targeted.contains(tid.as_str()) || !periods.changed.contains(tid) {
            continue;
        }
        let has_decision = stored.contains_key(tid);
        if !has_decision && !request.backfill {
            continue;
        }
        tx.execute_batch("SAVEPOINT decision_only")?;
        let digest = current.get(tid).map_or("", String::as_str);
        if decision_only(&tx, &input, tid, decision, digest, &request_id, request.now)? {
            tx.execute_batch("RELEASE decision_only")?;
            backfilled += 1;
        } else {
            tx.execute_batch("ROLLBACK TO decision_only; RELEASE decision_only")?;
        }
    }
    let summary = result.to_value()["summary"].clone();
    if written > 0 {
        insert_log(
            &tx,
            request.now,
            "card.automatic_classification",
            crate::plan::POLICY,
            &python_json(&summary),
        )?;
    }
    tx.commit()?;
    conn.execute_batch("DETACH DATABASE core")?;
    Ok(ApplyOutcome {
        summary,
        written,
        skipped_unjudged,
        skipped_mismatch,
        backfilled,
    })
}

/// 판정만 저장한다(화면 열은 건드리지 않는다). 저장된 행에서 도출한 열이 거래의 현재 판정 열과 다르면 저장하지 않는다.
fn decision_only(
    tx: &Transaction<'_>,
    input: &PlanInput,
    tid: &str,
    decision: &Decision,
    digest: &str,
    request_id: &str,
    now: &str,
) -> Result<bool, ApplyError> {
    let Some(row) = input
        .rows
        .iter()
        .find(|r| r.get("transaction_id").and_then(Value::as_str) == Some(tid))
    else {
        return Ok(false);
    };
    let text = |k: &str| row.get(k).and_then(Value::as_str).unwrap_or_default();
    let current: Vec<&str> = crate::plan::FIELDS.iter().map(|k| text(k)).collect();
    save_decision(
        tx,
        "core",
        decision,
        text("classification_source"),
        digest,
        row.get("revision").and_then(Value::as_i64).unwrap_or(0),
        now,
        request_id,
    )?;
    let derived = projection(tx, "core", tid)?;
    Ok(derived.is_some_and(|d| d.iter().map(String::as_str).eq(current.iter().copied())))
}

fn insert_log(
    tx: &Transaction<'_>,
    now: &str,
    kind: &str,
    subject: &str,
    detail: &str,
) -> rusqlite::Result<()> {
    tx.execute(
        "INSERT INTO change_log(at,kind,subject,detail_json) VALUES (?,?,?,?)",
        params![now, kind, subject, detail],
    )?;
    Ok(())
}

/// JSON 값을 SQLite에 묶는 값으로(`revision` 같은 정수 칸).
fn sql_value(value: &Value) -> Sql {
    match value {
        Value::Number(n) => n.as_i64().map_or(Sql::Null, Sql::Integer),
        Value::String(s) => Sql::Text(s.clone()),
        _ => Sql::Null,
    }
}

/// Python 참/거짓: `payload.get('item') or item`.
fn truthy(value: Option<&Value>) -> bool {
    match value {
        None | Some(Value::Null) | Some(Value::Bool(false)) => false,
        Some(Value::Number(n)) => n.as_f64() != Some(0.0),
        Some(Value::String(s)) => !s.is_empty(),
        Some(Value::Array(a)) => !a.is_empty(),
        Some(Value::Object(m)) => !m.is_empty(),
        Some(Value::Bool(true)) => true,
    }
}

fn blank_or_unclassified(value: Option<&Value>) -> bool {
    match value {
        None | Some(Value::Null) => true,
        Some(Value::String(s)) => s.is_empty() || s == "unclassified",
        _ => false,
    }
}

/// 판정 하나를 `core.decisions`에 저장하고, 저장된 행에서 도출한 화면 열을 `board.sqlite`에 쓴다.
/// 도출 값이 계획 값과 다르면 아무것도 쓰지 않고 `false`(호출자가 savepoint를 되돌린다).
#[allow(clippy::too_many_arguments)]
fn write_target(
    tx: &Transaction<'_>,
    input: &PlanInput,
    target: &Target,
    decision: &Decision,
    result: &PlanResult,
    request_id: &str,
    digests: &BTreeMap<String, String>,
    now: &str,
) -> Result<bool, ApplyError> {
    let tid = target.id.as_str();
    let revision = target.revision.as_i64().unwrap_or(0) + 1;
    save_decision(
        tx,
        "core",
        decision,
        &target.values[1],
        digests.get(tid).map_or("", String::as_str),
        revision,
        now,
        request_id,
    )?;
    let Some(values) = projection(tx, "core", tid)? else {
        return Ok(false);
    };
    if values != target.values {
        return Ok(false);
    }
    let values = &values;
    let correction = target.booking_trip_correction;
    let before = if correction {
        Some(snapshot(tx, input, tid)?)
    } else {
        None
    };
    let mut bind: Vec<Sql> = values.iter().cloned().map(Sql::Text).collect();
    bind.push(Sql::Text(tid.to_owned()));
    bind.push(sql_value(&target.revision));
    tx.execute(&Write::Transactions.sql(), rusqlite::params_from_iter(bind))?;
    let (item, tab, trip) = (&values[3], &values[5], &values[6]);
    tx.execute(&Write::LedgerFill.sql(), params![item, tab, trip, tid])?;
    if correction {
        tx.execute(&Write::LedgerCorrect.sql(), params![tab, trip, tid])?;
    }
    let row_id = format!("card-{tid}");
    let board: Option<(String, Option<String>)> = tx
        .query_row(
            "SELECT payload_json,display_tab_id FROM board_rows WHERE row_id=?",
            [&row_id],
            |r| Ok((r.get(0)?, r.get(1)?)),
        )
        .optional()?;
    if let Some((old_text, old_tab)) = board {
        sync_board(tx, &row_id, &old_text, old_tab, target, values, result, now)?;
    }
    if let Some(before) = before {
        let detail = json!({"before": before, "trip_id": trip, "basis": values[2]});
        insert_log(
            tx,
            now,
            "card.booking_trip_correction",
            tid,
            &python_json(&detail),
        )?;
    }
    Ok(true)
}

/// 교정 전 판정 열·개정 번호와 장부 귀속(`before`).
fn snapshot(tx: &Transaction<'_>, input: &PlanInput, tid: &str) -> Result<Value, ApplyError> {
    let row = input
        .rows
        .iter()
        .find(|r| r.get("transaction_id").and_then(Value::as_str) == Some(tid))
        .ok_or(ApplyError::PlanFailed)?;
    let mut transaction = Map::new();
    for key in crate::plan::FIELDS.iter().chain(["revision"].iter()) {
        transaction.insert(
            (*key).to_owned(),
            row.get(*key).cloned().unwrap_or(Value::Null),
        );
    }
    let ledger: Option<(String, String)> = tx
        .query_row(
            "SELECT display_tab_id,trip_id FROM ledger_entries WHERE transaction_id=?",
            [tid],
            |r| Ok((r.get(0)?, r.get(1)?)),
        )
        .optional()?;
    Ok(json!({"transaction": transaction,
        "ledger": ledger.map_or(Value::Null, |(tab, trip)| json!([tab, trip]))}))
}

#[allow(clippy::too_many_arguments)]
fn sync_board(
    tx: &Transaction<'_>,
    row_id: &str,
    old_text: &str,
    old_tab: Option<String>,
    target: &Target,
    values: &[String; 7],
    result: &PlanResult,
    now: &str,
) -> Result<(), ApplyError> {
    let (item, tab) = (&values[3], &values[5]);
    let original: Value = serde_json::from_str(old_text).map_err(|_| ApplyError::PayloadInvalid)?;
    let mut payload = original.clone();
    let map = payload.as_object_mut().ok_or(ApplyError::PayloadInvalid)?;
    map.insert("classification_state".into(), json!("classified"));
    if !truthy(map.get("item")) {
        map.insert("item".into(), json!(item));
    }
    let mut board_tab = if blank_or_unclassified(old_tab.as_deref().map(|s| json!(s)).as_ref()) {
        tab.clone()
    } else {
        old_tab.clone().unwrap_or_default()
    };
    let correction = target.booking_trip_correction;
    if correction {
        board_tab = tab.clone();
        map.insert("display_tab_id".into(), json!(tab));
        map.insert("classification_source".into(), json!(values[1]));
        map.insert("classification_basis".into(), json!(values[2]));
    }
    if blank_or_unclassified(map.get("display_tab_id")) {
        map.insert("display_tab_id".into(), json!(board_tab));
    }
    if payload == original && old_tab.as_deref() == Some(board_tab.as_str()) {
        return Ok(());
    }
    if correction {
        let old_revision: i64 = tx.query_row(
            "SELECT revision FROM board_rows WHERE row_id=?",
            [row_id],
            |r| r.get(0),
        )?;
        payload["revision"] = json!(old_revision + 1);
        tx.execute(
            "INSERT INTO board_revisions(row_id,revision,prev_json,new_json,event_id,change_mode,actor,created_at,client_request_id) VALUES (?,?,?,?,?,?,?,?,?)",
            params![
                row_id,
                old_revision + 1,
                old_text,
                python_json(&payload),
                "",
                "rule_change",
                "automatic",
                now,
                format!("booking-period-{}", &result.digest[..24])
            ],
        )?;
    }
    tx.execute(
        &Write::Board.sql(),
        params![python_json(&payload), board_tab, row_id],
    )?;
    Ok(())
}
