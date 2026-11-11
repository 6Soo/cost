// 합성 검증: 조회기간/소스 정책 경계. 네트워크·브라우저·파일·스토어 없음.
import assert from "node:assert/strict";

import {
  PolicyError,
  POSTING_AXIS,
  SOURCE_URLS,
  sourcesFromFlag,
  buildPeriod,
} from "../../tools/kb_card_collection/policy.mjs";

let failures = 0;
function check(name, fn) {
  try {
    fn();
    process.stdout.write(`PASS ${name}\n`);
  } catch (err) {
    failures += 1;
    process.stdout.write(`FAIL ${name}: ${err && err.message}\n`);
  }
}

check("start day is caller last-use day, no day subtracted", () => {
  const p = buildPeriod({
    lastUseDate: "2026-10-01",
    executionDate: "2026-10-31",
    allowedCeiling: { floor: "2026-10-01", ceiling: "2026-10-31" },
  });
  assert.equal(p.status, "OK");
  assert.equal(p.startDate, "2026-10-01");
  assert.equal(p.postingAxis, POSTING_AXIS);
});

check("end day = min(screen ceiling, execution date)", () => {
  const a = buildPeriod({
    lastUseDate: "2026-10-01",
    executionDate: "2026-10-31",
    allowedCeiling: { floor: "2026-10-01", ceiling: "2026-10-20" },
  });
  assert.equal(a.endDate, "2026-10-20");
  const b = buildPeriod({
    lastUseDate: "2026-10-01",
    executionDate: "2026-10-10",
    allowedCeiling: { floor: "2026-10-01", ceiling: "2026-10-20" },
  });
  assert.equal(b.endDate, "2026-10-10");
});

check("missing screen allowed-dates -> ENV_PROBE_UNVERIFIED, no substitution", () => {
  const p = buildPeriod({
    lastUseDate: "2026-10-01",
    executionDate: "2026-10-31",
    allowedCeiling: null,
  });
  assert.equal(p.status, "ENV_PROBE_UNVERIFIED");
  assert.equal(p.startDate, null);
  assert.equal(p.endDate, null);
  assert.notEqual(p.endDate, "2026-10-31");
});

check("invalid screen window -> PolicyError", () => {
  assert.throws(() => buildPeriod({
    lastUseDate: "2026-10-01",
    executionDate: "2026-10-02",
    allowedCeiling: { floor: "2026-10-31", ceiling: "2026-10-01" },
  }), PolicyError);
});

check("empty resolved window -> NO_WINDOW", () => {
  const p = buildPeriod({
    lastUseDate: "2026-10-05",
    executionDate: "2026-10-04",
    allowedCeiling: { floor: "2026-10-01", ceiling: "2026-10-04" },
  });
  assert.equal(p.status, "NO_WINDOW");
});

check("lookback clamp reported, not silent", () => {
  const p = buildPeriod({
    lastUseDate: "2020-01-01",
    executionDate: "2026-10-31",
    allowedCeiling: { floor: "2020-01-01", ceiling: "2026-10-31" },
    maxLookbackDays: 100,
  });
  assert.equal(p.status, "OK");
  assert.equal(p.clampedByLookback, true);
  assert.equal(p.endDate, "2020-04-10");
});

check("bad date strings rejected", () => {
  assert.throws(() => buildPeriod({ lastUseDate: "2026-13-01", executionDate: "2026-10-01", allowedCeiling: { floor: "2026-10-01", ceiling: "2026-10-31" } }), PolicyError);
  assert.throws(() => buildPeriod({ lastUseDate: "2026-10-01", executionDate: "not-a-date", allowedCeiling: { floor: "2026-10-01", ceiling: "2026-10-31" } }), PolicyError);
});

check("source selection mirrors domestic/overseas/both", () => {
  assert.deepEqual(sourcesFromFlag("domestic"), ["국민 기업카드 국내 매입"]);
  assert.deepEqual(sourcesFromFlag("overseas"), ["국민 기업카드 해외 매입"]);
  assert.deepEqual(sourcesFromFlag("both"), ["국민 기업카드 국내 매입", "국민 기업카드 해외 매입"]);
  assert.equal(sourcesFromFlag("nope"), null);
});

check("official sources map to kbcard paths", () => {
  assert.equal(SOURCE_URLS["국민 기업카드 국내 매입"], "https://biz.kbcard.com/CXERCMLSD0002.cms");
  assert.equal(SOURCE_URLS["국민 기업카드 해외 매입"], "https://biz.kbcard.com/CXERCMLS0008.cms");
});

process.stdout.write(failures === 0 ? "POLICY OK\n" : `POLICY FAIL ${failures}\n`);
process.exitCode = failures === 0 ? 0 : 1;
