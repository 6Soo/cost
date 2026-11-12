// 사이트별 로그인 시도 가드(영속, fail-closed).
// 시도 직전에 'attempting'을 먼저 기록하고, 성공하면 'verified'로 바꾼다.
// 실패·잠금 경고·추가 인증/에이전트 보조 대기, 그리고 비정상 종료로 남은 'attempting'은
// 사용자가 reset_attempt.ps1 로 해제하기 전까지 재실행해도 시도하지 않는다(계정 잠금 방지).
// 성공 기록은 다음 시도를 막지 않는다.
// fail-closed: 저장소가 깨졌거나 읽기·쓰기에 실패하면 시도하지 않고 멈춘다. 쓰기는 원자적(임시 파일 후 교체).
// 상태 파일에는 비밀 값을 쓰지 않는다(결과 코드·시각·사유 코드만).
import { mkdir, readFile, writeFile, rename, rm } from 'node:fs/promises';
import path from 'node:path';
import { redact } from './credentials.mjs';

export const DEFAULT_ATTEMPTS_PATH = 'D:/WebLedgerHost/data/card-login/attempts.json';
export const ATTEMPTS_SCHEMA = 'cost.card-login-attempts.v1';
// 이 결과로 끝나면 사용자 해제 전까지 재시도 금지.
// 'attempting'은 시도 직전 기록으로, 비정상 종료로 남으면 실패와 같이 취급해 차단한다.
export const BLOCKING_OUTCOMES = new Set(['attempting', 'login_failed', 'additional_auth_required', 'agent_assist_required', 'error']);

// 저장소 읽기(fail-closed). 파일이 없으면(ENOENT) 빈 저장소로 시작할 수 있지만,
// 파일이 있는데 깨졌거나 읽을 수 없으면 예외를 던져 호출자가 시도하지 않고 멈추게 한다.
async function readStore(file) {
  let raw;
  try {
    raw = await readFile(file, 'utf8');
  } catch (err) {
    if (err && err.code === 'ENOENT') return { schema: ATTEMPTS_SCHEMA, issuers: {} };
    throw err;
  }
  let data;
  try {
    data = JSON.parse(raw);
  } catch {
    throw new Error('ATTEMPTS_STORE_CORRUPT');
  }
  if (!data || data.schema !== ATTEMPTS_SCHEMA || !data.issuers || typeof data.issuers !== 'object') {
    throw new Error('ATTEMPTS_STORE_CORRUPT');
  }
  return data;
}

// 원자적 쓰기: 임시 파일에 쓴 뒤 교체한다. 쓰기가 실패하면 예외를 던진다(fail-closed).
async function writeStore(file, store) {
  await mkdir(path.dirname(file), { recursive: true });
  const tmp = `${file}.tmp-${process.pid}-${Date.now()}`;
  try {
    await writeFile(tmp, JSON.stringify(store, null, 1), 'utf8');
    await rename(tmp, file);
  } catch (err) {
    await rm(tmp, { force: true }).catch(() => {});
    throw err;
  }
}

export async function readAttempt(issuer, { path: file = DEFAULT_ATTEMPTS_PATH } = {}) {
  const store = await readStore(file);
  return store.issuers[issuer] || null;
}

export async function isBlocked(issuer, opts = {}) {
  const record = await readAttempt(issuer, opts);
  return Boolean(record && BLOCKING_OUTCOMES.has(record.lastOutcome));
}

// 시도 직전 기록(fail-closed): 로그인 입력을 시작하기 전에 'attempting'을 먼저 남긴다.
// 이 기록이 실패하면 호출자는 시도하지 않는다. 비정상 종료로 'attempting'이 남으면 재시도 차단.
export async function beginAttempt(issuer, { path: file = DEFAULT_ATTEMPTS_PATH } = {}) {
  const store = await readStore(file);
  store.issuers[issuer] = {
    lastOutcome: 'attempting',
    reason: null,
    at: new Date().toISOString(),
    blocked: true,
  };
  await writeStore(file, store);
  return store.issuers[issuer];
}

export async function recordAttempt(issuer, { outcome, reason = null, secrets = [] }, { path: file = DEFAULT_ATTEMPTS_PATH } = {}) {
  const store = await readStore(file);
  // 사유에 비밀 값이 섞여도 상태 파일에 남지 않도록 마스킹한다(결과 코드·시각만 영속).
  const safeReason = (typeof reason === 'string' && secrets.length > 0) ? redact(reason, secrets) : reason;
  store.issuers[issuer] = {
    lastOutcome: outcome,
    reason: safeReason,
    at: new Date().toISOString(),
    blocked: BLOCKING_OUTCOMES.has(outcome),
  };
  await writeStore(file, store);
  return store.issuers[issuer];
}

// 사용자 명시 해제: 해당 사이트 기록을 지워 다음 시도를 허용한다.
export async function resetAttempt(issuer, { path: file = DEFAULT_ATTEMPTS_PATH } = {}) {
  const store = await readStore(file);
  const existed = Object.prototype.hasOwnProperty.call(store.issuers, issuer);
  delete store.issuers[issuer];
  await writeStore(file, store);
  return existed;
}

export async function _clearStoreForTest(file) {
  try { await rm(file, { force: true }); } catch { /* noop */ }
}
