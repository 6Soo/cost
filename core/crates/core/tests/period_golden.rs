//! `core/golden/synthetic/period.jsonl`: Python `verified_period_for`(근거 인덱스 `_build_index` 경유)의 출력과
//! `cost_core::period::verified_period_for`가 같은 입력(다리 `periods`의 `facts`)에서 같은 결과를 내는가.
//! 추론·P2·항공 사례(`expected.found`)는 `period_for`가 같은 근거 종류·기간·근거 이름을 내는가.

use cost_core::period::{Found, PeriodRow, period_for, verified_period_for};
use serde_json::{Value, json};

/// 다리 출력의 거래별 `facts`와 `inferred`를 Rust가 받는 거래별 근거 한 값으로 합친다(`evidence_from_snapshot`과 같은 모양).
fn evidence_of(expected: &Value, tid: &str) -> Value {
    let candidates = expected["facts"].get(tid).cloned().unwrap_or(json!([]));
    match expected["inferred"].get(tid) {
        Some(inferred) => json!({"candidates": candidates, "inferred": inferred}),
        None => expected["facts"].get(tid).cloned().unwrap_or(Value::Null),
    }
}

fn found_text(found: &Found) -> Value {
    match found {
        Found::None => json!({"kind": "none", "period": ""}),
        Found::Verified(period) => json!({"kind": "verified", "period": period}),
        Found::Inferred { period, basis } => {
            json!({"kind": "inferred", "period": period, "basis": basis.as_str()})
        }
    }
}

#[test]
fn golden_period_matches_python() {
    let path = concat!(
        env!("CARGO_MANIFEST_DIR"),
        "/../../golden/synthetic/period.jsonl"
    );
    let body = std::fs::read_to_string(path).expect("golden file");
    let (mut cases, mut rows, mut with_period, mut inferred_rows, mut bad) =
        (0, 0, 0, 0, Vec::new());
    for line in body.lines().filter(|l| !l.trim().is_empty()) {
        let case: Value = serde_json::from_str(line).expect("json line");
        let id = case["case_id"].as_str().expect("case id");
        let expected = &case["expected"];
        let verified = expected["verified"].as_object().expect("verified");
        let flights = expected.get("flights").unwrap_or(&Value::Null);
        cases += 1;
        for row in case["input"]["rows"].as_array().expect("rows") {
            let row_id = row["row_id"].as_str().expect("row id");
            let period_row = PeriodRow::from_value(row);
            // 근거는 거래 ID(행 ID에서 접두를 뗀 값, 또는 source_event_id)로 찾는다.
            let tid = row["source_event_id"]
                .as_str()
                .unwrap_or(&row_id["card-".len().min(row_id.len())..]);
            let evidence = evidence_of(expected, tid);
            let candidates = expected["facts"].get(tid).unwrap_or(&Value::Null);
            let got = verified_period_for(&period_row, candidates);
            let want = verified[row_id].as_str().expect("expected period");
            rows += 1;
            with_period += usize::from(!want.is_empty());
            if got != want {
                bad.push(format!("{id} {row_id}: got {got:?} want {want:?}"));
            }
            if let Some(found) = expected.get("found") {
                inferred_rows += 1;
                let got = found_text(&period_for(&period_row, &evidence, flights));
                if got != found[row_id] {
                    bad.push(format!("{id} {row_id}: found {got} want {}", found[row_id]));
                }
            }
        }
    }
    eprintln!(
        "period golden: {cases} cases, {rows} rows, {with_period} with a period, {inferred_rows} with found"
    );
    assert!(bad.is_empty(), "{} differ:\n{}", bad.len(), bad.join("\n"));
    assert_eq!(cases, 76);
    assert_eq!(inferred_rows, 23);
}
