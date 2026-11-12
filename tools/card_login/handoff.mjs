// 스크립트가 막혀 에이전트 보조 단계로 넘길 때 남기는 상태/캡처 헬퍼.
// 상태 파일·캡처 파일 이름에 비밀 값을 넣지 않는다(사이트·단계·시각만).
// 캡처는 비공개 폴더에만 저장한다. 에이전트는 이 상태를 읽고 화면을 보며 보조 단계를 수행한다.
import { mkdir, writeFile, readFile } from 'node:fs/promises';
import path from 'node:path';

export const HANDOFF_SCHEMA = 'cost.card-login-agent-handoff.v1';
export const DEFAULT_ASSIST_DIR = 'D:/WebLedgerHost/data/backups/card-login-20261113/assist';

function stamp() {
  return new Date().toISOString().replace(/[:.]/g, '-');
}

// 비공개 폴더에 화면 캡처. 파일 이름은 <issuer>-<step>-<시각>.png (비밀 없음).
export async function captureAssistScreenshot(page, { issuer, step, dir = DEFAULT_ASSIST_DIR } = {}) {
  await mkdir(dir, { recursive: true });
  const file = path.join(dir, `${issuer}-${step}-${stamp()}.png`);
  if (page && typeof page.screenshot === 'function') {
    await page.screenshot({ path: file });
  }
  return file;
}

// 에이전트 보조 단계 상태 파일. 비밀 값 없는 지시·경로만 남긴다.
export async function writeAgentHandoff({
  issuer, step, reason = null, screenshot = null, agentAction = null,
  statusDir,
} = {}) {
  if (!statusDir) return null;
  await mkdir(statusDir, { recursive: true });
  const record = {
    schema: HANDOFF_SCHEMA,
    issuer,
    step,
    reason,
    agentAction,
    screenshot,
    observedAt: new Date().toISOString(),
  };
  const file = path.join(statusDir, `${issuer}-agent-handoff.json`);
  await writeFile(file, JSON.stringify(record, null, 1), 'utf8');
  return { file, record };
}

export async function readAgentHandoff(statusDir, issuer) {
  const file = path.join(statusDir, `${issuer}-agent-handoff.json`);
  try {
    const raw = await readFile(file, 'utf8');
    const data = JSON.parse(raw);
    if (data && data.schema === HANDOFF_SCHEMA) return data;
  } catch (err) {
    if (err && err.code !== 'ENOENT') throw err;
  }
  return null;
}
