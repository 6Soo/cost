//! 여행 추론. 원본: `app/automatic_classification.py`의 `infer_trip`·`infer_item`·`_card3820_owner_policy`.

use super::candidates::card_trip_candidates;
use super::region::{is_online_purchase_for_owner_card, transaction_region};
use super::select::{
    Canonical, FUKUTAKE_BASIS, card_trip_allowed, fukutake_trips, is_fukutake_purchase,
    period_or_preparation, regional_trips,
};
use super::{Nets, Trip, Txn};
use crate::dates::{CardRow, Evidence, RowDates, TripTab, excluded, parse_iso, quarter_of};
use regex::Regex;
use std::sync::LazyLock;

/// `infer_trip`의 선택 인자.
#[derive(Debug, Clone, Default)]
pub struct InferOptions<'a> {
    pub nets: Nets,
    pub reconsider: bool,
    pub completed_evidence: Option<&'a Evidence>,
}

fn non_empty(s: &str) -> Option<String> {
    (!s.is_empty()).then(|| s.to_string())
}

fn card_row(t: &Txn) -> CardRow {
    CardRow {
        dates: RowDates {
            approval_date: non_empty(&t.approval_date),
            posting_date: non_empty(&t.posting_date),
        },
        trip_id: non_empty(&t.trip_id),
        display_tab_id: non_empty(&t.display_tab_id),
        source_hash: non_empty(&t.source_hash),
    }
}

fn trip_tab(t: &Trip) -> TripTab {
    TripTab {
        trip_id: non_empty(&t.trip_id),
        tab_id: non_empty(&t.tab_id),
        starts_on: non_empty(&t.starts_on),
        ends_on: t.ends_on.clone(),
        deleted: t.deleted,
        archived: t.archived,
    }
}

/// 가장 알맞은 실제 여행과 근거를 고른다. 약한 동률은 고정 순서로 풀고 그 사실을 근거에 적는다.
pub fn infer_trip(t: &Txn, trips: &[Trip], opts: &InferOptions) -> (String, String) {
    infer_trip_in(t, trips, &Canonical::new(trips), opts)
}

/// `infer_trip`의 `_canonical` 변형: 같은 계획에서 이미 검증한 여행을 다시 검증하지 않는다.
/// `trips`는 완료 기간 판정(`excluded`)에만 쓴다.
pub fn infer_trip_in(
    t: &Txn,
    trips: &[Trip],
    canonical: &Canonical,
    opts: &InferOptions,
) -> (String, String) {
    let tabs: Vec<TripTab> = trips.iter().map(trip_tab).collect();
    if excluded(&card_row(t), &tabs, opts.completed_evidence, false) {
        return (String::new(), "PROC-072 · 완료 기간 자료".to_string());
    }
    let allowed: Vec<&Trip> = canonical
        .iter()
        .filter(|trip| card_trip_allowed(t, trip))
        .collect();
    if let Some(preferred) = fukutake_trips(t, &allowed) {
        let id = preferred.first().map(|trip| trip.trip_id.clone());
        return (id.unwrap_or_default(), FUKUTAKE_BASIS.to_string());
    }
    if !opts.reconsider {
        for key in [&t.trip_id, &t.display_tab_id] {
            if allowed.iter().any(|trip| &trip.trip_id == key) {
                return (key.clone(), "기존 실제 여행 유지".to_string());
            }
        }
    }
    let regional: Vec<Trip> = regional_trips(t, &allowed, true)
        .into_iter()
        .cloned()
        .collect();
    let valid = Canonical::from_validated(regional);
    let mut ranked = card_trip_candidates(t, &valid, &opts.nets);
    if !ranked.is_empty() {
        let starts = |id: &str| {
            valid
                .get(id)
                .map(|trip| trip.starts_on.clone())
                .unwrap_or_default()
        };
        ranked.sort_by(|a, b| {
            b.score
                .cmp(&a.score)
                .then_with(|| starts(&a.trip_id).cmp(&starts(&b.trip_id)))
                .then_with(|| a.trip_id.cmp(&b.trip_id))
        });
        let ties = ranked.iter().filter(|c| c.score == ranked[0].score).count();
        let suffix = if ties > 1 {
            format!(" · 동률 {ties}개 중 일정·ID 고정 순서로 선택")
        } else {
            String::new()
        };
        return (
            ranked[0].trip_id.clone(),
            format!("{}{suffix}", ranked[0].basis),
        );
    }
    // 이용일이 없거나 해석되지 않으면 가장 최근에 시작한 실제 여행(기존 경로 보존).
    if parse_iso(&t.approval_date).is_err()
        && let Some(latest) = valid
            .iter()
            .max_by(|a, b| (&a.starts_on, &a.trip_id).cmp(&(&b.starts_on, &b.trip_id)))
    {
        return (
            latest.trip_id.clone(),
            "이용일 단서 없음 · 가장 최근 시작한 실제 여행 선택".to_string(),
        );
    }
    (
        String::new(),
        "PROC-004 · 이용일을 포함하는 여행 없음 · 결제일 분기 기타비용".to_string(),
    )
}

/// 지정 카드(3820) 사용자 정책의 결과.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct OwnerPolicy {
    pub item: String,
    pub description: String,
    pub display_tab_id: String,
    pub trip_id: String,
    pub basis: String,
    pub source: &'static str,
}

/// 지정 카드 3820 정책. 싱가포르 기간 예외 → 해외 현장은 기간 안 여행 → 그 밖은 분기 기타비용. 해당 없으면 `None`.
pub fn card3820_owner_policy(t: &Txn, canonical: &Canonical) -> Option<OwnerPolicy> {
    if t.card_tail != "3820" || t.transaction_direction.as_deref() != Some("purchase") {
        return None;
    }
    let kind = t.transaction_kind.to_lowercase();
    if ["refund", "cancel", "취소", "승인"]
        .iter()
        .any(|marker| kind.contains(marker))
    {
        return None;
    }
    if !t.parse_error.is_empty() || t.amount_krw.is_none_or(|amount| amount <= 0) {
        return None;
    }
    let day_text = if t.approval_date.is_empty() {
        t.posting_date.as_str()
    } else {
        t.approval_date.as_str()
    };
    let occurred = parse_iso(day_text).ok()?;
    let day = day_text;
    let singapore: Vec<&Trip> = canonical
        .iter()
        .filter(|trip| {
            trip.destination == "싱가포르"
                && !trip.starts_on.is_empty()
                && trip.ends_on.as_deref().is_some_and(|end| {
                    !end.is_empty() && trip.starts_on.as_str() <= day && day <= end
                })
        })
        .collect();
    let item_or = |fallback: &str| {
        if t.item.is_empty() {
            fallback.to_string()
        } else {
            t.item.clone()
        }
    };
    if ("2026-09-19"..="2026-09-24").contains(&day) {
        let [only] = singapore.as_slice() else {
            return None;
        };
        return Some(OwnerPolicy {
            item: item_or("현지경비"),
            description: t.description.clone(),
            display_tab_id: only.trip_id.clone(),
            trip_id: only.trip_id.clone(),
            basis: "사용자 예외: 2026-09-19~2026-09-24 카드 3820 사용내역은 싱가포르 여행에 배정"
                .to_string(),
            source: "user_exception",
        });
    }
    if transaction_region(t) == "overseas" {
        let all: Vec<&Trip> = canonical.iter().collect();
        let regional = regional_trips(t, &all, false);
        let candidates = period_or_preparation(&regional, day);
        if !is_online_purchase_for_owner_card(t, &candidates) {
            if candidates.is_empty() {
                return None;
            }
            let owned: Vec<Trip> = candidates.into_iter().cloned().collect();
            let options = InferOptions {
                reconsider: true,
                ..InferOptions::default()
            };
            let (target, basis) = infer_trip_in(
                t,
                &owned,
                &Canonical::from_validated(owned.clone()),
                &options,
            );
            return Some(OwnerPolicy {
                item: if t.item.is_empty() {
                    infer_item(t).0
                } else {
                    t.item.clone()
                },
                description: t.description.clone(),
                display_tab_id: target.clone(),
                trip_id: target,
                basis: format!("AUTO_INFERRED · 낮음 · 해외 사용 · 국가 일치 불필요 · {basis}"),
                source: "inference",
            });
        }
    }
    let (year, quarter) = quarter_of(occurred);
    Some(OwnerPolicy {
        item: "분기 기타비용".to_string(),
        description: format!("{year}년 {quarter}분기 기타비용"),
        display_tab_id: format!("quarter:{year}:{quarter}"),
        trip_id: String::new(),
        basis: "사용자 규칙: 기존 대사 후 남은 카드 3820 거래를 분기 기타비용으로 분류".to_string(),
        source: "owner_card_residual",
    })
}

const ITEM_GROUPS: [(&str, &str); 11] = [
    ("주차비", r"주차|parking"),
    ("주유비", r"주유|충전소|gas station|fuel"),
    ("통행료", r"통행료|고속도로|유료도로|터널|toll"),
    (
        "항공료",
        r"항공|airline|airways|aviation|gotogate|고투게이트",
    ),
    (
        "렌터카",
        r"렌터카|렌트카|rent.?a.?car|rent.?car|rent.?lease",
    ),
    (
        "숙박비",
        r"숙박|호텔|여관|모텔|펜션|리조트|hotel|inn\b|resort|agoda|booking\.com|airbnb|ryokan",
    ),
    (
        "식비",
        r"음식|식당|한식|중식|일식|양식|제과|커피|카페|식음료|국밥|김밥|칼국수|restaurant|cafe|coffee|bakery",
    ),
    (
        "식비",
        r"편의점|슈퍼|마트|세븐일레븐|이마트24|지에스25|gs25|\bcu\b|seven.?eleven|7.?eleven|family.?mart|lawson|mini.?stop|convenience|supermarket",
    ),
    (
        "교통비",
        r"택시|철도|버스|지하철|승차권|여객선|taxi|rail|train|subway|transit|ferry",
    ),
    (
        "입장료",
        r"입장|관람|박물관|수목원|미술관|공연|전시|museum|admission",
    ),
    ("여행경비", r"여행|관광|투어|tour|trip\.com|klook"),
];

static ITEM_REGEX: LazyLock<Vec<(&'static str, Regex)>> = LazyLock::new(|| {
    ITEM_GROUPS
        .iter()
        .map(|(item, pattern)| {
            (
                *item,
                Regex::new(&format!("(?i){pattern}")).expect("item regex"),
            )
        })
        .collect()
});

/// 업종·서비스 용도 어휘로 항목을 정한다(기존 항목이 있으면 유지).
pub fn infer_item(t: &Txn) -> (String, String) {
    if is_fukutake_purchase(t)
        && !["user_decision", "user_exception", "owner_booking"]
            .contains(&t.classification_source.as_str())
    {
        return (
            "입장료".to_string(),
            "사용자 규칙: FUKUTAKE FOUNDATION 미술관 입장료".to_string(),
        );
    }
    if !t.item.is_empty() {
        return (t.item.clone(), "기존 항목 유지".to_string());
    }
    let industry = t
        .description_raw
        .strip_prefix("card-category:")
        .unwrap_or("");
    for (text, basis) in [
        (industry, "카드사 업종 공통 규칙"),
        (t.merchant.as_str(), "가맹점 서비스 용도 공통 규칙"),
    ] {
        for (item, regex) in ITEM_REGEX.iter() {
            if regex.is_match(text) {
                return (item.to_string(), basis.to_string());
            }
        }
    }
    if matches!(
        t.transaction_direction.as_deref(),
        Some("refund" | "cancellation")
    ) {
        return (
            "취소·환불".to_string(),
            "원결제 항목 단서 부족 · 취소·환불 원행 용도".to_string(),
        );
    }
    if transaction_region(t) == "overseas" {
        return (
            "현지경비".to_string(),
            "해외 카드 사용 · 세부 업종 단서 부족".to_string(),
        );
    }
    (
        "기타경비".to_string(),
        "업종·용도 단서 부족 · 업무 카드 지출 기본 분류".to_string(),
    )
}
