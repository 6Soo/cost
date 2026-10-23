"""Synthetic contract tests for the isolated OTA payment review surface."""
import json
import os
import sqlite3
import tempfile
import threading
import unittest
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
                 "source_digest": "secret-digest", "raw_row_json": "secret-event"}
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
    def setUp(self):
        FakeCorePayments.occupied_transaction = "card-00"
        self.environment = mock.patch.dict(os.environ, {
            "WEBLEDGER_OTA_REVIEW_MODE": "isolated",
            "WEBLEDGER_OTA_REVIEW_DB": "C:/synthetic/review.sqlite",
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
            "WEBLEDGER_OTA_REVIEW_DB": "C:/synthetic/review.sqlite",
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
        self.assertEqual(len(snapshot["cards_by_event"][EVENT["ota_event_id"]]), 12)
        self.assertEqual(snapshot["cards_by_event"][EVENT["ota_event_id"]][11]["merchant"], "Merchant 11")
        self.assertEqual(snapshot["cards_by_event"][EVENT["ota_event_id"]][11]["approval_number"], "AUTH-11")
        self.assertEqual(snapshot["cards_by_event"][EVENT["ota_event_id"]][11]["already_linked_event_id"], "evt-synth-other")
        self.assertEqual(snapshot["cards_by_event"][EVENT["ota_event_id"]][11]["already_linked_label"], "다른 예약")
        self.assertIn("다음 결제에도 적용할까요?", snapshot["proposals"][0]["question"])
        serialized = json.dumps(snapshot)
        for forbidden in ("raw_row_json", "classification_private", "source_inventory",
                          "private-fixture-path", "secret-event", "source_digest"):
            self.assertNotIn(forbidden, serialized)
        self.assertEqual([call[0] for call in backend.calls], ["snapshot"])

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
        self.assertEqual(set(holds), {"card-syn-1", "card-syn-2", "frozen-card-a", "frozen-card-b"})
        self.assertEqual(holds["card-syn-1"]["kind"], "ota_group_review")
        self.assertEqual(holds["card-syn-1"]["ota_event_ids"], ["ota-syn-1"])
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
            "WEBLEDGER_OTA_REVIEW_DB": "C:/synthetic/review.sqlite",
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
            "WEBLEDGER_OTA_REVIEW_DB": "C:/synthetic/review.sqlite",
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
            primed(board, backend)
            before = Path(review_path).stat().st_mtime_ns
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

    def test_import_post_passes_only_new_transaction_ids_to_ota_refresh_hook(self):
        backend = FakeBackend()
        board = object()

        class FakePipeline:
            def receive(self, _raw, _filename):
                return {"batch_id": "synthetic-batch"}

        class FakeFlow:
            pipeline = FakePipeline()

            def __init__(self, _board):
                pass

            def classify(self, _batch_id):
                pass

            def state(self, _batch_id):
                return {"rows": [{"transaction_id": "new-01"}, {"transaction_id": "new-02"}]}

            def auto_record(self, _batch_id):
                return {"rows": [{"transaction_id": "new-01"}, {"transaction_id": "new-02"}], "auto_recorded": 0}

        handler = FakeHandler(backend, "/api/imports", b"synthetic card file")
        with mock.patch.dict(os.environ, {
            "WEBLEDGER_CARD_FLOW": "1", "WEBLEDGER_OTA_REVIEW_MODE": "isolated",
            "WEBLEDGER_OTA_REVIEW_DB": "C:/synthetic/review.sqlite",
        }, clear=True), mock.patch("webapp.ledger_board._active_store", return_value=board), \
                mock.patch.object(card_flow, "CardFlow", FakeFlow):
            adapter = lambda **_kwargs: backend
            ota_payment_review.configure_backend_factory(read_factory=adapter, write_factory=adapter)
            self.addCleanup(ota_payment_review.configure_backend_factory,
                            read_factory=None, write_factory=None)
            self.assertTrue(card_flow.dispatch(handler, urlsplit(handler.path), raw=handler.raw,
                                               csrf="token-synth"))
        self.assertEqual(handler.response[2]["ota_refresh_status"], "refreshed")
        self.assertEqual(backend.calls[-1], ("refresh_after_import", ["new-01", "new-02"]))

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
            "events": [], "cards_by_event": {EVENT["ota_event_id"]: rows}, "proposals": []})
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
        once = ota_payment_review.public_snapshot(raw)["cards_by_event"]["evt-direction"]
        twice = ota_payment_review.public_snapshot({"events": [], "cards_by_event": {"evt-direction": once},
                                                     "proposals": []})["cards_by_event"]["evt-direction"]
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
                       "booking_ref":f"BOOK-PARTIAL-{index}", "card_last4":"2042",
                       "evidence_status":"paid_verified", "payment_status":"paid",
                       "source_digest":f"partial-source-{index}"} for index in range(3)]
            backend = CoreOtaPaymentBackend(SimpleNamespace(conn=board_conn, _lock=threading.RLock()),
                str(review_path), read_only=False, payments=payments, store_type=OtaReviewStore, sources={})
            self.addCleanup(backend.close)
            with mock.patch.object(ota_payment_review, "enabled", return_value=True), \
                 mock.patch.object(payments, "build_ota_payment_events", side_effect=lambda _sources: events):
                snapshot = backend.snapshot()
                self.assertEqual({row["status"] for row in snapshot["events"]}, {"HOLD_PARTIAL_GROUP"})
                self.assertTrue(all(row["selection_disabled"] for rows in snapshot["cards_by_event"].values()
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
            self.assertEqual(matcher_result["status"], "HOLD_PARTIAL_GROUP")
            self.assertEqual(set(matcher_result["candidates"]),
                             {"range-card--1", "range-card-0", "range-card-1", "range-card-2"})
            backend.close()
            board_conn.close()
