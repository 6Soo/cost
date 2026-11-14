//! P1 계획 조립(M3 U9). 원본: `app/automatic_classification.py`의 `plan`(`:460-547`).
//!
//! 읽기만 한다. 보호 순서(완료 기간 → 보류·제외·원본 오류 → 기록된 P2 → 완결된 환불 원결제 → 3820 수동 결정 → 닫힌
//! 검토)를 지나, 이력이 있는 행은 항목 선택을 지키며 귀속을 복원하고 이력이 없는 행은 규칙·예외·여행 추론·예약 근거로
//! 새로 판정한다. 결과는 거래마다 [`Outcome`](`Judgement` 또는 기존 기록 유지)과 Python `plan`과 같은 모양의
//! `targets`·`summary`·`digest`다. 환불 연결은 [`Links`] 뒤에서 들어온다(2차 전환 전에는 Python 어댑터 결과).

mod fresh;
mod input;
mod judgement;

pub use crate::digest::{python_json, sha256_hex};
pub use input::{BoardRow, FIELDS, Links, PlanInput, ROW_COLUMNS, RefundLink, Row};
pub use judgement::{Keep, Outcome};

use crate::dates::{completed_period, excluded};
use crate::domain::{Judgement, ProtectionReason};
use crate::period::{PeriodEvidence, PeriodRow, verified_period_for};
use crate::trips::{Canonical, Trip, trip_tab};
use fresh::{Fresh, classify_new_row, restore_historical_row, values};
use input::{card_row, evidence_of, text, trip_of};
use serde_json::{Map, Value, json};
use std::collections::{BTreeMap, BTreeSet};
use thiserror::Error;

pub const POLICY: &str = "complete-card-inference-v1";

const USER_SOURCES: [&str; 3] = ["user_decision", "user_exception", "owner_booking"];

#[derive(Debug, Clone, PartialEq, Eq, Error)]
pub enum PlanError {
    #[error("{what}을(를) 읽지 못했다: {id}")]
    Json { id: String, what: String },
}

/// 바뀌는 행 하나(`plan`의 `targets` 원소).
#[derive(Debug, Clone, PartialEq)]
pub struct Target {
    pub id: String,
    /// `FIELDS` 순서의 새 판정 열.
    pub values: [String; 7],
    pub revision: Value,
    pub has_prior_classification: bool,
    pub booking_trip_correction: bool,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Summary {
    pub to_classify: usize,
    pub protected: usize,
    pub valid_trips: usize,
    pub scanned: usize,
    pub reviewed: usize,
    pub reconsider: bool,
}

#[derive(Debug, Clone, PartialEq)]
pub struct PlanResult {
    pub digest: String,
    pub targets: Vec<Target>,
    pub summary: Summary,
    /// 훑은 순서대로 거래별 결과.
    pub outcomes: Vec<(String, Outcome)>,
}

impl PlanResult {
    /// Python `plan`의 반환 모양(JSON).
    pub fn to_value(&self) -> Value {
        let targets: Vec<Value> = self.targets.iter().map(target_value).collect();
        let s = &self.summary;
        json!({"digest": self.digest, "targets": targets,
            "summary": {"to_classify": s.to_classify, "protected": s.protected, "valid_trips": s.valid_trips,
                "policy": POLICY, "scanned": s.scanned, "reviewed": s.reviewed, "reconsider": s.reconsider}})
    }
}

fn target_value(t: &Target) -> Value {
    let mut map = Map::new();
    map.insert("id".into(), json!(t.id));
    map.insert("values".into(), json!(t.values));
    map.insert("revision".into(), t.revision.clone());
    map.insert(
        "has_prior_classification".into(),
        json!(t.has_prior_classification),
    );
    if t.booking_trip_correction {
        map.insert("booking_trip_correction".into(), json!(true));
    }
    Value::Object(map)
}

/// 판정 계획. `links`는 환불 짝 연결의 출처다. 이용기간 근거 후보는 없다(저장 값만 읽는다).
pub fn plan(input: &PlanInput, links: &dyn Links) -> Result<PlanResult, PlanError> {
    plan_with_periods(input, links, &PeriodEvidence::default())
}

/// [`plan`]에 이용기간 근거를 더한다. 판정마다 이용기간이 함께 정해지고, 근거 digest가 바뀐 거래(`changed`)는
/// 판정 7칸이 그대로여도 새 `Decision`을 낸다(`targets`에는 넣지 않는다: 7칸 쓰기는 없다).
pub fn plan_with_periods(
    input: &PlanInput,
    links: &dyn Links,
    periods: &PeriodEvidence,
) -> Result<PlanResult, PlanError> {
    let all: BTreeMap<&str, &Row> = input.rows.iter().map(|r| (id_of(r), r)).collect();
    let mut rows: Vec<&Row> = input
        .rows
        .iter()
        .filter(|r| input.selected.as_ref().is_none_or(|s| s.contains(id_of(r))))
        .collect();
    rows.sort_by(|a, b| id_of(a).cmp(id_of(b)));
    let typed: Vec<Trip> = input.trips.iter().map(trip_of).collect();
    let tabs: Vec<_> = typed.iter().map(trip_tab).collect();
    let valid = Canonical::new(&typed);
    let valid_trips: Vec<Trip> = valid.iter().cloned().collect();
    let decisions: BTreeMap<String, String> = input.decisions.iter().cloned().collect();
    let ctx = Ctx {
        valid: &valid,
        valid_trips,
        nets: input.nets.clone(),
        links,
        ledger: &input.ledger,
        boards: &input.boards,
        decisions,
        reconsider: input.reconsider,
    };
    let judger = judgement::Judger::new(
        valid.iter().map(|t| t.trip_id.clone()),
        &input.allowed_items,
        &used_items(input),
    );
    // 범위 안 환불이 범위 밖 원결제의 항목·여행을 상속할 수 있도록 원결제를 함께 읽는다.
    let mut resolved: BTreeMap<String, Row> = rows
        .iter()
        .map(|r| (id_of(r).to_string(), (*r).clone()))
        .collect();
    for row in &rows {
        if let Some(link) = links.link(id_of(row))
            && !resolved.contains_key(&link.original_id)
            && let Some(original) = all.get(link.original_id.as_str())
        {
            resolved.insert(link.original_id.clone(), (*original).clone());
        }
    }
    let mut order: Vec<&Row> = rows.clone();
    order.sort_by(|a, b| {
        let key = |r: &Row| {
            (
                text(r, "transaction_direction") != "purchase",
                id_of(r).to_string(),
            )
        };
        key(a).cmp(&key(b))
    });
    let (mut targets, mut outcomes, mut protected) = (Vec::new(), Vec::new(), 0usize);
    let decide = |row: &Row, chosen: &Row, tid: &str, has_history: bool, fact: Option<&Value>| {
        let original = links
            .link(tid)
            .filter(|l| !l.inferred)
            .map(|l| l.original_id.as_str());
        let board = input.boards.get(&format!("card-{tid}"));
        let period_row = PeriodRow::for_card(tid, board.map(|b| b.payload_json.as_str()));
        let period = verified_period_for(&period_row, periods.facts_of(tid));
        judger.decide(row, chosen, tid, has_history, original, (fact, &period))
    };
    // 판정 7칸이 같아도 이용기간 근거가 바뀐 거래는 새 판정을 낸다.
    let kept = |tid: String, judged: Option<Judgement>| match judged {
        Some(j) => (tid, Outcome::Judged(j)),
        None => (tid, Outcome::Kept(Keep::Current)),
    };
    for row in order {
        let tid = id_of(row).to_string();
        let source = text(row, "classification_source");
        let fact = input.evidence.get(&tid);
        let manual =
            ctx.decisions.contains_key(&tid) || input.overrides.contains(&format!("card-{tid}"));
        let completed_evidence = fact.map(evidence_of);
        if excluded(&card_row(row), &tabs, completed_evidence.as_ref(), manual) {
            protected += 1;
            let day = card_row(row).dates;
            let judged = completed_period(&day).map_or(
                Judgement::Protected(ProtectionReason::DateBroken),
                judgement::completed,
            );
            outcomes.push((tid, Outcome::Judged(judged)));
            continue;
        }
        let held = input.holds.contains(&tid);
        let dropped = input.excluded.contains(&tid);
        if held
            || dropped
            || ["parse_error", "duplicate_of", "conflict_reason"]
                .iter()
                .any(|k| !text(row, k).is_empty())
        {
            protected += 1;
            let reason = judgement::protection(row, held, dropped);
            outcomes.push((tid, Outcome::Judged(Judgement::Protected(reason))));
            continue;
        }
        if source == "ai_inference" {
            outcomes.push((tid, Outcome::Kept(Keep::RecordedAiJudgement)));
            continue;
        }
        if refund_original_is_complete(row, &source, links.link(&tid), input.reconsider) {
            outcomes.push((tid, Outcome::Kept(Keep::CompleteRefundOriginal)));
            continue;
        }
        let decided_at = row.get("decided_at").is_some_and(|v| !v.is_null());
        if text(row, "card_tail") == "3820"
            && (decided_at || ["user_decision", "user_exception"].contains(&source.as_str()))
        {
            protected += 1;
            outcomes.push((
                tid,
                Outcome::Judged(Judgement::Protected(ProtectionReason::ManualDecision)),
            ));
            continue;
        }
        if input.closed_reviews.contains(&tid) {
            protected += 1;
            outcomes.push((
                tid,
                Outcome::Judged(Judgement::Protected(ProtectionReason::ClosedReview)),
            ));
            continue;
        }
        let has_history = ctx.decisions.contains_key(&tid)
            || decided_at
            || USER_SOURCES.contains(&source.as_str())
            || input.overrides.contains(&format!("card-{tid}"));
        let current = values(row);
        let mut chosen = row.clone();
        if has_history {
            restore_historical_row(&ctx, row, &mut chosen, &tid)?;
        } else {
            let row_evidence = if (input.ledger.contains_key(&tid)
                || input.boards.contains_key(&format!("card-{tid}")))
                && has_refund(&input.rows, row)
            {
                None
            } else {
                fact
            };
            match classify_new_row(&ctx, &resolved, row, &mut chosen, &tid, row_evidence)? {
                Fresh::Protected => {
                    protected += 1;
                    let reason = Judgement::Protected(ProtectionReason::Unattributable);
                    outcomes.push((tid, Outcome::Judged(reason)));
                    continue;
                }
                Fresh::Unchanged => {
                    let judged = periods
                        .changed
                        .contains(&tid)
                        .then(|| decide(row, &chosen, &tid, false, fact));
                    outcomes.push(kept(tid, judged));
                    continue;
                }
                Fresh::Changed => {}
            }
        }
        let now = values(&chosen);
        if now == current {
            let judged = periods
                .changed
                .contains(&tid)
                .then(|| decide(row, &chosen, &tid, has_history, fact));
            outcomes.push(kept(tid, judged));
            continue;
        }
        let basis = text(&chosen, "classification_basis");
        let correction = !has_history
            && input.reconsider
            && fact.is_some_and(|f| f.as_object().is_none_or(|m| !m.is_empty()))
            && text(&chosen, "trip_id") != text(row, "trip_id")
            && basis.contains("예약 이용기간 근거 우선:")
            && (input.boards.contains_key(&format!("card-{tid}"))
                || input.ledger.contains_key(&tid));
        let judged = decide(row, &chosen, &tid, has_history, fact);
        outcomes.push((tid.clone(), Outcome::Judged(judged)));
        targets.push(Target {
            id: tid.clone(),
            values: now,
            revision: row.get("revision").cloned().unwrap_or(Value::Null),
            has_prior_classification: has_history,
            booking_trip_correction: correction,
        });
        resolved.insert(tid, chosen);
    }
    let scanned = rows.len();
    let summary = Summary {
        to_classify: targets.len(),
        protected,
        valid_trips: valid.iter().count(),
        scanned,
        reviewed: scanned - protected,
        reconsider: input.reconsider,
    };
    let digest = fingerprint(input, &rows, &targets);
    Ok(PlanResult {
        digest,
        targets,
        summary,
        outcomes,
    })
}

fn id_of(row: &Row) -> &str {
    row.get("transaction_id")
        .and_then(Value::as_str)
        .unwrap_or_default()
}

/// `_refund_original_is_complete`.
fn refund_original_is_complete(
    row: &Row,
    source: &str,
    link: Option<&RefundLink>,
    reconsider: bool,
) -> bool {
    if text(row, "classification_state") != "classified" || source != "refund_original" {
        return false;
    }
    let verified = link;
    !reconsider
        || verified.is_some_and(|l| l.inferred)
        || verified.is_none_or(|l| !["full", "partial"].contains(&l.status.as_str()))
}

/// 같은 카드·승인번호를 원승인번호로 가리키는 취소·환불 행이 있는가(원결제는 근거 사실을 쓰지 않는다).
fn has_refund(rows: &[Row], row: &Row) -> bool {
    let approval = row.get("approval_number").and_then(Value::as_str);
    rows.iter().any(|r| {
        let same =
            |key: &str| r.get(key).and_then(Value::as_str).is_some() && r.get(key) == row.get(key);
        same("issuer")
            && same("card_tail")
            && r.get("original_approval_number")
                .and_then(Value::as_str)
                .is_some_and(|o| !o.is_empty() && Some(o) == approval)
            && (["cancellation", "refund"].contains(&text(r, "transaction_direction").as_str())
                || r.get("amount_krw")
                    .and_then(Value::as_i64)
                    .is_some_and(|a| a < 0))
    })
}
/// 계획이 쓰는 입력 안의 항목 이름(실사용 항목).
fn used_items(input: &PlanInput) -> Vec<String> {
    let mut items: Vec<String> = input.rows.iter().map(|r| text(r, "item")).collect();
    items.extend(input.ledger.values().map(|r| text(r, "item")));
    for board in input.boards.values() {
        if let Ok(Value::Object(payload)) = serde_json::from_str::<Value>(&board.payload_json)
            && let Some(item) = payload.get("item").and_then(Value::as_str)
        {
            items.push(item.to_string());
        }
    }
    items
}

/// `json.dumps([context, trips, nets or {}, selected, targets, POLICY, reconsider, evidence])`의 sha256.
fn fingerprint(input: &PlanInput, rows: &[&Row], targets: &[Target]) -> String {
    let set = |s: &BTreeSet<String>| json!(s.iter().collect::<Vec<_>>());
    let decisions: Map<String, Value> = input
        .decisions
        .iter()
        .map(|(t, tab)| (t.clone(), json!(tab)))
        .collect();
    let ledger: Map<String, Value> = input
        .ledger
        .iter()
        .map(|(t, r)| (t.clone(), Value::Object(r.clone())))
        .collect();
    let boards: Map<String, Value> = input
        .boards
        .iter()
        .map(|(id, b)| {
            (
                id.clone(),
                json!([b.display_tab_id, b.payload_json, b.revision]),
            )
        })
        .collect();
    let context = json!([
        rows.iter()
            .map(|r| Value::Object((*r).clone()))
            .collect::<Vec<_>>(),
        decisions,
        set(&input.holds),
        set(&input.excluded),
        set(&input.overrides),
        ledger,
        boards,
    ]);
    let nets: Map<String, Value> = input
        .nets
        .iter()
        .map(|(k, v)| (k.clone(), json!(v)))
        .collect();
    let selected = input.selected.as_ref().map_or(Value::Null, set);
    let evidence: Map<String, Value> = input
        .evidence
        .iter()
        .map(|(k, v)| (k.clone(), v.clone()))
        .collect();
    let payload = json!([
        context,
        input.trips,
        nets,
        selected,
        targets.iter().map(target_value).collect::<Vec<_>>(),
        POLICY,
        input.reconsider,
        evidence,
    ]);
    sha256_hex(&python_json(&payload))
}

/// 계획 한 번 동안 바뀌지 않는 값들.
pub(crate) struct Ctx<'a> {
    pub valid: &'a Canonical,
    pub valid_trips: Vec<Trip>,
    pub nets: BTreeMap<String, i64>,
    pub links: &'a dyn Links,
    pub ledger: &'a BTreeMap<String, Row>,
    pub boards: &'a BTreeMap<String, BoardRow>,
    pub decisions: BTreeMap<String, String>,
    pub reconsider: bool,
}
