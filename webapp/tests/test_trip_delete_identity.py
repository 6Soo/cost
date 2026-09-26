import copy
import json
import tempfile
import threading
import time
import unittest
from pathlib import Path

from webapp.ledger_store import LedgerStore, SaveError


def add_trip(store, tab_id="trip-demo-c"):
    store.conn.execute(
        "INSERT OR IGNORE INTO trip_tabs(tab_id, display_key, destination, starts_on,"
        " ends_on, prepared_on, prepared_by_name, archived, deleted, revision)"
        " VALUES (?,?,?,?,?,?,?,0,0,1)",
        (tab_id, tab_id, "합성 도착지", "2026-05-01", "2026-05-03", "", "테스트 소유자"),
    )
    store.conn.commit()


def database_state(store):
    state = {}
    for table in (
        "trip_tabs",
        "trip_tab_history",
        "trip_tab_requests",
        "board_rows",
        "board_revisions",
        "income_allocations",
        "ledger_outbox",
    ):
        state[table] = store.conn.execute(
            f"SELECT * FROM {table} ORDER BY 1"
        ).fetchall()
    state["operator_events"] = store.ledger.all_events()
    state["trip_a"] = store.tab_totals("trip-demo-a")
    state["trip_b"] = store.tab_totals("trip-demo-b")
    state["trip_c"] = store.tab_totals("trip-demo-c")
    return state


def close_store(store):
    store.ledger.close()
    store.close()


class TripDeleteRequestIdentityTests(unittest.TestCase):
    def make_store(self, directory):
        path = Path(directory) / "webledger.sqlite"
        store = LedgerStore(path)
        add_trip(store)
        self.assertTrue(path.with_suffix(".operator.sqlite").is_file())
        return store

    def apply_delete(self, store, request_id, snapshot, **overrides):
        payload = {
            "tab_id": "trip-demo-a",
            "expected_revision": snapshot["tab_revision"],
            "mode": "move-trip",
            "destination": "trip-demo-c",
            "snapshot": snapshot,
        }
        payload.update(overrides)
        return store.apply_tab_delete(
            tab_id=payload["tab_id"],
            expected_revision=payload["expected_revision"],
            mode=payload["mode"],
            destination=payload["destination"],
            snapshot=payload["snapshot"],
            client_request_id=request_id,
        )

    def test_same_request_retry_reuses_exact_result_without_new_effects(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as directory:
            store = self.make_store(directory)
            try:
                request_id = "trip-delete-same-request"
                snapshot = store.preview_tab_delete("trip-demo-a")["snapshot"]
                first = self.apply_delete(store, request_id, snapshot)
                first_state = database_state(store)
                reordered_snapshot = dict(reversed(list(snapshot.items())))
                retry = self.apply_delete(
                    store, request_id, reordered_snapshot,
                    destination="trip-demo-c",
                )
                self.assertEqual(retry, first)
                self.assertEqual(database_state(store), first_state)
                self.assertTrue(store.get_trip("trip-demo-a")["deleted"])
                self.assertIsNotNone(
                    store.ledger.find_by_client_request(
                        f"ledger-trip-{request_id}"
                    )
                )
            finally:
                close_store(store)

    def test_unused_mode_destination_is_normalized_before_binding(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as directory:
            store = self.make_store(directory)
            try:
                request_id = "trip-delete-unused-destination"
                snapshot = store.preview_tab_delete("trip-demo-a")["snapshot"]
                first = self.apply_delete(
                    store, request_id, snapshot,
                    mode="move-unclassified",
                    destination="trip-demo-c",
                )
                stored = json.loads(store.conn.execute(
                    "SELECT result_json FROM trip_tab_requests WHERE client_request_id=?",
                    (request_id,),
                ).fetchone()[0])
                self.assertIsNone(stored["request"]["destination"])
                first_state = database_state(store)
                retry = self.apply_delete(
                    store, request_id, snapshot,
                    mode="move-unclassified",
                    destination=None,
                )
                self.assertEqual(retry, first)
                self.assertEqual(database_state(store), first_state)
            finally:
                close_store(store)

    def test_same_request_id_rejects_every_changed_delete_field(self):
        cases = ("tab", "revision", "mode", "destination", "snapshot", "bool_int")
        for case in cases:
            with self.subTest(case=case), tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as directory:
                store = self.make_store(directory)
                try:
                    request_id = f"trip-delete-conflict-{case}"
                    snapshot = store.preview_tab_delete("trip-demo-a")["snapshot"]
                    self.apply_delete(store, request_id, snapshot)
                    first_state = database_state(store)
                    changed_snapshot = copy.deepcopy(snapshot)
                    overrides = {}
                    if case == "tab":
                        overrides["tab_id"] = "trip-demo-b"
                    elif case == "revision":
                        overrides["expected_revision"] = snapshot["tab_revision"] + 1
                    elif case == "mode":
                        overrides["mode"] = "move-unclassified"
                        overrides["destination"] = None
                    elif case == "destination":
                        overrides["destination"] = "trip-demo-b"
                    elif case == "snapshot":
                        changed_snapshot["request_probe"] = {"value": 1}
                    else:
                        changed_snapshot["tab_revision"] = True
                    with self.assertRaises(SaveError) as ctx:
                        self.apply_delete(
                            store, request_id, changed_snapshot, **overrides
                        )
                    self.assertEqual(ctx.exception.code, "REQUEST_ID_REUSED")
                    self.assertEqual(database_state(store), first_state)
                finally:
                    close_store(store)

    def test_legacy_delete_request_without_identity_is_not_reused(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as directory:
            store = self.make_store(directory)
            try:
                request_id = "trip-delete-legacy-request"
                snapshot = store.preview_tab_delete("trip-demo-a")["snapshot"]
                self.apply_delete(store, request_id, snapshot)
                result_json = store.conn.execute(
                    "SELECT result_json FROM trip_tab_requests WHERE client_request_id=?",
                    (request_id,),
                ).fetchone()[0]
                legacy = json.loads(result_json)
                legacy.pop("request")
                store.conn.execute(
                    "UPDATE trip_tab_requests SET result_json=? WHERE client_request_id=?",
                    (json.dumps(legacy, ensure_ascii=False, sort_keys=True), request_id),
                )
                store.conn.commit()
                legacy_state = database_state(store)
                with self.assertRaises(SaveError) as ctx:
                    self.apply_delete(store, request_id, snapshot)
                self.assertEqual(ctx.exception.code, "REQUEST_ID_REUSE_UNVERIFIED")
                self.assertEqual(database_state(store), legacy_state)
            finally:
                close_store(store)

    def test_concurrent_same_request_has_one_delete_effect(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as directory:
            path = Path(directory) / "webledger.sqlite"
            setup_store = LedgerStore(path)
            add_trip(setup_store)
            snapshot = setup_store.preview_tab_delete("trip-demo-a")["snapshot"]
            close_store(setup_store)

            first_store = LedgerStore(path)
            second_store = LedgerStore(path)
            gate_store = LedgerStore(path)
            barrier = threading.Barrier(3)
            results = []
            errors = []
            request_id = "trip-delete-concurrent-request"

            def worker(store):
                try:
                    barrier.wait(timeout=5)
                    results.append(self.apply_delete(store, request_id, snapshot))
                except BaseException as exc:
                    errors.append(exc)

            first_thread = threading.Thread(target=worker, args=(first_store,))
            second_thread = threading.Thread(target=worker, args=(second_store,))
            gate_store.conn.execute("BEGIN IMMEDIATE")
            try:
                first_thread.start()
                second_thread.start()
                barrier.wait(timeout=5)
                time.sleep(0.4)
                self.assertTrue(first_thread.is_alive())
                self.assertTrue(second_thread.is_alive())
            finally:
                gate_store.conn.execute("COMMIT")
            first_thread.join(timeout=10)
            second_thread.join(timeout=10)
            try:
                self.assertFalse(first_thread.is_alive())
                self.assertFalse(second_thread.is_alive())
                self.assertEqual(errors, [])
                self.assertEqual(len(results), 2)
                self.assertEqual(results[0], results[1])
                self.assertEqual(store_request_count(first_store, request_id), 1)
                self.assertEqual(
                    first_store.conn.execute(
                        "SELECT COUNT(*) FROM trip_tab_history"
                        " WHERE tab_id='trip-demo-a' AND change_kind='delete'"
                    ).fetchone()[0],
                    1,
                )
                moved = results[0]["moved_rows"]
                self.assertEqual(len(moved), len(set(moved)))
                self.assertEqual(
                    len(first_store.ledger.all_events()),
                    len(moved) + 1,
                )
            finally:
                close_store(first_store)
                close_store(second_store)
                close_store(gate_store)


def store_request_count(store, request_id):
    return store.conn.execute(
        "SELECT COUNT(*) FROM trip_tab_requests WHERE client_request_id=?",
        (request_id,),
    ).fetchone()[0]


if __name__ == "__main__":
    unittest.main()
