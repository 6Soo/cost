//! `costcore migrate`: core.sqlite 생성·이관 전용 명령. 임시 폴더만 쓰며 운영 경로·board를 열지 않는다.

use std::path::PathBuf;
use std::process::Command;

use rusqlite::Connection;
use serde_json::Value;

fn scratch(name: &str) -> PathBuf {
    static N: std::sync::atomic::AtomicU32 = std::sync::atomic::AtomicU32::new(0);
    let n = N.fetch_add(1, std::sync::atomic::Ordering::SeqCst);
    let dir = std::env::temp_dir().join(format!(
        "costcore-migrate-{}-{n}-{name}",
        std::process::id()
    ));
    let _ = std::fs::remove_dir_all(&dir);
    std::fs::create_dir_all(&dir).unwrap();
    dir
}

fn migrate(args: &[&str]) -> (i32, Value) {
    let out = Command::new(env!("CARGO_BIN_EXE_costcore"))
        .arg("migrate")
        .args(args)
        .output()
        .unwrap();
    let value = serde_json::from_slice(&out.stdout).unwrap();
    (out.status.code().unwrap(), value)
}

fn latest() -> u64 {
    u64::from(cost_core::store::latest_version())
}

#[test]
fn creates_new_file_at_latest_version() {
    let dir = scratch("new");
    let core = dir.join("core.sqlite");
    let (code, v) = migrate(&["--core", core.to_str().unwrap()]);
    assert_eq!(code, 0);
    assert_eq!(v["ok"], true);
    assert_eq!(v["created"], true);
    assert_eq!(v["from_version"], 0);
    assert_eq!(v["to_version"], latest());
    let conn = Connection::open(&core).unwrap();
    assert_eq!(
        u64::from(cost_core::store::current_version(&conn).unwrap()),
        latest()
    );
}

#[test]
fn second_run_changes_nothing() {
    let dir = scratch("idem");
    let core = dir.join("core.sqlite");
    let path = core.to_str().unwrap();
    migrate(&["--core", path]);
    let rows = |c: &Connection| -> i64 {
        c.query_row("SELECT COUNT(*) FROM schema_meta", [], |r| r.get(0))
            .unwrap()
    };
    let before = rows(&Connection::open(&core).unwrap());
    let (code, v) = migrate(&["--core", path]);
    assert_eq!(code, 0);
    assert_eq!(v["created"], false);
    assert_eq!(v["from_version"], latest());
    assert_eq!(v["to_version"], latest());
    assert_eq!(rows(&Connection::open(&core).unwrap()), before);
}

#[test]
fn migrates_older_file_and_keeps_data() {
    let dir = scratch("old");
    let core = dir.join("core.sqlite");
    {
        let conn = Connection::open(&core).unwrap();
        conn.execute_batch(
            "CREATE TABLE schema_meta (version INTEGER PRIMARY KEY, name TEXT NOT NULL,
                applied_at TEXT NOT NULL DEFAULT '');",
        )
        .unwrap();
        for m in cost_core::store::schema::MIGRATIONS
            .iter()
            .filter(|m| m.version == 1)
        {
            conn.execute_batch(m.sql).unwrap();
            conn.execute(
                "INSERT INTO schema_meta(version, name) VALUES (?1, ?2)",
                (m.version, m.name),
            )
            .unwrap();
        }
        conn.execute(
            "INSERT INTO budgets(day, scope, limit_units) VALUES ('d','s',5)",
            [],
        )
        .unwrap();
    }
    let (code, v) = migrate(&["--core", core.to_str().unwrap()]);
    assert_eq!(code, 0);
    assert_eq!(v["created"], false);
    assert_eq!(v["from_version"], 1);
    assert_eq!(v["to_version"], latest());
    let conn = Connection::open(&core).unwrap();
    let kept: i64 = conn
        .query_row("SELECT limit_units FROM budgets", [], |r| r.get(0))
        .unwrap();
    assert_eq!(kept, 5);
}

#[test]
fn rejects_newer_version_without_lowering() {
    let dir = scratch("new-ver");
    let core = dir.join("core.sqlite");
    let path = core.to_str().unwrap();
    migrate(&["--core", path]);
    let future = latest() + 1;
    Connection::open(&core)
        .unwrap()
        .execute(
            "INSERT INTO schema_meta(version, name) VALUES (?1, 'future')",
            [future],
        )
        .unwrap();
    let (code, v) = migrate(&["--core", path]);
    assert_eq!(code, 2);
    assert_eq!(v["ok"], false);
    assert_eq!(v["error"]["code"], "CORE_SCHEMA_MISMATCH");
    let max: u64 = Connection::open(&core)
        .unwrap()
        .query_row("SELECT MAX(version) FROM schema_meta", [], |r| r.get(0))
        .unwrap();
    assert_eq!(max, future);
}

#[test]
fn usage_and_store_errors_use_public_codes() {
    let (code, v) = migrate(&[]);
    assert_eq!(code, 2);
    assert_eq!(v["error"]["code"], "USAGE_INVALID");
    let dir = scratch("nodir");
    let bad = dir.join("missing").join("core.sqlite");
    let (code, v) = migrate(&["--core", bad.to_str().unwrap()]);
    assert_eq!(code, 2);
    assert_eq!(v["error"]["code"], "STORE_ERROR");
}

#[test]
fn never_touches_board() {
    let dir = scratch("board");
    let core = dir.join("core.sqlite");
    let board = dir.join("board.sqlite");
    let (code, _) = migrate(&[
        "--core",
        core.to_str().unwrap(),
        "--db",
        board.to_str().unwrap(),
    ]);
    assert_eq!(code, 0);
    assert!(!board.exists());
    let mut names: Vec<_> = std::fs::read_dir(&dir)
        .unwrap()
        .map(|e| e.unwrap().file_name().to_string_lossy().into_owned())
        .collect();
    names.sort();
    assert_eq!(names, ["core.sqlite"]);
}
