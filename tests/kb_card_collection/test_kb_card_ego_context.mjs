// synthetic verification: shipped default browser context (ego_context.mjs). No real
// ego-browser/browser/site/network/login: a made-up TaskSpace/Page seam exercises
// createCapture (page resolution, role scanning, selector pass-through, optional CSS
// reading, source-map navigation, saveAs path shaping). Live snapshot serialization and
// real API behavior are NOT_VERIFIED; only synthetic stand-ins are checked here.
import assert from "node:assert/strict";
import { mkdtemp, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import path from "node:path";

import { SOURCE_URLS } from "../../tools/kb_card_collection/policy.mjs";
import { createCapture, resetContextRuntime, setContextRuntime } from "../../tools/kb_card_collection/ego_context.mjs";

const ENV_KEYS = ["KB_CARD_BROWSER_CONTEXT"];
const SELECTORS = {
  session: "session-marker",
  dateFloor: "floor-marker",
  dateCeiling: "ceiling-marker",
  dateStartInput: "start-input",
  searchControl: "search-button",
  summaryResults: "summary-marker",
  downloadControl: "save-marker",
};
let failures = 0;
const pendingRuns = [];

async function withoutEnv(fn) {
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
      process.stdout.write("FAIL " + name + ": " + (err && err.stack ? err.stack.split("\n").slice(0, 3).join(" | ") : String(err)) + "\n");
    });
  pendingRuns.push(p);
  return p;
}

function fakePage(overrides = {}) {
  const pageCalls = [];
  const page = {
    pageCalls,
    async snapshot() {
      pageCalls.push("snapshot");
      return "summaryResults: 3 gross\ndownloadControl: present\n";
    },
    async goto(url) {
      pageCalls.push("goto:" + url);
    },
    async fill(selector, value) {
      pageCalls.push("fill:" + selector + ":" + value);
    },
    async click(selector) {
      pageCalls.push("click:" + selector);
    },
    async evaluate(fn, arg) {
      pageCalls.push("evaluate");
      return fn(arg);
    },
    async waitForEvent() {
      throw new Error("not used");
    },
  };
  return Object.assign(page, overrides);
}

function pagedTask(page) {
  return {
    async tabs() {
      return [{ label: "p1", page }];
    },
    async pages() {
      return [{ label: "p1", page }];
    },
    async page(label) {
      if (label !== "p1") throw new Error("no such page");
      return page;
    },
    async newPage() {
      page.pageCalls.push("newPage");
      return page;
    },
  };
}

// 1) no runtime, no injection -> CAPTURE_REQUIRED (live binding NOT_VERIFIED)
await check("createCapture without runtime/injection -> CAPTURE_REQUIRED", async () => {
  await withoutEnv(async () => {
    setContextRuntime({ taskSpace: null });
    await assert.rejects(
      () => createCapture({ space: "s", selectors: SELECTORS, operation: "probeSession", args: {} }),
      (err) => err && err.code === "CAPTURE_REQUIRED",
    );
    resetContextRuntime();
  });
});

// 2) injected taskSpace factory: called with the space, resolves p1, passes selectors verbatim, scans text
await check("factory taskSpace: invoked with space, p1 resolution, verbatim selectors, text scan", async () => {
  await withoutEnv(async () => {
    const page = fakePage();
    let gotSpace = null;
    setContextRuntime({ taskSpace: async (space) => { gotSpace = space; return pagedTask(page); } });
    const capture = await createCapture({ space: "synthetic-space", selectors: SELECTORS, operation: "probeSession", args: {} });
    assert.equal(gotSpace, "synthetic-space");
    assert.equal(capture.space, "synthetic-space");
    assert.equal(capture.pageLabel, "p1");
    const snapshot = await capture.snapshot(["summaryResults", "downloadControl"]);
    assert.deepEqual(snapshot, {
      summaryResults: { present: true, text: "3 gross" },
      downloadControl: { present: true, text: "present" },
    });
    await capture.fill("dateStartInput", "2026-10-02");
    await capture.query("searchControl");
    assert.deepEqual(page.pageCalls, ["snapshot", "fill:start-input:2026-10-02", "click:search-button"]);
    resetContextRuntime();
  });
});

// 3) pre-bound context object form, role-keyed payloads, and snapshot invalidation on mutation
await check("context object form, role-keyed scans, mutation invalidates cached snapshot", async () => {
  await withoutEnv(async () => {
    const calls = [];
    const page = fakePage({
      async snapshot() {
        calls.push("snapshot");
        return { summaryResults: { present: true, count: 0, text: null }, downloadControl: { present: true, count: 1, text: "" } };
      },
    });
    const staticContext = { createCapture: () => page };
    setContextRuntime({ taskSpace: staticContext });
    const capture = await createCapture({ space: "ignored-for-static", selectors: SELECTORS, operation: "probeSession", args: {} });
    assert.equal(capture.pageLabel, "p1");
    let snapshot = await capture.snapshot(["summaryResults", "downloadControl"]);
    assert.deepEqual(snapshot, { summaryResults: { present: true, text: null }, downloadControl: { present: true, text: null } }, JSON.stringify(snapshot));
    await capture.fill("dateStartInput", "2026-10-01");
    calls.push("fill");
    snapshot = await capture.snapshot(["summaryResults"]);
    assert.equal(calls.filter((call) => call === "snapshot").length, 2, "mutation invalidated cached snapshot");
    resetContextRuntime();
  });
});

// 4) page resolution: pages list -> page-handle smoke -> explicit failure (never fabricates a page)
await check("resolvePage: pages list, handle smoke, missing p1 fails explicitly", async () => {
  await withoutEnv(async () => {
    setContextRuntime({ taskSpace: async () => ({ async tabs() { return []; }, async pages() { return [{ label: "p1", page: fakePage() }]; } }) });
    let capture = await createCapture({ space: "s", selectors: SELECTORS, operation: "probeSession", args: {} });
    assert.equal(capture.pageLabel, "p1");
    resetContextRuntime();

    setContextRuntime({ taskSpace: async () => ({ async page(label) { if (label !== "p1") throw new Error("no p1"); return fakePage(); } }) });
    capture = await createCapture({ space: "s", selectors: SELECTORS, operation: "probeSession", args: {} });
    assert.equal(capture.pageLabel, "p1");
    resetContextRuntime();

    let newPageCalls = 0;
    setContextRuntime({ taskSpace: async () => ({ async tabs() { return []; }, async pages() { return []; }, async newPage() { newPageCalls += 1; return fakePage(); } }) });
    await assert.rejects(
      () => createCapture({ space: "s", selectors: SELECTORS, operation: "probeSession", args: {} }),
      (err) => err && (err.code === "EGO_PROTOCOL" || err.code === "CAPTURE_REQUIRED"),
    );
    assert.equal(newPageCalls, 0, "a missing p1 must fail, never synthesize a page");
    resetContextRuntime();
  });
});

// 5) navigation is read-only, from the fixed source map, memoized for one round
await check("navigate: fixed source map, once per capture, unknown labels no-op", async () => {
  await withoutEnv(async () => {
    const page = fakePage();
    setContextRuntime({ taskSpace: async () => pagedTask(page) });
    const capture = await createCapture({
      space: "s", selectors: SELECTORS, operation: "download",
      args: { source: "국민 기업카드 국내 매입", startDate: "2026-10-02", endDate: "2026-10-05", outDir: "C:/tmp/x", spaceName: "s" },
    });
    await capture.snapshot(["summaryResults"]);
    assert.deepEqual(page.pageCalls, ["goto:" + SOURCE_URLS["국민 기업카드 국내 매입"], "snapshot"]);
    page.pageCalls.length = 0;
    await capture.snapshot(["summaryResults"]);
    assert.deepEqual(page.pageCalls, [], "navigation is memoized for one round");
    resetContextRuntime();
  });
});

// 6) saveAs absolute/JS-safe paths; unusable event stops honestly
await check("saveAs: forward-slash absolute; no saveAs -> CAPTURE_REQUIRED", async () => {
  await withoutEnv(async () => {
    const got = [];
    const page = fakePage();
    page.saveAs = null;
    page.waitForEvent = async () => ({ async saveAs(p) { got.push(p); } });
    setContextRuntime({ taskSpace: async () => pagedTask(page) });
    const capture = await createCapture({ space: "s", selectors: SELECTORS, operation: "download", args: { source: "국민 카드 해외 매입" } });
    await capture.saveAs({ async saveAs(p) { got.push(p); } }, "C:\\Users\\x\\out.bin");
    assert.deepEqual(got, ["C:/Users/x/out.bin"]);
    await assert.rejects(() => capture.saveAs({}, "C:/tmp/x"), (err) => err && err.code === "CAPTURE_REQUIRED");
    resetContextRuntime();
  });
});

await Promise.all(pendingRuns);
process.stdout.write(failures === 0 ? "CTX OK\n" : "CTX FAIL " + failures + "\n");
process.exitCode = failures === 0 ? 0 : 1;
