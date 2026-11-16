//! 환불 판정 봉인의 JSON 입·출력(M3 U12 묶음 판정 → 게시 단위 소비). `links refund-entries`/`links refund-check`가 쓴다.
//!
//! 규칙: 입력은 주문이 아니라 **봉인 입력**이다. 원소가 출처 행에서 왔는지(외부 ID·중복·모양 파손)를 여기서 엄격히
//! 세우고, 판정은 `Refunds`에서 다시 도출한 것만 쓴다. `RefundGroup` 발급은 검증 함수(`issue_group`)가 유일하고,
//! `entries` 출력은 요청의 `id`·`already_booked`·`external`을 보존하며 `ready`·`blocked`·귀속·`refund_link`만 바꾼다.
//! `check`는 이번에 기록할 멤버가 있는 검증 묶음만, 일부만 기록 가능한 묶음은 내지 않는다. 새 저장 경로·스키마·writer가 없다.

use std::collections::{BTreeMap, BTreeSet};
use std::fmt;

use serde_json::{Map, Value, json};

use super::{Authority, Block, Entry, Refunds, Refusal, Role};
use crate::links::refund::{self, RefundInputInvalid, RefundTxn};

impl From<RefundInputInvalid> for VerdictError {
    fn from(_: RefundInputInvalid) -> Self {
        Self::new()
    }
}

impl From<Refusal> for VerdictError {
    fn from(refusal: Refusal) -> Self {
        Self::coded(refusal.code())
    }
}

/// 입력 모양이 깨졌을 때의 고정 코드.
pub const INVALID: &str = "REFUND_VERDICT_INVALID";

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct VerdictError {
    pub code: &'static str,
}

impl VerdictError {
    fn new() -> Self {
        Self { code: INVALID }
    }

    fn coded(code: &'static str) -> Self {
        Self { code }
    }
}

impl fmt::Display for VerdictError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.write_str(self.code)
    }
}

impl std::error::Error for VerdictError {}

fn object(value: &Value) -> Result<&Map<String, Value>, VerdictError> {
    value.as_object().ok_or_else(VerdictError::new)
}

fn text(value: Option<&Value>) -> Result<String, VerdictError> {
    match value {
        None | Some(Value::Null) => Ok(String::new()),
        Some(Value::String(s)) => Ok(s.clone()),
        Some(_) => Err(VerdictError::new()),
    }
}

fn flag(value: Option<&Value>, fallback: bool) -> Result<bool, VerdictError> {
    match value {
        None | Some(Value::Null) => Ok(fallback),
        Some(Value::Bool(b)) => Ok(*b),
        Some(_) => Err(VerdictError::new()),
    }
}

/// 입력 한 판. `rows`·`entries`·`booked`의 ID는 출처 행 ID 안에 있어야 하고 중복이 없어야 한다.
pub struct VerdictInput {
    pub rows: Vec<RefundTxn>,
    pub entries: Vec<Entry>,
    pub booked: BTreeSet<String>,
    pub trips: Option<BTreeMap<String, bool>>,
    pub tabs: Option<BTreeMap<String, bool>>,
}

/// DTO 파싱: `{rows, entries, booked, authority}`(authority `null` | `{trips, tabs}`).
pub fn parse_input(value: &Value) -> Result<VerdictInput, VerdictError> {
    let root = object(value)?;
    let rows = refund::refund_rows_from_json(root.get("rows").ok_or_else(VerdictError::new)?)?;
    let ids: BTreeSet<&str> = rows.iter().map(|r| r.transaction_id.as_str()).collect();
    let mut entries = Vec::new();
    let mut entry_ids: BTreeSet<String> = BTreeSet::new();
    let list = root
        .get("entries")
        .and_then(Value::as_array)
        .ok_or_else(VerdictError::new)?;
    for raw in list {
        let map = object(raw)?;
        let id = text(map.get("id"))?;
        if id.is_empty() || id.trim() != id {
            return Err(VerdictError::new());
        }
        if !ids.contains(id.as_str()) || !entry_ids.insert(id.clone()) {
            return Err(VerdictError::new());
        }
        let blocked = match map.get("blocked") {
            None | Some(Value::Null) => None,
            Some(Value::Object(b)) => {
                let code = text(b.get("code"))?;
                let reason = text(b.get("reason"))?;
                if code.is_empty() {
                    return Err(VerdictError::new());
                }
                Some(Block { code, reason })
            }
            Some(_) => return Err(VerdictError::new()),
        };
        let already_booked = flag(map.get("already_booked"), false)?;
        let external = flag(map.get("external"), false)?;
        let ready = flag(map.get("ready"), !already_booked && blocked.is_none())?;
        entries.push(Entry {
            id,
            item: text(map.get("item"))?,
            display_tab_id: text(map.get("display_tab_id"))?,
            trip_id: text(map.get("trip_id"))?,
            description: text(map.get("description"))?,
            blocked,
            already_booked,
            external,
            ready,
            refund_link: None,
        });
    }
    let mut booked = BTreeSet::new();
    let list = root
        .get("booked")
        .and_then(Value::as_array)
        .ok_or_else(VerdictError::new)?;
    for raw in list {
        let Some(id) = raw.as_str() else {
            return Err(VerdictError::new());
        };
        if id.trim().is_empty() || !ids.contains(id) || !booked.insert(id.to_owned()) {
            return Err(VerdictError::new());
        }
    }
    let authority = root.get("authority");
    let trips = map_of(authority, "trips")?;
    let tabs = map_of(authority, "tabs")?;
    Ok(VerdictInput {
        rows,
        entries,
        booked,
        trips,
        tabs,
    })
}

fn map_of(
    authority: Option<&Value>,
    key: &str,
) -> Result<Option<BTreeMap<String, bool>>, VerdictError> {
    match authority {
        None | Some(Value::Null) => Ok(None),
        Some(map) => {
            let map = object(map)?;
            match map.get(key) {
                None | Some(Value::Null) => Ok(None),
                Some(Value::Object(inner)) => {
                    let mut out = BTreeMap::new();
                    for (id, flag) in inner {
                        if id.trim().is_empty() || !flag.is_boolean() {
                            return Err(VerdictError::new());
                        }
                        out.insert(id.clone(), flag.as_bool().unwrap_or(false));
                    }
                    Ok(Some(out))
                }
                Some(_) => Err(VerdictError::new()),
            }
        }
    }
}

/// 소유 지도를 쓰는 검증기.
fn owned_validator(map: BTreeMap<String, bool>) -> impl Fn(&str) -> bool {
    move |id: &str| map.get(id).copied().unwrap_or(false)
}

/// `&impl Fn` → `&dyn Fn`(수명 유지).
fn as_dyn(f: &impl Fn(&str) -> bool) -> &dyn Fn(&str) -> bool {
    f
}

fn block_json(block: &Option<Block>) -> Value {
    match block {
        None => Value::Null,
        Some(b) => json!({"code": b.code, "reason": b.reason}),
    }
}

fn note_json(note: &refund::RefundNote) -> Value {
    let mut out = json!({
        "gross_krw": note.gross_krw,
        "refund_krw": note.refund_krw,
        "net_krw": note.net_krw,
        "status": note.status.as_str(),
        "role": match note.role {
            Role::Original => "original",
            Role::Refund => "refund",
        },
        "counterpart_id": note.counterpart_id,
    });
    if let Some(basis) = note.basis {
        out["basis"] = json!(basis.as_str());
    }
    if note.inferred {
        out["inferred"] = json!(true);
    }
    out
}

/// `links refund-entries`: 도출 → 적용 → 입력 항목 하나를 빠짐없이 그대로 돌려준다.
pub fn entries_verdict(input: &VerdictInput, config: &refund::PairingConfig) -> Value {
    let refunds = Refunds::derive(&input.rows, config);
    let mut entries = input.entries.clone();
    let trip_owner = input.trips.clone().map(owned_validator);
    let tab_owner = input.tabs.clone().map(owned_validator);
    let auth = Authority {
        trip: trip_owner.as_ref().map(as_dyn),
        tab: tab_owner.as_ref().map(as_dyn),
    };
    refund::apply_pairs(&refunds, &mut entries, &auth);
    let entries: Vec<Value> = entries
        .iter()
        .map(|e| {
            json!({
                "id": e.id,
                "already_booked": e.already_booked,
                "external": e.external,
                "ready": e.ready,
                "blocked": block_json(&e.blocked),
                "item": e.item,
                "display_tab_id": e.display_tab_id,
                "trip_id": e.trip_id,
                "description": e.description,
                "refund_link": e.refund_link.as_ref().map(note_json),
            })
        })
        .collect();
    json!({"ok": true, "result": {"entries": entries}})
}

/// `links refund-check`: `check_groups` 뒤, 이번에 기록할 멤버가 있는 검증 묶음만 `scope_group`·`issue_group`로
/// 봉인한다(일부만 기록 가능한 묶음·제외 사유·검증 밖 연결은 내지 않는다).
pub fn check_verdict(
    input: &VerdictInput,
    config: &refund::PairingConfig,
) -> Result<Value, VerdictError> {
    let refunds = Refunds::derive(&input.rows, config);
    let rows = supplement_booked(input);
    refund::check_groups(&refunds, &rows, &input.booked)?;
    let mut ready: BTreeSet<&str> = BTreeSet::new();
    for entry in &rows {
        if entry.ready && !entry.already_booked {
            ready.insert(entry.id.as_str());
        }
    }
    let mut groups = Vec::new();
    for original in refunds.originals() {
        let members = refunds.group(&original);
        if !members.iter().any(|m| ready.contains(m.as_str())) {
            continue;
        }
        if let Some(missing) = members.iter().find(|m| !rows.iter().any(|e| &e.id == *m)) {
            return Err(VerdictError::coded(
                Refusal::MemberMissing(missing.clone()).code(),
            ));
        }
        // `scope_group`의 `recordable=false`(예: 구성원이 이미 기록된 채 다른 구성원이 보류)도 게시 금지다:
        // `check_groups`는 묶음에 이미 기록된 멤버가 있으면 HalfBooked를 건너뛰므로 이 경계가 필요하다.
        match refund::scope_group(&refunds, &rows, &original) {
            Ok(scope) if scope.recordable => {}
            Ok(_) => return Err(VerdictError::coded(Refusal::HalfBooked.code())),
            Err(error) => return Err(VerdictError::from(error)),
        }
        let group = refund::issue_group(&refunds, &rows, &original)?;
        groups.push(json!({
            "id": group.id().as_str(),
            "members": group.members().iter().map(|m| m.as_str().to_owned()).collect::<Vec<_>>(),
        }));
    }
    Ok(json!({"ok": true, "result": {"groups": groups}}))
}

/// `booked`에만 있는 구성원은 `already_booked: true` 항목으로 보충한다(입력 항목 누락 허용, 원시 ID 집합은 이미 검사했다).
fn supplement_booked(input: &VerdictInput) -> Vec<Entry> {
    let mut rows: Vec<Entry> = input.entries.clone();
    let mut seen: BTreeSet<String> = rows.iter().map(|e| e.id.clone()).collect();
    for id in &input.booked {
        if seen.insert(id.clone()) {
            rows.push(Entry {
                id: id.clone(),
                already_booked: true,
                ..Entry::default()
            });
        }
    }
    rows
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    fn row(id: &str, direction: &str, amount: i64, original: &str) -> Value {
        json!({
            "transaction_id": id, "issuer": "SYN-BANK", "card_tail": "0001",
            "transaction_direction": direction, "approval_number": format!("SYN-A-{id}"),
            "original_approval_number": original, "amount_krw": amount,
            "approval_date": "2026-10-03", "posting_date": "2026-10-05",
            "merchant": "SYN SHOP", "merchant_normalized": "SYN SHOP",
            "foreign_amount": "", "foreign_currency": "",
            "duplicate_of": Value::Null, "conflict_reason": "", "parse_error": ""
        })
    }

    #[test]
    fn parse_rejects_foreign_duplicate_and_broken_entries() {
        let rows = json!([row("a", "purchase", 1000, "")]);
        for entries in [
            json!([{"id": "a", "blocked": null, "already_booked": false, "external": false, "ready": true},
                   {"id": "a", "blocked": null, "already_booked": false, "external": false, "ready": true}]),
            json!([{"id": "zz", "blocked": null, "already_booked": false, "external": false, "ready": true}]),
            json!([{"id": " a", "blocked": null, "already_booked": false, "external": false, "ready": true}]),
            json!([{"id": "a", "blocked": "x", "already_booked": false, "external": false, "ready": true}]),
            json!([{"id": "a", "blocked": null, "already_booked": "no", "external": false, "ready": true}]),
        ] {
            let value = json!({"rows": rows, "entries": entries, "booked": [], "authority": null});
            assert_eq!(parse_input(&value).err().unwrap().code, INVALID);
        }
        let value = json!({"rows": rows, "entries": [], "booked": ["zz"], "authority": null});
        assert_eq!(parse_input(&value).err().unwrap().code, INVALID);
        // 권위 지도는 여행/탭 ID 도메인이다: 출처 거래 ID 집합과 비교하지 않는다(다른 도메인 ID 허용).
        let input = parse_input(
            &json!({"rows": rows, "entries": [], "booked": [], "authority": {"trips": {"T-A": true, "syn-v1": true}}}),
        )
        .unwrap();
        assert_eq!(
            input.trips.as_ref().unwrap().get("syn-v1"),
            Some(&true),
            "다른 도메인 ID라도 형식(키 비어있지 않음·boolean)만 맞으면 받는다"
        );
        let value = json!({"rows": rows, "entries": [], "booked": [], "authority": {"trips": {"a": "yes"}}});
        assert_eq!(parse_input(&value).err().unwrap().code, INVALID);
        let value =
            json!({"rows": rows, "entries": [], "booked": [], "authority": {"trips": {"": true}}});
        assert_eq!(parse_input(&value).err().unwrap().code, INVALID);
        // authority null = 검증기 없음(None), 빈 객체 = 둘 다 없음.
        assert!(
            parse_input(&json!({"rows": rows, "entries": [], "booked": [], "authority": null}))
                .unwrap()
                .trips
                .is_none()
        );
        assert!(
            parse_input(&json!({"rows": rows, "entries": [], "booked": [], "authority": {}}))
                .unwrap()
                .tabs
                .is_none()
        );
    }
}
