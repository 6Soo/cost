from __future__ import annotations

import argparse
import json
import sqlite3
from collections import defaultdict
from datetime import date
from pathlib import Path

from openpyxl import Workbook, load_workbook
from openpyxl.formatting.rule import FormulaRule
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.worksheet.table import Table, TableStyleInfo
from openpyxl.utils import get_column_letter


PACKAGE_C_PATHS = {
    "current_card_trip_cluster_registry_exact",
    "current_card_travel_activity_placeholder",
    "current_card_reservation_placeholder",
    "current_card_inferred_external_target",
    "current_card_geography_context_exact_2026",
    "manual_travel_tab_reversal_exact",
    "manual_travel_tab_reversal_mn_target_invariant",
}

HEADERS = [
    "payment_id",
    "external_key",
    "source_event_id",
    "identity_fingerprint",
    "source_system",
    "occurred_on",
    "posted_on",
    "merchant",
    "business_category",
    "country",
    "currency",
    "foreign_amount",
    "amount_krw",
    "approval_number",
    "transaction_type",
    "record_version",
    "account",
    "cost_type",
    "allocation_target",
    "rule_path",
    "classification_source",
    "confidence",
    "confidence_label",
    "schedule_status",
    "conflict_count",
    "review_status",
    "review_outcome",
    "review_reason",
    "decision_status",
    "axis_finality_status",
    "finality_vetoes",
    "structural_rule_admitted",
    "plan_count",
    "allocation_count",
    "journal_count",
    "reversal_inheritance_count",
    "result_lane",
    "result_status",
    "classification_rationale",
    "review_rationale",
]


def unique_join(values: list[object]) -> str:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        text = str(value or "").strip()
        if text and text not in seen:
            result.append(text)
            seen.add(text)
    return "; ".join(result)


def iso_date(value: object) -> object:
    text = str(value or "")
    try:
        return date.fromisoformat(text)
    except (TypeError, ValueError):
        return text


def target_path(rule_path: object) -> str:
    parts = str(rule_path or "").split("|")
    return parts[1] if len(parts) > 1 else ""


def build_rows(db: sqlite3.Connection) -> list[list[object]]:
    payments = db.execute(
        """SELECT id,external_key,source_event_id,identity_fingerprint,
                  payment_method_id,source_system,occurred_on,posted_on,
                  merchant,business_category,country,currency,foreign_amount,
                  amount_krw,approval_number,transaction_type,record_version
           FROM payment_transactions ORDER BY id"""
    ).fetchall()

    decisions: dict[int, dict[str, list[object]]] = defaultdict(
        lambda: defaultdict(list)
    )
    decision_statuses: dict[int, list[object]] = defaultdict(list)
    for row in db.execute(
        """SELECT target_id,dimension,value,decision_status
           FROM current_classification_decisions
           WHERE target_type='payment'
           ORDER BY target_id,id"""
    ):
        payment_id = int(row[0])
        decisions[payment_id][str(row[1])].append(row[2])
        decision_statuses[payment_id].append(row[3])

    predictions: dict[int, list[sqlite3.Row]] = defaultdict(list)
    db.row_factory = sqlite3.Row
    for row in db.execute(
        """SELECT payment_id,rule_path,confidence,confidence_label,
                  schedule_status,conflict_count,axis_evidence_json,rationale
           FROM direct_high_coverage_classifier_predictions
           ORDER BY payment_id,prediction_id"""
    ):
        predictions[int(row["payment_id"])].append(row)

    reviews = {
        int(row[0]): row
        for row in db.execute(
            """SELECT payment_id,outcome,reason_code,rationale,
                      review_status
               FROM allocation_review_cases"""
        )
    }
    plans = {
        int(row[0]): (int(row[1]), unique_join(list(row[2:])))
        for row in db.execute(
            """SELECT payment_id,COUNT(*),GROUP_CONCAT(DISTINCT plan_status)
               FROM allocation_plans GROUP BY payment_id"""
        )
    }
    allocations = {
        int(row[0]): int(row[1])
        for row in db.execute(
            """SELECT payment_id,COUNT(*)
               FROM current_cost_allocations GROUP BY payment_id"""
        )
    }
    journals = {
        int(row[0]): int(row[1])
        for row in db.execute(
            """SELECT a.payment_id,COUNT(*)
               FROM current_cost_allocations a
               JOIN journal_entries j ON j.allocation_id=a.id
               GROUP BY a.payment_id"""
        )
    }
    inheritances = {
        int(row[0]): int(row[1])
        for row in db.execute(
            """SELECT reversal_payment_id,COUNT(*)
               FROM direct_high_coverage_reversal_inheritance
               GROUP BY reversal_payment_id"""
        )
    }

    result: list[list[object]] = []
    for payment in payments:
        payment_id = int(payment[0])
        pred_rows = predictions.get(payment_id, [])
        paths = [row["rule_path"] for row in pred_rows]
        path_names = [target_path(path) for path in paths]
        evidence_payloads: list[dict[str, object]] = []
        for pred in pred_rows:
            try:
                payload = json.loads(str(pred["axis_evidence_json"] or "{}"))
            except (TypeError, json.JSONDecodeError):
                payload = {}
            if isinstance(payload, dict):
                evidence_payloads.append(payload)
        finalities = [
            payload.get("row_finality")
            for payload in evidence_payloads
            if isinstance(payload.get("row_finality"), dict)
        ]
        finality = finalities[0] if finalities else {}
        admitted = any(
            path in PACKAGE_C_PATHS
            and any(
                isinstance(item, dict)
                and item.get("structural_rule_admitted") is True
                for item in finalities
            )
            for path in path_names
        )

        review = reviews.get(payment_id)
        review_status = str(review[4]) if review else ""
        allocation_count = allocations.get(payment_id, 0)
        if review_status == "auto_provisional":
            lane = "자동 임시분류"
        elif review_status == "needs_review":
            lane = "사람 확인"
        elif review_status == "confirmed" or allocation_count > 0:
            lane = "최종분류"
        else:
            lane = "미분류"

        decision_map = decisions.get(payment_id, {})
        account = unique_join(decision_map.get("account", []))
        cost_type = unique_join(decision_map.get("cost_type", []))
        allocation_target = unique_join(decision_map.get("allocation_target", []))
        if not allocation_target and pred_rows:
            allocation_target = unique_join([row["allocation_target"] for row in pred_rows])

        rules = unique_join(paths)
        sources = unique_join([str(path).split("|", 1)[0] for path in paths])
        prediction = pred_rows[0] if pred_rows else None
        decision_status = unique_join(decision_statuses.get(payment_id, []))
        plan_count = plans.get(payment_id, (0, ""))[0]
        review_outcome = str(review[1]) if review else ""
        review_reason = str(review[2]) if review else ""
        review_rationale = str(review[3]) if review else ""
        result.append(
            [
                payment_id,
                payment[1],
                payment[2],
                payment[3],
                payment[5],
                iso_date(payment[6]),
                iso_date(payment[7]),
                payment[8],
                payment[9],
                payment[10],
                payment[11],
                payment[12],
                payment[13],
                payment[14],
                payment[15],
                payment[16],
                account,
                cost_type,
                allocation_target,
                rules,
                sources,
                prediction["confidence"] if prediction else None,
                prediction["confidence_label"] if prediction else "",
                prediction["schedule_status"] if prediction else "",
                prediction["conflict_count"] if prediction else None,
                review_status,
                review_outcome,
                review_reason,
                decision_status,
                str(finality.get("status") or ""),
                unique_join(finality.get("vetoes", []) if isinstance(finality, dict) else []),
                "예" if admitted else "아니오",
                plan_count,
                allocation_count,
                journals.get(payment_id, 0),
                inheritances.get(payment_id, 0),
                lane,
                "final" if lane == "최종분류" else "nonfinal",
                prediction["rationale"] if prediction else "",
                review_rationale,
            ]
        )
    return result


def apply_table(sheet, end_row: int, end_col: int, name: str) -> None:
    ref = f"A1:{get_column_letter(end_col)}{end_row}"
    table = Table(displayName=name, ref=ref)
    table.tableStyleInfo = TableStyleInfo(
        name="TableStyleMedium2",
        showFirstColumn=False,
        showLastColumn=False,
        showRowStripes=True,
        showColumnStripes=False,
    )
    sheet.add_table(table)


def style_result_sheet(sheet, rows: list[list[object]]) -> None:
    sheet.freeze_panes = "A2"
    sheet.sheet_view.showGridLines = False
    end_row = len(rows) + 1
    end_col = len(HEADERS)
    header = sheet[1]
    for cell in header:
        cell.fill = PatternFill("solid", fgColor="17365D")
        cell.font = Font(bold=True, color="FFFFFF")
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
    sheet.row_dimensions[1].height =  thirty = 30
    sheet.auto_filter.ref = f"A1:{get_column_letter(end_col)}{end_row}"
    apply_table(sheet, end_row, end_col, "AllResults" if sheet.title == "전체결과" else "NonFinalResults")

    text_headers = {
        "external_key", "source_event_id", "identity_fingerprint", "approval_number",
        "foreign_amount", "currency", "rule_path", "classification_source",
    }
    wrapped = {"merchant", "review_reason", "classification_rationale", "review_rationale", "finality_vetoes"}
    for index, header_name in enumerate(HEADERS, start=1):
        letter = get_column_letter(index)
        column = sheet[f"{letter}2:{letter}{end_row}"]
        if header_name in text_headers:
            for cell in column[0]:
                cell.number_format = "@"
        elif header_name in {"amount_krw", "plan_count", "allocation_count", "journal_count", "reversal_inheritance_count", "conflict_count", "payment_id", "record_version"}:
            for cell in column[0]:
                cell.number_format = "#,##0;[Red](#,##0);-"
                cell.alignment = Alignment(horizontal="right", vertical="top")
        elif header_name == "confidence":
            for cell in column[0]:
                cell.number_format = "0.0%"
                cell.alignment = Alignment(horizontal="right", vertical="top")
        elif header_name in {"occurred_on", "posted_on"}:
            for cell in column[0]:
                cell.number_format = "yyyy-mm-dd"
        for cell in column[0]:
            cell.alignment = Alignment(
                horizontal="left" if header_name not in {"amount_krw", "confidence"} else "right",
                vertical="top",
                wrap_text=header_name in wrapped,
            )

    widths = {
        "payment_id": 11, "external_key": 25, "source_event_id": 28,
        "identity_fingerprint": 24, "source_system": 15, "occurred_on": 13,
        "posted_on": 13, "merchant": 27, "business_category": 16, "country": 12,
        "currency": 10, "foreign_amount": 14, "amount_krw": 14, "approval_number": 18,
        "transaction_type": 14, "record_version": 12, "account": 14, "cost_type": 15,
        "allocation_target": 24, "rule_path": 40, "classification_source": 28,
        "confidence": 12, "confidence_label": 13, "schedule_status": 16,
        "conflict_count": 12, "review_status": 15, "review_outcome": 18,
        "review_reason": 34, "decision_status": 18, "axis_finality_status": 18,
        "finality_vetoes": 32, "structural_rule_admitted": 18, "plan_count": 12,
        "allocation_count": 15, "journal_count": 13, "reversal_inheritance_count": 22,
        "result_lane": 16, "result_status": 13, "classification_rationale": 60,
        "review_rationale": 50,
    }
    for index, header_name in enumerate(HEADERS, start=1):
        sheet.column_dimensions[get_column_letter(index)].width = widths.get(header_name, 15)
    lane_col = get_column_letter(HEADERS.index("result_lane") + 1)
    data_range = f"${lane_col}2:${lane_col}{end_row}"
    sheet.conditional_formatting.add(
        data_range,
        FormulaRule(formula=[f"{lane_col}2=\"최종분류\""], fill=PatternFill("solid", fgColor="E2F0D9")),
    )
    sheet.conditional_formatting.add(
        data_range,
        FormulaRule(formula=[f"{lane_col}2=\"자동 임시분류\""], fill=PatternFill("solid", fgColor="FFF2CC")),
    )
    sheet.conditional_formatting.add(
        data_range,
        FormulaRule(formula=[f"{lane_col}2=\"사람 확인\""], fill=PatternFill("solid", fgColor="FCE4D6")),
    )


def write_result_sheet(sheet, rows: list[list[object]]) -> None:
    sheet.append(HEADERS)
    for row in rows:
        sheet.append(row)
    style_result_sheet(sheet, rows)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    report = json.loads(args.report.read_text(encoding="utf-8"))
    gates = {item["gate"]: item for item in report["gates"]}
    gate5 = gates[5]["actual"]
    db = sqlite3.connect(args.db)
    rows = build_rows(db)
    db.close()

    if len(rows) != int(gate5["candidate_payment_count"]):
        raise RuntimeError("export_row_count_does_not_match_candidate_count")

    args.output.parent.mkdir(parents=True, exist_ok=True)
    workbook = Workbook()
    summary = workbook.active
    summary.title = "요약"
    all_sheet = workbook.create_sheet("전체결과")
    nonfinal_sheet = workbook.create_sheet("비최종")
    checks = workbook.create_sheet("검증")

    write_result_sheet(all_sheet, rows)
    nonfinal_rows = [row for row in rows if row[HEADERS.index("result_status")] == "nonfinal"]
    write_result_sheet(nonfinal_sheet, nonfinal_rows)

    navy = "17365D"
    blue = "D9EAF7"
    green = "E2F0D9"
    yellow = "FFF2CC"
    orange = "FCE4D6"
    thin_gray = Side(style="thin", color="D9E1F2")

    summary.sheet_view.showGridLines = False
    summary.merge_cells("A1:H1")
    summary["A1"] = "비용분류 전체 결과 — package-c 격리 실행"
    summary["A1"].fill = PatternFill("solid", fgColor=navy)
    summary["A1"].font = Font(bold=True, color="FFFFFF", size=14)
    summary["A1"].alignment = Alignment(horizontal="left")
    summary["A2"] = "운영 정본이 아니라 최신 shadow 후보 결과입니다."
    summary["A2"].font = Font(italic=True, color="666666")
    summary["A3"] = "run_id"
    summary["B3"] = report.get("run_id", "")
    summary["D3"] = "출력 기준"
    summary["E3"] = "package-c / 전체 5,328건"
    summary["A4"] = "운영 반영"
    summary["B4"] = "아니오"
    summary["D4"] = "차단 이유"
    summary["E4"] = "HAN equality 없음; Gate6 기준선 없음"

    summary["A6"] = "핵심 수치"
    summary["A6"].fill = PatternFill("solid", fgColor=navy)
    summary["A6"].font = Font(bold=True, color="FFFFFF")
    summary.merge_cells("A6:B6")
    metric_header = ["항목", "현재값"]
    summary["A7"], summary["B7"] = metric_header
    for cell in summary[7][0:2]:
        cell.fill = PatternFill("solid", fgColor=blue)
        cell.font = Font(bold=True)
    lane_col = get_column_letter(HEADERS.index("result_lane") + 1)
    status_col = get_column_letter(HEADERS.index("result_status") + 1)
    admitted_col = get_column_letter(HEADERS.index("structural_rule_admitted") + 1)
    plan_col = get_column_letter(HEADERS.index("plan_count") + 1)
    alloc_col = get_column_letter(HEADERS.index("allocation_count") + 1)
    journal_col = get_column_letter(HEADERS.index("journal_count") + 1)
    inherit_col = get_column_letter(HEADERS.index("reversal_inheritance_count") + 1)
    last_row = len(rows) + 1
    def countif(column: str, criterion: str) -> str:
        return f'=COUNTIF(\'전체결과\'!${column}$2:${column}${last_row},"{criterion}")'
    metrics = [
        ("전체 결제", f"=COUNTA('전체결과'!$A$2:$A${last_row})"),
        ("최종분류", countif(lane_col, "최종분류")),
        ("자동 임시분류", countif(lane_col, "자동 임시분류")),
        ("사람 확인", countif(lane_col, "사람 확인")),
        ("비최종 전체", countif(status_col, "nonfinal")),
        ("미분류", countif(lane_col, "미분류")),
        ("package-c terminal", countif(admitted_col, "예")),
        ("비최종 배분계획", f'=SUMIFS(\'전체결과\'!${plan_col}$2:${plan_col}${last_row},\'전체결과\'!${status_col}$2:${status_col}${last_row},"nonfinal")'),
        ("비최종 배분", f'=SUMIFS(\'전체결과\'!${alloc_col}$2:${alloc_col}${last_row},\'전체결과\'!${status_col}$2:${status_col}${last_row},"nonfinal")'),
        ("비최종 전기", f'=SUMIFS(\'전체결과\'!${journal_col}$2:${journal_col}${last_row},\'전체결과\'!${status_col}$2:${status_col}${last_row},"nonfinal")'),
        ("비최종 환불상속", f'=SUMIFS(\'전체결과\'!${inherit_col}$2:${inherit_col}${last_row},\'전체결과\'!${status_col}$2:${status_col}${last_row},"nonfinal")'),
    ]
    for row_index, (label, formula) in enumerate(metrics, start=8):
        summary.cell(row_index, 1, label)
        summary.cell(row_index, 2, formula)
        summary.cell(row_index, 2).number_format = "#,##0;[Red](#,##0);-"
        summary.cell(row_index, 1).border = Border(bottom=thin_gray)
        summary.cell(row_index, 2).border = Border(bottom=thin_gray)

    summary["D6"] = "게이트 상태"
    summary["D6"].fill = PatternFill("solid", fgColor=navy)
    summary["D6"].font = Font(bold=True, color="FFFFFF")
    summary.merge_cells("D6:H6")
    for cell, value in zip(summary[7][3:8], ["게이트", "상태", "이유", "운영 의미", ""]):
        cell.value = value
        cell.fill = PatternFill("solid", fgColor=blue)
        cell.font = Font(bold=True)
    gate_rows = [
        ("Gate 1", gates[1]["passed"], gates[1]["reason"], "통과"),
        ("Gate 2", gates[2]["passed"], gates[2]["reason"], "통과"),
        ("Gate 3", gates[3]["passed"], gates[3]["reason"], "통과"),
        ("Gate 4", gates[4]["passed"], gates[4]["reason"], "HAN 대조 필요"),
        ("Gate 5", gates[5]["passed"], gates[5]["reason"], "분류 검증 통과"),
        ("Gate 6", gates[6]["passed"], gates[6]["reason"], "기준선 필요"),
        ("Gate 7", gates[7]["passed"], gates[7]["reason"], "통과"),
    ]
    for row_index, (gate, passed, reason, meaning) in enumerate(gate_rows, start=8):
        summary.cell(row_index, 4, gate)
        summary.cell(row_index, 5, "PASS" if passed else "FAIL")
        summary.cell(row_index, 6, reason)
        summary.cell(row_index, 7, meaning)
        summary.cell(row_index, 5).fill = PatternFill("solid", fgColor=green if passed else orange)
        for col in range(4, 8):
            summary.cell(row_index, col).border = Border(bottom=thin_gray)

    summary["D17"] = "임시분류 유형"
    summary["D17"].fill = PatternFill("solid", fgColor=navy)
    summary["D17"].font = Font(bold=True, color="FFFFFF")
    summary.merge_cells("D17:G17")
    for cell, value in zip(summary[18][3:7], ["분류 경로", "자동 임시분류", "사람 확인", "합계"]):
        cell.value = value
        cell.fill = PatternFill("solid", fgColor=blue)
        cell.font = Font(bold=True)
    path_col = get_column_letter(HEADERS.index("rule_path") + 1)
    review_col = get_column_letter(HEADERS.index("review_status") + 1)
    remaining_paths = [
        ("ota_mail_service_period_amount_tolerance_exact", "OTA 금액 확인"),
        ("ota_mail_service_period_exact", "OTA 서비스기간 확인"),
        ("gmail_payment_service_period_evidence", "Gmail 서비스기간 증거"),
        ("foreign_service_period_pending_review", "해외 서비스기간 미확인"),
        ("reversal_policy_fallback", "환불 원거래 연결 확인"),
    ]
    for row_index, (path, label) in enumerate(remaining_paths, start=19):
        summary.cell(row_index, 4, label)
        summary.cell(row_index, 5, f'=COUNTIFS(\'전체결과\'!${path_col}$2:${path_col}${last_row},"*{path}*",\'전체결과\'!${review_col}$2:${review_col}${last_row},"auto_provisional")')
        summary.cell(row_index, 6, f'=COUNTIFS(\'전체결과\'!${path_col}$2:${path_col}${last_row},"*{path}*",\'전체결과\'!${review_col}$2:${review_col}${last_row},"needs_review")')
        summary.cell(row_index, 7, f"=E{row_index}+F{row_index}")
        for col in range(4, 8):
            summary.cell(row_index, col).border = Border(bottom=thin_gray)

    summary.column_dimensions["A"].width = 24
    summary.column_dimensions["B"].width = 18
    summary.column_dimensions["C"].width = 4
    summary.column_dimensions["D"].width = 26
    summary.column_dimensions["E"].width = 18
    summary.column_dimensions["F"].width = 36
    summary.column_dimensions["G"].width = 20
    summary.column_dimensions["H"].width = 4
    for row in range(1, 30):
        summary.row_dimensions[row].height = 22
    summary.freeze_panes = "A7"

    checks.sheet_view.showGridLines = False
    checks.merge_cells("A1:F1")
    checks["A1"] = "결과 검증"
    checks["A1"].fill = PatternFill("solid", fgColor=navy)
    checks["A1"].font = Font(bold=True, color="FFFFFF", size=14)
    check_headers = ["검사", "기대값", "실제값", "결과", "근거", "비고"]
    for index, value in enumerate(check_headers, start=1):
        cell = checks.cell(3, index, value)
        cell.fill = PatternFill("solid", fgColor=blue)
        cell.font = Font(bold=True)
    check_items = [
        ("전체 건수", int(gate5["candidate_payment_count"]), f"='요약'!B8", "전체 결과 행 수"),
        ("최종분류", int(gate5["final_count"]), f"='요약'!B9", "Gate5 final_count"),
        ("자동 임시분류", int(gate5["auto_provisional_count"]), f"='요약'!B10", "임시분류 목표 <= 5"),
        ("사람 확인", int(gate5["human_question_nonfinal_count"]), f"='요약'!B11", "별도 확인 lane"),
        ("비최종 전체", int(gate5["nonfinal_count"]), f"='요약'!B12", "Gate5 nonfinal_count"),
        ("미분류", int(gate5["untriaged_nonfinal_count"]), f"='요약'!B13", "0이어야 함"),
        ("비최종 배분계획", 0, f"='요약'!B15", "비최종 side-effect"),
        ("비최종 배분", 0, f"='요약'!B16", "비최종 side-effect"),
        ("비최종 전기", 0, f"='요약'!B17", "비최종 side-effect"),
        ("비최종 환불상속", 0, f"='요약'!B18", "비최종 side-effect"),
    ]
    for row_index, (label, expected, formula, evidence) in enumerate(check_items, start=4):
        checks.cell(row_index, 1, label)
        checks.cell(row_index, 2, expected)
        checks.cell(row_index, 3, formula)
        checks.cell(row_index, 4, f'=IF(B{row_index}=C{row_index},"OK","확인 필요")')
        checks.cell(row_index, 5, evidence)
        checks.cell(row_index, 6, "package-c 최신 격리 실행")
        checks.cell(row_index, 2).number_format = "#,##0;[Red](#,##0);-"
        checks.cell(row_index, 3).number_format = "#,##0;[Red](#,##0);-"
        checks.cell(row_index, 4).fill = PatternFill("solid", fgColor=green)
        for col in range(1, 7):
            checks.cell(row_index, col).border = Border(bottom=thin_gray)
    checks["A16"] = "운영 반영 판정"
    checks["A16"].fill = PatternFill("solid", fgColor=navy)
    checks["A16"].font = Font(bold=True, color="FFFFFF")
    checks["B16"] = "차단"
    checks["C16"] = "Gate4 HAN equality 없음 / Gate6 baseline 없음"
    checks["A17"] = "저장 범위"
    checks["B17"] = "로컬 격리 결과"
    checks["C17"] = "정본·게시·장부 전기 없음"
    for col, width in enumerate([24, 16, 18, 14, 28, 26], start=1):
        checks.column_dimensions[get_column_letter(col)].width = width
    checks.freeze_panes = "A4"
    checks.auto_filter.ref = "A3:F13"

    for sheet in (summary, checks):
        for row in sheet.iter_rows():
            for cell in row:
                if cell.value is not None and cell.alignment == Alignment():
                    cell.alignment = Alignment(vertical="top", wrap_text=True)

    workbook.calculation.fullCalcOnLoad = True
    workbook.calculation.forceFullCalc = True
    workbook.calculation.calcMode = "auto"
    workbook.properties.title = "비용분류 전체 결과 package-c"
    workbook.properties.subject = "최신 shadow 후보 결과"
    workbook.save(args.output)

    # Structural verification without printing row-level data.
    check = load_workbook(args.output, read_only=True, data_only=False)
    if check.sheetnames != ["요약", "전체결과", "비최종", "검증"]:
        raise RuntimeError("unexpected_sheet_layout")
    if check["전체결과"].max_row != len(rows) + 1:
        raise RuntimeError("whole_result_row_count_mismatch")
    if check["비최종"].max_row != len(nonfinal_rows) + 1:
        raise RuntimeError("nonfinal_row_count_mismatch")
    if not str(check["검증"]["C4"].value).startswith("="):
        raise RuntimeError("verification_formula_missing")
    check.close()
    print("output", args.output)
    print("whole_result_rows", len(rows))
    print("nonfinal_rows", len(nonfinal_rows))
    print("auto_provisional", gate5["auto_provisional_count"])


if __name__ == "__main__":
    main()
