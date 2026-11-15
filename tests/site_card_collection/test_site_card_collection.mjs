// Synthetic Page + existing Hana/IBK fixtures + the production parser and KB
// validation helpers. No website, credential, live browser, or database access.
import assert from "node:assert/strict";
import { readFile, mkdtemp, rm, writeFile } from "node:fs/promises";
import path from "node:path";
import { tmpdir } from "node:os";
import { countCheck, download, probeSession, readScreenAllowedDates, resetSiteCollectionRuntime,
  runProviderCollection, setSiteCollectionRuntime, PROFILE_SCHEMA } from "../../tools/site_card_collection.mjs";

const root = await mkdtemp(path.join(tmpdir(), "hana-ibk-collection-e2e-"));
const parserModule = path.resolve("tools/verify_site_card_file.py");
const sources = {
  hana: { source: "하나 기업카드 이용내역", fixture: "tests/fixtures/hana-card-synthetic.csv", axis: "이용일" },
  ibk: { source: "IBK 기업카드 이용내역", fixture: "tests/fixtures/ibk-card-synthetic.xlsx", axis: "이용일" },
};
const requiredRoles = ["session", "dateFloor", "dateCeiling", "dateStartInput", "dateEndInput", "searchControl",
  "periodEchoSource", "periodEchoStart", "periodEchoEnd", "summaryResults", "downloadControl"];
const profileFor = (provider, overrides = {}) => ({
  schemaVersion: PROFILE_SCHEMA,
  provider,
  source: sources[provider].source,
  expectedOrigin: "https://cards.example.test",
  usageUrl: "https://cards.example.test/observed-issuer-usage",
  queryAxis: sources[provider].axis,
  sourceEcho: "기업카드 이용내역",
  verification: { status: "OWNER_VERIFIED", observedAt: "2026-11-16" },
  selectors: Object.fromEntries(requiredRoles.map((role) => [role, "selector-" + role])),
  ...overrides,
});

function fakeContext(profile, options = {}) {
  const calls = [];
  const context = {
    async createCapture({ operation, args }) {
      return {
        async origin() { calls.push("origin"); return options.actualOrigin ?? profile.expectedOrigin; },
        async navigate(url) { calls.push("navigate:" + url); },
        async snapshot(roles) {
          calls.push("snapshot:" + operation);
          const values = {
            session: options.authenticated !== false,
            dateFloor: options.floor ?? "2025-01-01",
            dateCeiling: options.ceiling ?? "2026-10-31",
            periodEchoSource: options.sourceEcho ?? profile.sourceEcho,
            periodEchoStart: options.echoStart ?? args.startDate ?? "2026-10-01",
            periodEchoEnd: options.echoEnd ?? args.endDate ?? "2026-10-31",
            summaryResults: options.summaryText ?? "1건",
            downloadControl: "저장",
          };
          return Object.fromEntries(roles.map((role) => [role, {
            present: typeof values[role] === "boolean" ? values[role] : values[role] !== undefined && values[role] !== null,
            text: typeof values[role] === "string" ? values[role] : null,
          }]));
        },
        async fill(role, value) { calls.push("fill:" + role + ":" + value); },
        async query(role) { calls.push("query:" + role); },
        async armDownloadEvent() {
          calls.push("arm");
          return { async wait() { calls.push("wait"); return { suggestedFilename: options.filename ?? path.basename(sources[profile.provider].fixture) }; } };
        },
        async activate(role) { calls.push("activate:" + role); },
        async saveAs(_event, destination) {
          calls.push("saveAs");
          const bytes = options.bytes ?? await readFile(sources[profile.provider].fixture);
          await writeFile(destination, bytes);
          return { savedPath: destination };
        },
      };
    },
  };
  return { context, calls };
}

function adapterFor(provider) {
  return { probeSession, readScreenAllowedDates, download, source: sources[provider].source };
}

function runtime(provider, options = {}) {
  const profile = profileFor(provider, options.profileOverrides ?? {});
  const fake = fakeContext(profile, options);
  setSiteCollectionRuntime({ browserContext: fake.context, profile, spaceName: "synthetic-task-space" });
  return { profile, ...fake };
}

async function run(provider, name, options = {}) {
  const { profile, calls } = runtime(provider, options);
  const result = await runProviderCollection(provider, {
    profile,
    adapter: adapterFor(provider),
    lastUseDate: options.lastUseDate ?? "2026-10-01",
    executionDate: options.executionDate ?? "2026-11-01",
    outDir: path.join(root, name),
    spaceName: "synthetic-task-space",
    parser: { command: "python", module: parserModule, timeoutMs: 30000 },
    previousManifest: options.previousManifest ?? null,
    now: "2026-11-16T00:00:00.000Z",
  });
  resetSiteCollectionRuntime();
  return { result, calls };
}

let passed = 0;
async function check(name, fn) {
  try {
    await fn();
    passed += 1;
    process.stdout.write("PASS " + name + "\n");
  } catch (error) {
    process.stdout.write("FAIL " + name + ": " + String(error?.stack ?? error).split("\n").slice(0, 3).join(" | ") + "\n");
    throw error;
  } finally {
    resetSiteCollectionRuntime();
  }
}

try {
  await check("count guard rejects booleans and mismatched screen counts", async () => {
    assert.equal(countCheck(1, 1).status, "MATCHED");
    assert.equal(countCheck(1, 2).status, "FAILED");
    assert.equal(countCheck(true, 1).status, "FAILED");
  });

  for (const provider of ["hana", "ibk"]) {
    await check(provider + " collection runs query, period verification, download, SHA, and real parser", async () => {
      const { result, calls } = await run(provider, provider + "-normal");
      assert.equal(result.status, "ok", JSON.stringify({ stopped: result.stopped, row: result.rows[0] }));
      assert.equal(result.selectorStatus, "OWNER_VERIFIED");
      assert.equal(result.rows[0].source, sources[provider].source);
      assert.equal(result.rows[0].query.postingAxis, sources[provider].axis);
      assert.equal(result.rows[0].countCheck.status, "MATCHED");
      assert.equal(result.rows[0].parserVerification.issuer_matches, true);
      assert.equal(result.rows[0].parserVerification.channel_matches, true);
      assert.equal(result.rows[0].verification.status, "ok");
      assert.equal(result.rows[0].file.sha256.length, 64);
      assert.ok(calls.indexOf("fill:dateStartInput:2026-10-01") < calls.indexOf("query:searchControl"));
      assert.ok(calls.indexOf("fill:dateEndInput:2026-10-31") < calls.indexOf("query:searchControl"));
      assert.ok(calls.indexOf("arm") < calls.indexOf("activate:downloadControl"));
      assert.equal(calls.filter((entry) => entry === "activate:downloadControl").length, 1);
      const manifest = JSON.parse(await readFile(result.manifestPath, "utf8"));
      assert.equal(manifest.rows[0].file.sha256, result.rows[0].file.sha256);
      assert.equal(manifest.importBoundary.status, "NOT_RUN");
    });
  }

  await check("zero result is recorded without arming or activating a download", async () => {
    const { result, calls } = await run("hana", "zero", { summaryText: "0건" });
    assert.equal(result.status, "ok");
    assert.equal(result.rows[0].verification.status, "no_data");
    assert.equal(result.rows[0].summary.pageTotalCount, 0);
    assert.equal(calls.includes("arm"), false);
    assert.equal(calls.some((entry) => entry.startsWith("activate:")), false);
  });

  await check("screen lower-bound error stops before query and download", async () => {
    const { result, calls } = await run("ibk", "period-floor", { floor: "2026-10-02" });
    assert.equal(result.status, "stopped");
    assert.equal(result.stopped.code, "PERIOD_BEFORE_ALLOWED_FLOOR");
    assert.equal(calls.some((entry) => entry.startsWith("fill:")), false);
    assert.equal(calls.includes("arm"), false);
  });

  await check("unparseable screen date limits fail closed", async () => {
    const { result, calls } = await run("hana", "period-format", { floor: "10/01/2026" });
    assert.equal(result.status, "stopped");
    assert.equal(result.stopped.code, "PERIOD_UNVERIFIED");
    assert.equal(calls.some((entry) => entry.startsWith("fill:")), false);
  });

  await check("period or source echo mismatch stops before download", async () => {
    const { result, calls } = await run("hana", "echo-mismatch", { echoEnd: "2026-10-30" });
    assert.equal(result.status, "stopped");
    assert.equal(result.stopped.code, "QUERY_ECHO_MISMATCH");
    assert.equal(calls.includes("arm"), false);
  });

  await check("HTML returned with a CSV suffix is rejected and retained for review", async () => {
    const { result } = await run("hana", "html-csv", {
      bytes: Buffer.from("<!doctype html><html><body>login</body></html>"), filename: "login.csv",
    });
    assert.equal(result.status, "completed_with_failures");
    assert.equal(result.rows[0].verification.status, "failed");
    assert.equal(result.rows[0].file.kind, "html");
    assert.equal(result.rows[0].countCheck.status, "FAILED");
  });

  await check("unsupported downloaded extension stops before saving", async () => {
    const { result, calls } = await run("ibk", "unsupported-ext", { filename: "export.zip" });
    assert.equal(result.status, "stopped");
    assert.equal(result.stopped.code, "FORMAT_UNVERIFIED");
    assert.equal(calls.includes("saveAs"), false);
  });

  await check("parser row count must exactly match the observed screen count", async () => {
    const { result } = await run("ibk", "count-mismatch", { summaryText: "2건" });
    assert.equal(result.status, "completed_with_failures");
    assert.equal(result.rows[0].countCheck.status, "FAILED");
    assert.equal(result.rows[0].verification.status, "failed");
  });

  await check("download checksum repetition is detectable without importing rows", async () => {
    const first = await run("hana", "idempotent-a");
    const second = await run("hana", "idempotent-b", { previousManifest: { rows: first.result.rows } });
    assert.equal(first.result.rows[0].file.sha256, second.result.rows[0].file.sha256);
    assert.equal(second.result.rows[0].duplicateCheck.status, "DUPLICATE_FILE");
    assert.equal(second.result.rows[0].duplicateCheck.databaseRows, "NOT_RUN");
  });

  await check("missing or malformed prior manifest never claims a clean duplicate check", async () => {
    const absent = await run("hana", "idempotent-no-prior-manifest");
    const malformed = await run("hana", "idempotent-malformed-prior-manifest", { previousManifest: { rows: "invalid" } });
    assert.equal(absent.result.rows[0].duplicateCheck.status, "NOT_CHECKED");
    assert.equal(malformed.result.rows[0].duplicateCheck.status, "NOT_VERIFIED");
  });

  await check("origin mismatch prevents all page actions", async () => {
    const { result, calls } = await run("ibk", "origin-mismatch", { actualOrigin: "https://wrong.example.test" });
    assert.equal(result.status, "stopped");
    assert.equal(result.stopped.code, "ORIGIN_MISMATCH");
    assert.equal(calls.some((entry) => entry.startsWith("snapshot:")), false);
  });

  await check("unverified profile never reaches the browser adapter", async () => {
    const profile = profileFor("hana", { verification: { status: "NOT_VERIFIED", observedAt: "2026-11-16" } });
    let touched = false;
    const result = await runProviderCollection("hana", {
      profile, adapter: { async probeSession() { touched = true; return { authenticated: true }; } },
      lastUseDate: "2026-10-01", executionDate: "2026-11-01", outDir: path.join(root, "profile-fail"),
    });
    assert.equal(result.status, "stopped");
    assert.equal(result.selectorStatus, "NOT_VERIFIED");
    assert.equal(touched, false);
  });

  await check("missing authenticated session stops without login automation", async () => {
    const { result, calls } = await run("ibk", "login-required", { authenticated: false });
    assert.equal(result.status, "stopped");
    assert.equal(result.stopped.code, "LOGIN_REQUIRED");
    assert.equal(calls.some((entry) => entry.startsWith("fill:")), false);
  });

  process.stdout.write("SUMMARY " + passed + " passed, 0 failed, 0 skipped\n");
} finally {
  resetSiteCollectionRuntime();
  await rm(root, { recursive: true, force: true });
}
