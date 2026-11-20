//! Traveloka mail parser — first retirement unit (playbook 3-b).
//!
//! Domain decisions, amount reading, flight dates and the fact digest are Rust. The shared
//! mail helpers (`authenticated_headers`, `body_text`, `_format_char_table`) stay in the Python
//! bridge for this unit, the same way `extract_sources.forest_name_keys` carries Python's
//! Unicode semantics across the boundary: the input carries the authentication result, the raw
//! text and the text after `Cf` removal.
//!
//! Python's regex semantics are reproduced with explicit classes, because the `regex` crate
//! differs from Python in three places this slice touches:
//!
//! * `\s` — Python's `str.isspace()` also matches U+001C..U+001F; the crate's `\s` does not.
//! * `\b`/`\w` — Python's `\w` is letters, Nd, Nl, No and `_`; the crate's includes combining
//!   marks and join controls instead. The two boundaries this slice needs are trailing, so they
//!   become a post-filter on the following character.
//! * `(?<![\d,])` — the crate has no lookbehind. A candidate whose preceding character is a
//!   digit or comma is rejected afterwards; every position inside a rejected candidate's amount
//!   span has exactly such a predecessor, so no valid Python match can hide inside one.

use std::sync::LazyLock;

use regex::Regex;
use serde::Deserialize;
use serde_json::{Value, json};

use crate::digest::{python_json_compact, sha256_hex};

/// Python `\s`: Unicode `White_Space` plus the four separator controls.
const PY_SPACE: &str = r"[\s\u{1C}-\u{1F}]";

/// Python `\w` as a reference class, used by the unit test that pins the hand-written test.
#[cfg(test)]
static PY_WORD: LazyLock<Regex> =
    LazyLock::new(|| Regex::new(r"^[\p{L}\p{Nd}\p{Nl}\p{No}_]$").unwrap());

/// `(?:예약\s*ID|Booking\s*ID)\s*[:：]?\s*(\d{6,20})`, `re.I`.
static BOOKING_ID: LazyLock<Regex> = LazyLock::new(|| {
    Regex::new(&format!(
        r"(?i)(?:예약{PY_SPACE}*ID|Booking{PY_SPACE}*ID){PY_SPACE}*[:：]?{PY_SPACE}*(\p{{Nd}}{{6,20}})"
    ))
    .unwrap()
});

/// `항공권|e-ticket|flight`, `re.I`.
static FLIGHT_SUBJECT: LazyLock<Regex> =
    LazyLock::new(|| Regex::new(r"(?i)항공권|e-ticket|flight").unwrap());

/// `취소|환불|cancel|refund`, `re.I`.
static CANCEL_SUBJECT: LazyLock<Regex> =
    LazyLock::new(|| Regex::new(r"(?i)취소|환불|cancel|refund").unwrap());

/// `결제\s*완료|payment\s*(?:complete|successful)`, `re.I`.
static COMPLETED_SUBJECT: LazyLock<Regex> = LazyLock::new(|| {
    Regex::new(&format!(
        r"(?i)결제{PY_SPACE}*완료|payment{PY_SPACE}*(?:complete|successful)"
    ))
    .unwrap()
});

/// `(?:\d+|[1-9]\d{0,2}(?:,\d{3})+)\s*원` — the capture is the amount without `\b`.
static AMOUNT: LazyLock<Regex> = LazyLock::new(|| {
    Regex::new(&format!(
        r"(\p{{Nd}}+|[1-9]\p{{Nd}}{{0,2}}(?:,\p{{Nd}}{{3}})+){PY_SPACE}*원"
    ))
    .unwrap()
});

/// `출발\s*항공편(.+?)(?:귀국\s*항공편|오는편|승객|$)`, `re.S`.
///
/// Python's `$` also matches just before one trailing newline; `(?:\n?\z)` reproduces it.
static OUTBOUND: LazyLock<Regex> = LazyLock::new(|| {
    Regex::new(&format!(
        r"(?s)출발{PY_SPACE}*항공편(.+?)(?:귀국{PY_SPACE}*항공편|오는편|승객|(?:\n?\z))"
    ))
    .unwrap()
});

/// `(20\d{2})년\s*(\d{1,2})월\s*(\d{1,2})일`.
static KOREAN_DATE: LazyLock<Regex> = LazyLock::new(|| {
    Regex::new(&format!(
        r"(20\p{{Nd}}{{2}})년{PY_SPACE}*(\p{{Nd}}{{1,2}})월{PY_SPACE}*(\p{{Nd}}{{1,2}})일"
    ))
    .unwrap()
});

/// `(\d{1,2})\s+(\d{1,2})월\s+(20\d{2})`, read as year, month, day.
static REVERSED_DATE: LazyLock<Regex> = LazyLock::new(|| {
    Regex::new(&format!(
        r"(\p{{Nd}}{{1,2}}){PY_SPACE}+(\p{{Nd}}{{1,2}})월{PY_SPACE}+(20\p{{Nd}}{{2}})"
    ))
    .unwrap()
});

/// One message as the Python bridge presents it to this unit.
#[derive(Debug, Clone, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct TravelokaInput {
    /// The whole message, hashed exactly as Python's compact `json.dumps` would hash it.
    pub message: Value,
    /// `authenticated_headers(message, ('traveloka.com',))` subject, or `None` when unauthenticated.
    pub subject: Option<String>,
    /// `message_text(message)` before `Cf` removal — `references()` reads this text only.
    pub raw_text: String,
    /// `message_text(message).translate(_format_char_table())`, the text `extract()` reads.
    pub stripped_text: String,
}

/// `(references, fact)`, matching `references()` and `extract()` in `app/traveloka_mail.py`.
///
/// `references` is returned even when `fact` is `None`, so the golden can compare both.
pub fn traveloka_fact(input: &TravelokaInput) -> (Vec<String>, Option<Value>) {
    let references = references(input);
    let Some(subject) = input.subject.as_ref() else {
        return (references, None);
    };
    if references.len() != 1 || !FLIGHT_SUBJECT.is_match(subject) {
        return (references, None);
    }
    // Requests and cancellation notices never prove a charge or a completed refund.
    let cancelled = CANCEL_SUBJECT.is_match(subject);
    let completed = COMPLETED_SUBJECT.is_match(subject);
    let amounts = amounts(&input.stripped_text);
    let amount = match (completed, cancelled, amounts.len()) {
        (true, false, 1) => match int_amount(&amounts[0]) {
            Some(value) => Some(value),
            // Python's `int()` raises on a non-digit and the whole fact disappears.
            None => return (references, None),
        },
        _ => None,
    };
    if amount.is_some_and(|value| value <= 0) {
        return (references, None);
    }
    let period = outbound_period(&input.stripped_text);
    let paid = amount.is_some();
    let fact = json!({
        "provider": "traveloka",
        "booking_ref": references[0].clone(),
        "item": "항공료",
        "paid_amount_krw": amount,
        "paid_on": Value::Null,
        "paid_on_semantics": "missing",
        "period": period,
        "reserved_dates": [],
        "reservation_status": "observed",
        "evidence_status": if cancelled {
            "evidence_conflict"
        } else if paid {
            "paid_verified"
        } else {
            "reservation_observed"
        },
        "event_type": if paid { "charge" } else { "reservation" },
        "source_sha256": sha256_hex(&python_json_compact(&input.message)),
    });
    (references, Some(fact))
}

/// `references(message)`: booking ids read from `subject + '\n' + message_text(message)`.
///
/// This text is the raw body — `Cf` removal is deliberately absent here, as in Python.
fn references(input: &TravelokaInput) -> Vec<String> {
    let Some(subject) = input.subject.as_ref() else {
        return Vec::new();
    };
    let text = format!("{subject}\n{}", input.raw_text);
    booking_ids(&text)
}

/// Booking ids with Python's trailing `\b` applied after each capture.
///
/// Python collects these into a `set`, so the same id written in both the subject and the body
/// counts once. Keeping the first-seen order makes the reference match Python's `next(iter(...))`
/// for the single-id case and keeps the comparison deterministic.
fn booking_ids(text: &str) -> Vec<String> {
    let mut ids: Vec<String> = Vec::new();
    for captures in BOOKING_ID.captures_iter(text) {
        let Some(found) = captures.get(1) else {
            continue;
        };
        if !word_boundary_after(text, found.end()) {
            continue;
        }
        let id = found.as_str().to_owned();
        if !ids.contains(&id) {
            ids.push(id);
        }
    }
    ids
}

/// Non-overlapping amount captures, deduplicated in the order Python first sees them.
fn amounts(text: &str) -> Vec<String> {
    let mut found: Vec<String> = Vec::new();
    for captures in AMOUNT.captures_iter(text) {
        let Some(found_match) = captures.get(0) else {
            continue;
        };
        let Some(capture) = captures.get(1) else {
            continue;
        };
        // `(?<![\d,])`: reject a candidate that continues a longer number.
        if starts_inside_number(text, found_match.start()) {
            continue;
        }
        if !word_boundary_after(text, found_match.end()) {
            continue;
        }
        let value = capture.as_str().to_owned();
        if !found.contains(&value) {
            found.push(value);
        }
    }
    found
}

fn starts_inside_number(text: &str, start: usize) -> bool {
    text.get(..start)
        .and_then(|prefix| prefix.chars().next_back())
        .is_some_and(|previous| previous == ',' || is_nd(previous))
}

/// Python `\b` at `end`: the character before and the character after differ in wordness.
fn word_boundary_after(text: &str, end: usize) -> bool {
    let before = text
        .get(..end)
        .and_then(|prefix| prefix.chars().next_back());
    let after = text.get(end..).and_then(|rest| rest.chars().next());
    let left = before.is_some_and(is_python_word);
    let right = after.is_some_and(is_python_word);
    left != right
}

/// Python `\w`: `str.isalnum()` (letters, Nd, Nl, No) plus underscore.
///
/// `char::is_alphanumeric` covers exactly letters and Nd/Nl/No, which is the Python set; the
/// crate's own `\w` would also include combining marks and join controls.
fn is_python_word(c: char) -> bool {
    c == '_' || c.is_alphanumeric()
}

/// Python `\d` is the Nd category, which covers fullwidth `０` and Arabic-Indic `٩`.
///
/// `char::is_digit(10)` is ASCII-only, so the category test is the only faithful option.
static ND: LazyLock<Regex> = LazyLock::new(|| Regex::new(r"^\p{Nd}$").unwrap());

fn is_nd(c: char) -> bool {
    ND.is_match(c.to_string().as_str())
}

/// `int(value.replace(',', ''))` over Unicode digits; `None` when the value cannot be held.
fn int_amount(value: &str) -> Option<i64> {
    let mut number: i64 = 0;
    let mut digits = 0;
    for c in value.chars().filter(|c| *c != ',') {
        let digit = i64::from(nd_value(c)?);
        number = number.checked_mul(10)?.checked_add(digit)?;
        digits += 1;
    }
    (digits > 0).then_some(number)
}

/// Decimal value of any Nd code point, the way Python's `int()` reads it.
///
/// Nd runs are contiguous decimal blocks in ascending value order, so counting back to the
/// first Nd code point of this character's block yields the digit. `char::to_digit` only
/// handles ASCII, which would reject fullwidth `０` and Arabic-Indic `٩`.
fn nd_value(c: char) -> Option<u32> {
    if !is_nd(c) {
        return None;
    }
    if c.is_ascii_digit() {
        return c.to_digit(10);
    }
    let code = c as u32;
    let mut start = code;
    while let Some(previous) = char::from_u32(start - 1).filter(|previous| is_nd(*previous)) {
        let _ = previous;
        start -= 1;
    }
    Some(code - start)
}

/// `{'starts_on': day, 'ends_on': day}` from the outbound flight section, or `None`.
fn outbound_period(text: &str) -> Option<Value> {
    let section = OUTBOUND.captures(text)?.get(1)?.as_str();
    let day = korean_date(section).or_else(|| reversed_date(section))?;
    Some(json!({"starts_on": day, "ends_on": day}))
}

fn korean_date(text: &str) -> Option<String> {
    let captures = KOREAN_DATE.captures(text)?;
    calendar(
        read_digits(captures.get(1)?.as_str()),
        read_digits(captures.get(2)?.as_str()),
        read_digits(captures.get(3)?.as_str()),
    )
}

fn reversed_date(text: &str) -> Option<String> {
    let captures = REVERSED_DATE.captures(text)?;
    calendar(
        read_digits(captures.get(3)?.as_str()),
        read_digits(captures.get(2)?.as_str()),
        read_digits(captures.get(1)?.as_str()),
    )
}

/// `int()` over any Unicode decimal digit, as Python does.
fn read_digits(text: &str) -> i64 {
    text.chars()
        .filter_map(nd_value)
        .fold(0, |value, digit| value * 10 + i64::from(digit))
}

/// `date(*parts).isoformat()`, `None` on `ValueError` (the Python `pass` branch).
fn calendar(year: i64, month: i64, day: i64) -> Option<String> {
    let month: time::Month = u8::try_from(month).ok().and_then(|m| m.try_into().ok())?;
    let day = u8::try_from(day).ok()?;
    let date = time::Date::from_calendar_date(i32::try_from(year).ok()?, month, day).ok()?;
    Some(date.to_string())
}

#[cfg(test)]
mod tests {
    use super::*;

    /// `char::is_alphanumeric` must cover Python's `\w` and nothing the crate's `\w` adds.
    #[test]
    fn word_class_matches_pythons_alnum_plus_underscore() {
        for c in ['a', 'Z', '0', '_', '가', 'Ⅳ', '①', '\u{0301}', '\u{200d}'] {
            assert_eq!(
                is_python_word(c),
                PY_WORD.is_match(c.to_string().as_str()),
                "{c:?}"
            );
        }
    }

    #[test]
    fn nd_is_the_python_decimal_digit_set() {
        for c in ['0', '9', '０', '٩', '۵'] {
            assert!(is_nd(c), "{c:?}");
        }
        for c in ['Ⅳ', '①', 'a', ' ', '.'] {
            assert!(!is_nd(c), "{c:?}");
        }
    }

    #[test]
    fn keyword_tests_stay_case_insensitive() {
        assert!(COMPLETED_SUBJECT.is_match("Payment Complete"));
        assert!(COMPLETED_SUBJECT.is_match("PAYMENT SUCCESSFUL"));
        assert!(!COMPLETED_SUBJECT.is_match("payment failed"));
        assert!(FLIGHT_SUBJECT.is_match("E-TICKET"));
        assert!(CANCEL_SUBJECT.is_match("Refund"));
    }

    #[test]
    fn whitespace_class_widens_only_for_the_four_separators() {
        let pattern = Regex::new(&format!("{PY_SPACE}+")).unwrap();
        for text in ["\u{1c}", "\u{1f}", "\u{a0}", "\u{3000}"] {
            assert!(pattern.is_match(text), "{text:?}");
        }
        for text in ["a", "\u{200b}"] {
            assert!(!pattern.is_match(text), "{text:?}");
        }
    }
}
