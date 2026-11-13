"""Reuse within a plan must never hide changed authority or input facts."""
from copy import deepcopy

import pytest

from app import automatic_classification as policy
from tools.benchmark_expense_performance import baseline
from webapp.tests.test_automatic_classification_completion import setup


def accept_proc004_quarter_fallback(expected, actual):
    """Translate legacy unassigned fallbacks to the approved PROC-004 result."""
    expected = dict(expected)
    expected["targets"] = [dict(target) for target in expected["targets"]]
    expected_by_id = {target["id"]: target for target in expected["targets"]}
    changed = False
    for current in actual["targets"]:
        target = expected_by_id[current["id"]]
        if current["values"][5].startswith("quarter:"):
            values = list(target["values"])
            assert values[5] == "unclassified"
            year, quarter = int(current["values"][5].split(":")[1]), int(current["values"][5].split(":")[2])
            assert values[2].endswith("등록된 유효 여행 없음 · complete-card-inference-v1")
            values[2] = values[2].replace(
                "등록된 유효 여행 없음 · complete-card-inference-v1",
                "실제 여행 후보 없음 · 결제일 기준 분기 기타비용 · complete-card-inference-v1",
            )
            values[3] = "분기 기타비용"
            values[4] = f"{year}년 {quarter}분기 기타비용"
            values[5] = f"quarter:{year}:{quarter}"
            target["values"] = tuple(values)
            changed = True
    assert set(expected_by_id) == {target["id"] for target in actual["targets"]}
    return expected, changed


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
        legacy = old.plan(board.conn, trips, **options)
        expected, proc004_changed = accept_proc004_quarter_fallback(
            legacy, actual
        )
        assert actual["targets"] == expected["targets"]
        assert actual["summary"] == expected["summary"]
        if proc004_changed:
            # A new target destination and rationale must produce a new digest.
            assert actual["digest"] != legacy["digest"]
        else:
            assert actual["digest"] == legacy["digest"]
        assert policy.plan(board.conn, trips, **options) == actual
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
