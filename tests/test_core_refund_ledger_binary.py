"""Synthetic ledger publication through the real costcore_bin, without customer data or live ports."""
import json
import os
import sqlite3
from contextlib import closing
from pathlib import Path

import pytest

from app import core_links
from app.db import StoreError
from tools.core_bridge.synthetic import scenario_db

pytestmark = pytest.mark.costcore_bin

GOLDENS = [json.loads(line) for line in
           (Path(__file__).resolve().parents[1] / 'core/golden/synthetic/refund_groups.jsonl')
           .read_text(encoding='utf-8').splitlines() if line.strip()]


@pytest.mark.parametrize('case', GOLDENS, ids=lambda case: case['case_id'])
def test_real_rust_pair_decisions_match_existing_python_goldens(case, monkeypatch):
    binary = os.environ.get('COSTCORE_TEST_BIN')
    assert binary, 'COSTCORE_TEST_BIN is required; use the official quality gate'
    monkeypatch.setenv(core_links.BIN_ENV, binary)
    request = case['input']
    with scenario_db(request['scenario']) as source, closing(sqlite3.connect(source)) as conn:
        booked = {row[0] for row in conn.execute('SELECT transaction_id FROM ledger_entries')}
        rows = []
        for spec in request.get('entries', []):
            row = {'item': '', 'description': '', 'display_tab_id': '', 'trip_id': '', **spec}
            row['already_booked'] = row['transaction_id'] in booked
            if row.get('blocked'):
                row['reason'] = 'synthetic hold'
            rows.append(row)
        ready = [row for row in rows if not row.get('blocked')]
        unresolved = [row for row in rows if row.get('blocked')]
        trips, tabs = request.get('valid_trips'), request.get('valid_tabs')
        before = core_links.fetch_rows(conn)
        core_links.ledger_pairs(conn, rows, ready, unresolved,
                                trip_validator=None if trips is None else lambda value: value in trips,
                                tab_validator=None if tabs is None else lambda value: value in tabs)
        keys = ('transaction_id', 'blocked', 'reason', 'item', 'description', 'display_tab_id', 'trip_id', 'refund_link')
        actual = [dict({key: row.get(key) for key in keys},
                       bucket='ready' if any(row is item for item in ready) else 'unresolved') for row in rows]
        assert actual == case['expected']['entries']
        assert core_links.fetch_rows(conn) == before


@pytest.fixture
def pair(monkeypatch):
    from webapp.tests.test_refund_group_commit import RefundGroupCommitTests
    monkeypatch.setenv(core_links.PRODUCER_ENV, 'python')

    case = RefundGroupCommitTests('test_state_lists_the_pair_as_one_recordable_group')
    case.setUp()
    try:
        binary = os.environ.get('COSTCORE_TEST_BIN')
        assert binary, 'COSTCORE_TEST_BIN is required; run the official quality gate to build it'
        monkeypatch.setenv(core_links.BIN_ENV, binary)
        yield case
    finally:
        case.tearDown()


def preview(case, validator=lambda _: True):
    return case.flow.pipeline.preview(case.batch, trip_validator=lambda _: True,
                                      tab_validator=validator, group_original=case.original)


def test_real_rust_pair_preview_equals_python_and_books_atomically(pair, monkeypatch):
    expected = preview(pair)
    source_before = core_links.fetch_rows(pair.board.conn)
    monkeypatch.setenv(core_links.PRODUCER_ENV, 'rust')
    actual = preview(pair)
    assert actual == expected
    result = pair.flow.pipeline.commit(pair.batch, actual['digest'], 'synthetic-rust-pair',
                                      trip_validator=lambda _: True, tab_validator=lambda _: True,
                                      group_original=pair.original)
    assert result['applied'] == 2
    assert pair.ledger() == (2, 300000)
    assert core_links.fetch_rows(pair.board.conn) == source_before
    replay = pair.flow.pipeline.commit(pair.batch, actual['digest'], 'synthetic-rust-pair',
                                      trip_validator=lambda _: True, tab_validator=lambda _: True,
                                      group_original=pair.original)
    assert replay == result and pair.ledger() == (2, 300000)


def test_real_rust_authority_loss_cannot_leave_half_a_group(pair, monkeypatch):
    monkeypatch.setenv(core_links.PRODUCER_ENV, 'rust')
    state = dict(armed=False, calls=0)
    def valid(_):
        if not state['armed']:
            return True
        state['calls'] += 1
        return state['calls'] == 1
    original_guard = core_links.check_ledger_groups
    def guard(*args):
        seal = original_guard(*args)
        state['armed'] = True
        return seal
    current = preview(pair, valid)
    monkeypatch.setattr(core_links, 'check_ledger_groups', guard)
    with pytest.raises(StoreError) as error:
        pair.flow.pipeline.commit(pair.batch, current['digest'], 'synthetic-rust-authority-loss',
                                  trip_validator=lambda _: True, tab_validator=valid,
                                  group_original=pair.original)
    assert error.value.code == 'REFUND_GROUP_INCOMPLETE'
    assert state['calls'] == 2 and pair.ledger() == (0, 0)


def test_real_rust_pair_without_authority_stays_blocked_like_python(pair, monkeypatch):
    expected = preview(pair, None)
    monkeypatch.setenv(core_links.PRODUCER_ENV, 'rust')
    assert preview(pair, None) == expected
