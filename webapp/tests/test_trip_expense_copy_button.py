"""Tests for trip tab bottom expense copy button and TSV export."""
import json
import hashlib
import os
import tempfile
import threading
import unittest
from unittest.mock import patch
import urllib.error
import urllib.request
from pathlib import Path
from webapp import access_control
from webapp import ledger_board as board, ledger_design as design
from webapp.ledger_store import LedgerStore
from webapp.tests.test_reserve_link import OWNER
from webapp.tests.test_reserve_link_browser import LinkBrowserFixture


def install_canonical_source(case, trip_id):
    """Real canonical read boundary with synthetic files, never a source bypass."""
    from app import google_authority as ga
    from app.db import Store
    from webapp.tests.test_sheet_expense_projection import _snapshot, _rows_doc, GOOGLE_KEY
    Store(board._active_store().conn, schema_policy='create')
    directory = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
    case.addCleanup(directory.cleanup)
    folder = Path(directory.name)
    snapshot_path, rows_path = folder/'snapshot.json', folder/'rows.json'
    env = patch.dict(os.environ, {'WEBLEDGER_GOOGLE_LEDGER_SNAPSHOT':str(snapshot_path),
                                 'WEBLEDGER_GOOGLE_LEDGER_ROWS':str(rows_path)})
    env.start();case.addCleanup(env.stop)
    (folder/'google-tab-mapping.json').write_text(json.dumps({GOOGLE_KEY:trip_id}),encoding='utf-8')
    def publish(expenses):
        snapshot, document = _snapshot(), _rows_doc()
        digest = hashlib.sha256(json.dumps(expenses,sort_keys=True).encode()).hexdigest()
        generation = digest[:32]
        snapshot['rows_generation'] = document['generation'] = generation
        for role in ('main','archive'):
            snapshot['sources'][role]['content_sha256'] = digest
            document['sources'][role]['content_sha256'] = digest
        document['sources']['main']['trips'][GOOGLE_KEY] = {'income':[], 'expense':expenses}
        total = sum(row['amount'] for row in expenses)
        trip=snapshot['trips'][0]
        trip.update(income_total=0,expense_total=total,net=-total)
        for name,amount in (('income',0),('expense',total)):
            trip['copies']['main'][name].update(sheet_total=amount,row_sum=amount,total=amount)
        ga._rows_file(rows_path,generation).write_text(json.dumps(document),encoding='utf-8')
        snapshot_path.write_text(json.dumps(snapshot),encoding='utf-8')
    publish([])
    return publish


class TripExpenseCopyButtonTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self._prev_db = os.environ.get("WEBLEDGER_DB")
        self.path = Path(self.tmp) / "test_copy.sqlite"
        os.environ["WEBLEDGER_DB"] = str(self.path)
        self.store = LedgerStore(self.path, seed_demo=True)
        board.bind_store(self.store)
        self.addCleanup(self._restore)
        install_canonical_source(self,'trip-demo-a')

    def _restore(self):
        board.bind_store(None)
        self.store.close()
        if self._prev_db is None:
            os.environ.pop("WEBLEDGER_DB", None)
        else:
            os.environ["WEBLEDGER_DB"] = self._prev_db

    def test_is_trip_tab(self):
        self.assertTrue(design._is_trip_tab("trip-demo-a"))
        self.assertFalse(design._is_trip_tab("2026-05-18_tokyo"))
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
        with self.assertRaisesRegex(ValueError, "INVALID_TRIP_TAB"):
            design.tsv_for_trip_expenses("non-existent-trip-tab")
        with patch.object(design, "_selected_rows", return_value=([], [], [], [])):
            res = design.tsv_for_trip_expenses("trip-demo-a")
        self.assertEqual(res["row_count"], 0)
        self.assertEqual(res["total_krw"], 0)
        self.assertEqual(res["tsv"], "")

    def test_export_preserves_values_and_holds_unsafe_rows(self):
        base = dict(board.EXPENSES[0])
        rows = [dict(base, source_event_id="valid", source_merchant="=FORMULA\tshop",
                     evidence_type="영수증", amount_krw=-123, display_amount_krw=-123,
                     reservation_no="", service_period="2026-04-09~2026-04-10")]
        for identity, overrides in [
            ("unknown", {"evidence_type": "현금"}),
            ("date", {"occurred_on": "2026-02-30"}),
            ("amount", {"amount_krw": 1.5}),
            ("blocked", {"blocked": "manual hold"}),
            ("duplicate", {}), ("duplicate", {}),
        ]:
            rows.append(dict(base, source_event_id=identity, **overrides))
        result = design._trip_expense_tsv("trip-demo-a", rows)
        self.assertEqual(result["row_count"], 1)
        self.assertEqual(result["total_krw"], -123)
        self.assertEqual(len(result["held"]), 6)
        self.assertEqual(result["tsv"].strip().split("\t"), [
            "2026-04-09", "'=FORMULA shop", "숙박비", "2026-04-09~2026-04-10", "", "영수증", "-123"])


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
        self.access.create_account(user_id="copy-viewer", role=access_control.ROLE_VIEWER)
        self.port = self.server.server_address[1]
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        access_control.bind_synthetic_sessions(True)
        board.bind_access(self.access)
        install_canonical_source(self,'trip-demo-a')

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
            body = exc.read().decode("utf-8")
            return exc.code, json.loads(body) if body.startswith("{") else {"message": body}

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

    def test_export_filters_and_access_protection(self):
        status, data = self.get_json("/api/tabs/trip-demo-a/tsv?q=does-not-match")
        self.assertEqual((status, data["row_count"]), (200, 0))
        status, data = self.get_json("/api/tabs/trip-demo-a/tsv?kind=in")
        self.assertEqual((status, data["row_count"]), (200, 0))
        for path in ("/api/tabs/trip-demo-a/tsv", "/api/board/tsv?tab=trip-demo-a"):
            status, data = self.get_json(path, user="copy-viewer")
            self.assertIn(status, (403, 404))
            self.assertNotIn("tsv", data)
            status, data = self.get_json(path, user="")
            self.assertEqual(status, 401)
            self.assertNotIn("tsv", data)

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
        publish = install_canonical_source(self,tab_id)

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
                "description": "도쿄 라멘야",
                "evidence_type": "영수증",
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
        clipboard = page.evaluate("navigator.clipboard.readText()")
        self.assertEqual(clipboard.strip().split("\t"), [
            "2026-06-02", "도쿄 라멘야", "식비", "", "", "영수증", "45000"])

        # Simulate the user's paste in a synthetic canonical file, then read it
        # afresh. A clipboard success alone must not suppress the next export.
        request = urllib.request.Request(f'http://127.0.0.1:{self.port}/api/tabs/{tab_id}/tsv',
            headers={access_control.SyntheticSessionAdapter.HEADER:OWNER})
        with urllib.request.urlopen(request) as response:
            self.assertEqual(json.load(response)['row_count'],1)
        publish([{'row':18,'cells':{'B':'2026-06-02','C':'도쿄 라멘야','D':'식비',
                                  'E':'','F':'','G':'영수증'},'amount':45000}])
        with urllib.request.urlopen(request) as response:
            reflected=json.load(response)
        self.assertTrue(reflected['source_available'])
        self.assertEqual(reflected['row_count'],0)
        self.assertEqual(len(reflected['matched']),1)

        # 2. Visit unclassified tab: copy button must NOT be present
        page.goto(f"http://127.0.0.1:{self.port}/board?tab=unclassified")
        self.assertEqual(page.locator("#copy-trip-expenses").count(), 0)


if __name__ == "__main__":
    unittest.main()
