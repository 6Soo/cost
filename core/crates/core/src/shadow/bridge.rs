//! Python 다리 `tools/core_bridge/cli.py plan` 호출. 다리는 DB를 `mode=ro`로만 연다.

use std::collections::BTreeMap;
use std::io::Write;
use std::path::PathBuf;
use std::process::{Command, Stdio};

use serde_json::{Value, json};

use crate::plan::RefundLink;

use super::{PlanEngine, PlanRequest, ShadowError, Target, parse_targets};

pub struct PythonBridge {
    pub python: String,
    pub repo_root: PathBuf,
}

impl PythonBridge {
    /// 다리 한 명령을 호출해 `result`를 돌려준다.
    fn call(&self, command: &str, body: &Value) -> Result<Value, ShadowError> {
        let script = self.repo_root.join("tools/core_bridge/cli.py");
        let mut child = Command::new(&self.python)
            .arg("-I")
            .arg(&script)
            .arg(command)
            .stdin(Stdio::piped())
            .stdout(Stdio::piped())
            .stderr(Stdio::null())
            .spawn()
            .map_err(|_| ShadowError::PythonBridgeFailed("PYTHON_NOT_STARTED".into()))?;
        let mut stdin = child.stdin.take().ok_or_else(bridge_failed)?;
        writeln!(stdin, "{body}").map_err(|_| bridge_failed())?;
        drop(stdin);
        let out = child.wait_with_output()?;
        let line = String::from_utf8_lossy(&out.stdout);
        let response: Value =
            serde_json::from_str(line.lines().next().unwrap_or("")).map_err(|_| bridge_failed())?;
        if response["ok"] != json!(true) {
            let code = response["error"]["code"].as_str().unwrap_or("UNKNOWN");
            return Err(ShadowError::PythonBridgeFailed(code.to_owned()));
        }
        Ok(response["result"].clone())
    }

    /// 2차 전환 전까지 환불 짝 연결은 Python 결과를 쓴다(`links` kind=refund).
    pub fn refund_links(
        &self,
        db: &std::path::Path,
        transaction_ids: Option<&[String]>,
    ) -> Result<BTreeMap<String, RefundLink>, ShadowError> {
        let mut body = json!({"kind": "refund", "db": db.to_string_lossy()});
        if let Some(ids) = transaction_ids {
            body["transaction_ids"] = json!(ids);
        }
        let result = self.call("links", &body)?;
        let found = result["links"].as_object().ok_or_else(bridge_failed)?;
        Ok(found
            .iter()
            .map(|(tid, link)| {
                let text = |key: &str| link[key].as_str().unwrap_or_default().to_owned();
                let link = RefundLink {
                    original_id: text("original_id"),
                    inferred: link["inferred"].as_bool().unwrap_or(false),
                    status: text("status"),
                };
                (tid.clone(), link)
            })
            .collect())
    }
}

impl PlanEngine for PythonBridge {
    fn plan(&self, request: &PlanRequest) -> Result<Vec<Target>, ShadowError> {
        let mut body = json!({
            "db": request.db.to_string_lossy(),
            "reconsider": request.reconsider,
        });
        if let Some(ids) = &request.transaction_ids {
            body["transaction_ids"] = json!(ids);
        }
        for key in ["trips", "nets", "evidence"] {
            if !request.context[key].is_null() {
                body[key] = request.context[key].clone();
            }
        }
        parse_targets(&self.call("plan", &body)?)
    }
}
fn bridge_failed() -> ShadowError {
    ShadowError::PythonBridgeFailed("PYTHON_BRIDGE_FAILED".into())
}
