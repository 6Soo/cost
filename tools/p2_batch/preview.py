"""Read-only preview for normalized stage-2 proposals."""
from __future__ import annotations

import argparse
from collections import Counter
import json
from pathlib import Path
import sqlite3
import hashlib

from app import classification_correction
from .scope import projection_disagreements


def _immutable_digest(target):
    before = target['before']
    values = {
        'transaction_id': before.get('transaction_id'), 'source_hash': before.get('source_hash'),
        'amount_krw': before.get('amount_krw'), 'foreign_amount': before.get('foreign_amount'),
        'foreign_currency': before.get('foreign_currency'), 'trip_id': before.get('trip_id'),
        'display_tab_id': before.get('display_tab_id'), 'raw_row_json': before.get('raw_row_json'),
    }
    return hashlib.sha256(json.dumps(values, ensure_ascii=False, sort_keys=True, default=str).encode()).hexdigest()


def _check_projection_invariants(target):
    before = target['before']
    ledger, board = target['ledger'], target['board']
    if bool(ledger) != bool(board):
        raise ValueError('P2_PROJECTION_SHAPE')
    if ledger:
        for key in ('transaction_id', 'amount_krw', 'trip_id', 'display_tab_id'):
            if key in ledger and key in before and ledger[key] != before[key]:
                raise ValueError('P2_IMMUTABLE_CHANGED')
    if board:
        payload = json.loads(board['payload_json'])
        for key in ('source_event_id', 'amount_krw', 'trip_id', 'display_tab_id'):
            expected = before.get('transaction_id') if key == 'source_event_id' else before.get(key)
            if key in payload and expected is not None and payload[key] != expected:
                raise ValueError('P2_IMMUTABLE_CHANGED')
    return dict(projection_pair=bool(ledger and board), immutable_digest=_immutable_digest(target))


def run(db, archive):
    root = Path(archive).resolve()
    proposals = [json.loads(line) for line in (root / 'normalized-proposals.jsonl').read_text(encoding='utf-8').splitlines() if line.strip()]
    before = json.loads((root / 'before-state.json').read_text(encoding='utf-8'))
    conn = sqlite3.connect(Path(db).resolve().as_uri() + '?mode=ro', uri=True)
    conn.row_factory = sqlite3.Row
    disagreements = projection_disagreements({
        'transactions': [dict(r) for r in conn.execute('SELECT transaction_id,trip_id,display_tab_id FROM transactions')],
        'ledger_entries': [dict(r) for r in conn.execute('SELECT transaction_id,trip_id,display_tab_id FROM ledger_entries')],
    })
    trips = []
    for row in conn.execute('SELECT * FROM trip_tabs'):
        trip = dict(row); trip['trip_id'] = trip['tab_id']; trips.append(trip)
    from tools.complete_card_classification import load_completed_period_evidence
    host = Path(db).resolve().parent.parent
    evidence = (load_completed_period_evidence(conn,host,trips)
                if (host/'config/card-flow.json').is_file() else {})
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
                if old['transaction_id'] in disagreements:
                    raise ValueError('PROJECTION_ATTRIBUTION_DISAGREEMENT')
                preview = classification_correction.preview(conn, [correction], trips,completed_evidence=evidence)
            except ValueError as exc:
                reason = str(exc); reasons[reason] += 1
                results.append(dict(transaction_id=old['transaction_id'], merchant_id=proposal['merchant_id'],
                                    status='excluded', reason=reason, before_item=old['item'], after_item=proposal['item']))
            else:
                target = preview['targets'][0]
                invariants = _check_projection_invariants(target)
                results.append(dict(transaction_id=old['transaction_id'], merchant_id=proposal['merchant_id'],
                                    status='pass', before_item=old['item'], after_item=proposal['item'],
                                    recorded_ledger=bool(target['ledger']), screen_row=bool(target['board']),
                                    **invariants))
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
