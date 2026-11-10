import { writeFile, mkdir, lstat, realpath } from 'node:fs/promises';
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
  const base = safeChildPath(root, provider);
  return safeChildPath(base, file);
}

function invalidPath() {
  // Never echo untrusted paths (which can contain credentials or identifiers).
  return new OtaError('OUTPUT_PATH_INVALID', { cls: 'write', diagnostic: 'output_path_invalid' });
}

export function safeChildPath(root, child) {
  if (typeof child !== 'string' || path.win32.isAbsolute(child) || path.posix.isAbsolute(child)) throw invalidPath();
  const parts = child.split(/[\\/]/);
  if (parts.some((part) => !/^[A-Za-z0-9_-][A-Za-z0-9._-]*$/.test(part)
    || part.endsWith('.') || /^(con|prn|aux|nul|com[1-9]|lpt[1-9])(?:\.|$)/i.test(part))) throw invalidPath();
  const base = path.resolve(root);
  const target = path.resolve(base, ...parts);
  const relative = path.relative(base, target);
  if (!relative || relative === '..' || relative.startsWith(`..${path.sep}`) || path.isAbsolute(relative)) throw invalidPath();
  return target;
}

async function safeDirectory(directory) {
  // Walk before creating children: mkdir({recursive:true}) would follow an
  // existing junction/symlink and could create directories outside the archive.
  const absolute = path.resolve(directory);
  const anchor = path.parse(absolute).root;
  let current = anchor;
  for (const part of absolute.slice(anchor.length).split(path.sep).filter(Boolean)) {
    current = path.join(current, part);
    try { await mkdir(current); } catch (error) { if (error.code !== 'EEXIST') throw error; }
    const stat = await lstat(current);
    if (stat.isSymbolicLink() || !stat.isDirectory()) throw invalidPath();
  }
  const physical = await realpath(absolute);
  if (path.relative(absolute, physical) !== '') throw invalidPath();
  return absolute;
}

export function relativeArtifact(file) {
  return file.split(path.sep).join('/');
}

export async function saveArtifacts({ root, provider, files }) {
  const saved = [];
  try {
    // Validate the whole batch before making any directory or writing bytes.
    const targets = files.map((entry) => artifactPath(root, provider, entry.file));
    for (let index = 0; index < files.length; index += 1) {
      const entry = files[index];
      const target = targets[index];
      const payload = `${JSON.stringify(entry.data, null, 2)}\n`;
      await safeDirectory(path.dirname(target));
      await writeFile(target, payload, { encoding: 'utf8', flag: 'wx' });
      saved.push(relativeArtifact(path.relative(path.join(root, provider), target)));
    }
  } catch (error) {
    const failure = error instanceof OtaError ? error : new OtaError(
      error?.code === 'EEXIST' ? 'OUTPUT_EXISTS' : 'WRITE_ERROR',
      { cls: 'write', diagnostic: error?.code === 'EEXIST' ? 'refuse_overwrite' : 'write_failed', cause: error },
    );
    failure.savedFiles = [...saved];
    throw failure;
  }
  return saved;
}

export async function ensureRunDirectory(root) {
  try {
    await safeDirectory(root);
    return root;
  } catch (error) {
    if (error instanceof OtaError) throw error;
    throw new OtaError('WRITE_ERROR', { cls: 'write', diagnostic: 'mkdir_failed', cause: error });
  }
}

export function sha256(text) {
  return createHash('sha256').update(String(text), 'utf8').digest('hex');
}
