//! 연결 그림자 시험: 골든의 기대 출력(= Python 출력)을 가짜 Python으로 쓴다. 운영 DB·Python 실행 없음.

use std::collections::BTreeSet;
use std::path::Path;

use serde_json::{Value, json};

use super::keys::validate_key;
use super::links::*;
use super::{KnownDiffs, parse_known_diffs};
use crate::links::ota::Defaults;
use crate::links::refund::{PairingConfig, RefundTxn};

fn root() -> std::path::PathBuf {
    Path::new(env!("CARGO_MANIFEST_DIR")).join("../../..")
}

fn golden(name: &str) -> Vec<Value> {
    std::fs::read_to_string(root().join("core/golden/synthetic").join(name))
        .unwrap()
        .lines()
        .map(|l| serde_json::from_str(l).unwrap())
        .collect()
}

fn config() -> PairingConfig {
    PairingConfig::from_json(
        &std::fs::read_to_string(root().join("config/refund-pairing.json")).unwrap(),
    )
    .unwrap()
}

fn defaults() -> Defaults {
    let text = std::fs::read_to_string(root().join("config/ota-matching-defaults.json")).unwrap();
    Defaults::from_value(&serde_json::from_str(&text).unwrap()).unwrap()
}

/// 합성 시나리오 DB가 채우는 기본값(`tools/core_bridge/synthetic.py`)을 따른다.
fn row(v: &Value) -> RefundTxn {
    let text = |k: &str| v[k].as_str().unwrap_or("").to_owned();
    let or = |k: &str, d: &str| v[k].as_str().unwrap_or(d).to_owned();
    let merchant = text("merchant");
    let normalized = text("merchant_normalized");
    RefundTxn {
        transaction_id: text("transaction_id"),
        issuer: or("issuer", "SYN-BANK"),
        card_tail: or("card_tail", "0001"),
        direction: or("transaction_direction", "purchase"),
        approval_number: text("approval_number"),
        original_approval_number: text("original_approval_number"),
        amount_krw: v["amount_krw"].as_i64(),
        approval_date: text("approval_date"),
        posting_date: text("posting_date"),
        merchant_normalized: if normalized.is_empty() {
            merchant.to_lowercase()
        } else {
            normalized
        },
        merchant,
        foreign_amount: text("foreign_amount"),
        foreign_currency: text("foreign_currency"),
        duplicate_of: v["duplicate_of"].as_str().map(str::to_owned),
        conflict_reason: text("conflict_reason"),
        parse_error: text("parse_error"),
    }
}

fn refund_case(case: &Value) -> (Vec<RefundTxn>, Value) {
    let rows = case["input"]["scenario"]["rows"]
        .as_array()
        .unwrap()
        .iter()
        .map(row)
        .collect();
    (rows, case["expected"].clone())
}

#[test]
fn refund_goldens_have_no_difference() {
    let cfg = config();
    let cases = golden("refund_pairing.jsonl");
    assert_eq!(cases.len(), 42);
    for case in &cases {
        let (rows, python) = refund_case(case);
        let part = compare_refund(&rows, &cfg, &python).unwrap();
        assert!(
            part.diffs.is_empty(),
            "{}: {:?}",
            case["case_id"],
            part.diffs
        );
    }
}

#[test]
fn a_changed_removed_or_extra_refund_link_gets_a_type_key() {
    let cfg = config();
    let case = golden("refund_pairing.jsonl")
        .into_iter()
        .find(|c| c["case_id"] == "refund_pairing-002")
        .unwrap();
    let (rows, python) = refund_case(&case);
    let key = |python: &Value| -> BTreeSet<String> {
        compare_refund(&rows, &cfg, python)
            .unwrap()
            .diffs
            .into_iter()
            .map(|d| d.key)
            .collect()
    };
    let mut changed = python.clone();
    changed["links"]["syn-r2"]["status"] = json!("partial");
    assert!(key(&changed).contains("B-C|refund_link|partial|differs"));
    let mut removed = python.clone();
    removed["links"] = json!({});
    assert!(key(&removed).contains("B-C|refund_link|full|added"));
    let mut extra = python.clone();
    extra["links"]["syn-r9"] = json!({"status": "full", "original_id": "syn-r1"});
    assert!(key(&extra).contains("B-C|refund_link|full|removed"));
    let mut review = python;
    review["review_originals"] = json!([]);
    assert!(key(&review).contains("B-C|refund_review|none|added"));
    for k in key(&changed)
        .iter()
        .chain(&key(&removed))
        .chain(&key(&review))
    {
        validate_key(k).unwrap();
    }
}

#[test]
fn ota_goldens_have_no_difference() {
    let defaults = defaults();
    let cases: Vec<Value> = ["ota_links.jsonl", "ota_mn.jsonl"]
        .iter()
        .flat_map(|n| golden(n))
        .collect();
    assert_eq!(cases.len(), 55 + 39);
    for case in &cases {
        let python = json!({"results": case["expected"]["results"]});
        let part = compare_ota(&case["input"], &defaults, &python).unwrap();
        assert!(
            part.diffs.is_empty(),
            "{}: {:?}",
            case["case_id"],
            part.diffs
        );
    }
}

#[test]
fn an_ota_status_change_and_a_missing_result_get_type_keys() {
    let defaults = defaults();
    let case = golden("ota_links.jsonl")
        .into_iter()
        .find(|c| c["expected"]["results"][0]["status"] == "MATCHED_AUTO")
        .unwrap();
    let mut python = json!({"results": case["expected"]["results"]});
    python["results"][0]["status"] = json!("MATCHED_USER");
    let part = compare_ota(&case["input"], &defaults, &python).unwrap();
    assert_eq!(part.diffs[0].key, "B-C|ota_link|MATCHED_USER|differs");
    let python = json!({"results": []});
    let part = compare_ota(&case["input"], &defaults, &python).unwrap();
    assert!(part.diffs.iter().any(|d| d.key.ends_with("|added")));
    assert!(
        part.diffs
            .iter()
            .any(|d| d.key == "B-C|ota_link|none|differs")
    );
    assert!(!part.diffs.is_empty());
}

#[test]
fn public_keys_outside_the_vocabulary_are_rejected() {
    for bad in [
        "B-C|refund_link|SYN SHOP|differs",
        "B-C|refund_link|full|renamed",
        "A-B|refund_link|full|differs",
        "B-C|ota_link|HOLD_X|differs",
    ] {
        assert!(validate_key(bad).is_err(), "{bad}");
    }
    validate_key("B-C|ota_link|HOLD_NO_CARD|removed").unwrap();
}

#[test]
fn only_link_keys_are_judged_and_the_two_shadows_do_not_mix() {
    let known: KnownDiffs = parse_known_diffs(
        "B-C|refund_link|full|added  # 근거\nB-C|state|rule|classified→needs_review  # 판정\nplan-039  # 사례\n",
    )
    .unwrap();
    let part = |keys: &[&str]| LinksPart {
        python_items: 1,
        rust_items: 1,
        diffs: keys
            .iter()
            .map(|k| LinkDiff {
                key: (*k).to_owned(),
                id: "x".to_owned(),
                python: Value::Null,
                rust: Value::Null,
            })
            .collect(),
    };
    let listed = judge_links(Some(part(&["B-C|refund_link|full|added"])), None, &known);
    assert!(listed.passed());
    assert!(listed.verdict.resolved.is_empty());
    let clean = judge_links(Some(part(&[])), None, &known);
    assert_eq!(clean.verdict.resolved, ["B-C|refund_link|full|added"]);
    let unlisted = judge_links(
        None,
        Some(part(&["B-C|ota_link|MATCHED_AUTO|differs"])),
        &known,
    );
    assert!(!unlisted.passed());
    let json = unlisted.public_json().unwrap();
    assert_eq!(json["status"], "FAIL");
    assert!(!json.to_string().contains("syn-"));
    assert!(
        known
            .without_link_keys()
            .keys
            .iter()
            .all(|k| !is_link_key(k))
    );
}

#[test]
fn ota_duplicates_are_reported_even_when_another_difference_is_listed() {
    let defaults = defaults();
    let case = golden("ota_links.jsonl")
        .into_iter()
        .find(|c| c["expected"]["results"][0]["status"] == "MATCHED_AUTO")
        .unwrap();
    let mut python = json!({"results": case["expected"]["results"]});
    python["results"][0]["status"] = json!("MATCHED_USER");
    let first = python["results"][0].clone();
    python["results"].as_array_mut().unwrap().push(first);
    let part = compare_ota(&case["input"], &defaults, &python).unwrap();
    let keys: BTreeSet<_> = part.diffs.iter().map(|d| d.key.as_str()).collect();
    assert!(keys.contains("B-C|ota_link|MATCHED_USER|differs"));
    assert!(keys.contains("B-C|ota_link|none|differs"));
    let known = parse_known_diffs("B-C|ota_link|MATCHED_USER|differs  # 근거\n").unwrap();
    assert!(!judge_links(None, Some(part), &known).passed());
}

#[test]
fn a_duplicated_refund_id_cannot_hide_in_the_link_map() {
    assert!(duplicate_link_diff(2, 2, 2).is_none());
    let diff = duplicate_link_diff(3, 2, 2).unwrap();
    assert_eq!(diff.key, "B-C|refund_link|none|differs");
    validate_key(&diff.key).unwrap();
    let known = parse_known_diffs(
        "B-C|refund_link|full|added  # 근거
",
    )
    .unwrap();
    let part = LinksPart {
        python_items: 2,
        rust_items: 3,
        diffs: vec![diff],
    };
    assert!(!judge_links(Some(part), None, &known).passed());
}
