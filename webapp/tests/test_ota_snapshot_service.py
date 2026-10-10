"""The OTA review snapshot: requests read it, one worker recomputes it, and content keys decide when."""
import json
import os
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

from app import ota_payments, ota_sources
from webapp.ota_snapshot import OtaSnapshotService


class FakeClock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


def service(keys, reconcile=None, clock=None, persist_path=None, **kwargs):
    counter = {"reconcile": 0}

    def default_reconcile():
        counter["reconcile"] += 1
        return {"public": {"events": [{"ota_event_id": f"e{counter['reconcile']}"}], "cards_by_event": {},
                           "proposals": []}, "results": [], "links": {}, "data": {}}

    state = {"key": None}
    key_fn = lambda: state["key"] if state["key"] is not None else keys.pop(0)
    svc = OtaSnapshotService(key_fn=key_fn, reconcile_fn=reconcile or default_reconcile,
                             clock=clock or FakeClock(), persist_path=persist_path, start=False, **kwargs)
    return svc, counter, state


class OtaSnapshotServiceTests(unittest.TestCase):

    def test_a_request_never_reconciles(self):
        svc, counter, _ = service(["k1"])
        view = svc.view()
        self.assertEqual(view["status"], "loading")
        self.assertEqual(counter["reconcile"], 0)

    def test_first_check_reconciles_once_and_later_identical_checks_do_not(self):
        svc, counter, _ = service(["k1", "k1", "k1"])
        svc.check_now()
        svc.check_now()
        svc.check_now()
        self.assertEqual(counter["reconcile"], 1)
        view = svc.view()
        self.assertEqual(view["status"], "ready")
        self.assertEqual(view["generation"], 1)

    def test_a_changed_input_key_refreshes_exactly_once(self):
        svc, counter, state = service(["k1"])
        svc.check_now()
        state["key"] = "k2"
        svc.check_now()
        svc.check_now()
        self.assertEqual(counter["reconcile"], 2)
        self.assertEqual(svc.view()["generation"], 2)

    def test_concurrent_checks_run_one_reconciliation(self):
        gate = threading.Event()
        calls = []

        def slow():
            calls.append(1)
            gate.wait(5)
            return {"public": {}, "results": [], "links": {}, "data": {}}

        svc, _, _ = service(["k1"] * 8, reconcile=slow)
        threads = [threading.Thread(target=svc.check_now) for _ in range(8)]
        for thread in threads:
            thread.start()
        time.sleep(0.1)
        gate.set()
        for thread in threads:
            thread.join(5)
        self.assertEqual(len(calls), 1)

    def test_a_failed_refresh_keeps_the_last_good_snapshot_and_waits_before_retrying(self):
        clock = FakeClock()
        attempts = {"n": 0}

        def flaky():
            attempts["n"] += 1
            if attempts["n"] == 2:
                raise RuntimeError("source read failed")
            return {"public": {"events": [{"ota_event_id": "good"}]}, "results": [], "links": {}, "data": {}}

        svc, _, state = service(["k1"], reconcile=flaky, clock=clock)
        svc.check_now()
        state["key"] = "k2"
        svc.check_now()
        view = svc.view()
        self.assertEqual(view["status"], "error")
        self.assertEqual(view["current"]["public"]["events"][0]["ota_event_id"], "good")
        svc.check_now()
        self.assertEqual(attempts["n"], 2)
        clock.now += 61
        svc.check_now()
        self.assertEqual(attempts["n"], 3)
        self.assertEqual(svc.view()["status"], "ready")

    def test_stale_when_the_worker_stops_checking(self):
        clock = FakeClock()
        svc, _, _ = service(["k1", "k1"], clock=clock, fresh_seconds=150)
        svc.check_now()
        self.assertFalse(svc.view()["stale"] is True)
        clock.now += 200
        view = svc.view()
        self.assertTrue(view["stale"])
        self.assertEqual(view["status"], "refreshing")
        current, fresh = svc.held()
        self.assertIsNotNone(current)
        self.assertFalse(fresh)

    def test_a_persisted_snapshot_is_loaded_and_serves_after_a_matching_check(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "ota-snapshot.json"
            first, _, _ = service(["k1"], persist_path=path)
            first.check_now()
            restarted, counter, _ = service(["k1"], persist_path=path)
            self.assertEqual(restarted.view()["status"], "refreshing")
            restarted.check_now()
            self.assertEqual(counter["reconcile"], 1)
            self.assertEqual(restarted.view()["status"], "ready")
            self.assertEqual(restarted.view()["current"]["public"]["events"][0]["ota_event_id"], "e1")

    def test_a_corrupt_or_foreign_persisted_snapshot_is_ignored(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "ota-snapshot.json"
            path.write_text("{not json", encoding="utf-8")
            svc, _, _ = service(["k1"], persist_path=path)
            self.assertIsNone(svc.view()["current"])
            path.write_text(json.dumps({"schema": "other", "key": "k"}), encoding="utf-8")
            svc2, _, _ = service(["k1"], persist_path=path)
            self.assertIsNone(svc2.view()["current"])


class SourceContentTests(unittest.TestCase):

    def test_same_size_and_time_but_different_content_changes_the_stamp(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "collection.json"
            path.write_bytes(b'{"a": 1}')
            stamp = os.stat(path).st_mtime_ns
            before = ota_sources.content_stamp(path)
            path.write_bytes(b'{"a": 2}')
            os.utime(path, ns=(stamp, stamp))
            self.assertEqual(os.stat(path).st_size, len(b'{"a": 1}'))
            self.assertNotEqual(ota_sources.content_stamp(path), before)

    def test_mail_parse_is_reused_only_while_mail_content_is_unchanged(self):
        with tempfile.TemporaryDirectory() as directory:
            mail = Path(directory)
            (mail / "gmail-1.json").write_text('{"responses": []}', encoding="utf-8")
            ota_payments._MAIL_EVENT_MEMO.clear()
            with mock.patch.object(ota_payments, "_parse_mail_events", return_value=[{"ota_event_id": "x"}]) as parse:
                first = ota_payments._mail_events([str(mail)])
                second = ota_payments._mail_events([str(mail)])
                self.assertEqual(parse.call_count, 1)
                self.assertEqual(first, second)
                first.append({"ota_event_id": "mutated"})
                self.assertEqual(len(ota_payments._mail_events([str(mail)])), 1)
                (mail / "gmail-1.json").write_text('{"responses": [ ]}', encoding="utf-8")
                ota_payments._mail_events([str(mail)])
                self.assertEqual(parse.call_count, 2)
            ota_payments._MAIL_EVENT_MEMO.clear()
