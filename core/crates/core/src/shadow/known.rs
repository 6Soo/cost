//! 그림자 실행의 판정: 목록 밖 차이 1건이면 실패, 목록에 있지만 사라진 차이는 '해소됨'으로 보고한다.
//! 줄 형식은 `known_diffs`가 읽는다.

use std::collections::BTreeSet;

use super::ShadowError;
use super::keys::validate_key;
use crate::known_diffs::KnownDiffs;

impl KnownDiffs {
    /// 판정 그림자(plan)가 보는 키: 연결 키를 뺀다.
    pub fn without_link_keys(&self) -> KnownDiffs {
        self.filtered(false)
    }

    /// 연결 그림자가 보는 키: 연결 키만 남긴다.
    pub fn only_link_keys(&self) -> KnownDiffs {
        self.filtered(true)
    }

    fn filtered(&self, links: bool) -> KnownDiffs {
        KnownDiffs {
            keys: self
                .keys
                .iter()
                .filter(|k| super::links::is_link_key(k) == links)
                .cloned()
                .collect(),
            case_ids: self.case_ids.clone(),
        }
    }
}

/// 줄 형식(`known_diffs`)에 더해 유형 키를 공개 허용 목록으로 검사한다.
pub fn parse_known_diffs(text: &str) -> Result<KnownDiffs, ShadowError> {
    let known = crate::known_diffs::parse_known_diffs(text)?;
    for key in &known.keys {
        validate_key(key).map_err(|_| ShadowError::KnownDiffsInvalid)?;
    }
    Ok(known)
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
