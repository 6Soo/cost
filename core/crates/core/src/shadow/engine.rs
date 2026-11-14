//! 비교용 엔진 어댑터: 운영 파이프라인(`pipeline::run_plan`)과 Python 다리를 `PlanEngine` 뒤에 둔다.

use super::{PlanEngine, PlanRequest, ShadowError, Target, parse_targets};
use crate::bridge::PythonBridge;
use crate::pipeline::run_plan;

pub struct RustEngine {
    /// 환불 연결 출처. 요청 `context.links`가 없을 때 쓴다.
    pub links: Option<PythonBridge>,
}

impl PlanEngine for RustEngine {
    fn plan(&self, request: &PlanRequest) -> Result<Vec<Target>, ShadowError> {
        Ok(run_plan(request, self.links.as_ref())?)
    }
}

impl PlanEngine for PythonBridge {
    fn plan(&self, request: &PlanRequest) -> Result<Vec<Target>, ShadowError> {
        parse_targets(&self.plan_json(
            &request.db,
            request.transaction_ids.as_deref(),
            request.reconsider,
            &request.context,
        )?)
    }
}
