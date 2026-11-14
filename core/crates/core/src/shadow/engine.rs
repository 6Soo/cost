//! Rust 판정 엔진: DB 읽기 어댑터(`read_plan_input`) + U9 `plan`. 환불 짝 연결은 2차 전환 전까지 Python 다리에서 받는다.

use std::collections::BTreeMap;

use super::{PlanEngine, PlanRequest, PythonBridge, ShadowError, Target, Values};
use crate::pipeline::{links_from, overlay_context};
use crate::plan::plan;
use crate::store::read_plan_input;

pub struct RustEngine {
    /// 환불 연결 출처. 요청 `context.links`가 없을 때 쓴다.
    pub links: Option<PythonBridge>,
}

impl PlanEngine for RustEngine {
    fn plan(&self, request: &PlanRequest) -> Result<Vec<Target>, ShadowError> {
        let mut input = read_plan_input(&request.db)?;
        let context = &request.context;
        overlay_context(
            &mut input,
            context,
            request.transaction_ids.as_deref(),
            request.reconsider,
        );
        let links = if context["links"].is_object() {
            links_from(&context["links"])
        } else if let Some(bridge) = &self.links {
            bridge.refund_links(&request.db, request.transaction_ids.as_deref())?
        } else {
            BTreeMap::new()
        };
        let result = plan(&input, &links).map_err(|_| ShadowError::PlanFailed)?;
        Ok(result
            .targets
            .into_iter()
            .map(|t| {
                let [
                    state,
                    source,
                    basis,
                    item,
                    description,
                    display_tab_id,
                    trip_id,
                ] = t.values;
                Target {
                    id: t.id,
                    values: Values {
                        state,
                        source,
                        basis,
                        item,
                        description,
                        display_tab_id,
                        trip_id,
                    },
                }
            })
            .collect())
    }
}
