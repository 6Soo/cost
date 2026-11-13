//! 거래 하나의 판정. 원본: `app/classify.py` `classify_transaction`·`_classify_transaction`(`:120-208`, `:304-468`).
//!
//! 여행 해석기가 없는 경로만 옮겼다: 여행을 확인해야 걸리는 규칙(현지·예약 이용기간)은 "여행 확인 실패"로 남고,
//! 후쿠타케·3820 예외·검증된 현지 여행 배정은 U6이 더한다(설계 §7.2).

use super::builtin::Builtin;
use super::matching::{Transaction, is_booking_or_online, rule_matches};
use super::normalize::{Rule, truthy};
use super::text::normalize_merchant;
use crate::dates::{CardRow, RowDates, excluded};
use serde_json::{Map, Value};

const STATE_NEEDS_REVIEW: &str = "needs_review";
const STATE_CLASSIFIED: &str = "classified";
const DEFAULT_TAB: &str = "unclassified";

const OWNER_BOOKING_ORIGIN: &str = "owner-ota-booking";
const OWNER_COUNTRY_EXCEPTION_ORIGIN: &str = "owner-country-exception-20261003";
const PERIOD_OTA_ORIGIN: &str = "auto-ota-period";
const OTA_MAIL_ORIGIN: &str = "ota-mail-live";
const OTA_PORTAL_ORIGIN: &str = "ota-portal-live";
const GUIDE_AIRFARE_ORIGIN: &str = "guide-airfare-live";
const HISTORY_RECOVERY_ORIGIN: &str = "history-recovery-20261003";

/// 판정 결과. 열 이름은 `transactions`의 판정 열과 같다.
#[derive(Debug, Clone, PartialEq, Eq, Default)]
pub struct Verdict {
    pub classification_state: String,
    pub classification_source: String,
    pub classification_basis: String,
    pub item: String,
    pub description: String,
    pub display_tab_id: String,
    pub trip_id: String,
    pub rule_id: String,
}

impl Verdict {
    fn new(state: &str, source: &str, basis: &str) -> Verdict {
        Verdict {
            classification_state: state.into(),
            classification_source: source.into(),
            classification_basis: basis.into(),
            ..Verdict::default()
        }
    }

    fn needs_review(source: &str, basis: &str) -> Verdict {
        Verdict::new(STATE_NEEDS_REVIEW, source, basis)
    }

    pub fn to_value(&self) -> Value {
        let mut map = Map::new();
        for (key, value) in [
            ("classification_state", &self.classification_state),
            ("classification_source", &self.classification_source),
            ("classification_basis", &self.classification_basis),
            ("item", &self.item),
            ("description", &self.description),
            ("display_tab_id", &self.display_tab_id),
            ("trip_id", &self.trip_id),
            ("rule_id", &self.rule_id),
        ] {
            map.insert(key.to_string(), Value::String(value.clone()));
        }
        Value::Object(map)
    }
}

/// `classify_transaction`(여행 해석기 없음). `prior_decision`은 이 거래에 이미 있는 사용자 답변이다.
pub fn classify(
    txn: &Transaction,
    rules: &[Rule],
    prior_decision: Option<&Map<String, Value>>,
    builtin: &Builtin,
) -> Verdict {
    let all: Vec<&Rule> = rules.iter().collect();
    classify_with(txn, &all, prior_decision, true, builtin)
}

fn text_field(txn: &Transaction, key: &str) -> Option<String> {
    txn.get(key).and_then(Value::as_str).map(str::to_string)
}

fn classify_with(
    txn: &Transaction,
    rules: &[&Rule],
    prior: Option<&Map<String, Value>>,
    allow_defaults: bool,
    builtin: &Builtin,
) -> Verdict {
    let row = CardRow {
        dates: RowDates {
            approval_date: text_field(txn, "approval_date"),
            posting_date: text_field(txn, "posting_date"),
        },
        trip_id: text_field(txn, "trip_id"),
        display_tab_id: text_field(txn, "display_tab_id"),
        source_hash: text_field(txn, "source_hash"),
    };
    // 완료 기간 행은 규칙보다 먼저 막는다. 날짜를 읽을 수 없는 행도 같은 쪽(보호)으로 닫힌다.
    if excluded(&row, &[], None, false) {
        let or_default = |key: &str, default: &str| {
            let value = txn.text(key);
            if value.is_empty() {
                default.to_string()
            } else {
                value
            }
        };
        return Verdict {
            classification_state: or_default("classification_state", STATE_NEEDS_REVIEW),
            classification_source: or_default("classification_source", ""),
            classification_basis: or_default("classification_basis", ""),
            item: or_default("item", ""),
            description: or_default("description", ""),
            display_tab_id: or_default("display_tab_id", ""),
            trip_id: or_default("trip_id", ""),
            rule_id: or_default("rule_id", ""),
        };
    }
    let (inferred, regular): (Vec<&Rule>, Vec<&Rule>) = rules
        .iter()
        .copied()
        .partition(|r| r.optional.get("inferred_assignment").is_some_and(truthy));
    let verdict = classify_regular(txn, &regular, prior, allow_defaults, builtin);
    let prior = prior.filter(|p| !p.is_empty());
    if prior.is_some()
        || txn.has("parse_error")
        || !verdict.trip_id.is_empty()
        || verdict.classification_source == "rule_conflict"
    {
        return verdict;
    }
    let mut matches: Vec<&Rule> = inferred
        .iter()
        .copied()
        .filter(|r| rule_matches(r, txn).0)
        .collect();
    if matches.is_empty() {
        return verdict;
    }
    // 사용자가 예약마다 고른 여행 > 확정 예약 메일의 이용기간 > 나머지.
    let owned: Vec<&Rule> = matches
        .iter()
        .copied()
        .filter(|r| r.origin == OWNER_BOOKING_ORIGIN)
        .collect();
    let booked: Vec<&Rule> = matches
        .iter()
        .copied()
        .filter(|r| r.origin == PERIOD_OTA_ORIGIN)
        .collect();
    if !owned.is_empty() {
        matches = owned;
    } else if !booked.is_empty() {
        matches = booked;
    }
    let proposal = |r: &Rule| {
        let trip = inference(r, "trip_id").to_string();
        let tab = r
            .effects
            .get("display_tab_id")
            .map_or(String::new(), |v| v.to_string());
        let item = r
            .effects
            .get("item")
            .map_or(String::new(), |v| v.to_string());
        (item, tab, trip)
    };
    let first = proposal(matches[0]);
    if matches.iter().any(|r| proposal(r) != first) {
        return Verdict {
            classification_state: STATE_NEEDS_REVIEW.into(),
            classification_source: "inference_conflict".into(),
            classification_basis: "추론 배정안이 서로 달라 확인이 필요합니다".into(),
            ..verdict
        };
    }
    let rank = |r: &Rule| match inference(r, "confidence") {
        "중간" => 1,
        "높음" => 2,
        _ => 0,
    };
    let rule = matches
        .iter()
        .copied()
        .min_by(|a, b| {
            (std::cmp::Reverse(rank(a)), &a.rule_id).cmp(&(std::cmp::Reverse(rank(b)), &b.rule_id))
        })
        .expect("matches is not empty");
    let target = inference(rule, "trip_id").to_string();
    let basis = inference(rule, "basis");
    if !target.is_empty() {
        // 여행 해석기가 없어 이 추론이 가리키는 여행을 확인할 수 없다.
        if rule.origin == OWNER_BOOKING_ORIGIN {
            return Verdict {
                classification_state: STATE_NEEDS_REVIEW.into(),
                classification_basis: "사용자가 고른 여행의 일정 원본을 다시 확인해야 합니다"
                    .into(),
                ..verdict
            };
        }
        return verdict;
    }
    let confidence = inference(rule, "confidence");
    let exception = rule.origin == OWNER_COUNTRY_EXCEPTION_ORIGIN;
    let (source, basis_text, tab) = match rule.origin.as_str() {
        GUIDE_AIRFARE_ORIGIN => (
            "guide_airfare_evidence",
            format!("대장·가이드 항공권 근거 · {basis}"),
            "",
        ),
        OWNER_BOOKING_ORIGIN => ("owner_booking", format!("예약 배정 · {basis}"), ""),
        // 여행 후보만 보완하는 규칙은 임시 배정 기록이 필요해 여행 해석기가 생긴 뒤 옮긴다. 그때까지는 판정을 바꾸지 않는다.
        "automatic-trip-priority" => return verdict,
        _ if exception => (
            "user_exception",
            format!("사용자 예외 · {basis}"),
            DEFAULT_TAB,
        ),
        _ => (
            "inference",
            format!("추론 배정 · {confidence} · {basis}"),
            DEFAULT_TAB,
        ),
    };
    Verdict {
        classification_state: STATE_CLASSIFIED.into(),
        classification_source: source.into(),
        classification_basis: basis_text,
        item: rule.effect("item").into(),
        description: rule.effect("description").into(),
        display_tab_id: tab.into(),
        trip_id: String::new(),
        rule_id: rule.rule_id.clone(),
    }
}

fn inference<'a>(rule: &'a Rule, key: &str) -> &'a str {
    rule.optional
        .get("inferred_assignment")
        .and_then(|i| i.get(key))
        .and_then(Value::as_str)
        .unwrap_or("")
}

fn without(rule: &Rule, key: &str) -> Rule {
    let mut copy = rule.clone();
    copy.optional.remove(key);
    copy
}

struct Hit<'a> {
    rule: &'a Rule,
    reasons: Vec<&'static str>,
    target: String,
}

impl Hit<'_> {
    fn same(&self, other: &Hit) -> bool {
        self.rule == other.rule && self.target == other.target
    }

    fn is_history_v1(&self) -> bool {
        self.rule.origin == HISTORY_RECOVERY_ORIGIN && self.rule.version == 1
    }

    fn item(&self) -> Option<&Value> {
        self.rule.effects.get("item")
    }

    fn has_source_hash(&self) -> bool {
        self.rule.opt("source_hash").is_some()
    }

    /// `target or effects.display_tab_id or ''`
    fn tab(&self) -> String {
        if self.target.is_empty() {
            self.rule.effect("display_tab_id").to_string()
        } else {
            self.target.clone()
        }
    }
}

fn classify_regular(
    txn: &Transaction,
    rules: &[&Rule],
    prior: Option<&Map<String, Value>>,
    allow_defaults: bool,
    builtin: &Builtin,
) -> Verdict {
    if txn.has("parse_error") {
        return Verdict::needs_review(
            "unreadable",
            &format!("금액을 읽지 못했어요: {}", txn.text("parse_error")),
        );
    }
    if let Some(prior) = prior.filter(|p| !p.is_empty()) {
        let field = |key: &str| {
            prior
                .get(key)
                .and_then(Value::as_str)
                .unwrap_or("")
                .to_string()
        };
        return Verdict {
            classification_state: STATE_CLASSIFIED.into(),
            classification_source: "previous_decision".into(),
            classification_basis: "이 거래에 이미 사용자 답변이 있어요".into(),
            item: field("item"),
            description: field("description"),
            display_tab_id: field("display_tab_id"),
            trip_id: field("trip_id"),
            rule_id: String::new(),
        };
    }
    let merchant = normalize_merchant(&txn.text("merchant"));
    let is_default = |r: &Rule| r.merchant() == "*";
    let defaults: Vec<&Rule> = if allow_defaults {
        rules.iter().copied().filter(|r| is_default(r)).collect()
    } else {
        Vec::new()
    };
    let rules: Vec<&Rule> = if allow_defaults {
        rules.iter().copied().filter(|r| !is_default(r)).collect()
    } else {
        rules.to_vec()
    };

    let mut matches: Vec<Hit> = Vec::new();
    let mut trip_blocked: Option<&Rule> = None;
    for &candidate in &rules {
        if candidate.opt("travel_country").is_some() {
            if is_booking_or_online(txn) && candidate.opt("booking_period").is_none() {
                continue;
            }
            if !rule_matches(&without(candidate, "travel_country"), txn).0 {
                continue;
            }
            trip_blocked = Some(candidate);
            continue;
        }
        if candidate.opt("booking_period").is_some() {
            if !rule_matches(&without(candidate, "booking_period"), txn).0 {
                continue;
            }
            trip_blocked = Some(candidate);
            continue;
        }
        let (matched, reasons) = rule_matches(candidate, txn);
        if matched {
            matches.push(Hit {
                rule: candidate,
                reasons,
                target: String::new(),
            });
        }
    }

    // 현재 원행의 예약 증거가 과거 자동 복원 규칙보다 구체적이다. 직접 수정된 규칙과 사용자 결정은 지우지 않는다.
    if matches.iter().any(|h| {
        (h.rule.origin == OTA_MAIL_ORIGIN || h.rule.origin == OTA_PORTAL_ORIGIN)
            && h.has_source_hash()
    }) {
        matches.retain(|h| !h.is_history_v1());
    }
    let provider_defaults: Vec<Hit> = matches
        .iter()
        .filter(|h| h.rule.opt("merchant_family").is_some())
        .map(|h| Hit {
            rule: h.rule,
            reasons: Vec::new(),
            target: h.target.clone(),
        })
        .collect();
    if let Some(lead) = provider_defaults.first() {
        let lead_item = lead.item().cloned();
        matches.retain(|h| !(h.is_history_v1() && h.item() != lead_item.as_ref()));
        let detailed = matches.iter().any(|h| {
            !provider_defaults.iter().any(|p| p.same(h))
                && (h.has_source_hash() || !h.target.is_empty())
                && h.item() == lead_item.as_ref()
        });
        if detailed {
            matches.retain(|h| !provider_defaults.iter().any(|p| p.same(h)));
        }
    }
    let source_bound: Vec<(Option<Value>, String)> = matches
        .iter()
        .filter(|h| h.has_source_hash())
        .map(|h| (h.item().cloned(), h.tab()))
        .collect();
    matches.retain(|h| {
        !(h.is_history_v1()
            && !h.has_source_hash()
            && !h.rule.effects.get("description").is_some_and(truthy)
            && source_bound
                .iter()
                .any(|(item, tab)| item.as_ref() == h.item() && *tab == h.tab()))
    });
    let distinct: std::collections::BTreeSet<String> = matches
        .iter()
        .map(|h| format!("{}|{}", Value::Object(h.rule.effects.clone()), h.target))
        .collect();
    if distinct.len() > 1 {
        return Verdict::needs_review(
            "rule_conflict",
            "여러 규칙이 서로 다른 항목을 제안합니다. 확인해 주세요",
        );
    }
    if let Some(hit) = matches
        .iter()
        .min_by(|a, b| a.rule.rule_id.cmp(&b.rule.rule_id))
    {
        return Verdict {
            classification_state: STATE_CLASSIFIED.into(),
            classification_source: "rule".into(),
            classification_basis: format!("규칙: {}", hit.reasons.join(", ")),
            item: hit.rule.effect("item").into(),
            description: hit.rule.effect("description").into(),
            display_tab_id: if hit.target.is_empty() {
                hit.rule.effect("display_tab_id").into()
            } else {
                hit.target.clone()
            },
            trip_id: hit.target.clone(),
            rule_id: hit.rule.rule_id.clone(),
        };
    }

    if let Some(blocked) = trip_blocked {
        let basis = if blocked.opt("booking_period").is_some() {
            "예약 이용기간에 맞는 여행을 확인해 주세요"
        } else {
            "국내·해외 구분과 여행 기간에 맞는 여행이 없습니다"
        };
        return Verdict {
            item: blocked.effect("item").into(),
            description: blocked.effect("description").into(),
            rule_id: blocked.rule_id.clone(),
            ..Verdict::needs_review("travel_location_hold", basis)
        };
    }

    let category = txn.text("description_raw");
    if let Some(industry) = category.strip_prefix("card-category:")
        && let Some(rule) = builtin.category_for(industry.trim())
    {
        return Verdict {
            item: rule.effects.item.clone(),
            display_tab_id: DEFAULT_TAB.into(),
            ..Verdict::new(
                STATE_CLASSIFIED,
                "card_category",
                &format!("{}{}", rule.basis, industry.trim()),
            )
        };
    }
    if let Some(rule) = builtin.provider_default_for(&merchant) {
        return Verdict {
            item: rule.effects.item.clone(),
            description: rule.effects.description.clone(),
            display_tab_id: DEFAULT_TAB.into(),
            rule_id: rule.rule_id.clone(),
            ..Verdict::new(STATE_CLASSIFIED, "provider_default", &rule.basis)
        };
    }
    if let Some(rule) = builtin.pattern_for(&merchant) {
        return Verdict {
            item: rule.effects.item.clone(),
            description: rule.effects.description.clone(),
            display_tab_id: DEFAULT_TAB.into(),
            ..Verdict::new(STATE_CLASSIFIED, "pattern", &rule.basis)
        };
    }

    // 사용자가 지정한 현지 경비 기본값은 구체적 규칙과 명확한 업종 뒤에만 적용한다.
    if !defaults.is_empty() && !is_booking_or_online(txn) {
        return classify_with(txn, &defaults, None, false, builtin);
    }
    if is_booking_or_online(txn) {
        return Verdict::needs_review(
            "booking_evidence_needed",
            "예약 자료로 구매 상품과 이용일을 확인해 주세요",
        );
    }
    Verdict::needs_review("", "적용할 규칙과 분명한 가맹점 이름이 없어 확인할래요")
}
