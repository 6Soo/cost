//! `core/golden/synthetic/plan.jsonl`(Python `automatic_classification.plan` 출력)과 `cost_core::plan::plan`을 비교한다.
//! 시나리오(행·이력·보류·제외·수동 교정·장부·화면 행)는 `tools/core_bridge/synthetic.py`가 DB에 넣는 값과 같은 기본값으로 읽는다.

use cost_core::plan::{BoardRow, Outcome, PlanInput, RefundLink, Row, plan, python_json};
use serde_json::{Map, Value, json};
use std::collections::{BTreeMap, BTreeSet};

// 알려진 차이는 `core/known-diffs.txt`(그림자 실행과 같은 파일)의 `plan-` 줄이다.
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

fn defaults(index: usize, spec: &Value) -> Row {
    let mut row: Row = [
        ("source_hash", json!("")),
        ("issuer", json!("SYN-BANK")),
        ("card_tail", json!("0001")),
        ("card_kind", json!("credit")),
        ("transaction_direction", json!("purchase")),
        ("transaction_kind", json!("승인")),
        ("approval_number", json!("")),
        ("original_approval_number", json!("")),
        ("approval_date", json!("")),
        ("posting_date", json!("")),
        ("merchant", json!("")),
        ("merchant_normalized", json!("")),
        ("amount_krw", Value::Null),
        ("foreign_amount", json!("")),
        ("foreign_currency", json!("")),
        ("description_raw", json!("")),
        ("raw_row_json", json!("{}")),
        ("duplicate_of", Value::Null),
        ("conflict_reason", json!("")),
        ("parse_error", json!("")),
        ("classification_state", json!("needs_review")),
        ("classification_source", json!("")),
        ("classification_basis", json!("")),
        ("item", json!("")),
        ("description", json!("")),
        ("display_tab_id", json!("")),
        ("trip_id", json!("")),
        ("revision", json!(1)),
        ("decided_at", Value::Null),
    ]
    .into_iter()
    .map(|(k, v)| (k.to_string(), v))
    .collect();
    for (key, value) in spec.as_object().expect("row spec") {
        row.insert(key.clone(), value.clone());
    }
    let id = row["transaction_id"].as_str().expect("id").to_string();
    if row["source_hash"] == json!("") {
        row.insert("source_hash".into(), json!(format!("syn-hash-{id}")));
    }
    if row["merchant_normalized"] == json!("") {
        let merchant = row["merchant"].as_str().unwrap_or_default().to_lowercase();
        row.insert("merchant_normalized".into(), json!(merchant));
    }
    let _ = index;
    row
}

fn strings(v: &Value) -> BTreeSet<String> {
    v.as_array()
        .map(|a| {
            a.iter()
                .filter_map(|s| s.as_str().map(str::to_string))
                .collect()
        })
        .unwrap_or_default()
}

fn ids(items: &Value) -> BTreeSet<String> {
    items
        .as_array()
        .map(|a| {
            a.iter()
                .filter_map(|h| h["transaction_id"].as_str().map(str::to_string))
                .collect()
        })
        .unwrap_or_default()
}

fn scenario_input(input: &Value) -> (PlanInput, BTreeMap<String, RefundLink>) {
    let scenario = &input["scenario"];
    let rows: Vec<Row> = scenario["rows"]
        .as_array()
        .expect("rows")
        .iter()
        .enumerate()
        .map(|(i, spec)| defaults(i, spec))
        .collect();
    let text = |v: &Value, key: &str| {
        v.get(key)
            .and_then(Value::as_str)
            .unwrap_or_default()
            .to_string()
    };
    let decisions = scenario["decisions"]
        .as_array()
        .map(|a| {
            a.iter()
                .map(|d| (text(d, "transaction_id"), text(d, "display_tab_id")))
                .collect()
        })
        .unwrap_or_default();
    let ledger = scenario["ledger"]
        .as_array()
        .map(|a| {
            a.iter()
                .map(|e| {
                    let mut entry = Map::new();
                    for key in ["item", "description", "display_tab_id", "trip_id"] {
                        entry.insert(key.to_string(), json!(text(e, key)));
                    }
                    (text(e, "transaction_id"), entry)
                })
                .collect()
        })
        .unwrap_or_default();
    let boards = scenario["boards"]
        .as_array()
        .map(|a| {
            a.iter()
                .map(|b| {
                    let row = BoardRow {
                        display_tab_id: text(b, "display_tab_id"),
                        payload_json: python_json(&b["payload"]),
                        revision: 1,
                    };
                    (format!("card-{}", text(b, "transaction_id")), row)
                })
                .collect()
        })
        .unwrap_or_default();
    let mut allowed: BTreeSet<String> = BTreeSet::new();
    for row in &rows {
        allowed.insert(row["item"].as_str().unwrap_or_default().to_string());
    }
    let links = input
        .get("links")
        .and_then(Value::as_object)
        .map(|m| {
            m.iter()
                .map(|(tid, link)| {
                    let link = RefundLink {
                        original_id: text(link, "original_id"),
                        inferred: link["inferred"].as_bool().unwrap_or(false),
                        status: text(link, "link_state"),
                    };
                    (tid.clone(), link)
                })
                .collect()
        })
        .unwrap_or_default();
    let built = PlanInput {
        rows,
        trips: input["trips"].as_array().cloned().unwrap_or_default(),
        nets: input
            .get("nets")
            .and_then(Value::as_object)
            .map(|m| {
                m.iter()
                    .filter_map(|(k, v)| Some((k.clone(), v.as_i64()?)))
                    .collect()
            })
            .unwrap_or_default(),
        selected: input.get("transaction_ids").map(strings),
        reconsider: input["reconsider"].as_bool().unwrap_or(false),
        evidence: input
            .get("evidence")
            .and_then(Value::as_object)
            .map(|m| m.iter().map(|(k, v)| (k.clone(), v.clone())).collect())
            .unwrap_or_default(),
        decisions,
        holds: ids(&scenario["holds"]),
        excluded: ids(&scenario["exclusions"]),
        overrides: strings(&scenario["overrides"])
            .into_iter()
            .map(|t| format!("card-{t}"))
            .collect(),
        ledger,
        boards,
        closed_reviews: BTreeSet::new(),
        allowed_items: allowed.into_iter().collect(),
    };
    (built, links)
}

#[test]
fn golden_plan_matches_python() {
    let path = concat!(
        env!("CARGO_MANIFEST_DIR"),
        "/../../golden/synthetic/plan.jsonl"
    );
    let body = std::fs::read_to_string(path).expect("golden file");
    let known_ids = known_cases("plan-");
    let (mut total, mut matched, mut known) = (0, 0, 0);
    let mut bad = Vec::new();
    for line in body.lines().filter(|l| !l.trim().is_empty()) {
        let case: Value = serde_json::from_str(line).expect("json line");
        let id = case["case_id"].as_str().expect("case id").to_string();
        let (input, links) = scenario_input(&case["input"]);
        let result = plan(&input, &links).expect("plan");
        total += 1;
        let same = result.to_value() == case["expected"];
        if known_ids.contains(&id) {
            assert!(!same, "{id} no longer differs: remove from known-diffs.txt");
            known += 1;
        } else if same {
            matched += 1;
        } else {
            bad.push(format!(
                "{id} ({}):\n  got  {}\n  want {}",
                case["note"],
                result.to_value(),
                case["expected"]
            ));
        }
        // 대기 상태가 없다: 바뀌는 거래는 모두 Judgement로 끝난다.
        for target in &result.targets {
            let outcome = result
                .outcomes
                .iter()
                .find(|(tid, _)| tid == &target.id)
                .map(|(_, o)| o);
            assert!(
                matches!(outcome, Some(Outcome::Judged(_))),
                "{id}: {}",
                target.id
            );
        }
    }
    eprintln!("plan golden: {matched} of {total} match, {known} known diffs");
    assert!(bad.is_empty(), "{} differ:\n{}", bad.len(), bad.join("\n"));
    assert_eq!(
        known,
        known_ids.len(),
        "known-diffs.txt lists a plan- case that is not in the golden file"
    );
    assert_eq!(total, 107);
}
