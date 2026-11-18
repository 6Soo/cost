//! Storage coverage is independent from the Python/Rust planning shadow.
//! Every existing decision is compared directly with its source and projection.

use std::collections::{BTreeMap, BTreeSet};

use rusqlite::{Connection, OptionalExtension};
use serde::Serialize;
use serde_json::Value;

use crate::domain::{Decision, Judgement};
use crate::period::{PERIOD_FN_VERSION, PeriodEvidence, current_digests};
use crate::pipeline::overlay_context;
use crate::plan::{FIELDS, Links, Outcome, Row, plan_with_periods};
use crate::store::decisions::{period_json, projection};
use crate::store::{StoreError, read_plan_input_in};

#[derive(Debug, Default, Serialize)]
pub struct Coverage {
    pub scanned: usize,
    pub stored: usize,
    pub eligible: usize,
    pub eligible_missing: usize,
    pub eligible_stale: usize,
    pub projection_mismatch: usize,
    pub source_mismatch: usize,
    pub period_mismatch: usize,
    pub classification_change_required: usize,
    pub protected_or_preserved: usize,
    pub kept: usize,
    pub orphaned: usize,
    pub plan_digest: String,
}

fn text(row: &Row, key: &str) -> String {
    row.get(key)
        .and_then(Value::as_str)
        .unwrap_or("")
        .to_owned()
}

pub fn decision_projection(decision: &Decision, source: &str) -> [String; 7] {
    [
        "classified".into(),
        source.into(),
        decision.basis().as_str().into(),
        decision.item().as_str().into(),
        decision.description().into(),
        decision.attribution().display_tab_id(),
        decision.attribution().trip_id(),
    ]
}

/// Caller supplies read transactions on both connections. No schema creation,
/// migration, classification, or audit-status writes are performed here.
pub fn audit(
    board: &Connection,
    core: &Connection,
    context: &Value,
    links: &dyn Links,
) -> Result<Coverage, StoreError> {
    let mut input = read_plan_input_in(board)?;
    overlay_context(
        &mut input,
        context,
        None,
        context["reconsider"] == Value::Bool(true),
    );
    let facts: BTreeMap<String, Value> = context["periods"]
        .as_object()
        .map(|m| m.iter().map(|(k, v)| (k.clone(), v.clone())).collect())
        .unwrap_or_default();
    let current = current_digests(
        input.rows.iter().filter_map(|r| {
            let tid = r.get("transaction_id")?.as_str()?;
            Some((
                tid,
                input
                    .boards
                    .get(&format!("card-{tid}"))
                    .map(|b| b.payload_json.as_str()),
            ))
        }),
        &facts,
    );
    // Force a typed outcome even when the seven legacy classification columns
    // already match. This is the case the planning shadow cannot detect.
    let periods = PeriodEvidence {
        facts,
        changed: current.keys().cloned().collect(),
    };
    let result = plan_with_periods(&input, links, &periods)
        .map_err(|_| StoreError::Sqlite(rusqlite::Error::InvalidQuery))?;
    let rows: BTreeMap<String, &Row> = input
        .rows
        .iter()
        .map(|r| (text(r, "transaction_id"), r))
        .collect();
    let mut report = Coverage {
        scanned: rows.len(),
        plan_digest: result.digest,
        ..Coverage::default()
    };
    let mut ids = BTreeSet::new();
    let mut stmt = core.prepare("SELECT transaction_id,source_hash,revision FROM decisions")?;
    let saved = stmt
        .query_map([], |r| {
            Ok((
                r.get::<_, String>(0)?,
                r.get::<_, String>(1)?,
                r.get::<_, i64>(2)?,
            ))
        })?
        .collect::<Result<Vec<_>, _>>()?;
    report.stored = saved.len();
    for (tid, hash, revision) in saved {
        ids.insert(tid.clone());
        let Some(row) = rows.get(&tid) else {
            report.orphaned += 1;
            continue;
        };
        if hash != text(row, "source_hash")
            || row.get("revision").and_then(Value::as_i64) != Some(revision)
        {
            report.source_mismatch += 1;
        }
        let actual: [String; 7] = FIELDS.map(|k| text(row, k));
        if projection(core, "main", &tid)?.as_ref() != Some(&actual) {
            report.projection_mismatch += 1;
        }
    }
    for (tid, outcome) in result.outcomes {
        match outcome {
            Outcome::Judged(Judgement::Decided(decision)) => {
                let row = rows[&tid];
                let actual: [String; 7] = FIELDS.map(|k| text(row, k));
                if decision_projection(&decision, &text(row, "classification_source")) != actual {
                    report.classification_change_required += 1;
                    continue;
                }
                report.eligible += 1;
                if !ids.contains(&tid) {
                    report.eligible_missing += 1;
                    continue;
                }
                let record: Option<(String,u32,String)> = core.query_row(
                    "SELECT evidence_digest,period_fn_version,service_period_json FROM decisions WHERE transaction_id=?",
                    [&tid], |r| Ok((r.get(0)?,r.get(1)?,r.get(2)?))).optional()?;
                if record.as_ref().is_none_or(|(digest, version, _)| {
                    current.get(&tid) != Some(digest) || *version != PERIOD_FN_VERSION
                }) {
                    report.eligible_stale += 1;
                }
                if record.as_ref().is_none_or(|(_, _, period)| {
                    serde_json::from_str::<Value>(period).ok().as_ref()
                        != Some(&period_json(decision.service_period()))
                }) {
                    report.period_mismatch += 1;
                }
            }
            Outcome::Judged(_) => report.protected_or_preserved += 1,
            Outcome::Kept(_) => report.kept += 1,
        }
    }
    Ok(report)
}
