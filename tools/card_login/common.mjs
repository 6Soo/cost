// 카드 로그인 공통 오케스트레이션.
// 수집 스크립트가 붙는 인터페이스: ensureCardLogin({ task, page, site, ... })
//   흐름: 로그인 확인 → 안 돼 있으면 자격 증명 읽어 1회 시도 → 실패/추가 인증/에이전트 보조면 멈춤.
// 보호: 사이트당 로그인 시도 1회(재시도 없음, 계정 잠금 방지).
//   영속 가드(attempts.json, fail-closed): 시도 직전 'attempting'을 먼저 기록하고 성공하면 'verified'로 바꾼다.
//   실패·잠금 경고·추가 인증/에이전트 보조 대기, 비정상 종료로 남은 'attempting'은 사용자가
//   reset_attempt.ps1 로 해제하기 전까지 재실행해도 시도하지 않는다. 성공은 막지 않는다.
//   저장소가 깨졌거나 읽기·쓰기에 실패하면 시도하지 않고 멈춘다. 비밀 값은 로그·상태·시도 기록에 쓰지 않는다.
import { mkdir, writeFile } from 'node:fs/promises';
import path from 'node:path';
import { readCredentials, safeStringify } from './credentials.mjs';
import { isBlocked, beginAttempt, recordAttempt, DEFAULT_ATTEMPTS_PATH } from './attempts.mjs';
import { captureAssistScreenshot, writeAgentHandoff, DEFAULT_ASSIST_DIR } from './handoff.mjs';

export const STATUS = Object.freeze({
  LOGGED_IN: 'logged_in',                       // 이미 로그인됨(시도 없음)
  VERIFIED: 'verified',                         // 로그인 성공 + 조회 화면 진입 확인 + 로그아웃
  REGISTRATION_REQUIRED: 'registration_required', // 자격 증명 미등록 → 사용자 등록 필요
  ADDITIONAL_AUTH_REQUIRED: 'additional_auth_required', // 휴대폰·OTP·간편인증 → handOff
  AGENT_ASSIST_REQUIRED: 'agent_assist_required', // 스크립트가 막힘 → 에이전트 보조 단계로 넘김
  LOGIN_FAILED: 'login_failed',                 // 1회 시도 실패(재시도 없음)
  ERROR: 'error',
});

// 프로세스 안에서 사이트당 시도 1회 가드(영속 가드와 별개의 이중 보호).
const attempted = new Set();
export function _resetAttemptGuard() { attempted.clear(); }

export async function writeStatus(statusDir, record, secrets) {
  if (!statusDir) return null;
  await mkdir(statusDir, { recursive: true });
  const file = path.join(statusDir, `${record.issuer}-login-status.json`);
  await writeFile(file, safeStringify(record, secrets), 'utf8');
  return file;
}

// site: { issuer, loginUrl, isLoggedIn(page), login(page, creds), confirmUsageScreen(page), logout(page) }
// login(page, creds) 반환: { outcome: 'success'|'additional_auth'|'agent_assist'|'failed', detail, step?, agentAction? }
export async function ensureCardLogin({
  task,
  page,
  site,
  credentials = null,
  statusDir = null,
  logoutAfterVerify = true,
  readCredentialsImpl = readCredentials,
  attemptsPath = DEFAULT_ATTEMPTS_PATH,
  assistDir = DEFAULT_ASSIST_DIR,
} = {}) {
  const issuer = site.issuer;
  const secrets = [];
  const stamp = () => new Date().toISOString();
  const finish = async (status, reason, extra = {}) => {
    const record = { issuer, status, reason: reason || null, observedAt: stamp(), ...extra };
    const file = await writeStatus(statusDir, record, secrets);
    return { ...record, statusFile: file };
  };
  // 시도 기록은 실패해도 흐름을 막지 않는다(가드는 best-effort). 사유는 마스킹해 영속한다.
  const record = (outcome, reason) =>
    recordAttempt(issuer, { outcome, reason, secrets }, { path: attemptsPath }).catch(() => {});

  // 1) 이미 로그인되어 있으면 시도하지 않는다.
  let already = false;
  try { already = await site.isLoggedIn(page); } catch { already = false; }
  if (already) return finish(STATUS.LOGGED_IN, 'session_alive');

  // 2) 자격 증명 확인. 미등록이면 로그인 시도 없이 멈춘다.
  let creds = credentials;
  if (!creds) {
    creds = await readCredentialsImpl(issuer);
  }
  if (!creds || creds.status !== 'ok') {
    return finish(STATUS.REGISTRATION_REQUIRED, 'credentials_not_registered');
  }
  secrets.push(creds.id, creds.password, creds.certPassword);

  // 3) 영속 가드(fail-closed): 저장소가 깨졌거나 읽을 수 없으면 시도하지 않고 멈춘다.
  //    이전 실패/대기/비정상 종료('attempting') 기록이 있으면 사용자 해제 전까지 시도하지 않는다.
  let blocked = false;
  try { blocked = await isBlocked(issuer, { path: attemptsPath }); }
  catch { return finish(STATUS.ERROR, 'attempts_store_unreadable'); }
  if (blocked) return finish(STATUS.LOGIN_FAILED, 'attempt_blocked_until_reset');

  // 4) 프로세스 내 1회 가드.
  if (attempted.has(issuer)) {
    return finish(STATUS.LOGIN_FAILED, 'attempt_already_used_this_run');
  }

  // 5) 시도 전 기록(fail-closed): 로그인 입력 직전에 'attempting'을 먼저 남긴다.
  //    기록이 실패하면 시도하지 않는다. 비정상 종료로 'attempting'이 남으면 재실행 시 차단된다.
  try { await beginAttempt(issuer, { path: attemptsPath }); }
  catch { return finish(STATUS.ERROR, 'attempt_record_failed'); }
  attempted.add(issuer);

  // 6) 1회 로그인 시도.
  let result;
  try {
    result = await site.login(page, creds);
  } catch (err) {
    await record('login_failed', 'login_threw');
    return finish(STATUS.LOGIN_FAILED, 'login_threw', { errorName: err && err.name ? err.name : 'Error' });
  }

  // 에이전트 보조: 스크립트가 막힌 단계(가상 키패드·인증서 선택·변화하는 팝업 등)를 에이전트에게 넘긴다.
  if (result.outcome === 'agent_assist') {
    const step = result.step || 'assist';
    let screenshot = null;
    try { screenshot = await captureAssistScreenshot(page, { issuer, step, dir: assistDir }); } catch { screenshot = null; }
    let handoffFile = null;
    try {
      const handoff = await writeAgentHandoff({
        issuer, step, reason: result.detail || null, screenshot,
        agentAction: result.agentAction || null, statusDir,
      });
      handoffFile = handoff ? handoff.file : null;
    } catch { /* 상태 파일 실패는 흐름을 막지 않는다 */ }
    if (task && typeof task.handOff === 'function') {
      try { await task.handOff(); } catch { /* handOff 실패는 상태만 남긴다 */ }
    }
    await record('agent_assist_required', step);
    return finish(STATUS.AGENT_ASSIST_REQUIRED, result.detail || 'agent_assist', { step, screenshot, handoffFile });
  }

  if (result.outcome === 'additional_auth') {
    if (task && typeof task.handOff === 'function') {
      try { await task.handOff(); } catch { /* handOff 실패는 상태만 남긴다 */ }
    }
    await record('additional_auth_required', result.detail || null);
    return finish(STATUS.ADDITIONAL_AUTH_REQUIRED, result.detail || 'additional_auth');
  }
  if (result.outcome !== 'success') {
    // 실패: 재시도하지 않는다. 비밀번호 오류 횟수 경고가 있으면 detail 에 남긴다.
    await record('login_failed', result.detail || null);
    return finish(STATUS.LOGIN_FAILED, result.detail || 'login_failed');
  }

  // 7) 성공: 이용내역 조회 화면 진입까지만 확인하고 로그아웃. 성공 기록('verified')은 다음 시도를 막지 않는다.
  let usageConfirmed = false;
  try { usageConfirmed = await site.confirmUsageScreen(page); } catch { usageConfirmed = false; }
  if (logoutAfterVerify && typeof site.logout === 'function') {
    try { await site.logout(page); } catch { /* 로그아웃 실패는 상태에 표시 */ }
  }
  await record('verified', usageConfirmed ? 'usage_screen_confirmed' : 'usage_screen_unconfirmed');
  return finish(STATUS.VERIFIED, usageConfirmed ? 'usage_screen_confirmed' : 'usage_screen_unconfirmed', { usageConfirmed });
}
