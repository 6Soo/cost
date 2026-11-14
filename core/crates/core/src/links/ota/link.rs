//! OTA 이벤트 ↔ 카드 최종 연결(M:N 묶음·점유·고정 그룹). 원본: `match_ota_payment_events`와 그 단계
//! (`_prepare_match_state`, `_allocate_repeated_groups`, `_select_singleton_payments`, `_assemble_ota_match_results`,
//! `_pinned_link_result`, `bind_legacy_portal_links`).
//!
//! 기존 수동·고정·옛 포털 연결과 고정 그룹의 카드는 다시 계산하지 않고 점유된 입력으로만 읽는다. 입력에서 사라진 사건의
//! 저장 연결도 점유로 남는다. 후보·거절 사유·점유 집합 같은 중간 산출물은 Python과 같다고 약속하지 않고, 최종 연결(쌍·
//! 상태·성분 구성)만 맞춘다. 연결 종류는 [`LinkKind`]로 구분해 추론 연결이 정확 연결로 읽히지 않게 한다.

use super::Matcher;
use super::assign::{Options, ambiguous_optimal_singletons, approval_key, assign_exact_first};
use super::decimal::Dec;
use super::inference::{BASIS, NOTE};
use super::pyval::{first_text, get, is_str, pystr, text, truthy};
use super::relations::{Relation, attach_relations};
use crate::digest::{python_json_compact, sha256_hex};
use crate::rules::casefold;
use serde_json::{Map, Value, json};
use std::collections::{BTreeMap, BTreeSet};

/// 연결이 어떻게 만들어졌는가. 추론은 정확 연결과 다른 종류다.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum LinkKind {
    /// 근거로 정확히 하나로 정해진 연결(승인 차액·할인 단계 포함).
    Exact,
    /// 같은 금액 반복 결제의 승인번호·예약번호 안정 순서 배정(고정 그룹이면 사용자가 확인한 순서).
    GroupOrder { frozen: bool },
    /// 결제일 없는 아고다의 상호 유일 추론.
    Inferred,
    /// 기존 수동·고정·옛 포털 연결을 그대로 둔 것.
    Pinned,
    /// M:N 근거 관계(`MATCHED_GROUP`). 카드 한 장에 대한 일대일 금융 배정이 없다.
    Relation,
    /// 보류.
    Hold,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct GroupShape {
    pub ota_ids: Vec<String>,
    pub card_ids: Vec<String>,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct MatchedCounts {
    pub matched: usize,
    pub unmatched_ota: usize,
    pub unmatched_card: usize,
}

#[derive(Debug, Clone, PartialEq)]
pub struct FrozenChange {
    pub frozen_mapping: Value,
    pub proposed_mapping: BTreeMap<String, String>,
}

/// 이벤트 하나의 최종 연결 결과(Python 결과 사전의 연결 칸).
#[derive(Debug, Clone, PartialEq)]
pub struct OtaLink {
    pub ota_event_id: String,
    pub status: String,
    pub reason: String,
    pub kind: LinkKind,
    pub transaction_id: Option<String>,
    pub candidates: Vec<String>,
    pub reserved_card_ids: Option<Vec<String>>,
    pub group: Option<GroupShape>,
    pub matched: Option<MatchedCounts>,
    pub allocation_basis: Option<&'static str>,
    pub group_order_frozen: Option<bool>,
    pub group_order_snapshot: Option<Value>,
    pub individual_payment_evidence: Option<bool>,
    pub frozen: Option<FrozenChange>,
    /// 승인 차액·할인 단계 칸(`rule_delta_krw`, `discount_cause_confirmed`)이 결과에 있는가.
    pub delta: Option<(Option<i64>, Option<bool>)>,
    pub payment_date_verified: Option<bool>,
    pub relation: Option<Relation>,
}

impl OtaLink {
    fn base(id: &str, status: &str, reason: &str, kind: LinkKind) -> Self {
        OtaLink {
            ota_event_id: id.to_string(),
            status: status.to_string(),
            reason: reason.to_string(),
            kind,
            transaction_id: None,
            candidates: Vec::new(),
            reserved_card_ids: None,
            group: None,
            matched: None,
            allocation_basis: None,
            group_order_frozen: None,
            group_order_snapshot: None,
            individual_payment_evidence: None,
            frozen: None,
            delta: None,
            payment_date_verified: None,
            relation: None,
        }
    }

    fn hold(id: &str, status: &str, reason: &str, candidates: Vec<String>) -> Self {
        let mut link = OtaLink::base(id, status, reason, LinkKind::Hold);
        link.candidates = candidates;
        link
    }

    /// Python 결과 사전 모양(연결 칸만). 골든 비교와 다리 출력이 쓴다.
    pub fn to_value(&self) -> Value {
        let mut out = Map::new();
        let mut put = |k: &str, v: Value| {
            out.insert(k.to_string(), v);
        };
        put("ota_event_id", json!(self.ota_event_id));
        put("status", json!(self.status));
        put("reason", json!(self.reason));
        put("transaction_id", json!(self.transaction_id));
        put("candidates", json!(self.candidates));
        if let Some(ids) = &self.reserved_card_ids {
            put("reserved_card_ids", json!(ids));
        }
        if let Some(g) = &self.group {
            put(
                "group_count",
                json!({"ota": g.ota_ids.len(), "cards": g.card_ids.len()}),
            );
            put("ota_group_ids", json!(g.ota_ids));
            put("card_group_ids", json!(g.card_ids));
        }
        if let Some(m) = &self.matched {
            put("matched_count", json!(m.matched));
            put("unmatched_ota_count", json!(m.unmatched_ota));
            put("unmatched_card_count", json!(m.unmatched_card));
        }
        if let Some(v) = self.allocation_basis {
            put("allocation_basis", json!(v));
        }
        if let Some(v) = self.group_order_frozen {
            put("group_order_frozen", json!(v));
        }
        if let Some(v) = &self.group_order_snapshot {
            put("group_order_snapshot", v.clone());
        }
        if let Some(v) = self.individual_payment_evidence {
            put("individual_payment_evidence", json!(v));
        }
        if let Some(f) = &self.frozen {
            put("review_warning", json!("confirm_group_reallocation"));
            put("frozen_mapping", f.frozen_mapping.clone());
            put("proposed_mapping", json!(f.proposed_mapping));
        }
        if let Some((delta, cause)) = self.delta {
            put("rule_delta_krw", json!(delta));
            put("discount_cause_confirmed", json!(cause));
        }
        if let Some(v) = self.payment_date_verified {
            put("payment_date_verified", json!(v));
        }
        if self.kind == LinkKind::Inferred {
            put("inferred_link", json!(true));
            put("inference_basis", json!(NOTE));
        }
        if let Some(r) = &self.relation {
            put("payment_relation", r.to_value());
        }
        Value::Object(out)
    }
}

/// 고정 그룹 한 줄(사용자가 확인한 묶음). 읽기만 한다.
struct Pin {
    event_ids: BTreeSet<String>,
    card_ids: BTreeSet<String>,
    mapping: BTreeMap<String, String>,
    mapping_raw: Value,
    snapshot: Value,
}

fn id_set(v: &Value, key: &str) -> BTreeSet<String> {
    get(v, key)
        .and_then(Value::as_array)
        .map(|a| a.iter().map(pystr).collect())
        .unwrap_or_default()
}

impl Pin {
    fn parse(v: &Value) -> Pin {
        let raw = get(v, "mapping").cloned();
        let mapping = raw
            .as_ref()
            .and_then(Value::as_object)
            .map(|m| m.iter().map(|(k, v)| (k.clone(), pystr(v))).collect())
            .unwrap_or_default();
        Pin {
            event_ids: id_set(v, "event_ids"),
            card_ids: id_set(v, "card_ids"),
            mapping,
            mapping_raw: raw.unwrap_or_else(|| json!({})),
            snapshot: v
                .get("order_snapshot")
                .cloned()
                .unwrap_or_else(|| json!({})),
        }
    }
}

struct Spec<'a> {
    events: Vec<&'a Value>,
    event_ids: Vec<String>,
    card_ids: Vec<String>,
    pairs: Vec<(String, String)>,
    matched: usize,
    card_rows: BTreeMap<String, &'a Value>,
    pin: Option<usize>,
    snapshot: Value,
}

struct Run<'a> {
    m: Matcher<'a>,
    events: &'a [Value],
    transactions: &'a [Value],
    existing: &'a Map<String, Value>,
    pins: Vec<Pin>,
    rows: BTreeMap<String, &'a Value>,
    claimed: BTreeSet<String>,
    pinned_counts: BTreeMap<String, usize>,
    pin_owners: BTreeMap<String, Vec<usize>>,
    events_by_id: BTreeMap<String, &'a Value>,
    raw_options: Options<'a>,
    options: Options<'a>,
    grouped: BTreeMap<String, OtaLink>,
    reserved: BTreeSet<String>,
    grouped_ids: BTreeSet<String>,
    selected: BTreeMap<String, String>,
    conflicts: BTreeSet<String>,
    inferred: BTreeMap<String, String>,
}

fn eid(event: &Value) -> String {
    pystr(event.get("ota_event_id").unwrap_or(&Value::Null))
}

fn tid(row: &Value) -> String {
    pystr(row.get("transaction_id").unwrap_or(&Value::Null))
}

fn link_card(link: &Value) -> Option<String> {
    let id = if link.is_object() {
        get(link, "transaction_id")
    } else {
        Some(link)
    };
    id.filter(|v| truthy(Some(v))).map(pystr)
}

fn sorted(set: impl IntoIterator<Item = String>) -> Vec<String> {
    set.into_iter()
        .collect::<BTreeSet<_>>()
        .into_iter()
        .collect()
}

/// 발급사·끝자리·방향.
type CardIdentity = (String, String, String);

fn card_identity(row: &Value) -> CardIdentity {
    (
        casefold(text(row, "issuer").trim()),
        first_text(row, &["card_tail", "card_last4"])
            .trim()
            .to_string(),
        Matcher::direction(row),
    )
}

fn four_digits(s: &str) -> bool {
    s.len() == 4 && s.bytes().all(|b| b.is_ascii_digit())
}

/// `_event_group_signature`: 같은 공급자·항목·종류·결제일·통화·금액의 이벤트는 같은 반복 결제 묶음 후보다.
fn signature(event: &Value) -> String {
    let currency = text(event, "currency").trim().to_uppercase();
    let raw = get(
        event,
        if currency == "KRW" {
            "amount_krw"
        } else {
            "amount"
        },
    );
    let amount = raw
        .and_then(|v| Dec::parse(&pystr(v)))
        .and_then(Dec::canonical_positive);
    let key = amount.map_or_else(
        || format!("I{}", text(event, "ota_event_id")),
        |a| format!("A{a}"),
    );
    let field = |k: &str| event.get(k).cloned().unwrap_or(Value::Null);
    json!([
        field("provider"),
        field("item"),
        field("event_type"),
        field("paid_on"),
        currency,
        key
    ])
    .to_string()
}

fn digest(value: &Value) -> String {
    sha256_hex(&python_json_compact(value))
}

/// 후보 카드 행의 digest. Python 후보 행은 `already_linked_event_id: None`이 붙은 사본이라 같은 칸을 넣는다.
fn card_digest(row: &Value) -> String {
    let mut copy = row.clone();
    if let Some(map) = copy.as_object_mut() {
        map.insert("already_linked_event_id".to_string(), Value::Null);
    }
    digest(&copy)
}

fn group_hold(
    id: &str,
    status: &str,
    reason: &str,
    candidates: Vec<String>,
    ota_ids: Vec<String>,
    card_ids: Vec<String>,
) -> OtaLink {
    let mut link = OtaLink::hold(id, status, reason, candidates);
    link.reserved_card_ids = Some(card_ids.clone());
    link.group = Some(GroupShape { ota_ids, card_ids });
    link
}

impl<'a> Run<'a> {
    fn prepare(
        m: Matcher<'a>,
        events: &'a [Value],
        transactions: &'a [Value],
        existing: &'a Map<String, Value>,
        frozen: &[Value],
    ) -> Run<'a> {
        let rows = transactions
            .iter()
            .filter(|r| truthy(get(r, "transaction_id")))
            .map(|r| (tid(r), r))
            .collect();
        let (mut claimed, mut pinned_counts) = (BTreeSet::new(), BTreeMap::new());
        for link in existing.values() {
            if let Some(card) = link_card(link) {
                *pinned_counts.entry(card.clone()).or_insert(0) += 1;
                claimed.insert(card);
            }
        }
        let pins: Vec<Pin> = frozen.iter().map(Pin::parse).collect();
        let mut pin_owners: BTreeMap<String, Vec<usize>> = BTreeMap::new();
        for (at, pin) in pins.iter().enumerate() {
            for card in &pin.card_ids {
                pin_owners.entry(card.clone()).or_default().push(at);
            }
        }
        let events_by_id = events
            .iter()
            .filter(|e| get(e, "ota_event_id").is_some())
            .map(|e| (eid(e), e))
            .collect();
        let (mut raw_options, mut options): (Options, Options) = (BTreeMap::new(), BTreeMap::new());
        for event in events {
            let id = eid(event);
            if existing.get(&id).is_some_and(|l| truthy(Some(l))) {
                continue;
            }
            let raw: Vec<&Value> = m
                .eligible_cards(event, transactions)
                .into_iter()
                .map(|i| &transactions[i])
                .collect();
            let free = raw
                .iter()
                .filter(|row| {
                    let card = tid(row);
                    !claimed.contains(&card)
                        && pin_owners.get(&card).is_none_or(|owners| {
                            owners.iter().all(|&p| pins[p].event_ids.contains(&id))
                        })
                })
                .copied()
                .collect();
            raw_options.insert(id.clone(), raw);
            options.insert(id, free);
        }
        let reserved = pin_owners.keys().cloned().collect();
        Run {
            m,
            events,
            transactions,
            existing,
            pins,
            rows,
            claimed,
            pinned_counts,
            pin_owners,
            events_by_id,
            raw_options,
            options,
            grouped: BTreeMap::new(),
            reserved,
            grouped_ids: BTreeSet::new(),
            selected: BTreeMap::new(),
            conflicts: BTreeSet::new(),
            inferred: BTreeMap::new(),
        }
    }

    fn option_ids(&self, event_id: &str) -> impl Iterator<Item = String> + '_ {
        self.options
            .get(event_id)
            .into_iter()
            .flatten()
            .filter(|r| truthy(get(r, "transaction_id")))
            .map(|r| tid(r))
    }

    fn raw_card_ids(&self, event_id: &str) -> impl Iterator<Item = String> + '_ {
        self.raw_options
            .get(event_id)
            .into_iter()
            .flatten()
            .filter(|r| truthy(get(r, "transaction_id")))
            .map(|r| tid(r))
    }

    fn changed(
        &self,
        id: &str,
        reason: &str,
        pin: &Pin,
        shape: GroupShape,
        proposed: BTreeMap<String, String>,
        snapshot: Value,
    ) -> OtaLink {
        let GroupShape { ota_ids, card_ids } = shape;
        let mut link = group_hold(
            id,
            "HOLD_GROUP_CHANGED",
            reason,
            card_ids.clone(),
            ota_ids,
            card_ids,
        );
        link.group_order_snapshot = Some(snapshot);
        link.frozen = Some(FrozenChange {
            frozen_mapping: pin.mapping_raw.clone(),
            proposed_mapping: proposed,
        });
        link
    }

    /// `_validate_frozen_group_membership`: 근거나 구성이 바뀐 고정 그룹의 구성원과 카드를 보류한다.
    fn validate_frozen(
        &mut self,
        by_signature: &[(String, Vec<&'a Value>)],
        signature_by_event: &BTreeMap<String, String>,
    ) -> BTreeSet<usize> {
        let mut stale_pins = BTreeSet::new();
        for at in 0..self.pins.len() {
            let pin = &self.pins[at];
            let present: Vec<&String> = pin
                .event_ids
                .iter()
                .filter(|i| self.events_by_id.contains_key(*i))
                .collect();
            let signatures: BTreeSet<Option<&String>> = pin
                .event_ids
                .iter()
                .map(|i| signature_by_event.get(i))
                .collect();
            let mut stale = pin.event_ids.is_empty()
                || pin.card_ids.is_empty()
                || present.len() != pin.event_ids.len()
                || signatures.contains(&None)
                || signatures.len() != 1;
            for (id, card) in &pin.mapping {
                if !self
                    .options
                    .get(id)
                    .is_some_and(|rows| rows.iter().any(|r| tid(r) == *card))
                {
                    stale = true;
                }
            }
            if !stale {
                let keys: BTreeSet<_> = pin
                    .event_ids
                    .iter()
                    .flat_map(|i| self.options.get(i).into_iter().flatten())
                    .map(|r| card_identity(r))
                    .collect();
                stale = keys.len() != 1;
            }
            if !stale {
                continue;
            }
            stale_pins.insert(at);
            let mut current: BTreeSet<String> = pin.card_ids.clone();
            for id in &present {
                current.extend(self.raw_card_ids(id));
            }
            let (cards, owners) = (
                sorted(current.clone()),
                sorted(pin.event_ids.iter().cloned()),
            );
            let mut made = Vec::new();
            for id in present {
                if self.existing.contains_key(id) {
                    continue;
                }
                made.push(self.changed(
                    id,
                    "frozen_group_evidence_changed",
                    pin,
                    GroupShape {
                        ota_ids: owners.clone(),
                        card_ids: cards.clone(),
                    },
                    BTreeMap::new(),
                    pin.snapshot.clone(),
                ));
            }
            self.reserved.extend(current);
            for link in made {
                self.grouped.insert(link.ota_event_id.clone(), link);
            }
        }
        for at in 0..self.pins.len() {
            if stale_pins.contains(&at) {
                continue;
            }
            let pin = &self.pins[at];
            let signature = pin
                .event_ids
                .iter()
                .next()
                .and_then(|i| signature_by_event.get(i));
            let members: BTreeSet<String> = by_signature
                .iter()
                .find(|(s, _)| Some(s) == signature)
                .map(|(_, evs)| evs.iter().map(|e| eid(e)).collect())
                .unwrap_or_default();
            if members == pin.event_ids {
                continue;
            }
            stale_pins.insert(at);
            let mut current: BTreeSet<String> = pin.card_ids.clone();
            for id in pin.event_ids.union(&members) {
                current.extend(self.raw_card_ids(id));
            }
            let cards = sorted(current.clone());
            let owners = sorted(pin.event_ids.iter().cloned());
            let mut made = Vec::new();
            for id in pin.event_ids.union(&members) {
                if self.events_by_id.contains_key(id) && !self.existing.contains_key(id) {
                    made.push(self.changed(
                        id,
                        "frozen_group_membership_changed",
                        pin,
                        GroupShape {
                            ota_ids: owners.clone(),
                            card_ids: cards.clone(),
                        },
                        BTreeMap::new(),
                        pin.snapshot.clone(),
                    ));
                }
            }
            self.reserved.extend(current);
            for link in made {
                self.grouped.insert(link.ota_event_id.clone(), link);
            }
        }
        stale_pins
    }

    /// `_build_repeated_group_specs`.
    fn build_specs(&mut self, by_signature: &[(String, Vec<&'a Value>)]) -> Vec<Spec<'a>> {
        let mut specs = Vec::new();
        for (_, group_events) in by_signature {
            let mut by_card_identity: Vec<(CardIdentity, Vec<&'a Value>)> = Vec::new();
            for event in group_events {
                let id = eid(event);
                if self.grouped.contains_key(&id) {
                    continue;
                }
                let keys: BTreeSet<_> = self
                    .options
                    .get(&id)
                    .into_iter()
                    .flatten()
                    .map(|r| card_identity(r))
                    .collect();
                if keys.len() == 1 {
                    let key = keys.into_iter().next().expect("one key");
                    match by_card_identity.iter_mut().find(|(k, _)| *k == key) {
                        Some((_, list)) => list.push(event),
                        None => by_card_identity.push((key, vec![event])),
                    }
                }
            }
            for (identity_key, identity_events) in by_card_identity {
                let event_ids: Vec<String> = identity_events.iter().map(|e| eid(e)).collect();
                let card_ids: BTreeSet<String> = event_ids
                    .iter()
                    .flat_map(|id| self.options.get(id).into_iter().flatten())
                    .filter(|r| {
                        card_identity(r) == identity_key && truthy(get(r, "transaction_id"))
                    })
                    .map(|r| tid(r))
                    .collect();
                if card_ids.is_empty() || (identity_events.len() < 2 && card_ids.len() < 2) {
                    continue;
                }
                if identity_events.len() == 1 {
                    let id = &event_ids[0];
                    let overlaps = self.options.iter().any(|(other, rows)| {
                        other != id && rows.iter().any(|r| card_ids.contains(&tid(r)))
                    });
                    if overlaps {
                        continue;
                    }
                }
                let mut sorted_events = identity_events.clone();
                sorted_events.sort_by_key(|e| (text(e, "booking_ref"), eid(e)));
                let card_rows: BTreeMap<String, &'a Value> = event_ids
                    .iter()
                    .flat_map(|id| self.options.get(id).into_iter().flatten())
                    .filter(|r| card_ids.contains(&tid(r)))
                    .map(|r| (tid(r), *r))
                    .collect();
                let all_ids = sorted(card_ids.iter().cloned());
                let tail_bad = sorted_events.iter().any(|e| {
                    truthy(get(e, "card_last4"))
                        && get(e, "card_last4") != Some(&Value::String(identity_key.1.clone()))
                });
                if identity_key.0.is_empty() || !four_digits(&identity_key.1) || tail_bad {
                    self.reserved.extend(card_ids.iter().cloned());
                    for ota in &sorted_events {
                        self.grouped.insert(
                            eid(ota),
                            group_hold(
                                &eid(ota),
                                "HOLD_AMBIGUOUS",
                                "repeated_group_card_identity_conflict",
                                all_ids.clone(),
                                sorted(event_ids.iter().cloned()),
                                all_ids.clone(),
                            ),
                        );
                    }
                    continue;
                }
                let mut sorted_cards: Vec<&String> = card_rows.keys().collect();
                sorted_cards.sort_by_key(|c| (approval_key(card_rows[*c]), (*c).clone()));
                let edges: Vec<Value> = sorted_events
                    .iter()
                    .flat_map(|item| {
                        let id = eid(item);
                        let mut ids: Vec<String> = self
                            .options
                            .get(&id)
                            .into_iter()
                            .flatten()
                            .map(|r| tid(r))
                            .filter(|c| card_ids.contains(c))
                            .collect();
                        ids.sort();
                        ids.into_iter().map(move |c| json!([id.clone(), c]))
                    })
                    .collect();
                let snapshot = json!({
                    "events": sorted_events.iter().map(|e| json!([eid(e), text(e, "booking_ref")])).collect::<Vec<_>>(),
                    "cards": sorted_cards.iter().map(|c| json!([c, approval_key(card_rows[*c])])).collect::<Vec<_>>(),
                    "event_evidence": sorted_events.iter().map(|e| json!([eid(e), digest(e)])).collect::<Vec<_>>(),
                    "card_evidence": sorted_cards.iter().map(|c| json!([c, card_digest(card_rows[*c])])).collect::<Vec<_>>(),
                    "eligible_edges_digest": digest(&Value::Array(edges)),
                });
                let mut pairs = assign_exact_first(
                    &sorted_events,
                    &self.options,
                    &self.claimed,
                    &BTreeSet::new(),
                );
                let matched = pairs.len();
                let current_events = sorted(event_ids.iter().cloned());
                let current_cards = all_ids.clone();
                let pin = self
                    .pins
                    .iter()
                    .position(|p| current_events.iter().any(|e| p.event_ids.contains(e)));
                if let Some(at) = pin {
                    let p = &self.pins[at];
                    let current_event_set: BTreeSet<String> =
                        current_events.iter().cloned().collect();
                    let current_card_set: BTreeSet<String> =
                        current_cards.iter().cloned().collect();
                    let mapped_events: BTreeSet<String> = p.mapping.keys().cloned().collect();
                    let mapped_cards: BTreeSet<String> = p.mapping.values().cloned().collect();
                    let snapshot_changed = truthy(Some(&p.snapshot)) && p.snapshot != snapshot;
                    if p.event_ids != current_event_set
                        || p.card_ids != current_card_set
                        || snapshot_changed
                        || mapped_events != current_event_set
                        || mapped_cards != current_card_set
                    {
                        let reserved_ids = sorted(p.card_ids.union(&current_card_set).cloned());
                        let owners = sorted(p.event_ids.union(&current_event_set).cloned());
                        let proposed: BTreeMap<String, String> = pairs.iter().cloned().collect();
                        let made: Vec<OtaLink> = sorted_events
                            .iter()
                            .map(|ota| {
                                self.changed(
                                    &eid(ota),
                                    "frozen_group_evidence_changed",
                                    p,
                                    GroupShape {
                                        ota_ids: owners.clone(),
                                        card_ids: reserved_ids.clone(),
                                    },
                                    proposed.clone(),
                                    snapshot.clone(),
                                )
                            })
                            .collect();
                        self.reserved.extend(reserved_ids);
                        for link in made {
                            self.grouped.insert(link.ota_event_id.clone(), link);
                        }
                        continue;
                    }
                    pairs = p
                        .mapping
                        .iter()
                        .map(|(a, b)| (a.clone(), b.clone()))
                        .collect();
                }
                specs.push(Spec {
                    events: sorted_events,
                    event_ids,
                    card_ids: all_ids,
                    pairs,
                    matched,
                    card_rows,
                    pin,
                    snapshot,
                });
            }
        }
        specs
    }

    /// `_resolve_repeated_group_specs`: 묶음끼리·단건과 후보 카드가 겹치면 연결된 성분 전체를 보류한다.
    fn resolve_specs(&mut self, specs: Vec<Spec<'a>>) {
        let mut group_events: BTreeSet<String> = BTreeSet::new();
        let mut card_owners: BTreeMap<&str, BTreeSet<usize>> = BTreeMap::new();
        for (at, spec) in specs.iter().enumerate() {
            group_events.extend(spec.events.iter().map(|e| eid(e)));
            for card in &spec.card_ids {
                card_owners.entry(card).or_default().insert(at);
            }
        }
        let mut collisions: BTreeSet<usize> = card_owners
            .values()
            .filter(|o| o.len() > 1)
            .flatten()
            .copied()
            .collect();
        let known: BTreeSet<&String> = group_events.iter().chain(self.grouped.keys()).collect();
        for (id, rows) in &self.options {
            if known.contains(id) {
                continue;
            }
            for row in rows {
                if let Some(owners) = card_owners.get(tid(row).as_str()) {
                    collisions.extend(owners);
                }
            }
        }
        let mut grouped_ids: BTreeSet<String> = group_events.clone();
        grouped_ids.extend(self.grouped.keys().cloned());
        let mut made: Vec<OtaLink> = Vec::new();
        let mut reserve: Vec<String> = Vec::new();
        let mut claim: Vec<String> = Vec::new();
        for (at, spec) in specs.iter().enumerate() {
            let owners = sorted(spec.event_ids.iter().cloned());
            let (cards, n_events) = (spec.card_ids.clone(), spec.events.len());
            let hold = |status: &str, reason: &str, ota: &Value| {
                group_hold(
                    &eid(ota),
                    status,
                    reason,
                    cards.clone(),
                    owners.clone(),
                    cards.clone(),
                )
            };
            if collisions.contains(&at) {
                made.extend(
                    spec.events
                        .iter()
                        .map(|o| hold("HOLD_AMBIGUOUS", "overlapping_global_group_candidates", o)),
                );
                reserve.extend(cards.clone());
                continue;
            }
            if spec.matched < n_events || spec.matched < cards.len() {
                reserve.extend(cards.clone());
                let status = if n_events > 1 && cards.len() == 1 {
                    "HOLD_AMBIGUOUS"
                } else {
                    "HOLD_PARTIAL_GROUP"
                };
                for ota in &spec.events {
                    let mut link = hold(status, "partial_repeated_payment_group", ota);
                    link.matched = Some(MatchedCounts {
                        matched: spec.matched,
                        unmatched_ota: n_events.saturating_sub(spec.matched),
                        unmatched_card: cards.len().saturating_sub(spec.matched),
                    });
                    made.push(link);
                }
                continue;
            }
            let selected: BTreeMap<&str, &str> = spec
                .pairs
                .iter()
                .map(|(a, b)| (a.as_str(), b.as_str()))
                .collect();
            let basis = if spec.pin.is_some() {
                "frozen_user_confirmed_order"
            } else {
                "auto_stable_order"
            };
            for ota in &spec.events {
                let id = eid(ota);
                let card = selected[id.as_str()];
                let row = spec.card_rows[card];
                let mut link = OtaLink::base(
                    &id,
                    "MATCHED_AUTO",
                    basis,
                    LinkKind::GroupOrder {
                        frozen: spec.pin.is_some(),
                    },
                );
                link.transaction_id = Some(card.to_string());
                link.candidates = vec![card.to_string()];
                link.allocation_basis = Some(basis);
                link.group_order_frozen = Some(spec.pin.is_some());
                link.individual_payment_evidence = Some(false);
                link.group = Some(GroupShape {
                    ota_ids: owners.clone(),
                    card_ids: cards.clone(),
                });
                link.group_order_snapshot = Some(spec.snapshot.clone());
                let (card_amount, event_amount) =
                    (Matcher::card_amount(row), Matcher::event_amount(ota));
                let delta = match (card_amount, event_amount) {
                    (Some(c), Some(e)) if c != e => c.checked_sub(e).and_then(Dec::trunc),
                    _ => None,
                };
                link.delta = Some((delta, Some(false)));
                made.push(link);
                claim.push(card.to_string());
            }
        }
        self.reserved.extend(reserve);
        self.claimed.extend(claim);
        for link in made {
            self.grouped.insert(link.ota_event_id.clone(), link);
        }
        self.grouped_ids = grouped_ids;
    }

    /// `_allocate_repeated_groups`.
    fn allocate_groups(&mut self) {
        let mut by_signature: Vec<(String, Vec<&'a Value>)> = Vec::new();
        let mut signature_by_event = BTreeMap::new();
        let events = self.events;
        for event in events {
            let id = eid(event);
            if self.existing.contains_key(&id)
                || !Matcher::event_is_paid(event)
                || !truthy(get(event, "paid_on"))
            {
                continue;
            }
            let sig = signature(event);
            signature_by_event.insert(id, sig.clone());
            match by_signature.iter_mut().find(|(s, _)| *s == sig) {
                Some((_, list)) => list.push(event),
                None => by_signature.push((sig, vec![event])),
            }
        }
        let stale = self.validate_frozen(&by_signature, &signature_by_event);
        let _ = stale;
        let specs = self.build_specs(&by_signature);
        self.resolve_specs(specs);
    }

    /// `_select_singleton_payments`: 묶음이 아닌 결제 확인 이벤트를 하나의 전역 배정 문제로 푼다.
    fn select_singletons(&mut self) {
        let mut singletons: Vec<&Value> = self
            .events
            .iter()
            .filter(|e| {
                let id = eid(e);
                !self.grouped_ids.contains(&id)
                    && !self.existing.contains_key(&id)
                    && Matcher::event_is_paid(e)
                    && (truthy(get(e, "paid_on"))
                        || self.options.get(&id).is_some_and(|o| !o.is_empty()))
            })
            .collect();
        singletons.sort_by_key(|e| eid(e));
        let unavailable: BTreeSet<String> = self.claimed.union(&self.reserved).cloned().collect();
        let pairs = assign_exact_first(&singletons, &self.options, &unavailable, &BTreeSet::new());
        self.conflicts =
            ambiguous_optimal_singletons(&singletons, &self.options, &pairs, &unavailable);
        self.selected = pairs.into_iter().collect();
        self.inferred = self
            .m
            .inferred_pairs(self.events, self.transactions, &unavailable);
    }

    /// `_pinned_link_result`: 기존 수동·옛 포털 연결을 검증만 하고 그대로 둔다.
    fn pinned(&self, event: &Value) -> Option<OtaLink> {
        let id = eid(event);
        let link = self.existing.get(&id).filter(|l| truthy(Some(l)))?;
        let card = link_card(link);
        let status = if link.is_object() {
            match link.get("status") {
                None => Some("MATCHED_USER".to_string()),
                Some(Value::String(s)) => Some(s.clone()),
                Some(_) => None,
            }
        } else {
            Some("MATCHED_USER".to_string())
        };
        let count = card
            .as_ref()
            .map_or(0, |c| self.pinned_counts.get(c).copied().unwrap_or(0));
        if count > 1 {
            return Some(OtaLink::hold(
                &id,
                "HOLD_AMBIGUOUS",
                "pinned_global_one_to_one_collision",
                card.into_iter().collect(),
            ));
        }
        let conflict =
            |reason: &str| OtaLink::hold(&id, "HOLD_EVIDENCE_CONFLICT", reason, Vec::new());
        let Some(status) = status.filter(|s| s == "MATCHED_AUTO" || s == "MATCHED_USER") else {
            return Some(conflict("invalid_existing_link_status"));
        };
        if link.is_object()
            && truthy(get(link, "legacy_exact"))
            && !self.legacy_valid(event, link, card.as_deref())
        {
            return Some(conflict("legacy_exact_binding_validation_failed"));
        }
        let mut out = OtaLink::base(&id, &status, "pinned_existing_link", LinkKind::Pinned);
        out.transaction_id = card;
        Some(out)
    }

    fn legacy_valid(&self, event: &Value, link: &Value, card: Option<&str>) -> bool {
        let Some(row) = card.and_then(|c| self.rows.get(c)) else {
            return false;
        };
        if get(link, "source_digest") != get(event, "source_digest")
            || !Matcher::event_is_paid(event)
        {
            return false;
        }
        let expected = if is_str(get(event, "event_type"), "refund") {
            "refund"
        } else {
            "purchase"
        };
        let hint = text(event, "card_last4");
        let actual = first_text(row, &["card_tail", "card_last4"]);
        let digests = |v: &Value| -> BTreeSet<String> {
            get(v, "source_digests")
                .and_then(Value::as_array)
                .map(|a| a.iter().map(pystr).collect())
                .unwrap_or_default()
        };
        let (old, current) = (digests(link), digests(event));
        self.m.amount_matches(event, row)
            && Matcher::direction(row) == expected
            && (hint.is_empty() || actual.ends_with(&hint))
            && !old.is_empty()
            && !current.is_empty()
            && old.intersection(&current).next().is_some()
    }

    /// 후보가 하나도 없을 때(`not options`)의 보류. 점유·고정 그룹에 막힌 후보가 있으면 그 사유가 먼저다.
    fn no_option_hold(&self, event: &Value, id: &str) -> OtaLink {
        let blocked: BTreeSet<String> = self
            .raw_options
            .get(id)
            .into_iter()
            .flatten()
            .filter(|r| {
                let card = tid(r);
                self.claimed.contains(&card)
                    || self
                        .pin_owners
                        .get(&card)
                        .into_iter()
                        .flatten()
                        .any(|&p| !self.pins[p].event_ids.contains(id))
            })
            .filter(|r| truthy(get(r, "transaction_id")))
            .map(|r| tid(r))
            .collect();
        if !blocked.is_empty() {
            let ids: Vec<String> = blocked.into_iter().collect();
            let mut link = OtaLink::hold(
                id,
                "HOLD_AMBIGUOUS",
                "candidate_cards_reserved_by_existing_or_frozen_link",
                ids.clone(),
            );
            link.reserved_card_ids = Some(ids);
            return link;
        }
        let is_claimed = |r: &Value| self.claimed.contains(&tid(r));
        let stage = self.m.no_card_hold(event, self.transactions, &is_claimed);
        match stage {
            super::Stage::Hold(h) => OtaLink::hold(
                id,
                h.status,
                h.reason,
                h.candidates.iter().map(pystr).collect(),
            ),
            _ => unreachable!("no_card_hold always holds"),
        }
    }

    /// `_assemble_ota_match_results`: 이벤트 입력 순서대로 연결·근거·단건 결과를 정한다.
    fn assemble(&mut self) -> Vec<OtaLink> {
        let events = self.events;
        let mut results = Vec::with_capacity(events.len());
        for event in events {
            let id = eid(event);
            if let Some(link) = self.grouped.get(&id) {
                results.push(link.clone());
                continue;
            }
            if let Some(link) = self.pinned(event) {
                results.push(link);
                continue;
            }
            results.push(self.single(event, &id));
        }
        let by_id = &self.events_by_id;
        attach_relations(
            by_id,
            &self.rows,
            &self.options,
            &mut results,
            self.existing,
        );
        results
    }

    fn single(&mut self, event: &Value, id: &str) -> OtaLink {
        if !Matcher::event_is_paid(event) {
            let status = Matcher::unpaid_status(event);
            return OtaLink::hold(id, status, "no_verified_paid_evidence", Vec::new());
        }
        let refund_ok = is_str(get(event, "refund_status"), "refunded")
            || is_str(get(event, "refund_status"), "refund_completed");
        if is_str(get(event, "event_type"), "refund") && !refund_ok {
            return OtaLink::hold(
                id,
                "HOLD_EVIDENCE_CONFLICT",
                "refund_not_explicitly_verified",
                Vec::new(),
            );
        }
        if let Some(card) = self.inferred.get(id) {
            let mut link = OtaLink::base(id, "MATCHED_AUTO", BASIS, LinkKind::Inferred);
            link.transaction_id = Some(card.clone());
            link.candidates = vec![card.clone()];
            link.allocation_basis = Some(BASIS);
            link.payment_date_verified = Some(false);
            return link;
        }
        let options: Vec<&Value> = self.options.get(id).cloned().unwrap_or_default();
        if !truthy(get(event, "paid_on")) && options.is_empty() {
            return OtaLink::hold(
                id,
                "HOLD_DATE_UNKNOWN",
                "payment_date_not_in_source",
                Vec::new(),
            );
        }
        let candidates: Vec<String> = options.iter().map(|r| tid(r)).collect();
        if self.conflicts.contains(id) {
            let reserved = sorted(
                self.conflicts
                    .iter()
                    .flat_map(|c| self.option_ids(c))
                    .collect::<Vec<_>>(),
            );
            self.reserved.extend(reserved.iter().cloned());
            let mut link = OtaLink::hold(
                id,
                "HOLD_AMBIGUOUS",
                "equal_optimum_global_singleton_allocations",
                candidates,
            );
            link.reserved_card_ids = Some(reserved);
            return link;
        }
        if options.iter().any(|r| self.reserved.contains(&tid(r))) {
            let reserved = sorted(
                candidates
                    .iter()
                    .filter(|c| self.reserved.contains(*c))
                    .cloned(),
            );
            let mut link = OtaLink::hold(
                id,
                "HOLD_AMBIGUOUS",
                "card_reserved_by_partial_or_ambiguous_group",
                candidates,
            );
            link.reserved_card_ids = Some(reserved);
            return link;
        }
        let free: Vec<&Value> = match self.selected.get(id) {
            Some(card) => options
                .iter()
                .filter(|r| tid(r) == *card)
                .copied()
                .collect(),
            // Python은 배정에서 탈락한 이벤트가 다른 이벤트에 배정된 카드를 먼저 집을 수 있다(한 카드 두 점유).
            // 한 카드는 한 연결에만 점유되므로 배정된 카드는 제외하고 충돌로 보류한다.
            None => options
                .iter()
                .filter(|r| {
                    let card = tid(r);
                    !self.claimed.contains(&card) && !self.selected.values().any(|c| *c == card)
                })
                .copied()
                .collect(),
        };
        if options.is_empty() {
            return self.no_option_hold(event, id);
        }
        let [row] = free.as_slice() else {
            return OtaLink::hold(
                id,
                "HOLD_AMBIGUOUS",
                "global_one_to_one_collision",
                candidates,
            );
        };
        let card = tid(row);
        self.claimed.insert(card.clone());
        let unique = self.m.unique_match(event, row);
        let mut link = OtaLink::base(id, "MATCHED_AUTO", unique.reason, LinkKind::Exact);
        link.transaction_id = Some(card.clone());
        link.candidates = vec![card];
        link.payment_date_verified = Some(truthy(get(event, "paid_on")));
        link.delta = Some((unique.rule_delta_krw, unique.discount_cause_confirmed));
        link
    }
}

impl Matcher<'_> {
    /// `match_ota_payment_events`. `existing_links`는 이벤트 id → 기존 연결, `frozen_groups`는 사용자가 확인한 묶음이다.
    /// 입력은 읽기만 한다.
    pub fn match_events(
        &self,
        events: &[Value],
        transactions: &[Value],
        existing_links: &Map<String, Value>,
        frozen_groups: &[Value],
    ) -> Vec<OtaLink> {
        let mut run = Run::prepare(*self, events, transactions, existing_links, frozen_groups);
        run.allocate_groups();
        run.select_singletons();
        run.assemble()
    }
}

/// `bind_legacy_portal_links`: 이미 검증된 포털 연결을 예약·원본·카드·금액 근거로 고정한다. 추측한 결제일은 쓰지 않는다.
/// 반환은 이벤트 id → 고정 연결(`existing_links`에 그대로 넣을 수 있는 모양)이다.
pub fn bind_legacy_portal_links(events: &[Value], legacy_links: &[Value]) -> Map<String, Value> {
    let mut bound = Map::new();
    for old in legacy_links {
        if !truthy(get(old, "verified_exact"))
            || !is_str(get(old, "evidence_kind"), "portal_payment_claim")
        {
            continue;
        }
        let currency = old.get("currency").cloned().unwrap_or_else(|| json!("KRW"));
        let found: Vec<&Value> = events
            .iter()
            .filter(|e| {
                is_str(get(e, "provider"), "agoda")
                    && get(e, "booking_ref") == get(old, "booking_ref")
                    && get(e, "source_digest") == get(old, "source_digest")
                    && get(e, "card_last4") == get(old, "card_last4")
                    && pystr(e.get("amount").unwrap_or(&Value::Null))
                        == pystr(old.get("amount").unwrap_or(&Value::Null))
                    && e.get("currency").unwrap_or(&Value::Null) == &currency
            })
            .collect();
        if let [event] = found.as_slice() {
            let digests: BTreeSet<String> =
                match get(old, "source_digests").filter(|v| truthy(Some(v))) {
                    Some(Value::Array(a)) => a.iter().map(pystr).collect(),
                    _ => BTreeSet::from([pystr(&old["source_digest"])]),
                };
            bound.insert(
                text(event, "ota_event_id"),
                json!({
                    "transaction_id": old["transaction_id"],
                    "status": "MATCHED_AUTO",
                    "legacy_exact": true,
                    "source_digest": old["source_digest"],
                    "source_digests": digests,
                }),
            );
        }
    }
    bound
}
