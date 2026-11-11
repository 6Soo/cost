"""Read operating data briefly; rehearse rule promotion only in memory."""
from collections import Counter, defaultdict
import hashlib
import json
from pathlib import Path
import sqlite3
import time

from app.db import Store
from app import rules, classify
from app.normalize import normalize_merchant as exact_merchant
from tools.p2_batch.layer1 import canonical_merchant_name
from tools.p2_batch.scope import MANUAL, tab
from .merchant_table import build_rule_table, normalize_merchant, to_jsonl


def read_memory(db):
    started = time.monotonic()
    live = sqlite3.connect(Path(db).resolve().as_uri() + '?mode=ro', uri=True, timeout=2)
    try:
        live.execute('PRAGMA query_only=ON')
        memory = sqlite3.connect(':memory:')
        live.backup(memory)
    finally:
        live.close()
    return memory, round(time.monotonic() - started, 3)


def rows(conn, table):
    cursor = conn.execute('SELECT * FROM "' + table + '"')
    columns = [c[0] for c in cursor.description]
    return [dict(zip(columns, row)) for row in cursor]


def build_applied_proposals(conn, applied, normalized, before):
    current = {r['transaction_id']: r for r in rows(conn, 'transactions')}
    by_merchant = {r['merchant_id']: r for r in normalized}
    inputs = []
    for mid, old in before.items():
        proposal = by_merchant[mid]
        groups = defaultdict(list)
        for original in old:
            tid = original['transaction_id']
            if tid not in applied:
                continue
            row = current[tid]
            if row['item'] != proposal['item'] or row['classification_source'] != 'ai_inference':
                raise ValueError('APPLIED_PROPOSAL_STALE')
            groups[row['merchant_normalized']].append(row)
        for merchant, values in groups.items():
            inputs.append(dict(merchant=merchant, item=proposal['item'], confidence=proposal['confidence'],
                               rows=len(values), basis=proposal['basis'], run_id=proposal['execution']['run_id']))
    if sum(p['rows'] for p in inputs) != len(applied):
        raise ValueError('APPLIED_PROPOSAL_COVERAGE')
    return inputs


def make_drafts(table):
    drafts = []
    for row in table['rules']:
        draft = rules.normalize_rule(dict(
            conditions=dict(merchant_normalized=row['merchant_key'], transaction_direction='purchase'),
            effects=dict(item=row['item']), optional={},
            origin='p2-layer1:' + ','.join(row['run_ids']),
            note=json.dumps(dict(basis=row['basis'], run_ids=row['run_ids']), ensure_ascii=False)))
        assert set(draft['effects']) == {'item'}
        drafts.append(draft)
    return drafts


def state(conn):
    return {table: rows(conn, table) for table in ('transactions', 'ledger_entries', 'board_rows')}


def difference(before, after, trips, applied):
    old = {r['transaction_id']: r for r in before['transactions']}
    new = {r['transaction_id']: r for r in after['transactions']}
    closed = {r['tab_id'] for r in trips if r['starts_on'] < '2026-06-30'}
    recorded = {r['transaction_id'] for r in before['ledger_entries']}
    changed = {tid for tid in old if old[tid] != new[tid]}
    manual = {tid for tid in changed if old[tid]['classification_source'] in MANUAL or old[tid]['decided_at'] is not None}
    recorded_changed = changed & recorded
    closed_changed = {tid for tid in changed if tab(old[tid]) in closed or (
        str(tab(old[tid])).startswith('quarter:') and str(tab(old[tid])) < 'quarter:2026:3')}
    attribution = {tid for tid in changed if any(old[tid][k] != new[tid][k] for k in ('trip_id', 'display_tab_id'))}
    new_affected = changed - set(applied)
    distribution = Counter((old[tid]['approval_date'] or old[tid]['posting_date'] or 'unknown')[:7] for tid in new_affected)
    return dict(changed=len(changed), a_item_changed=sum(old[tid]['item'] != new[tid]['item'] for tid in applied),
                b_manual_changed=len(manual), b_recorded_changed=len(recorded_changed),
                b_closed_changed=len(closed_changed), b_attribution_changed=len(attribution),
                b_any=len(manual | recorded_changed | closed_changed | attribution),
                c_new_affected=len(new_affected), c_periods=dict(sorted(distribution.items())))


def run(db, archive, applied_archive, output):
    root = Path(output).resolve()
    if not root.is_relative_to(Path(__file__).resolve().parents[2] / '.local-archive'):
        raise ValueError('PRIVATE_OUTPUT_REQUIRED')
    root.mkdir(parents=True, exist_ok=True)
    read = lambda p: json.loads(p.read_text(encoding='utf-8'))
    applied = set(read(Path(applied_archive) / 'target-before.json')['targets'])
    original = read(Path(archive) / 'before-state.json')
    proposals = [json.loads(s) for s in (Path(archive) / 'normalized-proposals.jsonl').read_text(encoding='utf-8').splitlines() if s.strip()]
    conn, seconds = read_memory(db)
    inputs = build_applied_proposals(conn, applied, proposals, original)
    table = build_rule_table(inputs, normalizer=exact_merchant)
    drafts = make_drafts(table)
    merchant_inputs = read(Path(archive) / 'merchant-inputs.json')
    names = [r['normalized'] for r in merchant_inputs]
    comparison = dict(compared=len(names), equal=sum(canonical_merchant_name(n) == normalize_merchant(n).casefold() for n in names),
                      chosen='app.normalize.normalize_merchant: exact stored merchant; no city/country stripping')
    (root / 'rule-table.json').write_text(json.dumps(table, ensure_ascii=False, indent=2), encoding='utf-8')
    (root / 'rule-drafts.jsonl').write_text(to_jsonl(drafts), encoding='utf-8')
    before = state(conn); trips = rows(conn, 'trip_tabs')
    # Compare the current rule set with the current rule set plus the proposed
    # rules.  Running the classifier with its implicit rule lookup would make
    # the rehearsal report unrelated historical reclassification as a rule
    # promotion side effect.
    existing_rules = rules.list_rules(Store(conn, schema_policy='require'))
    batches = [r[0] for r in conn.execute('SELECT batch_id FROM import_batches ORDER BY batch_id')]
    results = []
    for name in ('baseline', 'with_rules'):
        trial = sqlite3.connect(':memory:'); conn.backup(trial)
        store = Store(trial, schema_policy='require')
        active_rules = existing_rules
        if name == 'with_rules':
            saved = [rules.save_rule(store, draft) for draft in drafts]
            (root / 'simulated-rule-audit.json').write_text(json.dumps(saved, ensure_ascii=False, indent=2), encoding='utf-8')
            active_rules = existing_rules + drafts
        for batch in batches:
            classify.classify_batch(store, batch, rules=active_rules)
        trial.commit()
        after = state(trial)
        results.append((name, after, difference(before, after, trips, applied)))
        trial.close()
    rule_only = difference(results[0][1], results[1][1], trips, applied)
    base_rows = {r['transaction_id']: r for r in results[0][1]['transactions']}
    rule_rows = {r['transaction_id']: r for r in results[1][1]['transactions']}
    incremental_attribution = []
    for tid in sorted(base_rows):
        before_row, after_row = base_rows[tid], rule_rows[tid]
        if before_row == after_row:
            continue
        if any(before_row[k] != after_row[k] for k in ('trip_id', 'display_tab_id')):
            incremental_attribution.append({
                'transaction_id_sha256': hashlib.sha256(tid.encode()).hexdigest(),
                'merchant_normalized': after_row.get('merchant_normalized'),
                'item_before': before_row.get('item'), 'item_after': after_row.get('item'),
                'trip_before': before_row.get('trip_id'), 'trip_after': after_row.get('trip_id'),
                'display_tab_before': before_row.get('display_tab_id'),
                'display_tab_after': after_row.get('display_tab_id'),
            })
    report = dict(rule_count=len(drafts), rows=sum(r['rows'] for r in table['rules']), conflicts=table['stats']['conflicts'],
                  normalization=comparison, read_seconds=seconds, baseline=results[0][2],
                  with_rules=results[1][2], incremental=rule_only,
                  incremental_attribution=incremental_attribution,
                  status='PASS' if rule_only['b_any'] == 0 and rule_only['a_item_changed'] == 0 else 'STOP',
                  operating_writes=0)
    (root / 'rule-rehearsal-summary.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(report, ensure_ascii=False), flush=True)
    conn.close()
    return report


if __name__ == '__main__':
    import argparse
    p=argparse.ArgumentParser();p.add_argument('--db',required=True);p.add_argument('--archive',required=True)
    p.add_argument('--applied-archive',required=True);p.add_argument('--output',required=True)
    args=p.parse_args();run(args.db,args.archive,args.applied_archive,args.output)
