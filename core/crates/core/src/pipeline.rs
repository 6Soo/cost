//! 계획 입력 조립 공용부: DB에서 읽은 입력 위에 호출자 입력을 얹고 환불 연결을 읽는다.
//! 그림자 실행(`shadow`)과 투영 쓰기(`apply`)가 함께 쓴다. 어느 쪽도 다른 쪽을 가져오지 않는다.

use std::collections::{BTreeMap, BTreeSet};

use serde_json::Value;

use crate::plan::{PlanInput, RefundLink};

/// 요청 `context.links`(Python 다리 `links` 출력과 같은 모양)를 환불 연결로 읽는다.
pub fn links_from(value: &Value) -> BTreeMap<String, RefundLink> {
    let text = |v: &Value, key: &str| v[key].as_str().unwrap_or_default().to_owned();
    value
        .as_object()
        .map(|m| {
            m.iter()
                .map(|(tid, link)| {
                    let status = if link["status"].is_null() {
                        text(link, "link_state")
                    } else {
                        text(link, "status")
                    };
                    let link = RefundLink {
                        original_id: text(link, "original_id"),
                        inferred: link["inferred"].as_bool().unwrap_or(false),
                        status,
                    };
                    (tid.clone(), link)
                })
                .collect()
        })
        .unwrap_or_default()
}

/// 호출자가 넘기는 입력(trips·nets·evidence)과 범위·재검토 여부를 DB에서 읽은 입력 위에 얹는다.
pub fn overlay_context(
    input: &mut PlanInput,
    context: &Value,
    transaction_ids: Option<&[String]>,
    reconsider: bool,
) {
    if let Some(trips) = context["trips"].as_array() {
        input.trips = trips.clone();
    }
    if let Some(nets) = context["nets"].as_object() {
        input.nets = nets
            .iter()
            .filter_map(|(k, v)| Some((k.clone(), v.as_i64()?)))
            .collect();
    }
    if let Some(evidence) = context["evidence"].as_object() {
        input.evidence = evidence
            .iter()
            .map(|(k, v)| (k.clone(), v.clone()))
            .collect();
    }
    input.selected = transaction_ids.map(|ids| ids.iter().cloned().collect::<BTreeSet<_>>());
    input.reconsider = reconsider;
}
