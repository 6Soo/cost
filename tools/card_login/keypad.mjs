// 가상 키패드 입력 헬퍼(에이전트 보조 단계).
// 사이트가 제공하는 공식 가상 키패드를 클릭해 입력한다 — 정상 사용자 입력 경로이며 보안 프로그램을
// 끄거나 입력 속성을 변조하지 않는다. 키보드 보안이 합성 키 입력을 막을 때 이 경로를 쓴다.
// 비밀 값은 함수 내부에서만 다루며 클릭 순서(=비밀)를 출력·로그·반환값에 남기지 않는다.
// 반환값은 {entered} 뿐이며 글자 수는 남기지 않는다(길이 누출 방지). 오류에도 입력 문자를 넣지 않는다.
import { readCredentials } from './credentials.mjs';

// keyMap: 문자 → {x, y} (키패드 배치, 비밀 아님). secret 은 내부에서만 사용.
export async function enterByCoordinates(page, secret, keyMap, { delayMs = 120 } = {}) {
  const chars = [...String(secret)];
  for (const ch of chars) {
    const pos = keyMap[ch];
    if (!pos || typeof pos.x !== 'number' || typeof pos.y !== 'number') {
      // 어떤 문자가 누락됐는지 노출하지 않는다(비밀 유출 방지).
      throw new Error('KEYPAD_KEY_MISSING');
    }
    await page.mouse.click(pos.x, pos.y, { label: 'keypad key' });
    if (delayMs) await page.waitForTimeout(delayMs);
  }
  return { entered: true };
}

// HTML 키패드: 문자별 선택자를 해석해 클릭. resolveSelector 는 배치 정보만 다루고 비밀을 출력하지 않는다.
export async function enterBySelectors(page, secret, resolveSelector, { delayMs = 120 } = {}) {
  const chars = [...String(secret)];
  for (const ch of chars) {
    const sel = resolveSelector(ch);
    if (!sel) throw new Error('KEYPAD_KEY_MISSING');
    await page.click(sel, { label: 'keypad key' });
    if (delayMs) await page.waitForTimeout(delayMs);
  }
  return { entered: true };
}

// DOM 키패드 관찰: 한 글자 버튼의 중심 좌표로 문자→좌표 배치를 만든다(비밀 아님).
// 캔버스/이미지 키패드는 에이전트가 스크린샷에서 좌표를 읽어 keyMap 으로 넘긴다.
export async function observeDomKeypad(page, containerSelector) {
  return await page.evaluate((sel) => {
    const root = document.querySelector(sel);
    if (!root) return {};
    const map = {};
    const nodes = root.querySelectorAll('button, [role="button"], a, span, div, td');
    for (const el of nodes) {
      const t = (el.textContent || '').trim();
      if (t.length !== 1) continue;
      const r = el.getBoundingClientRect();
      if (r.width > 0 && r.height > 0) {
        map[t] = { x: Math.round(r.x + r.width / 2), y: Math.round(r.y + r.height / 2) };
      }
    }
    return map;
  }, containerSelector);
}

// 에이전트 보조 비밀번호/아이디 입력: DPAPI 저장소에서 비밀을 읽어 키패드 클릭 순서를 만들고 실행.
// 에이전트 대화에는 {status}("입력 완료")만 남는다. 글자 수·비밀 문자열은 반환·출력하지 않는다.
export async function assistKeypadEntry(page, {
  issuer,
  field = 'password',
  keyMap = null,
  containerSelector = null,
  storeRoot = null,
  readCredentialsImpl = readCredentials,
} = {}) {
  const cred = await readCredentialsImpl(issuer, { storeRoot });
  if (!cred || cred.status !== 'ok') return { status: 'registration_required' };
  const secret = field === 'id' ? cred.id
    : field === 'certPassword' ? cred.certPassword
      : cred.password;
  if (secret == null || secret === '') return { status: 'field_missing' };
  let map = keyMap;
  if (!map && containerSelector) map = await observeDomKeypad(page, containerSelector);
  if (!map || Object.keys(map).length === 0) return { status: 'keypad_unobserved' };
  await enterByCoordinates(page, secret, map);
  return { status: 'entered' };
}
