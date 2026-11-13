//! 여행 귀속 추론(M3 U8). 원본: `app/trip_selection.py`, `app/provisional_assignment.py`(`card_trip_candidates`),
//! `app/automatic_classification.py`(`infer_trip`·`infer_item`·`_card3820_owner_policy`), `app/reconciliation.py`
//! (`stay_trip`), `app/rules.py`의 지역 판정, `webapp/card_trip_authority.py`(`booking_trip`).
//!
//! 순수 함수만 둔다(DB·저장소를 모른다). 현 Python 동작을 그대로 옮기며, 규칙집과 다른 곳은 [`RULEBOOK_DIFF_CANDIDATES`]에
//! 표시만 한다. 날짜 계산은 [`crate::dates`]를 쓴다. 날짜 입력은 `YYYY-MM-DD`만 받으므로(D-12) 그 밖의 값은 Python의
//! 우연한 해석을 따르지 않고 날짜가 없는 쪽(또는 [`crate::dates`]의 완료 기간 보호)으로 닫힌다.

mod candidates;
mod infer;
mod region;
mod select;
mod stay;

pub use candidates::{Candidate, card_trip_candidates};
pub use infer::{
    InferOptions, OwnerPolicy, card3820_owner_policy, infer_item, infer_trip, infer_trip_in,
};
pub use region::{
    is_booking_or_online, is_online_purchase_for_owner_card, merchant_country, transaction_region,
    trip_countries, trip_region,
};
pub use select::{
    Canonical, FUKUTAKE_BASIS, card_trip_allowed, fukutake_trips, is_fukutake_purchase,
    period_or_preparation, regional_trips,
};
pub use stay::{BookingPeriod, booking_trip, stay_trip};

use std::collections::BTreeMap;

/// 여행 한 줄(`trips` 원소). 빈 문자열은 값 없음이다.
#[derive(Debug, Clone, Default, PartialEq, Eq)]
pub struct Trip {
    pub trip_id: String,
    pub tab_id: String,
    pub display_key: String,
    pub destination: String,
    pub starts_on: String,
    pub ends_on: Option<String>,
    pub deleted: bool,
    pub archived: bool,
    /// Python `trip.get('enabled') is False`.
    pub disabled: bool,
    /// Python `trip.get('valid') is False`.
    pub invalid: bool,
    pub conflict: bool,
    pub period_conflict: bool,
    pub flags: Vec<String>,
}

/// 카드 행에서 여행 추론이 읽는 칸. 빈 문자열은 Python의 없는 값과 같다.
#[derive(Debug, Clone, Default, PartialEq, Eq)]
pub struct Txn {
    pub merchant: String,
    pub approval_date: String,
    pub posting_date: String,
    pub card_kind: String,
    pub card_tail: String,
    pub issuer: String,
    pub foreign_currency: String,
    pub description_raw: String,
    /// `None`은 키가 없음(`is_fukutake_purchase`는 이때 `purchase`로 본다).
    pub transaction_direction: Option<String>,
    pub transaction_kind: String,
    pub parse_error: String,
    pub duplicate_of: String,
    pub conflict_reason: String,
    pub classification_source: String,
    pub item: String,
    pub description: String,
    pub trip_id: String,
    pub display_tab_id: String,
    pub source_hash: String,
    /// Python `type(amount_krw) is int`일 때만 값이 있다.
    pub amount_krw: Option<i64>,
    pub raw_row: BTreeMap<String, String>,
}

/// 여행별 수입-비용 차액(`nets`).
pub type Nets = BTreeMap<String, i64>;

/// 규칙집과 다르지만 Python 동작을 재현한 곳. 고치지 않고 표시만 한다(설계 §7 U8).
pub const RULEBOOK_DIFF_CANDIDATES: [(&str, &str); 5] = [
    (
        "TRIP-044",
        "기간이 겹치는 해외 여행 사이에서 사용 국가 일치를 보지 않고 가맹점 지역명·수입-비용 차액으로 고른다(CODE_GAPS)",
    ),
    (
        "TRIP-041",
        "stay_trip은 덮음·겹침·차액까지 동률이면 선택하지 않는다(None)(CODE_GAPS)",
    ),
    (
        "TRIP-042",
        "prep_trip은 체크아웃 이후 가장 가까운 시작일만 보고 직전 여행 종료·밤 비중첩을 검사하지 않는다(CODE_GAPS)",
    ),
    (
        "TRIP-036",
        "예약 이용기간 사실의 우선 적용은 계획 조립(U9)이 한다. 여기서는 이용기간으로 여행을 고르는 booking_trip만 둔다",
    ),
    (
        "D-12",
        "날짜가 없거나 YYYY-MM-DD가 아니면 완료 기간 보호(PROC-072)로 닫힌다. Python은 날짜 없는 행을 제외하지 않는다",
    ),
];

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn restricted_jeju_trip_is_open_only_to_card_4813() {
        let trip = Trip {
            display_key: "0909_제주".into(),
            starts_on: "2026-09-09".into(),
            ..Trip::default()
        };
        let card = |tail: &str| Txn {
            card_tail: tail.into(),
            ..Txn::default()
        };
        assert!(card_trip_allowed(&card("4813"), &trip));
        assert!(!card_trip_allowed(&card("0001"), &trip));
        let moved = Trip {
            starts_on: "2026-09-08".into(),
            ..trip
        };
        assert!(card_trip_allowed(&card("0001"), &moved));
    }
}
