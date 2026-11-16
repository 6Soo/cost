// Hana/IBK collection boundary. Browser selectors come only from a private,
// owner-verified profile; this module never logs in or handles credentials.
import { createHash } from "node:crypto";
import { mkdir, readFile, readdir, realpath, stat, writeFile } from "node:fs/promises";
import { extname, isAbsolute, join, relative, resolve } from "node:path";
import process from "node:process";
import { fileURLToPath } from "node:url";

import { createEgoBrowserAdapter } from "./kb_card_collection/adapter.mjs";
import { buildPeriod, PolicyError } from "./kb_card_collection/policy.mjs";
import { createCapture as createEgoCapture } from "./kb_card_collection/ego_context.mjs";
import { buildNoDataRecord, reserveAbsentPath, validateDownloaded } from "./kb_card_collection/validation.mjs";
import { PARSER_VERIFICATION_NOT_RUN, runParserVerification } from "./kb_card_collection/verify_python.mjs";

export const PROFILE_SCHEMA = "cost.site-card-selector-profile.v1";
export const MANIFEST_SCHEMA = "cost.kb-card-collection-manifest.v1";

const PROVIDERS = Object.freeze({
  hana: Object.freeze({
    issuer: "하나",
    source: "하나 기업카드 이용내역",
    channel: "domestic_acquired",
  }),
  ibk: Object.freeze({
    issuer: "기업",
    source: "IBK 기업카드 이용내역",
    channel: "statement",
  }),
});

const REQUIRED_ROLES = Object.freeze([
  "session",
  "dateFloor",
  "dateCeiling",
  "dateStartInput",
  "dateEndInput",
  "searchControl",
  "periodEchoSource",
  "periodEchoStart",
  "periodEchoEnd",
  "summaryResults",
  "downloadControl",
]);
const OPTIONAL_ROLES = Object.freeze(["exportOpenControl"]);
const ALLOWED_AXES = new Set(["이용일", "승인일", "매입일"]);
const ALLOWED_EXTENSIONS = new Set([".csv", ".xls", ".xlsx"]);
let injectedRuntime = null;

export class CollectionError extends Error {
  constructor(code, message = code) {
    super(message);
    this.name = "CollectionError";
    this.code = code;
  }
}

export function countCheck(parsedCount, screenCount) {
  const valid = (value) => Number.isSafeInteger(value) && value >= 0;
  return valid(parsedCount) && valid(screenCount) && parsedCount === screenCount
    ? { status: "MATCHED", parsedCount, screenCount }
    : {
        status: "FAILED",
        parsedCount: valid(parsedCount) ? parsedCount : null,
        screenCount: valid(screenCount) ? screenCount : null,
      };
}

export function fileEvidence(bytes) {
  const data = Buffer.isBuffer(bytes) ? bytes : Buffer.from(bytes);
  return { bytes: data.length, sha256: createHash("sha256").update(data).digest("hex") };
}

export function setSiteCollectionRuntime({ browserContext = null, profile = null, spaceName = null } = {}) {
  injectedRuntime = { browserContext, profile, spaceName };
}

export function resetSiteCollectionRuntime() {
  injectedRuntime = null;
}

function isIsoDate(value) {
  if (typeof value !== "string" || !/^\d{4}-\d{2}-\d{2}$/.test(value)) return false;
  const [year, month, day] = value.split("-").map(Number);
  const date = new Date(Date.UTC(year, month - 1, day));
  return date.getUTCFullYear() === year && date.getUTCMonth() === month - 1 && date.getUTCDate() === day;
}

function compareDates(left, right) {
  return left < right ? -1 : left > right ? 1 : 0;
}

function normalizeText(value) {
  return typeof value === "string" ? value.replace(/\s+/g, " ").trim() : "";
}

function isPlaceholder(value) {
  return typeof value === "string" && /__|<|>|PLACEHOLDER|OBSERVED_/i.test(value);
}

function profileError(message) {
  return new CollectionError("PROFILE_NOT_VERIFIED", message);
}

export function validateProfile(provider, profile) {
  const issuer = PROVIDERS[provider];
  if (!issuer) throw new CollectionError("UNKNOWN_PROVIDER");
  if (!profile || typeof profile !== "object" || Array.isArray(profile)) {
    throw profileError("private selector profile is required");
  }
  const allowedKeys = new Set([
    "schemaVersion", "provider", "source", "expectedOrigin", "usageUrl", "queryAxis", "sourceEcho", "verification", "selectors",
  ]);
  if (Object.keys(profile).some((key) => !allowedKeys.has(key))) {
    throw profileError("profile contains unsupported fields");
  }
  if (profile.schemaVersion !== PROFILE_SCHEMA || profile.provider !== provider || profile.source !== issuer.source) {
    throw profileError("profile schema or provider does not match the requested issuer");
  }
  if (!ALLOWED_AXES.has(profile.queryAxis)) throw profileError("profile queryAxis must be observed and explicit");
  const verification = profile.verification;
  if (!verification || typeof verification !== "object" || Array.isArray(verification)
      || Object.keys(verification).some((key) => !["status", "observedAt"].includes(key))
      || verification.status !== "OWNER_VERIFIED" || !isIsoDate(verification.observedAt)) {
    throw profileError("profile requires owner verification with an observation date");
  }
  if (typeof profile.expectedOrigin !== "string" || isPlaceholder(profile.expectedOrigin)) {
    throw profileError("profile expectedOrigin is required");
  }
  let origin;
  try {
    const url = new URL(profile.expectedOrigin);
    if (url.protocol !== "https:" || url.origin !== profile.expectedOrigin || url.username || url.password) {
      throw new Error("invalid origin");
    }
    origin = url.origin;
  } catch {
    throw profileError("profile expectedOrigin must be one exact HTTPS origin");
  }
  let usageUrl;
  try {
    if (isPlaceholder(profile.usageUrl)) throw new Error("placeholder usage URL");
    const url = new URL(profile.usageUrl);
    if (url.protocol !== "https:" || url.origin !== origin || url.username || url.password || url.search || url.hash) {
      throw new Error("invalid usage URL");
    }
    usageUrl = url.href;
  } catch {
    throw profileError("profile usageUrl must be an observed HTTPS page on the exact issuer origin");
  }
  const sourceEcho = normalizeText(profile.sourceEcho);
  if (!sourceEcho || sourceEcho.length > 120 || isPlaceholder(sourceEcho)
      || /(?:\d[ -]?){12,19}|[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}/.test(sourceEcho)) {
    throw profileError("profile sourceEcho must be a generic observed label without personal identifiers");
  }
  const selectors = profile.selectors;
  if (!selectors || typeof selectors !== "object" || Array.isArray(selectors)) {
    throw profileError("profile selectors are required");
  }
  const allowedRoles = new Set([...REQUIRED_ROLES, ...OPTIONAL_ROLES]);
  if (Object.keys(selectors).some((role) => !allowedRoles.has(role))) {
    throw profileError("profile contains an unsupported selector role");
  }
  for (const role of REQUIRED_ROLES) {
    if (typeof selectors[role] !== "string" || selectors[role].trim() === "" || selectors[role].length > 400 || isPlaceholder(selectors[role])) {
      throw profileError("profile is missing a required selector role");
    }
  }
  for (const role of OPTIONAL_ROLES) {
    if (selectors[role] !== undefined
        && (typeof selectors[role] !== "string" || selectors[role].trim() === "" || selectors[role].length > 400 || isPlaceholder(selectors[role]))) {
      throw profileError("optional selector role is invalid");
    }
  }
  return {
    schemaVersion: PROFILE_SCHEMA,
    provider,
    source: issuer.source,
    expectedOrigin: origin,
    usageUrl,
    queryAxis: profile.queryAxis,
    sourceEcho,
    verification: { status: "OWNER_VERIFIED", observedAt: verification.observedAt },
    selectors: { ...selectors },
  };
}

async function loadProfileFromFile(profilePath, provider) {
  if (typeof profilePath !== "string" || profilePath.trim() === "") {
    throw profileError("a private profile path is required");
  }
  let parsed;
  try {
    parsed = JSON.parse(await readFile(profilePath, "utf8"));
  } catch {
    throw profileError("private selector profile is unreadable JSON");
  }
  return validateProfile(provider, parsed);
}

async function profileForOperation(provider) {
  if (injectedRuntime?.profile) return validateProfile(provider, injectedRuntime.profile);
  return loadProfileFromFile(process.env.KB_CARD_SELECTORS, provider);
}

function requireRole(profile, role) {
  const selector = profile.selectors[role];
  if (typeof selector !== "string" || selector.trim() === "") {
    throw profileError("profile selector role is missing");
  }
  return selector;
}

function readRole(snapshot, role) {
  const value = snapshot && typeof snapshot === "object" ? snapshot[role] : null;
  if (!value || typeof value !== "object" || typeof value.present !== "boolean") {
    throw new CollectionError("EGO_PROTOCOL", "browser capture returned an invalid role shape");
  }
  return { present: value.present, text: normalizeText(value.text) || null };
}

async function openCapture(provider, operation, args = {}) {
  const profile = await profileForOperation(provider);
  const source = PROVIDERS[provider].source;
  if (args.source !== undefined && args.source !== source) {
    throw profileError("requested source does not match the verified profile");
  }
  const context = injectedRuntime?.browserContext ?? { createCapture: createEgoCapture };
  const space = args.spaceName ?? injectedRuntime?.spaceName;
  if (typeof space !== "string" || !space.trim()) {
    throw new CollectionError("CAPTURE_REQUIRED", "an existing TaskSpace name is required");
  }
  const capture = await context.createCapture({
    space: space.trim(),
    selectors: profile.selectors,
    operation,
    args: { ...args, source },
  });
  if (!capture || typeof capture !== "object" || typeof capture.snapshot !== "function") {
    throw new CollectionError("EGO_PROTOCOL", "browser capture is unavailable");
  }
  if (typeof capture.origin !== "function" || typeof capture.navigate !== "function") {
    throw new CollectionError("ORIGIN_UNVERIFIED", "browser page origin cannot be verified");
  }
  let actualOrigin;
  try {
    actualOrigin = await capture.origin();
  } catch {
    throw new CollectionError("ORIGIN_UNVERIFIED", "browser page origin could not be read");
  }
  if (actualOrigin !== profile.expectedOrigin) {
    throw new CollectionError("ORIGIN_MISMATCH", "browser page does not match the verified issuer origin");
  }
  try {
    await capture.navigate(profile.usageUrl);
    actualOrigin = await capture.origin();
  } catch {
    throw new CollectionError("ORIGIN_UNVERIFIED", "verified issuer usage page could not be opened");
  }
  if (actualOrigin !== profile.expectedOrigin) {
    throw new CollectionError("ORIGIN_MISMATCH", "navigation left the verified issuer origin");
  }
  return { capture, profile };
}

export async function probeSession({ source, spaceName } = {}) {
  const provider = source ? profileProvider(source) : await configuredProvider();
  const { capture, profile } = await openCapture(provider, "probeSession", { source, spaceName });
  requireRole(profile, "session");
  const authenticated = readRole(await capture.snapshot(["session"]), "session").present;
  return { authenticated };
}

export async function readScreenAllowedDates({ source, spaceName } = {}) {
  const { capture, profile } = await openCapture(profileProvider(source), "readScreenAllowedDates", { source, spaceName });
  requireRole(profile, "dateFloor");
  requireRole(profile, "dateCeiling");
  const snapshot = await capture.snapshot(["dateFloor", "dateCeiling"]);
  const floor = readRole(snapshot, "dateFloor");
  const ceiling = readRole(snapshot, "dateCeiling");
  if (!floor.present || !ceiling.present || !isIsoDate(floor.text) || !isIsoDate(ceiling.text)) {
    throw new CollectionError("PERIOD_UNVERIFIED", "screen allowed dates are missing or not ISO dates");
  }
  if (compareDates(floor.text, ceiling.text) > 0) {
    throw new CollectionError("PERIOD_INVALID", "screen date floor is after its ceiling");
  }
  return { floor: floor.text, ceiling: ceiling.text };
}

function profileProvider(source) {
  for (const [provider, config] of Object.entries(PROVIDERS)) {
    if (config.source === source) return provider;
  }
  throw new CollectionError("UNKNOWN_SOURCE");
}

async function configuredProvider() {
  if (injectedRuntime?.profile && PROVIDERS[injectedRuntime.profile.provider]) {
    return injectedRuntime.profile.provider;
  }
  try {
    const candidate = JSON.parse(await readFile(process.env.KB_CARD_SELECTORS, "utf8"));
    if (candidate && PROVIDERS[candidate.provider]) return candidate.provider;
  } catch {
    // Keep profile diagnostics generic; paths and profile contents stay private.
  }
  throw profileError("private selector profile does not identify a supported issuer");
}

function parseScreenCount(text) {
  const normalized = normalizeText(text);
  const match = /^(?:총\s*)?([0-9]+(?:,[0-9]{3})*)(?:\s*(?:건|rows?|records?))?$/i.exec(normalized);
  if (!match) throw new CollectionError("SUMMARY_UNVERIFIED", "screen result count is not an unambiguous integer");
  const count = Number(match[1].replaceAll(",", ""));
  if (!Number.isSafeInteger(count) || count < 0) {
    throw new CollectionError("SUMMARY_UNVERIFIED", "screen result count is outside the safe integer range");
  }
  return count;
}

async function assertEchoes(capture, profile, startDate, endDate) {
  const roles = ["periodEchoSource", "periodEchoStart", "periodEchoEnd", "summaryResults", "downloadControl"];
  for (const role of roles) requireRole(profile, role);
  const snapshot = await capture.snapshot(roles);
  const sourceEcho = readRole(snapshot, "periodEchoSource");
  const startEcho = readRole(snapshot, "periodEchoStart");
  const endEcho = readRole(snapshot, "periodEchoEnd");
  const summary = readRole(snapshot, "summaryResults");
  if (!sourceEcho.present || !startEcho.present || !endEcho.present || !summary.present) {
    throw new CollectionError("QUERY_ECHO_UNVERIFIED", "query result did not expose source, dates, and count");
  }
  if (sourceEcho.text !== profile.sourceEcho
      || startEcho.text !== startDate || endEcho.text !== endDate) {
    throw new CollectionError("QUERY_ECHO_MISMATCH", "observed query source or period differs from the requested values");
  }
  return { count: parseScreenCount(summary.text), snapshot };
}

export async function download({ source, startDate, endDate, outDir, spaceName } = {}) {
  const provider = profileProvider(source);
  if (!isIsoDate(startDate) || !isIsoDate(endDate) || compareDates(startDate, endDate) > 0) {
    throw new CollectionError("PERIOD_INVALID", "requested period is not a valid ISO date range");
  }
  if (typeof outDir !== "string" || !outDir.trim()) {
    throw new CollectionError("OUTPUT_UNUSABLE", "an output directory is required");
  }
  const { capture, profile } = await openCapture(provider, "download", { source, startDate, endDate, outDir, spaceName });
  for (const role of ["dateStartInput", "dateEndInput", "searchControl"]) requireRole(profile, role);
  for (const method of ["fill", "query", "armDownloadEvent", "activate", "saveAs"]) {
    if (typeof capture[method] !== "function") throw new CollectionError("EGO_PROTOCOL", "browser page lacks a required collection action");
  }

  await capture.fill("dateStartInput", startDate);
  await capture.fill("dateEndInput", endDate);
  await capture.query("searchControl");
  let result = await assertEchoes(capture, profile, startDate, endDate);
  if (result.count === 0) return { status: "no_data", pageTotalCount: 0, summaryAvailable: true };

  if (profile.selectors.exportOpenControl) {
    await capture.activate("exportOpenControl");
    result = await assertEchoes(capture, profile, startDate, endDate);
  }
  const control = readRole(result.snapshot, "downloadControl");
  if (!control.present) throw new CollectionError("DOWNLOAD_CONTROL_UNVERIFIED", "verified download control is not present");

  let event;
  try {
    event = await capture.armDownloadEvent();
  } catch {
    throw new CollectionError("NO_DOWNLOAD_EVENT", "download event could not be armed");
  }
  if (!event || typeof event.wait !== "function") {
    throw new CollectionError("EGO_PROTOCOL", "download event does not expose wait()");
  }
  try {
    await capture.activate("downloadControl");
  } catch {
    throw new CollectionError("DOWNLOAD_FAILED", "download control activation failed");
  }
  let eventInfo;
  try {
    eventInfo = await event.wait();
  } catch {
    throw new CollectionError("NO_DOWNLOAD_EVENT", "download event did not complete");
  }
  const suggested = eventInfo && typeof eventInfo.suggestedFilename === "string"
    ? eventInfo.suggestedFilename : "";
  const extension = extname(suggested).toLowerCase();
  if (!ALLOWED_EXTENSIONS.has(extension)) {
    throw new CollectionError("FORMAT_UNVERIFIED", "download did not expose a supported card export extension");
  }

  const outputDirectory = resolve(outDir);
  const target = await reserveAbsentPath(join(outputDirectory, provider + "-" + startDate + "-" + endDate + extension));
  let saved;
  try {
    saved = await capture.saveAs(event, target);
  } catch {
    throw new CollectionError("SAVE_FAILED", "download saveAs failed");
  }
  const savedPath = saved && typeof saved.savedPath === "string" ? saved.savedPath : target;
  if (resolve(savedPath) !== resolve(target)) {
    throw new CollectionError("SAVE_PATH_MISMATCH", "download was saved outside its reserved destination");
  }
  try {
    const info = await stat(savedPath);
    if (!info.isFile() || info.size <= 0) throw new Error("empty");
  } catch {
    throw new CollectionError("FILE_MISSING", "downloaded file is missing or empty");
  }
  const [realOutput, realSaved] = await Promise.all([realpath(outputDirectory), realpath(savedPath)]);
  const relativeSaved = relative(realOutput, realSaved);
  if (!relativeSaved || relativeSaved.startsWith("..") || isAbsolute(relativeSaved)) {
    throw new CollectionError("FILE_OUTSIDE_RUN_DIR", "downloaded file escaped the run directory");
  }
  return { status: "downloaded", savedPath: realSaved, pageTotalCount: result.count, summaryAvailable: true };
}

async function prepareRunDir(outDir) {
  if (typeof outDir !== "string" || !outDir.trim()) throw new CollectionError("OUTPUT_UNUSABLE", "output directory is required");
  const target = resolve(outDir);
  try {
    const entries = await readdir(target);
    if (entries.length > 0) throw new CollectionError("OUTPUT_NOT_EMPTY", "refusing to overwrite an existing run folder");
  } catch (err) {
    if (err instanceof CollectionError) throw err;
    if (err && err.code !== "ENOENT") throw new CollectionError("OUTPUT_UNUSABLE", "output directory cannot be read");
  }
  await mkdir(target, { recursive: true });
  return target;
}

function safeFailure(err) {
  const code = typeof err?.code === "string" ? err.code : "INTERNAL_ERROR";
  const messages = {
    ADAPTER_REQUIRED: "browser adapter is not configured",
    CAPTURE_REQUIRED: "existing authenticated browser TaskSpace is unavailable",
    LOGIN_REQUIRED: "an already authenticated issuer session is required; login was not attempted",
    PROFILE_NOT_VERIFIED: "private owner-verified selector profile is required",
    PERIOD_UNVERIFIED: "screen date bounds could not be verified",
    PERIOD_INVALID: "requested or observed date range is invalid",
    PERIOD_BEFORE_ALLOWED_FLOOR: "requested start date precedes the screen lower bound",
    NO_WINDOW: "requested date range is outside the screen bounds",
    QUERY_ECHO_UNVERIFIED: "query source, dates, or result count could not be verified",
    QUERY_ECHO_MISMATCH: "observed query source or dates do not match the requested values",
    SUMMARY_UNVERIFIED: "screen result count is not unambiguous",
    DOWNLOAD_CONTROL_UNVERIFIED: "verified download control is not present",
    FORMAT_UNVERIFIED: "download format is not supported or not observable",
    FILE_OUTSIDE_RUN_DIR: "downloaded file is outside the run folder",
    FILE_MISSING: "downloaded file is missing or empty",
    UNKNOWN_PROVIDER: "unsupported issuer",
    UNKNOWN_SOURCE: "unsupported collection source",
    EGO_PROTOCOL: "browser adapter did not satisfy its protocol",
    ORIGIN_UNVERIFIED: "issuer page origin could not be verified",
    ORIGIN_MISMATCH: "browser page does not match the verified issuer origin",
    PARSER_VERIFICATION_UNAVAILABLE: "existing card parser is unavailable",
    PARSER_VERIFICATION_TIMEOUT: "existing card parser timed out",
    MANIFEST_WRITE_FAILED: "manifest could not be written without overwriting",
  };
  return { code, message: messages[code] ?? "collection stopped safely" };
}

async function writeManifest(outDir, report) {
  const manifestPath = join(outDir, "manifest.json");
  const body = {
    schemaVersion: MANIFEST_SCHEMA,
    runId: report.runId,
    generatedAt: report.generatedAt,
    executionDate: report.executionDate,
    requestedSources: report.requestedSources,
    rows: report.rows,
    selectorStatus: report.selectorStatus,
    importBoundary: report.importBoundary,
    ...(report.stopped ? { stopped: report.stopped } : {}),
  };
  await writeFile(manifestPath, JSON.stringify(body, null, 2) + "\n", { encoding: "utf8", flag: "wx" });
  report.manifestPath = manifestPath;
}

function makeReport(provider, outDir, executionDate, now) {
  const config = PROVIDERS[provider];
  const generatedAt = new Date(now ?? Date.now()).toISOString();
  return {
    schema: "cost.site-card-collection-report.v1",
    runId: provider + "-" + generatedAt.replaceAll(":", "-").replaceAll(".", "-"),
    generatedAt,
    executionDate: executionDate ?? null,
    requestedSources: config ? [config.source] : [],
    rows: [],
    outDir: typeof outDir === "string" ? resolve(outDir) : null,
    manifestPath: null,
    selectorStatus: "NOT_VERIFIED",
    importBoundary: {
      status: "NOT_RUN",
      reason: "collection preserves source files only; import requires the existing protected Pipeline.receive procedure",
    },
  };
}

async function finish(report, outDir) {
  if (!report.stopped) {
    report.status = report.rows.some((row) => row.verification?.status !== "ok" && row.verification?.status !== "no_data")
      ? "completed_with_failures" : "ok";
  } else {
    report.status = "stopped";
  }
  if (!outDir) return report;
  try {
    await writeManifest(outDir, report);
  } catch (err) {
    report.manifestError = err?.code === "EEXIST" ? "manifest already exists; overwrite refused" : "manifest write failed";
    if (report.status === "ok") report.status = "stopped";
    report.stopped = safeFailure(new CollectionError("MANIFEST_WRITE_FAILED"));
  }
  return report;
}

async function parserResultFor(filePath, parser) {
  if (parser && typeof parser.verify === "function") return parser.verify({ filePath });
  if (!parser || !parser.command || !parser.module) {
    return { status: PARSER_VERIFICATION_NOT_RUN, reason: "configured production parser is required" };
  }
  return runParserVerification({
    command: parser.command,
    module: parser.module,
    filePath,
    timeoutMs: parser.timeoutMs,
  });
}

function duplicateCheck(sha256, previousManifest, currentRows) {
  if (previousManifest === null || previousManifest === undefined) {
    return { scope: "file_sha256_only", status: sha256 ? "NOT_CHECKED" : "NOT_VERIFIED", databaseRows: "NOT_RUN" };
  }
  if (!Array.isArray(previousManifest.rows)) {
    return { scope: "file_sha256_only", status: "NOT_VERIFIED", databaseRows: "NOT_RUN" };
  }
  const priorRows = [...previousManifest.rows, ...currentRows];
  return {
    scope: "file_sha256_only",
    status: sha256
      ? (priorRows.some((row) => row.file?.sha256 === sha256) ? "DUPLICATE_FILE" : "NO_FILE_MATCH")
      : "NOT_VERIFIED",
    databaseRows: "NOT_RUN",
  };
}

export async function runProviderCollection(provider, {
  profile = null,
  profilePath = null,
  adapter = null,
  lastUseDate = null,
  executionDate = null,
  outDir = null,
  spaceName = null,
  parser = null,
  previousManifest = null,
  now = undefined,
} = {}) {
  const report = makeReport(provider, outDir, executionDate, now);
  let outputDirectory = null;
  let verifiedProfile = null;
  try {
    if (!PROVIDERS[provider]) throw new CollectionError("UNKNOWN_PROVIDER");
    if (!isIsoDate(executionDate)) throw new PolicyError("executionDate must be a valid YYYY-MM-DD date");
    if (!isIsoDate(lastUseDate)) throw new PolicyError("lastUseDate must be a valid YYYY-MM-DD date");
    outputDirectory = await prepareRunDir(outDir);
    verifiedProfile = profile ? validateProfile(provider, profile) : await loadProfileFromFile(profilePath, provider);
    report.selectorStatus = "OWNER_VERIFIED";
  } catch (err) {
    report.stopped = safeFailure(err);
    return finish(report, outputDirectory);
  }

  if (!adapter || typeof adapter.probeSession !== "function"
      || typeof adapter.readScreenAllowedDates !== "function"
      || typeof adapter.download !== "function") {
    report.stopped = safeFailure(new CollectionError("ADAPTER_REQUIRED"));
    return finish(report, outputDirectory);
  }

  try {
    const session = await adapter.probeSession({ source: verifiedProfile.source, spaceName });
    if (!session || typeof session.authenticated !== "boolean") throw new CollectionError("EGO_PROTOCOL");
    if (!session.authenticated) throw new CollectionError("LOGIN_REQUIRED");

    const allowed = await adapter.readScreenAllowedDates({ source: verifiedProfile.source, spaceName });
    if (!allowed || !isIsoDate(allowed.floor) || !isIsoDate(allowed.ceiling)) {
      throw new CollectionError("PERIOD_UNVERIFIED");
    }
    if (compareDates(allowed.floor, allowed.ceiling) > 0) throw new CollectionError("PERIOD_INVALID");
    if (compareDates(lastUseDate, allowed.floor) < 0) throw new CollectionError("PERIOD_BEFORE_ALLOWED_FLOOR");

    const period = buildPeriod({
      lastUseDate,
      executionDate,
      allowedCeiling: allowed,
      postingAxis: verifiedProfile.queryAxis,
    });
    if (period.status !== "OK") {
      throw new CollectionError(period.status === "NO_WINDOW" ? "NO_WINDOW" : period.status);
    }

    const result = await adapter.download({
      source: verifiedProfile.source,
      startDate: period.startDate,
      endDate: period.endDate,
      outDir: outputDirectory,
      spaceName,
    });
    const base = {
      source: verifiedProfile.source,
      sourceUrl: null,
      startDate: period.startDate,
      endDate: period.endDate,
      postingAxis: period.postingAxis,
    };
    if (result?.status === "no_data") {
      report.rows.push(buildNoDataRecord({
        ...base,
        pageTotalCount: result.pageTotalCount ?? null,
        summaryAvailable: result.summaryAvailable === true,
      }));
    } else if (result?.status === "failed") {
      report.rows.push({
        ...base,
        summary: { available: false, pageTotalCount: null },
        file: null,
        verification: { status: "failed", failure: "download_failed" },
        parserVerification: { status: PARSER_VERIFICATION_NOT_RUN, reason: "no preserved file" },
        countCheck: { status: "FAILED", parsedCount: null, screenCount: null },
      });
    } else if (result?.status !== "downloaded" || typeof result.savedPath !== "string") {
      throw new CollectionError("EGO_PROTOCOL");
    } else {
      const realOutput = await realpath(outputDirectory);
      const realSaved = await realpath(result.savedPath);
      const relativeSaved = relative(realOutput, realSaved);
      if (!relativeSaved || relativeSaved.startsWith("..") || isAbsolute(relativeSaved)) {
        throw new CollectionError("FILE_OUTSIDE_RUN_DIR");
      }
      const row = await validateDownloaded({
        savedPath: realSaved,
        source: base.source,
        sourceUrl: null,
        startDate: base.startDate,
        endDate: base.endDate,
        postingAxis: base.postingAxis,
        pageTotalCount: result.pageTotalCount ?? null,
        summaryAvailable: result.summaryAvailable === true,
      });
      row.parserVerification = row.file
        ? await parserResultFor(realSaved, parser)
        : { status: PARSER_VERIFICATION_NOT_RUN, reason: "file format was not verified" };
      const parserCheck = row.parserVerification;
      const parserHealthy = parserCheck?.status === "PARSER_VERIFICATION_OK"
        && Number.isSafeInteger(parserCheck.rows) && parserCheck.rows >= 0
        && parserCheck.parse_issues === 0
        && parserCheck.channel === PROVIDERS[provider].channel
        && parserCheck.issuer_matches === true
        && parserCheck.channel_matches === true;
      row.countCheck = countCheck(parserHealthy ? parserCheck.rows : null, row.summary?.pageTotalCount);
      if (!parserHealthy) {
        row.verification = { status: "failed", failure: "parser_or_provider_mismatch" };
      } else if (row.countCheck.status !== "MATCHED") {
        row.verification = { status: "failed", failure: "parser_count_mismatch" };
      } else if (row.verification.status !== "ok") {
        // The existing validator owns byte, extension, and HTML checks.
      }
      row.duplicateCheck = duplicateCheck(row.file?.sha256, previousManifest, report.rows);
      report.rows.push(row);
    }
  } catch (err) {
    report.stopped = safeFailure(err);
  }
  return finish(report, outputDirectory);
}

function parseArgs(argv) {
  const values = {};
  for (let index = 0; index < argv.length; index += 1) {
    const arg = argv[index];
    if (arg === "--help" || arg === "-h") return { help: true };
    if (typeof arg !== "string" || !arg.startsWith("--")) return { error: "unexpected argument" };
    const split = arg.indexOf("=");
    const key = split === -1 ? arg : arg.slice(0, split);
    const inline = split === -1 ? undefined : arg.slice(split + 1);
    const next = () => {
      if (inline !== undefined) return inline;
      index += 1;
      if (index >= argv.length) throw new CollectionError("CLI_USAGE", "missing option value");
      return argv[index];
    };
    if (key === "--profile") values.profilePath = next();
    else if (key === "--last-use-date") values.lastUseDate = next();
    else if (key === "--execution-date") values.executionDate = next();
    else if (key === "--out-dir") values.outDir = next();
    else if (key === "--space-name") values.spaceName = next();
    else if (key === "--ego-bin") values.egoBin = next();
    else if (key === "--python") values.python = next();
    else if (key === "--previous-manifest") values.previousManifest = next();
    else return { error: "unknown option" };
  }
  return { values };
}

export const USAGE = "usage: node tools/<provider>_card_collection/collect.mjs --profile <private-json> --space-name <existing-task-space> --last-use-date YYYY-MM-DD --execution-date YYYY-MM-DD --out-dir <new-run-folder> [--python python] [--previous-manifest <manifest>]";

export async function cliMain(provider, argv = process.argv.slice(2)) {
  let parsed;
  try {
    parsed = parseArgs(argv);
  } catch {
    process.stdout.write(JSON.stringify({ status: "stopped", code: "CLI_USAGE", message: "invalid collection arguments" }) + "\n");
    process.exitCode = 2;
    return null;
  }
  if (parsed.help) {
    process.stdout.write(USAGE + "\n");
    return null;
  }
  if (parsed.error) {
    process.stdout.write(JSON.stringify({ status: "stopped", code: "CLI_USAGE", message: parsed.error }) + "\n");
    process.exitCode = 2;
    return null;
  }
  const values = parsed.values ?? {};
  let profile = null;
  try {
    profile = await loadProfileFromFile(values.profilePath, provider);
  } catch {
    // runProviderCollection writes a safe stopped manifest when the output path is usable.
  }
  let adapter = null;
  if (profile && values.spaceName) {
    process.env.KB_CARD_SELECTORS = resolve(values.profilePath);
    adapter = createEgoBrowserAdapter({
      entryPath: fileURLToPath(import.meta.url),
      spaceName: values.spaceName,
      egoBin: values.egoBin ?? "ego-browser",
      launchFromFile: true,
    });
  }
  let previousManifest = null;
  if (values.previousManifest) {
    try {
      const candidate = JSON.parse(await readFile(values.previousManifest, "utf8"));
      previousManifest = candidate && Array.isArray(candidate.rows) ? candidate : { rows: null };
    } catch {
      previousManifest = { rows: null };
    }
  }
  const parserModule = fileURLToPath(new URL("./verify_site_card_file.py", import.meta.url));
  const report = await runProviderCollection(provider, {
    profile,
    profilePath: values.profilePath,
    adapter,
    lastUseDate: values.lastUseDate,
    executionDate: values.executionDate,
    outDir: values.outDir,
    spaceName: values.spaceName,
    parser: { command: values.python ?? "python", module: parserModule, timeoutMs: 60000 },
    previousManifest,
  });
  process.stdout.write(JSON.stringify(report, null, 2) + "\n");
  if (report.status !== "ok" || report.manifestError) process.exitCode = 2;
  return report;
}
