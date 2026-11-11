// E2 KB card entry module: the three operations the orchestration (..collect_kb_card.mjs)
// and adapter (./adapter.mjs, EGO_ENTRY_CONTRACT) use.
//
// Browser surface is supplied by a context module, and site operation strings (selectors) come only
// from the user's config, keyed by role. No site selector/role is guessed; when required roles,
// the context, or the TaskSpace name are absent, this module stops honestly with
// CAPTURE_REQUIRED. Usernames/credentials/cert/OTP are never inputs and automation never handles
// them; login steps stay with the user (see docs/playbooks/kb-script-usage.md).
//
// Environment:
//   KB_CARD_BROWSER_CONTEXT  context module specifier (file URL/path/importable spec). Seam:
//       createCapture({space, selectors, operation, args}) -> capture
//       capture.snapshot(roles)                       -> { [role]: {present:boolean,text?:string} }
//       capture.armDownloadEvent()                    -> event (event.wait())
//       capture.activate(role)                        -> download control activation
//       capture.saveAs(event, destinationPath)         -> {savedPath}  (same round)
//       capture.fill(role, value)                      -> period input fill
//       capture.query(role)                            -> 조회 control invocation
//   If KB_CARD_BROWSER_CONTEXT is unset and no injection exists, the shipped default context
//   (./ego_context.mjs, the ego-browser TaskSpace/Page binding) is imported. It only works inside
//   an ego-browser node process or a synthetic-injected task; live screen shapes/parsing remain
//   NOT_VERIFIED until the user-run real session.
//   KB_CARD_SELECTORS   JSON {"space"?: name, "roles": {role: selector}} (flat maps accepted).
//   KB_CARD_SPACE_NAME  TaskSpace name; per-call `spaceName` arg wins; otherwise config.space.
//
// Canonical role names (documented contract; users supply the selector strings, never guessed):
//   session, dateFloor, dateCeiling (screen allowed-dates)
//   dateStartInput, dateEndInput, searchControl, periodEchoSource, periodEchoStart, periodEchoEnd,
//     summaryResults, downloadControl (download round)
// Missing roles/context/space -> CAPTURE_REQUIRED. A summary that clearly reads zero short-circuits to
// no_data WITHOUT arming/activating a download (conservative, locale/format dependent; boundary numbers
// like 10/100/1000 and unrecognized text are NOT treated as zero).

import { readFile, stat } from "node:fs/promises";
import path from "node:path";
import { pathToFileURL } from "node:url";

import { AdapterError } from "./adapter.mjs";
import { SOURCE_FILES_PREFIX, SOURCES } from "./policy.mjs";
import { reserveAbsentPath } from "./validation.mjs";

// Test/embedding injection seam (synthetic verification only). Real use: env vars / adapter CLI args.
let injected = null;

export function setEntryRuntime({ browserContext = null, selectors = null, spaceName = null } = {}) {
  injected = {
    browserContext: browserContext ?? null,
    selectors: selectors ?? null,
    spaceName: spaceName ?? null,
  };
}

export function resetEntryRuntime() {
  injected = null;
}

const datePattern = /^\d{4}-\d{2}-\d{2}$/;

function isIsoDate(value) {
  if (typeof value !== "string" || !datePattern.test(value)) return false;
  const [y, m, d] = value.split("-").map(Number);
  const dt = new Date(Date.UTC(y, m - 1, d));
  return dt.getUTCFullYear() === y && dt.getUTCMonth() === m - 1 && dt.getUTCDate() === d;
}

function errMessage(err) {
  if (err && typeof err === "object" && typeof err.code === "string" && typeof err.message === "string") {
    return `${err.code}: ${err.message}`;
  }
  return String(err && err.message ? err.message : err);
}

function protocolFailure(message) {
  return new AdapterError("EGO_PROTOCOL", message);
}

function captureRequired(message) {
  return new AdapterError("CAPTURE_REQUIRED", message);
}

// Clear-zero reading only: anchored leading zero with an optional unit, or explicit no-data prose.
// Boundary numbers that merely END in zero ("10", "100", "1,000", "검색 100건") do NOT match.
// Unrecognized/blank summaries do not match and never become a zero claim.
const ZERO_SUMMARY = /^0(?:\s*(?:건|rows?|records?|results?|transactions?|items?|entries?))?$/i;
const NO_DATA_WORDS = /^(?:no|none|without)(?:\s+(?:data|results?|records?|transactions?|matches?|items?|entries?))?$/i;

function looksLikeZeroSummary(text) {
  if (typeof text !== "string") return false;
  const normalized = text.replace(/\s+/g, " ").trim().replace(/[.;:,]+$/, "");
  return ZERO_SUMMARY.test(normalized) || NO_DATA_WORDS.test(normalized);
}

async function importContextModule(spec) {
  const value = String(spec).trim();
  try {
    if (value.startsWith("file:")) return await import(value);
    if (/^[A-Za-z]:[\\/]/.test(value) || value.startsWith("/") || value.startsWith("\\\\") || value.includes("/\\")) {
      return await import(pathToFileURL(value).href);
    }
    return await import(value);
  } catch (err) {
    throw captureRequired(`browser context module is not importable: ${value} (${errMessage(err)})`);
  }
}

async function loadBrowserContext() {
  if (injected?.browserContext) {
    if (typeof injected.browserContext === "string") return importContextModule(injected.browserContext);
    if (typeof injected.browserContext.createCapture === "function") return injected.browserContext;
    throw captureRequired("injected browserContext must export createCapture({space,selectors,operation,args})");
  }
  const spec = process.env.KB_CARD_BROWSER_CONTEXT;
  if (typeof spec === "string" && spec.trim() !== "") {
    const module = await importContextModule(spec);
    if (typeof module.createCapture !== "function") {
      throw captureRequired("KB_CARD_BROWSER_CONTEXT module must export createCapture({space,selectors,operation,args})");
    }
    return module;
  }
  // shipped default: ego-browser TaskSpace/Page binding (fails honestly outside its runtime)
  return await import("./ego_context.mjs");
}

async function loadSelectorRoles() {
  if (injected?.selectors) return normalizeSelectorConfig(injected.selectors, "injected selector config");
  const spec = process.env.KB_CARD_SELECTORS;
  if (typeof spec !== "string" || spec.trim() === "") {
    throw captureRequired(
      "no selector config: set KB_CARD_SELECTORS to a JSON file {\"space\"?:name,\"roles\":{role:selector}}; " +
        "site operation strings come from the user/procedure and are never guessed",
    );
  }
  let parsed;
  try {
    parsed = JSON.parse(await readFile(spec, "utf8"));
  } catch (err) {
    throw captureRequired(`KB_CARD_SELECTORS is not readable JSON: ${spec} (${errMessage(err)})`);
  }
  return normalizeSelectorConfig(parsed, `KB_CARD_SELECTORS (${spec})`);
}

function normalizeSelectorConfig(config, origin) {
  if (config === null || typeof config !== "object" || Array.isArray(config)) {
    throw captureRequired(`${origin} must be a JSON object: {"space"?:name,"roles":{role:selector}} or a flat role->selector map`);
  }
  const roles = config.roles !== undefined ? config.roles : config;
  if (roles === null || typeof roles !== "object" || Array.isArray(roles)) {
    throw captureRequired(`${origin} must contain a "roles" object mapping role -> selector string`);
  }
  for (const [role, selector] of Object.entries(roles)) {
    if (typeof selector !== "string" || selector.trim() === "") {
      throw captureRequired(`${origin} role "${role}" must map to a non-empty selector string`);
    }
  }
  return {
    space: typeof config.space === "string" && config.space.trim() !== "" ? config.space.trim() : null,
    roles: { ...roles },
    sources: config.sources ?? {},
  };
}

async function resolveSpace(args) {
  if (typeof args?.spaceName === "string" && args.spaceName.trim() !== "") return args.spaceName.trim();
  if (injected?.spaceName !== null && injected?.spaceName !== undefined && String(injected.spaceName).trim() !== "") {
    return String(injected.spaceName).trim();
  }
  if (typeof process.env.KB_CARD_SPACE_NAME === "string" && process.env.KB_CARD_SPACE_NAME.trim() !== "") {
    return process.env.KB_CARD_SPACE_NAME.trim();
  }
  const config = await loadSelectorRoles();
  return config.space ?? "";
}

async function openCapture(operation, args) {
  const config = await loadSelectorRoles();
  if (config.sources[args?.source]) Object.assign(config.roles, normalizeSelectorConfig({ roles: config.sources[args.source] }, "source roles").roles);
  const browserContext = await loadBrowserContext();
  if (typeof browserContext.createCapture !== "function") {
    throw captureRequired("browser context must export createCapture({space,selectors,operation,args})");
  }
  const space = await resolveSpace(args);
  if (space === "") {
    throw captureRequired("no TaskSpace name: pass --space-name, config.space, KB_CARD_SPACE_NAME, or inject one (tests)");
  }
  const capture = await browserContext.createCapture({ space, selectors: config.roles, operation, args });
  if (capture === null || typeof capture !== "object") {
    throw protocolFailure("browser context createCapture must return a capture object");
  }
  return { capture, roles: config.roles };
}

function requireRole(roles, role) {
  const selector = roles[role];
  if (typeof selector !== "string" || selector.trim() === "") {
    throw captureRequired(
      `selector not provided for role "${role}"; provide it via the selector config / user procedure (never guessed)`,
    );
  }
  return selector;
}

function readRole(snapshot, role) {
  const entry = snapshot !== null && typeof snapshot === "object" ? snapshot[role] : undefined;
  const present = entry && typeof entry === "object" ? entry.present : undefined;
  if (typeof present !== "boolean") {
    throw protocolFailure(`capture.snapshot role "${role}" must be { present: boolean, text?: string }`);
  }
  const text = typeof entry.text === "string" && entry.text.trim() !== "" ? entry.text.trim() : null;
  return { present, text };
}

// probeSession: true only when the session role is present (거짓 양성 금지).
export async function probeSession(args = {}) {
  const { capture, roles } = await openCapture("probeSession", args);
  requireRole(roles, "session");
  const snapshot = await capture.snapshot(["session"]);
  return { authenticated: readRole(snapshot, "session").present === true };
}

// readScreenAllowedDates: both roles observed as calendar dates, or null (no execution-date fallback).
export async function readScreenAllowedDates({ source, spaceName } = {}) {
  const { capture, roles } = await openCapture("readScreenAllowedDates", { source, spaceName });
  for (const role of ["dateFloor", "dateCeiling"]) requireRole(roles, role);
  const snapshot = await capture.snapshot(["dateFloor", "dateCeiling"]);
  const floor = readRole(snapshot, "dateFloor");
  const ceiling = readRole(snapshot, "dateCeiling");
  if (floor.present !== true || ceiling.present !== true) return null;
  if (!isIsoDate(floor.text) || !isIsoDate(ceiling.text)) {
    throw protocolFailure("screen date values must be YYYY-MM-DD");
  }
  return { floor: floor.text, ceiling: ceiling.text };
}

function safeNamePart(raw, fallback) {
  const cleaned = typeof raw === "string" ? raw.replace(/[\\/:*?"<>|\u0000-\u001f]+/g, "-").trim() : "";
  if (cleaned === "" || cleaned === "." || cleaned === ".." || /^\.+$/.test(cleaned)) return fallback;
  return cleaned.slice(0, 180);
}

function sourceSlug(source) {
  if (source === SOURCES.DOMESTIC) return "domestic";
  if (source === SOURCES.OVERSEAS) return "overseas";
  return null;
}

async function assertSavedFile(filePath) {
  try {
    const info = await stat(filePath);
    if (!info.isFile() || info.size === 0) {
      throw new AdapterError("save_failed", `saved file missing or empty: ${filePath}`);
    }
  } catch (err) {
    if (err instanceof AdapterError) throw err;
    throw new AdapterError("file_missing_after_save", `saved file not readable: ${filePath} (${errMessage(err)})`);
  }
}

// download: fill requested period -> 조회 -> read the observed source/start/end echo + summary
// (filling and clicking alone is never treatment of success; unobservable echoes stop loudly) ->
// clear-zero summary short-circuits to no_data without touching a download control -> otherwise arm
// event -> activate -> same-round save -> byte verification. Timeouts/failures never re-click.
export async function download({ source, startDate, endDate, outDir, spaceName } = {}) {
  if (!isIsoDate(startDate) || !isIsoDate(endDate)) {
    throw protocolFailure("download startDate/endDate must be YYYY-MM-DD");
  }
  if (typeof outDir !== "string" || outDir.trim() === "") {
    throw protocolFailure("download outDir must be a non-empty path");
  }
  const { capture, roles } = await openCapture("download", { source, startDate, endDate, outDir, spaceName });
  const required = [
    "dateStartInput", "dateEndInput", "searchControl",
    "periodEchoSource", "periodEchoStart", "periodEchoEnd",
    "summaryResults", "downloadControl",
  ];
  for (const role of required) requireRole(roles, role);

  await capture.fill("dateStartInput", startDate);
  await capture.fill("dateEndInput", endDate);
  await capture.query("searchControl");

  const snapshot = await capture.snapshot(required);
  for (const role of ["periodEchoSource", "periodEchoStart", "periodEchoEnd"]) {
    const observed = readRole(snapshot, role);
    if (observed.present !== true || observed.text === null) {
      throw captureRequired(`조회 결과 확인 불가: "${role}" was not observed after 조회 (occlusion/selector gap, not success)`);
    }
  }
  const summary = readRole(snapshot, "summaryResults");
  if (summary.present !== true) {
    throw captureRequired('조회 결과 확인 불가: "summaryResults" was not observed after 조회');
  }
  if (looksLikeZeroSummary(summary.text)) {
    return { status: "no_data", pageTotalCount: 0, summaryAvailable: true };
  }
  const countMatch = /^(?:총\s*)?([0-9]+(?:,[0-9]{3})*)\s*(?:건|rows?|records?)?$/.exec(summary.text ?? "");
  const observedCount = countMatch ? Number(countMatch[1].replaceAll(",", "")) : null;

  let control = readRole(snapshot, "downloadControl");
  if (roles.exportOpenControl) {
    await capture.activate("exportOpenControl");
    control = readRole(await capture.snapshot(["downloadControl"]), "downloadControl");
  }
  if (control.present !== true) {
    // 화면에 저장 제어가 없음: 성공 추정 금지, 크게 멈춘다.
    throw new AdapterError("download_control_missing", "download control not present on screen");
  }

  let event;
  try {
    event = await capture.armDownloadEvent(); // 실제 저장 제어 누르기 전에 대기 설치
  } catch (err) {
    throw new AdapterError("no_download_event", `armDownloadEvent failed: ${errMessage(err)}`);
  }
  if (event === null || typeof event !== "object" || typeof event.wait !== "function") {
    throw protocolFailure("capture.armDownloadEvent must return an event with wait()");
  }

  try {
    await capture.activate("downloadControl");
  } catch (err) {
    throw new AdapterError("download_failed", `activate download control failed: ${errMessage(err)}`);
  }

  let info = null;
  try {
    info = await event.wait();
  } catch (err) {
    throw new AdapterError("no_download_event", `download event did not fire: ${errMessage(err)}`);
  }
  if (info !== null && info !== undefined && typeof info !== "object") {
    throw protocolFailure("download event payload must be an object when present");
  }

  const slug = sourceSlug(source);
  const prefix = slug === null ? null : SOURCE_FILES_PREFIX[slug];
  const base = prefix !== null && prefix !== undefined ? safeNamePart(prefix, "kb-card-download") : "kb-card-download";
  const suggested = info && typeof info === "object" && typeof info.suggestedFilename === "string"
    ? safeNamePart(info.suggestedFilename, "")
    : "";
  const destination = await reserveAbsentPath(
    `${outDir}${outDir.endsWith(path.sep) ? "" : path.sep}${suggested !== "" ? suggested : `${base}-${startDate}-${endDate}`}`,
  );

  let saved = null;
  try {
    saved = await capture.saveAs(event, destination);
  } catch (err) {
    throw new AdapterError("save_failed", `saveAs failed: ${errMessage(err)}`);
  }
  const savedPath = saved && typeof saved === "object" && typeof saved.savedPath === "string" && saved.savedPath !== ""
    ? saved.savedPath
    : destination;
  await assertSavedFile(savedPath);

  // Only observed values are forwarded: no guessed counts.
  return {
    status: "downloaded",
    savedPath,
    ...(Number.isSafeInteger(observedCount) ? { pageTotalCount: observedCount, summaryAvailable: true } : {}),
    ...(observedCount === null && info !== null && info !== undefined && typeof info === "object" &&
      Number.isInteger(info.pageTotalCount) && info.pageTotalCount >= 0 ? { pageTotalCount: info.pageTotalCount } : {}),
    ...(info !== null && info !== undefined && typeof info === "object" && info.summaryAvailable === true
      ? { summaryAvailable: true } : {}),
  };
}

export default { probeSession, readScreenAllowedDates, download, setEntryRuntime, resetEntryRuntime };
