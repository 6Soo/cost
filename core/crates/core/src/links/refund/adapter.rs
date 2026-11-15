//! 환불 짝 입출력 어댑터: 원행(`TxnRow`·JSON) → 짝 도출 입력, 짝 결과 → Python 다리 `links`와 같은 모양의 JSON.
//! `costcore links refund`와 그림자 비교가 함께 쓴다.

use serde_json::{Map, Value, json};

use super::{Basis, Exclusion, RefundTxn, Refunds};
use crate::store::projection::TxnRow;

/// 호출자가 보낸 원행의 모양이 다르다. 공개 코드는 `PLAN_RESPONSE_INVALID`다.
#[derive(Debug, Clone, Copy, PartialEq, Eq, thiserror::Error)]
#[error("PLAN_RESPONSE_INVALID")]
pub struct RefundInputInvalid;

/// `TxnRow` → 짝 도출 입력. 열 이름·빈 칸 규칙은 Python `COALESCE(x,'')`와 같다.
pub fn refund_rows(rows: &[TxnRow]) -> Vec<RefundTxn> {
    rows.iter()
        .map(|r| RefundTxn {
            transaction_id: r.transaction_id.clone(),
            issuer: r.issuer.clone(),
            card_tail: r.card_tail.clone(),
            direction: r.transaction_direction.clone(),
            approval_number: r.approval_number.clone(),
            original_approval_number: r.original_approval_number.clone(),
            amount_krw: r.amount_krw,
            approval_date: r.approval_date.clone(),
            posting_date: r.posting_date.clone(),
            merchant: r.merchant.clone(),
            merchant_normalized: r.merchant_normalized.clone(),
            foreign_amount: r.foreign_amount.clone(),
            foreign_currency: r.foreign_currency.clone(),
            duplicate_of: r.duplicate_of.clone(),
            conflict_reason: r.conflict_reason.clone(),
            parse_error: r.parse_error.clone(),
        })
        .collect()
}

/// 호출자가 표준 입력으로 보낸 원행(열 이름 키의 객체 배열, 순서 유지) → 짝 도출 입력. 빈 문자열 열은 null도 받는다
/// (Python `COALESCE(x,'')`). 모양이 다르면 `PlanResponseInvalid`다.
pub fn refund_rows_from_json(value: &Value) -> Result<Vec<RefundTxn>, RefundInputInvalid> {
    let rows = value.as_array().ok_or(RefundInputInvalid)?;
    rows.iter().map(refund_row_from_json).collect()
}

fn refund_row_from_json(row: &Value) -> Result<RefundTxn, RefundInputInvalid> {
    if !row.is_object() {
        return Err(RefundInputInvalid);
    }
    let text = |key: &str| -> Result<String, RefundInputInvalid> {
        match row.get(key) {
            None | Some(Value::Null) => Ok(String::new()),
            Some(Value::String(s)) => Ok(s.clone()),
            Some(_) => Err(RefundInputInvalid),
        }
    };
    let amount_krw = match row.get("amount_krw") {
        None | Some(Value::Null) => None,
        Some(v) => Some(v.as_i64().ok_or(RefundInputInvalid)?),
    };
    let duplicate_of = match row.get("duplicate_of") {
        None | Some(Value::Null) => None,
        Some(Value::String(s)) => Some(s.clone()),
        Some(_) => return Err(RefundInputInvalid),
    };
    Ok(RefundTxn {
        transaction_id: text("transaction_id")?,
        issuer: text("issuer")?,
        card_tail: text("card_tail")?,
        direction: text("transaction_direction")?,
        approval_number: text("approval_number")?,
        original_approval_number: text("original_approval_number")?,
        amount_krw,
        approval_date: text("approval_date")?,
        posting_date: text("posting_date")?,
        merchant: text("merchant")?,
        merchant_normalized: text("merchant_normalized")?,
        foreign_amount: text("foreign_amount")?,
        foreign_currency: text("foreign_currency")?,
        duplicate_of,
        conflict_reason: text("conflict_reason")?,
        parse_error: text("parse_error")?,
    })
}

/// Rust 환불 짝 결과를 Python 다리 `links` 출력과 같은 모양으로 만든다.
pub fn refund_values(refunds: &Refunds) -> Value {
    let links: Map<String, Value> = refunds
        .links()
        .iter()
        .map(|l| {
            let mut out = json!({
                "gross_krw": l.gross_krw, "net_krw": l.net_krw, "original_id": l.original_id,
                "refund_count": l.refund_count, "refund_krw": l.refund_krw,
                "refunds_total_krw": l.refunds_total_krw, "status": l.status.as_str(),
            });
            if let Some(basis) = l.basis {
                out["basis"] = json!(basis.as_str());
                if basis != Basis::MerchantCardForeignAmount {
                    out["inferred"] = json!(l.inferred);
                    out["matching_source"] = json!("automatic");
                }
            }
            (l.refund_id.clone(), out)
        })
        .collect();
    let originals = refunds.originals();
    let groups: Map<String, Value> = originals
        .iter()
        .map(|o| (o.clone(), json!(refunds.group(o))))
        .collect();
    let exclusions: Map<String, Value> = originals
        .iter()
        .map(|o| {
            (
                o.clone(),
                json!(refunds.exclusion(o).map_or("", Exclusion::as_str)),
            )
        })
        .collect();
    let held: Map<String, Value> = refunds
        .held()
        .iter()
        .map(|(k, h)| {
            (
                k.clone(),
                json!({"purchases": h.purchases, "cancellations": h.cancellations}),
            )
        })
        .collect();
    json!({
        "links": links, "groups": groups, "group_exclusions": exclusions,
        "held": held, "review_originals": refunds.review_originals(),
    })
}
