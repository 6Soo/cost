"""The store used by one board server must stay local to its request."""

import tempfile
import threading
import unittest
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from webapp import ledger_board as board


class LedgerServerStoreIsolationTests(unittest.TestCase):
    def test_two_live_servers_never_cross_read_each_other_store(self):
        root = Path(tempfile.mkdtemp(prefix="ledger-server-isolation-"))
        server_a = board.serve(
            port=0, db_path=root / "a.sqlite", with_worker=False, seed_demo=True)
        server_b = board.serve(
            port=0, db_path=root / "b.sqlite", with_worker=False, seed_demo=True)
        threads = []
        try:
            for server, marker in (
                    (server_a, "SERVER-A-MARK"),
                    (server_b, "SERVER-B-MARK")):
                server.card_store.conn.execute(
                    "UPDATE trip_tabs SET destination=? WHERE tab_id=?",
                    (marker, "trip-demo-a"),
                )
                server.card_store.conn.commit()
                thread = threading.Thread(
                    target=server.serve_forever, daemon=True)
                thread.start()
                threads.append(thread)

            entered = threading.Barrier(2)
            original_trips_page = board.trips_page

            def wait_then_render(*args, **kwargs):
                entered.wait(timeout=5)
                return original_trips_page(*args, **kwargs)

            board.trips_page = wait_then_render

            def fetch(server):
                with urllib.request.urlopen(
                        f"http://127.0.0.1:{server.server_address[1]}/trips",
                        timeout=5) as response:
                    return response.read().decode("utf-8")

            with ThreadPoolExecutor(max_workers=2) as pool:
                bodies = list(pool.map(fetch, (server_a, server_b)))
            board.trips_page = original_trips_page

            for body, own_marker, other_marker in zip(
                    bodies,
                    ("SERVER-A-MARK", "SERVER-B-MARK"),
                    ("SERVER-B-MARK", "SERVER-A-MARK")):
                self.assertIn(own_marker, body)
                self.assertNotIn(other_marker, body)
        finally:
            if "original_trips_page" in locals():
                board.trips_page = original_trips_page
            for server in (server_a, server_b):
                server.shutdown()
                server.server_close()
            for thread in threads:
                thread.join(timeout=5)
            for server in (server_a, server_b):
                server.card_store.close()
            board.bind_store(None)

    def test_one_server_serializes_sqlite_connection_use(self):
        root = Path(tempfile.mkdtemp(prefix="ledger-server-connection-"))
        server = board.serve(
            port=0, db_path=root / "board.sqlite", with_worker=False, seed_demo=True)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        start = threading.Barrier(8)

        def fetch(_):
            start.wait(timeout=5)
            with urllib.request.urlopen(
                    f"http://127.0.0.1:{server.server_address[1]}/trips",
                    timeout=5) as response:
                return response.status

        try:
            with ThreadPoolExecutor(max_workers=8) as pool:
                statuses = list(pool.map(fetch, range(8)))
            self.assertEqual(statuses, [200] * 8)
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)
            server.card_store.close()
            board.bind_store(None)


if __name__ == "__main__":
    unittest.main()
