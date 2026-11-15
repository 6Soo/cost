//! OTA 최종 연결(U14)을 Python `match_ota_payment_events` 출력과 비교한다.
//! 비교 대상은 연결 칸(쌍·상태·사유·성분 구성·보류 여부·근거 관계)이다. 이벤트 원문 복사 칸은 비교하지 않는다.
//! 보호 불변식(속성 테스트): 한 카드가 두 연결에 점유되지 않고, 기존 수동 연결은 바뀌지 않는다.

use cost_core::links::ota::{Defaults, LinkKind, Matcher};
use cost_core::shadow::links::overlay_event;
use proptest::prelude::*;
use serde_json::{Map, Value, json};
use std::collections::BTreeSet;

const OUTPUT_KEYS: [&str; 22] = [
    "ota_event_id",
    "status",
    "reason",
    "transaction_id",
    "candidates",
    "reserved_card_ids",
    "group_count",
    "ota_group_ids",
    "card_group_ids",
    "matched_count",
    "unmatched_ota_count",
    "unmatched_card_count",
    "allocation_basis",
    "group_order_frozen",
    "group_order_snapshot",
    "individual_payment_evidence",
    "review_warning",
    "frozen_mapping",
    "proposed_mapping",
    "rule_delta_krw",
    "discount_cause_confirmed",
    "payment_date_verified",
];
const MORE_KEYS: [&str; 3] = ["inferred_link", "inference_basis", "payment_relation"];

fn read_lines(name: &str) -> Vec<Value> {
    let path = format!(
        "{}/../../golden/synthetic/{name}",
        env!("CARGO_MANIFEST_DIR")
    );
    std::fs::read_to_string(path)
        .expect("golden file")
        .lines()
        .map(|l| serde_json::from_str(l).expect("json line"))
        .collect()
}

fn defaults() -> Defaults {
    let path = format!(
        "{}/../../../config/ota-matching-defaults.json",
        env!("CARGO_MANIFEST_DIR")
    );
    let value: Value = serde_json::from_str(&std::fs::read_to_string(path).unwrap()).unwrap();
    Defaults::from_value(&value).expect("defaults")
}

fn array(v: &Value, key: &str) -> Vec<Value> {
    v.get(key)
        .and_then(Value::as_array)
        .cloned()
        .unwrap_or_default()
}

fn links(input: &Value) -> Map<String, Value> {
    input
        .get("existing_links")
        .and_then(Value::as_object)
        .cloned()
        .unwrap_or_default()
}

fn pick(result: &Value) -> Value {
    let keep = |k: &String| OUTPUT_KEYS.contains(&k.as_str()) || MORE_KEYS.contains(&k.as_str());
    Value::Object(
        result
            .as_object()
            .expect("object")
            .iter()
            .filter(|(k, _)| keep(k))
            .map(|(k, v)| (k.clone(), v.clone()))
            .collect(),
    )
}

fn run(case: &Value, overlay: bool) -> (Vec<Value>, Vec<Value>) {
    let defaults = defaults();
    let input = &case["input"];
    let (events, cards, rules, frozen) = (
        array(input, "events"),
        array(input, "transactions"),
        array(input, "rules"),
        array(input, "frozen_groups"),
    );
    let matcher = Matcher::new(&defaults, &rules);
    let got: Vec<Value> = matcher
        .match_events(&events, &cards, &links(input), &frozen)
        .iter()
        .map(|l| {
            let link = l.to_value();
            if !overlay {
                return pick(&link);
            }
            let source = events
                .iter()
                .find(|e| e["ota_event_id"] == link["ota_event_id"]);
            pick(&overlay_event(source, &link))
        })
        .collect();
    let want: Vec<Value> = case["expected"]["results"]
        .as_array()
        .expect("results")
        .iter()
        .map(pick)
        .collect();
    (got, want)
}

#[test]
fn final_links_match_python() {
    let (mut checked, mut bad) = (0, Vec::new());
    let cases: Vec<Value> = ["ota_links.jsonl", "ota_mn.jsonl"]
        .iter()
        .flat_map(|name| read_lines(name))
        .collect();
    assert_eq!(cases.len(), 55 + 46);
    for case in cases {
        let (got, want) = run(&case, true);
        for (g, w) in got.iter().zip(&want) {
            checked += 1;
            if g != w {
                bad.push(format!("{}\n  rust:   {g}\n  python: {w}", case["case_id"]));
            }
        }
        assert_eq!(got.len(), want.len(), "{}", case["case_id"]);
    }
    eprintln!(
        "ota links golden: {} of {checked} results match",
        checked - bad.len()
    );
    assert!(bad.is_empty(), "{}", bad.join("\n"));
}

#[test]
fn overlay_is_needed_for_event_fields_the_link_omits() {
    let cases: Vec<Value> = read_lines("ota_mn.jsonl")
        .into_iter()
        .filter(|c| {
            c["note"]
                .as_str()
                .is_some_and(|n| n.starts_with("shadow overlay:"))
        })
        .collect();
    assert_eq!(cases.len(), 7);
    let differs = |overlay: bool| {
        cases
            .iter()
            .filter(|c| {
                let (got, want) = run(c, overlay);
                got != want
            })
            .count()
    };
    assert!(
        differs(false) > 0,
        "without the overlay the new cases must differ"
    );
    assert_eq!(differs(true), 0);
}

fn event_strategy(n: usize) -> impl Strategy<Value = Value> {
    (
        prop_oneof![Just("trip"), Just("agoda")],
        prop_oneof![Just(Some("2026-09-04")), Just(None)],
        prop_oneof![Just(30000), Just(25000)],
        0usize..3,
    )
        .prop_map(move |(provider, paid_on, amount, booking)| {
            json!({
                "ota_event_id": format!("syn-e{n}"), "provider": provider, "booking_ref": format!("SYN-BOOK-{booking}"),
                "event_type": "charge", "paid_on": paid_on, "amount": amount.to_string(), "currency": "KRW",
                "amount_krw": amount, "card_last4": "2042", "item": "항공권", "evidence_status": "paid_verified",
                "payment_status": "paid", "source_digest": format!("syn-e{n}"),
                "service_period": {"starts_on": "2026-10-01", "ends_on": "2026-10-03"},
            })
        })
}

fn card_strategy(n: usize) -> impl Strategy<Value = Value> {
    (
        prop_oneof![Just(30000), Just(25000)],
        prop_oneof![Just("2026-09-04"), Just("2026-09-05")],
        prop_oneof![Just("trip.com"), Just("agoda")],
        0usize..3,
    )
        .prop_map(move |(amount, day, merchant, ap)| {
            json!({
                "transaction_id": format!("syn-t{n}"), "merchant": merchant, "merchant_normalized": merchant,
                "issuer": "SYN-BANK", "card_tail": "2042", "approval_date": day, "amount_krw": amount,
                "transaction_direction": "purchase", "approval_number": format!("SYN-AP-{ap}"),
            })
        })
}

proptest! {
    #![proptest_config(ProptestConfig::with_cases(400))]

    #[test]
    fn no_card_is_taken_by_two_connections_and_manual_links_stay(
        events in (1usize..5).prop_flat_map(|n| (0..n).map(event_strategy).collect::<Vec<_>>()),
        cards in (1usize..5).prop_flat_map(|n| (0..n).map(card_strategy).collect::<Vec<_>>()),
        manual in prop::option::of((0usize..5, 0usize..5)),
    ) {
        let defaults = defaults();
        let matcher = Matcher::new(&defaults, &[]);
        let mut existing = Map::new();
        if let Some((e, c)) = manual.filter(|(e, c)| *e < events.len() && *c < cards.len()) {
            existing.insert(
                events[e]["ota_event_id"].as_str().unwrap().to_string(),
                json!({"transaction_id": cards[c]["transaction_id"], "status": "MATCHED_USER"}),
            );
        }
        let (events_before, cards_before) = (events.clone(), cards.clone());
        let results = matcher.match_events(&events, &cards, &existing, &[]);
        let mut taken = BTreeSet::new();
        for link in &results {
            if let Some(card) = &link.transaction_id {
                prop_assert!(taken.insert(card.clone()), "카드 {card}가 두 연결에 점유됨");
            }
        }
        for (id, link) in &existing {
            let result = results.iter().find(|r| &r.ota_event_id == id).unwrap();
            prop_assert_eq!(&result.kind, &LinkKind::Pinned);
            prop_assert_eq!(result.transaction_id.as_deref(), link["transaction_id"].as_str());
            prop_assert_eq!(&result.status, "MATCHED_USER");
        }
        for link in &results {
            // 근거 관계 성분은 카드 한 장에 대한 일대일 배정을 만들지 않는다.
            if link.status == "MATCHED_GROUP" {
                prop_assert!(link.transaction_id.is_none());
            }
        }
        prop_assert_eq!(events, events_before);
        prop_assert_eq!(cards, cards_before);
    }
}
