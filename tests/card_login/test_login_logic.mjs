// 합성 전용 카드 로그인 로직 검사. 실제 사이트·로그인 세션·고객 자료·운영 DB 접근 없음.
// 모든 시도는 임시 폴더의 attempts.json/assist/status 로 격리한다(운영 상태 파일 접근 없음).
// 실행: node tests/card_login/test_login_logic.mjs  → PASS/FAIL 줄 + 요약, 실패 시 nonzero exit.
import assert from 'node:assert';
import { mkdtemp, readFile, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { redact, safeStringify } from '../../tools/card_login/credentials.mjs';
import { classifyLoginText, hasPasswordAttemptWarning } from '../../tools/card_login/detect.mjs';
import { ensureCardLogin, STATUS, _resetAttemptGuard } from '../../tools/card_login/common.mjs';

let failures = 0;
async function test(name, fn) {
  try { await fn(); console.log(`PASS ${name}`); }
  catch (err) { failures += 1; console.log(`FAIL ${name}: ${err && err.message ? err.message : err}`); }
}

const SECRET_ID = 'synthetic-id-123';
const SECRET_PW = 'synthetic-pw-456';
const SECRET_CERT = 'synthetic-cert-789';
const creds = { status: 'ok', id: SECRET_ID, password: SECRET_PW, certPassword: SECRET_CERT };

function fakeSite(overrides = {}) {
  return {
    issuer: 'kb',
    isLoggedIn: async () => false,
    login: async () => ({ outcome: 'success', detail: 'ok' }),
    confirmUsageScreen: async () => true,
    logout: async () => {},
    ...overrides,
  };
}
function fakeTask() {
  const calls = { handOff: 0 };
  return { calls, handOff: async () => { calls.handOff += 1; } };
}

// 임시 격리 환경: 운영 attempts.json/assist 폴더를 건드리지 않는다.
async function withTemp(fn) {
  const dir = await mkdtemp(path.join(tmpdir(), 'card-login-test-'));
  const env = {
    attemptsPath: path.join(dir, 'attempts.json'),
    assistDir: path.join(dir, 'assist'),
    statusDir: path.join(dir, 'status'),
  };
  try { await fn(env); } finally { await rm(dir, { recursive: true, force: true }); }
}

await test('redact masks all secret values', () => {
  const text = `id=${SECRET_ID} pw=${SECRET_PW} cert=${SECRET_CERT}`;
  const out = redact(text, [SECRET_ID, SECRET_PW, SECRET_CERT]);
  assert.ok(!out.includes(SECRET_ID) && !out.includes(SECRET_PW) && !out.includes(SECRET_CERT));
  assert.ok(out.includes('[REDACTED]'));
});

await test('safeStringify masks secrets in JSON', () => {
  const out = safeStringify({ note: `password is ${SECRET_PW}`, id: SECRET_ID }, [SECRET_ID, SECRET_PW]);
  assert.ok(!out.includes(SECRET_PW) && !out.includes(SECRET_ID));
});

await test('classifyLoginText detects additional auth', () => {
  assert.equal(classifyLoginText('휴대폰 인증번호를 입력하세요'), 'additional_auth');
  assert.equal(classifyLoginText('OTP 입력'), 'additional_auth');
  assert.equal(classifyLoginText('간편인증 승인 요청'), 'additional_auth');
});

await test('classifyLoginText detects failure', () => {
  assert.equal(classifyLoginText('비밀번호가 일치하지 않습니다'), 'failed');
  assert.equal(classifyLoginText('로그인 오류'), 'failed');
});

await test('classifyLoginText unknown for neutral text', () => {
  assert.equal(classifyLoginText('이용내역 조회 화면'), 'unknown');
});

await test('hasPasswordAttemptWarning detects lock warning', () => {
  assert.equal(hasPasswordAttemptWarning('비밀번호 오류 횟수 초과로 잠금'), true);
  assert.equal(hasPasswordAttemptWarning('3회 오류'), true);
  assert.equal(hasPasswordAttemptWarning('정상 화면'), false);
});

await test('already logged in -> logged_in, no login attempt', () => withTemp(async (env) => {
  _resetAttemptGuard();
  let loginCalls = 0;
  const site = fakeSite({ isLoggedIn: async () => true, login: async () => { loginCalls += 1; return { outcome: 'success' }; } });
  const res = await ensureCardLogin({ task: fakeTask(), page: {}, site, credentials: creds, ...env });
  assert.equal(res.status, STATUS.LOGGED_IN);
  assert.equal(loginCalls, 0);
}));

await test('not registered -> registration_required, no attempt', () => withTemp(async (env) => {
  _resetAttemptGuard();
  let loginCalls = 0;
  const site = fakeSite({ login: async () => { loginCalls += 1; return { outcome: 'success' }; } });
  const res = await ensureCardLogin({
    task: fakeTask(), page: {}, site,
    readCredentialsImpl: async () => ({ status: 'not_registered' }), ...env,
  });
  assert.equal(res.status, STATUS.REGISTRATION_REQUIRED);
  assert.equal(loginCalls, 0);
}));

await test('success -> verified, usage confirmed and logout called', () => withTemp(async (env) => {
  _resetAttemptGuard();
  let usage = 0, logout = 0;
  const site = fakeSite({ confirmUsageScreen: async () => { usage += 1; return true; }, logout: async () => { logout += 1; } });
  const res = await ensureCardLogin({ task: fakeTask(), page: {}, site, credentials: creds, ...env });
  assert.equal(res.status, STATUS.VERIFIED);
  assert.equal(res.usageConfirmed, true);
  assert.equal(usage, 1);
  assert.equal(logout, 1);
}));

await test('additional auth -> handOff and stop', () => withTemp(async (env) => {
  _resetAttemptGuard();
  const task = fakeTask();
  const site = fakeSite({ login: async () => ({ outcome: 'additional_auth', detail: 'otp' }) });
  const res = await ensureCardLogin({ task, page: {}, site, credentials: creds, ...env });
  assert.equal(res.status, STATUS.ADDITIONAL_AUTH_REQUIRED);
  assert.equal(task.calls.handOff, 1);
}));

await test('failure -> login_failed, persistent guard blocks retry until reset', () => withTemp(async (env) => {
  _resetAttemptGuard();
  let loginCalls = 0;
  const site = fakeSite({ login: async () => { loginCalls += 1; return { outcome: 'failed', detail: 'bad_pw' }; } });
  const first = await ensureCardLogin({ task: fakeTask(), page: {}, site, credentials: creds, ...env });
  assert.equal(first.status, STATUS.LOGIN_FAILED);
  assert.equal(loginCalls, 1);
  // 재실행(프로세스 가드 초기화 후)에도 영속 기록 때문에 시도하지 않는다.
  _resetAttemptGuard();
  const second = await ensureCardLogin({ task: fakeTask(), page: {}, site, credentials: creds, ...env });
  assert.equal(second.status, STATUS.LOGIN_FAILED);
  assert.equal(second.reason, 'attempt_blocked_until_reset');
  assert.equal(loginCalls, 1); // 재시도 없음
}));

await test('status file contains no secret values', () => withTemp(async (env) => {
  _resetAttemptGuard();
  const site = fakeSite({ login: async () => ({ outcome: 'failed', detail: `err ${SECRET_PW}` }) });
  const res = await ensureCardLogin({ task: fakeTask(), page: {}, site, credentials: creds, ...env });
  const body = await readFile(res.statusFile, 'utf8');
  assert.ok(!body.includes(SECRET_ID), 'id leaked');
  assert.ok(!body.includes(SECRET_PW), 'password leaked');
  assert.ok(!body.includes(SECRET_CERT), 'cert leaked');
}));

console.log(`card_login_logic: ${failures === 0 ? 'clean' : failures + ' failures'}`);
process.exit(failures === 0 ? 0 : 1);
