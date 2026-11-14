//! Python dict·`or`·`str()` 의미를 `serde_json::Value` 위에서 재현하는 작은 도우미.

use serde_json::Value;

/// `d.get(key)`: 없거나 null이면 `None`.
pub(super) fn get<'a>(v: &'a Value, key: &str) -> Option<&'a Value> {
    v.get(key).filter(|x| !x.is_null())
}

/// `key in d` 를 구분해야 할 때 쓴다(null도 값으로 본다).
pub(super) fn has(v: &Value, key: &str) -> bool {
    v.get(key).is_some()
}

pub(super) fn truthy(v: Option<&Value>) -> bool {
    match v {
        None | Some(Value::Null) => false,
        Some(Value::Bool(b)) => *b,
        Some(Value::Number(n)) => n.as_f64().is_some_and(|f| f != 0.0),
        Some(Value::String(s)) => !s.is_empty(),
        Some(Value::Array(a)) => !a.is_empty(),
        Some(Value::Object(o)) => !o.is_empty(),
    }
}

/// Python `str(value)`.
pub(super) fn pystr(v: &Value) -> String {
    match v {
        Value::Null => "None".into(),
        Value::Bool(true) => "True".into(),
        Value::Bool(false) => "False".into(),
        Value::String(s) => s.clone(),
        other => other.to_string(),
    }
}

/// `str(d.get(key) or "")`.
pub(super) fn text(v: &Value, key: &str) -> String {
    first_text(v, &[key])
}

/// `str(d.get(a) or d.get(b) or ... or "")`.
pub(super) fn first_text(v: &Value, keys: &[&str]) -> String {
    first_truthy(v, keys).map(pystr).unwrap_or_default()
}

/// `d.get(a) or d.get(b) or ...` 의 첫 참값.
pub(super) fn first_truthy<'a>(v: &'a Value, keys: &[&str]) -> Option<&'a Value> {
    keys.iter()
        .find_map(|k| get(v, k).filter(|x| truthy(Some(x))))
}

pub(super) fn is_int(v: &Value) -> bool {
    matches!(v, Value::Number(n) if n.is_i64() || n.is_u64())
}

pub(super) fn as_int(v: &Value) -> Option<i64> {
    v.as_i64().filter(|_| is_int(v))
}

/// `d.get(key) == "literal"`.
pub(super) fn is_str(v: Option<&Value>, literal: &str) -> bool {
    matches!(v, Some(Value::String(s)) if s == literal)
}

/// `a == b`(없음과 null은 같다).
pub(super) fn same(a: Option<&Value>, b: Option<&Value>) -> bool {
    a == b
}

/// 규칙 한 줄이 꺼졌는가: `("active" in rule and not rule["active"]) or status in (inactive, revoked)`.
pub(super) fn rule_inactive(rule: &Value) -> bool {
    let status = text(rule, "status").to_lowercase();
    (has(rule, "active") && !truthy(get(rule, "active")))
        || status == "inactive"
        || status == "revoked"
}
