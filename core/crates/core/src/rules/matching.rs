//! 규칙 일치와 거래의 국가·온라인 판정. 원본: `app/rules.py` `rule_matches`(`:291-351`)·`merchant_country`·
//! `transaction_region`·`is_booking_or_online`.

use super::normalize::{Rule, truthy};
use super::text::{casefold, normalize_merchant};
use crate::dates::parse_iso;
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

    fn raw_row(&self) -> Map<String, Value> {
        self.get("raw_row")
            .and_then(Value::as_object)
            .cloned()
            .unwrap_or_default()
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

const COUNTRY_CODES: [(&str, &str); 18] = [
    ("JPN", "JP"),
    ("KOR", "KR"),
    ("TWN", "TW"),
    ("AUT", "AT"),
    ("ITA", "IT"),
    ("FRA", "FR"),
    ("MNG", "MN"),
    ("SGP", "SG"),
    ("NLD", "NL"),
    ("DEU", "DE"),
    ("ESP", "ES"),
    ("CZE", "CZ"),
    ("GBR", "GB"),
    ("USA", "US"),
    ("GEO", "GE"),
    ("KAZ", "KZ"),
    ("TUR", "TR"),
    ("HKG", "HK"),
];
const COUNTRY_PATTERN: &str = "JP|KR|TW|AT|IT|FR|MN|SG|NL|DE|ES|CZ|GB|US|GE|KZ|TR|HK|LV";

fn three_to_two(code: &str) -> Option<&'static str> {
    COUNTRY_CODES
        .iter()
        .find(|(three, _)| *three == code)
        .map(|(_, two)| *two)
}

static SUFFIX: LazyLock<Regex> =
    LazyLock::new(|| Regex::new(&format!(r"\s({COUNTRY_PATTERN})\s*$")).unwrap());
static SUFFIX3: LazyLock<Regex> = LazyLock::new(|| {
    let codes: Vec<&str> = COUNTRY_CODES.iter().map(|(three, _)| *three).collect();
    Regex::new(&format!(r"\s({})\s*$", codes.join("|"))).unwrap()
});
static COMPACT: LazyLock<Regex> = LazyLock::new(|| {
    Regex::new(&format!(r"\s{{2,}}[A-Z0-9 .&/-]+?({COUNTRY_PATTERN})\s*$")).unwrap()
});

fn is_upper_alpha(s: &str, min: usize, max: usize) -> bool {
    (min..=max).contains(&s.len()) && s.bytes().all(|b| b.is_ascii_uppercase())
}

/// 현지 구매 규칙용 원본 국가. 통화나 여행 이름으로 국가를 추정하지 않는다.
pub fn merchant_country(txn: &Transaction) -> String {
    let raw = txn.raw_row();
    let raw_text = |key: &str| raw.get(key).map(value_text).unwrap_or_default();
    let mut explicit = ["country", "국가", "국가코드"]
        .iter()
        .filter_map(|k| raw.get(*k))
        .find(|v| truthy(v))
        .map(value_text)
        .unwrap_or_default();
    if explicit.is_empty() && txn.text("issuer") == "국민" {
        let candidate = raw_text("c8").trim().to_uppercase();
        if is_upper_alpha(&candidate, 2, 3) {
            explicit = candidate;
        }
    }
    let upper = explicit.trim().to_uppercase();
    if let Some(two) = three_to_two(&upper) {
        return two.to_string();
    }
    if !explicit.is_empty() && is_upper_alpha(&upper, 2, 2) {
        return upper;
    }
    let merchant = txn.text("merchant").to_uppercase();
    if let Some(found) = SUFFIX.captures(&merchant) {
        return found[1].to_string();
    }
    if let Some(found) = SUFFIX3.captures(&merchant)
        && let Some(two) = three_to_two(&found[1])
    {
        return two.to_string();
    }
    let overseas_raw = |key: &str| raw_text(key).starts_with("해외");
    if (txn.text("card_kind") == "해외" || overseas_raw("c1") || overseas_raw("c11"))
        && let Some(found) = COMPACT.captures(&merchant)
    {
        return found[1].to_string();
    }
    if overseas_raw("c11") {
        return String::new();
    }
    if txn.text("card_kind") == "국내" {
        return "KR".to_string();
    }
    String::new()
}

/// 국내(`KR`)와 해외(`overseas`)를 구분한다. 국가 일치까지는 요구하지 않는다.
pub fn transaction_region(txn: &Transaction) -> &'static str {
    let country = merchant_country(txn);
    if !country.is_empty() {
        return if country == "KR" { "KR" } else { "overseas" };
    }
    if txn.text("card_kind") == "국내" {
        return "KR";
    }
    let raw = txn.raw_row();
    let overseas_raw = ["c1", "c11"].iter().any(|k| {
        raw.get(*k)
            .map(value_text)
            .unwrap_or_default()
            .starts_with("해외")
    });
    if txn.text("card_kind") == "해외" || txn.has("foreign_currency") || overseas_raw {
        return "overseas";
    }
    ""
}

const BOOKING_MARKERS: [&str; 35] = [
    "AGODA",
    "BOOKING",
    "TRIP",
    "KLOOK",
    "RAKUTEN",
    "AIRBNB",
    "HOTEL",
    "RYOKAN",
    "아고다",
    "트립닷컴",
    "클룩",
    "부킹닷컴",
    "에어비앤비",
    "트래블로버",
    "나이스정보통신",
    "AIRLINE",
    "GOTOGATE",
    "AIRWAYS",
    "NICE",
    "PAY",
    "이니시스",
    "KCP",
    "항공",
    "AMAZON",
    "GOOGLE",
    "APPLE",
    "MICROSOFT",
    "인터넷상거래",
    "전자상거래",
    "통신판매",
    "어드벤처코리아",
    "결제대행",
    "네이버페이",
    "카카오페이",
    "페이팔",
];
const ONLINE_CATEGORIES: [&str; 4] = ["인터넷상거래", "전자상거래", "통신판매", "결제대행"];

/// 예약·온라인 결제는 사용 국가와 결제일만으로 현지 구매에 배정하지 않는다.
pub fn is_booking_or_online(txn: &Transaction) -> bool {
    let merchant = txn.text("merchant").to_uppercase();
    let category = txn.text("description_raw");
    BOOKING_MARKERS.iter().any(|m| merchant.contains(m))
        || (category.starts_with("card-category:")
            && ONLINE_CATEGORIES.iter().any(|m| category.contains(m)))
}
