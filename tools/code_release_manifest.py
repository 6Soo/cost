"""Preview or build a new code-only ZIP; preserve every repository original.

This is a distribution boundary, not secret scanning or runtime acceptance.
Historical outputs, original data, private host configuration, tests and unknown
file types never enter this package. Dynamic runtime dependencies remain subject
to review before an operator can use a package for deployment.
"""
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import subprocess
import zipfile

try:
    from tools.check_tracked_data import git, load_policy, preserved_entries, reasons, tree
except ModuleNotFoundError:
    from check_tracked_data import git, load_policy, preserved_entries, reasons, tree

ROOT = Path(__file__).resolve().parents[1]
CONFIG = {'config/guide-airfare-airports.json', 'config/ota-matching-defaults.json',
          'config/refund-pairing.json'}
ASSET_SUFFIXES = {'.css', '.js', '.html', '.svg', '.woff', '.woff2', '.txt', '.png', '.ico', '.webp', '.jpg', '.jpeg'}
# This existing runtime font is accompanied by static/fonts/OFL.txt. A changed
# blob must be reviewed explicitly; size/extension alone never clear large data.
LICENSED_LARGE_ASSETS = {'webapp/static/fonts/PretendardVariable.woff2':
                         ('49c54b5152a184a243e85f7281ed338b6569987e', 2057688)}


def permitted(path):
    item = PurePosixPath(path)
    if item.is_absolute() or '..' in item.parts or '\\' in path:
        return False
    if path in CONFIG or path in {'requirements.txt', 'run_candidate.py'}:
        return True
    if any(part in {'tests', 'fixtures', '__pycache__'} for part in item.parts):
        return False
    if path.startswith('webapp/static/'):
        return item.suffix.lower() in ASSET_SUFFIXES
    return (path.startswith(('app/', 'webapp/', 'ledger/')) and item.suffix == '.py'
            or path.startswith('tools/') and item.suffix in {'.py', '.ps1'})


def manifest(root, sha):
    if not re.fullmatch('[0-9a-f]{40}', sha):
        raise ValueError('EXACT_SHA_REQUIRED')
    policy = load_policy(root / 'config/tracked-data-policy.json')
    preserved = preserved_entries(policy)
    included, excluded = [], []
    for path, info in tree(root, sha).items():
        risk = reasons(path, info, policy)
        if LICENSED_LARGE_ASSETS.get(path) == (info['oid'], info['size']):
            risk = [reason for reason in risk if reason != 'LARGE_BLOB']
        if info['kind'] != 'blob':
            risk.append('NON_BLOB')
        if not permitted(path):
            risk.append('OUTSIDE_CODE_ALLOWLIST')
        if risk:
            # Older SHAs still carry blobs that now live in the external archive.
            outside = preserved.get(path, {}).get('git_blob') == info['oid']
            excluded.append({'path': path, 'reasons': list(dict.fromkeys(risk)),
                             'retention': 'PRESERVED_OUTSIDE_GIT' if outside
                             else 'PRESERVE_IN_ORIGINAL_REPOSITORY'})
        else:
            included.append({'path': path, 'blob': info['oid'], 'bytes': info['size']})
    return {'schema': 'cost-code-release-v1', 'sha': sha, 'included': included, 'excluded': excluded,
            'runtime_accepted': False, 'secret_scan_performed': False,
            'originals_modified': False}


def package(root, report, output):
    # Exclusive creation preserves user files even on partial-build failures.
    with Path(output).open('xb') as stream, zipfile.ZipFile(stream, 'w', compression=zipfile.ZIP_DEFLATED) as archive:
        for entry in report['included']:
            data = git(root, 'show', report['sha'] + ':' + entry['path'])
            digest = hashlib.sha1(b'blob ' + str(len(data)).encode() + b'\0' + data).hexdigest()
            if digest != entry['blob'] or len(data) != entry['bytes']:
                raise ValueError('GIT_BLOB_MISMATCH')
            archive.writestr(entry['path'], data)
        # Excluded paths may themselves be private. Publish only their count.
        archive.writestr('CODE_RELEASE.json', json.dumps({
            key: report[key] for key in ('schema', 'sha', 'included', 'runtime_accepted',
                                         'secret_scan_performed', 'originals_modified')
        } | {'excluded_count': len(report['excluded'])}, sort_keys=True))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=ROOT)
    parser.add_argument('--sha', required=True)
    parser.add_argument('--output', type=Path, help='explicit opt-in build at a new ZIP path')
    args = parser.parse_args(argv)
    try:
        root = args.root.resolve(strict=True)
        report = manifest(root, args.sha)
        if args.output is not None:
            package(root, report, args.output)
    except (OSError, ValueError, subprocess.CalledProcessError, zipfile.BadZipFile):
        print(json.dumps({'status': 'FAILED', 'code': 'CODE_PACKAGE_UNVERIFIED'}))
        return 2
    print(json.dumps({'status': 'BUILT_NOT_RUNTIME_ACCEPTED' if args.output is not None else 'PREVIEW',
                      'sha': report['sha'], 'included': len(report['included']),
                      'excluded': len(report['excluded']),
                      'excluded_reasons': dict(Counter(reason for entry in report['excluded'] for reason in entry['reasons'])),
                      'originals_modified': False, 'secret_scan_performed': False,
                      'runtime_accepted': False}))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
