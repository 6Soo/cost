//! Expectations produced by the unchanged Python Traveloka parser, using synthetic mail only.
//!
//! The input carries what the shared Python mail helpers compute (authentication, raw text,
//! `Cf`-stripped text); this unit owns the domain decisions and the fact digest.
use cost_core::digest::{python_json_compact, sha256_hex};
use cost_core::extract::{TravelokaInput, traveloka_fact};
use serde_json::{Value, json};

fn records() -> Vec<Value> {
    include_str!("../../../golden/synthetic/traveloka_mail.jsonl")
        .lines()
        .map(|line| serde_json::from_str(line).unwrap())
        .collect()
}

#[test]
fn every_python_traveloka_case_matches_references_fact_and_bytes() {
    let cases = records();
    assert!(cases.len() >= 20);
    for case in &cases {
        let input: TravelokaInput = serde_json::from_value(case["input"].clone()).unwrap();
        let (references, fact) = traveloka_fact(&input);
        let expected = &case["expected"];
        assert_eq!(
            json!(references),
            expected["references"],
            "{}",
            case["case_id"]
        );
        assert_eq!(
            fact.clone().map_or(Value::Null, Value::from),
            expected["fact"],
            "{}",
            case["case_id"]
        );
        let text = python_json_compact(&json!({"references": references, "fact": fact}));
        assert_eq!(sha256_hex(&text), case["sha256"], "{}", case["case_id"]);
        assert_eq!(json!(text.len()), case["bytes"], "{}", case["case_id"]);
        assert_eq!(
            json!(text.chars().count()),
            case["chars"],
            "{}",
            case["case_id"]
        );
    }
}

#[test]
fn unauthenticated_input_never_invents_a_fact() {
    let cases = records();
    let unauthenticated = cases
        .iter()
        .find(|case| case["input"]["subject"].is_null())
        .expect("unauthenticated case");
    let input: TravelokaInput = serde_json::from_value(unauthenticated["input"].clone()).unwrap();
    let (references, fact) = traveloka_fact(&input);
    assert!(references.is_empty());
    assert!(fact.is_none());
}

#[test]
fn malformed_input_is_rejected() {
    let cases = records();
    for pointer in ["/raw_text", "/stripped_text"] {
        let mut broken = cases[1]["input"].clone();
        *broken.pointer_mut(pointer).unwrap() = Value::Null;
        assert!(serde_json::from_value::<TravelokaInput>(broken).is_err());
    }
}

#[test]
fn lookbehind_and_word_boundary_post_filters_hold() {
    let shapes = [
        ("1234,567원", None),
        ("1123,456원", None),
        ("1,234원", Some(1234)),
        ("000123원", Some(123)),
        ("1,230원 1230원", None),
    ];
    for (text, expected) in shapes {
        let body = format!("Booking ID: 987654321\n{text}");
        let input = TravelokaInput {
            message: json!({"payload": {"headers": []}}),
            subject: Some("Traveloka e-ticket payment complete".to_owned()),
            raw_text: body.clone(),
            stripped_text: body,
        };
        let (_, fact) = traveloka_fact(&input);
        let amount = fact.map(|fact| fact["paid_amount_krw"].clone());
        match expected {
            None => assert_eq!(amount, Some(Value::Null), "{text}"),
            Some(value) => assert_eq!(amount, Some(json!(value)), "{text}"),
        }
    }
}
