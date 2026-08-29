from __future__ import annotations

import csv
import io
import json
from pathlib import Path

from .contracts import canonical_text

SIDECAR_FIELDS = ["key", "amount_krw", "lane", "sign"]


def export_sidecar_rows(reader) -> list[dict]:
    rows = []
    for payment in reader.queue_rows(limit=100000):
        key = payment.get("event_key") or str(payment.get("rowid"))
        amount = payment.get("amount_krw")
        sign = -1 if (isinstance(amount, int) and amount < 0) else 1
        rows.append(
            {
                "key": key,
                "amount_krw": abs(int(amount)) if amount is not None else 0,
                "lane": "",
                "sign": sign,
            }
        )
    return rows


def write_csv(rows, path) -> Path:
    path = Path(path)
    with open(path, "w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=SIDECAR_FIELDS)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)
    return path


def read_sidecar(path) -> list[dict]:
    path = Path(path)
    if path.suffix.lower() == ".xlsx":
        from openpyxl import load_workbook

        workbook = load_workbook(str(path), read_only=True, data_only=True)
        sheet = workbook.active
        iterator = sheet.iter_rows(values_only=True)
        header = [str(cell) for cell in next(iterator)]
        records = []
        for values in iterator:
            record = dict(zip(header, values))
            records.append(
                {
                    "key": str(record["key"]),
                    "amount_krw": int(record["amount_krw"]),
                    "lane": "" if record.get("lane") is None else str(record["lane"]),
                    "sign": int(record["sign"]),
                }
            )
        workbook.close()
        return records
    with open(path, "r", encoding="utf-8-sig", newline="") as handle:
        return [
            {
                "key": row["key"],
                "amount_krw": int(row["amount_krw"]),
                "lane": row.get("lane") or "",
                "sign": int(row["sign"]),
            }
            for row in csv.DictReader(handle)
        ]


def compare_rows(baseline_rows, other_rows) -> dict:
    base = {row["key"]: row for row in baseline_rows}
    other = {row["key"]: row for row in other_rows}
    problems = []
    missing = sorted(set(base) - set(other))
    extra = sorted(set(other) - set(base))
    mismatched = []
    for key in sorted(set(base) & set(other)):
        b, o = base[key], other[key]
        if int(b["amount_krw"]) != int(o["amount_krw"]):
            mismatched.append({"key": key, "field": "amount_krw"})
        elif int(b["sign"]) != int(o["sign"]):
            mismatched.append({"key": key, "field": "sign"})
    if missing:
        problems.append({"type": "missing_in_other", "keys": missing[:50]})
    if extra:
        problems.append({"type": "extra_in_other", "keys": extra[:50]})
    if mismatched:
        problems.append({"type": "field_mismatch", "items": mismatched[:50]})
    return {
        "ok": not problems,
        "baseline_count": len(base),
        "other_count": len(other),
        "problems": problems,
    }


def diff_json(before: dict, after: dict) -> dict:
    keys = sorted(set(before) | set(after))
    changes = []
    for key in keys:
        b, a = before.get(key), after.get(key)
        if canonical_text(b) != canonical_text(a):
            changes.append({"key": key, "as_is": b, "to_be": a})
    return {"changed_count": len(changes), "changes": changes}
