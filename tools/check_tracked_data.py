"""RF-003 metadata-only inventory/preflight with opt-in static source references.

Sensitivity stays UNASSESSED. Path/format/size checks cannot detect secrets
embedded in source. This command never deletes data or rewrites Git history.
Use --source-references to scan only tracked Python under app/, webapp/, tools/,
ledger/domain/, and known root launchers. It compares exact path literals with
Git metadata paths; dynamic/indirect use remains UNKNOWN and UNVERIFIED.
This is a candidate scan, not proof of active use or sensitivity safety.
"""
from __future__ import annotations
import argparse
import ast
from collections import Counter
import fnmatch
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import subprocess

ROOT = Path(__file__).resolve().parents[1]
POLICY = ROOT / 'config' / 'tracked-data-policy.json'
SOURCE_ROOTS = ('app/', 'webapp/', 'tools/', 'ledger/domain/')
ROOT_LAUNCHERS = {'run_candidate.py'}


def _source_candidates(entries):
    return [path for path, info in entries.items()
            if info['kind'] == 'blob' and path.endswith('.py')
            and (path.startswith(SOURCE_ROOTS) or path in ROOT_LAUNCHERS)]


def _path_literal(node, known):
    if isinstance(node, ast.Constant) and isinstance(node.value, str) and node.value in known:
        return node.value
    return None


def _source_references(source, source_path, known):
    tree = ast.parse(source, filename=source_path)
    results = []
    io_targets = {}

    def literal(node):
        return _path_literal(node, known)

    def add_target(node, candidate):
        target = literal(node)
        if target is not None:
            io_targets[id(node)] = (target, candidate)

    def mode_candidate(mode_node, default_read=False):
        if mode_node is None:
            return 'READ_CANDIDATE' if default_read else 'REFERENCE'
        if not isinstance(mode_node, ast.Constant) or not isinstance(mode_node.value, str):
            return 'REFERENCE'
        mode = mode_node.value
        primary = [char for char in mode if char in 'rwax']
        if len(primary) != 1 or any(char not in 'rwaxbt+' for char in mode):
            return 'REFERENCE'
        if len(set(mode)) != len(mode) or ('b' in mode and 't' in mode):
            return 'REFERENCE'
        return 'WRITE_CANDIDATE' if primary[0] in 'wax' or '+' in mode else 'READ_CANDIDATE'

    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        name = func.attr if isinstance(func, ast.Attribute) else func.id if isinstance(func, ast.Name) else ''
        if isinstance(func, ast.Name) and func.id == 'open':
            path_node = node.args[0] if node.args else next(
                (kw.value for kw in node.keywords if kw.arg == 'file'), None)
            mode_node = node.args[1] if len(node.args) > 1 else next(
                (kw.value for kw in node.keywords if kw.arg == 'mode'), None)
            add_target(path_node, mode_candidate(mode_node, default_read=mode_node is None))
        elif isinstance(func, ast.Attribute) and name in {
                'open', 'read_text', 'read_bytes', 'write_text', 'write_bytes'}:
            receiver = func.value
            receiver_path = None
            if isinstance(receiver, ast.Call) and receiver.args:
                constructor = receiver.func.id if isinstance(receiver.func, ast.Name) else ''
                if constructor in {'Path', 'PurePath', 'PurePosixPath', 'WindowsPath', 'PosixPath'}:
                    receiver_path = receiver.args[0]
            if name == 'open':
                mode_node = node.args[0] if node.args else next(
                    (kw.value for kw in node.keywords if kw.arg == 'mode'), None)
                candidate = mode_candidate(mode_node, default_read=mode_node is None)
            elif name in {'read_text', 'read_bytes'}:
                candidate = 'READ_CANDIDATE'
            else:
                candidate = 'WRITE_CANDIDATE'
            add_target(receiver_path, candidate)

    # Preserve every exact path literal. Promote only AST nodes proven to be
    # the target of a recognized file operation; content/other arguments stay REFERENCE.
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str) and node.value in known:
            target, candidate = io_targets.get(id(node), (node.value, 'REFERENCE'))
            results.append({'source_path': source_path, 'line': node.lineno,
                            'candidate': candidate, 'reason': 'EXACT_TRACKED_PATH_LITERAL',
                            '_target': target})
    return results


def _add_source_references(root, entries, files):
    """Opt-in read of approved tracked Python source only; data blobs stay unopened."""
    by_path = {item['path']: item for item in files}
    protected = {item['path'] for item in files if item['risk_markers']}
    errors = []
    candidates = _source_candidates(entries)
    reference_count = 0
    if not protected:
        return errors, 0, 0
    for source_path in candidates:
        try:
            candidate = (root / source_path).resolve(strict=True)
            candidate.relative_to(root)
            if candidate != (root / source_path).absolute():
                raise ValueError('SOURCE_INDIRECT_PATH')
            if not candidate.is_file():
                raise ValueError('SOURCE_PATH_NOT_FILE')
            text = candidate.read_text(encoding='utf-8-sig')
            refs = _source_references(text, source_path, protected)
        except (OSError, UnicodeError, ValueError, SyntaxError, RuntimeError) as exc:
            if isinstance(exc, SyntaxError):
                reason = 'SOURCE_PARSE_FAILED'
            elif isinstance(exc, UnicodeError):
                reason = 'SOURCE_READ_FAILED'
            elif isinstance(exc, (ValueError, RuntimeError)):
                reason = 'SOURCE_PATH_OUTSIDE_OR_MISSING'
            else:
                reason = 'SOURCE_READ_FAILED'
            errors.append({'path': source_path, 'reason': reason})
            continue
        for ref in refs:
            target = ref.pop('_target')
            by_path[target].setdefault('source_references', []).append(ref)
            reference_count += 1
    for item in files:
        item.setdefault('source_references', [])
    return errors, len(candidates), reference_count


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
    _validate_preserved(value)
    return value


def _hex(value, length):
    return isinstance(value, str) and re.fullmatch(f'[0-9a-f]{{{length}}}', value) is not None


def _validate_preserved(policy):
    """Exact path+hash entries copied out of Git; never a prefix or wildcard."""
    batches = policy.get('externally_preserved', [])
    if not isinstance(batches, list):
        raise ValueError('INVALID_EXTERNALLY_PRESERVED')
    seen = set()
    for batch in batches:
        if (not isinstance(batch, dict) or set(batch) != {'archive', 'manifest_sha256', 'files'}
                or not isinstance(batch['archive'], str) or not batch['archive'].strip()
                or not _hex(batch['manifest_sha256'], 64)
                or not isinstance(batch['files'], list) or not batch['files']):
            raise ValueError('INVALID_EXTERNALLY_PRESERVED')
        for entry in batch['files']:
            if not isinstance(entry, dict) or set(entry) != {'path', 'sha256', 'git_blob'}:
                raise ValueError('INVALID_EXTERNALLY_PRESERVED')
            path = entry['path']
            if (not isinstance(path, str)
                    or '\\' in path or '..' in PurePosixPath(path).parts or any(c in path for c in '*?[')
                    or not any(path.lower().startswith(p.lower()) for p in policy['protected_prefixes'])
                    or not _hex(entry['sha256'], 64) or not _hex(entry['git_blob'], 40) or path in seen):
                raise ValueError('INVALID_EXTERNALLY_PRESERVED')
            seen.add(path)


def preserved_entries(policy):
    return {entry['path']: entry for batch in policy.get('externally_preserved', [])
            for entry in batch['files']}


def externally_preserved(root, path, info, preserved):
    """Only the exact recorded blob may leave Git; content hash is rechecked from the baseline."""
    entry = preserved.get(path)
    if entry is None or info['kind'] != 'blob' or info['oid'] != entry['git_blob']:
        return False
    return hashlib.sha256(git(root, 'cat-file', 'blob', info['oid'])).hexdigest() == entry['sha256']


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


def inspect(root=ROOT, *, mode='staged', base='HEAD', policy_path=POLICY, source_references=False):
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
    preserved = preserved_entries(policy)
    for path in deleted_paths:
        info = baseline[path]
        markers = reasons(path, info, policy)
        if markers:
            cleared = externally_preserved(root, path, info, preserved)
            files.append({'path': path, 'size': info['size'], 'status': 'DELETED',
                          'sensitivity': 'UNASSESSED',
                          'risk_markers': ['EXTERNALLY_PRESERVED_UNTRACK' if cleared else 'PROTECTED_DELETION',
                                           *markers],
                          'blocked': mode != 'inventory' and not cleared,
                          'producer': 'UNKNOWN', 'consumer': 'UNKNOWN', 'active_use': 'UNVERIFIED'})
    source_errors, source_scanned, source_reference_count = (
        _add_source_references(root, index(root), files) if source_references else ([], 0, 0)
    )
    source_scan_fields = ({
        'source_references_enabled': True,
        'source_scan_count': source_scanned,
        'source_reference_count': source_reference_count,
        'errors': source_errors,
        'source_reference_provenance': {
            'path_metadata': 'Git index',
            'source_text': 'working tree',
        },
    } if source_references else {})
    return {'schema_version': 1, 'mode': mode, 'base': base, 'metadata_only': not source_references,
            **source_scan_fields,
            'files': files, 'blocked_count': sum(x['blocked'] for x in files),
            'deleted_count': len(deleted_paths),
            'limitations': ['No content scan or sensitivity clearance; embedded secrets require separate review.',
                            'Exact static literals only; dynamic paths and indirect consumers remain UNKNOWN and UNVERIFIED.',
                            'Source references read working-tree text while path metadata comes from the Git index; they are not a same-revision comparison.',
                            'Existing source data is preserved; this tool never deletes or rewrites history.']}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=ROOT)
    parser.add_argument('--mode', choices=('inventory', 'staged', 'base'), default='staged')
    parser.add_argument('--base', default='HEAD', help='Explicit Git baseline; base mode compares HEAD to it')
    parser.add_argument('--policy', type=Path, default=POLICY)
    parser.add_argument('--json', action='store_true')
    parser.add_argument('--source-references', action='store_true',
                        help='opt in to exact data-path literal candidates in approved tracked Python source; dynamic use remains unverified')
    args = parser.parse_args(argv)
    try:
        result = inspect(args.root.resolve(), mode=args.mode, base=args.base, policy_path=args.policy,
                         source_references=args.source_references)
    except (OSError, ValueError, subprocess.CalledProcessError) as exc:
        print(json.dumps({'status': 'ERROR', 'code': type(exc).__name__}))
        return 2
    if args.json:
        print(json.dumps(result, ensure_ascii=True, indent=2))
    else:
        summary = {'mode': args.mode, 'files': len(result['files']),
                   'blocked_count': result['blocked_count'], 'deleted_count': result['deleted_count'],
                   'risk_counts': dict(Counter(r for x in result['files'] for r in x['risk_markers']))}
        if args.source_references:
            summary.update({'source_scan_count': result['source_scan_count'],
                            'source_reference_count': result['source_reference_count'],
                            'source_error_count': len(result['errors'])})
        print(json.dumps(summary))
    return 2 if result.get('errors') else 1 if result['blocked_count'] else 0


if __name__ == '__main__':
    raise SystemExit(main())
