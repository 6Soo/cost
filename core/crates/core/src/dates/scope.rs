//! 열린 분기·열린 여행 판별과 `OpenScope` 발급. 원본: `app/classification_correction.py:18-37`(`_open_p2_tab`).
//!
//! `OpenScope`(domain)의 생성자는 `pub(crate)`이고 이 모듈이 유일한 발급처다.
//! 탭 `quarter:Y:Q`는 `OpenScope::quarter`, 그 밖은 `trip`(탭 스냅숏의 `TripId`)이다.
//! 날짜만 열린 행(귀속 탭 없음)의 안전한 최소 의미: 행 날짜의 분기(`quarter_of`, 현행 기간
//! 2026-06-30~09-30은 3분기)가 2026Q3 이후이면 그 분기 범위 하나만 발급한다. 그 밖은 발급하지 않는다.
//! 연·분기가 `OpenScope`로 표현되지 않는 값(분기 1~4 밖, `u16` 밖)은 열린 탭으로 보지 않고 토큰을 내지 않는다.

use super::calendar::quarter_of;
use super::closed_period::{CardRow, TripTab, open_scope, open_trip};
use crate::domain::{OpenScope, Quarter, TripCatalog};
/// Python `int()`의 ASCII 부분: 앞뒤 공백, 부호, 숫자 사이의 밑줄 하나.
fn py_int(s: &str) -> Option<i64> {
    let s = s.trim();
    let (negative, body) = match s.strip_prefix('-') {
        Some(r) => (true, r),
        None => (false, s.strip_prefix('+').unwrap_or(s)),
    };
    if body.is_empty() || body.starts_with('_') || body.ends_with('_') || body.contains("__") {
        return None;
    }
    let cleaned: String = body.chars().filter(|c| *c != '_').collect();
    if !cleaned.bytes().all(|b| b.is_ascii_digit()) {
        return None;
    }
    let value: i64 = cleaned.parse().ok()?;
    Some(if negative { -value } else { value })
}

/// `quarter:{연}:{분기}` / `quarter:{연}-Q{분기}` 탭의 (연, 분기). 값 검증은 하지 않는다.
fn parse_quarter_tab(trip_id: &str) -> Option<(i64, i64)> {
    let (_, rest) = trip_id.split_once(':')?;
    let value = if rest.contains(": ") {
        rest.replace(": ", ":")
    } else {
        rest.to_string()
    };
    let parts = value.split_once(':').or_else(|| value.split_once("-Q"))?;
    Some((py_int(parts.0)?, py_int(parts.1)?))
}

fn open_quarter(trip_id: &str) -> bool {
    parse_quarter_tab(trip_id).is_some_and(|yq| yq >= (2026, 3))
}

/// `_open_p2_tab`: `quarter:{연}:{분기}` 탭은 2026년 3분기부터, 그 밖의 탭은 열린 여행일 때만 열려 있다.
pub fn open_p2_tab(trips: &[TripTab], trip_id: &str) -> bool {
    if trip_id.starts_with("quarter:") {
        return open_quarter(trip_id);
    }
    trips
        .iter()
        .find(|t| t.tab_key() == trip_id)
        .is_some_and(|t| open_trip(Some(t)))
}

fn quarter_scope(year: i64, quarter: i64) -> Option<OpenScope> {
    let year = u16::try_from(year).ok()?;
    let quarter = Quarter::from_number(u8::try_from(quarter).ok()?).ok()?;
    Some(OpenScope::quarter(year, quarter))
}

/// 열린 탭이면 `OpenScope`를 발급한다(P2·AI 검수 교정 적용 경로의 입력).
pub fn scope_for_tab(trips: &[TripTab], trip_id: &str) -> Option<OpenScope> {
    if !open_p2_tab(trips, trip_id) {
        return None;
    }
    if trip_id.starts_with("quarter:") {
        let (year, quarter) = parse_quarter_tab(trip_id)?;
        return quarter_scope(year, quarter);
    }
    let catalog = TripCatalog::from_snapshot(trips.iter().map(|t| t.tab_key().to_owned()));
    catalog.resolve(trip_id).map(|t| OpenScope::trip(&t))
}

/// 행이 열린 범위(`open_scope`)일 때 `OpenScope`를 발급한다. 귀속 탭이 있으면 그 탭, 없으면 날짜의 분기.
pub fn scope_for_row(row: &CardRow, trips: &[TripTab]) -> Option<OpenScope> {
    if !open_scope(row, trips) {
        return None;
    }
    for id in [row.trip_id.as_deref(), row.display_tab_id.as_deref()]
        .into_iter()
        .flatten()
    {
        if let Some(scope) = scope_for_tab(trips, id) {
            return Some(scope);
        }
    }
    let day = row.dates.day()?;
    let (year, quarter) = quarter_of(day);
    if (i64::from(year), i64::from(quarter)) < (2026, 3) {
        return None;
    }
    quarter_scope(i64::from(year), i64::from(quarter))
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::dates::RowDates;

    fn tab(id: &str, starts: &str) -> TripTab {
        TripTab {
            trip_id: Some(id.into()),
            starts_on: Some(starts.into()),
            ..TripTab::default()
        }
    }

    fn row(day: &str, trip: Option<&str>) -> CardRow {
        CardRow {
            dates: RowDates {
                approval_date: Some(day.into()),
                posting_date: None,
            },
            trip_id: trip.map(Into::into),
            ..CardRow::default()
        }
    }

    #[test]
    fn quarter_tabs_issue_quarter_scope_only_when_open() {
        assert!(scope_for_tab(&[], "quarter:2026:3").is_some());
        assert!(scope_for_tab(&[], "quarter:2026:2").is_none());
        assert!(scope_for_tab(&[], "quarter:2026:7").is_none()); // 열린 탭이지만 표현 불가
        assert!(scope_for_tab(&[], "quarter:2026-Q4").is_some());
    }

    #[test]
    fn trip_tabs_issue_trip_scope_only_when_open() {
        let trips = [tab("open", "2026-08-01"), tab("old", "2026-01-01")];
        assert!(scope_for_tab(&trips, "open").is_some());
        assert!(scope_for_tab(&trips, "old").is_none());
        assert!(scope_for_tab(&trips, "ghost").is_none());
    }

    #[test]
    fn date_only_rows_get_their_own_open_quarter_or_nothing() {
        let q3 = scope_for_row(&row("2026-08-15", None), &[]).unwrap();
        assert!(q3.covers(&crate::domain::Attribution::QuarterOther {
            year: 2026,
            quarter: Quarter::Q3
        }));
        // 2026-06-30은 현행 기간(3분기) 첫날이다
        let edge = scope_for_row(&row("2026-06-30", None), &[]).unwrap();
        assert!(edge.covers(&crate::domain::Attribution::QuarterOther {
            year: 2026,
            quarter: Quarter::Q3
        }));
        assert!(scope_for_row(&row("2026-06-29", None), &[]).is_none());
        assert!(scope_for_row(&row("2026-03-01", None), &[]).is_none());
    }

    #[test]
    fn row_with_open_trip_gets_trip_scope() {
        let trips = [tab("open", "2026-08-01")];
        let scope = scope_for_row(&row("2026-03-01", Some("open")), &trips).unwrap();
        assert!(!scope.covers(&crate::domain::Attribution::QuarterOther {
            year: 2026,
            quarter: Quarter::Q1
        }));
    }
}
