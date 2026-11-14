//! 이용기간 규칙·근거 digest·재판정 선택·판정 저장(설계 §2.7). 합성 값만 쓴다.

use cost_core::domain::{Judgement, ServicePeriod, UnknownPeriodReason};
use cost_core::period::{
    PERIOD_FN_VERSION, PeriodEvidence, PeriodRow, changed_since, current_digests, evidence_digest,
    service_period, verified_period_for,
};
use cost_core::plan::{BoardRow, Outcome, PlanInput, RefundLink, Row, plan_with_periods};
use cost_core::store::decisions::{
    save_decision, stored_digests, stored_digests_readonly, stored_period,
};
use cost_core::store::open_core;
use serde_json::{Value, json};
use std::collections::BTreeMap;
use std::path::PathBuf;

const HASH: &str = "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef";

fn fact(changes: Value) -> Value {
    let mut fact = json!({
        "transaction_id": "syn-t1", "item": "숙박비", "source_hash": "syn-hash", "reservation_status": "confirmed",
        "booking_ref": "SYN-BOOK-1", "period": {"starts_on": "2026-10-01", "ends_on": "2026-10-03"},
        "source_digests": ["syn-e1"], "source_sha256": "syn-e1", "inferred_link": false,
    });
    for (k, v) in changes.as_object().unwrap() {
        fact[k] = v.clone();
    }
    fact
}

fn candidate(fact: Value) -> Value {
    json!([{
        "fact": fact, "matches": [fact],
        "event": {"event_type": "charge", "evidence_status": "paid_verified", "payment_status": "paid", "source_digest": "syn-e1"},
        "card": {"source_hash": "syn-hash", "transaction_direction": "purchase"},
        "event_blocked": false, "manual": false,
    }])
}

fn row(reservation_no: &str) -> PeriodRow {
    PeriodRow::from_value(
        &json!({"row_id": "card-syn-t1", "service_period": "", "reservation_no": reservation_no}),
    )
}

#[test]
fn group_and_shared_facts_hide_the_booking_number_but_keep_the_period() {
    let group = candidate(fact(json!({"booking_ref": "", "group_size": 2})));
    assert_eq!(
        verified_period_for(&row(""), &group),
        "2026-10-01~2026-10-03"
    );
    // 예약번호가 비어 있는 묶음에 번호가 적힌 행은 그 번호를 확인할 수 없다.
    assert_eq!(verified_period_for(&row("SYN-BOOK-1"), &group), "");
    // 번호도 묶음 표시도 공통 기간 근거도 없으면 근거가 아니다.
    let none = candidate(fact(json!({"booking_ref": ""})));
    assert_eq!(verified_period_for(&row(""), &none), "");
    let shared = candidate(fact(
        json!({"booking_ref": "", "service_period_basis": "LINK-108"}),
    ));
    assert_eq!(
        verified_period_for(&row(""), &shared),
        "2026-10-01~2026-10-03"
    );
}

#[test]
fn a_period_missing_one_date_never_yields_a_period() {
    let half = candidate(fact(json!({"period": {"starts_on": "2026-10-01"}})));
    assert_eq!(verified_period_for(&row(""), &half), "");
    assert_eq!(verified_period_for(&row(""), &Value::Null), "");
}

#[test]
fn service_period_text_becomes_a_typed_period_or_a_reasoned_unknown() {
    assert!(matches!(
        service_period("2026-10-01~2026-10-03", "숙박비"),
        ServicePeriod::Known { .. }
    ));
    assert_eq!(
        service_period("", "숙박비"),
        ServicePeriod::unknown(UnknownPeriodReason::NoEvidence)
    );
    assert_eq!(
        service_period("", "식비"),
        ServicePeriod::unknown(UnknownPeriodReason::NotApplicable)
    );
    for bad in [
        "2026-10-03~2026-10-01",
        "2026-10-01",
        "x~y",
        "2026-13-01~2026-13-02",
    ] {
        assert_eq!(
            service_period(bad, "숙박비"),
            ServicePeriod::unknown(UnknownPeriodReason::EvidenceAmbiguous),
            "{bad}"
        );
    }
}

#[test]
fn digest_follows_only_what_the_rule_reads() {
    let base = candidate(fact(json!({})));
    let digest = evidence_digest(&row(""), &base);
    // 규칙이 읽지 않는 칸(가맹점 등)이 바뀌어도 같다.
    let mut other = base.clone();
    other[0]["fact"]["merchant"] = json!("SYN OTHER");
    other[0]["matches"][0]["merchant"] = json!("SYN OTHER");
    other[0]["event"]["note"] = json!("x");
    assert_eq!(digest, evidence_digest(&row(""), &other));
    // 예약 사실·연결·저장 값이 바뀌면 달라진다.
    let moved = candidate(fact(
        json!({"period": {"starts_on": "2026-10-02", "ends_on": "2026-10-03"}}),
    ));
    assert_ne!(digest, evidence_digest(&row(""), &moved));
    let cancelled = candidate(fact(json!({"reservation_status": "cancelled"})));
    assert_ne!(digest, evidence_digest(&row(""), &cancelled));
    assert_ne!(digest, evidence_digest(&row("SYN-BOOK-1"), &base));
    assert_ne!(digest, evidence_digest(&row(""), &Value::Null));
    let mut stored = row("");
    stored.service_period = "2026-09-01~2026-09-02".into();
    assert_ne!(digest, evidence_digest(&stored, &base));
}

#[test]
fn changed_since_picks_new_and_differing_transactions_only() {
    let map = |pairs: &[(&str, &str)]| -> BTreeMap<String, String> {
        pairs
            .iter()
            .map(|(k, v)| ((*k).to_owned(), (*v).to_owned()))
            .collect()
    };
    let stored = map(&[("a", "1"), ("b", "2"), ("gone", "9")]);
    let current = map(&[("a", "1"), ("b", "3"), ("c", "4")]);
    assert_eq!(changed_since(&stored, &current), vec!["b", "c"]);
    assert!(changed_since(&current, &current).is_empty());
}

fn base_row(id: &str, changes: Value) -> Row {
    let mut row: Row = json!({
        "transaction_id": id, "source_hash": HASH, "issuer": "SYN-BANK", "card_tail": "0001",
        "card_kind": "국내", "transaction_direction": "purchase", "transaction_kind": "purchase",
        "approval_number": format!("SYN-AP-{id}"), "original_approval_number": "",
        "approval_date": "2026-10-03", "posting_date": "2026-10-05", "merchant": "SYN HOTEL",
        "merchant_normalized": "syn hotel", "amount_krw": 15000, "foreign_amount": "", "foreign_currency": "",
        "description_raw": "", "raw_row_json": "{}", "parse_error": "", "duplicate_of": null,
        "conflict_reason": "", "classification_state": "needs_review", "classification_source": "",
        "classification_basis": "", "item": "", "description": "", "display_tab_id": "", "trip_id": "",
        "revision": 1, "decided_at": null
    })
    .as_object()
    .cloned()
    .unwrap();
    for (k, v) in changes.as_object().unwrap() {
        row.insert(k.clone(), v.clone());
    }
    row
}

fn input(rows: Vec<Row>) -> PlanInput {
    PlanInput {
        rows,
        trips: vec![
            json!({"trip_id": "T-A", "display_key": "SYN-A", "destination": "도쿄", "starts_on": "2026-10-01", "ends_on": "2026-10-05"}),
        ],
        ..PlanInput::default()
    }
}

fn evidence(facts: &BTreeMap<String, Value>, changed: &[&str]) -> PeriodEvidence {
    PeriodEvidence {
        facts: facts.clone(),
        changed: changed.iter().map(|t| (*t).to_owned()).collect(),
    }
}

fn digests_for(input: &PlanInput, facts: &BTreeMap<String, Value>) -> BTreeMap<String, String> {
    let cards = input
        .rows
        .iter()
        .filter_map(|r| r["transaction_id"].as_str())
        .map(|tid| {
            let board = input.boards.get(&format!("card-{tid}"));
            (tid, board.map(|b| b.payload_json.as_str()))
        });
    current_digests(cards, facts)
}

fn decided(
    input: &PlanInput,
    periods: &BTreeMap<String, Value>,
    id: &str,
) -> cost_core::domain::Decision {
    let result = plan_with_periods(
        input,
        &BTreeMap::<String, RefundLink>::new(),
        &evidence(periods, &[]),
    )
    .unwrap();
    match result.outcomes.into_iter().find(|(t, _)| t == id) {
        Some((_, Outcome::Judged(Judgement::Decided(d)))) => d,
        other => panic!("{other:?}"),
    }
}

#[test]
fn the_decision_carries_the_verified_period_or_a_reasoned_unknown() {
    let hotel = input(vec![
        base_row("syn-t1", json!({})),
        base_row(
            "syn-t2",
            json!({"merchant": "gs25", "merchant_normalized": "gs25"}),
        ),
    ]);
    let facts = BTreeMap::from([("syn-t1".to_owned(), candidate(fact(json!({}))))]);
    let with = decided(&hotel, &facts, "syn-t1");
    assert!(matches!(
        with.service_period(),
        ServicePeriod::Known { starts_on, ends_on }
            if starts_on.to_string() == "2026-10-01" && ends_on.to_string() == "2026-10-03"
    ));
    let without = decided(&hotel, &BTreeMap::new(), "syn-t1");
    assert_eq!(
        *without.service_period(),
        ServicePeriod::unknown(UnknownPeriodReason::NoEvidence)
    );
    let shop = decided(&hotel, &BTreeMap::new(), "syn-t2");
    assert_eq!(
        *shop.service_period(),
        ServicePeriod::unknown(UnknownPeriodReason::NotApplicable)
    );
    // 화면에 저장된 이용기간이 근거보다 먼저다.
    let mut stored = hotel.clone();
    stored.boards.insert(
        "card-syn-t1".into(),
        BoardRow {
            display_tab_id: String::new(),
            payload_json: r#"{"service_period": "2026-09-01~2026-09-02"}"#.into(),
            revision: 1,
        },
    );
    let d = decided(&stored, &facts, "syn-t1");
    assert!(matches!(
        d.service_period(),
        ServicePeriod::Known { starts_on, .. } if starts_on.to_string() == "2026-09-01"
    ));
}

struct Scratch(PathBuf);

impl Scratch {
    fn new(name: &str) -> Self {
        let dir =
            std::env::temp_dir().join(format!("costcore-period-{}-{name}", std::process::id()));
        std::fs::create_dir_all(&dir).unwrap();
        Self(dir)
    }
}

impl Drop for Scratch {
    fn drop(&mut self) {
        let _ = std::fs::remove_dir_all(&self.0);
    }
}

#[test]
fn only_a_changed_basis_selects_a_stored_transaction_for_rejudging() {
    let dir = Scratch::new("store");
    let path = dir.0.join("core.sqlite");
    let conn = open_core(&path).unwrap();
    let hotel = input(vec![base_row("syn-t1", json!({}))]);
    let facts = BTreeMap::from([("syn-t1".to_owned(), candidate(fact(json!({}))))]);
    let decision = decided(&hotel, &facts, "syn-t1");
    let digests = digests_for(&hotel, &facts);
    save_decision(
        &conn,
        "main",
        &decision,
        "inference",
        &digests["syn-t1"],
        1,
        "2026-11-14T00:00:00Z",
        "",
    )
    .unwrap();

    let stored = stored_digests(&conn).unwrap();
    assert!(
        changed_since(&stored, &digests).is_empty(),
        "같은 근거는 다시 고르지 않는다"
    );
    let period: Value =
        serde_json::from_str(&stored_period(&conn, "syn-t1").unwrap().unwrap()).unwrap();
    assert_eq!(period["starts_on"], "2026-10-01");
    assert_eq!(period["kind"], "known", "저장 표기는 kind를 가진다");
    assert_eq!(stored_period(&conn, "syn-none").unwrap(), None);

    // 예약 사실이 바뀐 거래만 고른다.
    let moved = BTreeMap::from([(
        "syn-t1".to_owned(),
        candidate(fact(
            json!({"period": {"starts_on": "2026-10-02", "ends_on": "2026-10-03"}}),
        )),
    )]);
    assert_eq!(
        changed_since(&stored, &digests_for(&hotel, &moved)),
        vec!["syn-t1"]
    );

    // 판정 함수 버전이 다르게 저장된 거래는 근거가 같아도 다시 고른다.
    conn.execute(
        "UPDATE decisions SET period_fn_version = ?1",
        [PERIOD_FN_VERSION + 1],
    )
    .unwrap();
    let stale = stored_digests(&conn).unwrap();
    assert_eq!(changed_since(&stale, &digests), vec!["syn-t1"]);
    conn.execute(
        "UPDATE decisions SET period_fn_version = ?1",
        [PERIOD_FN_VERSION],
    )
    .unwrap();

    // 다시 저장하면 이전 값이 이력에 남고 판정은 한 줄이다.
    let moved_digest = &digests_for(&hotel, &moved)["syn-t1"];
    let moved_decision = decided(&hotel, &moved, "syn-t1");
    save_decision(
        &conn,
        "main",
        &moved_decision,
        "inference",
        moved_digest,
        1,
        "2026-11-15T00:00:00Z",
        "req-1",
    )
    .unwrap();
    let rows: i64 = conn
        .query_row("SELECT count(*) FROM decisions", [], |r| r.get(0))
        .unwrap();
    let history: i64 = conn
        .query_row(
            "SELECT count(*) FROM decision_history WHERE transaction_id='syn-t1'",
            [],
            |r| r.get(0),
        )
        .unwrap();
    assert_eq!((rows, history), (1, 1));
    // 같은 레코드를 다시 저장하면 쓰지 않는다. 이용기간은 같고 근거 digest만 달라져도 digest를 갱신한다.
    let again = |digest: &str| {
        save_decision(
            &conn,
            "main",
            &moved_decision,
            "inference",
            digest,
            1,
            "2026-11-16T00:00:00Z",
            "req-2",
        )
        .unwrap()
    };
    assert!(!again(moved_digest));
    assert!(again("digest-only-change"));
    assert_eq!(
        stored_digests(&conn).unwrap()["syn-t1"],
        "digest-only-change"
    );
    let request_ids: Vec<String> = conn
        .prepare("SELECT request_id FROM decision_history WHERE transaction_id='syn-t1' ORDER BY history_id")
        .unwrap()
        .query_map([], |r| r.get(0))
        .unwrap()
        .map(Result::unwrap)
        .collect();
    assert_eq!(request_ids, ["req-1", "req-2"]);
    drop(conn);

    let read_only = stored_digests_readonly(&path).unwrap();
    assert_eq!(read_only["syn-t1"], "digest-only-change");
    assert!(
        stored_digests_readonly(&dir.0.join("absent.sqlite"))
            .unwrap()
            .is_empty()
    );
}

#[test]
fn a_period_only_change_rejudges_even_when_the_seven_columns_are_equal() {
    let held = base_row(
        "syn-h",
        json!({"item": "숙박비", "classification_state": "classified", "decided_at": "2026-10-04T00:00:00Z",
               "display_tab_id": "T-A", "trip_id": "T-A"}),
    );
    let mut plan_input = input(vec![held]);
    plan_input.boards.insert(
        "card-syn-h".into(),
        BoardRow {
            display_tab_id: "T-A".into(),
            payload_json: r#"{"item": "숙박비"}"#.into(),
            revision: 1,
        },
    );
    let facts = BTreeMap::from([(
        "syn-h".to_owned(),
        candidate(fact(json!({"transaction_id": "syn-h"}))),
    )]);
    let none = BTreeMap::<String, RefundLink>::new();
    let quiet = plan_with_periods(&plan_input, &none, &evidence(&facts, &[])).unwrap();
    assert!(matches!(quiet.outcomes[0].1, Outcome::Kept(_)));
    let loud = plan_with_periods(&plan_input, &none, &evidence(&facts, &["syn-h"])).unwrap();
    assert!(loud.targets.is_empty(), "7칸 쓰기는 없다");
    let Outcome::Judged(Judgement::Decided(d)) = &loud.outcomes[0].1 else {
        panic!("{:?}", loud.outcomes)
    };
    assert!(matches!(d.service_period(), ServicePeriod::Known { .. }));
}
