//! `costcore links ota` 끝에서 끝까지: 골든 풀이기 입력을 표준 입력으로 받아 연결 칸이 골든과 같고, 입력 오류는 고정 코드로 끝난다.
//! DB·운영 포트·Python을 쓰지 않는다.

use std::io::Write;
use std::path::{Path, PathBuf};
use std::process::{Command, Stdio};

use serde_json::{Value, json};

fn repo_root() -> PathBuf {
    Path::new(env!("CARGO_MANIFEST_DIR"))
        .join("../../..")
        .canonicalize()
        .unwrap()
}

fn golden(name: &str) -> Vec<Value> {
    std::fs::read_to_string(repo_root().join("core/golden/synthetic").join(name))
        .unwrap()
        .lines()
        .map(|l| serde_json::from_str(l).unwrap())
        .collect()
}

fn links_ota(body: &str, extra: &[&str]) -> (i32, Value) {
    let mut child = Command::new(env!("CARGO_BIN_EXE_costcore"))
        .args(["links", "ota", "--repo-root"])
        .arg(repo_root())
        .args(extra)
        .stdin(Stdio::piped())
        .stdout(Stdio::piped())
        .spawn()
        .unwrap();
    child
        .stdin
        .take()
        .unwrap()
        .write_all(body.as_bytes())
        .unwrap();
    let out = child.wait_with_output().unwrap();
    let line = String::from_utf8(out.stdout).unwrap();
    (
        out.status.code().unwrap(),
        serde_json::from_str(line.lines().next().unwrap()).unwrap(),
    )
}

#[test]
fn every_ota_golden_input_gives_the_golden_link_columns() {
    let (mut cases, mut compared) = (0, 0);
    for case in ["ota_links.jsonl", "ota_mn.jsonl"]
        .iter()
        .flat_map(|n| golden(n))
    {
        let (code, response) = links_ota(&case["input"].to_string(), &[]);
        assert_eq!(
            (code, &response["ok"]),
            (0, &json!(true)),
            "{}",
            case["case_id"]
        );
        let got = response["result"]["results"].as_array().unwrap();
        let want = case["expected"]["results"].as_array().unwrap();
        assert_eq!(got.len(), want.len(), "{}", case["case_id"]);
        for (g, w) in got.iter().zip(want) {
            for (key, value) in g.as_object().unwrap() {
                assert_eq!(value, &w[key], "{} {key}", case["case_id"]);
                compared += 1;
            }
        }
        cases += 1;
    }
    assert_eq!(cases, 55 + 46);
    assert!(compared > 0);
}

#[test]
fn input_errors_end_with_a_fixed_code_and_no_other_text() {
    for (body, code) in [
        ("not json", "INPUT_INVALID"),
        ("[]", "INPUT_INVALID"),
        (r#"{"events":{},"transactions":[]}"#, "INPUT_INVALID"),
        (r#"{"existing_links":[]}"#, "INPUT_INVALID"),
    ] {
        let (status, response) = links_ota(body, &[]);
        assert_eq!(status, 2);
        assert_eq!(response, json!({"ok": false, "error": {"code": code}}));
    }
    let (status, response) = links_ota("{}", &["--bogus", "x"]);
    assert_eq!(status, 2);
    assert_eq!(response["error"]["code"], "USAGE_INVALID");
    let (status, response) = links_ota("{}", &["--input", "no-such-file.json"]);
    assert_eq!(
        (status, &response["error"]["code"]),
        (2, &json!("IO_ERROR"))
    );
}
