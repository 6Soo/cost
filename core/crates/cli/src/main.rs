//! costcore 실행 파일. `shadow`(U10)와 `plan` 외부 호출. 하위 명령은 후속 단위가 더한다.
//! 출력은 JSON 한 줄이며 고객 원문·거래 ID는 담지 않는다(비공개 상세는 보호 경로 파일에만).

use std::io::Read;
use std::path::PathBuf;
use std::process::ExitCode;

use cost_core::apply::{ApplyRequest, apply, open_board_writable, utc_now};
use cost_core::pipeline::links_from;
use cost_core::shadow::{
    PlanEngine, PlanRequest, PythonBridge, RustEngine, ShadowError, parse_known_diffs,
    reject_live_db, run_shadow, targets_json, write_private_lines,
};
use serde_json::{Value, json};

const DEFAULT_HOST: &str = "D:/WebLedgerHost";

/// Rust 판정 엔진(U9 `plan` + DB 어댑터). 환불 연결은 2차 전환 전까지 Python 다리에서 받는다.
fn rust_engine(flags: &Flags) -> Box<dyn PlanEngine> {
    Box::new(RustEngine {
        links: Some(python_bridge(flags)),
    })
}

fn python_bridge(flags: &Flags) -> PythonBridge {
    PythonBridge {
        python: flags.get("--python").unwrap_or("python").to_owned(),
        repo_root: PathBuf::from(flags.get("--repo-root").unwrap_or(".")),
    }
}

fn main() -> ExitCode {
    let args: Vec<String> = std::env::args().skip(1).collect();
    match args.first().map(String::as_str) {
        None | Some("--version") => {
            println!("costcore {}", env!("CARGO_PKG_VERSION"));
            ExitCode::SUCCESS
        }
        Some("shadow") => finish(shadow(&args[1..]), "status"),
        Some("plan") => finish(plan(&args[1..]), "ok"),
        Some("apply") => finish(apply_cmd(&args[1..]), "ok"),
        Some(_) => {
            eprintln!("usage: costcore <shadow|plan|apply> ...");
            ExitCode::from(2)
        }
    }
}

/// `Ok((코드, 값))`을 한 줄로 내고 종료 코드로 바꾼다. `Err`은 공개 안전한 오류 코드만 낸다.
fn finish(result: Result<(u8, Value), ShadowError>, kind: &str) -> ExitCode {
    match result {
        Ok((code, value)) => {
            println!("{value}");
            ExitCode::from(code)
        }
        Err(error) => {
            let value = if kind == "ok" {
                json!({"ok": false, "error": {"code": error.code()}})
            } else {
                json!({"status": "ERROR", "code": error.code()})
            };
            println!("{value}");
            ExitCode::from(2)
        }
    }
}

struct Flags {
    values: Vec<(String, String)>,
    switches: Vec<String>,
}

impl Flags {
    fn parse(args: &[String]) -> Result<Self, ShadowError> {
        let mut flags = Flags {
            values: Vec::new(),
            switches: Vec::new(),
        };
        let mut iter = args.iter();
        while let Some(arg) = iter.next() {
            match arg.as_str() {
                "--reconsider" | "--allow-live" => flags.switches.push(arg.clone()),
                "--db" | "--host-root" | "--known-diffs" | "--private-out" | "--python"
                | "--repo-root" | "--digest" | "--now" | "--core" => {
                    let value = iter.next().ok_or(ShadowError::UsageInvalid)?;
                    flags.values.push((arg.clone(), value.clone()));
                }
                _ => return Err(ShadowError::UsageInvalid),
            }
        }
        Ok(flags)
    }
    fn get(&self, name: &str) -> Option<&str> {
        self.values
            .iter()
            .rev()
            .find(|(k, _)| k == name)
            .map(|(_, v)| v.as_str())
    }
    fn on(&self, name: &str) -> bool {
        self.switches.iter().any(|s| s == name)
    }
}

fn shadow(args: &[String]) -> Result<(u8, Value), ShadowError> {
    let flags = Flags::parse(args)?;
    let db = PathBuf::from(flags.get("--db").ok_or(ShadowError::UsageInvalid)?);
    let host = PathBuf::from(flags.get("--host-root").unwrap_or(DEFAULT_HOST));
    let repo = PathBuf::from(flags.get("--repo-root").unwrap_or("."));
    let known_path = flags
        .get("--known-diffs")
        .map(PathBuf::from)
        .unwrap_or_else(|| repo.join("core").join("known-diffs.txt"));
    reject_live_db(&db, &host)?;
    // 비공개 파일 경로는 실행 전에 검사해, 거부될 실행이 시간을 쓰지 않게 한다.
    let private_out = match flags.get("--private-out") {
        Some(path) => Some(cost_core::shadow::ensure_private_path(
            &PathBuf::from(path),
            &host,
        )?),
        None => None,
    };
    let known = parse_known_diffs(&std::fs::read_to_string(&known_path)?)?;
    let python = python_bridge(&flags);
    let outcome = run_shadow(
        &db,
        flags.on("--reconsider"),
        &python,
        &*rust_engine(&flags),
        &known,
    )?;
    let mut public = outcome.report.public_json()?;
    if let Some(path) = private_out {
        let lines: Vec<String> = outcome.private.iter().map(|d| d.line()).collect();
        write_private_lines(&path, &host, &lines)?;
        public["private_details"] = json!(lines.len());
    }
    Ok((u8::from(!outcome.report.passed()), public))
}

/// `costcore plan --db PATH`: 표준 입력의 JSON(선택)을 요청에 합쳐 Rust 엔진 결과를 낸다.
fn plan(args: &[String]) -> Result<(u8, Value), ShadowError> {
    let flags = Flags::parse(args)?;
    let db = PathBuf::from(flags.get("--db").ok_or(ShadowError::UsageInvalid)?);
    let mut body = String::new();
    std::io::stdin().read_to_string(&mut body)?;
    let extra: Value = if body.trim().is_empty() {
        Value::Null
    } else {
        serde_json::from_str(&body).map_err(|_| ShadowError::PlanResponseInvalid)?
    };
    let ids = extra["transaction_ids"].as_array().map(|ids| {
        ids.iter()
            .filter_map(|v| v.as_str().map(str::to_owned))
            .collect()
    });
    let request = PlanRequest {
        db,
        transaction_ids: ids,
        reconsider: flags.on("--reconsider") || extra["reconsider"] == json!(true),
        context: extra,
    };
    let targets = rust_engine(&flags).plan(&request)?;
    Ok((0, json!({"ok": true, "result": targets_json(&targets)})))
}

/// `costcore apply --db PATH --core CORE.sqlite --digest D [--allow-live]`: 표준 입력의 JSON(`trips`·`nets`·`evidence`·`transaction_ids`·
/// `reconsider`·`links`)으로 계획을 다시 만들어 digest가 같을 때만 쓴다. 운영 DB 경로는 `--allow-live` 없이는 거부한다.
fn apply_cmd(args: &[String]) -> Result<(u8, Value), ShadowError> {
    let flags = Flags::parse(args)?;
    let db = PathBuf::from(flags.get("--db").ok_or(ShadowError::UsageInvalid)?);
    let digest = flags.get("--digest").ok_or(ShadowError::UsageInvalid)?;
    let host = PathBuf::from(flags.get("--host-root").unwrap_or(DEFAULT_HOST));
    if !flags.on("--allow-live") {
        reject_live_db(&db, &host)?;
    }
    let mut body = String::new();
    std::io::stdin().read_to_string(&mut body)?;
    let context: Value = if body.trim().is_empty() {
        Value::Null
    } else {
        serde_json::from_str(&body).map_err(|_| ShadowError::PlanResponseInvalid)?
    };
    let ids: Option<Vec<String>> = context["transaction_ids"].as_array().map(|ids| {
        ids.iter()
            .filter_map(|v| v.as_str().map(str::to_owned))
            .collect()
    });
    let links = if context["links"].is_object() {
        links_from(&context["links"])
    } else {
        python_bridge(&flags).refund_links(&db, ids.as_deref())?
    };
    let core = PathBuf::from(flags.get("--core").ok_or(ShadowError::UsageInvalid)?);
    cost_core::store::open_core(&core)?;
    let mut conn = open_board_writable(&db)?;
    let now = match flags.get("--now") {
        Some(now) => now.to_owned(),
        None => utc_now(&conn)?,
    };
    let request = ApplyRequest {
        expected_digest: digest,
        transaction_ids: ids.as_deref(),
        reconsider: context["reconsider"] == json!(true) || flags.on("--reconsider"),
        context: &context,
        now: &now,
    };
    let out = apply(&mut conn, &core, &request, &links)?;
    Ok((
        0,
        json!({"ok": true, "result": out.summary, "written": out.written,
            "skipped_unjudged": out.skipped_unjudged, "skipped_mismatch": out.skipped_mismatch}),
    ))
}
