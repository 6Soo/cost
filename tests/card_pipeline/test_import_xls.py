"""Binary .xls card exports are read directly by the web import, with the same duplicate protection."""
import csv
import io
import sqlite3
import sys
from pathlib import Path

import pytest

from app import Pipeline
from app.import_card import ParseError, parse_card_file

DATA = Path(__file__).parent / "data"
KB_HEADERS = ['매입일', '승인일', '승인시간', '부서번호', '부서명', '카드번호', '이용자명', '가맹점명', '업종명',
              '결제방법', '할부개월수', '승인금액', '부가세', '승인구분', '승인방식', '승인번호', '상태', '과세유형',
              '가맹점상태', '가맹점번호', '가맹점사업자등록번호', '대표자성명', '가맹점주소', '가맹점전화번호']
CSV_ROWS = [
    ['2026.10.02', '2026.10.01', '14:13:41', "'00002", '합성 주식회사', '5585-26**-****-3820', '김*형', '합성편의점',
     '편의점', '일시불', '0', '12000', '0', '국내', 'IC', '71000001', '정상', '과세', '정상', '1', '1', '홍', '서울', '02'],
    ['2026.10.02', '2026.10.01', '15:00:00', "'00002", '합성 주식회사', '5585-26**-****-3820', '김*형', '합성식당',
     '일반음식점', '일시불', '0', '45000', '0', '국내', 'IC', '71000002', '정상', '과세', '정상', '2', '2', '홍', '서울', '02'],
    ['2026.10.03', '2026.10.02', '09:30:10', "'00002", '합성 주식회사', '5585-26**-****-3820', '김*형', '합성식당',
     '일반음식점', '일시불', '0', '-45000', '0', '국내', 'IC', '71000002', '취소', '과세', '정상', '2', '2', '홍', '서울', '02'],
]


def domestic_xls() -> bytes:
    return (DATA / "kb-domestic-acquired-synthetic.xls").read_bytes()


def same_data_as_csv() -> bytes:
    """The CSV a person would have produced by saving the same sheet as text."""
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\r\n")
    writer.writerow(KB_HEADERS)
    writer.writerows(CSV_ROWS)
    return ("﻿" + buffer.getvalue()).encode("utf-8")


def test_a_binary_xls_is_parsed_with_the_same_normalized_rows_as_its_csv():
    from_xls = parse_card_file(domestic_xls(), "kb.xls", use_cache=False)
    from_csv = parse_card_file(same_data_as_csv(), "kb.csv", use_cache=False)
    assert from_xls.parser == "xls:headered" and from_csv.parser == "csv:headered"
    assert len(from_xls.rows) == len(from_csv.rows) == 3
    keys = ("approval_number", "approval_date", "posting_date", "merchant", "amount_krw",
            "transaction_direction", "card_tail")
    assert [tuple(getattr(r, k) for k in keys) for r in from_xls.rows] == \
           [tuple(getattr(r, k) for k in keys) for r in from_csv.rows]
    assert [r.amount_krw for r in from_xls.rows] == [12000, 45000, -45000]
    assert from_xls.issues == []


def test_the_original_cells_are_kept_beside_the_normalized_values():
    parsed = parse_card_file(domestic_xls(), "kb.xls", use_cache=False)
    assert parsed.rows[0].source_row[7] == "합성편의점"
    assert parsed.rows[0].raw["c7"] == "합성편의점"


def test_an_approval_file_is_stored_as_evidence_not_a_transaction():
    from app import source_links
    import sqlite3
    pipe = Pipeline(sqlite3.connect(":memory:", isolation_level=None))
    received = pipe.receive((DATA / "kb-approval-synthetic.xls").read_bytes(), "kb-approval.xls")
    assert received["channel"] == "approval"
    assert received["inserted"] == 0
    assert pipe.store.conn.execute("SELECT COUNT(*) FROM transactions").fetchone()[0] == 0
    assert pipe.store.conn.execute("SELECT COUNT(*) FROM approval_evidence").fetchone()[0] > 0
    summary = source_links.audit(pipe.store.conn)
    assert summary["approvals"] > 0
    # 같은 승인 파일을 다시 올려도 증거가 늘지 않는다.
    again = pipe.receive((DATA / "kb-approval-synthetic.xls").read_bytes(), "kb-approval.xls")
    assert again["reused"] is True
    assert pipe.store.conn.execute("SELECT COUNT(*) FROM approval_evidence").fetchone()[0] == summary["approvals"]


def test_a_missing_xls_reader_is_reported_not_guessed(monkeypatch):
    monkeypatch.setitem(sys.modules, "xlrd", None)
    with pytest.raises(ParseError) as caught:
        parse_card_file(domestic_xls(), "kb.xls", use_cache=False)
    assert caught.value.code == "XLS_READER_UNAVAILABLE"


def test_a_corrupt_xls_is_unreadable_not_a_crash():
    broken = bytes.fromhex("d0cf11e0a1b11ae1") + b"\x00" * 64
    with pytest.raises(ParseError) as caught:
        parse_card_file(broken, "broken.xls", use_cache=False)
    assert caught.value.code == "UNREADABLE_FILE"


def test_uploading_the_xls_after_the_csv_adds_no_transactions_and_keeps_decisions():
    pipe = Pipeline(sqlite3.connect(":memory:", isolation_level=None))
    first = pipe.receive(same_data_as_csv(), "kb.csv")
    assert first["inserted"] == 3
    pipe.classify_batch(first["batch_id"])
    row = pipe.get_batch(first["batch_id"])["rows"][0]
    pipe.save_decision(row["transaction_id"], row["revision"], item="소모품비", display_tab_id="unclassified",
                       tab_validator=lambda _: True, request_id="decision-1")
    again = pipe.receive(domestic_xls(), "kb.xls")
    assert again["reused"] is False
    assert again["inserted"] == 0 and again["already_present"] == 3 and again["conflicts"] == 0
    count = pipe.store.conn.execute("SELECT COUNT(*) FROM transactions").fetchone()[0]
    assert count == 3
    decided = pipe.store.conn.execute(
        "SELECT item, user_confirmed FROM transactions WHERE transaction_id=?", (row["transaction_id"],)).fetchone()
    assert decided == ("소모품비", 1)


def test_the_same_xls_twice_is_one_batch():
    pipe = Pipeline(sqlite3.connect(":memory:", isolation_level=None))
    first = pipe.receive(domestic_xls(), "kb.xls")
    second = pipe.receive(domestic_xls(), "again.xls")
    assert second["reused"] is True and second["batch_id"] == first["batch_id"]
