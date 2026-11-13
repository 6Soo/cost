//! 규칙 한 건의 검증과 정규형. 원본: `app/rules.py` `normalize_rule`(`:135-258`).
//!
//! 거부 조건·문구·오류 코드는 Python과 같다. 날짜는 `YYYY-MM-DD`만 받는다(Python의 느슨한 날짜 해석은 옮기지 않는다).

use super::{RuleError, text::normalize_merchant};
use crate::dates::parse_iso;
use serde_json::{Map, Value};

const ALLOWED_DRAFT: [&str; 6] = [
    "conditions",
    "optional",
    "effects",
    "note",
    "origin",
    "rule_id",
];
const CONDITION_FIELDS: [&str; 3] = ["merchant_normalized", "card_kind", "transaction_direction"];
const OPTIONAL_FIELDS: [&str; 7] = [
    "amount_range",
    "date_or_service_period",
    "travel_country",
    "source_hash",
    "booking_period",
    "inferred_assignment",
    "merchant_family",
];
const EFFECT_FIELDS: [&str; 3] = ["item", "description", "display_tab_id"];
const TRAVEL_COUNTRIES: [&str; 8] = ["local", "overseas", "JP", "KR", "TW", "AT", "IT", "FR"];

/// 정규화된(또는 DB에서 읽은) 규칙. Python dict처럼 값을 그대로 들고 있고 평가가 읽는다.
#[derive(Debug, Clone, PartialEq, Default)]
pub struct Rule {
    pub rule_id: String,
    pub version: i64,
    pub conditions: Map<String, Value>,
    pub optional: Map<String, Value>,
    pub effects: Map<String, Value>,
    pub origin: String,
    pub note: String,
}

impl Rule {
    /// 검증 없이 읽는다(저장된 규칙·합성 입력용). 검증이 필요하면 `normalize_rule`을 쓴다.
    pub fn from_value(v: &Value) -> Rule {
        let map = |key: &str| {
            v.get(key)
                .and_then(Value::as_object)
                .cloned()
                .unwrap_or_default()
        };
        let text = |key: &str| {
            v.get(key)
                .and_then(Value::as_str)
                .unwrap_or_default()
                .to_string()
        };
        Rule {
            rule_id: text("rule_id"),
            version: v.get("version").and_then(Value::as_i64).unwrap_or(1),
            conditions: map("conditions"),
            optional: map("optional"),
            effects: map("effects"),
            origin: text("origin"),
            note: text("note"),
        }
    }

    /// `normalize_rule`이 돌려주는 사전과 같은 모양.
    pub fn to_value(&self) -> Value {
        serde_json::json!({
            "conditions": self.conditions,
            "optional": self.optional,
            "effects": self.effects,
            "note": self.note,
            "origin": self.origin,
            "rule_id": self.rule_id,
        })
    }

    pub(crate) fn merchant(&self) -> &str {
        self.conditions
            .get("merchant_normalized")
            .and_then(Value::as_str)
            .unwrap_or("")
    }

    /// Python `optional.get(key)`가 참인 값.
    pub(crate) fn opt(&self, key: &str) -> Option<&Value> {
        self.optional.get(key).filter(|v| truthy(v))
    }

    pub(crate) fn effect(&self, key: &str) -> &str {
        self.effects.get(key).and_then(Value::as_str).unwrap_or("")
    }
}

/// Python 참/거짓.
pub(crate) fn truthy(v: &Value) -> bool {
    match v {
        Value::Null => false,
        Value::Bool(b) => *b,
        Value::Number(n) => n.as_f64() != Some(0.0),
        Value::String(s) => !s.is_empty(),
        Value::Array(a) => !a.is_empty(),
        Value::Object(o) => !o.is_empty(),
    }
}

/// Python `str(value or "")`.
fn text_of(v: &Value) -> String {
    if !truthy(v) {
        return String::new();
    }
    match v {
        Value::String(s) => s.clone(),
        Value::Bool(_) => "True".to_string(),
        other => other.to_string(),
    }
}

fn py_list(items: &[&str]) -> String {
    let inner: Vec<String> = items.iter().map(|s| format!("'{s}'")).collect();
    format!("[{}]", inner.join(", "))
}

/// `value or {}`. 객체가 아닌 참값은 `Err`로 돌려 호출자가 형식 오류를 낸다.
fn object_or_empty<'a>(
    v: Option<&'a Value>,
    empty: &'a Map<String, Value>,
) -> Option<&'a Map<String, Value>> {
    match v {
        None => Some(empty),
        Some(value) if !truthy(value) => Some(empty),
        Some(Value::Object(o)) => Some(o),
        Some(_) => None,
    }
}

fn is_hex64(s: &str) -> bool {
    s.len() == 64 && s.bytes().all(|b| matches!(b, b'0'..=b'9' | b'a'..=b'f'))
}

fn amount_krw(v: &Value) -> Option<i64> {
    match v {
        Value::Number(n) => n.as_i64().or_else(|| {
            n.as_f64()
                .filter(|f| f.fract() == 0.0 && f.abs() < 9e15)
                .map(|f| f as i64)
        }),
        Value::String(s) => {
            let mut text = s.trim().to_string();
            let mut negative = text.starts_with('(') && text.ends_with(')');
            if negative {
                text = text[1..text.len() - 1].trim().to_string();
            }
            text.retain(|c| !(c == ',' || c.is_whitespace() || c == '원' || c == '₩'));
            if let Some(rest) = text.strip_prefix('+') {
                text = rest.to_string();
            } else if let Some(rest) = text.strip_prefix('-') {
                negative = !negative;
                text = rest.to_string();
            }
            let (whole, fraction) = text.split_once('.').unwrap_or((&text, ""));
            let digits = |t: &str| t.bytes().all(|b| b.is_ascii_digit());
            if whole.is_empty()
                || !digits(whole)
                || !digits(fraction)
                || fraction.bytes().any(|b| b != b'0')
            {
                return None;
            }
            let magnitude: i64 = whole.parse().ok()?;
            Some(if negative { -magnitude } else { magnitude })
        }
        _ => None,
    }
}

fn date_or_empty(v: &Value) -> String {
    match v.as_str() {
        Some(s) if parse_iso(s).is_ok() => s.to_string(),
        _ => String::new(),
    }
}

/// 규칙 하나를 검증하고 정규형을 돌려준다. `merchant_normalized`는 필수다: 가맹점 조건이 없으면
/// 모든 카드의 모든 입수에 걸린다. (원천 금액·날짜·거래 ID 필드 금지는 허용 키 검사가 먼저 막는다.)
pub fn normalize_rule(draft: &Value) -> Result<Rule, RuleError> {
    let fail = |m: &str| Err(RuleError::invalid(m));
    let Some(draft) = draft.as_object() else {
        return fail("규칙 형식이 달라요");
    };
    let mut unknown: Vec<&str> = draft
        .keys()
        .map(String::as_str)
        .filter(|k| !ALLOWED_DRAFT.contains(k))
        .collect();
    unknown.sort_unstable();
    if !unknown.is_empty() {
        return fail(&format!(
            "규칙에 쓸 수 없는 항이 있어요: {}",
            py_list(&unknown)
        ));
    }

    let empty = Map::new();
    let Some(raw_conditions) = object_or_empty(draft.get("conditions"), &empty) else {
        return fail("조건 형식이 달라요");
    };
    let mut bad: Vec<&str> = raw_conditions
        .keys()
        .map(String::as_str)
        .filter(|k| !CONDITION_FIELDS.contains(k))
        .collect();
    bad.sort_unstable();
    if !bad.is_empty() {
        return fail(&format!("허용되지 않은 조건이에요: {}", py_list(&bad)));
    }
    let mut conditions = Map::new();
    for (field, value) in raw_conditions {
        if field == "merchant_normalized" {
            let merchant = normalize_merchant(&text_of(value));
            if merchant.is_empty() {
                return fail("가맹점 조건이 비어 있어요");
            }
            conditions.insert(field.clone(), Value::String(merchant));
        } else {
            let text = text_of(value).trim().to_string();
            if text.is_empty() {
                return fail(&format!("{field} 조건이 비어 있어요"));
            }
            let text = if field == "card_kind" {
                super::text::casefold(&text)
            } else {
                text
            };
            conditions.insert(field.clone(), Value::String(text));
        }
    }
    let Some(merchant) = conditions
        .get("merchant_normalized")
        .and_then(Value::as_str)
        .map(str::to_string)
    else {
        return fail("가맹점 조건은 반드시 필요해요");
    };

    let Some(raw_optional) = object_or_empty(draft.get("optional"), &empty) else {
        return fail("선택 조건 형식이 달라요");
    };
    let mut bad: Vec<&str> = raw_optional
        .keys()
        .map(String::as_str)
        .filter(|k| !OPTIONAL_FIELDS.contains(k))
        .collect();
    bad.sort_unstable();
    if !bad.is_empty() {
        return fail(&format!("허용되지 않은 선택 조건이에요: {}", py_list(&bad)));
    }
    let mut optional = raw_optional.clone();
    let has = |key: &str| optional.contains_key(key);

    if let Some(family) = optional.get("merchant_family")
        && (family.as_str() != Some("agoda") || merchant != "agoda")
    {
        return fail("가맹점 그룹은 확인된 아고다 규칙에만 사용할 수 있습니다");
    }
    if let Some(country) = optional.get("travel_country")
        && !country
            .as_str()
            .is_some_and(|c| TRAVEL_COUNTRIES.contains(&c))
    {
        return fail("현지 여행 조건의 국가를 확인해 주세요");
    }
    if merchant == "*" && optional.get("travel_country").and_then(Value::as_str) != Some("local") {
        return fail(
            "전체 가맹점 규칙은 사용 국가와 명시 여행이 일치하는 현지 사용에만 적용할 수 있습니다",
        );
    }
    if let Some(hash) = optional.get("source_hash")
        && !is_hex64(&text_of_raw(hash))
    {
        return fail("원본 거래 결속 값이 올바르지 않습니다");
    }
    if let Some(inference) = optional.get("inferred_assignment") {
        let ok = inference.as_object().is_some_and(|i| {
            let keys_ok = i.len() == 3
                && ["trip_id", "basis", "confidence"]
                    .iter()
                    .all(|k| i.contains_key(*k));
            let confidence = i.get("confidence").and_then(Value::as_str);
            let basis = i.get("basis").and_then(Value::as_str);
            keys_ok
                && has("source_hash")
                && merchant != "*"
                && matches!(confidence, Some("높음" | "중간" | "낮음"))
                && i.get("trip_id").is_some_and(Value::is_string)
                && basis.is_some_and(|b| !b.trim().is_empty() && b.chars().count() <= 1600)
                && !has("booking_period")
                && !has("travel_country")
        });
        if !ok {
            return fail("추론 배정은 해당 원본 거래와 근거, 확신 정도를 함께 저장해야 합니다");
        }
    }
    if let Some(period) = optional.get("booking_period").cloned() {
        let ok = period.as_object().is_some_and(|p| {
            p.len() == 4
                && ["starts_on", "ends_on", "target_code", "source_sha256"]
                    .iter()
                    .all(|k| p.contains_key(*k))
                && has("source_hash")
                && is_hex64(&p.get("source_sha256").map(text_of_raw).unwrap_or_default())
        });
        if !ok {
            return fail("예약 이용기간과 원본 거래 근거를 확인해 주세요");
        }
        let mut period = period;
        let map = period.as_object_mut().expect("checked above");
        for field in ["starts_on", "ends_on"] {
            let day = date_or_empty(&map[field]);
            map.insert(field.to_string(), Value::String(day));
        }
        let (start, end) = (text_of(&map["starts_on"]), text_of(&map["ends_on"]));
        if start.is_empty() || end.is_empty() || end < start {
            return fail("예약 이용기간이 올바르지 않습니다");
        }
        optional.insert("booking_period".to_string(), period);
    }
    if let Some(window) = optional.get("amount_range").cloned() {
        let window = if truthy(&window) {
            window
        } else {
            Value::Object(Map::new())
        };
        let Some(window) = window
            .as_object()
            .filter(|w| w.keys().all(|k| k == "min" || k == "max"))
        else {
            return fail("금액 범위 형식이 달라요");
        };
        let mut clean = Map::new();
        for bound in ["min", "max"] {
            match window.get(bound) {
                None | Some(Value::Null) => continue,
                Some(Value::String(s)) if s.is_empty() => continue,
                Some(value) => match amount_krw(value) {
                    Some(n) => {
                        clean.insert(bound.to_string(), Value::from(n));
                    }
                    None => return fail(&format!("금액 범위 {bound} 값을 읽을 수 없어요")),
                },
            }
        }
        if let (Some(min), Some(max)) = (
            clean.get("min").and_then(Value::as_i64),
            clean.get("max").and_then(Value::as_i64),
        ) && min > max
        {
            return fail("금액 범위 최소값이 최대값보다 커요");
        }
        optional.insert("amount_range".to_string(), Value::Object(clean));
    }
    if let Some(period) = optional.get("date_or_service_period").cloned() {
        let period = if truthy(&period) {
            period
        } else {
            Value::Object(Map::new())
        };
        let Some(map) = period
            .as_object()
            .filter(|p| p.keys().all(|k| k == "start" || k == "end"))
        else {
            return fail("기간 형식이 달라요");
        };
        let mut map = map.clone();
        for bound in ["start", "end"] {
            if map.get(bound).is_some_and(truthy) {
                let day = date_or_empty(&map[bound]);
                if day.is_empty() {
                    return fail(&format!("기간 {bound} 날짜를 읽을 수 없어요"));
                }
                map.insert(bound.to_string(), Value::String(day));
            }
        }
        optional.insert("date_or_service_period".to_string(), Value::Object(map));
    }

    let Some(effects_in) = object_or_empty(draft.get("effects"), &empty).filter(|e| !e.is_empty())
    else {
        return fail("적용할 항목이나 내용을 입력해 주세요");
    };
    let mut bad: Vec<&str> = effects_in
        .keys()
        .map(String::as_str)
        .filter(|k| !EFFECT_FIELDS.contains(k))
        .collect();
    bad.sort_unstable();
    if !bad.is_empty() {
        return fail(&format!("허용되지 않은 효과예요: {}", py_list(&bad)));
    }
    let mut effects = Map::new();
    for (field, value) in effects_in {
        let text = text_of(value).trim().to_string();
        if text.is_empty() {
            return fail(&format!("{field} 효과가 비어 있어요"));
        }
        effects.insert(field.clone(), Value::String(text));
    }
    if effects
        .get("display_tab_id")
        .is_some_and(|v| v.as_str() != Some("unclassified"))
    {
        return fail("가맹점 분류 규칙으로 여행을 자동 배정할 수 없습니다. 거래별로 확인해 주세요");
    }

    let note = text_of(draft.get("note").unwrap_or(&Value::Null))
        .trim()
        .to_string();
    if note.chars().count() > 2000 {
        return fail("규칙 메모가 너무 길어요");
    }
    let capped = |key: &str| -> String {
        text_of(draft.get(key).unwrap_or(&Value::Null))
            .trim()
            .chars()
            .take(200)
            .collect()
    };
    Ok(Rule {
        rule_id: capped("rule_id"),
        version: 1,
        conditions,
        optional,
        effects,
        origin: capped("origin"),
        note,
    })
}

/// Python `str(x)`: 문자열은 그대로, 그 밖은 JSON 표기(16진 해시 검사에서 문자열이 아니면 거부된다).
fn text_of_raw(v: &Value) -> String {
    match v {
        Value::String(s) => s.clone(),
        other => other.to_string(),
    }
}
