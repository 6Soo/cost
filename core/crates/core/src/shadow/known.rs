//! `core/known-diffs.txt` 형식과 판정. 목록 밖 차이 1건이면 실패, 목록에 있지만 사라진 차이는 '해소됨'으로 보고한다.
//! 줄 = `키  # 근거`. 유형 키(`쌍|필드|…`)만 그림자 실행이 쓰고, 골든 사례 ID 줄(`classify-176`)은 건드리지 않는다.

use std::collections::BTreeSet;

use super::ShadowError;
use super::keys::validate_key;

#[derive(Debug, Default, Clone, PartialEq, Eq)]
pub struct KnownDiffs {
    pub keys: BTreeSet<String>,
}

pub fn parse_known_diffs(text: &str) -> Result<KnownDiffs, ShadowError> {
    let mut keys = BTreeSet::new();
    for line in text.lines() {
        let entry = line.split('#').next().unwrap_or("").trim();
        if entry.is_empty() {
            continue;
        }
        if entry.contains('|') {
            validate_key(entry).map_err(|_| ShadowError::KnownDiffsInvalid)?;
            keys.insert(entry.to_owned());
        }
    }
    Ok(KnownDiffs { keys })
}

#[derive(Debug, Clone, PartialEq, Eq, Default)]
pub struct Verdict {
    pub unlisted: Vec<String>,
    pub resolved: Vec<String>,
}

impl Verdict {
    pub fn passed(&self) -> bool {
        self.unlisted.is_empty()
    }
}

/// `observed`는 B↔C 차이 유형 키(회귀 판정 대상).
pub fn judge(known: &KnownDiffs, observed: &BTreeSet<String>) -> Verdict {
    Verdict {
        unlisted: observed.difference(&known.keys).cloned().collect(),
        resolved: known
            .keys
            .iter()
            .filter(|k| k.starts_with("B-C|") && !observed.contains(*k))
            .cloned()
            .collect(),
    }
}
