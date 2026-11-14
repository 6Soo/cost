//! 승인 규칙 범위 검사와 규칙 일치(`_rule_scope_valid`·`_rule_matches`·`_date_lag_bounds`·`_approved_lag_match`).

use super::Matcher;
use super::pyval::{as_int, get, has, pystr, rule_inactive, same, text, truthy};
use crate::dates::parse_iso;
use regex::Regex;
use serde_json::{Map, Value};
use std::sync::LazyLock;

const ALLOWED: [&str; 23] = [
    "provider",
    "item",
    "merchant_normalized",
    "issuer",
    "card_last4",
    "date_lag_days",
    "date_lag_min_days",
    "date_lag_max_days",
    "amount_delta_krw",
    "currency",
    "event_type",
    "discount_rate_bps",
    "discount_cap_krw",
    "minimum_amount_krw",
    "rounding_mode",
    "payment_method",
    "valid_from",
    "valid_to",
    "rule_kind",
    "approval_source",
    "alias_version",
    "alias",
    "event_issuer_alias",
];

static DIGITS4: LazyLock<Regex> = LazyLock::new(|| Regex::new(r"\A\d{4}\z").unwrap());
static CURRENCY: LazyLock<Regex> = LazyLock::new(|| Regex::new(r"\A[A-Za-z]{3}\z").unwrap());

pub(super) fn four_digits(s: &str) -> bool {
    DIGITS4.is_match(s)
}

fn valid_day(v: Option<&Value>) -> bool {
    parse_iso(&v.map_or_else(|| "None".to_string(), pystr)).is_ok()
}

fn int_in(v: Option<&Value>, low: i64, high: i64) -> bool {
    v.and_then(as_int)
        .is_some_and(|n| (low..=high).contains(&n))
}

fn positive_int(v: Option<&Value>) -> bool {
    v.and_then(as_int).is_some_and(|n| n > 0)
}

/// `_rule_scope_valid`: 규칙 조건이 허용된 키·범위 안에 있는가.
pub(super) fn rule_scope_valid(c: &Value) -> bool {
    let Some(map) = c.as_object() else {
        return false;
    };
    if !map.keys().all(|k| ALLOWED.contains(&k.as_str())) {
        return false;
    }
    match get(c, "rule_kind").and_then(Value::as_str) {
        Some("provider_alias") => {
            return truthy(get(c, "provider"))
                && truthy(get(c, "alias"))
                && truthy(get(c, "approval_source"))
                && positive_int(get(c, "alias_version"));
        }
        Some("issuer_alias") => {
            return truthy(get(c, "provider"))
                && truthy(get(c, "event_issuer_alias"))
                && truthy(get(c, "issuer"))
                && truthy(get(c, "approval_source"))
                && positive_int(get(c, "alias_version"));
        }
        _ => {}
    }
    if !truthy(get(c, "provider")) || !truthy(get(c, "item")) {
        return false;
    }
    if !(truthy(get(c, "merchant_normalized"))
        || (truthy(get(c, "issuer")) && truthy(get(c, "card_last4"))))
    {
        return false;
    }
    let (lag_min, lag_max) = (get(c, "date_lag_min_days"), get(c, "date_lag_max_days"));
    if lag_min.is_some() != lag_max.is_some() {
        return false;
    }
    if let (Some(lo), Some(hi)) = (lag_min, lag_max) {
        let ordered = matches!((as_int(lo), as_int(hi)), (Some(a), Some(b)) if a <= b);
        if has(c, "date_lag_days")
            || !int_in(Some(lo), -7, 7)
            || !int_in(Some(hi), -7, 7)
            || !ordered
        {
            return false;
        }
    }
    let zero = Value::from(0);
    let lag = if has(c, "date_lag_days") {
        c.get("date_lag_days")
    } else {
        Some(&zero)
    };
    let delta = if has(c, "amount_delta_krw") {
        c.get("amount_delta_krw")
    } else {
        Some(&zero)
    };
    let (has_from, has_to) = (has(c, "valid_from"), has(c, "valid_to"));
    let bounds_ok = (!has_from && !has_to)
        || (has_from
            && has_to
            && valid_day(c.get("valid_from"))
            && valid_day(c.get("valid_to"))
            && pystr(&c["valid_from"]) <= pystr(&c["valid_to"]));
    let percent_ok = get(c, "discount_rate_bps").is_none_or(|p| {
        int_in(Some(p), 1, 10_000)
            && positive_int(get(c, "minimum_amount_krw"))
            && positive_int(get(c, "discount_cap_krw"))
            && matches!(
                get(c, "rounding_mode").and_then(Value::as_str),
                Some("floor" | "half_up" | "ceiling")
            )
            && truthy(get(c, "payment_method"))
            && truthy(get(c, "valid_from"))
            && truthy(get(c, "valid_to"))
    });
    let last4_ok = get(c, "card_last4").is_none_or(|v| !truthy(Some(v)) || four_digits(&pystr(v)));
    let currency_ok = get(c, "currency").is_none_or(|v| CURRENCY.is_match(&pystr(v)));
    let event_type_ok =
        get(c, "event_type").is_none_or(|v| matches!(v.as_str(), Some("charge" | "refund")));
    int_in(lag, -7, 7)
        && int_in(delta, -10_000, 10_000)
        && bounds_ok
        && percent_ok
        && last4_ok
        && currency_ok
        && event_type_ok
}

/// 규칙에 `conditions`가 없을 때 규칙 자체에서 허용 키만 뽑은 조건.
fn rule_keys(rule: &Value) -> Value {
    let map: Map<String, Value> = rule
        .as_object()
        .into_iter()
        .flatten()
        .filter(|(k, _)| ALLOWED.contains(&k.as_str()))
        .map(|(k, v)| (k.clone(), v.clone()))
        .collect();
    Value::Object(map)
}

/// `_date_lag_bounds`: 허용 지연 일수 범위.
pub(super) fn date_lag_bounds(c: &Value) -> Option<(i64, i64)> {
    if let (Some(lo), Some(hi)) = (get(c, "date_lag_min_days"), get(c, "date_lag_max_days")) {
        return match (as_int(lo), as_int(hi)) {
            (Some(a), Some(b)) if (-7..=7).contains(&a) && a <= b && b <= 7 => Some((a, b)),
            _ => None,
        };
    }
    let zero = Value::from(0);
    let limit = if has(c, "date_lag_days") {
        c.get("date_lag_days")
    } else {
        Some(&zero)
    };
    let n = limit.and_then(as_int).filter(|n| (-7..=7).contains(n))?;
    Some(if n >= 0 { (0, n) } else { (n, 0) })
}

/// 카드 날짜 - 결제일(일).
pub(super) fn lag_days(card_day: &str, paid_on: &str) -> Option<i64> {
    Some((parse_iso(card_day).ok()? - parse_iso(paid_on).ok()?).whole_days())
}

impl Matcher<'_> {
    pub(super) fn rule_approved(rule: &Value) -> bool {
        truthy(get(rule, "approved_by"))
            || truthy(get(rule, "user_confirmation"))
            || get(rule, "approved") == Some(&Value::Bool(true))
    }

    /// `_rule_matches(event, row, rules)`.
    pub(super) fn rule_matches(&self, event: &Value, row: &Value) -> bool {
        self.rules
            .iter()
            .any(|rule| Matcher::rule_matches_one(rule, event, row))
    }

    pub(super) fn rule_matches_one(rule: &Value, event: &Value, row: &Value) -> bool {
        if rule_inactive(rule) || !Matcher::rule_approved(rule) {
            return false;
        }
        let built;
        let c = match get(rule, "conditions") {
            Some(c) => c,
            None => {
                built = rule_keys(rule);
                &built
            }
        };
        if !rule_scope_valid(c) {
            return false;
        }
        if matches!(
            get(c, "rule_kind").and_then(Value::as_str),
            Some("provider_alias" | "issuer_alias")
        ) {
            return false;
        }
        if !same(get(c, "provider"), get(event, "provider"))
            || !same(get(c, "item"), get(event, "item"))
        {
            return false;
        }
        if truthy(get(c, "currency"))
            && pystr(&c["currency"]).to_uppercase() != text(event, "currency").to_uppercase()
        {
            return false;
        }
        if truthy(get(c, "event_type")) && !same(get(c, "event_type"), get(event, "event_type")) {
            return false;
        }
        let paid_on = text(event, "paid_on");
        let in_window = |c: &Value| {
            !paid_on.is_empty()
                && pystr(c.get("valid_from").unwrap_or(&Value::Null)) <= paid_on
                && paid_on <= pystr(c.get("valid_to").unwrap_or(&Value::Null))
        };
        if has(c, "valid_from") && !in_window(c) {
            return false;
        }
        if truthy(get(c, "merchant_normalized"))
            && !same(
                get(c, "merchant_normalized"),
                get(row, "merchant_normalized"),
            )
        {
            return false;
        }
        if truthy(get(c, "issuer")) && !same(get(c, "issuer"), get(row, "issuer")) {
            return false;
        }
        if truthy(get(c, "card_last4")) && text(row, "card_tail") != pystr(&c["card_last4"]) {
            return false;
        }
        if get(c, "discount_rate_bps").is_some() {
            let amount = Matcher::event_amount(event);
            let minimum = Matcher::dec_of(c.get("minimum_amount_krw"));
            return pystr(get(event, "event_type").unwrap_or(&Value::Null)) == "charge"
                && Matcher::direction(row) == "purchase"
                && text(row, "payment_method") == text(c, "payment_method")
                && amount.zip(minimum).is_some_and(|(a, m)| a >= m)
                && in_window(c);
        }
        true
    }

    /// `_approved_lag_match`: 승인된 규칙의 날짜 지연 범위 안에서 0이 아닌 지연.
    pub(super) fn approved_lag_match(&self, event: &Value, row: &Value) -> bool {
        let (paid, card) = (get(event, "paid_on"), get(row, "approval_date"));
        if !truthy(paid) || !truthy(card) {
            return false;
        }
        let (Some(paid), Some(card)) = (paid, card) else {
            return false;
        };
        let Some(lag) = lag_days(&pystr(card), &pystr(paid)) else {
            return false;
        };
        self.rules.iter().any(|rule| {
            let c = if has(rule, "conditions") {
                get(rule, "conditions").unwrap_or(&Value::Null)
            } else {
                rule
            };
            date_lag_bounds(c).is_some_and(|(low, high)| low <= lag && lag <= high && lag != 0)
                && Matcher::rule_matches_one(rule, event, row)
        })
    }
}
