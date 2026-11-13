// 하나/IBK 공통 수집 경계. 미관측 화면에서는 절대 조회/저장하지 않는다.
import { createHash } from "node:crypto";
import { mkdir, writeFile } from "node:fs/promises";
import path from "node:path";
import { ensureCardLogin, STATUS } from "./card_login/common.mjs";

const PROVIDERS = {
  hana: { issuer: "hana", source: "하나 기업카드 이용내역", entry: "./card_login/hana.mjs" },
  ibk: { issuer: "ibk", source: "IBK 기업카드 이용내역", entry: "./card_login/ibk.mjs" },
};
const iso = (v) => /^\d{4}-\d\d-\d\d$/.test(v || "");
export function countCheck(parsedCount, screenCount) {
  return Number.isSafeInteger(parsedCount) && parsedCount >= 0 &&
    Number.isSafeInteger(screenCount) && screenCount >= 0 && parsedCount === screenCount
    ? { status: "MATCHED", parsedCount, screenCount }
    : { status: "FAILED", parsedCount: Number.isSafeInteger(parsedCount) ? parsedCount : null,
        screenCount: Number.isSafeInteger(screenCount) ? screenCount : null };
}
export function fileEvidence(bytes) {
  return { bytes: bytes.length, sha256: createHash("sha256").update(bytes).digest("hex") };
}
export async function runProviderCollection(provider, args = process.argv.slice(2)) {
  const config = PROVIDERS[provider];
  if (!config) throw new Error("unsupported provider");
  const report = { schemaVersion: "cost.kb-card-collection-manifest.v1",
    runId: `${provider}-${new Date().toISOString().replaceAll(":", "-")}`,
    generatedAt: new Date().toISOString(), executionDate: null,
    requestedSources: [config.source], rows: [], selectorStatus: "NOT_VERIFIED",
    importBoundary: { status: "NOT_RUN", reason: "site selectors and download flow are NOT_VERIFIED" },
    stopped: { code: "NOT_VERIFIED", message: "site screen interaction is not verified" } };
  // Login uses the approved interface only. A missing browser/task/page fails closed before any attempt.
  const page = globalThis.__COST_CARD_PAGE__;
  const task = globalThis.__COST_CARD_TASK__;
  if (page) {
    const site = await import(config.entry);
    const status = await ensureCardLogin({ task, page, site: site.default ?? site });
    if ([STATUS.REGISTRATION_REQUIRED, STATUS.LOGIN_FAILED, STATUS.ERROR].includes(status.status)) {
      report.stopped = status.status === STATUS.REGISTRATION_REQUIRED ? "LOGIN_REQUIRED" : status.status;
    }
  } else {
    report.stopped = "LOGIN_REQUIRED";
  }
  const outDirIndex = args.findIndex((x) => x === "--out-dir");
  const outDir = args.find((x) => x.startsWith("--out-dir="))?.slice(10) ??
    (outDirIndex >= 0 ? args[outDirIndex + 1] : null);
  if (outDir) {
    await mkdir(outDir, { recursive: true });
    const manifest = path.join(outDir, "manifest.json");
    await writeFile(manifest, JSON.stringify(report, null, 2) + "\n", { encoding: "utf8", flag: "wx" });
  }
  return report;
}
