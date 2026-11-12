// 합성 전용 에이전트 보조(하이브리드) 헬퍼 검사. 실제 사이트·비밀 값·운영 폴더 접근 없음.
// 검증: 키패드 좌표/선택자 클릭(비밀 미출력), 누락 키 일반 오류, DOM 키패드 관찰,
//       assistKeypadEntry 상태(entered/registration_required/field_missing/keypad_unobserved),
//       캡처 파일명·handoff 상태에 비밀 없음, ensureCardLogin agent_assist 흐름.
// 실행: node tests/card_login/test_assist_logic.mjs → PASS/FAIL 줄 + 요약, 실패 시 nonzero exit.
import assert from 'node:assert';
import { mkdtemp, readFile, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import path from 'node:path';
import {
  enterByCoordinates, enterBySelectors, observeDomKeypad, assistKeypadEntry,
} from '../../tools/card_login/keypad.mjs';
import {
  captureAssistScreenshot, writeAgentHandoff, readAgentHandoff, HANDOFF_SCHEMA,
} from '../../tools/card_login/handoff.mjs';
import { isBlocked } from '../../tools/card_login/attempts.mjs';
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

// 비밀 문자 각각에 좌표를 부여한 배치(비밀 아님 — 배치 정보).
function keyMapFor(secret) {
  const map = {};
  [...secret].forEach((ch, i) => { map[ch] = { x: 100 + i, y: 200 }; });
  return map;
}

function fakePage({ doc = null, evalResult = undefined } = {}) {
  const clicks = [];
  const shots = [];
  return {
    clicks, shots,
    mouse: { click: async (x, y, opts) => { clicks.push({ x, y, label: opts && opts.label }); } },
    click: async (sel, opts) => { clicks.push({ sel, label: opts && opts.label }); },
    waitForTimeout: async () => {},
    screenshot: async ({ path: file }) => { shots.push(file); },
    evaluate: async (fn, arg) => {
      if (doc) {
        const saved = global.document;
        global.document = doc;
        try { return fn(arg); } finally { global.document = saved; }
      }
      return evalResult;
    },
    url: async () => 'https://example.test/',
  };
}

function fakeDoc(buttons) {
  const root = {
    querySelectorAll: () => buttons.map((b) => ({
      textContent: b.text,
      getBoundingClientRect: () => ({ x: b.x, y: b.y, width: b.w, height: b.h }),
    })),
  };
  return { querySelector: (sel) => (sel === '#keypad' ? root : null) };
}

async function withTemp(fn) {
  const dir = await mkdtemp(path.join(tmpdir(), 'card-assist-test-'));
  try { await fn(dir); } finally { await rm(dir, { recursive: true, force: true }); }
}

await test('enterByCoordinates clicks each char, no count/secret in result', async () => {
  const page = fakePage();
  const res = await enterByCoordinates(page, SECRET_PW, keyMapFor(SECRET_PW), { delayMs: 0 });
  assert.equal(res.entered, true);
  assert.equal(page.clicks.length, [...SECRET_PW].length);
  assert.ok(!('count' in res), 'length leaked via count');
  assert.ok(!JSON.stringify(res).includes(SECRET_PW), 'secret in result');
  for (const c of page.clicks) assert.ok(!String(c.label).includes(SECRET_PW), 'secret in click label');
});

await test('enterByCoordinates missing key throws generic error (no char leak)', async () => {
  const page = fakePage();
  await assert.rejects(
    () => enterByCoordinates(page, 'ab', { a: { x: 1, y: 2 } }, { delayMs: 0 }),
    (err) => err.message === 'KEYPAD_KEY_MISSING' && !err.message.includes('b'),
  );
});

await test('enterBySelectors clicks per-char selectors, no count in result', async () => {
  const page = fakePage();
  const res = await enterBySelectors(page, 'abc', (ch) => `#key-${ch}`, { delayMs: 0 });
  assert.equal(res.entered, true);
  assert.ok(!('count' in res), 'length leaked via count');
  assert.deepEqual(page.clicks.map((c) => c.sel), ['#key-a', '#key-b', '#key-c']);
});

await test('observeDomKeypad maps single-char buttons, ignores multi-char', async () => {
  const doc = fakeDoc([
    { text: '1', x: 0, y: 0, w: 10, h: 10 },
    { text: '2', x: 20, y: 0, w: 10, h: 10 },
    { text: '확인', x: 0, y: 40, w: 30, h: 10 }, // 여러 글자 → 제외
  ]);
  const page = fakePage({ doc });
  const map = await observeDomKeypad(page, '#keypad');
  assert.deepEqual(map['1'], { x: 5, y: 5 });
  assert.deepEqual(map['2'], { x: 25, y: 5 });
  assert.ok(!('확인' in map));
});

await test('assistKeypadEntry entered (keyMap provided), no count/secret output', async () => {
  const page = fakePage();
  const res = await assistKeypadEntry(page, {
    issuer: 'kb', keyMap: keyMapFor(SECRET_PW),
    readCredentialsImpl: async () => creds,
  });
  assert.equal(res.status, 'entered');
  assert.deepEqual(Object.keys(res), ['status'], 'result must only carry status (no length)');
  assert.ok(!('count' in res), 'length leaked via count');
  assert.ok(!JSON.stringify(res).includes(SECRET_PW), 'secret in result');
  assert.ok(!JSON.stringify(res).includes(String([...SECRET_PW].length)), 'length leaked numerically');
});

await test('assistKeypadEntry registration_required when not registered', async () => {
  const page = fakePage();
  const res = await assistKeypadEntry(page, {
    issuer: 'kb', keyMap: keyMapFor(SECRET_PW),
    readCredentialsImpl: async () => ({ status: 'not_registered' }),
  });
  assert.equal(res.status, 'registration_required');
  assert.equal(page.clicks.length, 0);
});

await test('assistKeypadEntry field_missing when password empty', async () => {
  const page = fakePage();
  const res = await assistKeypadEntry(page, {
    issuer: 'kb', keyMap: keyMapFor(SECRET_PW),
    readCredentialsImpl: async () => ({ ...creds, password: '' }),
  });
  assert.equal(res.status, 'field_missing');
});

await test('assistKeypadEntry keypad_unobserved when no map observed', async () => {
  const page = fakePage({ evalResult: {} });
  const res = await assistKeypadEntry(page, {
    issuer: 'kb', containerSelector: '#keypad',
    readCredentialsImpl: async () => creds,
  });
  assert.equal(res.status, 'keypad_unobserved');
});

await test('captureAssistScreenshot filename has issuer/step, no secret', () => withTemp(async (dir) => {
  const page = fakePage();
  const file = await captureAssistScreenshot(page, { issuer: 'kb', step: 'keypad_password', dir });
  assert.ok(file.startsWith(dir));
  assert.ok(path.basename(file).includes('kb') && path.basename(file).includes('keypad_password'));
  assert.ok(!file.includes(SECRET_PW) && !file.includes(SECRET_ID));
  assert.equal(page.shots.length, 1);
}));

await test('writeAgentHandoff record + read roundtrip, no secret', () => withTemp(async (dir) => {
  const { file, record } = await writeAgentHandoff({
    issuer: 'kb', step: 'keypad_password', reason: 'security_input_readonly',
    screenshot: path.join(dir, 'kb-keypad_password-x.png'),
    agentAction: 'assistKeypadEntry 로 입력(비밀 출력 금지)', statusDir: dir,
  });
  assert.equal(record.schema, HANDOFF_SCHEMA);
  const body = await readFile(file, 'utf8');
  assert.ok(!body.includes(SECRET_PW) && !body.includes(SECRET_ID) && !body.includes(SECRET_CERT));
  const read = await readAgentHandoff(dir, 'kb');
  assert.equal(read.step, 'keypad_password');
  assert.equal(read.issuer, 'kb');
}));

await test('ensureCardLogin agent_assist -> handOff, screenshot+handoff, blocked', () => withTemp(async (dir) => {
  _resetAttemptGuard();
  const env = { attemptsPath: path.join(dir, 'attempts.json'), assistDir: path.join(dir, 'assist'), statusDir: path.join(dir, 'status') };
  const task = { calls: 0, handOff: async () => { task.calls += 1; } };
  const site = {
    issuer: 'kb', isLoggedIn: async () => false,
    login: async () => ({ outcome: 'agent_assist', step: 'keypad_password', detail: 'security_input_readonly', agentAction: 'keypad' }),
    confirmUsageScreen: async () => true, logout: async () => {},
  };
  const page = fakePage();
  const res = await ensureCardLogin({ task, page, site, credentials: creds, ...env });
  assert.equal(res.status, STATUS.AGENT_ASSIST_REQUIRED);
  assert.equal(res.step, 'keypad_password');
  assert.equal(task.calls, 1);
  assert.ok(res.screenshot, 'screenshot missing');
  assert.ok(res.handoffFile, 'handoff file missing');
  assert.ok(!JSON.stringify(res).includes(SECRET_PW), 'secret in result');
  assert.equal(await isBlocked('kb', { path: env.attemptsPath }), true);
}));

console.log(`card_assist_logic: ${failures === 0 ? 'clean' : failures + ' failures'}`);
process.exit(failures === 0 ? 0 : 1);
