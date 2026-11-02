"""Synthetic contract tests for the isolated OTA payment review surface."""
import json
import os
import sqlite3
import tempfile
import threading
import unittest
from contextlib import ExitStack
from typing import Any
from http.server import BaseHTTPRequestHandler, HTTPServer
from unittest import mock
from types import SimpleNamespace
from pathlib import Path
from urllib.parse import urlsplit
import urllib.error
import urllib.request

from webapp import ota_payment_review
from webapp import card_flow

SYNTHETIC_REVIEW_DB = str(Path(tempfile.gettempdir()) / "cost-synthetic-ota-review.sqlite")


EVENT: dict[str, Any] = {
    "ota_event_id": "evt-synth-001",
    "provider": "Synthetic Stay",
    "booking_ref": "BOOK-SYNTH-001",
    "event_type": "charge",
    "paid_on": "2026-09-04",
    "amount": 12500,
    "currency": "KRW",
    "amount_krw": 12500,
    "service_period": "2026-10-01 to 2026-10-02",
    "item": "Synthetic room",
    "status": "HOLD_AMBIGUOUS",
    "reason": "Two same-date candidates",
    "source_digest": "digest-synth-001",
}


def cards(count=12) -> list[dict[str, Any]]:
    return [{
        "transaction_id": f"card-{index:02d}",
        "issuer": "Synthetic Bank",
        "card_kind": "credit",
        "card_tail": "2042",
        "approval_date": "2026-09-04",
        "posting_date": "2026-09-05",
        "merchant": f"Merchant {index:02d}",
        "amount_krw": 12525 if index == 2 else 12500 + index,
        "foreign_amount": "12.50 USD",
        "currency": "USD",
        "authorization_id": f"AUTH-{index:02d}",
        "approval_number": f"AUTH-{index:02d}",
        "cancellation_status": "not_cancelled",
        "refund_status": "no_refund",
        "transaction_direction": "purchase",
        "already_linked_event_id": "" if index != 11 else "evt-synth-other",
    } for index in range(count)]


def primed(board, backend):
    """A reconciled snapshot for a synthetic board, built by the same functions the worker uses."""
    from webapp.ota_snapshot import OtaSnapshotService
    service = OtaSnapshotService(key_fn=lambda: ota_payment_review.input_key_for(backend),
                                 reconcile_fn=lambda: ota_payment_review.reconcile_for(backend), start=False)
    board._ota_snapshot_service = service
    service.check_now()
    return service


class FakeBackend:
    def __init__(self):
        self.calls = []
        self.stale = False
        self.proposal_action = None

    def snapshot(self):
        self.calls.append(("snapshot",))
        event = {**EVENT, "source_inventory": {"secret": "private-fixture-path"},
                 "source_digest": "secret-digest", "raw_row_json": "secret-event",
                 "card_candidate_count": len(cards())}
        rows = [{**row, "raw_row_json": "secret-card", "classification_private": "secret"}
                for row in cards()]
        return {"events": [event], "cards_by_event": {EVENT["ota_event_id"]: rows},
                "proposals": [{"proposal_id": "proposal-synth-001", "question": "Use this match once?",
                               "status": "pending", "conditions": {"provider": "Synthetic Stay"}}]}

    def preview(self, event_id, transaction_id):
        self.calls.append(("preview", event_id, transaction_id))
        return {"event_id": event_id, "transaction_id": transaction_id,
                "preview_digest": "preview-synth-current", "difference_krw": 25,
                "event_amount_krw": 12500, "card_amount_krw": 12525}

    def confirm(self, event_id, transaction_id, preview_digest, *, request_id, user):
        self.calls.append(("confirm", event_id, transaction_id, preview_digest, request_id, user))
        if self.stale or preview_digest != "preview-synth-current":
            raise ota_payment_review.StalePreviewError
        return {"status": "MATCHED_USER", "transaction_id": transaction_id,
                "proposal_id": "proposal-synth-001"}

    def answer_proposal(self, proposal_id, action, *, user, conditions=None):
        self.calls.append(("proposal", proposal_id, action, user, conditions))
        self.proposal_action = action
        return {"proposal_id": proposal_id, "status": "answered_once" if action == "once" else "answered",
                "action": action}

    def confirm_group_order(self, event_ids, *, user, replace=False, request_id=None):
        self.calls.append(("confirm_group_order", list(event_ids), user, replace, request_id))
        return {"status":"frozen", "event_ids":list(event_ids)}

    def refresh_after_import(self, transaction_ids):
        self.calls.append(("refresh_after_import", list(transaction_ids)))

    def cards_for_event(self, event_id):
        self.calls.append(("cards_for_event", event_id))
        # Return processed card data similar to real implementation
        processed = []
        for row in cards():
            r = {**row, "raw_row_json": "secret-card", "classification_private": "secret"}
            r.setdefault("approval_number", r.get("approval_number") or r.get("authorization_id"))
            r.setdefault("currency", r.get("foreign_currency") or r.get("currency"))
            r["direction"] = (r.get("transaction_direction") or r.get("direction") or "미확인")
            if r.get("already_linked_event_id") and not r.get("already_linked_label"):
                r["already_linked_label"] = "다른 예약"
            processed.append(r)
        return processed


class FakeHandler:
    def __init__(self, backend, path, raw=None, csrf="token-synth", supplied_csrf="token-synth"):
        self.backend = backend
        self.path = path
        self.raw = raw
        self.headers = {"X-CSRF-Token": supplied_csrf}
        self.csrf = csrf
        self.response: Any = None

    def current_user_id(self):
        return "synthetic-owner"

    def _send(self, body, code=200):
        self.response = (code, "text/html", body)

    def _send_json(self, payload, code=200):
        self.response = (code, "application/json", payload)


class FakeCoreStore:
    writer_calls = 0
    last_store: Any = None

    def __init__(self, _path):
        self.calls = []
        type(self).last_store = self

    extra_links: dict = {}

    def links(self):
        return {
            "evt-exact": {"transaction_id": "card-01", "source_digest": "exact-digest"},
            "evt-user": {"transaction_id": "card-03", "source_digest": "old-user-digest"},
            **type(self).extra_links,
        }

    def close(self):
        self.calls.append(("close",))

    def active_rules(self):
        return []

    def proposals(self):
        return [{"proposal_id": "proposal-synth-001", "status": "pending",
                 "question": "Use this match once?", "conditions": {}}]

    def preview(self, _event, _transaction):
        return {"preview_digest": "core-preview-synth", "event_amount_krw": 12500,
                "card_amount_krw": 12525, "difference_krw": -25}

    def confirm(self, _event, _transaction, preview_digest, *, request_id, user, allocations=None):
        type(self).writer_calls += 1
        self.calls.append(("confirm", preview_digest, request_id, user, allocations))
        return {"status": "MATCHED_USER"}

    def answer_proposal(self, proposal_id, action, *, user, conditions=None):
        type(self).writer_calls += 1
        self.calls.append(("answer", proposal_id, action, user, conditions))
        return {"proposal_id": proposal_id, "status": "answered"}

    def refresh(self, _events, _transactions, *, changed_transaction_ids=None, changed_event_ids=None):
        type(self).writer_calls += 1
        self.calls.append(("refresh", changed_transaction_ids, changed_event_ids))
        return {"changed_transaction_ids": changed_transaction_ids,
                "changed_event_ids": changed_event_ids}


class FakeCorePayments:
    occupied_transaction = "card-00"

    def build_ota_payment_events(self, _sources):
        user_event = {**EVENT, "ota_event_id": "evt-user", "source_digest": "new-user-digest",
                      "booking_ref": "BOOK-USER"}
        return [dict(EVENT), user_event]

    def match_ota_payment_events(self, events, _transactions, *, existing_links=None, rules=None):
        hold = {**events[0], "status": "HOLD_AMBIGUOUS", "reason": "Two same-date candidates"}
        auto = {"ota_event_id": "evt-auto", "status": "MATCHED_AUTO",
                "transaction_id": self.occupied_transaction}
        matched_user = {**events[1], "status": "MATCHED_USER", "transaction_id": "card-03",
                        "evidence_changed": False}
        return [hold, auto, matched_user]

    def same_date_cards(self, event, transactions, *, links=None):
        result = []
        for transaction in transactions:
            if transaction.get("approval_date") != event.get("paid_on"):
                continue
            row = dict(transaction)
            row["already_linked_event_id"] = ""
            for event_id, link in (links or {}).items():
                if link.get("transaction_id") == row.get("transaction_id"):
                    row["already_linked_event_id"] = event_id
            result.append(row)
        return result


def _local_review_request(backend, path, payload=None):
    class Handler(BaseHTTPRequestHandler):
        def current_user_id(self):
            return "synthetic-acceptance-owner"
        def _send_json(self, value, status=200):
            body = json.dumps(value).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        def _backend_for_request(self):
            return backend() if callable(backend) and not hasattr(backend, "snapshot") else backend
        def do_POST(self):
            body = self.rfile.read(int(self.headers.get("Content-Length", "0")))
            request_backend = self._backend_for_request()
            try:
                ota_payment_review.dispatch(self, urlsplit(self.path), raw=body,
                    csrf="synthetic-acceptance-csrf", backend=request_backend)
            finally:
                if request_backend is not backend and callable(getattr(request_backend, "close", None)):
                    request_backend.close()
        def do_GET(self):
            request_backend = self._backend_for_request()
            try:
                ota_payment_review.dispatch(self, urlsplit(self.path), csrf="", backend=request_backend)
            finally:
                if request_backend is not backend and callable(getattr(request_backend, "close", None)):
                    request_backend.close()
        def log_message(self, *_args):
            pass

    server = HTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        url = f"http://127.0.0.1:{server.server_port}{path}"
        if payload is None:
            request = urllib.request.Request(url, method="GET")
        else:
            request = urllib.request.Request(url, data=json.dumps(payload).encode("utf-8"), method="POST",
                headers={"Content-Type":"application/json", "X-CSRF-Token":"synthetic-acceptance-csrf"})
        try:
            with urllib.request.urlopen(request, timeout=5) as response:
                return response.status, json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as error:
            return error.code, json.loads(error.read().decode("utf-8"))
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


class OtaPaymentReviewTests(unittest.TestCase):
    def test_reservation_routes_are_separate_csrf_protected_and_revision_bound(self):
        class ReservationBackend(FakeBackend):
            def reservation_preview(self, event_id, transaction_id):
                self.calls.append(("reservation_preview", event_id, transaction_id))
                return {"preview_digest": "reservation-digest", "expected_revision": 4,
                        "payment_verified": False}

            def reservation_confirm(self, event_id, transaction_id, digest, *, expected_revision,
                                    request_id, user):
                self.calls.append(("reservation_confirm", event_id, transaction_id, digest,
                                   expected_revision, request_id, user))
                return {"status": "USER_CONFIRMED", "transaction_id": transaction_id,
                        "payment_verified": False}

        backend = ReservationBackend()
        preview = FakeHandler(backend, "/api/imports/ota/reservation/preview",
                              json.dumps({"event_id": "toyoko-syn", "transaction_id": "card-syn"}).encode())
        ota_payment_review.dispatch(preview, urlsplit(preview.path), raw=preview.raw,
                                    csrf="token-synth", backend=backend)
        self.assertEqual(preview.response[0], 200)
        self.assertFalse(preview.response[2]["payment_verified"])
        confirm_body = {"event_id": "toyoko-syn", "transaction_id": "card-syn",
                        "preview_digest": "reservation-digest", "expected_revision": 4,
                        "request_id": "reservation-request"}
        confirm = FakeHandler(backend, "/api/imports/ota/reservation/confirm",
                              json.dumps(confirm_body).encode())
        ota_payment_review.dispatch(confirm, urlsplit(confirm.path), raw=confirm.raw,
                                    csrf="token-synth", backend=backend)
        self.assertEqual(confirm.response[0], 200)
        self.assertEqual(backend.calls[-1], ("reservation_confirm", "toyoko-syn", "card-syn",
            "reservation-digest", 4, "reservation-request", "synthetic-owner"))
        bad_body = {**confirm_body, "expected_revision": True}
        bad = FakeHandler(backend, "/api/imports/ota/reservation/confirm", json.dumps(bad_body).encode())
        ota_payment_review.dispatch(bad, urlsplit(bad.path), raw=bad.raw,
                                    csrf="token-synth", backend=backend)
        self.assertEqual(bad.response[0], 422)
        denied = FakeHandler(backend, "/api/imports/ota/reservation/confirm",
                             json.dumps(confirm_body).encode(), supplied_csrf="wrong")
        ota_payment_review.dispatch(denied, urlsplit(denied.path), raw=denied.raw,
                                    csrf="token-synth", backend=backend)
        self.assertEqual(denied.response[0], 403)

    def setUp(self):
        FakeCorePayments.occupied_transaction = "card-00"
        self.environment = mock.patch.dict(os.environ, {
            "WEBLEDGER_OTA_REVIEW_MODE": "isolated",
            "WEBLEDGER_OTA_REVIEW_DB": SYNTHETIC_REVIEW_DB,
        })
        self.environment.start()
        self.addCleanup(self.environment.stop)

    def test_default_is_disabled_and_isolated_mode_requires_a_separate_review_database(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            self.assertFalse(ota_payment_review.enabled())
        with mock.patch.dict(os.environ, {"WEBLEDGER_OTA_REVIEW_MODE": "isolated"}, clear=True):
            self.assertFalse(ota_payment_review.enabled())
        with mock.patch.dict(os.environ, {
            "WEBLEDGER_OTA_REVIEW_MODE": "isolated",
            "WEBLEDGER_OTA_REVIEW_DB": SYNTHETIC_REVIEW_DB,
        }, clear=True):
            self.assertTrue(ota_payment_review.enabled())

    def test_old_manual_link_id_crosswalk_requires_one_matching_saved_payment(self):
        saved = {"legacy-event": {"source_digest":"same-proof", "provider":"agoda",
                                  "booking_ref":"BOOK-A", "event_type":"charge",
                                  "amount_krw":50000, "card_last4":"1234"}}
        events = [
            {"ota_event_id":"new-a", "source_digest":"same-proof", "provider":"agoda",
             "booking_ref":"BOOK-A", "event_type":"charge", "amount_krw":50000, "card_last4":"1234"},
            {"ota_event_id":"new-b", "source_digest":"same-proof", "provider":"agoda",
             "booking_ref":"BOOK-B", "event_type":"charge", "amount_krw":70000, "card_last4":"5678"},
        ]
        links, crosswalk = ota_payment_review._manual_link_crosswalk(
            events, {"legacy-event":{"transaction_id":"card-pinned", "status":"MATCHED_USER"}}, saved)
        self.assertEqual(links, {"new-a":{"transaction_id":"card-pinned", "status":"MATCHED_USER"}})
        self.assertEqual(crosswalk, {"legacy-event":"new-a"})
        ambiguous, no_crosswalk = ota_payment_review._manual_link_crosswalk(
            [events[0], {**events[0], "ota_event_id":"new-a-copy"}],
            {"legacy-event":{"transaction_id":"card-pinned"}}, saved)
        self.assertIn("legacy-event", ambiguous)
        self.assertEqual(no_crosswalk, {})
        persisted, saved_crosswalk = ota_payment_review._manual_link_crosswalk(
            [events[0], {**events[0], "ota_event_id":"new-a-copy"}],
            {"legacy-event":{"transaction_id":"card-pinned"}}, saved,
            {"legacy-event":{"current_event_id":"new-a-copy", "evidence_digest":"same-proof"}})
        self.assertEqual(persisted, {"new-a-copy":{"transaction_id":"card-pinned"}})
        self.assertEqual(saved_crosswalk, {"legacy-event":"new-a-copy"})
        changed, rejected_crosswalk = ota_payment_review._manual_link_crosswalk(
            [{**events[0], "ota_event_id":"new-a-copy", "amount_krw":51000}],
            {"legacy-event":{"transaction_id":"card-pinned"}}, saved,
            {"legacy-event":{"current_event_id":"new-a-copy", "evidence_digest":"same-proof"}})
        self.assertEqual(changed, {"legacy-event":{"transaction_id":"card-pinned"}})
        self.assertEqual(rejected_crosswalk, {})

    def test_get_renders_every_card_and_proposal_without_calling_a_write_method(self):
        backend = FakeBackend()
        handler = FakeHandler(backend, "/api/imports/ota")
        handled = ota_payment_review.dispatch(handler, urlsplit(handler.path), csrf="token-synth", backend=backend)
        self.assertTrue(handled)
        self.assertEqual(handler.response[0], 200)
        snapshot = handler.response[2]
        # Main snapshot no longer includes cards (lazy-loaded via /cards/<event_id>)
        self.assertEqual(snapshot["cards_by_event"], {})
        self.assertIn("다음 결제에도 적용할까요?", snapshot["proposals"][0]["question"])
        # Verify card_candidate_count is present for UI badge
        self.assertGreaterEqual(snapshot["events"][0]["card_candidate_count"], 12)
        serialized = json.dumps(snapshot)
        for forbidden in ("raw_row_json", "classification_private", "source_inventory",
                          "private-fixture-path", "secret-event", "source_digest"):
            self.assertNotIn(forbidden, serialized)
        self.assertEqual([call[0] for call in backend.calls], ["snapshot"])
        # Also test the new cards endpoint
        handler2 = FakeHandler(backend, "/api/imports/ota/cards/" + EVENT["ota_event_id"])
        handled2 = ota_payment_review.dispatch(handler2, urlsplit(handler2.path), backend=backend)
        self.assertTrue(handled2)
        self.assertEqual(handler2.response[0], 200)
        cards_response = handler2.response[2]
        self.assertEqual(cards_response["event_id"], EVENT["ota_event_id"])
        self.assertEqual(len(cards_response["cards"]), 12)
        self.assertEqual(cards_response["cards"][11]["merchant"], "Merchant 11")
        self.assertEqual(cards_response["cards"][11]["approval_number"], "AUTH-11")
        self.assertEqual(cards_response["cards"][11]["already_linked_event_id"], "evt-synth-other")
        self.assertEqual(cards_response["cards"][11]["already_linked_label"], "다른 예약")
        # Verify internal/private fields are NOT leaked via cards endpoint
        serialized_cards = json.dumps(cards_response)
        for forbidden in ("raw_row_json", "classification_private", "source_inventory",
                          "private-fixture-path", "secret-event", "source_digest"):
            self.assertNotIn(forbidden, serialized_cards)
        # Verify allowed fields are present
        self.assertIn("transaction_id", serialized_cards)
        self.assertIn("selection_disabled", serialized_cards)
        self.assertIn("already_linked_event_id", serialized_cards)
        self.assertIn("approval_number", serialized_cards)

    def test_owner_diagnostic_reads_public_snapshot_without_reconciliation_or_private_source_data(self):
        backend = FakeBackend()
        handler = FakeHandler(backend, "/api/imports/ota/diagnostics/evt-synth-001")
        handled = ota_payment_review.dispatch(handler, urlsplit(handler.path), backend=backend)
        self.assertTrue(handled)
        self.assertEqual(handler.response[0], 200)
        result = handler.response[2]
        self.assertEqual(result["event_id"], "evt-synth-001")
        self.assertTrue(result["source"]["present"])
        self.assertEqual(result["reconciliation"]["status"], "HOLD_AMBIGUOUS")
        self.assertEqual(len(result["financial"]), 12)
        encoded = json.dumps(result)
        for forbidden in ("private-fixture-path", "secret-event", "secret-digest", "source_digest"):
            self.assertNotIn(forbidden, encoded)
        self.assertEqual([call[0] for call in backend.calls], ["snapshot"])

    def test_owner_diagnostic_requires_a_session(self):
        backend = FakeBackend()
        handler = FakeHandler(backend, "/api/imports/ota/diagnostics/evt-synth-001")
        handler.current_user_id = lambda: ""
        ota_payment_review.dispatch(handler, urlsplit(handler.path), backend=backend)
        self.assertEqual(handler.response[0], 403)
        self.assertEqual(backend.calls, [])

    def test_a_linked_card_names_the_owning_booking_not_the_internal_id(self):
        events = {"evt-a": {"ota_event_id": "evt-a", "provider": "Synthetic Stay", "booking_ref": "BOOK-1"}}
        self.assertEqual(ota_payment_review._event_label(events, "evt-a"), "Synthetic Stay · BOOK-1")
        self.assertEqual(ota_payment_review._event_label(events, "evt-a|evt-a"), "Synthetic Stay · BOOK-1")
        self.assertEqual(ota_payment_review._event_label(events, "evt-x"), "다른 예약")
        self.assertEqual(ota_payment_review._event_label(events, ""), "다른 예약")

    def test_partial_group_reservations_reach_the_adapter_occupancy_boundary(self):
        from webapp.ota_payment_review import CoreOtaPaymentBackend
        backend = object.__new__(CoreOtaPaymentBackend)
        backend.store = SimpleNamespace(group_pins=lambda: [])
        occupied = backend._occupied_cards({}, [{"ota_event_id":"evt-syn-a",
            "status":"HOLD_PARTIAL_GROUP", "reserved_card_ids":["card-syn-a", "card-syn-b"]}])
        self.assertEqual(set(occupied), {"card-syn-a", "card-syn-b"})
        self.assertTrue(all(value[1] == "partial_group_reservation" for value in occupied.values()))
        backend.store = SimpleNamespace(group_pins=lambda: [{"event_ids":["missing-a", "missing-b"],
                                                            "card_ids":["frozen-a"]}])
        frozen_occupied = backend._occupied_cards({}, [])
        self.assertEqual(frozen_occupied["frozen-a"], ("missing-a|missing-b", "confirmed_group_reservation"))

    def test_removed_frozen_group_card_is_rejected_by_manual_selection(self):
        from webapp.ota_payment_review import CoreOtaPaymentBackend, InvalidReviewInput
        backend = object.__new__(CoreOtaPaymentBackend)
        pinned = {"event_ids":["removed-event-a", "removed-event-b"], "card_ids":["card-02"]}
        backend.store = SimpleNamespace(group_pins=lambda: [pinned], active_rules=lambda: [])
        candidate = cards(3)[2]
        event = {**EVENT, "ota_event_id":"current-hold", "paid_on":"2026-09-04"}
        backend._data = lambda: ([event], [candidate], {}, [{**event, "status":"HOLD_NO_CARD"}])
        backend._event_rows = lambda *_args: [candidate]
        with self.assertRaises(InvalidReviewInput):
            backend._selection("current-hold", "card-02")

    def test_partial_group_ids_project_from_read_backend_into_ledger_holds(self):
        from webapp.card_flow import CardFlow
        from webapp.ota_payment_review import CoreOtaPaymentBackend
        class ReadBackend:
            store = SimpleNamespace(group_pins=lambda: [{"event_ids":["missing-ota-a", "missing-ota-b"],
                                                         "card_ids":["frozen-card-a", "frozen-card-b"]}])
            def _transactions(self):
                return []
            def close(self):
                pass
        class Reconciled:
            def held(self):
                return ({"results": [{"ota_event_id":"ota-syn-1", "status":"HOLD_PARTIAL_GROUP",
                                      "reserved_card_ids":["card-syn-1", "card-syn-2"]}],
                         "links": {}, "public": {}, "generation": 1, "key": "k"}, True)
        flow = object.__new__(CardFlow)
        flow.board = object()
        with mock.patch.object(ota_payment_review, "enabled", return_value=True), \
             mock.patch.object(CoreOtaPaymentBackend, "from_host", return_value=ReadBackend()), \
             mock.patch.object(ota_payment_review, "snapshot_service", return_value=Reconciled()):
            holds = flow.ota_group_holds()
        self.assertEqual(set(holds), {"frozen-card-a", "frozen-card-b"})
        self.assertEqual(holds["frozen-card-a"]["ota_event_ids"], ["missing-ota-a", "missing-ota-b"])

    def test_preview_then_confirm_requires_current_digest_and_records_separate_manual_link(self):
        backend = FakeBackend()
        preview = {"event_id": EVENT["ota_event_id"], "transaction_id": "card-02"}
        request = FakeHandler(backend, "/api/imports/ota/preview", json.dumps(preview).encode())
        ota_payment_review.dispatch(request, urlsplit(request.path), raw=request.raw, csrf="token-synth", backend=backend)
        self.assertEqual(request.response[0], 200)
        self.assertEqual(request.response[2]["difference_krw"], 25)
        body = {**preview, "preview_digest": "preview-synth-current", "request_id": "req-synth-001"}
        confirm = FakeHandler(backend, "/api/imports/ota/confirm", json.dumps(body).encode())
        ota_payment_review.dispatch(confirm, urlsplit(confirm.path), raw=confirm.raw, csrf="token-synth", backend=backend)
        self.assertEqual(confirm.response[0], 200)
        self.assertEqual(confirm.response[2]["status"], "MATCHED_USER")
        self.assertEqual(backend.calls[-1], ("confirm", "evt-synth-001", "card-02",
                                             "preview-synth-current", "req-synth-001", "synthetic-owner"))

    def test_stale_preview_is_rejected_and_csrf_is_checked_before_backend_write(self):
        backend = FakeBackend()
        backend.stale = True
        body = {"event_id": "evt-synth-001", "transaction_id": "card-02",
                "preview_digest": "old-preview", "request_id": "req-synth-stale"}
        request = FakeHandler(backend, "/api/imports/ota/confirm", json.dumps(body).encode())
        ota_payment_review.dispatch(request, urlsplit(request.path), raw=request.raw, csrf="token-synth", backend=backend)
        self.assertEqual(request.response[0], 409)
        self.assertEqual(request.response[2]["code"], "STALE_PREVIEW")
        rejected_backend = FakeBackend()
        rejected = FakeHandler(rejected_backend, "/api/imports/ota/confirm", json.dumps(body).encode(),
                               supplied_csrf="wrong-token")
        ota_payment_review.dispatch(rejected, urlsplit(rejected.path), raw=rejected.raw,
                                    csrf="token-synth", backend=rejected_backend)
        self.assertEqual(rejected.response[0], 403)
        self.assertEqual([call[0] for call in rejected_backend.calls], [])
        for token, header in (("", ""), ("configured", ""), ("", "configured")):
            blank_backend = FakeBackend()
            blank = FakeHandler(blank_backend, "/api/imports/ota/preview", b"{}",
                                csrf=token, supplied_csrf=header)
            ota_payment_review.dispatch(blank, urlsplit(blank.path), raw=blank.raw,
                                        csrf=token, backend=blank_backend)
            self.assertEqual(blank.response[0], 403)
            self.assertEqual(blank_backend.calls, [])

    def test_proposal_once_approve_and_edit_are_explicit_and_keep_pending_until_answer(self):
        backend = FakeBackend()
        for action in ("once", "approve", "edit"):
            body = {"proposal_id": "proposal-synth-001", "action": action,
                    "conditions": {"provider": "Synthetic Stay", "item": "Synthetic room",
                                   "issuer": "Synthetic Bank", "card_last4": "2042"}}
            request = FakeHandler(backend, "/api/imports/ota/proposal", json.dumps(body).encode())
            ota_payment_review.dispatch(request, urlsplit(request.path), raw=request.raw,
                                        csrf="token-synth", backend=backend)
            self.assertEqual(request.response[0], 200)
            self.assertEqual(backend.calls[-1][2], action)
            if action == "once":
                self.assertEqual(request.response[2]["status"], "answered_once")

    def test_approval_rejects_unscoped_or_unknown_conditions(self):
        backend = FakeBackend()
        for conditions in ({}, {"anything": "broad"}, {"card_last4": "12x4"},
                           {"date_lag_days": -8}):
            body = {"proposal_id": "proposal-synth-001", "action": "approve",
                    "conditions": conditions}
            request = FakeHandler(backend, "/api/imports/ota/proposal", json.dumps(body).encode())
            ota_payment_review.dispatch(request, urlsplit(request.path), raw=request.raw,
                                        csrf="token-synth", backend=backend)
            self.assertEqual(request.response[0], 422)

    def test_proposal_accepts_signed_exact_krw_delta_and_bounds_date_lag_to_seven_days(self):
        backend = FakeBackend()
        conditions = {"provider": "Synthetic Stay", "item": "Synthetic room",
                      "issuer": "Synthetic Bank", "card_last4": "2042",
                      "amount_delta_krw": -4000, "date_lag_days": 7}
        for lag in (-7, -1, 0, 1, 7):
            body: dict[str, Any] = {"proposal_id": "proposal-synth-001", "action": "edit",
                    "conditions": {**conditions, "date_lag_days": lag}}
            request = FakeHandler(backend, "/api/imports/ota/proposal", json.dumps(body).encode())
            ota_payment_review.dispatch(request, urlsplit(request.path), raw=request.raw,
                                        csrf="token-synth", backend=backend)
            self.assertEqual(request.response[0], 200)
            self.assertEqual(backend.calls[-1][-1], body["conditions"])
        for value in (True, 1.5, "-4000"):
            invalid = {**body, "conditions": {**body["conditions"], "amount_delta_krw": value}}
            response = FakeHandler(backend, "/api/imports/ota/proposal", json.dumps(invalid).encode())
            ota_payment_review.dispatch(response, urlsplit(response.path), raw=response.raw,
                                        csrf="token-synth", backend=backend)
            self.assertEqual(response.response[0], 422)
        invalid = {**body, "conditions": {**body["conditions"], "date_lag_days": 8}}
        response = FakeHandler(backend, "/api/imports/ota/proposal", json.dumps(invalid).encode())
        ota_payment_review.dispatch(response, urlsplit(response.path), raw=response.raw,
                                    csrf="token-synth", backend=backend)
        self.assertEqual(response.response[0], 422)

    def test_negative_lag_approve_and_edit_over_real_http(self):
        backend = FakeBackend()
        class Handler(BaseHTTPRequestHandler):
            def current_user_id(self):
                return "synthetic-owner"
            def _send_json(self, payload, status=200):
                data = json.dumps(payload).encode("utf-8")
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)
            def do_POST(self):
                raw = self.rfile.read(int(self.headers.get("Content-Length", "0")))
                ota_payment_review.dispatch(self, urlsplit(self.path), raw=raw,
                    csrf="synthetic-csrf", backend=backend)
            def log_message(self, *_args):
                pass
        server = HTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            with mock.patch.object(ota_payment_review, "enabled", return_value=True):
                for action in ("approve", "edit"):
                    payload = {"proposal_id": "proposal-synth-001", "action": action,
                        "conditions": {"provider": "Synthetic Stay", "item": "Synthetic room",
                            "issuer": "Synthetic Bank", "card_last4": "2042", "date_lag_days": -3}}
                    request = urllib.request.Request(
                        f"http://127.0.0.1:{server.server_port}/api/imports/ota/proposal",
                        data=json.dumps(payload).encode("utf-8"), method="POST",
                        headers={"Content-Type": "application/json", "X-CSRF-Token": "synthetic-csrf"})
                    with urllib.request.urlopen(request, timeout=5) as response:
                        self.assertEqual(response.status, 200)
                    self.assertEqual(backend.calls[-1][-1]["date_lag_days"], -3)
                alias = {"proposal_id":"proposal-synth-001", "action":"approve",
                    "conditions":{"rule_kind":"provider_alias", "provider":"agoda",
                        "alias":"AGODA.COM", "approval_source":"synthetic-source", "alias_version":2}}
                request = urllib.request.Request(
                    f"http://127.0.0.1:{server.server_port}/api/imports/ota/proposal",
                    data=json.dumps(alias).encode("utf-8"), method="POST",
                    headers={"Content-Type":"application/json", "X-CSRF-Token":"synthetic-csrf"})
                with urllib.request.urlopen(request, timeout=5) as response:
                    self.assertEqual(response.status, 200)
                self.assertEqual(backend.calls[-1][-1], alias["conditions"])
                issuer_alias = {"proposal_id":"proposal-synth-001", "action":"approve",
                    "conditions":{"rule_kind":"issuer_alias", "provider":"agoda",
                        "event_issuer_alias":"Synthetic issuer", "issuer":"Synthetic Bank",
                        "approval_source":"synthetic-source", "alias_version":1}}
                request = urllib.request.Request(
                    f"http://127.0.0.1:{server.server_port}/api/imports/ota/proposal",
                    data=json.dumps(issuer_alias).encode("utf-8"), method="POST",
                    headers={"Content-Type":"application/json", "X-CSRF-Token":"synthetic-csrf"})
                with urllib.request.urlopen(request, timeout=5) as response:
                    self.assertEqual(response.status, 200)
                self.assertEqual(backend.calls[-1][-1], issuer_alias["conditions"])
                missing_request_id = urllib.request.Request(
                    f"http://127.0.0.1:{server.server_port}/api/imports/ota/group/confirm",
                    data=json.dumps({"event_ids":["evt-syn-a", "evt-syn-b"]}).encode("utf-8"), method="POST",
                    headers={"Content-Type":"application/json", "X-CSRF-Token":"synthetic-csrf"})
                with self.assertRaises(urllib.error.HTTPError) as error:
                    urllib.request.urlopen(missing_request_id, timeout=5)
                self.assertEqual(error.exception.code, 422)
                group = {"event_ids":["evt-syn-a", "evt-syn-b"], "replace":False,
                         "request_id":"group-http-synthetic-001"}
                request = urllib.request.Request(
                    f"http://127.0.0.1:{server.server_port}/api/imports/ota/group/confirm",
                    data=json.dumps(group).encode("utf-8"), method="POST",
                    headers={"Content-Type":"application/json", "X-CSRF-Token":"synthetic-csrf"})
                with urllib.request.urlopen(request, timeout=5) as response:
                    self.assertEqual(response.status, 200)
                self.assertEqual(backend.calls[-1],
                                 ("confirm_group_order", group["event_ids"], "synthetic-owner", False,
                                  group["request_id"]))
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)

    def test_card_flow_hook_needs_both_card_import_and_isolated_review_opt_in(self):
        handler = FakeHandler(FakeBackend(), "/api/imports/ota")
        with mock.patch.dict(os.environ, {}, clear=True):
            self.assertFalse(card_flow.dispatch(handler, urlsplit(handler.path), csrf="token-synth"))
        with mock.patch.dict(os.environ, {"WEBLEDGER_CARD_FLOW": "1"}, clear=True):
            self.assertFalse(card_flow.dispatch(handler, urlsplit(handler.path), csrf="token-synth"))

    def test_card_flow_routes_isolated_request_through_the_injected_backend(self):
        backend = FakeBackend()
        handler = FakeHandler(backend, "/api/imports/ota")
        configure = lambda **_kwargs: backend
        with mock.patch.dict(os.environ, {
            "WEBLEDGER_CARD_FLOW": "1",
            "WEBLEDGER_OTA_REVIEW_MODE": "isolated",
            "WEBLEDGER_OTA_REVIEW_DB": SYNTHETIC_REVIEW_DB,
        }, clear=True), mock.patch("webapp.ledger_board._active_store", return_value=object()):
            ota_payment_review.configure_backend_factory(read_factory=configure, write_factory=configure)
            self.addCleanup(ota_payment_review.configure_backend_factory,
                            read_factory=None, write_factory=None)
            handled = card_flow.dispatch(handler, urlsplit(handler.path), csrf="token-synth")
        self.assertTrue(handled)
        self.assertEqual(handler.response[0], 200)
        self.assertEqual(handler.response[2]["events"][0]["ota_event_id"], EVENT["ota_event_id"])

    def test_card_flow_rejects_post_before_creating_backend_when_csrf_is_invalid(self):
        backend = FakeBackend()
        factory_calls = []
        handler = FakeHandler(backend, "/api/imports/ota/confirm", b"{}", supplied_csrf="bad")
        with mock.patch.dict(os.environ, {
            "WEBLEDGER_CARD_FLOW": "1",
            "WEBLEDGER_OTA_REVIEW_MODE": "isolated",
            "WEBLEDGER_OTA_REVIEW_DB": SYNTHETIC_REVIEW_DB,
        }, clear=True):
            def factory(**kwargs):
                factory_calls.append(kwargs)
                return backend
            ota_payment_review.configure_backend_factory(read_factory=factory, write_factory=factory)
            self.addCleanup(ota_payment_review.configure_backend_factory,
                            read_factory=None, write_factory=None)
            handled = card_flow.dispatch(handler, urlsplit(handler.path), raw=handler.raw, csrf="token-synth")
        self.assertTrue(handled)
        self.assertEqual(handler.response[0], 403)
        self.assertEqual(factory_calls, [])

    def test_core_backend_is_read_only_on_snapshot_and_refuses_automatic_or_exactly_linked_cards(self):
        from webapp.ota_payment_review import CoreOtaPaymentBackend
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as directory:
            board_path = os.path.join(directory, "board.sqlite")
            review_path = os.path.join(directory, "review.sqlite")
            board_conn = sqlite3.connect(board_path, check_same_thread=False)
            board_conn.row_factory = sqlite3.Row
            self.addCleanup(board_conn.close)
            board_conn.execute("CREATE TABLE transactions (transaction_id TEXT, issuer TEXT, approval_date TEXT, posting_date TEXT, merchant TEXT, amount_krw INTEGER, foreign_amount TEXT, authorization_id TEXT, cancellation_status TEXT, refund_status TEXT)")
            board_conn.executemany("INSERT INTO transactions VALUES (?,?,?,?,?,?,?,?,?,?)", [
                (row["transaction_id"], row["issuer"], row["approval_date"], row["posting_date"],
                 row["merchant"], row["amount_krw"], row["foreign_amount"], row["authorization_id"],
                 row["cancellation_status"], row["refund_status"]) for row in cards()])
            board_conn.commit()
            board = SimpleNamespace(conn=board_conn, _lock=threading.RLock())
            Path(review_path).touch()
            FakeCoreStore.writer_calls = 0
            payments = FakeCorePayments()
            backend = CoreOtaPaymentBackend(board, review_path, read_only=True,
                                            payments=payments, store_type=FakeCoreStore,
                                            sources={"mail_directories": [], "portal_databases": [],
                                                     "reference_documents": []})
            with mock.patch.object(ota_payment_review, "legacy_exact_bindings",
                                   side_effect=AssertionError("review snapshot must not run legacy matching")):
                primed(board, backend)
            before = Path(review_path).stat().st_mtime_ns
            with mock.patch.object(ota_payment_review, "legacy_exact_bindings",
                                   side_effect=AssertionError("review snapshot must not run legacy matching")):
                snapshot = backend.snapshot()
            self.assertEqual(len(snapshot["cards_by_event"]["evt-synth-001"]), 12)
            self.assertEqual(snapshot["cards_by_event"]["evt-synth-001"][0]["already_linked_event_id"], "evt-auto")
            self.assertEqual(Path(review_path).stat().st_mtime_ns, before)
            self.assertEqual(FakeCoreStore.writer_calls, 0)
            with self.assertRaises(ota_payment_review.InvalidReviewInput):
                backend.preview("evt-synth-001", "card-00")
            with self.assertRaises(ota_payment_review.InvalidReviewInput):
                backend.preview("evt-synth-001", "card-01")
            preview = backend.preview("evt-synth-001", "card-02")
            self.assertEqual(preview["difference_krw"], 25)
            # Another manual link now owns card-02: that is a review-database change, so the snapshot's
            # fingerprint moves and the confirm must be refused as stale rather than written.
            FakeCoreStore.extra_links = {"evt-other": {"transaction_id": "card-02", "source_digest": "other"}}
            self.addCleanup(lambda: setattr(FakeCoreStore, "extra_links", {}))
            writer_backend = CoreOtaPaymentBackend(board, review_path, read_only=False,
                                                   payments=payments, store_type=FakeCoreStore,
                                                   sources={"mail_directories": [], "portal_databases": [],
                                                            "reference_documents": []})
            with self.assertRaises(ota_payment_review.StalePreviewError):
                writer_backend.confirm("evt-synth-001", "card-02", preview["preview_digest"],
                                       request_id="req-synth-002", user="synthetic-owner")
            self.assertEqual(FakeCoreStore.writer_calls, 0)
            board_conn.close()

    def test_confirm_passes_fresh_full_card_allocations_even_when_empty(self):
        from webapp.ota_payment_review import CoreOtaPaymentBackend

        class EmptyLinkStore(FakeCoreStore):
            def links(self):
                return {}

        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as directory:
            board_path = Path(directory) / "board.sqlite"
            board_conn = sqlite3.connect(board_path, check_same_thread=False)
            board_conn.row_factory = sqlite3.Row
            board_conn.execute("""CREATE TABLE transactions (
                transaction_id TEXT,source_hash TEXT,merchant TEXT,merchant_normalized TEXT,
                card_kind TEXT,card_tail TEXT,transaction_direction TEXT,approval_date TEXT,
                amount_krw INTEGER)""")
            board_conn.executemany("INSERT INTO transactions VALUES (?,?,?,?,?,?,?,?,?)", [
                ("card-00", "hash-00", "TRIP.COM", "trip.com", "credit", "2042", "purchase", "2026-09-04", 12500),
                ("card-02", "hash-02", "TRIP.COM", "trip.com", "credit", "2042", "purchase", "2026-09-04", 12525),
                ("card-03", "hash-03", "TRIP.COM", "trip.com", "credit", "2042", "purchase", "2026-09-04", 12500),
            ])
            board_conn.commit()
            board = SimpleNamespace(conn=board_conn, _lock=threading.RLock())
            payments = FakeCorePayments()
            payments.occupied_transaction = "card-00"
            backend = CoreOtaPaymentBackend(board, str(Path(directory) / "review.sqlite"),
                                            read_only=False, payments=payments,
                                            store_type=EmptyLinkStore, sources={})
            primed(board, backend)
            preview = backend.preview("evt-synth-001", "card-02")
            backend.confirm("evt-synth-001", "card-02", preview["preview_digest"],
                            request_id="req-allocations", user="synthetic-owner")
            allocations = EmptyLinkStore.last_store.calls[-1][-1]
            self.assertEqual(allocations, {"evt-auto": "card-00", "evt-user": "card-03"})
            backend.close()
            board_conn.close()

    def test_core_backend_reads_real_core_api_without_creating_review_path_on_first_get(self):
        from webapp.ota_payment_review import backend_for_request
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as directory:
            board_path = Path(directory) / "board.sqlite"
            board_conn = sqlite3.connect(board_path, check_same_thread=False)
            self.addCleanup(board_conn.close)
            board_conn.execute("CREATE TABLE transactions (transaction_id TEXT, approval_date TEXT)")
            board_conn.commit()
            board = SimpleNamespace(conn=board_conn, _lock=threading.RLock())
            review_path = Path(directory) / "not-created" / "review.sqlite"
            with mock.patch.dict(os.environ, {
                ota_payment_review.REVIEW_DB_ENV: str(review_path),
                ota_payment_review.SOURCES_ENV: json.dumps({
                    "mail_directories": [], "portal_databases": [], "reference_documents": []}),
            }, clear=False):
                backend = backend_for_request(board, None, read_only=True)
                self.assertEqual(backend.snapshot(), {"events": [], "cards_by_event": {}, "proposals": []})
                backend.close()
            self.assertFalse(review_path.parent.exists())
            board_conn.close()

    def test_core_snapshot_connects_undated_merchant_amount_tail_and_preserves_unknown_date(self):
        from app import ota_payments
        from app.ota_review import OtaReviewStore
        from tests.card_pipeline.test_ota_payments import card as ota_card, event as ota_event
        from webapp.ota_payment_review import CoreOtaPaymentBackend

        class Payments:
            def build_ota_payment_events(self, _sources):
                return [candidate_event]

            def match_ota_payment_events(self, events, _transactions, **_kwargs):
                return ota_payments.match_ota_payment_events(events, _transactions, **_kwargs)

            search_card_candidates = staticmethod(ota_payments.search_card_candidates)
            _event_is_paid = staticmethod(ota_payments._event_is_paid)

            def same_date_cards(self, _event, _transactions, **_kwargs):
                return []

        candidate_event = ota_event("ota-undated-candidate", paid_on=None, amount=30000,
            amount_krw=30000, verified_portal_snapshot=True, reservation_status="completed",
            service_period={"starts_on": "2026-10-01", "ends_on": "2026-10-03"})
        candidate_card = ota_card("synthetic-undated-card", source_hash="c" * 64,
            merchant="AGODA.COM", merchant_normalized="agoda.com", approval_date="2026-10-01",
            amount_krw=30000, card_tail="1234", ota_inference_eligible=True)
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as directory:
            board_path = Path(directory) / "board.sqlite"
            board_conn = sqlite3.connect(board_path, check_same_thread=False)
            board_conn.row_factory = sqlite3.Row
            board_conn.executescript("""
                CREATE TABLE transactions (
                    transaction_id TEXT, source_hash TEXT, merchant TEXT, merchant_normalized TEXT,
                    issuer TEXT, card_tail TEXT, transaction_direction TEXT, approval_date TEXT,
                    posting_date TEXT, amount_krw INTEGER, classification_state TEXT,
                    classification_source TEXT, duplicate_of TEXT, parse_error TEXT, conflict_reason TEXT);
                CREATE TABLE board_rows (row_id TEXT, row_kind TEXT);
            """)
            board_conn.execute("INSERT INTO transactions VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", (
                candidate_card["transaction_id"], candidate_card["source_hash"], candidate_card["merchant"],
                candidate_card["merchant_normalized"], "Synthetic Bank", candidate_card["card_tail"],
                "purchase", candidate_card["approval_date"], "2026-10-02", candidate_card["amount_krw"],
                "classified", "automatic", "", "", ""))
            board_conn.commit()
            board = SimpleNamespace(conn=board_conn, _lock=threading.RLock())
            review_path = Path(directory) / "review.sqlite"
            review_path.touch()
            backend = CoreOtaPaymentBackend(board, str(review_path), read_only=True,
                payments=Payments(), store_type=OtaReviewStore, sources={})
            try:
                data = backend._data()
                result = data[3][0]
                self.assertEqual(result["status"], "MATCHED_AUTO")
                self.assertFalse(result['payment_relation']['payment_date_verified'])
                snapshot = backend.snapshot_from(data)
                self.assertEqual(snapshot['events'], [])  # Successful matches leave the hold subset.
                candidate = backend._event_rows(dict(candidate_event, **result), data[1], data[2])[0]
                self.assertEqual(candidate["transaction_id"], candidate_card["transaction_id"])
                self.assertFalse(candidate.get("selection_disabled", False))
                self.assertIsNone(result.get('paid_on'))
            finally:
                backend.close()
                board_conn.close()

    def test_core_snapshot_exposes_amount_mismatch_as_disabled_diagnostic_candidate(self):
        from app import ota_payments
        from app.ota_review import OtaReviewStore
        from tests.card_pipeline.test_ota_payments import card as ota_card, event as ota_event
        from webapp.ota_payment_review import CoreOtaPaymentBackend

        event = ota_event("ota-amount-diagnostic", paid_on="2026-10-01", amount=31000,
            amount_krw=31000, verified_portal_snapshot=True, reservation_status="completed")
        candidate_card = ota_card("synthetic-amount-diagnostic-card", source_hash="d" * 64,
            merchant="AGODA.COM", merchant_normalized="agoda.com", approval_date="2026-10-01",
            amount_krw=30000, card_tail="1234", ota_inference_eligible=True)

        class Payments:
            def build_ota_payment_events(self, _sources):
                return [event]

            def match_ota_payment_events(self, events, _transactions, **_kwargs):
                return [{"ota_event_id": events[0]["ota_event_id"], "status": "HOLD_AMOUNT_MISMATCH",
                         "transaction_id": None, "candidates": [], "reason": "amount_differs"}]

            search_card_candidates = staticmethod(ota_payments.search_card_candidates)
            _event_is_paid = staticmethod(ota_payments._event_is_paid)

            def same_date_cards(self, _event, _transactions, **_kwargs):
                return []

        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as directory:
            board_path = Path(directory) / "board.sqlite"
            board_conn = sqlite3.connect(board_path, check_same_thread=False)
            board_conn.row_factory = sqlite3.Row
            board_conn.executescript("""
                CREATE TABLE transactions (
                    transaction_id TEXT, source_hash TEXT, merchant TEXT, merchant_normalized TEXT,
                    issuer TEXT, card_tail TEXT, transaction_direction TEXT, approval_date TEXT,
                    posting_date TEXT, amount_krw INTEGER, classification_state TEXT,
                    classification_source TEXT, duplicate_of TEXT, parse_error TEXT, conflict_reason TEXT);
                CREATE TABLE board_rows (row_id TEXT, row_kind TEXT);
            """)
            board_conn.execute("INSERT INTO transactions VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", (
                candidate_card["transaction_id"], candidate_card["source_hash"], candidate_card["merchant"],
                candidate_card["merchant_normalized"], "Synthetic Bank", candidate_card["card_tail"],
                "purchase", candidate_card["approval_date"], "2026-10-02", candidate_card["amount_krw"],
                "classified", "automatic", "", "", ""))
            board_conn.commit()
            board = SimpleNamespace(conn=board_conn, _lock=threading.RLock())
            review_path = Path(directory) / "review.sqlite"
            review_path.touch()
            backend = CoreOtaPaymentBackend(board, str(review_path), read_only=True,
                payments=Payments(), store_type=OtaReviewStore, sources={})
            try:
                data = backend._data()
                result = data[3][0]
                self.assertEqual(result["status"], "HOLD_AMOUNT_MISMATCH")
                self.assertEqual(result["candidate_search"]["rejected"][0]["reason"], "AMOUNT_MISMATCH")
                snapshot = backend.snapshot_from(data)
                row = snapshot["cards_by_event"][event["ota_event_id"]][0]
                self.assertEqual(row["candidate_rejection_reason"], "AMOUNT_MISMATCH")
                self.assertTrue(row["selection_disabled"])
                self.assertIn("결제 금액이 다릅니다", row["selection_disabled_reason"])
            finally:
                backend.close()
                board_conn.close()

    def test_manual_link_crosswalk_is_reconstructed_after_store_reopen_and_recollection(self):
        from app.ota_review import OtaReviewStore

        old_event = {**EVENT, "ota_event_id": "legacy-event-reopen", "provider": "agoda",
                     "booking_ref": "SYNTHETIC-REOPEN-BOOKING", "event_type": "charge",
                     "amount_krw": 30000, "source_digest": "same-verified-proof",
                     "card_last4": "2042", "evidence_status": "paid_verified", "payment_status": "paid"}
        current_event = {**old_event, "ota_event_id": "recollected-event"}
        card = {"transaction_id": "synthetic-reopen-card", "source_hash": "synthetic-source-hash",
                "merchant": "AGODA.COM", "merchant_normalized": "agoda.com", "issuer": "Synthetic Bank",
                "card_tail": "2042", "approval_date": "2026-10-01", "transaction_direction": "purchase",
                "amount_krw": 30000}
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as directory:
            path = Path(directory) / "review.sqlite"
            first = OtaReviewStore(path)
            preview = first.preview(old_event, card)
            first.confirm(old_event, card, preview["preview_digest"], request_id="synthetic-first-link",
                          user="synthetic-owner", allocations={})
            first.close()

            reopened = OtaReviewStore(path)
            stored_links = reopened.links()
            stored_events = reopened.event_snapshots()
            crosswalks = reopened.event_crosswalks()
            links, crosswalk = ota_payment_review._manual_link_crosswalk(
                [current_event], stored_links, stored_events, crosswalks)
            self.assertEqual(links["recollected-event"]["transaction_id"], card["transaction_id"])
            self.assertEqual(crosswalk, {"legacy-event-reopen": "recollected-event"})
            self.assertEqual(reopened.links()["legacy-event-reopen"]["transaction_id"],
                             card["transaction_id"])
            reopened.close()

    def test_default_source_resolution_uses_registered_manifest_and_legacy_environment_defaults(self):
        from app import ota_sources
        from webapp.ota_payment_review import CoreOtaPaymentBackend
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as directory:
            data_dir = Path(directory)
            mail_default = data_dir / "ota-mail"
            mail_registered = data_dir / "registered-mail"
            portal_default = data_dir / "agoda-default.sqlite"
            portal_registered = data_dir / "agoda-registered.sqlite"
            mail_default.mkdir()
            mail_registered.mkdir()
            portal_default.touch()
            portal_registered.touch()
            (data_dir / "ota-sources.json").write_text(json.dumps({
                "schema_version": ota_sources.SCHEMA_VERSION,
                "mail_directories": [str(mail_registered)],
                "portal_databases": [str(portal_registered)],
                "reference_documents": [],
            }), encoding="utf-8")
            board_path = data_dir / "board.sqlite"
            board_conn = sqlite3.connect(board_path)
            board_conn.execute("CREATE TABLE transactions (transaction_id TEXT)")
            board_conn.commit()
            board = SimpleNamespace(conn=board_conn, path=board_path, _lock=threading.RLock())
            review_path = data_dir / "review.sqlite"
            with mock.patch.dict(os.environ, {
                "WEBLEDGER_OTA_REVIEW_DB": str(review_path),
                "WEBLEDGER_OTA_SOURCES_JSON": "",
                "WEBLEDGER_OTA_MAIL_DIR": str(mail_default),
                "WEBLEDGER_AGODA_PORTAL_DB": str(portal_default),
            }, clear=True):
                backend = CoreOtaPaymentBackend.from_host(board, read_only=True)
                self.assertEqual(backend.sources["portal_databases"][0], portal_default)
            self.assertEqual(set(map(str, backend.sources["mail_directories"])),
                             {str(mail_default), str(mail_registered)})
            self.assertEqual(set(map(str, backend.sources["portal_databases"])),
                             {str(portal_default), str(portal_registered)})
            backend.close()
            board_conn.close()

    def test_legacy_binding_requires_unique_complete_evidence_and_pins_exact_transaction(self):
        from webapp.ota_payment_review import legacy_exact_bindings
        event = {**EVENT, "provider": "trip", "source_digest": "digest-a",
                 "source_digests": ["digest-a", "digest-canonical-merge"], "card_last4": "2042"}
        row = {"transaction_id": "card-legacy", "source_hash": "card-hash",
               "card_tail": "2042", "issuer": "Synthetic Bank",
               "transaction_direction": "purchase", "amount_krw": 12500,
               "foreign_currency": "", "foreign_amount": ""}
        # Old reports expose source identity and booking facts, but not card amount/currency/card-tail.
        fact = {"transaction_id": "card-legacy", "source_hash": "card-hash",
                "provider": "trip", "booking_ref": event["booking_ref"],
                "source_sha256": "digest-a", "direction": "purchase",
                "item": "Synthetic room", "period": None, "evidence_kind": "authenticated_mail"}
        links = legacy_exact_bindings([event], [row], {"matches": [fact]})
        self.assertEqual(links[event["ota_event_id"]]["transaction_id"], "card-legacy")
        self.assertTrue(links[event["ota_event_id"]]["legacy_exact"])
        for changed in (
                {**fact, "core_link": True},
                {**fact, "source_sha256": "digest-b"},
                {**fact, "booking_ref": "OTHER"},
                {**fact, "direction": "refund"},
        ):
            self.assertEqual(legacy_exact_bindings([event], [row], {"matches": [changed]}), {})
        self.assertEqual(legacy_exact_bindings([event], [row], {"matches": [fact, fact]}), {})
        self.assertEqual(legacy_exact_bindings([event], [{**row, "amount_krw": 12501}],
                                               {"matches": [fact]}), {})
        self.assertEqual(legacy_exact_bindings([event], [{**row, "card_tail": "9999"}],
                                               {"matches": [fact]}), {})

    def test_proposal_question_states_signed_difference_and_conditions_without_discount_claim(self):
        snapshot = ota_payment_review.public_snapshot({
            "events": [], "cards_by_event": {},
            "proposals": [{"proposal_id": "proposal-synth", "status": "pending", "conditions": {
                "provider": "Synthetic Stay", "item": "Synthetic room",
                "issuer": "Synthetic Bank", "card_last4": "2042",
                "amount_delta_krw": -4000, "date_lag_days": 3,
            }}],
        })
        question = snapshot["proposals"][0]["question"]
        self.assertIn("OTA 금액보다 카드 금액이 4,000원 적고", question)
        self.assertIn("Synthetic Stay", question)
        self.assertIn("Synthetic room", question)
        self.assertIn("카드 끝 네 자리 2042", question)
        self.assertIn("카드 승인일은 OTA 결제일보다 최대 3일 늦고", question)
        self.assertNotIn("할인", question)

    def test_import_refresh_targets_new_transactions_and_digest_changed_manual_links(self):
        from webapp.ota_payment_review import CoreOtaPaymentBackend
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as directory:
            board_path = Path(directory) / "board.sqlite"
            board_conn = sqlite3.connect(board_path, check_same_thread=False)
            board_conn.row_factory = sqlite3.Row
            self.addCleanup(board_conn.close)
            board_conn.execute("CREATE TABLE transactions (transaction_id TEXT, approval_date TEXT)")
            board_conn.execute("INSERT INTO transactions VALUES ('card-new-1','2026-09-04')")
            board_conn.commit()
            review_path = Path(directory) / "review.sqlite"
            review_path.touch()
            board = SimpleNamespace(conn=board_conn, _lock=threading.RLock())
            FakeCoreStore.writer_calls = 0
            backend = CoreOtaPaymentBackend(board, str(review_path), read_only=False,
                                            payments=FakeCorePayments(), store_type=FakeCoreStore,
                                            sources={"mail_directories": [], "portal_databases": [],
                                                     "reference_documents": []})
            snapshot = backend.snapshot()
            changed = next(event for event in snapshot["events"] if event["ota_event_id"] == "evt-user")
            self.assertTrue(changed["evidence_changed"])
            self.assertEqual(changed["status"], "MATCHED_USER")
            refreshed = backend.refresh_after_import(["card-new-1"])
            self.assertEqual(refreshed["changed_transaction_ids"], ["card-new-1"])
            self.assertEqual(refreshed["changed_event_ids"], ["evt-user"])
            self.assertEqual(FakeCoreStore.last_store.calls[-1],
                             ("refresh", ["card-new-1"], ["evt-user"]))
            self.assertEqual(FakeCoreStore.writer_calls, 1)
            backend.close()
            board_conn.close()

    def test_import_post_uses_completion_worker_without_legacy_ota_refresh_hook(self):
        backend = FakeBackend()
        board = object()

        class FakePipeline:
            def receive(self, _raw, _filename):
                return {"batch_id": "synthetic-batch"}

        class FakeFlow:
            pipeline = FakePipeline()

            def __init__(self, _board):
                pass

        handler = FakeHandler(backend, "/api/imports", b"synthetic card file")
        queued = []
        processed = []
        result = {"batch_id": "synthetic-batch", "status": "complete",
                  "classified_percent": 100.0, "recorded_rows": 2}
        with mock.patch.dict(os.environ, {
            "WEBLEDGER_CARD_FLOW": "1", "WEBLEDGER_OTA_REVIEW_MODE": "isolated",
            "WEBLEDGER_OTA_REVIEW_DB": SYNTHETIC_REVIEW_DB,
        }, clear=True), mock.patch("webapp.ledger_board._active_store", return_value=board), \
                mock.patch("webapp.ledger_board.current_role", return_value="owner"), \
                mock.patch("app.card_preflight.validate_upload",
                           return_value=(b"validated-source", {"synthetic": True})), \
                mock.patch("webapp.card_completion_worker.queue_batch",
                           side_effect=lambda _board, batch_id: queued.append(batch_id)), \
                mock.patch("webapp.card_upload_jobs.process",
                           side_effect=lambda *args: (processed.append(args) or (result, 200))), \
                mock.patch.object(card_flow, "CardFlow", FakeFlow):
            self.assertTrue(card_flow.dispatch(handler, urlsplit(handler.path), raw=handler.raw,
                                               csrf="token-synth"))
        self.assertEqual(handler.response, (200, "application/json", result))
        self.assertEqual(queued, ["synthetic-batch"])
        self.assertEqual(len(processed), 1)
        self.assertEqual(processed[0][4:], (b"validated-source", {"synthetic": True}))
        self.assertEqual(backend.calls, [], "card upload must not invoke the retired OTA refresh hook")

    def test_missing_paid_on_is_shown_as_unknown_and_never_used_to_choose_a_card(self):
        from webapp.ota_payment_review import CoreOtaPaymentBackend

        class NoDatePayments(FakeCorePayments):
            def build_ota_payment_events(self, _sources):
                return [{**EVENT, "paid_on": None}]

            def match_ota_payment_events(self, events, *_args, **_kwargs):
                return [{**events[0], "status": "HOLD_DATE_UNKNOWN", "transaction_id": None,
                         "reason": "payment_date_not_in_source"}]

        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as directory:
            board_path = Path(directory) / "board.sqlite"
            board_conn = sqlite3.connect(board_path, check_same_thread=False)
            board_conn.row_factory = sqlite3.Row
            board_conn.execute("CREATE TABLE transactions (transaction_id TEXT, approval_date TEXT)")
            board_conn.execute("INSERT INTO transactions VALUES ('card-01','2026-09-04')")
            board_conn.commit()
            board = SimpleNamespace(conn=board_conn, _lock=threading.RLock())
            review_path = Path(directory) / "review.sqlite"
            backend = CoreOtaPaymentBackend(board, str(review_path), read_only=True,
                                            payments=NoDatePayments(), store_type=FakeCoreStore,
                                            sources={})
            snapshot = backend.snapshot()
            self.assertEqual(snapshot["events"][0]["paid_on"], "미확인")
            self.assertEqual(snapshot["cards_by_event"][EVENT["ota_event_id"]], [])
            primed(board, backend)
            with self.assertRaises(ota_payment_review.InvalidReviewInput):
                backend.preview(EVENT["ota_event_id"], "card-01")
            backend.close()
            board_conn.close()


    def _flagged_backend(self):
        from webapp.ota_payment_review import CoreOtaPaymentBackend

        class Store(FakeCoreStore):
            def links(self):
                return {}

        class Payments:
            def build_ota_payment_events(self, _sources):
                return [dict(EVENT)]

            def match_ota_payment_events(self, events, *_args, **_kwargs):
                return [{**events[0], "status": "HOLD_AMBIGUOUS"}]

            def same_date_cards(self, event, transactions, *, links=None):
                return [dict(row) for row in transactions if row.get("approval_date") == event["paid_on"]]

        directory = tempfile.TemporaryDirectory(dir=Path(__file__).parent)
        self.addCleanup(directory.cleanup)
        board_path = Path(directory.name) / "board.sqlite"
        connection = sqlite3.connect(board_path, check_same_thread=False)
        self.addCleanup(connection.close)
        connection.row_factory = sqlite3.Row
        connection.execute("CREATE TABLE transactions (transaction_id TEXT, approval_date TEXT, duplicate_of TEXT, parse_error TEXT, conflict_reason TEXT, amount_krw INTEGER, transaction_direction TEXT, direction TEXT)")
        values = [
            ("card-duplicate", EVENT["paid_on"], "card-original", "", "", 12500, "purchase", "legacy-duplicate"),
            ("card-parse-error", EVENT["paid_on"], "", "bad date", "", 12500, "purchase", "legacy-parse"),
            ("card-conflict", EVENT["paid_on"], "", "", "conflicting source", 12500, "purchase", "legacy-conflict"),
            ("card-normal", EVENT["paid_on"], "", "", "", 12500, "purchase", "legacy-normal"),
        ]
        connection.executemany("INSERT INTO transactions VALUES (?,?,?,?,?,?,?,?)", values)
        connection.commit()
        board = SimpleNamespace(conn=connection, _lock=threading.RLock())
        Store.writer_calls = 0
        backend = CoreOtaPaymentBackend(
            board, str(Path(directory.name) / "review.sqlite"), read_only=False,
            payments=Payments(), store_type=Store, sources={})
        self.addCleanup(backend.close)
        primed(board, backend)
        return backend, Store

    def test_flagged_same_date_transactions_remain_visible_disabled_and_confirm_is_rejected(self):
        backend, store_type = self._flagged_backend()
        snapshot = backend.snapshot()
        rows = snapshot["cards_by_event"][EVENT["ota_event_id"]]
        self.assertEqual([row["transaction_id"] for row in rows], [
            "card-duplicate", "card-parse-error", "card-conflict", "card-normal"])
        twice = ota_payment_review.public_snapshot({
            "events": [], "cards_by_event": {EVENT["ota_event_id"]: rows}, "proposals": []}, include_cards=True)
        public_rows = twice["cards_by_event"][EVENT["ota_event_id"]]
        expected_reasons = ["중복 거래라 선택할 수 없습니다.",
                            "거래 파싱 오류가 있어 선택할 수 없습니다.",
                            "거래 충돌이 있어 선택할 수 없습니다."]
        for row, reason in zip(public_rows[:3], expected_reasons):
            self.assertTrue(row["selection_disabled"])
            self.assertEqual(row["selection_disabled_reason"], reason)
            with self.assertRaises(ota_payment_review.InvalidReviewInput):
                backend.preview(EVENT["ota_event_id"], row["transaction_id"])
            with self.assertRaises(ota_payment_review.InvalidReviewInput):
                backend.confirm(EVENT["ota_event_id"], row["transaction_id"], "digest",
                                request_id="req-blocked", user="synthetic-owner")
        self.assertFalse(public_rows[3]["selection_disabled"])
        for row in public_rows[:3]:
            handler = FakeHandler(backend, ota_payment_review.ROUTE_PREFIX + "/confirm",
                                  raw=json.dumps({"event_id": EVENT["ota_event_id"],
                                                  "transaction_id": row["transaction_id"],
                                                  "preview_digest": "digest", "request_id": "req-http"}).encode())
            ota_payment_review.dispatch(handler, urlsplit(handler.path), raw=handler.raw,
                                        csrf="token-synth", backend=backend)
            self.assertEqual(handler.response[0], 422)
            for private_detail in ("bad date", "card-original", "conflicting source"):
                self.assertNotIn(private_detail, json.dumps(handler.response[2]))
        self.assertEqual(store_type.writer_calls, 0)

    def test_normal_same_date_transaction_remains_selectable_and_confirmable(self):
        backend, store_type = self._flagged_backend()
        preview = backend.preview(EVENT["ota_event_id"], "card-normal")
        backend.confirm(EVENT["ota_event_id"], "card-normal", preview["preview_digest"],
                        request_id="req-normal", user="synthetic-owner")
        self.assertEqual(store_type.writer_calls, 1)

    def test_card_direction_prefers_transaction_direction_then_falls_back(self):
        raw = {"events": [], "cards_by_event": {"evt-direction": [
            {"transaction_id": "canonical", "transaction_direction": "refund", "direction": "purchase"},
            {"transaction_id": "fallback", "transaction_direction": "", "direction": "refund"},
            {"transaction_id": "unknown", "transaction_direction": None, "direction": None},
        ]}, "proposals": []}
        once = ota_payment_review.public_snapshot(raw, include_cards=True)["cards_by_event"]["evt-direction"]
        twice = ota_payment_review.public_snapshot({"events": [], "cards_by_event": {"evt-direction": once},
                                                     "proposals": []}, include_cards=True)["cards_by_event"]["evt-direction"]
        self.assertEqual([row["direction"] for row in twice], ["refund", "refund", "미확인"])


    def test_acceptance_01_partial_group_is_temporary_and_never_written_to_allocation_store(self):
        import app.ota_payments as payments
        from app.ota_review import OtaReviewStore
        from webapp.ota_payment_review import CoreOtaPaymentBackend

        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as directory:
            board_path = Path(directory) / "synthetic-board.sqlite"
            review_path = Path(directory) / "synthetic-review.sqlite"
            board_conn = sqlite3.connect(board_path, check_same_thread=False)
            board_conn.row_factory = sqlite3.Row
            self.addCleanup(board_conn.close)
            board_conn.execute("""CREATE TABLE transactions (
                transaction_id TEXT,source_hash TEXT,merchant TEXT,merchant_normalized TEXT,
                issuer TEXT,card_tail TEXT,approval_date TEXT,transaction_direction TEXT,
                amount_krw INTEGER,duplicate_of TEXT,parse_error TEXT,conflict_reason TEXT)""")
            board_conn.executemany("INSERT INTO transactions VALUES (?,?,?,?,?,?,?,?,?,?,?,?)", [
                (f"partial-card-{index}", f"hash-{index}", "TRIP.COM", "trip.com", "Bank A", "2042",
                 "2026-09-04", "purchase", 12500, None, None, None) for index in range(2)])
            board_conn.commit()
            events = [{**EVENT, "ota_event_id":f"partial-event-{index}",
                       "provider": "trip",
                       "booking_ref":f"BOOK-PARTIAL-{index}", "card_last4":"2042",
                       "evidence_status":"paid_verified", "payment_status":"paid",
                       "source_digest":f"partial-source-{index}"} for index in range(3)]
            backend = CoreOtaPaymentBackend(SimpleNamespace(conn=board_conn, _lock=threading.RLock()),
                str(review_path), read_only=False, payments=payments, store_type=OtaReviewStore, sources={})
            self.addCleanup(backend.close)
            with mock.patch.object(ota_payment_review, "enabled", return_value=True), \
                 mock.patch.object(payments, "build_ota_payment_events", side_effect=lambda _sources: events):
                snapshot = backend.snapshot()
                self.assertEqual({row["status"] for row in snapshot["events"]}, {"MATCHED_GROUP"})
                self.assertTrue(all(len(row['payment_relation']['transaction_ids']) == 2
                                    for row in snapshot['events']))
                self.assertTrue(all(row['selection_disabled'] for rows in snapshot['cards_by_event'].values()
                                    for row in rows))
                status, _response = _local_review_request(lambda: CoreOtaPaymentBackend(
                    SimpleNamespace(conn=board_conn, _lock=threading.RLock()), str(review_path), read_only=False,
                    payments=payments, store_type=OtaReviewStore, sources={}), "/api/imports/ota/group/confirm",
                    {"event_ids":[row["ota_event_id"] for row in events],
                     "request_id":"partial-group-rejected"})
            self.assertEqual(status, 422)
            self.assertFalse(review_path.exists())
            backend.close()
            board_conn.close()

    def test_acceptance_04_05_signed_lag_range_round_trips_over_http_sqlite_and_matcher(self):
        import app.ota_payments as payments
        from app.ota_review import OtaReviewStore
        from webapp.ota_payment_review import CoreOtaPaymentBackend

        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as directory:
            board_path = Path(directory) / "synthetic-board.sqlite"
            review_path = Path(directory) / "synthetic-review.sqlite"
            board_conn = sqlite3.connect(board_path, check_same_thread=False)
            board_conn.row_factory = sqlite3.Row
            self.addCleanup(board_conn.close)
            board_conn.execute("CREATE TABLE transactions (transaction_id TEXT)")
            board_conn.commit()
            candidate = {**EVENT, "ota_event_id":"lag-range-event", "provider":"trip",
                "item":"Synthetic flight", "event_type":"charge", "evidence_status":"paid_verified",
                "payment_status":"paid", "paid_on":"2026-09-04", "amount":100000,
                "amount_krw":100000, "currency":"KRW", "card_last4":"2042", "source_digest":"lag-source"}
            transaction = {"transaction_id":"lag-source-card", "issuer":"Bank A", "merchant":"TRIP.COM",
                "merchant_normalized":"trip.com", "card_tail":"2042", "approval_date":"2026-09-03",
                "transaction_direction":"purchase", "amount_krw":96000}
            setup = OtaReviewStore(review_path)
            preview = setup.preview(candidate, transaction)
            confirmed = setup.confirm(candidate, transaction, preview["preview_digest"],
                request_id="create-pending-proposal", user="synthetic-owner", allocations={})
            proposal_id = confirmed["proposal_id"]
            self.assertEqual(setup.active_rules(), [])
            setup.close()
            backend = CoreOtaPaymentBackend(SimpleNamespace(conn=board_conn, _lock=threading.RLock()),
                str(review_path), read_only=False, payments=payments, store_type=OtaReviewStore, sources={})
            self.addCleanup(backend.close)
            conditions = {"provider":"trip", "item":"Synthetic flight", "merchant_normalized":"trip.com",
                "issuer":"Bank A", "card_last4":"2042", "currency":"KRW", "event_type":"charge",
                "amount_delta_krw":-4000, "date_lag_min_days":-1, "date_lag_max_days":2}
            with mock.patch.object(ota_payment_review, "enabled", return_value=True):
                status, response = _local_review_request(lambda: CoreOtaPaymentBackend(
                    SimpleNamespace(conn=board_conn, _lock=threading.RLock()), str(review_path), read_only=False,
                    payments=payments, store_type=OtaReviewStore, sources={}), "/api/imports/ota/proposal",
                    {"proposal_id":proposal_id, "action":"approve", "conditions":conditions})
            self.assertEqual(status, 200, response)
            self.assertTrue(response["active"])
            rules = backend.store.active_rules()
            self.assertEqual(len(rules), 1)
            self.assertEqual(rules[0]["conditions"]["date_lag_min_days"], -1)
            self.assertEqual(rules[0]["conditions"]["date_lag_max_days"], 2)
            self.assertEqual(backend.store.conn.execute(
                "SELECT COUNT(*) FROM ota_review_rules WHERE active=1").fetchone()[0], 1)
            from datetime import date, timedelta
            rows = [{**transaction, "transaction_id":f"range-card-{offset}",
                     "approval_date":(date.fromisoformat(str(candidate["paid_on"]))+timedelta(days=offset)).isoformat()}
                    for offset in (-2, -1, 0, 1, 2, 3)]
            candidates = payments.same_date_cards(candidate, rows, rules=rules)
            self.assertEqual({row["transaction_id"] for row in candidates},
                             {"range-card--1", "range-card-0", "range-card-1", "range-card-2"})
            matcher_result = payments.match_ota_payment_events([candidate], rows, rules=rules)[0]
            self.assertEqual(matcher_result["status"], "MATCHED_GROUP")
            self.assertEqual(set(matcher_result["candidates"]),
                             {"range-card--1", "range-card-0", "range-card-1", "range-card-2"})
            backend.close()
            board_conn.close()

    def test_cards_for_event_equivalence_with_snapshot_from_financial_logic(self):
        """Test that cards_for_event returns identical financial post-processing as snapshot_from.

        Verifies risk cases:
        - Group/partial group holds disable individual selection
        - Already occupied cards from other events show already_linked_*
        - Amount/date mismatches produce correct selection_disabled + reason
        - Reservation history cards are included with selection_disabled
        - Rejected candidates (AMOUNT_MISMATCH, CURRENCY_MISMATCH) appear with correct reason
        """
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as directory, ExitStack() as resources:
            board_path = Path(directory) / "board.sqlite"
            review_path = Path(directory) / "review.sqlite"
            board_conn = sqlite3.connect(board_path, check_same_thread=False)
            resources.callback(board_conn.close)
            board_conn.row_factory = sqlite3.Row
            board_conn.executescript("""
                CREATE TABLE transactions (
                    transaction_id TEXT, source_hash TEXT, merchant TEXT, merchant_normalized TEXT,
                    issuer TEXT, card_tail TEXT, transaction_direction TEXT, approval_date TEXT,
                    posting_date TEXT, amount_krw INTEGER, classification_state TEXT,
                    classification_source TEXT, duplicate_of TEXT, parse_error TEXT, conflict_reason TEXT,
                    foreign_amount TEXT, currency TEXT, foreign_currency TEXT,
                    authorization_id TEXT, cancellation_status TEXT, refund_status TEXT
                );
                CREATE TABLE board_rows (row_id TEXT, row_kind TEXT);
            """)
            board_conn.executemany("""INSERT INTO transactions VALUES
                (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""", [
                # Base event cards (same date)
                ("card-base-01", "hash-01", "Hotel A", "hotel-a", "Bank A", "1111", "purchase", "2026-09-04", "2026-09-05", 100000, "classified", "automatic", "", "", "", "100.00", "USD", "USD", "AUTH-01", "not_cancelled", "no_refund"),
                ("card-base-02", "hash-02", "Hotel A", "hotel-a", "Bank A", "2222", "purchase", "2026-09-04", "2026-09-05", 105000, "classified", "automatic", "", "", "", "105.00", "USD", "USD", "AUTH-02", "not_cancelled", "no_refund"),
                # Occupied by another event
                ("card-occupied", "hash-occ", "Hotel B", "hotel-b", "Bank B", "3333", "purchase", "2026-09-04", "2026-09-05", 100000, "classified", "automatic", "", "", "", "100.00", "USD", "USD", "AUTH-OCC", "not_cancelled", "no_refund"),
                # Amount mismatch
                ("card-amount-mismatch", "hash-amt", "Hotel A", "hotel-a", "Bank A", "4444", "purchase", "2026-09-04", "2026-09-05", 90000, "classified", "automatic", "", "", "", "90.00", "USD", "USD", "AUTH-AMT", "not_cancelled", "no_refund"),
                # Currency mismatch
                ("card-currency-mismatch", "hash-cur", "Hotel A", "hotel-a", "Bank A", "5555", "purchase", "2026-09-04", "2026-09-05", 100000, "classified", "automatic", "", "", "", "90.00", "EUR", "EUR", "AUTH-CUR", "not_cancelled", "no_refund"),
                # Date unknown
                ("card-date-unknown", "hash-dat", "Hotel A", "hotel-a", "Bank A", "6666", "purchase", "2026-09-01", "2026-09-02", 100000, "classified", "automatic", "", "", "", "100.00", "USD", "USD", "AUTH-DAT", "not_cancelled", "no_refund"),
                # History card (already confirmed)
                ("card-history", "hash-hist", "Hotel A", "hotel-a", "Bank A", "7777", "purchase", "2026-09-04", "2026-09-05", 100000, "classified", "automatic", "", "", "", "100.00", "USD", "USD", "AUTH-HIST", "not_cancelled", "no_refund"),
            ])
            board_conn.commit()

            # Create review DB with a confirmed link for card-history
            review_path.touch()
            from app.ota_review import OtaReviewStore
            store = OtaReviewStore(str(review_path))
            event = {
                "ota_event_id": "evt-test", "provider": "agoda", "booking_ref": "BOOK-001",
                "event_type": "charge", "paid_on": "2026-09-04", "amount": 100000,
                "amount_krw": 100000, "currency": "KRW", "source_digest": "digest-test",
                "evidence_status": "paid_verified", "payment_status": "paid"
            }
            transaction = {
                "transaction_id": "card-history", "merchant": "Hotel A", "amount_krw": 100000,
                "approval_date": "2026-09-04", "posting_date": "2026-09-05"
            }
            preview = store.preview(event, transaction)
            store.confirm(event, transaction, preview["preview_digest"],
                          request_id="req-hist", user="test", allocations={})
            occupied_event = {
                "ota_event_id": "evt-other", "provider": "synthetic", "booking_ref": "BOOK-OTHER",
                "event_type": "charge", "paid_on": "2026-09-04", "amount": 100000,
                "amount_krw": 100000, "currency": "KRW", "source_digest": "digest-other",
                "evidence_status": "paid_verified", "payment_status": "paid"
            }
            occupied_transaction = {
                "transaction_id": "card-occupied", "merchant": "Hotel B", "amount_krw": 100000,
                "approval_date": "2026-09-04", "posting_date": "2026-09-05"
            }
            occupied_preview = store.preview(occupied_event, occupied_transaction)
            store.confirm(occupied_event, occupied_transaction, occupied_preview["preview_digest"],
                          request_id="req-occupied", user="test", allocations={})
            store.close()
            # Ensure store connection is closed before temp dir cleanup

            # Build backend
            from app import ota_payments
            payments = ota_payments

            class TestPayments:
                def build_ota_payment_events(self, _sources):
                    return [{
                        "ota_event_id": "evt-test", "provider": "agoda", "booking_ref": "BOOK-001",
                        "event_type": "charge", "paid_on": "2026-09-04",
                        "amount": 100000, "amount_krw": 100000, "currency": "KRW",
                        "service_period": {"starts_on": "2026-10-01", "ends_on": "2026-10-03"},
                        "item": "Standard Room", "source_digest": "digest-test",
                        "status": "HOLD_AMBIGUOUS", "reason": "Multiple candidates"
                    }]

                def match_ota_payment_events(self, events, transactions, *, existing_links=None, rules=None, frozen_groups=None):
                    return [{
                        "ota_event_id": "evt-test", "status": "HOLD_AMBIGUOUS",
                        "reason": "Multiple candidates",
                        "candidate_search": {
                            "status": "CANDIDATES_FOUND",
                            "candidates": [
                                {"transaction_id": "card-base-01", "basis": "HOTEL_AND_STAY_AND_AMOUNT", "amount_status": "MATCH", "stay_date_status": "MATCH", "resolution_allowed": True, "date_status": "MATCH"},
                                {"transaction_id": "card-base-02", "basis": "HOTEL_AND_STAY_AND_AMOUNT", "amount_status": "MISMATCH", "stay_date_status": "MATCH", "resolution_allowed": True, "date_status": "MATCH"},
                                {"transaction_id": "card-occupied", "basis": "HOTEL_AND_STAY_AND_AMOUNT", "amount_status": "MATCH", "stay_date_status": "MATCH", "resolution_allowed": True, "date_status": "MATCH"},
                                {"transaction_id": "card-amount-mismatch", "basis": "HOTEL_AND_STAY_ONLY", "amount_status": "MISMATCH", "stay_date_status": "MATCH", "resolution_allowed": False, "date_status": "MATCH"},
                                {"transaction_id": "card-currency-mismatch", "basis": "HOTEL_AND_STAY_ONLY", "amount_status": "CURRENCY_MISMATCH", "stay_date_status": "MATCH", "resolution_allowed": False, "date_status": "MATCH"},
                                {"transaction_id": "card-date-unknown", "basis": "HOTEL_BRANCH_AND_STAY_ONLY", "amount_status": "MATCH", "stay_date_status": "UNKNOWN", "resolution_allowed": False, "date_status": "UNKNOWN"},
                            ],
                            "rejected": [
                                {"transaction_id": "card-amount-mismatch", "reason": "AMOUNT_MISMATCH"},
                                {"transaction_id": "card-currency-mismatch", "reason": "CURRENCY_MISMATCH"},
                            ],
                            "date_status": "MATCH"
                        },
                        "reservation_link": {
                            "status": "USER_CONFIRMED",
                            "transaction_id": "card-history",
                            "basis": "USER",
                            "amount_status": "MATCH",
                            "payment_verified": False
                        }
                    }]

                def same_date_cards(self, event, transactions, *, links=None, rules=None):
                    paid_on = event.get("paid_on")
                    return [t for t in transactions if t.get("approval_date") == paid_on]

                def search_card_candidates(self, event, transactions, *, existing_links=None, rules=None):
                    return self.match_ota_payment_events([event], transactions, existing_links=existing_links, rules=rules)[0]["candidate_search"]

                def _event_is_paid(self, event):
                    return True

            test_payments = TestPayments()
            backend = ota_payment_review.CoreOtaPaymentBackend(
                SimpleNamespace(conn=board_conn, _lock=threading.RLock()),
                str(review_path), read_only=True,
                payments=test_payments, store_type=OtaReviewStore, sources={})
            resources.callback(backend.close)

            # Get snapshot_from with cards (full build)
            data = backend._data()
            snapshot_full = backend.snapshot_from(data, include_cards=True)
            snapshot_cards = snapshot_full["cards_by_event"]["evt-test"]
            backend._action_data = lambda: (dict(zip(('events', 'transactions', 'links', 'results'), data)), {})

            # Get cards_for_event (per-event build)
            cards_endpoint = [ota_payment_review._sanitize_card_row(card)
                              for card in backend.cards_for_event("evt-test")]

            # Verify equivalence of key financial fields
            by_txn_snapshot = {c["transaction_id"]: c for c in snapshot_cards}
            by_txn_endpoint = {c["transaction_id"]: c for c in cards_endpoint}

            self.assertEqual(set(by_txn_snapshot.keys()), set(by_txn_endpoint.keys()))

            for txn_id in by_txn_snapshot:
                s = by_txn_snapshot[txn_id]
                e = by_txn_endpoint[txn_id]
                # Core financial fields must match
                self.assertEqual(s.get("reservation_candidate"), e.get("reservation_candidate"), f"reservation_candidate mismatch for {txn_id}")
                self.assertEqual(s.get("reservation_candidate_basis"), e.get("reservation_candidate_basis"), f"basis mismatch for {txn_id}")
                self.assertEqual(s.get("reservation_amount_status"), e.get("reservation_amount_status"), f"amount_status mismatch for {txn_id}")
                self.assertEqual(s.get("reservation_stay_date_status"), e.get("reservation_stay_date_status"), f"stay_date_status mismatch for {txn_id}")
                self.assertEqual(s.get("selection_disabled"), e.get("selection_disabled"), f"selection_disabled mismatch for {txn_id}")
                self.assertEqual(s.get("selection_disabled_reason"), e.get("selection_disabled_reason"), f"selection_disabled_reason mismatch for {txn_id}")
                self.assertEqual(s.get("already_linked_event_id"), e.get("already_linked_event_id"), f"already_linked_event_id mismatch for {txn_id}")
                self.assertEqual(s.get("already_linked_reason"), e.get("already_linked_reason"), f"already_linked_reason mismatch for {txn_id}")
                self.assertEqual(s.get("candidate_date_status"), e.get("candidate_date_status"), f"candidate_date_status mismatch for {txn_id}")
                self.assertEqual(s.get("candidate_rejection_reason"), e.get("candidate_rejection_reason"), f"candidate_rejection_reason mismatch for {txn_id}")
                self.assertEqual(s.get("reservation_history"), e.get("reservation_history"), f"reservation_history mismatch for {txn_id}")

            # Verify specific risk cases
            # 1. card-occupied should show already_linked to another event
            occ = by_txn_endpoint["card-occupied"]
            self.assertEqual(occ.get("already_linked_event_id"), "evt-other")
            self.assertEqual(occ.get("already_linked_reason"), "다른 예약에 연결됨")

            # 2. card-amount-mismatch should be disabled with correct reason
            amt = by_txn_endpoint["card-amount-mismatch"]
            self.assertTrue(amt.get("selection_disabled"))
            self.assertEqual(amt.get("candidate_rejection_reason"), "AMOUNT_MISMATCH")
            self.assertIn("결제 금액이 다릅니다", amt.get("selection_disabled_reason", ""))

            # 3. card-currency-mismatch should be disabled with correct reason
            cur = by_txn_endpoint["card-currency-mismatch"]
            self.assertTrue(cur.get("selection_disabled"))
            self.assertEqual(cur.get("candidate_rejection_reason"), "CURRENCY_MISMATCH")
            self.assertIn("결제 통화가 다릅니다", cur.get("selection_disabled_reason", ""))

            # 4. card-date-unknown should be disabled with UNKNOWN reason
            dat = by_txn_endpoint["card-date-unknown"]
            self.assertTrue(dat.get("selection_disabled"))
            self.assertEqual(dat.get("candidate_date_status"), "UNKNOWN")
            self.assertEqual(dat.get("selection_disabled_reason"), "OTA_PAYMENT_DATE_UNKNOWN")

            # 5. card-history should have reservation_history=True and be disabled
            hist = by_txn_endpoint["card-history"]
            self.assertTrue(hist.get("reservation_history"))
            self.assertTrue(hist.get("selection_disabled"))
            self.assertIn("선택 이력", hist.get("selection_disabled_reason", ""))

            # 6. Valid candidate (card-base-01) should NOT be disabled (no hold/group)
            valid = by_txn_endpoint["card-base-01"]
            self.assertFalse(valid.get("selection_disabled"))
            self.assertTrue(valid.get("reservation_candidate"))

            backend.close()
            board_conn.close()

    def test_snapshot_excludes_full_cards_but_includes_card_candidate_count(self):
        """Verify public snapshot (include_cards=False) does NOT build full card rows
        but still includes accurate card_candidate_count for UI badges.
        """
        from webapp.ota_payment_review import CoreOtaPaymentBackend
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as directory, ExitStack() as resources:
            board_path = Path(directory) / "board.sqlite"
            review_path = Path(directory) / "review.sqlite"
            board_conn = sqlite3.connect(board_path, check_same_thread=False)
            resources.callback(board_conn.close)
            board_conn.row_factory = sqlite3.Row
            board_conn.executescript("""
                CREATE TABLE transactions (
                    transaction_id TEXT, source_hash TEXT, merchant TEXT, merchant_normalized TEXT,
                    issuer TEXT, card_tail TEXT, transaction_direction TEXT, approval_date TEXT,
                    posting_date TEXT, amount_krw INTEGER, classification_state TEXT,
                    classification_source TEXT, duplicate_of TEXT, parse_error TEXT, conflict_reason TEXT,
                    foreign_amount TEXT, currency TEXT, foreign_currency TEXT,
                    authorization_id TEXT, cancellation_status TEXT, refund_status TEXT
                );
                CREATE TABLE board_rows (row_id TEXT, row_kind TEXT);
            """)
            # Create 500 candidate cards (simulating large scale)
            rows = []
            for i in range(500):
                rows.append((
                    f"card-{i:03d}", f"hash-{i:03d}", f"Hotel {i%10}", f"hotel-{i%10}",
                    "Bank A", f"{i:04d}", "purchase", "2026-09-04", "2026-09-05",
                    100000 + i, "classified", "automatic", "", "", "",
                    "100.00", "USD", "USD", f"AUTH-{i:03d}", "not_cancelled", "no_refund"
                ))
            board_conn.executemany("""INSERT INTO transactions VALUES
                (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""", rows)
            board_conn.commit()

            review_path.touch()
            from app.ota_review import OtaReviewStore
            from app import ota_payments

            class ScalePayments:
                def build_ota_payment_events(self, _sources):
                    return [{
                        "ota_event_id": "evt-scale", "provider": "agoda", "booking_ref": "BOOK-SCALE",
                        "event_type": "charge", "paid_on": "2026-09-04",
                        "amount": 100000, "amount_krw": 100000, "currency": "KRW",
                        "service_period": {"starts_on": "2026-10-01", "ends_on": "2026-10-03"},
                        "item": "Standard Room", "source_digest": "digest-scale",
                        "status": "HOLD_AMBIGUOUS", "reason": "Many candidates"
                    }]

                def match_ota_payment_events(self, events, transactions, *, existing_links=None, rules=None, frozen_groups=None):
                    # All 500 cards are candidates
                    candidates = [
                        {"transaction_id": f"card-{i:03d}", "basis": "HOTEL_AND_STAY_AND_AMOUNT",
                         "amount_status": "MATCH" if i == 0 else "MISMATCH", "stay_date_status": "MATCH",
                         "resolution_allowed": True, "date_status": "MATCH"}
                        for i in range(500)
                    ]
                    return [{
                        "ota_event_id": "evt-scale", "status": "HOLD_AMBIGUOUS",
                        "reason": "Many candidates",
                        "candidate_search": {
                            "status": "CANDIDATES_FOUND",
                            "candidates": candidates,
                            "rejected": [],
                            "date_status": "MATCH"
                        }
                    }]

                def same_date_cards(self, event, transactions, *, links=None, rules=None):
                    paid_on = event.get("paid_on")
                    return [t for t in transactions if t.get("approval_date") == paid_on]

                def search_card_candidates(self, event, transactions, *, existing_links=None, rules=None):
                    return self.match_ota_payment_events([event], transactions, existing_links=existing_links, rules=rules)[0]["candidate_search"]

                def _event_is_paid(self, event):
                    return True

            scale_payments = ScalePayments()
            from webapp.ota_payment_review import public_snapshot
            backend = CoreOtaPaymentBackend(
                SimpleNamespace(conn=board_conn, _lock=threading.RLock()),
                str(review_path), read_only=True,
                payments=scale_payments, store_type=OtaReviewStore, sources={})
            resources.callback(backend.close)

            # Call snapshot_from with include_cards=False (public path)
            data = backend._data()
            snapshot_no_cards = backend.snapshot_from(data, include_cards=False)

            # Verify cards_by_event is empty (no full rows built)
            self.assertEqual(snapshot_no_cards["cards_by_event"], {})

            # Verify card_candidate_count is present and correct (500 candidates)
            self.assertEqual(len(snapshot_no_cards["events"]), 1)
            event = snapshot_no_cards["events"][0]
            self.assertIn("card_candidate_count", event)
            self.assertEqual(event["card_candidate_count"], 500)

            # Verify that _event_rows was NOT called for the 500 cards by checking
            # that the public snapshot doesn't have the full card data
            public = public_snapshot(snapshot_no_cards, include_cards=False)
            self.assertEqual(public["cards_by_event"], {})
            self.assertEqual(public["events"][0]["card_candidate_count"], 500)

            backend.close()
            board_conn.close()

    def test_cards_for_event_handles_event_not_in_holds(self):
        """cards_for_event should return correct rows even for events not in holds list.

        Events with status MATCHED_AUTO (not HOLD) don't appear in holds but
        cards_for_event should still return their card rows with correct financial logic.
        """
        from webapp.ota_payment_review import CoreOtaPaymentBackend
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as directory, ExitStack() as resources:
            board_path = Path(directory) / "board.sqlite"
            review_path = Path(directory) / "review.sqlite"
            board_conn = sqlite3.connect(board_path, check_same_thread=False)
            resources.callback(board_conn.close)
            board_conn.row_factory = sqlite3.Row
            board_conn.executescript("""
                CREATE TABLE transactions (
                    transaction_id TEXT, source_hash TEXT, merchant TEXT, merchant_normalized TEXT,
                    issuer TEXT, card_tail TEXT, transaction_direction TEXT, approval_date TEXT,
                    posting_date TEXT, amount_krw INTEGER, classification_state TEXT,
                    classification_source TEXT, duplicate_of TEXT, parse_error TEXT, conflict_reason TEXT,
                    foreign_amount TEXT, currency TEXT, foreign_currency TEXT,
                    authorization_id TEXT, cancellation_status TEXT, refund_status TEXT
                );
                CREATE TABLE board_rows (row_id TEXT, row_kind TEXT);
            """)
            board_conn.executemany("""INSERT INTO transactions VALUES
                (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""", [
                ("card-matched", "hash-m", "Hotel M", "hotel-m", "Bank M", "9999", "purchase", "2026-09-04", "2026-09-05", 100000, "classified", "automatic", "", "", "", "100.00", "USD", "USD", "AUTH-M", "not_cancelled", "no_refund"),
            ])
            board_conn.commit()

            review_path.touch()
            from app.ota_review import OtaReviewStore

            class MatchedPayments:
                def build_ota_payment_events(self, _sources):
                    return [{
                        "ota_event_id": "evt-matched", "provider": "agoda", "booking_ref": "BOOK-MATCHED",
                        "event_type": "charge", "paid_on": "2026-09-04",
                        "amount": 100000, "amount_krw": 100000, "currency": "KRW",
                        "service_period": {"starts_on": "2026-10-01", "ends_on": "2026-10-03"},
                        "item": "Standard Room", "source_digest": "digest-matched",
                        "status": "MATCHED_AUTO", "transaction_id": "card-matched",
                        "inferred_link": True, "inference_basis": "EXACT_MATCH"
                    }]

                def match_ota_payment_events(self, events, transactions, *, existing_links=None, rules=None, frozen_groups=None):
                    return [{
                        "ota_event_id": "evt-matched", "status": "MATCHED_AUTO",
                        "transaction_id": "card-matched",
                        "inferred_link": True, "inference_basis": "EXACT_MATCH",
                        "candidate_search": {"status": "NO_CANDIDATE", "candidates": [], "rejected": []}
                    }]

                def same_date_cards(self, event, transactions, *, links=None, rules=None):
                    paid_on = event.get("paid_on")
                    return [t for t in transactions if t.get("approval_date") == paid_on]

                def search_card_candidates(self, event, transactions, *, existing_links=None, rules=None):
                    return {"status": "NO_CANDIDATE", "candidates": [], "rejected": []}

                def _event_is_paid(self, event):
                    return True

            matched_payments = MatchedPayments()
            backend = CoreOtaPaymentBackend(
                SimpleNamespace(conn=board_conn, _lock=threading.RLock()),
                str(review_path), read_only=True,
                payments=matched_payments, store_type=OtaReviewStore, sources={})
            resources.callback(backend.close)

            # This event is MATCHED_AUTO (not a HOLD) so it won't be in holds
            # But cards_for_event should still work
            data = backend._data()
            backend._action_data = lambda: (dict(zip(('events', 'transactions', 'links', 'results'), data)), {})
            cards = backend.cards_for_event("evt-matched")

            # Should return the matched card row
            self.assertEqual(len(cards), 1)
            self.assertEqual(cards[0]["transaction_id"], "card-matched")
            # A payment match is distinct from a reservation relation, so it remains selectable here.
            self.assertFalse(cards[0].get("selection_disabled", False))

            backend.close()
            board_conn.close()
