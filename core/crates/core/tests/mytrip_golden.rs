//! Expectations produced by the unchanged Python Mytrip parser, using synthetic mail only.
//!
//! The input carries what the shared Python mail helpers compute (subject, body text, KST send
//! date); this slice owns the matching, leg and total checks, aggregation and ids.
use cost_core::digest::{python_json_compact, sha256_hex};
use cost_core::extract::{MytripInput, mytrip_events};
use serde_json::{Value, json};

fn records() -> Vec<Value> {
    include_str!("../../../golden/synthetic/mytrip_mail.jsonl")
        .lines()
        .map(|line| serde_json::from_str(line).unwrap())
        .collect()
}

#[test]
fn every_python_mytrip_case_matches_events_and_bytes() {
    let cases = records();
    assert_eq!(cases.len(), 26, "golden case count changed");
    for case in &cases {
        let input: MytripInput = serde_json::from_value(case["input"].clone()).unwrap();
        let events = mytrip_events(&input);
        assert_eq!(
            json!(events),
            case["expected"]["events"],
            "{}",
            case["case_id"]
        );
        let text = python_json_compact(&json!({"events": events}));
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
fn malformed_input_is_rejected() {
    let cases = records();
    for pointer in ["/messages", "/inventory"] {
        let mut broken = cases[1]["input"].clone();
        *broken.pointer_mut(pointer).unwrap() = Value::Null;
        assert!(serde_json::from_value::<MytripInput>(broken).is_err());
    }
    let mut broken = cases[1]["input"].clone();
    *broken.pointer_mut("/messages/m1/sent_day").unwrap() = json!(1);
    assert!(serde_json::from_value::<MytripInput>(broken).is_err());
}
