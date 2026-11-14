//! `core/golden/synthetic/period.jsonl`: Python `verified_period_for`(근거 인덱스 `_build_index` 경유)의 출력과
//! `cost_core::period::verified_period_for`가 같은 입력(다리 `periods`의 `facts`)에서 같은 결과를 내는가.

use cost_core::period::{PeriodRow, verified_period_for};
use serde_json::Value;

#[test]
fn golden_period_matches_python() {
    let path = concat!(
        env!("CARGO_MANIFEST_DIR"),
        "/../../golden/synthetic/period.jsonl"
    );
    let body = std::fs::read_to_string(path).expect("golden file");
    let (mut cases, mut rows, mut with_period, mut bad) = (0, 0, 0, Vec::new());
    for line in body.lines().filter(|l| !l.trim().is_empty()) {
        let case: Value = serde_json::from_str(line).expect("json line");
        let id = case["case_id"].as_str().expect("case id");
        let facts = &case["expected"]["facts"];
        let verified = case["expected"]["verified"].as_object().expect("verified");
        cases += 1;
        for row in case["input"]["rows"].as_array().expect("rows") {
            let row_id = row["row_id"].as_str().expect("row id");
            let period_row = PeriodRow::from_value(row);
            // 후보 목록은 거래 ID(행 ID에서 접두를 뗀 값, 또는 source_event_id)로 찾는다.
            let tid = row["source_event_id"]
                .as_str()
                .unwrap_or(&row_id["card-".len().min(row_id.len())..]);
            let candidates = facts.get(tid).unwrap_or(&Value::Null);
            let got = verified_period_for(&period_row, candidates);
            let want = verified[row_id].as_str().expect("expected period");
            rows += 1;
            with_period += usize::from(!want.is_empty());
            if got != want {
                bad.push(format!("{id} {row_id}: got {got:?} want {want:?}"));
            }
        }
    }
    eprintln!("period golden: {cases} cases, {rows} rows, {with_period} with a period");
    assert!(bad.is_empty(), "{} differ:\n{}", bad.len(), bad.join("\n"));
    assert_eq!(cases, 53);
}
