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

#[test]
fn links_command_rejects_unknown_kind_and_a_missing_database() {
    // `links ota` is a real command (#921): no input is INPUT_INVALID, never a usage error.
    let out = Command::new(env!("CARGO_BIN_EXE_costcore"))
        .args(["links", "ota"])
        .stdin(Stdio::null())
        .output()
        .unwrap();
    assert!(
        String::from_utf8(out.stdout)
            .unwrap()
            .contains("INPUT_INVALID")
    );
    for args in [vec!["links", "foo"], vec!["links"], vec!["links", "refund"]] {
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
