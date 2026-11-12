// IBK 기업은행 기업카드 로그인 모듈 — 틀(NOT_VERIFIED, 공개 정보 기반).
// 공개 정보(2026-11-13 웹 검색): 기업인터넷뱅킹 kiup.ibk.co.kr 로그인에 공동인증서(WizIN-Delfino G3)
//   + 아이디/비밀번호 병행. OTP·씨크리트카드 추가 인증 가능. ONE 비밀번호 3회 오류 시 로그인 제한.
//   카드 이용내역은 인증센터/이용내역 메뉴. 실제 화면·선택자·성공 판정은 라이브로 확인하지 못했다.
// URL 은 공개 검색 출처이며 접속·입력 방식은 라이브 검증으로 확정한다. 추측 입력을 하지 않는다.
import { classifyLoginText, hasPasswordAttemptWarning } from './detect.mjs';

export const issuer = 'ibk';
export const loginUrl = 'https://kiup.ibk.co.kr/uib/jsp/online/main/main_login.jsp'; // NOT_VERIFIED(공개 출처)
export const usageUrls = { domestic: null, overseas: null }; // 이용내역 메뉴 경로 미확정
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
