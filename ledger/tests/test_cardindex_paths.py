import os
import shutil
import sqlite3
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

from openpyxl import Workbook

from ledger import cardindex
from ledger.domain import direct_projection, direct_sources
from ledger.domain.ledger_db import initialize


def _book(path, rows):
    wb = Workbook()
    try:
        ws = wb.active
        for row in rows:
            ws.append(row)
        wb.save(path)
    finally:
        wb.close()


def _root(marker="shop"):
    root = Path(tempfile.mkdtemp())
    conv = root / "newcard" / "conv"
    conv.mkdir(parents=True)
    f = ["x"] * 17
    f[0] = "2026-07-01"; f[1] = "2026-07-01"; f[5] = "1234"
    f[7] = marker; f[8] = "food"; f[11] = "100"; f[12] = "0"; f[15] = "1"; f[16] = "ok"
    e = ["x"] * 17
    e[0] = "2026-07-01"; e[1] = "2026-07-01"; e[4] = "1234"; e[7] = marker
    e[10] = "JPY"; e[11] = "10"; e[16] = "100"
    g = ["x"] * 20
    g[0] = "ok"; g[1] = "2026-07-01"; g[3] = "1234"; g[4] = "2"; g[5] = "100"; g[6] = "0"
    g[7] = marker; g[8] = "food"; g[14] = "100"; g[16] = "2026-07-01"
    g[17] = "ok"; g[18] = "0"
    han_header = ["h"] * 20
    han_header[5] = "승인금액"; han_header[6] = "승인취소금액"; han_header[14] = "매입금액"
    a = ["purchase", "domestic", "2026-07-01", "1234", "x", marker, "100",
         "KRW", "x", "x", "x", "x", "x", "1"]
    _book(conv / "F.xlsx", [["h"] * 17, f])
    _book(conv / "E.xlsx", [["h"] * 17, e])
    _book(conv / "G.xlsx", [["h"] * 20] * 5 + [han_header, g])
    _book(conv / "H.xlsx", [["h"] * 20] * 5 + [han_header, g])
    _book(conv / "A_20260720.xlsx", [a])
    return root


class CardIndexPathTests(unittest.TestCase):
    def test_load_closes_fake_workbook_once_after_materializing(self):
        rows = [["header"], ["value"]]

        class FakeSheet:
            def iter_rows(self, values_only=False):
                return iter(rows)

        class FakeWorkbook:
            sheetnames = ["Sheet1"]

            def __init__(self):
                self.closed = 0

            def __getitem__(self, name):
                return FakeSheet()

            def close(self):
                self.closed += 1

        workbook = FakeWorkbook()
        with patch("ledger.cardindex.openpyxl.load_workbook", return_value=workbook):
            self.assertEqual(cardindex.load("F", ledger_dir=Path("/synthetic")), rows)
        self.assertEqual(workbook.closed, 1)

    def test_load_closes_fake_workbook_once_on_iteration_error(self):
        class FakeSheet:
            def iter_rows(self, values_only=False):
                raise RuntimeError("sentinel iteration failure")

        class FakeWorkbook:
            sheetnames = ["Sheet1"]

            def __init__(self):
                self.closed = 0

            def __getitem__(self, name):
                return FakeSheet()

            def close(self):
                self.closed += 1

        workbook = FakeWorkbook()
        with patch("ledger.cardindex.openpyxl.load_workbook", return_value=workbook):
            with self.assertRaisesRegex(RuntimeError, "sentinel"):
                cardindex.load("F", ledger_dir=Path("/synthetic"))
        self.assertEqual(workbook.closed, 1)

    def test_explicit_default_and_arbitrary_cwd(self):
        root = _root()
        self.addCleanup(shutil.rmtree, root)
        old = Path.cwd()
        self.addCleanup(os.chdir, old)
        try:
            os.chdir(tempfile.gettempdir())
            self.assertEqual(len(cardindex.build_cards(ledger_dir=root)), 5)
            with patch.object(cardindex, "DEFAULT_LEDGER_DIR", root):
                self.assertEqual(len(cardindex.build_cards()), 5)
        finally:
            os.chdir(old)

    def test_relative_root_from_synthetic_parent_cwd(self):
        parent = Path(tempfile.mkdtemp())
        root = _root()
        self.addCleanup(shutil.rmtree, parent)
        relative_root = parent / "ledger-root"
        root.rename(relative_root)
        old = Path.cwd()
        self.addCleanup(os.chdir, old)
        os.chdir(parent)
        self.assertEqual(len(cardindex.build_cards(ledger_dir=Path("ledger-root"))), 5)

    def test_consumers_forward_exact_root_and_leave_cwd_unchanged(self):
        root = Path("/synthetic/ledger-root")
        old = Path.cwd()
        self.addCleanup(os.chdir, old)
        try:
            with patch("os.chdir", side_effect=AssertionError("chdir called")):
                with patch.object(cardindex, "build_cards",
                                  return_value=[]) as builder:
                    self.assertEqual(direct_projection._read_cards(root), [])
                    db = sqlite3.connect(":memory:")
                    try:
                        initialize(db)
                        result = direct_sources.import_cards(db, root)
                    finally:
                        db.close()
                    self.assertEqual(result, {"records": 0, "inserted": 0,
                                              "identity_collisions": 0,
                                              "normalized_payments": 0})
                    self.assertEqual(builder.call_args_list[0].kwargs["ledger_dir"], root)
                    self.assertEqual(builder.call_args_list[1].kwargs["ledger_dir"], root)
            self.assertEqual(Path.cwd(), old)
        finally:
            os.chdir(old)

    def test_consumer_exceptions_leave_cwd_unchanged(self):
        root = Path("/synthetic/ledger-root")
        old = Path.cwd()
        self.addCleanup(os.chdir, old)
        try:
            with patch.object(cardindex, "build_cards",
                              side_effect=OSError("synthetic")):
                with self.assertRaises(OSError):
                    direct_projection._read_cards(root)
                db = sqlite3.connect(":memory:")
                try:
                    with self.assertRaises(OSError):
                        direct_sources.import_cards(db, root)
                finally:
                    db.close()
            self.assertEqual(Path.cwd(), old)
        finally:
            os.chdir(old)

    def test_concurrent_distinct_roots_do_not_cross_read(self):
        roots = [_root("alpha"), _root("bravo")]
        for root in roots:
            self.addCleanup(shutil.rmtree, root)
        results = [None, None]

        def read(index, root):
            cards = cardindex.build_cards(ledger_dir=root)
            results[index] = (len(cards), cards[0]["mer"])

        threads = [threading.Thread(target=read, args=(i, root))
                   for i, root in enumerate(roots)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        self.assertEqual(results, [(5, "alpha"), (5, "bravo")])

    def test_missing_input_fails_closed(self):
        root = _root()
        self.addCleanup(shutil.rmtree, root)
        (root / "newcard/conv/E.xlsx").unlink()
        with self.assertRaises(FileNotFoundError):
            cardindex.build_cards(ledger_dir=root)


if __name__ == "__main__": unittest.main()
