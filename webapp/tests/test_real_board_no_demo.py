"""A store that was never seeded must not show the example board.

REAL-BOARD-DEMO-LEAK-001. The report was "still only examples" against a real
deployment. The cause is here: `_expense_rows` and `_income_rows` walked the
module-level `EXPENSES`/`INCOMES` and fell back to the static dict for any row the
bound store did not have. A store opened with `seed_demo=False` therefore rendered
the whole example board while its own `board_rows` table held nothing, and the page
badge said 합성 자료 over data that had never been imported.

So these tests open the store the way an operational start does, `seed_demo=False`,
and check that what is on screen is what the store holds. A store that *is* seeded
must keep showing its seeded rows, and a store with a row of its own must show that
row and not the examples.

Synthetic values only. A temporary directory, rows written here through the store's
own save path, and a synthetic owner session. No customer data, no import, and no
database file from a deployment.
"""

import json
import os
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path

from webapp import access_control
from webapp import ledger_board as board_mod
from webapp import ledger_design
from webapp import live_sync
from webapp.ledger_store import LedgerStore

OWNER = "syn-owner-O"
VIEWER = "syn-staff-real"

# Every id the module-level example data defines. Nothing rendered from a bound
# store may carry one of these, because a bound store either has the row persisted
# under that id or has nothing at all.
EXAMPLE_IDS = (
    "expense-demo-c1", "expense-demo-c2", "expense-demo-c3", "expense-demo-c4",
    "income-demo-i1", "income-demo-i2", "income-demo-i3",
    "trip-demo-a", "trip-demo-b",
)


class RealStoreBoardTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self._prev_db = os.environ.get("WEBLEDGER_DB")
        os.environ["WEBLEDGER_DB"] = str(Path(self.tmp) / "real.sqlite")
        # `serve` opens the store itself, so the flag belongs there. Passing
        # `seed_demo=False` to a constructor and then calling `serve()` without it
        # would not help: `serve` makes a *second* store on the same path with its
        # own default and binds that one, which is how the example trips came back
        # in the first version of this test.
        self.server = board_mod.serve(port=0, with_worker=False, seed_demo=False)
        self.store = board_mod._active_store()
        self.access = access_control.attach_to_ledger_store(self.store)
        self.access.ensure_owner(OWNER)
        self.port = self.server.server_address[1]
        self.thread = threading.Thread(target=self.server.serve_forever,
                                       daemon=True)
        self.thread.start()
        access_control.bind_synthetic_sessions(True)
        board_mod.bind_access(self.access)
        self.trip = ""
        self._saved = 0

    def tearDown(self):
        board_mod.bind_access(None)
        access_control.bind_sessions(access_control.UnboundSessionAdapter())
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)
        board_mod.bind_store(None)
        self.store.close()
        if self._prev_db is None:
            os.environ.pop("WEBLEDGER_DB", None)
        else:
            os.environ["WEBLEDGER_DB"] = self._prev_db

    # ------------------------------------------------------------- helpers
    def get(self, path, user=OWNER, headers=None):
        head = dict(headers or {})
        head[access_control.SyntheticSessionAdapter.HEADER] = user
        request = urllib.request.Request(
            f"http://127.0.0.1:{self.port}{path}", headers=head)
        try:
            with urllib.request.urlopen(request) as response:
                return response.status, response.read().decode("utf-8")
        except urllib.error.HTTPError as exc:
            return exc.code, exc.read().decode("utf-8")

    def get_json(self, path, user=OWNER, headers=None):
        status, body = self.get(path, user, headers)
        return status, json.loads(body)

    def fragment(self, tab, user=OWNER):
        """The `X-Part: live-state` answer, which is what a second browser gets."""
        _status, body = self.get(
            f"/api/live/state?tab={tab}", user, {"X-Part": "live-state"})
        return body

    def make_trip(self, display_key="2026-05 실제여행", starts_on="2026-05-01"):
        """Create a trip and remember the id the store made for it.

        The store names the tab itself, so the id is not chosen here and the tests
        read it back rather than assuming one.
        """
        created = self.store.create_trip(
            starts_on=starts_on, ends_on="2026-05-07", destination="실제여행",
            display_key=display_key, client_request_id=f"trip-{starts_on}")
        self.assertTrue(created["tab_id"])
        self.trip = created["tab_id"]
        return self.trip

    def expense(self, tab=None, amount=125000, item="실제 지출"):
        """Create an expense the way the product creates one.

        `save` refuses a row the store has never seen, so a new row goes through
        the same `create_manual_expense` call the board's own 지출 추가 button uses.
        That is deliberate: a fixture inserting rows straight into SQLite would be
        testing a state the product cannot reach.
        """
        if tab is None and not self.trip:
            self.make_trip()
        result = self.store.create_manual_expense(
            fields={"display_tab_id": self.trip or "unclassified",
                    "occurred_on": "2026-05-02", "amount_krw": amount,
                    "item": item, "description": "실제 자료 행",
                    "pay_method": "현금", "source_kind": "직접입력",
                    "source_event_id": "REAL-EV-1",
                    "source_merchant": "실제 가맹점"},
            client_request_id=f"real-ex-{amount}")
        self.expense_id = result["row_id"]
        return result

    def income(self, amount=400000, customer="실제 고객"):
        if not self.trip:
            self.make_trip()
        result = self.store.create_direct_income(
            fields={"display_tab_id": self.trip, "occurred_on": "2026-05-03",
                    "amount_krw": amount, "income_kind": "deposit",
                    "customer_id": "U-REAL", "customer_name": customer,
                    "nickname": "실제", "source_kind": "직접입력",
                    "source_event_id": "REAL-IN-1"},
            client_request_id=f"real-in-{amount}")
        self.income_id = result["row_id"]
        return result

    def assert_no_example_data(self, markup, where):
        for example_id in EXAMPLE_IDS:
            self.assertNotIn(example_id, markup,
                             f"{where} still shows the example id {example_id}")

    # ----------------------------------------------------------------- tests
    def test_the_store_really_is_empty(self):
        """The premise, asserted, so a leak cannot pass on a seeded fixture."""
        self.assertEqual(self.store.conn.execute(
            "SELECT COUNT(*) FROM board_rows").fetchone()[0], 0)
        self.assertEqual(board_mod.live_trips(), [])
        self.assertEqual(board_mod._expense_rows(), [])
        self.assertEqual(board_mod._income_rows(), [])

    def test_an_empty_store_renders_no_example_rows(self):
        _status, page = self.get("/board?tab=unclassified")
        self.assert_no_example_data(page, "the board page")
        for word in ("예시 숙소", "예시여행", board_mod.SYNTHETIC_MARK):
            self.assertNotIn(word, page,
                             f"the board page still shows {word}")

    def test_the_board_page_shows_no_example_rows(self):
        _status, page = self.get("/board")
        self.assert_no_example_data(page, "/board")
        self.assertNotIn("여행을 선택해 주세요", page)

    def test_the_unclassified_page_shows_no_example_rows(self):
        _status, page = self.get("/board?tab=unclassified")
        self.assert_no_example_data(page, "the unclassified page")

    def test_a_nonexistent_trip_id_renders_no_rows(self):
        """Asking for a trip the store does not have shows nothing, not examples.

        The id asked for is echoed back into the nav form's hidden input, so the
        check is on the row region rather than the whole document.
        """
        _status, page = self.get("/board?tab=trip-never-existed")
        self.assert_no_example_data(page, "the page for a trip that does not exist")
        # the empty state, not the example board that used to stand in for it
        self.assertIn("지출 내역이 없어요", page)

    def test_the_sync_fragments_carry_no_example_rows(self):
        """A second browser gets the fragments, so the leak reaches it too.

        A page that renders cleanly is not enough: the live refresh swaps the
        regions from this bundle, and it reads the same rows.
        """
        for tab in ("unclassified", "trip-demo-a"):
            self.assert_no_example_data(self.fragment(tab),
                                        f"the fragment for {tab}")
        _status, poll = self.get_json(f"/api/live/state?tab={self.trip or 'x'}")
        self.assert_no_example_data(json.dumps(poll, ensure_ascii=False),
                                    "the poll body")

    def test_the_default_tab_is_not_a_trip_that_does_not_exist(self):
        """`/board` with no `tab` must not open on a hard-coded example trip.

        It used to default to `trip-demo-a`, which on a store that was never
        seeded is a trip that does not exist, so the page opened on a head saying
        pick a trip with a rail that had nothing selected.
        """
        self.assertEqual(board_mod.default_board_tab(), "unclassified")
        _status, page = self.get("/board")
        self.assert_no_example_data(page, "/board")
        self.assertIn("분류대기", page)

    def test_the_default_tab_follows_the_data(self):
        """A trip grouped under past trips remains explicitly accessible."""
        self.make_trip()
        self.assertEqual(board_mod.default_board_tab(), "unclassified")
        _status, page = self.get(f"/board?tab={self.trip}")
        self.assertIn("2026-05 실제여행", page)

    def test_a_persisted_row_is_shown_and_no_example_is_added(self):
        """The store's own row appears, and the examples do not come with it."""
        self.expense()
        _status, page = self.get(f"/board?tab={self.trip}")
        self.assertIn("실제 지출", page)
        self.assertIn("125,000원", page)
        self.assert_no_example_data(page, "the board page")
        self.assertEqual([r["row_id"] for r in board_mod._expense_rows()],
                         [self.expense_id])

    def test_a_persisted_row_also_reaches_the_fragment(self):
        self.expense()
        bundle = self.fragment(self.trip)
        self.assertIn("실제 지출", bundle)
        self.assert_no_example_data(bundle, "the fragment")

    def test_the_badge_reports_the_persisted_count_not_synthetic_data(self):
        """The badge said 합성 자료 on a store serving its own rows, which is false.

        It now reports the number of rows the store holds, which is the number the
        board is rendering and the reader can check.
        """
        self.assertEqual(board_mod.data_status_mark(), "장부 기록 0건")
        self.expense()
        self.assertEqual(board_mod.data_status_mark(), "여행 1개 · 장부 기록 1건")
        _status, page = self.get(f"/board?tab={self.trip}")
        self.assertIn("장부 기록 1건", page)
        self.assertNotIn(board_mod.SYNTHETIC_MARK, page)

    def test_a_seeded_store_still_says_synthetic_data(self):
        """A store holding only the example rows is the example board.

        The seeder writes those rows into the database, so a seeded store and an
        imported one are indistinguishable by where the rows live. They are
        distinguishable by what the rows are, and a store whose every row is an
        example id on an example trip is showing examples whatever wrote it.
        """
        seeded = LedgerStore(Path(self.tmp) / "badge.sqlite", seed_demo=True)
        try:
            board_mod.bind_store(seeded)
            self.assertEqual(board_mod.data_status_mark(),
                             board_mod.SYNTHETIC_MARK)
            # and one row of its own takes it off the example board
            seeded.create_manual_expense(
                fields={"display_tab_id": "trip-demo-a",
                        "occurred_on": "2026-05-02", "amount_krw": 1000,
                        "item": "직접 행", "pay_method": "현금"},
                client_request_id="badge-1")
            self.assertEqual(board_mod.data_status_mark(),
                             "여행 2개 · 장부 기록 8건")
        finally:
            board_mod.bind_store(self.store)
            seeded.close()

    def test_the_unclassified_bucket_shows_a_persisted_row_with_no_trip(self):
        """A row saved with no trip lands in 분류대기, and only that row does."""
        self.make_trip()
        self.expense(amount=9000, item="미배정 지출")
        # put it in the bucket the way the product does: the id the form sends
        self.store.save(
            row_id=self.expense_id, expected_revision=1,
            client_request_id="move-real-unc", change_mode="exception",
            changes={"display_tab_id": "unclassified"})
        self.assertEqual([r["row_id"] for r in board_mod._unclassified_rows()],
                         [self.expense_id])
        _status, page = self.get("/board?tab=unclassified")
        self.assertIn("미배정 지출", page)
        self.assert_no_example_data(page, "the unclassified page")

    def test_an_income_row_is_shown_too(self):
        self.income()
        _status, page = self.get(f"/board?tab={self.trip}")
        self.assertIn("실제 고객", page)
        self.assert_no_example_data(page, "the board page")

    def test_an_allocation_projection_is_still_shown(self):
        """Removing the static rows must not remove the projections.

        The store's own `list_tab_rows` returns allocation rows, and the board has
        always shown them, so a store that holds only allocations must still show
        them. A fix that read `board_rows` directly instead of going through
        `list_tab_rows` would pass every other test here and lose these.
        """
        self.income(amount=600000, customer="원천")
        result = self.store.save_allocations(
            source_row_id=self.income_id, expected_source_revision=1,
            allocations=[{"customer_name": "배분 고객",
                          "display_tab_id": self.trip,
                          "income_kind": "deposit", "amount_krw": 250000}],
            client_request_id="split-real-1")
        self.assertEqual(result["outcome"], "saved")
        rows = board_mod._income_rows()
        ids = [r["row_id"] for r in rows]
        # The store names the projection after the request, not after the word
        # "alloc", so the check is on the row's own flag rather than its id.
        self.assertTrue(any(r.get("is_allocation") for r in rows),
                        f"the allocation projection is missing: {ids}")
        self.assertIn("배분 고객",
                      " ".join(str(r.get("customer_name")) for r in rows))
        self.assert_no_example_data(" ".join(ids), "the income rows")

    def test_a_seeded_store_still_shows_its_seeded_rows(self):
        """A store that *is* seeded keeps its rows. The fix is not 'show nothing'."""
        seeded = LedgerStore(Path(self.tmp) / "seeded.sqlite", seed_demo=True)
        try:
            board_mod.bind_store(seeded)
            self.assertTrue(board_mod._expense_rows())
            self.assertTrue(board_mod._income_rows())
            self.assertIn("trip-demo-a", board_mod.valid_tab_ids())
            # those rows are persisted, not module constants leaking through
            for row in board_mod._expense_rows():
                self.assertIsNotNone(seeded.get_row(row["row_id"]),
                                     f"{row['row_id']} is not in the seeded store")
            self.assertEqual(board_mod.default_board_tab(), "unclassified")
        finally:
            board_mod.bind_store(self.store)
            seeded.close()

    def test_no_store_bound_still_renders_the_in_memory_examples(self):
        """The no-store path is the explicit synthetic demo, and it stays.

        `_active_store()` is None only in tests and in the in-memory demo. It is
        the one place the static rows are the right answer, so removing them
        everywhere would break the developer board several existing tests use.
        """
        board_mod.bind_store(None)
        try:
            self.assertTrue(board_mod._expense_rows())
            self.assertTrue(board_mod._income_rows())
            self.assertEqual(board_mod.data_status_mark(),
                             board_mod.SYNTHETIC_MARK)
            self.assertEqual(board_mod.default_board_tab(), "unclassified")
        finally:
            board_mod.bind_store(self.store)

    def test_the_row_detail_page_has_no_examples(self):
        """`/row` is a separate path over the same rows."""
        self.expense()
        _status, page = self.get(f"/row?id={self.expense_id}")
        self.assert_no_example_data(page, "the row page")
        self.assertIn(self.expense_id, page)

    def test_the_two_second_sync_still_works_on_a_real_store(self):
        """The live refresh is unaffected: a save moves the token and the bundle.

        This is here because the row readers changed underneath it. A refresh that
        stopped finding real rows would not show up in any test above.
        """
        self.expense()
        before = live_sync.owner_token(self.store, self.trip)
        _status, poll = self.get_json(
            f"/api/live/state?tab={self.trip}&token={before}")
        self.assertFalse(poll["changed"])
        status, body = self._save_through_the_api(self.expense_id,
                                                 description="실시간 갱신 확인")
        self.assertEqual(status, 200, body[:300])
        _status, poll = self.get_json(
            f"/api/live/state?tab={self.trip}&token={before}")
        self.assertTrue(poll["changed"])
        bundle = self.fragment(self.trip)
        self.assertIn("실시간 갱신 확인", bundle)
        self.assert_no_example_data(bundle, "the fragment")

    def _save_through_the_api(self, row_id, **changes):
        row = self.store.get_row(row_id)
        payload = {
            "csrf": board_mod.CSRF_TOKEN,
            "expected_revision": row["revision"],
            "client_request_id": f"real-api-{row['revision']}-{row_id}",
            "change_mode": "exception",
        }
        payload.update(changes)
        request = urllib.request.Request(
            f"http://127.0.0.1:{self.port}/api/rows/{row_id}/save",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json",
                     access_control.SyntheticSessionAdapter.HEADER: OWNER},
            method="POST")
        try:
            with urllib.request.urlopen(request) as response:
                return response.status, response.read()
        except urllib.error.HTTPError as exc:
            return exc.code, exc.read()

    def test_a_viewer_sees_no_examples_either(self):
        """The viewer's own board goes through a different renderer."""
        self.access.create_account(user_id=VIEWER, role=access_control.ROLE_VIEWER)
        self.expense()
        self.access.register_reservation_person(
            reservation_person_id="rp-real", display_name="실제 담당자")
        application = self.access.create_application(
            user_id=VIEWER, requested_name="실제 담당자", nickname="담당",
            description="합성 링크", client_request_id="app-real")
        self.access.approve_application(
            application_id=application["application_id"], owner_id=OWNER,
            expected_revision=1, reservation_person_id="rp-real",
            client_request_id="dec-real")
        self.access.apply_assignment_snapshot(
            user_id=VIEWER,
            items=[{"tab_id": self.trip, "snapshot_revision": 1,
                    "state": access_control.ASSIGN_ACTIVE}],
            source_version="src-real", complete=False)
        status, page = self.get(f"/board?tab={self.trip}", user=VIEWER)
        self.assertEqual(status, 200)
        self.assert_no_example_data(page, "the viewer board")
        self.assertIn("125,000원", page)


class DesignRendererTests(unittest.TestCase):
    """The renderers called directly, so a leak is caught without a server."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self._prev_db = os.environ.get("WEBLEDGER_DB")
        self.path = Path(self.tmp) / "design.sqlite"
        os.environ["WEBLEDGER_DB"] = str(self.path)
        self.store = LedgerStore(self.path, seed_demo=False)
        board_mod.bind_store(self.store)
        self.addCleanup(self._restore)

    def _restore(self):
        board_mod.bind_store(None)
        self.store.close()
        if self._prev_db is None:
            os.environ.pop("WEBLEDGER_DB", None)
        else:
            os.environ["WEBLEDGER_DB"] = self._prev_db

    def test_rows_region_is_empty_for_an_unseeded_store(self):
        self.assertNotIn("expense-demo", ledger_design.rows_region("unclassified"))
        self.assertNotIn("expense-demo", ledger_design.nav_region("unclassified"))

    def test_rows_part_has_no_example_rows_for_an_unseeded_store(self):
        """The empty-state table is still rendered; what matters is its content.

        Asserting the part is an empty string would be asserting the wrong thing:
        the reader needs the table with its headers and its "no rows" line, not a
        blank region.
        """
        part = ledger_design.rows_part("unclassified")
        self.assertIn("지출 내역이 없어요", part)
        for example_id in EXAMPLE_IDS:
            self.assertNotIn(example_id, part)

    def test_the_page_for_a_missing_trip_has_no_examples(self):
        markup = ledger_design.render(ledger_design.page("trip-demo-a"))
        self.assertNotIn("expense-demo", markup)
        self.assertNotIn("income-demo", markup)

    def test_a_persisted_row_reaches_the_rows_part(self):
        trip = self.store.create_trip(
            starts_on="2026-05-01", ends_on="2026-05-07", destination="실제여행",
            display_key="2026-05 실제여행", client_request_id="t-d1")["tab_id"]
        self.store.create_manual_expense(
            fields={"display_tab_id": trip, "occurred_on": "2026-05-02",
                    "amount_krw": 7000, "item": "직접 확인 행",
                    "pay_method": "현금", "source_kind": "직접입력",
                    "source_event_id": "D-EV", "source_merchant": "가맹점"},
            client_request_id="d-1")
        part = ledger_design.rows_part(trip)
        self.assertIn("직접 확인 행", part)
        for example_id in EXAMPLE_IDS:
            self.assertNotIn(example_id, part)
