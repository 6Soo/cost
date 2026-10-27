"""Tests for trip tab bottom expense copy button and TSV export."""
import json
import os
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path
from webapp import access_control
from webapp import ledger_board as board, ledger_design as design
from webapp.ledger_store import LedgerStore
from webapp.tests.test_reserve_link import OWNER
from webapp.tests.test_reserve_link_browser import LinkBrowserFixture


class TripExpenseCopyButtonTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self._prev_db = os.environ.get("WEBLEDGER_DB")
        self.path = Path(self.tmp) / "test_copy.sqlite"
        os.environ["WEBLEDGER_DB"] = str(self.path)
        self.store = LedgerStore(self.path, seed_demo=True)
        board.bind_store(self.store)
        self.addCleanup(self._restore)

    def _restore(self):
        board.bind_store(None)
        self.store.close()
        if self._prev_db is None:
            os.environ.pop("WEBLEDGER_DB", None)
        else:
            os.environ["WEBLEDGER_DB"] = self._prev_db

    def test_is_trip_tab(self):
        self.assertTrue(design._is_trip_tab("trip-demo-a"))
        self.assertTrue(design._is_trip_tab("2026-05-18_tokyo"))
        self.assertFalse(design._is_trip_tab("unclassified"))
        self.assertFalse(design._is_trip_tab("refunds"))
        self.assertFalse(design._is_trip_tab("quarter:2026:1"))
        self.assertFalse(design._is_trip_tab("quarter:2026:2"))
        self.assertFalse(design._is_trip_tab(""))
        self.assertFalse(design._is_trip_tab(None))

    def test_tsv_for_trip_expenses_standard_7_columns(self):
        res = design.tsv_for_trip_expenses("trip-demo-a")
        self.assertEqual(res["tab_id"], "trip-demo-a")
        self.assertEqual(res["row_count"], 3)
        self.assertEqual(res["total_krw"], 180000)

        lines = res["tsv"].strip().split("\n")
        self.assertEqual(len(lines), 3)
        for line in lines:
            cols = line.split("\t")
            self.assertEqual(len(cols), 7, f"Line must have exactly 7 columns: {cols}")
            # Col 0: date
            self.assertRegex(cols[0], r"^\d{4}-\d{2}-\d{2}$")
            # Col 1: payee
            self.assertTrue(bool(cols[1]))
            # Col 2: category
            self.assertEqual(cols[2], "숙박비")
            # Col 5: evidence type
            self.assertIn(cols[5], ("카드", "영수증"))
            # Col 6: amount int
            self.assertNotEqual(cols[6], "")

    def test_copy_button_only_at_bottom_of_trip_tabs(self):
        # 1. Real trip tab: copy button is present at bottom of rows_region and rows_part
        html_trip = design.rows_region("trip-demo-a")
        self.assertIn("trip-copy-wrap", html_trip)
        self.assertIn("copy-trip-expenses", html_trip)
        self.assertIn("지출내용 복사", html_trip)
        self.assertIn("data-tab='trip-demo-a'", html_trip)

        part_trip = design.rows_part("trip-demo-a")
        self.assertIn("trip-copy-wrap", part_trip)
        self.assertIn("copy-trip-expenses", part_trip)

        # 2. unclassified tab: copy button MUST NOT be present
        html_unc = design.rows_region("unclassified")
        self.assertNotIn("trip-copy-wrap", html_unc)
        self.assertNotIn("copy-trip-expenses", html_unc)
        self.assertNotIn("지출내용 복사", html_unc)

        part_unc = design.rows_part("unclassified")
        self.assertNotIn("trip-copy-wrap", part_unc)
        self.assertNotIn("copy-trip-expenses", part_unc)

        # 3. refunds tab: copy button MUST NOT be present
        html_ref = design.rows_region("refunds")
        self.assertNotIn("trip-copy-wrap", html_ref)
        self.assertNotIn("copy-trip-expenses", html_ref)

        part_ref = design.rows_part("refunds")
        self.assertNotIn("trip-copy-wrap", part_ref)
        self.assertNotIn("copy-trip-expenses", part_ref)

    def test_tsv_for_empty_trip(self):
        res = design.tsv_for_trip_expenses("non-existent-trip-tab")
        self.assertEqual(res["row_count"], 0)
        self.assertEqual(res["total_krw"], 0)
        self.assertEqual(res["tsv"], "")


class TripExpenseCopyApiHttpTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self._prev_db = os.environ.get("WEBLEDGER_DB")
        self.path = Path(self.tmp) / "http_copy.sqlite"
        os.environ["WEBLEDGER_DB"] = str(self.path)
        self.server = board.serve(port=0, with_worker=False, seed_demo=True)
        self.store = board._active_store()
        self.access = access_control.attach_to_ledger_store(self.store)
        self.access.ensure_owner(OWNER)
        self.port = self.server.server_address[1]
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        access_control.bind_synthetic_sessions(True)
        board.bind_access(self.access)

    def tearDown(self):
        board.bind_access(None)
        access_control.bind_sessions(access_control.UnboundSessionAdapter())
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)
        board.bind_store(None)
        self.store.close()
        if self._prev_db is None:
            os.environ.pop("WEBLEDGER_DB", None)
        else:
            os.environ["WEBLEDGER_DB"] = self._prev_db

    def get_json(self, path, user=OWNER):
        head = {access_control.SyntheticSessionAdapter.HEADER: user}
        req = urllib.request.Request(f"http://127.0.0.1:{self.port}{path}", headers=head)
        try:
            with urllib.request.urlopen(req) as resp:
                return resp.status, json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            return exc.code, json.loads(exc.read().decode("utf-8"))

    def test_get_tsv_endpoint_success(self):
        status, data = self.get_json("/api/tabs/trip-demo-a/tsv")
        self.assertEqual(status, 200)
        self.assertEqual(data["tab_id"], "trip-demo-a")
        self.assertEqual(data["row_count"], 3)
        self.assertEqual(data["total_krw"], 180000)
        self.assertIn("숙박비", data["tsv"])

    def test_get_board_tsv_query_param(self):
        status, data = self.get_json("/api/board/tsv?tab=trip-demo-a")
        self.assertEqual(status, 200)
        self.assertEqual(data["tab_id"], "trip-demo-a")
        self.assertEqual(data["row_count"], 3)
        self.assertIn("숙박비", data["tsv"])

    def test_refuses_non_trip_tabs(self):
        status, data = self.get_json("/api/tabs/unclassified/tsv")
        self.assertEqual(status, 400)
        self.assertEqual(data["code"], "INVALID_TRIP_TAB")

        status, data = self.get_json("/api/tabs/refunds/tsv")
        self.assertEqual(status, 400)
        self.assertEqual(data["code"], "INVALID_TRIP_TAB")


class TripExpenseCopyBrowserTests(LinkBrowserFixture):
    def test_browser_copy_trip_expenses_interaction(self):
        # Create a synthetic trip with an expense row
        trip = self.server.card_store.create_trip(
            starts_on="2026-06-01", ends_on="2026-06-05",
            destination="Tokyo", display_key="2026-06 Tokyo",
            client_request_id="trip-copy-e2e")
        tab_id = trip["tab_id"]

        self.server.card_store.create_manual_expense(
            fields={
                "display_tab_id": tab_id,
                "occurred_on": "2026-06-02",
                "amount_krw": 45000,
                "item": "식비",
                "pay_method": "현금",
                "source_kind": "입력",
                "source_event_id": "EV-COPY-1",
                "source_merchant": "도쿄 라멘야",
            },
            client_request_id="exp-copy-e2e")

        context = self.browser.new_context(viewport={"width": 1440, "height": 900})
        self.addCleanup(context.close)
        context.grant_permissions(["clipboard-read", "clipboard-write"])
        context.set_extra_http_headers({access_control.SyntheticSessionAdapter.HEADER: OWNER})
        page = context.new_page()

        # 1. Visit trip tab: copy button must be visible at bottom
        page.goto(f"http://127.0.0.1:{self.port}/board?tab={tab_id}")
        btn = page.locator("#copy-trip-expenses")
        self.assertTrue(btn.is_visible())
        self.assertIn("지출내용 복사", btn.inner_text())

        # Click the copy button
        btn.click()

        # Verify status message appears
        status = page.locator("#copy-status")
        page.wait_for_function("() => document.getElementById('copy-status').textContent.includes('복사되었습니다')")
        self.assertIn("지출내용이 복사되었습니다", status.inner_text())
        self.assertIn("1건", status.inner_text())

        # 2. Visit unclassified tab: copy button must NOT be present
        page.goto(f"http://127.0.0.1:{self.port}/board?tab=unclassified")
        self.assertEqual(page.locator("#copy-trip-expenses").count(), 0)


if __name__ == "__main__":
    unittest.main()
