"""Independent, read-only revalidation of the five Hana Q1/Q2 exports.

The report expands every source row into an immutable card event.  It compares
against the master ledger first and uses the current classified view plus the
G/H raw snapshots as corroboration only.  It never mutates a source workbook
or any central ledger file.
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

import openpyxl
import xlrd

ROOT = Path(__file__).resolve().parents[1]
DOWNLOAD = Path(
    os.environ.get("HANA_XLS_DIR", ROOT / "inputs" / "hana_q1q2")
).expanduser().resolve()
INPUTS = sorted(DOWNLOAD.glob("*하나카드*해외_*_2026_Q1Q2.xls"))
OUTDIR = ROOT / "outputs" / "hana_q1q2_revalidation"
RESULT = OUTDIR / "rematch_result.json"
DETAIL = OUTDIR / "rematch_detail.csv"
MASTER = ROOT / "ledger" / "master_ledger.csv"
CLASSIFIED = ROOT / "ledger" / "data" / "classified_v14.csv"
RAW_FILES = [ROOT / "ledger" / "newcard" / "conv" / name for name in ("G.xlsx", "H.xlsx")]
START, END = date(2026, 1, 1), date(2026, 6, 30)


def txt(v: object) -> str:
    if v is None:
        return ""
    if isinstance(v, float) and v.is_integer():
        return str(int(v))
    return str(v).strip()


def num(v: object) -> int:
    try:
        return int(round(float(txt(v).replace(",", ""))))
    except ValueError:
        return 0


def digits(v: object) -> str:
    return re.sub(r"\D", "", txt(v))


def normalized_approval(v: object) -> str:
    # Hana prints six digit values, but central data may have dropped leading 0.
    return digits(v).lstrip("0") or "0" if digits(v) else ""


def merchant(v: object) -> str:
    return re.sub(r"[^A-Z0-9가-힣]", "", txt(v).upper())


def parse_date(v: object) -> str:
    s = txt(v)
    for fmt in ("%Y.%m.%d", "%Y-%m-%d", "%Y/%m/%d"):
        try:
            return datetime.strptime(s[:10], fmt).date().isoformat()
        except ValueError:
            pass
    return ""


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def atomic_write(path: Path, body: str) -> None:
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(body, encoding="utf-8-sig", newline="")
    os.replace(temp, path)


def date_in_scope(s: str) -> bool:
    try:
        d = date.fromisoformat(s)
        return START <= d <= END
    except ValueError:
        return False


def master_index():
    approval_index, support_index = defaultdict(list), defaultdict(list)
    total = hana = q1q2 = 0
    with MASTER.open(encoding="utf-8-sig", newline="") as fh:
        for r in csv.DictReader(fh):
            total += 1
            if r.get("카드사") != "하나":
                continue
            hana += 1
            use = txt(r.get("승인일"))
            if not date_in_scope(use):
                continue
            q1q2 += 1
            c4 = digits(r.get("카드4"))[-4:]
            ap = normalized_approval(r.get("승인번호"))
            signed = num(r.get("원화금액"))
            # The master stores cancellation as positive amount plus 취소여부.
            cancel = txt(r.get("취소여부")) == "취소"
            amount = -abs(signed) if cancel else abs(signed)
            event_kind = "cancel" if cancel else "normal"
            rec = {"key": txt(r.get("거래키")), "use_date": use, "card4": c4,
                   "approval": ap, "merchant": txt(r.get("가맹점")), "amount": amount,
                   "event_kind": event_kind}
            if ap and c4:
                approval_index[(c4, ap, event_kind)].append(rec)
            support_index[(c4, use, amount, merchant(rec["merchant"]))].append(rec)
    return approval_index, support_index, {"rows": total, "hana_rows": hana, "hana_q1q2_rows": q1q2}


def classified_index():
    idx = defaultdict(list)
    total = hana = 0
    with CLASSIFIED.open(encoding="utf-8-sig", newline="") as fh:
        for r in csv.DictReader(fh):
            total += 1
            if r.get("src") != "HAN":
                continue
            hana += 1
            use = txt(r.get("use_date"))
            if not date_in_scope(use):
                continue
            c4 = digits(r.get("card4"))[-4:]
            ap = normalized_approval(r.get("appr"))
            event_kind = "cancel" if txt(r.get("cancel")).lower() == "true" else "normal"
            if ap and c4:
                idx[(c4, ap, event_kind)].append(txt(r.get("uid")))
    return idx, {"rows": total, "hana_rows": hana}


def raw_index():
    idx = defaultdict(list)
    counts = {}
    for path in RAW_FILES:
        wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
        ws = wb[wb.sheetnames[0]]
        n = 0
        for rownum, row in enumerate(ws.iter_rows(values_only=True), start=1):
            # The established G/H layout starts actual transactions at row 7.
            if rownum < 7 or len(row) < 19:
                continue
            c4, ap = digits(row[3])[-4:], normalized_approval(row[4])
            if not c4 or not ap:
                continue
            normal, cancelled = num(row[5]), num(row[6])
            if normal:
                idx[(c4, ap, "normal")].append(f"{path.name}:{rownum}")
                n += 1
            if cancelled:
                idx[(c4, ap, "cancel")].append(f"{path.name}:{rownum}")
                n += 1
        counts[path.name] = n
        wb.close()
    return idx, counts


def input_events():
    # The five issuer exports contain one already-signed event per displayed row.
    # There is no time field and no separate cancellation column, so a negative
    # billed amount is the cancellation event.  Every row remains an event.
    seen = defaultdict(list)
    all_events, file_meta = [], []
    for path in INPUTS:
        book = xlrd.open_workbook(path)
        source_rows = []
        for sheet_name in book.sheet_names():
            sh = book.sheet_by_name(sheet_name)
            for i in range(1, sh.nrows):
                r = sh.row_values(i)
                if len(r) < 12 or not txt(r[0]):
                    continue
                use, c4, ap = parse_date(r[1]), digits(r[2])[-4:], normalized_approval(r[3])
                amount, local = num(r[11]), num(r[5])
                mer, country = txt(r[4]), txt(r[10])
                # Footer/summaries have no coherent event fields.
                # Issuer exports append two summary/footer rows.  Their row
                # number exists, but they have neither date nor card nor
                # merchant and must not become zero-value card events.
                if not use and not c4 and not mer and amount == 0:
                    continue
                kind = "cancel" if amount < 0 else "normal"
                ev = {"source_file": path.name, "sheet": sheet_name,
                      "source_row_1based": i + 1, "use_date": use, "card4": c4,
                      "approval_no": ap, "merchant": mer, "merchant_key": merchant(mer),
                      "local_amount": local, "country": country, "billed_krw": amount,
                      "event_kind": kind}
                ev["input_event_key"] = (c4, ap, kind, use, ev["merchant_key"], amount)
                seen[ev["input_event_key"]].append(ev)
                source_rows.append(ev)
                all_events.append(ev)
        file_meta.append({"file": path.name, "path": str(path), "bytes": path.stat().st_size,
                          "sha256": sha256(path), "transaction_rows": len(source_rows),
                          "event_rows": len(source_rows), "cards": sorted({x["card4"] for x in source_rows}),
                          "use_date_min": min((x["use_date"] for x in source_rows if x["use_date"]), default=""),
                          "use_date_max": max((x["use_date"] for x in source_rows if x["use_date"]), default="")})
    return all_events, file_meta, seen


def main():
    OUTDIR.mkdir(parents=True, exist_ok=True)
    if len(INPUTS) != 5:
        raise RuntimeError(f"Expected exactly 5 input XLS files, found {len(INPUTS)}")
    master_by_ap, master_support, master_counts = master_index()
    classified_by_ap, classified_counts = classified_index()
    raw_by_ap, raw_counts = raw_index()
    events, files, input_duplicates = input_events()
    output = []
    for ev in events:
        ap_key = (ev["card4"], ev["approval_no"], ev["event_kind"])
        support_key = (ev["card4"], ev["use_date"], ev["billed_krw"], ev["merchant_key"])
        masters = master_by_ap.get(ap_key, []) if ev["approval_no"] else []
        exact_masters = [x for x in masters if x["amount"] == ev["billed_krw"]]
        # Card/export files are captured at different stages (authorisation
        # versus billed settlement) and their KRW values can differ by fees or
        # exchange settlement.  The issuer's card4+approval+event-kind is the
        # identity key; amount variance alone is a diagnostic, not a duplicate
        # or conflict.  A conflict needs multiple incompatible central events
        # for that same stable issuer key.
        unique_master_events = {(x["key"], x["amount"], x["use_date"], merchant(x["merchant"])) for x in masters}
        raw_hits, class_hits = raw_by_ap.get(ap_key, []), classified_by_ap.get(ap_key, [])
        duplicate_count = len(input_duplicates[ev["input_event_key"]])
        if not ev["use_date"] or not ev["card4"] or not ev["merchant"] or ev["billed_krw"] == 0:
            status, reason = "review", "required_event_field_missing"
        elif not date_in_scope(ev["use_date"]):
            status, reason = "review", "outside_requested_date_range"
        elif duplicate_count > 1:
            status, reason = "conflict", "duplicate_source_event_key_across_input_files"
        elif not ev["approval_no"]:
            # No issuer approval: support data may narrow investigation, never auto-dedup.
            status, reason = "review", "approval_number_missing"
        elif len(unique_master_events) > 1:
            status, reason = "conflict", "multiple_central_master_events_share_same_stable_issuer_key"
        elif masters:
            status = "existing"
            reason = ("master_exact_card_approval_event_kind_amount" if exact_masters
                      else "master_stable_card_approval_event_kind_match_settlement_amount_variance")
        elif raw_hits or class_hits:
            # A snapshot-only match indicates an integration inconsistency.  Do not
            # add a second master event without resolving why master lacks it.
            status, reason = "conflict", "central_snapshot_match_but_master_missing"
        elif master_support.get(support_key):
            status, reason = "review", "approval_differs_but_date_card_amount_merchant_support_match"
        else:
            status, reason = "new", "no_master_or_central_snapshot_match_by_stable_event_key"
        rec = {**ev, "disposition": status, "reason": reason,
               "master_keys": "|".join(x["key"] for x in masters),
               "master_amounts": "|".join(str(x["amount"]) for x in masters),
               "raw_snapshot_refs": "|".join(raw_hits),
               "classified_uids": "|".join(class_hits),
               "support_master_keys": "|".join(x["key"] for x in master_support.get(support_key, [])),
               "merge_eligible": status == "new"}
        # tuple key is not serializable and not useful in the CSV.
        rec.pop("input_event_key", None)
        output.append(rec)

    counter = Counter(x["disposition"] for x in output)
    amounts = {k: sum(x["billed_krw"] for x in output if x["disposition"] == k) for k in sorted(counter)}
    event_counts = Counter(x["event_kind"] for x in output)
    merge = [x for x in output if x["merge_eligible"]]
    result = {
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "scope": "read-only independent revalidation; central and source files unchanged",
        "date_range": [START.isoformat(), END.isoformat()],
        "comparison_sources": {
            "master_ledger": {"path": str(MASTER), "sha256": sha256(MASTER), **master_counts},
            "classified_v14": {"path": str(CLASSIFIED), "sha256": sha256(CLASSIFIED), **classified_counts},
            "hana_raw_snapshots": [{"path": str(x), "sha256": sha256(x), "events_indexed": raw_counts[x.name]} for x in RAW_FILES],
        },
        "input_files": files,
        "event_rule": "one XLS row equals one immutable event; negative billed KRW is cancellation; no event is dropped or netted",
        "aggregate": {
            "input_event_rows": len(output), "normal_events": event_counts["normal"], "cancel_events": event_counts["cancel"],
            "input_positive_krw": sum(x["billed_krw"] for x in output if x["billed_krw"] > 0),
            "input_cancel_krw": sum(x["billed_krw"] for x in output if x["billed_krw"] < 0),
            "input_net_krw": sum(x["billed_krw"] for x in output),
            "disposition_counts": dict(sorted(counter.items())), "disposition_amounts_krw": amounts,
            "merge_eligible_count": len(merge), "merge_eligible_positive_krw": sum(x["billed_krw"] for x in merge if x["billed_krw"] > 0),
            "merge_eligible_cancel_krw": sum(x["billed_krw"] for x in merge if x["billed_krw"] < 0),
            "merge_eligible_net_krw": sum(x["billed_krw"] for x in merge),
        },
        "merge_gate": {
            "safe_to_merge_without_user_review": len(merge),
            "blocked_conflicts": counter["conflict"], "review_only": counter["review"],
            "rule": "only disposition=new is merge eligible; conflicts and review remain immutable unmerged candidates"
        },
        "artifacts": {"result_json": str(RESULT), "detail_csv": str(DETAIL)},
    }
    fields = [k for k in output[0] if k not in {"merchant_key"}] if output else []
    buf = io.StringIO(newline="")
    writer = csv.DictWriter(buf, fieldnames=fields, extrasaction="ignore")
    writer.writeheader(); writer.writerows(output)
    atomic_write(DETAIL, buf.getvalue())
    atomic_write(RESULT, json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    # Persisted-artifact verification.
    with DETAIL.open(encoding="utf-8-sig", newline="") as fh:
        if sum(1 for _ in csv.DictReader(fh)) != len(output):
            raise RuntimeError("detail CSV reread count mismatch")
    with RESULT.open(encoding="utf-8-sig") as fh:
        persisted = json.load(fh)
    if persisted["aggregate"]["input_event_rows"] != len(output):
        raise RuntimeError("result JSON reread count mismatch")
    # A JSON document cannot contain a stable hash of itself.  Persist the CSV
    # checksum in the report; the caller records the final JSON file hash after
    # this last atomic write.
    result["artifact_checksums"] = {"detail_csv": {"bytes": DETAIL.stat().st_size, "sha256": sha256(DETAIL)}}
    atomic_write(RESULT, json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    # Re-read once more because checksums were added in the final atomic write.
    json.loads(RESULT.read_text(encoding="utf-8-sig"))
    print(json.dumps(result["aggregate"], ensure_ascii=False))


if __name__ == "__main__":
    main()
