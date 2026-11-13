use std::path::{Path, PathBuf};
use std::sync::atomic::{AtomicU32, Ordering};

use rusqlite::Connection;

use super::projection::{ALLOWED_ITEMS_SQL, AUX_TABLES, TRANSACTION_FIELDS};
use super::schema::{MIGRATIONS, TABLES};
use super::source_map::{Mapped, SourceInput, map_source};
use super::write_columns::*;
use super::*;
use crate::domain::ActorKind;

/// 임시 폴더(테스트 전용 합성 파일). 운영 경로를 쓰지 않는다.
struct TempDir(PathBuf);

impl TempDir {
    fn new() -> Self {
        static N: AtomicU32 = AtomicU32::new(0);
        let dir = std::env::temp_dir().join(format!(
            "cost-store-test-{}-{}",
            std::process::id(),
            N.fetch_add(1, Ordering::SeqCst)
        ));
        std::fs::create_dir_all(&dir).unwrap();
        Self(dir)
    }
    fn file(&self, name: &str) -> PathBuf {
        self.0.join(name)
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

const CHANGE_LOG: &str = "
CREATE TABLE change_log (entry_id INTEGER PRIMARY KEY AUTOINCREMENT, at TEXT NOT NULL,
    kind TEXT NOT NULL, subject TEXT NOT NULL, detail_json TEXT NOT NULL DEFAULT '{}');
";

const HASH: &str = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa";

fn insert_txn(
    conn: &Connection,
    id: &str,
    amount: Option<i64>,
    source: &str,
    decided: Option<&str>,
) {
    conn.execute(
        "INSERT INTO transactions (transaction_id,source_hash,batch_id,issuer,card_tail,card_kind,
         transaction_direction,transaction_kind,approval_number,original_approval_number,
         approval_date,posting_date,merchant,merchant_normalized,amount_krw,row_index,raw_row_json,
         classification_source,item,decided_at,created_at)
         VALUES (?1,?2,'b1','합성카드','1234','credit','charge','일시불','AP1','','2026-01-02',
         '2026-01-03','합성상점','합성상점',?3,0,'{}',?4,'식비',?5,'2026-01-03')",
        rusqlite::params![id, HASH, amount, source, decided],
    )
    .unwrap();
}

/// 합성 board.sqlite. `with_log`이면 감사 구조(change_log)도 만든다.
fn synthetic_board(dir: &TempDir, with_log: bool) -> PathBuf {
    let path = dir.file("board.sqlite");
    let conn = Connection::open(&path).unwrap();
    conn.execute_batch(BOARD_SCHEMA).unwrap();
    if with_log {
        conn.execute_batch(CHANGE_LOG).unwrap();
    }
    insert_txn(&conn, "t1", Some(-12000), "rule", None);
    insert_txn(&conn, "t2", None, "user_decision", Some("2026-02-01"));
    conn.execute_batch(
        "INSERT INTO trip_tabs(tab_id,display_key,starts_on,ends_on) VALUES ('1001_합성','1001','2026-01-01','2026-01-09');
         INSERT INTO review_decisions VALUES ('t2',1,'식비','','1001_합성','',0,'2026-02-01');
         INSERT INTO review_decisions VALUES ('t1',1,'교통','','1001_합성','',0,'2026-02-01');
         INSERT INTO board_manual_overrides VALUES ('card-t2','item','e1');
         INSERT INTO transaction_review_holds VALUES ('t1','h','user_hold','x');
         INSERT INTO transaction_company_exclusions VALUES ('t1','h',1,1,'','2026-01-01');
         INSERT INTO board_rows VALUES ('card-t1','card','1001_합성',1,'{}');
         INSERT INTO ledger_entries VALUES ('t1','b1','식비','','1001_합성','1001_합성',-12000,'합성상점','2026-01-02','charge','h','2026-01-04');",
    )
    .unwrap();
    path
}

// ---- 스키마·이관 ----

#[test]
fn migrate_creates_every_table_of_the_design() {
    let dir = TempDir::new();
    let conn = open_core(&dir.file("core.sqlite")).unwrap();
    assert_eq!(current_version(&conn).unwrap(), latest_version());
    for t in TABLES {
        let n: i64 = conn
            .query_row(
                "SELECT count(*) FROM sqlite_master WHERE type='table' AND name=?1",
                [t],
                |r| r.get(0),
            )
            .unwrap();
        assert_eq!(n, 1, "테이블 {t} 없음");
    }
    // 설계 §3.2 표의 16개(schema_meta 포함), refund_groups·links 포함.
    assert_eq!(TABLES.len(), 16);
    assert!(TABLES.contains(&"refund_groups") && TABLES.contains(&"links"));
}

#[test]
fn migrations_are_consecutive_and_idempotent() {
    for (i, m) in MIGRATIONS.iter().enumerate() {
        assert_eq!(m.version as usize, i + 1);
    }
    let dir = TempDir::new();
    let path = dir.file("core.sqlite");
    drop(open_core(&path).unwrap());
    let mut conn = open_core(&path).unwrap();
    assert_eq!(migrate(&mut conn).unwrap(), latest_version());
    let rows: i64 = conn
        .query_row("SELECT count(*) FROM schema_meta", [], |r| r.get(0))
        .unwrap();
    assert_eq!(rows as usize, MIGRATIONS.len());
}

#[test]
fn newer_schema_is_refused() {
    let dir = TempDir::new();
    let path = dir.file("core.sqlite");
    let conn = open_core(&path).unwrap();
    conn.execute(
        "INSERT INTO schema_meta(version,name) VALUES (99,'미래')",
        [],
    )
    .unwrap();
    drop(conn);
    assert!(matches!(
        open_core(&path),
        Err(StoreError::SchemaTooNew { found: 99, .. })
    ));
}

#[test]
fn links_and_refund_groups_enforce_vocabularies() {
    let dir = TempDir::new();
    let conn = open_core(&dir.file("core.sqlite")).unwrap();
    let ok = |producer: &str, kind: &str, status: &str| {
        conn.execute(
            "INSERT INTO links(snapshot_digest,producer,link_kind,exactness,basis,status,left_ref,right_ref)
             VALUES ('d',?1,?2,'exact','b',?3,'l','r')",
            [producer, kind, status],
        )
    };
    assert!(ok("rust", "refund_number", "full").is_ok());
    assert!(ok("python", "ota_mn_group", "partial").is_ok());
    assert!(ok("java", "refund_number", "full").is_err());
    assert!(ok("rust", "unknown_kind", "full").is_err());
    assert!(ok("rust", "refund_number", "weird").is_err());
    let group = |status: &str| {
        conn.execute(
            "INSERT INTO refund_groups(group_id,snapshot_digest,original_txn_id,member_txn_ids_json,net_krw,status)
             VALUES (?1,'d','o','[]',0,?2)",
            [status, status],
        )
    };
    assert!(group("excess").is_ok());
    assert!(group("bogus").is_err());
}

#[test]
fn core_schema_has_no_source_value_columns() {
    // 판정·연결 저장소는 원천 값(금액·원문·가맹점·승인번호)의 사본을 두지 않는다.
    let dir = TempDir::new();
    let conn = open_core(&dir.file("core.sqlite")).unwrap();
    let banned = [
        "amount_krw",
        "raw_row_json",
        "merchant",
        "approval_number",
        "description_raw",
        "foreign_amount",
        "content_bytes",
    ];
    for t in TABLES {
        let mut stmt = conn.prepare(&format!("PRAGMA table_info({t})")).unwrap();
        let cols: Vec<String> = stmt
            .query_map([], |r| r.get::<_, String>(1))
            .unwrap()
            .map(Result::unwrap)
            .collect();
        for c in cols {
            assert!(!banned.contains(&c.as_str()), "{t}.{c}는 원천 값 사본");
        }
    }
}

// ---- 읽기 전용 투영 ----

fn scope_py() -> String {
    let path = Path::new(env!("CARGO_MANIFEST_DIR")).join("../../../tools/p2_batch/scope.py");
    std::fs::read_to_string(path).unwrap()
}

#[test]
fn projection_columns_match_scope_py() {
    let src = scope_py();
    let start = src.find("FIELDS = (").unwrap();
    let end = start + src[start..].find(".split()").unwrap();
    let literal: String = src[start..end]
        .split('\'')
        .enumerate()
        .filter(|(i, _)| i % 2 == 1)
        .map(|(_, s)| s)
        .collect::<Vec<_>>()
        .join("");
    let python: Vec<&str> = literal.split_whitespace().collect();
    assert_eq!(python, TRANSACTION_FIELDS, "scope.FIELDS와 같은 열·순서");

    let a = src.find("for table, columns in (").unwrap();
    let b = a + src[a..]
        .find(
            "):
",
        )
        .unwrap();
    let python_aux: Vec<(String, String)> = src[a..b]
        .split("('")
        .skip(1)
        .map(|chunk| {
            let (table, rest) = chunk.split_once("', '").unwrap();
            let (columns, _) = rest.split_once('\'').unwrap();
            (table.to_owned(), columns.to_owned())
        })
        .collect();
    let rust_aux: Vec<(String, String)> = AUX_TABLES
        .iter()
        .map(|(t, c)| ((*t).to_owned(), (*c).to_owned()))
        .collect();
    assert_eq!(
        rust_aux, python_aux,
        "보조 테이블·열·순서가 scope.py와 정확히 같아야 한다"
    );
    assert_eq!(AUX_TABLES.len(), 7);

    let c = src.find("data['allowed_items']").unwrap();
    let d = c + src[c..].find("\")})").unwrap();
    let python_sql: String = src[c..d]
        .split('"')
        .enumerate()
        .filter(|(i, _)| i % 2 == 1)
        .map(|(_, s)| s)
        .collect();
    assert_eq!(
        ALLOWED_ITEMS_SQL, python_sql,
        "allowed_items 조회문이 scope.py와 같아야 한다"
    );
}

#[test]
fn projection_reads_rows_and_does_not_modify_the_file() {
    let dir = TempDir::new();
    let path = synthetic_board(&dir, true);
    let before = std::fs::read(&path).unwrap();
    let p = read_projection(&path).unwrap();
    assert_eq!(
        std::fs::read(&path).unwrap(),
        before,
        "읽기가 파일을 바꿨다"
    );
    assert_eq!(p.transactions.len(), 2);
    let t1 = p
        .transactions
        .iter()
        .find(|t| t.transaction_id == "t1")
        .unwrap();
    assert_eq!(t1.amount_krw, Some(-12000));
    assert_eq!(t1.duplicate_of, None);
    assert_eq!(t1.classification_source, "rule");
    let t2 = p
        .transactions
        .iter()
        .find(|t| t.transaction_id == "t2")
        .unwrap();
    assert_eq!(t2.amount_krw, None);
    assert_eq!(t2.decided_at.as_deref(), Some("2026-02-01"));
    assert_eq!(p.trip_tabs.len(), 1);
    assert_eq!(p.review_decisions.len(), 2);
    assert_eq!(p.board_manual_overrides[0].field, "item");
    assert_eq!(p.transaction_review_holds[0].kind, "user_hold");
    assert_eq!(p.transaction_company_exclusions[0].excluded, 1);
    assert_eq!(p.board_rows[0].row_id, "card-t1");
    assert_eq!(p.ledger_entries[0].trip_id, "1001_합성");
    assert_eq!(p.allowed_items, vec!["식비".to_owned()]);
    assert!(p.closed_provenance_review.is_empty());
}

#[test]
fn projection_works_without_change_log() {
    let dir = TempDir::new();
    let path = synthetic_board(&dir, false);
    let p = read_projection(&path).unwrap();
    // 감사 구조가 없으면 모든 결정이 보호된다.
    assert_eq!(p.review_decisions.len(), 2);
    assert!(p.closed_provenance_review.is_empty());
}

#[test]
fn released_decision_is_excluded_until_restored() {
    let dir = TempDir::new();
    let path = synthetic_board(&dir, true);
    let conn = Connection::open(&path).unwrap();
    conn.execute(
        "INSERT INTO change_log(at,kind,subject,detail_json) VALUES
         ('t','card.dist141_provenance_corrected','t1','{\"decision_revision\":1,\"opened\":0}')",
        [],
    )
    .unwrap();
    drop(conn);
    let p = read_projection(&path).unwrap();
    assert_eq!(p.review_decisions.len(), 1);
    assert_eq!(p.review_decisions[0].transaction_id, "t2");
    assert_eq!(p.closed_provenance_review, vec!["t1".to_owned()]);

    let conn = Connection::open(&path).unwrap();
    conn.execute(
        "INSERT INTO change_log(at,kind,subject,detail_json) VALUES
         ('t','card.dist141_provenance_restored','t1','{\"release_entry_id\":1}')",
        [],
    )
    .unwrap();
    drop(conn);
    let p = read_projection(&path).unwrap();
    assert_eq!(p.review_decisions.len(), 2);
    assert!(p.closed_provenance_review.is_empty());
}

#[test]
fn board_connection_is_read_only_and_query_only() {
    let dir = TempDir::new();
    let path = synthetic_board(&dir, true);
    let conn = open_board_readonly(&path).unwrap();
    let q: i64 = conn
        .query_row("PRAGMA query_only", [], |r| r.get(0))
        .unwrap();
    assert_eq!(q, 1);
    assert!(
        conn.execute("UPDATE transactions SET amount_krw=1", [])
            .is_err(),
        "쓰기가 거부돼야 한다"
    );
    assert!(conn.execute("DELETE FROM transactions", []).is_err());
    assert!(conn.execute_batch("CREATE TABLE x(a)").is_err());
    // 쓰기 시도 뒤에도 데이터가 그대로다.
    let n: i64 = conn
        .query_row("SELECT count(*) FROM transactions", [], |r| r.get(0))
        .unwrap();
    assert_eq!(n, 2);
}

#[test]
fn projection_does_not_create_a_missing_file() {
    let dir = TempDir::new();
    let path = dir.file("missing.sqlite");
    assert!(read_projection(&path).is_err());
    assert!(!path.exists(), "읽기 전용 열기는 파일을 만들면 안 된다");
}

#[test]
fn projection_leaves_no_open_transaction() {
    // 읽은 뒤 곧바로 다른 연결이 쓸 수 있어야 한다(짧은 트랜잭션).
    let dir = TempDir::new();
    let path = synthetic_board(&dir, true);
    read_projection(&path).unwrap();
    let w = Connection::open(&path).unwrap();
    w.execute(
        "UPDATE transactions SET item='교통' WHERE transaction_id='t1'",
        [],
    )
    .unwrap();
}

// ---- 출처 대응표 ----

fn mapped(source: &str) -> Mapped {
    map_mapped(SourceInput {
        source,
        ..SourceInput::default()
    })
}

fn kind(k: ActorKind, user_exception: bool) -> Mapped {
    Mapped::Actor {
        kind: k,
        user_exception,
    }
}

fn map_mapped(i: SourceInput<'_>) -> Mapped {
    map_source(i).mapped
}

#[test]
fn source_table_maps_every_value() {
    use ActorKind::*;
    for s in [
        "user_decision",
        "manual",
        "previous_decision",
        "manual_hold",
    ] {
        assert_eq!(mapped(s), kind(Manual, false), "{s}");
    }
    for s in ["user_exception", "owner_booking"] {
        assert_eq!(mapped(s), kind(Manual, true), "{s}");
    }
    for s in ["refund_original", "guide_airfare_evidence"] {
        assert_eq!(mapped(s), kind(P1Exact, false), "{s}");
    }
    assert_eq!(mapped("owner_card_residual"), kind(P1Inferred, true));
    for s in [
        "rule",
        "pattern",
        "card_category",
        "provider_default",
        "inference",
        "code_inference",
        "auto_inferred",
    ] {
        assert_eq!(mapped(s), kind(P1Inferred, false), "{s}");
    }
    for s in [
        "rule_conflict",
        "inference_conflict",
        "travel_location_hold",
        "booking_evidence_needed",
        "unreadable",
        "",
        "  ",
    ] {
        assert_eq!(mapped(s), Mapped::NoJudgement, "{s:?}");
    }
    assert_eq!(mapped("auto"), Mapped::Unrecognized);
    assert_eq!(mapped("something_new"), Mapped::Unrecognized);
}

#[test]
fn decided_at_makes_any_source_manual() {
    for s in ["rule", "ai_inference", "", "unreadable", "refund_original"] {
        let m = map_mapped(SourceInput {
            source: s,
            has_decided_at: true,
            ..SourceInput::default()
        });
        assert_eq!(m, kind(ActorKind::Manual, false), "{s:?}");
    }
}

#[test]
fn ai_inference_splits_on_the_ai_review_basis_prefix() {
    let with = |basis: &str| {
        map_mapped(SourceInput {
            source: "ai_inference",
            basis,
            ..SourceInput::default()
        })
    };
    assert_eq!(
        with("AI_REVIEW · {x} · 이유"),
        kind(ActorKind::AiReview, false)
    );
    assert_eq!(with("AI_REVIEW ·"), kind(ActorKind::P2, false));
    assert_eq!(with("근거 문장"), kind(ActorKind::P2, false));
    assert_eq!(with(""), kind(ActorKind::P2, false));
}

#[test]
fn bound_booking_rule_is_p1_exact_only_for_the_three_origins() {
    let rule = |origin: &str, bound: bool| {
        map_mapped(SourceInput {
            source: "rule",
            rule_origin: origin,
            source_hash_bound: bound,
            ..SourceInput::default()
        })
    };
    for o in ["ota-mail-live", "ota-portal-live", "auto-ota-period"] {
        assert_eq!(rule(o, true), kind(ActorKind::P1Exact, false), "{o}");
        assert_eq!(
            rule(o, false),
            kind(ActorKind::P1Inferred, false),
            "{o} 결속 없음"
        );
    }
    assert_eq!(
        rule("history-recovery-20261003", true),
        kind(ActorKind::P1Inferred, false)
    );
    assert_eq!(rule("", true), kind(ActorKind::P1Inferred, false));
}

#[test]
fn projection_sources_in_a_synthetic_board_all_map() {
    let dir = TempDir::new();
    let path = synthetic_board(&dir, true);
    let p = read_projection(&path).unwrap();
    let maps: Vec<Mapped> = p
        .transactions
        .iter()
        .map(|t| {
            map_mapped(SourceInput {
                source: &t.classification_source,
                basis: &t.classification_basis,
                has_decided_at: t.decided_at.is_some(),
                ..SourceInput::default()
            })
        })
        .collect();
    assert!(maps.contains(&kind(ActorKind::P1Inferred, false)));
    assert!(maps.contains(&kind(ActorKind::Manual, false)));
}

// ---- 쓰기 열 목록 ----

#[test]
fn write_lists_contain_no_source_column() {
    for (name, list) in [
        ("transactions", TRANSACTIONS_WRITE),
        ("ledger_entries", LEDGER_ENTRIES_WRITE),
        ("board_rows", BOARD_ROWS_WRITE),
    ] {
        for c in list {
            // `display_tab_id`·`item` 등은 판정 열이며 원천이 아니다.
            assert!(
                !SOURCE_COLUMNS.contains(c),
                "{name} 쓰기 목록에 원천 열 {c}"
            );
        }
    }
    assert_eq!(
        TRANSACTIONS_WRITE,
        [
            "classification_state",
            "classification_source",
            "classification_basis",
            "item",
            "description",
            "display_tab_id",
            "trip_id",
            "revision"
        ]
    );
}

#[test]
fn source_columns_cover_every_projection_source_field() {
    // 투영이 읽는 열 중 쓰기 목록에 없는 것은 모두 원천(또는 판정 읽기 전용) 열이다.
    for f in TRANSACTION_FIELDS {
        let writable = TRANSACTIONS_WRITE.contains(f);
        let source = SOURCE_COLUMNS.contains(f);
        assert!(
            writable != source,
            "{f}: 쓰기 열과 원천 열은 정확히 한쪽이어야 한다"
        );
    }
}

#[test]
fn set_clause_uses_only_the_allowed_columns() {
    let s = set_clause(TRANSACTIONS_WRITE);
    assert_eq!(s.matches('=').count(), TRANSACTIONS_WRITE.len());
    for c in SOURCE_COLUMNS {
        assert!(!s.split(',').any(|p| p.trim_end_matches("=?") == *c));
    }
}

#[test]
fn applying_the_write_list_never_changes_source_columns() {
    let dir = TempDir::new();
    let path = synthetic_board(&dir, true);
    let conn = Connection::open(&path).unwrap();
    let snapshot = |c: &Connection| -> Vec<String> {
        let cols = SOURCE_COLUMNS
            .iter()
            .filter(|c| {
                TRANSACTION_FIELDS.contains(c)
                    || **c == "batch_id"
                    || **c == "row_index"
                    || **c == "created_at"
            })
            .copied()
            .collect::<Vec<_>>()
            .join("||'|'||");
        let mut s = c
            .prepare(&format!(
                "SELECT COALESCE({cols},'') FROM transactions ORDER BY transaction_id"
            ))
            .unwrap();
        s.query_map([], |r| r.get::<_, String>(0))
            .unwrap()
            .map(Result::unwrap)
            .collect()
    };
    let before = snapshot(&conn);
    let sql = format!(
        "UPDATE transactions SET {} WHERE transaction_id='t1'",
        set_clause(TRANSACTIONS_WRITE)
    );
    conn.execute(
        &sql,
        rusqlite::params![
            "classified",
            "rule",
            "b",
            "교통",
            "d",
            "1001_합성",
            "1001_합성",
            2
        ],
    )
    .unwrap();
    assert_eq!(snapshot(&conn), before);
}

#[test]
fn ledger_and_board_write_lists_are_pinned() {
    assert_eq!(LEDGER_ENTRIES_WRITE, ["item", "display_tab_id", "trip_id"]);
    assert_eq!(
        BOARD_ROWS_WRITE,
        ["payload_json", "display_tab_id", "revision"]
    );
}

#[test]
fn manual_hold_keeps_its_raw_source_and_is_not_recordable() {
    for decided in [false, true] {
        let m = map_source(SourceInput {
            source: " manual_hold ",
            has_decided_at: decided,
            ..SourceInput::default()
        });
        assert_eq!(m.mapped, kind(ActorKind::Manual, false));
        assert_eq!(m.raw_source, "manual_hold");
        assert!(m.is_manual_hold());
    }
    let m = map_source(SourceInput {
        source: "user_decision",
        ..SourceInput::default()
    });
    assert_eq!(m.mapped, kind(ActorKind::Manual, false));
    assert_eq!(m.raw_source, "user_decision");
    assert!(!m.is_manual_hold());
}

#[test]
fn rollback_failure_keeps_the_original_read_error() {
    let e = StoreError::ReadFailedRollbackFailed {
        read: Box::new(StoreError::SchemaTooNew { found: 2, known: 1 }),
        rollback: rusqlite::Error::InvalidQuery,
    };
    let text = e.to_string();
    assert!(text.contains("스키마 버전 2") && text.contains("롤백도 실패"));
}
