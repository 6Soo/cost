//! 판정 주체 우선순위와 덮어쓰기(설계 §2.3). 덮어쓰기는 `supersede` 한 곳뿐이다.

use thiserror::Error;

use crate::decision::{Actor, ActorKind, Decision};
use crate::ids::{ModelName, RuleId, RunId};

/// 확정 P1 판정을 AI 검수가 뒤집으려 할 때 남기는 원인 조사 요청(`SPEC.md:130`).
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct RaiseCause {
    pub rule_id: RuleId,
    pub rule_version: u32,
    pub run_id: RunId,
    pub model: ModelName,
}

#[derive(Debug, Clone, PartialEq, Eq, Error)]
pub enum OverrideDenied {
    #[error("더 강한 판정 주체의 판정을 덮을 수 없다")]
    LowerPriority {
        existing: ActorKind,
        proposed: ActorKind,
    },
    #[error("확정 규칙 판정은 AI 검수가 덮을 수 없고 원인 조사를 올린다")]
    RaiseCause(RaiseCause),
    #[error("다른 대상의 판정이다")]
    SubjectMismatch,
    #[error("다른 확정 규칙의 판정은 덮을 수 없다(두 규칙 충돌)")]
    ExactRuleConflict { existing: RuleId, proposed: RuleId },
    #[error("더 낮은 개정 번호의 제안이다")]
    StaleRevision { existing: u32, proposed: u32 },
}

/// 표(기존 행 × 제안 열): 허용이면 `true`. 25칸을 그대로 적는다.
/// (P1Exact×P1Exact는 같은 규칙일 때만 허용 — `supersede`가 규칙 ID를 추가 검사한다.)
pub const fn allowed(existing: ActorKind, proposed: ActorKind) -> bool {
    use ActorKind::{AiReview, Manual, P1Exact, P1Inferred, P2};
    match (existing, proposed) {
        (Manual, Manual) => true,
        (Manual, P1Exact | AiReview | P2 | P1Inferred) => false,
        (P1Exact, Manual | P1Exact) => true,
        (P1Exact, AiReview | P2 | P1Inferred) => false,
        (AiReview, Manual | P1Exact | AiReview) => true,
        (AiReview, P2 | P1Inferred) => false,
        (P2, Manual | P1Exact | AiReview | P2) => true,
        (P2, P1Inferred) => false,
        (P1Inferred, _) => true,
    }
}

/// 제안이 기존 판정을 대체할 수 있으면 제안을 돌려준다.
pub fn supersede(existing: &Decision, proposed: Decision) -> Result<Decision, OverrideDenied> {
    if existing.subject().key() != proposed.subject().key() {
        return Err(OverrideDenied::SubjectMismatch);
    }
    if let (Some(er), Some(pr)) = (existing.subject().revision(), proposed.subject().revision())
        && pr < er
    {
        return Err(OverrideDenied::StaleRevision {
            existing: er,
            proposed: pr,
        });
    }
    let (e, p) = (existing.actor().kind(), proposed.actor().kind());
    if let (Actor::P1Exact { rule_id: a, .. }, Actor::P1Exact { rule_id: b, .. }) =
        (existing.actor(), proposed.actor())
        && a != b
    {
        return Err(OverrideDenied::ExactRuleConflict {
            existing: a.clone(),
            proposed: b.clone(),
        });
    }
    if allowed(e, p) {
        return Ok(proposed);
    }
    if let (
        Actor::P1Exact {
            rule_id,
            rule_version,
        },
        Actor::AiReview { run_id, model },
    ) = (existing.actor(), proposed.actor())
    {
        return Err(OverrideDenied::RaiseCause(RaiseCause {
            rule_id: rule_id.clone(),
            rule_version: *rule_version,
            run_id: run_id.clone(),
            model: model.clone(),
        }));
    }
    Err(OverrideDenied::LowerPriority {
        existing: e,
        proposed: p,
    })
}
