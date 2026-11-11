// synthetic verification: the packaged entry module (entry_kb.mjs). No real ego-browser,
// browser, site, network or login is involved. A made-up browserContext seam plus selector
// config drive probeSession / readScreenAllowedDates / download end to end. Live screen
// shapes and real selector values are NOT_VERIFIED; unmet requirements stop honestly.
import assert from "node:assert/strict";
import { mkdtemp, readFile, stat, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import path from "node:path";

import { SOURCES } from "../../tools/kb_card_collection/policy.mjs";
import entry, { resetEntryRuntime, setEntryRuntime } from "../../tools/kb_card_collection/entry_kb.mjs";

const ENV_KEYS = ["KB_CARD_BROWSER_CONTEXT", "KB_CARD_SELECTORS", "KB_CARD_SPACE_NAME"];
const SELECTORS = {
  session: "session-marker",
  dateFloor: "floor-marker",
  dateCeiling: "ceiling-marker",
  dateStartInput: "start-input",
  dateEndInput: "end-input",
  searchControl: "search-button",
  periodEchoSource: "echo-source",
  periodEchoStart: "echo-start",
  periodEchoEnd: "echo-end",
  summaryResults: "summary-marker",
  downloadControl: "save-marker",
};
const ECHO_OK = { periodEchoSource: "src", periodEchoStart: "2026-10-01", periodEchoEnd: "2026-10-05" };

let failures = 0;
const pendingRuns = [];

async function withCleanEnv(fn) {
  const saved = {};
  for (const key of ENV_KEYS) {
    saved[key] = process.env[key];
    delete process.env[key];
  }
  try {
    return await fn();
  } finally {
    for (const key of ENV_KEYS) {
      if (saved[key] === undefined) delete process.env[key];
      else process.env[key] = saved[key];
    }
  }
}

function check(name, fn) {
  const p = Promise.resolve()
    .then(fn)
    .then(() => process.stdout.write("PASS " + name + "\n"))
    .catch((err) => {
      failures += 1;
      process.stdout.write("FAIL " + name + ": " + String(err && err.stack ? err.stack.split("\n").slice(0, 3).join(" | ") : err) + "\n");
    });
  pendingRuns.push(p);
  return p;
}

async function tempDir(prefix) {
  return mkdtemp(path.join(tmpdir(), prefix));
}

async function newFake(opts = {}) {
  const calls = [];
  const echoed = Object.assign({} , opts.echoText || {});
  const capture = {
    async snapshot() {
      calls.push("snapshot");
      return {
        session: { present: Boolean(opts.sessionPresent) },
        dateFloor: { present: Boolean(opts.floorPresent), text: opts.floorText || "" },
        dateCeiling: { present: Boolean(opts.ceilingPresent), text: opts.ceilingText || "" },
        downloadControl: { present: Boolean(opts.controlPresent) },
        summaryResults: { present: Boolean(opts.summaryPresent), text: opts.summaryText || "" },
        periodEchoSource: opts.echoPresent !== false ? { present: true, text: echoed.periodEchoSource } : { present: false, text: null },
        periodEchoStart: opts.echoPresent !== false ? { present: true, text: echoed.periodEchoStart } : { present: false, text: null },
        periodEchoEnd: opts.echoPresent !== false ? { present: true, text: echoed.periodEchoEnd } : { present: false, text: null },
      };
    },
    async armDownloadEvent() {
      calls.push("arm");
      return { async wait() { calls.push("wait"); return opts.eventPayload; } };
    },
    async activate() { calls.push("activate"); },
    async fill(role, value) { calls.push("fill:" + role + ":" + String(value)); },
    async query(role) { calls.push("query:" + role); },
    async saveAs(_event, destination) {
      calls.push("saveAs");
      await writeFile(destination, opts.saveBytes || "synthetic-entry-bytes");
      return { savedPath: destination };
    },
  };
  return { calls, bindings: { createCapture: () => capture } };
}

const DOWNLOAD_ARGS = { startDate: "2026-10-02", endDate: "2026-10-05", spaceName: "synthetic-space" };

// 1) session truthfulness
await check("probeSession: true only when the session role is present", async () => {
  await withCleanEnv(async () => {
    setEntryRuntime({ browserContext: (await newFake({ sessionPresent: true })).bindings, selectors: SELECTORS, spaceName: "synthetic-space" });
    assert.deepEqual(await entry.probeSession({ spaceName: "synthetic-space" }), { authenticated: true });
    resetEntryRuntime();
    setEntryRuntime({ browserContext: (await newFake({ sessionPresent: false })).bindings, selectors: SELECTORS, spaceName: "synthetic-space" });
    assert.deepEqual(await entry.probeSession({ spaceName: "synthetic-space" }), { authenticated: false });
    resetEntryRuntime();
  });
});

// 2) allowed dates: observed pair / null / non-ISO error
await check("readScreenAllowedDates: pair, null when missing, protocol error on non-ISO", async () => {
  await withCleanEnv(async () => {
    setEntryRuntime({ browserContext: (await newFake({ floorPresent: true, ceilingPresent: true, floorText: "2026-10-02", ceilingText: "2026-10-05" })).bindings, selectors: SELECTORS, spaceName: "synthetic-space" });
    assert.deepEqual(await entry.readScreenAllowedDates({ source: "x", spaceName: "synthetic-space" }), { floor: "2026-10-02", ceiling: "2026-10-05" });
    resetEntryRuntime();
    setEntryRuntime({ browserContext: (await newFake({ floorPresent: true, ceilingPresent: false })).bindings, selectors: SELECTORS, spaceName: "synthetic-space" });
    assert.equal(await entry.readScreenAllowedDates({ source: "x", spaceName: "synthetic-space" }), null);
    resetEntryRuntime();
    setEntryRuntime({ browserContext: (await newFake({ floorPresent: true, ceilingPresent: true, floorText: "10/02" })).bindings, selectors: SELECTORS, spaceName: "synthetic-space" });
    await assert.rejects(() => entry.readScreenAllowedDates({ source: "x", spaceName: "synthetic-space" }), (err) => err && err.code === "EGO_PROTOCOL");
    resetEntryRuntime();
  });
});

// 3) happy path: fill -> lookup -> observation -> arm -> activate -> same-round save
await check("download: fill -> lookup -> observation -> arm -> activate -> same-round save", async () => {
  await withCleanEnv(async () => {
    const dir = await tempDir("kb-entry-");
    const fake = await newFake({
      controlPresent: true,
      summaryPresent: true,
      summaryText: "3건",
      echoText: ECHO_OK,
      eventPayload: { suggestedFilename: "kb-observed.bin", pageTotalCount: 3, summaryAvailable: true },
    });
    setEntryRuntime({ browserContext: fake.bindings, selectors: SELECTORS, spaceName: "synthetic-space" });
    const result = await entry.download({ source: SOURCES.DOMESTIC, ...DOWNLOAD_ARGS, outDir: dir });
    assert.equal(result.status, "downloaded");
    assert.equal(result.pageTotalCount, 3);
    assert.equal(result.summaryAvailable, true);
    assert.equal(result.savedPath, path.join(dir, "kb-observed.bin"));
    const calls = fake.calls;
    const detail = JSON.stringify(calls);
    assert.ok(calls.includes("fill:dateStartInput:2026-10-02") && calls.includes("fill:dateEndInput:2026-10-05"), detail);
    assert.ok(calls.indexOf("query:searchControl") > calls.indexOf("fill:dateEndInput:2026-10-05"), detail);
    assert.ok(calls.indexOf("snapshot") > calls.indexOf("query:searchControl"), detail);
    assert.ok(calls.includes("arm") && calls.includes("activate") && calls.includes("wait") && calls.includes("saveAs"), detail);
    const info = await stat(result.savedPath);
    assert.ok(info.isFile() && info.size > 0);
    assert.equal(await readFile(result.savedPath, "utf8"), "synthetic-entry-bytes");
    resetEntryRuntime();
  });
});

// 4) clear-zero reading: no_data and zero download actions, for several unit styles
await check("clear-zero summary: no_data with zero download actions", async () => {
  await withCleanEnv(async () => {
    for (const text of ["0", "0건", "0 results", "No data", "No records"]) {
      const dir = await tempDir("kb-entry-");
      const fake = await newFake({ controlPresent: true, summaryPresent: true, summaryText: text, echoText: ECHO_OK });
      setEntryRuntime({ browserContext: fake.bindings, selectors: SELECTORS, spaceName: "synthetic-space" });
      const result = await entry.download({ source: SOURCES.DOMESTIC, ...DOWNLOAD_ARGS, outDir: dir });
      assert.equal(result.status, "no_data");
      assert.equal(result.pageTotalCount, 0);
      assert.equal(result.summaryAvailable, true);
      assert.deepEqual(fake.calls.filter((call) => /arm|activate|saveAs|wait/.test(call)), []);
      resetEntryRuntime();
    }
  });
});

// 5) boundary / end-zero / unclear summaries are never treated as zero
await check("boundary and unclear summaries are not treated as zero", async () => {
  await withCleanEnv(async () => {
    for (const text of ["10", "10건", "100", "100건", "1,000건", "건수 확인 중", "", "오류 응답"]) {
      const dir = await tempDir("kb-entry-");
      const fake = await newFake({ controlPresent: true, summaryPresent: true, summaryText: text, echoText: ECHO_OK, eventPayload: {} });
      setEntryRuntime({ browserContext: fake.bindings, selectors: SELECTORS, spaceName: "synthetic-space" });
      const result = await entry.download({ source: SOURCES.DOMESTIC, ...DOWNLOAD_ARGS, outDir: dir });
      assert.equal(result.status, "downloaded", "not a zero claim: " + JSON.stringify(text));
      resetEntryRuntime();
    }
  });
});

// 6) output-period echo roles are required observations
await check("missing period-echo observation stops before any download handling", async () => {
  await withCleanEnv(async () => {
    const fake = await newFake({ controlPresent: true, summaryPresent: true, summaryText: "3건", echoPresent: false });
    setEntryRuntime({ browserContext: fake.bindings, selectors: SELECTORS, spaceName: "synthetic-space" });
    let caught = null;
    try {
      await entry.download({ source: SOURCES.DOMESTIC, ...DOWNLOAD_ARGS, outDir: await tempDir("kb-entry-") });
    } catch (err) {
      caught = err;
    }
    assert.equal(caught && caught.code, "CAPTURE_REQUIRED", "caught=" + String(caught));
    assert.deepEqual(fake.calls.filter((call) => /arm|activate|saveAs|wait/.test(call)), [], JSON.stringify(fake.calls));
    assert.deepEqual(fake.calls.filter((call) => /arm|activate|saveAs|wait/.test(call)), []);
    resetEntryRuntime();
  });
});

// 7) missing selector / context / space are CAPTURE_REQUIRED, never guessed
await check("missing selector/context/space stop with CAPTURE_REQUIRED", async () => {
  await withCleanEnv(async () => {
    const fake = await newFake({ sessionPresent: true });
    setEntryRuntime({ browserContext: fake.bindings, selectors: SELECTORS, spaceName: "synthetic-space" });
    assert.deepEqual(await entry.probeSession(), { authenticated: true });
    setEntryRuntime({ browserContext: fake.bindings, selectors: { dateFloor: "f", dateCeiling: "c", dateStartInput: "a", dateEndInput: "b", searchControl: "q", periodEchoSource: "e1", periodEchoStart: "e2", periodEchoEnd: "e3", summaryResults: "sum", downloadControl: "dl" }, spaceName: "synthetic-space" });
    await assert.rejects(() => entry.probeSession(), (err) => err && err.code === "CAPTURE_REQUIRED" && /session/.test(err.message));
    resetEntryRuntime();

    setEntryRuntime({ browserContext: fake.bindings, selectors: SELECTORS, spaceName: "" });
    await assert.rejects(() => entry.probeSession(), (err) => err && err.code === "CAPTURE_REQUIRED");
    resetEntryRuntime();

    setEntryRuntime({ browserContext: null, selectors: SELECTORS, spaceName: "synthetic-space" });
    await assert.rejects(() => entry.probeSession(), (err) => err && err.code === "CAPTURE_REQUIRED");
    resetEntryRuntime();

    await assert.rejects(() => entry.probeSession(), (err) => err && err.code === "CAPTURE_REQUIRED");
    resetEntryRuntime();
  });
});

await Promise.all(pendingRuns);
process.stdout.write(failures === 0 ? "ENTRY OK\n" : "ENTRY FAIL " + failures + "\n");
process.exitCode = failures === 0 ? 0 : 1;
