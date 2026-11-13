//! `core/golden/synthetic/trips.jsonl`(Python 함수 직접 호출 출력)과 `cost_core::trips` 결과를 모두 비교한다.

use cost_core::dates::{Evidence, ServicePeriod};
use cost_core::trips::{
    BookingPeriod, Canonical, InferOptions, Nets, Trip, Txn, booking_trip, card_trip_candidates,
    card3820_owner_policy, infer_item, infer_trip, stay_trip,
};
use serde_json::{Value, json};
use std::collections::BTreeMap;

fn text(v: &Value, key: &str) -> String {
    v.get(key).and_then(Value::as_str).unwrap_or("").to_string()
}

fn truthy(v: &Value, key: &str) -> bool {
    match v.get(key) {
        Some(Value::Bool(b)) => *b,
        Some(Value::Number(n)) => n.as_f64().is_some_and(|f| f != 0.0),
        Some(Value::String(s)) => !s.is_empty(),
        Some(Value::Array(a)) => !a.is_empty(),
        _ => false,
    }
}

fn trip(v: &Value) -> Trip {
    Trip {
        trip_id: text(v, "trip_id"),
        tab_id: text(v, "tab_id"),
        display_key: text(v, "display_key"),
        destination: text(v, "destination"),
        starts_on: text(v, "starts_on"),
        ends_on: v.get("ends_on").and_then(Value::as_str).map(str::to_string),
        deleted: truthy(v, "deleted"),
        archived: truthy(v, "archived"),
        disabled: v.get("enabled") == Some(&Value::Bool(false)),
        invalid: v.get("valid") == Some(&Value::Bool(false)),
        conflict: truthy(v, "conflict"),
        period_conflict: truthy(v, "period_conflict"),
        flags: v
            .get("flags")
            .and_then(Value::as_array)
            .map(|a| {
                a.iter()
                    .filter_map(|f| f.as_str().map(str::to_string))
                    .collect()
            })
            .unwrap_or_default(),
    }
}

fn trips(input: &Value) -> Vec<Trip> {
    input["trips"]
        .as_array()
        .map_or_else(Vec::new, |a| a.iter().map(trip).collect())
}

fn txn(v: &Value) -> Txn {
    Txn {
        merchant: text(v, "merchant"),
        approval_date: text(v, "approval_date"),
        posting_date: text(v, "posting_date"),
        card_kind: text(v, "card_kind"),
        card_tail: text(v, "card_tail"),
        issuer: text(v, "issuer"),
        foreign_currency: text(v, "foreign_currency"),
        description_raw: text(v, "description_raw"),
        transaction_direction: v
            .get("transaction_direction")
            .and_then(Value::as_str)
            .map(str::to_string),
        transaction_kind: text(v, "transaction_kind"),
        parse_error: text(v, "parse_error"),
        duplicate_of: text(v, "duplicate_of"),
        conflict_reason: text(v, "conflict_reason"),
        classification_source: text(v, "classification_source"),
        item: text(v, "item"),
        description: text(v, "description"),
        trip_id: text(v, "trip_id"),
        display_tab_id: text(v, "display_tab_id"),
        source_hash: text(v, "source_hash"),
        amount_krw: v.get("amount_krw").and_then(Value::as_i64),
        raw_row: v
            .get("raw_row")
            .and_then(Value::as_object)
            .map(|m| {
                m.iter()
                    .filter_map(|(k, x)| x.as_str().map(|s| (k.clone(), s.to_string())))
                    .collect()
            })
            .unwrap_or_default(),
    }
}

fn nets(input: &Value) -> Nets {
    input
        .get("nets")
        .and_then(Value::as_object)
        .map(|m| {
            m.iter()
                .filter_map(|(k, x)| Some((k.clone(), x.as_i64()?)))
                .collect()
        })
        .unwrap_or_default()
}

fn evidence(v: &Value) -> Option<Evidence> {
    let v = v.get("completed_evidence")?;
    let period = &v["service_period"];
    let opt = |x: &Value, k: &str| x.get(k).and_then(Value::as_str).map(str::to_string);
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

fn tab(all: &[Trip], at: Option<usize>) -> Value {
    at.map_or(Value::Null, |i| json!(all[i].tab_id))
}

fn run(input: &Value) -> Value {
    let all = trips(input);
    match input["op"].as_str().unwrap() {
        "infer_trip" => {
            let fact = evidence(input);
            let options = InferOptions {
                nets: nets(input),
                reconsider: input["reconsider"].as_bool().unwrap_or(false),
                completed_evidence: fact.as_ref(),
            };
            let (id, basis) = infer_trip(&txn(&input["row"]), &all, &options);
            json!({"trip_id": id, "basis": basis})
        }
        "candidates" => {
            let mut found =
                card_trip_candidates(&txn(&input["row"]), &Canonical::new(&all), &nets(input));
            found.sort_by(|a, b| a.trip_id.cmp(&b.trip_id));
            let list: Vec<Value> = found
                .iter()
                .map(|c| {
                    json!({"trip_id": c.trip_id, "score": c.score, "confidence": c.confidence, "basis": c.basis})
                })
                .collect();
            json!({"candidates": list})
        }
        "stay_trip" => {
            let at = stay_trip(
                &all,
                &text(input, "check_in"),
                &text(input, "check_out"),
                input["service"].as_bool().unwrap_or(false),
                &nets(input),
            )
            .expect("golden dates are valid");
            json!({"tab_id": tab(&all, at)})
        }
        "booking_trip" => {
            let period = BookingPeriod {
                starts_on: text(input, "check_in"),
                ends_on: text(input, "check_out"),
                service: input["service"].as_bool().unwrap_or(false),
                target_code: input["target_code"].as_str().map(str::to_string),
            };
            let id = booking_trip(&txn(&input["row"]), &all, &period, &nets(input))
                .expect("valid dates");
            json!({"tab_id": id})
        }
        "card3820" => {
            let policy = card3820_owner_policy(&txn(&input["row"]), &Canonical::new(&all)).map(|p| {
                json!({"item": p.item, "description": p.description, "display_tab_id": p.display_tab_id,
                       "trip_id": p.trip_id, "basis": p.basis, "source": p.source})
            });
            json!({"policy": policy})
        }
        "infer_item" => {
            let (item, basis) = infer_item(&txn(&input["row"]));
            json!({"item": item, "basis": basis})
        }
        other => panic!("unknown op {other}"),
    }
}

#[test]
fn golden_trips_match_python() {
    let path = concat!(
        env!("CARGO_MANIFEST_DIR"),
        "/../../golden/synthetic/trips.jsonl"
    );
    let body = std::fs::read_to_string(path).expect("golden file");
    let mut per_op: BTreeMap<String, usize> = BTreeMap::new();
    let mut bad = Vec::new();
    for line in body.lines() {
        let case: Value = serde_json::from_str(line).expect("json line");
        let input = &case["input"];
        let mut want = case["expected"].clone();
        let mut got = run(input);
        if input["op"] == "candidates" {
            let key = |a: &Value, b: &Value| a["trip_id"].as_str().cmp(&b["trip_id"].as_str());
            want["candidates"].as_array_mut().unwrap().sort_by(key);
            got["candidates"].as_array_mut().unwrap().sort_by(key);
        }
        *per_op
            .entry(input["op"].as_str().unwrap().to_string())
            .or_default() += 1;
        if got != want {
            bad.push(format!(
                "{} ({}): want {want} got {got}",
                case["case_id"], case["note"]
            ));
        }
    }
    let total: usize = per_op.values().sum();
    assert!(
        bad.is_empty(),
        "{} of {total} differ ({per_op:?}):\n{}",
        bad.len(),
        bad.join("\n")
    );
    assert_eq!(total, body.lines().count());
    eprintln!("trips golden: {total} of {total} match ({per_op:?})");
}
