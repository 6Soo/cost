//! 계획 결과가 `Judgement`로 닫히는 모양: 정상 거래는 `Decided`, 보호는 이유가 있는 `Protected`, 완료 기간은 `Preserved`.

use cost_core::domain::{Actor, Attribution, Judgement, ProtectionReason};
use cost_core::plan::{BoardRow, Keep, Outcome, PlanInput, RefundLink, Row, plan};
use serde_json::{Value, json};
use std::collections::BTreeMap;

const HASH: &str = "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef";

fn row(id: &str, changes: Value) -> Row {
    let mut row: Row = json!({
        "transaction_id": id, "source_hash": HASH, "issuer": "SYN-BANK", "card_tail": "0001",
        "card_kind": "국내", "transaction_direction": "purchase", "transaction_kind": "purchase",
        "approval_number": format!("SYN-AP-{id}"), "original_approval_number": "",
        "approval_date": "2026-10-03", "posting_date": "2026-10-05", "merchant": "gs25",
        "merchant_normalized": "gs25", "amount_krw": 15000, "foreign_amount": "", "foreign_currency": "",
        "description_raw": "", "raw_row_json": "{}", "parse_error": "", "duplicate_of": null,
        "conflict_reason": "", "classification_state": "needs_review", "classification_source": "",
        "classification_basis": "", "item": "", "description": "", "display_tab_id": "", "trip_id": "",
        "revision": 1, "decided_at": null
    })
    .as_object()
    .cloned()
    .unwrap();
    for (key, value) in changes.as_object().unwrap() {
        row.insert(key.clone(), value.clone());
    }
    row
}

fn trips() -> Vec<Value> {
    vec![
        json!({"trip_id": "T-A", "display_key": "SYN-A", "destination": "도쿄", "starts_on": "2026-10-01", "ends_on": "2026-10-05"}),
    ]
}

fn run(rows: Vec<Row>, tweak: impl FnOnce(&mut PlanInput)) -> Vec<(String, Outcome)> {
    let mut input = PlanInput {
        rows,
        trips: trips(),
        ..PlanInput::default()
    };
    tweak(&mut input);
    plan(&input, &BTreeMap::<String, RefundLink>::new())
        .unwrap()
        .outcomes
}

fn judged(outcomes: &[(String, Outcome)], id: &str) -> Judgement {
    match outcomes.iter().find(|(tid, _)| tid == id) {
        Some((_, Outcome::Judged(j))) => j.clone(),
        other => panic!("{id}: {other:?}"),
    }
}

#[test]
fn ordinary_rows_are_decided_with_an_attribution() {
    let out = run(
        vec![
            row("syn-a", json!({"merchant": "SYN HOTEL"})),
            row(
                "syn-b",
                json!({"approval_date": "2026-12-20", "posting_date": "2026-12-21"}),
            ),
        ],
        |_| {},
    );
    let Judgement::Decided(trip) = judged(&out, "syn-a") else {
        panic!("not decided")
    };
    assert!(matches!(trip.attribution(), Attribution::Trip(t) if t.as_str() == "T-A"));
    assert_eq!(trip.item().as_str(), "숙박비");
    assert!(matches!(trip.actor(), Actor::P1Inferred { .. }));
    let Judgement::Decided(quarter) = judged(&out, "syn-b") else {
        panic!("not decided")
    };
    assert_eq!(quarter.attribution().display_tab_id(), "quarter:2026:4");
}

#[test]
fn protection_has_a_reason_and_completed_periods_are_preserved() {
    let rows = vec![
        row("syn-hold", json!({})),
        row("syn-cut", json!({})),
        row("syn-dup", json!({"duplicate_of": "syn-x"})),
        row(
            "syn-old",
            json!({"approval_date": "2025-03-01", "posting_date": "2025-03-02"}),
        ),
        row(
            "syn-blank",
            json!({"approval_date": "", "posting_date": ""}),
        ),
        row(
            "syn-bad",
            json!({"approval_date": "20261003", "posting_date": ""}),
        ),
        row(
            "syn-amount",
            json!({"parse_error": "AMOUNT_UNREADABLE", "amount_krw": null}),
        ),
    ];
    let out = run(rows, |input| {
        input.holds.insert("syn-hold".into());
        input.excluded.insert("syn-cut".into());
    });
    assert!(matches!(
        judged(&out, "syn-hold"),
        Judgement::Protected(ProtectionReason::UserHold)
    ));
    assert!(matches!(
        judged(&out, "syn-cut"),
        Judgement::Protected(ProtectionReason::CompanyExcluded)
    ));
    assert!(matches!(
        judged(&out, "syn-dup"),
        Judgement::Protected(ProtectionReason::Duplicate)
    ));
    assert!(matches!(judged(&out, "syn-old"), Judgement::Preserved(_)));
    assert!(matches!(
        judged(&out, "syn-blank"),
        Judgement::Protected(ProtectionReason::DateBroken)
    ));
    assert!(matches!(
        judged(&out, "syn-bad"),
        Judgement::Protected(ProtectionReason::DateBroken)
    ));
    assert!(matches!(
        judged(&out, "syn-amount"),
        Judgement::Protected(ProtectionReason::AmountUnreadable(_))
    ));
}

#[test]
fn history_is_restored_as_a_manual_decision_and_recorded_p2_is_kept() {
    let rows = vec![
        row(
            "syn-h",
            json!({"item": "식비", "classification_state": "classified", "decided_at": "2026-10-04T00:00:00Z"}),
        ),
        row(
            "syn-ai",
            json!({"classification_source": "ai_inference", "classification_state": "classified", "item": "식비", "trip_id": "T-A", "display_tab_id": "T-A"}),
        ),
    ];
    let out = run(rows, |input| {
        input.boards.insert(
            "card-syn-h".into(),
            BoardRow {
                display_tab_id: "T-A".into(),
                payload_json: r#"{"item": "식비"}"#.into(),
                revision: 1,
            },
        );
    });
    let Judgement::Decided(restored) = judged(&out, "syn-h") else {
        panic!("not decided")
    };
    assert!(matches!(restored.actor(), Actor::Manual { .. }));
    assert_eq!(restored.attribution().display_tab_id(), "T-A");
    assert!(matches!(
        out.iter().find(|(t, _)| t == "syn-ai"),
        Some((_, Outcome::Kept(Keep::RecordedAiJudgement)))
    ));
}

#[test]
fn a_verified_refund_link_hands_the_original_to_the_cancellation() {
    let original = row(
        "syn-o",
        json!({"item": "식비", "classification_state": "classified", "classification_source": "inference", "trip_id": "T-A", "display_tab_id": "T-A"}),
    );
    let refund = row(
        "syn-r",
        json!({"transaction_direction": "cancellation", "transaction_kind": "취소", "amount_krw": -15000, "original_approval_number": "SYN-AP-syn-o"}),
    );
    let input = PlanInput {
        rows: vec![original, refund],
        trips: trips(),
        ..PlanInput::default()
    };
    let links = BTreeMap::from([(
        "syn-r".to_string(),
        RefundLink {
            original_id: "syn-o".into(),
            inferred: false,
            status: "full".into(),
        },
    )]);
    let result = plan(&input, &links).unwrap();
    let target = result
        .targets
        .iter()
        .find(|t| t.id == "syn-r")
        .expect("refund target");
    assert_eq!(target.values[1], "refund_original");
    assert_eq!(target.values[5], "T-A");
}

#[test]
fn invalid_hash_revision_and_id_are_protected_with_their_own_reason() {
    let rows = vec![
        row("syn-hash", json!({"source_hash": "not-a-hash"})),
        row("syn-upper", json!({"source_hash": HASH.to_uppercase()})),
        row("syn-rev-null", json!({"revision": null})),
        row("syn-rev-neg", json!({"revision": -1})),
        row("syn-rev-big", json!({"revision": 4_294_967_296_u64})),
    ];
    let out = run(rows, |_| {});
    for id in ["syn-hash", "syn-upper"] {
        assert!(matches!(
            judged(&out, id),
            Judgement::Protected(ProtectionReason::SourceHashInvalid)
        ));
    }
    for id in ["syn-rev-null", "syn-rev-neg", "syn-rev-big"] {
        assert!(matches!(
            judged(&out, id),
            Judgement::Protected(ProtectionReason::RevisionInvalid)
        ));
    }
}

#[test]
fn original_manual_google_row_outranks_calendar_only_during_explicit_review() {
    let mut input = PlanInput {
        rows: vec![row(
            "syn-google",
            json!({"approval_date":"2026-06-12", "posting_date":"2026-06-14",
            "classification_source":"inference", "classification_state":"classified", "item":"숙박비",
            "display_tab_id":"T-A", "trip_id":"T-A"}),
        )],
        trips: vec![
            json!({"trip_id":"T-A", "starts_on":"2026-06-12", "ends_on":"2026-06-15", "destination":"SYN OLD"}),
            json!({"trip_id":"T-B", "starts_on":"2026-06-10", "ends_on":"2026-06-11", "destination":"SYN NEW"}),
        ],
        ..PlanInput::default()
    };
    input.evidence.insert(
        "syn-google".into(),
        json!({"kind":"google_manual_expense", "source_hash":HASH,
        "trip_id":"T-B", "basis":"GOOGLE_MANUAL_ROW · SYNTHETIC!6 · original verified"}),
    );
    input.ledger.insert(
        "syn-google".into(),
        json!({"display_tab_id":"T-A", "trip_id":"T-A", "item":"숙박비"})
            .as_object()
            .unwrap()
            .clone(),
    );
    let links = BTreeMap::<String, RefundLink>::new();
    assert!(plan(&input, &links).unwrap().targets.is_empty());
    input.reconsider = true;
    let result = plan(&input, &links).unwrap();
    assert_eq!(result.targets.len(), 1);
    assert_eq!(result.targets[0].values[5], "T-B");
    assert!(result.targets[0].booking_trip_correction);
    input.overrides.insert("card-syn-google".into());
    assert!(plan(&input, &links).unwrap().targets.is_empty());
}
