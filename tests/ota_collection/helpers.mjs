import { mkdtemp, readFile, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import path from 'node:path';

// Synthetic fixtures only: no real portal, account, cookie, token or customer data.
export const FIXTURE_TOKEN = 'fixture-observed-token-synthetic';

export function response(status, payload, { headers = {}, raw = null } = {}) {
  const body = raw === null ? JSON.stringify(payload) : raw;
  return {
    status,
    ok: status >= 200 && status < 300,
    headers: { get: (name) => headers[String(name).toLowerCase()] ?? null },
    text: async () => body,
  };
}

export function fakeFetch(handler) {
  const calls = [];
  const fn = async (url, init = {}) => {
    calls.push({ url: String(url), init });
    return handler(String(url), init ?? {});
  };
  fn.calls = calls;
  fn.lastCall = () => calls[calls.length - 1] ?? null;
  return fn;
}

export async function makeTempDir() {
  return mkdtemp(path.join(tmpdir(), 'ota-collection-test-'));
}

export async function readJson(file) {
  return JSON.parse(await readFile(file, 'utf8'));
}

export async function cleanup(dir) {
  await rm(dir, { recursive: true, force: true });
}
