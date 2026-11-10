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
