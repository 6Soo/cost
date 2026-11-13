"""Build a throw-away board database from a synthetic scenario (never a real database)."""
from __future__ import annotations

import json
import os
import tempfile
from contextlib import contextmanager
from pathlib import Path

TXN_DEFAULTS = {
    'source_hash': '', 'batch_id': 'syn-batch', 'issuer': 'SYN-BANK', 'card_tail': '0001',
    'card_kind': 'credit', 'transaction_direction': 'purchase', 'transaction_kind': '승인',
    'approval_number': '', 'original_approval_number': '', 'approval_date': '', 'posting_date': '',
    'merchant': '', 'merchant_normalized': '', 'amount_krw': None, 'foreign_amount': '',
    'foreign_currency': '', 'description_raw': '', 'raw_row_json': '{}', 'duplicate_of': None,
    'conflict_reason': '', 'parse_error': '', 'classification_state': 'needs_review',
    'classification_source': '', 'classification_basis': '', 'item': '', 'description': '',
    'display_tab_id': '', 'trip_id': '', 'revision': 1, 'decided_at': None,
    'created_at': '2026-01-01T00:00:00Z',
}


def _insert(conn, table, row):
    cols = list(row)
    conn.execute(f'INSERT INTO {table}({",".join(cols)}) VALUES ({",".join("?" * len(cols))})',
                 [row[c] for c in cols])


def _transaction(index, spec):
    row = dict(TXN_DEFAULTS, row_index=index + 1)
    row.update(spec)
    if not row['source_hash']:
        row['source_hash'] = 'syn-hash-' + row['transaction_id']
    if not row['merchant_normalized']:
        row['merchant_normalized'] = str(row['merchant']).lower()
    return row


@contextmanager
def scenario_db(scenario):
    """Yield the path of a temporary board DB holding the scenario; removed afterwards."""
    from webapp.card_flow import CardFlow
    from webapp.ledger_store import LedgerStore
    saved = {k: os.environ.get(k) for k in ('WEBLEDGER_UNIFIED_DB', 'WEBLEDGER_REVIEW_FROM')}
    os.environ['WEBLEDGER_UNIFIED_DB'] = '1'
    os.environ['WEBLEDGER_REVIEW_FROM'] = ''
    with tempfile.TemporaryDirectory(prefix='core-bridge-') as folder:
        path = Path(folder) / 'synthetic.sqlite'
        store = LedgerStore(path, seed_demo=False)
        CardFlow(store)  # creates the card tables
        try:
            conn = store.conn
            for index, spec in enumerate(scenario.get('rows', [])):
                _insert(conn, 'transactions', _transaction(index, spec))
            for hold in scenario.get('holds', []):
                _insert(conn, 'transaction_review_holds', {
                    'kind': 'user_hold', 'reason': 'synthetic', 'source_hash': 'syn-hash-' + hold['transaction_id'], **hold})
            for item in scenario.get('exclusions', []):
                tid = item['transaction_id']
                conn.execute('INSERT INTO transaction_company_exclusions(transaction_id,source_hash,excluded,revision,note,updated_at) '
                             'VALUES (?,?,1,1,?,?)', (tid, 'syn-hash-' + tid, 'synthetic', '2026-01-02T00:00:00Z'))
            for decision in scenario.get('decisions', []):
                _insert(conn, 'review_decisions', {
                    'revision': 1, 'item': '', 'description': '', 'display_tab_id': '', 'note': '', 'reuse_rule': 0,
                    'decided_at': '2026-01-02T00:00:00Z', **decision})
            for tid in scenario.get('overrides', []):
                conn.execute('INSERT INTO board_manual_overrides(row_id,field,event_id) VALUES (?,?,?)',
                             ('card-' + tid, 'item', 'syn-event'))
            for entry in scenario.get('ledger', []):
                _insert(conn, 'ledger_entries', {
                    'batch_id': 'syn-batch', 'description': '', 'trip_id': '', 'amount_krw': None, 'merchant': '',
                    'occurred_on': '', 'transaction_direction': 'purchase', 'source_hash': '',
                    'committed_at': '2026-01-02T00:00:00Z', **entry})
            for board in scenario.get('boards', []):
                payload = json.dumps(board['payload'], ensure_ascii=False, sort_keys=True)
                conn.execute("INSERT INTO board_rows(row_id,row_kind,display_tab_id,revision,payload_json) VALUES (?,?,?,1,?)",
                             ('card-' + board['transaction_id'], 'expense', board.get('display_tab_id', ''), payload))
            conn.commit()
        finally:
            store.close()
            for key, value in saved.items():
                if value is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = value
        yield path
