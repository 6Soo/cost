//! OTA 후보·쌍 검사(U13)를 Python 출력과 비교한다.
//! 1) `ota_candidates.jsonl`: 후보 카드·`pair_check` 코드·`search_card_candidates` 결과가 Python 직접 호출과 같은가.
//! 2) `ota_links.jsonl`: 후보 단계만으로 결정되는 사례의 최종 상태·사유·후보가 같은가. M:N·점유·정확 연결 우선 배정이
//!    필요한 사례는 U14로 넘기고 개수만 센다.
//! 3) 보호 불변식(속성 테스트): 점유된 카드는 후보가 되지 않고, 방향·끝 4자리·통화가 다른 행은 후보가 될 수 없다.

use cost_core::links::ota::{Defaults, Matcher, Search, Stage};
use proptest::prelude::*;
use serde_json::{Map, Value, json};

fn read_lines(name: &str) -> Vec<Value> {
    let path = format!(
        "{}/../../golden/synthetic/{name}",
        env!("CARGO_MANIFEST_DIR")
    );
    std::fs::read_to_string(path)
        .expect("golden file")
        .lines()
        .map(|l| serde_json::from_str(l).expect("json line"))
        .collect()
}

fn defaults() -> Defaults {
    let path = format!(
        "{}/../../../config/ota-matching-defaults.json",
        env!("CARGO_MANIFEST_DIR")
    );
    let value: Value = serde_json::from_str(&std::fs::read_to_string(path).unwrap()).unwrap();
    Defaults::from_value(&value).expect("defaults")
}

fn array(v: &Value, key: &str) -> Vec<Value> {
    v.get(key)
        .and_then(Value::as_array)
        .cloned()
        .unwrap_or_default()
}

fn links(input: &Value) -> Map<String, Value> {
    input
        .get("existing_links")
        .and_then(Value::as_object)
        .cloned()
        .unwrap_or_default()
}

fn id(row: &Value) -> Value {
    row.get("transaction_id").cloned().unwrap_or(Value::Null)
}

#[test]
fn candidates_match_python() {
    let defaults = defaults();
    let (mut checked, mut bad) = (0, Vec::new());
    for case in read_lines("ota_candidates.jsonl") {
        let input = &case["input"];
        let (events, cards, rules) = (
            array(input, "events"),
            array(input, "transactions"),
            array(input, "rules"),
        );
        let existing = links(input);
        let matcher = Matcher::new(&defaults, &rules);
        let expected = case["expected"]["events"].as_array().expect("events");
        for (event, want) in events.iter().zip(expected) {
            checked += 1;
            let eligible: Vec<Value> = matcher
                .eligible_cards(event, &cards)
                .into_iter()
                .map(|i| id(&cards[i]))
                .collect();
            let pairs: Map<String, Value> = cards
                .iter()
                .map(|row| {
                    let code = matcher
                        .pair_check(event, row)
                        .map_or(Value::Null, |c| json!(c));
                    (id(row).as_str().unwrap().to_string(), code)
                })
                .collect();
            let search = match matcher.search_card_candidates(
                event,
                &cards,
                &existing,
                cost_core::links::ota::DEFAULT_MAX_COMPARISONS,
            ) {
                Search::Done(r) => serde_json::to_value(r).unwrap(),
                Search::Delegated(name) => json!({ "delegated": name }),
            };
            let got = json!({
                "ota_event_id": event.get("ota_event_id").cloned().unwrap_or(Value::Null),
                "eligible": eligible,
                "pair_check": pairs,
                "search": search,
            });
            if &got != want {
                bad.push(format!(
                    "{}\n  rust:   {got}\n  python: {want}",
                    case["case_id"]
                ));
            }
        }
    }
    eprintln!(
        "ota candidates golden: {} of {checked} events match",
        checked - bad.len()
    );
    assert!(bad.is_empty(), "{}", bad.join("\n"));
}

/// 후보 단계 결과가 Python 최종 결과 한 줄과 같은가. `None`이면 후보 단계만으로는 결정되지 않는다(U14).
fn stage_matches(stage: &Stage, event: &Value, result: &Value) -> Option<Result<(), String>> {
    let compare = |what: &str, got: Value, want: &Value| {
        (&got != want).then(|| format!("{what}: rust {got} python {want}"))
    };
    let diffs: Vec<String> = match stage {
        Stage::Pinned => return None,
        Stage::Hold(h) => [
            compare("status", json!(h.status), &result["status"]),
            compare("reason", json!(h.reason), &result["reason"]),
            compare("candidates", json!(h.candidates), &result["candidates"]),
        ]
        .into_iter()
        .flatten()
        .collect(),
        Stage::Options { ids, unique } => {
            let (Some(unique), [only]) = (unique, ids.as_slice()) else {
                return None;
            };
            [
                compare("status", json!("MATCHED_AUTO"), &result["status"]),
                compare("transaction_id", only.clone(), &result["transaction_id"]),
                compare("candidates", json!([only]), &result["candidates"]),
                compare("reason", json!(unique.reason), &result["reason"]),
                compare(
                    "rule_delta_krw",
                    json!(unique.rule_delta_krw),
                    &result["rule_delta_krw"],
                ),
                compare(
                    "discount_cause_confirmed",
                    json!(unique.discount_cause_confirmed),
                    &result["discount_cause_confirmed"],
                ),
                compare(
                    "payment_date_verified",
                    json!(event.get("paid_on").is_some_and(|v| !v.is_null())),
                    &result["payment_date_verified"],
                ),
            ]
            .into_iter()
            .flatten()
            .collect()
        }
    };
    Some(if diffs.is_empty() {
        Ok(())
    } else {
        Err(diffs.join("; "))
    })
}

#[test]
fn candidate_stage_decides_ota_links_cases_like_python() {
    let defaults = defaults();
    let (mut decided, mut handed_to_u14, mut bad) = (0, Vec::new(), Vec::new());
    for case in read_lines("ota_links.jsonl") {
        let input = &case["input"];
        let (events, cards, rules) = (
            array(input, "events"),
            array(input, "transactions"),
            array(input, "rules"),
        );
        let existing = links(input);
        let matcher = Matcher::new(&defaults, &rules);
        let results = case["expected"]["results"].as_array().expect("results");
        let stages: Vec<Stage> = events
            .iter()
            .map(|e| matcher.candidate_stage(e, &cards, &existing))
            .collect();
        // 한 카드가 두 이벤트의 후보이거나 기존 연결이 있으면 배정(U14)이 필요하다.
        let mut seen: Vec<&Value> = Vec::new();
        let shared = stages.iter().any(|s| match s {
            Stage::Options { ids, .. } => ids.iter().any(|i| {
                let dup = seen.contains(&i);
                seen.push(i);
                dup
            }),
            _ => false,
        });
        let outcomes: Vec<_> = events
            .iter()
            .zip(&stages)
            .map(|(event, stage)| {
                let result = results
                    .iter()
                    .find(|r| r["ota_event_id"] == event["ota_event_id"])
                    .expect("result");
                if shared {
                    None
                } else {
                    stage_matches(stage, event, result)
                }
            })
            .collect();
        if outcomes.iter().any(Option::is_none) {
            handed_to_u14.push(case["case_id"].as_str().unwrap().to_string());
            continue;
        }
        decided += 1;
        for outcome in outcomes.into_iter().flatten() {
            if let Err(e) = outcome {
                bad.push(format!("{}: {e}", case["case_id"]));
            }
        }
    }
    eprintln!(
        "ota_links: {decided} decided by the candidate stage and matching, {} handed to U14: {handed_to_u14:?}",
        handed_to_u14.len()
    );
    assert!(bad.is_empty(), "{}", bad.join("\n"));
    assert_eq!(decided + handed_to_u14.len(), 55);
    // U14로 넘기는 사례는 M:N 묶음·점유·정확 연결 우선 배정·기존 연결이 필요한 것만이다.
    assert_eq!(
        decided, 29,
        "후보 단계로 결정되는 사례 수가 바뀌었다: {handed_to_u14:?}"
    );
}

fn cell(v: &Value, key: &str) -> String {
    v.get(key).and_then(Value::as_str).unwrap_or("").to_string()
}

fn event_strategy() -> impl Strategy<Value = Value> {
    (
        prop_oneof![Just("charge"), Just("refund")],
        prop_oneof![Just(Some("2026-09-04")), Just(Some("2026-09-05")), Just(None)],
        prop_oneof![Just("KRW"), Just("JPY")],
        prop_oneof![Just(Some("2042")), Just(Some("9999")), Just(None)],
        prop_oneof![Just("trip"), Just("agoda"), Just("booking")],
    )
        .prop_map(|(kind, paid_on, currency, last4, provider)| {
            let refund = kind == "refund";
            json!({
                "ota_event_id": "syn-e1", "provider": provider, "event_type": kind, "currency": currency,
                "paid_on": paid_on, "card_last4": last4, "amount": "30000",
                "amount_krw": if currency == "KRW" { json!(30000) } else { Value::Null },
                "evidence_status": if refund { "refund_verified" } else { "paid_verified" },
                "refund_status": if refund { json!("refunded") } else { Value::Null },
                "payment_status": "paid",
            })
        })
}

fn card_strategy(n: usize) -> impl Strategy<Value = Value> {
    (
        prop_oneof![Just("purchase"), Just("refund"), Just("cancellation")],
        prop_oneof![Just("2026-09-04"), Just("2026-09-05"), Just("2026-10-04")],
        prop_oneof![Just("2042"), Just("9999")],
        prop_oneof![Just(30000), Just(-30000), Just(31000)],
        prop_oneof![Just(""), Just("JPY"), Just("USD")],
        prop_oneof![Just("trip.com"), Just("agoda"), Just("booking.com"), Just("syn other")],
    )
        .prop_map(move |(direction, day, tail, amount, foreign, merchant)| {
            json!({
                "transaction_id": format!("syn-t{n}"), "transaction_direction": direction, "approval_date": day,
                "card_tail": tail, "amount_krw": amount, "foreign_currency": foreign,
                "foreign_amount": if foreign.is_empty() { json!("") } else { json!("30000") },
                "merchant": merchant, "merchant_normalized": merchant, "issuer": "SYN-BANK",
            })
        })
}

proptest! {
    #![proptest_config(ProptestConfig::with_cases(300))]

    #[test]
    fn candidates_respect_direction_tail_currency_and_occupancy(
        event in event_strategy(),
        cards in prop::collection::vec(0usize..1, 1..6).prop_flat_map(|v| {
            (0..v.len()).map(card_strategy).collect::<Vec<_>>()
        }),
        claim in prop::option::of(0usize..5),
    ) {
        let defaults = defaults();
        let matcher = Matcher::new(&defaults, &[]);
        let (event_before, cards_before) = (event.clone(), cards.clone());
        let want = if cell(&event, "event_type") == "refund" { "refund" } else { "purchase" };
        for i in matcher.eligible_cards(&event, &cards) {
            let row = &cards[i];
            prop_assert_eq!(cell(row, "transaction_direction"), want);
            let last4 = cell(&event, "card_last4");
            prop_assert!(last4.is_empty() || cell(row, "card_tail").ends_with(&last4));
            let currency = cell(&event, "currency");
            if currency != "KRW" {
                prop_assert_eq!(cell(row, "foreign_currency"), currency);
            }
        }
        let mut existing = Map::new();
        if let Some(i) = claim.filter(|i| *i < cards.len()) {
            existing.insert("syn-e9".into(), json!({"transaction_id": cards[i]["transaction_id"], "status": "MATCHED_AUTO"}));
        }
        let claimed: Vec<Value> = existing.values().map(|l| l["transaction_id"].clone()).collect();
        if let Stage::Options { ids, .. } = matcher.candidate_stage(&event, &cards, &existing) {
            prop_assert!(ids.iter().all(|i| !claimed.contains(i)));
        }
        prop_assert_eq!(event, event_before);
        prop_assert_eq!(cards, cards_before);
    }
}

#[test]
fn provider_specific_reservation_search_is_delegated() {
    let defaults = defaults();
    let matcher = Matcher::new(&defaults, &[]);
    for provider in ["forest", "toyoko", "rakuten"] {
        let event =
            json!({"ota_event_id": "syn-e1", "provider": provider, "event_type": "reservation"});
        assert_eq!(
            matcher.search_card_candidates(&event, &[], &Map::new(), 10),
            Search::Delegated(match provider {
                "forest" => "forest",
                "toyoko" => "toyoko",
                _ => "rakuten",
            })
        );
    }
}
