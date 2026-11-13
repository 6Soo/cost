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


def accept_booking_evidence_basis(expected, transaction_id, evidence):
    """Apply the approved 8bc945ff evidence-basis delta to the legacy plan."""
    expected = dict(expected)
    expected["targets"] = [dict(target) for target in expected["targets"]]
    target = next(t for t in expected["targets"] if t["id"] == transaction_id)
    values = list(target["values"])
    basis = values[2]
    stale_distance = " · 카드 이용일과 여행 기간 거리 0일 · "
    assert stale_distance in basis
    fact_basis = evidence[transaction_id]["basis"]
    values[2] = basis.replace(
        stale_distance,
        f" · {fact_basis} · ",
        1,
    )
    target["values"] = tuple(values)
    return expected


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
    actual = policy.plan(board.conn, TRIPS, **options)
    if reconsider and not history:
        # 8bc945ff preserves source-bound reservation-period evidence in the
        # basis. The accepted delta is only that rationale; target fields and
        # all other plan output remain checked against the old implementation.
        expected = accept_booking_evidence_basis(expected, tid, evidence)
        assert actual["targets"] == expected["targets"]
        assert actual["summary"] == expected["summary"]
        assert actual["digest"] != baseline_policy().plan(board.conn, TRIPS, **options)["digest"]
        assert policy.plan(board.conn, TRIPS, **options) == actual
    else:
        assert actual == expected
    assert board.conn.total_changes == before
