"""Local synthetic browser checks for the opt-in OTA HOLD review surface."""
import json
import hashlib
import os
import sqlite3
import tempfile
import threading
import unittest
from datetime import datetime, timezone, timedelta
from email.utils import format_datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest import mock
from unittest.mock import patch
from urllib.parse import urlsplit

from playwright.sync_api import sync_playwright

from webapp import ota_payment_review
from webapp import card_flow
from webapp.tests.test_ota_payment_review import FakeBackend


class OtaReviewBrowserTests(unittest.TestCase):
    def test_amount_mismatch_candidate_is_explained_but_cannot_be_confirmed(self):
        snapshot = ota_payment_review.public_snapshot({
            "events": [{"ota_event_id": "synthetic-amount-event", "provider": "Synthetic OTA",
                        "booking_ref": "SYNTHETIC-AMOUNT-BOOKING", "event_type": "charge",
                        "paid_on": "2026-10-01", "amount": 31000, "amount_krw": 31000,
                        "status": "HOLD_AMOUNT_MISMATCH", "reason": "amount_differs",
                        "candidate_search_status": "NO_CANDIDATE", "candidate_rejected_count": 1}],
            "cards_by_event": {"synthetic-amount-event": [{
                "transaction_id": "synthetic-amount-card", "issuer": "Synthetic Bank",
                "merchant": "AGODA.COM", "amount_krw": 30000, "approval_date": "2026-10-01",
                "transaction_direction": "purchase", "candidate_date_status": "MISMATCH",
                "candidate_resolution_allowed": False, "candidate_rejection_reason": "AMOUNT_MISMATCH",
                "selection_disabled": True, "selection_disabled_reason": "카드 정보는 일부 맞지만 결제 금액이 다릅니다."}]},
            "proposals": []})

        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            try:
                page = browser.new_page(viewport={"width": 390, "height": 844})
                page.route("**/api/imports/ota", lambda route: route.fulfill(
                    status=200, content_type="application/json",
                    body=json.dumps(snapshot, ensure_ascii=False)))
                page.set_content("<base href='http://localhost/'>" +
                                 ota_payment_review.render_import_section("token-synth"))
                event = page.locator('[data-event="synthetic-amount-event"]')
                event.get_by_text("SYNTHETIC-AMOUNT-BOOKING", exact=False).first.wait_for()
                self.assertIn("\uC81C\uC678\uD55C \uCE74\uB4DC \uD6C4\uBCF4: 1\uAC74", event.inner_text())
                card = event.locator(".ota-card-row")
                self.assertIn("결제 금액이 다릅니다", card.inner_text())
                self.assertTrue(card.locator("input[type=radio]").is_disabled())
                self.assertTrue(event.locator("button[data-preview]").is_disabled())
            finally:
                browser.close()

    def test_undated_payment_candidate_is_visible_but_cannot_be_confirmed(self):
        snapshot = ota_payment_review.public_snapshot({
            "events": [{"ota_event_id": "synthetic-undated-event", "provider": "Synthetic OTA",
                        "booking_ref": "SYNTHETIC-UNCONFIRMED-BOOKING", "event_type": "charge",
                        "paid_on": "미확정", "amount": 30000, "amount_krw": 30000,
                        "status": "HOLD_DATE_UNKNOWN", "reason": "payment_date_not_in_source",
                        "candidate_search_status": "CANDIDATES_FOUND", "candidate_date_status": "UNKNOWN",
                        "candidate_count": 1}],
            "cards_by_event": {"synthetic-undated-event": [{
                "transaction_id": "synthetic-undated-card", "issuer": "Synthetic Bank",
                "merchant": "AGODA.COM", "amount_krw": 30000, "approval_date": "2026-10-01",
                "transaction_direction": "purchase", "candidate_date_status": "UNKNOWN",
                "candidate_resolution_allowed": False, "selection_disabled": True}]},
            "proposals": []})

        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            try:
                page = browser.new_page(viewport={"width": 390, "height": 844})
                page.route("**/api/imports/ota", lambda route: route.fulfill(
                    status=200, content_type="application/json",
                    body=json.dumps(snapshot, ensure_ascii=False)))
                page.set_content("<base href='http://localhost/'>" +
                                 ota_payment_review.render_import_section("token-synth"))
                event = page.locator('[data-event="synthetic-undated-event"]')
                event.get_by_text("SYNTHETIC-UNCONFIRMED-BOOKING", exact=False).first.wait_for()
                card = event.locator(".ota-card-row")
                self.assertEqual(card.count(), 1)
                self.assertIn("결제일이 확인되지 않아 OTA 연결을 확정할 수 없습니다.", card.inner_text())
                self.assertTrue(card.locator("input[type=radio]").is_disabled())
                self.assertTrue(event.locator("button[data-preview]").is_disabled())
            finally:
                browser.close()

    def test_nm_order_proposal_shows_booking_to_card_pairs_as_unverified(self):
        event_ids = ["synthetic-event-a", "synthetic-event-b"]
        card_ids = ["synthetic-card-a", "synthetic-card-b"]
        events = [{"ota_event_id": event_ids[index], "provider": "Synthetic OTA",
                   "booking_ref": f"SYNTHETIC-BOOKING-{index}", "event_type": "charge",
                   "amount": 30000, "amount_krw": 30000, "currency": "KRW",
                   "status": "MATCHED_AUTO", "transaction_id": card_ids[index],
                   "allocation_basis": "user_approved_stable_order",
                   "group_count": {"ota": 2, "cards": 2}, "matched_count": 2,
                   "ota_group_ids": event_ids, "card_group_ids": card_ids}
                  for index in range(2)]
        cards = [{"transaction_id": identity, "issuer": "Synthetic Bank", "amount_krw": 30000,
                  "selection_disabled": True, "selection_disabled_reason": "group mapping review"}
                 for identity in card_ids]
        snapshot = ota_payment_review.public_snapshot({
            "events": events,
            "cards_by_event": {identity: cards for identity in event_ids}, "proposals": []})
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            try:
                page = browser.new_page(viewport={"width": 390, "height": 844})
                page.route("**/api/imports/ota", lambda route: route.fulfill(
                    status=200, content_type="application/json",
                    body=json.dumps(snapshot, ensure_ascii=False)))
                page.set_content("<base href='http://localhost/'>" +
                                 ota_payment_review.render_import_section("token-synth"))
                pair = page.locator(".ota-group-proposal").first
                pair.locator("summary").click()
                text = pair.inner_text()
                self.assertIn("SYNTHETIC-BOOKING-0", text)
                self.assertIn("synthetic-card-a", text)
                self.assertIn("개별 결제 근거가 아닌 정렬 순서 제안", text)
            finally:
                browser.close()

    def test_partial_nm_group_shows_each_card_evidence_and_keeps_individual_links_blocked(self):
        cards = [{"transaction_id": f"synthetic-card-{index}", "issuer": "Synthetic Bank",
                  "merchant": f"Synthetic merchant {index}", "amount_krw": 30000,
                  "approval_date": "2026-09-23", "transaction_direction": "purchase",
                  "selection_disabled": True,
                  "selection_disabled_reason": "partial group; individual assignment blocked"}
                 for index in range(1, 4)]
        snapshot = ota_payment_review.public_snapshot({
            "events": [{"ota_event_id": "synthetic-event-a", "provider": "Synthetic OTA",
                        "booking_ref": "SYNTHETIC-BOOKING-A", "event_type": "charge",
                        "amount": 30000, "amount_krw": 30000, "currency": "KRW",
                        "status": "HOLD_PARTIAL_GROUP", "reason": "partial_nm_group",
                        "group_count": {"ota": 2, "cards": 3}, "matched_count": 2,
                        "allocation_basis": "user_confirmed_group_required",
                        "individual_payment_evidence": False,
                        "ota_group_ids": ["synthetic-event-a", "synthetic-event-b"],
                        "card_group_ids": [card["transaction_id"] for card in cards]}],
            "cards_by_event": {"synthetic-event-a": cards}, "proposals": []})

        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            try:
                page = browser.new_page(viewport={"width": 390, "height": 844})
                page.route("**/api/imports/ota", lambda route: route.fulfill(
                    status=200, content_type="application/json",
                    body=json.dumps(snapshot, ensure_ascii=False)))
                page.set_content("<base href='http://localhost/'>" +
                                 ota_payment_review.render_import_section("token-synth"))
                page.get_by_text("SYNTHETIC-BOOKING-A", exact=False).first.wait_for()
                event = page.locator('[data-event="synthetic-event-a"]')
                self.assertEqual(event.locator(".ota-card-row").count(), 3)
                self.assertIn("2건 ↔ 3건", event.inner_text())
                self.assertIn("부분 묶음", event.inner_text())
                ids = event.locator(".ota-ids")
                ids.locator("summary").click()
                self.assertIn("synthetic-card-3", ids.inner_text())
                self.assertTrue(event.locator("input[type=radio]").nth(0).is_disabled())
                self.assertEqual(event.locator("button[data-preview]").count(), 1)
                self.assertTrue(event.locator("button[data-preview]").is_disabled())
            finally:
                browser.close()

    def test_no_match_hold_shows_plain_reason_sorts_by_amount_and_can_stay_on_hold(self):
        def snapshot(amounts):
            rows = [{"transaction_id": f"card-{amount}", "issuer": "Synthetic Bank", "merchant": f"Merchant {amount}",
                     "amount_krw": amount, "approval_date": "2026-09-23", "posting_date": "2026-09-24",
                     "card_tail": "2042", "card_kind": "credit", "transaction_direction": "purchase",
                     "currency": "KRW", "refund_status": "no_refund"} for amount in amounts]
            return ota_payment_review.public_snapshot({
                "events": [{"ota_event_id": "evt-nomatch", "provider": "trip", "booking_ref": "BOOK-NOMATCH",
                            "event_type": "charge", "paid_on": "2026-09-23", "amount": 90121,
                            "currency": "KRW", "amount_krw": 90121, "status": "HOLD_NO_CARD",
                            "reason": "no_exact_amount_date_direction_card", "item": "숙박비"}],
                "cards_by_event": {"evt-nomatch": rows}, "proposals": []})

        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            try:
                page = browser.new_page(viewport={"width": 1440, "height": 900})
                page.set_default_timeout(5000)
                current = {"body": snapshot([873, 2388, 5000])}
                page.route("**/api/imports/ota", lambda route: route.fulfill(
                    status=200, content_type="application/json",
                    body=json.dumps(current["body"], ensure_ascii=False)))
                page.set_content("<base href='http://localhost/'>" +
                                 ota_payment_review.render_import_section("token-synth"))
                page.get_by_text("BOOK-NOMATCH", exact=False).first.wait_for()
                body = page.locator("#ota-events").inner_text()
                self.assertIn("맞는 카드 거래 없음", body)
                self.assertIn("결제 금액과 같은 카드 거래가 없습니다", body)
                self.assertIn("결제 금액·날짜·방향이 모두 맞는 카드 거래가 없습니다", body)
                self.assertNotIn("HOLD_NO_CARD", body)
                self.assertNotIn("no_exact_amount_date_direction_card", body)
                rows = page.locator(".ota-card-row")
                self.assertIn("5,000원", rows.nth(0).inner_text())
                self.assertEqual(page.locator("input[type=radio]:checked").count(), 0)
                rows.nth(0).get_by_role("radio").check()
                page.get_by_role("button", name="차이 미리 보기").first.wait_for()
                self.assertTrue(page.get_by_role("button", name="차이 미리 보기").first.is_enabled())
                page.get_by_role("button", name="연결할 거래 없음 · 보류 유지").click()
                self.assertEqual(page.locator("input[type=radio]:checked").count(), 0)
                self.assertTrue(page.get_by_role("button", name="차이 미리 보기").first.is_disabled())

                current["body"] = snapshot([5000, 90121])
                page.set_content("<base href='http://localhost/'>" +
                                 ota_payment_review.render_import_section("token-synth"))
                page.get_by_text("BOOK-NOMATCH", exact=False).first.wait_for()
                self.assertIn("금액 일치", page.locator(".ota-card-row").nth(0).inner_text())
                self.assertIn("결제 금액과 같은 카드 거래가 1건 있습니다", page.locator("#ota-events").inner_text())
            finally:
                browser.close()

    def test_flagged_rows_are_hidden_while_normal_row_remains_selectable_on_mobile_and_desktop(self):
        rows = []
        for identity, flag in (("duplicate", "duplicate_of"),
                               ("parse-error", "parse_error"),
                               ("conflict", "conflict_reason"),
                               ("normal", "")):
            row = {"transaction_id": f"card-{identity}", "issuer": "Synthetic Bank",
                   "approval_date": "2026-09-04", "amount_krw": 12500,
                   "merchant": "Synthetic merchant", "transaction_direction": "purchase"}
            if flag:
                row[flag] = "synthetic private diagnostic"
            else:
                row["direction"] = "refund"
            rows.append(row)
        rows.append({"transaction_id": "card-linked-group", "issuer": "Synthetic Bank",
                     "approval_date": "2026-09-04", "amount_krw": 12500,
                     "merchant": "Linked synthetic merchant", "transaction_direction": "purchase",
                     "already_linked_event_id": "evt-other", "already_linked_label": "OTHER-BOOKING",
                     "already_linked_reason": "confirmed_group_reservation", "selection_disabled": True})
        snapshot = ota_payment_review.public_snapshot({
            "events": [{"ota_event_id": "evt-browser", "provider": "Synthetic Stay",
                        "booking_ref": "BOOK-BROWSER", "event_type": "charge",
                        "paid_on": "2026-09-04", "amount": 12500,
                        "currency": "KRW", "amount_krw": 12500,
                        "status": "HOLD_AMBIGUOUS"}],
            "cards_by_event": {"evt-browser": rows}, "proposals": []})

        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            try:
                for width, height in ((390, 844), (1440, 900)):
                    with self.subTest(width=width):
                        page = browser.new_page(viewport={"width": width, "height": height})
                        page.set_default_timeout(5000)
                        page.route("**/api/imports/ota", lambda route: route.fulfill(
                            status=200, content_type="application/json",
                            body=json.dumps(snapshot, ensure_ascii=False)))
                        page.set_content("<base href='http://localhost/'>" +
                                         ota_payment_review.render_import_section("token-synth"))
                        page.get_by_text("BOOK-BROWSER", exact=True).wait_for()
                        visible_rows = page.locator(".ota-event > .ota-cards > .ota-card-row")
                        self.assertEqual(visible_rows.count(), 1)
                        body = page.locator("#ota-events").inner_text()
                        self.assertNotIn("card-duplicate", body)
                        self.assertNotIn("card-parse-error", body)
                        self.assertNotIn("card-conflict", body)
                        self.assertNotIn("선택할 수 없습니다", body)
                        self.assertIn("결제일과 승인 규칙 범위의 카드 거래 1건", body)
                        self.assertIn("결제 금액과 같은 카드 거래가 1건 있습니다", body)
                        self.assertFalse(visible_rows.nth(0).get_by_role("radio").is_disabled())
                        self.assertIn("거래 방향: 구매", visible_rows.nth(0).inner_text())
                        self.assertNotIn("거래 방향: refund", visible_rows.nth(0).inner_text())
                        visible_rows.nth(0).get_by_role("radio").check()
                        self.assertTrue(visible_rows.nth(0).get_by_role("radio").is_checked())
                        linked = page.locator(".ota-linked-cards")
                        self.assertEqual(linked.count(), 1)
                        self.assertIn("다른 예약에 연결된 거래 1건", linked.locator("summary").inner_text())
                        linked.locator("summary").click()
                        self.assertEqual(linked.locator(".ota-card-row").count(), 1)
                        self.assertIn("Linked synthetic merchant", linked.locator(".ota-card-row").inner_text())
                        self.assertEqual(page.evaluate("document.documentElement.scrollWidth"), width)
                        page.close()
            finally:
                browser.close()

    def test_mobile_and_desktop_can_select_preview_confirm_and_answer_pending_proposal(self):
        backend = FakeBackend()

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_args):
                pass

            def _send_json(self, payload, code=200):
                self.response = (code, "application/json; charset=utf-8", payload)

            def current_user_id(self):
                return "synthetic-owner"

            def _send(self, body, status=200, content_type="text/html; charset=utf-8"):
                if isinstance(body, (dict, list)):
                    body = json.dumps(body, ensure_ascii=False)
                data = body.encode("utf-8")
                self.send_response(status)
                self.send_header("Content-Type", content_type)
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def do_GET(self):
                parsed = urlsplit(self.path)
                if parsed.path == "/import":
                    self._send(ota_payment_review.render_import_section("token-synth"))
                    return
                if ota_payment_review.dispatch(self, parsed, csrf="token-synth", backend=backend):
                    self._send(self.response[2], self.response[0], self.response[1])
                    return
                self._send("not found", 404)

            def do_POST(self):
                parsed = urlsplit(self.path)
                raw = self.rfile.read(int(self.headers.get("Content-Length", "0")))
                if ota_payment_review.dispatch(self, parsed, raw=raw, csrf="token-synth", backend=backend):
                    self._send(self.response[2], self.response[0], self.response[1])
                    return
                self._send("not found", 404)

        with patch.dict("os.environ", {
            "WEBLEDGER_OTA_REVIEW_MODE": "isolated",
            "WEBLEDGER_OTA_REVIEW_DB": "C:/synthetic/review.sqlite",
        }):
            server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                with sync_playwright() as playwright:
                    browser = playwright.chromium.launch(headless=True)
                    for width, height in ((390, 844), (1440, 900)):
                        with self.subTest(width=width):
                            page = browser.new_page(viewport={"width": width, "height": height})
                            page.set_default_timeout(5000)
                            page_errors = []
                            page.on("pageerror", lambda error: page_errors.append(str(error)))
                            page.goto(f"http://127.0.0.1:{server.server_port}/import")
                            try:
                                page.get_by_text("BOOK-SYNTH-001", exact=True).wait_for()
                            except Exception as error:
                                self.fail(f"OTA snapshot did not render: {error}; page errors={page_errors}; body={page.locator('body').inner_text()}")
                            rows = page.locator(".ota-card-row")
                            self.assertEqual(rows.count(), 12)
                            row_text = rows.filter(has_text="AUTH-02").first.inner_text()
                            self.assertIn("Synthetic Bank", row_text)
                            self.assertIn("승인일: 2026-09-04", row_text)
                            self.assertIn("매입일: 2026-09-05", row_text)
                            self.assertIn("AUTH-02", row_text)
                            self.assertIn("카드 끝 네 자리: 2042", row_text)
                            self.assertIn("외화 금액: 12.50 USD", row_text)
                            self.assertIn("거래 방향: 구매", row_text)
                            self.assertIn("환불 상태: 환불 없음", row_text)
                            self.assertGreaterEqual(page.locator(".ota-card-row input:disabled").count(), 1)
                            page.locator(".ota-linked-cards summary").click()
                            linked_text = page.locator(".ota-linked-cards .ota-card-row").first.inner_text()
                            self.assertNotIn("evt-synth-other", linked_text)
                            self.assertIn("다른 예약에 연결됨", linked_text)
                            self.assertEqual(page.evaluate("document.documentElement.scrollWidth"), width)
                            row = rows.nth(2)
                            row.get_by_role("radio").check()
                            # Wait for the preview answer itself, not a timer: a refused preview shows no difference
                            # and must fail with the server's answer and the page's status, not as a bare timeout.
                            with page.expect_response(lambda r: "/api/imports/ota/preview" in r.url) as answer:
                                page.locator(".ota-event").get_by_role("button", name="차이 미리 보기").click()
                            if answer.value.status != 200:
                                self.fail(f"preview answered {answer.value.status}: {answer.value.text()}; "
                                          f"status={page.locator('#status').inner_text()!r}")
                            if not page.get_by_text("차이 25원", exact=True).count():
                                page.get_by_text("차이 25원", exact=True).wait_for()
                            self.assertIn("12,500원", page.locator("#ota-difference").inner_text())
                            page.get_by_role("button", name="이 거래로 결제 연결 확정").click()
                            page.get_by_text("사용자 확인 연결", exact=True).wait_for()
                            proposal = page.locator("#ota-proposals [data-proposal]")
                            self.assertEqual(proposal.count(), 1)
                            self.assertIn("pending", proposal.get_attribute("data-status"))
                            image_name = "ota-first-ui-mobile.png" if width == 390 else "ota-first-ui-desktop.png"
                            screenshot_path = Path(__file__).resolve().parents[2] / "docs" / image_name
                            page.screenshot(path=str(screenshot_path), full_page=True)
                            proposal.get_by_label("이번 건만").check()
                            proposal.get_by_role("button", name="제안에 답하기").click()
                            page.get_by_text("규칙 저장 없이 이번 건만 처리했습니다.", exact=True).wait_for()
                            self.assertEqual(page.evaluate("document.documentElement.scrollWidth"), width)
                            page.close()
                    browser.close()
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=3)

    def test_real_core_adapter_store_and_board_readonly_through_confirm_once_and_approve(self):
        from app import ota_review

        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as directory:
            root = Path(directory)
            mail_dir = root / "synthetic-mail"
            mail_dir.mkdir()
            sent = datetime(2026, 9, 4, 12, 0, tzinfo=timezone(timedelta(hours=9)))
            messages = []
            for identity, booking in (("message-a", "BOOKSYNTHA001"), ("message-b", "BOOKSYNTHB001")):
                messages.append({
                    "id": identity,
                    "internal_date": str(int(sent.timestamp() * 1000)),
                    "payload": {
                        "headers": [
                            {"name": "From", "value": "noreply@trip.com"},
                            {"name": "Subject", "value": "[예약 확정 안내] 합성 숙소 예약이 확정되었습니다"},
                            {"name": "Date", "value": format_datetime(sent)},
                            {"name": "Authentication-Results", "value": "mx.google.com; dkim=pass header.i=@trip.com"},
                        ],
                        "mime_type": "text/plain",
                        "body": {"content": (
                            f"예약번호: {booking}\n체크인: 2026년 10월 1일\n"
                            "체크아웃: 2026년 10월 2일\n주소: 합성 주소\n"
                            f"총 금액\n온라인 사전 결제\n{12500 if booking == 'BOOKSYNTHA001' else 13500:,}원\n카드 끝자리 {2042 if booking == 'BOOKSYNTHA001' else 9999}")},
                        "parts": None,
                    },
                })
            (mail_dir / "gmail-synthetic.json").write_text(
                json.dumps({"responses": messages}, ensure_ascii=False), encoding="utf-8")

            board_path = root / "board.sqlite"
            board_conn = sqlite3.connect(board_path, check_same_thread=False)
            board_conn.row_factory = sqlite3.Row
            board_conn.execute("""CREATE TABLE transactions (
                transaction_id TEXT PRIMARY KEY, source_hash TEXT, merchant TEXT,
                merchant_normalized TEXT, card_kind TEXT, card_tail TEXT,
                transaction_direction TEXT, approval_date TEXT, posting_date TEXT,
                amount_krw INTEGER, foreign_currency TEXT, foreign_amount TEXT,
                duplicate_of TEXT, parse_error TEXT, conflict_reason TEXT,
                issuer TEXT, authorization_id TEXT, cancellation_status TEXT,
                refund_status TEXT)""")
            rows = [(f"card-{index}", f"hash-{index}", "TRIP.COM", "trip.com", "credit", "2042" if index < 2 else "9999",
                     "purchase", "2026-09-04", "2026-09-05", 12000 if index < 2 else 13000, "", "", "", "", "",
                     "Synthetic Bank", f"AUTH-{index}", "not_cancelled", "no_refund")
                    for index in range(4)]
            board_conn.executemany("INSERT INTO transactions VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", rows)
            board_conn.commit()
            board = type("SyntheticBoard", (), {})()
            board.conn = board_conn
            board.path = board_path
            board._lock = threading.RLock()
            initial_rows = [tuple(row) for row in board_conn.execute(
                "SELECT * FROM transactions ORDER BY transaction_id")]
            initial_changes = board_conn.total_changes

            review_path = root / "review.sqlite"
            source_config = json.dumps({
                "mail_directories": [str(mail_dir)],
                "portal_databases": [],
                "reference_documents": [],
            })

            class Handler(BaseHTTPRequestHandler):
                def log_message(self, *_args):
                    pass

                def current_user_id(self):
                    return "synthetic-owner"

                def _send(self, body, status=200, content_type="text/html; charset=utf-8"):
                    if isinstance(body, (dict, list)):
                        body = json.dumps(body, ensure_ascii=False)
                    data = body.encode("utf-8")
                    self.send_response(status)
                    self.send_header("Content-Type", content_type)
                    self.send_header("Content-Length", str(len(data)))
                    self.end_headers()
                    self.wfile.write(data)

                def _send_json(self, payload, status=200):
                    self._send(payload, status, "application/json; charset=utf-8")

                def do_GET(self):
                    parsed = urlsplit(self.path)
                    if parsed.path == "/import":
                        self._send(ota_payment_review.render_import_section("token-synth"))
                    elif not card_flow.dispatch(self, parsed, csrf="token-synth"):
                        self._send("not found", 404)

                def do_POST(self):
                    parsed = urlsplit(self.path)
                    raw = self.rfile.read(int(self.headers.get("Content-Length", "0")))
                    if not card_flow.dispatch(self, parsed, raw=raw, csrf="token-synth"):
                        self._send("not found", 404)

            environment = {
                "WEBLEDGER_CARD_FLOW": "1",
                "WEBLEDGER_OTA_REVIEW_MODE": "isolated",
                "WEBLEDGER_OTA_REVIEW_DB": str(review_path),
                "WEBLEDGER_OTA_SOURCES_JSON": source_config,
            }
            with mock.patch.dict(os.environ, environment, clear=False), \
                    mock.patch("webapp.ledger_board._active_store", return_value=board):
                server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
                thread = threading.Thread(target=server.serve_forever, daemon=True)
                thread.start()
                try:
                    with sync_playwright() as playwright:
                        browser = playwright.chromium.launch(headless=True)
                        page = browser.new_page(viewport={"width": 1440, "height": 900})
                        page.set_default_timeout(8000)
                        page.goto(f"http://127.0.0.1:{server.server_port}/import")
                        try:
                            page.get_by_text("BOOKSYNTHA001", exact=True).wait_for(timeout=40000)
                        except Exception as error:
                            self.fail(f"real core snapshot did not render: {error}; status={page.locator('#ota-status').inner_text()}; body={page.locator('body').inner_text()}")
                        self.assertEqual(page.locator(".ota-event").count(), 2)
                        self.assertFalse(review_path.exists())

                        first = page.locator(".ota-event").nth(0)
                        first.locator('input[type="radio"]:not(:disabled)').first.check()
                        first.get_by_role("button", name="차이 미리 보기").click()
                        page.get_by_role("button", name="이 거래로 결제 연결 확정").wait_for()
                        self.assertFalse(review_path.exists(), "POST preview must not initialize the review DB")
                        page.get_by_role("button", name="이 거래로 결제 연결 확정").click()
                        proposal_once = page.locator("#ota-proposals [data-proposal]").first
                        proposal_once.wait_for()
                        proposal_once.locator('input[value="once"]').check()
                        proposal_once.get_by_role("button", name="제안에 답하기").click()
                        page.get_by_text("규칙 저장 없이 이번 건만 처리했습니다.", exact=True).wait_for()

                        remaining = page.locator(".ota-event").first
                        remaining.locator('input[type="radio"]:not(:disabled)').first.check()
                        # The server refuses a preview while the snapshot refreshes after the last answer; retry until it is ready.
                        for _ in range(20):
                            if page.get_by_role("button", name="이 거래로 결제 연결 확정").count():
                                break
                            preview_button = remaining.get_by_role("button", name="차이 미리 보기")
                            if preview_button.is_enabled():
                                preview_button.click()
                            page.wait_for_timeout(1000)
                        page.get_by_role("button", name="이 거래로 결제 연결 확정").wait_for()
                        page.get_by_role("button", name="이 거래로 결제 연결 확정").click()
                        proposal_approve = page.locator("#ota-proposals [data-proposal]").first
                        proposal_approve.wait_for()
                        proposal_approve.locator('input[value="approve"]').check()
                        proposal_approve.get_by_role("button", name="제안에 답하기").click()
                        page.get_by_text("검토한 조건으로 규칙을 저장했습니다.", exact=True).wait_for()
                        review_digest = hashlib.sha256(review_path.read_bytes()).hexdigest()
                        (mail_dir / "gmail-synthetic.json").unlink()
                        page.reload()
                        page.get_by_text("원본 근거: 근거 사라짐", exact=True).first.wait_for(timeout=40000)
                        self.assertEqual(page.locator(".ota-event").count(), 2)
                        self.assertEqual(page.locator(".ota-card-row input[type=radio]:disabled").count(), 8)
                        self.assertEqual(hashlib.sha256(review_path.read_bytes()).hexdigest(), review_digest)
                        browser.close()
                finally:
                    server.shutdown()
                    server.server_close()
                    thread.join(timeout=3)
                    ota_payment_review.shutdown_snapshot_service(board)

            self.assertEqual(board_conn.total_changes, initial_changes)
            self.assertEqual([tuple(row) for row in board_conn.execute(
                "SELECT * FROM transactions ORDER BY transaction_id")], initial_rows)
            store = ota_review.OtaReviewStore(review_path)
            self.assertEqual(len(store.links()), 2)
            self.assertEqual(len(store.active_rules()), 1)
            answered = [proposal["status"] for proposal in store.proposals()]
            self.assertIn("answered_once", answered)
            self.assertIn("approved", answered)
            store.close()
            board_conn.close()
            board_conn.close()


if __name__ == "__main__":
    unittest.main()
