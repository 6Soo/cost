//! 해석할 수 없는 날짜 입력은 Python과 달리 항상 보호(제외) 방향이어야 한다(소유자 결정 2026-11-14).

use cost_core::dates::{
    CardRow, Evidence, ServicePeriod, TripTab, excluded, open_scope, open_trip,
};
use cost_core::dates::{RowDates, covers_stay, parse_iso, tab_of};
use std::collections::BTreeSet;

const MALFORMED: [&str; 14] = [
    "",
    "20250315",
    "2025-3-15",
    "2025-03-15 ",
    " 2025-03-15",
    "20250101xx",
    "2025-03-15é",
    "2026-W27-2",
    "2026W272",
    "2025-02-29",
    "2026-13-01",
    "0000-01-01",
    "garbage",
    "２０２５-０３-１５",
];

fn row(date: &str) -> CardRow {
    CardRow {
        dates: RowDates {
            approval_date: Some(date.into()),
            posting_date: Some("2025-03-15".into()),
        },
        trip_id: Some("T-open".into()),
        source_hash: Some("h".into()),
        ..CardRow::default()
    }
}

fn open_trip_tab() -> TripTab {
    TripTab {
        trip_id: Some("T-open".into()),
        starts_on: Some("2026-07-01".into()),
        ends_on: Some("2026-07-10".into()),
        ..TripTab::default()
    }
}

#[test]
fn only_iso_dashed_dates_parse() {
    assert!(parse_iso("2025-03-15").is_ok());
    assert!(parse_iso("2028-02-29").is_ok());
    for bad in MALFORMED {
        assert!(parse_iso(bad).is_err(), "{bad:?} must not parse");
    }
}

#[test]
fn unparseable_row_dates_are_protected_never_open() {
    let trips = [open_trip_tab()];
    let evidence = Evidence {
        trip_id: Some("T-open".into()),
        service_period: ServicePeriod {
            starts_on: Some("2026-07-02".into()),
            ends_on: Some("2026-07-08".into()),
        },
        formal_link: true,
        source_hash: Some("h".into()),
    };
    for bad in MALFORMED {
        // 승인일이 비었으면 매입일(2025-03-15)로 넘어가는 빈 문자열은 제외한다.
        if bad.is_empty() {
            continue;
        }
        let r = row(bad);
        for manual in [false, true] {
            assert!(
                excluded(&r, &trips, None, manual),
                "{bad:?} manual={manual}"
            );
            assert!(
                excluded(&r, &trips, Some(&evidence), manual),
                "{bad:?} evidence"
            );
        }
        assert!(tab_of(&r.dates).is_none());
        // 열린 여행 소속이 아니면 날짜만으로 열리지 않는다.
        let no_trip = CardRow { trip_id: None, ..r };
        assert!(
            !open_scope(&no_trip, &trips),
            "{bad:?} must not be open by date"
        );
    }
    let no_dates = CardRow::default();
    assert!(excluded(&no_dates, &trips, None, false));
}

#[test]
fn unparseable_trip_start_is_not_open() {
    for bad in ["2026-6-30", "20260701", "9999", "zzz", "2026-07-01 "] {
        let trip = TripTab {
            starts_on: Some(bad.into()),
            ..open_trip_tab()
        };
        assert!(!open_trip(Some(&trip)), "{bad:?}");
    }
}

#[test]
fn unparseable_stay_dates_are_errors_not_open_results() {
    let none = BTreeSet::new();
    for service in [false, true] {
        assert!(
            covers_stay(
                "2026-06-30",
                "2026-07-10",
                "zzz",
                "2026-07-02",
                service,
                &none
            )
            .is_err()
        );
        assert!(
            covers_stay(
                "9999",
                "2026-07-10",
                "2026-07-01",
                "2026-07-02",
                service,
                &none
            )
            .is_err()
        );
    }
}
