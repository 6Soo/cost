"""Reuse within a plan must never hide changed authority or input facts."""
from copy import deepcopy

import pytest

from app import automatic_classification as policy
from tools.benchmark_expense_performance import baseline
from webapp.tests.test_automatic_classification_completion import setup


@pytest.mark.parametrize('reconsider', [False, True])
def test_reused_periods_match_previous_plan_and_refresh_between_calls(setup, reconsider):
    board, _, _, _ = setup
    old = baseline('114af50d')
    trips = [dict(trip_id='A', starts_on='2026-10-01', ends_on=''),
             dict(trip_id='B', starts_on='2026-10-04', ends_on='2026-10-08')]
    before = board.conn.execute('SELECT * FROM transactions').fetchall()
    outputs = []
    for mutate in ('original', 'period', 'removed', 'empty'):
        if mutate == 'period':
            trips[1]['starts_on'] = '2026-10-02'
        elif mutate == 'removed':
            trips.pop(0)
        elif mutate == 'empty':
            trips.clear()
        original = deepcopy(trips)
        options = dict(reconsider=reconsider, nets={'B': 12000})
        actual = policy.plan(board.conn, trips, **options)
        assert actual == old.plan(board.conn, trips, **options)
        assert trips == original
        outputs.append(actual)
    assert outputs[0] != outputs[-1]
    assert before == board.conn.execute('SELECT * FROM transactions').fetchall()


def test_independent_inference_revalidates_changed_trips_and_nets():
    trips = [dict(trip_id=t, starts_on='2026-10-01', ends_on='2026-10-05')
             for t in ('A', 'B')]
    row = dict(approval_date='2026-10-03')
    assert policy.infer_trip(row, trips, nets={'A': 1})[0] == 'A'
    assert policy.infer_trip(row, trips, nets={'B': 1})[0] == 'B'
    trips[0]['starts_on'] = 'invalid'
    assert policy.infer_trip(row, trips, nets={'A': 1000})[0] == 'B'
    trips[1]['ends_on'] = 'invalid'
    assert policy.infer_trip(row, trips)[0] == ''
