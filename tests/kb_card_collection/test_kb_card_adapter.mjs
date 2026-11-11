// 합성 검증: ego 어댑터 계약/런너 프로토콜/CLI 배선. 실제 ego-browser·사이트·세션·네트워크 없음.
// stub runner와 fake spawn만 사용하며, 실환경 selector/사이트 동작은 검증됐다고 주장하지 않는다(NOT_VERIFIED).
import assert from "node:assert/strict";
import { EventEmitter } from "node:events";
import { mkdtemp, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import path from "node:path";
import { spawnSync } from "node:child_process";
import { fileURLToPath } from "node:url";

import {
  AdapterError,
  assertSessionAlive,
  createEgoBrowserAdapter,
} from "../../tools/kb_card_collection/adapter.mjs";
import { runCollector } from "../../tools/collect_kb_card.mjs";

const SOURCES = ["국민 기업카드 국내 매입"];
const ROOT = path.resolve(fileURLToPath(new URL("../..", import.meta.url)));
const CLI = path.join(ROOT, "tools", "collect_kb_card.mjs");
let failures = 0;
const pending = [];
function check(name, fn) {
  const p = Promise.resolve()
    .then(fn)
    .then(() => process.stdout.write(`PASS ${name}\n`))
        .catch((err) => {
          failures += 1;
          const detail = err && err.message ? err.message : String(err);
          process.stdout.write(`FAIL ${name}: ${detail}\n`);
          if (err && err.stack) process.stdout.write(`  ${err.stack.split("\n").slice(0, 6).join("\n  ")}\n`);
          if (err && "actual" in err && "expected" in err) {
            process.stdout.write(`  actual=${String(err.actual)} expected=${String(err.expected)}\n`);
          }
        });
  pending.push(p);
  return p;
}
async function tempDir(prefix) {
  return mkdtemp(path.join(tmpdir(), prefix));
}

function stubAdapter(handlers) {
  return createEgoBrowserAdapter({ entryPath: "irrelevant.mjs", spaceName: "synthetic-space", runner: async (request) => {
    const handler = handlers[request.operation];
    if (!handler) throw new Error(`unexpected operation ${request.operation}`);
    return handler(request.args);
  }});
}

 check("probe: authenticated boolean enforced; false -> LOGIN_REQUIRED", async () => {
   const ok = stubAdapter({ probeSession: () => ({ authenticated: true }) });
   assert.deepEqual(await ok.probeSession(), { authenticated: true });
   const badShape = stubAdapter({ probeSession: () => ({ session: "yes" }) });
   await assert.rejects(() => badShape.probeSession(), (err) => err instanceof AdapterError && err.code === "EGO_PROTOCOL");
   const loggedOut = stubAdapter({ probeSession: () => ({ authenticated: false }) });
   assert.deepEqual(await loggedOut.probeSession(), { authenticated: false });
   await assert.rejects(
     () => assertSessionAlive({ probe: () => loggedOut.probeSession() }),
     (err) => err instanceof AdapterError && err.code === "LOGIN_REQUIRED",
   );
 });

function makeEndToEnd() {
  return {
    SOURCES,
    get: (name) => stubAdapter({
      probeSession: () => ({ authenticated: true }),
      readScreenAllowedDates: () => ({ floor: "2026-10-01", ceiling: "2026-10-20" }),
      download: async ({ outDir }) => {
        if (name === "happy") {
          const file = path.join(outDir, "kb-domestic-acquired-2026-10-01-2026-10-20.csv");
          await writeFile(file, "가맹점,승인일,금액\n테스트,2026-10-02,1000\n", "utf8");
          return { status: "downloaded", savedPath: file, pageTotalCount: 1 };
        }
        if (name === "nodata") return { status: "no_data", pageTotalCount: 0 };
        return { status: "failed", code: "no_download_event" };
      },
    }),
  };
}

check("happy: row verified, parser NOT_RUN (unconfigured), manifest written", async () => {
  const { get, SOURCES: sources } = makeEndToEnd();
  const dir = await tempDir("kb-adapter-");
  const report = await runCollector({
    adapter: get("happy"), lastUseDate: "2026-10-01", executionDate: "2026-10-25",
    outDir: dir, sources, runId: "adapter-happy",
  });
  assert.equal(report.status, "ok");
  assert.equal(report.rows[0].verification.status, "ok");
  assert.equal(typeof report.rows[0].file.savedPath, "string");
  assert.equal(report.manifestPath.endsWith("manifest.json"), true);
});

check("0건 with summary -> no_data; without -> no_data_unverified", async () => {
  const { get, SOURCES: sources } = makeEndToEnd();
  const withCount = await runCollector({
    adapter: get("nodata"), lastUseDate: "2026-10-01", executionDate: "2026-10-25", outDir: null, sources,
  });
  assert.equal(withCount.rows[0].verification.status, "no_data");
  const without = stubAdapter({
    probeSession: () => ({ authenticated: true }),
    readScreenAllowedDates: () => ({ floor: "2026-10-01", ceiling: "2026-10-20" }),
    download: () => ({ status: "no_data" }),
  });
  const bare = await runCollector({
    adapter: without, lastUseDate: "2026-10-01", executionDate: "2026-10-25", outDir: null, sources: SOURCES,
  });
  assert.equal(bare.rows[0].verification.status, "no_data_unverified");
});

check("download data failure -> sequence stops for that source; unknown status/report is loud", async () => {
  const failed = stubAdapter({
    probeSession: () => ({ authenticated: true }),
    readScreenAllowedDates: () => ({ floor: "2026-10-01", ceiling: "2026-10-20" }),
    download: () => ({ status: "failed", code: "save_failed" }),
  });
  const report = await runCollector({
    adapter: failed, lastUseDate: "2026-10-01", executionDate: "2026-10-25", outDir: null, sources: SOURCES,
  });
  assert.equal(report.status, "completed_with_failures");
  assert.equal(report.rows[0].verification.code, "save_failed");

  const weird = stubAdapter({
    probeSession: () => ({ authenticated: true }),
    readScreenAllowedDates: () => ({ floor: "2026-10-01", ceiling: "2026-10-20" }),
    download: () => ({ status: "whatever" }),
  });
  const loud = await runCollector({
    adapter: weird, lastUseDate: "2026-10-01", executionDate: "2026-10-25", outDir: null, sources: SOURCES,
  });
  assert.equal(loud.status, "stopped");
  assert.equal(loud.stopped.code, "EGO_PROTOCOL");
});

async function waitFor(predicate, ms = 3000) {
  const deadline = Date.now() + ms;
  while (!predicate()) {
    if (Date.now() > deadline) throw new Error("condition not met before timeout");
    await new Promise((resolve) => setTimeout(resolve, 5));
  }
}

check("default runner: stages a launcher importing the entry and parses its JSON", async () => {
  const work = await tempDir("kb-runner-");
  const entry = path.join(work, "entry.mjs");
  await writeFile(entry, "export const probeSession = async () => ({ authenticated: true });\n", "utf8");
  let argvCapture = null;
  let stdinSource = null;
  const fake = new EventEmitter();
  fake.stdin = { end: (src) => { stdinSource = src; } };
  fake.stdout = new EventEmitter();
  fake.stderr = new EventEmitter();
  const spawnImpl = (bin, argv) => { argvCapture = { bin, argv }; return fake; };
  const adapter = createEgoBrowserAdapter({ entryPath: entry, spaceName: "s", workDir: work, spawnImpl });
  const pending = adapter.probeSession();
  await waitFor(() => argvCapture !== null);
  assert.equal(argvCapture.bin, "ego-browser");
  assert.deepEqual(argvCapture.argv, ["nodejs"]);
  fake.stdout.emit("data", Buffer.from('{"ok":true,"result":{"authenticated":true}}\n'));
  fake.emit("close", 0);
  assert.deepEqual(await pending, { authenticated: true });
  assert.match(stdinSource, /entry\.mjs/);
  assert.match(stdinSource, /probeSession/);
});

check("default runner: invalid JSON and failed rounds are EGO_PROTOCOL, never silent success", async () => {
  const work = await tempDir("kb-runner-bad-");
  const entry = path.join(work, "entry.mjs");
  await writeFile(entry, "export const probeSession = async () => ({ authenticated: false });\n", "utf8");
  async function runWith({ stdoutText = "", exitCode = 0 } = {}) {
  let spawned = false;
  const fake = new EventEmitter();
  fake.stdin = { end: () => {} };
  fake.stdout = new EventEmitter();
  fake.stderr = new EventEmitter();
  const spawnImpl = () => { spawned = true; return fake; };
  const adapter = createEgoBrowserAdapter({ entryPath: entry, spaceName: "s", workDir: work, spawnImpl });
    const pending = adapter.probeSession();
    await waitFor(() => spawned, 2000, "default runner spawn");
    if (stdoutText) fake.stdout.emit("data", Buffer.from(stdoutText));
    fake.emit("close", exitCode);
    return pending.catch((err) => err);
  }
  const invalid = await runWith({ stdoutText: "not json at all\n" });
  assert.ok(invalid instanceof AdapterError);
  assert.equal(invalid.code, "EGO_PROTOCOL");
  const failed = await runWith({ stdoutText: '{"ok":true,"result":{"authenticated":true}}\n', exitCode: 1 });
  assert.equal(failed.code, "EGO_PROTOCOL");
  assert.match(failed.message, /round failed/);
});

check("CLI: help lists ego flags; missing/invalid entry config stops instead of faking success", () => {
  const help = spawnSync(process.execPath, [CLI, "--help"], { encoding: "utf8" });
  assert.equal(help.status, 0);
  assert.equal(help.stdout.includes("--ego-entry"), true);
  assert.equal(help.stdout.includes("--space-name"), true);

  const noSpace = spawnSync(process.execPath, [CLI, "--ego-entry", "whatever.mjs", "--execution-date", "2026-10-25", "--last-use-date", "2026-10-01", "--source", "domestic"], { encoding: "utf8" });
  assert.equal(noSpace.status, 2);
  assert.equal(JSON.parse(noSpace.stderr).code, "ADAPTER_REQUIRED");

  const noEntry = spawnSync(process.execPath, [CLI, "--execution-date", "2026-10-25", "--last-use-date", "2026-10-01", "--source", "domestic"], { encoding: "utf8" });
  assert.equal(noEntry.status, 2);
  assert.equal(JSON.parse(noEntry.stderr).code, "ADAPTER_REQUIRED");
});

check("CLI with entry path: unreadable entry surfaces as stopped EGO_PROTOCOL (exit 2), nothing fabricated", () => {
  const outDir = path.join(tmpdir(), `kb-cli-${Date.now()}`);
  const miss = path.join(outDir, "missing-entry.mjs");
  const proc = spawnSync(process.execPath, [CLI, "--ego-entry", miss, "--space-name", "s", "--execution-date", "2026-10-25", "--last-use-date", "2026-10-01", "--source", "domestic", "--out-dir", outDir], { encoding: "utf8" });
  assert.equal(proc.status, 2);
  const report = JSON.parse(proc.stdout);
  assert.equal(report.status, "stopped");
  assert.equal(report.stopped.code, "EGO_PROTOCOL");
});

await Promise.all(pending);
process.stdout.write(failures === 0 ? "ADAPTER OK\n" : `ADAPTER FAIL ${failures}\n`);
process.exitCode = failures === 0 ? 0 : 1;
