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
