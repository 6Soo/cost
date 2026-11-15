//! M:N 근거 관계(`app/ota_payment_relations.py:attach_relations`). 허용된 모든 간선을 보존하고 같은 카드는 한 번만
//! 센다. 일대일 금융 배정을 만들지 않는다: 보류·부분 그룹은 `MATCHED_GROUP`(거래 ID 없음)으로 바뀐다.

use super::Matcher;
use super::assign::Options;
use super::decimal::Dec;
use super::link::{LinkKind, OtaLink};
use super::pyval::{get, pystr, text, truthy};
use crate::digest::{python_json, sha256_hex};
use serde_json::{Map, Value, json};
use std::collections::{BTreeMap, BTreeSet};

/// `payment_relation`. 금액 합계는 소수 자릿수를 그대로 둔 [`Dec`]다.
#[derive(Debug, Clone, PartialEq)]
pub struct Relation {
    pub relation_id: String,
    pub event_ids: Vec<String>,
    pub transaction_ids: Vec<String>,
    pub group_transaction_ids: Vec<String>,
    pub currency: Option<String>,
    pub booking_count: usize,
    pub source_total_status: &'static str,
    pub source_total: Option<Dec>,
    pub card_total: Option<Dec>,
    pub balance: &'static str,
    pub payment_date_verified: bool,
    pub basis: &'static str,
    pub individual_payment_verified: bool,
}

impl Relation {
    pub(super) fn to_value(&self) -> Value {
        let total = |d: Option<Dec>| d.map_or(Value::Null, |d| Value::String(d.plain()));
        json!({
            "status": "LINKED",
            "relation_id": self.relation_id,
            "event_ids": self.event_ids,
            "transaction_ids": self.transaction_ids,
            "group_transaction_ids": self.group_transaction_ids,
            "event_count": self.event_ids.len(),
            "card_count": self.group_transaction_ids.len(),
            "currency": self.currency,
            "booking_count": self.booking_count,
            "source_total_status": self.source_total_status,
            "source_total": total(self.source_total),
            "card_total": total(self.card_total),
            "balance": self.balance,
            "payment_date_verified": self.payment_date_verified,
            "basis": self.basis,
            "individual_payment_verified": self.individual_payment_verified,
        })
    }
}

fn abs_amount(v: Option<&Value>) -> Option<Dec> {
    Matcher::dec_of(v).filter(|d| !d.is_zero()).map(Dec::abs)
}

fn sum(mut values: impl Iterator<Item = Dec>) -> Option<Dec> {
    values.try_fold(Dec::from_int(0), Dec::checked_add)
}

const ALLOWED: [&str; 4] = [
    "MATCHED_AUTO",
    "HOLD_AMBIGUOUS",
    "HOLD_PARTIAL_GROUP",
    "HOLD_DATE_UNKNOWN",
];
const EVIDENCE_FLAGS: [&str; 4] = [
    "evidence_changed",
    "evidence_missing",
    "service_period_conflict",
    "period_conflict",
];

pub(super) fn attach_relations(
    events: &BTreeMap<String, &Value>,
    cards: &BTreeMap<String, &Value>,
    options: &Options,
    results: &mut [OtaLink],
    existing_links: &Map<String, Value>,
) {
    let status_of: BTreeMap<String, &str> = results
        .iter()
        .map(|r| (r.ota_event_id.clone(), r.status.as_str()))
        .collect();
    let mut edges: BTreeMap<&str, BTreeSet<String>> = BTreeMap::new();
    let mut reverse: BTreeMap<String, BTreeSet<&str>> = BTreeMap::new();
    for (identity, candidates) in options {
        let (Some(event), Some(status)) = (events.get(identity), status_of.get(identity)) else {
            continue;
        };
        if existing_links.contains_key(identity)
            || !ALLOWED.contains(status)
            || EVIDENCE_FLAGS.iter().any(|k| truthy(get(event, k)))
        {
            continue;
        }
        let ids: BTreeSet<String> = candidates
            .iter()
            .filter(|c| truthy(get(c, "transaction_id")))
            .map(|c| text(c, "transaction_id"))
            .collect();
        if !ids.is_empty() {
            for card in &ids {
                reverse.entry(card.clone()).or_default().insert(identity);
            }
            edges.insert(identity, ids);
        }
    }
    let mut visited: BTreeSet<&str> = BTreeSet::new();
    let mut relations: BTreeMap<String, Relation> = BTreeMap::new();
    for first in edges.keys().copied() {
        if visited.contains(first) {
            continue;
        }
        let (mut pending, mut event_set, mut card_set) =
            (vec![first], BTreeSet::new(), BTreeSet::new());
        while let Some(identity) = pending.pop() {
            if !event_set.insert(identity) {
                continue;
            }
            for card in &edges[identity] {
                card_set.insert(card.as_str());
                pending.extend(reverse[card].iter().filter(|e| !event_set.contains(**e)));
            }
        }
        visited.extend(event_set.iter().copied());
        let event_ids: Vec<String> = event_set.iter().map(|s| (*s).to_string()).collect();
        let card_ids: Vec<String> = card_set.iter().map(|s| (*s).to_string()).collect();
        let currencies: BTreeSet<String> = event_ids
            .iter()
            .map(|i| text(events[i], "currency").to_uppercase())
            .collect();
        let currency = (currencies.len() == 1).then(|| currencies.into_iter().next().unwrap());
        let krw = currency.as_deref() == Some("KRW");
        let amounts: Vec<Option<Dec>> = event_ids
            .iter()
            .map(|i| abs_amount(get(events[i], if krw { "amount_krw" } else { "amount" })))
            .collect();
        let card_amounts: Vec<Option<Dec>> = card_ids
            .iter()
            .map(|i| {
                abs_amount(get(
                    cards[i],
                    if krw { "amount_krw" } else { "foreign_amount" },
                ))
            })
            .collect();
        let bookings: Vec<(String, String)> = event_ids
            .iter()
            .map(|i| {
                let e = events[i];
                let booking = if truthy(get(e, "booking_ref")) {
                    text(e, "booking_ref")
                } else {
                    i.clone()
                };
                (text(e, "provider"), booking)
            })
            .collect();
        let mut booking_counts: BTreeMap<&(String, String), usize> = BTreeMap::new();
        for b in &bookings {
            *booking_counts.entry(b).or_default() += 1;
        }
        let mut payment_amounts: BTreeMap<String, Option<Dec>> = BTreeMap::new();
        let mut not_distinct = false;
        for ((identity, booking), amount) in event_ids.iter().zip(&bookings).zip(&amounts) {
            let source = events[identity];
            let payment = if truthy(get(source, "payment_event_id")) {
                Some(pystr(&source["payment_event_id"]))
            } else if truthy(get(source, "payment_id")) && truthy(get(source, "payment_id_scheme"))
            {
                Some(format!(
                    "('{}', '{}', '{}')",
                    text(source, "provider"),
                    text(source, "payment_id_scheme"),
                    text(source, "payment_id")
                ))
            } else {
                None
            };
            if booking_counts[booking] > 1 && payment.is_none() {
                not_distinct = true;
            }
            let key = payment.unwrap_or_else(|| identity.clone());
            if payment_amounts
                .get(&key)
                .is_some_and(|prior| prior != amount)
            {
                not_distinct = true;
            }
            payment_amounts.insert(key, *amount);
        }
        let known = currency.as_deref().is_some_and(|c| !c.is_empty());
        let source_total = (known && !not_distinct && amounts.iter().all(Option::is_some))
            .then(|| sum(payment_amounts.values().flatten().copied()))
            .flatten();
        let card_total = (known && card_amounts.iter().all(Option::is_some))
            .then(|| sum(card_amounts.iter().flatten().copied()))
            .flatten();
        let balance = match (source_total, card_total) {
            (Some(s), Some(c)) if s == c => "BALANCED",
            (Some(_), Some(_)) => "AMOUNT_DIFFERENCE",
            _ => "UNKNOWN",
        };
        let relation_id = format!(
            "ota-relation-{}",
            sha256_hex(&python_json(&json!([event_ids, card_ids])))
        );
        for identity in &event_ids {
            let dated = truthy(get(events[identity], "paid_on"));
            relations.insert(
                identity.clone(),
                Relation {
                    relation_id: relation_id.clone(),
                    event_ids: event_ids.clone(),
                    transaction_ids: edges[identity.as_str()].iter().cloned().collect(),
                    group_transaction_ids: card_ids.clone(),
                    currency: currency.clone(),
                    booking_count: booking_counts.len(),
                    source_total_status: if not_distinct {
                        "OBSERVATIONS_NOT_DISTINCT_PAYMENTS"
                    } else if source_total.is_some() {
                        "VERIFIED_PAYMENT_TOTAL"
                    } else {
                        "AMOUNT_UNVERIFIED"
                    },
                    source_total,
                    card_total,
                    balance,
                    payment_date_verified: dated,
                    basis: if dated {
                        "verified_payment_edges"
                    } else {
                        "merchant_amount_card_tail_without_payment_date"
                    },
                    individual_payment_verified: event_ids.len() == 1 && card_ids.len() == 1,
                },
            );
        }
    }
    for result in results {
        let Some(relation) = relations.remove(&result.ota_event_id) else {
            continue;
        };
        if matches!(
            result.status.as_str(),
            "HOLD_AMBIGUOUS" | "HOLD_PARTIAL_GROUP"
        ) {
            result.status = "MATCHED_GROUP".to_string();
            result.reason = "many_to_many_payment_relation".to_string();
            result.transaction_id = None;
            result.individual_payment_evidence = Some(false);
            result.kind = LinkKind::Relation;
        }
        result.relation = Some(relation);
    }
}
