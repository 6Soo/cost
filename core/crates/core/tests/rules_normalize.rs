//! `normalize_rule`의 거부·정규형을 합성 규칙 표로 확인한다. `rules_normalize_cases.jsonl`의 기대값은
//! Python `app.rules.normalize_rule` 출력이다(손으로 고치지 않는다). 그 밖에 Rust가 더 엄격한 날짜 해석과
//! 내장 규칙 표의 적재 거부를 확인한다.

use cost_core::rules::{Builtin, Rule, normalize_rule};
use serde_json::{Value, json};

#[test]
fn normalize_rule_matches_python_table() {
    let path = concat!(
        env!("CARGO_MANIFEST_DIR"),
        "/tests/rules_normalize_cases.jsonl"
    );
    let text = std::fs::read_to_string(path).unwrap();
    let (mut total, mut rejected) = (0, 0);
    for line in text.lines().filter(|l| !l.trim().is_empty()) {
        let case: Value = serde_json::from_str(line).unwrap();
        total += 1;
        let note = case["note"].as_str().unwrap();
        match normalize_rule(&case["draft"]) {
            Ok(rule) => {
                assert!(
                    case.get("error").is_none(),
                    "{note}: Python rejected, Rust accepted"
                );
                assert_eq!(rule.to_value(), case["expected"], "{note}");
            }
            Err(error) => {
                rejected += 1;
                assert_eq!(error.code, case["error"]["code"], "{note}");
                assert_eq!(error.message, case["error"]["message"], "{note}");
            }
        }
    }
    assert!(
        total >= 50 && rejected >= 30,
        "table shrank: {total}/{rejected}"
    );
}

#[test]
fn period_dates_must_be_iso() {
    // Python은 `2026/10/01`도 날짜로 읽지만 Rust는 `YYYY-MM-DD`만 받는다.
    for bad in ["2026/10/01", "20261001", "2026-10-01T00:00", " 2026-10-01"] {
        let draft = json!({
            "conditions": {"merchant_normalized": "a"},
            "optional": {"date_or_service_period": {"start": bad}},
            "effects": {"item": "x"},
        });
        let error = normalize_rule(&draft).unwrap_err();
        assert_eq!(error.message, "기간 start 날짜를 읽을 수 없어요", "{bad}");
    }
}

#[test]
fn stored_rule_loads_without_validation() {
    let rule = Rule::from_value(&json!({
        "rule_id": "r1", "version": 2,
        "conditions": {"merchant_normalized": "a"}, "effects": {"item": "x"}, "optional": {},
    }));
    assert_eq!((rule.rule_id.as_str(), rule.version), ("r1", 2));
}

#[test]
fn embedded_builtin_table_loads() {
    let builtin = Builtin::embedded().unwrap();
    assert_eq!(builtin.rules().count(), 31);
    assert_eq!(builtin.provider_for("어드벤처코리아"), Some("skyticket"));
    assert_eq!(builtin.provider_for("none such"), None);
}

fn rule_json(extra: Value) -> String {
    let mut rule = json!({
        "rule_id": "P1-X", "version": 1, "kind": "merchant_pattern", "strength": "inferred", "stage": 40,
        "policy_refs": [], "conditions": {"merchant": {"equals_or_prefix": "x"}}, "scope": {},
        "effects": {"item": "i"}, "attribution": "none", "origin": "test", "basis": "b",
    });
    rule.as_object_mut()
        .unwrap()
        .extend(extra.as_object().unwrap().clone());
    json!([rule]).to_string()
}

#[test]
fn builtin_load_rejects_malformed_tables() {
    let aliases = "[]";
    assert!(Builtin::load(&[&rule_json(json!({}))], aliases).is_ok());
    for (what, extra) in [
        ("stage mismatch", json!({"stage": 30})),
        (
            "unported kind",
            json!({"kind": "owner_exception", "stage": 60}),
        ),
        ("unknown field", json!({"surprise": 1})),
        ("bad policy ref", json!({"policy_refs": ["item-1"]})),
        ("blank item", json!({"effects": {"item": " "}})),
        (
            "bad regex",
            json!({"conditions": {"merchant": {"compact_regex": "("}}}),
        ),
        (
            "two matchers",
            json!({"conditions": {"merchant": {"equals_or_prefix": "x", "compact_regex": "y"}}}),
        ),
        (
            "wrong condition for kind",
            json!({"conditions": {"provider": "p"}}),
        ),
    ] {
        assert!(
            Builtin::load(&[&rule_json(extra)], aliases).is_err(),
            "{what} was accepted"
        );
    }
    let one = rule_json(json!({}));
    assert!(
        Builtin::load(&[&one, &one], aliases).is_err(),
        "duplicate id was accepted"
    );
}
