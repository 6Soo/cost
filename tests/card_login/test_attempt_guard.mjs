// 합성 전용 영속 시도 가드 검사. 실제 사이트·운영 상태 파일 접근 없음(임시 폴더만 사용).
// 검증: 실패/대기 기록 후 재시도 차단, reset 후 허용, 성공은 비차단, 사유 비밀 마스킹,
//       시도 전 'attempting' 기록(비정상 종료 시 차단), 깨진/읽기 불가/쓰기 불가 저장소 → 미시도(fail-closed),
//       원자적 쓰기, reset_attempt.ps1 실제 실행으로 사이트 기록 해제.
// 실행: node tests/card_login/test_attempt_guard.mjs → PASS/FAIL 줄 + 요약, 실패 시 nonzero exit.
import assert from 'node:assert';
import { spawnSync } from 'node:child_process';
import { mkdtemp, readFile, writeFile, chmod, readdir, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import {
  readAttempt, isBlocked, beginAttempt, recordAttempt, resetAttempt, ATTEMPTS_SCHEMA,
} from '../../tools/card_login/attempts.mjs';
import { ensureCardLogin, STATUS, _resetAttemptGuard } from '../../tools/card_login/common.mjs';

const HERE = path.dirname(fileURLToPath(import.meta.url));
const RESET_SCRIPT = path.join(HERE, '..', '..', 'tools', 'card_login', 'reset_attempt.ps1');

let failures = 0;
async function test(name, fn) {
  try { await fn(); console.log(`PASS ${name}`); }
  catch (err) { failures += 1; console.log(`FAIL ${name}: ${err && err.message ? err.message : err}`); }
}

const SECRET_PW = 'synthetic-pw-456';
const creds = { status: 'ok', id: 'synthetic-id-123', password: SECRET_PW, certPassword: 'synthetic-cert-789' };

async function withTemp(fn) {
  const dir = await mkdtemp(path.join(tmpdir(), 'card-guard-test-'));
  const attemptsPath = path.join(dir, 'attempts.json');
  try { await fn({ dir, attemptsPath }); } finally { await rm(dir, { recursive: true, force: true }); }
}

function fakeSite(overrides = {}) {
  return {
    issuer: 'kb', isLoggedIn: async () => false,
    login: async () => ({ outcome: 'success', detail: 'ok' }),
    confirmUsageScreen: async () => true, logout: async () => {}, ...overrides,
  };
}

await test('no record -> not blocked', () => withTemp(async ({ attemptsPath }) => {
  assert.equal(await isBlocked('kb', { path: attemptsPath }), false);
  assert.equal(await readAttempt('kb', { path: attemptsPath }), null);
}));

await test('login_failed record -> blocked', () => withTemp(async ({ attemptsPath }) => {
  await recordAttempt('kb', { outcome: 'login_failed', reason: 'bad_pw' }, { path: attemptsPath });
  assert.equal(await isBlocked('kb', { path: attemptsPath }), true);
}));

await test('verified record -> not blocked (success does not block)', () => withTemp(async ({ attemptsPath }) => {
  await recordAttempt('kb', { outcome: 'verified', reason: 'usage_screen_confirmed' }, { path: attemptsPath });
  assert.equal(await isBlocked('kb', { path: attemptsPath }), false);
}));

await test('additional_auth_required record -> blocked', () => withTemp(async ({ attemptsPath }) => {
  await recordAttempt('hana', { outcome: 'additional_auth_required', reason: 'otp' }, { path: attemptsPath });
  assert.equal(await isBlocked('hana', { path: attemptsPath }), true);
}));

await test('agent_assist_required record -> blocked', () => withTemp(async ({ attemptsPath }) => {
  await recordAttempt('ibk', { outcome: 'agent_assist_required', reason: 'keypad_password' }, { path: attemptsPath });
  assert.equal(await isBlocked('ibk', { path: attemptsPath }), true);
}));

await test('resetAttempt clears block', () => withTemp(async ({ attemptsPath }) => {
  await recordAttempt('kb', { outcome: 'login_failed', reason: 'bad_pw' }, { path: attemptsPath });
  assert.equal(await isBlocked('kb', { path: attemptsPath }), true);
  const existed = await resetAttempt('kb', { path: attemptsPath });
  assert.equal(existed, true);
  assert.equal(await isBlocked('kb', { path: attemptsPath }), false);
}));

await test('attempts file masks secrets in reason and stores schema', () => withTemp(async ({ attemptsPath }) => {
  await recordAttempt('kb', { outcome: 'login_failed', reason: `err ${SECRET_PW}`, secrets: [SECRET_PW] }, { path: attemptsPath });
  const body = await readFile(attemptsPath, 'utf8');
  assert.ok(!body.includes(SECRET_PW), 'password leaked into attempts.json');
  const data = JSON.parse(body);
  assert.equal(data.schema, ATTEMPTS_SCHEMA);
  assert.equal(data.issuers.kb.lastOutcome, 'login_failed');
  assert.ok(data.issuers.kb.reason.includes('[REDACTED]'));
}));

await test('integration: failure blocks re-run, reset allows, then success', () => withTemp(async ({ dir, attemptsPath }) => {
  const env = { attemptsPath, assistDir: path.join(dir, 'assist'), statusDir: path.join(dir, 'status') };
  let loginCalls = 0;
  const site = fakeSite({ login: async () => { loginCalls += 1; return { outcome: 'failed', detail: 'bad_pw' }; } });
  _resetAttemptGuard();
  const first = await ensureCardLogin({ task: null, page: {}, site, credentials: creds, ...env });
  assert.equal(first.status, STATUS.LOGIN_FAILED);
  assert.equal(loginCalls, 1);
  // 재실행: 영속 기록 때문에 시도하지 않는다.
  _resetAttemptGuard();
  const blocked = await ensureCardLogin({ task: null, page: {}, site, credentials: creds, ...env });
  assert.equal(blocked.reason, 'attempt_blocked_until_reset');
  assert.equal(loginCalls, 1);
  // 사용자 해제 후: 다시 시도 허용.
  await resetAttempt('kb', { path: attemptsPath });
  _resetAttemptGuard();
  const siteOk = fakeSite({ login: async () => { loginCalls += 1; return { outcome: 'success', detail: 'ok' }; } });
  const after = await ensureCardLogin({ task: null, page: {}, site: siteOk, credentials: creds, ...env });
  assert.equal(after.status, STATUS.VERIFIED);
  assert.equal(loginCalls, 2);
  // 성공 기록은 다음 시도를 막지 않는다.
  assert.equal(await isBlocked('kb', { path: attemptsPath }), false);
}));

await test('reset_attempt.ps1 removes issuer entry (real script)', () => withTemp(async ({ attemptsPath }) => {
  await recordAttempt('kb', { outcome: 'login_failed', reason: 'bad_pw' }, { path: attemptsPath });
  await recordAttempt('hana', { outcome: 'login_failed', reason: 'bad_pw' }, { path: attemptsPath });
  const run = spawnSync('powershell.exe', [
    '-NoProfile', '-NonInteractive', '-ExecutionPolicy', 'Bypass',
    '-File', RESET_SCRIPT, '-Issuer', 'kb', '-AttemptsPath', attemptsPath,
  ], { encoding: 'utf8', windowsHide: true });
  assert.equal(run.status, 0, `reset script failed: ${run.stderr || run.stdout}`);
  const data = JSON.parse(await readFile(attemptsPath, 'utf8'));
  assert.equal(data.schema, ATTEMPTS_SCHEMA);
  assert.ok(!Object.prototype.hasOwnProperty.call(data.issuers, 'kb'), 'kb not removed');
  assert.ok(Object.prototype.hasOwnProperty.call(data.issuers, 'hana'), 'hana should remain');
  assert.equal(await isBlocked('kb', { path: attemptsPath }), false);
}));

await test('beginAttempt writes attempting and blocks', () => withTemp(async ({ attemptsPath }) => {
  const rec = await beginAttempt('kb', { path: attemptsPath });
  assert.equal(rec.lastOutcome, 'attempting');
  assert.equal(rec.blocked, true);
  assert.equal(await isBlocked('kb', { path: attemptsPath }), true);
}));

await test('success leaves verified, not attempting', () => withTemp(async ({ dir, attemptsPath }) => {
  const env = { attemptsPath, assistDir: path.join(dir, 'assist'), statusDir: path.join(dir, 'status') };
  _resetAttemptGuard();
  const site = fakeSite({ login: async () => ({ outcome: 'success', detail: 'ok' }) });
  const res = await ensureCardLogin({ task: null, page: {}, site, credentials: creds, ...env });
  assert.equal(res.status, STATUS.VERIFIED);
  const after = await readAttempt('kb', { path: attemptsPath });
  assert.equal(after.lastOutcome, 'verified');
}));

await test('attempting leftover (abnormal exit) -> re-run does not attempt until reset', () => withTemp(async ({ dir, attemptsPath }) => {
  const env = { attemptsPath, assistDir: path.join(dir, 'assist'), statusDir: path.join(dir, 'status') };
  // 비정상 종료 모사: 시도 전 기록만 남기고 결과 기록 없이 중단.
  await beginAttempt('kb', { path: attemptsPath });
  let loginCalls = 0;
  const site = fakeSite({ login: async () => { loginCalls += 1; return { outcome: 'success' }; } });
  _resetAttemptGuard();
  const res = await ensureCardLogin({ task: null, page: {}, site, credentials: creds, ...env });
  assert.equal(res.status, STATUS.LOGIN_FAILED);
  assert.equal(res.reason, 'attempt_blocked_until_reset');
  assert.equal(loginCalls, 0);
  _resetAttemptGuard();
  const again = await ensureCardLogin({ task: null, page: {}, site, credentials: creds, ...env });
  assert.equal(again.reason, 'attempt_blocked_until_reset');
  assert.equal(loginCalls, 0);
  // 사용자 해제 후 허용.
  await resetAttempt('kb', { path: attemptsPath });
  _resetAttemptGuard();
  const after = await ensureCardLogin({ task: null, page: {}, site, credentials: creds, ...env });
  assert.equal(after.status, STATUS.VERIFIED);
  assert.equal(loginCalls, 1);
}));

await test('corrupt attempts.json -> no attempt (fail-closed)', () => withTemp(async ({ dir, attemptsPath }) => {
  await writeFile(attemptsPath, '{ this is not valid json', 'utf8');
  const env = { attemptsPath, assistDir: path.join(dir, 'assist'), statusDir: path.join(dir, 'status') };
  let loginCalls = 0;
  const site = fakeSite({ login: async () => { loginCalls += 1; return { outcome: 'success' }; } });
  _resetAttemptGuard();
  const res = await ensureCardLogin({ task: null, page: {}, site, credentials: creds, ...env });
  assert.equal(res.status, STATUS.ERROR);
  assert.equal(res.reason, 'attempts_store_unreadable');
  assert.equal(loginCalls, 0);
}));

await test('schema-mismatch attempts.json -> no attempt (fail-closed)', () => withTemp(async ({ dir, attemptsPath }) => {
  await writeFile(attemptsPath, JSON.stringify({ schema: 'wrong-schema', issuers: {} }), 'utf8');
  const env = { attemptsPath, assistDir: path.join(dir, 'assist'), statusDir: path.join(dir, 'status') };
  let loginCalls = 0;
  const site = fakeSite({ login: async () => { loginCalls += 1; return { outcome: 'success' }; } });
  _resetAttemptGuard();
  const res = await ensureCardLogin({ task: null, page: {}, site, credentials: creds, ...env });
  assert.equal(res.status, STATUS.ERROR);
  assert.equal(res.reason, 'attempts_store_unreadable');
  assert.equal(loginCalls, 0);
}));

await test('unwritable store path (parent is file) -> no attempt (fail-closed)', () => withTemp(async ({ dir }) => {
  const blocker = path.join(dir, 'blocker');
  await writeFile(blocker, 'x', 'utf8');
  const attemptsPath = path.join(blocker, 'attempts.json'); // 부모가 파일 → 읽기/쓰기 불가
  const env = { attemptsPath, assistDir: path.join(dir, 'assist'), statusDir: path.join(dir, 'status') };
  let loginCalls = 0;
  const site = fakeSite({ login: async () => { loginCalls += 1; return { outcome: 'success' }; } });
  _resetAttemptGuard();
  const res = await ensureCardLogin({ task: null, page: {}, site, credentials: creds, ...env });
  assert.equal(res.status, STATUS.ERROR);
  // 플랫폼에 따라 읽기 또는 쓰기 단계에서 실패한다. 어느 쪽이든 시도하지 않고 멈춰야 한다.
  assert.ok(['attempts_store_unreadable', 'attempt_record_failed'].includes(res.reason), `unexpected reason ${res.reason}`);
  assert.equal(loginCalls, 0);
}));

await test('record write failure -> no attempt (fail-closed)', () => withTemp(async ({ dir, attemptsPath }) => {
  // 읽기는 성공하도록 유효한 저장소를 만든 뒤 읽기 전용으로 바꿔 교체(쓰기)를 실패시킨다.
  await recordAttempt('kb', { outcome: 'verified', reason: 'ok' }, { path: attemptsPath });
  await chmod(attemptsPath, 0o444);
  const env = { attemptsPath, assistDir: path.join(dir, 'assist'), statusDir: path.join(dir, 'status') };
  let loginCalls = 0;
  const site = fakeSite({ login: async () => { loginCalls += 1; return { outcome: 'success' }; } });
  _resetAttemptGuard();
  let res;
  try {
    res = await ensureCardLogin({ task: null, page: {}, site, credentials: creds, ...env });
  } finally {
    await chmod(attemptsPath, 0o666); // 임시 폴더 정리용 권한 복원
  }
  assert.equal(res.status, STATUS.ERROR);
  assert.equal(res.reason, 'attempt_record_failed');
  assert.equal(loginCalls, 0);
}));

await test('atomic write leaves valid JSON and no temp file', () => withTemp(async ({ dir, attemptsPath }) => {
  await beginAttempt('kb', { path: attemptsPath });
  await recordAttempt('kb', { outcome: 'verified', reason: 'ok' }, { path: attemptsPath });
  const data = JSON.parse(await readFile(attemptsPath, 'utf8'));
  assert.equal(data.schema, ATTEMPTS_SCHEMA);
  assert.equal(data.issuers.kb.lastOutcome, 'verified');
  const files = await readdir(dir);
  assert.ok(!files.some((f) => f.includes('.tmp-')), 'temp file left behind');
}));

console.log(`card_attempt_guard: ${failures === 0 ? 'clean' : failures + ' failures'}`);
process.exit(failures === 0 ? 0 : 1);
