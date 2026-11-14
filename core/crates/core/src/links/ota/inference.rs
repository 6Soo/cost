//! 결제일 없는 아고다 관측의 엄격한 일대일 추론(`app/ota_inference.py:unique_pairs`). 결과는 정확 연결과 다른
//! 종류([`super::LinkKind::Inferred`])로만 나가고, 점유된 카드와 이미 결제일이 있는 다른 이벤트의 후보는 건드리지 않는다.

use super::Matcher;
use super::pyval::{get, is_str, pystr, text, truthy};
use serde_json::Value;
use std::collections::{BTreeMap, BTreeSet};

pub(super) const BASIS: &str = "mutually_unique_undated_agoda";
pub(super) const NOTE: &str = "추론 연결: 카드 끝자리·원문 금액·전체 자료의 일대일 대응과 이용기간 확인. 실제 결제일은 미확인";

const REFUND_STATES: [&str; 4] = [
    "refund_pending",
    "refund_requested",
    "refunded",
    "refund_completed",
];

fn four_ascii_digits(s: &str) -> bool {
    s.len() == 4 && s.bytes().all(|b| b.is_ascii_digit())
}

fn is_true(v: Option<&Value>) -> bool {
    v == Some(&Value::Bool(true))
}

impl Matcher<'_> {
    /// 이벤트 id → 추론으로 연결할 카드 행 id. `occupied`는 이미 점유된 카드다.
    pub(super) fn inferred_pairs(
        &self,
        events: &[Value],
        transactions: &[Value],
        occupied: &BTreeSet<String>,
    ) -> BTreeMap<String, String> {
        let mut result = BTreeMap::new();
        if !self.defaults.agoda_undated_unique_match {
            return result;
        }
        let bare = Matcher::new(self.defaults, &[]);
        for event in events {
            if !is_str(get(event, "provider"), "agoda")
                || truthy(get(event, "paid_on"))
                || !is_str(get(event, "event_type"), "charge")
                || !Matcher::event_is_paid(event)
                || !is_true(get(event, "verified_portal_snapshot"))
                || !(is_str(get(event, "reservation_status"), "confirmed")
                    || is_str(get(event, "reservation_status"), "completed"))
                || !(get(event, "refund_status").is_none()
                    || is_str(get(event, "refund_status"), "")
                    || is_str(get(event, "refund_status"), "none_displayed"))
                || !four_ascii_digits(&text(event, "card_last4"))
            {
                continue;
            }
            let period = get(event, "service_period")
                .filter(|p| truthy(Some(p)))
                .cloned()
                .unwrap_or_else(|| Value::Object(Default::default()));
            let day =
                |key: &str| get(&period, key).and_then(|v| crate::dates::parse_iso(&pystr(v)).ok());
            match (day("starts_on"), day("ends_on")) {
                (Some(start), Some(end)) if end > start => {}
                _ => continue,
            }
            let same_booking = |e: &Value| {
                get(e, "provider") == get(event, "provider")
                    && get(e, "booking_ref") == get(event, "booking_ref")
            };
            if events.iter().filter(|e| same_booking(e)).any(|e| {
                is_str(get(e, "reservation_status"), "cancelled")
                    || truthy(get(e, "service_period_conflict"))
                    || is_str(get(e, "event_type"), "refund")
                    || get(e, "refund_status")
                        .and_then(Value::as_str)
                        .is_some_and(|s| REFUND_STATES.contains(&s))
                    || (truthy(get(e, "service_period"))
                        && get(e, "service_period") != Some(&period))
            }) {
                continue;
            }
            let exact = |e: &Value, row: &Value| {
                get(e, "card_last4") == get(event, "card_last4")
                    && self.provider_compatible(e, row)
                    && bare.strict_card_identity(e, row)
                    && bare.compare_with(e, row, &[]).is_match()
            };
            let cards: Vec<&Value> = transactions
                .iter()
                .filter(|row| {
                    Matcher::direction(row) == "purchase"
                        && !truthy(get(row, "duplicate_of"))
                        && exact(event, row)
                })
                .collect();
            let [row] = cards.as_slice() else { continue };
            let card_id = text(row, "transaction_id");
            if truthy(get(row, "parse_error"))
                || truthy(get(row, "conflict_reason"))
                || !is_true(get(row, "ota_inference_eligible"))
                || occupied.contains(&card_id)
            {
                continue;
            }
            let claims = events.iter().filter(|e| {
                is_str(get(e, "provider"), "agoda")
                    && is_str(get(e, "event_type"), "charge")
                    && Matcher::event_is_paid(e)
                    && exact(e, row)
            });
            if claims.count() != 1 {
                continue;
            }
            if events.iter().any(|e| {
                truthy(get(e, "paid_on"))
                    && Matcher::event_is_paid(e)
                    && self.pair_check(e, row).is_none()
            }) {
                continue;
            }
            result.insert(text(event, "ota_event_id"), card_id);
        }
        result
    }
}
