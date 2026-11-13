//! `core/golden/synthetic/dates.jsonl`(생산기: `tools/core_dates_golden.py`)의 Python 기대값과 Rust 결과를 모두 비교한다.

use cost_rules::closed_period::{
    CardRow, Evidence, ServicePeriod, TripTab, completed_period, completed_trip, exception_trip,
    excluded, open_scope, open_trip,
};
use cost_rules::dates::{
    DateError, RowDates, Span, card_use_date, covers_stay, handover_days, ledger_date_for_booking,
    open_trip_end, overlaps_stay, parse_iso, prep_trip, quarter_of, shared_days, tab_of,
};
use cost_rules::open_scope::open_p2_tab;
use serde_json::{Value, json};
use std::collections::{BTreeMap, BTreeSet};

fn opt(v: &Value, key: &str) -> Option<String> {
    v.get(key).and_then(Value::as_str).map(str::to_string)
}

fn row_dates(v: &Value) -> RowDates {
    RowDates {
        approval_date: opt(v, "approval_date"),
        posting_date: opt(v, "posting_date"),
    }
}

fn card_row(v: &Value) -> CardRow {
    CardRow {
        dates: row_dates(v),
        trip_id: opt(v, "trip_id"),
        display_tab_id: opt(v, "display_tab_id"),
        source_hash: opt(v, "source_hash"),
    }
}

fn trip_tab(v: &Value) -> TripTab {
    TripTab {
        trip_id: opt(v, "trip_id"),
        tab_id: opt(v, "tab_id"),
        starts_on: opt(v, "starts_on"),
        ends_on: opt(v, "ends_on"),
        deleted: v.get("deleted").and_then(Value::as_bool).unwrap_or(false),
        archived: v.get("archived").and_then(Value::as_bool).unwrap_or(false),
    }
}

fn span(v: &Value) -> Span {
    Span {
        starts_on: opt(v, "starts_on"),
        ends_on: opt(v, "ends_on"),
    }
}

fn evidence(v: &Value) -> Option<Evidence> {
    if v.is_null() {
        return None;
    }
    let period = &v["service_period"];
    Some(Evidence {
        trip_id: opt(v, "trip_id"),
        service_period: ServicePeriod {
            starts_on: opt(period, "starts_on"),
            ends_on: opt(period, "ends_on"),
        },
        formal_link: v["formal_link"].as_bool().unwrap_or(false),
        source_hash: opt(v, "source_hash"),
    })
}

fn s<'a>(v: &'a Value, key: &str) -> &'a str {
    v[key].as_str().unwrap_or("")
}

/// 기대값이 `err`이면 `Err`, 아니면 `out`. 비교 가능한 JSON으로 맞춘다.
fn expected(case: &Value) -> Result<Value, ()> {
    if case.get("err").is_some() {
        Err(())
    } else {
        Ok(case["out"].clone())
    }
}

fn date_result<T>(r: Result<T, DateError>, f: impl FnOnce(T) -> Value) -> Result<Value, ()> {
    r.map(f).map_err(|_| ())
}

fn opt_json(v: Option<String>) -> Value {
    v.map_or(Value::Null, Value::String)
}

#[test]
fn golden_dates_match_python() {
    let path = concat!(
        env!("CARGO_MANIFEST_DIR"),
        "/../../golden/synthetic/dates.jsonl"
    );
    let text = std::fs::read_to_string(path).expect("golden file");
    let mut fixtures: BTreeMap<String, Vec<TripTab>> = BTreeMap::new();
    let mut counts: BTreeMap<String, usize> = BTreeMap::new();
    let mut total = 0;
    for line in text.lines() {
        let case: Value = serde_json::from_str(line).expect("json line");
        let name = case["fn"].as_str().unwrap().to_string();
        if name == "_fixtures" {
            for (key, trips) in case["trips"].as_object().unwrap() {
                fixtures.insert(
                    key.clone(),
                    trips.as_array().unwrap().iter().map(trip_tab).collect(),
                );
            }
            continue;
        }
        let input = &case["in"];
        let want = expected(&case);
        let trips_of = |v: &Value| fixtures[v["trips"].as_str().unwrap()].clone();
        let got: Result<Value, ()> = match name.as_str() {
            "quarter_of" => date_result(parse_iso(s(input, "day")), |d| {
                let (y, q) = quarter_of(d);
                json!([y, q])
            }),
            "tab_of" => Ok(opt_json(tab_of(&row_dates(&input["row"])))),
            "completed_period" => {
                Ok(completed_period(&row_dates(&input["row"])).map_or(Value::Null, |p| json!(p)))
            }
            "ledger_date_for_booking" => Ok(json!(ledger_date_for_booking(
                input["service"].as_str(),
                input["payment"].as_str()
            ))),
            "open_trip_end" => date_result(
                open_trip_end(
                    input["starts_on"].as_str(),
                    input["next_starts_on"].as_str(),
                ),
                opt_json,
            ),
            "card_use_date" => Ok(json!(card_use_date(input["approval_date"].as_str()))),
            "handover_days" => {
                let spans: Vec<Span> = input["trips"]
                    .as_array()
                    .unwrap()
                    .iter()
                    .map(span)
                    .collect();
                date_result(handover_days(&spans), |set| {
                    json!(set.into_iter().collect::<Vec<_>>())
                })
            }
            "prep_trip" => {
                let spans: Vec<Span> = input["trips"]
                    .as_array()
                    .unwrap()
                    .iter()
                    .map(span)
                    .collect();
                Ok(prep_trip(&spans, s(input, "check_out")).map_or(Value::Null, |i| json!(i)))
            }
            "covers_stay" | "overlaps_stay" | "shared_days" => {
                let handover: BTreeSet<String> = input["handover"]
                    .as_array()
                    .unwrap()
                    .iter()
                    .map(|v| v.as_str().unwrap().to_string())
                    .collect();
                let args = (
                    s(input, "trip_start"),
                    s(input, "trip_end"),
                    s(input, "check_in"),
                    s(input, "check_out"),
                    input["service"].as_bool().unwrap(),
                );
                match name.as_str() {
                    "covers_stay" => date_result(
                        covers_stay(args.0, args.1, args.2, args.3, args.4, &handover),
                        |b| json!(b),
                    ),
                    "overlaps_stay" => date_result(
                        overlaps_stay(args.0, args.1, args.2, args.3, args.4, &handover),
                        |b| json!(b),
                    ),
                    _ => date_result(
                        shared_days(args.0, args.1, args.2, args.3, args.4, &handover),
                        |n| json!(n),
                    ),
                }
            }
            "open_trip" => Ok(json!(open_trip(Some(&trip_tab(&input["trip"]))))),
            "completed_trip" => Ok(json!(completed_trip(Some(&trip_tab(&input["trip"]))))),
            "open_scope" => Ok(json!(open_scope(
                &card_row(&input["row"]),
                &trips_of(input)
            ))),
            "excluded_and_exception_trip" => {
                let (row, trips, ev, manual) = (
                    card_row(&input["row"]),
                    trips_of(input),
                    evidence(&input["evidence"]),
                    input["manual"].as_bool().unwrap(),
                );
                Ok(json!({
                    "excluded": excluded(&row, &trips, ev.as_ref(), manual),
                    "exception_trip": opt_json(exception_trip(&row, &trips, ev.as_ref(), manual)),
                }))
            }
            "open_p2_tab" => Ok(json!(open_p2_tab(&trips_of(input), s(input, "trip_id")))),
            other => panic!("unknown golden function {other}"),
        };
        assert_eq!(got, want, "case {name}: {line}");
        *counts.entry(name).or_default() += 1;
        total += 1;
    }
    println!("dates golden: {total} cases, {counts:?}");
    assert!(total >= 1300, "golden shrank: {total}");
}

#[test]
fn boundary_days_are_explicit() {
    let day = |s: &str| parse_iso(s).unwrap();
    assert_eq!(quarter_of(day("2026-06-29")), (2026, 2));
    assert_eq!(quarter_of(day("2026-06-30")), (2026, 3));
    assert_eq!(quarter_of(day("2026-09-30")), (2026, 3));
    assert_eq!(quarter_of(day("2026-10-01")), (2026, 4));
    let dates = |a: &str| RowDates {
        approval_date: Some(a.into()),
        posting_date: None,
    };
    assert_eq!(completed_period(&dates("2025-01-01")), Some("2025"));
    assert_eq!(completed_period(&dates("2025-12-31")), Some("2025"));
    assert_eq!(completed_period(&dates("2026-01-01")), Some("2026Q1"));
    assert_eq!(completed_period(&dates("2026-03-31")), Some("2026Q1"));
    assert_eq!(completed_period(&dates("2026-04-01")), None);
    assert_eq!(completed_period(&dates("2024-12-31")), None);
}
