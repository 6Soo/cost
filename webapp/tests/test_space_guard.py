"""Regression tests for SPEC_REFINEMENT 19.3: refusing writes on a full volume.

19.3 asks for a specific order (new files and new outputs first, row saving
last), a specific honesty (never a faked success, never a refusal reported as a
parse error), and a specific restraint (nothing already stored is deleted).

Each test drives the real write path with the free-space probe forced, because a
test that mocks the call site would pass whether or not the path asked.
"""
import json
import pathlib
import re
import shutil
import sqlite3
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[2]
import sys

sys.path.insert(0, str(ROOT))

from webapp import ops  # noqa: E402
from webapp import space_guard  # noqa: E402
from webapp.space_guard import SpaceRefused  # noqa: E402
from webapp.card_import import CardImporter  # noqa: E402
from webapp.ledger_store import LedgerStore, SaveError  # noqa: E402
from webapp.sheets_export import reserve_export_space  # noqa: E402

CARD_CSV = ("occurred_on,merchant,amount_krw,card_kind\n"
            "2026-04-09,Synthetic Cafe,-12000,K1\n")
MB = 1024 * 1024


class ForcedSpace:
    """Force the free-space probe for the duration of a block."""

    def __init__(self, free):
        self.free = free
        self.original = None

    def __enter__(self):
        self.original = space_guard.free_bytes
        space_guard.free_bytes = lambda path: self.free
        return self

    def __exit__(self, *exc):
        space_guard.free_bytes = self.original
        return False


class SpaceGuardTest(unittest.TestCase):
    def setUp(self):
        self.tmp = pathlib.Path(tempfile.mkdtemp(prefix="space-guard-"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.data = self.tmp / "data"
        for sub in ("", "exports", "evidence", "source"):
            (self.data / sub if sub else self.data).mkdir(parents=True,
                                                          exist_ok=True)
        self.db = self.data / "board.sqlite"
        self.store = LedgerStore(self.db)
        self.addCleanup(self.store.close)
        self.store.conn.execute(
            "INSERT INTO trip_tabs(tab_id, display_key) VALUES ('t1','Trip')")
        self.store.conn.execute(
            "INSERT INTO board_rows(row_id, row_kind, display_tab_id, revision,"
            " payload_json) VALUES ('r1','expense','t1',1,'{}')")
        self.store.conn.commit()
        self.config = ops.DurableConfig(
            data_root=self.data, db_path=self.db,
            export_dir=self.data / "exports",
            evidence_dir=self.data / "evidence",
            source_dir=self.data / "source",
            required_secrets=(), environment="local-synthetic")

    def revision(self):
        conn = sqlite3.connect(str(self.db))
        try:
            return conn.execute(
                "SELECT revision FROM board_rows WHERE row_id='r1'"
            ).fetchone()[0]
        finally:
            conn.close()

    # ------------------------------------------------------------ row saving
    def test_a_row_save_is_refused_rather_than_reported_as_successful(self):
        """19.3: 최소 여유 공간도 없으면 행 저장 역시 성공으로 위장하지 않고 거부."""
        with ForcedSpace(0):
            with self.assertRaises(SaveError) as caught:
                self.store.save(row_id="r1", expected_revision=1,
                                client_request_id="req-a",
                                change_mode="exception",
                                changes={"operator_note": "changed"})
        self.assertEqual(caught.exception.code, "SAVE_NO_SPACE")
        self.assertEqual(self.revision(), 1)

    def test_a_refused_save_records_no_request_as_done(self):
        with ForcedSpace(0):
            with self.assertRaises(SaveError):
                self.store.save(row_id="r1", expected_revision=1,
                                client_request_id="req-b",
                                change_mode="exception",
                                changes={"operator_note": "changed"})
        conn = sqlite3.connect(str(self.db))
        try:
            self.assertEqual(conn.execute(
                "SELECT COUNT(*) FROM board_requests").fetchone()[0], 0)
        finally:
            conn.close()

    def test_a_completed_request_still_replays_on_a_full_volume(self):
        """A stored result performs no write, so refusing it would report a
        finished request as a new failure. This is the one case where a full
        volume must not stop the save path."""
        with ForcedSpace(50 * MB):
            first = self.store.save(row_id="r1", expected_revision=1,
                                    client_request_id="req-c",
                                    change_mode="exception",
                                    changes={"operator_note": "first"})
        with ForcedSpace(0):
            replay = self.store.save(row_id="r1", expected_revision=1,
                                     client_request_id="req-c",
                                     change_mode="exception",
                                     changes={"operator_note": "first"})
        self.assertEqual(replay["revision"], first["revision"])

    def test_a_save_works_again_once_there_is_room(self):
        with ForcedSpace(50 * MB):
            result = self.store.save(row_id="r1", expected_revision=1,
                                     client_request_id="req-d",
                                     change_mode="exception",
                                     changes={"operator_note": "kept"})
        self.assertEqual(result["revision"], 2)
        self.assertEqual(self.revision(), 2)

    # --------------------------------------------------------- file acceptance
    def test_a_card_file_is_refused_before_any_batch_row_exists(self):
        """19.3: 아직 받지 못한 파일을 접수 완료로 기록하지 않는다."""
        importer = CardImporter(self.store.conn, self.store)
        with ForcedSpace(0):
            with self.assertRaises(space_guard.SpaceRefused) as caught:
                importer.receive(CARD_CSV.encode("utf-8"), "cards.csv")
        self.assertEqual(caught.exception.code, "IMPORT_NO_SPACE")
        conn = sqlite3.connect(str(self.db))
        try:
            self.assertEqual(conn.execute(
                "SELECT COUNT(*) FROM card_import_batches").fetchone()[0], 0)
            self.assertEqual(conn.execute(
                "SELECT COUNT(*) FROM source_blobs").fetchone()[0], 0)
        finally:
            conn.close()

    def test_a_refused_upload_is_not_reported_as_a_parse_error(self):
        """19.3: 파싱 오류처럼 표시하지 않는다. The refusal carries its own code."""
        importer = CardImporter(self.store.conn, self.store)
        with ForcedSpace(0):
            with self.assertRaises(space_guard.SpaceRefused) as caught:
                importer.receive(CARD_CSV.encode("utf-8"), "cards.csv")
        self.assertNotIn("PARSE", caught.exception.code)

    def test_the_same_file_is_accepted_once_there_is_room(self):
        importer = CardImporter(self.store.conn, self.store)
        with ForcedSpace(50 * MB):
            result = importer.receive(CARD_CSV.encode("utf-8"), "cards.csv")
        self.assertTrue(result["batch_id"].startswith("imp-"))

    def test_a_stored_file_is_answered_from_its_batch_even_when_full(self):
        """Re-uploading a file that is already stored needs no new space."""
        importer = CardImporter(self.store.conn, self.store)
        with ForcedSpace(50 * MB):
            importer.receive(CARD_CSV.encode("utf-8"), "cards.csv")
        with ForcedSpace(0):
            again = importer.receive(CARD_CSV.encode("utf-8"), "cards.csv")
        self.assertTrue(again["reused"])

    # ------------------------------------------------------------------ output
    def test_a_new_output_is_refused_when_the_volume_cannot_hold_it(self):
        with ForcedSpace(0):
            with self.assertRaises(space_guard.SpaceRefused) as caught:
                reserve_export_space(self.data / "exports",
                                      {"tabs": [{"row_count": 5000}]})
        self.assertEqual(caught.exception.code, "EXPORT_NO_SPACE")

    def test_a_refusal_deletes_no_existing_output(self):
        existing = self.data / "exports" / "earlier.xlsx"
        existing.write_bytes(b"an earlier output")
        with ForcedSpace(0):
            with self.assertRaises(space_guard.SpaceRefused):
                reserve_export_space(self.data / "exports",
                                      {"tabs": [{"row_count": 5000}]})
        self.assertTrue(existing.is_file())
        self.assertEqual(existing.read_bytes(), b"an earlier output")

    def test_an_output_is_refused_before_a_temp_file_is_created(self):
        """19.3: 실패한 출력의 임시 파일만 정리한다. Nothing is created at all
        when the volume cannot take the output, so there is nothing to clean."""
        out = self.data / "exports"
        with ForcedSpace(0):
            with self.assertRaises(space_guard.SpaceRefused):
                reserve_export_space(out, {"tabs": [{"row_count": 5000}]})
        self.assertEqual(list(out.iterdir()), [])

    def test_publish_workbook_itself_refuses_and_leaves_nothing_behind(self):
        """The reserve helper is not the output path. This drives the real
        `publish_workbook`, because a refusal placed after the temp file is
        made would still refuse and still leave the caller to clean up."""
        from openpyxl import Workbook
        from webapp.sheets_export import publish_workbook

        out = self.data / "exports"
        out.mkdir(parents=True, exist_ok=True)
        wb = Workbook()
        wb.active["A1"] = "행"
        with ForcedSpace(0):
            with self.assertRaises(space_guard.SpaceRefused):
                publish_workbook(wb, {"tabs": [{"row_count": 5000}]}, out,
                                 "blocked")
        self.assertEqual(list(out.iterdir()),
                         [], "a refused output must leave no temp and no file")

    def test_publish_workbook_still_publishes_when_there_is_room(self):
        from openpyxl import Workbook
        from webapp.sheets_export import publish_workbook

        out = self.data / "exports"
        out.mkdir(parents=True, exist_ok=True)
        wb = Workbook()
        wb.active["A1"] = "행"
        with ForcedSpace(50 * MB):
            target, manifest = publish_workbook(
                wb, {"tabs": [{"row_count": 1}]}, out, "allowed")
        self.assertTrue(target.is_file())
        self.assertEqual(len(manifest["output_sha256"]), 64)

    def test_publish_workbook_cleans_only_its_own_temp_on_a_write_failure(self):
        """19.3: 실패한 출력의 임시 파일만 정리하며 과거 산출물을 자동 삭제하지
        않는다. A workbook that cannot be saved must not take earlier outputs
        with it, and must not leave its temp file behind."""
        from openpyxl import Workbook
        from webapp.sheets_export import publish_workbook

        out = self.data / "exports"
        out.mkdir(parents=True, exist_ok=True)
        earlier = out / "earlier.xlsx"
        earlier.write_bytes(b"an earlier output")

        class Broken:
            def save(self, path):
                raise RuntimeError("the workbook could not be written")

        with ForcedSpace(50 * MB):
            with self.assertRaises(RuntimeError):
                publish_workbook(Broken(), {"tabs": [{"row_count": 1}]}, out,
                                 "broken")
        self.assertTrue(earlier.is_file())
        self.assertEqual(sorted(p.name for p in out.iterdir()),
                         ["earlier.xlsx"])

    # ------------------------------------------------------------- headroom
    def test_the_health_line_and_the_guard_read_the_same_number(self):
        """One threshold, one function. A health line that measured separately
        could report ok while a write was already being refused."""
        self.assertIs(ops.MIN_FREE_BYTES, space_guard.MIN_FREE_BYTES)
        with ForcedSpace(2 * MB):
            measured = ops._free_bytes(self.data)
            state = space_guard.state(self.data, needed_bytes=0)
        self.assertEqual(measured, 2 * MB)
        self.assertEqual(state["free_bytes"], measured)

    def test_health_warns_before_writes_start_being_refused(self):
        """19.3: 공간 부족 전에 경고한다. The warning is not fatal."""
        with ForcedSpace(5 * MB):
            low = {c["check"]: c for c in ops.health_check(
                self.config)["checks"]}
        with ForcedSpace(500 * MB):
            high = {c["check"]: c for c in ops.health_check(
                self.config)["checks"]}
        self.assertFalse(low["free_space_headroom"]["ok"])
        self.assertFalse(low["free_space_headroom"]["fatal"])
        self.assertTrue(low["free_space"]["ok"],
                        "5MB is still above the refusal threshold")
        self.assertTrue(high["free_space_headroom"]["ok"])

    def test_an_unreadable_volume_refuses_rather_than_assuming_room(self):
        """19.3 asks for a refusal rather than a faked success.

        The first version reported an unreadable `disk_usage` as `can_write`,
        while `ops.health_check` reported the same situation as a *failed*
        check. One surface said the volume was fine and the other said it was
        broken. Both now refuse, and the refusal says the number could not be
        read instead of inventing one.
        """
        with ForcedSpace(None):
            state = space_guard.state(self.data, needed_bytes=0)
        self.assertIsNone(state["free_bytes"])
        self.assertFalse(state["can_write"])
        self.assertEqual(state["reason"], "space_unreadable")
        with ForcedSpace(None):
            with self.assertRaises(space_guard.SpaceRefused) as caught:
                space_guard.reserve(self.data, 1, code="X", what="테스트")
        self.assertEqual(caught.exception.reason, "space_unreadable")

    def test_ops_health_and_the_guard_refuse_on_the_same_condition(self):
        """One condition, one policy. This is the pair that disagreed."""
        from webapp import ops as _ops
        with ForcedSpace(None):
            health = _ops.health_check(self.config)
            measured = space_guard.state(self.data, needed_bytes=0)
        free_check = {c["check"]: c for c in health["checks"]}["free_space"]
        self.assertFalse(free_check["ok"], "health must fail when space is unreadable")
        self.assertFalse(measured["can_write"], "the guard must refuse the same case")

    def test_the_guard_never_deletes_anything(self):
        with ForcedSpace(0):
            for call in (lambda: self.store.save(
                             row_id="r1", expected_revision=1,
                             client_request_id="req-e", change_mode="exception",
                             changes={"operator_note": "x"}),
                         lambda: reserve_export_space(
                             self.data / "exports",
                             {"tabs": [{"row_count": 1}]})):
                with self.assertRaises((SaveError, space_guard.SpaceRefused)):
                    call()
        self.assertTrue(self.db.is_file())
        self.assertEqual(self.revision(), 1)


class WritePathCoverageTest(unittest.TestCase):
    """Every public state-changing path must pass the low-space policy.

    The first version guarded `save` and 47 other public methods wrote to the
    same database with no check at all. A per-method call site invites the next
    omission, so this audits the source instead: a new write method is either
    routed through the guarded choke point or named here as read-only. Adding a
    write method without one of those two things fails the suite.
    """

    #: `INSERT INTO` / `UPDATE ... SET`, not a bare keyword. A plain
    #: `\bUPDATE\b` matched `board_row.update(...)` and the string
    #: `"updated_at"`, which is how `conversation_state` came to look like a
    #: writer. The audit has to be wrong in the safe direction, so it now asks
    #: for SQL shape.
    WRITE_SQL = re.compile(r"\bINSERT\s+INTO\b|\bUPDATE\s+\w+\s+SET\b|"
                           r"executescript\(", re.I)

    #: Public methods that only read. Each one has a reason, not a default.
    READ_ONLY = {
        "conversation_state": "reads the conversation, writes nothing",
        "preview_rule": "previews an impact set; the apply path writes",
        "get_job": "reads one export job",
        "list_jobs": "lists export jobs",
        "ensure_schema": "creates tables; guarding it could brick a database "
                         "that is exactly the one that needs them",
    }

    def public_writes(self, rel, class_name):
        import ast
        source = (ROOT / rel).read_text(encoding="utf-8")
        tree = ast.parse(source)
        found = {}
        for node in tree.body:
            if not isinstance(node, ast.ClassDef) or node.name != class_name:
                continue
            for m in node.body:
                if not isinstance(m, ast.FunctionDef):
                    continue
                if m.name.startswith("_"):
                    continue
                seg = ast.get_source_segment(source, m) or ""
                if not self.WRITE_SQL.search(seg):
                    continue
                guarded = ("_begin_write" in seg or "reserve_" in seg
                           or "space_guard" in seg)
                found[m.name] = guarded
        return found

    def test_every_ledger_store_write_path_is_guarded_or_declared_read_only(self):
        found = self.public_writes("webapp/ledger_store.py", "LedgerStore")
        self.assertGreater(len(found), 20,
                           "the audit found suspiciously few write methods; "
                           "if the shape of the file changed, update this")
        unguarded = sorted(name for name, ok in found.items() if not ok)
        self.assertEqual(
            unguarded, [],
            f"these public methods write without the low-space policy: "
            f"{unguarded}. Route them through _begin_write(), or add them to "
            f"READ_ONLY with a reason.")

    def test_the_read_only_allow_list_is_not_stale(self):
        """An entry that no longer writes is a hole in the audit, not a spare."""
        found = self.public_writes("webapp/ledger_store.py", "LedgerStore")
        for name in self.READ_ONLY:
            if name in found:
                self.fail(f"{name} is listed as read-only but writes; move it to "
                          f"the guarded set or explain the change")

    def test_record_conflict_is_guarded(self):
        """It keeps its own transaction, so it must call the choke point itself."""
        source = (ROOT / "webapp/ledger_store.py").read_text(encoding="utf-8")
        start = source.index("    def record_conflict(")
        end = source.index("\n    def ", start + 10)
        body = source[start:end]
        self.assertTrue(
            "_begin_write" in body or "reserve_write" in body
            or "reserve_conn" in body,
            "record_conflict appends a revision row in its own transaction and "
            "so has to reserve for it explicitly")

    def test_the_export_job_record_is_guarded(self):
        source = (ROOT / "webapp/sheets_export.py").read_text(encoding="utf-8")
        start = source.index("def record_job(")
        end = source.index("\ndef ", start + 10)
        self.assertTrue("reserve" in source[start:end],
                        "record_job writes a row and needs the policy")

    def test_card_import_worker_paths_are_guarded(self):
        """`process` and `finish` write rows after the file was accepted."""
        source = (ROOT / "webapp/card_import.py").read_text(encoding="utf-8")
        for name in ("process", "finish"):
            start = source.index(f"    def {name}(")
            end = source.index("\n    def ", start + 10)
            body = source[start:end]
            self.assertTrue("reserve" in body,
                            f"CardImporter.{name} writes without the policy")


class ExportEstimateIsBuiltFromTheRealManifest(unittest.TestCase):
    """The estimate has to read the manifest `build_workbook` really produces."""

    def setUp(self):
        self.tmp = pathlib.Path(tempfile.mkdtemp(prefix="estimate-"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)

    def real_manifest(self, tabs, income=0, expense=0):
        """A manifest with exactly the keys `_build_workbook_snapshot` writes."""
        from webapp import sheets_export as se
        return {
            "template_version": se.TEMPLATE_VERSION,
            "tab_order": [f"t{i}" for i in range(tabs)],
            "tabs": [{"tab_id": f"t{i}", "sheet_name": f"T{i}",
                      "income_rows": income, "expense_rows": expense,
                      "prepared_on": "", "prepared_by_name": ""}
                     for i in range(tabs)],
            "input_snapshot_sha256": "0" * 64, "created_at": "2026-09-29T00:00:00+00:00",
        }

    def test_a_real_manifest_is_not_read_as_zero_rows(self):
        """The defect: the estimate read `row_count`/`rows`, which no real
        manifest has, so a real export asked for the base cost only."""
        from webapp import sheets_export as se
        manifest = self.real_manifest(4, income=200, expense=90)
        estimate = se.export_size_estimate(manifest)
        self.assertEqual(estimate["sheets"], 4)
        # The counts are per tab, as `_build_workbook_snapshot` writes them.
        self.assertEqual(estimate["rows"], 4 * (200 + 90))
        self.assertTrue(estimate["shape_known"])
        empty = se.export_size_estimate(self.real_manifest(4))
        self.assertGreater(
            estimate["bytes"], empty["bytes"],
            "290 rows across 4 sheets must cost more than 4 empty sheets; the "
            "old key set made these two identical")

    def test_the_estimate_grows_with_rows_and_with_sheets(self):
        from webapp import sheets_export as se
        one = se.export_size_estimate(self.real_manifest(1))
        many_sheets = se.export_size_estimate(self.real_manifest(20))
        many_rows = se.export_size_estimate(self.real_manifest(1, expense=5000))
        self.assertGreater(many_sheets["bytes"], one["bytes"])
        self.assertGreater(many_rows["bytes"], one["bytes"])

    def test_an_unknown_manifest_shape_is_not_treated_as_small(self):
        from webapp import sheets_export as se
        unknown = se.export_size_estimate({"template_version": "x"})
        self.assertIsNone(unknown["bytes"])
        self.assertFalse(unknown["shape_known"])
        # The wrapper must still reserve something, and something large.
        with ForcedSpace(50 * MB):
            estimate = se.reserve_export_space(self.tmp, {"nope": 1})
        self.assertGreaterEqual(estimate["bytes"],
                                se.EXPORT_BASE_BYTES)

    def test_a_tab_without_row_counts_is_flagged_not_assumed_empty(self):
        from webapp import sheets_export as se
        manifest = {"tabs": [{"tab_id": "t", "sheet_name": "T"}]}
        estimate = se.export_size_estimate(manifest)
        self.assertEqual(estimate["sheets"], 1)
        self.assertFalse(estimate["shape_known"])
        self.assertTrue(estimate["note"])

    def test_the_estimate_is_never_smaller_than_a_real_file(self):
        """P1-6: compare the estimate against real published bytes."""
        from webapp import sheets_export as se
        from webapp.ledger_store import LedgerStore

        for tabs, expense in ((1, 0), (1, 40), (6, 40), (12, 120)):
            db = self.tmp / f"e{tabs}_{expense}.sqlite"
            store = LedgerStore(db, seed_demo=False)
            ids = []
            for t in range(tabs):
                tab = f"t{t:02}"
                ids.append(tab)
                store.conn.execute(
                    "INSERT INTO trip_tabs(tab_id, display_key) VALUES (?,?)",
                    (tab, f"Sheet {t}"))
                for i in range(expense):
                    store.conn.execute(
                        "INSERT INTO board_rows(row_id, row_kind,"
                        " display_tab_id, revision, payload_json)"
                        " VALUES (?,?,?,1,?)",
                        (f"{tab}-e{i}", "expense", tab,
                         json.dumps({"row_id": f"{tab}-e{i}",
                                     "row_kind": "expense",
                                     "display_tab_id": tab,
                                     "amount_krw": -1000 - i,
                                     "item": f"Item {i}",
                                     "occurred_on": "2026-04-09",
                                     "source_kind": "카드"},
                                    ensure_ascii=False)))
            store.conn.commit()
            wb, manifest = se.build_workbook(store, ids)
            estimate = se.export_size_estimate(manifest)
            stem = f"x{tabs}_{expense}"
            se.publish_workbook(wb, manifest, self.tmp, stem)
            real = (self.tmp / f"{stem}.xlsx").stat().st_size
            store.close()
            with self.subTest(tabs=tabs, expense=expense):
                self.assertGreaterEqual(
                    estimate["bytes"], real,
                    f"the estimate ({estimate['bytes']:,}) is below the real "
                    f"file ({real:,}); a low estimate lets a write through")


class ExportDirectoryIsCreatedAfterTheCheck(unittest.TestCase):
    """P1-3: a full volume makes `mkdir` fail with an error that says nothing."""

    def setUp(self):
        self.tmp = pathlib.Path(tempfile.mkdtemp(prefix="mkdir-"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        from openpyxl import Workbook
        self.wb = Workbook()
        self.wb.active["A1"] = "row"
        self.manifest = {"tabs": [{"tab_id": "t", "sheet_name": "T",
                                   "income_rows": 1, "expense_rows": 1,
                                   "prepared_on": "", "prepared_by_name": ""}],
                         "template_version": "t", "tab_order": ["t"],
                         "input_snapshot_sha256": "0" * 64,
                         "created_at": "2026-09-29T00:00:00+00:00"}

    def test_a_refusal_on_a_full_volume_creates_no_directory(self):
        from webapp import sheets_export as se
        out = self.tmp / "not-created"
        with ForcedSpace(0):
            with self.assertRaises(space_guard.SpaceRefused):
                se.publish_workbook(self.wb, self.manifest, out, "blocked")
        self.assertFalse(out.exists(),
                         "mkdir ran before the space check, so a full volume "
                         "left a half-created directory behind")

    def test_the_refusal_comes_from_the_check_not_from_mkdir(self):
        """mkdir on a full volume raises a bare OSError. The code has to be the
        guard's, so an operator is told about space rather than about a path."""
        from webapp import sheets_export as se
        out = self.tmp / "not-created-either"
        with ForcedSpace(0):
            with self.assertRaises(space_guard.SpaceRefused) as caught:
                se.publish_workbook(self.wb, self.manifest, out, "blocked")
        self.assertEqual(caught.exception.code, "EXPORT_NO_SPACE")
        self.assertEqual(caught.exception.reason, "insufficient_space")

    def test_an_existing_directory_still_publishes(self):
        from webapp import sheets_export as se
        out = self.tmp / "exists"
        out.mkdir(parents=True, exist_ok=True)
        with ForcedSpace(50 * MB):
            target, manifest = se.publish_workbook(self.wb, self.manifest, out,
                                                   "ok")
        self.assertTrue(target.is_file())


class ThresholdAndBoundaryBehaviour(unittest.TestCase):
    """P1-5/P1-7: one threshold, exact edges, validated sizes."""

    def setUp(self):
        self.tmp = pathlib.Path(tempfile.mkdtemp(prefix="edges-"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        space_guard.reset_probe_cache()

    def tearDown(self):
        space_guard.reset_probe_cache()

    def test_the_exact_threshold_boundary(self):
        need = 1024
        with ForcedSpace(space_guard.MIN_FREE_BYTES + need):
            self.assertTrue(space_guard.state(self.tmp,
                                              needed_bytes=need)["can_write"])
        space_guard.reset_probe_cache()
        with ForcedSpace(space_guard.MIN_FREE_BYTES + need - 1):
            self.assertFalse(space_guard.state(self.tmp,
                                               needed_bytes=need)["can_write"])

    def test_the_warning_boundary_is_defined_in_one_place(self):
        """The old code warned at 11 MiB in health and 10 MiB in the guard."""
        need = 0
        with ForcedSpace(space_guard.WARN_FREE_BYTES + need):
            self.assertFalse(space_guard.state(self.tmp,
                                              needed_bytes=need)["warn"])
        space_guard.reset_probe_cache()
        with ForcedSpace(space_guard.WARN_FREE_BYTES + need - 1):
            self.assertTrue(space_guard.state(self.tmp,
                                             needed_bytes=need)["warn"])

    def test_a_negative_or_non_integer_need_is_refused(self):
        for bad in (-1, -1024, True, False, "1024", 1.5, None):
            with self.subTest(needed=bad):
                with self.assertRaises(ValueError):
                    space_guard.state(self.tmp, needed_bytes=bad)
                with self.assertRaises(ValueError):
                    space_guard.reserve(self.tmp, bad, code="X", what="테스트")

    def test_a_negative_need_does_not_make_a_full_volume_look_roomy(self):
        """The reason for the validation, stated as a check."""
        with ForcedSpace(space_guard.MIN_FREE_BYTES + 10):
            self.assertTrue(space_guard.state(self.tmp,
                                              needed_bytes=0)["can_write"])
        with ForcedSpace(0):
            with self.assertRaises(space_guard.SpaceRefused):
                space_guard.reserve(self.tmp, 0, code="X", what="테스트")


class ContentionAndRetryBehaviour(unittest.TestCase):
    """P1-7: no overcommit, and no syscall storm from a retry loop."""

    def setUp(self):
        self.tmp = pathlib.Path(tempfile.mkdtemp(prefix="race-"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        space_guard.reset_probe_cache()

    def tearDown(self):
        space_guard.reset_probe_cache()

    def test_two_writers_do_not_both_spend_the_same_free_bytes(self):
        """Each writer sees the other's outstanding reservation."""
        free = 3 * space_guard.MIN_FREE_BYTES
        with ForcedSpace(free):
            with space_guard.reserve_write(self.tmp,
                                           2 * space_guard.MIN_FREE_BYTES,
                                           code="A",
                                           what="첫 번째") as first:
                self.assertTrue(first["can_write"])
                with self.assertRaises(space_guard.SpaceRefused):
                    with space_guard.reserve_write(
                            self.tmp, 2 * space_guard.MIN_FREE_BYTES,
                            code="B", what="두 번째"):
                        pass
            # The first writer has finished, so the space is available again.
            with space_guard.reserve_write(self.tmp,
                                           2 * space_guard.MIN_FREE_BYTES,
                                           code="C",
                                           what="세 번째") as third:
                self.assertTrue(third["can_write"],
                                "the reservation was not released when the "
                                "write ended")

    def test_a_reservation_is_released_even_when_the_write_raises(self):
        with ForcedSpace(2 * space_guard.MIN_FREE_BYTES):
            with self.assertRaises(RuntimeError):
                with space_guard.reserve_write(self.tmp,
                                               space_guard.MIN_FREE_BYTES,
                                               code="A", what="실패할 쓰기"):
                    raise RuntimeError("the write failed")
            measured = space_guard.state(self.tmp, needed_bytes=0)
            self.assertEqual(measured["reserved_bytes"], 0,
                             "a failed write kept its reservation and would "
                             "shrink the volume for everyone else")

    def test_repeated_checks_do_not_stat_every_time(self):
        """A busy server must not turn every write into a disk_usage call."""
        calls = []
        original = space_guard.free_bytes
        space_guard.free_bytes = lambda p: (calls.append(1),
                                            original(p))[1]
        try:
            # Far above the threshold, so the answer may be reused.
            with ForcedSpace(500 * MB):
                space_guard.reset_probe_cache()
                for _ in range(50):
                    space_guard.state(self.tmp, needed_bytes=0)
            first_round = len(calls)
            self.assertLess(first_round, 25,
                            f"{first_round} probes for 50 checks far from the "
                            f"threshold; the cache is not working")
        finally:
            space_guard.free_bytes = original

    def test_near_the_threshold_every_check_re_probes(self):
        """The cache window must never let a write through a filling volume.

        The reading is inside the warn band, which is exactly the region where a
        stale number would turn a refusal into a half-written file.
        """
        original = space_guard.free_bytes
        band = space_guard.WARN_FREE_BYTES // 2
        readings = iter([band, 0])
        space_guard.free_bytes = lambda p: next(readings, 0)
        try:
            space_guard.reset_probe_cache()
            first = space_guard.state(self.tmp, needed_bytes=0)
            self.assertTrue(first["can_write"])
            self.assertFalse(first["cached"],
                             "a value inside the warn band must not be cached")
            second = space_guard.state(self.tmp, needed_bytes=0)
            self.assertFalse(second["can_write"],
                             "the volume filled up and the check reused the "
                             "old number")
        finally:
            space_guard.free_bytes = original


class BypassPathsAreActuallyRefused(unittest.TestCase):
    """The choke point has to refuse the real paths, not just be present.

    The coverage audit proves every method calls the guard. These tests drive the
    actual methods on a full volume, because a guard in the source and a guard
    on the path are different claims.
    """

    def setUp(self):
        self.tmp = pathlib.Path(tempfile.mkdtemp(prefix="bypass-"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        space_guard.reset_probe_cache()
        self.db = self.tmp / "board.sqlite"
        self.store = LedgerStore(self.db)
        self.addCleanup(self.store.close)
        self.store.conn.execute(
            "INSERT INTO trip_tabs(tab_id, display_key) VALUES ('t1','Trip A')")
        self.store.conn.execute(
            "INSERT INTO board_rows(row_id, row_kind, display_tab_id, revision,"
            " payload_json) VALUES ('r1','expense','t1',1,'{}')")
        self.store.conn.commit()

    def tearDown(self):
        space_guard.reset_probe_cache()

    def assert_refused(self, call, label):
        before = self.db.read_bytes()
        with ForcedSpace(0):
            with self.assertRaises(SpaceRefused, msg=label):
                call()
        self.assertEqual(before, self.db.read_bytes(),
                         f"{label} wrote to the database on a full volume")

    def test_import_row_is_refused(self):
        self.assert_refused(
            lambda: self.store.import_row(
                row_id="r-imported",
                fields={"display_tab_id": "t1",
                        "occurred_on": "2026-04-09", "amount_krw": -1000,
                        "item": "Item", "description": "", "memo": "",
                        "service_period": "", "reservation_no": "",
                        "evidence_type": "카드", "source_event_id": "SRC-1",
                        "source_kind": "카드", "event_kind": "purchase"},
                batch_id="b1", client_request_id="imp-1", actor="owner"),
            "import_row")

    def test_create_direct_income_is_refused(self):
        self.assert_refused(
            lambda: self.store.create_direct_income(
                fields={"display_tab_id": "t1",
                        "customer_name": "Synthetic Co",
                        "occurred_on": "2026-04-09", "amount_krw": 1000,
                        "income_kind": "deposit", "nickname": ""},
                client_request_id="inc-1", actor="owner"),
            "create_direct_income")

    def test_create_manual_expense_is_refused(self):
        self.assert_refused(
            lambda: self.store.create_manual_expense(
                fields={"display_tab_id": "t1",
                        "occurred_on": "2026-04-09", "amount_krw": -1000,
                        "item": "Item", "pay_method": "현금"},
                client_request_id="exp-1", actor="owner"),
            "create_manual_expense")

    def test_save_trip_meta_is_refused(self):
        self.assert_refused(
            lambda: self.store.save_trip_meta(
                tab_id="t1", expected_revision=1,
                client_request_id="tab-1", display_key="Renamed",
                actor="owner"),
            "save_trip_meta")

    def test_create_trip_is_refused(self):
        self.assert_refused(
            lambda: self.store.create_trip(
                starts_on="2026-05-01", destination="Synthetic",
                display_key="New Trip", client_request_id="trip-1",
                actor="owner"),
            "create_trip")

    def test_record_conflict_is_refused(self):
        self.assert_refused(
            lambda: self.store.record_conflict(
                row_id="r1", expected_revision=99,
                attempted={"display_tab_id": "t1"}, client_request_id="c-1"),
            "record_conflict")

    def test_revert_row_is_refused(self):
        """Revert needs a row that actually has something to revert."""
        with ForcedSpace(50 * MB):
            self.store.save(row_id="r1", expected_revision=1,
                            client_request_id="seed-1", change_mode="exception",
                            changes={"operator_note": "first"})
        self.assert_refused(
            lambda: self.store.revert_row(
                row_id="r1", expected_revision=2,
                client_request_id="rev-1", actor="owner"),
            "revert_row")

    def test_the_export_job_row_is_refused(self):
        from webapp import sheets_export as se
        before = self.db.read_bytes()
        with ForcedSpace(0):
            with self.assertRaises(SpaceRefused):
                se.record_job(self.store.conn, job_id="j1", tab_ids=["t1"],
                              manifest={"template_version": "t",
                                        "input_snapshot_sha256": "0" * 64},
                              status="started")
        self.assertEqual(before, self.db.read_bytes(),
                         "record_job wrote to the database on a full volume")

    def test_the_import_summary_is_refused(self):
        from webapp.card_import import CardImporter
        importer = CardImporter(self.store.conn, self.store)
        with ForcedSpace(50 * MB):
            importer.receive(CARD_CSV.encode("utf-8"), "cards.csv")
        batch = self.store.conn.execute(
            "SELECT batch_id FROM card_import_batches").fetchone()[0]
        with ForcedSpace(0):
            with self.assertRaises(SpaceRefused):
                importer.finish(batch)
        status = self.store.conn.execute(
            "SELECT status FROM card_import_batches WHERE batch_id=?",
            (batch,)).fetchone()[0]
        self.assertNotIn("completed", status,
                         "the import was recorded as finished on a full volume")

    def test_a_ledger_write_still_succeeds_once_there_is_room(self):
        """The guard must not simply refuse everything."""
        with ForcedSpace(50 * MB):
            result = self.store.save(row_id="r1", expected_revision=1,
                                     client_request_id="ok-1",
                                     change_mode="exception",
                                     changes={"operator_note": "kept"})
        self.assertEqual(result["revision"], 2)

    def test_each_write_path_asks_for_its_own_declared_size(self):
        """A size of zero passes a test that only ever fills the volume to zero.

        On a completely full volume even a zero-byte need is refused, so asking
        for nothing still looks correct. The declared sizes are therefore pinned
        at the exact edge: one byte short of the need is refused, the need
        itself is allowed. That is what makes the number itself matter.
        """
        from webapp.ledger_store import SaveError

        need = space_guard.WRITE_BYTES
        call = (lambda: self.store.save(row_id="r1", expected_revision=1,
                                        client_request_id="sz-1",
                                        change_mode="exception",
                                        changes={"operator_note": "x"}))
        space_guard.reset_probe_cache()
        with ForcedSpace(space_guard.MIN_FREE_BYTES + need - 1):
            # `save` carries the refusal in its own error shape, so both are
            # accepted here; the requirement is that it does not succeed.
            with self.assertRaises((SpaceRefused, SaveError)):
                call()
        space_guard.reset_probe_cache()
        with ForcedSpace(space_guard.MIN_FREE_BYTES + need):
            call()

    def test_the_import_summary_needs_its_declared_bytes(self):
        from webapp.card_import import CardImporter
        from webapp.space_guard import WRITE_BYTES as _W
        importer = CardImporter(self.store.conn, self.store)
        with ForcedSpace(50 * MB):
            importer.receive(CARD_CSV.encode("utf-8"), "cards.csv")
        batch = self.store.conn.execute(
            "SELECT batch_id FROM card_import_batches").fetchone()[0]
        from webapp import card_import as ci
        need = ci.IMPORT_SUMMARY_BYTES
        self.assertGreater(need, 0, "a declared size of zero cannot be pinned")
        space_guard.reset_probe_cache()
        with ForcedSpace(space_guard.MIN_FREE_BYTES + need - 1):
            with self.assertRaises(SpaceRefused):
                importer.finish(batch)
        space_guard.reset_probe_cache()
        with ForcedSpace(space_guard.MIN_FREE_BYTES + need):
            result = importer.finish(batch)
        self.assertIn(result["status"], ("completed", "completed_with_issues",
                                         "reconciling"))


if __name__ == "__main__":
    unittest.main()
