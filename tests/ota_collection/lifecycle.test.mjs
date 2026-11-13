import { test } from 'node:test';
import assert from 'node:assert/strict';
import {
  MAX_FAILURES,
  PROVIDER_LIST,
  STATUS,
  maxStatus,
  severityOf,
} from '../../tools/ota_collection/constants.mjs';
import { isOtaError, OtaError, statusForError } from '../../tools/ota_collection/errors.mjs';
import { makeRequester } from '../../tools/ota_collection/http.mjs';
import { createBudget, runPool } from '../../tools/ota_collection/collector.mjs';
import { buildPlanText, parseProviders, EGO_RUN_COMMAND } from '../../tools/collect_ota_portals.mjs';
import { sha256 } from '../../tools/ota_collection/storage.mjs';
import { writeCollectionRunSummaries } from '../../tools/ota_collection/manifest.mjs';
import { readFile, mkdtemp, rm, writeFile } from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import { response } from './helpers.mjs';

test('provider list and plan helper stay inside the owned three providers', () => {
  assert.deepEqual([...PROVIDER_LIST], ['agoda', 'trip', 'booking']);
  assert.deepEqual(parseProviders('agoda, trip'), ['agoda', 'trip']);
  assert.deepEqual(parseProviders(''), ['agoda', 'trip', 'booking']);
  assert.throws(() => parseProviders('expedia'), /unknown provider/);
  assert.throws(() => parseProviders(',,,'), /unknown provider/);
  const plan = buildPlanText(['booking']);
  assert.match(plan, /read-only OTA portal collection/);
  assert.match(plan, /--plan/);
  assert.ok(EGO_RUN_COMMAND.startsWith('ego-browser nodejs'));
});

test('status ordering treats capture-required and login-required as worse than partial', () => {
  assert.equal(severityOf(STATUS.LOGIN_REQUIRED), 5);
  assert.equal(severityOf(STATUS.INTERRUPTED), 4);
  assert.ok(severityOf(STATUS.CAPTURE_REQUIRED) === 3);
  assert.ok(severityOf(STATUS.PARTIAL) <= severityOf(STATUS.CAPTURE_REQUIRED));
  assert.equal(maxStatus([STATUS.OK, STATUS.PARTIAL, STATUS.INVALID]), STATUS.PARTIAL);
  assert.equal(maxStatus([STATUS.OK, STATUS.CAPTURE_REQUIRED, STATUS.INTERRUPTED]), STATUS.INTERRUPTED);
});

test('OtaError carries class so callers map to honest statuses', () => {
  assert.equal(isOtaError(new OtaError('LOGIN_REQUIRED', { cls: 'auth' })), true);
  assert.equal(statusForError(new OtaError('HTTP_ERROR', { cls: 'http' })), 'FAILED');
  assert.equal(statusForError(new OtaError('SHAPE', { cls: 'shape' })), STATUS.CAPTURE_REQUIRED);
  assert.equal(statusForError(new OtaError('IDENTITY', { cls: 'identity' })), 'invalid');
  assert.equal(statusForError(new OtaError('X', { cls: 'abort' })), STATUS.INTERRUPTED);
  assert.equal(statusForError(new OtaError('X', { cls: 'auth' })), STATUS.LOGIN_REQUIRED);
});

test('network requests back off with exponential waits and stop at attemptCap', async () => {
  let calls = 0;
  const waits = [];
  const sleeper = makeRequester(async () => {
    calls += 1;
    if (calls < 3) throw new TypeError('fetch failed');
    return response(200, { ok: true });
  }, { retryDelay: (attempt) => { waits.push(attempt); return 0; }, attemptCap: 3 });
  const result = await sleeper('http://synthetic.invalid/list', { method: 'GET' });
  assert.equal(result.status, 200);
  assert.deepEqual(waits, [1, 2]);
  assert.equal(calls, 3);

  let exhausted = 0;
  const failing = makeRequester(async () => { exhausted += 1; throw new TypeError('offline'); }, { retryDelay: () => 0, attemptCap: 2 });
  await assert.rejects(failing('http://synthetic.invalid/offline'), (error) => isOtaError(error) && error.cls === 'network');
  assert.equal(exhausted, 2);
});

test('login responses are classified as LOGIN_REQUIRED instead of escaping as generic failed', async () => {
  const requester = makeRequester(async () => response(401, { message: 'unauthenticated' }), { retryDelay: () => 0, attemptCap: 3, authStatuses: [401, 403] });
  await assert.rejects(requester('http://synthetic.invalid/account'), (error) => isOtaError(error) && error.code === 'LOGIN_REQUIRED');

  const plain = makeRequester(async () => response(401, { message: 'unauthenticated' }), { retryDelay: () => 0, attemptCap: 1 });
  await assert.rejects(plain('http://synthetic.invalid/account'), (error) => isOtaError(error) && error.cls === 'http');
});

test('budget stops after a bounded number of failures and counts list requests', () => {
  const budget = createBudget({ maxFailures: MAX_FAILURES });
  for (let i = 0; i < MAX_FAILURES; i += 1) budget.spike();
  assert.equal(budget.failures(), MAX_FAILURES);
  assert.equal(budget.failureLimitReached(), false, '30 failures are allowed; more stops the run');
  budget.spike();
  assert.equal(budget.failureLimitReached(), true);
  budget.bumpList();
  budget.bumpList();
  assert.equal(budget.listRequests(), 2);
});

test('runPool never exceeds its lane limit and preserves result order', async () => {
  let active = 0;
  let peak = 0;
  const values = Array.from({ length: 9 }, (_, index) => index);
  const results = await runPool(values, 3, async (value) => {
    active += 1;
    peak = Math.max(peak, active);
    await new Promise((resolve) => setTimeout(resolve, 2));
    active -= 1;
    return value * 2;
  });
  assert.equal(peak, 3);
  assert.deepEqual(results.map((entry) => entry.value), values.map((value) => value * 2));
});

test('sha256 is stable and digest-shaped', () => {
  assert.match(sha256('synthetic'), /^[0-9a-f]{64}$/);
  assert.equal(sha256('synthetic'), sha256('synthetic'));
  assert.notEqual(sha256('synthetic'), sha256('synthetic2'));
});

test('final OTA manifest writes minimal login summaries and a later success clears login_required', async () => {
  const dataRoot = await mkdtemp(path.join(os.tmpdir(), 'collection-run-summary-'));
  const previous = process.env.WEBLEDGER_DATA_ROOT;
  process.env.WEBLEDGER_DATA_ROOT = dataRoot;
  try {
    await writeCollectionRunSummaries({ providers: [
      { provider: 'agoda', status: STATUS.LOGIN_REQUIRED },
      { provider: 'trip', status: STATUS.AUTH_UNKNOWN },
      { provider: 'booking', status: STATUS.FAILED },
    ] });
    const agodaPath = path.join(dataRoot, 'collection-runs', 'agoda.json');
    const first = JSON.parse(await readFile(agodaPath, 'utf8'));
    assert.deepEqual(Object.keys(first).sort(), ['finished_at', 'login_required', 'schema', 'source', 'status']);
    assert.equal(first.login_required, true);
    assert.equal(first.source, 'agoda');
    assert.equal(first.status, STATUS.LOGIN_REQUIRED);
    assert.equal(await readFile(path.join(dataRoot, 'collection-runs', 'trip.json'), 'utf8').then(JSON.parse).then((x) => x.login_required), true);
    await assert.rejects(() => readFile(path.join(dataRoot, 'collection-runs', 'booking.json')));

    await writeCollectionRunSummaries({ providers: [{ provider: 'agoda', status: STATUS.OK }] });
    const success = JSON.parse(await readFile(agodaPath, 'utf8'));
    assert.equal(success.login_required, false);
    assert.equal(success.status, STATUS.OK);
  } finally {
    if (previous === undefined) delete process.env.WEBLEDGER_DATA_ROOT;
    else process.env.WEBLEDGER_DATA_ROOT = previous;
    await rm(dataRoot, { recursive: true, force: true });
  }
});

test('summary write failure is swallowed with a warning and does not stop collection', async () => {
  const dataRoot = await mkdtemp(path.join(os.tmpdir(), 'collection-run-summary-fail-'));
  const blocker = path.join(dataRoot, 'not-a-directory');
  await writeFile(blocker, 'x');
  const previous = process.env.WEBLEDGER_DATA_ROOT;
  process.env.WEBLEDGER_DATA_ROOT = blocker; // mkdir(<file>/collection-runs) fails
  const originalWrite = process.stderr.write.bind(process.stderr);
  let warned = '';
  process.stderr.write = (chunk) => { warned += String(chunk); return true; };
  try {
    await writeCollectionRunSummaries({ providers: [{ provider: 'agoda', status: STATUS.LOGIN_REQUIRED }] });
  } finally {
    process.stderr.write = originalWrite;
    if (previous === undefined) delete process.env.WEBLEDGER_DATA_ROOT;
    else process.env.WEBLEDGER_DATA_ROOT = previous;
    await rm(dataRoot, { recursive: true, force: true });
  }
  assert.match(warned, /collection run summary not written/);
  assert.doesNotMatch(warned, /agoda|not-a-directory/);
});
