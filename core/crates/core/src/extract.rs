//! M6 transition extractor. Source parsers remain in the read-only Python bridge;
//! forest period enrichment, proven-payment merging and baseline bytes are Rust.
//! No card, classification, override or ledger writes are performed here.

mod decimal;
mod forest;
mod merge;
mod traveloka;

pub use traveloka::{TravelokaInput, traveloka_fact};

use std::collections::{BTreeMap, BTreeSet};
use std::fs::OpenOptions;
use std::io::Write;
use std::path::Path;

use serde::{Deserialize, Serialize};
use serde_json::{Value, json};

use crate::digest::{python_json, python_json_compact, sha256_hex};
use crate::guard::{GuardError, ensure_private_path};
use decimal::Decimal;

pub use merge::{combine_evidence, event_semantic_conflict, merge_proven_duplicate_payments};

pub const STAGES_SCHEMA: &str = "ota-extract-stages/1";

#[derive(Debug, thiserror::Error)]
pub enum ExtractError {
    #[error("EXTRACT_INPUT_INVALID")]
    InputInvalid,
    #[error("DB_IS_LIVE")]
    DbIsLive,
    #[error("OUT_INSIDE_REPO")]
    OutInsideRepo,
    #[error(transparent)]
    Guard(#[from] GuardError),
    #[error("IO_ERROR")]
    Io(#[from] std::io::Error),
}

impl ExtractError {
    pub fn code(&self) -> &'static str {
        match self {
            Self::InputInvalid => "EXTRACT_INPUT_INVALID",
            Self::DbIsLive => "DB_IS_LIVE",
            Self::OutInsideRepo => "OUT_INSIDE_REPO",
            Self::Guard(error) => error.code(),
            Self::Io(_) => "IO_ERROR",
        }
    }
}

/// Parser boundary, before any cross-source enrichment or payment merging.
/// The five vectors retain Python source order (the first event wins fields).
#[derive(Debug, Clone, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub struct SourceStages {
    pub schema_version: String,
    pub mail_events: Vec<Value>,
    pub portal_events: Vec<Value>,
    pub trip_reservation_events: Vec<Value>,
    pub booking_trip_events: Vec<Value>,
    pub forest_portal_events: Vec<Value>,
    /// Exact Python Unicode `re.sub(r'\W', '', name).casefold()` at the parser boundary.
    pub forest_name_keys: BTreeMap<String, String>,
}

pub fn build_ota_payment_events(stages: SourceStages) -> Result<Vec<Value>, ExtractError> {
    if stages.schema_version != STAGES_SCHEMA {
        return Err(ExtractError::InputInvalid);
    }
    for event in stages
        .mail_events
        .iter()
        .chain(&stages.portal_events)
        .chain(&stages.trip_reservation_events)
        .chain(&stages.booking_trip_events)
        .chain(&stages.forest_portal_events)
    {
        validate_event(event)?;
    }
    for event in stages
        .mail_events
        .iter()
        .chain(&stages.portal_events)
        .chain(&stages.trip_reservation_events)
        .chain(&stages.booking_trip_events)
        .filter(|e| text(e, "evidence_kind") == "authenticated_forest_pg_card_receipt")
    {
        if !stages
            .forest_name_keys
            .contains_key(text(event, "merchant_name"))
        {
            return Err(ExtractError::InputInvalid);
        }
    }
    if stages
        .forest_portal_events
        .iter()
        .any(|e| !stages.forest_name_keys.contains_key(text(e, "hotel_name")))
    {
        return Err(ExtractError::InputInvalid);
    }
    let mut events = stages.mail_events;
    events.extend(stages.portal_events);
    events.extend(stages.trip_reservation_events);
    events.extend(stages.booking_trip_events);
    events = forest::attach_periods(
        events,
        &stages.forest_portal_events,
        &stages.forest_name_keys,
    );
    let mut events = merge_proven_duplicate_payments(&events);
    events.sort_by(|a, b| text(a, "ota_event_id").cmp(text(b, "ota_event_id")));
    Ok(events)
}

fn validate_event(event: &Value) -> Result<(), ExtractError> {
    if !event.is_object() || text(event, "ota_event_id").is_empty() {
        return Err(ExtractError::InputInvalid);
    }
    for key in [
        "source_ids",
        "source_digests",
        "identity_source_ids",
        "source_binding_ids",
        "source_lineage_ids",
        "observation_ids",
    ] {
        if let Some(value) = event.get(key) {
            let Some(items) = value.as_array() else {
                return Err(ExtractError::InputInvalid);
            };
            if items.iter().any(|item| !item.is_string()) {
                return Err(ExtractError::InputInvalid);
            }
        }
    }
    Ok(())
}

/// Canonical M3 baseline bytes: no trailing newline, Python's default separators.
pub fn baseline_bytes(events: &[Value]) -> Result<String, ExtractError> {
    for event in events {
        validate_event(event)?;
    }
    let mut sorted = events.to_vec();
    sorted.sort_by(|a, b| text(a, "ota_event_id").cmp(text(b, "ota_event_id")));
    Ok(python_json(&json!({"events": sorted})))
}

/// Refuse protected operational databases and aliases before reading parser stages.
pub fn check_stages_input(path: &Path, hosts: &[&Path]) -> Result<(), ExtractError> {
    let source = path.canonicalize()?;
    for host in hosts {
        for name in [
            "board.sqlite",
            "core.sqlite",
            "ota-evidence.sqlite",
            "ota-review/ota-review.sqlite",
        ] {
            let live = host.join("data").join(name);
            if let Ok(live) = live.canonicalize()
                && (source == live || crate::pipeline::same_file(&source, &live))
            {
                return Err(ExtractError::DbIsLive);
            }
        }
    }
    Ok(())
}

/// Check before parsing sources, including symlinks and a host placed inside the repo.
pub fn check_output(path: &Path, host: &Path, repo: &Path) -> Result<(), ExtractError> {
    let target = ensure_private_path(path, host)?;
    let compiled_repo = Path::new(env!("CARGO_MANIFEST_DIR")).join("../../..");
    for root in [repo, compiled_repo.as_path()] {
        if let Ok(root) = root.canonicalize()
            && target.starts_with(root)
        {
            return Err(ExtractError::OutInsideRepo);
        }
    }
    if target.exists() {
        return Err(std::io::Error::from(std::io::ErrorKind::AlreadyExists).into());
    }
    Ok(())
}

/// Exclusive creation only. Public result has counts and a digest, never events.
pub fn write_baseline(
    path: &Path,
    host: &Path,
    repo: &Path,
    events: &[Value],
) -> Result<Value, ExtractError> {
    check_output(path, host, repo)?;
    let bytes = baseline_bytes(events)?;
    let target = ensure_private_path(path, host)?;
    if let Some(parent) = target.parent() {
        std::fs::create_dir_all(parent)?;
    }
    let mut file = OpenOptions::new()
        .write(true)
        .create_new(true)
        .open(target)?;
    file.write_all(bytes.as_bytes())?;
    Ok(json!({"events": events.len(), "sha256": sha256_hex(&bytes), "bytes": bytes.len()}))
}

fn text<'a>(event: &'a Value, key: &str) -> &'a str {
    event[key].as_str().unwrap_or("")
}

fn truthy(value: &Value) -> bool {
    match value {
        Value::Null => false,
        Value::Bool(value) => *value,
        Value::Number(value) => value.as_f64() != Some(0.0),
        Value::String(value) => !value.is_empty(),
        Value::Array(value) => !value.is_empty(),
        Value::Object(value) => !value.is_empty(),
    }
}

fn strings(event: &Value, key: &str) -> Vec<String> {
    event[key]
        .as_array()
        .into_iter()
        .flatten()
        .filter_map(Value::as_str)
        .map(str::to_owned)
        .collect()
}

fn union(group: &[Value], key: &str, omit_empty: bool) -> Vec<String> {
    group
        .iter()
        .flat_map(|event| strings(event, key))
        .filter(|s| !omit_empty || !s.is_empty())
        .collect::<BTreeSet<_>>()
        .into_iter()
        .collect()
}

fn digest(value: &Value) -> String {
    sha256_hex(&python_json_compact(value))
}

fn event_id(source_ids: &Value) -> String {
    let ids: BTreeSet<&str> = source_ids
        .as_array()
        .into_iter()
        .flatten()
        .filter_map(Value::as_str)
        .collect();
    format!("ota_{}", digest(&json!(ids)))
}

fn decimal(value: &Value) -> Option<Decimal> {
    if let Some(text) = value.as_str() {
        Decimal::parse(text)
    } else {
        Decimal::parse(&value.to_string())
    }
}

fn amount(event: &Value) -> Option<Decimal> {
    decimal(&event["amount_krw"])
        .filter(|v| !v.is_zero())
        .map(Decimal::abs)
}

fn is_paid(event: &Value) -> bool {
    text(event, "payment_status") == "paid"
        && match text(event, "event_type") {
            "charge" => text(event, "evidence_status") == "paid_verified",
            "refund" => {
                text(event, "evidence_status") == "refund_verified"
                    && matches!(
                        text(event, "refund_status"),
                        "refunded" | "refund_completed"
                    )
            }
            _ => false,
        }
}
