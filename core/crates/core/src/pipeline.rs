//! 운영 판정 진입점: DB 읽기 → 호출자 입력 얹기 → 환불 연결 → `plan` → 목표 목록.
//! `costcore plan`·`apply`가 쓰고, 그림자 실행(`shadow`)은 이 결과를 비교만 한다. `shadow`를 가져오지 않는다.

use std::collections::{BTreeMap, BTreeSet};
use std::path::{Path, PathBuf};

use serde_json::{Value, json};

use crate::bridge::{BridgeError, PythonBridge};
use crate::domain::{ActorKind, Decision, Judgement, ServicePeriod};
use crate::period::PeriodEvidence;
use crate::plan::{Outcome, PlanInput, RefundLink, plan_with_periods};
use crate::store::{StoreError, read_plan_input};

#[derive(Debug, thiserror::Error)]
pub enum PipelineError {
    #[error("PLAN_FAILED")]
    PlanFailed,
    #[error("DB_IS_LIVE")]
    DbIsLive,
    #[error("파이썬 다리 오류: {0}")]
    Bridge(#[from] BridgeError),
    #[error("저장 계층 오류: {0}")]
    Store(#[from] StoreError),
}

/// `app.automatic_classification.FIELDS` 중 비교·보고에 쓰는 값.
#[derive(Debug, Clone, PartialEq, Eq, Default)]
pub struct Values {
    pub state: String,
    pub source: String,
    pub basis: String,
    pub item: String,
    pub description: String,
    pub display_tab_id: String,
    pub trip_id: String,
    /// 이용기간(`시작/끝` 또는 `unknown`). 그 판정 경로가 내지 않으면 `None`이며 비교하지 않는다.
    pub period: Option<String>,
    /// 판정 주체 종류. 알 수 없으면 `None`.
    pub actor: Option<ActorKind>,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Target {
    pub id: String,
    pub values: Values,
    /// 이전 판정 기록이 있었는지(Python `has_prior_classification`).
    pub has_history: bool,
}

#[derive(Debug, Clone)]
pub struct PlanRequest {
    pub db: PathBuf,
    pub transaction_ids: Option<Vec<String>>,
    pub reconsider: bool,
    /// 호출자가 더 넘기는 입력(trips, nets, evidence, links, periods). 파이프라인이 해석한다.
    pub context: Value,
}

pub fn targets_json(targets: &[Target]) -> Value {
    json!({ "targets": targets.iter().map(|t| json!({
        "id": t.id,
        "values": [t.values.state, t.values.source, t.values.basis, t.values.item,
                   t.values.description, t.values.display_tab_id, t.values.trip_id],
    })).collect::<Vec<_>>() })
}

/// 운영 DB 자체는 거부한다(사본만 받는다).
pub fn reject_live_db(db: &Path, host_root: &Path) -> Result<(), PipelineError> {
    let live = host_root.join("data").join("board.sqlite");
    if let (Ok(a), Ok(b)) = (db.canonicalize(), live.canonicalize())
        && (a == b || same_file(&a, &b))
    {
        return Err(PipelineError::DbIsLive);
    }
    Ok(())
}

/// 같은 경로가 아니어도 하드 링크처럼 같은 파일이면 참이다. unsafe 없이 쓸 수 있는 신원만 본다:
/// unix는 (장치, inode), Windows는 길이·생성 시각·수정 시각이 모두 같은 경우(복사본은 생성 시각이 새로 생긴다).
fn same_file(a: &Path, b: &Path) -> bool {
    let (Ok(x), Ok(y)) = (std::fs::metadata(a), std::fs::metadata(b)) else {
        return false;
    };
    #[cfg(unix)]
    {
        use std::os::unix::fs::MetadataExt;
        x.dev() == y.dev() && x.ino() == y.ino()
    }
    #[cfg(not(unix))]
    {
        match (x.created(), y.created(), x.modified(), y.modified()) {
            (Ok(xc), Ok(yc), Ok(xm), Ok(ym)) => x.len() == y.len() && xc == yc && xm == ym,
            _ => false,
        }
    }
}

/// Rust 판정: DB 읽기 어댑터(`read_plan_input`) + `plan`. 환불 짝 연결은 `context.links`가 없으면 `links` 다리에서 받는다.
pub fn run_plan(
    request: &PlanRequest,
    links: Option<&PythonBridge>,
) -> Result<Vec<Target>, PipelineError> {
    let mut input = read_plan_input(&request.db)?;
    let context = &request.context;
    overlay_context(
        &mut input,
        context,
        request.transaction_ids.as_deref(),
        request.reconsider,
    );
    let links = if context["links"].is_object() {
        links_from(&context["links"])
    } else if let Some(bridge) = links {
        bridge.refund_links(&request.db, request.transaction_ids.as_deref())?
    } else {
        BTreeMap::new()
    };
    let periods = PeriodEvidence {
        facts: context["periods"]
            .as_object()
            .map(|m| m.iter().map(|(k, v)| (k.clone(), v.clone())).collect())
            .unwrap_or_default(),
        changed: BTreeSet::new(),
    };
    let result =
        plan_with_periods(&input, &links, &periods).map_err(|_| PipelineError::PlanFailed)?;
    let decisions: BTreeMap<&str, &Decision> = result
        .outcomes
        .iter()
        .filter_map(|(id, outcome)| match outcome {
            Outcome::Judged(Judgement::Decided(d)) => Some((id.as_str(), d)),
            _ => None,
        })
        .collect();
    Ok(result
        .targets
        .iter()
        .map(|t| {
            let decision = decisions.get(t.id.as_str());
            let period = decision.map(|d| match d.service_period() {
                ServicePeriod::Known { starts_on, ends_on } => format!("{starts_on}/{ends_on}"),
                ServicePeriod::Unknown { .. } => "unknown".to_owned(),
            });
            let [
                state,
                source,
                basis,
                item,
                description,
                display_tab_id,
                trip_id,
            ] = t.values.clone();
            Target {
                id: t.id.clone(),
                has_history: t.has_prior_classification,
                values: Values {
                    state,
                    source,
                    basis,
                    item,
                    description,
                    display_tab_id,
                    trip_id,
                    period,
                    actor: decision.map(|d| d.actor().kind()),
                },
            }
        })
        .collect())
}
/// 요청 `context.links`(Python 다리 `links` 출력과 같은 모양)를 환불 연결로 읽는다.
pub fn links_from(value: &Value) -> BTreeMap<String, RefundLink> {
    let text = |v: &Value, key: &str| v[key].as_str().unwrap_or_default().to_owned();
    value
        .as_object()
        .map(|m| {
            m.iter()
                .map(|(tid, link)| {
                    let status = if link["status"].is_null() {
                        text(link, "link_state")
                    } else {
                        text(link, "status")
                    };
                    let link = RefundLink {
                        original_id: text(link, "original_id"),
                        inferred: link["inferred"].as_bool().unwrap_or(false),
                        status,
                    };
                    (tid.clone(), link)
                })
                .collect()
        })
        .unwrap_or_default()
}

/// 호출자가 넘기는 입력(trips·nets·evidence)과 범위·재검토 여부를 DB에서 읽은 입력 위에 얹는다.
pub fn overlay_context(
    input: &mut PlanInput,
    context: &Value,
    transaction_ids: Option<&[String]>,
    reconsider: bool,
) {
    if let Some(trips) = context["trips"].as_array() {
        input.trips = trips.clone();
    }
    if let Some(nets) = context["nets"].as_object() {
        input.nets = nets
            .iter()
            .filter_map(|(k, v)| Some((k.clone(), v.as_i64()?)))
            .collect();
    }
    if let Some(evidence) = context["evidence"].as_object() {
        input.evidence = evidence
            .iter()
            .map(|(k, v)| (k.clone(), v.clone()))
            .collect();
    }
    input.selected = transaction_ids.map(|ids| ids.iter().cloned().collect::<BTreeSet<_>>());
    input.reconsider = reconsider;
}
