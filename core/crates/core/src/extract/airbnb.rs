//! Airbnb confirmation mails as reservation-only facts — retirement unit 3-b (second).
//!
//! Unlike Traveloka, `collect()` in `app/airbnb_mail.py` parses, aggregates, assembles the
//! event and derives its ids in one function, so the whole slice is Rust. The shared mail
//! helpers (`authenticated_headers`, `message_text`, `sent_day`) stay in the Python bridge and
//! arrive as boundary values — `sent_day` especially, because it is RFC 2822 parsing in KST
//! with a receipt-delay rule, shared by ten call sites.
//!
//! No cross-parser dependency: only `ota_payments._parse_mail_events` imports this module.

use std::collections::{BTreeMap, BTreeSet};

use regex::Regex;
use serde::Deserialize;
use serde_json::{Value, json};

use super::pyre::{PY_SPACE, read_digits, word_boundary_after, word_boundary_before};
use crate::digest::{python_json_compact, sha256_hex};

/// `\bHM[A-Z0-9]{8}\b` — no `re.I`, ASCII only, body text only.
fn code_pattern() -> Regex {
    Regex::new(r"HM[A-Z0-9]{8}").unwrap()
}

/// `^예약 확정(?: 안내)?\s*:\s*(\d{1,2})월\s*(\d{1,2})일\s*~\s*(?:(\d{1,2})월\s*)?(\d{1,2})일`.
///
/// The `^` anchor is kept as an explicit start-of-text check because the crate's `^` would
/// also match after a newline if the pattern ever gained `(?m)`.
fn confirmed_pattern() -> Regex {
    Regex::new(&format!(
        r"예약 확정(?: 안내)?{PY_SPACE}*:{PY_SPACE}*(\p{{Nd}}{{1,2}})월{PY_SPACE}*(\p{{Nd}}{{1,2}})일{PY_SPACE}*~{PY_SPACE}*(?:(\p{{Nd}}{{1,2}})월{PY_SPACE}*)?(\p{{Nd}}{{1,2}})일"
    ))
    .unwrap()
}

/// `예약이 취소되었습니다` — a literal substring.
fn cancelled_pattern() -> Regex {
    Regex::new(r"예약이 취소되었습니다").unwrap()
}

/// One message as the Python bridge presents it.
#[derive(Debug, Clone, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct AirbnbMessage {
    pub message: Value,
    /// `str(headers.get('subject') or '')` when authenticated, `None` otherwise.
    pub subject: Option<String>,
    /// `message_text(message)` — the body only, with no `Cf` removal.
    pub raw_text: String,
    /// `sent_day(message, headers)` in KST, ISO date, or `None`.
    pub sent_day: Option<String>,
}

#[derive(Debug, Clone, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct AirbnbInput {
    pub messages: BTreeMap<String, AirbnbMessage>,
    pub inventory: Vec<Value>,
}

/// `collect(messages, inventory)`: code-ordered events, one per observed reservation code.
pub fn airbnb_events(input: &AirbnbInput) -> Vec<Value> {
    let code = code_pattern();
    let confirmed = confirmed_pattern();
    let cancelled = cancelled_pattern();
    let mut observed: BTreeMap<String, Vec<(String, Value, String)>> = BTreeMap::new();
    let mut withdrawn_codes: BTreeSet<String> = BTreeSet::new();
    for (message_id, record) in &input.messages {
        let Some(subject) = record.subject.as_deref() else {
            continue;
        };
        let is_confirmed = at_start(&confirmed, subject);
        let is_withdrawn = cancelled.is_match(subject);
        if !is_confirmed && !is_withdrawn {
            continue;
        }
        let codes = body_codes(&code, &record.raw_text);
        if codes.len() != 1 {
            continue;
        }
        let code = codes[0].clone();
        if is_withdrawn {
            withdrawn_codes.insert(code);
            continue;
        }
        let match_ = confirmed.captures(subject);
        let Some(sent_day) = record.sent_day.as_deref() else {
            continue;
        };
        let Some(period) = match_.as_ref().and_then(|m| period(m, sent_day)) else {
            continue;
        };
        observed.entry(code).or_default().push((
            message_id.clone(),
            period,
            sha256_hex(&python_json_compact(&record.message)),
        ));
    }
    let mut events = Vec::new();
    for (code, rows) in observed {
        let periods: BTreeSet<String> = rows
            .iter()
            .map(|(_, period, _)| python_json_compact(period))
            .collect();
        let source_ids: Vec<String> = rows.iter().map(|(id, _, _)| format!("mail:{id}")).collect();
        let single = periods.len() == 1;
        let service_period = if single {
            Some(rows.last().unwrap().1.clone())
        } else {
            None
        };
        let mut event = json!({
            "provider": "airbnb",
            "booking_ref": code,
            "event_type": "reservation",
            "item": "숙박비",
            "paid_on": Value::Null,
            "amount": Value::Null,
            "currency": Value::Null,
            "amount_krw": Value::Null,
            "card_last4": Value::Null,
            "service_period": service_period,
            "service_period_conflict": !single,
            "reservation_status": if withdrawn_codes.contains(&code) { "cancelled" } else { "observed" },
            "payment_status": "unknown",
            "evidence_status": "reservation_observed",
            "evidence_kind": "authenticated_reservation_mail",
            "source_digest": rows.last().unwrap().2.clone(),
            "source_digests": rows.iter().map(|(_, _, d)| d.clone()).collect::<Vec<_>>(),
            "source_ids": source_ids,
            "identity_source_ids": source_ids,
            "source_inventory": input.inventory.clone(),
            "paid_on_semantics": "missing",
        });
        // One code is one reservation: later confirmation or cancellation mails keep its identity.
        let identity = format!("airbnb:{code}");
        event["source_lineage_ids"] = json!([identity.clone()]);
        let observations: Vec<String> = source_ids
            .iter()
            .map(|source| {
                format!(
                    "obs_{}",
                    sha256_hex(&python_json_compact(&json!([identity, source])))
                )
            })
            .collect();
        let mut sorted = observations;
        sorted.sort();
        event["observation_ids"] = json!(sorted);
        event["ota_event_id"] = json!(format!(
            "ota_{}",
            sha256_hex(&python_json_compact(&json!([identity])))
        ));
        events.push(event);
    }
    events
}

/// Python's `CONFIRMED.search` with a `^` anchor: only a match at position 0 counts.
fn at_start(pattern: &Regex, text: &str) -> bool {
    let Some(m) = pattern.find(text) else {
        return false;
    };
    m.start() == 0
}

/// `set(CODE.findall(message_text(message))`, with Python's word boundaries on both sides.
fn body_codes(pattern: &Regex, text: &str) -> Vec<String> {
    let mut codes: Vec<String> = Vec::new();
    for m in pattern.find_iter(text) {
        if !word_boundary_before(text, m.start()) || !word_boundary_after(text, m.end()) {
            continue;
        }
        let code = m.as_str().to_owned();
        if !codes.contains(&code) {
            codes.push(code);
        }
    }
    codes
}

/// `_period(match, sent)` — the subject omits the year, so the stay follows the send date.
fn period(m: &regex::Captures<'_>, sent: &str) -> Option<Value> {
    let groups: Vec<Option<i64>> = (1..=4)
        .map(|i| m.get(i).map(|g| read_digits(g.as_str())))
        .collect();
    let start_month = groups[0]?;
    let start_day = groups[1]?;
    let end_month = groups[2];
    let end_day = groups[3]?;
    let sent = parse_date(sent)?;
    let start = calendar(sent.year(), start_month, start_day)?;
    let start = if start < sent && (sent - start).whole_days() > 31 {
        // Python retries the next year inside the same `try`, so a failure there is the same
        // `ValueError` path: `None`, never a second retry.
        calendar(sent.year() + 1, start_month, start_day)?
    } else {
        start
    };
    // Python's `end_month or start_month`: a captured `0` is falsy and falls back.
    let end_month = match end_month {
        Some(value) if value != 0 => value,
        _ => start_month,
    };
    let year_step = i64::from(end_month < start_month);
    let end = calendar(
        start.year() + i32::try_from(year_step).ok()?,
        end_month,
        end_day,
    )?;
    let days = (end - start).whole_days();
    if !(1..=60).contains(&days) {
        return None;
    }
    Some(json!({"starts_on": crate::dates::iso(start), "ends_on": crate::dates::iso(end)}))
}

fn parse_date(text: &str) -> Option<time::Date> {
    crate::dates::parse_iso(text).ok()
}

/// `date(year, month, day)` with Python's `ValueError` as `None`.
fn calendar(year: i32, month: i64, day: i64) -> Option<time::Date> {
    let month: time::Month = u8::try_from(month).ok().and_then(|m| m.try_into().ok())?;
    let day: u8 = u8::try_from(day).ok()?;
    time::Date::from_calendar_date(year, month, day).ok()
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn code_needs_word_boundaries_on_both_sides() {
        let pattern = code_pattern();
        // `Ⅳ` is a Python word character (Nl) but not a crate `\w` character.
        assert!(body_codes(&pattern, "ⅣHMABCDEFGH").is_empty());
        assert_eq!(
            body_codes(&pattern, "확인 코드 HMABCDEFGH"),
            vec!["HMABCDEFGH"]
        );
        assert!(body_codes(&pattern, "XHMABCDEFGH").is_empty());
        assert_eq!(body_codes(&pattern, "hmabcdefgh"), Vec::<String>::new());
    }

    #[test]
    fn confirmed_only_matches_at_the_start() {
        let pattern = confirmed_pattern();
        assert!(at_start(&pattern, "예약 확정: 5월 16일~17일"));
        assert!(at_start(&pattern, "예약 확정 안내: 5월 16일~17일 여행"));
        assert!(!at_start(&pattern, "안내: 예약 확정: 5월 16일~17일"));
    }

    #[test]
    fn period_year_follows_the_send_date_and_crosses_the_year_boundary() {
        let pattern = confirmed_pattern();
        let m = pattern.captures("예약 확정: 12월 28일~1월 3일").unwrap();
        let value = period(&m, "2026-12-13").unwrap();
        assert_eq!(value["starts_on"], "2026-12-28");
        assert_eq!(value["ends_on"], "2027-01-03");
        // A stay confirmed more than 31 days after its start belongs to the next year.
        let m = pattern.captures("예약 확정: 1월 3일~1월 9일").unwrap();
        let value = period(&m, "2026-12-13").unwrap();
        assert_eq!(value["starts_on"], "2027-01-03");
    }

    #[test]
    fn period_rejects_same_day_and_over_sixty() {
        let pattern = confirmed_pattern();
        let m = pattern.captures("예약 확정: 5월 16일~16일").unwrap();
        assert!(period(&m, "2026-05-13").is_none());
        let m = pattern.captures("예약 확정: 5월 16일~7월 20일").unwrap();
        assert!(period(&m, "2026-05-13").is_none());
    }

    #[test]
    fn period_treats_a_zero_end_month_as_absent() {
        let pattern = confirmed_pattern();
        // `０월` reads as 0, Python's `or` falls back to the start month, and the day stays 20.
        let m = pattern.captures("예약 확정: 5월 16일~０월 20일").unwrap();
        let value = period(&m, "2026-05-13").unwrap();
        assert_eq!(value["starts_on"], "2026-05-16");
        assert_eq!(value["ends_on"], "2026-05-20");
    }

    #[test]
    fn period_rejects_february_29_in_both_directions() {
        let pattern = confirmed_pattern();
        // 2027 is not a leap year, so a same-year start fails outright.
        let m = pattern.captures("예약 확정: 2월 29일~3월 2일").unwrap();
        assert!(period(&m, "2027-02-13").is_none());
        // 2028 is, so the same pattern succeeds.
        assert!(period(&m, "2028-02-13").is_some());
    }
}
