//! 날짜·분기·장부 날짜 규칙. 원본: `app/quarter_costs.py`, `app/reconciliation.py:27-104`.
//!
//! 날짜 문자열은 Python `date.fromisoformat`(3.14)과 같은 형태(`YYYY-MM-DD`, `YYYYMMDD`, ISO 주 날짜)만 받는다.
//! 파싱 실패는 Python의 `ValueError`에 해당하는 `DateError`다. 문자열 비교(`>=` 등)는 Python처럼 바이트 사전순이다.

use std::collections::BTreeSet;
use time::{Date, Duration, Month, Weekday};

/// 날짜 문자열을 해석하지 못했거나 날짜 범위를 벗어났다(Python `ValueError`·`OverflowError`).
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct DateError(pub String);

impl std::fmt::Display for DateError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        write!(f, "invalid ISO date: {:?}", self.0)
    }
}

impl std::error::Error for DateError {}

/// 3분기를 6월 30일에 시작하는 현행 기간(`CURRENT_PERIOD_START`).
const CURRENT_PERIOD_START: (i32, u8, u8) = (2026, 6, 30);
const CURRENT_PERIOD_END: (i32, u8, u8) = (2026, 9, 30);

fn digits(s: &str, from: usize, len: usize) -> Option<u32> {
    let part = s.get(from..from + len)?;
    if !part.bytes().all(|b| b.is_ascii_digit()) {
        return None;
    }
    part.parse().ok()
}

/// `date.fromisoformat` 대응.
pub fn parse_iso(s: &str) -> Result<Date, DateError> {
    let err = || DateError(s.to_string());
    if !s.is_ascii() {
        return Err(err());
    }
    let year = digits(s, 0, 4).ok_or_else(err)? as i32;
    let rest = &s[4..];
    // 주 날짜: YYYY-Www[-D], YYYYWww[D]
    let (week_part, dashed) = match rest.strip_prefix("-W") {
        Some(r) => (Some(r), true),
        None => (rest.strip_prefix('W'), false),
    };
    if let Some(r) = week_part {
        let week = digits(r, 0, 2).ok_or_else(err)? as u8;
        let tail = &r[2..];
        let day = if tail.is_empty() {
            1
        } else {
            let t = if dashed {
                tail.strip_prefix('-')
            } else {
                Some(tail)
            };
            let t = t.ok_or_else(err)?;
            if t.len() != 1 {
                return Err(err());
            }
            digits(t, 0, 1).ok_or_else(err)?
        };
        let weekday = match day {
            1 => Weekday::Monday,
            2 => Weekday::Tuesday,
            3 => Weekday::Wednesday,
            4 => Weekday::Thursday,
            5 => Weekday::Friday,
            6 => Weekday::Saturday,
            7 => Weekday::Sunday,
            _ => return Err(err()),
        };
        if year < 1 {
            return Err(err());
        }
        return Date::from_iso_week_date(year, week, weekday).map_err(|_| err());
    }
    let (month, day) = if let Some(r) = rest.strip_prefix('-') {
        if r.len() != 5 || r.as_bytes()[2] != b'-' {
            return Err(err());
        }
        (
            digits(r, 0, 2).ok_or_else(err)?,
            digits(r, 3, 2).ok_or_else(err)?,
        )
    } else {
        if rest.len() != 4 {
            return Err(err());
        }
        (
            digits(rest, 0, 2).ok_or_else(err)?,
            digits(rest, 2, 2).ok_or_else(err)?,
        )
    };
    if year < 1 {
        return Err(err());
    }
    let month = Month::try_from(u8::try_from(month).map_err(|_| err())?).map_err(|_| err())?;
    Date::from_calendar_date(year, month, day as u8).map_err(|_| err())
}

/// `date.isoformat()` 대응.
pub fn iso(date: Date) -> String {
    format!(
        "{:04}-{:02}-{:02}",
        date.year(),
        u8::from(date.month()),
        date.day()
    )
}

fn ymd(parts: (i32, u8, u8)) -> Date {
    Date::from_calendar_date(parts.0, Month::try_from(parts.1).unwrap(), parts.2).unwrap()
}

/// `quarter_of`: 현행 기간(2026-06-30~2026-09-30)은 3분기, 그 밖은 달력 분기.
pub fn quarter_of(day: Date) -> (i32, u8) {
    if ymd(CURRENT_PERIOD_START) <= day && day <= ymd(CURRENT_PERIOD_END) {
        return (day.year(), 3);
    }
    (day.year(), (u8::from(day.month()) - 1) / 3 + 1)
}

/// 카드 행의 날짜 두 칸. 빈 문자열은 Python처럼 없는 값과 같다.
#[derive(Debug, Clone, Default, PartialEq, Eq)]
pub struct RowDates {
    pub approval_date: Option<String>,
    pub posting_date: Option<String>,
}

fn truthy(value: &Option<String>) -> Option<&str> {
    value.as_deref().filter(|s| !s.is_empty())
}

impl RowDates {
    /// `row.get('approval_date') or row.get('posting_date') or ''`
    pub fn raw(&self) -> &str {
        truthy(&self.approval_date)
            .or_else(|| truthy(&self.posting_date))
            .unwrap_or("")
    }

    /// 해석 가능한 날짜. 해석 불가·없음은 `None`.
    pub fn day(&self) -> Option<Date> {
        parse_iso(self.raw()).ok()
    }
}

/// `_tab_of`: `quarter:{year}:{quarter}` 또는 날짜를 해석하지 못하면 `None`.
pub fn tab_of(row: &RowDates) -> Option<String> {
    let (year, quarter) = quarter_of(row.day()?);
    Some(format!("quarter:{year}:{quarter}"))
}

/// `ledger_date_for_booking`: 이용일이 있으면 이용일, 없으면 결제일, 둘 다 없으면 빈 문자열.
pub fn ledger_date_for_booking<'a>(
    service_date: Option<&'a str>,
    payment_date: Option<&'a str>,
) -> &'a str {
    service_date
        .filter(|s| !s.is_empty())
        .or(payment_date.filter(|s| !s.is_empty()))
        .unwrap_or("")
}

/// `open_trip_end`: 종료일 없는 여행은 다음 여행 시작 전날에 끝난다. 없으면 `Ok(None)`.
pub fn open_trip_end(
    starts_on: Option<&str>,
    next_starts_on: Option<&str>,
) -> Result<Option<String>, DateError> {
    let (Some(starts), Some(next)) = (
        starts_on.filter(|s| !s.is_empty()),
        next_starts_on.filter(|s| !s.is_empty()),
    ) else {
        return Ok(None);
    };
    if next <= starts {
        return Ok(None);
    }
    shift_days(parse_iso(next)?, -1).map(|d| Some(iso(d)))
}

/// `card_use_date`: 승인일(없으면 빈 문자열).
pub fn card_use_date(approval_date: Option<&str>) -> &str {
    approval_date.unwrap_or("")
}

fn shift_days(day: Date, days: i64) -> Result<Date, DateError> {
    day.checked_add(Duration::days(days))
        .filter(|d| d.year() >= 1)
        .ok_or_else(|| DateError(iso(day)))
}

fn shift_str(value: &str, days: i64) -> Result<String, DateError> {
    shift_days(parse_iso(value)?, days).map(iso)
}

/// 여행 기간(`trips` 원소의 시작·종료). `None`·빈 문자열은 값 없음이다.
#[derive(Debug, Clone, Default, PartialEq, Eq)]
pub struct Span {
    pub starts_on: Option<String>,
    pub ends_on: Option<String>,
}

/// `handover_days`: 다른 여행이 그날 또는 다음 날 시작하는 여행 종료일 집합.
pub fn handover_days(trips: &[Span]) -> Result<BTreeSet<String>, DateError> {
    let mut out = BTreeSet::new();
    for (i, t) in trips.iter().enumerate() {
        let Some(end) = truthy(&t.ends_on) else {
            continue;
        };
        if trips.len() < 2 {
            continue;
        }
        // Python은 다른 여행이 있을 때만 다음 날을 계산하므로 형식 오류도 그때만 난다.
        let next = shift_str(end, 1)?;
        if trips
            .iter()
            .enumerate()
            .any(|(j, u)| j != i && truthy(&u.starts_on).is_some_and(|s| s == end || s == next))
        {
            out.insert(end.to_string());
        }
    }
    Ok(out)
}

/// `_nights`: 여행에 속한 숙박일 구간(체크인~체크아웃 전날), 없으면 `None`.
fn nights(
    trip_start: &str,
    trip_end: &str,
    check_in: &str,
    check_out: &str,
    handover: &BTreeSet<String>,
) -> Result<Option<(String, String)>, DateError> {
    let last = if handover.contains(trip_end) {
        shift_str(trip_end, -1)?
    } else {
        trip_end.to_string()
    };
    let first = check_in.max(trip_start).to_string();
    let out = shift_str(check_out, -1)?;
    let end = out.as_str().min(last.as_str()).to_string();
    Ok((first <= end).then_some((first, end)))
}

/// `covers_stay`: 예약 전체가 여행 안에 있는가. `service`면 항공처럼 양 끝날이 모두 이용일이다.
pub fn covers_stay(
    trip_start: &str,
    trip_end: &str,
    check_in: &str,
    check_out: &str,
    service: bool,
    handover: &BTreeSet<String>,
) -> Result<bool, DateError> {
    if trip_start.is_empty() || trip_end.is_empty() {
        return Ok(false);
    }
    if service {
        return Ok(trip_start <= check_in && check_out <= trip_end);
    }
    let found = nights(trip_start, trip_end, check_in, check_out, handover)?;
    let want = (check_in.to_string(), shift_str(check_out, -1)?);
    Ok(found.is_some_and(|n| n == want))
}

/// `overlaps_stay`: 예약의 이용일 하루라도 여행 안에 있는가.
pub fn overlaps_stay(
    trip_start: &str,
    trip_end: &str,
    check_in: &str,
    check_out: &str,
    service: bool,
    handover: &BTreeSet<String>,
) -> Result<bool, DateError> {
    if trip_start.is_empty() || trip_end.is_empty() {
        return Ok(false);
    }
    if service {
        return Ok(check_in.max(trip_start) <= check_out.min(trip_end));
    }
    Ok(nights(trip_start, trip_end, check_in, check_out, handover)?.is_some())
}

/// `shared_days`: 예약과 여행이 겹치는 숙박일(항공은 이용일) 수.
pub fn shared_days(
    trip_start: &str,
    trip_end: &str,
    check_in: &str,
    check_out: &str,
    service: bool,
    handover: &BTreeSet<String>,
) -> Result<i64, DateError> {
    if !overlaps_stay(trip_start, trip_end, check_in, check_out, service, handover)? {
        return Ok(0);
    }
    let (first, last) = if service {
        (
            check_in.max(trip_start).to_string(),
            check_out.min(trip_end).to_string(),
        )
    } else {
        nights(trip_start, trip_end, check_in, check_out, handover)?
            .expect("overlap implies nights")
    };
    Ok((parse_iso(&last)? - parse_iso(&first)?).whole_days() + 1)
}

/// `prep_trip`: 체크아웃 당일 이후 가장 가까이 시작하는 여행의 위치. 같은 날 시작이 둘 이상이면 `None`.
pub fn prep_trip(trips: &[Span], check_out: &str) -> Option<usize> {
    let first = trips
        .iter()
        .filter_map(|t| truthy(&t.starts_on))
        .filter(|s| *s >= check_out)
        .min()?;
    let mut nearest = trips
        .iter()
        .enumerate()
        .filter(|(_, t)| truthy(&t.starts_on) == Some(first));
    let only = nearest.next()?;
    nearest.next().is_none().then_some(only.0)
}
