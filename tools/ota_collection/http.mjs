import { setTimeout as sleep } from 'node:timers/promises';
import { MAX_ATTEMPTS, RETRY_BASE_MS, RETRY_CAP_MS } from './constants.mjs';
import { OtaError } from './errors.mjs';

export function retryBackoff(attempt) {
  return Math.min(RETRY_BASE_MS * 2 ** Math.max(0, attempt - 1), RETRY_CAP_MS);
}

const LOGIN_MARKERS = /(sign[- ]?in|log[- ]?in|signin|로그인|계정에 로그인|회원 로그인)/i;
const LOGIN_PAGE_CONTENT = /^\s*(?:<!doctype\s+html|<html|<head|<body|window\.)/i;

async function readBody(response) {
  if (typeof response.text === 'function') return response.text();
  if (typeof response.json === 'function') return JSON.stringify(await response.json());
  if (typeof response.body === 'string') return response.body;
  if (response.body === null || response.body === undefined) return '';
  return JSON.stringify(response.body);
}

export async function requestJson({
  fetchImpl,
  url,
  method = 'GET',
  headers = {},
  body,
  json,
  authStatuses = [],
  attemptCap = MAX_ATTEMPTS,
  retryDelay: delay = retryBackoff,
  signal,
  provider = null,
  beforeAttempt = null,
}) {
  const payload = json !== undefined ? json : body;
  let lastFailure = null;
  for (let attempt = 1; attempt <= attemptCap; attempt += 1) {
    if (beforeAttempt) await beforeAttempt(attempt);
    try {
      const init = { method, headers: { accept: 'application/json', ...headers }, signal };
      if (payload !== undefined) {
        init.body = typeof payload === 'string' ? payload : JSON.stringify(payload);
        if (!('content-type' in headers) && !('Content-Type' in headers)) init.headers['content-type'] = 'application/json';
      }
      const response = await fetchImpl(url, init);
      const status = Number(response?.status ?? 0);
      if (status === 429 || status >= 500) {
        lastFailure = new OtaError('HTTP_ERROR', {
          cls: 'rate',
          status,
          diagnostic: `http_${status}`,
          resume: attempt < attemptCap ? null : 'transient service error; retry later',
          provider,
        });
        if (attempt < attemptCap) {
          await sleep(typeof delay === 'function' ? delay(attempt) : delay);
          continue;
        }
        throw lastFailure;
      }
      if (!(status >= 200 && status < 300)) {
        if (authStatuses.includes(status)) {
          throw new OtaError('LOGIN_REQUIRED', {
            cls: 'auth',
            status,
            diagnostic: `auth_status_${status}`,
            resume: 're-login manually in the portal session; no credential automation',
            provider,
          });
        }
        throw new OtaError('HTTP_ERROR', {
          cls: 'http',
          status,
          diagnostic: `http_${status}`,
          resume: 'request rejected; verify the observed template/session without guessing',
          provider,
        });
      }
      const text = await readBody(response);
      if (!text) {
        throw new OtaError('RESPONSE_EMPTY', { cls: 'shape', status, diagnostic: 'empty_body', provider });
      }
      if (typeof text === 'string' && (LOGIN_PAGE_CONTENT.test(text) && LOGIN_MARKERS.test(text))) {
        throw new OtaError('LOGIN_REQUIRED', {
          cls: 'auth',
          status,
          diagnostic: 'login_page_detected',
          resume: 're-login manually in the portal session; no credential automation',
          provider,
        });
      }
      try {
        return { status, json: JSON.parse(text), attempts: attempt };
      } catch {
        throw new OtaError('RESPONSE_NOT_JSON', {
          cls: 'shape',
          status,
          diagnostic: 'non_json_body',
          resume: 'response was not JSON; login state or template may have changed - verify without guessing',
          provider,
        });
      }
    } catch (error) {
      lastFailure = error;
      if (error instanceof OtaError) {
        if (error.cls === 'abort') throw error;
        if (error.cls === 'network' || error.cls === 'rate') {
          if (attempt < attemptCap) {
            await sleep(typeof delay === 'function' ? delay(attempt) : delay);
            continue;
          }
          throw error;
        }
        throw error;
      }
      if (error && typeof error === 'object' && error.name === 'AbortError') {
        throw new OtaError('ABORTED', { cls: 'abort', diagnostic: 'aborted', cause: error, provider });
      }
      if (attempt < attemptCap) {
        await sleep(typeof delay === 'function' ? delay(attempt) : delay);
        continue;
      }
      throw new OtaError('NETWORK_ERROR', {
        cls: 'network',
        diagnostic: 'fetch_failed',
        cause: error,
        provider,
      });
    }
  }
  throw lastFailure ?? new OtaError('NETWORK_ERROR', { cls: 'network', provider });
}

export function makeRequester(fetchImpl, defaults = {}) {
  return (url, init = {}) => requestJson({ fetchImpl, ...defaults, url, ...init });
}

export function adaptPageFetch(pageFetch) {
  return async (url, init = {}) => {
    const response = await pageFetch(url, init);
    return {
      status: Number(response?.status ?? 0),
      ok: Boolean(response?.ok),
      statusText: response?.statusText ?? '',
      url: response?.url ?? url,
      headers: {
        get: (name) => {
          const value = response?.headers?.[name] ?? response?.headers?.[name.toLowerCase()];
          return value === undefined || value === null ? null : String(value);
        },
      },
      text: typeof response?.text === 'function'
        ? () => response.text()
        : async () => (response?.body === undefined || response?.body === null ? '' : (typeof response.body === 'string' ? response.body : JSON.stringify(response.body))),
    };
  };
}
