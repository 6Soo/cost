//! Deterministic request binding, validation, and replay for P2.

use std::collections::HashSet;
use std::sync::LazyLock;

use regex::Regex;
use serde_json::{Map, Value, json};

const KEEP: &str = "기존 항목 유지";
const ERR_REQUEST: &str = "BATCH_REQUEST_INVALID";
const ERR_BINDING: &str = "BATCH_BINDING_INVALID";
const ERR_COVERAGE: &str = "BATCH_COVERAGE_INVALID";
const ERR_RESULT: &str = "BATCH_RESULT_INVALID";
const ERR_ITEM: &str = "BATCH_ITEM_INVALID";
const ERR_BASIS: &str = "BATCH_BASIS_INVALID";
const ERR_PRIVATE_BASIS: &str = "BATCH_BASIS_PRIVATE_IDENTIFIER";
const MAX_MERCHANTS: usize = 50;
const MAX_MERCHANT_ID_BYTES: usize = 128;
const MAX_POLICY_BYTES: usize = 128 * 1024;

static PRIVATE_NUMBER: LazyLock<Regex> =
    LazyLock::new(|| Regex::new(r"\d(?:[ -]?\d){4,}").expect("static number regex"));
static PRIVATE_EMAIL: LazyLock<Regex> =
    LazyLock::new(|| Regex::new(r"[\w.+-]+@[\w.-]+").expect("static email regex"));

/// Build the provider request and bind the merchant batch, allowed items, and policy.
/// `run_id` is carried separately and intentionally excluded from the digest.
pub fn prepare(input: &Value) -> Result<Value, &'static str> {
    validate_request_shape(input, false)?;
    let request = digest_input(input)?;
    let digest = crate::digest::sha256_hex(&crate::digest::python_json(&request));
    let mut output = request.as_object().cloned().ok_or(ERR_REQUEST)?;
    output.insert(
        "run_id".to_owned(),
        input.get("run_id").cloned().ok_or(ERR_REQUEST)?,
    );
    output.insert("request_digest".to_owned(), Value::String(digest));
    Ok(Value::Object(output))
}

/// Validate a provider answer against the bound request and return it unchanged.
pub fn validate(request: &Value, answer: &Value) -> Result<Value, &'static str> {
    validate_request_shape(request, true)?;
    let request_obj = request.as_object().ok_or(ERR_REQUEST)?;
    let answer_obj = answer.as_object().ok_or(ERR_BINDING)?;
    if !exact_keys(answer_obj, &["request_digest", "run_id", "results"])
        || answer_obj.get("request_digest") != request_obj.get("request_digest")
        || answer_obj.get("run_id") != request_obj.get("run_id")
    {
        return Err(ERR_BINDING);
    }

    let merchants = request_obj["merchants"].as_array().ok_or(ERR_REQUEST)?;
    let expected = merchants
        .iter()
        .map(|merchant| {
            merchant
                .get("merchant_id")
                .and_then(Value::as_str)
                .ok_or(ERR_REQUEST)
        })
        .collect::<Result<HashSet<_>, _>>()?;
    let allowed = request_obj["allowed_items"]
        .as_array()
        .ok_or(ERR_REQUEST)?
        .iter()
        .filter_map(Value::as_str)
        .collect::<HashSet<_>>();
    let results = answer_obj["results"].as_array().ok_or(ERR_COVERAGE)?;
    if results.len() != expected.len() {
        return Err(ERR_COVERAGE);
    }

    let mut seen = HashSet::with_capacity(results.len());
    for result in results {
        let result = result.as_object().ok_or(ERR_RESULT)?;
        if !exact_keys(result, &["merchant_id", "item", "confidence", "basis"]) {
            return Err(ERR_RESULT);
        }
        let merchant_id = result
            .get("merchant_id")
            .and_then(Value::as_str)
            .ok_or(ERR_COVERAGE)?;
        if !expected.contains(merchant_id) || !seen.insert(merchant_id) {
            return Err(ERR_COVERAGE);
        }
        let item = result.get("item").and_then(Value::as_str).ok_or(ERR_ITEM)?;
        let confidence = result
            .get("confidence")
            .and_then(Value::as_str)
            .ok_or(ERR_ITEM)?;
        if (item != KEEP && !allowed.contains(item)) || !matches!(confidence, "높음" | "낮음") {
            return Err(ERR_ITEM);
        }
        let basis = result
            .get("basis")
            .and_then(Value::as_str)
            .ok_or(ERR_BASIS)?;
        if basis.trim().is_empty() || basis.chars().count() > 600 {
            return Err(ERR_BASIS);
        }
        if PRIVATE_NUMBER.is_match(basis) || PRIVATE_EMAIL.is_match(basis) {
            return Err(ERR_PRIVATE_BASIS);
        }
    }
    if seen.len() != expected.len() {
        return Err(ERR_COVERAGE);
    }
    Ok(answer.clone())
}

/// A provider-independent runner contract. Implementations always validate their output.
pub trait P2Runner {
    fn run(&self, request: &Value) -> Result<Value, &'static str>;
}

/// Deterministic test runner; it never starts a model process.
pub struct Replay {
    pub answer: Value,
}

impl P2Runner for Replay {
    fn run(&self, request: &Value) -> Result<Value, &'static str> {
        validate(request, &self.answer)
    }
}

fn validate_request_shape(request: &Value, has_digest: bool) -> Result<(), &'static str> {
    let object = request.as_object().ok_or(ERR_REQUEST)?;
    let fields: &[&str] = if has_digest {
        &[
            "merchants",
            "allowed_items",
            "policy",
            "run_id",
            "request_digest",
        ]
    } else {
        &["merchants", "allowed_items", "policy", "run_id"]
    };
    if !exact_keys(object, fields) {
        return Err(ERR_REQUEST);
    }
    let merchants = object
        .get("merchants")
        .and_then(Value::as_array)
        .ok_or(ERR_REQUEST)?;
    if merchants.len() > MAX_MERCHANTS {
        return Err(ERR_REQUEST);
    }
    let mut ids = HashSet::with_capacity(merchants.len());
    for merchant in merchants {
        let merchant = merchant.as_object().ok_or(ERR_REQUEST)?;
        let id = merchant
            .get("merchant_id")
            .and_then(Value::as_str)
            .ok_or(ERR_REQUEST)?;
        if id.trim().is_empty()
            || id.len() > MAX_MERCHANT_ID_BYTES
            || id.chars().any(char::is_control)
            || !ids.insert(id)
        {
            return Err(ERR_REQUEST);
        }
    }
    let allowed_items = object
        .get("allowed_items")
        .and_then(Value::as_array)
        .ok_or(ERR_REQUEST)?;
    if allowed_items.iter().any(|item| {
        item.as_str()
            .is_none_or(|item| item.trim().is_empty() || item.chars().any(char::is_control))
    }) {
        return Err(ERR_REQUEST);
    }
    let policy = object
        .get("policy")
        .and_then(Value::as_str)
        .ok_or(ERR_REQUEST)?;
    if policy.trim().is_empty() || policy.len() > MAX_POLICY_BYTES {
        return Err(ERR_REQUEST);
    }
    let run_id = object
        .get("run_id")
        .and_then(Value::as_str)
        .ok_or(ERR_REQUEST)?;
    if run_id.is_empty() || run_id.len() > 128 || !is_hex(run_id) {
        return Err(ERR_REQUEST);
    }

    if has_digest {
        let digest = object
            .get("request_digest")
            .and_then(Value::as_str)
            .ok_or(ERR_BINDING)?;
        if digest.len() != 64 || !is_hex(digest) {
            return Err(ERR_BINDING);
        }
        let hash_input = digest_input(request)?;
        let expected = crate::digest::sha256_hex(&crate::digest::python_json(&hash_input));
        if digest != expected {
            return Err(ERR_BINDING);
        }
    }
    Ok(())
}

fn digest_input(input: &Value) -> Result<Value, &'static str> {
    Ok(json!({
        "merchants": input.get("merchants").cloned().ok_or(ERR_REQUEST)?,
        "allowed_items": input.get("allowed_items").cloned().ok_or(ERR_REQUEST)?,
        "policy": input.get("policy").cloned().ok_or(ERR_REQUEST)?,
    }))
}

fn exact_keys(object: &Map<String, Value>, expected: &[&str]) -> bool {
    object.len() == expected.len() && expected.iter().all(|key| object.contains_key(*key))
}

fn is_hex(value: &str) -> bool {
    value.bytes().all(|byte| byte.is_ascii_hexdigit())
}
