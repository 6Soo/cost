//! 규칙 일치. 원본: `app/rules.py` `rule_matches`(`:291-351`). 국가·온라인 판정은 [`crate::region`]이 한다.

use super::normalize::{Rule, truthy};
use super::text::{casefold, normalize_merchant};
use crate::dates::parse_iso;
use crate::region::TxnView;
use regex::Regex;
use serde_json::{Map, Value};
use std::sync::LazyLock;

/// 판정 입력 거래. Python dict처럼 원본 열을 그대로 들고 있다(`raw_row`는 원본 파일 열).
#[derive(Debug, Clone, Default, PartialEq)]
pub struct Transaction {
    fields: Map<String, Value>,
}

impl Transaction {
    pub fn from_value(v: &Value) -> Transaction {
        Transaction {
            fields: v.as_object().cloned().unwrap_or_default(),
        }
    }

    /// 여행 확인 결과 같은 내부 표지(`_verified_travel_country` 등)를 더한 사본.
    pub fn with(&self, key: &str, value: Value) -> Transaction {
        let mut copy = self.clone();
        copy.fields.insert(key.to_string(), value);
        copy
    }

    pub(crate) fn get(&self, key: &str) -> Option<&Value> {
        self.fields.get(key)
    }

    /// Python `str(txn.get(key) or '')`.
    pub(crate) fn text(&self, key: &str) -> String {
        self.get(key).map(value_text).unwrap_or_default()
    }

    pub(crate) fn has(&self, key: &str) -> bool {
        self.get(key).is_some_and(truthy)
    }

    pub(crate) fn amount_krw(&self) -> Option<i64> {
        self.get("amount_krw").and_then(Value::as_i64)
    }
}

impl TxnView for Transaction {
    fn text(&self, key: &str) -> String {
        Transaction::text(self, key)
    }

    fn raw_text(&self, key: &str) -> String {
        self.get("raw_row")
            .and_then(Value::as_object)
            .and_then(|raw| raw.get(key))
            .map(value_text)
            .unwrap_or_default()
    }

    fn direction(&self) -> Option<String> {
        self.get("transaction_direction")
            .map(|v| v.as_str().unwrap_or_default().to_string())
    }
}

/// Python `str(v or '')`.
fn value_text(v: &Value) -> String {
    if !truthy(v) {
        return String::new();
    }
    match v {
        Value::String(s) => s.clone(),
        Value::Bool(_) => "True".to_string(),
        other => other.to_string(),
    }
}

static AGODA_FAMILY: LazyLock<Regex> =
    LazyLock::new(|| Regex::new(r"^(?:agoda|아고다)(?:[\s._*\-]|$)").unwrap());

/// 이 규칙이 이 거래에 걸리는가와 그 근거 문구. 있는 조건은 모두 맞아야 한다.
pub fn rule_matches(rule: &Rule, txn: &Transaction) -> (bool, Vec<&'static str>) {
    const NO: (bool, Vec<&str>) = (false, Vec::new());
    let mut reasons = Vec::new();
    let merchant = normalize_merchant(&txn.text("merchant"));
    let wanted = rule
        .conditions
        .get("merchant_normalized")
        .and_then(Value::as_str);
    if rule.optional.get("merchant_family").and_then(Value::as_str) == Some("agoda") {
        if !AGODA_FAMILY.is_match(&merchant) {
            return NO;
        }
    } else if wanted != Some("*") && wanted != Some(merchant.as_str()) {
        return NO;
    }
    reasons.push(if wanted == Some("*") {
        "현지 사용 기본 규칙"
    } else {
        "가맹점 일치"
    });
    if let Some(hash) = rule.opt("source_hash")
        && txn.get("source_hash") != Some(hash)
    {
        return NO;
    }
    if let Some(country) = rule.opt("travel_country") {
        if txn.get("_verified_travel_country") != Some(country) {
            return NO;
        }
        reasons.push("사용 장소와 검증된 여행 일정 일치");
    }
    if rule.opt("booking_period").is_some() {
        if !txn.has("_booking_verified") {
            return NO;
        }
        reasons.push("예약번호·결제금액·결제일과 이용기간 검증");
    }
    if let Some(kind) = rule.conditions.get("card_kind") {
        if casefold(txn.text("card_kind").trim()) != value_text(kind) {
            return NO;
        }
        reasons.push("카드 종류 일치");
    }
    if let Some(direction) = rule.conditions.get("transaction_direction") {
        if txn.text("transaction_direction") != value_text(direction) {
            return NO;
        }
        reasons.push("거래 방향 일치");
    }
    if let Some(window) = rule.opt("amount_range").and_then(Value::as_object) {
        // 읽을 수 없는 금액은 범위 안에 있을 수 없다.
        let Some(amount) = txn.amount_krw() else {
            return NO;
        };
        for (bound, below) in [("min", true), ("max", false)] {
            match window.get(bound) {
                None | Some(Value::Null) => {}
                Some(limit) => {
                    let Some(limit) = limit.as_i64() else {
                        return NO;
                    };
                    if (below && amount < limit) || (!below && amount > limit) {
                        return NO;
                    }
                }
            }
        }
        reasons.push("금액 범위 일치");
    }
    if let Some(period) = rule
        .opt("date_or_service_period")
        .and_then(Value::as_object)
    {
        let occurred = txn.text("approval_date");
        let bound = |key: &str| period.get(key).filter(|v| truthy(v)).map(value_text);
        let (start, end) = (bound("start"), bound("end"));
        if (start.is_some() || end.is_some()) && parse_iso(&occurred).is_err() {
            return NO;
        }
        if start.is_some_and(|s| occurred < s) || end.is_some_and(|e| occurred > e) {
            return NO;
        }
        reasons.push("기간 일치");
    }
    (true, reasons)
}
