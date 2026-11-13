//! P1 규칙 엔진 1단계(M3 U5). 설계 `docs/design/m3-core.md` §4.
//!
//! 원본: `app/rules.py`(`normalize_rule`·`rule_matches`·국가·온라인 판정)와 `app/classify.py`의
//! `_classify_transaction`. 여행 해석기가 없는 경로만 옮겼다(여행 배정·후쿠타케·3820 예외는 U6).

mod builtin;
mod classify;
mod matching;
mod normalize;
mod text;

pub use builtin::{Attribution, Builtin, BuiltinRule, Effects, Kind, Strength};
pub use classify::{Verdict, classify};
pub use matching::{
    Transaction, is_booking_or_online, merchant_country, rule_matches, transaction_region,
};
pub use normalize::{Rule, normalize_rule};
pub use text::{casefold, normalize_merchant};

/// Python `StoreError(CODE_INVALID_INPUT, message)`와 같은 코드·문구의 거부.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct RuleError {
    pub code: &'static str,
    pub message: String,
}

pub const CODE_INVALID_INPUT: &str = "INVALID_INPUT";

impl RuleError {
    pub(crate) fn invalid(message: impl Into<String>) -> Self {
        Self {
            code: CODE_INVALID_INPUT,
            message: message.into(),
        }
    }
}

impl std::fmt::Display for RuleError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        write!(f, "{}: {}", self.code, self.message)
    }
}

impl std::error::Error for RuleError {}
