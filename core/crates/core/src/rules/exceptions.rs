//! 사용자 예외(`owner_exception`)와 추론 배정 출처 우선(`inferred_assignment`)을 데이터 표로 둔다(설계 §4.2 stage 60).
//!
//! 원본: `app/classify.py`(`:134-147`, `:162-208`, `:211-301`)와 `app/reconciliation.py`의 출처 상수.
//! 각 항목은 `DECISION_POLICY.md` §5·`docs/policy/*.md`의 규칙 ID를 단다. 여행을 정하는 일은 호출자가 넘기는
//! [`TripResolver`]가 맡는다(여행 해석기 U8은 이 모듈이 알지 못한다).

use super::builtin::Builtin;
use super::classify::{STATE_CLASSIFIED, STATE_NEEDS_REVIEW, Verdict};
use super::matching::Transaction;
use crate::dates::{parse_iso, quarter_of};

/// 여행 해석기에 묻는 질문. Python `trip_resolver(transaction, hint)`의 `hint`.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum TripHint {
    /// 사용 국가(`JP` 등) 또는 `overseas`·`KR`: 이 국가의 여행 일정에 드는가.
    Country(String),
    /// 예약 이용기간에 맞는 여행.
    BookingPeriod,
    /// 후쿠타케: 결제일 당일 또는 이후 가장 가까운 세토우치 출발 여행.
    Fukutake,
    /// 추론 규칙이 가리킨 여행이 이 거래에 맞는가(맞으면 그 ID를 돌려준다).
    InferredTrip { trip_id: String, origin: String },
    /// 카드 3820의 2026-09-19~24 싱가포르 예외.
    OwnerCard3820Singapore,
}

/// 여행을 정하는 쪽. 빈 문자열은 맞는 여행이 없다는 뜻이다.
pub trait TripResolver {
    fn resolve(&self, txn: &Transaction, hint: &TripHint) -> String;
}

impl<F: Fn(&Transaction, &TripHint) -> String> TripResolver for F {
    fn resolve(&self, txn: &Transaction, hint: &TripHint) -> String {
        self(txn, hint)
    }
}

/// 사용자 예외 규칙 한 건.
#[derive(Debug)]
pub struct OwnerException {
    pub rule_id: &'static str,
    /// `docs/policy/*.md`의 규칙 ID.
    pub policy_ids: &'static [&'static str],
    /// 원래 코드 위치.
    pub origin: &'static str,
    pub card_tail: Option<&'static str>,
    pub period: Option<(&'static str, &'static str)>,
    pub item: &'static str,
    pub source: &'static str,
    pub basis: &'static str,
}

pub const FUKUTAKE: OwnerException = OwnerException {
    rule_id: "owner-fukutake-next-setouchi",
    policy_ids: &["TRIP-072", "ITEM-050"],
    origin: "app/classify.py:134-143",
    card_tail: None,
    period: None,
    item: "입장료",
    source: "rule",
    basis: "사용자 규칙: FUKUTAKE FOUNDATION · 결제일 당일 또는 이후 가장 가까운 세토우치 출발일",
};

pub const CARD3820_SINGAPORE: OwnerException = OwnerException {
    rule_id: "owner-card3820-singapore-20261012",
    policy_ids: &["TRIP-070", "ITEM-037"],
    origin: "app/classify.py:144-147,211-236",
    card_tail: Some("3820"),
    period: Some(("2026-09-19", "2026-09-24")),
    item: "현지경비",
    source: "user_exception",
    basis: "사용자 예외: 2026-09-19~2026-09-24 카드 3820 사용내역은 싱가포르 여행에 배정",
};

pub const CARD3820_RESIDUAL: OwnerException = OwnerException {
    rule_id: "owner-card3820-residual-20261012",
    policy_ids: &["TRIP-071", "ITEM-038"],
    origin: "app/classify.py:159-160,273-301",
    card_tail: Some("3820"),
    period: None,
    item: "분기 기타비용",
    source: "owner_card_residual",
    basis: "사용자 규칙: 기존 대사 후 남은 카드 3820 거래를 분기 기타비용으로 분류",
};

pub const OWNER_EXCEPTIONS: [&OwnerException; 3] =
    [&FUKUTAKE, &CARD3820_SINGAPORE, &CARD3820_RESIDUAL];

/// 추론 배정이 이긴 뒤 판정에 쓰는 방식.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Outcome {
    /// 규칙의 항목·설명을 쓰고 여행이 없으면 탭도 비운다.
    Assigned,
    /// 규칙의 항목·설명을 쓰고 여행이 없으면 `unclassified` 탭.
    AssignedOrDefaultTab,
    /// 여행 후보만 보완한다. 기존 판정의 항목·설명을 유지하고 임시 배정 기록을 남긴다.
    ProvisionalTrip,
}

/// 추론 배정 규칙의 출처 한 종류.
#[derive(Debug)]
pub struct InferredOrigin {
    pub origin: &'static str,
    pub policy_ids: &'static [&'static str],
    /// 높을수록 먼저(같은 거래에 여러 출처가 걸릴 때 가장 높은 층만 남는다).
    pub priority: u8,
    pub source: &'static str,
    /// `{basis}`·`{confidence}`를 채운다.
    pub basis_template: &'static str,
    pub outcome: Outcome,
    /// 여행 확인이 실패했을 때 확인 대기로 돌리는 문구(없으면 판정을 그대로 둔다).
    pub unverified_basis: Option<&'static str>,
}

pub const OWNER_BOOKING: InferredOrigin = InferredOrigin {
    origin: "owner-ota-booking",
    policy_ids: &["TRIP-014", "TRIP-036"],
    priority: 2,
    source: "owner_booking",
    basis_template: "예약 배정 · {basis}",
    outcome: Outcome::Assigned,
    unverified_basis: Some("사용자가 고른 여행의 일정 원본을 다시 확인해야 합니다"),
};
pub const PERIOD_OTA: InferredOrigin = InferredOrigin {
    origin: "auto-ota-period",
    policy_ids: &["TRIP-036"],
    priority: 1,
    source: "inference",
    basis_template: "추론 배정 · {confidence} · {basis}",
    outcome: Outcome::AssignedOrDefaultTab,
    unverified_basis: None,
};
pub const GUIDE_AIRFARE: InferredOrigin = InferredOrigin {
    origin: "guide-airfare-live",
    policy_ids: &["TRIP-063"],
    priority: 0,
    source: "guide_airfare_evidence",
    basis_template: "대장·가이드 항공권 근거 · {basis}",
    outcome: Outcome::Assigned,
    unverified_basis: None,
};
pub const COUNTRY_EXCEPTION: InferredOrigin = InferredOrigin {
    origin: "owner-country-exception-20261003",
    policy_ids: &["DATE-043"],
    priority: 0,
    source: "user_exception",
    basis_template: "사용자 예외 · {basis}",
    outcome: Outcome::AssignedOrDefaultTab,
    unverified_basis: None,
};
pub const AUTOMATIC_TRIP_PRIORITY: InferredOrigin = InferredOrigin {
    origin: "automatic-trip-priority",
    policy_ids: &["TRIP-046"],
    priority: 0,
    source: "inference",
    basis_template: "추론 배정 · 낮음 · {basis}",
    outcome: Outcome::ProvisionalTrip,
    unverified_basis: None,
};
/// 위 표에 없는 출처(과거 장부 복원·OTA 메일·포털 등)의 일반 추론 배정.
pub const PLAIN_INFERENCE: InferredOrigin = InferredOrigin {
    origin: "",
    policy_ids: &["TRIP-085"],
    priority: 0,
    source: "inference",
    basis_template: "추론 배정 · {confidence} · {basis}",
    outcome: Outcome::AssignedOrDefaultTab,
    unverified_basis: None,
};

pub const INFERRED_ORIGINS: [&InferredOrigin; 5] = [
    &OWNER_BOOKING,
    &PERIOD_OTA,
    &GUIDE_AIRFARE,
    &COUNTRY_EXCEPTION,
    &AUTOMATIC_TRIP_PRIORITY,
];

pub fn inferred_origin(origin: &str) -> &'static InferredOrigin {
    INFERRED_ORIGINS
        .iter()
        .copied()
        .find(|o| o.origin == origin)
        .unwrap_or(&PLAIN_INFERENCE)
}

impl InferredOrigin {
    pub(super) fn basis(&self, basis: &str, confidence: &str) -> String {
        self.basis_template
            .replace("{basis}", basis)
            .replace("{confidence}", confidence)
    }
}

fn refund_like(txn: &Transaction) -> bool {
    let kind = txn.text("transaction_kind").to_lowercase();
    ["refund", "cancel", "취소", "승인"]
        .iter()
        .any(|m| kind.contains(m))
}

fn positive_amount(txn: &Transaction) -> bool {
    txn.amount_krw().is_some_and(|a| a > 0)
}

fn is_purchase(txn: &Transaction) -> bool {
    txn.get("transaction_direction")
        .and_then(|v| v.as_str())
        .is_some_and(|d| d == "purchase")
}

fn tail_is(txn: &Transaction, rule: &OwnerException) -> bool {
    txn.get("card_tail").and_then(|v| v.as_str()) == rule.card_tail
}

/// 후쿠타케: 입장료와 가장 가까운 세토우치 여행. 판정 `verdict`의 설명은 그대로 둔다.
pub(super) fn fukutake(
    txn: &Transaction,
    verdict: &Verdict,
    resolver: &dyn TripResolver,
) -> Verdict {
    let target = resolver.resolve(txn, &TripHint::Fukutake);
    Verdict {
        classification_state: STATE_CLASSIFIED.into(),
        classification_source: FUKUTAKE.source.into(),
        classification_basis: FUKUTAKE.basis.into(),
        item: FUKUTAKE.item.into(),
        display_tab_id: if target.is_empty() {
            "unclassified".into()
        } else {
            target.clone()
        },
        trip_id: target,
        rule_id: FUKUTAKE.rule_id.into(),
        ..verdict.clone()
    }
}

/// 3820 싱가포르: 이 기간에는 날짜 추론 없이 소유자가 정한 여행에 배정한다.
pub(super) fn singapore(
    txn: &Transaction,
    verdict: &Verdict,
    resolver: Option<&dyn TripResolver>,
) -> Option<Verdict> {
    let rule = &CARD3820_SINGAPORE;
    let day = ["approval_date", "posting_date"]
        .iter()
        .map(|k| txn.text(k))
        .find(|d| !d.is_empty())
        .unwrap_or_default();
    let (from, to) = rule.period?;
    if !tail_is(txn, rule)
        || !(from <= day.as_str() && day.as_str() <= to)
        || txn.has("parse_error")
        || !is_purchase(txn)
        || refund_like(txn)
        || !positive_amount(txn)
        || parse_iso(&day).is_err()
    {
        return None;
    }
    let target = resolver?.resolve(txn, &TripHint::OwnerCard3820Singapore);
    if target.is_empty() {
        return None;
    }
    let state = if verdict.classification_source == "rule_conflict" {
        STATE_NEEDS_REVIEW
    } else {
        STATE_CLASSIFIED
    };
    Some(Verdict {
        classification_state: state.into(),
        classification_source: rule.source.into(),
        classification_basis: rule.basis.into(),
        item: if verdict.item.is_empty() {
            rule.item.into()
        } else {
            verdict.item.clone()
        },
        display_tab_id: target.clone(),
        trip_id: target,
        rule_id: rule.rule_id.into(),
        ..verdict.clone()
    })
}

const RESIDUAL_SOURCES: [&str; 7] = [
    "",
    "pattern",
    "card_category",
    "booking_evidence_needed",
    "inference",
    "rule",
    "travel_location_hold",
];

/// 3820 잔여: 대사 뒤 남은 거래를 결제 분기 기타비용으로 끝낸다(분류만, 기록 아님).
pub(super) fn residual(txn: &Transaction, verdict: Verdict, builtin: &Builtin) -> Verdict {
    let rule = &CARD3820_RESIDUAL;
    let source = verdict.classification_source.as_str();
    // 해외 사용의 위치 보류는 여행 국가 확인이 먼저다. 국내 사용은 여행과 무관하므로 잔여로 본다.
    if !tail_is(txn, rule)
        || refund_like(txn)
        || !is_purchase(txn)
        || !positive_amount(txn)
        || !RESIDUAL_SOURCES.contains(&source)
        || (source == "travel_location_hold" && txn.has("foreign_currency"))
        || !verdict.trip_id.is_empty()
        || txn.has("parse_error")
    {
        return verdict;
    }
    let day = ["approval_date", "posting_date"]
        .iter()
        .map(|k| txn.text(k))
        .find(|d| !d.is_empty())
        .unwrap_or_default();
    let Ok(day) = parse_iso(&day) else {
        return verdict;
    };
    // 알려진 OTA 결제 표기는 비여행 잔여의 근거가 아니다. 예약·결제 대사를 위해 남겨 둔다.
    let merchant = if txn.has("merchant_normalized") {
        txn.text("merchant_normalized")
    } else {
        txn.text("merchant")
    };
    if builtin.provider_for(&merchant).is_some() {
        return verdict;
    }
    let (year, quarter) = quarter_of(day);
    Verdict {
        classification_state: STATE_CLASSIFIED.into(),
        classification_source: rule.source.into(),
        classification_basis: rule.basis.into(),
        item: rule.item.into(),
        description: format!("{year}년 {quarter}분기 기타비용"),
        display_tab_id: format!("quarter:{year}:{quarter}"),
        trip_id: String::new(),
        rule_id: rule.rule_id.into(),
        ..verdict
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::region::is_fukutake_purchase;

    #[test]
    fn every_exception_and_origin_names_policy_rules() {
        let mut text = String::new();
        let dir = concat!(env!("CARGO_MANIFEST_DIR"), "/../../../docs/policy");
        for entry in std::fs::read_dir(dir).expect("docs/policy") {
            let path = entry.unwrap().path();
            if path.extension().is_some_and(|e| e == "md") {
                text.push_str(&std::fs::read_to_string(path).unwrap());
            }
        }
        let ids = OWNER_EXCEPTIONS
            .iter()
            .flat_map(|e| e.policy_ids.iter())
            .chain(
                INFERRED_ORIGINS
                    .iter()
                    .chain([&&PLAIN_INFERENCE])
                    .flat_map(|o| o.policy_ids.iter()),
            );
        for id in ids {
            assert!(
                text.contains(&format!("### {id} · ")),
                "{id} is not a heading in docs/policy"
            );
        }
        assert!(OWNER_EXCEPTIONS.iter().all(|e| !e.policy_ids.is_empty()));
    }

    #[test]
    fn fukutake_name_needs_a_word_boundary() {
        let t = |m: &str| {
            Transaction::from_value(
                &serde_json::json!({"merchant": m, "transaction_direction": "purchase"}),
            )
        };
        assert!(is_fukutake_purchase(&t("fukutake  foundation")));
        assert!(is_fukutake_purchase(&t(" FUKUTAKE FOUNDATION SHOP")));
        assert!(!is_fukutake_purchase(&t("FUKUTAKE FOUNDATIONS")));
    }
}
