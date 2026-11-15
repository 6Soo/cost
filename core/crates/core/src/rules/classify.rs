//! 거래 하나의 판정. 원본: `app/classify.py` `classify_transaction`·`_classify_transaction`(`:120-208`, `:304-468`).
//!
//! 여행은 호출자가 넘기는 `TripResolver`가 정한다. 없으면 여행을 확인해야 걸리는 규칙(현지·예약 이용기간)은
//! "여행 확인 실패"로 남는다. 후쿠타케·3820 예외·추론 배정 출처는 `exceptions`의 표를 쓴다(U6).

use super::builtin::Builtin;
use super::exceptions::{
    OWNER_BOOKING, Outcome, TripHint, TripResolver, fukutake, inferred_origin, residual, singapore,
};
use super::matching::{Transaction, rule_matches};
use super::normalize::{Rule, truthy};
use super::text::normalize_merchant;
use crate::dates::{CardRow, RowDates, excluded};
use crate::region::{is_booking_or_online, is_fukutake_purchase, transaction_region};
use serde_json::{Map, Value};

pub(super) const STATE_NEEDS_REVIEW: &str = "needs_review";
pub(super) const STATE_CLASSIFIED: &str = "classified";
const DEFAULT_TAB: &str = "unclassified";

const OTA_MAIL_ORIGIN: &str = "ota-mail-live";
const OTA_PORTAL_ORIGIN: &str = "ota-portal-live";
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
    /// 여행 후보만 보완한 추론의 임시 배정 기록(`automatic-trip-priority`).
    pub provisional_assignment: Option<Value>,
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
        if let Some(decision) = &self.provisional_assignment {
            map.insert("provisional_assignment".to_string(), decision.clone());
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
    classify_with_trips(txn, rules, prior_decision, builtin, None, false)
}

/// `classify_transaction`. `resolver`가 여행을 정하고(없으면 여행 해석기 없음), `residual_policy`는 카드 3820 예외를 켠다.
pub fn classify_with_trips(
    txn: &Transaction,
    rules: &[Rule],
    prior_decision: Option<&Map<String, Value>>,
    builtin: &Builtin,
    resolver: Option<&dyn TripResolver>,
    residual_policy: bool,
) -> Verdict {
    let all: Vec<&Rule> = rules.iter().collect();
    let ctx = Ctx {
        builtin,
        resolver,
        residual_policy,
    };
    classify_with(txn, &all, prior_decision, true, &ctx)
}

#[derive(Clone, Copy)]
struct Ctx<'a> {
    builtin: &'a Builtin,
    resolver: Option<&'a dyn TripResolver>,
    residual_policy: bool,
}

fn text_field(txn: &Transaction, key: &str) -> Option<String> {
    txn.get(key).and_then(Value::as_str).map(str::to_string)
}

const LOCAL_USE_SUFFIX: &str = " · 검증된 여행 기간의 현지 사용";

/// `_verified_local_trip`: 현지 구매로 판단되는 항목만 검증된 여행에 배정한다. 숙박·교통편 예약은 결제일이 이용일이 아닐 수 있다.
fn verified_local_trip(txn: &Transaction, item: &str, ctx: &Ctx) -> String {
    let Some(resolver) = ctx.resolver else {
        return String::new();
    };
    if !txn.has("approval_date")
        || txn.get("transaction_direction").and_then(Value::as_str) != Some("purchase")
        || ["숙박비", "항공료", "렌터카"].contains(&item)
        || txn.text("merchant").contains("승차권")
        || is_booking_or_online(txn)
    {
        return String::new();
    }
    match transaction_region(txn) {
        "" => String::new(),
        region => resolver.resolve(txn, &TripHint::Country(region.to_string())),
    }
}

fn classify_with(
    txn: &Transaction,
    rules: &[&Rule],
    prior: Option<&Map<String, Value>>,
    allow_defaults: bool,
    ctx: &Ctx,
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
            provisional_assignment: None,
        };
    }
    let (inferred, regular): (Vec<&Rule>, Vec<&Rule>) = rules
        .iter()
        .copied()
        .partition(|r| r.optional.get("inferred_assignment").is_some_and(truthy));
    let mut verdict = classify_regular(txn, &regular, prior, allow_defaults, ctx);
    let prior = prior.filter(|p| !p.is_empty());
    if let Some(resolver) = ctx.resolver
        && is_fukutake_purchase(txn)
        && prior.is_none()
        && !["rule_conflict", "owner_booking", "user_exception"]
            .contains(&verdict.classification_source.as_str())
        && !inferred
            .iter()
            .any(|r| r.origin == OWNER_BOOKING.origin && rule_matches(r, txn).0)
    {
        return fukutake(txn, &verdict, resolver);
    }
    if ctx.residual_policy
        && prior.is_none()
        && let Some(exception) = singapore(txn, &verdict, ctx.resolver)
    {
        return exception;
    }
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
        let tab_free_rule = !verdict.rule_id.is_empty()
            && regular.iter().any(|r| {
                r.rule_id == verdict.rule_id && !r.effects.get("display_tab_id").is_some_and(truthy)
            });
        if verdict.classification_source == "rule" && tab_free_rule {
            let trip = verified_local_trip(txn, &verdict.item, ctx);
            if !trip.is_empty() {
                verdict.trip_id = trip.clone();
                verdict.display_tab_id = trip;
                verdict.classification_basis.push_str(LOCAL_USE_SUFFIX);
            }
        }
        if ctx.residual_policy {
            return residual(txn, verdict, ctx.builtin);
        }
        return verdict;
    }
    // 사용자가 예약마다 고른 여행 > 확정 예약 메일의 이용기간 > 나머지.
    let top = matches
        .iter()
        .map(|r| inferred_origin(&r.origin).priority)
        .max()
        .unwrap_or(0);
    if top > 0 {
        matches.retain(|r| inferred_origin(&r.origin).priority == top);
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
    let confidence = inference(rule, "confidence");
    let origin = inferred_origin(&rule.origin);
    if !target.is_empty() {
        let hint = TripHint::InferredTrip {
            trip_id: target.clone(),
            origin: rule.origin.clone(),
        };
        let verified = ctx
            .resolver
            .is_some_and(|r| r.resolve(txn, &hint) == target);
        if !verified {
            return match origin.unverified_basis {
                Some(text) => Verdict {
                    classification_state: STATE_NEEDS_REVIEW.into(),
                    classification_basis: text.into(),
                    ..verdict
                },
                // 근거가 맞지 않는 추론은 여행 없이 둔다. 다른 여행을 제시하지 않는다.
                None => verdict,
            };
        }
    }
    let basis_text = origin.basis(basis, confidence);
    match origin.outcome {
        Outcome::ProvisionalTrip => Verdict {
            classification_state: STATE_CLASSIFIED.into(),
            classification_source: origin.source.into(),
            classification_basis: basis_text,
            item: if verdict.item.is_empty() {
                rule.effect("item").into()
            } else {
                verdict.item.clone()
            },
            display_tab_id: target.clone(),
            trip_id: target.clone(),
            rule_id: rule.rule_id.clone(),
            provisional_assignment: Some(provisional_trip_decision(&target, basis, confidence)),
            ..verdict
        },
        outcome => Verdict {
            classification_state: STATE_CLASSIFIED.into(),
            classification_source: origin.source.into(),
            classification_basis: basis_text,
            item: rule.effect("item").into(),
            description: rule.effect("description").into(),
            display_tab_id: if outcome == Outcome::AssignedOrDefaultTab && target.is_empty() {
                DEFAULT_TAB.into()
            } else {
                target.clone()
            },
            trip_id: target,
            rule_id: rule.rule_id.clone(),
            provisional_assignment: None,
        },
    }
}

/// `provisional_trip_decision`(`app/provisional_assignment.py:15`): 검증된 여행의 임시 배정 기록.
fn provisional_trip_decision(trip_id: &str, basis: &str, confidence: &str) -> Value {
    serde_json::json!({
        "status": "CLASSIFIED",
        "trip_id": trip_id,
        "reason": basis,
        "assignment_source": "automatic",
        "confidence": confidence,
        "candidates": [{"trip_id": trip_id, "basis": basis, "confidence": confidence}],
        "policy_version": "automatic-classification-v2",
    })
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
    ctx: &Ctx,
) -> Verdict {
    let builtin = ctx.builtin;
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
            provisional_assignment: None,
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
        let mut target = String::new();
        let mut trial = txn.clone();
        if let Some(country) = candidate.opt("travel_country") {
            if is_booking_or_online(txn) && candidate.opt("booking_period").is_none() {
                continue;
            }
            if !rule_matches(&without(candidate, "travel_country"), txn).0 {
                continue;
            }
            let country = country.as_str().unwrap_or_default();
            let actual = if country == "local" {
                transaction_region(txn).to_string()
            } else {
                country.to_string()
            };
            if let Some(resolver) = ctx.resolver
                && !actual.is_empty()
            {
                target = resolver.resolve(txn, &TripHint::Country(actual));
            }
            if target.is_empty() {
                trip_blocked = Some(candidate);
                continue;
            }
            trial = txn.with(
                "_verified_travel_country",
                Value::String(country.to_string()),
            );
        } else if candidate.opt("booking_period").is_some() {
            if !rule_matches(&without(candidate, "booking_period"), txn).0 {
                continue;
            }
            if let Some(resolver) = ctx.resolver {
                target = resolver.resolve(txn, &TripHint::BookingPeriod);
            }
            if target.is_empty() {
                trip_blocked = Some(candidate);
                continue;
            }
            trial = txn.with("_booking_verified", Value::Bool(true));
        }
        let (matched, reasons) = rule_matches(candidate, &trial);
        if matched {
            matches.push(Hit {
                rule: candidate,
                reasons,
                target,
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
            provisional_assignment: None,
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
        let trip = verified_local_trip(txn, &rule.effects.item, ctx);
        let suffix = if trip.is_empty() {
            ""
        } else {
            LOCAL_USE_SUFFIX
        };
        return Verdict {
            item: rule.effects.item.clone(),
            display_tab_id: if trip.is_empty() {
                DEFAULT_TAB.into()
            } else {
                trip.clone()
            },
            trip_id: trip,
            ..Verdict::new(
                STATE_CLASSIFIED,
                "card_category",
                &format!("{}{}{suffix}", rule.basis, industry.trim()),
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
        let trip = verified_local_trip(txn, &rule.effects.item, ctx);
        let suffix = if trip.is_empty() {
            ""
        } else {
            LOCAL_USE_SUFFIX
        };
        return Verdict {
            item: rule.effects.item.clone(),
            description: rule.effects.description.clone(),
            display_tab_id: if trip.is_empty() {
                DEFAULT_TAB.into()
            } else {
                trip.clone()
            },
            trip_id: trip,
            ..Verdict::new(
                STATE_CLASSIFIED,
                "pattern",
                &format!("{}{suffix}", rule.basis),
            )
        };
    }

    // 사용자가 지정한 현지 경비 기본값은 구체적 규칙과 명확한 업종 뒤에만 적용한다.
    if !defaults.is_empty() && !is_booking_or_online(txn) {
        return classify_with(
            txn,
            &defaults,
            None,
            false,
            &Ctx {
                residual_policy: false,
                ..*ctx
            },
        );
    }
    if is_booking_or_online(txn) {
        return Verdict::needs_review(
            "booking_evidence_needed",
            "예약 자료로 구매 상품과 이용일을 확인해 주세요",
        );
    }
    Verdict::needs_review("", "적용할 규칙과 분명한 가맹점 이름이 없어 확인할래요")
}
