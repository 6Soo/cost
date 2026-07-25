"""v2 확정 배분을 읽는 read-only 병렬 워크북 어댑터와 회귀 리포트."""
from __future__ import annotations

import argparse
import json
import sqlite3
from collections import defaultdict
from pathlib import Path

import openpyxl

from ledger.domain.ledger_db import regression_totals


HEADERS = (
    "거래일자",
    "항목",
    "내용",
    "기간",
    "예약번호",
    "증빙유형",
    "금액(원)",
    "결제 이벤트 키",
    "배분 대상",
)

# 2026-07-25 사용자 확인과 원천 대사로 확정된 legacy 기준선 차이.
# 금액을 숨기지 않고 회귀 리포트에 사유를 붙여 전환 게이트가 설명 가능한 차이만 허용한다.
KNOWN_REGRESSION_CORRECTIONS = {
    ("allocation_targets", "0616_레분토&리시리", -634_113):
        "legacy_duplicate_projection_correction",
    ("allocation_targets", "0424_알펜루트", -60_539):
        "legacy_duplicate_projection_correction",
    ("allocation_targets", "0620_묘코", -665_316):
        "ota_supported_reallocation",
    ("allocation_targets", "0625_아키타", -3_439_871):
        "user_confirmed_reallocation",
    ("allocation_targets", "0630_오제", 4_123_942):
        "user_confirmed_reallocation",
    ("accounts", "항공료", -634_113):
        "legacy_duplicate_projection_correction",
    ("accounts", "식비", -60_539):
        "legacy_duplicate_projection_correction",
}


def workbook_rows(db: sqlite3.Connection) -> list[dict[str, object]]:
    rows = db.execute(
        """
        WITH booking_context AS (
            SELECT
                l.payment_id,
                GROUP_CONCAT(DISTINCT b.booking_number) AS booking_numbers
            FROM current_payment_booking_links l
            JOIN bookings b ON b.id=l.booking_id
            GROUP BY l.payment_id
        ),
        expense_context AS (
            SELECT target_id AS payment_id, value
            FROM current_classification_decisions
            WHERE target_type='payment' AND dimension='expense_type'
        )
        SELECT
            p.occurred_on,
            p.merchant,
            COALESCE(e.value, '') AS content,
            COALESCE(b.service_start_on, '') AS service_start_on,
            COALESCE(b.service_end_on, '') AS service_end_on,
            COALESCE(bc.booking_numbers, '') AS booking_numbers,
            COALESCE(pm.issuer, p.source_system) AS evidence_label,
            a.amount_krw,
            p.external_key,
            t.code AS allocation_target
        FROM current_cost_allocations a
        JOIN payment_transactions p ON p.id=a.payment_id
        JOIN allocation_targets t ON t.id=a.target_id
        LEFT JOIN expense_context e ON e.payment_id=p.id
        LEFT JOIN booking_context bc ON bc.payment_id=p.id
        LEFT JOIN current_payment_booking_links pbl ON pbl.payment_id=p.id
        LEFT JOIN bookings b ON b.id=pbl.booking_id
        LEFT JOIN payment_methods pm ON pm.id=p.payment_method_id
        ORDER BY t.code, p.occurred_on, p.id, a.id
        """
    ).fetchall()
    result: list[dict[str, object]] = []
    seen: set[tuple[object, ...]] = set()
    for row in rows:
        key = (
            row["external_key"],
            row["allocation_target"],
            row["amount_krw"],
            row["booking_numbers"],
        )
        if key in seen:
            continue
        seen.add(key)
        start = str(row["service_start_on"] or "")
        end = str(row["service_end_on"] or "")
        period = start if start and start == end else "_".join(filter(None, (start, end)))
        result.append(
            {
                "거래일자": row["occurred_on"] or "",
                "항목": row["merchant"] or "",
                "내용": row["content"] or "",
                "기간": period,
                "예약번호": row["booking_numbers"] or "",
                "증빙유형": row["evidence_label"] or "",
                "금액(원)": int(row["amount_krw"]),
                "결제 이벤트 키": row["external_key"],
                "배분 대상": row["allocation_target"],
            }
        )
    return result


def _safe_sheet_name(name: str, used: set[str]) -> str:
    clean = "".join("_" if char in r"[]:*?/\\" else char for char in name)[:31] or "미정"
    candidate = clean
    index = 2
    while candidate in used:
        suffix = f"_{index}"
        candidate = clean[: 31 - len(suffix)] + suffix
        index += 1
    used.add(candidate)
    return candidate


def export_parallel_workbook(db: sqlite3.Connection, destination: Path) -> dict[str, object]:
    """운영 양식을 건드리지 않고 v2 행만 별도 검증용 워크북으로 출력한다."""
    rows = workbook_rows(db)
    grouped: dict[str, list[dict[str, object]]] = defaultdict(list)
    for row in rows:
        grouped[str(row["배분 대상"])].append(row)
    workbook = openpyxl.Workbook()
    workbook.remove(workbook.active)
    used: set[str] = set()
    for target, target_rows in sorted(grouped.items()):
        sheet = workbook.create_sheet(_safe_sheet_name(target, used))
        sheet.append(HEADERS)
        for row in target_rows:
            sheet.append([row[header] for header in HEADERS])
        sheet.freeze_panes = "A2"
        sheet.auto_filter.ref = sheet.dimensions
    destination.parent.mkdir(parents=True, exist_ok=True)
    workbook.save(destination)
    return {
        "path": str(destination),
        "sheets": len(grouped),
        "rows": len(rows),
        "amount_krw": sum(int(row["금액(원)"]) for row in rows),
    }


def regression_report(
    db: sqlite3.Connection,
    baseline_path: Path,
) -> dict[str, object]:
    baseline = json.loads(baseline_path.read_text(encoding="utf-8"))
    current = regression_totals(db)
    hana_legacy_correction = int(
        db.execute(
            """
            SELECT COALESCE(SUM(ABS(refund.amount_krw)), 0)
            FROM transaction_relations relation
            JOIN payment_transactions refund
              ON refund.id=relation.transaction_id
            WHERE relation.match_method='hana_same_raw_row_approval_cancel'
              AND relation.relation_status='confirmed'
            """
        ).fetchone()[0]
    )
    sections: dict[str, list[dict[str, object]]] = {}
    for section in ("allocation_targets", "accounts"):
        before = {str(row["key"]): row for row in baseline[section]}
        after = {str(row["key"]): row for row in current[section]}
        differences = []
        for key in sorted(set(before) | set(after)):
            old = int(before.get(key, {}).get("amount_krw") or 0)
            new = int(after.get(key, {}).get("amount_krw") or 0)
            if old == new:
                continue
            classification = (
                "intended_improvement"
                if section == "allocation_targets"
                and key in {"여행_미배정", "0625_아키타"}
                and abs(new - old) == 18_755
                else "v2_error"
            )
            difference = new - old
            known_correction = KNOWN_REGRESSION_CORRECTIONS.get(
                (section, key, difference)
            )
            if known_correction:
                classification = known_correction
            elif section == "allocation_targets" and abs(difference) == 18_755:
                classification = "intended_improvement"
            elif (
                section == "allocation_targets"
                and difference == hana_legacy_correction - 18_755
            ):
                classification = (
                    "legacy_error_correction_and_intended_improvement"
                )
            elif section == "accounts" and difference == hana_legacy_correction:
                classification = "legacy_error_correction"
            differences.append(
                {
                    "key": key,
                    "before": old,
                    "after": new,
                    "difference": new - old,
                    "classification": classification,
                }
            )
        sections[section] = differences
    unexplained = sum(
        1
        for rows in sections.values()
        for row in rows
        if row["classification"] == "v2_error"
    )
    return {
        "differences": sections,
        "hana_legacy_correction_krw": hana_legacy_correction,
        "unexplained_differences": unexplained,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--baseline", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    from ledger.domain.ledger_db import connect, initialize

    db = connect(args.db)
    try:
        initialize(db)
        workbook = export_parallel_workbook(db, args.output)
        regression = regression_report(db, args.baseline)
    finally:
        db.close()
    result = {"workbook": workbook, "regression": regression}
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if regression["unexplained_differences"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
