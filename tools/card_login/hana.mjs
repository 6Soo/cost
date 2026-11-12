// 하나카드 기업/법인 로그인 모듈 — 틀(NOT_VERIFIED).
// 2026-11-13 기준 기업 로그인 화면 URL·입력 방식·보안 프로그램 요구를 라이브로 확인하지 못했다.
// (하나카드 홈은 자동화 환경에서 본문 미렌더 이력: card-login-research-20261111.md. 공개 웹 검색은 속도 제한.)
// URL·선택자·성공 판정은 라이브 조사로 확정한 뒤 채운다. 추측으로 입력을 시도하지 않는다.
import { classifyLoginText, hasPasswordAttemptWarning } from './detect.mjs';

export const issuer = 'hana';
export const loginUrl = null; // NOT_VERIFIED: 기업 로그인 진입점 미확정
export const usageUrls = { domestic: null, overseas: null };
export const selectors = {
  idInput: null, passwordInput: null, loginButton: null, logoutLink: 'text=로그아웃',
};

async function pageText(page) {
  try { return await page.evaluate(() => (document.body.innerText || '').slice(0, 4000)); }
  catch { return ''; }
}

export async function isLoggedIn(page) { return false; } // NOT_VERIFIED

export async function login(page, creds) {
  if (!loginUrl) return { outcome: 'failed', detail: 'login_url_unconfirmed' };
  // 아래는 URL·선택자 확정 후 활성화하는 입력 단계의 틀이다. 현재는 실행되지 않는다.
  await page.goto(loginUrl);
  await page.waitForLoadState();
  const editable = await page.evaluate(({ idSel, pwSel }) => {
    const id = idSel ? document.querySelector(idSel) : null;
    const pw = pwSel ? document.querySelector(pwSel) : null;
    return { idPresent: Boolean(id), pwPresent: Boolean(pw), idReadonly: id ? id.readOnly === true : null, pwReadonly: pw ? pw.readOnly === true : null };
  }, { idSel: selectors.idInput, pwSel: selectors.passwordInput });
  if (!editable.idPresent || !editable.pwPresent) return { outcome: 'failed', detail: 'login_inputs_not_found' };
  if (editable.idReadonly || editable.pwReadonly) return { outcome: 'failed', detail: 'security_input_readonly' };
  await page.fill(selectors.idInput, creds.id);
  await page.fill(selectors.passwordInput, creds.password);
  await page.click(selectors.loginButton);
  await page.waitForTimeout(2500);
  const text = await pageText(page);
  if (hasPasswordAttemptWarning(text)) return { outcome: 'failed', detail: 'password_attempt_warning_stop' };
  const cls = classifyLoginText(text);
  if (cls === 'additional_auth') return { outcome: 'additional_auth', detail: 'additional_auth_signal' };
  if (cls === 'failed') return { outcome: 'failed', detail: 'login_error_signal' };
  return { outcome: 'failed', detail: 'login_result_unconfirmed' };
}

export async function confirmUsageScreen(page) { return false; } // NOT_VERIFIED
export async function logout(page) { /* NOT_VERIFIED */ }

export default { issuer, loginUrl, usageUrls, selectors, isLoggedIn, login, confirmUsageScreen, logout };
