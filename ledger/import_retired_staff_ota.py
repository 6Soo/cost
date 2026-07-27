"""Import the former employee's immutable OTA tracking sheet.

Payment date, travel date, destination, OTA, passengers, and amount are useful
matching evidence.  Amounts are normally exact; overseas KRW/DCC records may
differ from the final card amount, so the reconciler records a separate 2%
tolerance signal instead of silently treating it as an exact match.
"""

from __future__ import annotations

import json
import hashlib
import re
import tempfile
import urllib.request
from datetime import date, datetime
from pathlib import Path

import openpyxl


SHEET_ID = "1DJpNY1MRG2JNxTWpdbk4Nn4zb51YDyBgtNTy6hsG7u4"
EXPORT_URL = f"https://docs.google.com/spreadsheets/d/{SHEET_ID}/export?format=xlsx"
DATA = Path(__file__).resolve().parent / "data"
OUTPUT = DATA / "retired_staff_ota_index.json"


def iso_date(value) -> str:
    if isinstance(value, (datetime, date)):
        return value.strftime("%Y-%m-%d")
    text = str(value or "").strip()
    for fmt in ("%Y-%m-%d", "%y.%m.%d", "%Y.%m.%d"):
        try:
            return datetime.strptime(text, fmt).strftime("%Y-%m-%d")
        except ValueError:
            pass
    return text


def travel_period(value) -> str:
    if isinstance(value, (datetime, date)):
        return value.strftime("%m%d")
    text = str(value or "").strip()
    match = re.search(
        r"(\d{1,2})[./](\d{1,2})\s*[~\-]\s*(?:(\d{1,2})[./])?(\d{1,2})",
        text,
    )
    if match:
        start = f"{int(match.group(1)):02d}{int(match.group(2)):02d}"
        end_month = int(match.group(3) or match.group(1))
        end = f"{end_month:02d}{int(match.group(4)):02d}"
        return f"{start}_{end}"
    match = re.search(r"(\d{1,2})[./](\d{1,2})", text)
    return f"{int(match.group(1)):02d}{int(match.group(2)):02d}" if match else ""


def provider(value) -> str:
    text = str(value or "").upper()
    if "트립닷컴" in text or "TRIP.COM" in text:
        return "trip"
    if "마이트립" in text or "MYTRIP" in text:
        return "mytrip"
    if "AGODA" in text or "아고다" in text:
        return "agoda"
    if "BOOKING" in text or "부킹" in text:
        return "booking"
    return text.lower()


def main() -> None:
    with tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False) as handle:
        temp_path = Path(handle.name)
    try:
        urllib.request.urlretrieve(EXPORT_URL, temp_path)
        source_sha256 = hashlib.sha256(temp_path.read_bytes()).hexdigest()
        workbook = openpyxl.load_workbook(temp_path, data_only=True)
        records = []
        for sheet in workbook.worksheets:
            for row_number, row in enumerate(
                sheet.iter_rows(min_row=2, values_only=True), start=2
            ):
                if not row or row[0] in (None, ""):
                    continue
                records.append({
                    "sourceSheet": sheet.title,
                    "sourceRow": row_number,
                    "paymentDate": iso_date(row[0]),
                    "travelDateRaw": str(row[1] or ""),
                    "travelPeriod": travel_period(row[1]),
                    "destination": str(row[2] or "").strip(),
                    "provider": provider(row[4]),
                    "passengers": str(row[7] or "").strip(),
                    "amountReference": row[5],
                    "amountTrusted": True,
                    "sourceUrl": (
                        f"https://docs.google.com/spreadsheets/d/{SHEET_ID}/edit"
                    ),
                })
        OUTPUT.write_text(
            json.dumps(
                {
                    "sheetId": SHEET_ID,
                    "sourceImmutable": True,
                    "sourceSha256": source_sha256,
                    "trustedFields": [
                        "paymentDate", "travelPeriod", "destination",
                        "provider", "passengers", "amountReference",
                    ],
                    "amountPolicy": {
                        "exactPreferred": True,
                        "overseasKrwToleranceRatio": 0.02,
                    },
                    "untrustedFields": ["allOtherFields"],
                    "records": records,
                },
                ensure_ascii=False,
                indent=2,
            ) + "\n",
            encoding="utf-8",
        )
        print(f"retired_staff_ota_index: {len(records)} rows")
    finally:
        temp_path.unlink(missing_ok=True)


if __name__ == "__main__":
    main()
