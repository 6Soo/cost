"""Create a read-only quarterly Google expense paste pack from the COST ledger."""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.google_tsv import EVIDENCE_TYPES, expense_tsv
from app.ota_cash_use import EVIDENCE_LABEL
from tools.quarter_review.pack import ROOT, prepare_rows, read_database


# The shared Google TSV serializer has no required check for these two columns.
# DATE-032 prevents inventing an inferred booking reference. Existing persisted
# service periods are used as stored; absent periods stay blank for every category.
EMPTY_FIELD_ALLOWLIST = {
    "reservation_no": ("DATE-032",),
}
PERIOD_NEXT_REVIEW_CATEGORIES = ("숙박비", "항공료")
OTA_PAYEE_BY_EVIDENCE = {
    EVIDENCE_LABEL["agoda"]: "아고다",
    EVIDENCE_LABEL["klook"]: "클룩",
    EVIDENCE_LABEL["trip"]: "트립닷컴",
}


def _evidence(row: dict) -> str | None:
    value = row.get("evidence") or row.get("evidence_type")
    if value in ("card", "카드"):
        return "card"
    if value in ("receipt", "영수증"):
        return "receipt"
    if value in EVIDENCE_TYPES:
        return value
    if value in (None, "") and isinstance(row.get("transaction_id"), str):
        # A persisted card transaction has card evidence by source type, even when
        # the optional projected evidence_type column is absent.
        return "card"
    return None


def _period_blank_cause(row: dict) -> str:
    """Classify blank periods only where the saved row provides a signal."""
    evidence_fields = (
        "service_period_conflict", "period_conflict", "service_period_candidates",
        "ota_evidence", "booking_ref", "reservation_no",
    )
    if any(row.get(field) for field in evidence_fields):
        return "도구가 근거를 읽지 못함"
    return "저장 기간 없음"


def _period_blank_counts(rows: list[dict]) -> dict:
    counts = defaultdict(Counter)
    for row in rows:
        if not (row.get("period") or row.get("service_period")):
            category = row.get("item") or "항목 없음"
            counts[category][_period_blank_cause(row)] += 1
    return {category: dict(sorted(causes.items()))
            for category, causes in sorted(counts.items())}


def _tsv_row(row: dict) -> dict:
    evidence = _evidence(row)
    period = row.get("period") or row.get("service_period") or ""
    reservation = row.get("reservation_no", row.get("booking_ref")) or ""
    payee = row.get("merchant") or row.get("payee") or OTA_PAYEE_BY_EVIDENCE.get(
        row.get("evidence") or row.get("evidence_type"), "")
    row_id = row.get("transaction_id") or row.get("row_id")
    if not isinstance(row_id, str):
        row_id = ""
    return {
        "transaction_id": row_id,
        "date": row.get("occurred_on") or row.get("approval_date") or row.get("posting_date") or "",
        "payee": payee,
        "category": row.get("item") or "",
        "period": period,
        "reservation_no": reservation,
        "evidence": evidence,
        "amount_krw": row.get("amount_krw"),
        "status": "ready",
    }


def _empty_allowed(row: dict, field: str) -> bool:
    if field == "reservation_no":
        return bool(EMPTY_FIELD_ALLOWLIST.get(field))
    return False


def _export_rows(rows: list[dict]) -> dict:
    shaped = [_tsv_row(row) for row in rows]
    held = []
    for row in shaped:
        for field in ("reservation_no",):
            if not row[field] and not _empty_allowed(row, field):
                held.append({"transaction_id": row["transaction_id"], "reason": "FIELD_MISSING"})
                break
    held.extend(expense_tsv(shaped, layout="rev")["held"])
    # The shared 7-column serializer remains the sole formatter and duplicate guard.
    rejected = {entry["transaction_id"] for entry in held}
    exportable = [row for row in shaped if row["transaction_id"] not in rejected]
    formatted = expense_tsv(exportable, layout="rev")
    reasons = Counter(entry["reason"] for entry in held)
    return {**formatted, "held": held, "held_reason_counts": dict(sorted(reasons.items()))}


def build_paste_pack(data: dict, year: int, quarter: int, out: Path) -> dict:
    trips, rows, excluded = prepare_rows(data, year, quarter, screen_tab_membership=True)
    trip_rows: dict[str, list[dict]] = defaultdict(list)
    quarter_rows: list[dict] = []
    for row in rows:
        destination = row.get("display_tab_id")
        if destination == f"quarter:{year}:{quarter}":
            quarter_rows.append(row)
        else:
            trip_rows[destination].append(row)

    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    summaries = []
    mismatches = []
    for index, trip in enumerate(trips, 1):
        tab_id = trip["tab_id"]
        result = _export_rows(trip_rows[tab_id])
        filename = f"trip-{index:03d}.tsv"
        (out / filename).write_text(result["tsv"], encoding="utf-8", newline="")
        ledger_total = data.get("tab_expense_totals", {}).get(tab_id, 0)
        refund_rows = [row for row in trip_rows[tab_id] if row.get("refund_tab_row")]
        refund_total = sum(row["amount_krw"] for row in refund_rows
                           if type(row.get("amount_krw")) is int)
        comparison_total = ledger_total + refund_total
        matches = comparison_total == result["total_krw"]
        causes = Counter(result["held_reason_counts"])
        causes["NO_LEDGER_ROW"] += excluded.get("no_ledger_by_tab", {}).get(tab_id, 0)
        causes += Counter()
        summary = {
            "tab": trip.get("display_key") or tab_id,
            "file": filename,
            "row_count": result["row_count"],
            "total_krw": result["total_krw"],
            "ledger_total_krw": ledger_total,
            "refund_tab_row_count": len(refund_rows),
            "refund_tab_total_krw": refund_total,
            "comparison_total_krw": comparison_total,
            "total_matches_ledger": matches,
            "held_count": len(result["held"]),
            "held_reasons": result["held_reason_counts"],
            "difference_causes": dict(sorted(causes.items())),
            "period_blank_counts": _period_blank_counts(trip_rows[tab_id]),
        }
        summaries.append(summary)
        if not matches:
            mismatches.append(tab_id)

    other = _export_rows(quarter_rows)
    other_total = data.get("tab_expense_totals", {}).get(f"quarter:{year}:{quarter}", 0)
    (out / f"quarter-{year}Q{quarter}-other.tsv").write_text(other["tsv"], encoding="utf-8", newline="")
    other_refunds = [row for row in quarter_rows if row.get("refund_tab_row")]
    other_refund_total = sum(row["amount_krw"] for row in other_refunds
                             if type(row.get("amount_krw")) is int)
    other_comparison_total = other_total + other_refund_total
    other_match = other_comparison_total == other["total_krw"]
    other_causes = Counter(other["held_reason_counts"])
    other_causes["NO_LEDGER_ROW"] += excluded.get("no_ledger_by_tab", {}).get(
        f"quarter:{year}:{quarter}", 0)
    other_causes += Counter()
    if not other_match:
        mismatches.append(f"quarter:{year}:{quarter}")

    held_by_reason = Counter()
    for summary in summaries:
        held_by_reason.update(summary["held_reasons"])
    held_by_reason.update(other["held_reason_counts"])
    held_count = sum(held_by_reason.values())
    no_ledger_count = excluded.get("no_ledger_row", 0)
    completeness_reasons = Counter()
    if mismatches:
        completeness_reasons["TAB_TOTAL_MISMATCH"] = len(mismatches)
    if no_ledger_count:
        completeness_reasons["NO_LEDGER_ROW"] = no_ledger_count
    completeness_complete = not completeness_reasons and held_count == 0
    summary = {
        "schema": "cost-quarter-paste-pack-v1",
        "period": f"{year}Q{quarter}",
        "trip_count": len(summaries),
        "trips": summaries,
        "quarter_other": {
            "file": f"quarter-{year}Q{quarter}-other.tsv",
            "row_count": other["row_count"],
            "total_krw": other["total_krw"],
            "ledger_total_krw": other_total,
            "refund_tab_row_count": len(other_refunds),
            "refund_tab_total_krw": other_refund_total,
            "comparison_total_krw": other_comparison_total,
            "total_matches_ledger": other_match,
            "held_count": len(other["held"]),
            "held_reasons": other["held_reason_counts"],
            "difference_causes": dict(sorted(other_causes.items())),
            "period_blank_counts": _period_blank_counts(quarter_rows),
        },
        "held_reason_counts": dict(sorted(held_by_reason.items())),
        "held_zero": held_count == 0,
        "held_status": ("보류 0 달성" if held_count == 0 and no_ledger_count == 0
                        else "보류 0 미달"),
        "completeness": "complete" if completeness_complete else "mismatch",
        "mismatch_count": len(mismatches),
        "completeness_reason_counts": dict(sorted(completeness_reasons.items())),
        "tab_totals_match_count": sum(s["total_matches_ledger"] for s in summaries) + other_match,
        "tab_total_count": len(summaries) + 1,
        "excluded_reason_counts": {"NO_LEDGER_ROW": no_ledger_count},
        "empty_field_allowlist": {key: list(value) for key, value in EMPTY_FIELD_ALLOWLIST.items()},
        "period_next_quarter_review_categories": list(PERIOD_NEXT_REVIEW_CATEGORIES),
    }
    (out / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
                                       encoding="utf-8")
    return summary


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host-root", type=Path, required=True)
    parser.add_argument("--year", type=int, required=True)
    parser.add_argument("--quarter", type=int, choices=range(1, 5), required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)
    out = args.out.resolve()
    if out.is_relative_to(ROOT.resolve()):
        parser.error("고객 산출물은 저장소 밖 비공개 폴더에만 둘 수 있습니다.")
    try:
        data = read_database(args.host_root / "data/board.sqlite")
        summary = build_paste_pack(data, args.year, args.quarter, out)
    except (OSError, ValueError, KeyError) as exc:
        print(f"분기 붙여넣기 묶음 생성 실패: {type(exc).__name__}", file=sys.stderr)
        return 2
    # Console output is intentionally count-only; private totals stay in summary.json.
    print(json.dumps({"period": summary["period"], "trip_count": summary["trip_count"],
                      "held_reason_counts": summary["held_reason_counts"],
                      "held_status": summary["held_status"],
                      "mismatch_count": summary["mismatch_count"]}, ensure_ascii=False))
    return 1 if summary["completeness"] != "complete" else 0


if __name__ == "__main__":
    raise SystemExit(main())
