"""OTA link producer switch (M3 2nd cutover): Python by default, `costcore links ota` when WEBLEDGER_LINKS_PRODUCER=rust.

Real-binary tests use the costcore named by COSTCORE_TEST_BIN (same variable as test_core_links_switch.py); they skip without it.
"""
import copy
import json
import os
import shutil
import sqlite3
import subprocess
from contextlib import closing
from pathlib import Path

import pytest

from app import core_ota_links, ota_payments
from tools.core_bridge import golden, ota_input
from tools.core_bridge.synthetic import scenario_db

ROOT = Path(__file__).resolve().parents[1]
GOLDEN = [json.loads(line) for name in ('ota_links.jsonl', 'ota_mn.jsonl')
          for line in (golden.GOLDEN_DIR / name).read_text(encoding='utf-8').splitlines()]
NO_EXTRA = [case for case in golden._ota_inputs() if not case[3]]


def canon(value):
    return json.loads(json.dumps(value, ensure_ascii=False, sort_keys=True))  # no default=str: a type difference must show


@pytest.fixture
def binary(request, monkeypatch):
    request.applymarker(pytest.mark.costcore_bin)  # run_quality_checks builds costcore and sets COSTCORE_TEST_BIN for it
    path = os.environ.get('COSTCORE_TEST_BIN')
    if not path or not Path(path).is_file():
        pytest.skip('COSTCORE_TEST_BIN not set (the quality runner wiring from the refund switch PR sets it)')
    monkeypatch.setenv(core_ota_links.BIN_ENV, path)
    return path


def python_solve(request):
    request = copy.deepcopy(request)
    return ota_payments.match_ota_payment_events(
        request['events'], request['transactions'], existing_links=request.get('existing_links'),
        rules=request.get('rules'), frozen_groups=request.get('frozen_groups'))


def rust_solve(request):
    request = copy.deepcopy(request)
    return core_ota_links.match_ota_payment_events(
        request['events'], request['transactions'], existing_links=request.get('existing_links'),
        rules=request.get('rules'), frozen_groups=request.get('frozen_groups'))


def request_of(note, events, cards, **extra):
    return dict({'events': events, 'transactions': cards}, **extra)


# ---- default and switch ---------------------------------------------------------------------------------------------

@pytest.mark.parametrize('value,expected', [(None, 'python'), ('', 'python'), ('python', 'python'), ('rsut', 'python'),
                                            ('rust', 'rust'), (' RUST ', 'rust')])
def test_only_the_value_rust_selects_the_core(monkeypatch, value, expected):
    if value is None:
        monkeypatch.delenv(core_ota_links.PRODUCER_ENV, raising=False)
    else:
        monkeypatch.setenv(core_ota_links.PRODUCER_ENV, value)
    assert core_ota_links.selected() == expected


class Payments:
    """The real solver with the event builder replaced by synthetic events; records which solver ran."""

    def __init__(self, events, calls):
        self.events, self.calls = events, calls

    def __getattr__(self, name):
        return getattr(ota_payments, name)

    def build_ota_payment_events(self, sources, **kwargs):
        return copy.deepcopy(self.events)

    def match_ota_payment_events(self, events, transactions, **kwargs):
        self.calls.append('python')
        return ota_payments.match_ota_payment_events(events, transactions, **kwargs)


def data_of(case, tmp_path, calls):
    """What `CoreOtaPaymentBackend._data` produces for a synthetic case (read-only copies, no host files)."""
    import app.ota_review as review
    from webapp.ota_payment_review import CoreOtaPaymentBackend
    note, events, cards, _extra = case
    board = tmp_path / 'board-copy.sqlite'
    with scenario_db({'rows': cards}) as path:
        shutil.copy(path, board)
    review_db = tmp_path / 'ota-review.sqlite'
    with closing(sqlite3.connect(review_db)) as conn:
        conn.execute('CREATE TABLE ota_review_marker(x)')
        conn.commit()
    with closing(sqlite3.connect(board.as_uri() + '?mode=ro', uri=True)) as conn:
        conn.row_factory = sqlite3.Row
        backend = CoreOtaPaymentBackend(ota_input._ReadOnlyBoard(conn, board), str(review_db), read_only=True,
                                        payments=Payments(events, calls), store_type=review.OtaReviewStore,
                                        sources={'mail_directories': []})
        try:
            return canon(backend._data())
        finally:
            backend.close()


def test_default_never_touches_costcore(monkeypatch, tmp_path):
    monkeypatch.delenv(core_ota_links.PRODUCER_ENV, raising=False)
    monkeypatch.delenv(core_ota_links.BIN_ENV, raising=False)
    monkeypatch.setattr(core_ota_links, '_run', lambda request: pytest.fail('costcore must not run by default'))
    monkeypatch.setattr(subprocess, 'run', lambda *a, **k: pytest.fail('no subprocess by default'))
    calls = []
    data_of(NO_EXTRA[0], tmp_path, calls)
    assert calls == ['python']


# ---- failure never falls back to Python -------------------------------------------------------------------------------

def test_costcore_failure_fails_and_python_is_not_called(monkeypatch, tmp_path):
    monkeypatch.setenv(core_ota_links.PRODUCER_ENV, 'rust')
    monkeypatch.setenv(core_ota_links.BIN_ENV, 'costcore')
    monkeypatch.setattr(subprocess, 'run', lambda *a, **k: subprocess.CompletedProcess(
        a[0], 2, stdout='{"ok":false,"error":{"code":"INPUT_INVALID"}}\n', stderr=''))
    calls = []
    with pytest.raises(RuntimeError, match='INPUT_INVALID'):
        data_of(NO_EXTRA[0], tmp_path, calls)
    assert calls == []


def test_missing_binary_setting_fails(monkeypatch, tmp_path):
    monkeypatch.setenv(core_ota_links.PRODUCER_ENV, 'rust')
    monkeypatch.delenv(core_ota_links.BIN_ENV, raising=False)
    calls = []
    with pytest.raises(RuntimeError, match='CORE_LINKS_NOT_CONFIGURED'):
        data_of(NO_EXTRA[0], tmp_path, calls)
    assert calls == []


def test_empty_response_fails(monkeypatch):
    monkeypatch.setenv(core_ota_links.BIN_ENV, 'costcore')
    monkeypatch.setattr(subprocess, 'run', lambda *a, **k: subprocess.CompletedProcess(a[0], 0, stdout='', stderr=''))
    with pytest.raises(RuntimeError, match='CORE_LINKS_NO_RESPONSE'):
        core_ota_links.match_ota_payment_events([], [])


def test_nonzero_exit_with_ok_body_fails(monkeypatch):
    monkeypatch.setenv(core_ota_links.BIN_ENV, 'costcore')
    monkeypatch.setattr(subprocess, 'run', lambda *a, **k: subprocess.CompletedProcess(
        a[0], 1, stdout='{"ok":true,"result":{"results":[]}}\n', stderr=''))
    with pytest.raises(RuntimeError):
        core_ota_links.match_ota_payment_events([], [])


def test_result_for_an_unknown_event_or_duplicate_event_ids_fail(monkeypatch):
    monkeypatch.setattr(core_ota_links, '_run', lambda request: [{'ota_event_id': 'ghost', 'status': 'HOLD_NO_CARD'}])
    with pytest.raises(RuntimeError, match='CORE_LINKS_UNKNOWN_EVENT'):
        core_ota_links.match_ota_payment_events([{'ota_event_id': 'e1'}], [])
    with pytest.raises(RuntimeError, match='CORE_LINKS_DUPLICATE_EVENT'):
        core_ota_links.match_ota_payment_events([{'ota_event_id': 'e1'}, {'ota_event_id': 'e1'}], [])


def test_a_result_count_that_differs_from_the_event_count_or_repeats_an_event_fails(monkeypatch):
    events = [{'ota_event_id': 'e1'}, {'ota_event_id': 'e2'}]
    monkeypatch.setattr(core_ota_links, '_run', lambda request: [{'ota_event_id': 'e1', 'status': 'HOLD_NO_CARD'}])
    with pytest.raises(RuntimeError, match='CORE_LINKS_RESULT_COUNT'):
        core_ota_links.match_ota_payment_events(events, [])
    monkeypatch.setattr(core_ota_links, '_run', lambda request: [{'ota_event_id': 'e1'}, {'ota_event_id': 'e1'}])
    with pytest.raises(RuntimeError, match='CORE_LINKS_DUPLICATE_RESULT'):
        core_ota_links.match_ota_payment_events(events, [])


def test_the_two_adapters_share_one_switch_decision():
    from app import core_links
    assert core_ota_links.selected is core_links.selected
    assert core_ota_links.PRODUCER_ENV == core_links.PRODUCER_ENV and core_ota_links.BIN_ENV == core_links.BIN_ENV


def test_the_quality_runner_builds_costcore_for_this_file():
    from tools import run_quality_checks
    assert run_quality_checks.needs_costcore(['tests/test_core_ota_links_switch.py'], root=ROOT)


# ---- real binary ------------------------------------------------------------------------------------------------------

@pytest.mark.parametrize('case', GOLDEN, ids=[f"{c['case_id']}" for c in GOLDEN])
def test_rust_equals_python_on_every_ota_golden_case(binary, case):
    request = case['input']
    assert canon(rust_solve(request)) == canon(python_solve(request))


DATA_CASES = [c for c in NO_EXTRA if 'authorization' not in json.dumps(c[2])]  # card columns the synthetic board has


@pytest.mark.parametrize('case', DATA_CASES, ids=[c[0][:40] for c in DATA_CASES])
def test_data_is_identical_under_both_producers(binary, monkeypatch, tmp_path, case):
    monkeypatch.delenv(core_ota_links.PRODUCER_ENV, raising=False)
    python_calls, rust_calls = [], []
    (tmp_path / 'py').mkdir()
    (tmp_path / 'rs').mkdir()
    python_data = data_of(case, tmp_path / 'py', python_calls)
    monkeypatch.setenv(core_ota_links.PRODUCER_ENV, 'rust')
    rust_data = data_of(case, tmp_path / 'rs', rust_calls)
    assert python_calls == ['python'] and rust_calls == []
    assert rust_data == python_data


def solved(binary, events, cards, **extra):
    request = request_of('', events, cards, **extra)
    got = canon(rust_solve(request))
    assert got == canon(python_solve(request))
    return {row['ota_event_id']: row for row in got}


def test_manual_link_stays_and_no_other_event_takes_its_card(binary):
    E, C = golden._event, golden._card
    pinned = {'syn-e1': {'transaction_id': 'syn-t2', 'status': 'MATCHED_USER'}}
    rows = solved(binary, [E('syn-e1'), E('syn-e2', booking_ref='SYN-BOOK-2')],
                  [C('syn-t1'), C('syn-t2', approval_number='SYN-AP-2')], existing_links=pinned)
    assert rows['syn-e1']['transaction_id'] == 'syn-t2' and rows['syn-e1']['status'] == 'MATCHED_USER'
    assert rows['syn-e2']['transaction_id'] != 'syn-t2'


def test_one_card_is_never_taken_by_two_events(binary):
    E, C = golden._event, golden._card
    rows = solved(binary, [E('syn-e1', booking_ref='SYN-BOOK-1'), E('syn-e2', booking_ref='SYN-BOOK-2')], [C('syn-t1')])
    taken = [row['transaction_id'] for row in rows.values() if row['transaction_id']]
    assert len(taken) == len(set(taken)) <= 1


@pytest.mark.parametrize('change', [{'duplicate_of': 'syn-t0'}, {'conflict_reason': 'syn conflict'},
                                    {'parse_error': 'AMOUNT_UNREADABLE'}, {'transaction_direction': 'refund'}])
def test_protected_cards_are_never_matched(binary, change):
    E, C = golden._event, golden._card
    rows = solved(binary, [E('syn-e1')], [C('syn-t1', **change)])
    assert rows['syn-e1']['transaction_id'] is None and not rows['syn-e1']['status'].startswith('MATCHED')


def test_frozen_group_keeps_the_confirmed_order_or_holds_for_review(binary):
    by_id = {c['case_id']: c for c in GOLDEN}
    kept = by_id['ota_mn-001']['input']
    rows = {r['ota_event_id']: r for r in canon(rust_solve(kept))}
    assert all(r['group_order_frozen'] is True and r['status'] == 'MATCHED_AUTO' for r in rows.values())
    assert canon(rust_solve(kept)) == canon(python_solve(kept))
    changed = by_id['ota_mn-005']['input']
    rows = canon(rust_solve(changed))
    assert rows == canon(python_solve(changed))
    assert {r['status'] for r in rows} == {'HOLD_GROUP_CHANGED'}
    assert {r['review_warning'] for r in rows} == {'confirm_group_reallocation'}

def test_input_errors_are_fixed_codes(binary):
    for body, code in (('not json', 'INPUT_INVALID'), ('[]', 'INPUT_INVALID'),
                       ('{"events":{}, "transactions":[]}', 'INPUT_INVALID')):
        done = subprocess.run([binary, 'links', 'ota', '--input', '-', '--repo-root', str(ROOT)], input=body,
                              capture_output=True, text=True, encoding='utf-8')
        assert done.returncode == 2 and json.loads(done.stdout) == {'ok': False, 'error': {'code': code}}
    done = subprocess.run([binary, 'links', 'ota', '--bogus', 'x'], capture_output=True, text=True, encoding='utf-8')
    assert done.returncode == 2 and json.loads(done.stdout)['error']['code'] == 'USAGE_INVALID'


def test_capture_still_reaches_the_python_solver_while_the_switch_is_on(monkeypatch, tmp_path):
    monkeypatch.setenv(core_ota_links.PRODUCER_ENV, 'rust')
    note, events, cards, _extra = NO_EXTRA[0]
    board = tmp_path / 'board-copy.sqlite'
    with scenario_db({'rows': cards}) as path:
        shutil.copy(path, board)
    review_db = tmp_path / 'ota-review.sqlite'
    with closing(sqlite3.connect(review_db)) as conn:
        conn.execute('CREATE TABLE ota_review_marker(x)')
        conn.commit()

    class Stub(Payments):
        pass

    data = ota_input.solver_input(board, review_db, {'mail_directories': []}, payments=Stub(events, []))
    assert data['kind'] == 'ota' and os.environ[core_ota_links.PRODUCER_ENV] == 'rust'
