//! `costcore queue` 브리지의 합성 계약 검사. 실제 모델·네트워크·운영 DB는 쓰지 않는다.
//!
//! 검수 지적: 큐 단위(`jobs_queue.rs`)만 검증되고 **브리지 경로**(문자열 → `FailureKind`,
//! 시각 변환)는 검사가 없었다. 여기서 보낸 문자열과 돌아온 DB 시각·상태를 직접 대조한다.

use std::path::{Path, PathBuf};
use std::process::{Command, Stdio};

use rusqlite::Connection;
use serde_json::{Value, json};

/// 브리지는 프로세스의 실제 시계를 쓴다. 기대 시각은 테스트가 시작할 때의 UTC 초로 잡는다.
fn now() -> i64 {
    std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .unwrap()
        .as_secs() as i64
}
const BIN: &str = env!("CARGO_BIN_EXE_costcore");

fn scratch(name: &str) -> PathBuf {
    static N: std::sync::atomic::AtomicU32 = std::sync::atomic::AtomicU32::new(0);
    let n = N.fetch_add(1, std::sync::atomic::Ordering::SeqCst);
    let dir =
        std::env::temp_dir().join(format!("costcore-queue-{}-{n}-{name}", std::process::id()));
    let _ = std::fs::remove_dir_all(&dir);
    std::fs::create_dir_all(&dir).unwrap();
    dir
}

fn core(path: &Path) -> PathBuf {
    let file = path.join("core.sqlite");
    let done = Command::new(BIN)
        .args(["migrate", "--core"])
        .arg(&file)
        .output()
        .unwrap();
    assert!(
        done.status.success(),
        "migrate failed: {}",
        String::from_utf8_lossy(&done.stdout)
    );
    file
}

fn queue(core: &Path, body: Value) -> (i32, Value) {
    let mut child = Command::new(BIN)
        .arg("queue")
        .arg("--core")
        .arg(core)
        .stdin(Stdio::piped())
        .stdout(Stdio::piped())
        .stderr(Stdio::piped())
        .spawn()
        .unwrap();
    {
        use std::io::Write;
        child
            .stdin
            .as_mut()
            .unwrap()
            .write_all(body.to_string().as_bytes())
            .unwrap();
    }
    let done = child.wait_with_output().unwrap();
    let code = done.status.code().unwrap_or(-1);
    let text = String::from_utf8_lossy(&done.stdout).to_string();
    let value: Value = serde_json::from_str(text.trim()).unwrap_or_else(|_| {
        panic!(
            "queue bridge did not emit one JSON line: {text:?} stderr={}",
            String::from_utf8_lossy(&done.stderr)
        )
    });
    (code, value)
}

fn ok(core: &Path, body: Value) -> Value {
    let (code, value) = queue(core, body);
    assert_eq!(code, 0, "expected success, got {value}");
    assert_eq!(
        value["ok"],
        json!(true),
        "unexpected error envelope: {value}"
    );
    value["result"].clone()
}

fn rejected(core: &Path, body: Value) -> String {
    let (code, value) = queue(core, body);
    assert_ne!(code, 0, "expected a rejection, got {value}");
    value["error"]["code"]
        .as_str()
        .unwrap_or_default()
        .to_owned()
}

/// 만료 시각을 과거로 돌려 "워커가 결과를 못 쓰고 죽은" 상태를 합성한다.
fn expire_lease(core: &Path, job_id: i64) {
    Connection::open(core)
        .unwrap()
        .execute("UPDATE jobs SET lease_until='1' WHERE job_id=?1", [job_id])
        .unwrap();
}

fn release_delay(core: &Path, job_id: i64) {
    Connection::open(core)
        .unwrap()
        .execute("UPDATE jobs SET not_before='1' WHERE job_id=?1", [job_id])
        .unwrap();
}

fn not_before(core: &Path, job_id: i64) -> i64 {
    let raw: String = Connection::open(core)
        .unwrap()
        .query_row(
            "SELECT not_before FROM jobs WHERE job_id=?1",
            [job_id],
            |row| row.get::<_, String>(0),
        )
        .unwrap();
    // 아직 대기 시각이 없는 행은 ''이며 0으로 본다.
    raw.parse().unwrap_or(0)
}

fn state(core: &Path, job_id: i64) -> String {
    Connection::open(core)
        .unwrap()
        .query_row("SELECT state FROM jobs WHERE job_id=?1", [job_id], |row| {
            row.get(0)
        })
        .unwrap()
}

fn enqueue_p2(core: &Path, key: &str) -> i64 {
    let result = ok(
        core,
        json!({"operation": "enqueue", "kind": "p2_merchant", "dedupe_key": key,
               "budget_key": "p2", "payload": {"synthetic": true}}),
    );
    result["job_id"].as_i64().unwrap()
}

fn claim(core: &Path, owner: &str) -> Value {
    ok(
        core,
        json!({"operation": "claim", "owner": owner, "kinds": ["p2_merchant"],
               "daily_budget_limit": 3, "lease_seconds": 30}),
    )["job"]
        .clone()
}

#[test]
fn bridge_capacity_honors_the_caller_retry_time_instead_of_3600() {
    let dir = scratch("capacity-caller");
    let db = core(&dir);
    let job = enqueue_p2(&db, "cap-caller");
    let lease = claim(&db, "node-a");
    assert_eq!(lease["token"]["job_id"], json!(job));

    let started = now();
    ok(
        &db,
        json!({"operation": "fail", "token": lease["token"],
               "failure": "capacity", "retry_after_seconds": 1800}),
    );

    // 호출자 1,800초가 그대로 반영된다(고정 3,600초가 아니다).
    let delay = not_before(&db, job) - started;
    assert!(
        (1775..=1825).contains(&delay),
        "capacity retry must be ~1800s, got {delay}"
    );
    assert_eq!(state(&db, job), "queued");
}

#[test]
fn bridge_capacity_without_a_time_uses_the_documented_default() {
    let dir = scratch("capacity-default");
    let db = core(&dir);
    let job = enqueue_p2(&db, "cap-default");
    let lease = claim(&db, "node-a");
    let started = now();
    ok(
        &db,
        json!({"operation": "fail", "token": lease["token"], "failure": "capacity"}),
    );
    let delay = not_before(&db, job) - started;
    assert!(
        (3575..=3625).contains(&delay),
        "policy default must be ~3600s, got {delay}"
    );
}

#[test]
fn bridge_capacity_rejects_non_advancing_times_without_silent_substitution() {
    let dir = scratch("capacity-invalid");
    let db = core(&dir);
    let job = enqueue_p2(&db, "cap-invalid");
    let lease = claim(&db, "node-a");

    for seconds in [0, -1, -3600] {
        let code = rejected(
            &db,
            json!({"operation": "fail", "token": lease["token"],
                   "failure": "capacity", "retry_after_seconds": seconds}),
        );
        assert_eq!(code, "retry_time_invalid", "seconds={seconds}");
        // 조용히 3,600으로 대체되지 않는다: 상태·대기 시각이 그대로다.
        assert_eq!(state(&db, job), "leased");
        assert_eq!(not_before(&db, job), 0);
    }
    // 잘못된 형식도 명시 거부다.
    let code = rejected(
        &db,
        json!({"operation": "fail", "token": lease["token"],
               "failure": "capacity", "retry_after_seconds": "1800"}),
    );
    assert_eq!(code, "QUEUE_INPUT_INVALID");
    // 거부 뒤에도 올바른 값으로 다시 통지할 수 있다(임대가 살아 있다).
    ok(
        &db,
        json!({"operation": "fail", "token": lease["token"],
               "failure": "capacity", "retry_after_seconds": 1800}),
    );
    assert_eq!(state(&db, job), "queued");
}

#[test]
fn bridge_transient_retry_matches_the_core_delays() {
    let dir = scratch("transient");
    let db = core(&dir);
    let job = enqueue_p2(&db, "transient-bridge");
    let lease = claim(&db, "node-a");
    let started = now();
    ok(
        &db,
        json!({"operation": "fail", "token": lease["token"], "failure": "transient"}),
    );
    let delay = not_before(&db, job) - started;
    assert!((25..=40).contains(&delay), "first retry ~30s, got {delay}");
    assert_eq!(state(&db, job), "queued");
}

#[test]
fn bridge_dead_ends_authentication_and_tool_failures() {
    let dir = scratch("dead-ends");
    let db = core(&dir);
    for (key, failure) in [("auth-bridge", "authentication"), ("tool-bridge", "tool")] {
        let job = enqueue_p2(&db, key);
        let lease = claim(&db, "node-a");
        assert_eq!(lease["token"]["job_id"], json!(job));
        ok(
            &db,
            json!({"operation": "fail", "token": lease["token"], "failure": failure}),
        );
        assert_eq!(state(&db, job), "dead", "{failure} must not be retried");
    }
}

#[test]
fn bridge_expired_lease_fences_the_old_node_and_recovery_is_bounded() {
    let dir = scratch("fencing");
    let db = core(&dir);
    let job = enqueue_p2(&db, "fence-bridge");
    let lease_a = claim(&db, "node-a");
    expire_lease(&db, job);

    // 만료 뒤 A의 완료·실패·heartbeat는 모두 거부된다(이중 쓰기 차단).
    for body in [
        json!({"operation": "complete", "token": lease_a["token"], "result": {"runner": "replay"}}),
        json!({"operation": "fail", "token": lease_a["token"], "failure": "transient"}),
        json!({"operation": "heartbeat", "token": lease_a["token"], "lease_seconds": 300}),
    ] {
        assert_eq!(rejected(&db, body), "lease_lost");
    }
    assert_eq!(state(&db, job), "leased", "회수는 claim에서만 일어난다");

    // claim이 회수하고 30초 지연을 걸며 generation을 올린다.
    assert!(
        claim(&db, "node-b").is_null(),
        "회수 직후에는 재시도 대기가 있다"
    );
    release_delay(&db, job);
    let lease_b = claim(&db, "node-b");
    assert_eq!(lease_b["token"]["generation"], json!(2));
    assert_eq!(
        rejected(
            &db,
            json!({"operation": "complete", "token": lease_a["token"],
                                    "result": {"runner": "replay"}})
        ),
        "lease_lost"
    );
    ok(
        &db,
        json!({"operation": "complete", "token": lease_b["token"],
               "result": {"runner": "replay", "answer": {"synthetic": true}}}),
    );
    assert_eq!(state(&db, job), "succeeded");
    // 완료된 뒤에도 옛 토큰은 여전히 거부된다.
    assert_eq!(
        rejected(
            &db,
            json!({"operation": "complete", "token": lease_a["token"],
                             "result": {"runner": "replay"}})
        ),
        "lease_lost"
    );
}

#[test]
fn bridge_repeated_identical_completion_is_idempotent_but_a_changed_result_is_not() {
    let dir = scratch("idempotent");
    let db = core(&dir);
    let job = enqueue_p2(&db, "idem-bridge");
    let lease = claim(&db, "node-a");
    let result = json!({"runner": "replay", "answer": {"synthetic": true}});
    ok(
        &db,
        json!({"operation": "complete", "token": lease["token"], "result": result.clone()}),
    );
    // 응답 유실 뒤 같은 요청 재전송: 성공으로 확인된다.
    ok(
        &db,
        json!({"operation": "complete", "token": lease["token"], "result": result.clone()}),
    );
    // 다른 결과는 거부되고 저장 결과는 첫 값 그대로다(이중 결과 금지).
    assert_eq!(
        rejected(
            &db,
            json!({"operation": "complete", "token": lease["token"],
                   "result": {"runner": "replay", "answer": {"synthetic": false}}})
        ),
        "lease_lost"
    );
    let stored: String = Connection::open(&db)
        .unwrap()
        .query_row("SELECT result_json FROM jobs WHERE job_id=?1", [job], |r| {
            r.get(0)
        })
        .unwrap();
    let stored: Value = serde_json::from_str(&stored).unwrap();
    assert_eq!(stored, result);
    assert_eq!(state(&db, job), "succeeded");
}

#[test]
fn bridge_retries_stop_at_the_attempt_limit_and_report_dead() {
    let dir = scratch("attempt-limit");
    let db = core(&dir);
    let job = enqueue_p2(&db, "limit-bridge");

    for attempt in 1..=3 {
        let lease = claim(&db, "node-a");
        assert_eq!(lease["attempts"], json!(attempt));
        let end = if attempt == 3 { "dead" } else { "queued" };
        ok(
            &db,
            json!({"operation": "fail", "token": lease["token"], "failure": "transient"}),
        );
        assert_eq!(state(&db, job), end, "attempt {attempt}");
        if attempt < 3 {
            release_delay(&db, job);
        }
    }
    // 무한 재시도 없음: 4번째 임대가 존재하지 않고 상태는 dead다.
    assert!(
        claim(&db, "node-a").is_null(),
        "dead job must not be claimable"
    );
    assert_eq!(state(&db, job), "dead");
    let attempts: i64 = Connection::open(&db)
        .unwrap()
        .query_row("SELECT attempts FROM jobs WHERE job_id=?1", [job], |r| {
            r.get(0)
        })
        .unwrap();
    assert_eq!(attempts, 3, "attempt counter must stop at MAX_ATTEMPTS");
}

#[test]
fn bridge_p1_stays_claimable_when_the_p2_budget_is_exhausted() {
    let dir = scratch("p1-first");
    let db = core(&dir);
    let payload = json!({"synthetic": true});
    ok(
        &db,
        json!({"operation": "enqueue", "kind": "p2_merchant", "dedupe_key": "budget-a",
               "budget_key": "p2", "payload": payload}),
    );
    ok(
        &db,
        json!({"operation": "enqueue", "kind": "p1_publish", "dedupe_key": "budget-p1",
               "payload": payload}),
    );
    let lease = claim(&db, "node-a");
    ok(
        &db,
        json!({"operation": "fail", "token": lease["token"], "failure": "authentication"}),
    );
    // 예산 소진(1/1) 뒤 P2는 임대 불가지만 P1은 서버 쪽에서 먼저 게시된다.
    assert!(claim(&db, "node-a").is_null(), "P2 budget is exhausted");
    let p1 = ok(
        &db,
        json!({"operation": "claim", "owner": "server-p1", "kinds": ["p1_publish"],
               "daily_budget_limit": 0, "lease_seconds": 300}),
    );
    assert_eq!(p1["job"]["kind"], json!("p1_publish"));
    ok(
        &db,
        json!({"operation": "complete", "token": p1["job"]["token"], "result": {"posted": true}}),
    );
    let status = ok(
        &db,
        json!({"operation": "status", "job_id": p1["job"]["token"]["job_id"]}),
    );
    assert_eq!(status["state"], json!("succeeded"));
}

#[test]
fn bridge_rejects_unknown_operations_and_missing_budget_keys() {
    let dir = scratch("invalid-input");
    let db = core(&dir);
    assert_eq!(
        rejected(&db, json!({"operation": "enqueue"})),
        "QUEUE_INPUT_INVALID"
    );
    assert_eq!(
        rejected(
            &db,
            json!({"operation": "enqueue", "kind": "p2_merchant", "dedupe_key": "no-budget",
                   "payload": {}})
        ),
        "QUEUE_BUDGET_REQUIRED"
    );
    assert_eq!(
        rejected(
            &db,
            json!({"operation": "claim", "owner": "node-a", "kinds": "p2_merchant"})
        ),
        "QUEUE_INPUT_INVALID"
    );
    assert_eq!(
        rejected(
            &db,
            json!({"operation": "fail", "token": {"job_id": 1, "owner": "a",
                                                            "generation": 1}, "failure": "nope"})
        ),
        "QUEUE_INPUT_INVALID"
    );
}

#[test]
fn bridge_refuses_a_database_the_queue_migration_has_not_reached() {
    let dir = scratch("old-schema");
    let db = dir.join("v2.sqlite");
    let conn = Connection::open(&db).unwrap();
    conn.execute_batch(
        "CREATE TABLE schema_meta (version INTEGER PRIMARY KEY, name TEXT NOT NULL,
         applied_at TEXT NOT NULL DEFAULT 'synthetic');
         INSERT INTO schema_meta(version,name) VALUES (1,'v1'),(2,'v2');",
    )
    .unwrap();
    drop(conn);
    let code = rejected(
        &db,
        json!({"operation": "claim", "owner": "node-a", "kinds": ["p2_merchant"]}),
    );
    assert_eq!(code, "CORE_SCHEMA_MISMATCH");
}
