//! Gotogate/Mytrip flight confirmations as reservation-only facts — retirement unit 3-b (third).
//!
//! Like Airbnb, `collect()` settles the whole slice: matching, aggregation, the event with its
//! amount and its ids. The shared mail helpers (`authenticated_headers`, `message_text`,
//! `sent_day`) stay in the Python bridge as boundary values.
//!
//! Quirks reproduced deliberately: one invalid leg rejects the whole message; the amount set is
//! over the **original strings** (`.00` only, `\b` after KRW); a confirmation outranks a
//! withdrawal because its pattern is fully anchored; a withdrawal reaches every order number in
//! its body and is sticky.

use std::collections::{BTreeMap, BTreeSet};

use regex::Regex;
use serde::Deserialize;
use serde_json::{Value, json};

use super::pyre::{PY_SPACE, read_digits, strip, word_boundary_after};
use crate::digest::{python_json_compact, sha256_hex};

const ORDER: &str = r"\p{Nd}{4}-\p{Nd}{3}-\p{Nd}{3}";

/// `^여행이\s*확정되었습니다\.\s*주문\s*번호\s*(ORDER)\s*$`.
///
/// Python's `$` also matches just before one trailing newline, unlike the crate's, so the tail
/// is spelled out; the `^` becomes an explicit start-of-text check.
fn confirmed_pattern() -> Regex {
    Regex::new(&format!(
        r"여행이{PY_SPACE}*확정되었습니다\.{PY_SPACE}*주문{PY_SPACE}*번호{PY_SPACE}*({ORDER}){PY_SPACE}*(?:\n?\z)"
    ))
    .unwrap()
}

/// `취소|환불|cancel|refund`, `re.I`.
fn withdrawn_pattern() -> Regex {
    Regex::new(r"(?i)취소|환불|cancel|refund").unwrap()
}

/// `(?:가는|오는)\s*편\s*[•·]\s*(\d{4})년\s*(\d{1,2})월\s*(\d{1,2})일`.
fn leg_pattern() -> Regex {
    Regex::new(&format!(
        r"(?:가는|오는){PY_SPACE}*편{PY_SPACE}*[•·]{PY_SPACE}*(\p{{Nd}}{{4}})년{PY_SPACE}*(\p{{Nd}}{{1,2}})월{PY_SPACE}*(\p{{Nd}}{{1,2}})일"
    ))
    .unwrap()
}

/// `합계\s*([0-9][0-9,]*)(?:\.00)?\s*KRW` — the trailing `\b` is applied afterwards.
fn total_pattern() -> Regex {
    Regex::new(&format!(
        r"합계{PY_SPACE}*([0-9][0-9,]*)(?:\.00)?{PY_SPACE}*KRW"
    ))
    .unwrap()
}

fn order_pattern() -> Regex {
    Regex::new(ORDER).unwrap()
}

/// One message as the Python bridge presents it.
#[derive(Debug, Clone, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct MytripMessage {
    pub message: Value,
    /// `str(headers.get('subject') or '')` when authenticated, `None` otherwise.
    pub subject: Option<String>,
    /// `message_text(message)` — the body only.
    pub raw_text: String,
    /// `sent_day(message, headers)` in KST, ISO date, or `None`.
    pub sent_day: Option<String>,
}

#[derive(Debug, Clone, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct MytripInput {
    pub messages: BTreeMap<String, MytripMessage>,
    pub inventory: Vec<Value>,
}

/// `collect(messages, inventory)`: order-ordered events.
pub fn mytrip_events(input: &MytripInput) -> Vec<Value> {
    let confirmed = confirmed_pattern();
    let withdrawn = withdrawn_pattern();
    let order_re = order_pattern();
    let mut observed: BTreeMap<String, Vec<(String, Value, String, String)>> = BTreeMap::new();
    let mut withdrawn_orders: BTreeSet<String> = BTreeSet::new();
    for (message_id, record) in &input.messages {
        let Some(subject) = record.subject.as_deref() else {
            continue;
        };
        let subject = strip(subject);
        let Some(captures) = confirmed_at_start(&confirmed, subject) else {
            if withdrawn.is_match(subject) {
                withdrawn_orders.extend(orders(&order_re, &record.raw_text));
            }
            continue;
        };
        let order = captures.get(1).unwrap().as_str().to_owned();
        let Some(facts) = facts(&order_re, &record.raw_text, &order) else {
            continue;
        };
        let Some(sent_day) = record.sent_day.as_deref() else {
            continue;
        };
        // The tuple `(period, amount)` is one unit so the conflict set compares both parts.
        observed.entry(order).or_default().push((
            message_id.clone(),
            facts,
            sent_day.to_owned(),
            sha256_hex(&python_json_compact(&record.message)),
        ));
    }
    let mut events = Vec::new();
    for (order, rows) in observed {
        let distinct: BTreeSet<String> = rows
            .iter()
            .map(|(_, facts, _, _)| python_json_compact(facts))
            .collect();
        let conflict = distinct.len() != 1;
        let source_ids: Vec<String> = rows
            .iter()
            .map(|(id, _, _, _)| format!("mail:{id}"))
            .collect();
        let last = rows.last().unwrap().1.clone();
        let observed_on: BTreeSet<String> =
            rows.iter().map(|(_, _, sent, _)| sent.clone()).collect();
        let mut event = json!({
            "provider": "gotogate",
            "booking_ref": order,
            "event_type": "reservation",
            "item": "항공료",
            "paid_on": Value::Null,
            "paid_on_semantics": "missing",
            "card_last4": Value::Null,
            "amount": if conflict { Value::Null } else { last["amount"].clone() },
            "amount_krw": if conflict { Value::Null } else { last["amount"].clone() },
            "currency": if conflict { Value::Null } else { json!("KRW") },
            "service_period": if conflict { Value::Null } else { last["period"].clone() },
            "service_period_conflict": conflict,
            "reservation_status": if withdrawn_orders.contains(&order) { "cancelled" } else { "observed" },
            "payment_status": "unknown",
            "evidence_status": "reservation_only",
            "evidence_kind": "authenticated_reservation_mail",
            "reservation_observed_on": observed_on.into_iter().collect::<Vec<_>>(),
            "source_digest": rows.last().unwrap().3.clone(),
            "source_digests": rows.iter().map(|(_, _, _, d)| d.clone()).collect::<Vec<_>>(),
            "source_ids": source_ids,
            "identity_source_ids": source_ids,
            "source_inventory": input.inventory.clone(),
        });
        let identity = format!("gotogate:{order}");
        event["source_lineage_ids"] = json!([identity.clone()]);
        let mut observations: Vec<String> = source_ids
            .iter()
            .map(|source| {
                format!(
                    "obs_{}",
                    sha256_hex(&python_json_compact(&json!([identity, source])))
                )
            })
            .collect();
        observations.sort();
        event["observation_ids"] = json!(observations);
        event["ota_event_id"] = json!(format!(
            "ota_{}",
            sha256_hex(&python_json_compact(&json!([identity])))
        ));
        events.push(event);
    }
    events
}

/// Python `CONFIRMED.match(subject.strip())` — `match` anchors at position 0.
fn confirmed_at_start<'t>(pattern: &Regex, subject: &'t str) -> Option<regex::Captures<'t>> {
    let captures = pattern.captures(subject)?;
    let whole = captures.get(0)?;
    (whole.start() == 0).then_some(captures)
}

/// `_facts(text, order)`: every order number in the body must be the confirmed one.
///
/// `Python` returns `(period_dict, amount)`, flattened here into one object so the caller can
/// compare both parts with a single canonical form.
fn facts(order_re: &Regex, text: &str, order: &str) -> Option<Value> {
    let found: BTreeSet<String> = orders(order_re, text).into_iter().collect();
    if found.len() != 1 || !found.contains(order) {
        return None;
    }
    let leg_re = leg_pattern();
    let mut legs: BTreeSet<time::Date> = BTreeSet::new();
    for captures in leg_re.captures_iter(text) {
        let year = read_digits(captures.get(1)?.as_str());
        let month = read_digits(captures.get(2)?.as_str());
        let day = read_digits(captures.get(3)?.as_str());
        // Python's `date()` raises ValueError on an impossible date, rejecting the whole message.
        legs.insert(calendar(year, month, day)?);
    }
    let totals = total_strings(text);
    if legs.is_empty() || totals.len() != 1 {
        return None;
    }
    let first = *legs.iter().next()?;
    let last = *legs.iter().next_back()?;
    if (last - first).whole_days() > 366 {
        return None;
    }
    let amount = amount_value(&totals[0])?;
    if amount <= 0 {
        return None;
    }
    Some(json!({
        "period": {"starts_on": crate::dates::iso(first), "ends_on": crate::dates::iso(last)},
        "amount": amount,
    }))
}

fn orders(pattern: &Regex, text: &str) -> Vec<String> {
    pattern
        .find_iter(text)
        .map(|m| m.as_str().to_owned())
        .collect()
}

/// `set(TOTAL.findall(text))` over the original strings, with Python's trailing `\b`.
fn total_strings(text: &str) -> Vec<String> {
    let pattern = total_pattern();
    let mut found: Vec<String> = Vec::new();
    for captures in pattern.captures_iter(text) {
        let whole = captures.get(0).unwrap();
        if !word_boundary_after(text, whole.end()) {
            continue;
        }
        let value = captures.get(1).unwrap().as_str().to_owned();
        if !found.contains(&value) {
            found.push(value);
        }
    }
    found
}

/// `int(value.replace(',', ''))` — the pattern already limits this to ASCII digits.
fn amount_value(text: &str) -> Option<i64> {
    let mut number: i64 = 0;
    let mut digits = 0;
    for c in text.chars().filter(|c| *c != ',') {
        let digit = i64::from(c.to_digit(10)?);
        number = number.checked_mul(10)?.checked_add(digit)?;
        digits += 1;
    }
    (digits > 0).then_some(number)
}

/// `date(year, month, day)` with Python's `ValueError` as `None`.
fn calendar(year: i64, month: i64, day: i64) -> Option<time::Date> {
    // Python's MINYEAR is 1; year 0 raises ValueError there.
    let year: i32 = i32::try_from(year).ok().filter(|y| *y >= 1)?;
    let month: time::Month = u8::try_from(month).ok().and_then(|m| m.try_into().ok())?;
    let day: u8 = u8::try_from(day).ok()?;
    time::Date::from_calendar_date(year, month, day).ok()
}

#[cfg(test)]
mod tests {
    use super::*;

    fn record(subject: &str, body: &str, sent: &str) -> MytripMessage {
        MytripMessage {
            message: json!({"payload": {"headers": []}}),
            subject: Some(subject.to_owned()),
            raw_text: body.to_owned(),
            sent_day: Some(sent.to_owned()),
        }
    }

    fn run(cases: &[(&str, &str, &str)]) -> Vec<Value> {
        let mut messages = BTreeMap::new();
        for (index, (subject, body, sent)) in cases.iter().enumerate() {
            messages.insert(format!("m{index}"), record(subject, body, sent));
        }
        mytrip_events(&MytripInput {
            messages,
            inventory: Vec::new(),
        })
    }

    #[test]
    fn confirmation_carries_amount_period_and_order() {
        let events = run(&[(
            "여행이 확정되었습니다. 주문 번호 1234-567-890",
            "가는 편 • 2026년 5월 16일\n오는 편 • 2026년 5월 20일\n합계 250,000.00 KRW\n주문 번호 1234-567-890",
            "2026-05-13",
        )]);
        assert_eq!(events.len(), 1);
        assert_eq!(events[0]["booking_ref"], "1234-567-890");
        assert_eq!(events[0]["amount_krw"], 250000);
        assert_eq!(events[0]["service_period"]["starts_on"], "2026-05-16");
        assert_eq!(events[0]["reservation_observed_on"][0], "2026-05-13");
    }

    #[test]
    fn one_invalid_leg_rejects_the_whole_message() {
        let events = run(&[(
            "여행이 확정되었습니다. 주문 번호 1234-567-890",
            "가는 편 • 2026년 2월 30일\n오는 편 • 2026년 3월 2일\n합계 250,000 KRW
주문 번호 1234-567-890",
            "2026-05-13",
        )]);
        assert!(events.is_empty());
    }

    #[test]
    fn year_zero_rejects_the_message() {
        let events = run(&[(
            "여행이 확정되었습니다. 주문 번호 1234-567-890",
            "가는 편 • 0000년 5월 16일\n합계 1 KRW
주문 번호 1234-567-890",
            "2026-05-13",
        )]);
        assert!(events.is_empty());
    }

    #[test]
    fn totals_compare_original_strings() {
        // Two spellings of one amount are two elements, so the message is rejected.
        let events = run(&[(
            "여행이 확정되었습니다. 주문 번호 1234-567-890",
            "가는 편 • 2026년 5월 16일\n합계 224,682 KRW\n합계 224682 KRW
주문 번호 1234-567-890",
            "2026-05-13",
        )]);
        assert!(events.is_empty());
    }

    #[test]
    fn withdrawal_is_sticky_across_reconfirmation() {
        let events = run(&[
            (
                "여행이 확정되었습니다. 주문 번호 1234-567-890",
                "가는 편 • 2026년 5월 16일\n합계 250,000 KRW
주문 번호 1234-567-890",
                "2026-05-13",
            ),
            (
                "예약 취소 안내 1234-567-890",
                "주문 번호 1234-567-890",
                "2026-05-14",
            ),
            (
                "여행이 확정되었습니다. 주문 번호 1234-567-890",
                "가는 편 • 2026년 5월 16일\n합계 250,000 KRW
주문 번호 1234-567-890",
                "2026-05-15",
            ),
        ]);
        assert_eq!(events.len(), 1);
        assert_eq!(events[0]["reservation_status"], "cancelled");
    }

    #[test]
    fn conflict_clears_amount_and_period_but_keeps_rows() {
        let events = run(&[
            (
                "여행이 확정되었습니다. 주문 번호 1234-567-890",
                "가는 편 • 2026년 5월 16일\n합계 250,000 KRW
주문 번호 1234-567-890",
                "2026-05-13",
            ),
            (
                "여행이 확정되었습니다. 주문 번호 1234-567-890",
                "가는 편 • 2026년 5월 17일\n합계 250,000 KRW
주문 번호 1234-567-890",
                "2026-05-14",
            ),
        ]);
        assert_eq!(events[0]["service_period"], Value::Null);
        assert_eq!(events[0]["amount_krw"], Value::Null);
        assert_eq!(events[0]["service_period_conflict"], true);
        assert_eq!(events[0]["source_ids"].as_array().unwrap().len(), 2);
    }

    #[test]
    fn total_tail_boundary_rejects_another_currency() {
        let events = run(&[(
            "여행이 확정되었습니다. 주문 번호 1234-567-890",
            "가는 편 • 2026년 5월 16일\n합계 250,000.00 USD",
            "2026-05-13",
        )]);
        assert!(events.is_empty());
    }
}
