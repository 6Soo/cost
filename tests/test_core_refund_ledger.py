"""Synthetic contracts for Rust refund decisions consumed by the Python ledger."""
import copy
import json
import sqlite3
import subprocess

import pytest

from app import core_links, ledger


@pytest.fixture
def connection():
    conn = sqlite3.connect(':memory:')
    columns = ','.join(f'{name} TEXT' for name in core_links.COLUMNS)
    conn.execute(f'CREATE TABLE transactions ({columns})')
    conn.executemany('INSERT INTO transactions(transaction_id) VALUES (?)', [('original',), ('refund',)])
    conn.execute('CREATE TABLE ledger_entries(transaction_id TEXT)')
    yield conn
    conn.close()


def entry(identity):
    return dict(transaction_id=identity, item='synthetic-item', display_tab_id='synthetic-tab',
                trip_id='', description='', amount_krw=123, merchant='synthetic-source')


def answer(monkeypatch, callback):
    monkeypatch.setenv(core_links.BIN_ENV, 'synthetic-costcore.exe')
    def run(command, **kwargs):
        request = json.loads(kwargs['input'])
        return subprocess.CompletedProcess(command, 0, json.dumps(dict(ok=True, result=callback(command, request))), '')
    monkeypatch.setattr(core_links.subprocess, 'run', run)


def test_rust_pairs_change_only_decision_fields(connection, monkeypatch):
    original, refund = entry('original'), entry('refund')
    refund['blocked'], refund['reason'] = 'item_missing', 'synthetic hold'
    ready, unresolved = [original], [refund]
    def response(command, request):
        assert command[1:3] == ['links', 'refund-entries']
        assert request['authority']['tabs']['synthetic-tab'] is True
        assert 'amount_krw' not in request['entries'][0]
        result = copy.deepcopy(request['entries'])
        result[1].update(item='inherited-item', blocked=None, ready=True)
        return dict(entries=result)
    answer(monkeypatch, response)
    core_links.ledger_pairs(connection, [original, refund], ready, unresolved,
                            trip_validator=lambda _: True, tab_validator=lambda _: True)
    assert refund['item'] == 'inherited-item'
    assert (refund['amount_krw'], refund['merchant']) == (123, 'synthetic-source')
    assert 'blocked' not in refund and ready == [original, refund] and unresolved == []


@pytest.mark.parametrize('mutation', ['missing', 'foreign', 'duplicate', 'source', 'booked', 'malformed'])
def test_bad_rust_response_changes_no_preview_rows(connection, monkeypatch, mutation):
    rows = [entry('original'), entry('refund')]
    before = copy.deepcopy(rows)
    def response(command, request):
        out = copy.deepcopy(request['entries'])
        if mutation == 'missing': out.pop()
        if mutation == 'foreign': out[0]['id'] = 'foreign'
        if mutation == 'duplicate': out[1]['id'] = out[0]['id']
        if mutation == 'source': out[0]['amount_krw'] = 999
        if mutation == 'booked': out[0]['already_booked'] = True
        if mutation == 'malformed': out[0]['ready'] = 'yes'
        return dict(entries=out)
    answer(monkeypatch, response)
    with pytest.raises(RuntimeError):
        core_links.ledger_pairs(connection, rows, list(rows), [], trip_validator=None, tab_validator=None)
    assert rows == before


def test_missing_rust_group_seal_fails_closed(connection, monkeypatch):
    rows = [entry('refund')]
    rows[0]['refund_link'] = dict(role='refund', counterpart_id='original', inferred=False)
    answer(monkeypatch, lambda *_: dict(groups=[]))
    with pytest.raises(RuntimeError):
        core_links.check_ledger_groups(connection, rows)


def test_group_seal_includes_previously_booked_member(connection, monkeypatch):
    connection.execute("INSERT INTO ledger_entries VALUES ('original')")
    rows = [entry('refund')]
    def response(command, request):
        assert command[1:3] == ['links', 'refund-check']
        assert request['booked'] == ['original']
        return dict(groups=[dict(id='refund:original', members=['original', 'refund'])])
    answer(monkeypatch, response)
    assert core_links.check_ledger_groups(connection, rows) == frozenset({'original', 'refund'})


def test_ledger_routes_rust_mode_to_rust_pair_decision(connection, monkeypatch):
    monkeypatch.setenv(core_links.PRODUCER_ENV, 'rust')
    called = []
    monkeypatch.setattr(core_links, 'ledger_pairs', lambda *args, **kwargs: called.append('pairs'))
    ledger._apply_refund_pairs(type('Store', (), {'conn': connection})(), [], [], [], None, None)
    assert called == ['pairs']


def test_ledger_routes_rust_mode_to_sealed_group_guard(connection, monkeypatch):
    monkeypatch.setenv(core_links.PRODUCER_ENV, 'rust')
    monkeypatch.setattr(core_links, 'check_ledger_groups', lambda *args: frozenset({'original', 'refund'}))
    assert ledger._check_refund_groups(type('Store', (), {'conn': connection})(), []) == frozenset({'original', 'refund'})


def test_source_change_during_rust_run_cannot_modify_preview(connection, monkeypatch):
    rows = [entry('original')]
    before = copy.deepcopy(rows)
    def response(command, request):
        connection.execute("UPDATE transactions SET merchant='changed synthetic' WHERE transaction_id='original'")
        return dict(entries=request['entries'])
    answer(monkeypatch, response)
    with pytest.raises(RuntimeError, match='DB_CHANGING'):
        core_links.ledger_pairs(connection, rows, list(rows), [], trip_validator=None, tab_validator=None)
    assert rows == before


def test_late_authority_loss_rolls_back_entire_sealed_group(monkeypatch):
    from webapp.tests.test_refund_group_commit import RefundGroupCommitTests
    from app.db import StoreError
    case = RefundGroupCommitTests('test_state_lists_the_pair_as_one_recordable_group')
    case.setUp()

    try:
        monkeypatch.setenv(core_links.PRODUCER_ENV, 'python')
        state = dict(armed=False, calls=0)
        def validator(_):
            if not state['armed']:
                return True
            state['calls'] += 1
            return state['calls'] == 1
        def seal(*_):
            state['armed'] = True
            return frozenset({case.original, case.refund})
        pipeline = case.flow.pipeline
        preview = pipeline.preview(case.batch, trip_validator=lambda _: True,
                                   tab_validator=validator, group_original=case.original)
        monkeypatch.setattr(ledger, '_check_refund_groups', seal)
        with pytest.raises(StoreError) as error:
            pipeline.commit(case.batch, preview['digest'], 'synthetic-authority-loss',
                            trip_validator=lambda _: True, tab_validator=validator, group_original=case.original)
        assert error.value.code == 'REFUND_GROUP_INCOMPLETE'
        assert state['calls'] == 2
        assert case.ledger() == (0, 0)
    finally:
        case.tearDown()
