"""CSV renderers for quarter review artifacts."""
from __future__ import annotations

import csv
import io
from webapp.sheets_export import guard_text


def _csv(headers, rows):
    stream = io.StringIO(newline="")
    writer = csv.writer(stream, lineterminator="\r\n")
    writer.writerow(headers)
    writer.writerows([[guard_text(value) if isinstance(value, str) else value for value in row]
                     for row in rows])
    return stream.getvalue()


def render_trip_summary_csv(rows, full_review_count=None):
    rows = list(rows)
    headers = ["여행", "시작일", "종료일", "수입", "지출", "차액", "지출건수", "검수필요건수", "사유별 검수"]
    rendered = [[
        row.get("trip", ""), row.get("starts_on", ""), row.get("ends_on", ""),
        "" if row.get("income") is None else row.get("income"),
        row.get("expense", 0), "" if row.get("profit") is None else row.get("profit"),
        row.get("expense_count", 0), row.get("review_count", 0), row.get("review_reason_summary", ""),
    ] for row in rows]
    complete = bool(rows) and all(row.get('income') is not None and row.get('profit') is not None for row in rows)
    review_total = sum(row.get('review_count', 0) for row in rows)
    rendered.append(['합계', '', '', sum(row['income'] for row in rows) if complete else '',
                     sum(row.get('expense', 0) for row in rows),
                     sum(row['profit'] for row in rows) if complete else '',
                     sum(row.get('expense_count', 0) for row in rows),
                     review_total, ''])
    if full_review_count is not None:
        other = full_review_count - review_total
        rendered.append(['안내', '', '', '', '', '', '', '',
                         f'검수필요건수 합계 {review_total}건은 여행 행만 센 것입니다. 나머지 {other}건은 분기 기타비용 행으로, '
                         f'전체 검수 목록({full_review_count}건)과 기타비용 시트에 있습니다.'])
    return _csv(headers, rendered)


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
