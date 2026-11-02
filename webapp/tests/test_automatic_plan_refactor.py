"""Full plan/digest equivalence, including manual and financial dependencies."""
import subprocess
import types

import pytest

from app import automatic_classification as policy
from webapp.tests.test_automatic_classification_completion import setup, TRIPS


def baseline_policy():
    source = subprocess.check_output(['git', 'show', '55e304ad:app/automatic_classification.py']).decode('utf-8')
    module = types.ModuleType('app._baseline_automatic_classification')
    module.__package__ = 'app'
    exec(compile(source, '<baseline-automatic-classification>', 'exec'), vars(module))
    return module


@pytest.mark.parametrize('reconsider', [False, True])
@pytest.mark.parametrize('selected', [False, True])
@pytest.mark.parametrize('history', [False, True])
def test_complete_plan_including_digest_matches_baseline(setup, reconsider, selected, history):
    board, flow, batch, rows = setup
    tid = rows[0]['transaction_id']
    if history:
        flow.pipeline.save_decision(tid, rows[0]['revision'], item='수동항목',
                                   display_tab_id='', trip_id='', request_id='synthetic-history')
    board.conn.execute("INSERT INTO transaction_review_holds VALUES (?,?,?,?)",
                       (rows[1]['transaction_id'], rows[1]['source_hash'], 'user_hold', 'synthetic hold'))
    board.conn.execute("UPDATE transactions SET conflict_reason='conflict' WHERE transaction_id=?", (rows[2]['transaction_id'],))
    evidence = {tid: dict(source_hash=rows[0]['source_hash'], trip_id='B', item='숙박비', basis='합성 예약기간')}
    options = dict(reconsider=reconsider, transaction_ids=[tid] if selected else None, evidence=evidence)
    before = board.conn.total_changes
    expected = baseline_policy().plan(board.conn, TRIPS, **options)
    assert policy.plan(board.conn, TRIPS, **options) == expected
    assert board.conn.total_changes == before
