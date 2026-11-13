//! core.sqlite 스키마(설계 §3.2)와 번호 매긴 이관.

use rusqlite::{Connection, OptionalExtension};

use super::error::StoreError;

/// 이관 하나. 번호는 1부터 연속이며, 적용한 이관은 고치지 않고 새 번호를 추가한다.
pub struct Migration {
    pub version: u32,
    pub name: &'static str,
    pub sql: &'static str,
}

const V1: &str = "
CREATE TABLE evidence (
    evidence_id INTEGER PRIMARY KEY,
    kind TEXT NOT NULL CHECK (kind IN ('import_batch_row','ota_evidence','receipt','manual')),
    sha256 TEXT NOT NULL CHECK (length(sha256) = 64),
    locator TEXT NOT NULL,
    UNIQUE (kind, sha256, locator)
);
CREATE TABLE facts (
    fact_id INTEGER PRIMARY KEY,
    snapshot_digest TEXT NOT NULL,
    subject TEXT NOT NULL,
    fact_kind TEXT NOT NULL,
    value_json TEXT NOT NULL,
    evidence_id INTEGER REFERENCES evidence(evidence_id),
    producer TEXT NOT NULL,
    python_sha TEXT NOT NULL DEFAULT ''
);
CREATE INDEX facts_subject ON facts(snapshot_digest, subject);
CREATE TABLE links (
    link_id INTEGER PRIMARY KEY,
    snapshot_digest TEXT NOT NULL,
    producer TEXT NOT NULL CHECK (producer IN ('rust','python')),
    link_kind TEXT NOT NULL CHECK (link_kind IN
        ('refund_number','refund_foreign','refund_amount_inferred',
         'ota_exact','ota_mn_group','ota_undated_inferred')),
    exactness TEXT NOT NULL CHECK (exactness IN ('exact','inferred')),
    basis TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('full','partial','excess')),
    component_id TEXT NOT NULL DEFAULT '',
    left_ref TEXT NOT NULL,
    right_ref TEXT NOT NULL,
    rule_version TEXT NOT NULL DEFAULT ''
);
CREATE INDEX links_snapshot ON links(snapshot_digest, producer);
CREATE TABLE refund_groups (
    group_id TEXT PRIMARY KEY,
    snapshot_digest TEXT NOT NULL,
    original_txn_id TEXT NOT NULL,
    member_txn_ids_json TEXT NOT NULL,
    net_krw INTEGER NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('full','partial','excess')),
    cross_file INTEGER NOT NULL DEFAULT 0 CHECK (cross_file IN (0,1)),
    hold_reason TEXT NOT NULL DEFAULT ''
);
CREATE TABLE trips (
    snapshot_digest TEXT NOT NULL,
    tab_id TEXT NOT NULL,
    read_at TEXT NOT NULL,
    digest TEXT NOT NULL,
    PRIMARY KEY (snapshot_digest, tab_id)
);
CREATE TABLE decisions (
    transaction_id TEXT PRIMARY KEY,
    source_hash TEXT NOT NULL,
    revision INTEGER NOT NULL,
    actor_kind TEXT NOT NULL CHECK (actor_kind IN
        ('manual','p1_exact','ai_review','p2','p1_inferred')),
    actor_ref TEXT NOT NULL DEFAULT '',
    attribution TEXT NOT NULL,
    item TEXT NOT NULL,
    description TEXT NOT NULL,
    service_period_json TEXT NOT NULL DEFAULT '{}',
    basis TEXT NOT NULL,
    uncertainty_json TEXT NOT NULL DEFAULT '[]',
    policy_refs_json TEXT NOT NULL DEFAULT '[]',
    evidence_ids_json TEXT NOT NULL DEFAULT '[]',
    decided_at TEXT NOT NULL
);
CREATE TABLE decision_history (
    history_id INTEGER PRIMARY KEY,
    transaction_id TEXT NOT NULL,
    before_json TEXT NOT NULL,
    after_json TEXT NOT NULL,
    actor_kind TEXT NOT NULL,
    request_id TEXT NOT NULL DEFAULT '',
    at TEXT NOT NULL
);
CREATE INDEX decision_history_txn ON decision_history(transaction_id);
CREATE TABLE overrides (
    override_id INTEGER PRIMARY KEY,
    transaction_id TEXT NOT NULL,
    origin TEXT NOT NULL CHECK (origin IN
        ('review_decision','board_manual_override','decided_at','manual_source','user_exception')),
    field TEXT NOT NULL DEFAULT '',
    event_ref TEXT NOT NULL DEFAULT '',
    UNIQUE (transaction_id, origin, field, event_ref)
);
CREATE TABLE rules_builtin (
    rule_id TEXT NOT NULL,
    version INTEGER NOT NULL,
    rule_json TEXT NOT NULL,
    rule_hash TEXT NOT NULL,
    PRIMARY KEY (rule_id, version)
);
CREATE TABLE jobs (
    job_id INTEGER PRIMARY KEY,
    kind TEXT NOT NULL,
    dedupe_key TEXT NOT NULL UNIQUE,
    state TEXT NOT NULL,
    lease_owner TEXT NOT NULL DEFAULT '',
    lease_until TEXT NOT NULL DEFAULT '',
    attempts INTEGER NOT NULL DEFAULT 0,
    not_before TEXT NOT NULL DEFAULT '',
    payload_json TEXT NOT NULL DEFAULT '{}'
);
CREATE TABLE budgets (
    day TEXT NOT NULL,
    scope TEXT NOT NULL,
    limit_units INTEGER NOT NULL,
    used_units INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (day, scope)
);
CREATE TABLE agent_runs (
    run_id TEXT PRIMARY KEY,
    job_id INTEGER REFERENCES jobs(job_id),
    model TEXT NOT NULL,
    started_at TEXT NOT NULL,
    finished_at TEXT NOT NULL DEFAULT '',
    outcome TEXT NOT NULL DEFAULT '',
    request_digest TEXT NOT NULL DEFAULT ''
);
CREATE TABLE p2_proposals (
    proposal_id INTEGER PRIMARY KEY,
    run_id TEXT NOT NULL REFERENCES agent_runs(run_id),
    transaction_id TEXT NOT NULL,
    proposal_json TEXT NOT NULL,
    validated INTEGER NOT NULL CHECK (validated IN (0,1)),
    error_code TEXT NOT NULL DEFAULT ''
);
CREATE TABLE shadow_runs (
    shadow_run_id INTEGER PRIMARY KEY,
    snapshot_digest TEXT NOT NULL,
    started_at TEXT NOT NULL,
    python_sha TEXT NOT NULL DEFAULT '',
    core_sha TEXT NOT NULL DEFAULT ''
);
CREATE TABLE shadow_diffs (
    shadow_run_id INTEGER NOT NULL REFERENCES shadow_runs(shadow_run_id),
    comparison TEXT NOT NULL CHECK (comparison IN ('B_vs_C','A_vs_C')),
    diff_key TEXT NOT NULL,
    count INTEGER NOT NULL,
    PRIMARY KEY (shadow_run_id, comparison, diff_key)
);
";

pub const MIGRATIONS: &[Migration] = &[Migration {
    version: 1,
    name: "초기 스키마(설계 §3.2)",
    sql: V1,
}];

/// 설계 §3.2 표의 새 테이블 이름 전부.
pub const TABLES: &[&str] = &[
    "schema_meta",
    "evidence",
    "facts",
    "links",
    "refund_groups",
    "trips",
    "decisions",
    "decision_history",
    "overrides",
    "rules_builtin",
    "jobs",
    "budgets",
    "agent_runs",
    "p2_proposals",
    "shadow_runs",
    "shadow_diffs",
];

pub fn latest_version() -> u32 {
    MIGRATIONS.last().map_or(0, |m| m.version)
}

pub fn current_version(conn: &Connection) -> Result<u32, StoreError> {
    let exists: Option<i64> = conn
        .query_row(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='schema_meta'",
            [],
            |r| r.get(0),
        )
        .optional()?;
    if exists.is_none() {
        return Ok(0);
    }
    let v: Option<u32> =
        conn.query_row("SELECT MAX(version) FROM schema_meta", [], |r| r.get(0))?;
    Ok(v.unwrap_or(0))
}

/// 아직 적용하지 않은 이관만 번호 순서로 적용한다. 이관마다 한 트랜잭션이다.
pub fn migrate(conn: &mut Connection) -> Result<u32, StoreError> {
    let found = current_version(conn)?;
    if found > latest_version() {
        return Err(StoreError::SchemaTooNew {
            found,
            known: latest_version(),
        });
    }
    for m in MIGRATIONS.iter().filter(|m| m.version > found) {
        let tx = conn.transaction()?;
        tx.execute_batch(
            "CREATE TABLE IF NOT EXISTS schema_meta (
                version INTEGER PRIMARY KEY,
                name TEXT NOT NULL,
                applied_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
            )",
        )?;
        tx.execute_batch(m.sql)?;
        tx.execute(
            "INSERT INTO schema_meta(version, name) VALUES (?1, ?2)",
            (m.version, m.name),
        )?;
        tx.commit()?;
    }
    current_version(conn)
}

/// 설정으로 받은 경로의 `core.sqlite`를 열고 이관한다. 기본 경로는 코어가 정하지 않는다.
pub fn open_core(path: &std::path::Path) -> Result<Connection, StoreError> {
    let mut conn = Connection::open(path)?;
    conn.execute_batch("PRAGMA foreign_keys=ON; PRAGMA busy_timeout=5000;")?;
    migrate(&mut conn)?;
    Ok(conn)
}
