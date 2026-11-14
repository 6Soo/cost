//! `core.sqlite`의 `decisions`·`decision_history` 쓰기와 읽기(설계 §3.2). 투영 쓰기가 `board.sqlite` 연결에
//! `core`라는 이름으로 `ATTACH`한 파일에 쓴다. 화면 열(`classification_*`·`item`·`display_tab_id`…)은 **여기 저장된 행에서만**
//! 도출한다([`projection`]). 판정 하나는 거래당 한 행이며, 바뀔 때마다 `decision_history`에 전후 값이 남는다.

use rusqlite::{Connection, OptionalExtension, params};
use serde_json::{Value, json};

use super::StoreError;
use crate::domain::{ActorKind, Decision, ServicePeriod, UnknownPeriodReason};
use crate::plan::python_json;

/// 판정 출처 이름(`decisions.actor_kind` 값).
pub fn actor_kind_name(kind: ActorKind) -> &'static str {
    match kind {
        ActorKind::Manual => "manual",
        ActorKind::P1Exact => "p1_exact",
        ActorKind::AiReview => "ai_review",
        ActorKind::P2 => "p2",
        ActorKind::P1Inferred => "p1_inferred",
    }
}

/// 저장하는 이용기간 표기. 화면·붙여넣기 묶음·장부 복사·시트 대사는 렌더 시점에 계산하지 않고 이 값을 읽는다.
pub fn period_json(period: &ServicePeriod) -> Value {
    match period {
        ServicePeriod::Known { starts_on, ends_on } => {
            json!({"kind": "known", "starts_on": starts_on.to_string(), "ends_on": ends_on.to_string()})
        }
        ServicePeriod::Unknown { reason } => {
            let reason = match reason {
                UnknownPeriodReason::NoEvidence => "no_evidence",
                UnknownPeriodReason::EvidenceAmbiguous => "evidence_ambiguous",
                UnknownPeriodReason::NotApplicable => "not_applicable",
            };
            json!({"kind": "unknown", "reason": reason})
        }
    }
}

/// 저장된 이용기간을 읽는 인터페이스(읽기 전용). 판정이 없으면 `None`, 있으면 저장된 JSON 그대로.
pub fn stored_service_period(
    conn: &Connection,
    schema: &str,
    transaction_id: &str,
) -> Result<Option<Value>, StoreError> {
    let text: Option<String> = conn
        .query_row(
            &format!("SELECT service_period_json FROM {schema}.decisions WHERE transaction_id=?"),
            [transaction_id],
            |r| r.get(0),
        )
        .optional()?;
    Ok(text.and_then(|t| serde_json::from_str(&t).ok()))
}

/// 저장된 판정 행에서 도출한 화면 열 일곱 개(`FIELDS` 순서).
pub fn projection(
    conn: &Connection,
    schema: &str,
    transaction_id: &str,
) -> Result<Option<[String; 7]>, StoreError> {
    let row: Option<(String, String, String, String, String)> = conn
        .query_row(
            &format!(
                "SELECT actor_ref,basis,item,description,attribution FROM {schema}.decisions WHERE transaction_id=?"
            ),
            [transaction_id],
            |r| Ok((r.get(0)?, r.get(1)?, r.get(2)?, r.get(3)?, r.get(4)?)),
        )
        .optional()?;
    Ok(row.map(|(source, basis, item, description, attribution)| {
        let a: Value = serde_json::from_str(&attribution).unwrap_or(Value::Null);
        let text = |k: &str| a[k].as_str().unwrap_or_default().to_owned();
        [
            "classified".to_owned(),
            source,
            basis,
            item,
            description,
            text("display_tab_id"),
            text("trip_id"),
        ]
    }))
}

fn record(decision: &Decision, legacy_source: &str) -> Value {
    let evidence: Vec<Value> = decision
        .evidence()
        .iter()
        .map(|e| json!({"sha256": e.sha256.as_str(), "locator": e.locator}))
        .collect();
    let kind = decision.actor().kind();
    // `actor_ref`에는 현 장부의 `classification_source` 값을 둔다(화면 열 도출용).
    json!({
        "actor_kind": actor_kind_name(kind),
        "actor_ref": legacy_source,
        "attribution": python_json(&json!({
            "display_tab_id": decision.attribution().display_tab_id(),
            "trip_id": decision.attribution().trip_id()})),
        "item": decision.item().as_str(),
        "description": decision.description(),
        "service_period_json": python_json(&period_json(decision.service_period())),
        "basis": decision.basis().as_str(),
        "evidence_ids_json": python_json(&Value::Array(evidence)),
    })
}

/// 판정 행을 저장한다. 내용(개정 번호·시각 제외)이 같으면 아무것도 쓰지 않고 `false`.
#[allow(clippy::too_many_arguments)]
pub fn save(
    conn: &Connection,
    schema: &str,
    decision: &Decision,
    legacy_source: &str,
    source_hash: &str,
    revision: i64,
    now: &str,
    request_id: &str,
) -> Result<bool, StoreError> {
    let tid = decision
        .subject()
        .card_txn_id()
        .map(ToString::to_string)
        .unwrap_or_default();
    let after = record(decision, legacy_source);
    let before: Option<Value> = conn
        .query_row(
            &format!(
                "SELECT actor_kind,actor_ref,attribution,item,description,service_period_json,basis,evidence_ids_json
                 FROM {schema}.decisions WHERE transaction_id=?"
            ),
            [&tid],
            |r| {
                Ok(json!({
                    "actor_kind": r.get::<_, String>(0)?, "actor_ref": r.get::<_, String>(1)?,
                    "attribution": r.get::<_, String>(2)?, "item": r.get::<_, String>(3)?,
                    "description": r.get::<_, String>(4)?, "service_period_json": r.get::<_, String>(5)?,
                    "basis": r.get::<_, String>(6)?, "evidence_ids_json": r.get::<_, String>(7)?,
                }))
            },
        )
        .optional()?;
    if before.as_ref() == Some(&after) {
        return Ok(false);
    }
    let text = |k: &str| after[k].as_str().unwrap_or_default().to_owned();
    conn.execute(
        &format!(
            "INSERT INTO {schema}.decisions(transaction_id,source_hash,revision,actor_kind,actor_ref,attribution,item,
             description,service_period_json,basis,evidence_ids_json,decided_at)
             VALUES (?1,?2,?3,?4,?5,?6,?7,?8,?9,?10,?11,?12)
             ON CONFLICT(transaction_id) DO UPDATE SET source_hash=?2,revision=?3,actor_kind=?4,actor_ref=?5,
             attribution=?6,item=?7,description=?8,service_period_json=?9,basis=?10,evidence_ids_json=?11,decided_at=?12"
        ),
        params![
            tid,
            source_hash,
            revision,
            text("actor_kind"),
            text("actor_ref"),
            text("attribution"),
            text("item"),
            text("description"),
            text("service_period_json"),
            text("basis"),
            text("evidence_ids_json"),
            now
        ],
    )?;
    conn.execute(
        &format!(
            "INSERT INTO {schema}.decision_history(transaction_id,before_json,after_json,actor_kind,request_id,at)
             VALUES (?,?,?,?,?,?)"
        ),
        params![
            tid,
            before.map_or_else(|| "{}".to_owned(), |b| python_json(&b)),
            python_json(&after),
            text("actor_kind"),
            request_id,
            now
        ],
    )?;
    Ok(true)
}
