//! 거래의 국가·지역·온라인 결제·후쿠타케 판정. 원본: `app/rules.py`의 `merchant_country`·`transaction_region`·
//! `is_booking_or_online`, `app/trip_selection.py`의 `is_fukutake_purchase`.
//!
//! `rules`(Python dict 모양의 `Transaction`)와 `trips`(칸이 정해진 `Txn`)가 같은 구현을 쓰도록 [`TxnView`] 뒤에 둔다.

use regex::Regex;
use std::sync::LazyLock;

/// 판정이 읽는 거래 칸. 값이 없거나 거짓이면 빈 문자열이다(Python `str(v or '')`).
pub trait TxnView {
    fn text(&self, key: &str) -> String;
    /// 원본 파일 열(`raw_row`) 안의 칸.
    fn raw_text(&self, key: &str) -> String;
    /// `transaction_direction`. 키가 없으면 `None`.
    fn direction(&self) -> Option<String>;
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
pub fn merchant_country<T: TxnView + ?Sized>(txn: &T) -> String {
    let mut explicit = ["country", "국가", "국가코드"]
        .iter()
        .map(|k| txn.raw_text(k))
        .find(|v| !v.is_empty())
        .unwrap_or_default();
    if explicit.is_empty() && txn.text("issuer") == "국민" {
        let candidate = txn.raw_text("c8").trim().to_uppercase();
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
    let overseas_raw = |key: &str| txn.raw_text(key).starts_with("해외");
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

/// 국내(`KR`)·해외(`overseas`)·알 수 없음(빈 문자열). 국가 일치까지는 요구하지 않는다.
pub fn transaction_region<T: TxnView + ?Sized>(txn: &T) -> &'static str {
    let country = merchant_country(txn);
    if !country.is_empty() {
        return if country == "KR" { "KR" } else { "overseas" };
    }
    if txn.text("card_kind") == "국내" {
        return "KR";
    }
    let overseas_raw = ["c1", "c11"]
        .iter()
        .any(|k| txn.raw_text(k).starts_with("해외"));
    if txn.text("card_kind") == "해외" || !txn.text("foreign_currency").is_empty() || overseas_raw
    {
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
pub const ONLINE_CATEGORIES: [&str; 4] = ["인터넷상거래", "전자상거래", "통신판매", "결제대행"];

/// 예약·온라인 결제는 사용 국가와 결제일만으로 현지 구매에 배정하지 않는다.
pub fn is_booking_or_online<T: TxnView + ?Sized>(txn: &T) -> bool {
    let merchant = txn.text("merchant").to_uppercase();
    let category = txn.text("description_raw");
    BOOKING_MARKERS.iter().any(|m| merchant.contains(m))
        || (category.starts_with("card-category:")
            && ONLINE_CATEGORIES.iter().any(|m| category.contains(m)))
}

static FUKUTAKE_NAME: LazyLock<Regex> =
    LazyLock::new(|| Regex::new(r"(?i)^FUKUTAKE\s+FOUNDATION\b").unwrap());

/// `is_fukutake_purchase`(`app/trip_selection.py:13`).
pub fn is_fukutake_purchase<T: TxnView + ?Sized>(txn: &T) -> bool {
    FUKUTAKE_NAME.is_match(txn.text("merchant").trim())
        && txn.direction().is_none_or(|d| d == "purchase")
        && ["parse_error", "duplicate_of", "conflict_reason"]
            .iter()
            .all(|k| txn.text(k).is_empty())
}
