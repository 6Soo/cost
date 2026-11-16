//! Offline M6 extractor. No production switches, runtime or database writes.
use super::{CliError, DEFAULT_HOST, Flags, python_bridge};
use cost_core::extract::{SourceStages, build_ota_payment_events, check_output, write_baseline};
use serde_json::{Value, json};
use std::path::{Path, PathBuf};

pub(super) fn run(args: &[String]) -> Result<(u8, Value), CliError> {
    // Keep the extract option set separate from operational commands: no --allow-live.
    let allowed = [
        "--ota-evidence",
        "--stages",
        "--out",
        "--host-root",
        "--repo-root",
        "--python",
    ];
    if !args.len().is_multiple_of(2)
        || args
            .chunks(2)
            .any(|pair| !allowed.contains(&pair[0].as_str()))
    {
        return Err(CliError::UsageInvalid);
    }
    let flags = Flags {
        values: args
            .chunks(2)
            .map(|p| (p[0].clone(), p[1].clone()))
            .collect(),
        switches: Vec::new(),
    };
    let host = PathBuf::from(flags.get("--host-root").unwrap_or(DEFAULT_HOST));
    let repo = PathBuf::from(flags.get("--repo-root").unwrap_or("."));
    let out = PathBuf::from(flags.get("--out").ok_or(CliError::UsageInvalid)?);
    check_output(&out, &host, &repo)?;
    let stages: SourceStages = match (flags.get("--ota-evidence"), flags.get("--stages")) {
        (Some(copy), None) => {
            serde_json::from_value(python_bridge(&flags).extract_sources(Path::new(copy), &host)?)
                .map_err(|_| cost_core::extract::ExtractError::InputInvalid)?
        }
        (None, Some(path)) => serde_json::from_str(&std::fs::read_to_string(path)?)
            .map_err(|_| cost_core::extract::ExtractError::InputInvalid)?,
        _ => return Err(CliError::UsageInvalid),
    };
    let events = build_ota_payment_events(stages)?;
    let result = write_baseline(&out, &host, &repo, &events)?;
    Ok((0, json!({"ok": true, "result": result})))
}
