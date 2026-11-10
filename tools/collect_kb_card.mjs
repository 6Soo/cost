#!/usr/bin/env node
// 국민 기업카드 국내/해외 매입 원본 수집 + 검증 경계 스크립트(합성/실환경 공용 오케스트레이션).
// 소유 경계: 조회기간 계산(p1) → 세션 검증/터치 없음 → 소스별 화면 허용일 → 어댑터 다운로드 → 산출물 검증 → 별도 파서 검증 연결 → 매니페스트.
// 불가/미검증 경계: 로그인·인증서·OTP 자동화 없음, 운영 DB 읽기/가져오기·금융 apply·백업·예약 등록 없음, ₩/ID/부호 가공 없음, 원문 비노출.
import { readdir, writeFile } from "node:fs/promises";
import path from "node:path";
import process from "node:process";
import { pathToFileURL } from "node:url";

import { AdapterError, DOWNLOAD_DATA_CODES, assertSessionAlive, createEgoBrowserAdapter } from "./kb_card_collection/adapter.mjs";
import {
  PolicyError,
  SOURCE_URLS,
  buildPeriod,
  sourcesFromFlag,
} from "./kb_card_collection/policy.mjs";
import { buildNoDataRecord, validateDownloaded } from "./kb_card_collection/validation.mjs";
import { PARSER_VERIFICATION_NOT_RUN, runParserVerification } from "./kb_card_collection/verify_python.mjs";

const SCHEMA = "cost.kb-card-collection-report.v1";
const BAD_VERIFICATION = new Set(["failed", "no_data_unverified"]);

const USAGE = `usage: collect_kb_card.mjs [options]

  --execution-date YYYY-MM-DD   실행일(필수, 결과 보고에 사용)
  --last-use-date YYYY-MM-DD     호출자가 넘긴 마지막 국민 이용일(시작일=당일, 차감 없음)
  --out-dir PATH                 새 보호 폴더(존재+비어있지 않음=거부, 원본/매니페스트 저장)
  --source domestic|overseas|both 소스 선택(기본 both)
  --python CMD                   파서 검증 Python(미지정 시 NOT_RUN 기록)
  --parser-module PATH           파서 검증 드라이버(.py, 미지정 시 NOT_RUN 기록)
  --parser-timeout-ms N          파서 검증 타임아웃(기본 60000)
  --ego-entry PATH               ego-browser 진입점(.mjs). 미지정 시 어댑터 없이 성공 불가
  --ego-bin NAME                 ego-browser 실행 파일(기본 ego-browser, PATH 탐색)
  --space-name NAME              재개할 TaskSpace 이름(미지정 시 어댑터 구성 거부)
  -h, --help                     이 도움말
`;

function cliError(message) {
  return { error: message };
}

function parseArgs(argv) {
  const values = {};
  for (let i = 0; i < argv.length; i += 1) {
    const arg = argv[i];
    if (arg === "-h" || arg === "--help") return { help: true };
    if (!arg.startsWith("--")) return cliError(`unexpected argument: ${arg}`);
    const eq = arg.indexOf("=");
    const name = eq === -1 ? arg : arg.slice(0, eq);
    const inline = eq === -1 ? undefined : arg.slice(eq + 1);
    const next = () => {
      if (inline !== undefined) return inline;
      i += 1;
      if (i >= argv.length) throw new Error(`missing value for ${name}`);
      return argv[i];
    };
    switch (name) {
      case "--execution-date": values.executionDate = next(); break;
      case "--last-use-date": values.lastUseDate = next(); break;
      case "--out-dir": values.outDir = next(); break;
      case "--source": values.source = next(); break;
      case "--python": values.python = next(); break;
      case "--parser-module": values.parserModule = next(); break;
      case "--parser-timeout-ms": values.parserTimeoutMs = next(); break;
      case "--ego-entry": values.egoEntry = next(); break;
      case "--ego-bin": values.egoBin = next(); break;
      case "--space-name": values.spaceName = next(); break;
      default: return cliError(`unknown option: ${name}`);
    }
  }
  return { values };
}

async function prepareRunDir(outDir) {
  let entries = null;
  try {
    entries = await readdir(outDir);
  } catch (err) {
    if (err && err.code === "ENOENT") return;
    throw new AdapterError("OUTPUT_UNUSABLE");
  }
  if (entries.length > 0) {
    throw new AdapterError("OUTPUT_NOT_EMPTY");
  }
}

function normalizeFailure(err) {
  if (err instanceof AdapterError) return { code: err.code, message: err.message };
  if (err instanceof PolicyError) return { code: "POLICY_REJECTED", message: err.message };
  return { code: "INTERNAL_ERROR", message: "unexpected failure while collecting", error: (err && typeof err.name === "string") ? err.name : "Error" };
}

function rowForUnknownSource(source) {
  return {
    source,
    sourceUrl: null,
    query: { startDate: null, endDate: null, postingAxis: "매입일" },
    summary: { available: false, pageTotalCount: null },
    file: null,
    verification: { status: "failed", failure: "unknown_source" },
    parserVerification: null,
  };
}

async function parserResultFor(fileRow, { source, parser }) {
  const preservedPath = fileRow.file?.savedPath ?? fileRow.savedPath;
  if (parser && typeof parser.verify === "function") {
    return parser.verify({ source, filePath: preservedPath });
  }
  if (parser && parser.command && parser.module) {
    return runParserVerification({
      command: parser.command,
      module: parser.module,
      filePath: preservedPath,
      timeoutMs: parser.timeoutMs,
    });
  }
  return { status: PARSER_VERIFICATION_NOT_RUN, reason: "not configured for this run" };
}

async function writeManifest(manifestPath, payload) {
  const body = `${JSON.stringify(payload, null, 2)}\n`;
  await writeFile(manifestPath, body, { encoding: "utf8", flag: "wx" });
}

// 실행 전체가 멈춘 경우에도 매니페스트까지 남긴다(원문 없이 상태만).
async function finish(report, outDir, { stopped = null, manifestPath } = {}) {
  report.status = stopped
    ? "stopped"
    : (report.rows.some((row) => BAD_VERIFICATION.has(row.verification?.status))
      ? "completed_with_failures" : "ok");
  if (manifestPath) report.manifestPath = manifestPath;
  if (stopped) report.stopped = stopped;
  if (report.status === "ok" || report.status === "completed_with_failures") {
    report.parserVerificationNotRun = report.rows.some((row) => row.parserVerification?.status === PARSER_VERIFICATION_NOT_RUN);
    report.countsUnverified = report.rows.some((row) => row.verification?.status === "ok_count_unverified");
  }
  if (outDir) {
    try {
      const target = manifestPath || report.manifestPath;
      await writeManifest(target, {
        schemaVersion: "cost.kb-card-collection-manifest.v1",
        runId: report.runId,
        generatedAt: report.generatedAt,
        executionDate: report.executionDate,
        requestedSources: report.requestedSources,
        rows: report.rows,
        ...(stopped ? { stopped } : {}),
      });
    } catch (err) {
      report.manifestError = err && err.code === "EEXIST"
        ? "manifest already exists in run folder; refusing to overwrite"
        : "manifest write failed";
    }
  }
  return report;
}

export async function runCollector({
  adapter,
  lastUseDate,
  executionDate,
  outDir,
  sources,
  runId,
  parser = {},
  now,
} = {}) {
  const generatedAt = new Date(now ?? Date.now()).toISOString();
  const report = {
    schema: SCHEMA,
    runId: runId || path.basename(path.resolve(outDir || ".")),
    generatedAt,
    executionDate: executionDate ?? null,
    requestedSources: [],
    rows: [],
    outDir: outDir ? path.resolve(outDir) : null,
    manifestPath: outDir ? path.join(path.resolve(outDir), "manifest.json") : null,
  };
  let selected = [];
  let exec = null;
  let start = null;
  try {
    if (typeof executionDate !== "string" || !executionDate.trim()) {
      throw new PolicyError("executionDate is required");
    }
    exec = parseDate(executionDate, "executionDate");
    report.executionDate = exec;
    start = parseDate(lastUseDate, "lastUseDate");
    if (!Array.isArray(sources) || sources.length === 0) {
      throw new PolicyError("sources must be a non-empty array");
    }
    const unknown = [];
    for (const source of sources) {
      if (!SOURCE_URLS[source]) {
        unknown.push(source);
        continue;
      }
      selected.push(source);
    }
    for (const source of unknown) report.rows.push(rowForUnknownSource(source));
    report.requestedSources = selected;
    if (outDir) await prepareRunDir(outDir);
  } catch (err) {
    return finish(report, outDir ? path.resolve(outDir) : null, { stopped: normalizeFailure(err) });
  }

  if (!adapter || typeof adapter.probeSession !== "function") {
    return finish(report, report.outDir, {
      stopped: {
        code: "ADAPTER_REQUIRED",
        message: "no browser adapter: supply --ego-entry/--space-name or a programmatic adapter; no silent stub fallback",
      },
    });
  }
  if (typeof adapter.readScreenAllowedDates !== "function" || typeof adapter.download !== "function") {
    return finish(report, report.outDir, {
      stopped: {
        code: "ADAPTER_REQUIRED",
        message: "browser adapter is incomplete: probeSession/readScreenAllowedDates/download are all required",
      },
    });
  }

  try {
    await assertSessionAlive({ probe: () => adapter.probeSession() });
  } catch (err) {
    return finish(report, report.outDir, { stopped: normalizeFailure(err) });
  }

  for (const source of selected) {
    let period;
    try {
      const ceiling = await adapter.readScreenAllowedDates({ source });
      period = buildPeriod({ lastUseDate: start, executionDate: exec, allowedCeiling: ceiling });
      if (period.status !== "OK") {
        throw new AdapterError(period.status, period.reason || "period not resolved");
      }
    } catch (err) {
      return finish(report, report.outDir, { stopped: normalizeFailure(err) });
    }

    let download;
    try {
      download = await adapter.download({ source, startDate: period.startDate, endDate: period.endDate, outDir: report.outDir });
    } catch (err) {
      if (err instanceof AdapterError && DOWNLOAD_DATA_CODES.has(err.code)) {
        download = { status: "failed", code: err.code };
      } else {
        return finish(report, report.outDir, { stopped: normalizeFailure(err) });
      }
    }

    const base = { source, sourceUrl: SOURCE_URLS[source], startDate: period.startDate, endDate: period.endDate, postingAxis: period.postingAxis };

    if (download.status === "no_data") {
      report.rows.push(
        buildNoDataRecord({
          ...base,
          pageTotalCount: download.pageTotalCount ?? null,
          summaryAvailable: download.summaryAvailable,
        }),
      );
      continue;
    }
    if (download.status === "failed") {
      report.rows.push({
        ...base,
        summary: { available: false, pageTotalCount: null },
        file: null,
        verification: { status: "failed", ...(download.code ? { code: download.code } : {}) },
        parserVerification: { status: PARSER_VERIFICATION_NOT_RUN, reason: "no preserved file to verify" },
      });
      continue;
    }
    if (download.status !== "downloaded") {
      return finish(report, report.outDir, { stopped: { code: "ADAPTER_ERROR", message: "adapter download returned an unsupported status" } });
    }

    const savedPath = typeof download.savedPath === "string" ? download.savedPath : "";
    const savedRelative = savedPath === "" ? null : path.relative(report.outDir, path.resolve(savedPath));
    const insideOutDir = savedRelative !== null && savedRelative !== "" && !savedRelative.startsWith("..") && !path.isAbsolute(savedRelative);
    const row = insideOutDir
      ? await validateDownloaded({
          savedPath,
          ...base,
          pageTotalCount: download.pageTotalCount ?? null,
          summaryAvailable: download.summaryAvailable,
          suggestedFilename: download.suggestedFilename,
        })
      : {
          source: base.source,
          sourceUrl: base.sourceUrl,
          query: { startDate: base.startDate, endDate: base.endDate, postingAxis: base.postingAxis },
          summary: { available: false, pageTotalCount: null },
          file: null,
          verification: { status: "failed", failure: "saved_path_outside_run_dir" },
          parserVerification: null,
        };
    row.parserVerification = insideOutDir && row.file
      ? await parserResultFor(row, { source, parser })
      : { status: PARSER_VERIFICATION_NOT_RUN, reason: "no preserved file to verify" };
    report.rows.push(row);
  }

  return finish(report, report.outDir, { stopped: null, manifestPath: report.manifestPath });
}

function parseDate(value, label) {
  if (typeof value !== "string" || !/^\d{4}-\d{2}-\d{2}$/.test(value.trim())) {
    throw new PolicyError(`${label} must be YYYY-MM-DD`);
  }
  return value.trim();
}

function parseTimeout(value) {
  const n = Number(value);
  if (!Number.isInteger(n) || n <= 0) throw new PolicyError("parser timeout must be a positive integer");
  return n;
}

async function main() {
  let parsed;
  try {
    parsed = parseArgs(process.argv.slice(2));
  } catch (err) {
    process.stderr.write(`${JSON.stringify({ status: "stopped", code: "CLI_USAGE", message: err.message })}\n`);
    process.exitCode = 2;
    return;
  }
  if (parsed.help) {
    process.stdout.write(USAGE);
    return;
  }
  if (parsed.error) {
    process.stderr.write(`${JSON.stringify({ status: "stopped", code: "CLI_USAGE", message: parsed.error })}\n`);
    process.exitCode = 2;
    return;
  }
  const values = parsed.values ?? {};
  if (values.source !== undefined) {
    const resolved = sourcesFromFlag(values.source);
    if (resolved === null) {
      process.stderr.write(`${JSON.stringify({ status: "stopped", code: "UNKNOWN_SOURCE", message: `--source must be domestic, overseas, or both` })}\n`);
      process.exitCode = 2;
      return;
    }
    values.sources = resolved;
  }
  let parser;
  if (values.parserModule) {
    let timeoutMs = 60000;
    if (values.parserTimeoutMs !== undefined) {
      try { timeoutMs = parseTimeout(values.parserTimeoutMs); } catch (err) {
        process.stderr.write(`${JSON.stringify({ status: "stopped", code: "CLI_USAGE", message: err.message })}\n`);
        process.exitCode = 2;
        return;
      }
    }
    parser = { command: values.python, module: values.parserModule, timeoutMs };
  }
  let adapter = null;
  if (values.egoEntry) {
    try {
      adapter = createEgoBrowserAdapter({
        entryPath: values.egoEntry,
        spaceName: values.spaceName ?? null,
        egoBin: values.egoBin ?? "ego-browser",
      });
    } catch (err) {
      process.stderr.write(`${JSON.stringify({ status: "stopped", code: "ADAPTER_REQUIRED", message: err.message })}\n`);
      process.exitCode = 2;
      return;
    }
  } else {
    process.stderr.write(`${JSON.stringify({ status: "stopped", code: "ADAPTER_REQUIRED", message: "--ego-entry/--space-name are required to run the browser adapter; no silent stub fallback" })}\n`);
    process.exitCode = 2;
    return;
  }
  const report = await runCollector({
    adapter,
    lastUseDate: values.lastUseDate,
    executionDate: values.executionDate,
    outDir: values.outDir,
    sources: values.sources,
    parser,
  });
  process.stdout.write(`${JSON.stringify(report, null, 2)}\n`);
  if (report.status === "stopped") process.exitCode = 2;
}

const invokedDirectly = process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href;
if (invokedDirectly) await main();
