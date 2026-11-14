//! 이력 없는 행의 신규 판정과 이력 복원. 원본: `app/automatic_classification.py`의 `_classify_new_row`·
//! `_restore_historical_row`·`_quarter_destination`.

use super::input::{FIELDS, RefundLink, Row, card_row, evidence_of, set, text, txn_of};
use super::{Ctx, POLICY, PlanError};
use crate::dates::{RowDates, completed_period, parse_iso, quarter_of};
use crate::region::is_fukutake_purchase;
use crate::trips::{
    InferOptions, card_trip_candidates, card3820_owner_policy, infer_item, infer_trip_in,
};
use serde_json::Value;
use std::collections::BTreeMap;

const USER_SOURCES: [&str; 3] = ["user_decision", "user_exception", "owner_booking"];
const CODE_SOURCES: [&str; 3] = ["inference", "auto_inferred", "code_inference"];
const GENERIC_ITEMS: [&str; 3] = ["기타경비", "현지경비", "여행경비"];

pub(super) enum Fresh {
    /// 정책상 보호(3820 정책에도 분기 귀속에도 맞지 않는 거래).
    Protected,
    Unchanged,
    Changed,
}

/// `observed_quarter`: 날짜 칸의 앞 10자로 분기 탭과 설명을 만든다.
fn observed_quarter(row: &Row) -> Option<(String, String)> {
    if !text(row, "parse_error").is_empty() || !text(row, "conflict_reason").is_empty() {
        return None;
    }
    let raw = card_row(row).dates;
    let head: String = RowDates::raw(&raw).chars().take(10).collect();
    let (year, quarter) = quarter_of(parse_iso(&head).ok()?);
    Some((
        format!("quarter:{year}:{quarter}"),
        format!("{year}년 {quarter}분기 기타비용"),
    ))
}

/// `_quarter_destination`: 양수 금액의 구매만 결제 분기로 끝낸다.
fn quarter_destination(row: &Row) -> Option<(String, String)> {
    let positive = row
        .get("amount_krw")
        .and_then(Value::as_i64)
        .is_some_and(|a| a > 0);
    if text(row, "transaction_direction") != "purchase" || !positive {
        return None;
    }
    observed_quarter(row)
}

fn json_object(raw: &str, id: &str, what: &str) -> Result<Value, PlanError> {
    let raw = if raw.is_empty() { "{}" } else { raw };
    serde_json::from_str(raw).map_err(|_| PlanError::Json {
        id: id.to_string(),
        what: what.to_string(),
    })
}

fn with_item(row: &Row, item: &str) -> Row {
    let mut copy = row.clone();
    set(&mut copy, "item", item);
    copy
}

pub(super) fn in_valid(ctx: &Ctx, key: &str) -> bool {
    ctx.valid.get(key).is_some()
}

/// `_restore_historical_row`: 이력이 있는 행은 항목 선택을 지키고 빠진 귀속만 복원한다.
pub(super) fn restore_historical_row(
    ctx: &Ctx,
    row: &Row,
    chosen: &mut Row,
    tid: &str,
) -> Result<(), PlanError> {
    if text(chosen, "item").is_empty() {
        let raw = json_object(&text(row, "raw_row_json"), tid, "raw_row_json")?;
        chosen.insert("raw_row".to_string(), raw);
        let (item, _) = infer_item(&txn_of(chosen));
        set(chosen, "item", item);
    }
    set(chosen, "classification_state", "classified");
    let display = text(row, "display_tab_id");
    let empty_trip =
        text(row, "trip_id").is_empty() && (display.is_empty() || display == "unclassified");
    if !empty_trip || text(chosen, "item") == "분기 기타비용" {
        return Ok(());
    }
    let recorded = ctx.ledger.get(tid);
    let board = ctx.boards.get(&format!("card-{tid}"));
    let decided = ctx.decisions.get(tid);
    let candidates = [
        board.map(|b| b.display_tab_id.clone()).unwrap_or_default(),
        decided.cloned().unwrap_or_default(),
        recorded.map(|r| text(r, "trip_id")).unwrap_or_default(),
        recorded
            .map(|r| text(r, "display_tab_id"))
            .unwrap_or_default(),
    ];
    let mut target = candidates
        .into_iter()
        .find(|v| in_valid(ctx, v) || v == "refunds")
        .unwrap_or_default();
    if !target.is_empty() {
        set(chosen, "display_tab_id", &target);
        set(
            chosen,
            "trip_id",
            if target == "refunds" { "" } else { &target },
        );
        set(
            chosen,
            "classification_basis",
            "TRIP_ASSIGNMENT_RESTORED · 기존 항목 보존 · 기존 장부/분류 이력의 배정 복원",
        );
    } else {
        let options = InferOptions {
            nets: ctx.nets.clone(),
            ..InferOptions::default()
        };
        let (inferred, basis) =
            infer_trip_in(&txn_of(chosen), &ctx.valid_trips, ctx.valid, &options);
        target = inferred;
        if !target.is_empty() {
            set(chosen, "display_tab_id", &target);
            set(chosen, "trip_id", &target);
            set(
                chosen,
                "classification_basis",
                format!("AUTO_TRIP_INFERRED · 낮음 · 기존 항목 보존 · {basis} · {POLICY}"),
            );
        }
    }
    if !target.is_empty() && !USER_SOURCES.contains(&text(row, "classification_source").as_str()) {
        set(chosen, "classification_source", "inference");
    }
    Ok(())
}

fn board_payload(ctx: &Ctx, tid: &str) -> Result<Option<Value>, PlanError> {
    ctx.boards
        .get(&format!("card-{tid}"))
        .map(|b| json_object(&b.payload_json, tid, "board payload"))
        .transpose()
}

fn fact_str<'a>(fact: &'a Value, key: &str) -> &'a str {
    fact.get(key).and_then(Value::as_str).unwrap_or_default()
}

/// `_classify_new_row`: 이력 없는 행을 판정한다. 바뀌지 않으면 `Unchanged`.
#[allow(clippy::too_many_lines)]
pub(super) fn classify_new_row(
    ctx: &Ctx,
    resolved: &BTreeMap<String, Row>,
    row: &Row,
    chosen: &mut Row,
    tid: &str,
    evidence: Option<&Value>,
) -> Result<Fresh, PlanError> {
    let recorded = ctx.ledger.get(tid);
    let board = ctx.boards.get(&format!("card-{tid}"));
    let payload = board_payload(ctx, tid)?;
    let payload_text = |key: &str| {
        payload
            .as_ref()
            .and_then(|p| p.get(key))
            .and_then(Value::as_str)
            .unwrap_or_default()
            .to_string()
    };
    if board.is_some() && text(chosen, "item").is_empty() {
        set(chosen, "item", payload_text("item"));
    }
    let recorded_item = recorded.map(|r| text(r, "item")).unwrap_or_default();
    if !recorded_item.is_empty() {
        set(chosen, "item", recorded_item);
    }
    let recorded_tab = recorded
        .map(|r| {
            let trip = text(r, "trip_id");
            if trip.is_empty() {
                text(r, "display_tab_id")
            } else {
                trip
            }
        })
        .unwrap_or_default();
    let existing_tab = [
        board.map(|b| b.display_tab_id.clone()).unwrap_or_default(),
        recorded_tab.clone(),
    ]
    .into_iter()
    .find(|v| in_valid(ctx, v) || v == "refunds")
    .unwrap_or_default();
    if !existing_tab.is_empty()
        && !(in_valid(ctx, &text(chosen, "trip_id"))
            || in_valid(ctx, &text(chosen, "display_tab_id")))
    {
        set(
            chosen,
            "trip_id",
            if existing_tab == "refunds" {
                ""
            } else {
                &existing_tab
            },
        );
        set(chosen, "display_tab_id", &existing_tab);
    }
    let source = text(row, "classification_source");
    // TRIP-036: 원천에 묶인 예약 이용기간은 새 판정에서도 결제일 근접보다 앞선다.
    let fresh = existing_tab.is_empty() && !USER_SOURCES.contains(&source.as_str());
    let completed = completed_period(&card_row(row).dates).is_some();
    let fact = if ctx.reconsider || completed || fresh {
        evidence
    } else {
        None
    };
    let direction = text(row, "transaction_direction");
    let valid_fact = fact.filter(|f| {
        f.as_object().is_some_and(|m| !m.is_empty())
            && f.get("source_hash").and_then(Value::as_str)
                == Some(text(row, "source_hash").as_str())
            && in_valid(ctx, fact_str(f, "trip_id"))
            && direction == "purchase"
    });
    let basis = text(row, "classification_basis");
    let automatic_quarter = CODE_SOURCES.contains(&source.as_str())
        && text(row, "item") == "분기 기타비용"
        && text(row, "trip_id").is_empty()
        && text(row, "display_tab_id").starts_with("quarter:")
        && [
            "실제 여행 후보 없음 · 결제일 기준 분기 기타비용",
            "일반 준비기간 추론 폐지",
        ]
        .iter()
        .any(|marker| basis.contains(marker));
    let specific = |chosen: &Row| infer_item(&txn_of(&with_item(chosen, ""))).0;
    if let (Some(f), true) = (valid_fact, automatic_quarter) {
        let item = Some(fact_str(f, "item"))
            .filter(|i| !i.is_empty())
            .map_or_else(|| specific(chosen), str::to_string);
        set(chosen, "item", item);
        set(chosen, "description", "");
    }
    let link: Option<&RefundLink> = ctx.links.link(tid);
    let recorded_correction = valid_fact.is_some()
        && !existing_tab.is_empty()
        && existing_tab != "refunds"
        && source == "inference"
        && link.is_none()
        && payload
            .as_ref()
            .is_none_or(|_| payload_text("confirmed_by") == "automatic")
        && (recorded_tab.is_empty() || recorded_tab == existing_tab);
    let merchant = text(row, "merchant").to_lowercase();
    let airfare_ota = merchant.contains("gotogate") || merchant.contains("고투게이트");
    let residual_with_fact = valid_fact.is_some() && source == "owner_card_residual";
    if (residual_with_fact || (airfare_ota && source == "owner_card_residual"))
        && existing_tab.is_empty()
    {
        let verified = valid_fact
            .map(|f| fact_str(f, "item"))
            .filter(|i| !i.is_empty());
        let item = verified.map_or_else(|| specific(chosen), str::to_string);
        set(chosen, "item", item);
        set(chosen, "description", "");
    }
    if valid_fact.is_none()
        && !airfare_ota
        && existing_tab.is_empty()
        && text(row, "card_tail") == "3820"
        && direction == "purchase"
    {
        match card3820_owner_policy(&txn_of(chosen), ctx.valid) {
            // 특수 카드 정책에 맞지 않아도 분기 귀속이 가능하면 아래 공통 추론으로 간다.
            None if quarter_destination(chosen).is_none() => return Ok(Fresh::Protected),
            None => {}
            Some(policy) => {
                set(chosen, "item", policy.item);
                set(chosen, "description", policy.description);
                set(chosen, "display_tab_id", policy.display_tab_id);
                set(chosen, "trip_id", policy.trip_id);
                set(chosen, "classification_state", "classified");
                set(chosen, "classification_source", policy.source);
                set(chosen, "classification_basis", policy.basis);
                return Ok(Fresh::Changed);
            }
        }
    }
    let original = link
        .filter(|l| !l.inferred)
        .and_then(|l| resolved.get(&l.original_id))
        .filter(|o| !text(o, "item").is_empty());
    let mut item_basis;
    if let Some(original) = original {
        set(chosen, "item", text(original, "item"));
        set(chosen, "trip_id", text(original, "trip_id"));
        set(chosen, "display_tab_id", text(original, "display_tab_id"));
        item_basis = "검증된 원결제 항목·여행 상속".to_string();
    } else {
        let raw = json_object(&text(row, "raw_row_json"), tid, "raw_row_json")?;
        chosen.insert("raw_row".to_string(), raw);
        let (item, found) = infer_item(&txn_of(chosen));
        set(chosen, "item", item);
        item_basis = found;
        if ctx.reconsider {
            let more = specific(chosen);
            if GENERIC_ITEMS.contains(&text(chosen, "item").as_str()) {
                set(chosen, "item", more);
            }
            item_basis = "기존 항목·카드 업종·서비스 용도 재대조".to_string();
        }
    }
    let mut applied_fact = None;
    if let Some(f) = valid_fact
        && text(chosen, "display_tab_id") != "refunds"
        && text(chosen, "item") != "분기 기타비용"
        && (existing_tab.is_empty() || recorded_correction)
    {
        applied_fact = Some(f);
        let trip = fact_str(f, "trip_id");
        set(chosen, "trip_id", trip);
        set(chosen, "display_tab_id", trip);
        let fact_item = fact_str(f, "item");
        if ["", "기타경비", "현지경비", "여행경비"].contains(&text(chosen, "item").as_str())
            && !fact_item.is_empty()
        {
            set(chosen, "item", fact_item);
        }
        let Some(why) = f.get("basis").and_then(Value::as_str) else {
            return Err(PlanError::Json {
                id: tid.to_string(),
                what: "evidence basis".to_string(),
            });
        };
        item_basis.push_str(&format!(" · 예약 이용기간 근거 우선: {why}"));
    }
    let mut quarter_assigned = false;
    let special =
        text(chosen, "display_tab_id") == "refunds" || text(chosen, "item") == "분기 기타비용";
    let trip_basis;
    if special {
        trip_basis = "환불/분기 비용 기존 배정 유지".to_string();
    } else {
        let rerank = ctx.reconsider
            && existing_tab.is_empty()
            && valid_fact.is_none()
            && link.is_none()
            && (source == "inference"
                || (["code_inference", "auto_inferred"].contains(&source.as_str())
                    && basis.contains("다음 여행 준비기간 · ")))
            && !basis.contains("예약 이용기간");
        let completed_evidence = fact.map(evidence_of);
        let options = InferOptions {
            nets: ctx.nets.clone(),
            reconsider: rerank,
            completed_evidence: completed_evidence.as_ref(),
        };
        let (target, inferred_basis) =
            infer_trip_in(&txn_of(chosen), &ctx.valid_trips, ctx.valid, &options);
        if !target.is_empty() {
            set(chosen, "trip_id", &target);
            set(chosen, "display_tab_id", &target);
            trip_basis = match (ctx.reconsider, applied_fact) {
                (true, Some(f)) => fact_str(f, "basis").to_string(),
                (true, None) => card_trip_candidates(&txn_of(chosen), ctx.valid, &ctx.nets)
                    .into_iter()
                    .find(|c| c.trip_id == target)
                    .map_or_else(
                        || "유효 여행 유지 · 이용일 단서 없음".to_string(),
                        |c| c.basis,
                    ),
                (false, _) => inferred_basis,
            };
        } else if let Some((tab, description)) = quarter_destination(chosen).filter(|_| {
            rerank || ["", "unclassified"].contains(&text(chosen, "display_tab_id").as_str())
        }) {
            // PROC-004: 분기로 끝나는 행의 항목은 분기 기타비용이고 사용자 예외·예약만 자기 항목을 지킨다.
            let keep = !text(chosen, "item").is_empty()
                && ["user_exception", "owner_booking"]
                    .contains(&text(chosen, "classification_source").as_str());
            let item = if keep {
                text(chosen, "item")
            } else {
                "분기 기타비용".to_string()
            };
            let description = Some(text(chosen, "description"))
                .filter(|d| !d.is_empty())
                .unwrap_or(description);
            set(chosen, "display_tab_id", tab);
            set(chosen, "trip_id", "");
            set(chosen, "item", item);
            set(chosen, "description", description);
            trip_basis = "실제 여행 후보 없음 · 결제일 기준 분기 기타비용".to_string();
            quarter_assigned = true;
        } else {
            let display = text(chosen, "display_tab_id");
            set(
                chosen,
                "display_tab_id",
                if display.is_empty() {
                    "unclassified"
                } else {
                    &display
                },
            );
            trip_basis = inferred_basis;
        }
    }
    let valid_nonempty = ctx.valid.iter().next().is_some();
    let needs_completion = (quarter_assigned
        && chosen.get("display_tab_id") != row.get("display_tab_id"))
        || (completed
            && valid_fact.is_some()
            && differs(chosen, row, &["trip_id", "display_tab_id", "item"]))
        || (is_fukutake_purchase(&txn_of(row)) && chosen.get("item") != row.get("item"))
        || ctx.reconsider
        || text(row, "classification_state") != "classified"
        || text(row, "item").is_empty()
        || (!special
            && valid_nonempty
            && !(in_valid(ctx, &text(row, "trip_id"))
                || in_valid(ctx, &text(row, "display_tab_id"))))
        || (!existing_tab.is_empty()
            && ["", "unclassified"].contains(&text(row, "display_tab_id").as_str())
            && chosen.get("display_tab_id") != row.get("display_tab_id"));
    if !needs_completion {
        return Ok(Fresh::Unchanged);
    }
    set(chosen, "classification_state", "classified");
    set(chosen, "classification_source", "inference");
    set(
        chosen,
        "classification_basis",
        format!("AUTO_INFERRED · 낮음 · {item_basis} · {trip_basis} · {POLICY}"),
    );
    if ctx.reconsider {
        let unchanged = !differs(chosen, row, &["item", "trip_id", "display_tab_id"]);
        if unchanged && !["", "inference"].contains(&source.as_str()) {
            set(chosen, "classification_source", &source);
        }
        let now = text(chosen, "classification_basis");
        set(
            chosen,
            "classification_basis",
            format!("CODE_REVIEW · {now}"),
        );
    }
    if original.is_some() {
        set(chosen, "classification_source", "refund_original");
        set(
            chosen,
            "classification_basis",
            format!(
                "원거래 승인번호 {}의 배정을 따름",
                text(row, "original_approval_number")
            ),
        );
    }
    if !ctx.reconsider
        && [
            "rule_conflict",
            "inference_conflict",
            "travel_location_hold",
            "booking_evidence_needed",
        ]
        .contains(&source.as_str())
    {
        let earlier: String = basis.chars().take(600).collect();
        let now = text(chosen, "classification_basis");
        set(
            chosen,
            "classification_basis",
            format!("{now} · 이전 단서: {earlier}"),
        );
    }
    Ok(Fresh::Changed)
}

fn differs(chosen: &Row, row: &Row, keys: &[&str]) -> bool {
    keys.iter().any(|k| chosen.get(*k) != row.get(*k))
}

/// 판정 열 일곱 개의 현재 값.
pub(super) fn values(row: &Row) -> [String; 7] {
    FIELDS.map(|k| text(row, k))
}
