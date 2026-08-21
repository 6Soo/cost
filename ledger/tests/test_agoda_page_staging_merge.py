import contextlib
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


def _connect(path: Path | str) -> contextlib.AbstractContextManager[sqlite3.Connection]:
    return contextlib.closing(sqlite3.connect(path, uri=True if isinstance(path, str) and path.startswith("file:") else False))

from tools.agoda_page_staging_merge import merge_page_databases
from tools.agoda_portal_page_capture import capture_page


class AgodaPageStagingMergeTests(unittest.TestCase):
    def test_merge_requires_and_publishes_all_thirteen_pages(self) -> None:
        page_template = """
        100 그룹 mmb-booking-card--{page_no}
          101 텍스트 Check in
          102 텍스트 Sun, Jan 25
          103 텍스트 Check out
          104 텍스트 Mon, Jan 26
        """
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            page_paths: list[Path] = []
            for page_no in range(1, 14):
                page_path = root / f"page-{page_no:02d}.sqlite"
                with patch(
                    "tools.agoda_portal_page_capture._go_to_page",
                    return_value=page_template.format(page_no=page_no),
                ):
                    capture_page(
                        app="msedge",
                        window_id=1,
                        page_no=page_no,
                        db_path=page_path,
                        run_id=f"page-{page_no}-run",
                    )
                page_paths.append(page_path)

            final_path = root / "merged.sqlite"
            result = merge_page_databases(
                page_db_paths=page_paths,
                db_path=final_path,
                run_id="merged-run",
            )
            self.assertEqual(result["captured_pages"], list(range(1, 14)))
            self.assertEqual(result["total_cards"], 13)
            with _connect(
                f"file:{final_path}?mode=ro&immutable=1",
            ) as connection:
                self.assertEqual(
                    connection.execute("SELECT COUNT(*) FROM agoda_pages").fetchone()[0],
                    13,
                )
                self.assertEqual(
                    connection.execute(
                        "SELECT COUNT(DISTINCT page_no) FROM agoda_completed_bookings"
                    ).fetchone()[0],
                    13,
                )

    def test_merge_rejects_cross_page_duplicate_booking_hashes(self) -> None:
        page_template = """
        100 그룹 mmb-booking-card--{booking}
          101 텍스트 Check in
          102 텍스트 Sun, Jan 25
        """
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            page_paths: list[Path] = []
            for page_no in range(1, 14):
                page_path = root / f"page-{page_no:02d}.sqlite"
                booking = "same" if page_no in {1, 2} else f"unique-{page_no}"
                with patch(
                    "tools.agoda_portal_page_capture._go_to_page",
                    return_value=page_template.format(booking=booking),
                ):
                    capture_page(
                        app="msedge",
                        window_id=1,
                        page_no=page_no,
                        db_path=page_path,
                        run_id=f"page-{page_no}-run",
                    )
                page_paths.append(page_path)

            with self.assertRaisesRegex(RuntimeError, "cross-page duplicate"):
                merge_page_databases(
                    page_db_paths=page_paths,
                    db_path=root / "merged.sqlite",
                    run_id="duplicate-merged-run",
                )

    def test_target_year_only_merge_ignores_non_target_cross_page_duplicates(self) -> None:
        page_template = """
        100 그룹 mmb-booking-card--{booking}
          101 텍스트 Check in
          102 텍스트 {date}
        """
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            page_paths: list[Path] = []
            for page_no in range(1, 14):
                page_path = root / f"page-{page_no:02d}.sqlite"
                if page_no in {1, 2}:
                    booking, date_text = "old-duplicate", "Thu, Dec 25, 25"
                else:
                    booking, date_text = f"target-{page_no}", "Sun, Jan 25"
                with patch(
                    "tools.agoda_portal_page_capture._go_to_page",
                    return_value=page_template.format(
                        booking=booking,
                        date=date_text,
                    ),
                ):
                    capture_page(
                        app="msedge",
                        window_id=1,
                        page_no=page_no,
                        db_path=page_path,
                        run_id=f"page-{page_no}-run",
                    )
                page_paths.append(page_path)

            result = merge_page_databases(
                page_db_paths=page_paths,
                db_path=root / "merged.sqlite",
                run_id="target-only-merged-run",
                target_year_only=True,
            )
            self.assertEqual(result["source_total_cards"], 13)
            self.assertEqual(result["total_cards"], 11)
            self.assertEqual(result["target_year_rows"], 11)
            self.assertEqual(result["distinct_target_year_bookings"], 11)
            with _connect(
                f"file:{root / 'merged.sqlite'}?mode=ro&immutable=1",
            ) as connection:
                self.assertEqual(
                    connection.execute(
                        "SELECT COUNT(*) FROM agoda_completed_bookings"
                    ).fetchone()[0],
                    11,
                )


if __name__ == "__main__":
    unittest.main()
