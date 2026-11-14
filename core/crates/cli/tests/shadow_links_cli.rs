//! `costcore shadow-links` 끝에서 끝까지: 합성 시나리오 DB·합성 OTA 입력에 실제 Python 다리를 불러 Rust와 비교한다.
//! 운영 DB·운영 포트를 쓰지 않는다. Python 3이 필요하며 없으면 실패한다(건너뛰지 않는다).

use std::path::{Path, PathBuf};
use std::process::{Command, Stdio};

use serde_json::Value;

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
    let dir = std::env::temp_dir().join(format!("costcore-links-{}-{name}", std::process::id()));
    let _ = std::fs::remove_dir_all(&dir);
    std::fs::create_dir_all(dir.join("data").join("backups")).unwrap();
    dir
}

fn golden(name: &str) -> Vec<Value> {
    std::fs::read_to_string(repo_root().join("core/golden/synthetic").join(name))
        .unwrap()
        .lines()
        .map(|l| serde_json::from_str(l).unwrap())
        .collect()
}

fn shadow_links(host: &Path, extra: &[&str]) -> (i32, Value) {
    let known = host.join("known.txt");
    std::fs::write(&known, "classify-176  # x\n").unwrap();
    let out = Command::new(env!("CARGO_BIN_EXE_costcore"))
        .arg("shadow-links")
        .args(["--host-root", host.to_str().unwrap()])
        .args(["--known-diffs", known.to_str().unwrap()])
        .args(["--python", &python()])
        .args(["--repo-root", repo_root().to_str().unwrap()])
        .args(extra)
        .stdin(Stdio::null())
        .output()
        .unwrap();
    let text = String::from_utf8(out.stdout).unwrap();
    (
        out.status.code().unwrap(),
        serde_json::from_str(text.lines().next().unwrap_or("")).unwrap_or(Value::Null),
    )
}

#[test]
fn refund_links_on_a_synthetic_copy_match_the_python_bridge() {
    let host = scratch("refund");
    let mut checked = 0;
    for case in golden("refund_pairing.jsonl")
        .iter()
        .filter(|c| {
            c["expected"]["links"]
                .as_object()
                .is_some_and(|l| !l.is_empty())
        })
        .take(4)
    {
        let scenario = host.join("scenario.json");
        std::fs::write(&scenario, case["input"]["scenario"].to_string()).unwrap();
        let db = host.join("copy.sqlite");
        let _ = std::fs::remove_file(&db);
        let built = Command::new(python())
            .arg("-I")
            .arg(repo_root().join("core/crates/cli/tests/links_python.py"))
            .args(["build", scenario.to_str().unwrap(), db.to_str().unwrap()])
            .output()
            .unwrap();
        assert!(
            built.status.success(),
            "{}",
            String::from_utf8_lossy(&built.stderr)
        );
        let (code, out) = shadow_links(&host, &["--db", db.to_str().unwrap()]);
        assert_eq!(code, 0, "{} {out}", case["case_id"]);
        assert_eq!(out["status"], "PASS", "{out}");
        assert!(out["refund"]["python"].as_u64().unwrap() > 0, "{out}");
        assert_eq!(out["refund"]["python"], out["refund"]["rust"], "{out}");
        checked += 1;
    }
    assert_eq!(checked, 4);
    let _ = std::fs::remove_dir_all(&host);
}

#[test]
fn ota_links_from_a_solver_input_file_match_the_python_bridge() {
    let host = scratch("ota");
    for case in golden("ota_links.jsonl").iter().take(3) {
        let input = host.join("ota-input.json");
        std::fs::write(&input, case["input"].to_string()).unwrap();
        let (code, out) = shadow_links(&host, &["--ota-input", input.to_str().unwrap()]);
        assert_eq!(code, 0, "{} {out}", case["case_id"]);
        assert_eq!(out["status"], "PASS", "{out}");
        assert_eq!(out["ota"]["python"], out["ota"]["rust"], "{out}");
        assert!(out["refund"].is_null());
    }
    let _ = std::fs::remove_dir_all(&host);
}

#[test]
fn without_any_input_the_command_ends_with_a_usage_code() {
    let host = scratch("usage");
    let (code, out) = shadow_links(&host, &[]);
    assert_eq!(code, 2);
    assert_eq!(out["code"], "USAGE_INVALID");
    let _ = std::fs::remove_dir_all(&host);
}

#[test]
fn links_refund_reproduces_every_refund_pairing_golden_case_from_the_db() {
    let host = scratch("links-cmd");
    let cases = golden("refund_pairing.jsonl");
    assert!(!cases.is_empty());
    for case in &cases {
        let scenario = host.join("scenario.json");
        std::fs::write(&scenario, case["input"]["scenario"].to_string()).unwrap();
        let db = host.join("copy.sqlite");
        let _ = std::fs::remove_file(&db);
        let built = Command::new(python())
            .arg("-I")
            .arg(repo_root().join("core/crates/cli/tests/links_python.py"))
            .args(["build", scenario.to_str().unwrap(), db.to_str().unwrap()])
            .output()
            .unwrap();
        assert!(built.status.success());
        let before = std::fs::read(&db).unwrap();
        let out = Command::new(env!("CARGO_BIN_EXE_costcore"))
            .args(["links", "refund", "--db", db.to_str().unwrap()])
            .args(["--repo-root", repo_root().to_str().unwrap()])
            .stdin(Stdio::null())
            .output()
            .unwrap();
        assert_eq!(out.status.code(), Some(0), "{}", case["case_id"]);
        let text = String::from_utf8(out.stdout).unwrap();
        let value: Value = serde_json::from_str(text.lines().next().unwrap()).unwrap();
        assert_eq!(value["ok"], true);
        assert_eq!(value["result"], case["expected"], "{}", case["case_id"]);
        assert_eq!(std::fs::read(&db).unwrap(), before, "read-only");
    }
    let _ = std::fs::remove_dir_all(&host);
}

fn links_refund_rows_stdin(body: &[u8], extra: &[&str]) -> (Option<i32>, Value) {
    use std::io::Write;
    let mut child = Command::new(env!("CARGO_BIN_EXE_costcore"))
        .args(["links", "refund", "--rows-stdin"])
        .args(["--repo-root", repo_root().to_str().unwrap()])
        .args(extra)
        .stdin(Stdio::piped())
        .stdout(Stdio::piped())
        .spawn()
        .unwrap();
    child.stdin.take().unwrap().write_all(body).unwrap();
    let out = child.wait_with_output().unwrap();
    let text = String::from_utf8(out.stdout).unwrap();
    (
        out.status.code(),
        serde_json::from_str(text.lines().next().unwrap_or("")).unwrap_or(Value::Null),
    )
}

#[test]
fn links_refund_from_stdin_rows_equals_the_golden_result_for_every_case() {
    let host = scratch("links-rows");
    for case in &golden("refund_pairing.jsonl") {
        let scenario = host.join("scenario.json");
        std::fs::write(&scenario, case["input"]["scenario"].to_string()).unwrap();
        let db = host.join("copy.sqlite");
        let _ = std::fs::remove_file(&db);
        let built = Command::new(python())
            .arg("-I")
            .arg(repo_root().join("core/crates/cli/tests/links_python.py"))
            .args(["build", scenario.to_str().unwrap(), db.to_str().unwrap()])
            .output()
            .unwrap();
        assert!(built.status.success());
        let rows = Command::new(python())
            .arg("-I")
            .arg(repo_root().join("core/crates/cli/tests/links_python.py"))
            .args(["rows", db.to_str().unwrap()])
            .output()
            .unwrap();
        assert!(
            rows.status.success(),
            "{}",
            String::from_utf8_lossy(&rows.stderr)
        );
        let (code, value) = links_refund_rows_stdin(&rows.stdout, &[]);
        assert_eq!(code, Some(0), "{}", case["case_id"]);
        assert_eq!(value["result"], case["expected"], "{}", case["case_id"]);
    }
    let _ = std::fs::remove_dir_all(&host);
}

#[test]
fn links_refund_rows_stdin_rejects_bad_shapes_and_a_database_flag() {
    for body in ["not json", "{}", "[1]", r#"[{"transaction_id":5}]"#] {
        let (code, value) = links_refund_rows_stdin(body.as_bytes(), &[]);
        assert_eq!(code, Some(2), "{body}");
        assert_eq!(value["ok"], false);
    }
    let (code, value) = links_refund_rows_stdin(b"[]", &["--db", "x.sqlite"]);
    assert_eq!(code, Some(2));
    assert_eq!(value["error"]["code"], "USAGE_INVALID");
    let (code, value) = links_refund_rows_stdin(b"[]", &[]);
    assert_eq!(code, Some(0));
    assert_eq!(value["ok"], true);
}

#[test]
fn links_command_rejects_unknown_kind_and_a_missing_database() {
    // `links ota` reads stdin without flags (INPUT_INVALID since #921); its usage errors are in links_ota_cli.rs.
    for args in [vec!["links"], vec!["links", "refund"]] {
        let out = Command::new(env!("CARGO_BIN_EXE_costcore"))
            .args(args)
            .stdin(Stdio::null())
            .output()
            .unwrap();
        assert_eq!(out.status.code(), Some(2));
        assert!(
            String::from_utf8(out.stdout)
                .unwrap()
                .contains("USAGE_INVALID")
        );
    }
}
