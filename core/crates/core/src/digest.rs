//! `hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True, default=...))`와 같은 바이트를 만든다.
//! 구분자는 Python 기본값(`", "`·`": "`)이고 키는 코드 포인트 순이다(`serde_json::Map`은 `BTreeMap`).

use serde_json::Value;
use sha2::{Digest, Sha256};
use std::fmt::Write;

/// Python `json.dumps(value, ensure_ascii=False, sort_keys=True)`.
pub fn python_json(value: &Value) -> String {
    let mut out = String::new();
    write_value(&mut out, value, (", ", ": "));
    out
}

/// `json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)`.
pub fn python_json_compact(value: &Value) -> String {
    let mut out = String::new();
    write_value(&mut out, value, (",", ":"));
    out
}

pub fn sha256_hex(text: &str) -> String {
    Sha256::digest(text.as_bytes())
        .iter()
        .fold(String::new(), |mut hex, byte| {
            let _ = write!(hex, "{byte:02x}");
            hex
        })
}

fn write_value(out: &mut String, value: &Value, sep: (&str, &str)) {
    match value {
        Value::Null => out.push_str("null"),
        Value::Bool(b) => out.push_str(if *b { "true" } else { "false" }),
        Value::Number(n) => out.push_str(&n.to_string()),
        Value::String(s) => write_string(out, s),
        Value::Array(items) => {
            out.push('[');
            for (i, item) in items.iter().enumerate() {
                if i > 0 {
                    out.push_str(sep.0);
                }
                write_value(out, item, sep);
            }
            out.push(']');
        }
        Value::Object(map) => {
            out.push('{');
            for (i, (key, item)) in map.iter().enumerate() {
                if i > 0 {
                    out.push_str(sep.0);
                }
                write_string(out, key);
                out.push_str(sep.1);
                write_value(out, item, sep);
            }
            out.push('}');
        }
    }
}

/// `ensure_ascii=False`: 따옴표·역슬래시·제어 문자(U+0000~U+001F)만 이스케이프한다.
fn write_string(out: &mut String, text: &str) {
    out.push('"');
    for c in text.chars() {
        match c {
            '"' => out.push_str("\\\""),
            '\\' => out.push_str("\\\\"),
            '\n' => out.push_str("\\n"),
            '\r' => out.push_str("\\r"),
            '\t' => out.push_str("\\t"),
            '\u{8}' => out.push_str("\\b"),
            '\u{c}' => out.push_str("\\f"),
            c if (c as u32) < 0x20 => {
                let _ = write!(out, "\\u{:04x}", c as u32);
            }
            c => out.push(c),
        }
    }
    out.push('"');
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    #[test]
    fn matches_python_dumps_defaults() {
        let value = json!({"b": [1, "가", null, true], "a": {"z": "q\"\\\n\u{1}", "y": -3}});
        assert_eq!(
            python_json(&value),
            r#"{"a": {"y": -3, "z": "q\"\\\n\u0001"}, "b": [1, "가", null, true]}"#
        );
    }

    #[test]
    fn sha256_of_abc() {
        assert_eq!(
            sha256_hex("abc"),
            "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"
        );
    }
}
