// 합성 Page + 기존 합성 XLS + 실제 읽기 전용 Python 파서. 고객/사이트/DB 접근 없음.
import assert from 'node:assert/strict';
import { copyFile, mkdtemp, readFile, rm } from 'node:fs/promises';
import path from 'node:path';
import { tmpdir } from 'node:os';
import { runCollector } from '../../tools/collect_kb_card.mjs';
import * as entry from '../../tools/kb_card_collection/entry_kb.mjs';
import { setContextRuntime, resetContextRuntime } from '../../tools/kb_card_collection/ego_context.mjs';
import { SOURCES } from '../../tools/kb_card_collection/policy.mjs';

const root = await mkdtemp(path.join(tmpdir(), 'kb-e2e-'));
let queried = false;
let resolveDownload;
const calls = [];
const values = { session: 'authenticated', dateFloor: '2026-01-01', dateCeiling: '2026-11-10',
  periodEchoStart: '2026-10-01', periodEchoEnd: '2026-11-10', periodEchoSource: '국내 매입',
  summaryResults: '총 3건', downloadControl: '저장', exportOpenControl: 'XLS 파일저장' };
const roles = Object.fromEntries([...Object.keys(values), 'dateStartInput', 'dateEndInput', 'searchControl']
  .map((role) => [role, 'css=#' + role]));
const page = {
  async goto() { queried = false; },
  async snapshot() { return ''; },
  async evaluate(fn, argument) {
    globalThis.document = { querySelectorAll(selector) {
      const role = selector.slice(1);
      const value = role === 'summaryResults' && !queried ? '총 99건' : values[role];
      return value === undefined ? [] : [{ textContent: value }];
    } };
    try { return fn(argument); } finally { delete globalThis.document; }
  },
  async fill() {},
  async click(selector) {
    calls.push(selector);
    if (selector.endsWith('searchControl')) queried = true;
    if (selector.endsWith('downloadControl')) {
      assert.ok(resolveDownload, 'download wait must be armed before click');
      resolveDownload({ suggestedFilename() { return 'synthetic.xls'; },
        async saveAs(destination) { await copyFile('tests/card_pipeline/data/kb-domestic-acquired-synthetic.xls', destination); } });
    }
  },
  waitForEvent() { calls.push('arm'); return new Promise((resolve) => { resolveDownload = resolve; }); },
};
const adapter = { probeSession: entry.probeSession, readScreenAllowedDates: entry.readScreenAllowedDates, download: entry.download };
try {
  setContextRuntime({ taskSpace: async () => ({ tabs: async () => [{ label: 'p1', page }] }) });
  entry.setEntryRuntime({ selectors: { roles }, spaceName: 'synthetic' });
  const run = (name, previousManifest = null) => runCollector({ adapter, sources: [SOURCES.DOMESTIC],
    lastUseDate: '2026-10-01', executionDate: '2026-11-11', outDir: path.join(root, name),
    parser: { command: 'python', module: path.resolve('tools/kb_card_collection/verify_xls.py') }, previousManifest });
  const first = await run('first');
  assert.equal(first.status, 'ok');
  assert.equal(first.rows[0].countCheck.status, 'MATCHED');
  assert.equal(first.rows[0].parserVerification.rows, 3);
  assert.ok(calls.indexOf('arm') < calls.indexOf('css=#downloadControl'));
  assert.ok(calls.indexOf('css=#exportOpenControl') < calls.indexOf('arm'));
  const persisted = JSON.parse(await readFile(first.manifestPath, 'utf8'));
  assert.equal(persisted.importBoundary.status, 'NOT_RUN');
  console.log('PASS synthetic Page query → download → actual XLS parser → count → import boundary');
  const second = await run('second', persisted);
  assert.equal(second.rows[0].duplicateCheck.status, 'DUPLICATE_FILE');
  assert.equal(second.rows[0].duplicateCheck.databaseRows, 'NOT_RUN');
  console.log('PASS prior manifest duplicate SHA is detected without changing original files');
  values.summaryResults = '총 4건';
  const mismatch = await run('mismatch');
  assert.equal(mismatch.status, 'completed_with_failures');
  assert.equal(mismatch.rows[0].countCheck.status, 'FAILED');
  console.log('PASS screen/file count mismatch fails collection verification');
  values.summaryResults = '0건';
  const before = calls.filter((call) => call === 'arm').length;
  const empty = await run('zero');
  assert.equal(empty.rows[0].verification.status, 'no_data');
  assert.equal(calls.filter((call) => call === 'arm').length, before);
  console.log('PASS zero screen summary does not arm or trigger downloads');
} finally {
  entry.resetEntryRuntime(); resetContextRuntime();
  await rm(root, { recursive: true, force: true });
}
