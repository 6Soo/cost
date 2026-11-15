//! `transactions.classification_source` → 판정 주체 대응표(설계 §3.2).

use super::ActorKind;

/// 결정 이력이 아닌 값(`decided_at`)까지 포함한 한 행의 출처 입력.
#[derive(Debug, Clone, Copy, Default)]
pub struct SourceInput<'a> {
    pub source: &'a str,
    pub basis: &'a str,
    pub has_decided_at: bool,
    /// 근거 규칙의 `origin`(규칙 출처 값). 규칙이 아니면 빈 문자열.
    pub rule_origin: &'a str,
    /// 규칙이 현재 원행의 `source_hash`에 결속돼 있는가.
    pub source_hash_bound: bool,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Mapped {
    Actor {
        kind: ActorKind,
        /// 사용자 예외(`user_exception`·`owner_booking`·`owner_card_residual`)로 표시.
        user_exception: bool,
    },
    /// 판정 없음: 그림자 실행이 새로 판정한다.
    NoJudgement,
    /// 대응표에 없는 값. 호출자는 판정으로 취급하지 말고 보고한다.
    Unrecognized,
}

const P1_EXACT_ORIGINS: [&str; 3] = ["ota-mail-live", "ota-portal-live", "auto-ota-period"];

const NO_JUDGEMENT: [&str; 5] = [
    "rule_conflict",
    "inference_conflict",
    "travel_location_hold",
    "booking_evidence_needed",
    "unreadable",
];

const AI_REVIEW_PREFIX: &str = "AI_REVIEW · ";

fn actor(kind: ActorKind, user_exception: bool) -> Mapped {
    Mapped::Actor {
        kind,
        user_exception,
    }
}

/// 대응 결과와 원래 출처 값. 원 값은 `manual_hold`처럼 판정 주체로는 `Manual`이어도
/// 기록 불가인 값을 U9·U14가 구분하는 데 쓴다.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct Mapping<'a> {
    pub mapped: Mapped,
    pub raw_source: &'a str,
}

impl Mapping<'_> {
    /// `app/automatic_classification.py:53`·`docs/policy/record.md:209`: 사용자 보류는 기록하지 않는다.
    pub fn is_manual_hold(&self) -> bool {
        self.raw_source.trim() == "manual_hold"
    }
}

pub fn map_source(i: SourceInput<'_>) -> Mapping<'_> {
    Mapping {
        mapped: map_source_kind(i),
        raw_source: i.source.trim(),
    }
}

fn map_source_kind(i: SourceInput<'_>) -> Mapped {
    let source = i.source.trim();
    // 실제 결정이 있으면 출처 값과 무관하게 수동이다(`classification_provenance.origin`).
    if i.has_decided_at {
        return actor(ActorKind::Manual, false);
    }
    match source {
        "user_decision" | "manual" | "previous_decision" | "manual_hold" => {
            actor(ActorKind::Manual, false)
        }
        "user_exception" | "owner_booking" => actor(ActorKind::Manual, true),
        "refund_original" | "guide_airfare_evidence" => actor(ActorKind::P1Exact, false),
        "rule" if i.source_hash_bound && P1_EXACT_ORIGINS.contains(&i.rule_origin) => {
            actor(ActorKind::P1Exact, false)
        }
        "owner_card_residual" => actor(ActorKind::P1Inferred, true),
        "rule" | "pattern" | "card_category" | "provider_default" | "inference"
        | "code_inference" | "auto_inferred" => actor(ActorKind::P1Inferred, false),
        "ai_inference" if i.basis.starts_with(AI_REVIEW_PREFIX) => {
            actor(ActorKind::AiReview, false)
        }
        "ai_inference" => actor(ActorKind::P2, false),
        "" => Mapped::NoJudgement,
        s if NO_JUDGEMENT.contains(&s) => Mapped::NoJudgement,
        _ => Mapped::Unrecognized,
    }
}
