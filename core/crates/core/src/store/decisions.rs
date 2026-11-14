//! `core.sqlite`의 판정 저장(설계 §2.7). 판정과 이용기간을 근거 digest·함수 버전과 함께 저장하고,
//! 재판정은 digest·버전이 바뀐 거래만 고른다. 화면은 저장 값만 읽고 렌더 때 다시 계산하지 않는다.

use std::collections::BTreeMap;

use rusqlite::{Connection, params};
use serde_json::{Value, json};

use super::StoreError;
use crate::domain::{Actor, Decision, EvidenceKind, ServicePeriod, UnknownPeriodReason};
use crate::period::PERIOD_FN_VERSION;

fn actor_columns(actor: &Actor) -> (&'static str, String) {
    match actor {
        Actor::Manual { event } => ("manual", event.as_str().to_owned()),
        Actor::P1Exact {
            rule_id,
            rule_version,
        } => ("p1_exact", format!("{}@{rule_version}", rule_id.as_str())),
        Actor::AiReview { run_id, .. } => ("ai_review", run_id.as_str().to_owned()),
        Actor::P2 { run_id, .. } => ("p2", run_id.as_str().to_owned()),
        Actor::P1Inferred {
            rule_id,
            rule_version,
            ..
        } => (
            "p1_inferred",
            format!("{}@{rule_version}", rule_id.as_str()),
        ),
    }
}

/// 이용기간의 저장 모양. 알면 `starts_on`·`ends_on`, 모르면 사유.
pub fn period_json(period: &ServicePeriod) -> Value {
    match period {
        ServicePeriod::Known { starts_on, ends_on } => {
            json!({"starts_on": starts_on.to_string(), "ends_on": ends_on.to_string()})
        }
        ServicePeriod::Unknown { reason } => json!({"unknown": match reason {
            UnknownPeriodReason::NoEvidence => "no_evidence",
            UnknownPeriodReason::EvidenceAmbiguous => "evidence_ambiguous",
            UnknownPeriodReason::NotApplicable => "not_applicable",
        }}),
    }
}

fn evidence_kind(kind: EvidenceKind) -> &'static str {
    match kind {
        EvidenceKind::ImportBatchRow => "import_batch_row",
        EvidenceKind::OtaEvidence => "ota_evidence",
        EvidenceKind::Receipt => "receipt",
        EvidenceKind::Manual => "manual",
    }
}

/// 판정 저장의 **유일한 쓰기 경로**다. 호출자는 U11 전환 도구의 적용(apply) 경로 하나이며, 그 경로가 `plan_with_periods`의
/// `Decision`과 [`crate::period::current_digests`]의 digest를 함께 넘긴다. 이 PR은 저장 함수와 재판정 선택까지이고
/// 적용 경로는 U11이 붙인다(그 전에는 시험만 호출한다). 다른 곳에서 `decisions`를 직접 쓰지 않는다.
///
/// 카드 거래 판정 하나를 거래 ID 키로 덮어써 저장한다. 같은 거래의 이전 값은 이력에 남긴다.
pub fn save_decision(
    conn: &Connection,
    decision: &Decision,
    evidence_digest: &str,
    decided_at: &str,
) -> Result<(), StoreError> {
    let (Some(tid), Some(source_hash), Some(revision)) = (
        decision.subject().card_txn_id(),
        decision.subject().source_hash(),
        decision.subject().revision(),
    ) else {
        return Err(StoreError::Sqlite(rusqlite::Error::InvalidParameterName(
            "카드 거래가 아닌 판정".to_owned(),
        )));
    };
    let mut evidence_ids = Vec::new();
    for e in decision.evidence() {
        conn.execute(
            "INSERT OR IGNORE INTO evidence(kind, sha256, locator) VALUES (?1, ?2, ?3)",
            params![evidence_kind(e.kind), e.sha256.as_str(), e.locator],
        )?;
        let id: i64 = conn.query_row(
            "SELECT evidence_id FROM evidence WHERE kind=?1 AND sha256=?2 AND locator=?3",
            params![evidence_kind(e.kind), e.sha256.as_str(), e.locator],
            |r| r.get(0),
        )?;
        evidence_ids.push(id);
    }
    let (kind, reference) = actor_columns(decision.actor());
    let uncertainty: Vec<&str> = decision.uncertainty().iter().map(|u| u.as_str()).collect();
    let policy: Vec<&str> = decision.policy_refs().iter().map(|p| p.as_str()).collect();
    let after = json!({
        "attribution": decision.attribution().display_tab_id(),
        "item": decision.item().as_str(),
        "service_period": period_json(decision.service_period()),
        "evidence_digest": evidence_digest,
    });
    let before: Option<String> = conn
        .query_row(
            "SELECT json_object('attribution',attribution,'item',item,'service_period',
                    json(service_period_json),'evidence_digest',evidence_digest)
             FROM decisions WHERE transaction_id=?1",
            [tid.as_str()],
            |r| r.get(0),
        )
        .ok();
    conn.execute(
        "INSERT INTO decisions(transaction_id, source_hash, revision, actor_kind, actor_ref, attribution,
             item, description, service_period_json, basis, uncertainty_json, policy_refs_json,
             evidence_ids_json, decided_at, evidence_digest, period_fn_version)
         VALUES (?1,?2,?3,?4,?5,?6,?7,?8,?9,?10,?11,?12,?13,?14,?15,?16)
         ON CONFLICT(transaction_id) DO UPDATE SET
             source_hash=excluded.source_hash, revision=excluded.revision, actor_kind=excluded.actor_kind,
             actor_ref=excluded.actor_ref, attribution=excluded.attribution, item=excluded.item,
             description=excluded.description, service_period_json=excluded.service_period_json,
             basis=excluded.basis, uncertainty_json=excluded.uncertainty_json,
             policy_refs_json=excluded.policy_refs_json, evidence_ids_json=excluded.evidence_ids_json,
             decided_at=excluded.decided_at, evidence_digest=excluded.evidence_digest,
             period_fn_version=excluded.period_fn_version",
        params![
            tid.as_str(),
            source_hash.as_str(),
            revision,
            kind,
            reference,
            decision.attribution().display_tab_id(),
            decision.item().as_str(),
            decision.description(),
            period_json(decision.service_period()).to_string(),
            decision.basis().as_str(),
            json!(uncertainty).to_string(),
            json!(policy).to_string(),
            json!(evidence_ids).to_string(),
            decided_at,
            evidence_digest,
            PERIOD_FN_VERSION,
        ],
    )?;
    if let Some(before) = before {
        conn.execute(
            "INSERT INTO decision_history(transaction_id, before_json, after_json, actor_kind, at)
             VALUES (?1,?2,?3,?4,?5)",
            params![tid.as_str(), before, after.to_string(), kind, decided_at],
        )?;
    }
    Ok(())
}

/// 저장된 거래별 근거 digest. 함수 버전이 현재와 다른 거래는 digest를 비워(재판정 대상) 돌려준다.
pub fn stored_digests(conn: &Connection) -> Result<BTreeMap<String, String>, StoreError> {
    let mut stmt =
        conn.prepare("SELECT transaction_id, evidence_digest, period_fn_version FROM decisions")?;
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
