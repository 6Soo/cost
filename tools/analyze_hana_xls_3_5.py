"""Read-only reconciliation for Hana overseas export files 3, 4, and 5.

The script intentionally writes only its two audit artifacts below ``outputs``.
It never mutates the input XLS files or the classified ledger.
"""
from __future__ import annotations

import csv
import hashlib
import json
import os
import re
from collections import Counter, defaultdict
from datetime import date, datetime
from pathlib import Path

import xlrd

ROOT = Path(__file__).resolve().parents[1]
INPUTS = [
    Path(r"D:\DownLoad\주식회사 숲길여행_하나카드_해외_3_2026_Q1Q2.xls"),
    Path(r"D:\DownLoad\주식회사 숲길여행_하나카드_해외_4_2026_Q1Q2.xls"),
    Path(r"D:\DownLoad\주식회사 숲길여행_하나카드_해외_5_2026_Q1Q2.xls"),
]
OUTDIR = ROOT / "outputs" / "hana_q1q2_parallel"
DETAIL = OUTDIR / "files_3_5_detail.csv"
RESULT = OUTDIR / "files_3_5_result.json"
LEDGER = ROOT / "ledger" / "data" / "classified_v14.csv"
START, END = date(2026, 1, 1), date(2026, 6, 30)


def text(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value).strip()


def money(value: object) -> int:
    s = text(value).replace(",", "")
    try:
        return int(round(float(s)))
    except ValueError:
        return 0


def merchant_key(value: object) -> str:
    return re.sub(r"[^A-Z0-9가-힣]", "", text(value).upper())


def approval(value: object) -> str:
    # Approval number is kept as the issuer printed it, including a leading zero.
    return re.sub(r"\D", "", text(value))


def card4(value: object) -> str:
    digits = re.sub(r"\D", "", text(value))
    return digits[-4:]


def parse_date(value: object) -> date | None:
    s = text(value)
    for fmt in ("%Y.%m.%d", "%Y-%m-%d", "%Y/%m/%d"):
        try:
            return datetime.strptime(s[:10], fmt).date()
        except ValueError:
            pass
    return None


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def atomic_write(path: Path, body: str) -> None:
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(body, encoding="utf-8-sig", newline="")
    os.replace(temp, path)


def ledger_index() -> tuple[dict[tuple[str, str], list[dict]], dict[tuple[str, str, int, str], list[dict]]]:
    by_approval: dict[tuple[str, str], list[dict]] = defaultdict(list)
    by_support: dict[tuple[str, str, int, str], list[dict]] = defaultdict(list)
    with LEDGER.open(encoding="utf-8-sig", newline="") as f:
        for r in csv.DictReader(f):
            if r.get("src") != "HAN":
                continue
            ap = approval(r.get("appr", ""))
            c4 = text(r.get("card4", ""))[-4:]
            if ap:
                by_approval[(c4, ap)].append(r)
            # Currency is empty in the current Hana central import.  This key
            # is retained only as an audit diagnostic; it is never enough to
            # declare a row duplicate without the issuer approval number.
            by_support[(c4, text(r.get("use_date", "")), money(r.get("krw", "")), merchant_key(r.get("merchant", "")))].append(r)
    return by_approval, by_support


def main() -> None:
    OUTDIR.mkdir(parents=True, exist_ok=True)
    by_approval, by_support = ledger_index()
    # Hana can emit an approval and its cancellation with the same approval
    # number.  The issuer approval identifies the relationship, not a reason
    # to discard either card event.  An input-file duplicate must therefore be
    # an exact event duplicate, including signed billed amount and merchant.
    seen_in_inputs: set[tuple[str, str, str, str, int]] = set()
    rows: list[dict] = []
    files: list[dict] = []

    for source in INPUTS:
        book = xlrd.open_workbook(source)
        sheet_summaries = []
        source_rows: list[dict] = []
        for sheet_name in book.sheet_names():
            sh = book.sheet_by_name(sheet_name)
            sheet_summaries.append({"name": sheet_name, "raw_rows": sh.nrows, "columns": sh.ncols})
            for idx in range(1, sh.nrows):
                values = sh.row_values(idx)
                # Exports carry two trailing summary/footer rows whose first
                # column is populated, but which contain no transaction data.
                # They are raw rows, never transaction rows.
                if len(values) < 12 or not text(values[0]) or not any(text(values[i]) for i in (1, 2, 3, 4, 11)):
                    continue
                dt = parse_date(values[1])
                ap = approval(values[3])
                c4 = card4(values[2])
                billed = money(values[11])
                foreign = money(values[5])
                merchant = text(values[4])
                support = (c4, dt.isoformat() if dt else "", billed, merchant_key(merchant))
                key = (c4, ap)
                event_key = (c4, ap, dt.isoformat() if dt else "", merchant_key(merchant), billed)
                existing = by_approval.get(key, []) if ap and c4 else []
                if not dt or not ap or not c4 or not merchant or billed == 0:
                    disposition, reason = "review", "필수 안정키 필드(일자·카드끝4·승인번호·가맹점·청구금액) 누락"
                elif not (START <= dt <= END):
                    disposition, reason = "out_of_range", "요청 범위 2026-01-01~2026-06-30 밖"
                elif event_key in seen_in_inputs:
                    disposition, reason = "file_duplicate", "같은 입력 묶음에 카드끝4+승인번호+일자+가맹점+부호포함 청구금액이 모두 일치"
                elif existing:
                    disposition, reason = "existing", "중앙 하나카드 이벤트에 카드끝4+승인번호 일치"
                else:
                    # No amount-only or merchant-only matching.  A support-key
                    # coincidence is deliberately exposed for later review only.
                    support_hits = by_support.get(support, [])
                    if support_hits:
                        disposition, reason = "review", "승인번호 불일치; 보조키 일치 후보만 있어 자동 중복 처리 금지"
                    else:
                        disposition, reason = "new", "중앙 하나카드 이벤트에 카드끝4+승인번호 없음"
                seen_in_inputs.add(event_key)
                rec = {
                    "source_file": source.name,
                    "sheet": sheet_name,
                    "source_row_1based": idx + 1,
                    "use_date": dt.isoformat() if dt else "",
                    "card4": c4,
                    "approval_no": ap,
                    "merchant": merchant,
                    "foreign_amount": foreign,
                    "billed_krw": billed,
                    "country": text(values[10]),
                    "disposition": disposition,
                    "reason": reason,
                    "existing_uids": "|".join(x.get("uid", "") for x in existing),
                    "support_candidate_uids": "|".join(x.get("uid", "") for x in by_support.get(support, [])),
                }
                source_rows.append(rec)
                rows.append(rec)
        counter = Counter(r["disposition"] for r in source_rows)
        by_status_amount = {k: sum(r["billed_krw"] for r in source_rows if r["disposition"] == k) for k in sorted(counter)}
        transaction_dates = [r["use_date"] for r in source_rows if r["use_date"]]
        positives = sum(r["billed_krw"] for r in source_rows if r["billed_krw"] > 0)
        negatives = sum(r["billed_krw"] for r in source_rows if r["billed_krw"] < 0)
        files.append({
            "file": source.name,
            "path": str(source),
            "sha256": sha256(source),
            "bytes": source.stat().st_size,
            "sheets": sheet_summaries,
            "raw_rows_including_headers": sum(x["raw_rows"] for x in sheet_summaries),
            "transaction_rows": len(source_rows),
            "min_use_date": min(transaction_dates) if transaction_dates else None,
            "max_use_date": max(transaction_dates) if transaction_dates else None,
            "card_last4": sorted({r["card4"] for r in source_rows}),
            "approval_krw": positives,
            "cancel_krw": negatives,
            "net_krw": positives + negatives,
            "disposition_counts": dict(sorted(counter.items())),
            "disposition_amounts_krw": by_status_amount,
        })

    fields = list(rows[0]) if rows else []
    csv_lines: list[str] = []
    import io
    buf = io.StringIO(newline="")
    writer = csv.DictWriter(buf, fieldnames=fields)
    writer.writeheader(); writer.writerows(rows)
    atomic_write(DETAIL, buf.getvalue())
    aggregate_counter = Counter(r["disposition"] for r in rows)
    aggregate_amount = {k: sum(r["billed_krw"] for r in rows if r["disposition"] == k) for k in sorted(aggregate_counter)}
    result = {
        "scope": "read-only comparison; source and central ledger unchanged",
        "requested_date_range": [START.isoformat(), END.isoformat()],
        "central_ledger": str(LEDGER),
        "central_hana_rows_indexed": sum(len(v) for v in by_approval.values()),
        "files": files,
        "aggregate": {
            "transaction_rows": len(rows),
            "disposition_counts": dict(sorted(aggregate_counter.items())),
            "disposition_amounts_krw": aggregate_amount,
            "approval_krw": sum(r["billed_krw"] for r in rows if r["billed_krw"] > 0),
            "cancel_krw": sum(r["billed_krw"] for r in rows if r["billed_krw"] < 0),
            "net_krw": sum(r["billed_krw"] for r in rows),
        },
        "artifacts": {"detail_csv": str(DETAIL), "result_json": str(RESULT)},
    }
    atomic_write(RESULT, json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    # Re-read both artifacts so a report cannot claim a write that did not persist.
    with DETAIL.open(encoding="utf-8-sig", newline="") as f:
        if sum(1 for _ in csv.DictReader(f)) != len(rows):
            raise RuntimeError("detail CSV re-read row count mismatch")
    with RESULT.open(encoding="utf-8-sig") as f:
        reread = json.load(f)
    if reread["aggregate"]["transaction_rows"] != len(rows):
        raise RuntimeError("result JSON re-read row count mismatch")
    print(json.dumps(result["aggregate"], ensure_ascii=False))
    print(DETAIL, DETAIL.stat().st_size)
    print(RESULT, RESULT.stat().st_size)


if __name__ == "__main__":
    main()
