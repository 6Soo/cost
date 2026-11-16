"""Read-only preflight for the recorded core-cutover evidence (2차 전환 범위).

The preflight verifies the inputs a run was recorded with: a copied board database, a copied
OTA solver-input file, the costcore binary and the repo the shadow ran against. It re-runs
`costcore shadow-links` and requires a PASS with no unlisted differences and equal, positive
Python/Rust regions. Any missing, zero, extra, damaged or failing piece of evidence blocks.

It reads named paths only, writes nothing and prints one aggregate JSON object on stdout. It
never contacts the live host's databases, never substitutes operational approval, the C2
measurement, verified backup/restore, or the cutover itself, and it never prints customer text.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
from argparse import ArgumentParser
from pathlib import Path

_HEX = re.compile(r'^[0-9a-fA-F]{64}$')
_VERSION = re.compile(r'costcore [0-9]+\.[0-9]+\.[0-9]+(?:-[0-9A-Za-z.-]+)?(?:\+[0-9A-Za-z.-]+)?')
_LIVE_FILES = ('board.sqlite', 'ota-evidence.sqlite', 'ota-review/ota-review.sqlite')
_KNOWN_UNLISTED = re.compile(r'^B-C\|[A-Za-z_][A-Za-z0-9_]*\|[^|\s]+\|(added|removed|differs)$')
_SIDECARS = ('-wal', '-shm', '-journal')
_REPO_FILES = ('core/known-diffs.txt', 'config/refund-pairing.json', 'config/ota-matching-defaults.json')
_LIMITS = ('offline verification of recorded copies only; does not substitute operational '
           'approval, C2 measurement, verified backup/restore, or cutover completion')


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, 'rb') as handle:
        while chunk := handle.read(1 << 20):
            digest.update(chunk)
    return digest.hexdigest()


def _real_runner():
    def run(argv):
        done = subprocess.run(argv, stdin=subprocess.DEVNULL, capture_output=True, text=True,
                               encoding='utf-8', timeout=600)
        return done.returncode, done.stdout, done.stderr
    return run


def _norm(path) -> str:
    return os.path.normcase(os.path.realpath(os.path.abspath(str(path))))


def _sidecar_paths(db: Path) -> list:
    base = str(db)
    return [base + suffix for suffix in _SIDECARS]


def _snapshot_repo(repo: Path) -> dict:
    """sha256 of the repo-side evidence the shadow reads; a missing or unreadable file is a refusal."""
    hashes = {}
    for rel in _REPO_FILES:
        path = repo / rel
        try:
            if not path.is_file():
                return None, rel
            hashes[rel] = _sha256(path)
        except OSError:
            return None, rel
    return hashes, None


def _same_file(a: object, b: object) -> bool:
    try:
        return os.path.samefile(str(a), str(b))
    except OSError:
        return False


def _blocked(code, **extra):
    result = {'status': 'BLOCKED', 'code': code, 'checks': [code], 'limits': _LIMITS}
    result.update(extra)
    return result


def _read(path: Path, code: str) -> tuple[str | None, dict | None]:
    try:
        if not path.is_file():
            return None, _blocked(code)
        return _sha256(path), None
    except OSError:
        return None, _blocked(code)


def _region(report, key) -> dict | str:
    value = report.get(key)
    if not isinstance(value, dict):
        return 'SHADOW_REGIONS_INVALID'
    counts = {}
    for side in ('python', 'rust'):
        number = value.get(side)
        if type(number) is not int or number < 0:
            return 'SHADOW_REGIONS_INVALID'
        counts[side] = number
    if counts['python'] != counts['rust']:
        return 'SHADOW_COUNT_MISMATCH'
    if counts['python'] <= 0:
        return 'SHADOW_ZERO_COUNT'
    return counts


def check(host_root, db, ota_input, costcore_bin, expected_binary_sha256, repo_root, *, runner=None):
    raw = {'host_root': host_root, 'db': db, 'ota_input': ota_input, 'costcore_bin': costcore_bin,
           'repo_root': repo_root}
    if any(value is None or (isinstance(value, str) and not value.strip()) for value in raw.values()):
        return _blocked('INPUTS_REQUIRED')
    paths = {key: str(value) for key, value in raw.items()}
    if expected_binary_sha256 is not None and not isinstance(expected_binary_sha256, str):
        return _blocked('BINARY_SHA_INVALID')
    host = Path(paths['host_root'])
    db_path, ota_path, bin_path, repo = (Path(paths[k]) for k in
                                         ('db', 'ota_input', 'costcore_bin', 'repo_root'))
    for path, symlink, missing in ((db_path, 'DB_IS_SYMLINK', 'DB_NOT_FOUND'),
                                   (ota_path, 'OTA_INPUT_IS_SYMLINK', 'OTA_INPUT_NOT_FOUND'),
                                   (bin_path, None, 'BINARY_NOT_FOUND'),
                                   (repo, None, 'REPO_NOT_FOUND')):
        try:
            if path.is_symlink():
                return _blocked(symlink or 'PATH_IS_SYMLINK')
            if path == repo:
                if repo.is_dir():
                    continue
                return _blocked(missing)
            if not path.is_file():
                return _blocked(missing)
        except OSError:
            return _blocked(missing)
    for sidecar in _sidecar_paths(db_path):
        if os.path.exists(sidecar):
            return _blocked('DB_SIDECAR_PRESENT', sidecar=os.path.basename(sidecar))
    repo_hashes, missing_repo = _snapshot_repo(repo)
    if missing_repo is not None:
        return _blocked('REPO_FILE_MISSING', missing=missing_repo)
    if expected_binary_sha256 is None:
        return _blocked('BINARY_SHA_REQUIRED')
    if not _HEX.match(expected_binary_sha256.strip()):
        return _blocked('BINARY_SHA_INVALID')
    db_norm, ota_norm = _norm(db_path), _norm(ota_path)
    for name in _LIVE_FILES:
        live = _norm(host / 'data' / name)
        if db_norm == live:
            return _blocked('DB_IS_LIVE')
        if ota_norm == live:
            return _blocked('OTA_INPUT_IS_LIVE')
    for path, code in ((db_path, 'DB_IS_LIVE'), (ota_path, 'OTA_INPUT_IS_LIVE')):
        for name in _LIVE_FILES:
            if _same_file(path, host / 'data' / name):
                return _blocked(code)
    db_hash, block = _read(db_path, 'DB_NOT_FOUND')
    if block:
        return block
    ota_hash, block = _read(ota_path, 'OTA_INPUT_NOT_FOUND')
    if block:
        return block
    try:
        binary_hash = _sha256(bin_path)
    except OSError:
        return _blocked('BINARY_NOT_FOUND')
    if binary_hash != expected_binary_sha256.strip().lower():
        return _blocked('BINARY_SHA_MISMATCH')
    run = runner if runner is not None else _real_runner()
    try:
        code, out, _ = run([str(bin_path), '--version'])
    except (OSError, subprocess.SubprocessError, UnicodeError):
        return _blocked('BINARY_VERSION_FAILED')
    version_ok = code == 0 and _VERSION.fullmatch((out or '').strip()) is not None
    if not version_ok:
        return _blocked('BINARY_VERSION_INVALID' if code == 0 else 'BINARY_VERSION_FAILED')
    try:
        if _sha256(bin_path) != binary_hash:
            return _blocked('BINARY_CHANGED', changed=['binary'])
    except OSError:
        return _blocked('BINARY_CHANGED', changed=['binary'])
    argv = [str(bin_path), 'shadow-links', '--host-root', str(host), '--db', str(db_path),
            '--ota-input', str(ota_path), '--repo-root', str(repo)]
    try:
        code, out, _ = run(argv)
    except (OSError, subprocess.SubprocessError, UnicodeError):
        return _blocked('SHADOW_RUN_FAILED')
    try:
        if _sha256(bin_path) != binary_hash:
            return _blocked('BINARY_CHANGED', changed=['binary'])
    except OSError:
        return _blocked('BINARY_CHANGED', changed=['binary'])
    try:
        db_after, _ = _read(db_path, 'INPUTS_CHANGED')
        ota_after, _ = _read(ota_path, 'INPUTS_CHANGED')
        repo_after, missing = _snapshot_repo(repo)
    except OSError:
        return _blocked('INPUTS_CHANGED')
    if db_after != db_hash or ota_after != ota_hash:
        return _blocked('INPUTS_CHANGED', changed=_changed(db_hash, db_after, ota_hash, ota_after))
    for sidecar in _sidecar_paths(db_path):
        if os.path.exists(sidecar):
            return _blocked('DB_SIDECAR_PRESENT', changed=['db' + sidecar[-4:]])
    if missing:
        return _blocked('REPO_FILE_CHANGED', changed=[missing])
    if repo_after != repo_hashes:
        key = next((rel for rel in _REPO_FILES if repo_after.get(rel) != repo_hashes.get(rel)), None)
        return _blocked('REPO_FILE_CHANGED', changed=[key] if key else [])
    return _shadow_result(code, out, db_hash, ota_hash, binary_hash, repo_hashes)


def _changed(before_db, after_db, before_ota, after_ota) -> list:
    changed = []
    if after_db != before_db:
        changed.append('db')
    if after_ota != before_ota:
        changed.append('ota_input')
    return changed


def _shadow_result(code, out, db_hash, ota_hash, binary_hash, repo_hashes) -> dict:
    if code != 0:
        return _blocked('SHADOW_EXIT_NONZERO', inputs={'db_sha256': db_hash, 'ota_input_sha256': ota_hash})
    text = (out or '').strip()
    if not text:
        return _blocked('SHADOW_RESULT_INVALID', inputs={'db_sha256': db_hash, 'ota_input_sha256': ota_hash})
    try:
        report = json.loads(text.splitlines()[0])
    except (ValueError, IndexError):
        return _blocked('SHADOW_RESULT_INVALID', inputs={'db_sha256': db_hash, 'ota_input_sha256': ota_hash})
    if not isinstance(report, dict) or report.get('status') != 'PASS':
        return _blocked('SHADOW_STATUS_NOT_PASS', inputs={'db_sha256': db_hash, 'ota_input_sha256': ota_hash})
    unlisted = report.get('unlisted')
    if not isinstance(unlisted, list) or any(not isinstance(key, str) for key in unlisted):
        return _blocked('SHADOW_RESULT_INVALID', inputs={'db_sha256': db_hash, 'ota_input_sha256': ota_hash})
    bad = [key for key in unlisted if _KNOWN_UNLISTED.match(key) is None]
    if bad:
        return _blocked('SHADOW_RESULT_INVALID', inputs={'db_sha256': db_hash, 'ota_input_sha256': ota_hash})
    if unlisted:
        return _blocked('SHADOW_UNLISTED', unlisted_count=len(unlisted),
                        inputs={'db_sha256': db_hash, 'ota_input_sha256': ota_hash})
    shadow = {'exit': code, 'status': 'PASS'}
    for key in ('refund', 'ota'):
        counts = _region(report, key)
        if isinstance(counts, str):
            return _blocked(counts, inputs={'db_sha256': db_hash, 'ota_input_sha256': ota_hash})
        shadow[key] = counts
    return {'status': 'READY', 'code': None, 'checks': [],
            'binary': {'sha256': binary_hash, 'version_ok': True},
            'inputs': {'db_sha256': db_hash, 'ota_input_sha256': ota_hash},
            'repo_files': repo_hashes,
            'shadow': shadow, 'inputs_changed': False, 'changed': [], 'limits': _LIMITS}


def main(argv=None) -> int:
    parser = ArgumentParser(description='Read-only core-cutover evidence preflight (aggregate JSON only).')
    parser.add_argument('--host-root', default=None)
    parser.add_argument('--db', default=None)
    parser.add_argument('--ota-input', default=None)
    parser.add_argument('--costcore-bin', default=None)
    parser.add_argument('--expected-binary-sha256', default=None)
    parser.add_argument('--repo-root', default=None)
    args = parser.parse_args(argv)
    result = check(args.host_root, args.db, args.ota_input, args.costcore_bin, args.expected_binary_sha256,
                   args.repo_root)
    print(json.dumps(result, sort_keys=True, ensure_ascii=False))
    return 0 if result.get('status') == 'READY' else 1


if __name__ == '__main__':
    raise SystemExit(main())
