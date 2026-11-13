//! 사용 지역 판정. 원본: `app/rules.py`의 `merchant_country`·`transaction_region`·`trip_region`·
//! `is_booking_or_online`·`is_online_purchase_for_owner_card`(TRIP-044·TRIP-045).

use super::{Trip, Txn};
use regex::Regex;
use std::collections::BTreeSet;
use std::sync::LazyLock;

const TRIP_COUNTRIES: [(&str, &[&str]); 5] = [
    (
        "KR",
        &[
            "부산",
            "의왕",
            "금오도",
            "호남",
            "군산",
            "화순",
            "영남",
            "경주",
            "통영",
            "황금해안",
            "변산",
            "양평",
            "제주",
            "세종",
            "길상사",
            "박달고치",
            "함양",
            "한티",
            "해남",
        ],
    ),
    ("TW", &["대만"]),
    ("MN", &["몽골"]),
    ("SG", &["싱가포르"]),
    (
        "JP",
        &[
            "에히메",
            "교토",
            "나가센도",
            "아오모리",
            "오사카",
            "알펜루트",
            "북해도",
            "레분토&리시리",
            "묘코",
            "묘코고원",
            "아키타",
            "오제",
            "야마가타",
            "세토우치",
            "야마구치",
            "북큐슈",
            "도고",
            "가루이자와",
            "야쿠시마",
            "도쿄",
            "노리쿠라",
            "다테시나",
            "도쿠시마",
        ],
    ),
];

const CODES: [(&str, &str); 17] = [
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
];
const CODES_EXTRA: [(&str, &str); 1] = [("HKG", "HK")];

const COUNTRY_PATTERN: &str = "JP|KR|TW|AT|IT|FR|MN|SG|NL|DE|ES|CZ|GB|US|GE|KZ|TR|HK|LV";

static SUFFIX: LazyLock<Regex> =
    LazyLock::new(|| Regex::new(&format!(r"\s({COUNTRY_PATTERN})\s*$")).expect("suffix regex"));
static THREE: LazyLock<Regex> = LazyLock::new(|| {
    let names: Vec<&str> = CODES.iter().chain(&CODES_EXTRA).map(|(k, _)| *k).collect();
    Regex::new(&format!(r"\s({})\s*$", names.join("|"))).expect("three-letter regex")
});
static COMPACT: LazyLock<Regex> = LazyLock::new(|| {
    Regex::new(&format!(r"\s{{2,}}[A-Z0-9 .&/-]+?({COUNTRY_PATTERN})\s*$")).expect("compact regex")
});

fn code_of(three: &str) -> Option<&'static str> {
    CODES
        .iter()
        .chain(&CODES_EXTRA)
        .find(|(k, _)| *k == three)
        .map(|(_, v)| *v)
}

/// 여행 행선지의 나라 코드 집합(`trip_countries`).
pub fn trip_countries(destination: &str) -> BTreeSet<&'static str> {
    if destination == "유럽" {
        return ["AT", "IT", "FR"].into_iter().collect();
    }
    TRIP_COUNTRIES
        .iter()
        .filter(|(_, regions)| regions.contains(&destination))
        .map(|(code, _)| *code)
        .collect()
}

fn raw<'a>(t: &'a Txn, key: &str) -> &'a str {
    t.raw_row.get(key).map_or("", String::as_str)
}

fn is_upper_alpha(s: &str, lens: &[usize]) -> bool {
    lens.contains(&s.chars().count()) && s.chars().all(|c| c.is_ascii_uppercase())
}

/// 현지 구매 규칙용 원본 국가 코드. 없으면 빈 문자열.
pub fn merchant_country(t: &Txn) -> String {
    let mut explicit = ["country", "국가", "국가코드"]
        .iter()
        .map(|k| raw(t, k))
        .find(|v| !v.is_empty())
        .unwrap_or("")
        .to_string();
    if explicit.is_empty() && t.issuer == "국민" {
        let candidate = raw(t, "c8").trim().to_uppercase();
        if is_upper_alpha(&candidate, &[2, 3]) {
            explicit = candidate;
        }
    }
    let upper = explicit.trim().to_uppercase();
    if let Some(code) = code_of(&upper) {
        return code.to_string();
    }
    if !explicit.is_empty() && is_upper_alpha(&upper, &[2]) {
        return upper;
    }
    let merchant = t.merchant.to_uppercase();
    if let Some(m) = SUFFIX.captures(&merchant) {
        return m[1].to_string();
    }
    if let Some(m) = THREE.captures(&merchant) {
        return code_of(&m[1]).unwrap_or("").to_string();
    }
    let overseas_field = ["c1", "c11"].iter().any(|k| raw(t, k).starts_with("해외"));
    if (t.card_kind == "해외" || overseas_field)
        && let Some(m) = COMPACT.captures(&merchant)
    {
        return m[1].to_string();
    }
    if raw(t, "c11").starts_with("해외") {
        return String::new();
    }
    if t.card_kind == "국내" {
        return "KR".to_string();
    }
    String::new()
}

/// 국내(`KR`)·해외(`overseas`)·알 수 없음(빈 문자열).
pub fn transaction_region(t: &Txn) -> &'static str {
    let country = merchant_country(t);
    if !country.is_empty() {
        return if country == "KR" { "KR" } else { "overseas" };
    }
    if t.card_kind == "국내" {
        return "KR";
    }
    let overseas_field = ["c1", "c11"].iter().any(|k| raw(t, k).starts_with("해외"));
    if t.card_kind == "해외" || !t.foreign_currency.is_empty() || overseas_field {
        return "overseas";
    }
    ""
}

/// 여행의 국내·해외 구분(행선지를 모르면 빈 문자열).
pub fn trip_region(trip: &Trip) -> &'static str {
    let countries = trip_countries(&trip.destination);
    if countries.is_empty() {
        ""
    } else if countries.len() == 1 && countries.contains("KR") {
        "KR"
    } else {
        "overseas"
    }
}

const BOOKING_MARKERS: [&str; 34] = [
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
];
const BOOKING_MARKERS_TAIL: [&str; 1] = ["페이팔"];
const ONLINE_CATEGORIES: [&str; 4] = ["인터넷상거래", "전자상거래", "통신판매", "결제대행"];

/// 예약·온라인 결제는 사용 국가와 결제일만으로 현지 구매에 배정하지 않는다.
pub fn is_booking_or_online(t: &Txn) -> bool {
    let merchant = t.merchant.to_uppercase();
    BOOKING_MARKERS
        .iter()
        .chain(&BOOKING_MARKERS_TAIL)
        .any(|m| merchant.contains(m))
        || (t.description_raw.starts_with("card-category:")
            && ONLINE_CATEGORIES
                .iter()
                .any(|m| t.description_raw.contains(m)))
}

static OWNER_ONLINE: LazyLock<Regex> = LazyLock::new(|| {
    Regex::new(
        &[
            r"AGODA|아고다|BOOKING\.COM|부킹닷컴|TRIP\.?\s?COM|트립닷컴|KLOOK|클룩|AIRBNB|에어비앤비|트래블로버",
            r"RAKUTEN\s?TRAVEL|라쿠텐트래블|GOTOGATE|AIRLINES?\b|AIRWAYS|항공|EXPEDIA|HOTELS\.COM",
            r"나이스정보통신|이니시스|KCP|결제대행|통신판매|어드벤처코리아|PAYPAL|페이팔",
            r"ANTHROPIC|OPENAI|CHATGPT|CLAUDE\.AI|CLAUDE\s(?:SUB|AI|PRO|MAX)|ALIEXPRESS|\bTEMU\b|\bCURSOR\b|GITHUB|MIDJOURNEY",
            r"PERPLEXITY|OPENROUTER|\bNOTION\b|DROPBOX|SPOTIFY|NETFLIX|ADOBE",
            r"AMAZON\.|AMZN|AMAZON\s?(?:PRIME|WEB|MKTP|DIGITAL)|\bAWS\b|GOOGLE\s?[*]|GOOGLE\s(?:CLOUD|ONE|PLAY|WORKSPACE)",
            r"APPLE\.COM|APPLE\s?(?:SERVICES|BILL)|ITUNES|MICROSOFT\s?[*]|MSFT",
        ]
        .join("|"),
    )
    .expect("owner online regex")
});

fn local_currency(country: &str) -> Option<&'static str> {
    match country {
        "JP" => Some("JPY"),
        "SG" => Some("SGD"),
        "TW" => Some("TWD"),
        "MN" => Some("MNT"),
        _ => None,
    }
}

/// 지정 카드 해외 거래 중 예약·결제대행·구독·온라인몰만 참(TRIP-045).
pub fn is_online_purchase_for_owner_card(t: &Txn, trips: &[&Trip]) -> bool {
    if OWNER_ONLINE.is_match(&t.merchant.to_uppercase()) {
        return true;
    }
    if !(t.description_raw.starts_with("card-category:")
        && ONLINE_CATEGORIES
            .iter()
            .any(|m| t.description_raw.contains(m)))
    {
        return false;
    }
    let country = merchant_country(t);
    let local = local_currency(&country)
        .is_some_and(|currency| t.foreign_currency.to_uppercase() == currency);
    !(local
        && trips
            .iter()
            .any(|trip| trip_countries(&trip.destination).contains(country.as_str())))
}
