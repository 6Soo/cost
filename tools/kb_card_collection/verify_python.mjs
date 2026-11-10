// 기존 Python 파서를 별도 읽기 전용 검증 단계로 호출. 출력은 건수/라벨만 남겨 원문 비노출 계약을 지킨다.
import { spawn } from "node:child_process";

export const PARSER_VERIFICATION_NOT_RUN = "PARSER_VERIFICATION_NOT_RUN";

const SAFE_TOKEN = /^[A-Za-z0-9_.:-]{0,40}$/;

function pickCounts(text) {
  const out = {};
  if (!text || typeof text !== "object") return out;
  for (const key of ["rows", "parse_issues"]) {
    if (Number.isInteger(text[key]) && text[key] >= 0) out[key] = text[key];
  }
  if (typeof text.parser === "string" && SAFE_TOKEN.test(text.parser)) out.parser = text.parser;
  if (typeof text.channel === "string" && SAFE_TOKEN.test(text.channel)) out.channel = text.channel;
  return out;
}

export function runParserVerification({ command, module: modulePath, filePath, timeoutMs = 60000 } = {}) {
  if (!command || !modulePath || !filePath) {
    return Promise.resolve({ status: PARSER_VERIFICATION_NOT_RUN, reason: "parser verify not configured" });
  }
  return new Promise((resolve) => {
    let settled = false;
    let stdout = "";
    let stderr = "";
    const finish = (result) => {
      if (settled) return;
      settled = true;
      clearTimeout(timer);
      resolve(result);
    };
    const argv = Array.isArray(command) ? command : [command];
    let child;
    try {
      child = spawn(argv[0], [...argv.slice(1), modulePath, "--file", filePath, "--json"], {
        windowsHide: true,
        stdio: ["ignore", "pipe", "pipe"],
      });
    } catch {
      return finish({ status: "PARSER_VERIFICATION_UNAVAILABLE", reason: "cannot start parser verification" });
    }
    const timer = setTimeout(() => {
      try { child.kill(); } catch { /* process already gone */ }
      finish({ status: "PARSER_VERIFICATION_TIMEOUT" });
    }, timeoutMs);
    child.stdout.on("data", (d) => { stdout += d.toString("utf8"); });
    child.stderr.on("data", (d) => { stderr += d.toString("utf8"); });
    child.on("error", () => { finish({ status: "PARSER_VERIFICATION_UNAVAILABLE", reason: "parser command unavailable" }); });
    child.on("close", (code) => {
      if (code !== 0) {
        return finish({ status: code === 3 ? "PARSER_VERIFICATION_UNAVAILABLE" : "PARSER_VERIFICATION_FAILED", code });
      }
      try {
        const parsed = JSON.parse(stdout);
        if (!parsed || typeof parsed !== "object") return finish({ status: "PARSER_VERIFICATION_INVALID_OUTPUT" });
        if (parsed.status === "parsed") return finish({ status: "PARSER_VERIFICATION_OK", ...pickCounts(parsed) });
        if (parsed.status === "failed") return finish({ status: "PARSER_VERIFICATION_FAILED" });
        if (parsed.status === "unavailable") return finish({ status: "PARSER_VERIFICATION_UNAVAILABLE" });
        void stderr;
        return finish({ status: "PARSER_VERIFICATION_INVALID_OUTPUT" });
      } catch {
        return finish({ status: "PARSER_VERIFICATION_INVALID_OUTPUT" });
      }
    });
  });
}
