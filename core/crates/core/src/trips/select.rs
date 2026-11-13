//! 권위 있는 여행 기간·지역 선택. 원본: `app/trip_selection.py`.

use super::region::{is_booking_or_online, transaction_region, trip_region};
use super::{Trip, Txn};
use crate::dates::{open_trip_end, parse_iso};
use regex::Regex;
use std::collections::HashMap;
use std::sync::LazyLock;

pub const FUKUTAKE_BASIS: &str =
    "사용자 규칙: FUKUTAKE FOUNDATION · 결제일 당일 또는 이후 가장 가까운 세토우치 출발일";

const INVALID_FLAGS: [&str; 4] = [
    "PERIOD_START_MISSING",
    "PERIOD_START_MISMATCH",
    "PERIOD_DATE_INVALID",
    "PERIOD_ORDER",
];

/// `canonical_trip_periods` 결과: 같은 계획 안에서 한 번 검증한 여행(키는 `trip_id`, 처음 나온 순서).
#[derive(Debug, Clone, Default)]
pub struct Canonical {
    trips: Vec<Trip>,
}

impl Canonical {
    /// 유효한 여행만 시작일 순으로 모으고, 종료일 없는 여행에는 다음 여행 직전일을 채운다.
    pub fn new(trips: &[Trip]) -> Self {
        let mut rows: Vec<(time::Date, Trip)> = trips
            .iter()
            .filter(|t| {
                !(t.trip_id.is_empty()
                    || t.archived
                    || t.deleted
                    || t.disabled
                    || t.invalid
                    || t.conflict
                    || t.period_conflict
                    || t.flags.iter().any(|f| INVALID_FLAGS.contains(&f.as_str())))
            })
            .filter_map(|t| {
                let start = parse_iso(&t.starts_on).ok()?;
                if let Some(end) = t.ends_on.as_deref().filter(|e| !e.is_empty())
                    && parse_iso(end).ok()? < start
                {
                    return None;
                }
                Some((start, t.clone()))
            })
            .collect();
        rows.sort_by_key(|(start, _)| *start);
        // 뒤에서 앞으로 한 번 훑어 같은 시작일 묶음은 같은 "다음 시작일"을 본다.
        let mut following: Option<String> = None;
        let mut group_start: Option<time::Date> = None;
        let mut next_start: Option<String> = None;
        for (start, trip) in rows.iter_mut().rev() {
            if Some(*start) != group_start {
                following = next_start.clone();
                group_start = Some(*start);
            }
            if trip.ends_on.as_deref().is_none_or(str::is_empty) {
                trip.ends_on = open_trip_end(Some(&trip.starts_on), following.as_deref())
                    .ok()
                    .flatten();
            }
            next_start = Some(trip.starts_on.clone());
        }
        Self::from_unique(rows.into_iter().map(|(_, t)| t))
    }

    /// 키가 같으면 값은 뒤의 여행이 이기고 자리는 처음 나온 곳이다(dict 대입).
    fn from_unique(trips: impl Iterator<Item = Trip>) -> Self {
        let mut out: Vec<Trip> = Vec::new();
        let mut at: HashMap<String, usize> = HashMap::new();
        for trip in trips {
            match at.get(&trip.trip_id) {
                Some(&i) => out[i] = trip,
                None => {
                    at.insert(trip.trip_id.clone(), out.len());
                    out.push(trip);
                }
            }
        }
        Self { trips: out }
    }

    /// 이미 검증된 여행의 부분집합(재검증 없이 쓰는 `_canonical` 입력).
    pub fn from_validated(trips: Vec<Trip>) -> Self {
        Self::from_unique(trips.into_iter())
    }

    pub fn iter(&self) -> impl Iterator<Item = &Trip> {
        self.trips.iter()
    }

    pub fn get(&self, trip_id: &str) -> Option<&Trip> {
        self.trips.iter().find(|t| t.trip_id == trip_id)
    }

    pub fn is_empty(&self) -> bool {
        self.trips.is_empty()
    }
}

static FUKUTAKE: LazyLock<Regex> =
    LazyLock::new(|| Regex::new(r"(?i)^FUKUTAKE\s+FOUNDATION(?:\b|$)").expect("fukutake regex"));

pub fn is_fukutake_purchase(t: &Txn) -> bool {
    FUKUTAKE.is_match(t.merchant.trim())
        && t.transaction_direction.as_deref().unwrap_or("purchase") == "purchase"
        && t.parse_error.is_empty()
        && t.duplicate_of.is_empty()
        && t.conflict_reason.is_empty()
}

/// FUKUTAKE 규칙 밖이면 `None`, 아니면 결제일 당일 또는 이후 가장 가까운 세토우치 출발일의 여행들(ID 순).
pub fn fukutake_trips<'a>(t: &Txn, trips: &[&'a Trip]) -> Option<Vec<&'a Trip>> {
    if !is_fukutake_purchase(t) {
        return None;
    }
    if parse_iso(&t.approval_date).is_err() {
        return Some(Vec::new());
    }
    let day = t.approval_date.as_str();
    let candidates: Vec<&Trip> = trips
        .iter()
        .copied()
        .filter(|trip| {
            (trip.destination.contains("세토우치") || trip.display_key.contains("세토우치"))
                && !trip.starts_on.is_empty()
                && trip.starts_on.as_str() >= day
        })
        .collect();
    let first = candidates.iter().map(|trip| trip.starts_on.as_str()).min();
    let mut chosen: Vec<&Trip> = candidates
        .iter()
        .copied()
        .filter(|trip| Some(trip.starts_on.as_str()) == first)
        .collect();
    chosen.sort_by_key(|trip| {
        if trip.trip_id.is_empty() {
            trip.tab_id.clone()
        } else {
            trip.trip_id.clone()
        }
    });
    Some(chosen)
}

/// 2026년 9월 제주 여행은 지정 카드(끝 4자리 4813)만 쓴다.
pub fn card_trip_allowed(t: &Txn, trip: &Trip) -> bool {
    let restricted = trip.display_key == "0909_제주" && trip.starts_on == "2026-09-09";
    !restricted || t.card_tail == "4813"
}

/// 카드 사용 지역과 맞는 여행. `booking_agnostic`이면 예약·온라인 결제는 지역을 보지 않는다.
pub fn regional_trips<'a>(t: &Txn, trips: &[&'a Trip], booking_agnostic: bool) -> Vec<&'a Trip> {
    let region = if booking_agnostic && is_booking_or_online(t) {
        ""
    } else {
        transaction_region(t)
    };
    trips
        .iter()
        .copied()
        .filter(|trip| {
            card_trip_allowed(t, trip) && (region.is_empty() || trip_region(trip) == region)
        })
        .collect()
}

/// 그날을 감싸는 여행만(소유자 결정 2026-11-12). 날짜가 `YYYY-MM-DD`가 아니면 없음.
pub fn period_or_preparation<'a>(trips: &[&'a Trip], day: &str) -> Vec<&'a Trip> {
    if parse_iso(day).is_err() {
        return Vec::new();
    }
    trips
        .iter()
        .copied()
        .filter(|trip| {
            !trip.starts_on.is_empty()
                && trip.ends_on.as_deref().is_some_and(|end| {
                    !end.is_empty() && trip.starts_on.as_str() <= day && day <= end
                })
        })
        .collect()
}
