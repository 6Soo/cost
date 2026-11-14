//! 이용기간 결정 규칙(M3 U9a, 설계 §2.1·§2.7). 원본: `webapp/ledger_stay_evidence.py`의 `verified_period_for`
//! (= `period_for`에서 화면 전용 추론을 뺀 것, DATE-109)와 그 근거 인덱스의 검증 경로(`_build_index` 본 줄기 +
//! `app/ota_mail.ledger_metadata`).
//!
//! 입력 근거(예약 사실·연결)는 2차 전환 전까지 Python 다리(`tools/core_bridge` `periods`)가 거래별 후보 목록으로 넘긴다.
//! 이 모듈은 그 목록과 화면 행의 저장값만 읽는 순수 함수이며 화면 렌더와 무관하다. 근거가 같으면 결과가 같으므로,
//! 근거 digest([`evidence_digest`])가 바뀔 때만 재판정하면 된다([`changed_since`]).

use std::collections::{BTreeMap, BTreeSet};

use serde_json::{Map, Value, json};
use time::Date;

use crate::dates::parse_iso;
use crate::digest::{python_json, sha256_hex};
use crate::domain::{ServicePeriod, UnknownPeriodReason};

/// 판정 함수 버전. 규칙을 고치면 올린다. digest에 들어가므로 모든 거래가 한 번 재판정된다.
pub const PERIOD_FN_VERSION: u32 = 1;

const SERVICE_ITEMS: [&str; 3] = ["숙박비", "항공료", "렌터카"];
const REFUND_STATES: [&str; 4] = [
    "refund_pending",
    "refund_requested",
    "refunded",
    "refund_completed",
];
/// 근거 digest에 들어가는 칸(규칙이 읽는 칸만. 다른 칸이 바뀌어도 재판정하지 않는다).
const FACT_KEYS: [&str; 17] = [
    "transaction_id",
    "item",
    "source_hash",
    "reservation_status",
    "evidence_pending",
    "refund_pending",
    "period_conflict",
    "booking_link_conflict",
    "booking_ref",
    "group_size",
    "service_period_basis",
    "period",
    "source_digests",
    "evidence_digests",
    "source_sha256",
    "inferred_link",
    "allocation_basis",
];
const EVENT_KEYS: [&str; 6] = [
    "event_type",
    "evidence_status",
    "payment_status",
    "source_digest",
    "period_conflict",
    "refund_status",
];
const CARD_KEYS: [&str; 5] = [
    "source_hash",
    "transaction_direction",
    "ota_review_held",
    "reservation_refund_blocked",
    "refund_status",
];

/// Python의 진리값.
fn truthy(v: &Value) -> bool {
    match v {
        Value::Null => false,
        Value::Bool(b) => *b,
        Value::Number(n) => n.as_f64().is_some_and(|f| f != 0.0),
        Value::String(s) => !s.is_empty(),
        Value::Array(a) => !a.is_empty(),
        Value::Object(o) => !o.is_empty(),
    }
}

/// Python `str(value or '')`.
fn py_str(v: &Value) -> String {
    match v {
        Value::String(s) => s.clone(),
        Value::Number(n) if n.as_f64() != Some(0.0) => n.to_string(),
        Value::Bool(true) => "True".to_owned(),
        _ => String::new(),
    }
}

fn field<'a>(v: &'a Value, key: &str) -> &'a Value {
    v.get(key).unwrap_or(&Value::Null)
}

fn flag(v: &Value, key: &str) -> bool {
    truthy(field(v, key))
}

fn str_is(v: &Value, key: &str, wanted: &str) -> bool {
    field(v, key).as_str() == Some(wanted)
}

fn in_states(v: &Value, key: &str, states: &[&str]) -> bool {
    field(v, key).as_str().is_some_and(|s| states.contains(&s))
}

/// 화면 행에서 규칙이 읽는 칸(Python `row`의 `row_id`·`source_event_id`·`service_period`·`reservation_no`).
#[derive(Debug, Clone, PartialEq, Eq, Default)]
pub struct PeriodRow {
    pub row_id: String,
    pub source_event_id: String,
    pub service_period: String,
    pub reservation_no: String,
}

impl PeriodRow {
    pub fn from_value(row: &Value) -> Self {
        Self {
            row_id: py_str(field(row, "row_id")),
            source_event_id: py_str(field(row, "source_event_id")),
            service_period: py_str(field(row, "service_period")),
            reservation_no: py_str(field(row, "reservation_no")),
        }
    }

    /// 카드 거래 행: 저장 값은 화면 행(`board_rows.payload_json`)의 `service_period`·`reservation_no`다.
    pub fn for_card(transaction_id: &str, payload_json: Option<&str>) -> Self {
        let payload: Value = payload_json
            .and_then(|p| serde_json::from_str(p).ok())
            .unwrap_or(Value::Null);
        Self {
            row_id: format!("card-{transaction_id}"),
            source_event_id: String::new(),
            service_period: py_str(field(&payload, "service_period")),
            reservation_no: py_str(field(&payload, "reservation_no")),
        }
    }

    /// 거래 ID. 행 ID가 `card-<거래 ID>` 꼴이 아니면 카드 행이 아니다.
    fn transaction_id(&self) -> Option<String> {
        let rest = self.row_id.strip_prefix("card-")?;
        let tid = if self.source_event_id.is_empty() {
            rest.to_owned()
        } else {
            self.source_event_id.clone()
        };
        (self.row_id == format!("card-{tid}")).then_some(tid)
    }
}

struct Metadata {
    booking_ref: String,
    period: String,
}

/// `ledger_metadata`: 같은 원천 해시의 확정 사실이 한 가지 이용기간을 말할 때만 값을 낸다.
fn ledger_metadata(
    matches: &[Value],
    tid: &str,
    source: &Value,
    direction: &Value,
    item: &str,
) -> Option<Metadata> {
    if direction.as_str() != Some("purchase") {
        return None;
    }
    let facts: Vec<&Value> = matches
        .iter()
        .filter(|f| field(f, "source_hash") == source)
        .collect();
    if facts.is_empty() {
        return None;
    }
    let bad = facts.iter().any(|f| {
        f.get("transaction_id")
            .is_some_and(|v| v.as_str() != Some(tid))
            || field(f, "item").as_str() != Some(item)
            || in_states(
                f,
                "reservation_status",
                &["cancelled", "refund_pending", "evidence_pending"],
            )
            || flag(f, "evidence_pending")
            || flag(f, "refund_pending")
            || flag(f, "period_conflict")
            || flag(f, "booking_link_conflict")
    });
    if bad {
        return None;
    }
    let mut refs: Vec<&Value> = Vec::new();
    for f in &facts {
        let r = field(f, "booking_ref");
        if !refs.contains(&r) {
            refs.push(r);
        }
    }
    let blank = refs.len() == 1 && refs[0] == &json!("");
    let group = blank && facts.iter().all(|f| flag(f, "group_size"));
    let shared = blank
        && facts
            .iter()
            .all(|f| str_is(f, "service_period_basis", "LINK-108"));
    if !group && !shared && (refs.len() != 1 || !truthy(refs[0])) {
        return None;
    }
    if facts.iter().any(|f| {
        !in_states(
            f,
            "reservation_status",
            &["observed", "confirmed", "completed"],
        )
    }) {
        return None;
    }
    let first = field(facts[0], "period");
    if facts.iter().any(|f| field(f, "period") != first) {
        return None;
    }
    if !truthy(first) && item == "숙박비" {
        return None;
    }
    let has_digest = facts.iter().any(|f| {
        ["source_digests", "evidence_digests"]
            .iter()
            .any(|k| field(f, k).as_array().is_some_and(|a| a.iter().any(truthy)))
            || flag(f, "source_sha256")
    });
    if !has_digest {
        return None;
    }
    let inferred = facts.iter().any(|f| flag(f, "inferred_link"));
    let period = if truthy(first) {
        format!(
            "{}~{}",
            first.get("starts_on")?.as_str()?,
            first.get("ends_on")?.as_str()?
        )
    } else {
        String::new()
    };
    let booking_ref = if group || inferred {
        String::new()
    } else {
        py_str(refs[0])
    };
    Some(Metadata {
        booking_ref,
        period,
    })
}

/// `_build_index` 본 줄기: 후보 하나가 근거 인덱스에 들어가는가.
fn admitted(candidate: &Value, tid: &str) -> Option<Metadata> {
    let fact = field(candidate, "fact");
    let (card, event) = (field(candidate, "card"), field(candidate, "event"));
    let item = field(fact, "item")
        .as_str()
        .filter(|i| SERVICE_ITEMS.contains(i))?;
    let period = field(fact, "period");
    if py_str(field(fact, "transaction_id")) != tid
        || flag(candidate, "manual")
        || !flag(card, "source_hash")
        || flag(candidate, "event_blocked")
        || str_is(fact, "reservation_status", "refunded")
        || !period.is_object()
        || !flag(period, "starts_on")
        || !flag(period, "ends_on")
    {
        return None;
    }
    if item != "숙박비" {
        let unpaid = !str_is(event, "event_type", "charge")
            || !str_is(event, "evidence_status", "paid_verified")
            || !str_is(event, "payment_status", "paid")
            || !flag(event, "source_digest")
            || flag(card, "ota_review_held")
            || flag(card, "reservation_refund_blocked")
            || in_states(card, "refund_status", &REFUND_STATES)
            || in_states(event, "refund_status", &REFUND_STATES);
        if unpaid {
            return None;
        }
    }
    let matches: Vec<Value> = field(candidate, "matches")
        .as_array()
        .cloned()
        .unwrap_or_default();
    ledger_metadata(
        &matches,
        tid,
        field(card, "source_hash"),
        field(card, "transaction_direction"),
        item,
    )
    .filter(|m| !m.period.is_empty())
}

/// `verified_period_for`: 저장 값이 있으면 그 값, 없으면 검증된 연결의 이용기간, 그 밖(추론·근거 없음)은 빈 문자열.
/// `candidates`는 이 거래의 후보 목록(`periods` 다리 출력의 거래별 배열). 없으면 `Null`.
pub fn verified_period_for(row: &PeriodRow, candidates: &Value) -> String {
    let stored = row.service_period.trim();
    if !stored.is_empty() {
        return stored.to_owned();
    }
    let Some(tid) = row.transaction_id() else {
        return String::new();
    };
    let found = candidates
        .as_array()
        .into_iter()
        .flatten()
        .filter_map(|c| admitted(c, &tid))
        .next_back();
    let Some(found) = found else {
        return String::new();
    };
    let reservation = row.reservation_no.trim();
    if !reservation.is_empty() && reservation != found.booking_ref {
        return String::new();
    }
    found.period
}

/// `YYYY-MM-DD~YYYY-MM-DD` 문자열을 이용기간으로. 비면 근거 없음(서비스 항목이 아니면 해당 없음).
pub fn service_period(text: &str, item: &str) -> ServicePeriod {
    let text = text.trim();
    if text.is_empty() {
        let reason = if SERVICE_ITEMS.contains(&item) {
            UnknownPeriodReason::NoEvidence
        } else {
            UnknownPeriodReason::NotApplicable
        };
        return ServicePeriod::unknown(reason);
    }
    let parsed = text.split_once('~').and_then(|(a, b)| {
        let day = |s: &str| -> Option<Date> { parse_iso(s.trim()).ok() };
        ServicePeriod::known(day(a)?, day(b)?).ok()
    });
    parsed.unwrap_or(ServicePeriod::unknown(
        UnknownPeriodReason::EvidenceAmbiguous,
    ))
}

fn pick(v: &Value, keys: &[&str]) -> Value {
    let mut out = Map::new();
    for key in keys {
        out.insert((*key).to_owned(), field(v, key).clone());
    }
    Value::Object(out)
}

/// 근거 digest: 판정 함수 버전과 규칙이 읽는 칸(저장 값·예약번호·후보의 사실)의 sha256. 같으면 재판정하지 않는다.
pub fn evidence_digest(row: &PeriodRow, candidates: &Value) -> String {
    let projected: Vec<Value> = candidates
        .as_array()
        .into_iter()
        .flatten()
        .map(|c| {
            let matches: Vec<Value> = field(c, "matches")
                .as_array()
                .into_iter()
                .flatten()
                .map(|m| pick(m, &FACT_KEYS))
                .collect();
            json!({
                "fact": pick(field(c, "fact"), &FACT_KEYS),
                "event": pick(field(c, "event"), &EVENT_KEYS),
                "card": pick(field(c, "card"), &CARD_KEYS),
                "event_blocked": flag(c, "event_blocked"),
                "manual": flag(c, "manual"),
                "matches": matches,
            })
        })
        .collect();
    let payload = json!([
        PERIOD_FN_VERSION,
        row.row_id,
        row.source_event_id,
        row.service_period.trim(),
        row.reservation_no.trim(),
        projected,
    ]);
    sha256_hex(&python_json(&payload))
}

/// 이용기간 근거(2차 전환 전까지 Python 다리 출력)와 재판정 대상. 계획이 판정마다 이용기간을 정하는 데 쓴다.
#[derive(Debug, Clone, Default)]
pub struct PeriodEvidence {
    /// 거래 ID → 후보 목록.
    pub facts: BTreeMap<String, Value>,
    /// 근거 digest가 바뀌어 7칸이 같아도 다시 판정할 거래([`changed_since`]의 결과).
    pub changed: BTreeSet<String>,
}

impl PeriodEvidence {
    pub fn facts_of(&self, transaction_id: &str) -> &Value {
        self.facts.get(transaction_id).unwrap_or(&Value::Null)
    }
}

/// 거래별 현재 근거 digest. `cards`는 `(거래 ID, 화면 행 payload_json)`, `facts`는 거래 ID → 후보 목록.
pub fn current_digests<'a>(
    cards: impl IntoIterator<Item = (&'a str, Option<&'a str>)>,
    facts: &BTreeMap<String, Value>,
) -> BTreeMap<String, String> {
    cards
        .into_iter()
        .map(|(tid, payload)| {
            let row = PeriodRow::for_card(tid, payload);
            let digest = evidence_digest(&row, facts.get(tid).unwrap_or(&Value::Null));
            (tid.to_owned(), digest)
        })
        .collect()
}

/// 저장된 digest와 현재 digest를 견주어 다시 판정할 거래만 고른다(없던 거래·digest가 다른 거래). 정렬된 ID.
pub fn changed_since(
    stored: &BTreeMap<String, String>,
    current: &BTreeMap<String, String>,
) -> Vec<String> {
    let known: BTreeSet<&String> = current.keys().collect();
    known
        .into_iter()
        .filter(|tid| stored.get(*tid) != current.get(*tid))
        .cloned()
        .collect()
}
