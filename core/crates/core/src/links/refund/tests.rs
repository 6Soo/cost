//! U12 시험: 합성 골든(짝 도출 `refund_pairing`, 묶음 판정 `refund_groups`), 규칙 단위 시험, 보호 불변식.

use std::collections::{BTreeMap, BTreeSet};
use std::path::Path;

use proptest::prelude::*;
use serde_json::{Value, json};

use super::*;

fn config() -> PairingConfig {
    let path = Path::new(env!("CARGO_MANIFEST_DIR")).join("../../../config/refund-pairing.json");
    PairingConfig::from_json(&std::fs::read_to_string(path).unwrap()).unwrap()
}

fn golden(area: &str) -> Vec<Value> {
    let path =
        Path::new(env!("CARGO_MANIFEST_DIR")).join(format!("../../golden/synthetic/{area}.jsonl"));
    std::fs::read_to_string(path)
        .unwrap()
        .lines()
        .map(|l| serde_json::from_str(l).unwrap())
        .collect()
}

fn text(v: &Value, key: &str) -> String {
    v.get(key).and_then(Value::as_str).unwrap_or("").to_string()
}

/// 합성 시나리오 DB(`tools/core_bridge/synthetic.py`)가 채우는 기본값을 따른다.
fn scenario_row(v: &Value) -> RefundTxn {
    let merchant = text(v, "merchant");
    let normalized = text(v, "merchant_normalized");
    let or_default = |key: &str, default: &str| {
        v.get(key)
            .and_then(Value::as_str)
            .unwrap_or(default)
            .to_string()
    };
    RefundTxn {
        transaction_id: text(v, "transaction_id"),
        issuer: or_default("issuer", "SYN-BANK"),
        card_tail: or_default("card_tail", "0001"),
        direction: or_default("transaction_direction", "purchase"),
        approval_number: text(v, "approval_number"),
        original_approval_number: text(v, "original_approval_number"),
        amount_krw: v.get("amount_krw").and_then(Value::as_i64),
        approval_date: text(v, "approval_date"),
        posting_date: text(v, "posting_date"),
        merchant_normalized: if normalized.is_empty() {
            merchant.to_lowercase()
        } else {
            normalized
        },
        merchant,
        foreign_amount: text(v, "foreign_amount"),
        foreign_currency: text(v, "foreign_currency"),
        duplicate_of: v
            .get("duplicate_of")
            .and_then(Value::as_str)
            .map(str::to_string),
        conflict_reason: text(v, "conflict_reason"),
        parse_error: text(v, "parse_error"),
    }
}

fn rows_of(input: &Value) -> Vec<RefundTxn> {
    input["scenario"]["rows"]
        .as_array()
        .unwrap()
        .iter()
        .map(scenario_row)
        .collect()
}

fn link_json(link: &Link) -> Value {
    let mut out = json!({
        "gross_krw": link.gross_krw, "net_krw": link.net_krw, "original_id": link.original_id,
        "refund_count": link.refund_count, "refund_krw": link.refund_krw,
        "refunds_total_krw": link.refunds_total_krw, "status": link.status.as_str(),
    });
    if let Some(basis) = link.basis {
        out["basis"] = json!(basis.as_str());
        if basis != Basis::MerchantCardForeignAmount {
            out["inferred"] = json!(link.inferred);
            out["matching_source"] = json!("automatic");
        }
    }
    out
}

fn links_json(refunds: &Refunds) -> Value {
    Value::Object(
        refunds
            .links()
            .iter()
            .map(|l| (l.refund_id.clone(), link_json(l)))
            .collect(),
    )
}

fn exclusions_json(refunds: &Refunds) -> Value {
    Value::Object(
        refunds
            .originals()
            .into_iter()
            .map(|o| {
                let reason = refunds.exclusion(&o).map_or("", Exclusion::as_str);
                (o, json!(reason))
            })
            .collect(),
    )
}

#[test]
fn pairing_golden_matches_python() {
    let cfg = config();
    let cases = golden("refund_pairing");
    assert_eq!(cases.len(), 42);
    for case in &cases {
        let rows = rows_of(&case["input"]);
        let refunds = Refunds::derive(&rows, &cfg);
        let held: BTreeMap<_, _> = refunds
            .held()
            .iter()
            .map(|(k, h)| {
                (
                    k.clone(),
                    json!({"purchases": h.purchases, "cancellations": h.cancellations}),
                )
            })
            .collect();
        let groups: BTreeMap<_, _> = refunds
            .originals()
            .into_iter()
            .map(|o| (o.clone(), refunds.group(&o)))
            .collect();
        let actual = json!({
            "links": links_json(&refunds), "groups": groups, "group_exclusions": exclusions_json(&refunds),
            "held": held, "review_originals": refunds.review_originals(),
        });
        assert_eq!(
            actual, case["expected"],
            "{} ({})",
            case["case_id"], case["note"]
        );
    }
}

fn entries_of(request: &Value, booked: &BTreeSet<String>) -> Vec<Entry> {
    request["entries"]
        .as_array()
        .map_or_else(Vec::new, |a| a.iter().collect())
        .into_iter()
        .map(|e| {
            let code = text(e, "blocked");
            Entry {
                id: text(e, "transaction_id"),
                item: text(e, "item"),
                display_tab_id: text(e, "display_tab_id"),
                trip_id: text(e, "trip_id"),
                description: text(e, "description"),
                blocked: (!code.is_empty()).then(|| Block {
                    code,
                    reason: "synthetic hold".into(),
                }),
                already_booked: booked.contains(&text(e, "transaction_id")),
                external: e.get("source_batch_id").is_some(),
                ready: text(e, "blocked").is_empty(),
                refund_link: None,
            }
        })
        .collect()
}

fn note_json(note: &RefundNote) -> Value {
    let mut out = json!({
        "gross_krw": note.gross_krw, "net_krw": note.net_krw, "refund_krw": note.refund_krw,
        "status": note.status.as_str(), "counterpart_id": note.counterpart_id,
        "role": if note.role == Role::Refund { "refund" } else { "original" },
    });
    if note.inferred {
        out["inferred"] = json!(true);
        out["basis"] = json!(note.basis.map(Basis::as_str));
    }
    out
}

#[test]
fn group_golden_matches_python() {
    let cfg = config();
    let cases = golden("refund_groups");
    assert_eq!(cases.len(), 53);
    for case in &cases {
        let id = format!("{} ({})", case["case_id"], case["note"]);
        let input = &case["input"];
        let rows = rows_of(input);
        let refunds = Refunds::derive(&rows, &cfg);
        let booked: BTreeSet<String> = input["scenario"]["ledger"]
            .as_array()
            .map_or_else(BTreeSet::new, |a| {
                a.iter().map(|e| text(e, "transaction_id")).collect()
            });
        let mut entries = entries_of(input, &booked);
        let valid = |key: &str| -> Option<Vec<String>> {
            input
                .get(key)
                .and_then(Value::as_array)
                .map(|a| a.iter().map(|v| v.as_str().unwrap().to_string()).collect())
        };
        let (trips, tabs) = (valid("valid_trips"), valid("valid_tabs"));
        let trip_ok = |t: &str| trips.as_ref().unwrap().iter().any(|v| v == t);
        let tab_ok = |t: &str| tabs.as_ref().unwrap().iter().any(|v| v == t);
        let authority = Authority {
            trip: trips.as_ref().map(|_| &trip_ok as &dyn Fn(&str) -> bool),
            tab: tabs.as_ref().map(|_| &tab_ok as &dyn Fn(&str) -> bool),
        };
        apply_pairs(&refunds, &mut entries, &authority);

        let mut actual = serde_json::Map::new();
        if let Some(batch) = input.get("batch_id").and_then(Value::as_str) {
            let membership = |wanted: Option<&str>| -> BTreeSet<String> {
                input["scenario"]["batch_rows"]
                    .as_array()
                    .unwrap()
                    .iter()
                    .filter(|b| wanted.is_none_or(|w| b["batch_id"] == w))
                    .map(|b| text(b, "transaction_id"))
                    .collect()
            };
            let current = membership(Some(batch));
            let anywhere = membership(None);
            let mut selected = current.clone();
            if input["extension"] == true {
                selected.extend(
                    extension(&refunds, &current)
                        .into_iter()
                        .filter(|i| anywhere.contains(i)),
                );
            }
            actual.insert("selected".into(), json!(selected));
        }
        let check = check_groups(&refunds, &entries, &booked)
            .err()
            .map_or("", |e| e.code());
        actual.insert("group_check".into(), json!(check));
        actual.insert(
            "entries".into(),
            Value::Array(
                entries
                    .iter()
                    .map(|e| {
                        json!({
                            "transaction_id": e.id, "blocked": e.blocked.as_ref().map(|b| &b.code),
                            "reason": e.blocked.as_ref().map(|b| &b.reason), "item": e.item,
                            "description": e.description, "display_tab_id": e.display_tab_id, "trip_id": e.trip_id,
                            "refund_link": e.refund_link.as_ref().map(note_json),
                            "bucket": if e.ready { "ready" } else { "unresolved" },
                        })
                    })
                    .collect(),
            ),
        );
        actual.insert("links".into(), links_json(&refunds));
        actual.insert("group_exclusions".into(), exclusions_json(&refunds));
        let mut scope = serde_json::Map::new();
        for original in refunds.originals() {
            let scoped = scope_group(&refunds, &entries, &original);
            let issued = issue_group(&refunds, &entries, &original);
            // 묶음 발급은 Python 범위 검증을 통과하고 제외 사유가 없을 때만 된다(제외는 전액 상쇄에도 적용: 더 엄격).
            assert_eq!(
                issued.is_ok(),
                scoped.is_ok() && refunds.exclusion(&original).is_none(),
                "{id}: issue {original}"
            );
            if let Ok(group) = &issued {
                assert_eq!(
                    group.members().len(),
                    refunds.group(&original).len(),
                    "{id}"
                );
            }
            scope.insert(
                original,
                match scoped {
                    Ok(s) => json!({"code": "", "recordable": s.recordable}),
                    Err(e) => json!({"code": e.code(), "recordable": false}),
                },
            );
        }
        actual.insert("scope".into(), Value::Object(scope));
        assert_eq!(Value::Object(actual), case["expected"], "{id}");
    }
}

// --- 규칙 단위 시험 ---------------------------------------------------------------------

fn txn(id: &str, direction: &str, amount: i64) -> RefundTxn {
    RefundTxn {
        transaction_id: id.into(),
        issuer: "B".into(),
        card_tail: "1".into(),
        direction: direction.into(),
        amount_krw: Some(amount),
        approval_date: "2026-10-03".into(),
        posting_date: "2026-10-05".into(),
        merchant: "SHOP".into(),
        merchant_normalized: "shop".into(),
        ..RefundTxn::default()
    }
}

fn purchase(id: &str, amount: i64, approval: &str) -> RefundTxn {
    RefundTxn {
        approval_number: approval.into(),
        ..txn(id, "purchase", amount)
    }
}

fn cancel(id: &str, amount: i64, original: &str) -> RefundTxn {
    RefundTxn {
        original_approval_number: original.into(),
        ..txn(id, "cancellation", amount)
    }
}

fn ids(rows: &[RefundTxn]) -> Vec<Entry> {
    rows.iter()
        .map(|r| Entry {
            id: r.transaction_id.clone(),
            item: if r.direction == "purchase" {
                "식비".into()
            } else {
                String::new()
            },
            display_tab_id: if r.direction == "purchase" {
                "T-A".into()
            } else {
                String::new()
            },
            trip_id: if r.direction == "purchase" {
                "T-A".into()
            } else {
                String::new()
            },
            ready: true,
            ..Entry::default()
        })
        .collect()
}

#[test]
fn numbered_pairs_are_one_to_many_and_status_follows_the_net() {
    let rows = [
        purchase("p", 10000, "A1"),
        cancel("c1", -4000, "A1"),
        cancel("c2", -6000, " A1 "),
    ];
    let refunds = Refunds::derive(&rows, &config());
    assert_eq!(refunds.links().len(), 2);
    assert!(
        refunds
            .links()
            .iter()
            .all(|l| l.status == Status::Full && l.net_krw == 0 && l.refund_count == 2)
    );
    assert_eq!(refunds.group("p"), ["p", "c1", "c2"]);
}

#[test]
fn two_purchases_with_one_approval_number_make_no_link() {
    let rows = [
        purchase("p1", 10000, "A1"),
        purchase("p2", 10000, "A1"),
        cancel("c", -10000, "A1"),
    ];
    assert!(Refunds::derive(&rows, &config()).links().is_empty());
}

#[test]
fn unclean_rows_cannot_be_an_original_and_cancel_siblings_are_dropped() {
    let mut dirty = purchase("p", 10000, "A1");
    dirty.conflict_reason = "syn conflict".into();
    assert!(
        Refunds::derive(&[dirty, cancel("c", -10000, "A1")], &config())
            .links()
            .is_empty()
    );
    let mut dup = cancel("c2", -4000, "A1");
    dup.duplicate_of = Some("c1".into());
    let rows = [purchase("p", 10000, "A1"), cancel("c1", -4000, "A1"), dup];
    let refunds = Refunds::derive(&rows, &config());
    assert_eq!(refunds.links().len(), 1);
    assert_eq!(refunds.exclusion("p"), Some(Exclusion::UncleanMember));
}

#[test]
fn foreign_decimal_keys_compare_by_value() {
    assert_eq!(
        foreign_amount_for_test("1500"),
        foreign_amount_for_test(" 1,500.00 ")
    );
    assert_eq!(
        foreign_amount_for_test("-1500"),
        foreign_amount_for_test("15E2")
    );
    assert_eq!(foreign_amount_for_test("0.0"), None);
    assert_eq!(foreign_amount_for_test("NaN"), None);
    assert_eq!(foreign_amount_for_test(""), None);
}

fn foreign_amount_for_test(value: &str) -> Option<(String, i64)> {
    super::pairing::foreign_amount(value)
}

#[test]
fn inferred_links_only_display_and_never_authorize_a_write() {
    let rows = [purchase("p", 10000, "A1"), cancel("c", -10000, "A1")];
    let mut refunds = Refunds::derive(&rows, &config());
    refunds.links[0].inferred = true;
    refunds.links[0].basis = Some(Basis::KakaoSameCardExactAmount);
    let mut entries = ids(&rows);
    let trip_ok = |_: &str| true;
    let authority = Authority {
        trip: Some(&trip_ok),
        tab: Some(&trip_ok),
    };
    apply_pairs(&refunds, &mut entries, &authority);
    assert!(entries.iter().all(|e| {
        e.blocked
            .as_ref()
            .is_some_and(|b| b.code == "refund_inferred")
            && !e.ready
    }));
    assert!(
        entries
            .iter()
            .all(|e| e.refund_link.as_ref().is_some_and(|n| n.inferred))
    );
    // 추론 연결은 묶음 발급 입력이 될 수 없다.
    assert_eq!(
        issue_group(&refunds, &entries, "p"),
        Err(Refusal::NotVerified)
    );
    assert!(extension(&refunds, &BTreeSet::from(["c".to_string()])).is_empty());
}

#[test]
fn a_refund_never_overwrites_its_own_attribution_and_money_is_untouched() {
    let rows = [purchase("p", 10000, "A1"), cancel("c", -4000, "A1")];
    let before = rows.clone();
    let refunds = Refunds::derive(&rows, &config());
    let mut entries = ids(&rows);
    entries[1].item = "식비".into();
    entries[1].description = "내 설명".into();
    let ok = |_: &str| true;
    apply_pairs(
        &refunds,
        &mut entries,
        &Authority {
            trip: Some(&ok),
            tab: Some(&ok),
        },
    );
    assert_eq!(entries[1].description, "내 설명");
    assert_eq!(entries[1].display_tab_id, "T-A");
    assert_eq!(rows, before);
}

#[test]
fn issuing_a_group_refuses_every_unsafe_shape() {
    let cfg = config();
    let all = |rows: &[RefundTxn]| ids(rows);
    // 초과 환불
    let rows = [purchase("p", 10000, "A1"), cancel("c", -12000, "A1")];
    let refunds = Refunds::derive(&rows, &cfg);
    assert_eq!(
        issue_group(&refunds, &all(&rows), "p"),
        Err(Refusal::NotVerified)
    );
    // 구성원 누락
    let rows = [purchase("p", 10000, "A1"), cancel("c", -4000, "A1")];
    let refunds = Refunds::derive(&rows, &cfg);
    let partial = all(&rows[..1]);
    assert_eq!(
        issue_group(&refunds, &partial, "p"),
        Err(Refusal::MemberMissing("c".into()))
    );
    // 완료 기간 구성원
    let mut old = rows.clone();
    old[0].approval_date = "2025-10-03".into();
    let refunds = Refunds::derive(&old, &cfg);
    assert_eq!(
        issue_group(&refunds, &all(&old), "p"),
        Err(Refusal::Excluded(Exclusion::CompletedPeriod))
    );
    // 깨끗하지 않은 취소
    let mut dirty = rows.to_vec();
    dirty.push(RefundTxn {
        parse_error: "AMOUNT_UNREADABLE".into(),
        ..cancel("d", -4000, "A1")
    });
    let refunds = Refunds::derive(&dirty, &cfg);
    assert_eq!(
        issue_group(&refunds, &all(&dirty), "p"),
        Err(Refusal::Excluded(Exclusion::UncleanMember))
    );
    // 외화 부분환불(원승인번호 연결이 아님)
    let foreign = |r: RefundTxn| RefundTxn {
        foreign_currency: "JPY".into(),
        foreign_amount: "1500".into(),
        ..r
    };
    let rows = [
        foreign(purchase("p", 14000, "")),
        foreign(cancel("c", -13000, "")),
    ];
    let refunds = Refunds::derive(&rows, &cfg);
    assert_eq!(refunds.links().len(), 1);
    assert_eq!(
        issue_group(&refunds, &all(&rows), "p"),
        Err(Refusal::NotVerified)
    );
    // 정상 묶음
    let rows = [purchase("p", 10000, "A1"), cancel("c", -4000, "A1")];
    let refunds = Refunds::derive(&rows, &cfg);
    let group = issue_group(&refunds, &all(&rows), "p").unwrap();
    assert_eq!(group.members().len(), 2);
    assert_eq!(group.id().as_str(), "refund:p");
}

#[test]
fn a_half_booked_group_is_refused() {
    let rows = [
        purchase("p", 10000, "A1"),
        cancel("c1", -4000, "A1"),
        cancel("c2", -6000, "A1"),
    ];
    let refunds = Refunds::derive(&rows, &config());
    let mut entries = ids(&rows);
    entries[2].ready = false;
    entries[2].blocked = Some(Block {
        code: "item_missing".into(),
        reason: String::new(),
    });
    assert_eq!(
        check_groups(&refunds, &entries, &BTreeSet::new()),
        Err(Refusal::HalfBooked)
    );
    assert_eq!(
        check_groups(&refunds, &entries, &BTreeSet::from(["p".to_string()])),
        Ok(())
    );
}

// --- 속성 시험 ------------------------------------------------------------------------

fn arb_row(index: usize) -> impl Strategy<Value = RefundTxn> {
    (
        prop::bool::ANY,
        prop::sample::select(vec!["1", "2"]),
        prop::sample::select(vec!["", "A", "B"]),
        1..4i64,
        prop::sample::select(vec!["shop", "taxi", "카카오 택시"]),
        prop::bool::ANY,
        prop::sample::select(vec!["", "10", "20"]),
        1..14u32,
        0..8u8,
    )
        .prop_map(
            move |(
                is_purchase,
                tail,
                reference,
                units,
                merchant,
                foreign,
                foreign_amount,
                day,
                dirt,
            )| {
                let amount = units * 1000;
                let mut r = txn(
                    &format!("t{index}"),
                    if is_purchase {
                        "purchase"
                    } else {
                        "cancellation"
                    },
                    0,
                );
                r.amount_krw = Some(if is_purchase { amount } else { -amount });
                r.card_tail = tail.into();
                if is_purchase {
                    r.approval_number = reference.into();
                } else {
                    r.original_approval_number = reference.into();
                }
                r.merchant = merchant.into();
                r.merchant_normalized = merchant.into();
                if foreign && !foreign_amount.is_empty() {
                    r.foreign_currency = "JPY".into();
                    r.foreign_amount = foreign_amount.into();
                }
                r.approval_date = format!("2026-10-{day:02}");
                match dirt {
                    0 => r.duplicate_of = Some("other".into()),
                    1 => r.conflict_reason = "c".into(),
                    2 => r.parse_error = "e".into(),
                    _ => {}
                }
                r
            },
        )
}

fn arb_rows() -> impl Strategy<Value = Vec<RefundTxn>> {
    (1..9usize).prop_flat_map(|n| (0..n).map(arb_row).collect::<Vec<_>>())
}

fn clean_row(r: &RefundTxn) -> bool {
    r.duplicate_of.is_none() && r.conflict_reason.is_empty() && r.parse_error.is_empty()
}

proptest! {
    #![proptest_config(ProptestConfig::with_cases(512))]

    #[test]
    fn links_never_break_the_protections(rows in arb_rows()) {
        let before = rows.clone();
        let refunds = Refunds::derive(&rows, &config());
        prop_assert_eq!(&rows, &before);
        let by_id: BTreeMap<&str, &RefundTxn> = rows.iter().map(|r| (r.transaction_id.as_str(), r)).collect();
        let mut refund_ids = BTreeSet::new();
        let mut single_use: BTreeSet<&str> = BTreeSet::new();
        let numbered: BTreeSet<&str> =
            refunds.links().iter().filter(|l| l.basis.is_none()).map(|l| l.original_id.as_str()).collect();
        for link in refunds.links() {
            // 한 취소는 한 연결, 원결제는 깨끗한 구매
            prop_assert!(refund_ids.insert(link.refund_id.as_str()));
            let original = by_id[link.original_id.as_str()];
            prop_assert!(original.direction == "purchase" && original.amount_krw.is_some_and(|a| a > 0) && clean_row(original));
            prop_assert!(clean_row(by_id[link.refund_id.as_str()]));
            // 순잔액은 파생값이고 상태는 순잔액을 따른다
            prop_assert_eq!(link.net_krw, link.gross_krw + link.refunds_total_krw);
            let expect = match link.net_krw { n if n < 0 => Status::Excess, 0 => Status::Full, _ => Status::Partial };
            prop_assert_eq!(link.status, expect);
            // 한 구매가 두 취소에 점유되지 않는다(원승인번호 1:N 연결은 같은 번호의 묶음이라 예외)
            if link.basis.is_some() {
                prop_assert!(single_use.insert(link.original_id.as_str()));
                prop_assert!(!numbered.contains(link.original_id.as_str()));
            }
        }
        // 검토 원결제는 실제 연결의 원결제를 모두 포함한다
        let review = refunds.review_originals();
        for link in refunds.links() {
            prop_assert!(review.contains(&link.original_id));
        }
    }

    #[test]
    fn a_group_is_issued_only_for_verified_clean_members(rows in arb_rows()) {
        let refunds = Refunds::derive(&rows, &config());
        let entries = ids(&rows);
        for original in refunds.originals() {
            let Ok(group) = issue_group(&refunds, &entries, &original) else { continue };
            prop_assert!(refunds.exclusion(&original).is_none());
            let members: Vec<&str> = group.members().iter().map(|m| m.as_str()).collect();
            prop_assert!(members.len() >= 2 && members[0] == original);
            for link in refunds.links().iter().filter(|l| l.original_id == original) {
                prop_assert!(!link.inferred && link.is_verified());
                prop_assert!(link.status != Status::Excess);
            }
            for member in members {
                let row = rows.iter().find(|r| r.transaction_id == member).unwrap();
                prop_assert!(clean_row(row));
            }
        }
    }
}
