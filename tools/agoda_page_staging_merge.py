#!/usr/bin/env python3
"""Merge the 13 isolated Agoda page staging databases.

Each input is opened only with SQLite ``mode=ro&immutable=1``.  The merge
publishes a new private staging database only after every page 1..13 has one
valid page manifest and all rows agree with that page number.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sqlite3
import tempfile
from contextlib import closing
from pathlib import Path
from typing import Any

try:
    from tools.agoda_portal_page_capture import _schema
except ModuleNotFoundError:  # direct ``python tools/...`` invocation
    from agoda_portal_page_capture import _schema


ALL_PAGE_ORDER = tuple(range(1, 14))


BOOKING_COLUMNS = (
    "page_no",
    "booking_id",
    "booking_id_sha256",
    "service_start_on",
    "service_end_on",
    "service_dates_json",
    "service_years_json",
    "is_2026",
    "status",
    "card_sha256",
)


def _require_tmp(path: Path) -> Path:
    resolved = path.expanduser().resolve()
    allowed_roots = [
        Path("/tmp").resolve(),
        Path(tempfile.gettempdir()).resolve(),
    ]
    if not any(root in resolved.parents or resolved == root for root in allowed_roots):
        raise RuntimeError("staging database must be under /tmp")
    return resolved


def _immutable_connection(path: Path) -> sqlite3.Connection:
    return sqlite3.connect(f"file:{path}?mode=ro&immutable=1", uri=True)


def _page_summary(row: tuple[Any, ...]) -> dict[str, Any]:
    return {
        "page": row[0],
        "card_count": row[1],
        "target_year_count": row[2],
        "no_service_date_count": row[3],
        "duplicate_booking_id_count": row[4],
        "min_service_on": row[5],
        "max_service_on": row[6],
        "page_sha256": row[7],
    }


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def merge_page_databases(
    *,
    page_db_paths: list[Path],
    db_path: Path,
    run_id: str,
    target_year_only: bool = False,
) -> dict[str, Any]:
    if len(page_db_paths) != len(ALL_PAGE_ORDER):
        raise RuntimeError("merge requires exactly 13 page databases")
    final_path = _require_tmp(db_path)
    if final_path.exists():
        raise RuntimeError("refusing to overwrite an existing merged staging database")
    input_paths = [_require_tmp(path) for path in page_db_paths]
    if len(set(input_paths)) != len(input_paths):
        raise RuntimeError("page database paths must be unique")
    if any(not path.is_file() for path in input_paths):
        raise RuntimeError("one or more page staging databases are missing")

    final_path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    connection = sqlite3.connect(":memory:")
    _schema(connection)
    connection.executescript(
        """
        CREATE TABLE merge_manifest (
            run_id TEXT PRIMARY KEY,
            capture_set_sha256 TEXT NOT NULL,
            target_year_only INTEGER NOT NULL CHECK (target_year_only IN (0, 1)),
            source_total_cards INTEGER NOT NULL,
            published_rows INTEGER NOT NULL
        );
        CREATE TABLE merge_input_manifest (
            page_no INTEGER PRIMARY KEY,
            source_path TEXT NOT NULL,
            source_sha256 TEXT NOT NULL
        );
        """
    )
    page_summaries: list[dict[str, Any]] = []
    seen_booking_hashes: set[str] = set()
    seen_page_hashes: set[str] = set()
    lock_path = final_path.with_name(f".{final_path.name}.lock")
    published_here = False
    try:
        input_hashes_before = {
            page_no: _file_sha256(path)
            for page_no, path in zip(ALL_PAGE_ORDER, input_paths)
        }
        connection.execute(
            "INSERT INTO run_manifest VALUES (?, ?, ?, ?, datetime('now'))",
            (
                run_id,
                "agoda_account_completed_pages_merged"
                + ("_2026_only" if target_year_only else ""),
                13,
                2026,
            ),
        )
        insert_sql = f"""
            INSERT INTO agoda_completed_bookings({', '.join(BOOKING_COLUMNS)})
            VALUES ({', '.join('?' for _ in BOOKING_COLUMNS)})
        """
        for expected_page, page_path in zip(ALL_PAGE_ORDER, input_paths):
            with closing(_immutable_connection(page_path)) as source:
                manifest = source.execute(
                    "SELECT source, captured_pages, target_year FROM run_manifest"
                ).fetchall()
                if manifest != [("agoda_account_completed_page", 1, 2026)]:
                    raise RuntimeError(f"page {expected_page} manifest is invalid")
                page_rows = source.execute(
                    """
                    SELECT page_no, card_count, target_year_count,
                           no_service_date_count, duplicate_booking_id_count,
                           min_service_on, max_service_on, page_sha256
                    FROM agoda_pages
                    """
                ).fetchall()
                if len(page_rows) != 1 or page_rows[0][0] != expected_page:
                    raise RuntimeError(f"page {expected_page} page manifest is invalid")
                booking_rows = source.execute(
                    f"SELECT {', '.join(BOOKING_COLUMNS)} "
                    "FROM agoda_completed_bookings ORDER BY row_id"
                ).fetchall()
                if any(row[0] != expected_page for row in booking_rows):
                    raise RuntimeError(f"page {expected_page} contains cross-page rows")
                if len(booking_rows) != page_rows[0][1]:
                    raise RuntimeError(f"page {expected_page} card count does not match rows")
                summary = _page_summary(page_rows[0])
                row_booking_hashes = [row[2] for row in booking_rows]
                row_card_hashes = [row[9] for row in booking_rows]
                recomputed_page_sha = hashlib.sha256(
                    "".join(sorted(row_card_hashes)).encode()
                ).hexdigest()
                if recomputed_page_sha != summary["page_sha256"]:
                    raise RuntimeError(f"page {expected_page} page hash does not match rows")
                if summary["page_sha256"] in seen_page_hashes:
                    raise RuntimeError(f"page {expected_page} duplicates another page fingerprint")
                page_duplicate_count = len(row_booking_hashes) - len(set(row_booking_hashes))
                if page_duplicate_count != summary["duplicate_booking_id_count"]:
                    raise RuntimeError(f"page {expected_page} duplicate count does not match rows")
                cross_page_duplicates = seen_booking_hashes.intersection(row_booking_hashes)
                if cross_page_duplicates and not target_year_only:
                    raise RuntimeError(f"page {expected_page} contains cross-page duplicate bookings")
                if summary["target_year_count"] != sum(row[7] for row in booking_rows):
                    raise RuntimeError(f"page {expected_page} target count does not match rows")
                if summary["no_service_date_count"] != sum(
                    row[3] is None for row in booking_rows
                ):
                    raise RuntimeError(f"page {expected_page} date count does not match rows")
                selected_rows = [
                    row for row in booking_rows if not target_year_only or row[7] == 1
                ]
                selected_booking_hashes = [row[2] for row in selected_rows]
                cross_page_selected_duplicates = seen_booking_hashes.intersection(
                    selected_booking_hashes
                )
                if cross_page_selected_duplicates:
                    raise RuntimeError(
                        f"page {expected_page} contains cross-page duplicate target bookings"
                    )
                seen_booking_hashes.update(selected_booking_hashes)
                seen_page_hashes.add(summary["page_sha256"])
                connection.executemany(insert_sql, selected_rows)
                connection.execute(
                    """
                    INSERT INTO agoda_pages(
                        page_no, card_count, target_year_count,
                        no_service_date_count, duplicate_booking_id_count,
                        min_service_on, max_service_on, page_sha256
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    page_rows[0],
                )
                page_summaries.append(summary)
            if _file_sha256(page_path) != input_hashes_before[expected_page]:
                raise RuntimeError(f"page {expected_page} changed during merge")

        connection.commit()
        total_cards = int(
            connection.execute("SELECT COUNT(*) FROM agoda_completed_bookings").fetchone()[0]
        )
        source_total_cards = sum(summary["card_count"] for summary in page_summaries)
        capture_set_sha256 = hashlib.sha256(
            json.dumps(
                [input_hashes_before[page] for page in ALL_PAGE_ORDER],
                separators=(",", ":"),
            ).encode()
        ).hexdigest()
        connection.execute(
            "INSERT INTO merge_manifest VALUES (?, ?, ?, ?, ?)",
            (
                run_id,
                capture_set_sha256,
                int(target_year_only),
                source_total_cards,
                total_cards,
            ),
        )
        connection.executemany(
            "INSERT INTO merge_input_manifest VALUES (?, ?, ?)",
            [
                (page, str(input_paths[page - 1]), input_hashes_before[page])
                for page in ALL_PAGE_ORDER
            ],
        )
        connection.commit()
        total_target_rows = int(
            connection.execute(
                "SELECT COUNT(*) FROM agoda_completed_bookings WHERE is_2026 = 1"
            ).fetchone()[0]
        )
        total_distinct_rows = int(
            connection.execute(
                "SELECT COUNT(DISTINCT booking_id_sha256) FROM agoda_completed_bookings"
            ).fetchone()[0]
        )
        target_distinct_rows = int(
            connection.execute(
                "SELECT COUNT(DISTINCT booking_id_sha256) FROM agoda_completed_bookings WHERE is_2026 = 1"
            ).fetchone()[0]
        )

        try:
            if any(
                _file_sha256(path) != input_hashes_before[page]
                for page, path in zip(ALL_PAGE_ORDER, input_paths)
            ):
                raise RuntimeError("input page changed before publication")
            lock_fd = os.open(lock_path, os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0) | os.O_WRONLY, 0o600)
        except FileExistsError as exc:
            raise RuntimeError("merged staging destination is locked") from exc
        os.close(lock_fd)
        temporary_path: Path | None = None
        try:
            temp_fd, temp_name = tempfile.mkstemp(
                prefix=f".{final_path.name}.",
                suffix=".tmp",
                dir=str(final_path.parent),
            )
            os.close(temp_fd)
            temporary_path = Path(temp_name)
            destination = sqlite3.connect(str(temporary_path))
            try:
                connection.backup(destination)
                destination.commit()
            finally:
                destination.close()
            os.chmod(temporary_path, 0o600)
            with temporary_path.open("r+b") as sync_file:
                os.fsync(sync_file.fileno())
            os.link(temporary_path, final_path)
            published_here = True
            temporary_path.unlink()
            os.chmod(final_path, 0o600)
            verified = _immutable_connection(final_path)
            try:
                verified_pages = verified.execute(
                    "SELECT COUNT(*) FROM agoda_pages"
                ).fetchone()[0]
                verified_rows = verified.execute(
                    "SELECT COUNT(*) FROM agoda_completed_bookings"
                ).fetchone()[0]
                verified_page_set = {
                    row[0]
                    for row in verified.execute("SELECT page_no FROM agoda_pages")
                }
                verified_manifest = verified.execute(
                    "SELECT capture_set_sha256, target_year_only, source_total_cards, published_rows "
                    "FROM merge_manifest WHERE run_id = ?",
                    (run_id,),
                ).fetchone()
            finally:
                verified.close()
            if (
                verified_pages != 13
                or verified_rows != total_cards
                or verified_page_set != set(ALL_PAGE_ORDER)
                or verified_manifest
                != (
                    capture_set_sha256,
                    int(target_year_only),
                    source_total_cards,
                    total_cards,
                )
            ):
                raise RuntimeError("merged immutable verification failed")
        except Exception:
            if published_here and final_path.exists():
                final_path.unlink()
            raise
        finally:
            if temporary_path is not None and temporary_path.exists():
                temporary_path.unlink()

        page_counts = sorted({summary["card_count"] for summary in page_summaries})
        return {
            "run_id": run_id,
            "db": str(final_path),
            "captured_pages": list(ALL_PAGE_ORDER),
            "page_summaries": page_summaries,
            "total_cards": total_cards,
            "source_total_cards": source_total_cards,
            "target_year_only": target_year_only,
            "capture_set_sha256": capture_set_sha256,
            "input_hashes_stable": True,
            "target_year_rows": total_target_rows,
            "distinct_total_bookings": total_distinct_rows,
            "distinct_target_year_bookings": target_distinct_rows,
            "duplicate_total_rows": total_cards - total_distinct_rows,
            "duplicate_target_year_rows": total_target_rows - target_distinct_rows,
            "page_card_count_values": page_counts,
            "page_card_count_is_constant": len(page_counts) == 1,
            "input_db_sha256": [
                hashlib.sha256(path.read_bytes()).hexdigest() for path in input_paths
            ],
        }
    finally:
        connection.close()
        if lock_path.exists():
            lock_path.unlink()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--page-db", type=Path, nargs=13, required=True)
    parser.add_argument("--db", type=Path, required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument(
        "--target-year-only",
        action="store_true",
        help="publish only rows whose service dates include the target year",
    )
    args = parser.parse_args()
    result = merge_page_databases(
        page_db_paths=args.page_db,
        db_path=args.db,
        run_id=args.run_id,
        target_year_only=args.target_year_only,
    )
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
