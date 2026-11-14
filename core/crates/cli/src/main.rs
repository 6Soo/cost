//! costcore 실행 파일. `shadow`(U10)와 `plan` 외부 호출. 하위 명령은 후속 단위가 더한다.
//! 출력은 JSON 한 줄이며 고객 원문·거래 ID는 담지 않는다(비공개 상세는 보호 경로 파일에만).

mod links_ota;

use std::collections::BTreeMap;
use std::io::Read;
use std::path::PathBuf;
use std::process::ExitCode;

use cost_core::apply::{ApplyError, ApplyRequest, apply, open_board_writable, utc_now};
use cost_core::bridge::{BridgeError, PythonBridge};
use cost_core::links::ota::Defaults;
use cost_core::links::refund::PairingConfig;
use cost_core::links::refund::Refunds;
use cost_core::period;
use cost_core::pipeline::{
    PipelineError, PlanRequest, links_from, reject_live_db, run_plan, targets_json,
};
use cost_core::shadow::links::{
    judge_links, refund_rows, refund_rows_from_json, refund_values, run_ota, run_refund,
};
use cost_core::shadow::{
    PlanEngine, RustEngine, ShadowError, parse_known_diffs, run_shadow, write_private_lines,
};
use cost_core::store::decisions::stored_digests_readonly;
use cost_core::store::{StoreError, read_plan_input, read_projection};
use serde_json::{Value, json};

const DEFAULT_HOST: &str = "D:/WebLedgerHost";

/// CLI 오류. 운영 명령(plan·apply)은 `ShadowError`를 거치지 않고, 비교·보호 경로 도우미의 오류만 `Shadow`로 담는다.
#[derive(Debug)]
enum CliError {
    UsageInvalid,
    PlanResponseInvalid,
    Pipeline(PipelineError),
    Apply(ApplyError),
    Store,
    CoreSchemaMismatch,
    Shadow(ShadowError),
    Io,
}

impl CliError {
    /// 공개 출력에 내는 고정 코드(메시지 본문은 내지 않는다).
    fn code(&self) -> String {
        match self {
            Self::UsageInvalid => "USAGE_INVALID".to_owned(),
            Self::PlanResponseInvalid => "PLAN_RESPONSE_INVALID".to_owned(),
            Self::Pipeline(PipelineError::PlanFailed) => "PLAN_FAILED".to_owned(),
            Self::Pipeline(PipelineError::DbIsLive) => "DB_IS_LIVE".to_owned(),
            Self::Pipeline(PipelineError::Bridge(BridgeError::Failed(code))) => {
                format!("PYTHON_BRIDGE_FAILED:{code}")
            }
            Self::Pipeline(PipelineError::Bridge(BridgeError::Io(_))) | Self::Io => {
                "IO_ERROR".to_owned()
            }
            Self::Pipeline(PipelineError::Store(_)) | Self::Store => "STORE_ERROR".to_owned(),
            Self::CoreSchemaMismatch => "CORE_SCHEMA_MISMATCH".to_owned(),
            Self::Apply(ApplyError::PreviewStale) => "CLASSIFICATION_PREVIEW_STALE".to_owned(),
            Self::Apply(ApplyError::PlanFailed) => "PLAN_FAILED".to_owned(),
            Self::Apply(_) => "APPLY_FAILED".to_owned(),
            Self::Shadow(error) => error.code(),
        }
    }
}

impl From<PipelineError> for CliError {
    fn from(error: PipelineError) -> Self {
        Self::Pipeline(error)
    }
}

impl From<BridgeError> for CliError {
    fn from(error: BridgeError) -> Self {
        Self::Pipeline(error.into())
    }
}

impl From<ApplyError> for CliError {
    fn from(error: ApplyError) -> Self {
        Self::Apply(error)
    }
}

impl From<StoreError> for CliError {
    fn from(_: StoreError) -> Self {
        Self::Store
    }
}

impl From<ShadowError> for CliError {
    fn from(error: ShadowError) -> Self {
        Self::Shadow(error)
    }
}

impl From<std::io::Error> for CliError {
    fn from(_: std::io::Error) -> Self {
        Self::Io
    }
}

/// 그림자 비교용 Rust 엔진 어댑터(운영 pipeline::run_plan). 환불 연결은 2차 전환 전까지 Python 다리에서 받는다.
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
        Some("links") if args.get(1).map(String::as_str) == Some("ota") => {
            links_ota::run(&args[2..])
        }
        Some("shadow") => finish(shadow(&args[1..]), "status"),
        Some("shadow-links") => finish(shadow_links(&args[1..]), "status"),
        Some("links") => finish(links_cmd(&args[1..]), "ok"),
        Some("plan") => finish(plan(&args[1..]), "ok"),
        Some("apply") => finish(apply_cmd(&args[1..]), "ok"),
        Some("rejudge") => finish(rejudge(&args[1..]), "ok"),
        Some("periods") => finish(periods(&args[1..]), "ok"),
        Some("migrate") => finish(migrate_cmd(&args[1..]), "ok"),
        Some(_) => {
            eprintln!(
                "usage: costcore <shadow|shadow-links|links|plan|apply|rejudge|periods|migrate> ..."
            );
            ExitCode::from(2)
        }
    }
}

/// `Ok((코드, 값))`을 한 줄로 내고 종료 코드로 바꾼다. `Err`은 공개 안전한 오류 코드만 낸다.
fn finish(result: Result<(u8, Value), CliError>, kind: &str) -> ExitCode {
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
    fn parse(args: &[String]) -> Result<Self, CliError> {
        let mut flags = Flags {
            values: Vec::new(),
            switches: Vec::new(),
        };
        let mut iter = args.iter();
        while let Some(arg) = iter.next() {
            match arg.as_str() {
                "--reconsider"
                | "--allow-live"
                | "--backfill-decisions"
                | "--changed"
                | "--rows-stdin" => flags.switches.push(arg.clone()),
                "--db" | "--host-root" | "--known-diffs" | "--private-out" | "--python"
                | "--repo-root" | "--digest" | "--now" | "--core" | "--periods" | "--ota-input" => {
                    let value = iter.next().ok_or(CliError::UsageInvalid)?;
                    flags.values.push((arg.clone(), value.clone()));
                }
                _ => return Err(CliError::UsageInvalid),
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

fn shadow(args: &[String]) -> Result<(u8, Value), CliError> {
    let flags = Flags::parse(args)?;
    let db = PathBuf::from(flags.get("--db").ok_or(CliError::UsageInvalid)?);
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

/// `costcore shadow-links [--db COPY] [--ota-input FILE] [--private-out PATH]`: 2차 전환 C1의 연결 그림자.
/// 환불 짝은 사본 DB(`--db`)에서, OTA 연결은 풀이기 입력 파일에서 Python 다리 `links`와 Rust 연결을 비교한다.
/// 둘 중 하나는 있어야 한다. 목록 밖 차이가 있으면 종료 코드 1이다. 공개 출력은 유형 키와 건수뿐이다.
fn shadow_links(args: &[String]) -> Result<(u8, Value), CliError> {
    let flags = Flags::parse(args)?;
    let db = flags.get("--db").map(PathBuf::from);
    let ota_input = flags.get("--ota-input").map(PathBuf::from);
    if db.is_none() && ota_input.is_none() {
        return Err(CliError::UsageInvalid);
    }
    let host = PathBuf::from(flags.get("--host-root").unwrap_or(DEFAULT_HOST));
    let repo = PathBuf::from(flags.get("--repo-root").unwrap_or("."));
    let known_path = flags
        .get("--known-diffs")
        .map(PathBuf::from)
        .unwrap_or_else(|| repo.join("core").join("known-diffs.txt"));
    if let Some(db) = &db {
        reject_live_db(db, &host)?;
    }
    let private_out = match flags.get("--private-out") {
        Some(path) => Some(cost_core::shadow::ensure_private_path(
            &PathBuf::from(path),
            &host,
        )?),
        None => None,
    };
    let known = parse_known_diffs(&std::fs::read_to_string(&known_path)?)?;
    let python = python_bridge(&flags);
    let config_json = |name: &str| std::fs::read_to_string(repo.join("config").join(name));
    let refund = match &db {
        Some(db) => {
            let config = PairingConfig::from_json(&config_json("refund-pairing.json")?)
                .map_err(|_| ShadowError::ConfigInvalid)?;
            Some(run_refund(db, &python, &config)?)
        }
        None => None,
    };
    let ota = match &ota_input {
        Some(path) => {
            let input: Value = serde_json::from_str(&std::fs::read_to_string(path)?)
                .map_err(|_| CliError::PlanResponseInvalid)?;
            let defaults: Value = serde_json::from_str(&config_json("ota-matching-defaults.json")?)
                .map_err(|_| ShadowError::ConfigInvalid)?;
            let defaults =
                Defaults::from_value(&defaults).map_err(|_| ShadowError::ConfigInvalid)?;
            Some(run_ota(&input, &python, &defaults)?)
        }
        None => None,
    };
    let report = judge_links(refund, ota, &known);
    let mut public = report.public_json()?;
    if let Some(path) = private_out {
        let lines = report.private_lines();
        write_private_lines(&path, &host, &lines)?;
        public["private_details"] = json!(lines.len());
    }
    Ok((u8::from(!report.passed()), public))
}

/// `costcore links refund --db BOARD [--repo-root ROOT]`: 환불 짝을 `transactions` 원행에서 도출해 Python 다리 `links`(kind=refund)와
/// 같은 계약의 JSON(`links`·`groups`·`group_exclusions`·`held`·`review_originals`)으로 낸다. 읽기 전용이라 운영 DB도 받는다.
fn links_cmd(args: &[String]) -> Result<(u8, Value), CliError> {
    if args.first().map(String::as_str) != Some("refund") {
        return Err(CliError::UsageInvalid);
    }
    let flags = Flags::parse(&args[1..])?;
    let stdin_rows = flags.on("--rows-stdin");
    if stdin_rows == flags.get("--db").is_some() {
        return Err(CliError::UsageInvalid);
    }
    let repo = PathBuf::from(flags.get("--repo-root").unwrap_or("."));
    let config = PairingConfig::from_json(&std::fs::read_to_string(
        repo.join("config").join("refund-pairing.json"),
    )?)
    .map_err(|_| ShadowError::ConfigInvalid)?;
    let rows = if stdin_rows {
        // 호출자가 쓰기 트랜잭션 안의 아직 커밋 안 된 행까지 담아 보낸다(파일은 읽지 않는다).
        let mut body = String::new();
        std::io::stdin().read_to_string(&mut body)?;
        let value: Value =
            serde_json::from_str(&body).map_err(|_| CliError::PlanResponseInvalid)?;
        refund_rows_from_json(&value)?
    } else {
        let db = PathBuf::from(flags.get("--db").ok_or(CliError::UsageInvalid)?);
        refund_rows(&read_projection(&db)?.transactions)
    };
    let refunds = Refunds::derive(&rows, &config);
    Ok((0, json!({"ok": true, "result": refund_values(&refunds)})))
}

/// `costcore plan --db PATH`: 표준 입력의 JSON(선택)을 요청에 합쳐 Rust 엔진 결과를 낸다.
fn plan(args: &[String]) -> Result<(u8, Value), CliError> {
    let flags = Flags::parse(args)?;
    let db = PathBuf::from(flags.get("--db").ok_or(CliError::UsageInvalid)?);
    let mut body = String::new();
    std::io::stdin().read_to_string(&mut body)?;
    let extra: Value = if body.trim().is_empty() {
        Value::Null
    } else {
        serde_json::from_str(&body).map_err(|_| CliError::PlanResponseInvalid)?
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
    let targets = run_plan(&request, Some(&python_bridge(&flags)))?;
    Ok((0, json!({"ok": true, "result": targets_json(&targets)})))
}

/// `costcore apply --db PATH --core CORE.sqlite --digest D [--allow-live]`: 표준 입력의 JSON(`trips`·`nets`·`evidence`·`transaction_ids`·
/// `reconsider`·`links`)으로 계획을 다시 만들어 digest가 같을 때만 쓴다. 운영 DB 경로는 `--allow-live` 없이는 거부한다.
fn apply_cmd(args: &[String]) -> Result<(u8, Value), CliError> {
    let flags = Flags::parse(args)?;
    let db = PathBuf::from(flags.get("--db").ok_or(CliError::UsageInvalid)?);
    let digest = flags.get("--digest").ok_or(CliError::UsageInvalid)?;
    let host = PathBuf::from(flags.get("--host-root").unwrap_or(DEFAULT_HOST));
    if !flags.on("--allow-live") {
        reject_live_db(&db, &host)?;
    }
    let mut body = String::new();
    std::io::stdin().read_to_string(&mut body)?;
    let context: Value = if body.trim().is_empty() {
        Value::Null
    } else {
        serde_json::from_str(&body).map_err(|_| CliError::PlanResponseInvalid)?
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
    let core = PathBuf::from(flags.get("--core").ok_or(CliError::UsageInvalid)?);
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
        backfill: flags.on("--backfill-decisions"),
    };
    let out = apply(&mut conn, &core, &request, &links)?;
    Ok((
        0,
        json!({"ok": true, "result": out.summary, "written": out.written,
            "skipped_unjudged": out.skipped_unjudged, "skipped_mismatch": out.skipped_mismatch, "backfilled": out.backfilled}),
    ))
}

/// `costcore migrate --core CORE.sqlite`: core.sqlite가 없으면 만들고 최신 스키마까지 이관한다. board는 열지 않는다.
fn migrate_cmd(args: &[String]) -> Result<(u8, Value), CliError> {
    let flags = Flags::parse(args)?;
    let core = PathBuf::from(flags.get("--core").ok_or(CliError::UsageInvalid)?);
    let created = !core.exists();
    let (from, to) = cost_core::store::migrate_file(&core).map_err(|error| match error {
        StoreError::SchemaTooNew { .. } => CliError::CoreSchemaMismatch,
        _ => CliError::Store,
    })?;
    Ok((
        0,
        json!({"ok": true, "created": created, "from_version": from, "to_version": to}),
    ))
}

/// `--periods FILE`(Python 다리 `periods` 출력)의 거래별 근거 후보 목록. 없으면 비어 있다.
fn load_period_facts(flags: &Flags) -> Result<BTreeMap<String, Value>, CliError> {
    let Some(path) = flags.get("--periods") else {
        return Ok(BTreeMap::new());
    };
    let body: Value = serde_json::from_str(&std::fs::read_to_string(path)?)
        .map_err(|_| CliError::PlanResponseInvalid)?;
    Ok(body["facts"]
        .as_object()
        .ok_or(CliError::PlanResponseInvalid)?
        .iter()
        .map(|(k, v)| (k.clone(), v.clone()))
        .collect())
}

/// `costcore periods --db BOARD [--periods FILE] [--private-out PATH]`: 거래마다 Rust 이용기간 규칙의 결과를
/// 낸다(그림자 비교용, 쓰지 않는다). 공개 출력은 건수뿐이고 거래 ID·기간은 보호 경로 파일에만 쓴다.
fn periods(args: &[String]) -> Result<(u8, Value), CliError> {
    let flags = Flags::parse(args)?;
    let db = PathBuf::from(flags.get("--db").ok_or(CliError::UsageInvalid)?);
    let host = PathBuf::from(flags.get("--host-root").unwrap_or(DEFAULT_HOST));
    reject_live_db(&db, &host)?;
    let private_out = match flags.get("--private-out") {
        Some(path) => Some(cost_core::shadow::ensure_private_path(
            &PathBuf::from(path),
            &host,
        )?),
        None => None,
    };
    let facts = load_period_facts(&flags)?;
    let input = read_plan_input(&db)?;
    let (mut lines, mut with_period) = (Vec::new(), 0usize);
    for row in &input.rows {
        let Some(tid) = row["transaction_id"].as_str() else {
            continue;
        };
        let board = input.boards.get(&format!("card-{tid}"));
        let found = period::verified_period_for(
            &period::PeriodRow::for_card(tid, board.map(|b| b.payload_json.as_str())),
            facts.get(tid).unwrap_or(&Value::Null),
        );
        with_period += usize::from(!found.is_empty());
        lines.push(json!({"id": tid, "period": found}).to_string());
    }
    if let Some(path) = private_out {
        write_private_lines(&path, &host, &lines)?;
    }
    Ok((
        0,
        json!({"ok": true, "rows": lines.len(), "with_period": with_period}),
    ))
}

/// `costcore rejudge --changed --db BOARD [--core CORE] [--periods FILE] [--private-out PATH]`:
/// 이용기간 근거 digest(예약 사실·연결·판정 함수 버전)가 저장값과 달라진 거래만 고른다. 쓰지 않는다.
/// `FILE`은 Python 다리 `periods` 출력(`{"facts": {거래 ID: 후보 목록}}`). 공개 출력은 건수뿐이다.
fn rejudge(args: &[String]) -> Result<(u8, Value), CliError> {
    let flags = Flags::parse(args)?;
    if !flags.on("--changed") {
        return Err(CliError::UsageInvalid);
    }
    let db = PathBuf::from(flags.get("--db").ok_or(CliError::UsageInvalid)?);
    let host = PathBuf::from(flags.get("--host-root").unwrap_or(DEFAULT_HOST));
    reject_live_db(&db, &host)?;
    let private_out = match flags.get("--private-out") {
        Some(path) => Some(cost_core::shadow::ensure_private_path(
            &PathBuf::from(path),
            &host,
        )?),
        None => None,
    };
    let facts = load_period_facts(&flags)?;
    let input = read_plan_input(&db)?;
    let cards = input
        .rows
        .iter()
        .filter_map(|r| r["transaction_id"].as_str())
        .map(|tid| {
            let board = input.boards.get(&format!("card-{tid}"));
            (tid, board.map(|b| b.payload_json.as_str()))
        });
    let current = period::current_digests(cards, &facts);
    let stored = match flags.get("--core") {
        Some(path) => stored_digests_readonly(&PathBuf::from(path))?,
        None => BTreeMap::new(),
    };
    let changed = period::changed_since(&stored, &current);
    if let Some(path) = private_out {
        write_private_lines(&path, &host, &changed)?;
    }
    Ok((
        0,
        json!({"ok": true, "scanned": current.len(), "changed": changed.len(),
               "unchanged": current.len() - changed.len(), "fn_version": period::PERIOD_FN_VERSION}),
    ))
}
