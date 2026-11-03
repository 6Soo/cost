"""The OTA review snapshot: requests read it, one worker recomputes it, and content keys decide when."""
import json
import os
import subprocess
import sys
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

    def test_read_burst_waits_for_normal_check_interval_but_explicit_check_still_wakes(self):
        clock = FakeClock()
        svc, counter, state = service(["k1"], clock=clock)
        svc.check_now()
        state["key"] = "k1"
        svc._autostart = True
        with mock.patch.object(svc, 'ensure_started'):
            for _ in range(100):
                self.assertEqual(svc.view()['status'], 'ready')
                svc.queue_page_context()
                svc.queue_group_context()
            self.assertFalse(svc._wake.is_set())
            self.assertEqual(counter['reconcile'], 1)
            # A review action can still request an immediate check.
            svc.request_check()
            self.assertTrue(svc._wake.is_set())
            svc._wake.clear()
            clock.now += svc._check_seconds
            svc.view()
            self.assertTrue(svc._wake.is_set())
            svc._wake.clear()
            state['key'] = 'k2'
            svc.check_now()
            self.assertEqual(svc.view()['generation'], 2)
            self.assertFalse(svc._wake.is_set())

    def test_unchecked_reads_wake_but_reads_during_refresh_do_not_queue_another_check(self):
        svc, _, _ = service(['k1'])
        svc._autostart = True
        with mock.patch.object(svc, 'ensure_started'):
            self.assertEqual(svc.view()['status'], 'loading')
            self.assertTrue(svc._wake.is_set())
            svc._wake.clear()
            svc._refreshing = True
            svc.view()
            self.assertFalse(svc._wake.is_set())

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

    def test_repeated_failure_of_the_same_input_backs_off(self):
        clock = FakeClock()
        attempts = {"n": 0}

        def always_fails():
            attempts["n"] += 1
            raise RuntimeError("source read failed")

        svc, _, state = service([], reconcile=always_fails, clock=clock)
        state["key"] = "k1"
        svc.check_now()
        clock.now += 61
        svc.check_now()
        self.assertEqual(attempts["n"], 2)
        clock.now += 61
        svc.check_now()
        self.assertEqual(attempts["n"], 2)
        clock.now += 60
        svc.check_now()
        self.assertEqual(attempts["n"], 3)

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


def test_authority_metadata_is_published_and_survives_a_restart(tmp_path):
    from webapp.ota_snapshot import OtaSnapshotService
    path = tmp_path / "ota-snapshot.json"
    meta = {"state": "degraded", "digest": "abc123abc123", "error": "timeout"}
    result = {"public": {}, "results": [], "links": {}, "data": {}, "authority": meta}
    service = OtaSnapshotService(key_fn=lambda: "k", reconcile_fn=lambda: result, persist_path=path, start=False)
    service.check_now()
    assert service.view()["current"]["authority"] == meta
    service.stop()
    reloaded = OtaSnapshotService(key_fn=lambda: "k", reconcile_fn=lambda: result, persist_path=path, start=False)
    assert reloaded.view()["current"]["authority"] == meta
    assert "CHULSOO" not in path.read_text(encoding="utf-8")
    reloaded.stop()


def test_snapshot_files_and_callbacks_wait_for_active_deployment_role(tmp_path, monkeypatch):
    route = tmp_path / 'route.json'
    path = tmp_path / 'snapshot.json'
    path.write_text('previous snapshot', encoding='utf-8')
    route.write_text(json.dumps({'port': 8751, 'paused': False}), encoding='utf-8')
    monkeypatch.setenv('WEBLEDGER_DEPLOYMENT_ROUTE', str(route))
    monkeypatch.setenv('WEBLEDGER_DEPLOYMENT_PORT', '8752')
    key = ['first']
    calls = []
    payload = {'public': {}, 'results': [], 'links': {}, 'data': {}}
    svc = OtaSnapshotService(key_fn=lambda: key[0], reconcile_fn=lambda: payload,
                             persist_path=path, on_published=lambda current: calls.append(current['key']),
                             start=False)
    svc.check_now()
    assert svc.view()['status'] == 'ready'
    assert path.read_text(encoding='utf-8') == 'previous snapshot'
    assert calls == []
    route.write_text(json.dumps({'port': 8752, 'paused': False}), encoding='utf-8')
    svc.check_now()
    assert json.loads(path.read_text(encoding='utf-8'))['key'] == 'first'
    assert calls == ['first']
    route.write_text(json.dumps({'port': 8752, 'paused': True}), encoding='utf-8')
    key[0] = 'second'
    svc.check_now()
    assert json.loads(path.read_text(encoding='utf-8'))['key'] == 'first'
    assert calls == ['first']
    route.write_text(json.dumps({'port': 8752, 'paused': False}), encoding='utf-8')
    svc.check_now()
    assert json.loads(path.read_text(encoding='utf-8'))['key'] == 'second'
    assert calls == ['first', 'second']


def test_source_check_error_revokes_freshness_until_same_source_is_checked_again():
    source = {'failed': False}
    calls = []
    def key():
        if source['failed']:
            raise OSError('synthetic source unavailable')
        return 'stable'
    def reconcile():
        calls.append('reconciled')
        return {'public': {}, 'results': [], 'links': {}, 'data': {}}
    svc = OtaSnapshotService(key_fn=key, reconcile_fn=reconcile, start=False)
    svc.check_now()
    assert svc.held()[1] is True
    source['failed'] = True
    svc.check_now()
    assert svc.view()['status'] == 'error'
    assert svc.view()['fresh'] is False
    assert svc.held()[1] is False
    assert svc.display_context()[1]['fresh'] is False
    source['failed'] = False
    svc.check_now()
    assert svc.view()['status'] == 'ready'
    assert svc.held()[1] is True
    assert svc.display_context()[1]['fresh'] is True
    assert calls == ['reconciled']


def test_changed_input_during_reconciliation_does_not_publish_or_claim_fresh(tmp_path):
    source = {'key': 'old', 'change_during_compute': False}
    calls = []
    path = tmp_path / 'snapshot.json'
    def reconcile():
        if source['change_during_compute']:
            source['key'] = 'after'
        return {'public': {}, 'results': [], 'links': {}, 'data': {}}
    svc = OtaSnapshotService(key_fn=lambda: source['key'], verify_key_fn=lambda: source['key'],
                             reconcile_fn=reconcile, persist_path=path,
                             on_published=lambda current: calls.append(current['key']), start=False)
    svc.check_now()
    assert calls == ['old']
    source.update(key='before', change_during_compute=True)
    svc.check_now()
    assert svc.view()['status'] == 'error'
    assert svc.held()[1] is False
    assert json.loads(path.read_text(encoding='utf-8'))['key'] == 'old'
    assert calls == ['old']
    source['change_during_compute'] = False
    svc.check_now()
    assert svc.view()['status'] == 'ready'
    assert svc.held()[1] is True
    assert json.loads(path.read_text(encoding='utf-8'))['key'] == 'after'
    assert calls == ['old', 'after']


def test_worker_promptly_retries_changed_input():
    source = {'key': 'before'}
    published = threading.Event()
    calls = []

    def reconcile():
        calls.append(source['key'])
        source['key'] = 'after'
        return {'public': {}, 'results': [], 'links': {}, 'data': {}}

    svc = OtaSnapshotService(key_fn=lambda: source['key'], verify_key_fn=lambda: source['key'],
                             reconcile_fn=reconcile, check_seconds=60,
                             on_published=lambda current: published.set())
    try:
        assert published.wait(5), 'changed input should be retried before the regular check interval'
        assert calls == ['before', 'after']
        assert svc.held()[1] is True
    finally:
        svc.stop()


def test_reverting_key_during_refresh_does_not_mark_held_snapshot_fresh():
    source = {'key': 'old'}
    entered, release = threading.Event(), threading.Event()
    payload = {'public': {}, 'results': [], 'links': {}, 'data': {}}
    def reconcile():
        if source['key'] == 'new':
            entered.set()
            assert release.wait(5)
        return payload
    svc = OtaSnapshotService(key_fn=lambda: source['key'], verify_key_fn=lambda: source['key'],
                             reconcile_fn=reconcile, start=False)
    svc.check_now()
    source['key'] = 'new'
    worker = threading.Thread(target=svc.check_now)
    try:
        worker.start()
        assert entered.wait(5)
        source['key'] = 'old'
        svc.check_now()
        assert svc.held()[1] is False
    finally:
        release.set()
        worker.join(5)
    assert not worker.is_alive()
    svc.check_now()
    assert svc.held()[1] is True


def test_ota_service_factory_checks_local_key_again_before_publication(tmp_path, monkeypatch):
    from types import SimpleNamespace
    from webapp import ota_payment_review as review
    state = {'key': 'before'}
    original = OtaSnapshotService
    monkeypatch.setattr(review.ota_snapshot, 'OtaSnapshotService',
                        lambda **kwargs: original(**{**kwargs, 'start': False}))
    monkeypatch.setattr(review, 'review_db_path', lambda: str(tmp_path / 'review.sqlite'))
    monkeypatch.setattr(review, 'input_key', lambda board: state['key'])
    monkeypatch.setattr(review, 'current_input_key', lambda board: state['key'])
    def reconcile(_board):
        state['key'] = 'after'
        return {'public': {}, 'results': [], 'links': {}, 'data': {}}
    monkeypatch.setattr(review, 'reconcile_in_child', reconcile)
    service = review.snapshot_service(SimpleNamespace())
    service.check_now()
    assert service.view()['status'] == 'error'
    assert service.held()[1] is False
    assert not (tmp_path / review.SNAPSHOT_FILE).exists()


def test_snapshot_is_republished_when_previous_release_regains_role(tmp_path, monkeypatch):
    route, snapshot = tmp_path / 'route.json', tmp_path / 'snapshot.json'
    monkeypatch.setenv('WEBLEDGER_DEPLOYMENT_ROUTE', str(route))
    monkeypatch.setenv('WEBLEDGER_DEPLOYMENT_PORT', '8751')
    calls = []
    payload = {'public': {}, 'results': [], 'links': {}, 'data': {}}
    svc = OtaSnapshotService(key_fn=lambda: 'old', reconcile_fn=lambda: payload,
                             persist_path=snapshot, on_published=lambda current: calls.append(current['key']),
                             start=False)
    route.write_text(json.dumps({'port': 8751, 'paused': False, 'generation': 'before'}), encoding='utf-8')
    svc.check_now()
    assert calls == ['old']
    route.write_text(json.dumps({'port': 8752, 'paused': False, 'generation': 'new'}), encoding='utf-8')
    svc.check_now()
    snapshot.write_text(json.dumps({'key': 'new'}), encoding='utf-8')
    route.write_text(json.dumps({'port': 8751, 'paused': False, 'generation': 'rollback'}), encoding='utf-8')
    svc.check_now()
    assert json.loads(snapshot.read_text(encoding='utf-8'))['key'] == 'old'
    assert calls == ['old', 'old']
    svc.check_now()
    assert calls == ['old', 'old']


def test_role_switch_waits_for_snapshot_callback_to_finish(tmp_path, monkeypatch):
    from webapp.deployment_role import route_lock
    route = tmp_path / 'route.json'
    route.write_text(json.dumps({'port': 8751, 'paused': False}), encoding='utf-8')
    monkeypatch.setenv('WEBLEDGER_DEPLOYMENT_ROUTE', str(route))
    monkeypatch.setenv('WEBLEDGER_DEPLOYMENT_PORT', '8751')
    entered, release, switched = threading.Event(), threading.Event(), threading.Event()
    def callback(_current):
        entered.set()
        assert release.wait(5)
    svc = OtaSnapshotService(key_fn=lambda: 'k',
                             reconcile_fn=lambda: {'public': {}, 'results': [], 'links': {}, 'data': {}},
                             on_published=callback, start=False)
    publishing = threading.Thread(target=svc.check_now)
    def switch():
        with route_lock(route):
            switched.set()
    switching = threading.Thread(target=switch)
    try:
        publishing.start()
        assert entered.wait(5)
        switching.start()
        assert not switched.wait(.2)
    finally:
        release.set()
        publishing.join(5)
        if switching.ident is not None:
            switching.join(5)
    assert not publishing.is_alive() and not switching.is_alive()
    assert switched.is_set()


def test_old_process_cannot_publish_after_new_process_takes_role(tmp_path):
    from webapp.deployment_role import route_lock
    route, snapshot = tmp_path / 'route.json', tmp_path / 'snapshot.json'
    route.write_text(json.dumps({'port': 8751, 'paused': False}), encoding='utf-8')
    driver = tmp_path / 'publisher.py'
    driver.write_text('''
import os, pathlib, sys, time
from webapp.ota_snapshot import OtaSnapshotService
root, name = pathlib.Path(sys.argv[1]), sys.argv[2]
def wait(path):
    until = time.monotonic() + 15
    while not path.exists():
        if time.monotonic() >= until: raise TimeoutError(str(path))
        time.sleep(.02)
def build():
    if name == "old":
        (root / "old-started").touch()
        wait(root / "release-old")
    return {"public": {}, "results": [], "links": {}, "data": {}}
svc = OtaSnapshotService(key_fn=lambda: name, reconcile_fn=build,
    persist_path=root / "snapshot.json", on_published=lambda current: (root / (name + "-published")).touch(),
    start=False)
svc.check_now()
if name == "new":
    (root / "new-ready").touch()
    wait(root / "activate-new")
    svc.check_now()
''', encoding='utf-8')
    def start(name, port):
        env = {**os.environ, 'WEBLEDGER_DEPLOYMENT_ROUTE': str(route), 'WEBLEDGER_DEPLOYMENT_PORT': str(port),
               'PYTHONPATH': os.pathsep.join(filter(None, (str(Path(__file__).resolve().parents[2]),
                                                           os.environ.get('PYTHONPATH', ''))))}
        return subprocess.Popen([sys.executable, str(driver), str(tmp_path), name], env=env,
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    def wait_for(path, process):
        deadline = time.monotonic() + 15
        while not path.exists():
            if process.poll() is not None:
                raise AssertionError(process.communicate()[1].decode('utf-8', errors='replace'))
            if time.monotonic() >= deadline:
                raise TimeoutError(str(path))
            time.sleep(.02)
    old = start('old', 8751)
    new = None
    try:
        wait_for(tmp_path / 'old-started', old)
        new = start('new', 8752)
        wait_for(tmp_path / 'new-ready', new)
        assert not snapshot.exists()
        with route_lock(route):
            route.write_text(json.dumps({'port': 8752, 'paused': False}), encoding='utf-8')
        (tmp_path / 'release-old').touch()
        (tmp_path / 'activate-new').touch()
        for process in (old, new):
            _, error = process.communicate(timeout=15)
            assert process.returncode == 0, error.decode('utf-8', errors='replace')
        assert json.loads(snapshot.read_text(encoding='utf-8'))['key'] == 'new'
        assert (tmp_path / 'new-published').exists()
        assert not (tmp_path / 'old-published').exists()
    finally:
        for process in (old, new):
            if process is not None and process.poll() is None:
                process.terminate()
                process.wait(timeout=5)
