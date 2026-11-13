import { mkdir, rename, rm, writeFile } from 'node:fs/promises';
import path from 'node:path';
import process from 'node:process';
import { randomUUID } from 'node:crypto';

const SOURCES = new Set(['kb', 'hana', 'ibk', 'agoda', 'trip', 'booking']);
export const COLLECTION_RUN_SUMMARY_SCHEMA = 'cost.collection-run-summary.v1';

/** Persist only the public, non-sensitive collection status contract. */
export async function writeCollectionRunSummary({
  source,
  status,
  loginRequired,
  finishedAt = new Date(),
  dataRoot = process.env.WEBLEDGER_DATA_ROOT,
} = {}) {
  if (!SOURCES.has(source)) throw new TypeError('unsupported collection summary source');
  if (typeof status !== 'string' || !status) throw new TypeError('collection summary status is required');
  if (typeof loginRequired !== 'boolean') throw new TypeError('loginRequired must be boolean');
  if (typeof dataRoot !== 'string' || !dataRoot.trim()) return null;

  const timestamp = new Date(finishedAt);
  if (!Number.isFinite(timestamp.getTime())) throw new TypeError('finishedAt must be a valid date');
  const directory = path.join(path.resolve(dataRoot), 'collection-runs');
  const target = path.join(directory, `${source}.json`);
  const temporary = path.join(directory, `.${source}.${randomUUID()}.tmp`);
  const body = `${JSON.stringify({
    schema: COLLECTION_RUN_SUMMARY_SCHEMA,
    source,
    finished_at: timestamp.toISOString(),
    status,
    login_required: loginRequired,
  }, null, 2)}\n`;

  await mkdir(directory, { recursive: true });
  try {
    await writeFile(temporary, body, { encoding: 'utf8', flag: 'wx' });
    await rename(temporary, target);
  } catch (error) {
    // Temporary files contain no source data; cleanup is best effort after a failed atomic write.
    try { await rm(temporary, { force: true }); } catch {}
    throw error;
  }
  return target;
}
