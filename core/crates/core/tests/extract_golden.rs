//! Expectations produced by unchanged Python helpers, using synthetic facts only.
use cost_core::digest::sha256_hex;
use cost_core::extract::{SourceStages, baseline_bytes, build_ota_payment_events};
use serde_json::{Value, json};

#[test]
fn every_python_extractor_vector_matches_all_fields_and_bytes() {
    let mut count = 0;
    for line in include_str!("../../../golden/synthetic/extract.jsonl").lines() {
        let case: Value = serde_json::from_str(line).unwrap();
        let stages: SourceStages = serde_json::from_value(case["input"].clone()).unwrap();
        let events = build_ota_payment_events(stages).unwrap();
        assert_eq!(
            json!({"events": events}),
            case["expected"],
            "{}",
            case["case_id"]
        );
        let bytes = baseline_bytes(&events).unwrap();
        assert_eq!(sha256_hex(&bytes), case["sha256"], "{}", case["case_id"]);
        assert_eq!(json!(bytes.len()), case["bytes"], "{}", case["case_id"]);
        count += 1;
    }
    assert!(count >= 50);
}

#[test]
fn malformed_stages_fail_instead_of_emitting_partial_events() {
    let valid: Value = serde_json::from_str(
        include_str!("../../../golden/synthetic/extract.jsonl")
            .lines()
            .nth(1)
            .unwrap(),
    )
    .unwrap();
    for (pointer, value) in [
        ("/schema_version", json!("wrong")),
        ("/mail_events/0/ota_event_id", Value::Null),
        ("/mail_events/0/source_ids", json!([1])),
    ] {
        let mut input = valid["input"].clone();
        *input.pointer_mut(pointer).unwrap() = value;
        let stages = serde_json::from_value(input).unwrap();
        assert_eq!(
            build_ota_payment_events(stages).unwrap_err().code(),
            "EXTRACT_INPUT_INVALID"
        );
    }
}
