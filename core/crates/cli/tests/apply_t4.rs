//! T4: 합성 DB에서 Python `apply`와 Rust `costcore apply`의 결과 DB가 테이블별로 같은지 본다(설계 §3.3, U11).
//! 운영 DB·운영 포트를 쓰지 않는다. Python 3(표준 라이브러리만)이 필요하며 없으면 실패한다(건너뛰지 않는다).

use std::io::Write;
use std::path::{Path, PathBuf};
use std::process::{Command, Stdio};

use rusqlite::Connection;
use rusqlite::types::ValueRef;
use serde_json::Value;

const NOW: &str = "2026-11-14T00:00:00+00:00";

type Dump = Vec<(String, Vec<Vec<String>>)>;

fn repo_root() -> PathBuf {
    Path::new(env!("CARGO_MANIFEST_DIR"))
        .join("../../..")
        .canonicalize()
        .unwrap()
}

fn python() -> String {
    std::env::var("COST_PYTHON").unwrap_or_else(|_| {
        if Command::new("python").arg("--version").output().is_ok() {
            "python".into()
        } else {
            "python3".into()
        }
    })
}

fn scratch(name: &str) -> PathBuf {
    static N: std::sync::atomic::AtomicU32 = std::sync::atomic::AtomicU32::new(0);
    let n = N.fetch_add(1, std::sync::atomic::Ordering::SeqCst);
    let dir = std::env::temp_dir().join(format!("costcore-t4-{}-{n}-{name}", std::process::id()));
    let _ = std::fs::remove_dir_all(&dir);
    std::fs::create_dir_all(dir.join("data").join("backups")).unwrap();
    dir
}

fn helper(args: &[&str]) -> String {
    let script = repo_root().join("core/crates/cli/tests/t4_python.py");
    let out = Command::new(python())
        .arg("-I")
        .arg(script)
        .args(args)
        .output()
        .unwrap();
    assert!(
        out.status.success(),
        "python helper failed: {}",
        String::from_utf8_lossy(&out.stderr)
    );
    String::from_utf8(out.stdout).unwrap()
}

fn costcore(args: &[&str], stdin: &str) -> (i32, Value) {
    costcore_with_python(args, stdin, &python())
}

fn costcore_with_python(args: &[&str], stdin: &str, python: &str) -> (i32, Value) {
    let mut child = Command::new(env!("CARGO_BIN_EXE_costcore"))
        .args(args)
        .arg("--python")
        .arg(python)
        .arg("--repo-root")
        .arg(repo_root())
        .stdin(Stdio::piped())
        .stdout(Stdio::piped())
        .spawn()
        .unwrap();
    child
        .stdin
        .take()
        .unwrap()
        .write_all(stdin.as_bytes())
        .unwrap();
    let out = child.wait_with_output().unwrap();
    let text = String::from_utf8(out.stdout).unwrap();
    (
        out.status.code().unwrap(),
        serde_json::from_str(text.lines().next().unwrap()).unwrap_or(Value::Null),
    )
}

/// 모든 테이블의 모든 행(rowid 순서)을 문자열로.
fn dump(path: &Path) -> Dump {
    let conn = Connection::open(path).unwrap();
    let names: Vec<String> = conn
        .prepare("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name")
        .unwrap()
        .query_map([], |r| r.get(0))
        .unwrap()
        .map(Result::unwrap)
        .collect();
    names
        .into_iter()
        .map(|name| {
            let mut stmt = conn
                .prepare(&format!("SELECT * FROM {name} ORDER BY rowid"))
                .unwrap();
            let n = stmt.column_count();
            let rows = stmt
                .query_map([], |r| {
                    Ok((0..n)
                        .map(|i| match r.get_ref(i).unwrap() {
                            ValueRef::Null => "NULL".to_owned(),
                            ValueRef::Integer(v) => v.to_string(),
                            ValueRef::Real(v) => v.to_string(),
                            ValueRef::Text(t) => String::from_utf8_lossy(t).into_owned(),
                            ValueRef::Blob(b) => format!("blob{}", b.len()),
                        })
                        .collect::<Vec<_>>())
                })
                .unwrap()
                .map(Result::unwrap)
                .collect();
            (name, rows)
        })
        .collect()
}

struct Pair {
    dir: PathBuf,
    python_db: PathBuf,
    rust_db: PathBuf,
    original: Dump,
    opts: String,
    digest: String,
    python_targets: u64,
}

fn pair(kind: &str) -> Pair {
    let dir = scratch(kind);
    let python_db = dir.join("python.sqlite");
    let rust_db = dir.join("rust.sqlite");
    let opts_path = dir.join("opts.json");
    helper(&[
        "build",
        kind,
        python_db.to_str().unwrap(),
        opts_path.to_str().unwrap(),
    ]);
    std::fs::copy(&python_db, &rust_db).unwrap();
    let original = dump(&rust_db);
    let opts = std::fs::read_to_string(&opts_path).unwrap();
    let out = helper(&[
        "apply",
        python_db.to_str().unwrap(),
        opts_path.to_str().unwrap(),
        NOW,
    ]);
    let report: Value = serde_json::from_str(out.trim()).unwrap();
    Pair {
        dir,
        python_db,
        rust_db,
        original,
        opts,
        digest: report["digest"].as_str().unwrap().to_owned(),
        python_targets: report["targets"].as_u64().unwrap(),
    }
}

fn core_path(p: &Pair) -> PathBuf {
    p.dir.join("core.sqlite")
}

fn rust_args<'a>(p: &'a Pair, db: &'a str, core: &'a str, digest: &'a str) -> Vec<&'a str> {
    vec![
        "apply",
        "--db",
        db,
        "--core",
        core,
        "--digest",
        digest,
        "--now",
        NOW,
        "--host-root",
        p.dir.to_str().unwrap(),
    ]
}

fn run_rust(p: &Pair, digest: &str) -> (i32, Value) {
    run_rust_with(p, digest, &[])
}

fn run_rust_with(p: &Pair, digest: &str, extra: &[&str]) -> (i32, Value) {
    let core = core_path(p);
    let mut args = rust_args(
        p,
        p.rust_db.to_str().unwrap(),
        core.to_str().unwrap(),
        digest,
    );
    args.extend_from_slice(extra);
    costcore(&args, &p.opts)
}

fn fresh_digest(p: &Pair) -> String {
    let plan = helper(&[
        "plan",
        p.rust_db.to_str().unwrap(),
        p.dir.join("opts.json").to_str().unwrap(),
    ]);
    let plan: Value = serde_json::from_str(plan.trim()).unwrap();
    plan["digest"].as_str().unwrap().to_owned()
}

/// 두 DB의 모든 테이블이 행 단위로 같다. 달라지면 테이블과 행을 알려 준다.
/// `right`는 Rust 결과다. 요구에 따라 Rust 작성 `card.automatic_classification` 기록에만 `detail_json.writer="costcore"`
/// 표식이 더 있으므로, 표식이 있음을 확인하고 떼어 낸 뒤 비교한다(나머지 내용은 Python과 같아야 한다).
fn tables_differ(left: &Dump, right: &Dump) -> Vec<String> {
    let mut diffs = Vec::new();
    for ((name, rows_a), (_, rows_b)) in left.iter().zip(right) {
        let mut rows_b = rows_b.clone();
        if name == "change_log" {
            for row in rows_b
                .iter_mut()
                .filter(|r| r[2] == "card.automatic_classification")
            {
                let mut detail: Value = serde_json::from_str(&row[4]).unwrap();
                let mark = detail.as_object_mut().unwrap().remove("writer");
                assert_eq!(mark, Some(Value::String("costcore".into())), "{row:?}");
                row[4] = cost_core::digest::python_json(&detail);
            }
        }
        if *rows_a != rows_b {
            diffs.push(format!("{name}: {} vs {} rows", rows_a.len(), rows_b.len()));
        }
    }
    diffs
}

#[test]
fn t4_general_python_and_rust_apply_leave_identical_tables() {
    let p = pair("general");
    assert!(
        p.python_targets >= 3,
        "합성 시나리오가 목표를 만들어야 한다"
    );
    let (code, out) = run_rust(&p, &p.digest);
    assert_eq!(code, 0, "{out}");
    assert_eq!(out["skipped_mismatch"], 0, "{out}");
    assert_eq!(out["skipped_unjudged"], 0, "{out}");
    assert_eq!(out["written"].as_u64().unwrap(), p.python_targets, "{out}");
    let diffs = tables_differ(&dump(&p.python_db), &dump(&p.rust_db));
    println!(
        "T4 general: python_targets={} rust={out} table_diffs={diffs:?}",
        p.python_targets
    );
    assert!(diffs.is_empty(), "{diffs:?}");
}

#[test]
fn t4_booking_period_correction_matches_python_including_history() {
    let p = pair("booking");
    assert_eq!(p.python_targets, 1);
    let (code, out) = run_rust(&p, &p.digest);
    assert_eq!(code, 0, "{out}");
    assert_eq!(out["written"], 1, "{out}");
    let diffs = tables_differ(&dump(&p.python_db), &dump(&p.rust_db));
    println!("T4 booking: rust={out} table_diffs={diffs:?}");
    assert!(diffs.is_empty(), "{diffs:?}");
}

/// 저장된 이용기간을 Python `verified_period_for`의 `YYYY-MM-DD~YYYY-MM-DD`(모르면 빈 문자열) 표기로.
fn stored_period(core: &Path, tid: &str) -> String {
    let conn = Connection::open(core).unwrap();
    let json: String = conn
        .query_row(
            "SELECT service_period_json FROM decisions WHERE transaction_id=?",
            [tid],
            |r| r.get(0),
        )
        .unwrap();
    let period: Value = serde_json::from_str(&json).unwrap();
    match period["kind"].as_str() {
        Some("known") => format!(
            "{}~{}",
            period["starts_on"].as_str().unwrap(),
            period["ends_on"].as_str().unwrap()
        ),
        _ => String::new(),
    }
}

#[test]
fn t4_stored_period_with_context_periods_equals_python_verified_period() {
    let p = pair("periods");
    let opts: Value = serde_json::from_str(&p.opts).unwrap();
    assert!(
        opts["periods"].as_object().is_some_and(|m| !m.is_empty()),
        "합성 시나리오가 근거를 만들어야 한다"
    );
    assert_eq!(p.python_targets, 2);
    let (code, out) = run_rust(&p, &p.digest);
    assert_eq!(code, 0, "{out}");
    assert_eq!(out["written"], 2, "{out}");
    let diffs = tables_differ(&dump(&p.python_db), &dump(&p.rust_db));
    let mut checked = 0;
    for (tid, expected) in opts["expected_periods"].as_object().unwrap() {
        let expected = expected.as_str().unwrap();
        let stored = stored_period(&core_path(&p), tid);
        println!("T4 periods {tid}: python={expected:?} rust={stored:?}");
        assert_eq!(stored, expected, "{tid}");
        checked += 1;
    }
    assert_eq!(checked, 2);
    assert_eq!(
        opts["expected_periods"]["p1"], "2026-10-01~2026-10-03",
        "근거가 있는 거래는 기간이 있어야 한다"
    );
    assert_eq!(
        opts["expected_periods"]["p2"], "",
        "근거가 없는 거래는 모름이어야 한다"
    );
    println!("T4 periods: rust={out} table_diffs={diffs:?}");
    assert!(diffs.is_empty(), "{diffs:?}");
    // 같은 근거로 다시 실행하면 판정 재저장도 없다(근거 digest 동일).
    let before = dump(&core_path(&p));
    let (code, again) = run_rust(&p, &fresh_digest(&p));
    assert_eq!(code, 0, "{again}");
    assert_eq!(again["written"], 0, "{again}");
    assert_eq!(again["backfilled"], 0, "{again}");
    assert_eq!(dump(&core_path(&p)), before);
}

#[test]
fn unjudgeable_targets_are_not_published() {
    let p = pair("unattributable");
    assert!(p.python_targets >= 1);
    let (code, out) = run_rust(&p, &p.digest);
    assert_eq!(code, 0, "{out}");
    assert_eq!(out["written"], 0, "{out}");
    assert_eq!(out["skipped_unjudged"].as_u64().unwrap(), p.python_targets);
    assert_eq!(dump(&p.rust_db), p.original);
}

#[test]
fn rerun_with_same_input_writes_nothing() {
    let p = pair("general");
    let (code, _) = run_rust(&p, &p.digest);
    assert_eq!(code, 0);
    let before = dump(&p.rust_db);
    let core_before = dump(&core_path(&p));
    let plan = helper(&[
        "plan",
        p.rust_db.to_str().unwrap(),
        p.dir.join("opts.json").to_str().unwrap(),
    ]);
    let plan: Value = serde_json::from_str(plan.trim()).unwrap();
    let (code, out) = run_rust(&p, plan["digest"].as_str().unwrap());
    assert_eq!(code, 0, "{out}");
    assert_eq!(out["written"], 0, "{out}");
    assert_eq!(dump(&p.rust_db), before);
    assert_eq!(dump(&core_path(&p)), core_before);
}

/// 요청에 `links`를 실어 준다. Python이 없는 경로를 주어도(다리를 띄우면 실패) 결과가 Python과 같다.
fn with_links(p: &Pair) -> String {
    let links = helper(&["links", p.rust_db.to_str().unwrap()]);
    let mut opts: Value = serde_json::from_str(&p.opts).unwrap();
    opts["links"] = serde_json::from_str(links.trim()).unwrap();
    opts.to_string()
}

#[test]
fn context_links_replace_the_python_bridge_and_leave_identical_tables() {
    let p = pair("general");
    let body = with_links(&p);
    let core = core_path(&p);
    let args = rust_args(
        &p,
        p.rust_db.to_str().unwrap(),
        core.to_str().unwrap(),
        &p.digest,
    );
    let (code, out) = costcore_with_python(&args, &body, "no-such-python-for-bridge");
    assert_eq!(code, 0, "{out}");
    assert_eq!(out["written"].as_u64().unwrap(), p.python_targets, "{out}");
    let diffs = tables_differ(&dump(&p.python_db), &dump(&p.rust_db));
    assert!(diffs.is_empty(), "{diffs:?}");
}

#[test]
fn without_context_links_the_bridge_is_still_used() {
    let p = pair("general");
    let core = core_path(&p);
    let args = rust_args(
        &p,
        p.rust_db.to_str().unwrap(),
        core.to_str().unwrap(),
        &p.digest,
    );
    let (code, out) = costcore_with_python(&args, &p.opts, "no-such-python-for-bridge");
    assert_ne!(code, 0, "{out}");
    assert_eq!(dump(&p.rust_db), p.original);
}

#[test]
fn stale_digest_is_refused_and_nothing_is_written() {
    let p = pair("general");
    let (code, out) = run_rust(&p, &"0".repeat(64));
    assert_eq!(code, 2);
    assert_eq!(out["error"]["code"], "CLASSIFICATION_PREVIEW_STALE");
    assert_eq!(dump(&p.rust_db), p.original);
}

#[test]
fn live_database_path_is_refused_without_allow_live() {
    let p = pair("general");
    let live = p.dir.join("data").join("board.sqlite");
    std::fs::copy(&p.rust_db, &live).unwrap();
    let core = core_path(&p);
    let args = rust_args(
        &p,
        live.to_str().unwrap(),
        core.to_str().unwrap(),
        &p.digest,
    );
    let (code, out) = costcore(&args, &p.opts);
    assert_eq!(code, 2);
    assert_eq!(out["error"]["code"], "DB_IS_LIVE");
}

#[test]
fn interrupted_write_is_recovered_by_backfilling_decisions_only() {
    let p = pair("general");
    let (code, first) = run_rust(&p, &p.digest);
    assert_eq!(code, 0, "{first}");
    let written = first["written"].as_u64().unwrap();
    assert!(written >= 3);
    // board 커밋 뒤·core 커밋 전 중단을 흉내 낸다: 화면 열은 채워지고 decisions가 없다.
    let core = core_path(&p);
    let decisions_before = {
        let all = dump(&core);
        all.into_iter().find(|(n, _)| n == "decisions").unwrap().1
    };
    Connection::open(&core)
        .unwrap()
        .execute("DELETE FROM decisions", [])
        .unwrap();
    let board_before = dump(&p.rust_db);
    // 그냥 다시 실행해서는 채워지지 않는다(더는 계획의 목표가 아니다).
    let (code, out) = run_rust(&p, &fresh_digest(&p));
    assert_eq!(code, 0, "{out}");
    assert_eq!(
        (out["written"].clone(), out["backfilled"].clone()),
        (0.into(), 0.into())
    );
    // 복구 모드는 판정만 채우고 board.sqlite는 건드리지 않는다.
    let (code, out) = run_rust_with(&p, &fresh_digest(&p), &["--backfill-decisions"]);
    assert_eq!(code, 0, "{out}");
    assert_eq!(out["written"], 0, "{out}");
    assert!(out["backfilled"].as_u64().unwrap() >= written, "{out}");
    assert_eq!(dump(&p.rust_db), board_before);
    let restored = dump(&core)
        .into_iter()
        .find(|(n, _)| n == "decisions")
        .unwrap()
        .1;
    for row in &decisions_before {
        assert!(restored.contains(row), "복원되지 않은 판정: {row:?}");
    }
    // 다시 하면 더 채울 것이 없다.
    let (_, again) = run_rust_with(&p, &fresh_digest(&p), &["--backfill-decisions"]);
    assert_eq!(again["backfilled"], 0, "{again}");
}
