//! `classify.jsonl` 중 여행 해석이 필요한 사례(`trip_ids`)와 3820 잔여 정책을 Rust 판정과 비교한다(U6).
//! 여행 입력은 골든의 `trip_ids` 그대로: 추론이 가리킨 여행이 목록에 있으면 그것, 아니면 첫 여행(`tools/core_bridge/commands.py:_pick`).

use cost_core::rules::{Builtin, Rule, Transaction, TripHint, classify_with_trips};
use serde_json::Value;

// 알려진 차이는 `core/known-diffs.txt`(그림자 실행과 같은 파일)의 `classify-` 줄이다.
fn known_cases(prefix: &str) -> Vec<String> {
    let path = concat!(env!("CARGO_MANIFEST_DIR"), "/../../known-diffs.txt");
    let text = std::fs::read_to_string(path).expect("known-diffs.txt");
    let known = cost_core::shadow::parse_known_diffs(&text).expect("known-diffs.txt format");
    known
        .cases_with_prefix(prefix)
        .into_iter()
        .map(str::to_owned)
        .collect()
}

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
    let known_ids = known_cases("classify-");
    let (mut compared, mut matched, mut residual, mut seen_known) = (0, 0, 0, 0);
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
        let python = &case["expected"]["verdicts"][0];
        let id = case["case_id"].as_str().unwrap();
        let protected = serde_json::json!({
            "classification_basis": "", "classification_source": "", "classification_state": "needs_review",
            "description": "", "display_tab_id": "", "item": "", "rule_id": "", "trip_id": ""
        });
        let known = known_ids.iter().any(|k| k == id);
        seen_known += usize::from(known);
        if known {
            // 사유: 빈 날짜는 보호. Python 기대값과 달라야 하고(사라지면 목록에서 지운다), Rust 기대값은 보호 판정이다.
            assert_ne!(
                &got, python,
                "{id} no longer differs: remove from known-diffs.txt"
            );
        }
        let want = if known { &protected } else { python };
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
    assert_eq!(
        seen_known,
        known_ids.len(),
        "known-diffs.txt lists a case not compared here"
    );
}
