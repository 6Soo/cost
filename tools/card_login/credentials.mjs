// 자격 증명 읽기(Node 측). 비밀 값은 일회성 named pipe 로만 받는다.
// 명령 인자·환경 변수·stdout·로그에 비밀 값을 남기지 않는다.
import { spawn } from 'node:child_process';
import net from 'node:net';
import crypto from 'node:crypto';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const HERE = path.dirname(fileURLToPath(import.meta.url));

function connectAndRead(pipePath, timeoutMs) {
  const deadline = Date.now() + timeoutMs;
  return new Promise((resolve, reject) => {
    const attempt = () => {
      const sock = net.connect(pipePath);
      let data = '';
      let settled = false;
      const done = () => {
        if (settled) return;
        settled = true;
        sock.destroy();
        resolve(data);
      };
      const fail = (err) => {
        if (settled) return;
        // Windows named pipe 는 서버 종료 시 'end' 대신 EPIPE/ECONNRESET 를 낼 수 있다.
        // 이미 데이터를 받았으면 정상 완료로 처리한다(전송은 끝나고 파이프만 닫힌 상태).
        if (data.length > 0 && (err.code === 'EPIPE' || err.code === 'ECONNRESET' || err.code === 'EOF')) {
          done();
          return;
        }
        settled = true;
        sock.destroy();
        if (Date.now() < deadline && (err.code === 'ENOENT' || err.code === 'ECONNREFUSED')) {
          setTimeout(attempt, 150);
        } else {
          reject(err);
        }
      };
      sock.on('data', (chunk) => { data += chunk.toString('utf8'); });
      sock.on('end', done);
      sock.on('close', () => { if (data.length > 0) done(); });
      sock.on('error', fail);
      sock.setTimeout(Math.max(1000, deadline - Date.now()), () => {
        if (data.length > 0) done();
        else fail(Object.assign(new Error('PIPE_TIMEOUT'), { code: 'PIPE_TIMEOUT' }));
      });
    };
    attempt();
  });
}

function waitExit(child, timeoutMs) {
  return new Promise((resolve) => {
    const timer = setTimeout(() => resolve(null), timeoutMs);
    child.on('exit', (code) => { clearTimeout(timer); resolve(code); });
  });
}

// issuer 자격 증명을 읽어 메모리로만 반환한다. 등록되지 않았으면 {status:'not_registered'}.
export async function readCredentials(issuer, opts = {}) {
  const powershell = opts.powershell || 'powershell.exe';
  const scriptDir = opts.scriptDir || HERE;
  const storeRoot = opts.storeRoot || null;
  const timeoutMs = opts.timeoutMs || 30000;
  const pipeName = 'cost-card-login-' + crypto.randomBytes(12).toString('hex');
  const pipePath = '\\\\.\\pipe\\' + pipeName;
  const args = ['-NoProfile', '-NonInteractive', '-ExecutionPolicy', 'Bypass',
    '-File', path.join(scriptDir, 'read_credentials.ps1'), '-Issuer', issuer, '-PipeName', pipeName];
  if (storeRoot) args.push('-StoreRoot', storeRoot);
  // stdio: stdin ignore, stdout ignore(비밀 없음), stderr 만 상태 코드용으로 수집.
  const child = spawn(powershell, args, { stdio: ['ignore', 'ignore', 'pipe'], windowsHide: true });
  let stderr = '';
  child.stderr.on('data', (d) => { stderr += d.toString('utf8'); });
  let raw;
  try {
    raw = await connectAndRead(pipePath, timeoutMs);
  } catch (err) {
    child.kill();
    const code = /CARD_LOGIN_NOT_REGISTERED/.test(stderr) ? 'not_registered' : 'read_error';
    return { status: code, reason: err.code || 'PIPE_ERROR' };
  }
  await waitExit(child, 5000);
  let env;
  try { env = JSON.parse(raw); } catch { return { status: 'read_error', reason: 'BAD_JSON' }; }
  if (env.status !== 'ok') return { status: env.status || 'read_error' };
  return { status: 'ok', id: env.id, password: env.password, certPassword: env.certPassword ?? null };
}

// 비밀 값이 출력·로그·상태 JSON 에 섞이지 않도록 마스킹한다.
export function redact(text, secrets) {
  let out = String(text);
  for (const s of secrets || []) {
    if (s && typeof s === 'string' && s.length > 0) {
      out = out.split(s).join('[REDACTED]');
    }
  }
  return out;
}

// 상태/로그용 안전 문자열화. 비밀 값 목록을 함께 넘기면 마스킹한다.
export function safeStringify(value, secrets) {
  return redact(JSON.stringify(value), secrets);
}
