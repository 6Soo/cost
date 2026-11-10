import { writeFile, mkdir } from 'node:fs/promises';
import { createHash } from 'node:crypto';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { DEFAULT_ARCHIVE_DIRNAME } from './constants.mjs';
import { OtaError } from './errors.mjs';

export function utcStamp(date = new Date()) {
  return date.toISOString().replace(/[:.]/g, '-').replace('T', '_');
}

export function resolveArchiveRoot({ archiveDir = null, env = process.env, moduleUrl = import.meta.url } = {}) {
  if (archiveDir) return { root: archiveDir, source: 'option' };
  if (env && typeof env.OTA_ARCHIVE_DIR === 'string' && env.OTA_ARCHIVE_DIR.trim()) {
    return { root: env.OTA_ARCHIVE_DIR, source: 'env' };
  }
  return { root: defaultRoot(moduleUrl), source: 'default' };
}

function defaultRoot(moduleUrl) {
  return path.join(repoRoot(moduleUrl), '.local-archive', DEFAULT_ARCHIVE_DIRNAME, utcStamp());
}

function repoRoot(moduleUrl) {
  try {
    return path.resolve(path.dirname(fileURLToPath(moduleUrl)), '..', '..');
  } catch {
    return process.cwd();
  }
}

export function artifactPath(root, provider, file) {
  return path.join(root, provider, file);
}

export function relativeArtifact(file) {
  return file.split(path.sep).join('/');
}

export async function saveArtifacts({ root, provider, files }) {
  const saved = [];
  for (const entry of files) {
    const target = artifactPath(root, provider, entry.file);
    const payload = `${JSON.stringify(entry.data, null, 2)}\n`;
    try {
      await mkdir(path.dirname(target), { recursive: true });
      await writeFile(target, payload, { encoding: 'utf8', flag: 'wx' });
      saved.push(relativeArtifact(path.relative(path.join(root, provider), target)));
    } catch (error) {
      if (error && (error.code === 'EEXIST' || error.code === 'EPERM')) {
        throw new OtaError('OUTPUT_EXISTS', { cls: 'write', diagnostic: `refuse_overwrite:${provider}/${entry.file}` });
      }
      throw new OtaError('WRITE_ERROR', { cls: 'write', diagnostic: `write_failed:${provider}/${entry.file}`, cause: error });
    }
  }
  return saved;
}

export async function ensureRunDirectory(root) {
  try {
    await mkdir(root, { recursive: true });
    return root;
  } catch (error) {
    throw new OtaError('WRITE_ERROR', { cls: 'write', diagnostic: 'mkdir_failed', cause: error });
  }
}

export function sha256(text) {
  return createHash('sha256').update(String(text), 'utf8').digest('hex');
}
