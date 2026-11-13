//! 열린 분기·열린 여행 판별과 `OpenScope` 생성 경계. 원본: `app/classification_correction.py:18-37`(`_open_p2_tab`).
//!
//! 설계 §2.4의 `OpenScope`는 U2(`cost-domain`)가 정의한다. 이 단위는 그 전에도 판별을 끝낼 수 있게 같은 모양의
//! 임시 토큰 `OpenScopeGrant`를 둔다: 필드가 비공개라 이 모듈의 `grant_*` 함수 밖에서는 만들 수 없다.
//! U2 병합 뒤 연결 방법: `OpenScopeGrant`를 `cost_domain::OpenScope`로 바꾸고, `grant_*` 함수 두 개가
//! 그 타입의 유일한 생성처가 되도록 U2의 생성자를 이 크레이트에서만 접근 가능하게 한다. 판별 함수
//! (`open_p2_tab`)와 골든은 그대로 쓴다.

use crate::closed_period::{CardRow, TripTab, open_scope};

/// 열린 범위 증명 토큰(임시 내부 타입, 위 모듈 문서 참조).
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct OpenScopeGrant {
    _private: (),
}

/// Python `int()`의 ASCII 부분: 앞뒤 공백, 부호, 숫자 사이의 밑줄 하나.
fn py_int(s: &str) -> Option<i64> {
    let s = s.trim();
    let (negative, body) = match s.strip_prefix('-') {
        Some(r) => (true, r),
        None => (false, s.strip_prefix('+').unwrap_or(s)),
    };
    if body.is_empty() || body.starts_with('_') || body.ends_with('_') || body.contains("__") {
        return None;
    }
    let cleaned: String = body.chars().filter(|c| *c != '_').collect();
    if !cleaned.bytes().all(|b| b.is_ascii_digit()) {
        return None;
    }
    let value: i64 = cleaned.parse().ok()?;
    Some(if negative { -value } else { value })
}

fn open_quarter(trip_id: &str) -> bool {
    let Some((_, rest)) = trip_id.split_once(':') else {
        return false;
    };
    let value = if rest.contains(": ") {
        rest.replace(": ", ":")
    } else {
        rest.to_string()
    };
    let parts = if let Some(parts) = value.split_once(':') {
        parts
    } else if let Some(parts) = value.split_once("-Q") {
        parts
    } else {
        return false;
    };
    match (py_int(parts.0), py_int(parts.1)) {
        (Some(year), Some(quarter)) => (year, quarter) >= (2026, 3),
        _ => false,
    }
}

/// `_open_p2_tab`: `quarter:{연}:{분기}` 탭은 2026년 3분기부터, 그 밖의 탭은 열린 여행일 때만 열려 있다.
pub fn open_p2_tab(trips: &[TripTab], trip_id: &str) -> bool {
    if trip_id.starts_with("quarter:") {
        return open_quarter(trip_id);
    }
    trips
        .iter()
        .find(|t| t.tab_key() == trip_id)
        .is_some_and(|t| crate::closed_period::open_trip(Some(t)))
}

/// 열린 탭이면 토큰을 만든다(P2·AI 검수 교정 적용 경로의 입력).
pub fn grant_for_tab(trips: &[TripTab], trip_id: &str) -> Option<OpenScopeGrant> {
    open_p2_tab(trips, trip_id).then_some(OpenScopeGrant { _private: () })
}

/// 행이 열린 범위(`open_scope`)이면 토큰을 만든다.
pub fn grant_for_row(row: &CardRow, trips: &[TripTab]) -> Option<OpenScopeGrant> {
    open_scope(row, trips).then_some(OpenScopeGrant { _private: () })
}
