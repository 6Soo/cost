"""Independent, read-only reparse of the five Hana Q1/Q2 XLS exports.

Each source row can contain an approval amount and a cancellation amount.
They are expanded into separate immutable events.  This module deliberately
does not reuse the earlier comparison script or modify any central dataset.
"""
from __future__ import annotations

import csv
import hashlib
import io
import json
import os
import re
from collections import Counter, defaultdict
from datetime import date, datetime
from pathlib import Path
from typing import Any

import xlrd


ROOT = Path(__file__).resolve().parents[1]
DOWNLOAD = Path(r"D:\DownLoad")
OUTDIR = ROOT / "outputs" / "hana_q1q2_revalidation"
OUT_JSON = OUTDIR / "reparse_events.json"
OUT_CSV = OUTDIR / "reparse_events_detail.csv"
START, END = date(2026, 1, 1), date(2026, 6, 30)


def txt(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value).strip()


def won(value: Any) -> int:
    raw = txt(value).replace(",", "").replace("₩", "").strip()
    if not raw or raw in {"-", "—"}:
        return 0
    raw = raw.replace("(", "-").replace(")", "")
    try:
        return int(round(float(raw)))
    except ValueError:
        return 0


def digits(value: Any) -> str:
    return re.sub(r"\D", "", txt(value))


def parse_day(value: Any, datemode: int) -> str:
    if isinstance(value, float):
        try:
            return xlrd.xldate_as_datetime(value, datemode).date().isoformat()
        except (ValueError, OverflowError):
            pass
    raw = txt(value)
    for fmt in ("%Y.%m.%d", "%Y-%m-%d", "%Y/%m/%d", "%Y%m%d"):
        try:
            return datetime.strptime(raw[:10], fmt).date().isoformat()
        except ValueError:
            pass
    return ""


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def atomic_text(path: Path, data: str) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(data, encoding="utf-8-sig", newline="")
    os.replace(tmp, path)


def column_map(header: list[Any]) -> dict[str, int]:
    """Map issuer headers by Korean/English semantic fragments.

    Names vary a little across each export, so later selection falls back to
    observed fixed positions only after the header is recorded in the audit.
    """
    normalized = [re.sub(r"\s+", "", txt(x)).upper() for x in header]
    targets = {
        "date": ("이용일", "거래일", "승인일", "DATE"),
        "card": ("카드번호", "CARDNO"),
        "approval": ("승인번호", "승인NO", "APPROVAL"),
        "merchant": ("가맹점명", "가맹점", "MERCHANT"),
        "approval_amount": ("승인금액", "이용금액", "결제금액", "APPROVALAMOUNT"),
        "cancel_amount": ("취소금액", "취소금", "CANCELAMOUNT"),
        "krw_amount": ("원화금액", "KRWAMOUNT"),
        "billed_amount": ("청구금액", "원화청구", "KRW"),
        "country": ("국가", "COUNTRY"),
    }
    found: dict[str, int] = {}
    for key, needles in targets.items():
        for i, cell in enumerate(normalized):
            if any(needle in cell for needle in needles):
                found[key] = i
                break
    return found


def pick(values: list[Any], mapping: dict[str, int], key: str, fallback: int | None = None) -> Any:
    index = mapping.get(key, fallback)
    if index is None or index >= len(values):
        return ""
    return values[index]


def source_files() -> list[Path]:
    files = sorted(
        (p for p in DOWNLOAD.glob("*_2026_Q1Q2.xls")
         if re.search(r"_[1-5]_2026_Q1Q2\.xls$", p.name)),
        key=lambda p: p.name,
    )
    if len(files) != 5:
        raise RuntimeError(f"Expected exactly five Q1Q2 XLS sources, found {len(files)}: {[p.name for p in files]}")
    return files


def is_transaction(values: list[Any], mapping: dict[str, int], datemode: int) -> bool:
    # A dated row with a card or merchant field is an issuer transaction row.
    # Summary/footer rows are excluded by the absence of the date or both IDs.
    day = parse_day(pick(values, mapping, "date", 1), datemode)
    card = digits(pick(values, mapping, "card", 2))
    merchant = txt(pick(values, mapping, "merchant", 4))
    return bool(day and (card or merchant))


def expand_row(values: list[Any], mapping: dict[str, int], *, source: Path, sheet: str,
               row_1based: int, datemode: int) -> list[dict[str, Any]]:
    """Create 0--2 events from one issuer row, never netting approval/cancel."""
    use_day = parse_day(pick(values, mapping, "date", 1), datemode)
    card = digits(pick(values, mapping, "card", 2))[-4:]
    approval = digits(pick(values, mapping, "approval", 3))
    merchant = txt(pick(values, mapping, "merchant", 4))
    country = txt(pick(values, mapping, "country", 10))
    # In the supplied overseas format, ``원화금액`` is the signed transaction
    # amount and ``청구금액`` is that amount plus the separately displayed fee.
    # The former is the card event amount; the latter remains an audit field.
    # A true explicit approval/cancellation header would take precedence.
    approval_amount = won(pick(values, mapping, "approval_amount", None))
    krw_amount = won(pick(values, mapping, "krw_amount", 6))
    cancel_amount = won(pick(values, mapping, "cancel_amount", None))
    billed_amount = won(pick(values, mapping, "billed_amount", 11))
    # In these overseas issuer files an explicitly provided cancellation field
    # may coexist with the approved amount.  If no cancellation header exists,
    # a negative billed value is itself the cancellation event, not an approval.
    events: list[tuple[str, int, str]] = []
    if "cancel_amount" in mapping:
        if approval_amount:
            events.append(("approval", abs(approval_amount), "approval_amount_column"))
        if cancel_amount:
            events.append(("cancel", -abs(cancel_amount), "cancel_amount_column"))
        # A negative approval column represents a cancellation in some exports.
        if approval_amount < 0:
            events = [("cancel", -abs(approval_amount), "negative_approval_amount_column")]
    elif krw_amount:
        events.append(("approval" if krw_amount > 0 else "cancel", krw_amount, "signed_krw_amount_column"))

    base = {
        "source_file": source.name,
        "source_sha256": sha256(source),
        "sheet": sheet,
        "source_row_1based": row_1based,
        "use_date": use_day,
        "card4": card,
        "approval_no": approval,
        "merchant": merchant,
        "country": country,
        "raw_approval_amount": approval_amount,
        "raw_krw_amount": krw_amount,
        "raw_cancel_amount": cancel_amount,
        "raw_billed_amount": billed_amount,
        "source_row_event_count": len(events),
    }
    return [{**base, "event_index": pos, "event_type": typ, "amount_krw": amount, "event_basis": basis}
            for pos, (typ, amount, basis) in enumerate(events, start=1)]


def main() -> None:
    OUTDIR.mkdir(parents=True, exist_ok=True)
    all_events: list[dict[str, Any]] = []
    dual_rows: list[dict[str, Any]] = []
    file_reports: list[dict[str, Any]] = []

    for path in source_files():
        book = xlrd.open_workbook(path)
        file_events: list[dict[str, Any]] = []
        transaction_rows = 0
        sheet_reports: list[dict[str, Any]] = []
        for sh in book.sheets():
            header_row = 0
            mapping = column_map(sh.row_values(header_row))
            sheet_tx = 0
            sheet_events = 0
            for row_idx in range(header_row + 1, sh.nrows):
                values = sh.row_values(row_idx)
                if not is_transaction(values, mapping, book.datemode):
                    continue
                transaction_rows += 1
                sheet_tx += 1
                expanded = expand_row(values, mapping, source=path, sheet=sh.name,
                                      row_1based=row_idx + 1, datemode=book.datemode)
                file_events.extend(expanded)
                all_events.extend(expanded)
                sheet_events += len(expanded)
                if len(expanded) == 2:
                    dual_rows.append({
                        "source_file": path.name, "sheet": sh.name,
                        "source_row_1based": row_idx + 1,
                        "approval_no": expanded[0]["approval_no"],
                        "merchant": expanded[0]["merchant"],
                        "approval_krw": next(x["amount_krw"] for x in expanded if x["event_type"] == "approval"),
                        "cancel_krw": next(x["amount_krw"] for x in expanded if x["event_type"] == "cancel"),
                    })
            sheet_reports.append({"sheet": sh.name, "rows": sh.nrows, "columns": sh.ncols,
                                  "header": [txt(x) for x in sh.row_values(header_row)],
                                  "column_map": mapping, "transaction_rows": sheet_tx,
                                  "generated_events": sheet_events})
        by_type = Counter(x["event_type"] for x in file_events)
        positives = sum(x["amount_krw"] for x in file_events if x["event_type"] == "approval")
        negatives = sum(x["amount_krw"] for x in file_events if x["event_type"] == "cancel")
        file_reports.append({
            "file": path.name, "path": str(path), "bytes": path.stat().st_size, "sha256": sha256(path),
            "source_transaction_rows": transaction_rows, "generated_events": len(file_events),
            "approval_events": by_type["approval"], "cancel_events": by_type["cancel"],
            "approval_krw": positives, "cancel_krw": negatives, "net_krw": positives + negatives,
            "two_event_source_rows": sum(1 for x in dual_rows if x["source_file"] == path.name),
            "sheets": sheet_reports,
        })

    fields = list(all_events[0]) if all_events else []
    csv_buf = io.StringIO(newline="")
    writer = csv.DictWriter(csv_buf, fieldnames=fields)
    writer.writeheader()
    writer.writerows(all_events)
    atomic_text(OUT_CSV, csv_buf.getvalue())

    by_type = Counter(x["event_type"] for x in all_events)
    approval_total = sum(x["amount_krw"] for x in all_events if x["event_type"] == "approval")
    cancel_total = sum(x["amount_krw"] for x in all_events if x["event_type"] == "cancel")
    report = {
        "scope": "Independent read-only reparse. Central ledger and source XLS files were not modified.",
        "date_range_requested": [START.isoformat(), END.isoformat()],
        "rule": "Each source row expands to 0, 1, or 2 immutable card events; approval and cancellation are never netted or dropped.",
        "files": file_reports,
        "aggregate": {
            "source_transaction_rows": sum(x["source_transaction_rows"] for x in file_reports),
            "generated_events": len(all_events), "approval_events": by_type["approval"],
            "cancel_events": by_type["cancel"], "approval_krw": approval_total,
            "cancel_krw": cancel_total, "net_krw": approval_total + cancel_total,
            "two_event_source_rows": len(dual_rows),
        },
        "two_event_source_rows": dual_rows,
        "artifacts": {"json": str(OUT_JSON), "detail_csv": str(OUT_CSV)},
    }
    atomic_text(OUT_JSON, json.dumps(report, ensure_ascii=False, indent=2) + "\n")

    # Persistence verification immediately after atomic replace.
    with OUT_JSON.open(encoding="utf-8-sig") as handle:
        reloaded = json.load(handle)
    with OUT_CSV.open(encoding="utf-8-sig", newline="") as handle:
        count = sum(1 for _ in csv.DictReader(handle))
    if reloaded["aggregate"]["generated_events"] != len(all_events) or count != len(all_events):
        raise RuntimeError("artifact re-read count mismatch")
    print(json.dumps({"aggregate": report["aggregate"], "json": {"path": str(OUT_JSON), "bytes": OUT_JSON.stat().st_size, "sha256": sha256(OUT_JSON)}, "csv": {"path": str(OUT_CSV), "bytes": OUT_CSV.stat().st_size, "sha256": sha256(OUT_CSV)}}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
