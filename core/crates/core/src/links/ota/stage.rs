//! 후보 단계 결과(`_assemble_ota_match_results`의 앞부분). 후보만으로 결정되는 것(미결제·후보 없음 보류·점유된
//! 후보 보류)은 [`Stage::Hold`]로 끝내고, 그 밖의 것은 후보 목록을 [`Stage::Options`]로 넘겨 U14가 배정한다.

use super::Matcher;
use super::amount::AmountStatus;
use super::pyval::{get, is_str, pystr, text, truthy};
use serde_json::{Map, Value};
use std::collections::BTreeSet;

/// 후보 단계에서 끝난 이벤트. `status`·`reason`은 Python 결과 그대로다.
#[derive(Debug, Clone, PartialEq)]
pub struct HoldOutcome {
    pub status: &'static str,
    pub reason: &'static str,
    pub candidates: Vec<Value>,
}

/// 후보가 하나일 때 Python이 붙이는 정확 연결 사유(점유·경합이 없다는 전제는 U14가 확인한다).
#[derive(Debug, Clone, PartialEq)]
pub struct UniqueMatch {
    pub reason: &'static str,
    pub rule_delta_krw: Option<i64>,
    pub discount_cause_confirmed: Option<bool>,
}

#[derive(Debug, Clone, PartialEq)]
pub enum Stage {
    /// 기존 수동·고정·옛 연결이 있는 이벤트. 다시 계산하지 않는다(U14).
    Pinned,
    Hold(HoldOutcome),
    /// 승인 조건을 모두 통과한 점유되지 않은 카드(입력 순서). 배정은 U14.
    Options {
        ids: Vec<Value>,
        unique: Option<UniqueMatch>,
    },
}

fn hold(status: &'static str, reason: &'static str, candidates: Vec<Value>) -> Stage {
    Stage::Hold(HoldOutcome {
        status,
        reason,
        candidates,
    })
}

fn flagged(row: &Value) -> bool {
    ["duplicate_of", "parse_error", "conflict_reason"]
        .iter()
        .any(|k| truthy(get(row, k)))
}

impl Matcher<'_> {
    pub(super) fn unpaid_status(event: &Value) -> &'static str {
        let evidence = get(event, "evidence_status");
        let provider = get(event, "provider").and_then(Value::as_str);
        if ["conflict", "evidence_conflict", "refund_conflict"]
            .iter()
            .any(|s| is_str(evidence, s))
        {
            "HOLD_EVIDENCE_CONFLICT"
        } else if is_str(get(event, "event_type"), "reservation")
            && (matches!(provider, Some("toyoko" | "forest" | "rakuten"))
                || is_str(evidence, "preauthorized")
                || truthy(get(event, "price_change_amount_krw")))
        {
            "RESERVATION_ONLY"
        } else if is_str(get(event, "event_type"), "scheduled_charge")
            || is_str(evidence, "scheduled")
            || is_str(get(event, "payment_status"), "scheduled")
        {
            "PENDING_PAYMENT"
        } else {
            "NOT_CARD_CHARGE"
        }
    }

    /// 이벤트 하나의 후보 단계 결과. `existing_links`는 이벤트 id → 기존 연결이다.
    pub fn candidate_stage(
        &self,
        event: &Value,
        transactions: &[Value],
        existing_links: &Map<String, Value>,
    ) -> Stage {
        let link_of = |id: &str| existing_links.get(id).filter(|l| truthy(Some(l)));
        if link_of(&text(event, "ota_event_id")).is_some() {
            return Stage::Pinned;
        }
        if !Matcher::event_is_paid(event) {
            return hold(
                Matcher::unpaid_status(event),
                "no_verified_paid_evidence",
                Vec::new(),
            );
        }
        if is_str(get(event, "event_type"), "refund")
            && !(is_str(get(event, "refund_status"), "refunded")
                || is_str(get(event, "refund_status"), "refund_completed"))
        {
            return hold(
                "HOLD_EVIDENCE_CONFLICT",
                "refund_not_explicitly_verified",
                Vec::new(),
            );
        }
        let claimed: BTreeSet<String> = existing_links
            .values()
            .filter_map(|link| {
                let id = if link.is_object() {
                    link.get("transaction_id")
                } else {
                    Some(link)
                };
                id.filter(|v| truthy(Some(v))).map(pystr)
            })
            .collect();
        let is_claimed =
            |row: &Value| get(row, "transaction_id").is_some_and(|id| claimed.contains(&pystr(id)));
        let raw = self.eligible_cards(event, transactions);
        let options: Vec<&Value> = raw
            .iter()
            .map(|&i| &transactions[i])
            .filter(|r| !is_claimed(r))
            .collect();
        if !truthy(get(event, "paid_on")) && options.is_empty() {
            return hold(
                "HOLD_DATE_UNKNOWN",
                "payment_date_not_in_source",
                Vec::new(),
            );
        }
        if !options.is_empty() {
            let ids = options
                .iter()
                .map(|r| r.get("transaction_id").cloned().unwrap_or(Value::Null))
                .collect();
            let unique = (options.len() == 1).then(|| self.unique_match(event, options[0]));
            return Stage::Options { ids, unique };
        }
        let blocked: BTreeSet<String> = raw
            .iter()
            .map(|&i| &transactions[i])
            .filter(|r| is_claimed(r))
            .filter_map(|r| {
                get(r, "transaction_id")
                    .filter(|v| truthy(Some(v)))
                    .map(pystr)
            })
            .collect();
        if !blocked.is_empty() {
            let ids = blocked.into_iter().map(Value::String).collect();
            return hold(
                "HOLD_AMBIGUOUS",
                "candidate_cards_reserved_by_existing_or_frozen_link",
                ids,
            );
        }
        self.no_card_hold(event, transactions, &is_claimed)
    }

    /// 후보가 하나도 없을 때의 보류 사유(`HOLD_AMOUNT_UNVERIFIED`·`HOLD_AMOUNT_MISMATCH`·`HOLD_NO_CARD`).
    pub(super) fn no_card_hold(
        &self,
        event: &Value,
        transactions: &[Value],
        is_claimed: &dyn Fn(&Value) -> bool,
    ) -> Stage {
        let want = if is_str(get(event, "event_type"), "refund") {
            "refund"
        } else {
            "purchase"
        };
        let paid_on = get(event, "paid_on");
        let same_day: Vec<&Value> = transactions
            .iter()
            .filter(|r| {
                get(r, "approval_date") == paid_on
                    && Matcher::direction(r) == want
                    && !is_claimed(r)
                    && !flagged(r)
            })
            .collect();
        let comparisons: Vec<_> = same_day
            .iter()
            .filter(|r| {
                self.provider_compatible(event, r)
                    && self.strict_card_identity(event, r)
                    && self.has_corroborator(event, r)
            })
            .map(|r| (*r, self.compare_payment_amount(event, r)))
            .collect();
        let unknown: Vec<_> = comparisons
            .iter()
            .filter(|(_, c)| c.status == AmountStatus::Unknown)
            .collect();
        let id_of = |r: &Value| r.get("transaction_id").cloned().unwrap_or(Value::Null);
        if !unknown.is_empty() {
            let reason = if unknown
                .iter()
                .any(|(_, c)| c.reason == Some("FX_EVIDENCE_REQUIRED"))
            {
                "FX_EVIDENCE_REQUIRED"
            } else {
                "AMOUNT_EVIDENCE_REQUIRED"
            };
            return hold(
                "HOLD_AMOUNT_UNVERIFIED",
                reason,
                unknown.iter().map(|(r, _)| id_of(r)).collect(),
            );
        }
        let wrong: Vec<Value> = comparisons
            .iter()
            .filter(|(_, c)| c.status == AmountStatus::Mismatch)
            .map(|(r, _)| id_of(r))
            .collect();
        if !wrong.is_empty() {
            return hold("HOLD_AMOUNT_MISMATCH", "amount_differs", wrong);
        }
        let exact = same_day
            .iter()
            .any(|r| self.amount_matches(event, r) && self.strict_card_identity(event, r));
        let reason = if exact {
            "exact_card_needs_descriptor_approval"
        } else {
            "no_exact_amount_date_direction_card"
        };
        hold("HOLD_NO_CARD", reason, Vec::new())
    }

    /// 후보가 하나인 이벤트의 정확 연결 사유와 승인 차액.
    pub(super) fn unique_match(&self, event: &Value, row: &Value) -> UniqueMatch {
        let or_zero = |v: &Value, key: &str| {
            let value = get(v, key).filter(|x| truthy(Some(x)));
            Matcher::dec_of(value.or(Some(&Value::from(0))))
        };
        let delta = or_zero(row, "amount_krw")
            .zip(or_zero(event, "amount_krw"))
            .and_then(|(a, b)| a.checked_sub(b));
        let has_delta_rule = Matcher::event_amount(event) != Matcher::card_amount(row)
            && self.approved_delta_match(event, row);
        let trip_delta = has_delta_rule
            && text(event, "provider").to_lowercase() == "trip"
            && self
                .defaults
                .trip_delta
                .item_values
                .contains(&crate::rules::casefold(&text(event, "item")));
        let reason = if !truthy(get(event, "paid_on")) {
            "merchant_amount_card_tail_without_payment_date"
        } else if trip_delta {
            "approved_trip_flight_delta"
        } else if has_delta_rule {
            "approved_delta_rule"
        } else {
            "unique_exact_evidence"
        };
        UniqueMatch {
            reason,
            rule_delta_krw: if has_delta_rule {
                delta.and_then(super::decimal::Dec::trunc)
            } else {
                None
            },
            discount_cause_confirmed: trip_delta.then_some(false),
        }
    }
}
