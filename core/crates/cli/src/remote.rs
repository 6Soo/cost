//! Transitional M5 transport entrypoints. Queue state remains owned by Rust.
use std::io::Read;
use std::path::PathBuf;
use std::process::{Command, ExitCode};
use std::time::{Duration, SystemTime, UNIX_EPOCH};

use cost_core::jobs::{self, ClaimOptions, EnqueueRequest, FailureKind, LeaseToken};
use rusqlite::{Connection, OpenFlags};
use serde_json::{Value, json};

type Reply = Result<(u8, Value), &'static str>;

fn arg(args: &[String], flag: &str) -> Option<String> {
    args.windows(2)
        .find(|pair| pair[0] == flag)
        .map(|pair| pair[1].clone())
}

fn text(body: &Value, key: &str) -> Result<String, &'static str> {
    body[key]
        .as_str()
        .map(str::to_owned)
        .ok_or("QUEUE_INPUT_INVALID")
}

/// This command is a private stdin/stdout bridge, never a public log endpoint.
pub fn queue(args: &[String]) -> Reply {
    if args.len() != 2 || args[0] != "--core" {
        return Err("USAGE_INVALID");
    }
    let mut stdin = String::new();
    std::io::stdin()
        .take(4 * 1024 * 1024 + 1)
        .read_to_string(&mut stdin)
        .map_err(|_| "QUEUE_INPUT_INVALID")?;
    if stdin.len() > 4 * 1024 * 1024 {
        return Err("QUEUE_INPUT_INVALID");
    }
    let body: Value = serde_json::from_str(&stdin).map_err(|_| "QUEUE_INPUT_INVALID")?;
    let mut conn = Connection::open_with_flags(&args[1], OpenFlags::SQLITE_OPEN_READ_WRITE)
        .map_err(|_| "QUEUE_STORE_ERROR")?;
    conn.busy_timeout(Duration::from_secs(10))
        .map_err(|_| "QUEUE_STORE_ERROR")?;
    let version: Option<u32> = conn
        .query_row("SELECT MAX(version) FROM schema_meta", [], |row| row.get(0))
        .map_err(|_| "CORE_SCHEMA_MISMATCH")?;
    if version != Some(cost_core::store::latest_version()) {
        return Err("CORE_SCHEMA_MISMATCH");
    }
    let now = i64::try_from(
        SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .map_err(|_| "QUEUE_CLOCK_INVALID")?
            .as_secs(),
    )
    .map_err(|_| "QUEUE_CLOCK_INVALID")?;
    let operation = text(&body, "operation")?;
    let result = match operation.as_str() {
        "enqueue" => {
            let kind = text(&body, "kind")?;
            let budget_key = body["budget_key"].as_str().map(str::to_owned);
            if kind.starts_with("p2") && budget_key.as_ref().is_none_or(String::is_empty) {
                return Err("QUEUE_BUDGET_REQUIRED");
            }
            let id = jobs::enqueue(
                &conn,
                EnqueueRequest {
                    kind,
                    dedupe_key: text(&body, "dedupe_key")?,
                    budget_key,
                    payload: body.get("payload").cloned().ok_or("QUEUE_INPUT_INVALID")?,
                },
            )
            .map_err(|e| e.code())?;
            json!({"job_id":id})
        }
        "claim" => {
            let mut options = ClaimOptions::new(text(&body, "owner")?);
            if let Some(value) = body.get("lease_seconds") {
                options.lease_seconds = value
                    .as_u64()
                    .and_then(|n| u32::try_from(n).ok())
                    .ok_or("QUEUE_INPUT_INVALID")?;
            }
            if let Some(value) = body.get("daily_budget_limit") {
                options.daily_budget_limit = value
                    .as_u64()
                    .and_then(|n| u32::try_from(n).ok())
                    .ok_or("QUEUE_INPUT_INVALID")?;
            }
            options.kinds = Some(
                serde_json::from_value(body["kinds"].clone()).map_err(|_| "QUEUE_INPUT_INVALID")?,
            );
            json!({"job":jobs::claim(&mut conn, options, now).map_err(|e| e.code())?})
        }
        "status" => {
            let id = body["job_id"].as_i64().ok_or("QUEUE_INPUT_INVALID")?;
            serde_json::to_value(jobs::status(&conn, id).map_err(|e| e.code())?)
                .map_err(|_| "QUEUE_INPUT_INVALID")?
        }
        "heartbeat" | "complete" | "fail" => {
            let token: LeaseToken =
                serde_json::from_value(body["token"].clone()).map_err(|_| "QUEUE_INPUT_INVALID")?;
            match operation.as_str() {
                "heartbeat" => {
                    let seconds = body["lease_seconds"]
                        .as_u64()
                        .and_then(|n| u32::try_from(n).ok())
                        .ok_or("QUEUE_INPUT_INVALID")?;
                    json!({"lease_until":jobs::heartbeat(&conn, &token, seconds, now).map_err(|e| e.code())?})
                }
                "complete" => {
                    let result = body.get("result").cloned().ok_or("QUEUE_INPUT_INVALID")?;
                    jobs::complete(&conn, &token, result, now).map_err(|e| e.code())?;
                    json!({"state":"succeeded"})
                }
                _ => {
                    let failure = match text(&body, "failure")?.as_str() {
                        "transient" => FailureKind::Transient,
                        "capacity" => FailureKind::Capacity {
                            not_before: now.checked_add(3600).ok_or("QUEUE_CLOCK_INVALID")?,
                        },
                        "authentication" => FailureKind::Authentication,
                        "tool" => FailureKind::Tool,
                        "permanent" => FailureKind::Permanent,
                        _ => return Err("QUEUE_INPUT_INVALID"),
                    };
                    json!({"state":jobs::fail(&conn, &token, failure, now).map_err(|e| e.code())?})
                }
            }
        }
        _ => return Err("QUEUE_INPUT_INVALID"),
    };
    Ok((0, json!({"ok":true,"result":result})))
}

/// M6 keeps the existing Python web runtime until its approved retirement.
/// Both roles are selected through this same executable; node opens no listener.
pub fn runtime(mode: &str, args: &[String]) -> ExitCode {
    let root = arg(args, "--repo-root")
        .map(PathBuf::from)
        .unwrap_or_else(|| PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../../.."));
    let python = arg(args, "--python").unwrap_or_else(|| "python".into());
    let mut forwarded = Vec::new();
    let mut iter = args.iter();
    while let Some(value) = iter.next() {
        if value == "--repo-root" || value == "--python" {
            iter.next();
        } else {
            forwarded.push(value);
        }
    }
    let Some(binary) = std::env::current_exe().ok() else {
        return ExitCode::from(2);
    };
    match Command::new(python)
        .arg("-I")
        .arg(root.join("tools/m5_runtime.py"))
        .arg(mode)
        .args(forwarded)
        .env("COSTCORE_RUNTIME_BINARY", binary)
        .status()
    {
        Ok(status) => ExitCode::from(u8::try_from(status.code().unwrap_or(2)).unwrap_or(2)),
        Err(_) => {
            eprintln!("M5_RUNTIME_NOT_STARTED");
            ExitCode::from(2)
        }
    }
}
