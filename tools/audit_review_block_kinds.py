"""Count source block kinds from explicit workbook headers without row values."""
from pathlib import Path
import csv
import json
from collections import Counter
from openpyxl import load_workbook
from webapp.review_context import _parse_source_ref, _parse_explicit_date, _parse_amount, _label_of


def main():
    root = Path(r"D:\WebLedgerHost\review\refreshed\3fc09872dec0d692-160b204dc024a387-cde8196ee1f5a2b7")
    workbook = load_workbook(root / "snapshot.xlsx", data_only=True)
    counts = Counter()
    income = ["거래일자", "이름", "닉네임", "예약금", "잔금", "추가금", "금액(원)"]
    expense = ["거래일자", "항목", "내용", "기간", "예약번호", "증빙유형", "금액(원)"]
    for row in csv.DictReader((root / "review.csv").open(encoding="utf-8-sig")):
        ref = _parse_source_ref(row["source_ref_snapshot_only"])
        sheet = workbook[ref.sheet]
        kind = "unknown"
        for n in range(ref.row - 1, 0, -1):
            labels = [_label_of(sheet.cell(n, c).value) for c in range(ref.date_col, ref.amount_col + 1)]
            if not any(labels):
                continue
            if _parse_explicit_date(sheet.cell(n, ref.date_col).value) is not None and _parse_amount(sheet.cell(n, ref.amount_col).value) is not None:
                continue
            if labels == income:
                kind = "income"
            elif labels == expense:
                kind = "expense"
            break
        counts[kind] += 1
    workbook.close()
    print(json.dumps(dict(counts), ensure_ascii=False))


if __name__ == "__main__":
    main()
