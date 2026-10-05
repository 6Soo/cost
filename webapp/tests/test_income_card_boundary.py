"""Synthetic deposits must never be accepted as card expenditure decisions."""
from pathlib import Path

import pytest
from openpyxl import load_workbook

from webapp.contracts import sha256_bytes, sha256_text
from webapp.real_review import RealReviewError, RealReviewService
from webapp.review_context import _attach_pipeline_recommendations
from webapp.tests import review_fixtures as fx


def income_service(directory: Path):
    manifest = fx.write_case(directory, rows=1)
    path = Path(manifest["snapshot_path"])
    book = load_workbook(path)
    sheet = book[fx.SHEET]
    labels = ("거래일자", "이름", "닉네임", "예약금", "잔금", "추가금", "금액(원)")
    for column, label in enumerate(labels, 1):
        sheet.cell(fx.HEADER_ROW, column).value = label
    for column, value in enumerate(("2026-04-01", fx.INJECTION, "합성닉네임",
                                     100001, None, None, 100001), 1):
        sheet.cell(fx.FIRST_ROW, column).value = value
    book.save(path)
    book.close()
    manifest["snapshot_sha256"] = sha256_bytes(path.read_bytes())
    review = fx.build_review_text(manifest["snapshot_sha256"], 1,
                                  lambda _: [fx.candidate_key(1)])
    Path(manifest["review_path"]).write_text(review, encoding="utf-8", newline="")
    manifest["review_sha256"] = sha256_text(review)
    return RealReviewService(manifest)


def test_income_source_keeps_customer_fields_and_original_candidate(tmp_path):
    row = income_service(tmp_path).model()["rows"][0]
    assert row["source"]["block_kind"] == "income"
    assert row["source"]["customer_name"] == fx.INJECTION
    assert row["source"]["income_components"] == {"예약금": "100001", "잔금": "", "추가금": ""}
    assert row["source"]["evidence_status"] == "available"
    assert [c["key"] for c in row["candidates"]] == [fx.candidate_key(1)]


def test_income_approval_is_rejected_by_service_and_saves_nothing(tmp_path):
    service = income_service(tmp_path)
    before = service.state()
    with pytest.raises(RealReviewError) as caught:
        service.save_decisions(
            [{"ref": fx.source_ref(fx.FIRST_ROW), "value": "APPROVE:" + fx.candidate_key(1)}],
            expected_revision=before["revision"], presented_binding=before["binding"])
    assert caught.value.code == "DECISION_VALUE_INVALID"
    assert service.state() == before


def test_income_and_unknown_sources_have_no_card_recommendations():
    rows = [{"source": {"block_kind": kind}, "decision": "",
             "candidates": [{"key": "synthetic-" + kind, "pipeline_recorded": True}]}
            for kind in ("income", "unknown", "expense")]
    _attach_pipeline_recommendations(rows)
    assert rows[0]["pipeline_recommendation"] is None
    assert rows[1]["pipeline_recommendation"] is None
    assert rows[2]["pipeline_recommendation"]["candidate_key"] == "synthetic-expense"
    assert all(r["decision"] == "" for r in rows)
