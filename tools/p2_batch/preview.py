"""Read-only preview for normalized stage-2 proposals."""
from __future__ import annotations

import argparse
from collections import Counter
import json
from pathlib import Path
import sqlite3

from app import classification_correction


def run(db, archive):
    root = Path(archive).resolve()
    proposals = [json.loads(line) for line in (root / 'normalized-proposals.jsonl').read_text(encoding='utf-8').splitlines() if line.strip()]
    before = json.loads((root / 'before-state.json').read_text(encoding='utf-8'))
    conn = sqlite3.connect(Path(db).resolve().as_uri() + '?mode=ro', uri=True)
    conn.row_factory = sqlite3.Row
    trips = []
    for row in conn.execute('SELECT * FROM trip_tabs'):
        trip = dict(row); trip['trip_id'] = trip['tab_id']; trips.append(trip)
    results, reasons = [], Counter()
    for proposal in proposals:
        if proposal['item'] == '기존 항목 유지':
            continue
        for old in before.get(proposal['merchant_id'], []):
            if old['item'] == proposal['item']:
                continue
            correction = dict(transaction_id=old['transaction_id'], source_hash=old['source_hash'],
                              revision=old['revision'], trip_id=old['trip_id'] or old['display_tab_id'],
                              item=proposal['item'], basis=proposal['basis'],
                              classification_source='ai_inference', execution=proposal['execution'])
            try:
                preview = classification_correction.preview(conn, [correction], trips)
            except ValueError as exc:
                reason = str(exc); reasons[reason] += 1
                results.append(dict(transaction_id=old['transaction_id'], merchant_id=proposal['merchant_id'],
                                    status='excluded', reason=reason, before_item=old['item'], after_item=proposal['item']))
            else:
                target = preview['targets'][0]
                results.append(dict(transaction_id=old['transaction_id'], merchant_id=proposal['merchant_id'],
                                    status='pass', before_item=old['item'], after_item=proposal['item'],
                                    recorded_ledger=bool(target['ledger']), screen_row=bool(target['board'])))
    conn.close()
    report = dict(candidates=len(results), passed=sum(r['status'] == 'pass' for r in results),
                  excluded=sum(r['status'] == 'excluded' for r in results), excluded_by_reason=dict(reasons),
                  recorded_ledger_targets=sum(r.get('recorded_ledger', False) for r in results),
                  screen_targets=sum(r.get('screen_row', False) for r in results), rows=results)
    (root / 'stage2-preview.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    return report


def main():
    parser = argparse.ArgumentParser(); parser.add_argument('--db', required=True); parser.add_argument('--archive', required=True)
    args = parser.parse_args(); report = run(args.db, args.archive)
    print(json.dumps({k: v for k, v in report.items() if k != 'rows'}, ensure_ascii=False))


if __name__ == '__main__':
    main()
