from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.google_authority import SnapshotError
from webapp import expense_amount_group_service as service


@pytest.fixture
def context(monkeypatch):
    snapshot = {'rows_generation': 'generation-a', 'synced_at': '2026-10-30T00:00:00Z',
                'sources': {'main': {'content_sha256': 'a' * 64}}}
    private = {'main': {'content_sha256': 'a' * 64}}
    mapping = {'sheet-key': 'trip-a'}
    payload = {'sources': {'main': {'status': 'ok', 'stale': False,
                                  'last_ok_at': '2026-10-30T00:00:00Z'}},
               'trips': [{'key': 'sheet-key', 'chosen_source': 'main', 'copies': {
                   'main': {'sheet': 'sheet-id', 'layout': 'rev', 'expense': {'verified': True}}}}]}
    detail = {'expense': [{'row': 7, 'amount': 500, 'payee': '다른 가맹점', 'date': '2025-01-01'}],
              'income': [{'row': 4, 'amount': 700, 'name': '수입 전용 합성'}]}
    costs = [{'row_id': 'board-a', 'display_tab_id': 'trip-a', 'amount_krw': 500}]
    board = SimpleNamespace(current_role=lambda: 'owner')
    monkeypatch.setattr(service.sheet_expense_reconciliation, '_store_and_trip', lambda *a: (object(), {'tab_id': 'trip-a'}))
    monkeypatch.setattr(service.sheet_expense_reconciliation, '_cost_preview_rows', lambda *a: costs)
    monkeypatch.setattr(service.sheet_expense_reconciliation, '_load_existing_links',
                        lambda *a: (_ for _ in ()).throw(AssertionError('legacy links must not be read')))
    monkeypatch.setattr(service.google_ledger_page, 'enabled', lambda: True)
    monkeypatch.setattr(service.google_ledger_page, 'snapshot_path', lambda: Path('synthetic.json'))
    monkeypatch.setattr(service.google_ledger_page, 'rows_path', lambda: Path('synthetic-rows.json'))
    monkeypatch.setattr(service.google_authority, 'load_consistent', lambda *a: (snapshot, private))
    monkeypatch.setattr(service.google_ledger_page, 'snapshot_for_display', lambda s: s)
    monkeypatch.setattr(service.google_ledger_page, 'load_mapping', lambda *a: mapping)
    monkeypatch.setattr(service.google_ledger_page, 'load_choices', lambda *a: {})
    monkeypatch.setattr(service.google_ledger_page, 'owner_payload', lambda *a: payload)
    monkeypatch.setattr(service.google_ledger_page, 'owner_rows', lambda *a: detail)
    return board, snapshot, private, mapping, payload, detail, costs


@pytest.mark.parametrize('failure', ['mapping', 'stale', 'source', 'hash', 'expense', 'generation', 'private_error'])
def test_bad_authority_never_becomes_green_or_unrecorded(context, monkeypatch, failure):
    board, snapshot, private, mapping, payload, detail, costs = context
    if failure == 'mapping': mapping.clear()
    elif failure == 'stale': payload['sources']['main']['stale'] = True
    elif failure == 'source': payload['trips'][0]['chosen_source'] = None
    elif failure == 'hash': private['main']['content_sha256'] = 'b' * 64
    elif failure == 'expense': payload['trips'][0]['copies']['main']['expense']['verified'] = False
    else:
        error = SnapshotError('GENERATION_MISMATCH') if failure == 'generation' else ValueError('C:/private/source.json')
        monkeypatch.setattr(service.google_authority, 'load_consistent',
                            lambda *a: (_ for _ in ()).throw(error))
    state = service.build_state(board, 'trip-a')
    assert state['available'] is False
    assert state['groups'] == [] and state['by_cost_id'] == {}
    assert state['summary']['matched'] == state['summary']['unrecorded'] == 0
    assert 'private' not in repr(state)
    if failure == 'stale': assert state['last_success_at'] == snapshot['synced_at']


def test_real_core_preserves_full_source_and_ignores_income_and_legacy_links(context):
    board, snapshot, private, mapping, payload, detail, costs = context
    before = deepcopy(context[1:])
    state = service.build_state(board, 'trip-a')
    assert state['available'] is True
    assert state['groups'][0]['status'] == 'matched'
    assert len(state['groups']) == 1
    assert state['groups'][0]['google_rows'][0]['date'] == '2025-01-01'
    assert context[1:] == before


def test_google_bank_transfer_expense_is_a_real_google_only_group(context):
    board, snapshot, private, mapping, payload, detail, costs = context
    detail['expense'].append({'row': 8, 'amount': 700, 'payee': '계좌이체 합성', 'evidence': '은행 이체'})
    state = service.build_state(board, 'trip-a')
    assert state['available'] is True
    assert state['summary']['google_only'] == 1
    assert next(g for g in state['groups'] if g['amount_krw'] == 700)['google_count'] == 1


def test_unbooked_transaction_uses_its_real_source_id(context):
    board, snapshot, private, mapping, payload, detail, costs = context
    costs[0].pop('row_id')
    costs[0]['transaction_id'] = 'transaction-real-ref'
    state = service.build_state(board, 'trip-a')
    assert state['available'] is True
    assert state['by_cost_id']['transaction-real-ref']['status'] == 'matched'
