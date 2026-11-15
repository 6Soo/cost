// 합성 검증: runParserVerification 프로토콜(스폰/종료코드/JSON 파싱/인자 전달). 실제 기존 파서가 아니라 프로토콜 대역
// 과정을 검증하는 가짜 node "파서" 프로세스를 띄운다. 실제 파서 연결·건수 일치는 별도 단계다.
import assert from "node:assert/strict";
import { mkdtemp, writeFile } from "node:fs/promises";
import { rmSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";

import {
  PARSER_VERIFICATION_NOT_RUN,
  runParserVerification,
} from "../../tools/kb_card_collection/verify_python.mjs";

let failures = 0;
const pending = [];
function check(name, fn) {
  const p = Promise.resolve()
    .then(fn)
    .then(() => process.stdout.write(`PASS ${name}\n`))
    .catch((err) => {
      failures += 1;
      process.stdout.write(`FAIL ${name}: ${err && err.message ? err.message : err}\n`);
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
function makeScript(lines) {
  return lines.join("\n") + "\n";
}

const OK_SCRIPT = makeScript([
  'const args = process.argv.slice(2);',
  'const fileIndex = args.indexOf("--file");',
  'const label = fileIndex >= 0 ? args[fileIndex + 1] : "";',
  'process.stdout.write(JSON.stringify({',
  '  status: "parsed", rows: label === "missing" ? 0 : 2, parse_issues: 0,',
  '  parser: label, channel: "domestic_acquired",',
  '}) + "\\n");',
]);
const INVALID_JSON = makeScript(['process.stdout.write("not json at all\\n");']);
const VALID_JSON_EXIT_1 = makeScript([
  'process.stdout.write(JSON.stringify({ status: "parsed", rows: 1 }) + "\\n");',
  "process.exit(1);",
]);
const UNAVAILABLE_EXIT_3 = makeScript([
  'process.stdout.write(JSON.stringify({ status: "unavailable" }) + "\\n");',
  "process.exit(3);",
]);
const ARGS_SCRIPT = makeScript([
  "const args = process.argv.slice(2);",
  'const i = args.indexOf("--file");',
  'const out = { status: "parsed", rows: i >= 0 ? 2 : 1, parse_issues: 0,',
  '  parser: "fake:" + (i >= 0 ? "hasfile" : "nofile"), channel: "domestic_acquired" };',
  'process.stdout.write(JSON.stringify(out) + "\\n");',
]);

async function withScript(name, body, fn) {
  const dir = await tempDir("kb-pv-");
  const script = path.join(dir, `${name}.mjs`);
  await writeFile(script, body, "utf8");
  const file = path.join(dir, "downloaded.csv");
  await writeFile(file, "synthetic-bytes\n", "utf8");
  return fn({ script, file });
}

check("unconfigured -> PARSER_VERIFICATION_NOT_RUN without a process", async () => {
  const result = await runParserVerification({});
  assert.equal(result.status, PARSER_VERIFICATION_NOT_RUN);
});

check("ok path: parses counts only; source text is never echoed", async () => {
  await withScript("ok", OK_SCRIPT, async ({ script, file }) => {
    const result = await runParserVerification({ command: process.execPath, module: script, filePath: file });
    assert.equal(result.status, "PARSER_VERIFICATION_OK");
    assert.equal(result.rows, 2);
    assert.equal(result.parse_issues, 0);
    assert.equal(result.channel, "domestic_acquired");
    assert.equal(JSON.stringify(result).includes("synthetic-bytes"), false);
  });
});

check("non-JSON output -> PARSER_VERIFICATION_INVALID_OUTPUT", async () => {
  await withScript("invalid", INVALID_JSON, async ({ script, file }) => {
    const result = await runParserVerification({ command: process.execPath, module: script, filePath: file });
    assert.equal(result.status, "PARSER_VERIFICATION_INVALID_OUTPUT");
  });
});

check("valid JSON but non-zero exit -> PARSER_VERIFICATION_FAILED", async () => {
  await withScript("exit1", VALID_JSON_EXIT_1, async ({ script, file }) => {
    const result = await runParserVerification({ command: process.execPath, module: script, filePath: file });
    assert.equal(result.status, "PARSER_VERIFICATION_FAILED");
    assert.equal(result.code, 1);
  });
});

check("unavailable verdict -> PARSER_VERIFICATION_UNAVAILABLE", async () => {
  await withScript("unavailable", UNAVAILABLE_EXIT_3, async ({ script, file }) => {
    const result = await runParserVerification({ command: process.execPath, module: script, filePath: file });
    assert.equal(result.status, "PARSER_VERIFICATION_UNAVAILABLE");
  });
});

check("--file delivered as a real argument", async () => {
  await withScript("args", ARGS_SCRIPT, async ({ script, file }) => {
    const result = await runParserVerification({ command: process.execPath, module: script, filePath: file });
    assert.equal(result.status, "PARSER_VERIFICATION_OK");
    assert.equal(result.parser, "fake:hasfile");
    assert.equal(result.rows, 2);
  });
});

await Promise.all(pending);
process.stdout.write(failures === 0 ? "PARSER VERIFY OK\n" : `PARSER VERIFY FAIL ${failures}\n`);
process.exitCode = failures === 0 ? 0 : 1;
