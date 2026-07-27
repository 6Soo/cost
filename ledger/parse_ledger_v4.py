"""수기장부의 여행별 지출 행을 manual_v3/v4 CSV로 변환한다.

Google Sheets에서 복제된 ``(1)`` 탭은 같은 행을 이중 계상하므로 제외한다.
열 위치를 고정하지 않고 '거래일자/항목/내용/증빙유형/금액' 헤더를 찾아
병합형 장부와 연속 열형 장부를 모두 처리한다.
"""

from __future__ import annotations

import argparse
import copy
import csv
import datetime as dt
import re
from pathlib import Path

import openpyxl


OUTPUT_FIELDS_V4 = ("tab", "row", "date", "item", "desc", "card", "amount", "book")
OUTPUT_FIELDS_V3 = ("tab", "date", "item", "desc", "card", "amount", "book")
PERIOD_DESC = re.compile(r"^(?:숙박|항공|렌터카|렌트|료칸)_\d{4}(?:_\d{4})?(?:_|$)")
SKIP_SHEETS = {
    "2분기_기타비용",
    "프리랜서 지급대장",
    "매출자료 양식",
    "매출자료 양식_rev",
    "매출자료 개선판",
    "행사경비총괄표",
}


def text(value: object) -> str:
    if value is None:
        return ""
    return str(value).strip()


def id_text(value: object) -> str:
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    value_text = text(value)
    return value_text if re.fullmatch(r"[A-Za-z0-9-]+", value_text) else ""


def date_text(value: object) -> str:
    # 기존 manual_v4와의 키 호환을 위해 셀 표시형을 임의 정규화하지 않는다.
    value_text = text(value)
    if isinstance(value, (dt.datetime, dt.date)):
        return value.strftime("%y.%m.%d")
    if re.match(r"^'?(?:\d{2}|\d{4})[./-]\d{1,2}[./-]\d{1,2}", value_text):
        return value_text
    return ""


def header_columns(values: tuple[object, ...]) -> dict[str, int] | None:
    labels = {text(value).replace(" ", ""): index for index, value in enumerate(values)}
    required = ("거래일자", "항목", "내용", "증빙유형")
    if not all(label in labels for label in required):
        return None
    amount = next((index for label, index in labels.items() if label.startswith("금액")), None)
    if amount is None:
        return None
    return {
        "date": labels["거래일자"],
        "item": labels["항목"],
        "desc": labels["내용"],
        "card": labels["증빙유형"],
        "amount": amount,
        # 구 병합형 장부는 예약번호 헤더 없이 금액 열 두 칸 뒤(K)에 값을 뒀다.
        "book": labels.get("예약번호", amount + 2),
    }


def parse_workbook(path: Path) -> list[dict[str, str]]:
    workbook = openpyxl.load_workbook(path, read_only=True, data_only=True)
    parsed: list[dict[str, str]] = []
    for sheet_name in workbook.sheetnames:
        if sheet_name in SKIP_SHEETS or re.search(r" \(\d+\)$", sheet_name):
            continue
        sheet = workbook[sheet_name]
        columns: dict[str, int] | None = None
        in_expenses = False
        for row_number, values in enumerate(sheet.iter_rows(values_only=True), start=1):
            row_text = [text(value) for value in values]
            if any("지출 내용" in value for value in row_text):
                in_expenses = True
                columns = None
                continue
            if not in_expenses:
                continue
            if any("총 금액 (B)" in value for value in row_text):
                break
            detected = header_columns(values)
            if detected:
                columns = detected
                continue
            if columns is None:
                continue
            max_index = max(index for index in columns.values() if index >= 0)
            padded = list(values) + [None] * (max_index + 1 - len(values))
            amount_value = padded[columns["amount"]]
            try:
                amount = float(str(amount_value).replace(",", ""))
            except (TypeError, ValueError):
                continue
            date = date_text(padded[columns["date"]])
            item = text(padded[columns["item"]])
            # 날짜/항목이 비어 있는 원기재도 카드 거래 보존 원칙상 버리지 않는다.
            if not any((date, item, text(padded[columns["desc"]]), text(padded[columns["card"]]))):
                continue
            book_index = columns["book"]
            parsed.append(
                {
                    "tab": sheet_name,
                    "row": str(row_number),
                    "date": date,
                    "item": item,
                    "desc": text(padded[columns["desc"]]),
                    "card": text(padded[columns["card"]]),
                    "amount": str(amount),
                    "book": id_text(padded[book_index]) if book_index >= 0 else "",
                }
            )
    return parsed


def preserve_verified_periods(
    rows: list[dict[str, str]], previous_path: Path | None
) -> int:
    """최신 시트가 내용을 '숙박/항공'으로 축약해도 확인된 기간은 잃지 않는다."""
    if previous_path is None or not previous_path.exists():
        return 0
    with previous_path.open(encoding="utf-8-sig") as handle:
        previous = list(csv.DictReader(handle))

    by_book: dict[str, str] = {}
    by_key: dict[tuple[str, str, str], set[str]] = {}
    for old in previous:
        desc = (old.get("desc") or "").strip()
        if not PERIOD_DESC.match(desc):
            continue
        book = (old.get("book") or "").strip()
        if book:
            by_book.setdefault(book, desc)
        key = (
            old.get("tab") or "",
            old.get("amount") or "",
            re.sub(r"\s+", "", (old.get("item") or "").upper()),
        )
        by_key.setdefault(key, set()).add(desc)

    restored = 0
    for row in rows:
        if PERIOD_DESC.match(row["desc"]):
            continue
        desc = by_book.get(row["book"]) if row["book"] else None
        if desc is None:
            key = (
                row["tab"],
                row["amount"],
                re.sub(r"\s+", "", row["item"].upper()),
            )
            candidates = by_key.get(key, set())
            if len(candidates) == 1:
                desc = next(iter(candidates))
        if desc:
            row["desc"] = desc
            restored += 1
    return restored


def write_csv(path: Path, rows: list[dict[str, str]], fields: tuple[str, ...]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("workbook", type=Path)
    parser.add_argument("--v4", type=Path, default=Path("data/manual_v4.csv"))
    parser.add_argument("--v3", type=Path, default=Path("data/manual_v3.csv"))
    parser.add_argument(
        "--periods",
        type=Path,
        default=Path("data/manual_periods.csv"),
        help="분류에는 쓰지 않는 표시용 기간 승계 CSV",
    )
    parser.add_argument(
        "--previous-v4",
        type=Path,
        help="기간이 확인된 이전 manual_v4. 생략하면 기존 --v4 파일을 사용",
    )
    args = parser.parse_args()

    previous_path = args.previous_v4 or args.v4
    rows = parse_workbook(args.workbook)
    period_rows = copy.deepcopy(rows)
    restored = preserve_verified_periods(period_rows, previous_path)
    write_csv(args.v4, rows, OUTPUT_FIELDS_V4)
    write_csv(args.v3, rows, OUTPUT_FIELDS_V3)
    write_csv(args.periods, period_rows, OUTPUT_FIELDS_V4)
    print(f"manual rows: {len(rows):,} | verified periods restored: {restored:,}")


if __name__ == "__main__":
    main()
