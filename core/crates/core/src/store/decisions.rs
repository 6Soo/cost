//! `core.sqlite`의 판정 저장(설계 §2.7). 쓰기는 `save_decision` 하나다(U11 적용이 유일한 호출자). 판정과 이용기간을 근거 digest·함수 버전과 함께 저장하고,
//! 재판정은 digest·버전이 바뀐 거래만 고른다. 화면은 저장 값만 읽고 렌더 때 다시 계산하지 않는다.

use std::collections::BTreeMap;

use rusqlite::{Connection, OptionalExtension, params};
use serde_json::{Value, json};

use super::StoreError;
use crate::digest::python_json;
use crate::domain::{ActorKind, Decision, ServicePeriod, UnknownPeriodReason};
use crate::period::PERIOD_FN_VERSION;

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

/// 이용기간의 저장 모양(화면·붙여넣기·장부 복사·시트 대사와 Python `stored_service_period`가 읽는 표기).
/// 검증된 기간은 `{"kind":"known","starts_on","ends_on"}`(기존 표기 그대로), 추론은 `{"kind":"inferred","starts_on","ends_on","basis"}`,
/// 모르면 `{"kind":"unknown","reason"}`. 읽는 쪽은 `known`을 검증으로 해석한다.
pub fn period_json(period: &ServicePeriod) -> Value {
    match period {
        ServicePeriod::Known { starts_on, ends_on } => {
            json!({"kind": "known", "starts_on": starts_on.to_string(), "ends_on": ends_on.to_string()})
        }
        ServicePeriod::Inferred {
            starts_on,
            ends_on,
            basis,
        } => {
            json!({"kind": "inferred", "starts_on": starts_on.to_string(), "ends_on": ends_on.to_string(),
                    "basis": basis.as_str()})
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

/// 저장된 판정 행에서 도출한 화면 열 일곱 개(`FIELDS` 순서). 화면 열은 여기서만 도출한다.
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

/// 저장하는 레코드(개정 번호·시각 제외). 같은 레코드면 쓰지 않는다.
fn record(decision: &Decision, legacy_source: &str, evidence_digest: &str) -> Value {
    let evidence: Vec<Value> = decision
        .evidence()
        .iter()
        .map(|e| json!({"sha256": e.sha256.as_str(), "locator": e.locator}))
        .collect();
    let uncertainty: Vec<&str> = decision.uncertainty().iter().map(|u| u.as_str()).collect();
    let policy: Vec<&str> = decision.policy_refs().iter().map(|p| p.as_str()).collect();
    json!({
        "actor_kind": actor_kind_name(decision.actor().kind()),
        // 현 장부의 `classification_source` 값(화면 열 도출용).
        "actor_ref": legacy_source,
        "attribution": python_json(&json!({
            "display_tab_id": decision.attribution().display_tab_id(),
            "trip_id": decision.attribution().trip_id()})),
        "item": decision.item().as_str(),
        "description": decision.description(),
        "service_period_json": python_json(&period_json(decision.service_period())),
        "basis": decision.basis().as_str(),
        "uncertainty_json": python_json(&json!(uncertainty)),
        "policy_refs_json": python_json(&json!(policy)),
        "evidence_ids_json": python_json(&Value::Array(evidence)),
        "evidence_digest": evidence_digest,
        "period_fn_version": PERIOD_FN_VERSION,
    })
}

const RECORD_COLUMNS: [&str; 14] = [
    "source_hash",
    "revision",
    "actor_kind",
    "actor_ref",
    "attribution",
    "item",
    "description",
    "service_period_json",
    "basis",
    "uncertainty_json",
    "policy_refs_json",
    "evidence_ids_json",
    "evidence_digest",
    "period_fn_version",
];

/// 판정 저장의 **유일한 쓰기 경로**다. 호출자는 U11 적용(`crate::apply`) 하나이며 `plan_with_periods`의 `Decision`과
/// [`crate::period::current_digests`]의 digest를 함께 넘긴다. 다른 곳에서 `decisions`를 직접 쓰지 않는다.
///
/// 거래 ID 키로 덮어써 저장한다. 근거 digest·함수 버전은 새 행과 갱신 모두에 쓴다(안 그러면 재판정이 변경을 놓친다).
/// 레코드가 같으면 아무것도 쓰지 않고 `false`. 이전 행이 있었으면 전후 레코드와 `request_id`를 이력에 남긴다.
/// `schema`는 `decisions`가 있는 데이터베이스 이름(`main` 또는 ATTACH한 `core`).
#[allow(clippy::too_many_arguments)]
pub fn save_decision(
    conn: &Connection,
    schema: &str,
    decision: &Decision,
    legacy_source: &str,
    evidence_digest: &str,
    revision: i64,
    now: &str,
    request_id: &str,
) -> Result<bool, StoreError> {
    let (Some(tid), Some(source_hash)) = (
        decision.subject().card_txn_id(),
        decision.subject().source_hash(),
    ) else {
        return Err(StoreError::Sqlite(rusqlite::Error::InvalidParameterName(
            "카드 거래가 아닌 판정".to_owned(),
        )));
    };
    let tid = tid.to_string();
    let mut after = record(decision, legacy_source, evidence_digest);
    after["source_hash"] = json!(source_hash.as_str());
    after["revision"] = json!(revision);
    let before: Option<Value> = conn
        .query_row(
            &format!(
                "SELECT {} FROM {schema}.decisions WHERE transaction_id=?",
                RECORD_COLUMNS.join(",")
            ),
            [&tid],
            |r| {
                let mut m = serde_json::Map::new();
                for (i, name) in RECORD_COLUMNS.iter().enumerate() {
                    let v = match r.get_ref(i)? {
                        rusqlite::types::ValueRef::Integer(n) => json!(n),
                        rusqlite::types::ValueRef::Text(t) => json!(String::from_utf8_lossy(t)),
                        _ => Value::Null,
                    };
                    m.insert((*name).to_owned(), v);
                }
                Ok(Value::Object(m))
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
             description,service_period_json,basis,uncertainty_json,policy_refs_json,evidence_ids_json,decided_at,
             evidence_digest,period_fn_version)
             VALUES (?1,?2,?3,?4,?5,?6,?7,?8,?9,?10,?11,?12,?13,?14,?15,?16)
             ON CONFLICT(transaction_id) DO UPDATE SET source_hash=?2,revision=?3,actor_kind=?4,actor_ref=?5,
             attribution=?6,item=?7,description=?8,service_period_json=?9,basis=?10,uncertainty_json=?11,
             policy_refs_json=?12,evidence_ids_json=?13,decided_at=?14,evidence_digest=?15,period_fn_version=?16"
        ),
        params![
            tid,
            source_hash.as_str(),
            revision,
            text("actor_kind"),
            text("actor_ref"),
            text("attribution"),
            text("item"),
            text("description"),
            text("service_period_json"),
            text("basis"),
            text("uncertainty_json"),
            text("policy_refs_json"),
            text("evidence_ids_json"),
            now,
            evidence_digest,
            PERIOD_FN_VERSION,
        ],
    )?;
    if let Some(before) = before {
        conn.execute(
            &format!(
                "INSERT INTO {schema}.decision_history(transaction_id,before_json,after_json,actor_kind,request_id,at)
                 VALUES (?,?,?,?,?,?)"
            ),
            params![
                tid,
                python_json(&before),
                python_json(&after),
                text("actor_kind"),
                request_id,
                now
            ],
        )?;
    }
    Ok(true)
}

/// 저장된 거래별 근거 digest. 함수 버전이 현재와 다른 거래는 digest를 비워(재판정 대상) 돌려준다.
pub fn stored_digests(conn: &Connection) -> Result<BTreeMap<String, String>, StoreError> {
    stored_digests_in(conn, "main")
}

/// [`stored_digests`]의 데이터베이스 이름 지정판(ATTACH한 `core`).
pub fn stored_digests_in(
    conn: &Connection,
    schema: &str,
) -> Result<BTreeMap<String, String>, StoreError> {
    let mut stmt = conn.prepare(&format!(
        "SELECT transaction_id, evidence_digest, period_fn_version FROM {schema}.decisions"
    ))?;
    let found = stmt
        .query_map([], |r| {
            Ok((
                r.get::<_, String>(0)?,
                r.get::<_, String>(1)?,
                r.get::<_, u32>(2)?,
            ))
        })?
        .collect::<Result<Vec<_>, _>>()?;
    Ok(found
        .into_iter()
        .map(|(tid, digest, version)| {
            let digest = if version == PERIOD_FN_VERSION {
                digest
            } else {
                String::new()
            };
            (tid, digest)
        })
        .collect())
}

/// 읽기 전용으로 연 `core.sqlite`의 저장 digest. 파일이 없거나 이 단위 이전 스키마면 저장된 판정이 없는 것으로 본다.
pub fn stored_digests_readonly(
    path: &std::path::Path,
) -> Result<BTreeMap<String, String>, StoreError> {
    if !path.is_file() {
        return Ok(BTreeMap::new());
    }
    let conn = Connection::open_with_flags(
        path,
        rusqlite::OpenFlags::SQLITE_OPEN_READ_ONLY | rusqlite::OpenFlags::SQLITE_OPEN_NO_MUTEX,
    )?;
    if super::schema::current_version(&conn)? < 2 {
        return Ok(BTreeMap::new());
    }
    stored_digests(&conn)
}

/// 저장된 이용기간(JSON 문자열). 화면·붙여넣기는 이 값을 읽는다.
pub fn stored_period(
    conn: &Connection,
    transaction_id: &str,
) -> Result<Option<String>, StoreError> {
    let found = conn.query_row(
        "SELECT service_period_json FROM decisions WHERE transaction_id=?1",
        [transaction_id],
        |r| r.get(0),
    );
    match found {
        Ok(value) => Ok(Some(value)),
        Err(rusqlite::Error::QueryReturnedNoRows) => Ok(None),
        Err(e) => Err(e.into()),
    }
}
