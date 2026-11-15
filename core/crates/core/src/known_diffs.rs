//! `core/known-diffs.txt` 줄 형식. 줄 = `항목  # 근거`. 항목은 두 가지이며 한 파일을 골든 시험과 그림자 실행이 함께 읽는다.
//! - 유형 키(`B-C|필드|이전 출처|전환`): 그림자 실행의 B↔C 차이 판정. 어휘 검사는 `shadow`가 한다.
//! - 골든 사례 ID(`classify-176`, `plan-039`): 골든 시험의 알려진 차이.
//!
//! 둘 다 아닌 줄과 중복 줄은 오류다.

use std::collections::BTreeSet;

#[derive(Debug, Default, Clone, PartialEq, Eq)]
pub struct KnownDiffs {
    pub keys: BTreeSet<String>,
    pub case_ids: BTreeSet<String>,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, thiserror::Error)]
#[error("KNOWN_DIFFS_INVALID")]
pub struct KnownDiffsInvalid;

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

/// 줄 형식만 검사한다(`|`가 있으면 유형 키, 아니면 사례 ID). 유형 키의 어휘는 보지 않는다.
pub fn parse_known_diffs(text: &str) -> Result<KnownDiffs, KnownDiffsInvalid> {
    let mut keys = BTreeSet::new();
    let mut case_ids = BTreeSet::new();
    for line in text.lines() {
        let entry = line.split('#').next().unwrap_or("").trim();
        if entry.is_empty() {
            continue;
        }
        let fresh = if entry.contains('|') {
            keys.insert(entry.to_owned())
        } else if is_case_id(entry) {
            case_ids.insert(entry.to_owned())
        } else {
            return Err(KnownDiffsInvalid);
        };
        if !fresh {
            return Err(KnownDiffsInvalid);
        }
    }
    Ok(KnownDiffs { keys, case_ids })
}
