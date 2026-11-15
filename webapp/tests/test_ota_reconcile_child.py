import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
import time
import subprocess
import threading

from webapp import ota_payment_review


def test_cancelled_reconciliation_does_not_start_a_child(tmp_path, monkeypatch):
    monkeypatch.setenv('WEBLEDGER_OTA_REVIEW_DB', str(tmp_path / 'review.sqlite'))
    event = threading.Event()
    event.set()
    def unexpected(*args, **kwargs):
        raise AssertionError('child should not start')
    monkeypatch.setattr(subprocess, 'Popen', unexpected)
    with unittest.TestCase().assertRaisesRegex(ota_payment_review.OtaReconcileChildError, 'cancelled'):
        ota_payment_review.reconcile_in_child(SimpleNamespace(path=tmp_path / 'board.sqlite'), cancel_event=event)
    assert list(tmp_path.glob('ota-reconcile-*')) == []


def test_stopping_snapshot_cancels_owned_reconciliation_child(tmp_path, monkeypatch):
    marker = tmp_path / 'child-ready'
    monkeypatch.setenv('WEBLEDGER_OTA_REVIEW_DB', str(tmp_path / 'review.sqlite'))
    monkeypatch.setattr(ota_payment_review, 'input_key', lambda board: 'synthetic')
    monkeypatch.setattr(ota_payment_review, 'current_input_key', lambda board: 'synthetic')
    monkeypatch.setattr(ota_payment_review, 'CHILD_BOOTSTRAP',
        'import pathlib,sys,time; pathlib.Path(sys.argv[2]).write_text("ready"); time.sleep(60)')
    real_popen = subprocess.Popen
    children = []
    def capture(*args, **kwargs):
        process = real_popen(*args, **kwargs)
        if '-c' in args[0]:
            children.append(process)
        return process
    monkeypatch.setattr(subprocess, 'Popen', capture)
    service = ota_payment_review.snapshot_service(SimpleNamespace(path=marker))
    try:
        deadline = time.monotonic() + 10
        while not marker.exists() and time.monotonic() < deadline:
            time.sleep(.02)
        assert marker.exists() and len(children) == 1
        service.stop(timeout=3)
        assert not service.worker_alive()
        assert children[0].poll() is not None
        assert list(tmp_path.glob('ota-reconcile-*')) == []
    finally:
        for child in children:
            if child.poll() is None:
                child.kill()
                child.wait(timeout=5)
        service.stop(timeout=5)


def test_child_time_limit_reads_the_environment_and_falls_back_to_the_default(monkeypatch):
    monkeypatch.delenv(ota_payment_review.CHILD_TIMEOUT_ENV, raising=False)
    assert ota_payment_review.child_timeout_seconds() == ota_payment_review.CHILD_TIMEOUT_SECONDS == 1800
    monkeypatch.setenv(ota_payment_review.CHILD_TIMEOUT_ENV, '2400')
    assert ota_payment_review.child_timeout_seconds() == 2400
    for bad in ('0', '-5', 'soon'):
        monkeypatch.setenv(ota_payment_review.CHILD_TIMEOUT_ENV, bad)
        assert ota_payment_review.child_timeout_seconds() == 1800


def test_child_past_its_time_limit_is_stopped(tmp_path, monkeypatch):
    monkeypatch.setenv('WEBLEDGER_OTA_REVIEW_DB', str(tmp_path / 'review.sqlite'))
    monkeypatch.setenv(ota_payment_review.CHILD_TIMEOUT_ENV, '0.5')
    monkeypatch.setattr(ota_payment_review, 'CHILD_BOOTSTRAP', 'import time; time.sleep(30)')
    started = time.monotonic()
    with unittest.TestCase().assertRaisesRegex(ota_payment_review.OtaReconcileChildError, 'timed out after 0.5 s'):
        ota_payment_review.reconcile_in_child(SimpleNamespace(path=tmp_path / 'board.sqlite'))
    assert time.monotonic() - started < 15


def _shared_runs(monkeypatch, key, outcomes):
    """Replace the child with `outcomes` (one per run: a value or an exception), each after `release` is set."""
    monkeypatch.setattr(ota_payment_review, '_SHARED', {})
    monkeypatch.setattr(ota_payment_review, 'current_input_key', lambda board: key[0])
    calls, release = [], threading.Event()

    def run(board, *, cancel_event=None):
        calls.append(board)
        release.wait(10)
        outcome = outcomes[len(calls) - 1]
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    monkeypatch.setattr(ota_payment_review, '_reconcile_in_child', run)
    return calls, release


def _in_threads(count, work):
    answers = [None] * count

    def call(index):
        try:
            answers[index] = work()
        except Exception as exc:
            answers[index] = exc

    threads = [threading.Thread(target=call, args=(index,)) for index in range(count)]
    for thread in threads:
        thread.start()
    return threads, answers


def test_callers_with_the_same_input_key_share_one_child(tmp_path, monkeypatch):
    key = ['k1']
    first, second = {'data': 1}, {'data': 2}
    calls, release = _shared_runs(monkeypatch, key, [first, second])
    board = SimpleNamespace(path=tmp_path / 'board.sqlite')
    threads, answers = _in_threads(3, lambda: ota_payment_review.reconcile_in_child(board))
    deadline = time.monotonic() + 5
    while not calls and time.monotonic() < deadline:
        time.sleep(.01)
    time.sleep(.2)
    release.set()
    for thread in threads:
        thread.join(10)
    assert len(calls) == 1 and all(answer is first for answer in answers)
    assert ota_payment_review.reconcile_in_child(board) is first and len(calls) == 1
    key[0] = 'k2'
    assert ota_payment_review.reconcile_in_child(board) is second and len(calls) == 2


def test_a_cancelled_run_is_redone_by_its_waiter_and_a_failed_one_is_reported(tmp_path, monkeypatch):
    result = {'data': 1}
    calls, release = _shared_runs(monkeypatch, ['k'], [
        ota_payment_review.OtaReconcileCancelled('the reconciliation was cancelled'), result])
    board = SimpleNamespace(path=tmp_path / 'board.sqlite')
    threads, answers = _in_threads(2, lambda: ota_payment_review.reconcile_in_child(board))
    deadline = time.monotonic() + 5
    while not calls and time.monotonic() < deadline:
        time.sleep(.01)
    time.sleep(.2)
    release.set()
    for thread in threads:
        thread.join(10)
    assert len(calls) == 2
    assert sorted(type(answer).__name__ for answer in answers) == ['OtaReconcileCancelled', 'dict']

    calls, release = _shared_runs(monkeypatch, ['k'], [
        ota_payment_review.OtaReconcileChildError('the reconciliation process timed out after 1800 s')])
    threads, answers = _in_threads(2, lambda: ota_payment_review.reconcile_in_child(board))
    deadline = time.monotonic() + 5
    while not calls and time.monotonic() < deadline:
        time.sleep(.01)
    time.sleep(.2)
    release.set()
    for thread in threads:
        thread.join(10)
    assert len(calls) == 1
    assert all(isinstance(answer, ota_payment_review.OtaReconcileChildError) and 'timed out' in str(answer)
               for answer in answers)


def test_inputs_that_moved_during_the_run_are_not_reused(tmp_path, monkeypatch):
    key = ['k']
    calls, release = _shared_runs(monkeypatch, key, [{'data': 1}, {'data': 2}])
    release.set()
    board = SimpleNamespace(path=tmp_path / 'board.sqlite')
    real = ota_payment_review._reconcile_in_child

    def moving(board, *, cancel_event=None):
        value = real(board, cancel_event=cancel_event)
        key[0] = 'moved'
        return value

    monkeypatch.setattr(ota_payment_review, '_reconcile_in_child', moving)
    assert ota_payment_review.reconcile_in_child(board) == {'data': 1}
    key[0] = 'k'
    assert ota_payment_review.reconcile_in_child(board) == {'data': 2} and len(calls) == 2


def test_the_snapshot_worker_board_is_the_host_for_its_path(tmp_path, monkeypatch):
    monkeypatch.setenv('WEBLEDGER_OTA_REVIEW_DB', str(tmp_path / 'review.sqlite'))
    monkeypatch.setattr(ota_payment_review, '_HOSTS', {})
    monkeypatch.setattr(ota_payment_review.ota_snapshot, 'OtaSnapshotService', lambda **kwargs: SimpleNamespace())
    monkeypatch.setattr(ota_payment_review.atexit, 'register', lambda *args: None)

    class Board:
        path = tmp_path / 'board.sqlite'

    board = Board()
    ota_payment_review.snapshot_service(board)
    assert ota_payment_review.host_board(str(tmp_path / '.' / 'board.sqlite')) is board
    assert ota_payment_review.host_board(tmp_path / 'other.sqlite') is None


class ReconcileChildTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self._prev = os.environ.get("WEBLEDGER_OTA_REVIEW_DB")
        os.environ["WEBLEDGER_OTA_REVIEW_DB"] = str(Path(self.tmp) / "ota-review.sqlite")

    def tearDown(self):
        if self._prev is None:
            os.environ.pop("WEBLEDGER_OTA_REVIEW_DB", None)
        else:
            os.environ["WEBLEDGER_OTA_REVIEW_DB"] = self._prev

    def test_a_failing_reconciliation_in_the_child_is_reported_with_its_cause(self):
        """A board with no sources cannot reconcile; the parent must see why, not a silent success."""
        class Board:
            path = Path(self.tmp) / "board.sqlite"
            _reservation_authority = None

        with self.assertRaises(ota_payment_review.OtaReconcileChildError) as raised:
            ota_payment_review.reconcile_in_child(Board())
        self.assertIn(":", str(raised.exception))
        self.assertEqual(list(Path(self.tmp).glob("ota-reconcile-*")), [])


if __name__ == "__main__":
    unittest.main()
