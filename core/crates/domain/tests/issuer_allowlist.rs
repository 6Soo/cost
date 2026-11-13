//! 발급 기능·함수를 쓰는 크레이트가 허용 목록 안에 있는지 작업공간 전체를 검사한다.
//! Cargo 기능 통합 때문에 한 크레이트가 기능을 켜면 모두가 호출할 수 있으므로,
//! 컴파일러 대신 이 검사가 우회를 막는다.

use std::fs;
use std::path::{Path, PathBuf};

const ISSUERS: [(&str, &str, &str, &str); 2] = [
    // (기능 이름, 호출 모듈, 허용 크레이트 폴더, 호출 흔적)
    ("refund-issuer", "issue_refund", "links", "issue_refund"),
    ("scope-issuer", "issue_scope", "rules", "issue_scope"),
];

fn crates_dir() -> PathBuf {
    Path::new(env!("CARGO_MANIFEST_DIR")).join("..")
}

fn rust_files(dir: &Path, out: &mut Vec<PathBuf>) {
    let Ok(read) = fs::read_dir(dir) else { return };
    for entry in read.flatten() {
        let p = entry.path();
        if p.is_dir() {
            rust_files(&p, out);
        } else if p.extension().is_some_and(|e| e == "rs") {
            out.push(p);
        }
    }
}

#[test]
fn only_allowed_crates_enable_or_call_issuers() {
    let mut checked = 0;
    for entry in fs::read_dir(crates_dir()).unwrap().flatten() {
        let folder = entry.file_name().to_string_lossy().into_owned();
        if folder == "domain" || !entry.path().is_dir() {
            continue;
        }
        checked += 1;
        let manifest = fs::read_to_string(entry.path().join("Cargo.toml")).unwrap_or_default();
        let mut sources = Vec::new();
        rust_files(&entry.path().join("src"), &mut sources);
        rust_files(&entry.path().join("tests"), &mut sources);
        let code: String = sources
            .iter()
            .map(|p| fs::read_to_string(p).unwrap_or_default())
            .collect();
        for (feature, _module, allowed, trace) in ISSUERS {
            let uses = manifest.contains(feature) || code.contains(trace);
            assert!(
                !uses || folder == allowed,
                "크레이트 {folder}는 {feature} 발급을 쓸 수 없다(허용: {allowed})"
            );
        }
    }
    assert!(checked >= 8, "작업공간 크레이트를 찾지 못했다");
}
