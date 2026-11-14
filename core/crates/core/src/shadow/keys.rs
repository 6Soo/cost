//! 차이 유형 키와 공개값 허용 목록. `tools/quarter_review/eval_cases.py`의 `validate_public`과 같은 방식:
//! 공개 출력에는 고정 어휘의 값과 건수만 나가고, 거래 ID·금액·가맹점·판정 근거 문장은 들어갈 수 없다.

use super::{ShadowError, Values};
use crate::domain::ActorKind;

/// `eval_cases.ITEM_VOCABULARY`와 같다(시험이 어긋남을 잡는다).
pub const ITEM_VOCABULARY: &[&str] = &[
    "주차비",
    "주유비",
    "통행료",
    "항공료",
    "렌터카",
    "숙박비",
    "식비",
    "편의점",
    "교통비",
    "입장료",
    "여행경비",
    "취소·환불",
    "현지경비",
    "기타경비",
    "분기 기타비용",
    "통신비",
    "소프트웨어구독료",
    "사무용품비",
    "소모품비",
    "대중교통",
    "기타비용",
    "",
];
/// `eval_cases.SOURCE_VOCABULARY`와 같다.
pub const SOURCE_VOCABULARY: &[&str] = &[
    "inference",
    "ai_inference",
    "rule",
    "pattern",
    "code_inference",
    "refund_original",
    "user_exception",
    "owner_booking",
    "card_category",
    "owner_card_residual",
    "auto_inferred",
    "booking_evidence_needed",
    "",
];
pub const STATE_VOCABULARY: &[&str] = &["classified", "needs_review", ""];
pub const ATTRIBUTION_VOCABULARY: &[&str] = &["none", "trip", "quarter"];
pub const OTHER: &str = "other";
pub const OTHER_ITEM: &str = "기타(목록 밖)";
pub const PAIRS: &[&str] = &["A-B", "B-C", "A-C"];
pub const FIELDS: &[&str] = &[
    "state",
    "source",
    "item",
    "attribution",
    "trip",
    "basis",
    "description",
    "period",
    "actor",
];
/// `ActorKind`의 고정 이름. 판정 주체가 없으면 `none`.
pub const ACTOR_VOCABULARY: &[&str] =
    &["Manual", "P1Exact", "AiReview", "P2", "P1Inferred", "none"];

fn label<'a>(value: &'a str, vocabulary: &[&str], fallback: &'a str) -> &'a str {
    if vocabulary.contains(&value) {
        value
    } else {
        fallback
    }
}

pub fn attribution_kind(tab: &str) -> &'static str {
    if tab.is_empty() || tab == "unclassified" {
        "none"
    } else if tab.starts_with("quarter:") {
        "quarter"
    } else {
        "trip"
    }
}

/// 두 판정 값의 차이마다 유형 키 하나. 키 = `쌍|필드|이전 출처|전환`.
pub fn diff_keys(pair: &str, left: &Values, right: &Values) -> Vec<String> {
    let source = label(&left.source, SOURCE_VOCABULARY, OTHER);
    let key = |field: &str, transition: String| format!("{pair}|{field}|{source}|{transition}");
    let mut keys = Vec::new();
    if left.state != right.state {
        keys.push(key(
            "state",
            format!(
                "{}→{}",
                label(&left.state, STATE_VOCABULARY, OTHER),
                label(&right.state, STATE_VOCABULARY, OTHER)
            ),
        ));
    }
    if left.source != right.source {
        keys.push(key(
            "source",
            format!(
                "{}→{}",
                label(&left.source, SOURCE_VOCABULARY, OTHER),
                label(&right.source, SOURCE_VOCABULARY, OTHER)
            ),
        ));
    }
    if left.item != right.item {
        keys.push(key(
            "item",
            format!(
                "{}→{}",
                label(&left.item, ITEM_VOCABULARY, OTHER_ITEM),
                label(&right.item, ITEM_VOCABULARY, OTHER_ITEM)
            ),
        ));
    }
    if left.display_tab_id != right.display_tab_id {
        keys.push(key(
            "attribution",
            format!(
                "{}→{}",
                attribution_kind(&left.display_tab_id),
                attribution_kind(&right.display_tab_id)
            ),
        ));
    } else if left.trip_id != right.trip_id {
        keys.push(key("trip", "differs".to_owned()));
    }
    // 문장·기간 값은 공개 키에 넣지 않고 달라졌다는 사실만 낸다.
    if left.basis != right.basis {
        keys.push(key("basis", "differs".to_owned()));
    }
    if left.description != right.description {
        keys.push(key("description", "differs".to_owned()));
    }
    // 기간·주체는 두 쪽 모두 값이 있을 때만 비교한다(없으면 그 쪽 판정 경로가 내지 않는 값).
    if let (Some(a), Some(b)) = (&left.period, &right.period)
        && a != b
    {
        keys.push(key("period", "differs".to_owned()));
    }
    if let (Some(a), Some(b)) = (left.actor, right.actor)
        && a != b
    {
        keys.push(key(
            "actor",
            format!("{}→{}", actor_label(a), actor_label(b)),
        ));
    }
    keys
}

pub fn actor_label(kind: ActorKind) -> &'static str {
    match kind {
        ActorKind::Manual => "Manual",
        ActorKind::P1Exact => "P1Exact",
        ActorKind::AiReview => "AiReview",
        ActorKind::P2 => "P2",
        ActorKind::P1Inferred => "P1Inferred",
    }
}

/// 키 하나가 허용 목록 안인지 검사한다. 밖이면 `PublicValueNotAllowed`.
pub fn validate_key(key: &str) -> Result<(), ShadowError> {
    let parts: Vec<&str> = key.split('|').collect();
    if super::links::is_link_key(key) {
        return if super::links::link_key_ok(&parts) {
            Ok(())
        } else {
            Err(ShadowError::PublicValueNotAllowed)
        };
    }
    let ok = parts.len() == 4
        && PAIRS.contains(&parts[0])
        && FIELDS.contains(&parts[1])
        && (SOURCE_VOCABULARY.contains(&parts[2]) || parts[2] == OTHER)
        && transition_ok(parts[1], parts[3]);
    if ok {
        Ok(())
    } else {
        Err(ShadowError::PublicValueNotAllowed)
    }
}

fn transition_ok(field: &str, transition: &str) -> bool {
    if matches!(field, "trip" | "basis" | "description" | "period") {
        return transition == "differs";
    }
    let sides: Vec<&str> = transition.split('→').collect();
    if sides.len() != 2 {
        return false;
    }
    sides.iter().all(|side| match field {
        "state" => STATE_VOCABULARY.contains(side) || *side == OTHER,
        "source" => SOURCE_VOCABULARY.contains(side) || *side == OTHER,
        "actor" => ACTOR_VOCABULARY.contains(side),
        "item" => ITEM_VOCABULARY.contains(side) || *side == OTHER_ITEM,
        _ => ATTRIBUTION_VOCABULARY.contains(side),
    })
}
