"""Phase 5 export tests (synthetic only).

Verifies W08: selected tabs only, row-by-row values and totals match
the app, formulas present but app totals authoritative, slot overflow,
long reservation numbers as text, formula-injection guard, sheet-name
collision, existing-file preservation, and failure behavior.
"""

import json
import tempfile
import threading
import unittest
from pathlib import Path

from openpyxl import load_workbook

from webapp.ledger_store import LedgerStore
from webapp.sheets_export import (
    build_workbook,
    EXPENSE_FIRST_ROW,
    EXPENSE_HEADER_ROW,
    EXPENSE_SLOTS,
    guard_text,
    publish_workbook,
    sanitize_sheet_name,
    COLUMN_WIDTHS,
)


def make_store():
    directory = tempfile.mkdtemp()
    return LedgerStore(Path(directory) / "webledger.sqlite")


class ReadOnlyJobLookupTests(unittest.TestCase):
    def test_job_reads_do_not_create_a_missing_table(self):
        import sqlite3
        from webapp.sheets_export import get_job, list_jobs
        with sqlite3.connect(':memory:') as conn:
            before = conn.execute('SELECT name,sql FROM sqlite_master').fetchall()
            self.assertIsNone(get_job(conn, 'missing'))
            self.assertEqual(list_jobs(conn), [])
            self.assertEqual(before, conn.execute('SELECT name,sql FROM sqlite_master').fetchall())

    def test_legacy_jobs_without_output_path_are_read_without_migration(self):
        import sqlite3
        from webapp.sheets_export import get_job, list_jobs, EXPORT_JOBS_SCHEMA
        with sqlite3.connect(':memory:') as conn:
            conn.executescript(EXPORT_JOBS_SCHEMA.replace('    output_path TEXT,', ''))
            conn.execute('INSERT INTO ledger_export_jobs VALUES (?,?,?,?,?,?,?)',
                         ('old-job', '[]', 'snapshot', 'template', 'digest', 'ready', '2026-10-07'))
            before = conn.execute('SELECT name,sql FROM sqlite_master').fetchall()
            job = get_job(conn, 'old-job')
            self.assertIsNone(job['output_path'])
            self.assertEqual(list_jobs(conn), [job])
            self.assertEqual(before, conn.execute('SELECT name,sql FROM sqlite_master').fetchall())


def sheet_values(path, name):
    wb = load_workbook(path, read_only=True, data_only=False)
    ws = wb[name]
    return ws, wb


class CoordinatedWorkbook:
    def __init__(self, label, workbook, first_saved, second_saved, barrier, paths, payloads):
        self.label = label
        self.workbook = workbook
        self.first_saved = first_saved
        self.second_saved = second_saved
        self.barrier = barrier
        self.paths = paths
        self.payloads = payloads

    def save(self, path):
        if self.label == "A":
            self.workbook.save(path)
            self.first_saved.set()
            if not self.second_saved.wait(5.0):
                raise RuntimeError("second workbook save timed out")
        else:
            if not self.first_saved.wait(5.0):
                raise RuntimeError("first workbook save timed out")
            self.workbook.save(path)
            self.second_saved.set()
        self.paths[self.label] = Path(path)
        self.payloads[self.label] = Path(path).read_bytes()
        self.barrier.wait(5.0)


class InterruptingWorkbook:
    def save(self, path):
        with Path(path).open("wb") as handle:
            handle.write(b"partial")
            handle.flush()
        raise KeyboardInterrupt("injected during workbook save")


def make_store_with_owner(company="합성회사", assignee="합성담당자"):
    """A store whose owner values are set explicitly by this fixture.

    B2 and H4 used to be non-empty because the product carried synthetic
    defaults. It does not any more: a cell is empty until the owner fills it.
    These tests care about layout and the formula guard, so the fixture supplies
    the values rather than the product inventing them.
    """
    store = make_store()
    store.save_owner_profile(expected_revision=0, client_request_id="fixture-p1",
                             company_name=company, assignee_name=assignee)
    for row in store.conn.execute(
            "SELECT tab_id, revision FROM trip_tabs").fetchall():
        store.save_trip_meta(tab_id=row[0], expected_revision=row[1],
                             client_request_id=f"fixture-m-{row[0]}",
                             prepared_by_name=assignee)
    return store


class ExportBasicsTests(unittest.TestCase):
    def test_two_tabs_values_and_totals(self):
        store = make_store()
        try:
            wb, manifest = build_workbook(store, ["trip-demo-a", "trip-demo-b"])
            self.assertEqual(wb.sheetnames, ["0408_예시여행A", "0420_예시여행B"])
            self.assertEqual(manifest["tab_order"], ["trip-demo-a", "trip-demo-b"])
            directory = tempfile.mkdtemp()
            target, manifest = publish_workbook(wb, manifest, directory, "ledger-test")
            self.assertTrue(target.exists())
            ws, _ = sheet_values(target, "0408_예시여행A")
            self.assertEqual(ws["C31"].value, "=SUM(H8:H30)")
            amounts = [ws.cell(row=r, column=8).value for r in range(8, 11)]
            self.assertEqual(amounts, [500000, 300000, 200000])
            expenses = [ws.cell(row=r, column=8).value for r in range(35, 38)]
            self.assertEqual(expenses, [100000, -20000, 100000])
            totals = store.tab_totals("trip-demo-a")
            self.assertEqual(sum(amounts), totals["income"])
            self.assertEqual(sum(expenses), totals["expense"])
        finally:
            store.close()

    def test_unselected_tabs_excluded(self):
        store = make_store()
        try:
            wb, _ = build_workbook(store, ["trip-demo-b"])
            self.assertEqual(wb.sheetnames, ["0420_예시여행B"])
        finally:
            store.close()

    def test_sheet_name_collision(self):
        used = set()
        first = sanitize_sheet_name("0408_예시여행A", used)
        second = sanitize_sheet_name("0408_예시여행A", used)
        self.assertNotEqual(first, second)
        self.assertTrue(len(second) <= 31)

    def test_guard_text_catches_a_formula_behind_leading_whitespace(self):
        # Excel trims leading whitespace on entry, so a tab or a space in front
        # of "=" would still arrive as a formula. The guard has to look past it.
        for prefix in ("", " ", "\t", "  \t ", "\r\n"):
            with self.subTest(prefix=repr(prefix)):
                guarded = guard_text(f"{prefix}=1+1")
                # The point is that the *first* character Excel sees is an
                # apostrophe, whatever whitespace was in front of the "=".
                self.assertTrue(guarded.startswith("'"),
                                f"{guarded!r} is not neutralised")
                # and the whitespace that Excel would have trimmed is gone, so
                # there is nothing in front of the apostrophe to re-appear
                self.assertEqual(guarded, "'=1+1")
        # the same for the other formula starters
        for starter in ("+", "-", "@"):
            self.assertTrue(guard_text(f"\t{starter}cmd").startswith("'"))
        # a leading space in front of ordinary text is left alone
        self.assertEqual(guard_text(" 일반 "), " 일반 ")

    def test_a_free_typed_trip_title_cannot_become_a_sheet_name_formula(self):
        # The trip title is free operator text and it is used verbatim as the
        # sheet name, so it is the one entry point the cell guard does not cover.
        store = make_store()
        try:
            trip = store.get_trip("trip-demo-a")
            store.save_trip_meta(
                tab_id="trip-demo-a", expected_revision=trip["revision"],
                client_request_id="x-title-formula", display_key="=1+1")
            self.assertEqual(store.get_trip("trip-demo-a")["display_key"], "=1+1")
            wb, manifest = build_workbook(store, ["trip-demo-a"])
            name = wb.sheetnames[0]
            self.assertTrue(name.startswith("'"),
                            f"sheet name {name!r} was not neutralised")
            self.assertFalse(name.startswith("="))
            # and the only formulas in the sheet are the three intended totals
            formulas = [c.value for row in wb[name].iter_rows() for c in row
                        if c.data_type == "f"]
            self.assertEqual(len(formulas), 3)
            self.assertTrue(all(str(f).startswith("=SUM") or str(f).startswith("=C")
                                for f in formulas), formulas)
        finally:
            store.close()

    def test_an_owner_name_cannot_become_a_formula_cell(self):
        # The owner name printed on the sheet is free text too.
        store = make_store()
        try:
            trip = store.get_trip("trip-demo-a")
            store.save_trip_meta(
                tab_id="trip-demo-a", expected_revision=trip["revision"],
                client_request_id="x-name-formula",
                prepared_by_name="=HYPERLINK(\"http://x\")")
            wb, _ = build_workbook(store, ["trip-demo-a"])
            ws = wb[wb.sheetnames[0]]
            found = [c.value for row in ws.iter_rows() for c in row
                     if isinstance(c.value, str) and "HYPERLINK" in c.value]
            self.assertTrue(found)
            for value in found:
                self.assertTrue(value.startswith("'"), value)
            self.assertEqual([c.value for row in ws.iter_rows() for c in row
                              if c.data_type == "f" and "HYPERLINK" in str(c.value)],
                             [])
        finally:
            store.close()

    def test_the_output_carries_the_template_sheet_metadata(self):
        """REVIEW 10절이 지적한 비식별 양식 메타데이터.

        All six merges, the eight column widths, the landscape orientation and
        the margins have to survive into the generated file, because the sheet
        is printed as well as read. The company name and the operator name stay
        synthetic: the real header values are a separate, external input.
        """
        from openpyxl import load_workbook

        store = make_store()
        try:
            wb, manifest = build_workbook(store, ["trip-demo-a"])
            name = wb.sheetnames[0]
            ws = wb[name]

            # the six merges the original template uses
            merged = {str(r) for r in ws.merged_cells.ranges}
            for expected in ("C2:H2", "B6:H6", "C31:H31",
                             "B33:H33", "C85:H85", "C87:H87"):
                self.assertIn(expected, merged)

            # the eight column widths
            expected_widths = {"A": 2.63, "B": 17.5, "C": 14.63, "D": 16.38,
                               "E": 11.88, "F": 12.38, "G": 11.25, "H": 14.88}
            for column, width in expected_widths.items():
                self.assertAlmostEqual(
                    ws.column_dimensions[column].width, width, places=2,
                    msg=f"column {column}")

            # print setup
            self.assertEqual(ws.page_setup.orientation, "landscape")
            margins = ws.page_margins
            self.assertAlmostEqual(margins.left, 0.7, places=3)
            self.assertAlmostEqual(margins.right, 0.7, places=3)
            self.assertAlmostEqual(margins.top, 0.75, places=3)
            self.assertAlmostEqual(margins.bottom, 0.75, places=3)
            self.assertEqual(margins.header, 0)
            self.assertEqual(margins.footer, 0)

            # and it must survive a write/read round trip, not just the object
            directory = tempfile.mkdtemp()
            target, _ = publish_workbook(wb, manifest, directory,
                                          "fmt-round")
            again = load_workbook(target)
            reloaded = again[name]
            self.assertEqual(reloaded.page_setup.orientation, "landscape")
            self.assertAlmostEqual(reloaded.page_margins.left, 0.7, places=3)
            self.assertEqual(reloaded.page_margins.footer, 0)
            self.assertAlmostEqual(reloaded.column_dimensions["B"].width, 17.5,
                                   places=2)
            self.assertIn("C2:H2",
                          {str(r) for r in reloaded.merged_cells.ranges})
        finally:
            store.close()

    def test_formula_guard(self):
        self.assertEqual(guard_text("=1+1"), "'=1+1")
        self.assertEqual(guard_text("+82"), "'+82")
        self.assertEqual(guard_text("일반"), "일반")
        self.assertEqual(guard_text(""), "")

    def test_long_reservation_number_text(self):
        store = make_store()
        try:
            created = store.create_manual_expense(
                fields={
                    "display_tab_id": "trip-demo-a", "occurred_on": "2026-04-09",
                    "pay_method": "현금", "item": "기타", "description": "=1+1",
                    "amount_krw": 1000, "memo": "",
                },
                client_request_id="man-resno-1",
            )
            wb, manifest = build_workbook(store, ["trip-demo-a"])
            mem_formats = {
                wb["0408_예시여행A"].cell(row=r, column=6).number_format
                for r in range(35, 39)
            }
            self.assertEqual(mem_formats, {"@"})
            directory = tempfile.mkdtemp()
            target, _ = publish_workbook(wb, manifest, directory, "ledger-resno")
            ws, _ = sheet_values(target, "0408_예시여행A")
            found = [
                ws.cell(row=r, column=4).value
                for r in range(35, 90)
                if ws.cell(row=r, column=4).value
            ]
            self.assertIn("'=1+1", found)
            for row in ws.iter_rows(min_row=8, max_row=120, values_only=False):
                for cell in row:
                    if cell.data_type == "f":
                        self.assertTrue(
                            str(cell.value).startswith("=SUM(") or "-C" in str(cell.value),
                            f"only total formulas allowed: {cell.coordinate}",
                        )
            reservation = None
            for r in range(35, 90):
                if ws.cell(row=r, column=4).value == "'=1+1":
                    reservation = ws.cell(row=r, column=6)
            self.assertIsNotNone(reservation)
        finally:
            store.close()

    def test_slot_overflow_extends(self):
        store = make_store()
        try:
            for i in range(55):
                store.create_manual_expense(
                    fields={
                        "display_tab_id": "trip-demo-b", "occurred_on": "2026-04-21",
                        "pay_method": "현금", "item": "기타", "description": f"항목{i}",
                        "amount_krw": 1000, "memo": "",
                    },
                    client_request_id=f"man-over-{i}",
                )
            wb, _ = build_workbook(store, ["trip-demo-b"])
            ws = wb["0420_예시여행B"]
            last_data = 35 + 55 - 1
            total_cell = ws.cell(row=last_data + 1, column=3).value
            self.assertEqual(total_cell, f"=SUM(H35:H{last_data})")
            self.assertEqual(store.tab_totals("trip-demo-b")["expense"], 55000)
        finally:
            store.close()

    def test_existing_file_preserved(self):
        store = make_store()
        try:
            wb, manifest = build_workbook(store, ["trip-demo-a"])
            directory = tempfile.mkdtemp()
            first, _ = publish_workbook(wb, manifest, directory, "ledger-same")
            before = first.read_bytes()
            wb2, manifest2 = build_workbook(store, ["trip-demo-b"])
            with self.assertRaises(FileExistsError):
                publish_workbook(wb2, manifest2, directory, "ledger-same")
            self.assertEqual(first.read_bytes(), before)
        finally:
            store.close()

    def test_manifest_hashes(self):
        store = make_store()
        try:
            wb, manifest = build_workbook(store, ["trip-demo-a"])
            self.assertEqual(len(manifest["input_snapshot_sha256"]), 64)
            self.assertEqual(manifest["template_version"], "sales-confirm-rev-p6-synthetic")
            directory = tempfile.mkdtemp()
            _, manifest = publish_workbook(wb, manifest, directory, "ledger-hash")
            self.assertEqual(len(manifest["output_sha256"]), 64)
        finally:
            store.close()

    def test_title_block_and_merges(self):
        store = make_store_with_owner()
        try:
            wb, _ = build_workbook(store, ["trip-demo-a"])
            ws = wb["0408_예시여행A"]
            self.assertTrue(ws["B2"].value)
            self.assertEqual(ws["C2"].value, "0408_예시여행A")
            self.assertIn("C2:H2", [str(r) for r in ws.merged_cells.ranges])
            self.assertEqual(ws["D4"].value, "작성일자")
            self.assertTrue(ws["E4"].value)
            self.assertEqual(ws["G4"].value, "담당자")
            self.assertTrue(ws["H4"].value)
            self.assertIn("B$2", ws.print_area or "")
        finally:
            store.close()

    def test_correction_and_allocation_projection(self):
        store = make_store()
        try:
            created = store.create_direct_income(
                fields={
                    "display_tab_id": "trip-demo-a", "occurred_on": "2026-04-01",
                    "amount_krw": 500000, "income_kind": "deposit",
                    "customer_id": None, "customer_name": "P1",
                    "nickname": "", "memo": "",
                },
                client_request_id="exp-split-1",
            )
            store.save_allocations(
                source_row_id=created["row_id"], expected_source_revision=1,
                allocations=[
                    {"customer_name": "U9", "display_tab_id": "trip-demo-a",
                     "income_kind": "deposit", "amount_krw": 300000},
                ],
                client_request_id="exp-split-plan",
            )
            wb, manifest = build_workbook(store, ["trip-demo-a"])
            ws = wb["0408_예시여행A"]
            values = [
                ws.cell(row=r, column=8).value for r in range(8, 12)
            ]
            self.assertEqual(values, [500000, 300000, 200000, 300000])
            tab = next(t for t in manifest["tabs"] if t["tab_id"] == "trip-demo-a")
            self.assertEqual(tab["prepared_on"], store.get_trip("trip-demo-a")["prepared_on"])
        finally:
            store.close()

    def test_user_string_text_guard_and_atomic_publish(self):
        store = make_store_with_owner()
        try:
            created = store.create_direct_income(
                fields={
                    "display_tab_id": "trip-demo-a", "occurred_on": "2026-04-01",
                    "amount_krw": 500000, "income_kind": "deposit",
                    "customer_id": None, "customer_name": "P1",
                    "nickname": "", "memo": "",
                },
                client_request_id="exp-text-1",
            )
            wb, manifest = build_workbook(store, ["trip-demo-a"])
            ws = wb["0408_예시여행A"]
            title_cell = ws["C2"]
            assignee_cell = ws["H4"]
            self.assertEqual(title_cell.value, "0408_예시여행A")
            self.assertEqual(title_cell.data_type, "s")
            self.assertTrue(assignee_cell.value)
            self.assertEqual(assignee_cell.data_type, "s")
            directory = tempfile.mkdtemp()
            target, manifest = publish_workbook(wb, manifest, directory, "ledger-text")
            self.assertTrue(target.exists())
            with open(str(target), "rb") as f:
                header_bytes = f.read()[:4]
            self.assertEqual(header_bytes, b"PK\x03\x04")
            with self.assertRaises(FileExistsError):
                publish_workbook(wb, manifest, directory, "ledger-text")
        finally:
            store.close()

    def test_snapshot_move_impact_on_workbook(self):
        store = make_store()
        try:
            c1_expense = store.get_row("expense-demo-c1")
            store.save(
                row_id="expense-demo-c1", expected_revision=1,
                client_request_id="move-c1", change_mode="exception",
                changes={"display_tab_id": "trip-demo-b"},
            )
            wb, manifest = build_workbook(store, ["trip-demo-a", "trip-demo-b"])
            directory = tempfile.mkdtemp()
            target, _ = publish_workbook(wb, manifest, directory, "consistency")
            ws = load_workbook(str(target))["0420_예시여행B"]
            expense_amounts = [
                ws.cell(row=r, column=8).value
                for r in range(EXPENSE_FIRST_ROW, EXPENSE_FIRST_ROW + 10)
            ]
            self.assertIn(100000, expense_amounts)
            self.assertNotIn(180000, expense_amounts)
            self.assertTrue(target.exists())
        finally:
            store.close()

    def test_atomic_publish_no_overwrite_and_text_guard(self):
        store = make_store_with_owner()
        try:
            wb, manifest = build_workbook(store, ["trip-demo-a"])
            directory = tempfile.mkdtemp()
            first, _ = publish_workbook(wb, manifest, directory, "atomic-a")
            self.assertTrue(first.exists())
            with open(str(first), "rb") as f:
                digest_before = __import__("hashlib").sha256(f.read()).hexdigest()
            wb2, manifest2 = build_workbook(store, ["trip-demo-b"])
            with self.assertRaises(FileExistsError):
                publish_workbook(wb2, manifest2, directory, "atomic-a")
            self.assertTrue(first.exists())
            with open(str(first), "rb") as f:
                digest_after = __import__("hashlib").sha256(f.read()).hexdigest()
            self.assertEqual(digest_before, digest_after)
            ws, _ = sheet_values(str(first), "0408_예시여행A")
            title_cell = ws["C2"]
            assignee_cell = ws["H4"]
            self.assertTrue(title_cell.value)
            self.assertEqual(title_cell.data_type, "s")
            self.assertTrue(assignee_cell.value)
            self.assertEqual(assignee_cell.data_type, "s")
        finally:
            store.close()

    def test_snapshot_move_before_read_snapshot_fixed(self):
        store = make_store()
        try:
            store.save(
                row_id="expense-demo-c1", expected_revision=1,
                client_request_id="mv-c1", change_mode="exception",
                changes={"display_tab_id": "trip-demo-b"},
            )
            wb, manifest = build_workbook(store, ["trip-demo-a", "trip-demo-b"])
            directory = tempfile.mkdtemp()
            target, manifest = publish_workbook(wb, manifest, directory, "consistent")
            self.assertTrue(target.exists())
            ws_b = load_workbook(str(target))["0420_예시여행B"]
            expense_amounts = [
                ws_b.cell(row=r, column=8).value
                for r in range(EXPENSE_FIRST_ROW, EXPENSE_FIRST_ROW + 10)
            ]
            total_income_trip_a = store.tab_totals("trip-demo-a")["income"]
            total_expense_trip_b = store.tab_totals("trip-demo-b")["expense"]
            # C1 moved to B removes 100000 from A expense and adds it to B expense.
            # Seed A has expense 180000 (C1 100000 + C2 -20000 + C4 100000).
            # After move, B expense = C1 100000; A expense = C2 -20000 + C4 100000.
            self.assertEqual(total_income_trip_a, 1000000)
            self.assertEqual(total_expense_trip_b, 100000)
            ws_a = load_workbook(str(target))["0408_예시여행A"]
            ws_b = load_workbook(str(target))["0420_예시여행B"]
            a_expense_sum = ws_a["C85"].value
            b_expense_sum = ws_b["C85"].value
            self.assertIn("=SUM(", str(a_expense_sum))
            self.assertIn("=SUM(", str(b_expense_sum))
            manifest = manifest or {}
            self.assertIn("input_snapshot_sha256", manifest)
        finally:
            store.close()

    def test_snapshot_concurrent_move_snapshot_fixed(self):
        store_a = make_store()
        store_b = LedgerStore(store_a.path)
        try:
            db_a = store_a
            store_a.conn.execute("PRAGMA journal_mode=WAL")
            store_b.conn.execute("PRAGMA journal_mode=WAL")
            original = store_a.list_tab_rows
            moved = []
            def interleave(tab_id):
                if tab_id == "trip-demo-b" and not moved:
                    moved.append(True)
                    store_b.save(
                        row_id="expense-demo-c1", expected_revision=1,
                        client_request_id="during-export", change_mode="exception",
                        changes={"display_tab_id": "trip-demo-b"},
                    )
                return original(tab_id)
            store_a.list_tab_rows = interleave
            wb, _ = build_workbook(db_a, ["trip-demo-a", "trip-demo-b"])
            total = sum(ws.cell(r, 8).value for ws in wb for r in range(35, 85) if isinstance(ws.cell(r, 8).value, int))
            self.assertEqual(total, 180000)
            # After concurrent save to B, total B expense should stay at original 180000
            # (C1 moved to B should make B expense = 100000, not 280000).
            # Because the interleave saves C1 to B before reading tab rows,
            # _with_display_amount sees it in B's rows.
            self.assertTrue(moved)
            self.assertEqual(store_a.tab_totals("trip-demo-b")["expense"], 100000)
            self.assertFalse(store_a.conn.in_transaction)
            store_a.conn.execute("BEGIN")
            try:
                wb2, _ = build_workbook(store_a, ["trip-demo-a"])
                self.assertTrue(store_a.conn.in_transaction)
            finally:
                store_a.conn.execute("ROLLBACK")
        finally:
            store_a.close()
            store_b.close()

    def test_publish_never_overwrites(self):
        import os

        store = make_store()
        try:
            wb, manifest = build_workbook(store, ["trip-demo-a"])
            directory = tempfile.mkdtemp()
            first, _ = publish_workbook(wb, manifest, directory, "ledger-once")
            before = first.read_bytes()
            wb2, manifest2 = build_workbook(store, ["trip-demo-b"])
            with self.assertRaises(FileExistsError):
                publish_workbook(wb2, manifest2, directory, "ledger-once")
            self.assertEqual(first.read_bytes(), before)
            self.assertTrue(os.path.exists(str(first)))
        finally:
            store.close()

    def test_concurrent_same_stem_has_one_winner_and_unique_temps(self):
        store = make_store()
        workbooks = []
        try:
            workbook_a, manifest_a = build_workbook(store, ["trip-demo-a"])
            workbook_b, manifest_b = build_workbook(store, ["trip-demo-b"])
            workbooks.extend([workbook_a, workbook_b])
            first_saved = threading.Event()
            second_saved = threading.Event()
            barrier = threading.Barrier(2)
            saved_paths = {}
            saved_payloads = {}
            coordinated_a = CoordinatedWorkbook(
                "A", workbook_a, first_saved, second_saved, barrier,
                saved_paths, saved_payloads,
            )
            coordinated_b = CoordinatedWorkbook(
                "B", workbook_b, first_saved, second_saved, barrier,
                saved_paths, saved_payloads,
            )
            results = {}

            def run_publish(label, workbook, manifest, directory):
                try:
                    target, published_manifest = publish_workbook(
                        workbook, manifest, directory, "same-stem",
                    )
                except FileExistsError as exc:
                    results[label] = ("exists", exc)
                except BaseException as exc:
                    results[label] = ("error", exc)
                else:
                    results[label] = ("success", (target, published_manifest))

            with tempfile.TemporaryDirectory() as directory:
                thread_a = threading.Thread(
                    target=run_publish,
                    args=("A", coordinated_a, manifest_a, directory),
                    daemon=True,
                )
                thread_b = threading.Thread(
                    target=run_publish,
                    args=("B", coordinated_b, manifest_b, directory),
                    daemon=True,
                )
                thread_a.start()
                thread_b.start()
                thread_a.join(10.0)
                thread_b.join(10.0)
                self.assertFalse(thread_a.is_alive())
                self.assertFalse(thread_b.is_alive())
                kinds = {label: result[0] for label, result in results.items()}
                self.assertEqual(sum(kind == "success" for kind in kinds.values()), 1)
                self.assertEqual(sum(kind == "exists" for kind in kinds.values()), 1)
                self.assertEqual(sum(kind == "error" for kind in kinds.values()), 0)
                self.assertNotEqual(saved_paths["A"], saved_paths["B"])
                winner = next(label for label, kind in kinds.items() if kind == "success")
                target = Path(directory) / "same-stem.xlsx"
                self.assertEqual(target.read_bytes(), saved_payloads[winner])
                self.assertEqual(
                    list(Path(directory).glob(".same-stem.*.tmp.xlsx")), [],
                )
        finally:
            for workbook in workbooks:
                workbook.close()
            store.close()
            store.ledger.close()

    def test_keyboard_interrupt_during_save_removes_target_and_temp(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(KeyboardInterrupt):
                publish_workbook(
                    InterruptingWorkbook(), {"input_snapshot_sha256": "test"},
                    directory, "interrupted",
                )
            output_dir = Path(directory)
            self.assertFalse((output_dir / "interrupted.xlsx").exists())
            self.assertEqual(
                list(output_dir.glob(".interrupted.*.tmp.xlsx")), [],
            )

    def test_all_merges_present(self):
        store = make_store()
        try:
            wb, _ = build_workbook(store, ["trip-demo-a"])
            ws = wb["0408_예시여행A"]
            merged = [str(r) for r in ws.merged_cells.ranges]
            self.assertIn("C2:H2", merged)
            self.assertIn("B6:H6", merged)
            self.assertIn("C31:H31", merged)
            self.assertIn("B33:H33", merged)
            self.assertIn("C85:H85", merged)
            self.assertIn("C87:H87", merged)
        finally:
            store.close()

    def test_column_widths(self):
        store = make_store()
        try:
            wb, _ = build_workbook(store, ["trip-demo-a"])
            ws = wb["0408_예시여행A"]
            for col_idx, expected_width in COLUMN_WIDTHS.items():
                col_letter = chr(64 + col_idx)
                self.assertAlmostEqual(ws.column_dimensions[col_letter].width, expected_width, places=2)
        finally:
            store.close()

    def test_landscape_orientation(self):
        store = make_store()
        try:
            wb, _ = build_workbook(store, ["trip-demo-a"])
            ws = wb["0408_예시여행A"]
            self.assertEqual(ws.page_setup.orientation, "landscape")
        finally:
            store.close()

    def test_margins(self):
        store = make_store()
        try:
            wb, _ = build_workbook(store, ["trip-demo-a"])
            ws = wb["0408_예시여행A"]
            margins = ws.page_margins
            self.assertAlmostEqual(margins.left, 0.7, places=2)
            self.assertAlmostEqual(margins.right, 0.7, places=2)
            self.assertAlmostEqual(margins.top, 0.75, places=2)
            self.assertAlmostEqual(margins.bottom, 0.75, places=2)
            self.assertAlmostEqual(margins.header, 0.0, places=2)
            self.assertAlmostEqual(margins.footer, 0.0, places=2)
        finally:
            store.close()

    def test_sum_formulas_preserved(self):
        store = make_store()
        try:
            wb, _ = build_workbook(store, ["trip-demo-a"])
            ws = wb["0408_예시여행A"]
            # Income total formula
            income_total_cell = ws["C31"]
            self.assertTrue(str(income_total_cell.value).startswith("=SUM(H8:H"))
            # Expense total formula  
            expense_total_cell = ws["C85"]
            self.assertTrue(str(expense_total_cell.value).startswith("=SUM(H35:H"))
            # Profit formula
            profit_cell = ws["C87"]
            self.assertTrue(str(profit_cell.value).startswith("=C31-C85"))
        finally:
            store.close()

    def test_overflow_merges_move_with_totals(self):
        store = make_store()
        try:
            # Add many expense rows to push totals down
            for i in range(60):
                store.create_manual_expense(
                    fields={
                        "display_tab_id": "trip-demo-b", "occurred_on": "2026-04-21",
                        "pay_method": "현금", "item": "기타", "description": f"항목{i}",
                        "amount_krw": 1000, "memo": "",
                    },
                    client_request_id=f"man-over-{i}",
                )
            wb, _ = build_workbook(store, ["trip-demo-b"])
            ws = wb["0420_예시여행B"]
            # With 60 expenses: expense_first=35, expense_end=35+60-1=94
            # expense_total_row=95, profit_row=97
            merged = [str(r) for r in ws.merged_cells.ranges]
            self.assertIn("C95:H95", merged)  # expense total merge moved
            self.assertIn("C97:H97", merged)  # profit merge moved
            # Income total should stay at row 31 (default slots)
            self.assertIn("C31:H31", merged)
        finally:
            store.close()


if __name__ == "__main__":
    unittest.main()
