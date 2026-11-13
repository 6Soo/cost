//! `classify.jsonl` 중 여행 해석이 필요한 사례(`trip_ids`)와 3820 잔여 정책을 Rust 판정과 비교한다(U6).
//! 여행 입력은 골든의 `trip_ids` 그대로: 추론이 가리킨 여행이 목록에 있으면 그것, 아니면 첫 여행(`tools/core_bridge/commands.py:_pick`).

use cost_core::rules::{Builtin, Rule, Transaction, TripHint, classify_with_trips};
use serde_json::Value;

fn pick(hint: &TripHint, trips: &[String]) -> String {
    match hint {
        TripHint::InferredTrip { trip_id, .. } if trips.contains(trip_id) => trip_id.clone(),
        _ => trips[0].clone(),
    }
}

#[test]
fn golden_classify_with_trip_input_matches_python() {
    let path = concat!(
        env!("CARGO_MANIFEST_DIR"),
        "/../../golden/synthetic/classify.jsonl"
    );
    let text = std::fs::read_to_string(path).expect("golden file");
    let builtin = Builtin::embedded().expect("embedded rules load");
    let (mut compared, mut matched, mut residual) = (0, 0, 0);
    for line in text.lines().filter(|l| !l.trim().is_empty()) {
        let case: Value = serde_json::from_str(line).unwrap();
        let input = &case["input"]["cases"][0];
        let trips: Vec<String> = input["trip_ids"]
            .as_array()
            .map(|t| t.iter().map(|v| v.as_str().unwrap().to_string()).collect())
            .unwrap_or_default();
        let is_residual = input["residual_policy"].as_bool().unwrap_or(false);
        if trips.is_empty() && !is_residual {
            continue;
        }
        compared += 1;
        residual += usize::from(is_residual);
        let rules: Vec<Rule> = input["rules"]
            .as_array()
            .map(|rules| rules.iter().map(Rule::from_value).collect())
            .unwrap_or_default();
        let txn = Transaction::from_value(&input["transaction"]);
        let resolver = |_: &Transaction, hint: &TripHint| pick(hint, &trips);
        let got = classify_with_trips(
            &txn,
            &rules,
            input["prior_decision"].as_object(),
            &builtin,
            if trips.is_empty() {
                None
            } else {
                Some(&resolver)
            },
            is_residual,
        )
        .to_value();
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
    println!("trip golden: {matched}/{compared} compared ({residual} residual)");
    assert!(compared >= 26, "golden shrank: {compared}");
    assert_eq!(matched, compared);
}
