"""Deterministically normalize completed stage-1 proposals."""
from __future__ import annotations

import argparse
from collections import Counter
import json
from pathlib import Path
import sqlite3

from .layer1 import KEEP, normalize_results


def operational_items(db):
    with sqlite3.connect(Path(db).resolve().as_uri() + '?mode=ro', uri=True) as conn:
        rows = conn.execute("SELECT DISTINCT item FROM transactions WHERE approval_date >= '2026-04-01' AND COALESCE(item,'') != ''")
        return sorted({r[0] for r in rows})


def run(archive, db):
    root = Path(archive).resolve()
    inputs = json.loads((root / 'merchant-inputs.json').read_text(encoding='utf-8'))
    proposals = [json.loads(line) for line in (root / 'proposals.jsonl').read_text(encoding='utf-8').splitlines() if line.strip()]
    known = operational_items(db)
    normalized = normalize_results(inputs, proposals, known)
    (root / 'normalized-proposals.jsonl').write_text(
        ''.join(json.dumps(row, ensure_ascii=False) + '\n' for row in normalized), encoding='utf-8')
    transitions = Counter()
    changed_merchants = affected_rows = 0
    for row in normalized:
        old = Counter(row['old_items'])
        affected = sum(n for item, n in old.items() if row['item'] not in (KEEP, item))
        if affected:
            changed_merchants += 1
            affected_rows += affected
        for item, n in old.items():
            if row['item'] not in (KEEP, item):
                transitions[f'{item} → {row["item"]}'] += n
    summary = dict(merchants=len(normalized), changed_merchants=changed_merchants,
                   affected_rows=affected_rows, kept=sum(r['item'] == KEEP for r in normalized),
                   item_counts=dict(Counter(r['item'] for r in normalized)),
                   transitions=dict(transitions), operational_items=known)
    (root / 'normalized-summary.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding='utf-8')
    return summary


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--archive', required=True)
    parser.add_argument('--db', required=True)
    args = parser.parse_args()
    print(json.dumps(run(args.archive, args.db), ensure_ascii=False))


if __name__ == '__main__':
    main()
