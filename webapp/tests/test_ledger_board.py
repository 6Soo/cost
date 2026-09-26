"""Phase 1 synthetic board tests.

Verifies the DETAILED_CONTRACT section 9 fixture expectations:
A income 1000000, expense 180000, profit 820000; U1 800000, U2 200000;
unclassified 30000 excluded from A expense. All synthetic.
"""

import unittest

from webapp.ledger_board import (
    board_page,
    customer_total,
    detail_page,
    trip_expense_total,
    trip_income_total,
    trip_profit,
    unclassified_expenses,
    unclassified_total,
)


class SyntheticTotalsTests(unittest.TestCase):
    def test_trip_a_totals(self):
        self.assertEqual(trip_income_total("trip-demo-a"), 1000000)
        self.assertEqual(trip_expense_total("trip-demo-a"), 180000)
        self.assertEqual(trip_profit("trip-demo-a"), 820000)

    def test_customer_totals_not_merged(self):
        self.assertEqual(customer_total("U1", "trip-demo-a"), 800000)
        self.assertEqual(customer_total("U2", "trip-demo-a"), 200000)

    def test_unclassified_excluded_from_trip_a(self):
        rows = unclassified_expenses()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["row_id"], "expense-demo-c3")
        self.assertEqual(unclassified_total(), 30000)

    def test_cancel_row_keeps_sign(self):
        self.assertEqual(trip_expense_total("trip-demo-a"), 100000 - 20000 + 100000)


class BoardPageTests(unittest.TestCase):
    def test_board_shows_synthetic_mark_and_totals(self):
        page = board_page("trip-demo-a")
        self.assertIn("합성 자료", page)
        self.assertIn("1,000,000원", page)
        self.assertIn("180,000원", page)
        self.assertIn("820,000원", page)

    def test_board_has_no_candidate_badge(self):
        page = board_page("trip-demo-a")
        self.assertNotIn("후보", page)
        self.assertNotIn("badge", page)

    def test_income_above_expense(self):
        page = board_page("trip-demo-a")
        self.assertLess(page.index("수입 내용"), page.index("지출 내용"))

    def test_detail_shows_basis(self):
        page = detail_page("expense-demo-c1")
        self.assertIn("합성 자료", page)
        self.assertIn("원천", page)
        self.assertIn("분류 근거", page)

    def test_edit_form_save_disabled(self):
        page = detail_page("expense-demo-c1", edit=True)
        self.assertIn("disabled", page)
        self.assertNotIn("저장됐습니다", page)

    def test_unknown_row(self):
        page = detail_page("no-such-row")
        self.assertIn("행이 없어요", page)

    def test_mobile_layout_present(self):
        page = board_page("trip-demo-a")
        self.assertIn("@media (max-width:760px)", page)
        self.assertIn("scrollx", page)


class BoardApiTests(unittest.TestCase):
    def setUp(self):
        import os
        import tempfile
        from pathlib import Path

        from webapp import ledger_board as board_mod
        from webapp.ledger_store import LedgerStore

        self.tmp = tempfile.mkdtemp()
        self._prev_db = os.environ.get("WEBLEDGER_DB")
        db_path = str(Path(self.tmp) / "server.sqlite")
        os.environ["WEBLEDGER_DB"] = db_path
        self.store = LedgerStore(Path(db_path))
        board_mod.bind_store(self.store)
        self.board_mod = board_mod
        self.server = board_mod.serve(port=0)
        self.port = self.server.server_address[1]
        import threading

        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self):
        import os

        worker = getattr(self.server, "card_worker", None)
        if worker is not None:
            worker.stop(timeout=5)
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)
        self.board_mod.bind_store(None)
        self.store.close()
        if self._prev_db is None:
            os.environ.pop("WEBLEDGER_DB", None)
        else:
            os.environ["WEBLEDGER_DB"] = self._prev_db

    def _post(self, row_id, payload):
        import json
        import urllib.request

        data = json.dumps(payload).encode("utf-8")
        request = urllib.request.Request(
            f"http://127.0.0.1:{self.port}/api/rows/{row_id}/save",
            data=data, headers={"Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(request) as response:
                return response.status, json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            return exc.code, json.loads(exc.read().decode("utf-8"))

    def _post_json_path(self, path, payload):
        import json
        import urllib.request

        data = json.dumps(payload).encode("utf-8")
        request = urllib.request.Request(
            f"http://127.0.0.1:{self.port}{path}",
            data=data,
            headers={"Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(request) as response:
                return response.status, json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            return exc.code, json.loads(exc.read().decode("utf-8"))

    def test_save_moves_row_and_updates_board(self):
        import urllib.request

        status, result = self._post("expense-demo-c1", {
            "csrf": self.board_mod.CSRF_TOKEN,
            "expected_revision": 1,
            "client_request_id": "api-c1-b",
            "change_mode": "exception",
            "display_tab_id": "trip-demo-b",
        })
        self.assertEqual(status, 200)
        self.assertEqual(result["outcome"], "saved")
        with urllib.request.urlopen(f"http://127.0.0.1:{self.port}/board?tab=trip-demo-b") as response:
            page = response.read().decode("utf-8")
        self.assertIn("100,000원", page)

    def test_save_without_csrf_rejected(self):
        status, result = self._post("expense-demo-c1", {
            "expected_revision": 1,
            "client_request_id": "api-c1-nocsrf",
            "change_mode": "exception",
            "display_tab_id": "trip-demo-b",
        })
        self.assertEqual(status, 403)

    def test_save_conflict_and_illegal_field(self):
        status, _ = self._post("expense-demo-c1", {
            "csrf": self.board_mod.CSRF_TOKEN,
            "expected_revision": 1,
            "client_request_id": "api-c1-ok",
            "change_mode": "exception",
            "display_tab_id": "trip-demo-b",
        })
        self.assertEqual(status, 200)
        status, result = self._post("expense-demo-c1", {
            "csrf": self.board_mod.CSRF_TOKEN,
            "expected_revision": 1,
            "client_request_id": "api-c1-stale",
            "change_mode": "exception",
            "display_tab_id": "trip-demo-a",
        })
        self.assertEqual(status, 409)
        self.assertEqual(result["code"], "EDIT_CONFLICT")
        status, result = self._post("expense-demo-c2", {
            "csrf": self.board_mod.CSRF_TOKEN,
            "expected_revision": 1,
            "client_request_id": "api-c2-amount",
            "change_mode": "exception",
            "amount_krw": 5,
        })
        self.assertEqual(status, 422)

    def test_history_shown_after_save(self):
        import urllib.request

        self._post("expense-demo-c1", {
            "csrf": self.board_mod.CSRF_TOKEN,
            "expected_revision": 1,
            "client_request_id": "api-c1-hist",
            "change_mode": "exception",
            "operator_note": "이력 확인",
        })
        with urllib.request.urlopen(
            f"http://127.0.0.1:{self.port}/row?id=expense-demo-c1"
        ) as response:
            page = response.read().decode("utf-8")
        self.assertIn("변경 이력", page)
        self.assertIn("rev 2", page)

    def test_upload_page_and_api(self):
        import json
        import urllib.request

        with urllib.request.urlopen(f"http://127.0.0.1:{self.port}/import") as response:
            self.assertEqual(response.status, 200)
            self.assertIn("카드 가져오기", response.read().decode("utf-8"))
        csv_body = (
            "occurred_on,merchant,amount_krw,currency,card_last4,approval_no,"
            "cancel_flag,suggested_tab,memo\n"
            "2026-04-09,AGODA TEST,100000,KRW,1111,AX1,,trip-demo-a,\n"
            "2026-04-11,UNKNOWN SHOP,30000,KRW,2222,AX2,,,\n"
        ).encode("utf-8")
        request = urllib.request.Request(
            f"http://127.0.0.1:{self.port}/api/imports",
            data=csv_body,
            headers={"Content-Type": "text/csv", "X-Filename": "up.csv",
                     "X-CSRF-Token": self.board_mod.CSRF_TOKEN},
        )
        with urllib.request.urlopen(request) as response:
            accepted = json.loads(response.read().decode("utf-8"))
        self.assertFalse(accepted["reused"])
        progress = self._poll_progress(accepted["batch_id"])
        self.assertEqual(progress["status"], "completed")
        self.assertEqual(progress["result"]["new_events"], 2)
        with urllib.request.urlopen(
            f"http://127.0.0.1:{self.port}/board?tab=trip-demo-a"
        ) as response:
            page = response.read().decode("utf-8")
        self.assertIn("AGODA TEST", page)
        self.assertIn("280,000원", page)

    def _poll_progress(self, batch_id, tries=100):
        import json
        import time
        import urllib.request

        for _ in range(tries):
            with urllib.request.urlopen(
                f"http://127.0.0.1:{self.port}/api/imports/{batch_id}"
            ) as response:
                progress = json.loads(response.read().decode("utf-8"))
            if progress["status"] not in ("reconciling", "parsing", "processing"):
                return progress
            time.sleep(0.05)
        return progress

    def test_upload_accepted_then_progress_completes(self):
        import json
        import urllib.request

        with urllib.request.urlopen(f"http://127.0.0.1:{self.port}/board?tab=trip-demo-a") as response:
            self.assertEqual(response.status, 200)
        body = (
            "occurred_on,merchant,amount_krw,currency,card_last4,approval_no,"
            "cancel_flag,suggested_tab,memo\n"
            "2026-04-09,PROBE SHOP,1000,KRW,9999,P9,,,\n"
        ).encode("utf-8")
        request = urllib.request.Request(
            f"http://127.0.0.1:{self.port}/api/imports",
            data=body,
            headers={"Content-Type": "text/csv", "X-Filename": "probe.csv",
                     "X-CSRF-Token": self.board_mod.CSRF_TOKEN},
        )
        with urllib.request.urlopen(request) as response:
            accepted = json.loads(response.read().decode("utf-8"))
        self.assertIn(accepted["status"], ("reconciling", "parsing", "processing",
                                           "completed", "completed_with_issues"))
        with urllib.request.urlopen(f"http://127.0.0.1:{self.port}/board?tab=unclassified") as response:
            self.assertEqual(response.status, 200)
        progress = self._poll_progress(accepted["batch_id"])
        self.assertEqual(progress["status"], "completed_with_issues"
                         if progress["result"]["parse_errors"] else "completed")

    def test_upload_51_rows_completes_and_reuses(self):
        import json
        import urllib.request

        lines = "".join(
            f"2026-04-{(i % 28) + 1:02d},SHOP{i},1000,KRW,1111,H{i},,,\n"
            for i in range(51)
        )
        body = (
            "occurred_on,merchant,amount_krw,currency,card_last4,approval_no,"
            "cancel_flag,suggested_tab,memo\n" + lines
        ).encode("utf-8")

        def upload():
            request = urllib.request.Request(
                f"http://127.0.0.1:{self.port}/api/imports",
                data=body,
                headers={"Content-Type": "text/csv", "X-Filename": "big.csv",
                         "X-CSRF-Token": self.board_mod.CSRF_TOKEN},
            )
            with urllib.request.urlopen(request) as response:
                return json.loads(response.read().decode("utf-8"))

        first = upload()
        self.assertFalse(first["reused"])
        progress = self._poll_progress(first["batch_id"])
        self.assertEqual(progress["status"], "completed")
        self.assertEqual(progress["result"]["new_events"], 51)
        second = upload()
        self.assertTrue(second["reused"])
        done = self._poll_progress(second["batch_id"])
        self.assertEqual(done["result"]["new_events"], 51)

    def test_export_download_and_request_binding(self):
        import json
        import os
        import urllib.request

        export_dir = os.path.join(self.tmp, "exports")
        prev = os.environ.get("WEBLEDGER_EXPORT_DIR")
        os.environ["WEBLEDGER_EXPORT_DIR"] = export_dir
        try:
            payload = {
                "csrf": self.board_mod.CSRF_TOKEN,
                "client_request_id": "exp-1",
                "tab_ids": ["trip-demo-a", "trip-demo-b"],
            }
            data = json.dumps(payload).encode("utf-8")
            request = urllib.request.Request(
                f"http://127.0.0.1:{self.port}/api/exports/xlsx",
                data=data, headers={"Content-Type": "application/json"},
            )
            with urllib.request.urlopen(request) as response:
                job = json.loads(response.read().decode("utf-8"))
            self.assertEqual(job["status"], "ready")
            self.assertEqual(job["tab_ids"], ["trip-demo-a", "trip-demo-b"])
            with urllib.request.urlopen(
                f"http://127.0.0.1:{self.port}/api/exports/{job['job_id']}/download"
            ) as response:
                self.assertEqual(response.status, 200)
                self.assertIn("spreadsheet", response.headers.get("Content-Type"))
                body = response.read()
            self.assertTrue(body.startswith(b"PK"))
            same = dict(payload, tab_ids=["trip-demo-a"])
            data = json.dumps(same).encode("utf-8")
            request = urllib.request.Request(
                f"http://127.0.0.1:{self.port}/api/exports/xlsx",
                data=data, headers={"Content-Type": "application/json"},
            )
            try:
                urllib.request.urlopen(request)
                self.fail("expected 409")
            except urllib.error.HTTPError as exc:
                self.assertEqual(exc.code, 409)
                error = json.loads(exc.read().decode("utf-8"))
            self.assertEqual(error["code"], "REQUEST_ID_REUSED")
        finally:
            if prev is None:
                os.environ.pop("WEBLEDGER_EXPORT_DIR", None)
            else:
                os.environ["WEBLEDGER_EXPORT_DIR"] = prev

    def test_upload_without_csrf_rejected(self):
        import urllib.request

        request = urllib.request.Request(
            f"http://127.0.0.1:{self.port}/api/imports",
            data=b"occurred_on,merchant,amount_krw\n",
            headers={"Content-Type": "text/csv"},
        )
        try:
            urllib.request.urlopen(request)
            self.fail("expected 403")
        except urllib.error.HTTPError as exc:
            self.assertEqual(exc.code, 403)

    def test_direct_income_http_amount_edit(self):
        status, result = self._post("income-demo-i1", {
            "csrf": self.board_mod.CSRF_TOKEN,
            "expected_revision": 1,
            "client_request_id": "api-i1-edit",
            "change_mode": "exception",
            "amount_krw": 450000,
        })
        self.assertEqual(status, 200)
        self.assertEqual(result["outcome"], "saved")
        self.assertEqual(result["revision"], 2)

    def test_unknown_field_rejected(self):
        status, result = self._post("income-demo-i1", {
            "csrf": self.board_mod.CSRF_TOKEN,
            "expected_revision": 1,
            "client_request_id": "api-i1-hack",
            "change_mode": "exception",
            "hack": 1,
        })
        self.assertEqual(status, 422)
        self.assertEqual(result["code"], "INVALID_VALUE")

    def test_memo_clear(self):
        self._post("income-demo-i1", {
            "csrf": self.board_mod.CSRF_TOKEN,
            "expected_revision": 1,
            "client_request_id": "api-i1-memo-set",
            "change_mode": "exception",
            "operator_note": "ab",
        })
        status, result = self._post("income-demo-i1", {
            "csrf": self.board_mod.CSRF_TOKEN,
            "expected_revision": 2,
            "client_request_id": "api-i1-memo-clear",
            "change_mode": "exception",
            "operator_note": "",
        })
        self.assertEqual(status, 200)
        self.assertEqual(self.store.get_row("income-demo-i1")["operator_note"], "")

    def test_allocation_detail_edit_revert_http_flow(self):
        import urllib.request

        created = self.store.create_direct_income(
            fields={
                "display_tab_id": None, "occurred_on": "2026-04-01",
                "amount_krw": 500000, "income_kind": "deposit",
                "customer_id": None, "customer_name": "P1",
                "nickname": "", "memo": "",
            },
            client_request_id="board-allocation-source",
        )
        self.store.save_allocations(
            source_row_id=created["row_id"], expected_source_revision=1,
            allocations=[
                {"customer_name": "U1", "display_tab_id": "trip-demo-a",
                 "income_kind": "deposit", "amount_krw": 300000},
                {"customer_name": "U2", "display_tab_id": "trip-demo-b",
                 "income_kind": "balance", "amount_krw": 200000},
            ],
            client_request_id="board-allocation-plan",
        )
        allocations = self.store.active_allocations(created["row_id"])
        l1 = next(a for a in allocations if a["display_tab_id"] == "trip-demo-a")
        l2 = next(a for a in allocations if a["display_tab_id"] == "trip-demo-b")
        with urllib.request.urlopen(
            f"http://127.0.0.1:{self.port}/row?id={l1['allocation_id']}&edit=1"
        ) as response:
            page = response.read().decode("utf-8")
        self.assertIn(f"/api/rows/{l1['allocation_id']}/save", page)
        self.assertIn("name='expected_revision' value='2'", page)
        self.assertIn("name='customer_name'", page)
        self.assertIn("name='display_tab_id'", page)
        self.assertIn("name='income_kind'", page)
        self.assertNotIn("name='amount_krw'", page)
        self.assertNotIn("name='occurred_on'", page)
        self.assertIn("readonly", page)
        status, result = self._post_json_path(
            f"/api/rows/{l1['allocation_id']}/save",
            {
                "csrf": self.board_mod.CSRF_TOKEN,
                "expected_revision": 2,
                "client_request_id": "board-allocation-amount",
                "amount_krw": 1,
            },
        )
        self.assertEqual(status, 422)
        self.assertEqual(result["code"], "FIELD_READ_ONLY")
        self.assertEqual(self.store.get_allocation(l1["allocation_id"])["amount_krw"], 300000)
        status, result = self._post_json_path(
            f"/api/rows/{l1['allocation_id']}/save",
            {
                "csrf": self.board_mod.CSRF_TOKEN,
                "expected_revision": 2,
                "client_request_id": "board-allocation-date",
                "occurred_on": "2026-04-02",
            },
        )
        self.assertEqual(status, 422)
        self.assertEqual(result["code"], "FIELD_READ_ONLY")
        self.assertEqual(self.store.get_allocation(l1["allocation_id"])["amount_krw"], 300000)
        edit_payload = {
            "csrf": self.board_mod.CSRF_TOKEN,
            "expected_revision": 2,
            "client_request_id": "board-allocation-edit",
            "customer_id": "U1",
            "customer_name": "U1-mod",
            "nickname": "별명",
            "display_tab_id": "trip-demo-b",
            "income_kind": "balance",
        }
        status, edited = self._post_json_path(
            f"/api/rows/{l1['allocation_id']}/save", edit_payload
        )
        self.assertEqual(status, 200)
        self.assertEqual(edited["revision"], 3)
        retry_status, retried = self._post_json_path(
            f"/api/rows/{l1['allocation_id']}/save", edit_payload
        )
        self.assertEqual(retry_status, 200)
        self.assertEqual(retried, edited)
        self.assertEqual(self.store.tab_totals("trip-demo-a")["income"], 1000000)
        self.assertEqual(self.store.tab_totals("trip-demo-b")["income"], 500000)
        with urllib.request.urlopen(
            f"http://127.0.0.1:{self.port}/row?id={l1['allocation_id']}"
        ) as response:
            detail = response.read().decode("utf-8")
        self.assertIn("이 배분 행 되돌리기", detail)
        self.assertIn(f"/api/rows/{l1['allocation_id']}/revert", detail)
        self.assertIn("name='expected_revision' value='3'", detail)
        self.assertIn("trip-demo-a", detail)
        revert_payload = {
            "csrf": self.board_mod.CSRF_TOKEN,
            "expected_revision": 3,
            "client_request_id": "board-allocation-revert",
        }
        status, reverted = self._post_json_path(
            f"/api/rows/{l1['allocation_id']}/revert", revert_payload
        )
        self.assertEqual(status, 200)
        self.assertEqual(reverted["outcome"], "reverted")
        self.assertEqual(reverted["revision"], 4)
        retry_status, retried_revert = self._post_json_path(
            f"/api/rows/{l1['allocation_id']}/revert", revert_payload
        )
        self.assertEqual(retry_status, 200)
        self.assertEqual(retried_revert, reverted)
        self.assertEqual(self.store.tab_totals("trip-demo-a")["income"], 1300000)
        self.assertEqual(self.store.tab_totals("trip-demo-b")["income"], 200000)
        final_l2 = self.store.get_allocation(l2["allocation_id"])
        for field in ("customer_name", "display_tab_id", "income_kind", "amount_krw"):
            self.assertEqual(final_l2[field], l2[field])
        stale_status, stale = self._post_json_path(
            f"/api/rows/{l1['allocation_id']}/save",
            dict(edit_payload, client_request_id="board-allocation-stale"),
        )
        self.assertEqual(stale_status, 409)
        self.assertEqual(stale["code"], "EDIT_CONFLICT")
        self.assertEqual(self.store.get_allocation(l1["allocation_id"])["display_tab_id"], "trip-demo-a")

    def test_allocation_detail_shows_revert_blocked_reason(self):
        import urllib.request

        created = self.store.create_direct_income(
            fields={
                "display_tab_id": None, "occurred_on": "2026-04-01",
                "amount_krw": 500000, "income_kind": "deposit",
                "customer_id": None, "customer_name": "P1",
                "nickname": "", "memo": "",
            },
            client_request_id="board-allocation-reason-source",
        )
        self.store.save_allocations(
            source_row_id=created["row_id"], expected_source_revision=1,
            allocations=[
                {"customer_name": "U1", "display_tab_id": "trip-demo-a",
                 "income_kind": "deposit", "amount_krw": 300000},
            ],
            client_request_id="board-allocation-reason-plan",
        )
        allocation = self.store.active_allocations(created["row_id"])[0]
        with urllib.request.urlopen(
            f"http://127.0.0.1:{self.port}/row?id={allocation['allocation_id']}"
        ) as response:
            page = response.read().decode("utf-8")
        self.assertIn("직전 변경은 배분 전체 수정", page)
        self.assertIn("이 배분 행 되돌리기", page)

    def test_bad_date_rejected(self):
        status, result = self._post("income-demo-i1", {
            "csrf": self.board_mod.CSRF_TOKEN,
            "expected_revision": 1,
            "client_request_id": "api-i1-baddate",
            "change_mode": "exception",
            "occurred_on": "2026-99-99",
        })
        self.assertEqual(status, 422)
        self.assertEqual(result["code"], "INVALID_VALUE")


if __name__ == "__main__":
    unittest.main()
