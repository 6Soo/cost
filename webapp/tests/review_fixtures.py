"""Synthetic source fixtures for the authenticated actual-source review tests.

Nothing here reads a real checkout, a customer file or a deployment database.
Every workbook, review CSV and master CSV is written by this module into a
temporary directory, with values that are obviously not real: the sheet is
합성시트, the candidates are 합성거래키-N, the merchant is 합성이용점 and the
customer name that the review screen must render as text is the literal
`<script>alert(1)</script>`.

The layout is the one the existing pure core requires: a seven column expense
block headed 거래일자 / 항목 / 내용 / 기간 / 예약번호 / 증빙유형 / 금액, one
physical row per transaction, and a source ref naming the sheet, the date cell,
the amount cell and the row they share.
"""

from __future__ import annotations

import csv
import io
import json
from pathlib import Path

from webapp.contracts import sha256_bytes, sha256_text

SHEET = "합성시트"
BLOCK_HEADER = ("거래일자", "항목", "내용", "기간", "예약번호", "증빙유형", "금액")
HEADER_ROW = 4
FIRST_ROW = 5
INJECTION = "<script>alert(1)</script>"

REVIEW_HEADERS = (
    "source_ref_snapshot_only", "source_date", "source_amount",
    "candidate_count", "candidate_transaction_keys", "candidate_date_fields",
    "disposition", "reviewer_decision", "review_note",
    "review_schema_version", "review_snapshot_sha256",
)
MASTER_HEADERS = (
    "거래키", "카드사", "카드4", "구분", "승인일", "매입일", "가맹점", "원화금액",
    "현지금액", "통화", "승인번호", "취소여부", "출처", "적재일", "기록여부",
    "워크북참조", "비고",
)


def source_ref(row: int) -> str:
    return f"{SHEET}!A{row}|G{row} (row {row})"


def candidate_key(index: int) -> str:
    return f"합성거래키-{index:04d}"


def build_snapshot_bytes(rows, *, with_header: bool = True):
    """One synthetic workbook holding the given transactions.

    `rows` is a list of `(date, item, description, amount)` tuples. A tuple whose
    description is None writes a blank cell, which is how a row with no header
    above it is made: `with_header=False` writes the data without the block
    header, and the core then reports the row as insufficient evidence.
    """
    from openpyxl import Workbook

    workbook = Workbook()
    sheet = workbook.active
    sheet.title = SHEET
    if with_header:
        for column, label in enumerate(BLOCK_HEADER, start=1):
            sheet.cell(row=HEADER_ROW, column=column, value=label)
    for offset, (date, item, description, amount) in enumerate(rows):
        row = FIRST_ROW + offset
        sheet.cell(row=row, column=1, value=date)
        sheet.cell(row=row, column=2, value=item)
        sheet.cell(row=row, column=3, value=description)
        sheet.cell(row=row, column=4, value="")
        sheet.cell(row=row, column=5, value="")
        sheet.cell(row=row, column=6, value="카드")
        sheet.cell(row=row, column=7, value=amount)
    buffer = io.BytesIO()
    workbook.save(buffer)
    workbook.close()
    return buffer.getvalue()


def build_master_text(keys, *, injection: bool = False) -> str:
    """The card master, one row per key, with all seventeen headers present."""
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(MASTER_HEADERS)
    for index, key in enumerate(keys, start=1):
        writer.writerow([
            key, "합성카드사", "0000", "매출", f"2026-04-{index % 28 + 1:02d}",
            f"2026-04-{index % 28 + 1:02d}",
            INJECTION if injection else "합성이용점",
            100000 + index, "", "KRW", f"APPROVAL-{index:04d}", "N",
            "합성원장", "2026-04-30", "Y", "", "",
        ])
    return buffer.getvalue()


def build_review_text(snapshot_sha, rows, keys_per_row, *, decisions=None,
                      injection: bool = False) -> str:
    """The review CSV that names the source refs and the candidate keys."""
    decisions = decisions or {}
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(REVIEW_HEADERS)
    for offset in range(rows):
        row = FIRST_ROW + offset
        keys = keys_per_row(offset)
        date_fields = json.dumps(
            {key: {"승인일": "2026-04-09", "매입일": "2026-04-10"}
             for key in keys}, ensure_ascii=False)
        writer.writerow([
            source_ref(row),
            f"2026-04-{offset % 28 + 1:02d}",
            100001 + offset,
            len(keys),
            json.dumps(keys, ensure_ascii=False),
            date_fields,
            "candidate_review_required",
            decisions.get(offset, ""),
            INJECTION if injection else "",
            "review-csv-v1",
            snapshot_sha,
        ])
    return buffer.getvalue()


def write_case(directory, *, rows=3, keys_per_row=None, with_header=True,
               decisions=None, injection=False, drift_master=False):
    """Write the three configured inputs and their digests into `directory`.

    Returns the manifest the service is configured with. `drift_master` appends a
    byte to the master after the digest is taken, which is how a source changed
    underneath a running service is reproduced.
    """
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    keys = [candidate_key(i) for i in range(1, rows * 2 + 1)]
    if keys_per_row is None:
        def keys_per_row(offset):
            return [keys[offset]]

    sheet_rows = [
        (f"2026-04-{offset % 28 + 1:02d}", "합성항목", f"합성내용 {offset}",
         100001 + offset)
        for offset in range(rows)
    ]
    snapshot = build_snapshot_bytes(sheet_rows, with_header=with_header)
    snapshot_path = directory / "합성스냅샷.xlsx"
    snapshot_path.write_bytes(snapshot)
    snapshot_sha = sha256_bytes(snapshot)

    review_text = build_review_text(
        snapshot_sha, rows, keys_per_row, decisions=decisions,
        injection=injection)
    # `newline=""` on every write. Without it, a text write translates each "\n"
    # into "\r\n" on this platform, so the bytes on disk would not be the bytes
    # the digest was taken over, and the service would correctly refuse to read a
    # file this test had just written.
    review_path = directory / "합성검토.csv"
    review_path.write_text(review_text, encoding="utf-8", newline="")
    review_sha = sha256_text(review_text)

    master_text = build_master_text(keys, injection=injection)
    master_path = directory / "합성마스터.csv"
    master_path.write_text(master_text, encoding="utf-8", newline="")
    master_sha = sha256_text(master_text)
    if drift_master:
        master_path.write_text(master_text + "\r\n합성표시,1\r\n",
                              encoding="utf-8", newline="")

    return {
        "snapshot_path": str(snapshot_path),
        "snapshot_sha256": snapshot_sha,
        "review_path": str(review_path),
        "review_sha256": review_sha,
        "master_path": str(master_path),
        "master_sha256": master_sha,
        "decisions_db_path": str(directory / "decisions.sqlite"),
    }
