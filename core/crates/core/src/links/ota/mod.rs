//! OTA 결제 이벤트 ↔ 카드 행 후보 탐색·쌍 검사(M3 U13). 원본: `app/ota_payments.py`의 `_direction`부터
//! `_preauthorization_candidates`까지(방향·결제 여부·금액, 가맹점 표기·승인 규칙 범위, 금액 비교·승인 차액·날짜 지연,
//! 카드 식별·같은 날 동액·공급자 호환·보강 근거, `pair_check`, `search_card_candidates`)와 `_assemble_ota_match_results`의
//! "후보 단계로 결정되는" 앞부분([`Matcher::candidate_stage`]).
//!
//! 이벤트·카드 행·규칙은 Python dict 그대로 `serde_json::Value`로 받는다. 모든 함수는 `&Value`만 읽으므로 카드 원천
//! 값을 바꾸는 경로가 없다. M:N 묶음·점유·정확 연결 우선 배정·고정 그룹은 U14다([`Matcher::match_events`], 모듈 `link`·`assign`·
//! `relations`·`inference`). 최종 연결(쌍·상태·성분 구성)만 Python과 맞추고 중간 산출물은 약속하지 않는다.
//!
//! 알려진 차이: 가맹점 `NFKC` 접기는 전각 ASCII만 접는다(`_merchant_descriptors`), 날짜는 `YYYY-MM-DD`만 받는다(D-12),
//! 공급자 별칭 길이가 같을 때의 해소 순서는 공급자 이름순이다(Python은 JSON 파일 순서), 가수가 `i128`을 넘는
//! 금액은 해석하지 않는다. 근거 관계 ID는 ASCII 이벤트·카드 ID에서만
//! Python과 같다.

mod amount;
mod assign;
mod decimal;
mod defaults;
mod inference;
mod link;
mod pair;
mod pyval;
mod relations;
mod rule_scope;
mod search;
mod stage;

pub use amount::{AmountCompare, AmountStatus};
pub use decimal::Dec;
pub use defaults::{Defaults, DefaultsError, TripDelta};
pub use link::{FrozenChange, GroupShape, LinkKind, MatchedCounts, OtaLink};
pub use relations::Relation;
pub use search::{Candidate, DEFAULT_MAX_COMPARISONS, Rejected, Search, SearchResult};
pub use stage::{HoldOutcome, Stage, UniqueMatch};

use serde_json::Value;

/// 기본 설정과 승인 규칙을 묶은 읽기 전용 판정기.
#[derive(Debug, Clone, Copy)]
pub struct Matcher<'a> {
    pub defaults: &'a Defaults,
    pub rules: &'a [Value],
}

impl<'a> Matcher<'a> {
    pub fn new(defaults: &'a Defaults, rules: &'a [Value]) -> Self {
        Matcher { defaults, rules }
    }
}
