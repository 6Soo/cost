//! 계획 입력. Python `automatic_classification._context`·`_read`가 읽는 열과 같다. 행은 Python dict처럼 열 이름으로 든다.

use crate::dates::{CardRow, Evidence, RowDates, ServicePeriod};
use crate::trips::{Trip, Txn};
use serde_json::{Map, Value};
use std::collections::{BTreeMap, BTreeSet};

pub type Row = Map<String, Value>;

/// `_read`가 읽는 열. 어댑터는 `transactions`에서 이 열을 모두 읽어 행을 만든다.
pub const ROW_COLUMNS: [&str; 30] = [
    "transaction_id",
    "source_hash",
    "issuer",
    "card_tail",
    "card_kind",
    "transaction_direction",
    "transaction_kind",
    "approval_number",
    "original_approval_number",
    "approval_date",
    "posting_date",
    "merchant",
    "merchant_normalized",
    "amount_krw",
    "foreign_amount",
    "foreign_currency",
    "description_raw",
    "raw_row_json",
    "parse_error",
    "duplicate_of",
    "conflict_reason",
    "classification_state",
    "classification_source",
    "classification_basis",
    "item",
    "description",
    "display_tab_id",
    "trip_id",
    "revision",
    "decided_at",
];

/// 판정 열 일곱 개(`FIELDS`).
pub const FIELDS: [&str; 7] = [
    "classification_state",
    "classification_source",
    "classification_basis",
    "item",
    "description",
    "display_tab_id",
    "trip_id",
];

/// 연결(환불 짝)이 계획에 주는 사실. Python `refund_links`의 값 중 계획이 읽는 칸만 둔다.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct RefundLink {
    pub original_id: String,
    /// 추론 연결은 원결제의 항목·여행을 상속하지 않는다.
    pub inferred: bool,
    /// `full`·`partial`·`excess` 등.
    pub status: String,
}

/// 환불 짝 연결의 출처. 1차 전환 전에는 Python 어댑터 결과, 2차 전환 뒤에는 Rust 연결이 이 자리에 선다.
pub trait Links {
    fn link(&self, transaction_id: &str) -> Option<&RefundLink>;
}

impl Links for BTreeMap<String, RefundLink> {
    fn link(&self, transaction_id: &str) -> Option<&RefundLink> {
        self.get(transaction_id)
    }
}

/// 화면 행(`board_rows`)의 `(display_tab_id, payload_json, revision)`.
#[derive(Debug, Clone, PartialEq)]
pub struct BoardRow {
    pub display_tab_id: String,
    pub payload_json: String,
    pub revision: i64,
}

/// `plan`이 읽는 모든 입력. 읽기만 하고 아무것도 쓰지 않는다.
#[derive(Debug, Clone, Default)]
pub struct PlanInput {
    /// `transactions` 전체. 범위를 좁히면 `selected`로 한다(환불의 원결제는 범위 밖에서도 읽는다).
    pub rows: Vec<Row>,
    /// 여행 목록 원본(digest가 그대로 쓴다).
    pub trips: Vec<Value>,
    pub nets: BTreeMap<String, i64>,
    pub selected: Option<BTreeSet<String>>,
    pub reconsider: bool,
    /// 예약 이용기간 근거. 거래 ID → 사실.
    pub evidence: BTreeMap<String, Value>,
    /// 해제되지 않은 검토 결정 `(transaction_id, display_tab_id)`, 개정 순.
    pub decisions: Vec<(String, String)>,
    pub holds: BTreeSet<String>,
    pub excluded: BTreeSet<String>,
    /// 수동 교정한 화면 행 ID(`card-<id>`).
    pub overrides: BTreeSet<String>,
    /// `ledger_entries`: 거래 ID → `item`·`description`·`display_tab_id`·`trip_id`.
    pub ledger: BTreeMap<String, Row>,
    /// 화면 행: `row_id`(`card-<id>`) → 값.
    pub boards: BTreeMap<String, BoardRow>,
    /// 닫힌 분기 검수로 보호된 거래.
    pub closed_reviews: BTreeSet<String>,
    /// 실사용 항목 목록(`ALLOWED_ITEMS_SQL`).
    pub allowed_items: Vec<String>,
}

/// Python `str(row.get(key) or '')`.
pub(super) fn text(row: &Row, key: &str) -> String {
    match row.get(key) {
        Some(Value::String(s)) => s.clone(),
        Some(Value::Number(n)) if n.as_f64() != Some(0.0) => n.to_string(),
        Some(Value::Bool(true)) => "True".to_string(),
        _ => String::new(),
    }
}

pub(super) fn set(row: &mut Row, key: &str, value: impl Into<String>) {
    row.insert(key.to_string(), Value::String(value.into()));
}

pub(super) fn non_empty(s: &str) -> Option<String> {
    (!s.is_empty()).then(|| s.to_string())
}

/// 행에서 여행 추론이 읽는 칸. `raw_row`는 문자열 값만 든다.
pub(super) fn txn_of(row: &Row) -> Txn {
    let raw_row = row
        .get("raw_row")
        .and_then(Value::as_object)
        .map(|m| {
            m.iter()
                .filter_map(|(k, v)| Some((k.clone(), v.as_str()?.to_string())))
                .collect()
        })
        .unwrap_or_default();
    Txn {
        merchant: text(row, "merchant"),
        approval_date: text(row, "approval_date"),
        posting_date: text(row, "posting_date"),
        card_kind: text(row, "card_kind"),
        card_tail: text(row, "card_tail"),
        issuer: text(row, "issuer"),
        foreign_currency: text(row, "foreign_currency"),
        description_raw: text(row, "description_raw"),
        transaction_direction: row
            .get("transaction_direction")
            .map(|_| text(row, "transaction_direction")),
        transaction_kind: text(row, "transaction_kind"),
        parse_error: text(row, "parse_error"),
        duplicate_of: text(row, "duplicate_of"),
        conflict_reason: text(row, "conflict_reason"),
        classification_source: text(row, "classification_source"),
        item: text(row, "item"),
        description: text(row, "description"),
        trip_id: text(row, "trip_id"),
        display_tab_id: text(row, "display_tab_id"),
        source_hash: text(row, "source_hash"),
        amount_krw: row.get("amount_krw").and_then(Value::as_i64),
        raw_row,
    }
}

pub(super) fn card_row(row: &Row) -> CardRow {
    CardRow {
        dates: RowDates {
            approval_date: non_empty(&text(row, "approval_date")),
            posting_date: non_empty(&text(row, "posting_date")),
        },
        trip_id: non_empty(&text(row, "trip_id")),
        display_tab_id: non_empty(&text(row, "display_tab_id")),
        source_hash: non_empty(&text(row, "source_hash")),
    }
}

/// 근거 사실에서 완료 기간 예외 판정이 읽는 칸.
pub(super) fn evidence_of(fact: &Value) -> Evidence {
    let opt = |v: &Value, k: &str| v.get(k).and_then(Value::as_str).map(str::to_string);
    let period = fact.get("service_period").unwrap_or(&Value::Null);
    Evidence {
        trip_id: opt(fact, "trip_id"),
        service_period: ServicePeriod {
            starts_on: opt(period, "starts_on"),
            ends_on: opt(period, "ends_on"),
        },
        formal_link: fact.get("formal_link") == Some(&Value::Bool(true)),
        source_hash: opt(fact, "source_hash"),
    }
}

/// 여행 한 줄(`Value`)을 `Trip`으로 읽는다(`trips` 골든 시험과 같은 해석).
pub(super) fn trip_of(v: &Value) -> Trip {
    let t = |key: &str| {
        v.get(key)
            .and_then(Value::as_str)
            .unwrap_or_default()
            .to_string()
    };
    let truthy = |key: &str| match v.get(key) {
        Some(Value::Bool(b)) => *b,
        Some(Value::Number(n)) => n.as_f64().is_some_and(|f| f != 0.0),
        Some(Value::String(s)) => !s.is_empty(),
        Some(Value::Array(a)) => !a.is_empty(),
        _ => false,
    };
    Trip {
        trip_id: t("trip_id"),
        tab_id: t("tab_id"),
        display_key: t("display_key"),
        destination: t("destination"),
        starts_on: t("starts_on"),
        ends_on: v.get("ends_on").and_then(Value::as_str).map(str::to_string),
        deleted: truthy("deleted"),
        archived: truthy("archived"),
        disabled: v.get("enabled") == Some(&Value::Bool(false)),
        invalid: v.get("valid") == Some(&Value::Bool(false)),
        conflict: truthy("conflict"),
        period_conflict: truthy("period_conflict"),
        flags: v
            .get("flags")
            .and_then(Value::as_array)
            .map(|a| {
                a.iter()
                    .filter_map(|f| f.as_str().map(str::to_string))
                    .collect()
            })
            .unwrap_or_default(),
    }
}
