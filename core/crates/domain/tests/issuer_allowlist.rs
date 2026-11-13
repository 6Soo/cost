//! 발급 기능·함수를 쓰는 크레이트가 허용 목록 안에 있는지 작업공간 전체를 검사한다.
//! Cargo 기능 통합 때문에 한 크레이트가 기능을 켜면 모두가 호출할 수 있으므로,
//! 컴파일러 대신 이 검사가 우회를 막는다.

use std::fs;
use std::path::{Path, PathBuf};

// (기능 이름, 허용 크레이트 폴더, 호출 흔적)
const ISSUERS: [(&str, &str, &str); 2] = [
    ("refund-issuer", "links", "issue_refund"),
    ("scope-issuer", "rules", "issue_scope"),
];

fn rust_files(dir: &Path, out: &mut Vec<PathBuf>) {
    let Ok(read) = fs::read_dir(dir) else { return };
    for entry in read.flatten() {
        let p = entry.path();
        if p.is_dir() {
            if p.file_name().is_some_and(|n| n == "target") {
                continue;
            }
            rust_files(&p, out);
        } else if p.extension().is_some_and(|e| e == "rs") {
            out.push(p);
        }
    }
}

/// `pub use` 문(세미콜론까지, 줄바꿈·공백 정규화) 중 발급 모듈을 다시 내보내는 것.
fn reexports_issuer(code: &str) -> bool {
    let flat = code.split_whitespace().collect::<Vec<_>>().join(" ");
    flat.split("pub ").skip(1).any(|rest| {
        let Some(rest) = rest.strip_prefix("use ").or_else(|| {
            // pub(crate) use / pub(super) use 도 같이 본다
            rest.split_once(") use ").map(|(_, r)| r)
        }) else {
            return false;
        };
        let stmt = rest.split(';').next().unwrap_or("");
        stmt.contains("issue_refund")
            || stmt.contains("issue_scope")
            || (stmt.contains("cost_domain") && stmt.contains('*'))
    })
}

/// `crates_dir` 아래 각 크레이트와 `root_manifest`(작업공간 루트 Cargo.toml)를 검사한다.
fn violations(crates_dir: &Path, root_manifest: &str) -> Vec<String> {
    let mut found = Vec::new();
    for (feature, ..) in ISSUERS {
        if root_manifest.contains(feature) {
            found.push(format!("작업공간 루트 Cargo.toml이 {feature}를 켠다"));
        }
    }
    for entry in fs::read_dir(crates_dir).unwrap().flatten() {
        let folder = entry.file_name().to_string_lossy().into_owned();
        if folder == "domain" || !entry.path().is_dir() {
            continue;
        }
        let manifest = fs::read_to_string(entry.path().join("Cargo.toml")).unwrap_or_default();
        let mut sources = Vec::new();
        rust_files(&entry.path(), &mut sources);
        let code: String = sources
            .iter()
            .map(|p| fs::read_to_string(p).unwrap_or_default() + "\n")
            .collect();
        if reexports_issuer(&code) {
            found.push(format!("크레이트 {folder}가 발급 모듈을 다시 내보낸다"));
        }
        for (feature, allowed, trace) in ISSUERS {
            let uses = manifest.contains(feature) || code.contains(trace);
            if uses && folder != allowed {
                found.push(format!(
                    "크레이트 {folder}는 {feature} 발급을 쓸 수 없다(허용: {allowed})"
                ));
            }
        }
    }
    found
}

fn real_crates() -> PathBuf {
    Path::new(env!("CARGO_MANIFEST_DIR")).join("..")
}

#[test]
fn workspace_obeys_issuer_allowlist() {
    let root = fs::read_to_string(real_crates().join("..").join("Cargo.toml")).unwrap();
    let found = violations(&real_crates(), &root);
    assert!(found.is_empty(), "{found:?}");
    let count = fs::read_dir(real_crates()).unwrap().count();
    assert!(count >= 8, "작업공간 크레이트를 찾지 못했다");
}

/// 가짜 작업공간(허용 크레이트 + 비허용 크레이트)에 파일을 심고 위반이 잡히는지 본다.
fn fixture(name: &str, files: &[(&str, &str)]) -> PathBuf {
    let dir = Path::new(env!("CARGO_TARGET_TMPDIR")).join(format!("allowlist-{name}"));
    let _ = fs::remove_dir_all(&dir);
    for crate_name in ["links", "pipeline"] {
        fs::create_dir_all(dir.join(crate_name).join("src")).unwrap();
        fs::write(dir.join(crate_name).join("Cargo.toml"), "[package]\n").unwrap();
    }
    for (rel, content) in files {
        let p = dir.join(rel);
        fs::create_dir_all(p.parent().unwrap()).unwrap();
        fs::write(p, content).unwrap();
    }
    dir
}

#[test]
fn clean_fixture_passes_and_allowed_crate_may_call() {
    let dir = fixture(
        "clean",
        &[(
            "links/src/lib.rs",
            "fn f() { cost_domain::issue_refund::refund_group(); }",
        )],
    );
    assert!(violations(&dir, "").is_empty());
}

#[test]
fn bypass_reexport_alias_from_allowed_crate_is_caught() {
    for stmt in [
        "pub use cost_domain::issue_refund as mint;",
        "pub use cost_domain::{\n    issue_refund as mint,\n};",
        "pub(crate) use cost_domain::issue_scope;",
        "pub use cost_domain::*;",
    ] {
        let dir = fixture("alias", &[("links/src/lib.rs", stmt)]);
        let found = violations(&dir, "");
        assert!(
            found.iter().any(|m| m.contains("다시 내보낸다")),
            "{stmt}: {found:?}"
        );
    }
}

#[test]
fn bypass_examples_benches_and_build_rs_are_scanned() {
    for rel in [
        "pipeline/examples/x.rs",
        "pipeline/benches/b.rs",
        "pipeline/build.rs",
        "pipeline/src/deep/nested/m.rs",
    ] {
        let dir = fixture(
            "scan",
            &[(rel, "fn f() { let _ = issue_refund::refund_group; }")],
        );
        let found = violations(&dir, "");
        assert!(
            found.iter().any(|m| m.contains("pipeline")),
            "{rel}: {found:?}"
        );
    }
}

#[test]
fn bypass_root_workspace_dependency_feature_is_caught() {
    let dir = fixture("root", &[]);
    let root = "[workspace.dependencies]\ncost-domain = { path = \"crates/domain\", features = [\"scope-issuer\"] }\n";
    assert!(violations(&dir, root).iter().any(|m| m.contains("루트")));
}

#[test]
fn bypass_manifest_feature_in_non_allowed_crate_is_caught() {
    let dir = fixture(
        "manifest",
        &[(
            "pipeline/Cargo.toml",
            "cost-domain = { features = [\"refund-issuer\"] }",
        )],
    );
    assert!(violations(&dir, "").iter().any(|m| m.contains("pipeline")));
}
