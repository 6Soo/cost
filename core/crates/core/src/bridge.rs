//! Python 다리 `tools/core_bridge/cli.py` 호출. 다리는 DB를 `mode=ro`로만 연다.
//! 2차 전환 전까지 환불 짝 연결(`links`)과 비교용 `plan`을 여기서 받는다.

use std::collections::BTreeMap;
use std::io::Write;
use std::path::{Path, PathBuf};
use std::process::{Command, Stdio};

use serde_json::{Value, json};

use crate::digest::{python_json, sha256_hex};
use crate::plan::RefundLink;

#[derive(Debug, thiserror::Error)]
pub enum BridgeError {
    #[error("PYTHON_BRIDGE_FAILED:{0}")]
    Failed(String),
    #[error("입출력 오류: {0}")]
    Io(#[from] std::io::Error),
}

pub struct PythonBridge {
    pub python: String,
    pub repo_root: PathBuf,
}

impl PythonBridge {
    /// 다리 한 명령을 호출해 `result`를 돌려준다.
    fn call(&self, command: &str, body: &Value) -> Result<Value, BridgeError> {
        let script = self.repo_root.join("tools/core_bridge/cli.py");
        let mut child = Command::new(&self.python)
            .arg("-I")
            .arg(&script)
            .arg(command)
            // 기준선은 이 프로세스의 생산자 선택과 무관하게 항상 Python이다. 부모 환경은 건드리지 않는다.
            .env("WEBLEDGER_LINKS_PRODUCER", "python")
            .env("WEBLEDGER_CLASSIFICATION_WRITER", "python")
            .stdin(Stdio::piped())
            .stdout(Stdio::piped())
            .stderr(Stdio::null())
            .spawn()
            .map_err(|_| BridgeError::Failed("PYTHON_NOT_STARTED".into()))?;
        let mut stdin = child.stdin.take().ok_or_else(bridge_failed)?;
        writeln!(stdin, "{body}").map_err(|_| bridge_failed())?;
        drop(stdin);
        let out = child.wait_with_output()?;
        let line = String::from_utf8_lossy(&out.stdout);
        let response: Value =
            serde_json::from_str(line.lines().next().unwrap_or("")).map_err(|_| bridge_failed())?;
        if response["ok"] != json!(true) {
            let code = response["error"]["code"].as_str().unwrap_or("UNKNOWN");
            return Err(BridgeError::Failed(code.to_owned()));
        }
        verify_envelope(&response, command, body)?;
        Ok(response["result"].clone())
    }

    /// 다리 `plan` 결과(`{targets:[...]}`). 호출자가 해석한다.
    pub fn plan_json(
        &self,
        db: &Path,
        transaction_ids: Option<&[String]>,
        reconsider: bool,
        context: &Value,
    ) -> Result<Value, BridgeError> {
        let mut body = json!({
            "db": db.to_string_lossy(),
            "reconsider": reconsider,
        });
        if let Some(ids) = transaction_ids {
            body["transaction_ids"] = json!(ids);
        }
        for key in ["trips", "nets", "evidence"] {
            if !context[key].is_null() {
                body[key] = context[key].clone();
            }
        }
        self.call("plan", &body)
    }

    /// 다리 `links` 명령(kind=refund·ota)의 `result`. 그림자 비교가 Python 쪽 값으로 쓴다.
    pub fn links_json(&self, body: &Value) -> Result<Value, BridgeError> {
        self.call("links", body)
    }

    /// 2차 전환 전까지 환불 짝 연결은 Python 결과를 쓴다(`links` kind=refund).
    pub fn refund_links(
        &self,
        db: &Path,
        transaction_ids: Option<&[String]>,
    ) -> Result<BTreeMap<String, RefundLink>, BridgeError> {
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

/// 응답이 이 요청에 대한 것인지(명령·입력 digest)와 Python 커밋 표시(40자리 16진수)를 확인한다.
pub(crate) fn verify_envelope(
    response: &Value,
    command: &str,
    body: &Value,
) -> Result<(), BridgeError> {
    let sha = response["python_sha"].as_str().unwrap_or("");
    let sha_ok = sha.len() == 40 && sha.bytes().all(|b| b.is_ascii_hexdigit());
    let digest_ok = response["input_digest"].as_str() == Some(&sha256_hex(&python_json(body)));
    if response["command"].as_str() == Some(command) && sha_ok && digest_ok {
        Ok(())
    } else {
        Err(BridgeError::Failed("ENVELOPE_MISMATCH".to_owned()))
    }
}

fn bridge_failed() -> BridgeError {
    BridgeError::Failed("PYTHON_BRIDGE_FAILED".into())
}
