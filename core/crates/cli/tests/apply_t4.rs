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
    let mut child = Command::new(env!("CARGO_BIN_EXE_costcore"))
        .args(args)
        .arg("--python")
        .arg(python())
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
    let core = core_path(p);
    let args = rust_args(
        p,
        p.rust_db.to_str().unwrap(),
        core.to_str().unwrap(),
        digest,
    );
    costcore(&args, &p.opts)
}

/// 두 DB의 모든 테이블이 행 단위로 같다. 달라지면 테이블과 행을 알려 준다.
fn tables_differ(left: &Dump, right: &Dump) -> Vec<String> {
    let mut diffs = Vec::new();
    for ((name, rows_a), (_, rows_b)) in left.iter().zip(right) {
        if rows_a != rows_b {
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
