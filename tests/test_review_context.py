"""Synthetic regression tests for webapp/review_context.py.

All fixtures are built in memory. Workbooks are synthetic openpyxl
workbooks serialized to bytes. CSV texts are synthetic strings. No
original data, no database, no network and no dependency on workspace
files. Tests run against the real adapter, the real core and the real
pure planner, never against stubs.
"""

from __future__ import annotations

import csv
import io
import json
import os

import pytest

from webapp.contracts import sha256_bytes, sha256_text
from webapp.review_context import (
    MASTER_HEADERS,
    ReviewContextError,
    build_review_context,
    build_review_export,
)

try:
    from openpyxl import Workbook
except Exception:
    Workbook = None


LABELS7 = ["거래일자", "항목", "내용", "기간", "예약번호", "증빙유형", "금액"]
DATE_TXT = "2026-03-04"
AMOUNT_INT = 12345
AMOUNT_TXT = "12345"
KEY_ONE = "TX-1"
KEY_TWO = "TX-2"
SHEET = "비용"

REVIEW_FIELDS = (
    "source_ref_snapshot_only",
    "source_date",
    "source_amount",
    "candidate_count",
    "candidate_transaction_keys",
    "candidate_date_fields",
    "disposition",
    "reviewer_decision",
    "review_note",
    "review_schema_version",
    "review_snapshot_sha256",
)


def _need_workbook():
    if Workbook is None:
        pytest.skip("openpyxl is not available")


def _workbook_bytes(blocks, sheet=SHEET):
    _need_workbook()
    book = Workbook()
    page = book.active
    page.title = sheet
    for block in blocks:
        header_row = block["header_row"]
        data_row = block["data_row"]
        date_col = block["date_col"]
        headers = block.get("headers")
        if headers is not None:
            for offset, label in enumerate(headers):
                page.cell(row=header_row, column=date_col + offset, value=label)
        for offset, value in enumerate(block["values"]):
            page.cell(row=data_row, column=date_col + offset, value=value)
    buf = io.BytesIO()
    book.save(buf)
    return buf.getvalue()


def _expense_block(data_row=5, header_row=4, date_col=2, amount_col=8,
                   headers=None, values=None):
    if headers is None:
        headers = list(LABELS7)
    if values is None:
        values = [DATE_TXT, "회의비", "팀 회의", "2026-03", "RSV-1", "카드전표", AMOUNT_INT]
    return {
        "header_row": header_row,
        "data_row": data_row,
        "date_col": date_col,
        "headers": headers,
        "values": values,
    }


def _ref(sheet, date_col, data_row, amount_col):
    cols = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
    return sheet + "!" + cols[date_col - 1] + str(data_row) + "|" + cols[amount_col - 1] + str(data_row) + " (row " + str(data_row) + ")"


def _master_row(key=KEY_ONE, approval="2026-03-03", posting="2026-03-04",
                merchant="식당", amount="12345", approval_no="AP-1"):
    row = {name: "" for name in MASTER_HEADERS}
    row.update({
        "거래키": key,
        "카드사": "신한",
        "카드4": "1234",
        "구분": "일시불",
        "승인일": approval,
        "매입일": posting,
        "가맹점": merchant,
        "원화금액": amount,
        "현지금액": amount,
        "통화": "KRW",
        "승인번호": approval_no,
        "취소여부": "N",
        "출처": "master",
        "적재일": "2026-03-05",
        "기록여부": "Y",
        "워크북참조": "w1",
        "비고": "memo",
    })
    return row


def _master_csv(rows):
    buf = io.StringIO()
    writer = csv.writer(buf, lineterminator="\n")
    writer.writerow(list(MASTER_HEADERS))
    for row in rows:
        writer.writerow([row.get(name, "") for name in MASTER_HEADERS])
    return buf.getvalue()


def _review_row(ref, snapshot_hex, date_txt=DATE_TXT, amount_txt=AMOUNT_TXT,
                keys=None, disposition="candidate_review_required",
                decision="", note="n1"):
    if keys is None:
        keys = [KEY_ONE]
    return {
        "source_ref_snapshot_only": ref,
        "source_date": date_txt,
        "source_amount": amount_txt,
        "candidate_count": str(len(keys)),
        "candidate_transaction_keys": json.dumps(keys, ensure_ascii=False),
        "candidate_date_fields": "2026-03-03/2026-03-04",
        "disposition": disposition,
        "reviewer_decision": decision,
        "review_note": note,
        "review_schema_version": "review-csv-v1",
        "review_snapshot_sha256": snapshot_hex,
    }


def _review_csv(rows, snapshot_hex, bom=False):
    buf = io.StringIO()
    writer = csv.writer(buf, lineterminator="\n")
    writer.writerow(list(REVIEW_FIELDS))
    for row in rows:
        writer.writerow([row.get(name, "") for name in REVIEW_FIELDS])
    text = buf.getvalue()
    if bom:
        text = "\ufeff" + text
    return text


def _standard_inputs(decision="", note="n1", bom=False):
    ref = _ref(SHEET, 2, 5, 8)
    snapshot_bytes = _workbook_bytes([_expense_block()])
    snapshot_hex = sha256_bytes(snapshot_bytes)
    review_text = _review_csv(
        [_review_row(ref, snapshot_hex, decision=decision, note=note)],
        snapshot_hex, bom=bom)
    master_text = _master_csv([_master_row()])
    return {
        "ref": ref,
        "snapshot_bytes": snapshot_bytes,
        "snapshot_hex": snapshot_hex,
        "review_text": review_text,
        "review_hex": sha256_text(review_text),
        "master_text": master_text,
        "master_hex": sha256_text(master_text),
    }


def _build_all(fixture):
    return build_review_context(
        fixture["snapshot_bytes"], fixture["review_text"],
        fixture["master_text"], fixture["snapshot_hex"],
        fixture["review_hex"], fixture["master_hex"])


def test_context_available_and_contract_wire_keys():
    model = _build_all(_standard_inputs())
    assert set(model.keys()) == {"snapshotsha", "reviewsha", "mastersha", "rows"}
    assert model["snapshotsha"] != model["reviewsha"]
    assert model["reviewsha"] != model["mastersha"]
    assert len(model["rows"]) == 1
    row = model["rows"][0]
    assert set(row.keys()) == {"ref", "source", "candidates", "decision", "pipeline_recommendation"}
    assert row["decision"] == ""
    assert row["pipeline_recommendation"] == {
        "candidate_key": KEY_ONE, "basis": "existing_reconciliation_unique"}
    source = row["source"]
    assert source["block_kind"] == "expense"
    assert source["evidence_status"] == "available"
    assert source["date"] == DATE_TXT
    assert source["amount"] == AMOUNT_TXT
    assert source["sourceLocator"] == row["ref"]
    assert len(source["fieldcells"]) == 7
    assert source["fieldcells"][0]["address"] == "B5"
    assert source["fieldcells"][0]["label"] == "거래일자"
    assert source["fieldcells"][0]["value"] == DATE_TXT


def test_source_merchant_absent_and_description_from_content():
    model = _build_all(_standard_inputs())
    source = model["rows"][0]["source"]
    assert source["merchant"] == "없음"
    assert source["description"] == "팀 회의"
    labels = [cell["label"] for cell in source["fieldcells"]]
    assert labels == LABELS7


def test_candidate_carries_master_evidence():
    model = _build_all(_standard_inputs())
    candidates = model["rows"][0]["candidates"]
    assert len(candidates) == 1
    candidate = candidates[0]
    assert candidate["key"] == KEY_ONE
    assert candidate["datefields"] == {"approval_date": "2026-03-03", "posting_date": "2026-03-04"}
    assert candidate["amount"] == AMOUNT_TXT
    assert candidate["merchant"] == "식당"
    assert candidate["approval_number"] == "AP-1"
    assert "row 2" in candidate["sourceLocator"]


def test_width8_extra_column_stays_raw_and_available():
    headers = ["거래일자", "항목", "내용", "기간", "예약번호", "증빙유형", "메모", "금액"]
    values = [DATE_TXT, "회의비", "팀 회의", "2026-03", "RSV-1", "카드전표", "추가메모", AMOUNT_INT]
    ref = _ref(SHEET, 2, 5, 9)
    snapshot_bytes = _workbook_bytes([_expense_block(date_col=2, amount_col=9, headers=headers, values=values)])
    snapshot_hex = sha256_bytes(snapshot_bytes)
    review_text = _review_csv([_review_row(ref, snapshot_hex)], snapshot_hex)
    master_text = _master_csv([_master_row()])
    model = build_review_context(
        snapshot_bytes, review_text, master_text, snapshot_hex,
        sha256_text(review_text), sha256_text(master_text))
    source = model["rows"][0]["source"]
    assert source["evidence_status"] == "available"
    assert len(source["fieldcells"]) == 8
    extra = source["fieldcells"][6]
    assert extra["address"] == "H5"
    assert extra["label"] == "메모"
    assert extra["value"] == "추가메모"
    assert source["merchant"] == "없음"
    assert source["description"] == "팀 회의"


def test_two_blocks_same_row_uses_only_block_range():
    expense = _expense_block()
    income = {
        "header_row": 4,
        "data_row": 5,
        "date_col": 10,
        "headers": ["수입일자", "수입항목", "수입내용", "수입기간", "예약번호", "증빙유형", "수입금액"],
        "values": ["2026-03-04", "용역수입", "수입내역", "2026-03", "RSV-9", "세금계산서", 999999],
    }
    ref = _ref(SHEET, 2, 5, 8)
    snapshot_bytes = _workbook_bytes([expense, income])
    snapshot_hex = sha256_bytes(snapshot_bytes)
    review_text = _review_csv([_review_row(ref, snapshot_hex)], snapshot_hex)
    master_text = _master_csv([_master_row()])
    model = build_review_context(
        snapshot_bytes, review_text, master_text, snapshot_hex,
        sha256_text(review_text), sha256_text(master_text))
    source = model["rows"][0]["source"]
    assert source["evidence_status"] == "available"
    assert len(source["fieldcells"]) == 7
    for cell in source["fieldcells"]:
        assert cell["value"] != "수입내역"
        assert cell["value"] != "999999"
    assert source["description"] == "팀 회의"


def test_other_block_header_cannot_label_expense_block():
    headers = ["수입일자", "항목", "내용", "기간", "예약번호", "증빙유형", "금액"]
    ref = _ref(SHEET, 2, 5, 8)
    snapshot_bytes = _workbook_bytes([_expense_block(headers=headers)])
    snapshot_hex = sha256_bytes(snapshot_bytes)
    review_text = _review_csv([_review_row(ref, snapshot_hex)], snapshot_hex)
    master_text = _master_csv([_master_row()])
    model = build_review_context(
        snapshot_bytes, review_text, master_text, snapshot_hex,
        sha256_text(review_text), sha256_text(master_text))
    source = model["rows"][0]["source"]
    assert source["evidence_status"] == "insufficient"
    assert source["description"] == ""


def test_missing_header_is_insufficient_and_blocks_approve():
    block = _expense_block(headers=None)
    block["headers"] = None
    ref = _ref(SHEET, 2, 5, 8)
    snapshot_bytes = _workbook_bytes([block])
    snapshot_hex = sha256_bytes(snapshot_bytes)
    review_text = _review_csv([_review_row(ref, snapshot_hex)], snapshot_hex)
    master_text = _master_csv([_master_row()])
    model = build_review_context(
        snapshot_bytes, review_text, master_text, snapshot_hex,
        sha256_text(review_text), sha256_text(master_text))
    source = model["rows"][0]["source"]
    assert source["evidence_status"] == "insufficient"
    assert source["fieldcells"][0] == {"address": "B5", "label": "", "value": DATE_TXT}
    with pytest.raises(ReviewContextError) as exc:
        build_review_export(model, review_text, [{"ref": ref, "value": "APPROVE:" + KEY_ONE}])
    assert exc.value.code == "INSUFFICIENT_EVIDENCE"
    result = build_review_export(model, review_text, [{"ref": ref, "value": "REJECT"}])
    assert result["counts"] == {"approved": 0, "rejected": 1, "incomplete": 0}


def test_zero_candidates_blocks_approve():
    ref = _ref(SHEET, 2, 5, 8)
    snapshot_bytes = _workbook_bytes([_expense_block()])
    snapshot_hex = sha256_bytes(snapshot_bytes)
    row = _review_row(ref, snapshot_hex, keys=[])
    review_text = _review_csv([row], snapshot_hex)
    master_text = _master_csv([_master_row()])
    model = build_review_context(
        snapshot_bytes, review_text, master_text, snapshot_hex,
        sha256_text(review_text), sha256_text(master_text))
    assert model["rows"][0]["candidates"] == []
    assert model["rows"][0]["source"]["evidence_status"] == "available"
    with pytest.raises(ReviewContextError) as exc:
        build_review_export(model, review_text, [{"ref": ref, "value": "APPROVE:" + KEY_ONE}])
    assert exc.value.code == "INSUFFICIENT_EVIDENCE"


def _context_with_manifest(ref, snapshot_bytes, snapshot_hex, date_txt, amount_txt, keys=None):
    review_text = _review_csv(
        [_review_row(ref, snapshot_hex, date_txt=date_txt, amount_txt=amount_txt, keys=keys)],
        snapshot_hex)
    master_text = _master_csv([_master_row(), _master_row(key=KEY_TWO)])
    return build_review_context(
        snapshot_bytes, review_text, master_text, snapshot_hex,
        sha256_text(review_text), sha256_text(master_text))


def test_source_date_mismatch_fails_closed():
    ref = _ref(SHEET, 2, 5, 8)
    snapshot_bytes = _workbook_bytes([_expense_block()])
    snapshot_hex = sha256_bytes(snapshot_bytes)
    with pytest.raises(ReviewContextError) as exc:
        _context_with_manifest(ref, snapshot_bytes, snapshot_hex, "2026-03-05", AMOUNT_TXT)
    assert exc.value.code == "SOURCE_DATE_MISMATCH"


def test_source_amount_mismatch_fails_closed():
    ref = _ref(SHEET, 2, 5, 8)
    snapshot_bytes = _workbook_bytes([_expense_block()])
    snapshot_hex = sha256_bytes(snapshot_bytes)
    with pytest.raises(ReviewContextError) as exc:
        _context_with_manifest(ref, snapshot_bytes, snapshot_hex, DATE_TXT, "12346")
    assert exc.value.code == "SOURCE_AMOUNT_MISMATCH"


def test_source_date_without_year_is_unparsable():
    values = ["4/1", "회의비", "팀 회의", "2026-03", "RSV-1", "카드전표", AMOUNT_INT]
    ref = _ref(SHEET, 2, 5, 8)
    snapshot_bytes = _workbook_bytes([_expense_block(values=values)])
    snapshot_hex = sha256_bytes(snapshot_bytes)
    with pytest.raises(ReviewContextError) as exc:
        _context_with_manifest(ref, snapshot_bytes, snapshot_hex, "2026-04-01", AMOUNT_TXT)
    assert exc.value.code == "SOURCE_DATE_UNPARSABLE"


def test_source_cell_missing_fails_closed():
    values = ["", "회의비", "팀 회의", "2026-03", "RSV-1", "카드전표", AMOUNT_INT]
    ref = _ref(SHEET, 2, 5, 8)
    snapshot_bytes = _workbook_bytes([_expense_block(values=values)])
    snapshot_hex = sha256_bytes(snapshot_bytes)
    with pytest.raises(ReviewContextError) as exc:
        _context_with_manifest(ref, snapshot_bytes, snapshot_hex, DATE_TXT, AMOUNT_TXT)
    assert exc.value.code == "SOURCE_CELL_MISSING"


def test_source_sheet_missing_fails_closed():
    ref = _ref("없는시트", 2, 5, 8)
    snapshot_bytes = _workbook_bytes([_expense_block()])
    snapshot_hex = sha256_bytes(snapshot_bytes)
    with pytest.raises(ReviewContextError) as exc:
        _context_with_manifest(ref, snapshot_bytes, snapshot_hex, DATE_TXT, AMOUNT_TXT)
    assert exc.value.code == "SOURCE_SHEET_MISSING"


def test_source_row_mismatch_fails_closed():
    ref = SHEET + "!B5|H6 (row 5)"
    snapshot_bytes = _workbook_bytes([_expense_block()])
    snapshot_hex = sha256_bytes(snapshot_bytes)
    with pytest.raises(ReviewContextError) as exc:
        _context_with_manifest(ref, snapshot_bytes, snapshot_hex, DATE_TXT, AMOUNT_TXT)
    assert exc.value.code == "SOURCE_ROW_MISMATCH"


def test_source_column_order_fails_closed():
    ref = SHEET + "!H5|B5 (row 5)"
    snapshot_bytes = _workbook_bytes([_expense_block()])
    snapshot_hex = sha256_bytes(snapshot_bytes)
    with pytest.raises(ReviewContextError) as exc:
        _context_with_manifest(ref, snapshot_bytes, snapshot_hex, DATE_TXT, AMOUNT_TXT)
    assert exc.value.code == "SOURCE_COLUMN_ORDER"


def test_invalid_source_ref_fails_closed():
    ref = "not-a-ref"
    snapshot_bytes = _workbook_bytes([_expense_block()])
    snapshot_hex = sha256_bytes(snapshot_bytes)
    with pytest.raises(ReviewContextError) as exc:
        _context_with_manifest(ref, snapshot_bytes, snapshot_hex, DATE_TXT, AMOUNT_TXT)
    assert exc.value.code == "INVALID_SOURCE_REF"


def test_unsupported_block_width_fails_closed():
    values = [DATE_TXT, "회의비", "팀 회의", "2026-03", 12345]
    headers = ["거래일자", "항목", "내용", "기간", "금액"]
    ref = _ref(SHEET, 2, 5, 6)
    snapshot_bytes = _workbook_bytes([_expense_block(date_col=2, amount_col=6, headers=headers, values=values)])
    snapshot_hex = sha256_bytes(snapshot_bytes)
    with pytest.raises(ReviewContextError) as exc:
        _context_with_manifest(ref, snapshot_bytes, snapshot_hex, DATE_TXT, AMOUNT_TXT)
    assert exc.value.code == "SOURCE_BLOCK_WIDTH_UNSUPPORTED"


def test_invalid_hash_arguments_fail_closed():
    fixture = _standard_inputs()
    with pytest.raises(ReviewContextError) as exc:
        build_review_context(
            fixture["snapshot_bytes"], fixture["review_text"],
            fixture["master_text"], "not-hex",
            fixture["review_hex"], fixture["master_hex"])
    assert exc.value.code == "INVALID_SHA256"


def test_snapshot_hash_mismatch_fails_closed():
    fixture = _standard_inputs()
    tampered = bytearray(fixture["snapshot_bytes"])
    tampered[len(tampered) // 2] ^= 1
    with pytest.raises(ReviewContextError) as exc:
        build_review_context(
            bytes(tampered), fixture["review_text"],
            fixture["master_text"], fixture["snapshot_hex"],
            fixture["review_hex"], fixture["master_hex"])
    assert exc.value.code == "SNAPSHOT_HASH_MISMATCH"


def test_review_hash_mismatch_fails_closed():
    fixture = _standard_inputs()
    with pytest.raises(ReviewContextError) as exc:
        build_review_context(
            fixture["snapshot_bytes"], fixture["review_text"],
            fixture["master_text"], fixture["snapshot_hex"],
            fixture["master_hex"], fixture["master_hex"])
    assert exc.value.code == "REVIEW_HASH_MISMATCH"


def test_master_hash_mismatch_fails_closed():
    fixture = _standard_inputs()
    with pytest.raises(ReviewContextError) as exc:
        build_review_context(
            fixture["snapshot_bytes"], fixture["review_text"],
            fixture["master_text"], fixture["snapshot_hex"],
            fixture["review_hex"], fixture["review_hex"])
    assert exc.value.code == "MASTER_HASH_MISMATCH"


def test_duplicate_master_key_fails_closed():
    fixture = _standard_inputs()
    master_text = _master_csv([_master_row(), _master_row()])
    with pytest.raises(ReviewContextError) as exc:
        build_review_context(
            fixture["snapshot_bytes"], fixture["review_text"],
            master_text, fixture["snapshot_hex"],
            fixture["review_hex"], sha256_text(master_text))
    assert exc.value.code == "DUPLICATE_MASTER_KEY"


def test_unresolved_candidate_key_fails_closed():
    fixture = _standard_inputs()
    review_text = _review_csv(
        [_review_row(fixture["ref"], fixture["snapshot_hex"], keys=["TX-9"])],
        fixture["snapshot_hex"])
    with pytest.raises(ReviewContextError) as exc:
        build_review_context(
            fixture["snapshot_bytes"], review_text,
            fixture["master_text"], fixture["snapshot_hex"],
            sha256_text(review_text), fixture["master_hex"])
    assert exc.value.code == "CANDIDATE_KEY_UNRESOLVED"


def test_unmatched_approve_passes_adapter_refusal_through():
    fixture = _standard_inputs()
    review_text = _review_csv(
        [_review_row(fixture["ref"], fixture["snapshot_hex"],
                     disposition="unmatched_review_required",
                     decision="APPROVE:" + KEY_ONE)],
        fixture["snapshot_hex"])
    with pytest.raises(ReviewContextError) as exc:
        build_review_context(
            fixture["snapshot_bytes"], review_text,
            fixture["master_text"], fixture["snapshot_hex"],
            sha256_text(review_text), fixture["master_hex"])
    assert exc.value.code == "APPROVAL_NOT_ALLOWED"


def test_duplicate_candidate_keys_pass_adapter_refusal_through():
    fixture = _standard_inputs()
    row = _review_row(fixture["ref"], fixture["snapshot_hex"], keys=[KEY_ONE, KEY_ONE])
    review_text = _review_csv([row], fixture["snapshot_hex"])
    with pytest.raises(ReviewContextError) as exc:
        build_review_context(
            fixture["snapshot_bytes"], review_text,
            fixture["master_text"], fixture["snapshot_hex"],
            sha256_text(review_text), fixture["master_hex"])
    assert exc.value.code == "APPROVED_KEY_DUPLICATED"


def test_bom_text_round_trips_with_bom_preserved():
    model = _build_all(_standard_inputs(bom=True))
    assert model["rows"][0]["source"]["evidence_status"] == "available"
    fixture = _standard_inputs(bom=True)
    result = build_review_export(
        model, fixture["review_text"],
        [{"ref": fixture["ref"], "value": "APPROVE:" + KEY_ONE}])
    assert result["decision_csv"].startswith("\ufeff")
    assert result["counts"] == {"approved": 1, "rejected": 0, "incomplete": 0}


def _parsed_rows(text):
    body = text[1:] if text.startswith("\ufeff") else text
    return list(csv.reader(io.StringIO(body), strict=True))


def test_export_approve_counts_plan_and_unchanged_fields():
    fixture = _standard_inputs()
    model = _build_all(fixture)
    result = build_review_export(
        model, fixture["review_text"],
        [{"ref": fixture["ref"], "value": "APPROVE:" + KEY_ONE}])
    assert result["counts"] == {"approved": 1, "rejected": 0, "incomplete": 0}
    assert result["plan_digest"]
    plan_json = result["plan_json"]
    assert set(plan_json.keys()) == {"counts", "plan_digest", "reviewed_plan", "snapshot_sha256"}
    assert plan_json["snapshot_sha256"] == fixture["snapshot_hex"]
    assert plan_json["plan_digest"] == result["plan_digest"]
    assert plan_json["counts"] == {"approved": 1, "rejected": 0, "incomplete": 0}
    reviewed = plan_json["reviewed_plan"]
    assert set(reviewed.keys()) == {"eligible", "refused", "counts"}
    assert len(reviewed["eligible"]) == 1
    assert reviewed["eligible"][0]["chosen_candidate_key"] == KEY_ONE
    assert reviewed["counts"] == {"eligible": 1, "refused": 0, "total": 1}
    before = _parsed_rows(fixture["review_text"])
    after = _parsed_rows(result["decision_csv"])
    assert after[0] == before[0]
    assert len(after) == len(before) == 2
    ref_col = before[0].index("source_ref_snapshot_only")
    dec_col = before[0].index("reviewer_decision")
    assert after[1][ref_col] == before[1][ref_col]
    assert after[1][dec_col] == "APPROVE:" + KEY_ONE
    for pos, cell in enumerate(before[1]):
        if pos != dec_col:
            assert after[1][pos] == cell


def test_export_omitted_decisions_preserve_original():
    ref_one = _ref(SHEET, 2, 5, 8)
    ref_two = _ref(SHEET, 2, 6, 8)
    values_two = [DATE_TXT, "택시비", "이동", "2026-03", "RSV-2", "카드전표", AMOUNT_INT]
    snapshot_bytes = _workbook_bytes([
        _expense_block(data_row=5),
        _expense_block(data_row=6, values=values_two),
    ])
    snapshot_hex = sha256_bytes(snapshot_bytes)
    review_text = _review_csv([
        _review_row(ref_one, snapshot_hex, decision="REJECT", note="keep"),
        _review_row(ref_two, snapshot_hex, decision="", keys=[KEY_TWO], note="hold"),
    ], snapshot_hex)
    master_text = _master_csv([_master_row(), _master_row(key=KEY_TWO)])
    model = build_review_context(
        snapshot_bytes, review_text, master_text, snapshot_hex,
        sha256_text(review_text), sha256_text(master_text))
    assert model["rows"][0]["decision"] == "REJECT"
    result = build_review_export(model, review_text, [])
    assert result["counts"] == {"approved": 0, "rejected": 1, "incomplete": 1}
    after = _parsed_rows(result["decision_csv"])
    dec_col = after[0].index("reviewer_decision")
    by_ref = {row[after[0].index("source_ref_snapshot_only")]: row for row in after[1:]}
    assert by_ref[ref_one][dec_col] == "REJECT"
    assert by_ref[ref_two][dec_col] == ""
    result_none = build_review_export(model, review_text, None)
    assert result_none["counts"] == result["counts"]


def test_export_rejects_unknown_duplicate_and_mistyped_decisions():
    fixture = _standard_inputs()
    model = _build_all(fixture)
    with pytest.raises(ReviewContextError) as exc:
        build_review_export(model, fixture["review_text"], [{"ref": "없는참조", "value": "REJECT"}])
    assert exc.value.code == "DECISION_UNKNOWN_REF"
    with pytest.raises(ReviewContextError) as exc:
        build_review_export(model, fixture["review_text"], [
            {"ref": fixture["ref"], "value": "REJECT"},
            {"ref": fixture["ref"], "value": ""},
        ])
    assert exc.value.code == "DECISION_DUPLICATE_REF"
    with pytest.raises(ReviewContextError) as exc:
        build_review_export(model, fixture["review_text"], [
            {"ref": fixture["ref"], "value": "REJECT", "note": "extra"},
        ])
    assert exc.value.code == "DECISION_SHAPE_INVALID"
    with pytest.raises(ReviewContextError) as exc:
        build_review_export(model, fixture["review_text"], [{"ref": fixture["ref"], "value": "APPROVE:"}])
    assert exc.value.code == "DECISION_VALUE_INVALID"
    with pytest.raises(ReviewContextError) as exc:
        build_review_export(model, fixture["review_text"], [{"ref": fixture["ref"], "value": "APPROVE:TX-9"}])
    assert exc.value.code == "DECISION_VALUE_INVALID"


def test_export_binding_rejects_text_and_model_drift():
    fixture = _standard_inputs()
    model = _build_all(fixture)
    drifted = fixture["review_text"].replace("n1", "n2")
    with pytest.raises(ReviewContextError) as exc:
        build_review_export(model, drifted, [])
    assert exc.value.code == "EXPORT_BINDING_MISMATCH"
    tampered = dict(model)
    tampered["rows"] = []
    with pytest.raises(ReviewContextError) as exc:
        build_review_export(tampered, fixture["review_text"], [])
    assert exc.value.code == "EXPORT_BINDING_MISMATCH"


def test_error_codes_carry_no_values():
    fixture = _standard_inputs()
    with pytest.raises(ReviewContextError) as exc:
        build_review_context(
            fixture["snapshot_bytes"], fixture["review_text"],
            fixture["master_text"], fixture["snapshot_hex"],
            fixture["review_hex"], fixture["review_hex"])
    assert exc.value.code == "MASTER_HASH_MISMATCH"
    assert str(exc.value) == "MASTER_HASH_MISMATCH"
    assert KEY_ONE not in str(exc.value)


def test_plan_json_pins_cli_allowlisted_shape():
    from tools import build_reviewed_import_plan_from_csv as plan_cli
    fixture = _standard_inputs()
    model = _build_all(fixture)
    result = build_review_export(
        model, fixture["review_text"],
        [{"ref": fixture["ref"], "value": "REJECT"}])
    reviewed = result["plan_json"]["reviewed_plan"]
    assert len(reviewed["refused"]) == 1
    assert set(reviewed["refused"][0].keys()) == set(plan_cli._REFUSED_FIELDS)
    assert set(reviewed["counts"].keys()) == set(plan_cli._PLAN_COUNT_FIELDS)


def test_core_writes_no_files(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    before = set(os.listdir("."))
    fixture = _standard_inputs()
    model = _build_all(fixture)
    build_review_export(model, fixture["review_text"], [{"ref": fixture["ref"], "value": "REJECT"}])
    assert set(os.listdir(".")) == before


def test_consecutive_rows_share_same_header_7col():
    values_two = [DATE_TXT, "택시비", "이동", "2026-03", "RSV-2", "카드전표", 6789]
    ref_one = _ref(SHEET, 2, 5, 8)
    ref_two = _ref(SHEET, 2, 6, 8)
    first = _expense_block(data_row=5)
    second = _expense_block(data_row=6, values=values_two)
    second["headers"] = None
    snapshot_bytes = _workbook_bytes([first, second])
    snapshot_hex = sha256_bytes(snapshot_bytes)
    review_text = _review_csv([
        _review_row(ref_one, snapshot_hex, keys=[KEY_ONE]),
        _review_row(ref_two, snapshot_hex, amount_txt="6789", keys=[KEY_TWO]),
    ], snapshot_hex)
    master_text = _master_csv([
        _master_row(),
        _master_row(key=KEY_TWO, merchant="교통", amount="6789", approval_no="AP-2"),
    ])
    model = build_review_context(
        snapshot_bytes, review_text, master_text, snapshot_hex,
        sha256_text(review_text), sha256_text(master_text))
    by_ref = {row["ref"]: row for row in model["rows"]}
    assert by_ref[ref_one]["source"]["evidence_status"] == "available"
    assert by_ref[ref_two]["source"]["evidence_status"] == "available"
    assert by_ref[ref_one]["source"]["description"] == "팀 회의"
    assert by_ref[ref_two]["source"]["description"] == "이동"
    assert by_ref[ref_two]["source"]["fieldcells"][0] == {
        "address": "B6", "label": "거래일자", "value": DATE_TXT}


def test_consecutive_rows_share_same_header_8col():
    headers = ["거래일자", "항목", "내용", "기간", "예약번호", "증빙유형", "메모", "금액"]
    values_one = [DATE_TXT, "회의비", "팀 회의", "2026-03", "RSV-1", "카드전표", "추가메모", AMOUNT_INT]
    values_two = [DATE_TXT, "택시비", "이동", "2026-03", "RSV-2", "카드전표", "추가메모2", 6789]
    ref_one = _ref(SHEET, 2, 5, 9)
    ref_two = _ref(SHEET, 2, 6, 9)
    first = _expense_block(date_col=2, amount_col=9, headers=headers, values=values_one)
    second = _expense_block(date_col=2, amount_col=9, data_row=6, values=values_two)
    second["headers"] = None
    snapshot_bytes = _workbook_bytes([first, second])
    snapshot_hex = sha256_bytes(snapshot_bytes)
    review_text = _review_csv([
        _review_row(ref_one, snapshot_hex, keys=[KEY_ONE]),
        _review_row(ref_two, snapshot_hex, amount_txt="6789", keys=[KEY_TWO]),
    ], snapshot_hex)
    master_text = _master_csv([
        _master_row(),
        _master_row(key=KEY_TWO, merchant="교통", amount="6789", approval_no="AP-2"),
    ])
    model = build_review_context(
        snapshot_bytes, review_text, master_text, snapshot_hex,
        sha256_text(review_text), sha256_text(master_text))
    by_ref = {row["ref"]: row for row in model["rows"]}
    assert by_ref[ref_one]["source"]["evidence_status"] == "available"
    assert by_ref[ref_two]["source"]["evidence_status"] == "available"
    assert len(by_ref[ref_two]["source"]["fieldcells"]) == 8
    assert by_ref[ref_two]["source"]["fieldcells"][6]["label"] == "메모"
    assert by_ref[ref_two]["source"]["fieldcells"][6]["value"] == "추가메모2"
    assert by_ref[ref_two]["source"]["description"] == "이동"


def test_invalid_header_blocks_older_header():
    _need_workbook()
    book = Workbook()
    page = book.active
    page.title = SHEET
    for offset, label in enumerate(LABELS7):
        page.cell(row=3, column=2 + offset, value=label)
    for offset, label in enumerate(["수입일자", "항목", "내용", "기간", "예약번호", "증빙유형", "금액"]):
        page.cell(row=4, column=2 + offset, value=label)
    for offset, value in enumerate([DATE_TXT, "회의비", "팀 회의", "2026-03", "RSV-1", "카드전표", AMOUNT_INT]):
        page.cell(row=5, column=2 + offset, value=value)
    buf = io.BytesIO()
    book.save(buf)
    snapshot_bytes = buf.getvalue()
    snapshot_hex = sha256_bytes(snapshot_bytes)
    ref = _ref(SHEET, 2, 5, 8)
    review_text = _review_csv([_review_row(ref, snapshot_hex)], snapshot_hex)
    master_text = _master_csv([_master_row()])
    model = build_review_context(
        snapshot_bytes, review_text, master_text, snapshot_hex,
        sha256_text(review_text), sha256_text(master_text))
    assert model["rows"][0]["source"]["evidence_status"] == "insufficient"
