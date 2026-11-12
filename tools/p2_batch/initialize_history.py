"""Initialize the private journal from retained proposals or a verified legacy snapshot."""
import argparse
import json
import hashlib
from pathlib import Path
import subprocess

from . import layer1
from .run_incremental import PRIVATE, DEFAULT_STATE, digest


def initialize(state, *, proposals=None, legacy_snapshot=None, legacy_summary=None):
    path = Path(state).resolve()
    if not path.is_relative_to(PRIVATE.resolve()) or path.exists():
        raise ValueError('NEW_PRIVATE_STATE_REQUIRED')
    if proposals:
        source = Path(proposals).read_bytes()
        rows = [json.loads(line) for line in source.decode('utf-8').splitlines() if line.strip()]
        if not rows:
            raise ValueError('EMPTY_HISTORY')
        mids = sorted({r['merchant_id'] for r in rows})
        evidence = dict(kind='retained_proposals', path=str(Path(proposals).resolve()), sha256=hashlib.sha256(source).hexdigest())
    else:
        # This is the actual pre-run selector, not today's PROC-072 selector.
        # Only restore identities when ALL retained pre-run aggregates match.
        sha = 'd2a0c4428c7e0e56a320e7c0f15c639490c6d47c'
        source = subprocess.check_output(['git', 'show', sha+':tools/p2_batch/scope.py'], cwd=layer1.ROOT).decode('utf-8')
        namespace = {'__name__': 'verified_legacy_scope'}
        exec(compile(source, '<verified legacy scope>', 'exec'), namespace)
        report, _, _, general = namespace['select'](namespace['read_projection'](legacy_snapshot))
        summary = json.loads(Path(legacy_summary).read_text(encoding='utf-8'))
        if (report['general_merchants'] != summary['merchants'] or report['general_rows'] != summary['rows']
                or summary['merchants'] != 585 or summary['rows'] != 1258 or summary['successful_calls'] != 13):
            raise ValueError('LEGACY_SCOPE_AGGREGATES_DIFFER')
        inputs, _ = layer1.merchants(general)
        mids = sorted(r['merchant_id'] for r in inputs)
        evidence = dict(kind='reconstructed_legacy_scope', selector_sha=sha, snapshot=str(Path(legacy_snapshot).resolve()),
                        summary=str(Path(legacy_summary).resolve()), summary_digest=digest(summary),
                        merchants=len(mids), rows=len(general), limitation='identities reconstructed from pre-run snapshot; original proposal files removed')
    path.parent.mkdir(parents=True, exist_ok=True)
    # Exclusive creation prevents a second initializer replacing a live journal.
    with path.open('x', encoding='utf-8') as stream:
        json.dump(dict(version=1, history_merchants=mids, history_evidence=evidence, jobs=[], runs=[]), stream, ensure_ascii=False, indent=2)
    return len(mids)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--state', default=str(DEFAULT_STATE))
    choice = parser.add_mutually_exclusive_group(required=True)
    choice.add_argument('--proposals')
    choice.add_argument('--legacy-snapshot')
    parser.add_argument('--legacy-summary')
    args = parser.parse_args()
    if args.legacy_snapshot and not args.legacy_summary:
        parser.error('--legacy-summary is required with --legacy-snapshot')
    print(json.dumps({'history_merchants': initialize(args.state, proposals=args.proposals,
        legacy_snapshot=args.legacy_snapshot, legacy_summary=args.legacy_summary)}))


if __name__ == '__main__':
    main()
