// 사이트별 마지막 로그인 시도 결과의 영속 가드.
// 실패·잠금 경고·추가 인증 대기로 끝난 사이트는 사용자가 reset_attempt.ps1 로 해제하기 전까지
// 재실행해도 시도하지 않는다(계정 잠금 방지). 성공 기록은 다음 시도를 막지 않는다.
// 상태 파일에는 비밀 값을 쓰지 않는다(결과 코드·시각·사유 코드만).
import { mkdir, readFile, writeFile, rm } from 'node:fs/promises';
import path from 'node:path';
import { redact } from './credentials.mjs';

export const DEFAULT_ATTEMPTS_PATH = 'D:/WebLedgerHost/data/card-login/attempts.json';
export const ATTEMPTS_SCHEMA = 'cost.card-login-attempts.v1';
// 이 결과로 끝나면 사용자 해제 전까지 재시도 금지(실패·잠금 경고·추가 인증/에이전트 보조 대기).
export const BLOCKING_OUTCOMES = new Set(['login_failed', 'additional_auth_required', 'agent_assist_required', 'error']);

async function readStore(file) {
  try {
    const raw = await readFile(file, 'utf8');
    const data = JSON.parse(raw);
    if (data && data.schema === ATTEMPTS_SCHEMA && data.issuers && typeof data.issuers === 'object') {
      return data;
    }
  } catch (err) {
    if (err && err.code !== 'ENOENT') throw err;
  }
  return { schema: ATTEMPTS_SCHEMA, issuers: {} };
}

async function writeStore(file, store) {
  await mkdir(path.dirname(file), { recursive: true });
  await writeFile(file, JSON.stringify(store, null, 1), 'utf8');
}

export async function readAttempt(issuer, { path: file = DEFAULT_ATTEMPTS_PATH } = {}) {
  const store = await readStore(file);
  return store.issuers[issuer] || null;
}

export async function isBlocked(issuer, opts = {}) {
  const record = await readAttempt(issuer, opts);
  return Boolean(record && BLOCKING_OUTCOMES.has(record.lastOutcome));
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
