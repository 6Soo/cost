//! 카드 이용일 기준 여행 후보 순위. 원본: `app/provisional_assignment.py`의 `card_trip_candidates`.

use super::select::{
    Canonical, FUKUTAKE_BASIS, fukutake_trips, period_or_preparation, regional_trips,
};
use super::{Nets, Trip, Txn};
use crate::dates::parse_iso;

/// 후보 한 건. `score`는 정책 순서의 서수이며 클수록 앞선다(확률이 아니다).
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Candidate {
    pub trip_id: String,
    pub score: usize,
    pub confidence: &'static str,
    pub basis: String,
}

/// 지역·기간·차액 순서를 공유하고, 의미상 동률은 동률로 남긴다.
pub fn card_trip_candidates(t: &Txn, canonical: &Canonical, nets: &Nets) -> Vec<Candidate> {
    let all: Vec<&Trip> = canonical.iter().collect();
    if let Some(preferred) = fukutake_trips(t, &all) {
        return preferred
            .iter()
            .map(|trip| Candidate {
                trip_id: trip.trip_id.clone(),
                score: 1,
                confidence: "높음",
                basis: FUKUTAKE_BASIS.to_string(),
            })
            .collect();
    }
    let Ok(day) = parse_iso(&t.approval_date) else {
        return Vec::new();
    };
    let merchant = t.merchant.to_lowercase();
    let regional = regional_trips(t, &all, true);
    let available = period_or_preparation(&regional, &t.approval_date);
    // (거리, 이름 불일치, -차액): 작을수록 좋다. 큰 순위부터 서수를 매긴다.
    struct Ranked<'a> {
        rank: (i64, bool, i64),
        trip: &'a Trip,
        distance: i64,
        named: bool,
    }
    let mut ranked = Vec::new();
    for trip in available {
        let Ok(start) = parse_iso(&trip.starts_on) else {
            continue;
        };
        let end = match trip.ends_on.as_deref().filter(|e| !e.is_empty()) {
            Some(e) => match parse_iso(e) {
                Ok(d) => d,
                Err(_) => continue,
            },
            None => day,
        };
        let distance = (start - day)
            .whole_days()
            .max((day - end).whole_days())
            .max(0);
        let named =
            !trip.destination.is_empty() && merchant.contains(&trip.destination.to_lowercase());
        let net = nets.get(&trip.trip_id).copied().unwrap_or(0);
        ranked.push(Ranked {
            rank: (distance, !named, -net),
            trip,
            distance,
            named,
        });
    }
    let mut order: Vec<(i64, bool, i64)> = ranked.iter().map(|r| r.rank).collect();
    order.sort_unstable_by(|a, b| b.cmp(a));
    order.dedup();
    ranked
        .iter()
        .map(|r| Candidate {
            trip_id: r.trip.trip_id.clone(),
            score: order.iter().position(|o| *o == r.rank).unwrap_or(0),
            confidence: "낮음",
            basis: format!(
                "{}카드 이용일과 여행 기간 거리 {}일",
                if r.named {
                    "가맹점 지역명 일치 · "
                } else {
                    ""
                },
                r.distance
            ),
        })
        .collect()
}
