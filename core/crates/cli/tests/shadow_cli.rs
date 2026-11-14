//! `costcore` 실행 파일 경계 시험(합성 경로만). Rust 엔진이 없는 동안의 동작과 보호 경로 거부.

use std::io::Write;
use std::path::PathBuf;
use std::process::{Command, Stdio};

fn scratch(name: &str) -> PathBuf {
    let dir = std::env::temp_dir().join(format!("costcore-cli-{}-{name}", std::process::id()));
    std::fs::create_dir_all(dir.join("data").join("backups")).unwrap();
    dir
}

fn run(args: &[&str], stdin: &str) -> (i32, String) {
    let mut child = Command::new(env!("CARGO_BIN_EXE_costcore"))
        .args(args)
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
    (
        out.status.code().unwrap(),
        String::from_utf8(out.stdout).unwrap(),
    )
}

#[test]
fn shadow_on_an_unreadable_copy_ends_with_a_public_safe_error() {
    let host = scratch("engine");
    let db = host.join("copy.sqlite");
    std::fs::write(&db, b"").unwrap();
    let known = host.join("known.txt");
    std::fs::write(&known, "classify-176  # x\n").unwrap();
    let (code, out) = run(
        &[
            "shadow",
            "--db",
            db.to_str().unwrap(),
            "--host-root",
            host.to_str().unwrap(),
            "--known-diffs",
            known.to_str().unwrap(),
        ],
        "",
    );
    assert_eq!(code, 2);
    assert!(out.contains("\"code\":\"STORE_ERROR\""), "{out}");
    let _ = std::fs::remove_dir_all(&host);
}

#[test]
fn shadow_rejects_private_output_outside_protected_backups() {
    let host = scratch("private");
    let db = host.join("copy.sqlite");
    std::fs::write(&db, b"").unwrap();
    let outside = host.join("details.jsonl");
    let (code, out) = run(
        &[
            "shadow",
            "--db",
            db.to_str().unwrap(),
            "--host-root",
            host.to_str().unwrap(),
            "--private-out",
            outside.to_str().unwrap(),
        ],
        "",
    );
    assert_eq!(code, 2);
    assert!(out.contains("PRIVATE_PATH_REJECTED"), "{out}");
    assert!(!outside.exists());
    let _ = std::fs::remove_dir_all(&host);
}

#[test]
fn shadow_rejects_the_live_database() {
    let host = scratch("live");
    let live = host.join("data").join("board.sqlite");
    std::fs::write(&live, b"").unwrap();
    let (code, out) = run(
        &[
            "shadow",
            "--db",
            live.to_str().unwrap(),
            "--host-root",
            host.to_str().unwrap(),
        ],
        "",
    );
    assert_eq!(code, 2);
    assert!(out.contains("DB_IS_LIVE"), "{out}");
    let _ = std::fs::remove_dir_all(&host);
}

#[test]
fn plan_on_a_missing_database_reports_a_public_safe_code() {
    let (code, out) = run(
        &["plan", "--db", "unused.sqlite"],
        "{\"transaction_ids\":[\"x\"]}",
    );
    assert_eq!(code, 2);
    assert!(
        out.contains("\"ok\":false") && out.contains("STORE_ERROR"),
        "{out}"
    );
}

#[test]
fn rejudge_needs_the_changed_switch_and_reports_public_safe_codes() {
    let (code, out) = run(&["rejudge", "--db", "unused.sqlite"], "");
    assert_eq!(code, 2);
    assert!(out.contains("USAGE_INVALID"), "{out}");
    let (code, out) = run(&["rejudge", "--changed", "--db", "unused.sqlite"], "");
    assert_eq!(code, 2);
    assert!(
        out.contains("\"ok\":false") && out.contains("STORE_ERROR"),
        "{out}"
    );
}

#[test]
fn periods_rejects_the_live_database() {
    let host = scratch("periods-live");
    let live = host.join("data").join("board.sqlite");
    std::fs::write(&live, b"").unwrap();
    let (code, out) = run(
        &[
            "periods",
            "--db",
            live.to_str().unwrap(),
            "--host-root",
            host.to_str().unwrap(),
        ],
        "",
    );
    assert_eq!(code, 2);
    assert!(out.contains("DB_IS_LIVE"), "{out}");
    let _ = std::fs::remove_dir_all(&host);
}
