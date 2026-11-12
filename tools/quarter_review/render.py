"""CSV renderers for quarter review artifacts."""
from __future__ import annotations

import csv
import io


def _csv(headers, rows):
    stream = io.StringIO(newline="")
    writer = csv.writer(stream, lineterminator="\r\n")
    writer.writerow(headers)
    writer.writerows(rows)
    return stream.getvalue()


def render_trip_summary_csv(rows):
    headers = ["여행", "시작일", "종료일", "수입", "지출", "차액", "지출건수", "검수필요건수", "사유별 검수"]
    return _csv(headers, [[
        row.get("trip", ""), row.get("starts_on", ""), row.get("ends_on", ""),
        "" if row.get("income") is None else row.get("income"),
        row.get("expense", 0), "" if row.get("profit") is None else row.get("profit"),
        row.get("expense_count", 0), row.get("review_count", 0), row.get("review_reason_summary", ""),
    ] for row in rows])


def render_review_list_csv(rows):
    headers = ["순위", "여행", "결제일", "가맹점", "항목", "금액", "판정주체", "사유"]
    rendered = []
    for index, row in enumerate(rows, 1):
        rendered.append([
            index, row.get("trip", ""), row.get("approval_date") or row.get("posting_date", ""),
            row.get("merchant", ""), row.get("item", ""), row.get("amount_krw", ""),
            row.get("source_label", ""), " · ".join(row.get("review_reasons", [])),
        ])
    return _csv(headers, rendered)
