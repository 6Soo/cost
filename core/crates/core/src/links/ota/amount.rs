//! 방향·결제 여부·금액 비교(`_direction`·`_event_is_paid`·`compare_payment_amount`·`_approved_delta_match`).

use super::Matcher;
use super::decimal::Dec;
use super::pyval::{get, is_str, pystr, text, truthy};
use super::rule_scope::lag_days;
use regex::Regex;
use serde_json::Value;
use std::sync::LazyLock;

static FOREIGN: LazyLock<Regex> = LazyLock::new(|| {
    Regex::new(r"\A[+-]?(?:[0-9]{1,3}(?:,[0-9]{3})+|[0-9]+)(?:\.[0-9]+)?\z").unwrap()
});

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum AmountStatus {
    Match,
    Mismatch,
    Unknown,
}

/// `compare_payment_amount`의 결과. `reason`은 Python의 사유 코드 그대로다.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct AmountCompare {
    pub status: AmountStatus,
    pub reason: Option<&'static str>,
}

impl AmountCompare {
    const fn new(status: AmountStatus, reason: Option<&'static str>) -> Self {
        AmountCompare { status, reason }
    }
    pub fn is_match(self) -> bool {
        self.status == AmountStatus::Match
    }
}

fn foreign_decimal(v: Option<&Value>) -> Option<Dec> {
    let s = v.map_or_else(|| "None".to_string(), pystr);
    let s = s.trim();
    FOREIGN
        .is_match(s)
        .then(|| Dec::parse(&s.replace(',', "")))
        .flatten()
}

impl Matcher<'_> {
    /// `_direction`.
    pub(super) fn direction(row: &Value) -> String {
        text(row, "transaction_direction").to_lowercase()
    }

    /// `Decimal(str(value))`(유한한 값만).
    pub(super) fn dec_of(v: Option<&Value>) -> Option<Dec> {
        Dec::parse(&v.map_or_else(|| "None".to_string(), pystr))
    }

    /// `_event_is_paid`.
    pub fn event_is_paid(event: &Value) -> bool {
        let kind = get(event, "event_type");
        if !(is_str(kind, "charge") || is_str(kind, "refund")) {
            return false;
        }
        let evidence = get(event, "evidence_status");
        if !(is_str(evidence, "paid_verified") || is_str(evidence, "refund_verified"))
            || !is_str(get(event, "payment_status"), "paid")
        {
            return false;
        }
        if is_str(kind, "refund") {
            return is_str(evidence, "refund_verified")
                && (is_str(get(event, "refund_status"), "refunded")
                    || is_str(get(event, "refund_status"), "refund_completed"));
        }
        is_str(evidence, "paid_verified")
    }

    /// `_event_amount`: 0이 아닌 유한한 금액의 절댓값.
    pub(super) fn event_amount(event: &Value) -> Option<Dec> {
        let v = get(event, "amount_krw")?;
        if v.as_str() == Some("") {
            return None;
        }
        Matcher::dec_of(Some(v))
            .filter(|d| !d.is_zero())
            .map(Dec::abs)
    }

    /// `_card_amount`: 0이 아닌 유한한 부호 있는 금액.
    pub(super) fn card_amount(row: &Value) -> Option<Dec> {
        Matcher::dec_of(get(row, "amount_krw")).filter(|d| !d.is_zero())
    }

    /// `compare_payment_amount`: 증거가 있는 공통 통화에서만 비교한다(환율 추정·허용 오차 없음).
    pub fn compare_payment_amount(&self, event: &Value, row: &Value) -> AmountCompare {
        self.compare_with(event, row, self.rules)
    }

    pub(super) fn compare_with(
        &self,
        event: &Value,
        row: &Value,
        rules: &[Value],
    ) -> AmountCompare {
        use AmountStatus::{Match, Mismatch, Unknown};
        let currency = text(event, "currency").to_uppercase();
        let is_refund = is_str(get(event, "event_type"), "refund");
        if currency == "KRW" {
            let (Some(target), Some(actual)) =
                (Matcher::event_amount(event), Matcher::card_amount(row))
            else {
                return AmountCompare::new(Unknown, Some("AMOUNT_EVIDENCE_REQUIRED"));
            };
            let matched = if is_refund {
                actual.abs() == target
            } else {
                (actual.is_positive() && actual == target)
                    || self.approved_delta_with(event, row, rules)
            };
            return if matched {
                AmountCompare::new(Match, None)
            } else {
                AmountCompare::new(Mismatch, Some("AMOUNT_MISMATCH"))
            };
        }
        if currency.is_empty() {
            return AmountCompare::new(Unknown, Some("AMOUNT_EVIDENCE_REQUIRED"));
        }
        let card_currency = text(row, "foreign_currency").to_uppercase();
        if card_currency.is_empty() || card_currency == "KRW" {
            return AmountCompare::new(Unknown, Some("FX_EVIDENCE_REQUIRED"));
        }
        if card_currency != currency {
            return AmountCompare::new(Mismatch, Some("CURRENCY_MISMATCH"));
        }
        let (Some(expected), Some(signed)) = (
            foreign_decimal(get(event, "amount")),
            foreign_decimal(get(row, "foreign_amount")),
        ) else {
            return AmountCompare::new(Unknown, Some("AMOUNT_EVIDENCE_REQUIRED"));
        };
        if expected.abs() == signed.abs() && (is_refund || signed.is_positive()) {
            AmountCompare::new(Match, None)
        } else {
            AmountCompare::new(Mismatch, Some("AMOUNT_MISMATCH"))
        }
    }

    pub(super) fn amount_matches(&self, event: &Value, row: &Value) -> bool {
        self.compare_payment_amount(event, row).is_match()
    }

    /// `_approved_delta_match`: 승인된 차액·할인율 규칙 또는 트립 항공권 기본 할인 단계.
    pub(super) fn approved_delta_match(&self, event: &Value, row: &Value) -> bool {
        self.approved_delta_with(event, row, self.rules)
    }

    fn approved_delta_with(&self, event: &Value, row: &Value, rules: &[Value]) -> bool {
        if text(event, "currency").to_uppercase() != "KRW"
            || get(event, "amount_krw").is_none()
            || !is_str(get(event, "event_type"), "charge")
            || Matcher::direction(row) != "purchase"
        {
            return false;
        }
        let (Some(card), Some(paid)) = (
            Matcher::dec_of(get(row, "amount_krw")),
            Matcher::dec_of(get(event, "amount_krw")),
        ) else {
            return false;
        };
        let Some(delta) = card.checked_sub(paid) else {
            return false;
        };
        let one = |rule: &Value| Matcher::rule_matches_one(rule, event, row);
        for rule in rules {
            let Some(c) = conditions_of(rule) else {
                continue;
            };
            let Some(expected) = get(c, "amount_delta_krw") else {
                continue;
            };
            if !one(rule) {
                continue;
            }
            if Matcher::dec_of(Some(expected)).is_some_and(|e| e == delta) {
                return true;
            }
        }
        for rule in rules {
            let Some(c) = conditions_of(rule) else {
                continue;
            };
            let Some(rate) = get(c, "discount_rate_bps") else {
                continue;
            };
            if !one(rule) {
                continue;
            }
            let discounted = (|| {
                let amount = Matcher::event_amount(event)?;
                let discount =
                    amount.discount(rate.as_i64()?, get(c, "rounding_mode")?.as_str()?)?;
                let cap = i128::from(get(c, "discount_cap_krw")?.as_i64()?);
                Some(Dec::from_i128(-discount.min(cap)))
            })();
            if discounted.is_some_and(|d| d == delta) {
                return true;
            }
        }
        self.trip_flight_delta(event, row, delta)
    }

    /// 트립 항공권 기본 할인 단계(`trip_flight_charge_delta`).
    fn trip_flight_delta(&self, event: &Value, row: &Value, delta: Dec) -> bool {
        let d = &self.defaults.trip_delta;
        let (low, high) = (Dec::from_int(d.minimum), Dec::from_int(d.maximum));
        d.enabled
            && crate::rules::casefold(&text(event, "provider")) == "trip"
            && d.item_values
                .contains(&crate::rules::casefold(&text(event, "item")))
            && d.currency
                .as_deref()
                .is_some_and(|c| text(event, "currency").to_uppercase() == c)
            && is_str(get(event, "event_type"), "charge")
            && d.direction.as_ref() == get(row, "transaction_direction")
            && low <= delta
            && delta <= high
            && delta
                .checked_sub(low)
                .is_some_and(|x| x.divisible_by(d.step.abs()))
    }

    /// `_foreign_day_lag_match`: 외화 결제의 카드 날짜가 결제일과 하루(설정값) 안쪽으로 다른가.
    pub(super) fn foreign_day_lag_match(&self, event: &Value, row: &Value) -> bool {
        let currency = text(event, "currency").to_uppercase();
        let limit = self.defaults.foreign_date_lag_days;
        let (paid, card) = (get(event, "paid_on"), get(row, "approval_date"));
        if limit == 0 || currency.is_empty() || currency == "KRW" || !truthy(paid) || !truthy(card)
        {
            return false;
        }
        let (Some(paid), Some(card)) = (paid, card) else {
            return false;
        };
        lag_days(&pystr(card), &pystr(paid)).is_some_and(|lag| lag.abs() <= limit)
    }
}

/// `rule.get("conditions", {})`.
fn conditions_of(rule: &Value) -> Option<&Value> {
    match rule.get("conditions") {
        None => Some(&Value::Null),
        Some(Value::Null) => None,
        Some(c) => Some(c),
    }
}
