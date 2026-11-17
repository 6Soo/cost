use std::path::PathBuf;
use std::sync::atomic::{AtomicU32, Ordering};
use std::sync::{Arc, Barrier};
use std::thread;

use cost_core::jobs::{self, ClaimOptions, EnqueueRequest, FailureKind, JobState, QueueError};
use cost_core::store::schema::MIGRATIONS;
use cost_core::store::{current_version, latest_version, migrate, open_core};
use rusqlite::{Connection, params};
use serde_json::{Value, json};
use time::{OffsetDateTime, Time};

const T0: i64 = 1_800_000_000;

struct TempDb(PathBuf);

impl TempDb {
    fn new() -> Self {
        static NEXT: AtomicU32 = AtomicU32::new(0);
        let path = std::env::temp_dir().join(format!(
            "cost-jobs-test-{}-{}.sqlite",
            std::process::id(),
            NEXT.fetch_add(1, Ordering::SeqCst)
        ));
        Self(path)
    }

    fn path(&self) -> &std::path::Path {
        &self.0
    }
}

impl Drop for TempDb {
    fn drop(&mut self) {
        for suffix in ["", "-journal", "-wal", "-shm"] {
            let mut path = self.0.as_os_str().to_owned();
            path.push(suffix);
            let _ = std::fs::remove_file(path);
        }
    }
}

fn memory_db() -> Connection {
    let mut conn = Connection::open_in_memory().unwrap();
    migrate(&mut conn).unwrap();
    conn
}

fn request(kind: &str, key: &str, budget: Option<&str>, payload: Value) -> EnqueueRequest {
    EnqueueRequest {
        kind: kind.to_owned(),
        dedupe_key: key.to_owned(),
        budget_key: budget.map(str::to_owned),
        payload,
    }
}

fn options(owner: &str) -> ClaimOptions {
    ClaimOptions {
        owner: owner.to_owned(),
        lease_seconds: 30,
        daily_budget_limit: 30,
        kinds: None,
    }
}

fn next_day_start(now: i64) -> i64 {
    let date = OffsetDateTime::from_unix_timestamp(now)
        .unwrap()
        .date()
        .next_day()
        .unwrap();
    date.with_time(Time::MIDNIGHT).assume_utc().unix_timestamp()
}

#[test]
fn concurrent_connections_never_receive_the_same_active_lease() {
    let db = TempDb::new();
    let setup = open_core(db.path()).unwrap();
    jobs::enqueue(
        &setup,
        request("p2", "once-1", Some("shared-model"), json!({"value": 1})),
    )
    .unwrap();
    jobs::enqueue(
        &setup,
        request("p2", "once-2", Some("shared-model"), json!({"value": 2})),
    )
    .unwrap();
    drop(setup);

    let barrier = Arc::new(Barrier::new(2));
    let workers = (0..2)
        .map(|worker| {
            let path = db.path().to_owned();
            let barrier = Arc::clone(&barrier);
            thread::spawn(move || {
                let mut conn = open_core(&path).unwrap();
                barrier.wait();
                let mut claim_options = options(&format!("worker-{worker}"));
                claim_options.daily_budget_limit = 1;
                jobs::claim(&mut conn, claim_options, T0).unwrap()
            })
        })
        .collect::<Vec<_>>();
    let claimed = workers
        .into_iter()
        .map(|worker| worker.join().unwrap())
        .filter(Option::is_some)
        .count();
    assert_eq!(claimed, 1);

    let conn = open_core(db.path()).unwrap();
    let used: i64 = conn
        .query_row(
            "SELECT used_units FROM budgets WHERE day=?1 AND scope='shared-model'",
            [OffsetDateTime::from_unix_timestamp(T0)
                .unwrap()
                .date()
                .to_string()],
            |row| row.get(0),
        )
        .unwrap();
    assert_eq!(
        used, 1,
        "동시 claim은 동일 일일 예산을 한 번만 예약해야 한다"
    );
    let states: (i64, i64) = conn
        .query_row(
            "SELECT sum(state='leased'),sum(state='queued') FROM jobs",
            [],
            |row| Ok((row.get(0)?, row.get(1)?)),
        )
        .unwrap();
    assert_eq!(states, (1, 1));
}

#[test]
fn expired_lease_fences_old_tokens_and_heartbeat_extends_current_lease() {
    let mut conn = memory_db();
    let id = jobs::enqueue(&conn, request("p1", "fence", None, json!({"x": true}))).unwrap();
    let first = jobs::claim(&mut conn, options("worker"), T0)
        .unwrap()
        .unwrap();
    assert_eq!(first.token.job_id(), id);
    assert_eq!(first.lease_until, T0 + 30);

    assert_eq!(
        jobs::heartbeat(&conn, &first.token, 60, T0 + 10).unwrap(),
        T0 + 70
    );
    assert_eq!(
        jobs::heartbeat(&conn, &first.token, 60, T0 + 70),
        Err(QueueError::LeaseLost)
    );

    // Expiry recovery waits 30 seconds after the first attempt before another claim.
    let recovered_at = T0 + 100;
    assert_eq!(
        jobs::claim(&mut conn, options("worker"), recovered_at).unwrap(),
        None
    );
    let second_at = T0 + 130;
    let second = jobs::claim(&mut conn, options("worker"), second_at)
        .unwrap()
        .unwrap();
    assert_eq!(second.token.generation(), first.token.generation() + 1);
    assert_eq!(
        jobs::complete(&conn, &first.token, json!({"stale": true}), second_at),
        Err(QueueError::LeaseLost)
    );
    assert_eq!(
        jobs::heartbeat(&conn, &second.token, 10, second_at).unwrap(),
        second_at + 10
    );
    assert_eq!(jobs::status(&conn, id).unwrap().attempts, 2);
}

#[test]
fn expired_attempts_are_delayed_and_dead_after_the_third_lease() {
    let mut conn = memory_db();
    let id = jobs::enqueue(&conn, request("p1", "expire-three", None, json!({}))).unwrap();

    let first = jobs::claim(&mut conn, options("worker"), T0)
        .unwrap()
        .unwrap();
    assert_eq!(
        jobs::claim(&mut conn, options("worker"), T0 + 30).unwrap(),
        None
    );
    let second_at = T0 + 60;
    let second = jobs::claim(&mut conn, options("worker"), second_at)
        .unwrap()
        .unwrap();
    assert_eq!(second.attempts, 2);
    assert_eq!(
        jobs::claim(&mut conn, options("worker"), second_at + 30).unwrap(),
        None
    );
    let third_at = second_at + 90;
    let third = jobs::claim(&mut conn, options("worker"), third_at)
        .unwrap()
        .unwrap();
    assert_eq!(third.attempts, 3);
    assert_eq!(
        jobs::claim(&mut conn, options("worker"), third_at + 30).unwrap(),
        None
    );
    assert_eq!(jobs::status(&conn, id).unwrap().state, JobState::Dead);
    assert_eq!(
        jobs::complete(&conn, &first.token, json!({}), third_at + 30),
        Err(QueueError::LeaseLost)
    );
}

#[test]
fn lease_and_budget_survive_restart_and_old_tokens_are_fenced_after_reclaim() {
    let db = TempDb::new();
    let setup = open_core(db.path()).unwrap();
    let id = jobs::enqueue(
        &setup,
        request("p2", "restart", Some("model"), json!({"synthetic": true})),
    )
    .unwrap();
    drop(setup);

    let mut before_restart = open_core(db.path()).unwrap();
    let mut claim_options = options("node-before-restart");
    claim_options.daily_budget_limit = 2;
    let first = jobs::claim(&mut before_restart, claim_options, T0)
        .unwrap()
        .unwrap();
    drop(before_restart);

    let mut after_restart = open_core(db.path()).unwrap();
    let persisted = jobs::status(&after_restart, id).unwrap();
    assert_eq!(persisted.state, JobState::Leased);
    assert_eq!(persisted.attempts, 1);
    let mut claim_options = options("node-after-restart");
    claim_options.daily_budget_limit = 2;
    assert_eq!(
        jobs::claim(&mut after_restart, claim_options, T0 + 29).unwrap(),
        None
    );

    // 만료 시각 포함 같은 시각부터 구 토큰은 heartbeat할 수 없다.
    assert_eq!(
        jobs::heartbeat(&after_restart, &first.token, 30, T0 + 30),
        Err(QueueError::LeaseLost)
    );
    let mut claim_options = options("node-after-restart");
    claim_options.daily_budget_limit = 2;
    assert_eq!(
        jobs::claim(&mut after_restart, claim_options, T0 + 30).unwrap(),
        None
    );

    let mut claim_options = options("node-after-restart");
    claim_options.daily_budget_limit = 2;
    let second = jobs::claim(&mut after_restart, claim_options, T0 + 60)
        .unwrap()
        .unwrap();
    assert_eq!(second.token.generation(), first.token.generation() + 1);
    assert_eq!(
        jobs::complete(
            &after_restart,
            &first.token,
            json!({"stale": true}),
            T0 + 60
        ),
        Err(QueueError::LeaseLost)
    );
    assert_eq!(
        jobs::heartbeat(&after_restart, &first.token, 30, T0 + 60),
        Err(QueueError::LeaseLost)
    );
    let used: i64 = after_restart
        .query_row(
            "SELECT used_units FROM budgets WHERE scope='model'",
            [],
            |row| row.get(0),
        )
        .unwrap();
    assert_eq!(used, 2, "재시작·임대 회수 중 예산 예약은 유지돼야 한다");
}

#[test]
fn daily_budgets_count_failed_calls_reset_by_utc_day_and_are_scoped() {
    let mut conn = memory_db();
    jobs::enqueue(
        &conn,
        request("p2", "alpha-1", Some("alpha"), json!({"a": 1})),
    )
    .unwrap();
    jobs::enqueue(
        &conn,
        request("p2", "alpha-2", Some("alpha"), json!({"a": 2})),
    )
    .unwrap();
    jobs::enqueue(
        &conn,
        request("p2", "beta-1", Some("beta"), json!({"b": 1})),
    )
    .unwrap();
    let p1_id = jobs::enqueue(&conn, request("p1", "p1-job", None, json!({"p1": true}))).unwrap();

    let mut limited = options("p2-worker");
    limited.daily_budget_limit = 1;
    limited.kinds = Some(vec!["p2".to_owned()]);
    let alpha = jobs::claim(&mut conn, limited, T0).unwrap().unwrap();
    assert_eq!(alpha.budget_key.as_deref(), Some("alpha"));
    assert_eq!(
        jobs::fail(&conn, &alpha.token, FailureKind::Authentication, T0 + 1).unwrap(),
        JobState::Dead
    );

    let mut limited = options("p2-worker");
    limited.daily_budget_limit = 1;
    limited.kinds = Some(vec!["p2".to_owned()]);
    let beta = jobs::claim(&mut conn, limited, T0 + 2).unwrap().unwrap();
    assert_eq!(beta.budget_key.as_deref(), Some("beta"));
    assert_eq!(
        jobs::fail(&conn, &beta.token, FailureKind::Tool, T0 + 3).unwrap(),
        JobState::Dead
    );

    let mut limited = options("p2-worker");
    limited.daily_budget_limit = 1;
    limited.kinds = Some(vec!["p2".to_owned()]);
    assert_eq!(jobs::claim(&mut conn, limited, T0 + 4).unwrap(), None);

    // P1 uses an explicit kind filter and remains claimable after both P2 scopes are exhausted.
    let mut p1_only = options("p1-worker");
    p1_only.daily_budget_limit = 0;
    let p1 = jobs::claim(&mut conn, p1_only, T0 + 5).unwrap().unwrap();
    assert_eq!(p1.token.job_id(), p1_id);
    jobs::fail(&conn, &p1.token, FailureKind::Tool, T0 + 6).unwrap();

    let next_day = next_day_start(T0);
    let mut limited = options("p2-worker");
    limited.daily_budget_limit = 1;
    limited.kinds = Some(vec!["p2".to_owned()]);
    let next_day_job = jobs::claim(&mut conn, limited, next_day).unwrap().unwrap();
    assert_eq!(next_day_job.budget_key.as_deref(), Some("alpha"));

    let day_one = OffsetDateTime::from_unix_timestamp(T0)
        .unwrap()
        .date()
        .to_string();
    let used: i64 = conn
        .query_row(
            "SELECT used_units FROM budgets WHERE day=?1 AND scope='alpha'",
            [day_one],
            |row| row.get(0),
        )
        .unwrap();
    assert_eq!(used, 1);
}

#[test]
fn dedupe_is_idempotent_but_rejects_kind_payload_or_budget_changes() {
    let conn = memory_db();
    let first = jobs::enqueue(
        &conn,
        request("p2", "same", Some("scope"), json!({"a": 1, "b": [2]})),
    )
    .unwrap();
    let repeated = jobs::enqueue(
        &conn,
        request("p2", "same", Some("scope"), json!({"b": [2], "a": 1})),
    )
    .unwrap();
    assert_eq!(repeated, first);
    assert_eq!(
        jobs::enqueue(
            &conn,
            request("p1", "same", Some("scope"), json!({"a": 1, "b": [2]}))
        ),
        Err(QueueError::DedupeConflict)
    );
    assert_eq!(
        jobs::enqueue(&conn, request("p2", "same", Some("scope"), json!({"a": 9}))),
        Err(QueueError::DedupeConflict)
    );
    assert_eq!(
        jobs::enqueue(
            &conn,
            request("p2", "same", Some("other"), json!({"a": 1, "b": [2]}))
        ),
        Err(QueueError::DedupeConflict)
    );
    let count: i64 = conn
        .query_row("SELECT count(*) FROM jobs", [], |row| row.get(0))
        .unwrap();
    assert_eq!(count, 1);
}

#[test]
fn transient_failures_use_30_and_60_second_delays_then_dead() {
    let mut conn = memory_db();
    let id = jobs::enqueue(
        &conn,
        request("p1", "retry", None, json!({"safe": "payload"})),
    )
    .unwrap();

    let first = jobs::claim(&mut conn, options("worker"), T0)
        .unwrap()
        .unwrap();
    assert_eq!(
        jobs::fail(&conn, &first.token, FailureKind::Transient, T0 + 1).unwrap(),
        JobState::Queued
    );
    assert_eq!(
        jobs::claim(&mut conn, options("worker"), T0 + 30).unwrap(),
        None
    );

    let second_at = T0 + 31;
    let second = jobs::claim(&mut conn, options("worker"), second_at)
        .unwrap()
        .unwrap();
    assert_eq!(second.attempts, 2);
    assert_eq!(
        jobs::fail(&conn, &second.token, FailureKind::Transient, second_at + 1).unwrap(),
        JobState::Queued
    );
    assert_eq!(
        jobs::claim(&mut conn, options("worker"), second_at + 60).unwrap(),
        None
    );

    let third_at = second_at + 61;
    let third = jobs::claim(&mut conn, options("worker"), third_at)
        .unwrap()
        .unwrap();
    assert_eq!(third.attempts, 3);
    assert_eq!(
        jobs::fail(&conn, &third.token, FailureKind::Transient, third_at + 1).unwrap(),
        JobState::Dead
    );
    assert_eq!(jobs::status(&conn, id).unwrap().state, JobState::Dead);
}

#[test]
fn capacity_retry_sets_the_caller_provided_next_allowed_time() {
    let mut conn = memory_db();
    jobs::enqueue(&conn, request("p2", "capacity", Some("p2"), json!({}))).unwrap();
    let mut claim_options = options("worker");
    claim_options.daily_budget_limit = 3;
    let first = jobs::claim(&mut conn, claim_options, T0).unwrap().unwrap();
    jobs::fail(
        &conn,
        &first.token,
        FailureKind::Capacity {
            not_before: T0 + 600,
        },
        T0 + 1,
    )
    .unwrap();

    let mut claim_options = options("worker");
    claim_options.daily_budget_limit = 3;
    assert_eq!(
        jobs::claim(&mut conn, claim_options, T0 + 599).unwrap(),
        None
    );
    let mut claim_options = options("worker");
    claim_options.daily_budget_limit = 3;
    let second = jobs::claim(&mut conn, claim_options, T0 + 600)
        .unwrap()
        .unwrap();
    assert_eq!(second.attempts, 2);
}

#[test]
fn text_epoch_columns_compare_numbers_and_parse_legacy_iso_times() {
    let mut conn = memory_db();
    let iso_id = jobs::enqueue(&conn, request("p1", "not-before-iso", None, json!({}))).unwrap();
    let numeric_id =
        jobs::enqueue(&conn, request("p1", "not-before-999", None, json!({}))).unwrap();
    jobs::enqueue(&conn, request("p1", "not-before-1000", None, json!({}))).unwrap();
    conn.execute(
        "UPDATE jobs SET not_before='1970-01-01 00:16:38' WHERE job_id=?1",
        [iso_id],
    )
    .unwrap();
    conn.execute(
        "UPDATE jobs SET not_before='999' WHERE job_id=?1",
        [numeric_id],
    )
    .unwrap();
    conn.execute(
        "UPDATE jobs SET not_before='1000' WHERE dedupe_key='not-before-1000'",
        [],
    )
    .unwrap();

    let first = jobs::claim(&mut conn, options("worker"), 1_000)
        .unwrap()
        .unwrap();
    assert_eq!(first.token.job_id(), iso_id);
    let second = jobs::claim(&mut conn, options("worker"), 1_000)
        .unwrap()
        .unwrap();
    assert_eq!(second.token.job_id(), numeric_id);
    let third = jobs::claim(&mut conn, options("worker"), 1_000)
        .unwrap()
        .unwrap();
    assert_eq!(third.dedupe_key, "not-before-1000");

    let lease_id = jobs::enqueue(&conn, request("p1", "legacy-lease", None, json!({}))).unwrap();
    let mut short = options("worker");
    short.lease_seconds = 100;
    let lease = jobs::claim(&mut conn, short, 900).unwrap().unwrap();
    assert_eq!(lease.token.job_id(), lease_id);
    conn.execute(
        "UPDATE jobs SET lease_until='1970-01-01T00:16:40Z' WHERE job_id=?1",
        [lease_id],
    )
    .unwrap();
    assert_eq!(
        jobs::claim(&mut conn, options("worker"), 999).unwrap(),
        None
    );
    assert_eq!(
        jobs::claim(&mut conn, options("worker"), 1_000).unwrap(),
        None
    );
    let recovered = jobs::claim(&mut conn, options("worker"), 1_030)
        .unwrap()
        .unwrap();
    assert_eq!(recovered.token.job_id(), lease_id);
    assert_eq!(recovered.attempts, 2);
}

#[test]
fn permanent_failure_uses_failed_state_and_invalid_limits_are_rejected() {
    let mut conn = memory_db();
    let id = jobs::enqueue(&conn, request("p1", "permanent", None, json!({}))).unwrap();
    let lease = jobs::claim(&mut conn, options("worker"), T0)
        .unwrap()
        .unwrap();
    assert_eq!(
        jobs::fail(&conn, &lease.token, FailureKind::Permanent, T0 + 1).unwrap(),
        JobState::Failed
    );
    assert_eq!(jobs::status(&conn, id).unwrap().state, JobState::Failed);

    let mut invalid = options("worker");
    invalid.lease_seconds = 0;
    assert_eq!(
        jobs::claim(&mut conn, invalid, T0),
        Err(QueueError::InvalidInput)
    );
    let mut invalid = options("worker");
    invalid.lease_seconds = jobs::MAX_LEASE_SECONDS + 1;
    assert_eq!(
        jobs::claim(&mut conn, invalid, T0),
        Err(QueueError::InvalidInput)
    );
    let mut invalid = options("worker");
    invalid.daily_budget_limit = jobs::MAX_DAILY_BUDGET_LIMIT + 1;
    assert_eq!(
        jobs::claim(&mut conn, invalid, T0),
        Err(QueueError::InvalidInput)
    );
}

#[test]
fn debug_output_redacts_payload_and_completion_result_is_readable_by_status() {
    let mut conn = memory_db();
    let secret = "customer-original-text";
    let id = jobs::enqueue(&conn, request("p1", "redact", None, json!({"raw": secret}))).unwrap();
    let lease = jobs::claim(&mut conn, options("worker"), T0)
        .unwrap()
        .unwrap();
    assert!(!format!("{lease:?}").contains(secret));
    assert!(format!("{lease:?}").contains("[REDACTED]"));
    let wire_lease = serde_json::to_value(&lease).unwrap();
    assert_eq!(wire_lease["token"]["owner"], "worker");
    assert_eq!(wire_lease["payload"]["raw"], secret);
    jobs::complete(&conn, &lease.token, json!({"decision": "accepted"}), T0 + 1).unwrap();
    // 완료 응답이 유실돼 같은 요청이 재전송된 경우 성공 결과를 확인할 수 있다.
    jobs::complete(&conn, &lease.token, json!({"decision": "accepted"}), T0 + 2).unwrap();
    assert_eq!(
        jobs::complete(&conn, &lease.token, json!({"decision": "changed"}), T0 + 2),
        Err(QueueError::LeaseLost)
    );
    let status = jobs::status(&conn, id).unwrap();
    assert_eq!(status.state, JobState::Succeeded);
    assert_eq!(status.result, Some(json!({"decision": "accepted"})));
    let wire_status = serde_json::to_value(&status).unwrap();
    assert_eq!(wire_status["state"], "succeeded");
    assert_eq!(wire_status["result"]["decision"], "accepted");
}

#[test]
fn lease_token_wire_round_trip_validates_fields_and_does_not_grant_a_lease() {
    let token = jobs::LeaseToken::from_parts(1, "worker", 2).unwrap();
    let wire = serde_json::to_value(&token).unwrap();
    assert_eq!(
        wire,
        json!({"job_id": 1, "owner": "worker", "generation": 2})
    );
    let decoded: jobs::LeaseToken = serde_json::from_value(wire).unwrap();
    assert_eq!(decoded, token);
    assert_eq!(
        serde_json::from_value::<jobs::LeaseToken>(json!({
            "job_id": 1,
            "owner": "worker",
            "generation": 0
        }))
        .unwrap_err()
        .to_string(),
        "invalid_input"
    );
    assert_eq!(
        jobs::LeaseToken::from_parts(0, "worker", 1),
        Err(QueueError::InvalidInput)
    );

    let conn = memory_db();
    assert_eq!(
        jobs::heartbeat(&conn, &decoded, 30, T0),
        Err(QueueError::LeaseLost),
        "wire token construction alone must not authorize queue mutation"
    );
}

#[test]
fn claim_budget_reservation_rolls_back_when_job_lease_update_fails() {
    let mut conn = memory_db();
    jobs::enqueue(&conn, request("p2", "rollback", Some("p2"), json!({}))).unwrap();
    conn.execute_batch(
        "CREATE TRIGGER force_lease_failure BEFORE UPDATE OF state ON jobs
         WHEN NEW.state='leased' BEGIN SELECT RAISE(ABORT,'synthetic rollback'); END;",
    )
    .unwrap();

    let error = jobs::claim(&mut conn, options("worker"), T0).unwrap_err();
    assert_eq!(error, QueueError::Storage);
    let state: String = conn
        .query_row("SELECT state FROM jobs", [], |row| row.get(0))
        .unwrap();
    assert_eq!(state, "queued");
    let budgets: i64 = conn
        .query_row("SELECT count(*) FROM budgets", [], |row| row.get(0))
        .unwrap();
    assert_eq!(budgets, 0, "예산 예약은 job 임대 실패와 함께 롤백돼야 한다");
}

fn v2_connection() -> Connection {
    let mut conn = Connection::open_in_memory().unwrap();
    conn.execute_batch(
        "CREATE TABLE schema_meta (version INTEGER PRIMARY KEY, name TEXT NOT NULL,
         applied_at TEXT NOT NULL DEFAULT 'synthetic');",
    )
    .unwrap();
    for migration in &MIGRATIONS[..2] {
        let tx = conn.transaction().unwrap();
        tx.execute_batch(migration.sql).unwrap();
        tx.execute(
            "INSERT INTO schema_meta(version,name) VALUES (?1,?2)",
            params![migration.version, migration.name],
        )
        .unwrap();
        tx.commit().unwrap();
    }
    conn
}

#[test]
fn v3_is_additive_and_preserves_existing_decision_and_financial_links() {
    let mut conn = v2_connection();
    conn.execute(
        "INSERT INTO jobs(kind,dedupe_key,state,lease_owner,lease_until,attempts,not_before,payload_json)
         VALUES ('p2','pre-v3','queued','','',1,'','{\"kept\":true}')",
        [],
    )
    .unwrap();
    conn.execute(
        "INSERT INTO budgets(day,scope,limit_units,used_units)
         VALUES ('2026-11-17','model',30,4)",
        [],
    )
    .unwrap();
    conn.execute_batch(
        "INSERT INTO evidence(evidence_id,kind,sha256,locator)
         VALUES (1,'manual','aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa','synthetic');
         INSERT INTO facts(fact_id,snapshot_digest,subject,fact_kind,value_json,evidence_id,producer)
         VALUES (1,'snap','tx-1','amount_basis','{\"amount\":1200}',1,'test');
         INSERT INTO links(link_id,snapshot_digest,producer,link_kind,exactness,basis,status,left_ref,right_ref)
         VALUES (1,'snap','rust','refund_number','exact','same approval','full','tx-1','tx-2');
         INSERT INTO refund_groups(group_id,snapshot_digest,original_txn_id,member_txn_ids_json,net_krw,status)
         VALUES ('refund-1','snap','tx-1','[\"tx-1\",\"tx-2\"]',0,'full');
         INSERT INTO decisions(transaction_id,source_hash,revision,actor_kind,attribution,item,description,basis,decided_at)
         VALUES ('tx-1','hash',1,'manual','owner','교통','합성 설명','합성 근거','2026-11-01T00:00:00Z');
         INSERT INTO decision_history(history_id,transaction_id,before_json,after_json,actor_kind,request_id,at)
         VALUES (1,'tx-1','{\"item\":\"식비\"}','{\"item\":\"교통\"}','manual','req-1','2026-11-01T00:00:00Z');",
    )
    .unwrap();
    let before_decision: (String, i64, String, String) = conn
        .query_row(
            "SELECT transaction_id,revision,item,basis FROM decisions WHERE transaction_id='tx-1'",
            [],
            |row| Ok((row.get(0)?, row.get(1)?, row.get(2)?, row.get(3)?)),
        )
        .unwrap();
    let before_history: (String, String, String) = conn
        .query_row(
            "SELECT transaction_id,before_json,after_json FROM decision_history WHERE history_id=1",
            [],
            |row| Ok((row.get(0)?, row.get(1)?, row.get(2)?)),
        )
        .unwrap();
    let before_fact: String = conn
        .query_row("SELECT value_json FROM facts WHERE fact_id=1", [], |row| {
            row.get(0)
        })
        .unwrap();
    let before_group: (String, i64) = conn
        .query_row(
            "SELECT member_txn_ids_json,net_krw FROM refund_groups WHERE group_id='refund-1'",
            [],
            |row| Ok((row.get(0)?, row.get(1)?)),
        )
        .unwrap();

    assert_eq!(current_version(&conn).unwrap(), 2);
    assert_eq!(migrate(&mut conn).unwrap(), 3);
    assert_eq!(latest_version(), 3);
    assert_eq!(
        conn.query_row(
            "SELECT transaction_id,revision,item,basis FROM decisions WHERE transaction_id='tx-1'",
            [],
            |row| Ok((row.get(0)?, row.get(1)?, row.get(2)?, row.get(3)?)),
        )
        .unwrap(),
        before_decision
    );
    assert_eq!(
        conn.query_row(
            "SELECT transaction_id,before_json,after_json FROM decision_history WHERE history_id=1",
            [],
            |row| Ok((row.get(0)?, row.get(1)?, row.get(2)?)),
        )
        .unwrap(),
        before_history
    );
    assert_eq!(
        conn.query_row("SELECT value_json FROM facts WHERE fact_id=1", [], |row| {
            row.get::<_, String>(0)
        })
        .unwrap(),
        before_fact
    );
    assert_eq!(
        conn.query_row(
            "SELECT member_txn_ids_json,net_krw FROM refund_groups WHERE group_id='refund-1'",
            [],
            |row| Ok((row.get::<_, String>(0)?, row.get::<_, i64>(1)?)),
        )
        .unwrap(),
        before_group
    );
    assert_eq!(
        conn.query_row(
            "SELECT budget_key,lease_generation,result_json FROM jobs WHERE dedupe_key='pre-v3'",
            [],
            |row| Ok((
                row.get::<_, String>(0)?,
                row.get::<_, i64>(1)?,
                row.get::<_, String>(2)?
            )),
        )
        .unwrap(),
        (String::new(), 0, String::new())
    );
    assert_eq!(
        conn.query_row(
            "SELECT limit_units,used_units FROM budgets WHERE day='2026-11-17' AND scope='model'",
            [],
            |row| Ok((row.get::<_, i64>(0)?, row.get::<_, i64>(1)?)),
        )
        .unwrap(),
        (30, 4)
    );

    let invalid_state = conn.execute(
        "INSERT INTO jobs(kind,dedupe_key,state) VALUES ('p1','invalid','waiting')",
        [],
    );
    assert!(invalid_state.is_err());
}

#[test]
fn failed_v3_migration_rolls_back_its_added_columns() {
    let mut conn = v2_connection();
    conn.execute_batch(
        "CREATE TRIGGER jobs_state_valid_insert BEFORE INSERT ON jobs BEGIN SELECT 1; END;",
    )
    .unwrap();
    assert!(migrate(&mut conn).is_err());
    assert_eq!(current_version(&conn).unwrap(), 2);
    let columns = conn
        .prepare("PRAGMA table_info(jobs)")
        .unwrap()
        .query_map([], |row| row.get::<_, String>(1))
        .unwrap()
        .map(Result::unwrap)
        .collect::<Vec<_>>();
    assert!(!columns.contains(&"budget_key".to_owned()));
    assert!(!columns.contains(&"lease_generation".to_owned()));
    assert!(!columns.contains(&"result_json".to_owned()));
}
