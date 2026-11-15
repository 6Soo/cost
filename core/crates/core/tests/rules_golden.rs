//! `core/golden/synthetic/classify.jsonl`(Python `classify_transaction` 출력)과 Rust 판정을 비교한다.
//! 여행 해석기가 필요한 사례(`trip_ids`)와 3820 잔여 정책(`residual_policy`)은 U6 범위라 세지 않는다.

use cost_core::rules::{Builtin, Rule, Transaction, classify};
use serde_json::Value;

#[test]
fn golden_classify_without_trip_resolver_matches_python() {
    let path = concat!(
        env!("CARGO_MANIFEST_DIR"),
        "/../../golden/synthetic/classify.jsonl"
    );
    let text = std::fs::read_to_string(path).expect("golden file");
    let builtin = Builtin::embedded().expect("embedded rules load");
    let (mut total, mut compared, mut matched) = (0, 0, 0);
    for line in text.lines().filter(|l| !l.trim().is_empty()) {
        let case: Value = serde_json::from_str(line).unwrap();
        let input = &case["input"]["cases"][0];
        total += 1;
        let needs_resolver = input["trip_ids"].as_array().is_some_and(|t| !t.is_empty())
            || input["residual_policy"].as_bool().unwrap_or(false);
        if needs_resolver {
            continue;
        }
        compared += 1;
        let rules: Vec<Rule> = input["rules"]
            .as_array()
            .map(|rules| rules.iter().map(Rule::from_value).collect())
            .unwrap_or_default();
        let txn = Transaction::from_value(&input["transaction"]);
        let prior = input["prior_decision"].as_object();
        let got = classify(&txn, &rules, prior, &builtin).to_value();
        let want = &case["expected"]["verdicts"][0];
        if &got == want {
            matched += 1;
        } else {
            eprintln!(
                "MISMATCH {} ({}):\n  got  {got}\n  want {want}",
                case["case_id"], case["note"]
            );
        }
    }
    println!("classify golden: {matched}/{compared} compared ({total} total)");
    assert!(compared >= 100, "golden shrank: {compared}");
    assert_eq!(matched, compared);
}
