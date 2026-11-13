//! PROC-072 완료 기간 경계. 원본: `app/closed_period.py`(`completed_period`·`trip_map`·`open_trip`·`completed_trip`·
//! `exception_trip`·`excluded`·`open_scope`). DB를 읽는 `manual_ids`·`excluded_ids`와 `formal_facts`·
//! `booking_period_evidence`(여행 후보 의존)는 이 단위 범위 밖이다.

use super::calendar::{RowDates, parse_iso};
use time::{Date, Month};

/// 이 날짜 이후 시작하는 여행·행이 열린 범위다.
fn open_from() -> Date {
    Date::from_calendar_date(2026, Month::June, 30).unwrap()
}

fn truthy(value: &Option<String>) -> Option<&str> {
    value.as_deref().filter(|s| !s.is_empty())
}

/// 카드 행: 날짜 두 칸, 귀속 탭 두 칸, 원천 해시.
#[derive(Debug, Clone, Default, PartialEq, Eq)]
pub struct CardRow {
    pub dates: RowDates,
    pub trip_id: Option<String>,
    pub display_tab_id: Option<String>,
    pub source_hash: Option<String>,
}

/// Google 탭 스냅숏의 여행 한 줄.
#[derive(Debug, Clone, Default, PartialEq, Eq)]
pub struct TripTab {
    pub trip_id: Option<String>,
    pub tab_id: Option<String>,
    pub starts_on: Option<String>,
    pub ends_on: Option<String>,
    pub deleted: bool,
    pub archived: bool,
}

impl TripTab {
    /// `trip_map` 키: `str(trip_id or tab_id)`. 둘 다 없으면 Python처럼 `"None"`.
    fn map_key(&self) -> String {
        truthy(&self.trip_id)
            .or(self.tab_id.as_deref())
            .unwrap_or("None")
            .to_string()
    }

    /// `_open_p2_tab`의 키: `str(trip_id or tab_id or '')`.
    pub(crate) fn tab_key(&self) -> &str {
        truthy(&self.trip_id).or(truthy(&self.tab_id)).unwrap_or("")
    }

    fn starts(&self) -> &str {
        truthy(&self.starts_on).unwrap_or("")
    }

    /// 시작일. 비었거나 YYYY-MM-DD가 아니면 None.
    fn start_day(&self) -> Option<Date> {
        parse_iso(self.starts()).ok()
    }
}

/// `valid.get(key)`: 같은 키가 겹치면 뒤의 여행이 이긴다(dict 대입).
pub(super) fn lookup<'a>(trips: &'a [TripTab], key: Option<&str>) -> Option<&'a TripTab> {
    let key = key?;
    trips.iter().rev().find(|t| t.map_key() == key)
}

/// `completed_period`: `"2025"`, `"2026Q1"` 또는 완료 기간 밖(`None`).
pub fn completed_period(dates: &RowDates) -> Option<&'static str> {
    let day = dates.day()?;
    if day.year() == 2025 {
        return Some("2025");
    }
    let from = Date::from_calendar_date(2026, Month::January, 1).unwrap();
    let to = Date::from_calendar_date(2026, Month::March, 31).unwrap();
    (from <= day && day <= to).then_some("2026Q1")
}

/// `open_trip`: 지워지지도 보관되지도 않았고 2026-06-30 이후 시작하는 여행.
pub fn open_trip(trip: Option<&TripTab>) -> bool {
    trip.is_some_and(|t| {
        !t.deleted && !t.archived && t.start_day().is_some_and(|d| d >= open_from())
    })
}

/// `completed_trip`: 시작일이 2025-01-01~2026-03-31(문자열 비교)인 제출 완료 장부 여행.
pub fn completed_trip(trip: Option<&TripTab>) -> bool {
    // 시작일이 있는데 해석되지 않으면 보호 방향으로 완료 여행으로 본다.
    trip.is_some_and(|t| match t.start_day() {
        Some(d) => {
            let from = Date::from_calendar_date(2025, Month::January, 1).unwrap();
            let to = Date::from_calendar_date(2026, Month::March, 31).unwrap();
            from <= d && d <= to
        }
        None => !t.starts().is_empty(),
    })
}

/// 격리된 사실의 이용 기간.
#[derive(Debug, Clone, Default, PartialEq, Eq)]
pub struct ServicePeriod {
    pub starts_on: Option<String>,
    pub ends_on: Option<String>,
}

/// 원천에 묶인 정식 연결 사실(`evidence`).
#[derive(Debug, Clone, Default, PartialEq, Eq)]
pub struct Evidence {
    pub trip_id: Option<String>,
    pub service_period: ServicePeriod,
    /// Python `fact.get('formal_link') is True`.
    pub formal_link: bool,
    pub source_hash: Option<String>,
}

/// `exception_trip`: 완료 기간 행이 예외로 열린 여행에 들어갈 때 그 여행 값, 아니면 `None`.
pub fn exception_trip(
    row: &CardRow,
    trips: &[TripTab],
    evidence: Option<&Evidence>,
    manual: bool,
) -> Option<String> {
    let current = truthy(&row.trip_id).or(row.display_tab_id.as_deref());
    if manual && open_trip(lookup(trips, current)) {
        return current.map(str::to_string);
    }
    let fact = evidence?;
    let target = fact.trip_id.as_deref();
    let trip = lookup(trips, target);
    let (start, end) = (
        truthy(&fact.service_period.starts_on),
        truthy(&fact.service_period.ends_on),
    );
    let row_hash = truthy(&row.source_hash)?;
    if !(fact.formal_link && fact.source_hash.as_deref() == Some(row_hash) && open_trip(trip)) {
        return None;
    }
    let (start, end) = (start?, end?);
    let trip = trip?;
    let trip_end = truthy(&trip.ends_on)?;
    let (Ok(trip_start), Ok(start), Ok(end), Ok(trip_end)) = (
        parse_iso(trip.starts()),
        parse_iso(start),
        parse_iso(end),
        parse_iso(trip_end),
    ) else {
        return None;
    };
    (trip_start <= start && start <= end && end <= trip_end)
        .then(|| target.map(str::to_string))
        .flatten()
}

const CLOSED_QUARTERS: [&str; 5] = [
    "quarter:2025:1",
    "quarter:2025:2",
    "quarter:2025:3",
    "quarter:2025:4",
    "quarter:2026:1",
];

/// `excluded`: 완료 기간 행이 자동 판정에서 제외되는가.
pub fn excluded(
    row: &CardRow,
    trips: &[TripTab],
    evidence: Option<&Evidence>,
    manual: bool,
) -> bool {
    // 날짜가 없거나 `YYYY-MM-DD`가 아니면 완료 기간 여부를 알 수 없으므로 보호(제외)한다.
    if row.dates.day().is_none() {
        return true;
    }
    if completed_period(&row.dates).is_none() {
        return false;
    }
    let ids = [row.trip_id.as_deref(), row.display_tab_id.as_deref()];
    if ids
        .iter()
        .any(|id| id.is_some_and(|v| CLOSED_QUARTERS.contains(&v)))
    {
        return true;
    }
    if ids.iter().any(|id| completed_trip(lookup(trips, *id))) {
        return true;
    }
    exception_trip(row, trips, evidence, manual).is_none_or(|v| v.is_empty())
}

/// `open_scope`: 열린 여행에 속하거나 날짜가 2026-06-30 이후인 행.
pub fn open_scope(row: &CardRow, trips: &[TripTab]) -> bool {
    let ids = [row.trip_id.as_deref(), row.display_tab_id.as_deref()];
    ids.iter().any(|id| open_trip(lookup(trips, *id)))
        || row.dates.day().is_some_and(|d| d >= open_from())
}
