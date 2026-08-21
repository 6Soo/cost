from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
import sys
from collections import Counter, defaultdict
from datetime import date
from pathlib import Path

from openpyxl import Workbook, load_workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.worksheet.table import Table, TableStyleInfo
from openpyxl.utils import get_column_letter


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from ledger.domain.result_selection_rules import (  # noqa: E402
    ALLOWED_EVENT_YEARS,
    EventPeriod,
    event_period_for_targets,
    event_year_label,
    normalize_merchant_name,
    split_targets,
)
from tools.export_package_c_results import HEADERS, build_rows  # noqa: E402


MANUAL_HEADERS = (
    "거래일자",
    "항목",
    "내용",
    "증빙유형",
    "금액",
    "행사기간",
    "행사년도",
    "원본가맹점",
    "분류상태",
    "배분대상",
    "분류경로",
    "결제ID",
    "승인번호",
    "통화",
    "외화금액",
    "배분계획",
    "배분",
    "전기",
    "환불상속",
)

EXCLUDED_HEADERS = (
    "거래일자",
    "원본가맹점",
    "정규화가맹점",
    "금액",
    "배분대상",
    "행사기간",
    "행사년도",
    "기간판정",
    "제외사유",
    "결제ID",
    "승인번호",
)

CARD_LABELS = {
    "KBD": "국민",
    "KBO": "국민",
    "KBO_OVS": "국민",
    "KBO_OVERSEAS": "국민",
    "HAN": "하나",
    "CORP": "기업",
    "MAN": "영수증",
}

NAVY = "17365D"
BLUE = "D9EAF7"
GREEN = "E2F0D9"
YELLOW = "FFF2CC"
ORANGE = "FCE4D6"
GRAY = "666666"
THIN_GRAY = Side(style="thin", color="D9E1F2")

ROW_INDEX = {header: index for index, header in enumerate(HEADERS)}


def _value(row: dict[str, object], name: str) -> object:
    return row.get(name, "")


def _as_int(value: object) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _date_or_text(value: object) -> object:
    if isinstance(value, date):
        return value
    text = str(value or "")
    try:
        return date.fromisoformat(text)
    except ValueError:
        return text


def _load_period_context(
    db: sqlite3.Connection,
) -> tuple[dict[str, tuple[object, object]], dict[str, list[tuple[object, object]]], dict[int, list[object]]]:
    trips = {
        str(row[0]): (row[1], row[2])
        for row in db.execute("SELECT code,starts_on,ends_on FROM trips")
    }
    registries: dict[str, list[tuple[object, object]]] = defaultdict(list)
    for row in db.execute(
        """SELECT target_code,starts_on,ends_on
           FROM direct_high_coverage_trip_registries
           ORDER BY registry_id"""
    ):
        registries[str(row[0])].append((row[1], row[2]))

    evidence: dict[int, list[object]] = defaultdict(list)
    for row in db.execute(
        """SELECT payment_id,axis_evidence_json
           FROM direct_high_coverage_classifier_predictions
           ORDER BY payment_id,prediction_id"""
    ):
        try:
            payload = json.loads(str(row[1] or "{}"))
        except json.JSONDecodeError:
            payload = {}
        evidence[int(row[0])].append(payload)
    return trips, registries, evidence


def _is_nontravel_target(target_value: object) -> bool:
    targets = split_targets(target_value)
    return bool(targets) and all(target == "기타비용" for target in targets)


def _tab_target(target_value: object, period: EventPeriod) -> str:
    targets = split_targets(target_value)
    if (
        len(targets) == 1
        and targets[0] != "기타비용"
        and "행사기간미상" not in targets[0]
        and not targets[0].startswith("여행_미배정")
    ):
        return targets[0]
    if len(targets) > 1:
        return "다중대상_" + "+".join(targets[:2])
    if period.target:
        return period.target
    return "미배정_행사일확인_" + (event_year_label(period) or "미상")


def _period_reason(period: EventPeriod, target_value: object) -> str:
    if _is_nontravel_target(target_value):
        return "기타비용/비여행 대상"
    if period.starts_on is None:
        return "행사기간 없음"
    years = ",".join(str(year) for year in sorted(period.event_years))
    allowed = ",".join(str(year) for year in sorted(ALLOWED_EVENT_YEARS))
    return f"행사년도 {years or '미상'} — 허용연도 {allowed} 밖"


def _evidence_label(source_system: object) -> str:
    text = str(source_system or "").strip()
    return CARD_LABELS.get(text, text or "카드")


def _manual_row(row: dict[str, object], period: EventPeriod) -> list[object]:
    account = str(_value(row, "account") or "").strip()
    cost_type = str(_value(row, "cost_type") or "").strip()
    content = cost_type or account or "미분류"
    return [
        _date_or_text(_value(row, "occurred_on")),
        normalize_merchant_name(_value(row, "merchant")),
        content,
        _evidence_label(_value(row, "source_system")),
        _as_int(_value(row, "amount_krw")),
        period.display,
        event_year_label(period),
        str(_value(row, "merchant") or "").strip(),
        f"{_value(row, 'result_lane')} / {_value(row, 'result_status')}",
        str(_value(row, "allocation_target") or "").strip(),
        str(_value(row, "rule_path") or "").strip(),
        _as_int(_value(row, "payment_id")),
        str(_value(row, "approval_number") or ""),
        str(_value(row, "currency") or ""),
        _value(row, "foreign_amount"),
        _as_int(_value(row, "plan_count")),
        _as_int(_value(row, "allocation_count")),
        _as_int(_value(row, "journal_count")),
        _as_int(_value(row, "reversal_inheritance_count")),
    ]


def _excluded_row(
    row: dict[str, object],
    period: EventPeriod,
    reason: str,
) -> list[object]:
    return [
        _date_or_text(_value(row, "occurred_on")),
        str(_value(row, "merchant") or "").strip(),
        normalize_merchant_name(_value(row, "merchant")),
        _as_int(_value(row, "amount_krw")),
        str(_value(row, "allocation_target") or "").strip(),
        period.display,
        ",".join(str(year) for year in sorted(period.event_years)),
        period.reason,
        reason,
        _as_int(_value(row, "payment_id")),
        str(_value(row, "approval_number") or ""),
    ]


def _safe_sheet_name(name: str, used: set[str]) -> str:
    clean = "".join("_" if char in r"[]:*?/\\" else char for char in name).strip()
    if len(clean) > 31:
        digest = hashlib.sha1(name.encode("utf-8")).hexdigest()[:8]
        clean = clean[:21] + "_" + digest
    clean = clean or "미정"
    candidate = clean[:31]
    index = 2
    while candidate in used:
        suffix = f"_{index}"
        candidate = clean[: 31 - len(suffix)] + suffix
        index += 1
    used.add(candidate)
    return candidate


def _table_name(prefix: str, index: int) -> str:
    return f"{prefix}{index}"[:250]


def _style_header(sheet, row: int, end_col: int) -> None:
    for cell in sheet[row][:end_col]:
        cell.fill = PatternFill("solid", fgColor=NAVY)
        cell.font = Font(bold=True, color="FFFFFF")
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
    sheet.row_dimensions[row].height = 30


def _style_data_sheet(sheet, headers: tuple[str, ...], *, table_prefix: str, table_index: int) -> None:
    end_row = sheet.max_row
    end_col = len(headers)
    sheet.freeze_panes = "A2"
    sheet.sheet_view.showGridLines = False
    _style_header(sheet, 1, end_col)
    if end_row >= 2:
        sheet.auto_filter.ref = f"A1:{get_column_letter(end_col)}{end_row}"
        table = Table(
            displayName=_table_name(table_prefix, table_index),
            ref=f"A1:{get_column_letter(end_col)}{end_row}",
        )
        table.tableStyleInfo = TableStyleInfo(
            name="TableStyleMedium2",
            showFirstColumn=False,
            showLastColumn=False,
            showRowStripes=True,
            showColumnStripes=False,
        )
        sheet.add_table(table)

    for index, header in enumerate(headers, start=1):
        letter = get_column_letter(index)
        width = 15
        if header in {"항목", "원본가맹점", "정규화가맹점"}:
            width = 28
        elif header in {"내용", "배분대상", "분류경로", "제외사유"}:
            width = 30
        elif header in {"행사기간", "승인번호"}:
            width = 22
        elif header in {"거래일자"}:
            width = 13
        elif header in {"금액", "외화금액"}:
            width = 14
        elif header in {"결제ID", "배분계획", "배분", "전기", "환불상속"}:
            width = 12
        sheet.column_dimensions[letter].width = width
        for cell in sheet[letter][1:]:
            cell.alignment = Alignment(
                horizontal="right" if header in {"금액", "외화금액"} else "left",
                vertical="top",
                wrap_text=header in {"내용", "원본가맹점", "분류경로", "제외사유"},
            )
            if header == "거래일자":
                cell.number_format = "yyyy-mm-dd"
            elif header in {"금액", "외화금액", "배분계획", "배분", "전기", "환불상속", "결제ID"}:
                cell.number_format = "#,##0;[Red](#,##0);-"


def _write_data_sheet(
    sheet,
    headers: tuple[str, ...],
    rows: list[list[object]],
    *,
    table_prefix: str,
    table_index: int,
) -> None:
    sheet.append(list(headers))
    for row in rows:
        sheet.append(row)
    _style_data_sheet(sheet, headers, table_prefix=table_prefix, table_index=table_index)
    if rows and "금액" in headers:
        amount_col = headers.index("금액") + 1
        total_row = len(rows) + 3
        sheet.cell(total_row, amount_col - 1, "합계")
        sheet.cell(total_row, amount_col, f"=SUM({get_column_letter(amount_col)}2:{get_column_letter(amount_col)}{len(rows)+1})")
        sheet.cell(total_row, amount_col - 1).font = Font(bold=True)
        sheet.cell(total_row, amount_col).font = Font(bold=True)
        sheet.cell(total_row, amount_col).number_format = "#,##0;[Red](#,##0);-"


def _add_summary(
    sheet,
    *,
    report: dict[str, object],
    source_count: int,
    selected_count: int,
    excluded_count: int,
    selected_amount: int,
    excluded_amount: int,
    year_counts: Counter[str],
    year_amounts: Counter[str],
    excluded_reasons: Counter[str],
    changed_merchants: int,
    sheet_count: int,
    selected_nonfinal_count: int,
    selected_nonfinal_side_effects: dict[str, int],
) -> None:
    sheet.sheet_view.showGridLines = False
    sheet.merge_cells("A1:H1")
    sheet["A1"] = "2026·2027 행사자료 — 수기장부형 여행별 결과"
    sheet["A1"].fill = PatternFill("solid", fgColor=NAVY)
    sheet["A1"].font = Font(bold=True, color="FFFFFF", size=14)
    sheet["A1"].alignment = Alignment(horizontal="left")
    sheet["A2"] = "후보 DB를 변경하지 않고, 행사기간 기준으로 결과만 재구성한 출력본입니다."
    sheet["A2"].font = Font(italic=True, color=GRAY)
    sheet["A3"] = "source run_id"
    sheet["B3"] = str(report.get("run_id") or "")
    sheet["D3"] = "허용 행사년도"
    sheet["E3"] = "2026, 2027"
    sheet["A4"] = "운영 반영"
    sheet["B4"] = "아니오 — 출력 전용"
    sheet["D4"] = "결제일 규칙"
    sheet["E4"] = "2025 결제라도 2026·2027 행사기간이면 포함"

    sheet.merge_cells("A6:B6")
    sheet["A6"] = "핵심 집계"
    sheet["A6"].fill = PatternFill("solid", fgColor=NAVY)
    sheet["A6"].font = Font(bold=True, color="FFFFFF")
    for cell, value in zip(sheet[7][:2], ["항목", "값"]):
        cell.value = value
        cell.fill = PatternFill("solid", fgColor=BLUE)
        cell.font = Font(bold=True)
    metrics = [
        ("원본 후보", source_count),
        ("출력 포함", selected_count),
        ("출력 제외", excluded_count),
        ("포함+제외 검산", selected_count + excluded_count),
        ("포함 금액(원)", selected_amount),
        ("제외 금액(원)", excluded_amount),
        ("여행별 탭 수", sheet_count),
        ("가맹점명 정규화 변경", changed_merchants),
        ("포함 비최종", selected_nonfinal_count),
    ]
    for row_index, (label, value) in enumerate(metrics, start=8):
        sheet.cell(row_index, 1, label)
        sheet.cell(row_index, 2, value)
        sheet.cell(row_index, 1).border = Border(bottom=THIN_GRAY)
        sheet.cell(row_index, 2).border = Border(bottom=THIN_GRAY)
        if "금액" in label or label in {"원본 후보", "출력 포함", "출력 제외", "포함+제외 검산", "여행별 탭 수", "가맹점명 정규화 변경", "포함 비최종"}:
            sheet.cell(row_index, 2).number_format = "#,##0;[Red](#,##0);-"

    sheet.merge_cells("D6:H6")
    sheet["D6"] = "행사년도별 포함"
    sheet["D6"].fill = PatternFill("solid", fgColor=NAVY)
    sheet["D6"].font = Font(bold=True, color="FFFFFF")
    for cell, value in zip(sheet[7][3:6], ["행사년도", "건수", "금액(원)"]):
        cell.value = value
        cell.fill = PatternFill("solid", fgColor=BLUE)
        cell.font = Font(bold=True)
    for row_index, year in enumerate(("2026", "2027"), start=8):
        sheet.cell(row_index, 4, year)
        sheet.cell(row_index, 5, year_counts.get(year, 0))
        sheet.cell(row_index, 6, year_amounts.get(year, 0))
        sheet.cell(row_index, 6).number_format = "#,##0;[Red](#,##0);-"

    sheet["D11"] = "제외 사유"
    sheet["D11"].fill = PatternFill("solid", fgColor=NAVY)
    sheet["D11"].font = Font(bold=True, color="FFFFFF")
    for cell, value in zip(sheet[12][3:5], ["사유", "건수"]):
        cell.value = value
        cell.fill = PatternFill("solid", fgColor=BLUE)
        cell.font = Font(bold=True)
    for row_index, (reason, count) in enumerate(excluded_reasons.most_common(), start=13):
        sheet.cell(row_index, 4, reason)
        sheet.cell(row_index, 5, count)

    start = max(13, 13 + len(excluded_reasons) + 2)
    sheet.cell(start, 1, "비최종 부작용 검산")
    sheet.cell(start, 1).fill = PatternFill("solid", fgColor=NAVY)
    sheet.cell(start, 1).font = Font(bold=True, color="FFFFFF")
    for cell, value in zip(sheet[start + 1][:2], ["항목", "건수"]):
        cell.value = value
        cell.fill = PatternFill("solid", fgColor=BLUE)
        cell.font = Font(bold=True)
    for row_index, (label, count) in enumerate(
        (("배분계획", selected_nonfinal_side_effects["plan"]),
         ("배분", selected_nonfinal_side_effects["allocation"]),
         ("전기", selected_nonfinal_side_effects["journal"]),
         ("환불상속", selected_nonfinal_side_effects["inheritance"])),
        start=start + 2,
    ):
        sheet.cell(row_index, 1, label)
        sheet.cell(row_index, 2, count)
        sheet.cell(row_index, 2).fill = PatternFill("solid", fgColor=GREEN if count == 0 else ORANGE)

    rule_start = start + 8
    sheet.cell(rule_start, 1, "적용 규칙")
    sheet.cell(rule_start, 1).fill = PatternFill("solid", fgColor=NAVY)
    sheet.cell(rule_start, 1).font = Font(bold=True, color="FFFFFF")
    rules = [
        "1. 행사기간의 시작일~종료일이 2026 또는 2027에 걸치는 결제만 포함.",
        "2. 2025년 결제일은 행사기간이 2026·2027이면 포함하고, 결제일만으로 행사일을 추정하지 않음.",
        "3. 일정표 → 임시 레지스트리 → 명시적 서비스/행사 증거 → 대상명 날짜 순으로 행사기간을 확인.",
        "4. 행사기간이 없는 기타비용·미배정 행은 여행별 결과에서 제외하고 제외감사 탭에 보존.",
        "5. 항목은 국가/지역 접미어(TOKYO JP 등)와 과도한 공백을 제거한 가맹점명.",
        "6. 첫 5열은 수기장부 지출 열: 거래일자·항목·내용·증빙유형·금액.",
        "7. 이 파일은 분류 결과의 출력본이며 final 확정·배분·전기·배포를 의미하지 않음.",
    ]
    for index, rule in enumerate(rules, start=rule_start + 1):
        sheet.cell(index, 1, rule)
        sheet.merge_cells(start_row=index, start_column=1, end_row=index, end_column=8)
        sheet.cell(index, 1).alignment = Alignment(wrap_text=True, vertical="top")

    sheet.column_dimensions["A"].width = 28
    sheet.column_dimensions["B"].width = 18
    sheet.column_dimensions["C"].width = 4
    sheet.column_dimensions["D"].width = 38
    sheet.column_dimensions["E"].width = 18
    sheet.column_dimensions["F"].width = 20
    sheet.column_dimensions["G"].width = 20
    sheet.column_dimensions["H"].width = 4
    for row in sheet.iter_rows():
        for cell in row:
            if cell.value is not None and cell.alignment == Alignment():
                cell.alignment = Alignment(vertical="top", wrap_text=True)
    sheet.freeze_panes = "A7"


def _add_verification(sheet, *, checks: list[tuple[str, object, object, str]]) -> None:
    sheet.sheet_view.showGridLines = False
    sheet.merge_cells("A1:F1")
    sheet["A1"] = "출력 검증"
    sheet["A1"].fill = PatternFill("solid", fgColor=NAVY)
    sheet["A1"].font = Font(bold=True, color="FFFFFF", size=14)
    headers = ("검사", "기대값", "실제값", "결과", "근거", "비고")
    for index, value in enumerate(headers, start=1):
        cell = sheet.cell(3, index, value)
        cell.fill = PatternFill("solid", fgColor=BLUE)
        cell.font = Font(bold=True)
    for row_index, (label, expected, actual, evidence) in enumerate(checks, start=4):
        ok = expected == actual
        sheet.cell(row_index, 1, label)
        sheet.cell(row_index, 2, expected)
        sheet.cell(row_index, 3, actual)
        sheet.cell(row_index, 4, "OK" if ok else "확인 필요")
        sheet.cell(row_index, 5, evidence)
        sheet.cell(row_index, 6, "출력본 검증")
        sheet.cell(row_index, 4).fill = PatternFill("solid", fgColor=GREEN if ok else ORANGE)
        for col in range(1, 7):
            sheet.cell(row_index, col).border = Border(bottom=THIN_GRAY)
    for index, width in enumerate((28, 18, 18, 14, 34, 18), start=1):
        sheet.column_dimensions[get_column_letter(index)].width = width
    sheet.freeze_panes = "A4"
    sheet.auto_filter.ref = f"A3:F{len(checks)+3}"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    report = json.loads(args.report.read_text(encoding="utf-8"))
    db = sqlite3.connect(args.db)
    try:
        raw_rows = build_rows(db)
        trips, registries, evidence = _load_period_context(db)
    finally:
        db.close()

    if not raw_rows:
        raise RuntimeError("candidate_rows_empty")
    source_count = len(raw_rows)
    gate5 = next((item.get("actual", {}) for item in report.get("gates", []) if item.get("gate") == 5), {})
    expected_source_count = int(gate5.get("candidate_payment_count") or source_count)
    if source_count != expected_source_count:
        raise RuntimeError(f"source_row_count_mismatch:{source_count}!={expected_source_count}")

    selected: list[dict[str, object]] = []
    excluded: list[list[object]] = []
    excluded_reasons: Counter[str] = Counter()
    year_counts: Counter[str] = Counter()
    year_amounts: Counter[str] = Counter()
    changed_merchants = 0
    for raw in raw_rows:
        row = dict(zip(HEADERS, raw))
        payment_id = _as_int(_value(row, "payment_id"))
        period = event_period_for_targets(
            _value(row, "allocation_target"),
            trips=trips,
            registries=registries,
            evidence_payloads=evidence.get(payment_id, ()),
        )
        original_merchant = str(_value(row, "merchant") or "").strip()
        normalized_merchant = normalize_merchant_name(original_merchant)
        if original_merchant != normalized_merchant:
            changed_merchants += 1
        if period.eligible and not _is_nontravel_target(_value(row, "allocation_target")):
            selected.append(
                {
                    "row": row,
                    "period": period,
                    "target": _tab_target(_value(row, "allocation_target"), period),
                    "ledger": _manual_row(row, period),
                }
            )
            for year in sorted(period.event_years & ALLOWED_EVENT_YEARS):
                year_counts[str(year)] += 1
                year_amounts[str(year)] += _as_int(_value(row, "amount_krw"))
        else:
            reason = _period_reason(period, _value(row, "allocation_target"))
            excluded_reasons[reason] += 1
            excluded.append(_excluded_row(row, period, reason))

    # A row with a multi-year period is counted once in the detail tab, but its
    # year bucket is intentionally counted in each eligible year for audit.
    selected_amount = sum(_as_int(item["row"].get("amount_krw")) for item in selected)
    excluded_amount = sum(int(row[3] or 0) for row in excluded)
    selected_nonfinal = [item for item in selected if item["row"].get("result_status") == "nonfinal"]
    side_effects = {
        "plan": sum(_as_int(item["row"].get("plan_count")) for item in selected_nonfinal),
        "allocation": sum(_as_int(item["row"].get("allocation_count")) for item in selected_nonfinal),
        "journal": sum(_as_int(item["row"].get("journal_count")) for item in selected_nonfinal),
        "inheritance": sum(_as_int(item["row"].get("reversal_inheritance_count")) for item in selected_nonfinal),
    }

    grouped: dict[str, list[dict[str, object]]] = defaultdict(list)
    for item in selected:
        grouped[str(item["target"])].append(item)

    args.output.parent.mkdir(parents=True, exist_ok=True)
    workbook = Workbook()
    summary = workbook.active
    summary.title = "요약"
    all_sheet = workbook.create_sheet("전체결과")
    nonfinal_sheet = workbook.create_sheet("비최종")
    excluded_sheet = workbook.create_sheet("제외감사")
    checks = workbook.create_sheet("검증")

    all_ledger = [item["ledger"] for item in selected]
    nonfinal_ledger = [item["ledger"] for item in selected_nonfinal]
    _write_data_sheet(all_sheet, MANUAL_HEADERS, all_ledger, table_prefix="AllLedger", table_index=1)
    _write_data_sheet(nonfinal_sheet, MANUAL_HEADERS, nonfinal_ledger, table_prefix="NonFinalLedger", table_index=1)
    _write_data_sheet(excluded_sheet, EXCLUDED_HEADERS, excluded, table_prefix="ExcludedAudit", table_index=1)

    used_sheet_names = set(workbook.sheetnames)
    sheet_name_by_target: dict[str, str] = {}
    for index, target in enumerate(sorted(grouped), start=1):
        sheet_name = _safe_sheet_name(target, used_sheet_names)
        sheet_name_by_target[target] = sheet_name
        sheet = workbook.create_sheet(sheet_name)
        target_rows = sorted(
            grouped[target],
            key=lambda item: (
                str(item["row"].get("occurred_on") or ""),
                _as_int(item["row"].get("payment_id")),
            ),
        )
        _write_data_sheet(
            sheet,
            MANUAL_HEADERS,
            [item["ledger"] for item in target_rows],
            table_prefix="TripLedger",
            table_index=index,
        )

    _add_summary(
        summary,
        report=report,
        source_count=source_count,
        selected_count=len(selected),
        excluded_count=len(excluded),
        selected_amount=selected_amount,
        excluded_amount=excluded_amount,
        year_counts=year_counts,
        year_amounts=year_amounts,
        excluded_reasons=excluded_reasons,
        changed_merchants=changed_merchants,
        sheet_count=len(grouped),
        selected_nonfinal_count=len(selected_nonfinal),
        selected_nonfinal_side_effects=side_effects,
    )

    checks_list: list[tuple[str, object, object, str]] = [
        ("원본 행 수", source_count, len(raw_rows), "package-c Gate5 candidate count"),
        ("포함+제외=원본", source_count, len(selected) + len(excluded), "행 단위 selection partition"),
        ("2026 포함 건수", year_counts.get("2026", 0), sum(1 for item in selected if "2026" in item["ledger"][6]), "event period year"),
        ("2027 포함 건수", year_counts.get("2027", 0), sum(1 for item in selected if "2027" in item["ledger"][6]), "event period year"),
        ("금액 보존", selected_amount + excluded_amount, sum(_as_int(row[ROW_INDEX["amount_krw"]]) for row in raw_rows), "selected + excluded"),
        ("비최종 배분계획", 0, side_effects["plan"], "nonfinal side-effect invariant"),
        ("비최종 배분", 0, side_effects["allocation"], "nonfinal side-effect invariant"),
        ("비최종 전기", 0, side_effects["journal"], "nonfinal side-effect invariant"),
        ("비최종 환불상속", 0, side_effects["inheritance"], "nonfinal side-effect invariant"),
        ("가맹점 정규화 idempotent", 0, sum(1 for item in selected if normalize_merchant_name(item["ledger"][1]) != item["ledger"][1]), "normalize twice"),
    ]
    _add_verification(checks, checks=checks_list)

    workbook.calculation.fullCalcOnLoad = True
    workbook.calculation.forceFullCalc = True
    workbook.calculation.calcMode = "auto"
    workbook.properties.title = "2026·2027 행사자료 수기장부형 여행별 결과"
    workbook.properties.subject = "행사년도 필터·가맹점명 정규화·여행별 탭"
    workbook.save(args.output)

    # Structural checks after serialization.  These do not depend on a GUI
    # recalculation engine and catch accidental sheet/table truncation.
    check = load_workbook(args.output, read_only=True, data_only=False)
    if check.sheetnames[:5] != ["요약", "전체결과", "비최종", "제외감사", "검증"]:
        raise RuntimeError("unexpected_core_sheet_layout")
    if check["전체결과"].max_row != len(all_ledger) + 3:
        raise RuntimeError("all_result_row_count_mismatch")
    if check["비최종"].max_row != len(nonfinal_ledger) + 3:
        raise RuntimeError("nonfinal_row_count_mismatch")
    if check["제외감사"].max_row != len(excluded) + 3:
        raise RuntimeError("excluded_audit_row_count_mismatch")
    if tuple(next(check["전체결과"].iter_rows(min_row=1, max_row=1, values_only=True)))[:5] != MANUAL_HEADERS[:5]:
        raise RuntimeError("manual_ledger_header_mismatch")
    check.close()

    print("output", args.output)
    print("source_rows", source_count)
    print("selected_rows", len(selected))
    print("excluded_rows", len(excluded))
    print("selected_amount_krw", selected_amount)
    print("excluded_amount_krw", excluded_amount)
    print("trip_sheets", len(grouped))
    print("year_counts", dict(year_counts))
    print("changed_merchants", changed_merchants)
    print("nonfinal_side_effects", side_effects)


if __name__ == "__main__":
    main()
