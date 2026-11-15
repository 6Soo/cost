use std::path::PathBuf;
use std::sync::atomic::{AtomicU32, Ordering};

use rusqlite::Connection;

use super::keys::{ITEM_VOCABULARY, SOURCE_VOCABULARY};
use super::*;
use crate::guard::{GuardError, ensure_private_path, write_private_lines};
use crate::pipeline::{PipelineError, reject_live_db};

struct TempDir(PathBuf);

impl TempDir {
    fn new() -> Self {
        static N: AtomicU32 = AtomicU32::new(0);
        let dir = std::env::temp_dir().join(format!(
            "cost-shadow-test-{}-{}",
            std::process::id(),
            N.fetch_add(1, Ordering::SeqCst)
        ));
        std::fs::create_dir_all(&dir).unwrap();
        Self(dir)
    }
    /// 합성 호스트 폴더(`data/backups`, `data/board.sqlite` 자리).
    fn host(&self) -> PathBuf {
        std::fs::create_dir_all(self.0.join("data").join("backups")).unwrap();
        self.0.clone()
    }
}

impl Drop for TempDir {
    fn drop(&mut self) {
        let _ = std::fs::remove_dir_all(&self.0);
    }
}

const BOARD_SCHEMA: &str = "
CREATE TABLE transactions (
    transaction_id TEXT PRIMARY KEY, source_hash TEXT NOT NULL, batch_id TEXT NOT NULL,
    issuer TEXT NOT NULL, card_tail TEXT NOT NULL, card_kind TEXT NOT NULL,
    transaction_direction TEXT NOT NULL, transaction_kind TEXT NOT NULL,
    approval_number TEXT NOT NULL, original_approval_number TEXT NOT NULL,
    approval_date TEXT NOT NULL, posting_date TEXT NOT NULL, merchant TEXT NOT NULL,
    merchant_normalized TEXT NOT NULL, amount_krw INTEGER, foreign_amount TEXT NOT NULL DEFAULT '',
    foreign_currency TEXT NOT NULL DEFAULT '', description_raw TEXT NOT NULL DEFAULT '',
    row_index INTEGER NOT NULL, raw_row_json TEXT NOT NULL, duplicate_of TEXT,
    conflict_reason TEXT NOT NULL DEFAULT '', parse_error TEXT NOT NULL DEFAULT '',
    classification_state TEXT NOT NULL DEFAULT 'needs_review',
    classification_source TEXT NOT NULL DEFAULT '', classification_basis TEXT NOT NULL DEFAULT '',
    item TEXT NOT NULL DEFAULT '', description TEXT NOT NULL DEFAULT '',
    display_tab_id TEXT NOT NULL DEFAULT '', trip_id TEXT NOT NULL DEFAULT '',
    revision INTEGER NOT NULL DEFAULT 1, decided_at TEXT, created_at TEXT NOT NULL);
CREATE TABLE trip_tabs (tab_id TEXT PRIMARY KEY, display_key TEXT NOT NULL,
    starts_on TEXT NOT NULL DEFAULT '', ends_on TEXT NOT NULL DEFAULT '',
    deleted INTEGER NOT NULL DEFAULT 0);
CREATE TABLE review_decisions (transaction_id TEXT NOT NULL, revision INTEGER NOT NULL,
    item TEXT NOT NULL, description TEXT NOT NULL, display_tab_id TEXT NOT NULL,
    note TEXT NOT NULL, reuse_rule INTEGER NOT NULL DEFAULT 0, decided_at TEXT NOT NULL,
    PRIMARY KEY (transaction_id, revision));
CREATE TABLE board_manual_overrides (row_id TEXT NOT NULL, field TEXT NOT NULL,
    event_id TEXT NOT NULL, PRIMARY KEY (row_id, field));
CREATE TABLE transaction_review_holds (transaction_id TEXT PRIMARY KEY, source_hash TEXT NOT NULL,
    kind TEXT NOT NULL, reason TEXT NOT NULL);
CREATE TABLE transaction_company_exclusions (transaction_id TEXT PRIMARY KEY,
    source_hash TEXT NOT NULL, excluded INTEGER NOT NULL, revision INTEGER NOT NULL,
    note TEXT NOT NULL, updated_at TEXT NOT NULL);
CREATE TABLE board_rows (row_id TEXT PRIMARY KEY, row_kind TEXT NOT NULL, display_tab_id TEXT,
    revision INTEGER NOT NULL, payload_json TEXT NOT NULL);
CREATE TABLE ledger_entries (transaction_id TEXT NOT NULL UNIQUE, batch_id TEXT NOT NULL,
    item TEXT NOT NULL, description TEXT NOT NULL, display_tab_id TEXT NOT NULL,
    trip_id TEXT NOT NULL DEFAULT '', amount_krw INTEGER, merchant TEXT NOT NULL,
    occurred_on TEXT NOT NULL, transaction_direction TEXT NOT NULL, source_hash TEXT NOT NULL,
    committed_at TEXT NOT NULL);
";

const SECRET_ID: &str = "SYNTHETIC-TXN-SECRET-1";
const SECRET_MERCHANT: &str = "합성비밀상점";

fn board(dir: &TempDir, host: &Path) -> PathBuf {
    let path = host.join("copy-board.sqlite");
    let _ = dir;
    let conn = Connection::open(&path).unwrap();
    conn.execute_batch(BOARD_SCHEMA).unwrap();
    for (id, item, tab) in [
        (SECRET_ID, "식비", "quarter:2026:4"),
        ("SYNTHETIC-TXN-2", "교통비", "1001_합성"),
    ] {
        conn.execute(
            "INSERT INTO transactions (transaction_id,source_hash,batch_id,issuer,card_tail,card_kind,
             transaction_direction,transaction_kind,approval_number,original_approval_number,
             approval_date,posting_date,merchant,merchant_normalized,amount_krw,row_index,raw_row_json,
             classification_state,classification_source,item,display_tab_id,created_at)
             VALUES (?1,'h','b1','합성카드','1234','credit','charge','일시불','AP1','','2026-01-02',
             '2026-01-03',?2,?2,-12000,0,'{}','classified','inference',?3,?4,'2026-01-03')",
            rusqlite::params![id, SECRET_MERCHANT, item, tab],
        )
        .unwrap();
    }
    path
}

fn values(item: &str, tab: &str) -> Values {
    Values {
        state: "classified".into(),
        source: "inference".into(),
        item: item.into(),
        display_tab_id: tab.into(),
        ..Values::default()
    }
}

struct Fake(Vec<Target>);

impl PlanEngine for Fake {
    fn plan(&self, _request: &PlanRequest) -> Result<Vec<Target>, ShadowError> {
        Ok(self.0.clone())
    }
}

fn target(id: &str, item: &str, tab: &str) -> Target {
    Target {
        id: id.into(),
        values: values(item, tab),
        has_history: false,
    }
}

#[test]
fn diff_keys_use_vocabulary_and_hide_out_of_list_values() {
    let left = values("식비", "quarter:2026:4");
    let right = values(SECRET_MERCHANT, "1001_합성");
    let keys = diff_keys("B-C", &left, &right);
    assert_eq!(
        keys,
        vec![
            "B-C|item|inference|식비→기타(목록 밖)".to_owned(),
            "B-C|attribution|inference|quarter→trip".to_owned(),
        ]
    );
    for key in &keys {
        validate_key(key).unwrap();
        assert!(!key.contains(SECRET_MERCHANT) && !key.contains("1001"));
    }
    let mut odd = left.clone();
    odd.trip_id = "T-1".into();
    assert_eq!(
        diff_keys("A-C", &left, &odd),
        vec!["A-C|trip|inference|differs".to_owned()]
    );
    assert!(diff_keys("B-C", &left, &left).is_empty());
}

#[test]
fn validate_key_rejects_values_outside_the_allow_list() {
    for bad in [
        "B-C|item|inference|식비→합성비밀상점",
        "B-C|item|합성가맹점|식비→교통비",
        "B-X|item|inference|식비→교통비",
        "B-C|amount|inference|1→2",
        "B-C|trip|inference|T-1",
        "B-C|item|inference|식비",
        "classify-176",
    ] {
        assert!(
            matches!(validate_key(bad), Err(ShadowError::PublicValueNotAllowed)),
            "{bad}"
        );
    }
}

#[test]
fn vocabularies_match_eval_cases() {
    let text = std::fs::read_to_string(format!(
        "{}/../../../tools/quarter_review/eval_cases.py",
        env!("CARGO_MANIFEST_DIR")
    ))
    .unwrap();
    for word in ITEM_VOCABULARY.iter().chain(SOURCE_VOCABULARY) {
        if !word.is_empty() {
            assert!(text.contains(&format!("'{word}'")), "{word}");
        }
    }
}

fn outcome(python: &[Target], rust: &[Target], known: &str) -> ShadowOutcome {
    let dir = TempDir::new();
    let host = dir.host();
    let db = board(&dir, &host);
    run_shadow(
        &db,
        false,
        &Fake(python.to_vec()),
        &Fake(rust.to_vec()),
        &parse_known_diffs(known).unwrap(),
    )
    .unwrap()
}

#[test]
fn equal_python_and_rust_pass_and_a_differences_are_reference_only() {
    let both = [target(SECRET_ID, "교통비", "quarter:2026:4")];
    let out = outcome(&both, &both, "");
    assert!(out.report.passed());
    assert_eq!(out.report.rows, 2);
    assert_eq!(out.report.pairs["A-B"].diff_rows, 1);
    assert_eq!(out.report.pairs["A-C"].diff_rows, 1);
    assert!(!out.report.pairs.contains_key("B-C"));
}

#[test]
fn unlisted_b_c_difference_fails_and_listing_it_passes() {
    let python = [target(SECRET_ID, "교통비", "quarter:2026:4")];
    let rust = [target(SECRET_ID, "숙박비", "quarter:2026:4")];
    let out = outcome(&python, &rust, "");
    assert!(!out.report.passed());
    assert_eq!(
        out.report.verdict.unlisted,
        vec!["B-C|item|inference|교통비→숙박비".to_owned()]
    );

    let known =
        "B-C|item|inference|교통비→숙박비  # TRIP-044 합성 근거\nclassify-176  # 골든 줄은 무시\n";
    let out = outcome(&python, &rust, known);
    assert!(out.report.passed());
    assert!(out.report.verdict.resolved.is_empty());
}

#[test]
fn listed_but_vanished_difference_is_reported_resolved() {
    let both = [target(SECRET_ID, "식비", "quarter:2026:4")];
    let known = "B-C|item|inference|교통비→숙박비  # 근거\n";
    let out = outcome(&both, &both, known);
    assert!(out.report.passed());
    assert_eq!(
        out.report.verdict.resolved,
        vec!["B-C|item|inference|교통비→숙박비".to_owned()]
    );
}

#[test]
fn public_report_has_keys_and_counts_only() {
    let python = [target(SECRET_ID, "교통비", "quarter:2026:4")];
    let rust = [target(SECRET_ID, SECRET_MERCHANT, "1001_합성")];
    let out = outcome(&python, &rust, "");
    let text = out.report.public_json().unwrap().to_string();
    for secret in [SECRET_ID, SECRET_MERCHANT, "1001_합성", "SYNTHETIC-TXN-2"] {
        assert!(!text.contains(secret), "{secret}");
    }
    assert!(text.contains("\"status\":\"FAIL\""));
    // 비공개 상세에는 ID가 있다.
    assert!(out.private.iter().any(|d| d.line().contains(SECRET_ID)));
}

#[test]
fn private_files_only_under_protected_backups() {
    let dir = TempDir::new();
    let host = dir.host();
    let inside = host
        .join("data")
        .join("backups")
        .join("shadow")
        .join("d.jsonl");
    let written = write_private_lines(&inside, &host, &["{}".to_owned()]).unwrap();
    assert!(written.is_file());
    // 같은 파일을 다시 쓰면 거부(덮어쓰기 없음).
    assert!(write_private_lines(&inside, &host, &[]).is_err());

    let outside = [
        host.join("data").join("d.jsonl"),
        host.join("d.jsonl"),
        host.join("data").join("backups").join("..").join("d.jsonl"),
        host.join("data").join("backups"),
        std::env::temp_dir().join("shadow-private.jsonl"),
    ];
    for path in outside {
        assert!(
            matches!(
                ensure_private_path(&path, &host),
                Err(GuardError::PrivatePathRejected)
            ),
            "{}",
            path.display()
        );
        assert!(!path.is_file());
    }
}

#[test]
fn live_database_is_rejected() {
    let dir = TempDir::new();
    let host = dir.host();
    let live = host.join("data").join("board.sqlite");
    std::fs::write(&live, b"").unwrap();
    assert!(matches!(
        reject_live_db(&live, &host),
        Err(PipelineError::DbIsLive)
    ));
    let copy = board(&dir, &host);
    assert!(reject_live_db(&copy, &host).is_ok());
}

#[test]
fn hard_link_to_the_live_database_is_rejected() {
    let dir = TempDir::new();
    let host = dir.host();
    let live = host.join("data").join("board.sqlite");
    std::fs::write(&live, b"x").unwrap();
    let alias = host.join("data").join("backups").join("alias.sqlite");
    std::fs::hard_link(&live, &alias).unwrap();
    assert!(matches!(
        reject_live_db(&alias, &host),
        Err(PipelineError::DbIsLive)
    ));
    let missing = host.join("data").join("backups").join("none.sqlite");
    std::fs::remove_file(&live).unwrap();
    assert!(reject_live_db(&missing, &host).is_ok());
}

#[test]
fn known_diffs_file_in_repo_parses_and_bad_keys_are_rejected() {
    let text = std::fs::read_to_string(concat!(
        env!("CARGO_MANIFEST_DIR"),
        "/../../known-diffs.txt"
    ))
    .unwrap();
    assert!(parse_known_diffs(&text).is_ok());
    assert!(matches!(
        parse_known_diffs("B-C|item|inference|식비→합성상점  # x"),
        Err(ShadowError::KnownDiffsInvalid)
    ));
}

#[test]
fn plan_json_round_trips() {
    let targets = vec![target("t1", "식비", "quarter:2026:4")];
    assert_eq!(parse_targets(&targets_json(&targets)).unwrap(), targets);
    assert!(matches!(
        parse_targets(&serde_json::json!({"targets": [{"id": "x", "values": []}]})),
        Err(ShadowError::PlanResponseInvalid)
    ));
}

#[test]
fn rust_engine_reads_a_copy_and_plans_without_a_python_bridge() {
    let dir = TempDir::new();
    let host = dir.host();
    let db = board(&dir, &host);
    let request = PlanRequest {
        db,
        transaction_ids: None,
        reconsider: false,
        context: Value::Null,
    };
    let targets = RustEngine { links: None }.plan(&request).unwrap();
    assert!(targets.len() <= 2);
}

#[test]
fn new_fields_are_compared_but_public_keys_carry_no_text() {
    let left = Values {
        basis: "합성근거 가".into(),
        description: "합성설명 가".into(),
        period: Some("2026-01-01/2026-01-03".into()),
        actor: Some(ActorKind::P1Inferred),
        ..values("식비", "1001_합성")
    };
    let right = Values {
        basis: "합성근거 나".into(),
        description: "합성설명 나".into(),
        period: Some("unknown".into()),
        actor: Some(ActorKind::Manual),
        ..values("식비", "1001_합성")
    };
    let keys = diff_keys("B-C", &left, &right);
    assert_eq!(
        keys,
        vec![
            "B-C|basis|inference|differs".to_owned(),
            "B-C|description|inference|differs".to_owned(),
            "B-C|period|inference|differs".to_owned(),
            "B-C|actor|inference|P1Inferred→Manual".to_owned(),
        ]
    );
    for key in &keys {
        validate_key(key).unwrap();
        assert!(!key.contains("합성"));
    }
    // 한쪽이 기간·주체를 내지 않으면 비교하지 않는다.
    let silent = Values {
        period: None,
        actor: None,
        ..right.clone()
    };
    assert_eq!(diff_keys("B-C", &left, &silent).len(), 2);
}

#[test]
fn stored_description_is_read_so_an_equal_description_is_no_difference() {
    let dir = TempDir::new();
    let host = dir.host();
    let db = board(&dir, &host);
    Connection::open(&db)
        .unwrap()
        .execute("UPDATE transactions SET description='합성설명'", [])
        .unwrap();
    let mut same = target(SECRET_ID, "식비", "quarter:2026:4");
    same.values.description = "합성설명".into();
    let out = run_shadow(
        &db,
        false,
        &Fake(vec![same.clone()]),
        &Fake(vec![same]),
        &KnownDiffs::default(),
    )
    .unwrap();
    assert!(!out.report.pairs.contains_key("A-B"));
    let mut other = target(SECRET_ID, "식비", "quarter:2026:4");
    other.values.description = "다른 설명".into();
    let out = run_shadow(
        &db,
        false,
        &Fake(vec![other.clone()]),
        &Fake(vec![other]),
        &KnownDiffs::default(),
    )
    .unwrap();
    assert!(
        out.report.pairs["A-B"]
            .types
            .contains_key("A-B|description|inference|differs")
    );
}

#[test]
fn result_ids_must_be_unique_known_and_in_range() {
    let dir = TempDir::new();
    let host = dir.host();
    let db = board(&dir, &host);
    let good = target(SECRET_ID, "식비", "quarter:2026:4");
    let run = |python: Vec<Target>, rust: Vec<Target>| {
        run_shadow(
            &db,
            false,
            &Fake(python),
            &Fake(rust),
            &KnownDiffs::default(),
        )
    };
    let duplicate = run(vec![good.clone(), good.clone()], vec![good.clone()]);
    assert!(matches!(duplicate, Err(ShadowError::ResultIdsInvalid)));
    let unknown = run(vec![good.clone()], vec![target("NOT-IN-DB", "식비", "")]);
    assert!(matches!(unknown, Err(ShadowError::ResultIdsInvalid)));
    assert!(run(vec![good.clone()], vec![good.clone()]).is_ok());

    let ids = [SECRET_ID.to_owned()];
    let db_ids: BTreeSet<&str> = [SECRET_ID, "SYNTHETIC-TXN-2"].into();
    let outside = target("SYNTHETIC-TXN-2", "식비", "");
    assert!(matches!(
        index_targets(&[outside], &db_ids, Some(&ids)),
        Err(ShadowError::ResultIdsInvalid)
    ));
    assert!(index_targets(&[good], &db_ids, Some(&ids)).is_ok());
}

#[test]
fn known_diffs_keep_keys_and_case_ids_apart_and_reject_garbage() {
    let known = parse_known_diffs(
        "plan-039  # x
classify-176  # y
B-C|basis|rule|differs  # z
",
    )
    .unwrap();
    assert_eq!(known.keys.len(), 1);
    assert_eq!(known.cases_with_prefix("plan-").len(), 1);
    assert_eq!(known.cases_with_prefix("classify-").len(), 1);
    for bad in [
        "plan 039  # x",
        "plan-039
plan-039",
        "B-C|basis|rule|differs
B-C|basis|rule|differs",
    ] {
        assert!(matches!(
            parse_known_diffs(bad),
            Err(ShadowError::KnownDiffsInvalid)
        ));
    }
}

#[test]
fn bridge_envelope_must_match_command_digest_and_commit() {
    let body = serde_json::json!({"db": "x", "reconsider": false});
    let digest = crate::digest::sha256_hex(&crate::digest::python_json(&body));
    let sha = "a".repeat(40);
    let ok = serde_json::json!({"command": "plan", "python_sha": sha, "input_digest": digest});
    assert!(crate::bridge::verify_envelope(&ok, "plan", &body).is_ok());
    for bad in [
        serde_json::json!({"command": "plan", "python_sha": sha, "input_digest": "0"}),
        serde_json::json!({"command": "plan", "python_sha": "", "input_digest": digest}),
        serde_json::json!({"command": "links", "python_sha": sha, "input_digest": digest}),
    ] {
        assert!(crate::bridge::verify_envelope(&bad, "plan", &body).is_err());
    }
}
