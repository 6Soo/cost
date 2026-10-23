"""Preview and confirm read the reconciled snapshot; they never reconcile, and they refuse when anything moved."""
import json
import os
import shutil
import sqlite3
import tempfile
import threading
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock
from urllib.parse import urlsplit

from app import ota_matching_defaults
from webapp import ota_payment_review
from webapp.ota_payment_review import CoreOtaPaymentBackend
from webapp.ota_snapshot import OtaSnapshotService
from webapp.card_flow import CardFlow
from webapp.tests.test_ota_payment_review import EVENT, FakeCorePayments, FakeCoreStore, primed


class SnapshotActionTests(unittest.TestCase):

    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(dir=Path(__file__).parent)
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.board_conn = sqlite3.connect(self.root / "board.sqlite", check_same_thread=False)
        self.board_conn.row_factory = sqlite3.Row
        self.addCleanup(self.board_conn.close)
        self.board_conn.execute("CREATE TABLE transactions (transaction_id TEXT, approval_date TEXT, amount_krw INTEGER, merchant TEXT)")
        self.board_conn.executemany("INSERT INTO transactions VALUES (?,?,?,?)", [
            ("card-02", "2026-09-04", 12525, "TRIP.COM"), ("card-03", "2026-09-04", 12500, "TRIP.COM")])
        self.board_conn.commit()
        self.board = SimpleNamespace(conn=self.board_conn, _lock=threading.RLock())
        self.review_path = self.root / "review.sqlite"
        Path(self.review_path).touch()
        self.mail = self.root / "ota-mail"
        self.mail.mkdir()
        (self.mail / "gmail-1.json").write_text('{"responses": []}', encoding="utf-8")
        self.sources = {"mail_directories": [str(self.mail)], "portal_databases": [], "reference_documents": []}
        FakeCoreStore.extra_links = {}
        self.addCleanup(lambda: setattr(FakeCoreStore, "extra_links", {}))
        FakeCoreStore.writer_calls = 0
        self.backend = CoreOtaPaymentBackend(self.board, str(self.review_path), read_only=False,
                                             payments=FakeCorePayments(), store_type=FakeCoreStore,
                                             sources=self.sources)
        self.addCleanup(self.backend.close)
        self.addCleanup(lambda: ota_payment_review.shutdown_snapshot_service(self.board))
        self.service = primed(self.board, self.backend)

    def _preview(self):
        return self.backend.preview(EVENT["ota_event_id"], "card-02")

    def test_preview_reads_the_snapshot_and_never_reconciles(self):
        with mock.patch.object(ota_payment_review, "reconcile_for", side_effect=AssertionError("reconciled")), \
             mock.patch.object(CoreOtaPaymentBackend, "_data", side_effect=AssertionError("full data")), \
             mock.patch("app.ota_payments._parse_mail_events", side_effect=AssertionError("mail parsed")):
            preview = self._preview()
        self.assertEqual(preview["snapshot_generation"], 1)
        self.assertTrue(preview["preview_digest"])

    def test_review_api_and_expense_holds_read_the_same_published_generation(self):
        class Host:
            headers = {}
            def _send_json(inner, payload, status=200):
                inner.response = (status, payload)

        host = Host()
        env = {"WEBLEDGER_OTA_REVIEW_MODE":"isolated",
               "WEBLEDGER_OTA_REVIEW_DB":str(self.review_path)}
        with mock.patch.dict(os.environ, env), \
             mock.patch.object(CoreOtaPaymentBackend, "_data", side_effect=AssertionError("request recomputed")):
            self.assertTrue(ota_payment_review.dispatch(
                host, urlsplit("/api/imports/ota"), backend=self.backend))
        response = host.response[1]
        current, fresh = self.service.held()
        self.assertEqual(response["generation"], current["generation"])
        self.assertEqual(response["snapshot_key"], current["key"][:12])
        self.assertTrue(fresh)

        flow = CardFlow.__new__(CardFlow)
        flow.board = self.board
        with mock.patch.object(ota_payment_review.CoreOtaPaymentBackend, "from_host",
                               return_value=SimpleNamespace(store=SimpleNamespace(group_pins=lambda: []),
                                                            close=lambda: None)):
            holds = flow._ota_group_holds_base()
        self.assertNotIn("card-02", holds)

    def test_source_content_change_makes_the_preview_stale(self):
        (self.mail / "gmail-1.json").write_text('{"responses": [ ]}', encoding="utf-8")
        with self.assertRaises(ota_payment_review.StalePreviewError):
            self._preview()

    def test_card_ledger_change_makes_the_preview_stale(self):
        self.board_conn.execute("UPDATE transactions SET amount_krw=12526 WHERE transaction_id='card-02'")
        self.board_conn.commit()
        with self.assertRaises(ota_payment_review.StalePreviewError):
            self._preview()

    def test_review_database_change_makes_the_preview_stale(self):
        FakeCoreStore.extra_links = {"evt-other": {"transaction_id": "card-03", "source_digest": "other"}}
        with self.assertRaises(ota_payment_review.StalePreviewError):
            self._preview()

    def test_rule_configuration_change_makes_the_preview_stale(self):
        defaults = ota_matching_defaults.load_defaults()
        changed = dict(defaults, _synthetic_marker=1)
        with mock.patch.object(ota_matching_defaults, "load_defaults", return_value=changed):
            with self.assertRaises(ota_payment_review.StalePreviewError):
                self._preview()
    def test_same_generation_confirms_once(self):
        preview = self._preview()
        self.backend.confirm(EVENT["ota_event_id"], "card-02", preview["preview_digest"],
                             request_id="act-ok", user="synthetic-owner")
        self.assertEqual(FakeCoreStore.writer_calls, 1)

    def test_a_generation_change_after_preview_refuses_the_confirm_without_writing(self):
        preview = self._preview()
        FakeCoreStore.extra_links = {"evt-other": {"transaction_id": "card-03", "source_digest": "other"}}
        with self.assertRaises(ota_payment_review.StalePreviewError):
            self.backend.confirm(EVENT["ota_event_id"], "card-02", preview["preview_digest"],
                                 request_id="act-moved", user="synthetic-owner")
        self.assertEqual(FakeCoreStore.writer_calls, 0)

    def test_a_group_occupancy_change_after_preview_refuses_the_confirm(self):
        preview = self._preview()

        class Pinned(FakeCoreStore):
            def group_pins(self):
                return [{"group_id": "g1", "event_ids": ["evt-x"], "card_ids": ["card-02"],
                         "mapping": {}, "confirmed_by": "owner", "version": 1, "order_snapshot": {}}]

        writer = CoreOtaPaymentBackend(self.board, str(self.review_path), read_only=False,
                                       payments=FakeCorePayments(), store_type=Pinned, sources=self.sources)
        self.addCleanup(writer.close)
        with self.assertRaises(ota_payment_review.StalePreviewError):
            writer.confirm(EVENT["ota_event_id"], "card-02", preview["preview_digest"],
                           request_id="act-group", user="synthetic-owner")
        self.assertEqual(FakeCoreStore.writer_calls, 0)

    def test_a_missing_snapshot_answers_not_ready_and_never_computes(self):
        self.service.stop()
        self.board._ota_snapshot_service = OtaSnapshotService(
            key_fn=lambda: "unknown", reconcile_fn=lambda: (_ for _ in ()).throw(RuntimeError("x")), start=False)
        with self.assertRaises(ota_payment_review.OtaSnapshotNotReady):
            self._preview()


    def test_a_retry_of_a_recorded_confirm_returns_the_record_even_after_the_snapshot_moved(self):
        preview = self._preview()

        class Recorded(FakeCoreStore):
            def prior_confirmation(self, request_id):
                return {"status": "MATCHED_USER", "request_id": request_id} if request_id == "act-retry" else None

        writer = CoreOtaPaymentBackend(self.board, str(self.review_path), read_only=False,
                                       payments=FakeCorePayments(), store_type=Recorded, sources=self.sources)
        self.addCleanup(writer.close)
        FakeCoreStore.extra_links = {"evt-other": {"transaction_id": "card-03", "source_digest": "other"}}
        result = writer.confirm(EVENT["ota_event_id"], "card-02", preview["preview_digest"],
                                request_id="act-retry", user="synthetic-owner")
        self.assertEqual(result, {"status": "MATCHED_USER", "request_id": "act-retry"})
        self.assertEqual(FakeCoreStore.writer_calls, 0)

    def test_a_post_takes_the_user_from_the_decided_session_when_the_handler_states_none(self):
        class Host:
            def __init__(self):
                self.headers = {"X-CSRF-Token": "tok"}
                self.sent = []

            def _send_json(self, payload, status=200):
                self.sent.append((status, payload))

        host = Host()
        body = json.dumps({"event_id": EVENT["ota_event_id"], "transaction_id": "card-02",
                           "request_id": "session-user"}).encode("utf-8")
        env = {"WEBLEDGER_OTA_REVIEW_MODE": "isolated", "WEBLEDGER_OTA_REVIEW_DB": str(self.review_path)}
        with mock.patch.dict(os.environ, env), \
             mock.patch("webapp.ledger_board.current_session",
                        return_value=SimpleNamespace(user_id="synthetic-owner")):
            ota_payment_review.dispatch(host, urlsplit("/api/imports/ota/preview"), raw=body, csrf="tok",
                                        backend=self.backend)
        self.assertEqual(host.sent[0][0], 200)
        self.assertIn("preview_digest", host.sent[0][1])


class WorkerLifecycleTests(unittest.TestCase):

    def _service(self, **kwargs):
        return OtaSnapshotService(key_fn=lambda: "k", reconcile_fn=lambda: {"public": {}, "results": [],
                                                                             "links": {}, "data": {}}, **kwargs)

    def test_stop_joins_the_worker_and_repeated_stop_is_safe(self):
        service = self._service()
        time.sleep(0.05)
        worker = service._thread
        self.assertTrue(service.worker_alive())
        service.stop()
        self.assertFalse(worker.is_alive())
        self.assertFalse(service.worker_alive())
        service.stop()
        self.assertFalse(worker.is_alive())

    def test_a_restart_starts_one_worker_only(self):
        service = self._service()
        self.addCleanup(service.stop)
        first = service._thread
        service.ensure_started()
        service.ensure_started()
        self.assertIs(service._thread, first)
        self.assertEqual(sum(1 for t in threading.enumerate() if t is first), 1)

    def test_a_stopped_service_never_starts_again(self):
        service = self._service()
        service.stop()
        service.ensure_started()
        self.assertFalse(service.worker_alive())
    def test_no_reconciliation_runs_after_stop(self):
        calls = []
        service = OtaSnapshotService(key_fn=lambda: "k", reconcile_fn=lambda: calls.append(1) or
                                     {"public": {}, "results": [], "links": {}, "data": {}}, start=False)
        service.stop()
        service.check_now()
        self.assertEqual(calls, [])

    def test_temporary_snapshot_folder_is_removable_after_stop(self):
        directory = tempfile.mkdtemp(dir=Path(__file__).parent)
        self.addCleanup(lambda: shutil.rmtree(directory, ignore_errors=True))
        persist = Path(directory) / "ota-snapshot.json"
        service = OtaSnapshotService(key_fn=lambda: "k", reconcile_fn=lambda: {"public": {"events": []},
                                                                               "results": [], "links": {},
                                                                               "data": {}},
                                     persist_path=persist)
        time.sleep(0.05)
        service.stop()
        shutil.rmtree(directory)
        self.assertFalse(os.path.exists(directory))
