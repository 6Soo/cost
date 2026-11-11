// 브라우저 어댑터 경계. 국민 기업카드 조회(국내/해외)에 필요한 최소 표면과 결과 검증만 소유한다.
// 실제 페이지 selector·좌표는 이 저장소의 실행 환경에서 관측되지 않았다(NOT_VERIFIED).
// 기본 진입점은 entry_kb.mjs이며 미관측 선택자만 설정한다.
import { spawn } from "node:child_process";
import { mkdir, readFile, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import path from "node:path";
import process from "node:process";
import { pathToFileURL } from "node:url";

export const EGO_ENTRY_CONTRACT = Object.freeze({
  format: "UTF-8 .mjs run by ego-browser nodejs; one named TaskSpace for the whole goal",
  exports: Object.freeze({
    probeSession: "async () => ({ authenticated: boolean })",
    readScreenAllowedDates: "async ({ source }) => ({ floor: YYYY-MM-DD, ceiling: YYYY-MM-DD } | null)",
    download:
      "async ({ source, startDate, endDate, outDir }) => ({ status: 'downloaded', savedPath, pageTotalCount?, summaryAvailable? } | { status: 'no_data', pageTotalCount? } | { status: 'failed', code })",
  }),
  rules: Object.freeze([
    "resume the same space with taskSpace(name); each round is a fresh process",
    "refs/coordinates are per-snapshot only and never persisted",
    "arm page.waitForEvent('download') before the real save control; never re-click on timeout",
    "download.saveAs() in the same round; preserve originals without overwrite; no raw content in logs/manifest",
    "no credential/cert/OTP automation; hand off to the user on login expiry",
    "report only what the round observed; unmet selectors stay NOT_VERIFIED",
  ]),
});

export class AdapterError extends Error {
  constructor(code, message) {
    super(message ?? code);
    this.name = "AdapterError";
    this.code = code;
  }
}

// 세션 생존은 어댑터 probe 결과로만 판정한다. 콘텐츠·쿠키 원문을 담지 않는 계약.
export async function assertSessionAlive({ probe }) {
  if (typeof probe !== "function") throw new AdapterError("ADAPTER_REQUIRED", "no session probe configured");
  let result;
  try {
    result = await probe();
  } catch (err) {
    if (err instanceof AdapterError) throw err;
    throw new AdapterError("ENV_PROBE_UNVERIFIED", "session probe failed");
  }
  if (!result || typeof result !== "object" || typeof result.authenticated !== "boolean") {
    throw new AdapterError("ENV_PROBE_UNVERIFIED", "session probe returned an invalid result");
  }
  if (!result.authenticated) {
    throw new AdapterError("LOGIN_REQUIRED", "no authenticated enterprise KB session detected");
  }
  return result;
}

// 다운로드 계열 데이터성 실패 코드: 해당 소스 결과행으로 기록하고 다음 소스로 진행한다.
export const DOWNLOAD_DATA_CODES = Object.freeze(new Set([
  "download_failed",
  "no_download_event",
  "download_canceled",
  "save_failed",
  "output_exists",
  "path_exhausted",
  "file_missing_after_save",
]));

function protocolFailure(detail) {
  return new AdapterError("EGO_PROTOCOL", `ego entry result is not usable: ${detail}`);
}

function assertIsoDate(value, label) {
  if (typeof value !== "string" || !/^\d{4}-\d{2}-\d{2}$/.test(value)) {
    throw protocolFailure(`${label} must be YYYY-MM-DD`);
  }
  const [y, m, d] = value.split("-").map(Number);
  const dt = new Date(Date.UTC(y, m - 1, d));
  if (dt.getUTCFullYear() !== y || dt.getUTCMonth() !== m - 1 || dt.getUTCDate() !== d) {
    throw protocolFailure(`${label} is not a calendar date: ${value}`);
  }
  return value;
}

function downloadFailure(code) {
  return new AdapterError(typeof code === "string" && code ? code : "download_failed", "download did not complete");
}

async function defaultRunner({ entryPath, workDir, egoBin, spawnImpl, operation, args, timeoutMs, launchFromFile }) {
  if (!entryPath || !workDir) throw new AdapterError("EGO_PROTOCOL", "runner is not configured");
  let entryModuleUrl;
  try {
    entryModuleUrl = pathToFileURL(entryPath).href;
    await readFile(entryPath);
  } catch {
    throw new AdapterError("EGO_PROTOCOL", `ego entry is not readable: ${entryPath}`);
  }
  const base = path.basename(entryPath, path.extname(entryPath)).replace(/[^A-Za-z0-9_.-]+/g, "_");
  const round = `${base}-${operation}-${process.pid}-${Date.now()}`;
  const launcherPath = path.join(workDir, `${round}.mjs`);
  const launcherSource = [
    `process.env.KB_CARD_SELECTORS = ${JSON.stringify(process.env.KB_CARD_SELECTORS ? path.resolve(process.env.KB_CARD_SELECTORS) : "")};`,
    `const mod = await import(${JSON.stringify(entryModuleUrl)});`,
    `const fn = mod[${JSON.stringify(operation)}];`,
    `const result = await fn(${JSON.stringify(args ?? {})});`,
    `process.stdout.write(JSON.stringify({ ok: true, result }) + "\\n");`,
  ].join("\n");
  try {
    await mkdir(workDir, { recursive: true });
    await writeFile(launcherPath, launcherSource, "utf8");
  } catch {
    throw new AdapterError("EGO_PROTOCOL", "cannot stage ego entry round");
  }
  const child = spawnImpl(egoBin, launchFromFile
    ? ["nodejs", "-e", `await import('${pathToFileURL(launcherPath).href}')`]
    : ["nodejs"], {
    stdio: ["pipe", "pipe", "pipe"],
    windowsHide: true,
  });
  let stdout = "";
  let stderr = "";
  child.stdout?.on("data", (d) => { stdout += d.toString("utf8"); });
  child.stderr?.on("data", (d) => { stderr += d.toString("utf8"); });
  try {
    child.stdin?.end(launchFromFile ? undefined : launcherSource);
  } catch {
    // early-closed stdin surfaces through the round's exit status below
  }
  let timer;
  const closed = new Promise((resolve, reject) => {
    child.on("error", reject);
    child.on("close", (code, signal) => resolve({ code, signal }));
  });
  try {
    const exit = await Promise.race([
      closed,
      new Promise((_, reject) => {
        timer = setTimeout(() => {
          try { child.kill(); } catch { /* already gone */ }
          reject(new AdapterError("EGO_PROTOCOL", "ego-browser round timed out"));
        }, timeoutMs);
        timer.unref?.();
      }),
    ]);
    await rm(launcherPath, { force: true }).catch(() => {});
    if (exit.code !== 0) {
      throw new AdapterError("EGO_PROTOCOL", `ego-browser round failed (code ${exit.code ?? "null"}, signal ${exit.signal ?? "null"})`);
    }
    const trimmed = stdout.trim();
    try {
      const parsed = JSON.parse(trimmed);
      if (parsed && parsed.ok === true && "result" in parsed) return parsed.result;
      return parsed;
    } catch {
      for (const line of trimmed.split(/\r?\n/).reverse()) {
        if (!line.trim()) continue;
        try {
          const parsed = JSON.parse(line);
          if (parsed && typeof parsed === "object") return parsed;
        } catch {
          // not JSON; keep scanning
        }
      }
      throw new AdapterError("EGO_PROTOCOL", "ego entry produced no parseable JSON result");
    }
  } finally {
    if (timer) clearTimeout(timer);
    await rm(launcherPath, { force: true }).catch(() => {});
  }
}

// 실제 ego-browser 연결 어댑터. 검증에서는 runner를 주입해 합성 결과만 흐른다.
export function createEgoBrowserAdapter({
  entryPath,
  spaceName,
  egoBin = "ego-browser",
  workDir,
  runner,
  spawnImpl = spawn,
  timeoutMs = 30000,
  launchFromFile = false,
} = {}) {
  if (!entryPath) throw new AdapterError("ADAPTER_REQUIRED", "ego entry path is required");
  if (!spaceName) throw new AdapterError("ADAPTER_REQUIRED", "task space name is required");
  const run = runner ?? ((request) => defaultRunner({
    entryPath,
    workDir: workDir ?? path.join(tmpdir(), "kb-card-collection"),
    egoBin,
    spawnImpl,
    operation: request.operation,
    args: request.args,
    timeoutMs,
    launchFromFile,
  }));

  return {
    kind: "ego-browser",
    spaceName,

    async probeSession() {
      const result = await run({ operation: "probeSession", args: { spaceName } });
      if (!result || typeof result !== "object" || typeof result.authenticated !== "boolean") {
        throw protocolFailure("probeSession must return { authenticated: boolean }");
      }
      return { authenticated: result.authenticated };
    },

    async readScreenAllowedDates({ source }) {
      const result = await run({ operation: "readScreenAllowedDates", args: { source, spaceName } });
      if (result === null || result === undefined) return null;
      if (typeof result !== "object") throw protocolFailure("readScreenAllowedDates must return an object or null");
      return {
        floor: assertIsoDate(result.floor, "screen.floor"),
        ceiling: assertIsoDate(result.ceiling, "screen.ceiling"),
      };
    },

    async download({ source, startDate, endDate, outDir }) {
      assertIsoDate(startDate, "startDate");
      assertIsoDate(endDate, "endDate");
       const result = await run({ operation: "download", args: { source, startDate, endDate, outDir, spaceName } });
      if (!result || typeof result !== "object") throw protocolFailure("download must return an object");
      if (result.status === "downloaded") {
        if (typeof result.savedPath !== "string" || result.savedPath === "") {
          throw protocolFailure("download.savedPath must be a non-empty path");
        }
        return {
          status: "downloaded",
          savedPath: result.savedPath,
          ...(typeof result.suggestedFilename === "string" ? { suggestedFilename: result.suggestedFilename } : {}),
          ...(Number.isInteger(result.pageTotalCount) && result.pageTotalCount >= 0 ? { pageTotalCount: result.pageTotalCount } : {}),
          ...(result.summaryAvailable === true ? { summaryAvailable: true } : {}),
        };
      }
      if (result.status === "no_data") {
        return {
          status: "no_data",
          ...(Number.isInteger(result.pageTotalCount) && result.pageTotalCount >= 0 ? { pageTotalCount: result.pageTotalCount } : {}),
          ...(result.summaryAvailable === true ? { summaryAvailable: true } : {}),
        };
      }
      if (result.status === "failed") throw downloadFailure(result.code);
      throw protocolFailure(`download status not recognized: ${String(result.status)}`);
    },
  };
}
