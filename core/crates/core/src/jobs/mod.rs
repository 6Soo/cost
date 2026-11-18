//! 제공자와 무관한 SQLite 작업 큐. 시간은 UTC Unix 초 단위로 호출자가 전달한다.
//!
//! `jobs.lease_until`과 `jobs.not_before`는 기존 TEXT 열을 유지하며 Unix 초의
//! 십진 문자열을 저장한다. 비교는 숫자로 변환하고, 과거 ISO 시각도 해석해
//! 사전순 문자열 비교에 따른 임대·대기 시간 오류를 막는다.

use std::fmt;

use rusqlite::{
    Connection, OptionalExtension, Transaction, TransactionBehavior, params, types::Value,
};
use serde::de::{self, Deserializer};
use serde::{Deserialize, Serialize};
use serde_json::Value as JsonValue;
use time::OffsetDateTime;

pub type JobId = i64;

pub const DEFAULT_DAILY_BUDGET_LIMIT: u32 = 30;
pub const MAX_DAILY_BUDGET_LIMIT: u32 = 30;
pub const MAX_ATTEMPTS: u32 = 3;
pub const MAX_LEASE_SECONDS: u32 = 7_200;
pub const DEFAULT_LEASE_SECONDS: u32 = 300;

/// 용량(제공자 한도) 실패에서 호출자가 대기 시각을 보내지 않았을 때만 쓰는 정책 기본값.
/// 호출자 값은 이 기본값보다 우선하며, 서버는 호출자 값을 덮어쓰지 않는다.
pub const DEFAULT_CAPACITY_RETRY_SECONDS: i64 = 3_600;

const FIRST_RETRY_DELAY_SECONDS: i64 = 30;
const SECOND_RETRY_DELAY_SECONDS: i64 = 60;

/// 고객 payload나 SQLite 내부 오류 문자열을 노출하지 않는 안정적인 오류 코드.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum QueueError {
    InvalidInput,
    InvalidState,
    DedupeConflict,
    JobNotFound,
    LeaseLost,
    GenerationExhausted,
    RetryTimeInvalid,
    CorruptData,
    Storage,
}

impl QueueError {
    pub const fn code(self) -> &'static str {
        match self {
            Self::InvalidInput => "invalid_input",
            Self::InvalidState => "invalid_state",
            Self::DedupeConflict => "dedupe_conflict",
            Self::JobNotFound => "job_not_found",
            Self::LeaseLost => "lease_lost",
            Self::GenerationExhausted => "generation_exhausted",
            Self::RetryTimeInvalid => "retry_time_invalid",
            Self::CorruptData => "corrupt_data",
            Self::Storage => "storage_error",
        }
    }
}

impl fmt::Display for QueueError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.write_str(self.code())
    }
}

impl std::error::Error for QueueError {}

impl From<rusqlite::Error> for QueueError {
    fn from(_: rusqlite::Error) -> Self {
        Self::Storage
    }
}

/// 신규 job 값. `budget_key: None`은 P1 등 P2 호출 예산을 쓰지 않는 작업이다.
pub struct EnqueueRequest {
    pub kind: String,
    pub dedupe_key: String,
    pub budget_key: Option<String>,
    pub payload: JsonValue,
}

/// 클레임 설정. `daily_budget_limit`은 0..=30 범위에서만 허용된다.
pub struct ClaimOptions {
    pub owner: String,
    pub lease_seconds: u32,
    pub daily_budget_limit: u32,
    /// `None`이면 모든 kind, 빈 목록이면 어떤 job도 선택하지 않는다.
    pub kinds: Option<Vec<String>>,
}

impl ClaimOptions {
    pub fn new(owner: impl Into<String>) -> Self {
        Self {
            owner: owner.into(),
            lease_seconds: DEFAULT_LEASE_SECONDS,
            daily_budget_limit: DEFAULT_DAILY_BUDGET_LIMIT,
            kinds: None,
        }
    }
}

/// 완료·heartbeat·fail에서 작업자 fencing에 사용하는 불변 토큰.
#[derive(Clone, PartialEq, Eq, Serialize)]
pub struct LeaseToken {
    job_id: JobId,
    owner: String,
    generation: i64,
}

impl LeaseToken {
    /// JSON·HTTPS 응답으로 받은 토큰을 복원한다. 이 생성자는 권한을 부여하지 않으며,
    /// 모든 변경은 DB의 owner·generation·lease 검사를 통과해야 한다.
    pub fn from_parts(
        job_id: JobId,
        owner: impl Into<String>,
        generation: i64,
    ) -> Result<Self, QueueError> {
        let owner = owner.into();
        if job_id <= 0 || generation <= 0 {
            return Err(QueueError::InvalidInput);
        }
        validate_name(&owner, 128)?;
        Ok(Self {
            job_id,
            owner,
            generation,
        })
    }

    pub const fn job_id(&self) -> JobId {
        self.job_id
    }

    pub const fn generation(&self) -> i64 {
        self.generation
    }

    pub fn owner(&self) -> &str {
        &self.owner
    }
}

impl<'de> Deserialize<'de> for LeaseToken {
    fn deserialize<D>(deserializer: D) -> Result<Self, D::Error>
    where
        D: Deserializer<'de>,
    {
        #[derive(Deserialize)]
        #[serde(deny_unknown_fields)]
        struct Fields {
            job_id: JobId,
            owner: String,
            generation: i64,
        }

        let fields = Fields::deserialize(deserializer)?;
        Self::from_parts(fields.job_id, fields.owner, fields.generation).map_err(de::Error::custom)
    }
}

impl fmt::Debug for LeaseToken {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.debug_struct("LeaseToken")
            .field("job_id", &self.job_id)
            .field("generation", &self.generation)
            .finish_non_exhaustive()
    }
}

/// 큐에서 임대한 작업. Debug 출력에서 payload는 항상 가린다.
#[derive(Serialize, PartialEq)]
pub struct LeasedJob {
    pub token: LeaseToken,
    pub kind: String,
    pub dedupe_key: String,
    pub budget_key: Option<String>,
    pub payload: JsonValue,
    pub attempts: u32,
    pub lease_until: i64,
}

impl fmt::Debug for LeasedJob {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.debug_struct("LeasedJob")
            .field("token", &self.token)
            .field("kind", &self.kind)
            .field("dedupe_key", &self.dedupe_key)
            .field("budget_key", &self.budget_key)
            .field("payload", &"[REDACTED]")
            .field("attempts", &self.attempts)
            .field("lease_until", &self.lease_until)
            .finish()
    }
}

#[derive(Debug, Clone, Copy, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "lowercase")]
pub enum JobState {
    Queued,
    Leased,
    Succeeded,
    Failed,
    Dead,
}

impl JobState {
    fn parse(value: &str) -> Result<Self, QueueError> {
        match value {
            "queued" => Ok(Self::Queued),
            "leased" => Ok(Self::Leased),
            "succeeded" => Ok(Self::Succeeded),
            "failed" => Ok(Self::Failed),
            "dead" => Ok(Self::Dead),
            _ => Err(QueueError::InvalidState),
        }
    }
}

/// 조회 응답. 완료 결과는 Debug 출력에서 가린다.
#[derive(Serialize)]
pub struct JobStatus {
    pub job_id: JobId,
    pub kind: String,
    pub state: JobState,
    pub attempts: u32,
    pub result: Option<JsonValue>,
}

impl fmt::Debug for JobStatus {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.debug_struct("JobStatus")
            .field("job_id", &self.job_id)
            .field("kind", &self.kind)
            .field("state", &self.state)
            .field("attempts", &self.attempts)
            .field("result", &self.result.as_ref().map(|_| "[REDACTED]"))
            .finish()
    }
}

/// 재시도 분류. capacity의 `not_before`는 다음 허용 시각(Unix 초)이다.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum FailureKind {
    Transient,
    Capacity { not_before: i64 },
    Authentication,
    Tool,
    Permanent,
}

/// `dedupe_key`가 이미 있으면 kind·JSON payload·budget scope가 같은 job ID를 반환한다.
/// 다른 조합이면 `dedupe_conflict`를 반환하며 기존 행은 덮어쓰지 않는다.
///
/// 삽입과 조회는 한 트랜잭션이다: 동시 같은 키 삽입에서 조회가 행을 놓쳐 `Storage`로
/// 실패하는 경합을 없앤다(`ON CONFLICT DO NOTHING` 뒤 조회는 항상 한 행을 본다).
/// **호출자는 열린 트랜잭션 안에서 이 함수를 호출하면 안 된다.** 내부는 `BEGIN IMMEDIATE`를
/// 시작하므로 중첩 트랜잭션에서 실패한다(현재 호출부는 모두 트랜잭션 밖이다).
pub fn enqueue(conn: &Connection, request: EnqueueRequest) -> Result<JobId, QueueError> {
    debug_assert!(
        conn.is_autocommit(),
        "enqueue는 열린 트랜잭션에서 호출하면 안 된다(중첩 BEGIN IMMEDIATE)"
    );
    validate_name(&request.kind, 64)?;
    validate_name(&request.dedupe_key, 256)?;
    let budget_key = request.budget_key.unwrap_or_default();
    if !budget_key.is_empty() {
        validate_name(&budget_key, 128)?;
    }
    let payload_json =
        serde_json::to_string(&request.payload).map_err(|_| QueueError::InvalidInput)?;

    // 삽입과 조회는 한 쓰기 트랜잭션이다: 동시 같은 키 삽입에서 조회가 경합 행을 놓치는
    // 경로를 없앤다. 쓰기 잠금(BEGIN IMMEDIATE)을 먼저 잡아 조회 전에 다른 연결의 삽입이
    // 끼어들 수 없게 하고, `&Connection`을 유지해 기존 호출부(브리지 포함)를 바꾸지 않는다.
    let tx = Transaction::new_unchecked(conn, TransactionBehavior::Immediate)?;
    tx.execute(
        "INSERT INTO jobs(kind,dedupe_key,state,payload_json,budget_key)
         VALUES (?1,?2,'queued',?3,?4)
         ON CONFLICT(dedupe_key) DO NOTHING",
        params![request.kind, request.dedupe_key, payload_json, budget_key],
    )?;

    let existing = tx
        .query_row(
            "SELECT job_id,kind,payload_json,budget_key FROM jobs WHERE dedupe_key=?1",
            [&request.dedupe_key],
            |row| {
                Ok((
                    row.get::<_, JobId>(0)?,
                    row.get::<_, String>(1)?,
                    row.get::<_, String>(2)?,
                    row.get::<_, String>(3)?,
                ))
            },
        )
        .optional()?
        .ok_or(QueueError::Storage)?;

    let (job_id, kind, stored_payload, stored_budget) = existing;
    let stored_payload: JsonValue =
        serde_json::from_str(&stored_payload).map_err(|_| QueueError::CorruptData)?;
    if kind != request.kind || stored_payload != request.payload || stored_budget != budget_key {
        return Err(QueueError::DedupeConflict);
    }
    tx.commit()?;
    Ok(job_id)
}

/// 만료 임대를 회수하고, 예산 예약과 새 임대를 하나의 `BEGIN IMMEDIATE` 트랜잭션으로 처리한다.
/// 예산이 소진됐거나 선택 가능한 작업이 없으면 `Ok(None)`이며 사용량은 차감되지 않는다.
pub fn claim(
    conn: &mut Connection,
    options: ClaimOptions,
    now: i64,
) -> Result<Option<LeasedJob>, QueueError> {
    validate_name(&options.owner, 128)?;
    validate_lease_seconds(options.lease_seconds)?;
    if options.daily_budget_limit > MAX_DAILY_BUDGET_LIMIT {
        return Err(QueueError::InvalidInput);
    }
    if let Some(kinds) = &options.kinds {
        for kind in kinds {
            validate_name(kind, 64)?;
        }
    }
    let lease_until = now
        .checked_add(i64::from(options.lease_seconds))
        .ok_or(QueueError::InvalidInput)?;
    let day = utc_day(now)?;
    let tx = conn.transaction_with_behavior(TransactionBehavior::Immediate)?;

    recover_expired(&tx, now)?;
    if options.kinds.as_ref().is_some_and(Vec::is_empty) {
        tx.commit()?;
        return Ok(None);
    }
    tx.execute(
        "UPDATE jobs SET state='dead', lease_owner='', lease_until=''
         WHERE state='queued' AND attempts >= ?1",
        [i64::from(MAX_ATTEMPTS)],
    )?;

    let candidate = select_candidate(&tx, &options, now, &day)?;
    let Some(candidate) = candidate else {
        tx.commit()?;
        return Ok(None);
    };

    let attempts = u32::try_from(candidate.attempts).map_err(|_| QueueError::CorruptData)?;
    let generation = candidate
        .lease_generation
        .checked_add(1)
        .filter(|generation| *generation > 0)
        .ok_or(QueueError::GenerationExhausted)?;
    let payload: JsonValue =
        serde_json::from_str(&candidate.payload_json).map_err(|_| QueueError::CorruptData)?;

    if !candidate.budget_key.is_empty() {
        reserve_budget(&tx, &day, &candidate.budget_key, options.daily_budget_limit)?;
    }
    let changed = tx.execute(
        "UPDATE jobs SET state='leased', lease_owner=?1, lease_until=?2,
             attempts=attempts+1, not_before='', lease_generation=?3
         WHERE job_id=?4 AND state='queued' AND attempts=?5 AND lease_generation=?6",
        params![
            options.owner,
            lease_until.to_string(),
            generation,
            candidate.job_id,
            candidate.attempts,
            candidate.lease_generation,
        ],
    )?;
    if changed != 1 {
        return Err(QueueError::Storage);
    }

    tx.commit()?;
    Ok(Some(LeasedJob {
        token: LeaseToken {
            job_id: candidate.job_id,
            owner: options.owner,
            generation,
        },
        kind: candidate.kind,
        dedupe_key: candidate.dedupe_key,
        budget_key: (!candidate.budget_key.is_empty()).then_some(candidate.budget_key),
        payload,
        attempts: attempts + 1,
        lease_until,
    }))
}

/// 현재 임대가 유효할 때만 임대를 연장한다. 만료 시각과 같은 시각부터는 거부된다.
pub fn heartbeat(
    conn: &Connection,
    token: &LeaseToken,
    lease_seconds: u32,
    now: i64,
) -> Result<i64, QueueError> {
    validate_lease_seconds(lease_seconds)?;
    let lease_until = now
        .checked_add(i64::from(lease_seconds))
        .ok_or(QueueError::InvalidInput)?;
    let sql = format!(
        "UPDATE jobs SET lease_until=?1 WHERE job_id=?2 AND state='leased'
         AND lease_owner=?3 AND lease_generation=?4 AND {}>?5",
        epoch_expression("lease_until")
    );
    let changed = conn.execute(
        &sql,
        params![
            lease_until.to_string(),
            token.job_id,
            token.owner,
            token.generation,
            now,
        ],
    )?;
    if changed != 1 {
        return Err(QueueError::LeaseLost);
    }
    Ok(lease_until)
}

/// 유효 임대의 작업만 완료하고 결과 JSON을 보존한다. 장부·금융 테이블은 쓰지 않는다.
pub fn complete(
    conn: &Connection,
    token: &LeaseToken,
    result: JsonValue,
    now: i64,
) -> Result<(), QueueError> {
    let result_json = serde_json::to_string(&result).map_err(|_| QueueError::InvalidInput)?;
    let sql = format!(
        "UPDATE jobs SET state='succeeded', lease_until='', result_json=?1
         WHERE job_id=?2 AND state='leased' AND lease_owner=?3 AND lease_generation=?4
           AND {}>?5",
        epoch_expression("lease_until")
    );
    let changed = conn.execute(
        &sql,
        params![
            result_json,
            token.job_id,
            token.owner,
            token.generation,
            now
        ],
    )?;
    if changed == 1 {
        return Ok(());
    }

    // 응답이 유실돼 같은 완료 요청이 재전송되면 이전 결과만 성공으로 확인한다.
    // 결과와 상태는 위의 단일 UPDATE로 함께 저장되므로 부분 완료는 보이지 않는다.
    let completed = conn
        .query_row(
            "SELECT state,lease_owner,lease_generation,result_json FROM jobs WHERE job_id=?1",
            [token.job_id],
            |row| {
                Ok((
                    row.get::<_, String>(0)?,
                    row.get::<_, String>(1)?,
                    row.get::<_, i64>(2)?,
                    row.get::<_, String>(3)?,
                ))
            },
        )
        .optional()?;
    let Some((state, owner, generation, stored_result)) = completed else {
        return Err(QueueError::LeaseLost);
    };
    if state != "succeeded" || owner != token.owner || generation != token.generation {
        return Err(QueueError::LeaseLost);
    }
    let stored_result: JsonValue =
        serde_json::from_str(&stored_result).map_err(|_| QueueError::CorruptData)?;
    if stored_result == result {
        Ok(())
    } else {
        Err(QueueError::LeaseLost)
    }
}

/// 실패한 호출은 이미 claim 때 예산에 반영되어 있다. 인증·도구 오류는 즉시 dead,
/// 일시·용량 오류는 시각을 늦춰 재시도하며 3번째 시도 이후에는 dead로 끝낸다.
pub fn fail(
    conn: &Connection,
    token: &LeaseToken,
    failure: FailureKind,
    now: i64,
) -> Result<JobState, QueueError> {
    let attempts: i64 = conn
        .query_row(
            "SELECT attempts FROM jobs WHERE job_id=?1 AND state='leased'
               AND lease_owner=?2 AND lease_generation=?3",
            params![token.job_id, token.owner, token.generation],
            |row| row.get(0),
        )
        .optional()?
        .ok_or(QueueError::LeaseLost)?;
    let attempts = u32::try_from(attempts).map_err(|_| QueueError::CorruptData)?;
    let (state, not_before) = match failure {
        FailureKind::Authentication | FailureKind::Tool => (JobState::Dead, None),
        FailureKind::Permanent => (JobState::Failed, None),
        FailureKind::Transient if attempts >= MAX_ATTEMPTS => (JobState::Dead, None),
        FailureKind::Capacity { .. } if attempts >= MAX_ATTEMPTS => (JobState::Dead, None),
        FailureKind::Transient => {
            let delay = if attempts <= 1 {
                FIRST_RETRY_DELAY_SECONDS
            } else {
                SECOND_RETRY_DELAY_SECONDS
            };
            let retry_at = now.checked_add(delay).ok_or(QueueError::InvalidInput)?;
            (JobState::Queued, Some(retry_at))
        }
        FailureKind::Capacity { not_before } if not_before > now => {
            (JobState::Queued, Some(not_before))
        }
        FailureKind::Capacity { .. } => return Err(QueueError::RetryTimeInvalid),
    };
    let next_state = state.as_str();
    let next_not_before = not_before.map_or_else(String::new, |value| value.to_string());
    let sql = format!(
        "UPDATE jobs SET state=?1, lease_owner='', lease_until='', not_before=?2
         WHERE job_id=?3 AND state='leased' AND lease_owner=?4 AND lease_generation=?5
           AND {}>?6",
        epoch_expression("lease_until")
    );
    let changed = conn.execute(
        &sql,
        params![
            next_state,
            next_not_before,
            token.job_id,
            token.owner,
            token.generation,
            now
        ],
    )?;
    if changed != 1 {
        return Err(QueueError::LeaseLost);
    }
    Ok(state)
}

/// 작업 상태와 완료 결과를 읽는다. 없는 ID는 `job_not_found`이다.
pub fn status(conn: &Connection, job_id: JobId) -> Result<JobStatus, QueueError> {
    let row = conn
        .query_row(
            "SELECT kind,state,attempts,result_json FROM jobs WHERE job_id=?1",
            [job_id],
            |row| {
                Ok((
                    row.get::<_, String>(0)?,
                    row.get::<_, String>(1)?,
                    row.get::<_, i64>(2)?,
                    row.get::<_, String>(3)?,
                ))
            },
        )
        .optional()?
        .ok_or(QueueError::JobNotFound)?;
    let (kind, state, attempts, result) = row;
    let result = if result.is_empty() {
        None
    } else {
        Some(serde_json::from_str(&result).map_err(|_| QueueError::CorruptData)?)
    };
    Ok(JobStatus {
        job_id,
        kind,
        state: JobState::parse(&state)?,
        attempts: u32::try_from(attempts).map_err(|_| QueueError::CorruptData)?,
        result,
    })
}

impl JobState {
    fn as_str(self) -> &'static str {
        match self {
            Self::Queued => "queued",
            Self::Leased => "leased",
            Self::Succeeded => "succeeded",
            Self::Failed => "failed",
            Self::Dead => "dead",
        }
    }
}

struct Candidate {
    job_id: JobId,
    kind: String,
    dedupe_key: String,
    budget_key: String,
    attempts: i64,
    lease_generation: i64,
    payload_json: String,
}

fn select_candidate(
    tx: &Transaction<'_>,
    options: &ClaimOptions,
    now: i64,
    day: &str,
) -> Result<Option<Candidate>, QueueError> {
    let not_before = epoch_expression("j.not_before");
    let mut sql = format!(
        "SELECT j.job_id,j.kind,j.dedupe_key,j.budget_key,j.attempts,j.lease_generation,j.payload_json
         FROM jobs j
         WHERE j.state='queued' AND {not_before}<=?1 AND j.attempts<?4
           AND (j.budget_key='' OR (?3>0 AND COALESCE(
               (SELECT b.used_units < MIN(b.limit_units,?3) FROM budgets b
                WHERE b.day=?2 AND b.scope=j.budget_key),1)))"
    );
    if let Some(kinds) = &options.kinds {
        let placeholders = (0..kinds.len()).map(|_| "?").collect::<Vec<_>>().join(",");
        sql.push_str(&format!(" AND j.kind IN ({placeholders})"));
    }
    sql.push_str(&format!(" ORDER BY {not_before},j.job_id LIMIT 1"));

    let mut values = vec![
        Value::Integer(now),
        Value::Text(day.to_owned()),
        Value::Integer(i64::from(options.daily_budget_limit)),
        Value::Integer(i64::from(MAX_ATTEMPTS)),
    ];
    if let Some(kinds) = &options.kinds {
        values.extend(kinds.iter().cloned().map(Value::Text));
    }
    let candidate = tx
        .query_row(&sql, rusqlite::params_from_iter(values.iter()), |row| {
            Ok(Candidate {
                job_id: row.get(0)?,
                kind: row.get(1)?,
                dedupe_key: row.get(2)?,
                budget_key: row.get(3)?,
                attempts: row.get(4)?,
                lease_generation: row.get(5)?,
                payload_json: row.get(6)?,
            })
        })
        .optional()?;
    Ok(candidate)
}

fn reserve_budget(
    tx: &Transaction<'_>,
    day: &str,
    scope: &str,
    configured_limit: u32,
) -> Result<(), QueueError> {
    let limit = i64::from(configured_limit);
    tx.execute(
        "INSERT INTO budgets(day,scope,limit_units,used_units) VALUES (?1,?2,?3,0)
         ON CONFLICT(day,scope) DO NOTHING",
        params![day, scope, limit],
    )?;
    // 설정 변경은 기존 당일 상한을 낮출 수는 있어도 높일 수는 없다.
    tx.execute(
        "UPDATE budgets SET limit_units=MIN(limit_units,?3) WHERE day=?1 AND scope=?2",
        params![day, scope, limit],
    )?;
    let reserved = tx.execute(
        "UPDATE budgets SET used_units=used_units+1
         WHERE day=?1 AND scope=?2 AND used_units<limit_units",
        params![day, scope],
    )?;
    if reserved != 1 {
        return Err(QueueError::CorruptData);
    }
    Ok(())
}

fn recover_expired(tx: &Transaction<'_>, now: i64) -> Result<(), QueueError> {
    let lease_until = epoch_expression("lease_until");
    let sql = format!(
        "UPDATE jobs
         SET state=CASE WHEN attempts>=?2 THEN 'dead' ELSE 'queued' END,
             lease_owner='', lease_until='',
             not_before=CASE WHEN attempts>=?2 THEN not_before
                ELSE CAST(?1 + CASE WHEN attempts<=1 THEN ?3 ELSE ?4 END AS TEXT) END
         WHERE state='leased' AND {lease_until}<=?1"
    );
    tx.execute(
        &sql,
        params![
            now,
            i64::from(MAX_ATTEMPTS),
            FIRST_RETRY_DELAY_SECONDS,
            SECOND_RETRY_DELAY_SECONDS,
        ],
    )?;
    Ok(())
}

/// 생성된 SQL에서만 사용하는 고정 열 이름. 숫자 문자열과 기존 SQLite 시각을 모두 초 단위로 비교한다.
fn epoch_expression(column: &str) -> String {
    format!(
        "CASE WHEN trim({column})=CAST(CAST(trim({column}) AS INTEGER) AS TEXT)
              THEN CAST(trim({column}) AS INTEGER)
              WHEN strftime('%s',{column}) IS NOT NULL THEN CAST(strftime('%s',{column}) AS INTEGER)
              ELSE 0 END"
    )
}

fn utc_day(now: i64) -> Result<String, QueueError> {
    let date_time =
        OffsetDateTime::from_unix_timestamp(now).map_err(|_| QueueError::InvalidInput)?;
    Ok(date_time.date().to_string())
}

fn validate_lease_seconds(seconds: u32) -> Result<(), QueueError> {
    if seconds == 0 || seconds > MAX_LEASE_SECONDS {
        return Err(QueueError::InvalidInput);
    }
    Ok(())
}

fn validate_name(value: &str, max_bytes: usize) -> Result<(), QueueError> {
    if value.trim().is_empty() || value.len() > max_bytes || value.chars().any(char::is_control) {
        return Err(QueueError::InvalidInput);
    }
    Ok(())
}
