//! 사용 지역 판정. 원본: `app/rules.py`의 `merchant_country`·`transaction_region`·`trip_region`·
//! `is_booking_or_online`·`is_online_purchase_for_owner_card`(TRIP-044·TRIP-045).

use super::{Trip, Txn};
use crate::region::ONLINE_CATEGORIES;
pub use crate::region::{is_booking_or_online, merchant_country, transaction_region};
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
