import { randomBytes } from 'node:crypto';
import { writeFile } from 'node:fs/promises';
import path from 'node:path';
import { MAX_FAILURES, PROVIDER_LIST, STATUS, maxStatus } from './constants.mjs';
import { ensureRunDirectory, relativeArtifact, saveArtifacts, sha256 } from './storage.mjs';
import { buildManifest } from './manifest.mjs';
import { isOtaError, statusForError, toOtaError } from './errors.mjs';
import { makeRequester } from './http.mjs';
import {
  enterProvider,
  getProvider,
  assertAllowedUrl,
  resolveAccess,
} from './providers.mjs';

export function createBudget({ maxFailures = MAX_FAILURES } = {}) {
  let failures = 0;
  let listRequests = 0;
  return {
    listRequests: () => listRequests,
    bumpList: () => { listRequests += 1; },
    spike: (diagnostic = null) => { failures += 1; return { failures, limit: maxFailures, diagnostic }; },
    failures: () => failures,
    failureLimitReached: () => failures > maxFailures,
    maxFailures,
    snapshot: () => ({ failures, listRequests }),
  };
}

export async function runPool(items, limit, worker) {
  const results = new Array(items.length);
  let next = 0;
  const lanes = Math.max(1, Math.min(limit, items.length || 1));
  async function lane() {
    for (;;) {
      const index = next;
      next += 1;
      if (index >= items.length) return;
      try {
        results[index] = { ok: true, value: await worker(items[index], index) };
      } catch (error) {
        results[index] = { ok: false, error };
      }
    }
  }
  await Promise.all(Array.from({ length: lanes }, () => lane()));
  return results;
}

function detailCounts(outcomes, listed, invalidItems) {
  const counts = {
    listed,
    details_saved: 0,
    details_invalid: 0,
    details_capture: 0,
    details_skipped: 0,
    details_login_required: 0,
    items_invalid: invalidItems,
  };
  for (const outcome of outcomes ?? []) {
    if (!outcome || typeof outcome !== 'object') continue;
    switch (outcome.status) {
      case STATUS.OK:
        counts.details_saved += 1;
        break;
      case STATUS.INVALID:
        counts.details_invalid += 1;
        break;
      case STATUS.CAPTURE_REQUIRED:
      case STATUS.AUTH_UNKNOWN:
        counts.details_capture += 1;
        break;
      case STATUS.LOGIN_REQUIRED:
        counts.details_login_required += 1;
        break;
      case STATUS.SKIPPED:
      case STATUS.INTERRUPTED:
      default:
        counts.details_skipped += 1;
        break;
    }
  }
  return counts;
}

function unique(values, cap = 8) {
  const out = [];
  for (const value of values) {
    if (typeof value !== 'string' || !value.trim()) continue;
    if (!out.includes(value)) out.push(value.slice(0, 200));
    if (out.length >= cap) break;
  }
  return out;
}

async function runOneProvider(name, ctxBase, archiveRoot) {
  const provider = getProvider(name);
  if (!provider) {
    return {
      provider: name,
      status: STATUS.INVALID,
      counts: detailCounts([], 0, 0),
      files: [],
      diagnostics: ['provider_unknown'],
      resume: ['provider must be one of agoda, trip, booking'],
    };
  }
  const opts = ctxBase.opts ?? {};
  const access = resolveAccess(name, opts);
  if (access.error) {
    return {
      provider: name,
      status: STATUS.INVALID,
      counts: detailCounts([], 0, 0),
      files: [],
      diagnostics: unique(access.diagnostics ?? ['provider_access_config']),
      resume: ['fix provider URL configuration; no URL is guessed'],
    };
  }
  const fetchImpl = ctxBase.fetchImpl;
  if (typeof fetchImpl !== 'function') {
    return {
      provider: name,
      status: STATUS.FAILED,
      counts: detailCounts([], 0, 0),
      files: [],
      diagnostics: ['browser_access_missing'],
      resume: ['run under ego-browser nodejs or provide a fetch implementation bound to the provider page'],
    };
  }
  const guardedFetch = async (href, init) => {
    const url = assertAllowedUrl(href, access);
    return fetchImpl(url, init);
  };
  const budget = createBudget();
  const ctx = {
    provider: name,
    budget,
    access,
    clock: ctxBase.clock ?? (() => new Date()),
    opts,
    requestJson: makeRequester(guardedFetch, { provider: name }),
    goto: typeof ctxBase.goto === 'function' ? ctxBase.goto : null,
    async save(files) {
      return saveArtifacts({ root: archiveRoot, provider: name, files });
    },
  };
  let result;
  try {
    const navigation = await enterProvider(ctx);
    result = await provider.run(ctx);
    return await finalize(name, result, navigation, archiveRoot, ctx);
  } catch (error) {
    const ota = toOtaError(error);
    return {
      provider: name,
      status: isOtaError(ota) ? statusForError(ota) : STATUS.FAILED,
      counts: detailCounts([], 0, 0),
      files: [],
      diagnostics: [ota.diagnostic ?? ota.code ?? 'internal_error'],
      resume: ota.resume ? [ota.resume] : [],
    };
  }
}

async function finalize(name, result, navigation, archiveRoot, ctx) {
  const outcomes = Array.isArray(result?.outcomes) ? result.outcomes : [];
  const listed = Array.isArray(result?.items) ? result.items.length : 0;
  const invalidItems = Number(result?.invalidItems) || 0;
  const statuses = [result?.listStatus, ...outcomes.map((outcome) => outcome?.status)];
  const status = maxStatus(statuses.filter(Boolean));
  const diagnostics = unique([
    ...(navigation?.diagnostics ?? []),
    ...(Array.isArray(result?.diagnostics) ? result.diagnostics : []),
    ...outcomes.map((outcome) => outcome?.diagnostic).filter(Boolean),
  ]);
  const resume = unique([
    ...(navigation?.resume ?? []),
    ...(Array.isArray(result?.resume) ? result.resume : []),
    ...outcomes.map((outcome) => outcome?.resume).filter(Boolean),
  ]);
  const files = [];
  for (const outcome of outcomes) {
    if (outcome?.record && typeof outcome.file === 'string' && outcome.file) files.push({ file: outcome.file, data: outcome.record });
  }
  if (Array.isArray(result?.files)) files.push(...result.files);
  let saved = [];
  if (files.length > 0) {
    try {
      saved = await ctx.save(files);
    } catch (error) {
      const ota = toOtaError(error);
      return {
        provider: name,
        status: STATUS.FAILED,
        counts: detailCounts(outcomes, listed, invalidItems),
        files: [],
        diagnostics: unique([...(Array.isArray(result?.diagnostics) ? result.diagnostics : []), ota.diagnostic ?? ota.code ?? 'write_failed']),
        resume: unique([...(Array.isArray(result?.resume) ? result.resume : []), ota.resume ? [ota.resume] : [],
          'written files were kept in place; use a fresh run directory so saved responses are never overwritten']),
      };
    }
  }
  return {
    provider: name,
    status,
    counts: detailCounts(outcomes, listed, invalidItems),
    files: saved.map(relativeArtifact),
    navigation: { provider: name, origin: ctx.access?.origin ?? null, entry: ctx.access?.urls?.entry ?? null, verified: Boolean(navigation?.verified) },
    diagnostics,
    resume,
    savedCount: files.length,
  };
}

export async function runCollection({
  providers = PROVIDER_LIST,
  archiveRoot,
  runId = `run-${randomBytes(4).toString('hex')}`,
  clock,
  opts = {},
  fetchImpl,
  goto = null,
  startedAt = new Date(),
} = {}) {
  if (typeof archiveRoot !== 'string' || !archiveRoot.trim()) {
    throw new Error('archiveRoot is required; resolve it with resolveArchiveRoot() first');
  }
  await ensureRunDirectory(archiveRoot);
  const list = Array.isArray(providers) && providers.length ? providers : [...PROVIDER_LIST];
  const rows = [];
  for (const name of list) {
    rows.push(await runOneProvider(name, { clock, opts, fetchImpl, goto }, archiveRoot));
  }
  const manifest = buildManifest({ runId, startedAt, archiveRoot, rows });
  const manifestBytes = `${JSON.stringify(manifest, null, 2)}\n`;
  try {
    await writeFile(path.join(archiveRoot, 'manifest.json'), manifestBytes, { encoding: 'utf8', flag: 'wx' });
  } catch (error) {
    if (error && error.code === 'EEXIST') {
      throw new Error(`manifest already exists in ${archiveRoot}; use a fresh run directory`);
    }
    throw toOtaError(error, 'WRITE_ERROR');
  }
  return { runId, archiveRoot, rows, manifest, manifestSha256: sha256(manifestBytes) };
}
