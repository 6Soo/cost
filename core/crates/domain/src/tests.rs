use proptest::prelude::*;
use time::{Date, Month};

use crate::*;

fn hash() -> SourceHash {
    SourceHash::new("a".repeat(64)).unwrap()
}

fn txn(id: &str) -> TxnId {
    TxnId::new(id).unwrap()
}

fn trip(tab: &str) -> TripId {
    TripCatalog::from_snapshot([tab.to_owned()])
        .resolve(tab)
        .unwrap()
}

fn allow() -> ItemAllowList {
    ItemAllowList::from_items(["식비".to_owned(), "교통".to_owned()])
}

fn source(id: &str, revision: u32, amount: &str) -> SourceTxn {
    SourceTxn::new(
        txn(id),
        hash(),
        revision,
        Amount::parse(amount),
        Direction::Purchase,
        Date::from_calendar_date(2026, Month::November, 1).unwrap(),
        "상점".into(),
    )
}

fn card_subject(id: &str, revision: u32) -> Subject {
    Subject::card(&source(id, revision, "1,000")).unwrap()
}

fn actor(kind: ActorKind) -> Actor {
    let rule = || RuleId::new("R-1").unwrap();
    let run = || RunId::new("run-1").unwrap();
    let model = || ModelName::new("m").unwrap();
    match kind {
        ActorKind::Manual => Actor::Manual {
            event: ManualEventRef::new("ev-1").unwrap(),
        },
        ActorKind::P1Exact => Actor::P1Exact {
            rule_id: rule(),
            rule_version: 1,
        },
        ActorKind::AiReview => Actor::AiReview {
            run_id: run(),
            model: model(),
        },
        ActorKind::P2 => Actor::P2 {
            run_id: run(),
            model: model(),
        },
        ActorKind::P1Inferred => Actor::P1Inferred {
            rule_id: rule(),
            rule_version: 1,
            confidence: Confidence::Low,
        },
    }
}

fn decision_full(
    id: &str,
    revision: u32,
    kind: ActorKind,
    item: &str,
    attribution: Attribution,
) -> Decision {
    let draft = DecisionDraft {
        subject: card_subject(id, revision),
        attribution,
        item: allow().item(item).unwrap(),
        description: "설명".into(),
        service_period: ServicePeriod::unknown(UnknownPeriodReason::NoEvidence),
        evidence: vec![],
        actor: actor(kind),
        basis: Basis::new("근거").unwrap(),
        uncertainty: vec![],
        policy_refs: vec![PolicyRef::new("PROC-001").unwrap()],
    };
    if matches!(kind, ActorKind::P2 | ActorKind::AiReview) {
        Decision::new_machine(draft, &OpenScope::quarter(2026, Quarter::Q4)).unwrap()
    } else {
        Decision::new(draft).unwrap()
    }
}

fn decision_for(id: &str, kind: ActorKind, item: &str) -> Decision {
    let q = Attribution::QuarterOther {
        year: 2026,
        quarter: Quarter::Q4,
    };
    decision_full(id, 1, kind, item, q)
}

fn decision(kind: ActorKind, item: &str) -> Decision {
    decision_for("t1", kind, item)
}

/// 설계 §2.3 표 원문(행=기존, 열=제안 Manual/P1Exact/AiReview/P2/P1Inferred). T=허용.
const TABLE: [[bool; 5]; 5] = [
    [true, false, false, false, false],
    [true, true, false, false, false],
    [true, true, true, false, false],
    [true, true, true, true, false],
    [true, true, true, true, true],
];

#[test]
fn supersede_table_all_25_cells() {
    for (r, existing_kind) in ActorKind::ALL.into_iter().enumerate() {
        for (c, proposed_kind) in ActorKind::ALL.into_iter().enumerate() {
            let existing = decision(existing_kind, "식비");
            let proposed = decision(proposed_kind, "교통");
            let out = supersede(&existing, proposed.clone());
            let cell = format!("{existing_kind:?} x {proposed_kind:?}");
            if TABLE[r][c] {
                assert_eq!(out, Ok(proposed), "{cell}");
            } else if existing_kind == ActorKind::P1Exact && proposed_kind == ActorKind::AiReview {
                assert!(matches!(out, Err(OverrideDenied::RaiseCause(_))), "{cell}");
            } else {
                assert_eq!(
                    out,
                    Err(OverrideDenied::LowerPriority {
                        existing: existing_kind,
                        proposed: proposed_kind
                    }),
                    "{cell}"
                );
            }
            assert_eq!(allowed(existing_kind, proposed_kind), TABLE[r][c], "{cell}");
        }
    }
}

#[test]
fn raise_cause_carries_rule_and_run() {
    let out = supersede(
        &decision(ActorKind::P1Exact, "식비"),
        decision(ActorKind::AiReview, "교통"),
    );
    let Err(OverrideDenied::RaiseCause(c)) = out else {
        panic!("RaiseCause 기대")
    };
    assert_eq!(c.rule_id.as_str(), "R-1");
    assert_eq!(c.run_id.as_str(), "run-1");
}

#[test]
fn supersede_rejects_other_subject() {
    let existing = decision_for("t1", ActorKind::P1Inferred, "식비");
    let proposed = decision_for("t2", ActorKind::Manual, "교통");
    assert_eq!(
        supersede(&existing, proposed),
        Err(OverrideDenied::SubjectMismatch)
    );
}

#[test]
fn rank_orders_manual_strongest() {
    let ranks: Vec<u8> = ActorKind::ALL.iter().map(|k| actor(*k).rank()).collect();
    assert_eq!(ranks, vec![0, 1, 2, 3, 4]);
}

proptest! {
    #[test]
    fn manual_is_only_replaced_by_manual(p in 0usize..5) {
        let kind = ActorKind::ALL[p];
        let out = supersede(&decision(ActorKind::Manual, "식비"), decision(kind, "교통"));
        prop_assert_eq!(out.is_ok(), kind == ActorKind::Manual);
    }

    #[test]
    fn weaker_never_replaces_stronger(e in 0usize..5, p in 0usize..5) {
        let (ek, pk) = (ActorKind::ALL[e], ActorKind::ALL[p]);
        let out = supersede(&decision(ek, "식비"), decision(pk, "교통"));
        if p > e {
            prop_assert!(out.is_err());
        } else {
            prop_assert!(out.is_ok());
        }
    }

    #[test]
    fn unparsable_amount_is_never_zero(s in "[^0-9]{0,12}") {
        let a = Amount::parse(&s);
        prop_assert!(matches!(a, Amount::Unreadable(_)));
        prop_assert_eq!(a.readable(), None);
    }

    #[test]
    fn parse_roundtrips_integers(v in any::<i64>()) {
        prop_assert_eq!(Amount::parse(&v.to_string()), Amount::Readable(KrwAmount::new(v)));
    }

    #[test]
    fn parse_with_commas_equals_plain(v in 0i64..1_000_000_000_000) {
        let s = v.to_string();
        let mut out = String::new();
        for (i, ch) in s.chars().enumerate() {
            if i > 0 && (s.len() - i) % 3 == 0 { out.push(','); }
            out.push(ch);
        }
        prop_assert_eq!(Amount::parse(&out), Amount::Readable(KrwAmount::new(v)));
    }

    #[test]
    fn unreadable_amount_never_decided(s in "[a-z]{1,8}") {
        let j = Judgement::from_amount(Amount::parse(&s), |_| decision(ActorKind::P1Exact, "식비"));
        prop_assert!(matches!(j, Judgement::Protected(ProtectionReason::AmountUnreadable(_))));
        prop_assert!(j.decision().is_none());
    }

    #[test]
    fn period_requires_order(a in 1i64..3000, b in 1i64..3000) {
        let d = |n: i64| Date::from_julian_day(2_460_000 + n as i32).unwrap();
        let r = ServicePeriod::known(d(a), d(b));
        prop_assert_eq!(r.is_ok(), b >= a);
    }

    #[test]
    fn basis_empty_or_blank_rejected(s in "[ \t\n]{0,6}") {
        prop_assert!(Basis::new(s).is_err());
    }

    #[test]
    fn machine_basis_rejects_digit_runs(prefix in "[가-힣 ]{0,10}", digits in "[0-9]{5,12}") {
        let b = Basis::new(format!("{prefix}{digits}")).unwrap();
        prop_assert_eq!(b.check_machine_authored(), Err(DomainError::BasisPrivateIdentifier));
    }

    #[test]
    fn trip_only_from_snapshot(tab in "[a-z0-9_]{1,10}", other in "[A-Z]{1,6}") {
        let cat = TripCatalog::from_snapshot([tab.clone()]);
        prop_assert!(cat.resolve(&tab).is_some());
        prop_assert!(cat.resolve(&other).is_none());
    }
}

#[test]
fn amount_zero_is_readable_but_empty_is_not() {
    assert_eq!(Amount::parse("0"), Amount::Readable(KrwAmount::new(0)));
    assert!(matches!(
        Amount::parse(""),
        Amount::Unreadable(ParseError {
            kind: ParseErrorKind::Empty
        })
    ));
    assert!(matches!(Amount::parse("1.5"), Amount::Unreadable(_)));
    assert!(matches!(
        Amount::parse("99999999999999999999"),
        Amount::Unreadable(ParseError {
            kind: ParseErrorKind::Overflow
        })
    ));
}

#[test]
fn state_has_exactly_three_variants() {
    // 새 변형(예: "대기")이 생기면 이 match가 컴파일되지 않는다.
    let j = Judgement::Protected(ProtectionReason::Duplicate);
    match j {
        Judgement::Decided(_) | Judgement::Protected(_) | Judgement::Preserved(_) => {}
    }
}

#[test]
fn source_txn_exposes_getters_only() {
    let t = SourceTxn::new(
        txn("t1"),
        hash(),
        3,
        Amount::parse("1,000"),
        Direction::Purchase,
        Date::from_calendar_date(2026, Month::November, 1).unwrap(),
        "상점".into(),
    );
    assert_eq!(t.amount().readable().unwrap().get(), 1000);
    assert_eq!(t.revision(), 3);
    assert_eq!(t.merchant(), "상점");
}

#[test]
fn item_only_from_allow_list() {
    assert!(allow().item("식비").is_ok());
    assert_eq!(allow().item("없는항목"), Err(DomainError::ItemNotAllowed));
}

#[test]
fn quarter_range_and_display_tab_mapping() {
    assert!(Quarter::from_number(0).is_err() && Quarter::from_number(5).is_err());
    let q = Attribution::QuarterOther {
        year: 2026,
        quarter: Quarter::Q3,
    };
    assert_eq!(
        (q.display_tab_id().as_str(), q.trip_id().as_str()),
        ("quarter:2026:3", "")
    );
    let t = Attribution::Trip(trip("1005_경주"));
    assert_eq!(
        (t.display_tab_id().as_str(), t.trip_id().as_str()),
        ("1005_경주", "1005_경주")
    );
    let g = RefundGroup::new(RefundGroupId("g1".into()), vec![txn("a")]).unwrap();
    let r = Attribution::RefundPair(g.id().clone());
    assert_eq!(
        (r.display_tab_id().as_str(), r.trip_id().as_str()),
        ("refunds", "")
    );
}

#[test]
fn machine_actors_cannot_refund_pair_but_exact_can() {
    let g = RefundGroup::new(RefundGroupId("g1".into()), vec![txn("a")]).unwrap();
    for kind in [ActorKind::P2, ActorKind::AiReview] {
        let d = Decision::new_machine(
            DecisionDraft {
                subject: Subject::cash_use(CashUseId::new("c").unwrap()),
                attribution: Attribution::RefundPair(g.id().clone()),
                item: allow().item("식비").unwrap(),
                description: String::new(),
                service_period: ServicePeriod::unknown(UnknownPeriodReason::NotApplicable),
                evidence: vec![],
                actor: actor(kind),
                basis: Basis::new("근거").unwrap(),
                uncertainty: vec![],
                policy_refs: vec![],
            },
            &OpenScope::quarter(2026, Quarter::Q4),
        );
        assert_eq!(
            d,
            Err(DomainError::RefundPairNotAllowedForActor),
            "{kind:?}"
        );
    }
}

#[test]
fn machine_actor_basis_is_checked_in_decision_new() {
    let d = Decision::new_machine(
        DecisionDraft {
            subject: Subject::receipt(ReceiptId::new("r").unwrap()),
            attribution: Attribution::QuarterOther {
                year: 2026,
                quarter: Quarter::Q1,
            },
            item: allow().item("식비").unwrap(),
            description: String::new(),
            service_period: ServicePeriod::unknown(UnknownPeriodReason::NoEvidence),
            evidence: vec![],
            actor: actor(ActorKind::P2),
            basis: Basis::new("연락 a.b@example.com").unwrap(),
            uncertainty: vec![],
            policy_refs: vec![],
        },
        &OpenScope::quarter(2026, Quarter::Q1),
    );
    assert_eq!(d, Err(DomainError::BasisPrivateIdentifier));
    assert_eq!(
        Basis::new("가".repeat(601))
            .unwrap()
            .check_machine_authored(),
        Err(DomainError::BasisTooLong)
    );
}

fn proposal(attr: ProposedAttribution) -> P2Proposal {
    P2Proposal {
        attribution: attr,
        item: allow().item("식비").unwrap(),
        service_period: ServicePeriod::unknown(UnknownPeriodReason::NoEvidence),
        basis: Basis::new("근거").unwrap(),
        uncertainty: vec![Uncertainty::new("예약 확인 못함").unwrap()],
    }
}

fn ctx() -> P2Context {
    P2Context {
        subject: card_subject("t1", 1),
        description: "설명".into(),
        evidence: vec![],
        policy_refs: vec![],
        run_id: RunId::new("r").unwrap(),
        model: ModelName::new("m").unwrap(),
    }
}

#[test]
fn p2_proposal_becomes_p2_decision_only_inside_open_scope() {
    let open_q = OpenScope::quarter(2026, Quarter::Q4);
    let ok = proposal(ProposedAttribution::QuarterOther {
        year: 2026,
        quarter: Quarter::Q4,
    })
    .into_decision(ctx(), &open_q)
    .unwrap();
    assert_eq!(ok.actor().kind(), ActorKind::P2);

    let closed = proposal(ProposedAttribution::QuarterOther {
        year: 2026,
        quarter: Quarter::Q1,
    })
    .into_decision(ctx(), &open_q);
    assert_eq!(closed, Err(DomainError::OutsideOpenScope));

    let t = trip("1005_경주");
    let open_t = OpenScope::trip(&t);
    assert!(
        proposal(ProposedAttribution::Trip(t))
            .into_decision(ctx(), &open_t)
            .is_ok()
    );
    let other = proposal(ProposedAttribution::Trip(trip("other"))).into_decision(ctx(), &open_t);
    assert_eq!(other, Err(DomainError::OutsideOpenScope));
}

fn refund_member(group: &RefundGroup, id: &str) -> Decision {
    decision_full(
        id,
        1,
        ActorKind::P1Exact,
        "식비",
        Attribution::RefundPair(group.id().clone()),
    )
}

#[test]
fn group_publication_is_all_or_nothing_shape() {
    let g = RefundGroup::new(RefundGroupId("g1".into()), vec![txn("a"), txn("b")]).unwrap();
    assert!(
        GroupPublication::new(
            g.clone(),
            vec![refund_member(&g, "a"), refund_member(&g, "b")]
        )
        .is_ok()
    );
    // 구성원 누락, 중복, 외부 구성원, 다른 귀속 모두 거부
    let bad = [
        vec![refund_member(&g, "a")],
        vec![refund_member(&g, "a"), refund_member(&g, "a")],
        vec![refund_member(&g, "a"), refund_member(&g, "z")],
        vec![
            refund_member(&g, "a"),
            decision_for("b", ActorKind::P1Exact, "식비"),
        ],
    ];
    for decisions in bad {
        assert_eq!(
            GroupPublication::new(g.clone(), decisions),
            Err(DomainError::GroupPublicationMismatch)
        );
    }
    assert_eq!(
        RefundGroup::new(RefundGroupId("g".into()), vec![]),
        Err(DomainError::EmptyGroup)
    );
}

#[test]
fn id_and_ref_validation() {
    assert!(TxnId::new("  ").is_err());
    assert!(SourceHash::new("xyz").is_err());
    assert!(SourceHash::new("A".repeat(64)).is_err());
    for ok in ["PROC-001", "ITEM-019", "RFND-004"] {
        assert!(PolicyRef::new(ok).is_ok(), "{ok}");
    }
    for bad in ["proc-1", "PROC", "PROC-", "-1", "PROC-1a"] {
        assert!(PolicyRef::new(bad).is_err(), "{bad}");
    }
    assert!(TripCatalog::from_snapshot(["".into(), " ".into()]).is_empty());
}

fn draft_with(actor_kind: ActorKind, subject: Subject, attribution: Attribution) -> DecisionDraft {
    DecisionDraft {
        subject,
        attribution,
        item: allow().item("식비").unwrap(),
        description: String::new(),
        service_period: ServicePeriod::unknown(UnknownPeriodReason::NoEvidence),
        evidence: vec![],
        actor: actor(actor_kind),
        basis: Basis::new("근거").unwrap(),
        uncertainty: vec![],
        policy_refs: vec![],
    }
}

fn q4() -> Attribution {
    Attribution::QuarterOther {
        year: 2026,
        quarter: Quarter::Q4,
    }
}

#[test]
fn machine_actors_need_scope_token() {
    for kind in [ActorKind::P2, ActorKind::AiReview] {
        let d = Decision::new(draft_with(kind, card_subject("t1", 1), q4()));
        assert_eq!(d, Err(DomainError::MachineActorNeedsScope), "{kind:?}");
        let closed = OpenScope::quarter(2026, Quarter::Q1);
        let d = Decision::new_machine(draft_with(kind, card_subject("t1", 1), q4()), &closed);
        assert_eq!(d, Err(DomainError::OutsideOpenScope), "{kind:?}");
        let open = OpenScope::quarter(2026, Quarter::Q4);
        assert!(
            Decision::new_machine(draft_with(kind, card_subject("t1", 1), q4()), &open).is_ok()
        );
    }
    for kind in [ActorKind::Manual, ActorKind::P1Exact, ActorKind::P1Inferred] {
        let open = OpenScope::quarter(2026, Quarter::Q4);
        let d = Decision::new_machine(draft_with(kind, card_subject("t1", 1), q4()), &open);
        assert_eq!(d, Err(DomainError::NotMachineActor), "{kind:?}");
    }
}

#[test]
fn unreadable_amount_txn_cannot_become_subject_or_decision() {
    for raw in ["", "abc", "1.5", "99999999999999999999"] {
        let txn = source("u1", 1, raw);
        assert!(matches!(
            Subject::card(&txn),
            Err(ProtectionReason::AmountUnreadable(_))
        ));
    }
    assert!(Subject::card(&source("ok", 1, "0")).is_ok());
}

#[test]
fn exact_over_exact_only_for_same_rule() {
    let with_rule = |rule: &str, version: u32| {
        let mut draft = draft_with(ActorKind::P1Exact, card_subject("t1", 1), q4());
        draft.actor = Actor::P1Exact {
            rule_id: RuleId::new(rule).unwrap(),
            rule_version: version,
        };
        Decision::new(draft).unwrap()
    };
    let existing = with_rule("R-1", 1);
    assert!(supersede(&existing, with_rule("R-1", 2)).is_ok());
    assert_eq!(
        supersede(&existing, with_rule("R-2", 1)),
        Err(OverrideDenied::ExactRuleConflict {
            existing: RuleId::new("R-1").unwrap(),
            proposed: RuleId::new("R-2").unwrap()
        })
    );
}

#[test]
fn lower_revision_cannot_supersede_higher() {
    let q = q4();
    let newer = decision_full("t1", 5, ActorKind::P1Inferred, "식비", q.clone());
    let older = decision_full("t1", 4, ActorKind::Manual, "교통", q.clone());
    assert_eq!(
        supersede(&newer, older),
        Err(OverrideDenied::StaleRevision {
            existing: 5,
            proposed: 4
        })
    );
    assert!(
        supersede(
            &newer,
            decision_full("t1", 5, ActorKind::Manual, "교통", q.clone())
        )
        .is_ok()
    );
    assert!(supersede(&newer, decision_full("t1", 6, ActorKind::Manual, "교통", q)).is_ok());
}
