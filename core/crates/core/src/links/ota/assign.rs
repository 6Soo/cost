//! 정확 연결 우선 단건 배정과 모호 최적 단건 검사. 원본: `_assign_exact_first`, `_ambiguous_optimal_singletons`.
//!
//! 최대 개수 → 정확 간선 → 승인번호·ID 안정 순서로 최소 비용 유량을 구한다. 간선을 만드는 순서와 SPFA 순회가
//! 같은 해를 고르므로 Python과 같은 순서로 쌓는다.

use super::Matcher;
use super::pyval::{first_text, get, pystr, text, truthy};
use serde_json::Value;
use std::collections::{BTreeMap, BTreeSet, VecDeque};

/// 이벤트 id → 승인 조건을 통과한 점유되지 않은 카드(입력 순서).
pub(super) type Options<'a> = BTreeMap<String, Vec<&'a Value>>;

struct Edge {
    to: usize,
    rev: usize,
    cap: i64,
    cost: i64,
}

fn add_edge(
    graph: &mut [Vec<Edge>],
    from: usize,
    to: usize,
    cap: i64,
    cost: i64,
) -> (usize, usize) {
    let (forward_at, reverse_at) = (graph[from].len(), graph[to].len());
    graph[from].push(Edge {
        to,
        rev: reverse_at,
        cap,
        cost,
    });
    graph[to].push(Edge {
        to: from,
        rev: forward_at,
        cap: 0,
        cost: -cost,
    });
    (from, forward_at)
}

/// 통화가 KRW가 아니거나 이벤트·카드 금액이 같은가(정확 간선).
fn exact_edge(event: &Value, row: &Value) -> bool {
    text(event, "currency").to_uppercase() != "KRW"
        || Matcher::event_amount(event) == Matcher::card_amount(row)
}

pub(super) fn approval_key(row: &Value) -> String {
    first_text(
        row,
        &[
            "approval_number",
            "authorization_number",
            "authorization_id",
        ],
    )
}

pub(super) fn assign_exact_first(
    events: &[&Value],
    options: &Options,
    unavailable: &BTreeSet<String>,
    excluded: &BTreeSet<(String, String)>,
) -> Vec<(String, String)> {
    let mut ordered: Vec<&Value> = events.to_vec();
    ordered.sort_by_key(|e| (text(e, "booking_ref"), text(e, "ota_event_id")));
    let event_ids: Vec<String> = ordered.iter().map(|e| text(e, "ota_event_id")).collect();
    let mut row_by_card: BTreeMap<String, &Value> = BTreeMap::new();
    for id in &event_ids {
        for row in options.get(id).into_iter().flatten() {
            if let Some(card) = get(row, "transaction_id").filter(|v| truthy(Some(v))) {
                row_by_card.insert(pystr(card), row);
            }
        }
    }
    let mut card_ids: Vec<String> = row_by_card
        .keys()
        .filter(|id| !unavailable.contains(*id))
        .cloned()
        .collect();
    card_ids.sort_by_key(|id| (approval_key(row_by_card[id]), id.clone()));
    if event_ids.is_empty() || card_ids.is_empty() {
        return Vec::new();
    }
    let (n, c) = (event_ids.len() as i64, card_ids.len() as i64);
    let source = 0;
    let event_base = 1;
    let card_base = event_base + event_ids.len();
    let sink = card_base + card_ids.len();
    let mut graph: Vec<Vec<Edge>> = (0..=sink).map(|_| Vec::new()).collect();
    let card_index: BTreeMap<&str, usize> = card_ids
        .iter()
        .enumerate()
        .map(|(i, id)| (id.as_str(), i))
        .collect();
    let exact_priority = (c - 1) * n * (n + 1) / 2 + 1;
    let mut chosen: BTreeMap<(String, String), (usize, usize)> = BTreeMap::new();
    for (index, identity) in event_ids.iter().enumerate() {
        add_edge(&mut graph, source, event_base + index, 1, 0);
        for row in options.get(identity).into_iter().flatten() {
            let card_id = text(row, "transaction_id");
            let Some(&at) = card_index.get(card_id.as_str()) else {
                continue;
            };
            if excluded.contains(&(identity.clone(), card_id.clone())) {
                continue;
            }
            let stable = at as i64 * (n - index as i64);
            let cost = stable
                - if exact_edge(ordered[index], row) {
                    exact_priority
                } else {
                    0
                };
            let handle = add_edge(&mut graph, event_base + index, card_base + at, 1, cost);
            chosen.insert((identity.clone(), card_id), handle);
        }
    }
    for index in 0..card_ids.len() {
        add_edge(&mut graph, card_base + index, sink, 1, 0);
    }
    loop {
        let mut distance: Vec<Option<i64>> = vec![None; graph.len()];
        let mut previous: Vec<Option<(usize, usize)>> = vec![None; graph.len()];
        let mut queued = vec![false; graph.len()];
        let mut queue = VecDeque::from([source]);
        distance[source] = Some(0);
        queued[source] = true;
        while let Some(node) = queue.pop_front() {
            queued[node] = false;
            let base = distance[node].unwrap_or(0);
            for (at, edge) in graph[node].iter().enumerate() {
                if edge.cap <= 0 {
                    continue;
                }
                let next = base + edge.cost;
                if distance[edge.to].is_none_or(|d| next < d) {
                    distance[edge.to] = Some(next);
                    previous[edge.to] = Some((node, at));
                    if !queued[edge.to] {
                        queue.push_back(edge.to);
                        queued[edge.to] = true;
                    }
                }
            }
        }
        if previous[sink].is_none() {
            break;
        }
        let mut node = sink;
        while node != source {
            let (parent, at) = previous[node].expect("path");
            graph[parent][at].cap -= 1;
            let rev = graph[parent][at].rev;
            graph[node][rev].cap += 1;
            node = parent;
        }
    }
    chosen
        .into_iter()
        .filter(|(_, (from, at))| graph[*from][*at].cap == 0)
        .map(|(pair, _)| pair)
        .collect()
}

fn row_of<'a>(options: &Options<'a>, identity: &str, card_id: &str) -> Option<&'a Value> {
    options
        .get(identity)?
        .iter()
        .find(|row| pystr(row.get("transaction_id").unwrap_or(&Value::Null)) == card_id)
        .copied()
}

/// 최대 개수 최적 배정이 하나가 아닌 단건 이벤트(이벤트 id).
pub(super) fn ambiguous_optimal_singletons(
    events: &[&Value],
    options: &Options,
    selected: &[(String, String)],
    unavailable: &BTreeSet<String>,
) -> BTreeSet<String> {
    let event_by_id: BTreeMap<String, &Value> = events
        .iter()
        .map(|e| (text(e, "ota_event_id"), *e))
        .collect();
    let usable = |row: &Value| {
        let id = text(row, "transaction_id");
        (!id.is_empty() && !unavailable.contains(&id)).then_some(id)
    };
    let mut card_to_events: BTreeMap<String, BTreeSet<String>> = BTreeMap::new();
    for identity in event_by_id.keys() {
        for row in options.get(identity).into_iter().flatten() {
            if let Some(card) = usable(row) {
                card_to_events
                    .entry(card)
                    .or_default()
                    .insert(identity.clone());
            }
        }
    }
    let mut adjacency: BTreeMap<&str, BTreeSet<&str>> = BTreeMap::new();
    for identities in card_to_events.values() {
        for identity in identities {
            adjacency.entry(identity).or_default().extend(
                identities
                    .iter()
                    .filter(|other| *other != identity)
                    .map(String::as_str),
            );
        }
    }
    let mut unresolved: BTreeSet<&str> = event_by_id.keys().map(String::as_str).collect();
    let mut ambiguous = BTreeSet::new();
    while let Some(root) = unresolved.pop_first() {
        let mut component = BTreeSet::from([root]);
        let mut stack = vec![root];
        while let Some(current) = stack.pop() {
            for neighbor in adjacency.get(current).into_iter().flatten() {
                if unresolved.remove(neighbor) {
                    component.insert(*neighbor);
                    stack.push(neighbor);
                }
            }
        }
        let root_cards: BTreeSet<String> = options
            .get(root)
            .into_iter()
            .flatten()
            .filter_map(|row| usable(row))
            .collect();
        if component.len() == 1 && root_cards.len() <= 1 {
            continue;
        }
        let component_events: Vec<&Value> = component.iter().map(|id| event_by_id[*id]).collect();
        let current: Vec<&(String, String)> = selected
            .iter()
            .filter(|(identity, _)| component.contains(identity.as_str()))
            .collect();
        let exact_count = |pairs: &[(&str, &str)]| {
            pairs
                .iter()
                .filter(|(identity, card)| {
                    let event = event_by_id[*identity];
                    text(event, "currency").to_uppercase() != "KRW"
                        || row_of(options, identity, card).is_some_and(|row| {
                            Matcher::event_amount(event) == Matcher::card_amount(row)
                        })
                })
                .count()
        };
        let current_pairs: Vec<(&str, &str)> = current
            .iter()
            .map(|(a, b)| (a.as_str(), b.as_str()))
            .collect();
        let (current_count, current_exact) = (current_pairs.len(), exact_count(&current_pairs));
        for pair in &current {
            let excluded = BTreeSet::from([(*pair).clone()]);
            let alternative =
                assign_exact_first(&component_events, options, unavailable, &excluded);
            let alt_pairs: Vec<(&str, &str)> = alternative
                .iter()
                .map(|(a, b)| (a.as_str(), b.as_str()))
                .collect();
            if alt_pairs.len() == current_count && exact_count(&alt_pairs) == current_exact {
                ambiguous.extend(component.iter().map(|id| (*id).to_string()));
            }
        }
    }
    ambiguous
}
