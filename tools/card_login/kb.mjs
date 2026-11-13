// 국민 기업카드 로그인 모듈.
// 확인됨(2026-11-13 DOM 관찰): 아이디/공동인증서 2탭. 아이디 로그인은 doIdLoginA(),
//   인증서 로그인은 Wizvera Delfino G3(doCertLoginA). 아이디·비밀번호 입력란은 readonly이며
//   AhnLab ASTx2 키보드 보안(secuKeyASTx2)·가상키패드(secukeyPad)가 로드된다.
// 미검증: 자동 입력 가능 여부(readonly 해제/키보드 전환), 로그인 성공/실패 화면 선택자, 조회 화면 선택자.
//   → 라이브 검증 전까지 성공으로 단정하지 않는다. 보안 입력은 우회하지 않고 막힘으로 보고한다.
import { classifyLoginText, hasPasswordAttemptWarning } from './detect.mjs';

export const issuer = 'kb';
export const loginUrl = 'https://biz.kbcard.com/CXERCZZC0001.cms';
export const usageUrls = {
  domestic: 'https://biz.kbcard.com/CXERCMLSD0002.cms',
  overseas: 'https://biz.kbcard.com/CXERCMLS0008.cms',
};
export const selectors = {
  idTab: 'text=아이디',
  idInput: 'input[placeholder="아이디"]',
  passwordInput: '#loginPwdBiz',
  idLoginButton: 'button[onclick="javascript:doIdLoginA();"]',
  logoutLink: 'text=로그아웃',
};

async function pageText(page) {
  try { return await page.evaluate(() => (document.body.innerText || '').slice(0, 4000)); }
  catch { return ''; }
}

// 이미 로그인된 세션인지. 검증된 선택자가 없어 보수적으로 로그아웃 링크 존재로 판단(NOT_VERIFIED).
export async function isLoggedIn(page) {
  try {
    const url = await page.url();
    if (!/biz\.kbcard\.com/.test(url)) return false;
    const found = await page.evaluate((sel) => {
      const links = [...document.querySelectorAll('a,button')];
      return links.some((el) => /로그아웃/.test(el.textContent || ''));
    }, selectors.logoutLink);
    return Boolean(found);
  } catch { return false; }
}

// 1회 로그인 시도. 성공/실패/추가인증/막힘을 반환. 재시도 없음.
export async function login(page, creds) {
  await page.goto(loginUrl);
  await page.waitForLoadState();
  try { await page.click(selectors.idTab); } catch { /* 이미 아이디 탭일 수 있음 */ }
  await page.waitForTimeout(500);

  // 보안 입력(readonly) 확인. 우회하지 않는다.
  const editable = await page.evaluate(({ idSel, pwSel }) => {
    const id = document.querySelector(idSel);
    const pw = document.querySelector(pwSel);
    return {
      idPresent: Boolean(id), pwPresent: Boolean(pw),
      idReadonly: id ? id.readOnly === true : null,
      pwReadonly: pw ? pw.readOnly === true : null,
    };
  }, { idSel: selectors.idInput, pwSel: selectors.passwordInput });

  if (!editable.idPresent || !editable.pwPresent) {
    return { outcome: 'failed', detail: 'login_inputs_not_found' };
  }
  if (editable.idReadonly || editable.pwReadonly) {
    // 가상키패드/키보드 보안으로 직접 입력 불가. 보안 프로그램을 끄거나 입력 속성을 변조하지 않고
    // 에이전트 보조 단계(공식 가상키패드 클릭)로 넘긴다. 비밀은 스크립트 내부에서만 읽는다.
    return {
      outcome: 'agent_assist', step: 'keypad_password', detail: 'security_input_readonly',
      agentAction: '가상키패드 좌표를 관찰해 assistKeypadEntry 로 비밀번호를 입력한다(비밀 출력 금지).',
    };
  }

  await page.fill(selectors.idInput, creds.id);
  await page.fill(selectors.passwordInput, creds.password);
  await page.click(selectors.idLoginButton);
  await page.waitForTimeout(2500);

  const text = await pageText(page);
  if (hasPasswordAttemptWarning(text)) {
    return { outcome: 'failed', detail: 'password_attempt_warning_stop' };
  }
  const cls = classifyLoginText(text);
  if (cls === 'additional_auth') return { outcome: 'additional_auth', detail: 'additional_auth_signal' };
  if (cls === 'failed') return { outcome: 'failed', detail: 'login_error_signal' };

  // 성공 판정: 로그인 화면을 벗어났는지 확인(NOT_VERIFIED — 실제 성공 선택자 라이브 확정 필요).
  const url = await page.url();
  const leftLogin = !/CXERCZZC0001/.test(url);
  if (leftLogin) return { outcome: 'success', detail: 'left_login_page' };
  return { outcome: 'failed', detail: 'login_result_unconfirmed' };
}

// 이용내역 조회 화면 진입 확인(결제·한도·설정 화면 금지). NOT_VERIFIED.
export async function confirmUsageScreen(page) {
  await page.goto(usageUrls.domestic);
  await page.waitForLoadState();
  const url = await page.url();
  if (/CXERCZZC0001/.test(url)) return false; // 로그인으로 되돌아감
  const text = await pageText(page);
  return /매입|이용내역|조회/.test(text);
}

export async function logout(page) {
  try { await page.click(selectors.logoutLink); await page.waitForTimeout(1000); } catch { /* noop */ }
}

export default { issuer, loginUrl, usageUrls, selectors, isLoggedIn, login, confirmUsageScreen, logout };
