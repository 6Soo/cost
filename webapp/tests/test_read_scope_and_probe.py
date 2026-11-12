import http.client
import os
import tempfile
import threading
import unittest
from pathlib import Path

from webapp import access_control
from webapp import ledger_board as board_mod
from webapp import read_scope
from webapp.ledger_store import LedgerStore


class ReadScopeTests(unittest.TestCase):
    def test_remember_reuses_inside_a_scope_and_recomputes_outside(self):
        calls = []

        @read_scope.scoped
        def render():
            first = read_scope.remember("k", lambda: calls.append(1) or "a")
            second = read_scope.remember("k", lambda: calls.append(1) or "b")
            return first, second

        self.assertEqual(render(), ("a", "a"))
        self.assertEqual(len(calls), 1)
        self.assertEqual(read_scope.remember("k", lambda: "fresh"), "fresh")


class LivenessProbeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self._prev_db = os.environ.get("WEBLEDGER_DB")
        os.environ["WEBLEDGER_DB"] = str(Path(self.tmp) / "probe.sqlite")
        self.store = LedgerStore(Path(os.environ["WEBLEDGER_DB"]), seed_demo=False)
        self.access = access_control.attach_to_ledger_store(self.store)
        board_mod.bind_store(self.store)
        self.server = board_mod.serve(port=0, with_worker=False, seed_demo=False)
        self.port = self.server.server_address[1]
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        if self._prev_db is None:
            os.environ.pop("WEBLEDGER_DB", None)
        else:
            os.environ["WEBLEDGER_DB"] = self._prev_db

    def test_healthz_answers_while_the_store_lock_is_held_by_a_slow_request(self):
        status = {}

        def probe():
            conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
            conn.request("GET", "/healthz")
            status["code"] = conn.getresponse().status
            conn.close()

        with self.server.store_lock:
            worker = threading.Thread(target=probe)
            worker.start()
            worker.join(3)
            self.assertFalse(worker.is_alive(), "healthz waited behind the store lock")
        self.assertEqual(status.get("code"), 200)

    def test_store_lock_wait_is_recorded_for_real_http_request(self):
        from unittest.mock import patch
        from app import request_metrics
        # The registry is process-global and bounded, so samples from other
        # requests would pollute a single-request measurement. Isolate it.
        with patch.object(request_metrics, '_REGISTRY', request_metrics.MetricsWindow()):
            before = request_metrics.summary().get('db_lock_wait.db_lock_wait', {}).get('samples', 0)
            response = {}

            def request():
                conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
                conn.request("GET", "/board")
                response["code"] = conn.getresponse().status
                conn.close()

            self.server.store_lock.acquire()
            worker = threading.Thread(target=request)
            worker.start()
            # Hold the lock with enough margin that the handler is queued on it
            # before release, so the recorded wait is a real delay, not a race.
            worker.join(0.5)
            self.server.store_lock.release()
            worker.join(5)
            self.assertFalse(worker.is_alive())
            self.assertEqual(response.get("code"), 200)
            after = request_metrics.summary()['db_lock_wait.db_lock_wait']
            self.assertEqual(after['samples'], before + 1)
            self.assertGreaterEqual(after['p50_ms'], 50)


if __name__ == "__main__":
    unittest.main()
