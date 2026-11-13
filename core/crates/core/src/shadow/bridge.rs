//! Python 다리 `tools/core_bridge/cli.py plan` 호출. 다리는 DB를 `mode=ro`로만 연다.

use std::io::Write;
use std::path::PathBuf;
use std::process::{Command, Stdio};

use serde_json::{Value, json};

use super::{PlanEngine, PlanRequest, ShadowError, Target, parse_targets};

pub struct PythonBridge {
    pub python: String,
    pub repo_root: PathBuf,
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
        let script = self.repo_root.join("tools/core_bridge/cli.py");
        let mut child = Command::new(&self.python)
            .arg("-I")
            .arg(&script)
            .arg("plan")
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
        parse_targets(&response["result"])
    }
}

fn bridge_failed() -> ShadowError {
    ShadowError::PythonBridgeFailed("PYTHON_BRIDGE_FAILED".into())
}
