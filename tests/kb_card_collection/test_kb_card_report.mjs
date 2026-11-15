// 합성 검증: 수집 오케스트레이션(세션/허용일/다운로드/검증/실패/0건/경로경계/캐럿/매니페스트).
// fake adapter만 사용. 네트워크·실제 브라우저·고객 자료·운영 저장소 접근 없음.
import assert from "node:assert/strict";
import { mkdtemp, readFile, writeFile } from "node:fs/promises";
import { rmSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";

import { AdapterError } from "../../tools/kb_card_collection/adapter.mjs";
import { runCollector } from "../../tools/collect_kb_card.mjs";
import { reserveAbsentPath } from "../../tools/kb_card_collection/validation.mjs";

const SENTINEL = "CUSTOMER-SENTINEL-42-₩-0000";
let failures = 0;
const pending = [];
function check(name, fn) {
  const p = Promise.resolve()
    .then(fn)
    .then(() => process.stdout.write(`PASS ${name}\n`))
    .catch((err) => {
      failures += 1;
      process.stdout.write(`FAIL ${name}: ${err && err.stack ? err.stack.split("\n").slice(0, 3).join(" | ") : err}\n`);
    });
  pending.push(p);
  return p;
}
const tempDirs = [];
process.on("exit", () => {
  for (const dir of tempDirs) rmSync(dir, { recursive: true, force: true, maxRetries: 5, retryDelay: 100 });
});
async function tempDir(prefix) {
  const dir = await mkdtemp(path.join(tmpdir(), prefix));
  tempDirs.push(dir);
  return dir;
}

function happyAdapter({ onDownload } = {}) {
  return {
    probeCalls: 0,
    async probeSession() {
      this.probeCalls += 1;
      return { authenticated: true };
    },
    async readScreenAllowedDates() {
      return { floor: "2026-10-01", ceiling: "2026-10-20" };
    },
    async download({ source, outDir }) {
      if (onDownload) await onDownload({ source, outDir });
      const name = source === "국민 기업카드 국내 매입" ? "domestic.csv" : "overseas.csv";
      const file = path.join(outDir, name);
      await writeFile(file, `merchant,amount\n${SENTINEL},1000\n`, "utf8");
      return { status: "downloaded", savedPath: file, suggestedFilename: name, pageTotalCount: 3, summaryAvailable: true };
    },
  };
}

check("happy path: two sources, verified rows, counts, manifest, no raw text", async () => {
  const dir = await tempDir("kb-happy-");
  const adapter = happyAdapter();
  const report = await runCollector({
    adapter,
    lastUseDate: "2026-10-01",
    executionDate: "2026-10-25",
    outDir: dir,
    sources: ["국민 기업카드 국내 매입", "국민 기업카드 해외 매입"],
    runId: "synthetic-happy",
  });
  assert.equal(report.status, "ok");
  assert.equal(report.rows.length, 2);
  for (const row of report.rows) {
    assert.equal(row.verification.status, "ok");
    assert.equal(row.query.startDate, "2026-10-01");
    assert.equal(row.query.endDate, "2026-10-20");
    assert.equal(row.parserVerification.status, "PARSER_VERIFICATION_NOT_RUN");
  }
  const manifestText = await readFile(path.join(dir, "manifest.json"), "utf8");
  assert.equal(manifestText.includes(SENTINEL), false);
  assert.equal(JSON.stringify(report).includes("₩"), false);

  const clean = await tempDir("kb-manifest-");
  await writeFile(path.join(clean, "leftover.txt"), "x", "utf8");
  const before = await readFile(path.join(clean, "leftover.txt"), "utf8");
  const second = await runCollector({
    adapter: happyAdapter(),
    lastUseDate: "2026-10-01",
    executionDate: "2026-10-25",
    outDir: clean,
    sources: ["국민 기업카드 국내 매입"],
  });
  assert.equal(second.status, "stopped");
  assert.equal(second.stopped.code, "OUTPUT_NOT_EMPTY");
  assert.equal(await readFile(path.join(clean, "leftover.txt"), "utf8"), before);
});

check("expired/unauthenticated session stops without touching download", async () => {
  const dir = await tempDir("kb-login-");
  let downloads = 0;
  const adapter = {
    async probeSession() { return { authenticated: false }; },
    async readScreenAllowedDates() { throw new Error("must not run"); },
    async download() { downloads += 1; throw new Error("must not run"); },
  };
  const report = await runCollector({
    adapter,
    lastUseDate: "2026-10-01",
    executionDate: "2026-10-25",
    outDir: dir,
    sources: ["국민 기업카드 국내 매입"],
  });
  assert.equal(report.status, "stopped");
  assert.equal(report.stopped.code, "LOGIN_REQUIRED");
  assert.equal(downloads, 0);
  const manifest = JSON.parse(await readFile(path.join(dir, "manifest.json"), "utf8"));
  assert.equal(manifest.stopped.code, "LOGIN_REQUIRED");
});

check("env probe unverified (network/env throw) stops", async () => {
  const adapter = {
    async probeSession() { throw new Error("cdp unavailable"); },
    async readScreenAllowedDates() { throw new Error("must not run"); },
    async download() { throw new Error("must not run"); },
  };
  const report = await runCollector({
    adapter,
    lastUseDate: "2026-10-01",
    executionDate: "2026-10-25",
    outDir: null,
    sources: ["국민 기업카드 국내 매입"],
  });
  assert.equal(report.status, "stopped");
  assert.equal(report.stopped.code, "ENV_PROBE_UNVERIFIED");
});

check("unreadable screen allowed-dates stops; unrelated sources not run", async () => {
  const adapter = {
    async probeSession() { return { authenticated: true }; },
    async readScreenAllowedDates() { return null; },
    async download() { throw new Error("must not run"); },
  };
  const report = await runCollector({
    adapter,
    lastUseDate: "2026-10-01",
    executionDate: "2026-10-25",
    outDir: null,
    sources: ["국민 기업카드 국내 매입", "국민 기업카드 해외 매입"],
  });
  assert.equal(report.status, "stopped");
  assert.equal(report.stopped.code, "ENV_PROBE_UNVERIFIED");
});

check("per-source download failure recorded; next source still attempted", async () => {
  let overseas = 0;
  const adapter = {
    async probeSession() { return { authenticated: true }; },
    async readScreenAllowedDates() { return { floor: "2026-10-01", ceiling: "2026-10-20" }; },
    async download({ source, outDir }) {
      if (source === "국민 기업카드 국내 매입") {
        throw new AdapterError("no_download_event", "no download event before timeout");
      }
      overseas += 1;
      const file = path.join(outDir, "overseas.csv");
      await writeFile(file, "merchant,amount\n", "utf8");
      return { status: "downloaded", savedPath: file, suggestedFilename: "overseas.csv", pageTotalCount: 1, summaryAvailable: true };
    },
  };
  const dir = await tempDir("kb-partial-");
  const report = await runCollector({
    adapter,
    lastUseDate: "2026-10-01",
    executionDate: "2026-10-25",
    outDir: dir,
    sources: ["국민 기업카드 국내 매입", "국민 기업카드 해외 매입"],
  });
  assert.equal(report.status, "completed_with_failures");
  assert.equal(overseas, 1);
  assert.equal(report.rows[0].verification.status, "failed");
  assert.equal(report.rows[0].verification.code, "no_download_event");
  assert.equal(report.rows[1].verification.status, "ok");
});

check("0건 only with summary basis -> no_data; missing basis -> no_data_unverified", async () => {
  async function run(entry) {
    const adapter = {
      async probeSession() { return { authenticated: true }; },
      async readScreenAllowedDates() { return { floor: "2026-10-01", ceiling: "2026-10-20" }; },
      async download() { return entry; },
    };
    return runCollector({
      adapter,
      lastUseDate: "2026-10-01",
      executionDate: "2026-10-25",
      outDir: null,
      sources: ["국민 기업카드 국내 매입"],
    });
  }
  const valid = await run({ status: "no_data", pageTotalCount: 0 });
  assert.equal(valid.rows[0].verification.status, "no_data");
  const basisOnly = await run({ status: "no_data", summaryAvailable: true });
  assert.equal(basisOnly.rows[0].verification.status, "no_data");
  const invalid = await run({ status: "no_data" });
  assert.equal(invalid.status, "completed_with_failures");
  assert.equal(invalid.rows[0].verification.status, "no_data_unverified");
  const contradict = await run({ status: "no_data", pageTotalCount: 5 });
  assert.equal(contradict.rows[0].verification.status, "no_data_unverified");
});

check("saved path outside run dir -> failed row, file never read", async () => {
  const outside = await tempDir("kb-outside-");
  const outsideFile = path.join(outside, "x.csv");
  await writeFile(outsideFile, "x", "utf8");
  const dir = await tempDir("kb-traversal-");
  const adapter = {
    async probeSession() { return { authenticated: true }; },
    async readScreenAllowedDates() { return { floor: "2026-10-01", ceiling: "2026-10-20" }; },
    async download() { return { status: "downloaded", savedPath: outsideFile, pageTotalCount: 1 }; },
  };
  const report = await runCollector({
    adapter, lastUseDate: "2026-10-01", executionDate: "2026-10-25", outDir: dir,
    sources: ["국민 기업카드 국내 매입"],
  });
  assert.equal(report.status, "completed_with_failures");
  assert.equal(report.rows[0].verification.failure, "saved_path_outside_run_dir");
});

check("reserveAbsentPath never overwrites an existing file", async () => {
  const dir = await tempDir("kb-reserve-");
  const target = path.join(dir, "kb-domestic-acquired-2026-10-01-2026-10-20.xls");
  await writeFile(target, "first", "utf8");
  const second = await reserveAbsentPath(target);
  assert.notEqual(second, target);
  assert.equal(await readFile(target, "utf8"), "first");
  await writeFile(second, "second", "utf8");
  const third = await reserveAbsentPath(target);
  assert.notEqual(third, target);
  assert.notEqual(third, second);
});

check("--help / CLI usage: help text, unknown option, unknown source", async () => {
  const { spawnSync } = await import("node:child_process");
  const { fileURLToPath } = await import("node:url");
  const entry = fileURLToPath(new URL("../../tools/collect_kb_card.mjs", import.meta.url));
  const help = spawnSync(process.execPath, [entry, "--help"], { encoding: "utf8" });
  assert.equal(help.status, 0);
  assert.equal(help.stdout.includes("usage: collect_kb_card.mjs"), true);
  const unknownOption = spawnSync(process.execPath, [entry, "--nope"], { encoding: "utf8" });
  assert.equal(unknownOption.status, 2);
  assert.equal(JSON.parse(unknownOption.stderr).code, "CLI_USAGE");
  const unknownSource = spawnSync(process.execPath, [entry, "--source", "amex"], { encoding: "utf8" });
  assert.equal(unknownSource.status, 2);
  assert.equal(JSON.parse(unknownSource.stderr).code, "UNKNOWN_SOURCE");
});

await Promise.all(pending);
process.stdout.write(failures === 0 ? "REPORT OK\n" : `REPORT FAIL ${failures}\n`);
process.exitCode = failures === 0 ? 0 : 1;
