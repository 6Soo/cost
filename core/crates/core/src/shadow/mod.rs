//! 그림자 실행 (M3 U10). 설계 `docs/design/m3-core.md` §3.3.
//! 같은 입력(운영 `board.sqlite` 사본)에서 A(저장값)·B(Python 재판정)·C(Rust 재판정)를 내어 유형 키로 집계한다.
//! 회귀 판정은 B↔C, A↔C·A↔B는 참고다. Rust 엔진은 `PlanEngine` 하나 뒤에 두어 U9가 끼워 넣는다.

mod bridge;
mod guard;
mod keys;
mod known;
#[cfg(test)]
mod tests;

use std::collections::{BTreeMap, BTreeSet};
use std::path::{Path, PathBuf};

use serde_json::{Value, json};

use crate::store::projection::TxnRow;
use crate::store::{StoreError, read_projection};

pub use bridge::PythonBridge;
pub use guard::{ensure_private_path, protected_root, write_private_lines};
pub use keys::{attribution_kind, diff_keys, validate_key};
pub use known::{KnownDiffs, Verdict, judge, parse_known_diffs};

#[derive(Debug, thiserror::Error)]
pub enum ShadowError {
    #[error("ENGINE_NOT_AVAILABLE")]
    EngineNotAvailable,
    #[error("PYTHON_BRIDGE_FAILED:{0}")]
    PythonBridgeFailed(String),
    #[error("PLAN_RESPONSE_INVALID")]
    PlanResponseInvalid,
    #[error("DB_IS_LIVE")]
    DbIsLive,
    #[error("PRIVATE_PATH_REJECTED")]
    PrivatePathRejected,
    #[error("PUBLIC_VALUE_NOT_ALLOWED")]
    PublicValueNotAllowed,
    #[error("KNOWN_DIFFS_INVALID")]
    KnownDiffsInvalid,
    #[error("USAGE_INVALID")]
    UsageInvalid,
    #[error("저장 계층 오류: {0}")]
    Store(#[from] StoreError),
    #[error("입출력 오류: {0}")]
    Io(#[from] std::io::Error),
}

impl ShadowError {
    /// 공개 출력에 내는 고정 코드(메시지 본문은 내지 않는다).
    pub fn code(&self) -> String {
        match self {
            Self::Store(_) => "STORE_ERROR".to_owned(),
            Self::Io(_) => "IO_ERROR".to_owned(),
            other => other.to_string(),
        }
    }
}

/// `app.automatic_classification.FIELDS` 중 비교·보고에 쓰는 값.
#[derive(Debug, Clone, PartialEq, Eq, Default)]
pub struct Values {
    pub state: String,
    pub source: String,
    pub basis: String,
    pub item: String,
    pub description: String,
    pub display_tab_id: String,
    pub trip_id: String,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Target {
    pub id: String,
    pub values: Values,
}

#[derive(Debug, Clone)]
pub struct PlanRequest {
    pub db: PathBuf,
    pub transaction_ids: Option<Vec<String>>,
    pub reconsider: bool,
    /// 호출자가 더 넘기는 입력(trips, nets, evidence). 엔진이 해석하며 이 모듈은 열어 보지 않는다.
    pub context: Value,
}

/// P1 `plan` 엔진 한 겹. Python 다리와 Rust 엔진이 같은 입력·출력 형식을 쓴다.
pub trait PlanEngine {
    fn plan(&self, request: &PlanRequest) -> Result<Vec<Target>, ShadowError>;
}

/// U9 `plan`이 병합되기 전의 Rust 쪽 자리.
pub struct UnavailableEngine;

impl PlanEngine for UnavailableEngine {
    fn plan(&self, _request: &PlanRequest) -> Result<Vec<Target>, ShadowError> {
        Err(ShadowError::EngineNotAvailable)
    }
}

/// Python 다리 `plan` 결과(`{targets:[{id, values:[7칸]}]}`)와 `costcore plan` 출력이 같은 모양이다.
pub fn parse_targets(result: &Value) -> Result<Vec<Target>, ShadowError> {
    let invalid = || ShadowError::PlanResponseInvalid;
    let mut out = Vec::new();
    for target in result["targets"].as_array().ok_or_else(invalid)? {
        let id = target["id"].as_str().ok_or_else(invalid)?.to_owned();
        let cells = target["values"].as_array().ok_or_else(invalid)?;
        if cells.len() < 7 {
            return Err(invalid());
        }
        let cell = |i: usize| cells[i].as_str().unwrap_or("").to_owned();
        out.push(Target {
            id,
            values: Values {
                state: cell(0),
                source: cell(1),
                basis: cell(2),
                item: cell(3),
                description: cell(4),
                display_tab_id: cell(5),
                trip_id: cell(6),
            },
        });
    }
    Ok(out)
}

pub fn targets_json(targets: &[Target]) -> Value {
    json!({ "targets": targets.iter().map(|t| json!({
        "id": t.id,
        "values": [t.values.state, t.values.source, t.values.basis, t.values.item,
                   t.values.description, t.values.display_tab_id, t.values.trip_id],
    })).collect::<Vec<_>>() })
}

fn stored(row: &TxnRow) -> Values {
    Values {
        state: row.classification_state.clone(),
        source: row.classification_source.clone(),
        basis: row.classification_basis.clone(),
        item: row.item.clone(),
        description: String::new(),
        display_tab_id: row.display_tab_id.clone(),
        trip_id: row.trip_id.clone(),
    }
}

/// 비공개 상세(거래 ID 포함). 보호 경로 안 파일에만 쓴다.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct PrivateDiff {
    pub id: String,
    pub key: String,
    pub left: Values,
    pub right: Values,
}

impl PrivateDiff {
    pub fn line(&self) -> String {
        let side = |v: &Values| {
            json!({"state": v.state, "source": v.source, "item": v.item,
                   "display_tab_id": v.display_tab_id, "trip_id": v.trip_id})
        };
        json!({"id": self.id, "key": self.key, "left": side(&self.left), "right": side(&self.right)})
            .to_string()
    }
}

#[derive(Debug, Clone, PartialEq, Eq, Default)]
pub struct PairReport {
    pub diff_rows: u64,
    pub types: BTreeMap<String, u64>,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct ShadowReport {
    pub rows: u64,
    pub python_targets: u64,
    pub rust_targets: u64,
    pub pairs: BTreeMap<String, PairReport>,
    pub verdict: Verdict,
}

impl ShadowReport {
    pub fn passed(&self) -> bool {
        self.verdict.passed()
    }

    /// 공개 보고. 모든 유형 키를 허용 목록으로 다시 검사한다.
    pub fn public_json(&self) -> Result<Value, ShadowError> {
        let mut pairs = serde_json::Map::new();
        for (pair, report) in &self.pairs {
            let mut types = Vec::new();
            for (key, count) in &report.types {
                validate_key(key)?;
                types.push(json!({"key": key, "count": count}));
            }
            pairs.insert(
                pair.clone(),
                json!({"diff_rows": report.diff_rows, "types": types}),
            );
        }
        for key in self.verdict.unlisted.iter().chain(&self.verdict.resolved) {
            validate_key(key)?;
        }
        Ok(json!({
            "status": if self.passed() { "PASS" } else { "FAIL" },
            "rows": self.rows,
            "python_targets": self.python_targets,
            "rust_targets": self.rust_targets,
            "pairs": pairs,
            "unlisted": self.verdict.unlisted,
            "resolved": self.verdict.resolved,
        }))
    }
}

pub struct ShadowOutcome {
    pub report: ShadowReport,
    pub private: Vec<PrivateDiff>,
}

/// 운영 DB 자체는 거부한다(사본만 받는다).
pub fn reject_live_db(db: &Path, host_root: &Path) -> Result<(), ShadowError> {
    let live = host_root.join("data").join("board.sqlite");
    if let (Ok(a), Ok(b)) = (db.canonicalize(), live.canonicalize())
        && a == b
    {
        return Err(ShadowError::DbIsLive);
    }
    Ok(())
}

/// A·B·C 세 값을 같은 거래에서 비교한다. Rust 엔진을 먼저 불러 없으면 곧바로 끝난다.
pub fn run_shadow(
    db: &Path,
    reconsider: bool,
    python: &dyn PlanEngine,
    rust: &dyn PlanEngine,
    known: &KnownDiffs,
) -> Result<ShadowOutcome, ShadowError> {
    let request = PlanRequest {
        db: db.to_owned(),
        transaction_ids: None,
        reconsider,
        context: Value::Null,
    };
    let rust_targets = rust.plan(&request)?;
    let python_targets = python.plan(&request)?;
    let projection = read_projection(db)?;

    let by_id = |targets: &[Target]| -> BTreeMap<String, Values> {
        targets
            .iter()
            .map(|t| (t.id.clone(), t.values.clone()))
            .collect()
    };
    let (python_by, rust_by) = (by_id(&python_targets), by_id(&rust_targets));

    let mut pairs: BTreeMap<String, PairReport> = BTreeMap::new();
    let mut private = Vec::new();
    for row in &projection.transactions {
        let a = stored(row);
        let id = &row.transaction_id;
        let b = python_by.get(id).cloned().unwrap_or_else(|| a.clone());
        let c = rust_by.get(id).cloned().unwrap_or_else(|| a.clone());
        for (pair, left, right) in [("A-B", &a, &b), ("B-C", &b, &c), ("A-C", &a, &c)] {
            let found = diff_keys(pair, left, right);
            if found.is_empty() {
                continue;
            }
            let report = pairs.entry(pair.to_owned()).or_default();
            report.diff_rows += 1;
            for key in found {
                *report.types.entry(key.clone()).or_default() += 1;
                private.push(PrivateDiff {
                    id: id.clone(),
                    key,
                    left: left.clone(),
                    right: right.clone(),
                });
            }
        }
    }
    let observed: BTreeSet<String> = pairs
        .get("B-C")
        .map(|p| p.types.keys().cloned().collect())
        .unwrap_or_default();
    let verdict = judge(known, &observed);
    Ok(ShadowOutcome {
        report: ShadowReport {
            rows: projection.transactions.len() as u64,
            python_targets: python_targets.len() as u64,
            rust_targets: rust_targets.len() as u64,
            pairs,
            verdict,
        },
        private,
    })
}
