//! 예약 이용기간으로 여행 고르기. 원본: `app/reconciliation.py`의 `stay_trip`(TRIP-039 숙박 밤 기준·TRIP-042 준비 숙박),
//! `webapp/card_trip_authority.py`의 `booking_trip`(TRIP-036). 날짜 계산은 [`crate::dates`]를 쓴다.

use super::select::card_trip_allowed;
use super::{Nets, Trip, Txn};
use crate::dates::{
    DateError, Span, covers_stay, handover_days, overlaps_stay, prep_trip, shared_days,
};

fn span(t: &Trip) -> Span {
    Span {
        starts_on: Some(t.starts_on.clone()),
        ends_on: t.ends_on.clone(),
    }
}

/// 예약 체류가 속한 여행의 위치(`trips` 안 색인). 하루도 겹치는 여행이 없으면 `None`이다.
///
/// 체류 전체를 덮는 여행이 이기고, 아니면 가장 많은 밤을 공유하는 여행이다. 동률은 수입-비용 차액이 큰 쪽이고
/// 그래도 같으면 고르지 않는다. 어느 여행과도 밤을 공유하지 않는 숙박은 다음 여행의 준비 숙박(`prep_trip`)이다.
pub fn stay_trip(
    trips: &[Trip],
    check_in: &str,
    check_out: &str,
    service: bool,
    nets: &Nets,
) -> Result<Option<usize>, DateError> {
    let spans: Vec<Span> = trips.iter().map(span).collect();
    let handover = handover_days(&spans)?;
    let end_of = |s: &Span| s.ends_on.clone().unwrap_or_default();
    let start_of = |s: &Span| s.starts_on.clone().unwrap_or_default();
    let mut covering = Vec::new();
    for (i, s) in spans.iter().enumerate() {
        if covers_stay(
            &start_of(s),
            &end_of(s),
            check_in,
            check_out,
            service,
            &handover,
        )? {
            covering.push(i);
        }
    }
    let pool = if covering.is_empty() {
        let mut overlapping = Vec::new();
        for (i, s) in spans.iter().enumerate() {
            if overlaps_stay(
                &start_of(s),
                &end_of(s),
                check_in,
                check_out,
                service,
                &handover,
            )? {
                overlapping.push(i);
            }
        }
        overlapping
    } else {
        covering.clone()
    };
    if pool.is_empty() {
        return Ok(if service {
            None
        } else {
            prep_trip(&spans, check_out)
        });
    }
    let mut ranks = Vec::new();
    for &i in &pool {
        let shared = if covering.is_empty() {
            shared_days(
                &start_of(&spans[i]),
                &end_of(&spans[i]),
                check_in,
                check_out,
                service,
                &handover,
            )?
        } else {
            0
        };
        ranks.push((i, (shared, nets.get(&trips[i].tab_id).copied())));
    }
    let best = ranks.iter().map(|(_, r)| *r).max();
    let mut top = ranks.iter().filter(|(_, r)| Some(*r) == best);
    let first = top.next().map(|(i, _)| *i);
    Ok(if top.next().is_some() { None } else { first })
}

/// 예약 이용기간(숙박은 체크인·체크아웃, 항공은 service).
#[derive(Debug, Clone, Default)]
pub struct BookingPeriod {
    pub starts_on: String,
    pub ends_on: String,
    pub service: bool,
    pub target_code: Option<String>,
}

/// 이용기간에 맞는 검증된 여행의 `tab_id`(없으면 빈 문자열). 저장된 여행 이름이 기간과 겹치는 여행이 하나면 그 여행을 쓴다.
pub fn booking_trip(
    t: &Txn,
    trips: &[Trip],
    period: &BookingPeriod,
    nets: &Nets,
) -> Result<String, DateError> {
    let verified: Vec<Trip> = trips
        .iter()
        .filter(|trip| card_trip_allowed(t, trip))
        .cloned()
        .collect();
    let spans: Vec<Span> = verified.iter().map(span).collect();
    let handover = handover_days(&spans)?;
    let mut named = Vec::new();
    for (trip, s) in verified.iter().zip(&spans) {
        if period.target_code.as_deref() == Some(trip.display_key.as_str())
            && overlaps_stay(
                s.starts_on.as_deref().unwrap_or(""),
                s.ends_on.as_deref().unwrap_or(""),
                &period.starts_on,
                &period.ends_on,
                period.service,
                &handover,
            )?
        {
            named.push(trip);
        }
    }
    if let [only] = named.as_slice() {
        return Ok(only.tab_id.clone());
    }
    let chosen = stay_trip(
        &verified,
        &period.starts_on,
        &period.ends_on,
        period.service,
        nets,
    )?;
    Ok(chosen
        .map(|i| verified[i].tab_id.clone())
        .unwrap_or_default())
}
