//! `core/known-diffs.txt` 형식과 판정. 목록 밖 차이 1건이면 실패, 목록에 있지만 사라진 차이는 '해소됨'으로 보고한다.
//! 줄 = `항목  # 근거`. 항목은 두 가지이며 한 파일을 골든 시험과 그림자 실행이 함께 읽는다.
//! - 유형 키(`B-C|필드|이전 출처|전환`): 그림자 실행의 B↔C 차이 판정.
//! - 골든 사례 ID(`classify-176`, `plan-039`): 골든 시험의 알려진 차이.
//!
//! 둘 다 아닌 줄과 중복 줄은 오류다.

use std::collections::BTreeSet;

use super::ShadowError;
use super::keys::validate_key;

#[derive(Debug, Default, Clone, PartialEq, Eq)]
pub struct KnownDiffs {
    pub keys: BTreeSet<String>,
    pub case_ids: BTreeSet<String>,
}

impl KnownDiffs {
    /// 접두어(`plan-`, `classify-`)로 고른 골든 사례 ID.
    pub fn cases_with_prefix(&self, prefix: &str) -> BTreeSet<&str> {
        self.case_ids
            .iter()
            .filter(|id| id.starts_with(prefix))
            .map(String::as_str)
            .collect()
    }
}

/// `소문자-숫자`(예: `plan-039`).
fn is_case_id(entry: &str) -> bool {
    entry.split_once('-').is_some_and(|(kind, number)| {
        !kind.is_empty()
            && kind.bytes().all(|b| b.is_ascii_lowercase())
            && !number.is_empty()
            && number.bytes().all(|b| b.is_ascii_digit())
    })
}

pub fn parse_known_diffs(text: &str) -> Result<KnownDiffs, ShadowError> {
    let mut keys = BTreeSet::new();
    let mut case_ids = BTreeSet::new();
    for line in text.lines() {
        let entry = line.split('#').next().unwrap_or("").trim();
        if entry.is_empty() {
            continue;
        }
        let fresh = if entry.contains('|') {
            validate_key(entry).map_err(|_| ShadowError::KnownDiffsInvalid)?;
            keys.insert(entry.to_owned())
        } else if is_case_id(entry) {
            case_ids.insert(entry.to_owned())
        } else {
            return Err(ShadowError::KnownDiffsInvalid);
        };
        if !fresh {
            return Err(ShadowError::KnownDiffsInvalid);
        }
    }
    Ok(KnownDiffs { keys, case_ids })
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
