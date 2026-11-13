// 카드 로그인 모듈 레지스트리 + ego-browser 진입점.
// 수집 스크립트는 ensureCardLogin 인터페이스로 붙는다(common.mjs 참조).
// 이 진입점은 명시적으로 호출할 때만 TaskSpace 를 만들고 로그인을 시도한다. import 만으로는 기동하지 않는다.
import * as kb from './kb.mjs';
import * as hana from './hana.mjs';
import * as ibk from './ibk.mjs';
import { ensureCardLogin, STATUS } from './common.mjs';

export const SITES = { kb, hana, ibk };

export function siteFor(issuer) {
  const site = SITES[issuer];
  if (!site) throw new Error(`unknown issuer: ${issuer}; expected kb|hana|ibk`);
  return site;
}

// ego-browser nodejs 에서 실행하는 명시적 진입점.
// 사용: ego-browser nodejs -e "const { mainEgo } = await import('file:///C:/.../tools/card_login/entry.mjs'); await mainEgo({ taskSpace: globalThis.taskSpace, issuer: 'kb' })"
export async function mainEgo({
  taskSpace,
  issuer,
  spaceName = 'card login automation',
  statusDir = 'D:/WebLedgerHost/data/backups/card-login-20261113/status',
  logoutAfterVerify = true,
} = {}) {
  if (typeof taskSpace !== 'function') throw new Error('taskSpace factory required (run under ego-browser nodejs)');
  const site = siteFor(issuer);
  const task = await taskSpace(spaceName);
  const page = task.page('p1');
  const result = await ensureCardLogin({ task, page, site, statusDir, logoutAfterVerify });
  // 비밀 값 없는 상태만 출력한다.
  console.log(JSON.stringify({
    issuer: result.issuer,
    status: result.status,
    reason: result.reason,
    usageConfirmed: result.usageConfirmed ?? null,
    statusFile: result.statusFile,
  }));
  const needsUser = [STATUS.REGISTRATION_REQUIRED, STATUS.ADDITIONAL_AUTH_REQUIRED, STATUS.LOGIN_FAILED].includes(result.status);
  if (needsUser) {
    // additional_auth 는 ensureCardLogin 안에서 이미 handOff 했다. 나머지는 사용자가 등록/확인해야 한다.
    if (result.status !== STATUS.ADDITIONAL_AUTH_REQUIRED && typeof task.handOff === 'function') {
      try { await task.handOff(); } catch { /* noop */ }
    }
  } else if (typeof task.finish === 'function') {
    await task.finish({ keep: [] });
  }
  return result;
}
