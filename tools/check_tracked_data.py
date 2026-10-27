"""RF-003 metadata-only inventory/preflight; never read tracked file contents.

Sensitivity stays UNASSESSED. Path/format/size checks cannot detect secrets
embedded in source. This command never deletes data or rewrites Git history.
"""
from __future__ import annotations
import argparse
from collections import Counter
import fnmatch
import json
from pathlib import Path, PurePosixPath
import subprocess

ROOT = Path(__file__).resolve().parents[1]
POLICY = ROOT / 'config' / 'tracked-data-policy.json'


def git(root, *args):
    return subprocess.run(['git', '-C', str(root), *args], check=True,
                          stdout=subprocess.PIPE, stderr=subprocess.PIPE).stdout


def tree(root, revision):
    entries = {}
    for record in git(root, 'ls-tree', '-r', '-z', '-l', revision).split(b'\0'):
        if not record:
            continue
        meta, path = record.split(b'\t', 1)
        mode, kind, oid, size = meta.split()
        entries[path.decode('utf-8')] = {'oid': oid.decode(), 'size': int(size) if size != b'-' else 0,
                                       'mode': mode.decode(), 'kind': kind.decode()}
    return entries


def index(root):
    entries = {}
    for record in git(root, 'ls-files', '--stage', '-z').split(b'\0'):
        if not record:
            continue
        meta, path = record.split(b'\t', 1)
        mode, oid, stage = meta.split()
        if stage != b'0':
            raise ValueError('UNMERGED_INDEX')
        kind = 'commit' if mode == b'160000' else 'blob'
        entries[path.decode('utf-8')] = {'oid': oid.decode(), 'size': 0, 'mode': mode.decode(), 'kind': kind}
    blobs = [info for info in entries.values() if info['kind'] == 'blob']
    if blobs:
        sizes = subprocess.run(['git', '-C', str(root), 'cat-file', '--batch-check=%(objectsize)'],
                               input=''.join(info['oid'] + '\n' for info in blobs).encode('ascii'),
                               check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE).stdout.splitlines()
        if len(sizes) != len(blobs):
            raise ValueError('INVALID_OBJECT_METADATA')
        for info, size in zip(blobs, sizes):
            info['size'] = int(size)
    return entries


def load_policy(path=POLICY):
    value = json.loads(Path(path).read_text(encoding='utf-8'))
    if not isinstance(value, dict):
        raise ValueError('INVALID_POLICY')
    required = ('protected_prefixes', 'denied_names', 'data_extensions', 'synthetic_allowlist')
    if value.get('schema_version') != 1 or any(
        not isinstance(value.get(key), list) or any(not isinstance(x, str) for x in value[key])
        for key in required
    ) or type(value.get('max_blob_bytes')) is not int or value['max_blob_bytes'] < 1:
        raise ValueError('INVALID_POLICY')
    for entry in value['synthetic_allowlist']:
        if not entry.startswith('tests/fixtures/') or '..' in PurePosixPath(entry).parts or any(c in entry for c in '*?['):
            raise ValueError('INVALID_SYNTHETIC_ALLOWLIST')
    return value


def reasons(path, info, policy):
    normalized = path.replace('\\', '/').lower()
    name = PurePosixPath(normalized).name
    result = []
    if any(normalized.startswith(prefix.lower()) for prefix in policy['protected_prefixes']):
        result.append('PROTECTED_PATH')
    if any(fnmatch.fnmatchcase(name, pattern.lower()) for pattern in policy['denied_names']):
        result.append('SECRET_FILENAME')
    if info['mode'] in ('120000', '160000'):
        result.append('INDIRECT_OBJECT')
    if info['size'] > policy['max_blob_bytes']:
        result.append('LARGE_BLOB')
    if PurePosixPath(normalized).suffix in policy['data_extensions'] and path not in policy['synthetic_allowlist']:
        result.append('DATA_FORMAT')
    return result


def inspect(root=ROOT, *, mode='staged', base='HEAD', policy_path=POLICY):
    if mode not in ('inventory', 'staged', 'base'):
        raise ValueError('INVALID_MODE')
    policy = load_policy(policy_path)
    baseline = tree(root, base)
    current = baseline if mode == 'inventory' else index(root) if mode == 'staged' else tree(root, 'HEAD')
    protected_oids = {info['oid'] for path, info in baseline.items() if reasons(path, info, policy)}
    files = []
    for path, info in sorted(current.items()):
        previous = baseline.get(path)
        unchanged = previous is not None and info == previous
        if mode != 'inventory' and unchanged:
            continue
        markers = reasons(path, info, policy)
        if not unchanged and info['oid'] in protected_oids and previous is None:
            markers.append('REUSED_PROTECTED_OBJECT')
        files.append({'path': path, 'size': info['size'],
                      'status': 'UNCHANGED' if unchanged else 'MODIFIED' if previous else 'ADDED',
                      'sensitivity': 'UNASSESSED', 'risk_markers': markers,
                      'blocked': mode != 'inventory' and bool(markers),
                      'producer': 'UNKNOWN', 'consumer': 'UNKNOWN', 'active_use': 'UNVERIFIED'})
    deleted_paths = sorted(set(baseline) - set(current))
    for path in deleted_paths:
        info = baseline[path]
        markers = reasons(path, info, policy)
        if markers:
            files.append({'path': path, 'size': info['size'], 'status': 'DELETED',
                          'sensitivity': 'UNASSESSED',
                          'risk_markers': ['PROTECTED_DELETION', *markers],
                          'blocked': mode != 'inventory',
                          'producer': 'UNKNOWN', 'consumer': 'UNKNOWN', 'active_use': 'UNVERIFIED'})
    return {'schema_version': 1, 'mode': mode, 'base': base, 'metadata_only': True,
            'files': files, 'blocked_count': sum(x['blocked'] for x in files),
            'deleted_count': len(deleted_paths),
            'limitations': ['No content scan or sensitivity clearance; embedded secrets require separate review.',
                            'Existing source data is preserved; this tool never deletes or rewrites history.']}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=ROOT)
    parser.add_argument('--mode', choices=('inventory', 'staged', 'base'), default='staged')
    parser.add_argument('--base', default='HEAD', help='Explicit Git baseline; base mode compares HEAD to it')
    parser.add_argument('--policy', type=Path, default=POLICY)
    parser.add_argument('--json', action='store_true')
    args = parser.parse_args(argv)
    try:
        result = inspect(args.root.resolve(), mode=args.mode, base=args.base, policy_path=args.policy)
    except (OSError, ValueError, subprocess.CalledProcessError) as exc:
        print(json.dumps({'status': 'ERROR', 'code': type(exc).__name__}))
        return 2
    if args.json:
        print(json.dumps(result, ensure_ascii=True, indent=2))
    else:
        print(json.dumps({'mode': args.mode, 'files': len(result['files']),
                          'blocked_count': result['blocked_count'], 'deleted_count': result['deleted_count'],
                          'risk_counts': dict(Counter(r for x in result['files'] for r in x['risk_markers']))}))
    return 1 if result['blocked_count'] else 0


if __name__ == '__main__':
    raise SystemExit(main())
