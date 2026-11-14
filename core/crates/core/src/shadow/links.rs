//! 연결 그림자 (M3 2차 전환 C1). 같은 입력에서 Python 다리 `links` 출력(B)과 Rust 연결(C)을 비교한다.
//! 환불 짝은 운영 사본 DB에서, OTA 연결은 풀이기 입력 파일(`events`·`transactions`·`existing_links`·`rules`·`frozen_groups`)에서 읽는다.
//! 차이 유형 키는 `B-C|필드|범위|added·removed·differs` 형식이며 `core/known-diffs.txt`가 판정한다.

use std::collections::BTreeMap;
use std::path::Path;

use serde_json::{Map, Value, json};

use super::keys::validate_key;
use super::{KnownDiffs, ShadowError, Verdict, judge};
use crate::bridge::PythonBridge;
use crate::links::ota::{Defaults, Matcher};
use crate::links::refund::{Basis, Exclusion, PairingConfig, RefundTxn, Refunds};
use crate::store::projection::TxnRow;
use crate::store::read_projection;

/// 연결 필드 이름. 유형 키의 두 번째 칸이다.
pub const LINK_FIELDS: &[&str] = &[
    "refund_link",
    "refund_group",
    "refund_exclusion",
    "refund_held",
    "refund_review",
    "ota_link",
];
/// 유형 키의 세 번째 칸(Python 쪽 상태). 값은 고정 어휘이며 거래·가맹점 문장은 들어갈 수 없다.
pub const LINK_SCOPES: &[&str] = &[
    "full",
    "partial",
    "completed_period",
    "unclean_member",
    "HOLD_AMBIGUOUS",
    "HOLD_AMOUNT_MISMATCH",
    "HOLD_AMOUNT_UNVERIFIED",
    "HOLD_DATE_UNKNOWN",
    "HOLD_EVIDENCE_CONFLICT",
    "HOLD_GROUP_CHANGED",
    "HOLD_NO_CARD",
    "HOLD_PARTIAL_GROUP",
    "MATCHED_AUTO",
    "MATCHED_GROUP",
    "MATCHED_USER",
    "RESERVATION_ONLY",
    "none",
    "other",
];
pub const LINK_CHANGES: &[&str] = &["added", "removed", "differs"];

/// 연결 키인지(`B-C|연결필드|…`). 판정 그림자와 연결 그림자가 서로의 키를 '해소됨'으로 세지 않게 가른다.
pub fn is_link_key(key: &str) -> bool {
    key.split('|')
        .nth(1)
        .is_some_and(|field| LINK_FIELDS.contains(&field))
}

/// 연결 유형 키의 허용 목록 검사.
pub fn link_key_ok(parts: &[&str]) -> bool {
    parts.len() == 4
        && parts[0] == "B-C"
        && LINK_FIELDS.contains(&parts[1])
        && LINK_SCOPES.contains(&parts[2])
        && LINK_CHANGES.contains(&parts[3])
}

/// Python 다리 `links` 호출 자리. 시험은 골든의 기대 출력을 가짜 Python으로 쓴다.
pub trait LinksSource {
    fn refund(&self, db: &Path) -> Result<Value, ShadowError>;
    fn ota(&self, input: &Value) -> Result<Value, ShadowError>;
}

impl LinksSource for PythonBridge {
    fn refund(&self, db: &Path) -> Result<Value, ShadowError> {
        Ok(self.links_json(&json!({"kind": "refund", "db": db.to_string_lossy()}))?)
    }

    fn ota(&self, input: &Value) -> Result<Value, ShadowError> {
        let mut body = input.clone();
        body["kind"] = json!("ota");
        Ok(self.links_json(&body)?)
    }
}

/// 비공개 상세(거래·이벤트 ID 포함). 보호 경로 안 파일에만 쓴다.
#[derive(Debug, Clone, PartialEq)]
pub struct LinkDiff {
    pub key: String,
    pub id: String,
    pub python: Value,
    pub rust: Value,
}

impl LinkDiff {
    pub fn line(&self) -> String {
        json!({"id": self.id, "key": self.key, "python": self.python, "rust": self.rust})
            .to_string()
    }
}

/// 한 영역(환불 짝 또는 OTA)의 비교 결과.
#[derive(Debug, Clone, PartialEq)]
pub struct LinksPart {
    pub python_items: u64,
    pub rust_items: u64,
    pub diffs: Vec<LinkDiff>,
}

#[derive(Debug, Clone, PartialEq)]
pub struct LinksReport {
    pub refund: Option<LinksPart>,
    pub ota: Option<LinksPart>,
    pub types: BTreeMap<String, u64>,
    pub verdict: Verdict,
}

impl LinksReport {
    pub fn passed(&self) -> bool {
        self.verdict.passed()
    }

    pub fn private_lines(&self) -> Vec<String> {
        self.parts()
            .flat_map(|p| p.diffs.iter().map(LinkDiff::line))
            .collect()
    }

    fn parts(&self) -> impl Iterator<Item = &LinksPart> {
        self.refund.iter().chain(self.ota.iter())
    }

    /// 공개 보고. 모든 유형 키를 허용 목록으로 다시 검사한다.
    pub fn public_json(&self) -> Result<Value, ShadowError> {
        let part = |p: &Option<LinksPart>| {
            p.as_ref().map_or(
                Value::Null,
                |p| json!({"python": p.python_items, "rust": p.rust_items}),
            )
        };
        let mut types = Vec::new();
        for (key, count) in &self.types {
            validate_key(key)?;
            types.push(json!({"key": key, "count": count}));
        }
        for key in self.verdict.unlisted.iter().chain(&self.verdict.resolved) {
            validate_key(key)?;
        }
        Ok(json!({
            "status": if self.passed() { "PASS" } else { "FAIL" },
            "refund": part(&self.refund),
            "ota": part(&self.ota),
            "types": types,
            "unlisted": self.verdict.unlisted,
            "resolved": self.verdict.resolved,
        }))
    }
}

fn status_scope(value: &Value) -> String {
    match value["status"].as_str() {
        Some(s) if LINK_SCOPES.contains(&s) => s.to_owned(),
        Some(_) => "other".to_owned(),
        None => "none".to_owned(),
    }
}

fn text_scope(value: &Value) -> String {
    match value.as_str() {
        Some(s) if !s.is_empty() && LINK_SCOPES.contains(&s) => s.to_owned(),
        Some(s) if !s.is_empty() => "other".to_owned(),
        _ => "none".to_owned(),
    }
}

fn no_scope(_: &Value) -> String {
    "none".to_owned()
}

/// 두 쪽 맵을 ID별로 대조한다. 한쪽에만 있으면 added(Rust만)·removed(Python만), 값이 다르면 differs.
fn diff_maps(
    field: &str,
    python: &Map<String, Value>,
    rust: &Map<String, Value>,
    scope: fn(&Value) -> String,
) -> Vec<LinkDiff> {
    let mut diffs = Vec::new();
    let mut ids: Vec<&String> = python.keys().chain(rust.keys()).collect();
    ids.sort();
    ids.dedup();
    for id in ids {
        let (change, basis) = match (python.get(id), rust.get(id)) {
            (Some(p), Some(r)) if p == r => continue,
            (Some(p), Some(_)) => ("differs", p),
            (Some(p), None) => ("removed", p),
            (None, Some(r)) => ("added", r),
            (None, None) => continue,
        };
        diffs.push(LinkDiff {
            key: format!("B-C|{field}|{}|{change}", scope(basis)),
            id: id.clone(),
            python: python.get(id).cloned().unwrap_or(Value::Null),
            rust: rust.get(id).cloned().unwrap_or(Value::Null),
        });
    }
    diffs
}

fn object<'a>(value: &'a Value, key: &str) -> Result<&'a Map<String, Value>, ShadowError> {
    value[key]
        .as_object()
        .ok_or(ShadowError::PlanResponseInvalid)
}

fn id_set(value: &Value, key: &str) -> Result<Map<String, Value>, ShadowError> {
    let list = value[key]
        .as_array()
        .ok_or(ShadowError::PlanResponseInvalid)?;
    Ok(list
        .iter()
        .filter_map(|v| v.as_str().map(|s| (s.to_owned(), json!(true))))
        .collect())
}

/// `TxnRow` → 짝 도출 입력. 열 이름·빈 칸 규칙은 Python `COALESCE(x,'')`와 같다.
pub fn refund_rows(rows: &[TxnRow]) -> Vec<RefundTxn> {
    rows.iter()
        .map(|r| RefundTxn {
            transaction_id: r.transaction_id.clone(),
            issuer: r.issuer.clone(),
            card_tail: r.card_tail.clone(),
            direction: r.transaction_direction.clone(),
            approval_number: r.approval_number.clone(),
            original_approval_number: r.original_approval_number.clone(),
            amount_krw: r.amount_krw,
            approval_date: r.approval_date.clone(),
            posting_date: r.posting_date.clone(),
            merchant: r.merchant.clone(),
            merchant_normalized: r.merchant_normalized.clone(),
            foreign_amount: r.foreign_amount.clone(),
            foreign_currency: r.foreign_currency.clone(),
            duplicate_of: r.duplicate_of.clone(),
            conflict_reason: r.conflict_reason.clone(),
            parse_error: r.parse_error.clone(),
        })
        .collect()
}

/// 호출자가 표준 입력으로 보낸 원행(열 이름 키의 객체 배열, 순서 유지) → 짝 도출 입력. 빈 문자열 열은 null도 받는다
/// (Python `COALESCE(x,'')`). 모양이 다르면 `PlanResponseInvalid`다.
pub fn refund_rows_from_json(value: &Value) -> Result<Vec<RefundTxn>, ShadowError> {
    let rows = value.as_array().ok_or(ShadowError::PlanResponseInvalid)?;
    rows.iter().map(refund_row_from_json).collect()
}

fn refund_row_from_json(row: &Value) -> Result<RefundTxn, ShadowError> {
    if !row.is_object() {
        return Err(ShadowError::PlanResponseInvalid);
    }
    let text = |key: &str| -> Result<String, ShadowError> {
        match row.get(key) {
            None | Some(Value::Null) => Ok(String::new()),
            Some(Value::String(s)) => Ok(s.clone()),
            Some(_) => Err(ShadowError::PlanResponseInvalid),
        }
    };
    let amount_krw = match row.get("amount_krw") {
        None | Some(Value::Null) => None,
        Some(v) => Some(v.as_i64().ok_or(ShadowError::PlanResponseInvalid)?),
    };
    let duplicate_of = match row.get("duplicate_of") {
        None | Some(Value::Null) => None,
        Some(Value::String(s)) => Some(s.clone()),
        Some(_) => return Err(ShadowError::PlanResponseInvalid),
    };
    Ok(RefundTxn {
        transaction_id: text("transaction_id")?,
        issuer: text("issuer")?,
        card_tail: text("card_tail")?,
        direction: text("transaction_direction")?,
        approval_number: text("approval_number")?,
        original_approval_number: text("original_approval_number")?,
        amount_krw,
        approval_date: text("approval_date")?,
        posting_date: text("posting_date")?,
        merchant: text("merchant")?,
        merchant_normalized: text("merchant_normalized")?,
        foreign_amount: text("foreign_amount")?,
        foreign_currency: text("foreign_currency")?,
        duplicate_of,
        conflict_reason: text("conflict_reason")?,
        parse_error: text("parse_error")?,
    })
}

/// Rust 환불 짝 결과를 Python 다리 `links` 출력과 같은 모양으로 만든다.
pub fn refund_values(refunds: &Refunds) -> Value {
    let links: Map<String, Value> = refunds
        .links()
        .iter()
        .map(|l| {
            let mut out = json!({
                "gross_krw": l.gross_krw, "net_krw": l.net_krw, "original_id": l.original_id,
                "refund_count": l.refund_count, "refund_krw": l.refund_krw,
                "refunds_total_krw": l.refunds_total_krw, "status": l.status.as_str(),
            });
            if let Some(basis) = l.basis {
                out["basis"] = json!(basis.as_str());
                if basis != Basis::MerchantCardForeignAmount {
                    out["inferred"] = json!(l.inferred);
                    out["matching_source"] = json!("automatic");
                }
            }
            (l.refund_id.clone(), out)
        })
        .collect();
    let originals = refunds.originals();
    let groups: Map<String, Value> = originals
        .iter()
        .map(|o| (o.clone(), json!(refunds.group(o))))
        .collect();
    let exclusions: Map<String, Value> = originals
        .iter()
        .map(|o| {
            (
                o.clone(),
                json!(refunds.exclusion(o).map_or("", Exclusion::as_str)),
            )
        })
        .collect();
    let held: Map<String, Value> = refunds
        .held()
        .iter()
        .map(|(k, h)| {
            (
                k.clone(),
                json!({"purchases": h.purchases, "cancellations": h.cancellations}),
            )
        })
        .collect();
    json!({
        "links": links, "groups": groups, "group_exclusions": exclusions,
        "held": held, "review_originals": refunds.review_originals(),
    })
}

/// 같은 환불 ID의 연결이 둘이면 맵에서 하나가 덮이므로, 연결 개수와 맵 크기를 대조해 드러낸다.
pub fn duplicate_link_diff(
    rust_links: usize,
    map_size: usize,
    python_links: usize,
) -> Option<LinkDiff> {
    (rust_links != map_size).then(|| LinkDiff {
        key: "B-C|refund_link|none|differs".to_owned(),
        id: String::new(),
        python: json!(python_links),
        rust: json!(rust_links),
    })
}

/// 환불 짝: 같은 행에서 Rust가 도출한 값과 Python 다리 출력(`links` kind=refund)을 대조한다.
pub fn compare_refund(
    rows: &[RefundTxn],
    config: &PairingConfig,
    python: &Value,
) -> Result<LinksPart, ShadowError> {
    let refunds = Refunds::derive(rows, config);
    let rust = refund_values(&refunds);
    let mut diffs = Vec::new();
    diffs.extend(duplicate_link_diff(
        refunds.links().len(),
        object(&rust, "links")?.len(),
        object(python, "links")?.len(),
    ));
    for (field, key, scope) in [
        ("refund_link", "links", status_scope as fn(&Value) -> String),
        ("refund_group", "groups", no_scope),
        ("refund_exclusion", "group_exclusions", text_scope),
        ("refund_held", "held", no_scope),
    ] {
        diffs.extend(diff_maps(
            field,
            object(python, key)?,
            object(&rust, key)?,
            scope,
        ));
    }
    diffs.extend(diff_maps(
        "refund_review",
        &id_set(python, "review_originals")?,
        &id_set(&rust, "review_originals")?,
        no_scope,
    ));
    Ok(LinksPart {
        python_items: object(python, "links")?.len() as u64,
        rust_items: refunds.links().len() as u64,
        diffs,
    })
}

/// 운영 사본 DB에서 환불 짝을 비교한다(전체 거래).
pub fn run_refund(
    db: &Path,
    source: &dyn LinksSource,
    config: &PairingConfig,
) -> Result<LinksPart, ShadowError> {
    let rows = refund_rows(&read_projection(db)?.transactions);
    let python = source.refund(db)?;
    compare_refund(&rows, config, &python)
}

const OTA_KEYS: [&str; 25] = [
    "ota_event_id",
    "status",
    "reason",
    "transaction_id",
    "candidates",
    "reserved_card_ids",
    "group_count",
    "ota_group_ids",
    "card_group_ids",
    "matched_count",
    "unmatched_ota_count",
    "unmatched_card_count",
    "allocation_basis",
    "group_order_frozen",
    "group_order_snapshot",
    "individual_payment_evidence",
    "review_warning",
    "frozen_mapping",
    "proposed_mapping",
    "rule_delta_krw",
    "discount_cause_confirmed",
    "payment_date_verified",
    "inferred_link",
    "inference_basis",
    "payment_relation",
];

fn list(input: &Value, key: &str) -> Vec<Value> {
    input[key].as_array().cloned().unwrap_or_default()
}

fn by_event(results: &[Value]) -> (Map<String, Value>, bool) {
    let mut map = Map::new();
    let mut duplicate = false;
    for result in results {
        let kept = match result.as_object() {
            Some(o) => Value::Object(
                o.iter()
                    .filter(|(k, _)| OTA_KEYS.contains(&k.as_str()))
                    .map(|(k, v)| (k.clone(), v.clone()))
                    .collect(),
            ),
            None => result.clone(),
        };
        let id = result["ota_event_id"].as_str().unwrap_or("").to_owned();
        duplicate |= map.insert(id, kept).is_some();
    }
    (map, duplicate)
}

/// 운영 `dict(event, **link)`와 같이 입력 사건 칸 위에 연결 칸을 덮는다.
pub fn overlay_event(event: Option<&Value>, link: &Value) -> Value {
    let mut row = event
        .and_then(Value::as_object)
        .cloned()
        .unwrap_or_default();
    if let Some(link) = link.as_object() {
        row.extend(link.iter().map(|(k, v)| (k.clone(), v.clone())));
    }
    Value::Object(row)
}

/// OTA 연결: 풀이기 입력으로 Rust `Matcher`를 돌려 Python 출력(`links` kind=ota)과 연결 칸만 대조한다.
pub fn compare_ota(
    input: &Value,
    defaults: &Defaults,
    python: &Value,
) -> Result<LinksPart, ShadowError> {
    let (events, cards) = (list(input, "events"), list(input, "transactions"));
    let rules = list(input, "rules");
    let frozen = list(input, "frozen_groups");
    let existing = input["existing_links"]
        .as_object()
        .cloned()
        .unwrap_or_default();
    let rust: Vec<Value> = Matcher::new(defaults, &rules)
        .match_events(&events, &cards, &existing, &frozen)
        .iter()
        .map(|l| {
            let link = l.to_value();
            let source = events
                .iter()
                .find(|e| e["ota_event_id"] == link["ota_event_id"]);
            overlay_event(source, &link)
        })
        .collect();
    let python_results = python["results"]
        .as_array()
        .ok_or(ShadowError::PlanResponseInvalid)?;
    let (py_map, py_dup) = by_event(python_results);
    let (rs_map, rs_dup) = by_event(&rust);
    let mut diffs = diff_maps("ota_link", &py_map, &rs_map, status_scope);
    if py_dup || rs_dup || python_results.len() != rust.len() {
        diffs.push(LinkDiff {
            key: "B-C|ota_link|none|differs".to_owned(),
            id: String::new(),
            python: json!(python_results.len()),
            rust: json!(rust.len()),
        });
    }
    Ok(LinksPart {
        python_items: python_results.len() as u64,
        rust_items: rust.len() as u64,
        diffs,
    })
}

pub fn run_ota(
    input: &Value,
    source: &dyn LinksSource,
    defaults: &Defaults,
) -> Result<LinksPart, ShadowError> {
    let python = source.ota(input)?;
    compare_ota(input, defaults, &python)
}

/// 두 영역의 차이를 모아 목록 대조로 판정한다(연결 키만 본다).
pub fn judge_links(
    refund: Option<LinksPart>,
    ota: Option<LinksPart>,
    known: &KnownDiffs,
) -> LinksReport {
    let mut types: BTreeMap<String, u64> = BTreeMap::new();
    for diff in refund.iter().chain(ota.iter()).flat_map(|p| &p.diffs) {
        *types.entry(diff.key.clone()).or_default() += 1;
    }
    let observed = types.keys().cloned().collect();
    let verdict = judge(&known.only_link_keys(), &observed);
    LinksReport {
        refund,
        ota,
        types,
        verdict,
    }
}
