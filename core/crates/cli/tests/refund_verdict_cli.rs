//! `costcore links refund-entries` / `costcore links refund-check`: 환불 판정 봉인을 한 JSON 판으로 노출한다.
//!
//! 입력은 봉인 입력(`rows`·`entries`·`booked`·`authority`)이고 출력은 결정적이다. `entries`는 도출→적용 결과만 돌려주고,
//! `check`는 이번에 직접 기록할 멤버가 있는 검증 묶음만 봉인한다. 외부 ID·중복·모양 파손은 엄격히 거부한다.
//! 합성 자료만 쓰고 DB·네트워크·Python을 쓰지 않는다.

use std::io::Write;
use std::process::{Command, Stdio};

use serde_json::{Value, json};

fn bin(sub: &str) -> Command {
    let mut cmd = Command::new(env!("CARGO_BIN_EXE_costcore"));
    cmd.args(["links"])
        .arg(sub)
        .arg("--repo-root")
        .arg(repo_root());
    cmd
}

fn repo_root() -> std::path::PathBuf {
    std::path::Path::new(env!("CARGO_MANIFEST_DIR"))
        .join("../../..")
        .canonicalize()
        .unwrap()
}

fn verdict(sub: &str, body: &str) -> (i32, Value) {
    let mut child = bin(sub)
        .stdin(Stdio::piped())
        .stdout(Stdio::piped())
        .stderr(Stdio::piped())
        .spawn()
        .expect("costcore 실행");
    child
        .stdin
        .take()
        .unwrap()
        .write_all(body.as_bytes())
        .unwrap();
    let out = child.wait_with_output().unwrap();
    let line = String::from_utf8(out.stdout).unwrap();
    let parsed = line
        .lines()
        .next()
        .and_then(|l| serde_json::from_str(l).ok());
    (
        out.status.code().unwrap_or(-1),
        parsed.unwrap_or(Value::Null),
    )
}

fn verified_pair_rows() -> Value {
    json!([
        {"transaction_id":"syn-v1","issuer":"SYN-BANK","card_tail":"0001","transaction_direction":"purchase",
         "approval_number":"SYN-A-1","original_approval_number":"","amount_krw":10000,
         "approval_date":"2026-10-03","posting_date":"2026-10-05","merchant":"SYN SHOP","merchant_normalized":"SYN SHOP",
         "foreign_amount":"","foreign_currency":"","duplicate_of":null,"conflict_reason":"","parse_error":""},
        {"transaction_id":"syn-v2","issuer":"SYN-BANK","card_tail":"0001","transaction_direction":"cancellation",
         "approval_number":"SYN-X-2","original_approval_number":"SYN-A-1","amount_krw":-10000,
         "approval_date":"2026-10-04","posting_date":"2026-10-06","merchant":"SYN SHOP","merchant_normalized":"SYN SHOP",
         "foreign_amount":"","foreign_currency":"","duplicate_of":null,"conflict_reason":"","parse_error":""}
    ])
}

fn base_request() -> Value {
    json!({
        "rows": verified_pair_rows(),
        "entries": [
            {"id":"syn-v1","item":"식비","display_tab_id":"T-A","trip_id":"T-A","description":"",
             "blocked":null,"already_booked":false,"external":false,"ready":true},
            {"id":"syn-v2","item":"","display_tab_id":"","trip_id":"","description":"",
             "blocked":null,"already_booked":false,"external":false,"ready":true}
        ],
        "booked": [],
        "authority": {"trips":{"T-A":true},"tabs":{"T-A":true,"refunds":true}}
    })
}

#[test]
fn entries_apply_is_stable_and_preserves_request_fields() {
    let (code, out) = verdict("refund-entries", &base_request().to_string());
    assert_eq!(code, 0, "{out}");
    assert_eq!(out["ok"], json!(true), "{out}");
    let entries = out["result"]["entries"].as_array().unwrap();
    assert_eq!(entries.len(), 2, "{out}");
    let by_id = |id: &str| {
        entries
            .iter()
            .find(|e| e["id"] == id)
            .unwrap_or_else(|| panic!("{id} missing: {out}"))
    };
    // 요청 필드 보존 + 귀속·note만 바뀐 결과.
    assert_eq!(by_id("syn-v1")["already_booked"], json!(false), "{out}");
    assert_eq!(by_id("syn-v1")["external"], json!(false), "{out}");
    assert_eq!(by_id("syn-v2")["id"], json!("syn-v2"), "{out}");
    // 전액 상쇄 쌍은 환불 탭, 연결 표시가 붙는다.
    assert_eq!(by_id("syn-v1")["display_tab_id"], json!("refunds"), "{out}");
    assert_eq!(by_id("syn-v2")["display_tab_id"], json!("refunds"), "{out}");
    assert_eq!(
        by_id("syn-v2")["refund_link"]["role"],
        json!("refund"),
        "{out}"
    );
    assert_eq!(
        by_id("syn-v2")["refund_link"]["basis"],
        Value::Null,
        "{out}"
    );
    assert_eq!(by_id("syn-v1")["blocked"], Value::Null, "{out}");
}

#[test]
fn entries_hold_or_pair_a_blocked_member() {
    let mut req = base_request();
    req["entries"][1]["blocked"] = json!({"code":"held_not_unblockable","reason":"synthetic"});
    req["entries"][1]["ready"] = json!(false);
    let (code, out) = verdict("refund-entries", &req.to_string());
    assert_eq!(code, 0, "{out}");
    let entries = out["result"]["entries"].as_array().unwrap();
    assert_eq!(
        entries.iter().find(|e| e["id"] == "syn-v1").unwrap()["blocked"]["code"],
        json!("refund_pair_incomplete"),
        "{out}"
    );
    // 보류 사유는 덮어쓰지 않는다.
    assert_eq!(
        entries.iter().find(|e| e["id"] == "syn-v2").unwrap()["blocked"]["code"],
        json!("held_not_unblockable"),
        "{out}"
    );
    // 검증기 없음(None)은 false와 다르게 `*_unverified`로 남는다.
    let mut req = base_request();
    req["authority"] = Value::Null;
    let (code, out) = verdict("refund-entries", &req.to_string());
    assert_eq!(code, 0, "{out}");
    let entries = out["result"]["entries"].as_array().unwrap();
    // 검증기 없음(None): false(no_longer_valid)와 다른 `*_unverified`.
    assert_eq!(
        entries.iter().find(|e| e["id"] == "syn-v1").unwrap()["blocked"]["code"],
        json!("tab_unverified"),
        "{out}"
    );
    assert_eq!(
        entries.iter().find(|e| e["id"] == "syn-v2").unwrap()["blocked"]["code"],
        json!("tab_unverified"),
        "{out}"
    );
    // 같은 모양이라도 false는 no_longer_valid로 남는다(None과 구분).
    let mut req = base_request();
    req["authority"] = json!({"trips":{"T-A":false},"tabs":{"T-A":false,"refunds":false}});
    let (code, out) = verdict("refund-entries", &req.to_string());
    assert_eq!(code, 0, "{out}");
    let entries = out["result"]["entries"].as_array().unwrap();
    assert_eq!(
        entries.iter().find(|e| e["id"] == "syn-v1").unwrap()["blocked"]["code"],
        json!("tab_no_longer_valid"),
        "{out}"
    );
}

#[test]
fn check_only_seals_recordable_verified_groups() {
    let (code, out) = verdict("refund-check", &base_request().to_string());
    assert_eq!(code, 0, "{out}");
    assert_eq!(out["ok"], json!(true), "{out}");
    let groups = out["result"]["groups"].as_array().unwrap();
    assert_eq!(groups.len(), 1, "{out}");
    assert_eq!(groups[0]["id"], json!("refund:syn-v1"), "{out}");
    let mut members: Vec<&str> = groups[0]["members"]
        .as_array()
        .unwrap()
        .iter()
        .map(|m| m.as_str().unwrap())
        .collect();
    members.sort_unstable();
    assert_eq!(members, vec!["syn-v1", "syn-v2"], "{out}");

    // 이미 기록된 원결제가 entries 밖에 있어도 booked 증거를 보충해 전체 묶음을 봉인한다.
    let mut req = base_request();
    req["booked"] = json!(["syn-v1"]);
    req["entries"] = json!([req["entries"][1].clone()]);
    let (code, out) = verdict("refund-check", &req.to_string());
    assert_eq!(code, 0, "{out}");
    assert_eq!(
        out["result"]["groups"][0]["members"],
        json!(["syn-v1", "syn-v2"]),
        "{out}"
    );

    // 받아들이는 게 반쪽뿐이면 봉인하지 않는다(일부 게시 가능 형태 금지).
    let mut req = base_request();
    req["entries"][1]["blocked"] = json!({"code":"held_not_unblockable","reason":"synthetic"});
    let (code, out) = verdict("refund-check", &req.to_string());
    assert_eq!(code, 2, "{out}");
    assert_eq!(
        out["error"]["code"],
        json!("REFUND_GROUP_INCOMPLETE"),
        "{out}"
    );

    // 이번 판정이 받쳐 주지 않는 묶음은 게시 금지: 실패는 조용한 빈 목록이 아니라 고정 코드다.
    let mut req = base_request();
    req["entries"][1]["blocked"] = json!({"code":"held_not_unblockable","reason":"synthetic"});
    req["entries"][1]["ready"] = json!(false);
    let (status, out) = verdict("refund-check", &req.to_string());
    assert_eq!(status, 2, "{out}");
    assert_eq!(
        out,
        json!({"ok":false,"error":{"code":"REFUND_GROUP_INCOMPLETE"}}),
        "{out}"
    );

    // 이미 기록된 멤버가 있으면 check_groups는 HalfBooked를 건너뛰지만, 다른 멤버의 보류로
    // scope.recordable=false이면 게시 금지다.
    let mut req = base_request();
    req["booked"] = json!(["syn-v1"]);
    req["entries"][0]["already_booked"] = json!(true);
    req["entries"][0]["ready"] = json!(false);
    req["entries"][1]["blocked"] = json!({"code":"held_not_unblockable","reason":"synthetic"});
    req["entries"][1]["ready"] = json!(true);
    let (status, out) = verdict("refund-check", &req.to_string());
    assert_eq!(status, 2, "{out}");
    assert_eq!(
        out,
        json!({"ok":false,"error":{"code":"REFUND_GROUP_INCOMPLETE"}}),
        "{out}"
    );

    // 입력 범위에 없는 구성원은 봉인 거부로 전파된다.
    let mut req = base_request();
    req["entries"] = json!([req["entries"][0].clone()]);
    let (status, out) = verdict("refund-check", &req.to_string());
    assert_eq!(status, 2, "{out}");
    assert_eq!(
        out,
        json!({"ok":false,"error":{"code":"REFUND_GROUP_INCOMPLETE"}}),
        "{out}"
    );

    // 보수적 결번: check_groups가 통과해도 발급 조건(검증 연결)이 무너지면 거부한다.
    let mut req = base_request();
    req["rows"][1]["amount_krw"] = json!(-10001);
    let (status, out) = verdict("refund-check", &req.to_string());
    assert_eq!(status, 2, "{out}");
    assert_eq!(
        out["error"]["code"],
        json!("REFUND_GROUP_INCOMPLETE"),
        "{out}"
    );
}

#[test]
fn verdict_input_is_strict_about_shape() {
    // 본문 자체가 JSON이 아니면 INPUT_INVALID.
    let (status, out) = verdict("refund-entries", "not json");
    assert_eq!(status, 2, "{out}");
    assert_eq!(
        out,
        json!({"ok":false,"error":{"code":"INPUT_INVALID"}}),
        "{out}"
    );
    // 형태 결함(외부 ID·중복·깨진 필드·없는 키)은 REFUND_VERDICT_INVALID.
    let cases = [
        json!({"entries": [], "booked": [], "authority": null}),
        json!({"rows": verified_pair_rows(), "entries": [], "booked": [], "authority": null}),
    ];
    for body in cases {
        let (status, out) = verdict("refund-check", &body.to_string());
        if body.get("rows").is_none() {
            assert_eq!(
                out["error"]["code"],
                json!("REFUND_VERDICT_INVALID"),
                "{out}"
            );
        } else {
            assert_eq!(status, 0, "{out}");
        }
    }
    let foreign = json!({"rows": verified_pair_rows(),
        "entries": [{"id":"zz","blocked":null,"already_booked":false,"external":false,"ready":true}],
        "booked": [], "authority": null});
    let (status, out) = verdict("refund-entries", &foreign.to_string());
    assert_eq!(status, 2, "{out}");
    assert_eq!(
        out,
        json!({"ok":false,"error":{"code":"REFUND_VERDICT_INVALID"}}),
        "{out}"
    );

    let duplicate = json!({"rows": verified_pair_rows(),
        "entries": [
            {"id":"syn-v1","blocked":null,"already_booked":false,"external":false,"ready":true},
            {"id":"syn-v1","blocked":null,"already_booked":false,"external":false,"ready":true}],
        "booked": [], "authority": null});
    let (status, out) = verdict("refund-entries", &duplicate.to_string());
    assert_eq!(status, 2, "{out}");
    assert_eq!(
        out,
        json!({"ok":false,"error":{"code":"REFUND_VERDICT_INVALID"}}),
        "{out}"
    );

    // 알 수 없는 하위 명령은 기존 usage 코드가 그대로다.
    let (status, out) = verdict("bogus-subcommand", "{}");
    assert_eq!(status, 2, "{out}");
    assert_eq!(out["error"]["code"], json!("USAGE_INVALID"), "{out}");
}
