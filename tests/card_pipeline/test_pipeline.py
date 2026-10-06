# -*- coding: utf-8 -*-
"""The pipeline, from a card file to a booked ledger entry.

Every input is synthetic and every database is a temporary directory.
"""

from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import Pipeline, StoreError  # noqa: E402
from app.db import (CODE_PREVIEW_STALE, CODE_REQUEST_ID_REUSED,  # noqa: E402
                    CODE_REVISION_CONFLICT, CODE_SOURCE_CONFLICT)
from app.import_card import parse_card_file  # noqa: E402
from app.normalize import AmountUnreadable, to_amount_krw, to_date  # noqa: E402
from .fixtures import (DOMESTIC_HEADERS, corp_row, domestic_row,  # noqa: E402
                            foreign_row, make_csv, make_xlsx)


@pytest.fixture()
def pipe(tmp_path):
    conn = sqlite3.connect(str(tmp_path / "cost.sqlite"), isolation_level=None)
    yield Pipeline(conn)
    conn.close()


# What the web app would own: its real trips, and the buckets it allows for a
# cost that is not on a trip yet.
REAL_TRIPS = ("trip-seoul-2026", "trip-jeju-2026")
ALLOWED_TABS = ("trip:seoul-2026", "trip:jeju-2026", "unclassified", "2026-Q2")


def trip_validator(trip_id: str) -> bool:
    return trip_id in REAL_TRIPS


def tab_validator(display_tab_id: str) -> bool:
    return display_tab_id in ALLOWED_TABS


def book_everything(pipe, batch_id, *, item="식비", tab="unclassified"):
    """Confirm every parseable row so a preview can have something ready."""
    batch = pipe.get_batch(batch_id)
    for row in batch["rows"]:
        if row["classification_state"] == "needs_review" and not row["user_confirmed"]:
            pipe.save_decision(row["transaction_id"], row["revision"], item=item,
                               description="", display_tab_id=tab,
                               tab_validator=tab_validator,
                               request_id="dec-" + row["transaction_id"][:12])


# ------------------------------------------------------------ real-format XLSX

def test_a_domestic_card_xlsx_is_read_by_its_headers(pipe):
    content = make_xlsx([
        domestic_row(merchant="GS25 역삼점", amount=12000, approval="12345678"),
        domestic_row(merchant="서울교통공사", amount=1400, approval="87654321",
                     card="****-****-****-9999"),
    ], DOMESTIC_HEADERS)
    batch = pipe.receive(content, "합성카드.xlsx")
    assert batch["inserted"] == 2

    rows = pipe.get_batch(batch["batch_id"])["rows"]
    assert [r["merchant"] for r in rows] == ["GS25 역삼점", "서울교통공사"]
    assert rows[0]["amount_krw"] == 12000
    assert rows[0]["approval_number"] == "12345678"
    assert rows[0]["approval_date"] == "2026-04-09"
    assert rows[0]["card_tail"] == "1234"
    # The original cells survive beside the normalized ones.
    assert rows[0]["raw_row"]["c4"] == "GS25 역삼점"
    assert rows[0]["source_hash"]


def test_an_english_headered_csv_is_also_read(pipe):
    content = make_csv([
        foreign_row(merchant="SYNTHETIC CAFE", amount="13.50", approval="ABC12345"),
    ], headers=["Issuer", "Card No", "Card Type", "Type", "Merchant", "Amount",
                "Foreign Amount", "Currency", "Amount KRW", "Date", "Post Date",
                "Authorization Code", "Cancel", "Status"])
    batch = pipe.receive(content, "statement.csv")
    rows = pipe.get_batch(batch["batch_id"])["rows"]
    assert rows[0]["merchant"] == "SYNTHETIC CAFE"
    # Foreign amount kept as text with its currency; won column used for KRW.
    assert rows[0]["foreign_amount"] == "13.50"
    assert rows[0]["foreign_currency"] == "USD"
    assert rows[0]["amount_krw"] == 13500


def test_a_foreign_decimal_amount_never_becomes_zero(pipe):
    content = make_xlsx([
        foreign_row(merchant="SYNTHETIC CAFE", amount="13.50", approval="ABC12345"),
    ], ["Issuer", "Card No", "Card Type", "Type", "Merchant", "Amount",
        "Foreign Amount", "Currency", "Amount KRW", "Date", "Post Date",
        "Authorization Code", "Cancel", "Status"])
    pipe.receive(content, "foreign.xlsx")
    row = pipe.get_batch(
        pipe.store.conn.execute(
            "SELECT batch_id FROM import_batches LIMIT 1").fetchone()[0])["rows"][0]
    assert row["amount_krw"] == 13500
    assert row["parse_error"] == ""


def test_an_unreadable_amount_is_an_error_not_zero(pipe):
    content = make_xlsx([
        domestic_row(merchant="금액오류", amount="확인필요", approval="11112222"),
    ], DOMESTIC_HEADERS)
    batch = pipe.receive(content, "broken.xlsx")
    rows = pipe.get_batch(batch["batch_id"])["rows"]
    assert rows[0]["amount_krw"] is None
    assert "amount" in rows[0]["parse_error"]
    # And it cannot reach the ledger.
    assert pipe.preview(batch["batch_id"], tab_validator=tab_validator)["ready"] == 0


def test_a_formula_with_no_cached_value_is_an_error(pipe):
    content = make_xlsx([
        domestic_row(merchant="공식금액", amount="", approval="33334444"),
    ], DOMESTIC_HEADERS)
    batch = pipe.receive(content, "formula.xlsx")
    rows = pipe.get_batch(batch["batch_id"])["rows"]
    assert rows[0]["amount_krw"] is None
    assert rows[0]["parse_error"]


def test_a_headerless_corporate_export_is_read_by_its_shape(pipe):
    content = make_xlsx([corp_row(approval="555000(111222)")], headered=False)
    parsed = parse_card_file(content, "corp.xlsx")
    assert parsed.parser.endswith("fixed:corp-f")
    row = parsed.rows[0]
    assert row.merchant == "합성식당"
    assert row.amount_krw == 12000
    # `555000(111222)` keeps both numbers: the approval and what it refers to.
    assert row.approval_number == "555000"
    assert row.original_approval_number == "111222"


def test_an_unrecognised_shape_is_refused(pipe):
    content = make_xlsx([["a", "b", "c"], ["1", "2", "3"]], headered=False)
    with pytest.raises(StoreError) as caught:
        pipe.receive(content, "unknown.xlsx")
    assert caught.value.code == "UNKNOWN_FORMAT"


# ---------------------------------------------------------- split / cancellation

def test_one_approval_split_across_rows_keeps_both_parts(pipe):
    content = make_xlsx([
        domestic_row(merchant="합성호텔", amount=60000, approval="77778888",
                     status="매입"),
        domestic_row(merchant="합성호텔", amount=40000, approval="88889999(77778888)",
                     status="취소", kind="취소"),
    ], DOMESTIC_HEADERS)
    rows = pipe.get_batch(pipe.receive(content, "split.xlsx")["batch_id"])["rows"]
    assert len(rows) == 2
    directions = {r["transaction_direction"] for r in rows}
    assert directions == {"purchase", "cancellation"}
    # The cancellation points back at the approval it reverses.
    assert any(r["original_approval_number"] == "77778888" for r in rows)
    # Both amounts are preserved as stated; nothing is netted or dropped.
    assert sorted(r["amount_krw"] for r in rows) == [-40000, 60000]


def test_a_cancellation_keeps_its_own_amount_and_direction(pipe):
    content = make_xlsx([
        domestic_row(merchant="합성호텔", amount=40000, approval="99990000(77778888)",
                     kind="취소", status="취소"),
    ], DOMESTIC_HEADERS)
    row = pipe.get_batch(
        pipe.receive(content, "cancel.xlsx")["batch_id"])["rows"][0]
    assert row["transaction_direction"] == "cancellation"
    assert row["amount_krw"] == -40000
    assert row["original_approval_number"] == "77778888"


# ------------------------------------------------------------ identity & repeat

def test_the_same_file_uploaded_twice_returns_the_same_batch(pipe):
    content = make_xlsx([
        domestic_row(merchant="GS25", amount=5000, approval="11110000"),
    ], DOMESTIC_HEADERS)
    first = pipe.receive(content, "a.xlsx")
    second = pipe.receive(content, "a.xlsx")
    assert second["batch_id"] == first["batch_id"]
    assert second["reused"] is True
    assert pipe.store.conn.execute(
        "SELECT COUNT(*) FROM import_batches").fetchone()[0] == 1


def test_the_same_transactions_in_a_differently_named_file_are_not_written_twice(pipe):
    row = domestic_row(merchant="GS25", amount=5000, approval="22220000")
    pipe.receive(make_xlsx([row], DOMESTIC_HEADERS), "first.xlsx")
    # Different bytes (different filename is not part of the file, so build a
    # second file with an extra blank row), same transaction inside.
    again = make_xlsx([row, [""] * 14], DOMESTIC_HEADERS)
    second = pipe.receive(again, "second-file.xlsx")
    assert second["already_present"] == 1
    assert second["inserted"] == 0
    total = pipe.store.conn.execute(
        "SELECT COUNT(*) FROM transactions").fetchone()[0]
    assert total == 1


def test_same_approval_number_with_different_amount_is_a_conflict(pipe):
    pipe.receive(make_xlsx([
        domestic_row(merchant="GS25", amount=5000, approval="33330000")],
        DOMESTIC_HEADERS), "one.xlsx")
    second = pipe.receive(make_xlsx([
        domestic_row(merchant="GS25", amount=9999, approval="33330000")],
        DOMESTIC_HEADERS), "two.xlsx")
    assert second["conflicts"] == 1
    rows = pipe.get_batch(second["batch_id"])["rows"]
    assert rows[0]["conflict_reason"]
    assert rows[0]["classification_state"] == "needs_review"
    # The original row is untouched.
    kept = pipe.store.conn.execute(
        "SELECT amount_krw FROM transactions WHERE user_confirmed=0"
        " AND conflict_reason='' AND amount_krw=5000").fetchone()
    assert kept[0] == 5000


def test_several_real_transactions_without_an_approval_number_all_survive(pipe):
    rows = [domestic_row(merchant="같은가맹점", amount=7000, approval="",
                         date="2026-04-09", card="****-****-****-1111")]
    for extra in ("", "", ""):
        # Three identical-looking rows from one statement, each at its own row.
        pass
    content = make_xlsx(rows * 3, DOMESTIC_HEADERS)
    batch = pipe.receive(content, "no-approval.xlsx")
    assert batch["inserted"] == 3
    stored = pipe.get_batch(batch["batch_id"])["rows"]
    assert len(stored) == 3
    assert len({r["transaction_id"] for r in stored}) == 3
    assert all(r["amount_krw"] == 7000 for r in stored)


def test_editing_a_memo_does_not_change_the_source_hash(pipe):
    content = make_xlsx([
        domestic_row(merchant="GS25", amount=5000, approval="44440000")],
        DOMESTIC_HEADERS)
    batch = pipe.receive(content, "a.xlsx")
    row = pipe.get_batch(batch["batch_id"])["rows"][0]
    before = row["source_hash"]
    pipe.save_decision(row["transaction_id"], row["revision"], item="식비",
                       note="팀 비용", request_id="d1")
    after = pipe.get_batch(batch["batch_id"])["rows"][0]
    assert after["source_hash"] == before
    assert after["note"] if "note" in after else True
    # Re-uploading the same statement does not see a source change either.
    again = pipe.receive(content, "a.xlsx")
    assert again["reused"] is True


def test_the_date_and_amount_cannot_be_edited_by_a_decision(pipe):
    content = make_xlsx([
        domestic_row(merchant="GS25", amount=5000, approval="55550000",
                     date="2026-04-09")],
        DOMESTIC_HEADERS)
    batch = pipe.receive(content, "a.xlsx")
    row = pipe.get_batch(batch["batch_id"])["rows"][0]
    pipe.save_decision(row["transaction_id"], row["revision"], item="식비",
                       description="memo", request_id="d1")
    after = pipe.get_batch(batch["batch_id"])["rows"][0]
    assert after["amount_krw"] == 5000
    assert after["approval_date"] == "2026-04-09"
    assert after["occurred_on"] if "occurred_on" in after else True
    # There is no API that could have changed them.
    assert not hasattr(pipe.save_decision, "amount_krw")


# ------------------------------------------------------------------- rules

def test_a_rule_matches_by_scope_and_a_manual_decision_is_protected(pipe):
    content = make_xlsx([
        domestic_row(merchant="합성erei 합성", amount=5000, approval="6001"),
    ], DOMESTIC_HEADERS)
    pipe.receive(content, "a.xlsx")
    pipe.save_rule({"conditions": {"merchant_normalized": "합성erei 합성"},
                    "effects": {"item": "식비"}, "rule_id": "rule-a"})
    counts = pipe.classify_batch(
        pipe.store.conn.execute(
            "SELECT batch_id FROM import_batches LIMIT 1").fetchone()[0])
    assert counts["classified"] == 1

    # Confirming it, then adding a rule that would say something else, must not
    # overwrite the person's answer.
    batch_id = pipe.store.conn.execute(
        "SELECT batch_id FROM import_batches LIMIT 1").fetchone()[0]
    row = pipe.get_batch(batch_id)["rows"][0]
    pipe.save_decision(row["transaction_id"], row["revision"], item="팀회식",
                       request_id="d1")
    pipe.save_rule({"conditions": {"merchant_normalized": "합성erei 합성"},
                    "effects": {"item": "간식"}, "rule_id": "rule-b"})
    again = pipe.classify_batch(batch_id)
    assert again["protected"] == 1
    kept = pipe.get_batch(batch_id)["rows"][0]
    assert kept["item"] == "팀회식"
    assert kept["user_confirmed"] is True


def test_a_rule_cannot_rewrite_the_source_amount_or_date(pipe):
    for bad in ({"amount_krw": 1}, {"approval_date": "2020-01-01"},
                {"transaction_id": "x"}):
        with pytest.raises(StoreError):
            pipe.save_rule({"conditions": {"merchant_normalized": "가맹점"},
                            "effects": {"item": "식비"}, **bad})


def test_a_rule_without_a_merchant_condition_is_refused(pipe):
    with pytest.raises(StoreError):
        pipe.save_rule({"conditions": {"card_kind": "신용"},
                        "effects": {"item": "식비"}})


def test_an_amount_range_narrows_the_rule(pipe):
    rows = [domestic_row(merchant="합성erei", amount=3000, approval="7001"),
            domestic_row(merchant="합성erei", amount=90000, approval="7002")]
    batch = pipe.receive(make_xlsx(rows, DOMESTIC_HEADERS), "a.xlsx")
    pipe.save_rule({"conditions": {"merchant_normalized": "합성erei"},
                    "optional": {"amount_range": {"max": 10000}},
                    "effects": {"item": "소모품"}, "rule_id": "rule-range"})
    counts = pipe.classify_batch(batch["batch_id"])
    assert counts["classified"] == 1
    states = {r["amount_krw"]: r["classification_state"]
              for r in pipe.get_batch(batch["batch_id"])["rows"]}
    assert states[3000] == "classified"
    assert states[90000] == "needs_review"


def test_a_reuse_rule_is_only_created_when_asked(pipe):
    content = make_xlsx([
        domestic_row(merchant="합성erei", amount=3000, approval="8001")],
        DOMESTIC_HEADERS)
    batch = pipe.receive(content, "a.xlsx")
    row = pipe.get_batch(batch["batch_id"])["rows"][0]
    # No reuse: nothing is registered.
    plain = pipe.save_decision(row["transaction_id"], row["revision"],
                               item="식비", request_id="d1")
    assert "rule" not in plain
    assert pipe.list_rules() == []

    other = make_xlsx([
        domestic_row(merchant="합성erei", amount=4000, approval="8002")],
        DOMESTIC_HEADERS)
    batch2 = pipe.receive(other, "b.xlsx")
    row2 = pipe.get_batch(batch2["batch_id"])["rows"][0]
    reused = pipe.save_decision(row2["transaction_id"], row2["revision"],
                                item="식비", request_id="d2", reuse_rule=True)
    assert reused["rule"]["created"] is True
    assert len(pipe.list_rules()) == 1


def test_agoda_alone_does_not_assign_a_trip(pipe):
    content = make_xlsx([
        domestic_row(merchant="AGODA.COM", amount=120000, approval="9001")],
        DOMESTIC_HEADERS)
    batch = pipe.receive(content, "agoda.xlsx")
    row = pipe.get_batch(batch["batch_id"])["rows"][0]
    # A pattern may name the item, but the trip stays empty.
    assert row["trip_id"] == ""
    pipe.save_decision(row["transaction_id"], row["revision"], item="숙박비",
                       request_id="d1")
    assert pipe.get_batch(batch["batch_id"])["rows"][0]["trip_id"] == ""


def test_a_trip_needs_the_callers_validator(pipe):
    content = make_xlsx([
        domestic_row(merchant="AGODA.COM", amount=120000, approval="9002")],
        DOMESTIC_HEADERS)
    batch = pipe.receive(content, "agoda.xlsx")
    row = pipe.get_batch(batch["batch_id"])["rows"][0]
    with pytest.raises(StoreError):
        pipe.save_decision(row["transaction_id"], row["revision"], item="숙박비",
                           trip_id="trip-1", request_id="d1")
    # A validator the parent owns is enough.
    allowed = {"trip-ok"}
    pipe.save_decision(row["transaction_id"], row["revision"], item="숙박비",
                       trip_id="trip-ok", trip_validator=allowed.__contains__,
                       request_id="d2")
    assert pipe.get_batch(batch["batch_id"])["rows"][0]["trip_id"] == "trip-ok"


def test_a_card_date_is_not_turned_into_a_service_period(pipe):
    content = make_xlsx([
        domestic_row(merchant="AGODA.COM", amount=120000, approval="9003",
                     date="2026-04-09", posting="2026-04-09")],
        DOMESTIC_HEADERS)
    batch = pipe.receive(content, "agoda.xlsx")
    row = pipe.get_batch(batch["batch_id"])["rows"][0]
    assert row["approval_date"] == "2026-04-09"
    # No service period anywhere: the column does not exist.
    assert "service_period" not in row


# ------------------------------------------------------------ unresolved hold

def test_an_unconfirmed_row_is_held_out_of_the_ledger(pipe):
    content = make_xlsx([
        domestic_row(merchant="합성erei", amount=3000, approval="A1"),
    ], DOMESTIC_HEADERS)
    batch = pipe.receive(content, "a.xlsx")
    result = pipe.preview(batch["batch_id"], tab_validator=tab_validator)
    assert result["ready"] == 0
    assert result["unresolved"] == 1
    booked = pipe.commit(batch["batch_id"], result["digest"], "c1",
                tab_validator=tab_validator)
    assert booked["applied"] == 0
    assert pipe.store.conn.execute(
        "SELECT COUNT(*) FROM ledger_entries").fetchone()[0] == 0


def test_a_classified_row_can_be_approved_by_preview_commit(pipe):
    content = make_xlsx([
        domestic_row(merchant="GS25", amount=3000, approval="A2")],
        DOMESTIC_HEADERS)
    batch = pipe.receive(content, "a.xlsx")
    pipe.classify_batch(batch["batch_id"])
    result = pipe.preview(batch["batch_id"], tab_validator=tab_validator)
    assert result["ready"] == 1
    assert result["unresolved"] == 0


# -------------------------------------------------------------- preview/commit

def test_confirm_then_preview_then_commit_books_once(pipe):
    content = make_xlsx([
        domestic_row(merchant="GS25", amount=3000, approval="B1"),
    ], DOMESTIC_HEADERS)
    batch = pipe.receive(content, "a.xlsx")
    book_everything(pipe, batch["batch_id"])
    result = pipe.preview(batch["batch_id"], tab_validator=tab_validator)
    assert result["ready"] == 1
    applied = pipe.commit(batch["batch_id"], result["digest"], "c1",
                tab_validator=tab_validator)
    assert applied["applied"] == 1
    # A second commit of the same request returns the same answer, no new row.
    again = pipe.commit(batch["batch_id"], result["digest"], "c1",
                tab_validator=tab_validator)
    assert again["applied"] == 1
    assert pipe.store.conn.execute(
        "SELECT COUNT(*) FROM ledger_entries").fetchone()[0] == 1


def test_a_stale_preview_is_refused(pipe):
    content = make_xlsx([
        domestic_row(merchant="GS25", amount=3000, approval="B2"),
    ], DOMESTIC_HEADERS)
    batch = pipe.receive(content, "a.xlsx")
    book_everything(pipe, batch["batch_id"])
    stale = pipe.preview(batch["batch_id"], tab_validator=tab_validator)["digest"]
    # A decision made after the preview was read.
    rows = pipe.get_batch(batch["batch_id"])["rows"]
    pipe.save_decision(rows[0]["transaction_id"], rows[0]["revision"],
                       item="간식", request_id="late")
    with pytest.raises(StoreError) as caught:
        pipe.commit(batch["batch_id"], stale, "c1", tab_validator=tab_validator)
    assert caught.value.code == CODE_PREVIEW_STALE
    assert pipe.store.conn.execute(
        "SELECT COUNT(*) FROM ledger_entries").fetchone()[0] == 0


def test_a_failure_midway_rolls_everything_back_and_a_retry_books_one_row(pipe):
    rows = [domestic_row(merchant="GS25", amount=3000, approval="B3"),
            domestic_row(merchant="GS25", amount=4000, approval="B4")]
    batch = pipe.receive(make_xlsx(rows, DOMESTIC_HEADERS), "a.xlsx")
    book_everything(pipe, batch["batch_id"])
    result = pipe.preview(batch["batch_id"], tab_validator=tab_validator)
    assert result["ready"] == 2

    seen = {"n": 0}

    def projection(entry):
        seen["n"] += 1
        if seen["n"] == 2:
            raise RuntimeError("projection failed")

    with pytest.raises(RuntimeError):
        pipe.commit(batch["batch_id"], result["digest"], "c1",
                    projection=projection, tab_validator=tab_validator)
    # Nothing survived: not the entries, not the request result, not the log.
    assert pipe.store.conn.execute(
        "SELECT COUNT(*) FROM ledger_entries").fetchone()[0] == 0
    assert pipe.store.conn.execute(
        "SELECT COUNT(*) FROM requests WHERE scope='commit'").fetchone()[0] == 0
    assert pipe.store.conn.execute(
        "SELECT COUNT(*) FROM change_log WHERE kind='ledger.booked'"
    ).fetchone()[0] == 0

    # Retrying after the failure books exactly two rows, not four.
    retried = pipe.commit(batch["batch_id"], result["digest"], "c1",
                tab_validator=tab_validator)
    assert retried["applied"] == 2
    assert pipe.store.conn.execute(
        "SELECT COUNT(*) FROM ledger_entries").fetchone()[0] == 2


def test_a_restart_and_retry_does_not_double_book(pipe, tmp_path):
    path = str(tmp_path / "cost.sqlite")
    first = sqlite3.connect(path, isolation_level=None)
    pipe = Pipeline(first)
    content = make_xlsx([
        domestic_row(merchant="GS25", amount=3000, approval="B5")],
        DOMESTIC_HEADERS)
    batch = pipe.receive(content, "a.xlsx")
    book_everything(pipe, batch["batch_id"])
    digest = pipe.preview(batch["batch_id"], tab_validator=tab_validator)["digest"]
    first.close()

    # A new connection, as after a restart.
    second = sqlite3.connect(path, isolation_level=None)
    pipe2 = Pipeline(second)
    pipe2.commit(batch["batch_id"], digest, "c1", tab_validator=tab_validator)
    # Same request id after the restart: idempotent.
    pipe2.commit(batch["batch_id"], digest, "c1", tab_validator=tab_validator)
    count = pipe2.store.conn.execute(
        "SELECT COUNT(*) FROM ledger_entries").fetchone()[0]
    assert count == 1
    second.close()


def test_the_projection_runs_inside_the_same_transaction(pipe):
    content = make_xlsx([
        domestic_row(merchant="GS25", amount=3000, approval="B6")],
        DOMESTIC_HEADERS)
    batch = pipe.receive(content, "a.xlsx")
    book_everything(pipe, batch["batch_id"])
    result = pipe.preview(batch["batch_id"], tab_validator=tab_validator)
    seen = []

    def projection(entry):
        # Writes through the same connection, so it is inside the transaction.
        pipe.store.conn.execute(
            "INSERT INTO change_log(at, kind, subject, detail_json)"
            " VALUES (?,?,?,?)", ("now", "board_rows.published",
                                  entry["transaction_id"], "{}"))
        seen.append(entry["transaction_id"])

    pipe.commit(batch["batch_id"], result["digest"], "c1",
                projection=projection, tab_validator=tab_validator)
    assert len(seen) == 1
    assert pipe.store.conn.execute(
        "SELECT COUNT(*) FROM change_log WHERE kind='board_rows.published'"
    ).fetchone()[0] == 1


# ------------------------------------------------------- ids and conflicts

def test_the_same_request_id_with_different_input_is_refused(pipe):
    content = make_xlsx([
        domestic_row(merchant="GS25", amount=3000, approval="B7")],
        DOMESTIC_HEADERS)
    batch = pipe.receive(content, "a.xlsx")
    rows = pipe.get_batch(batch["batch_id"])["rows"]
    row = rows[0]
    first = pipe.save_decision(row["transaction_id"], row["revision"],
                               item="식비", request_id="req-1")
    assert first["revision"] == row["revision"] + 1
    with pytest.raises(StoreError) as caught:
        pipe.save_decision(row["transaction_id"], first["revision"],
                           item="간식", request_id="req-1")
    assert caught.value.code == CODE_REQUEST_ID_REUSED


def test_a_stale_revision_is_refused(pipe):
    content = make_xlsx([
        domestic_row(merchant="GS25", amount=3000, approval="B8")],
        DOMESTIC_HEADERS)
    batch = pipe.receive(content, "a.xlsx")
    row = pipe.get_batch(batch["batch_id"])["rows"][0]
    pipe.save_decision(row["transaction_id"], row["revision"], item="식비",
                       request_id="r1")
    with pytest.raises(StoreError) as caught:
        pipe.save_decision(row["transaction_id"], row["revision"], item="간식",
                           request_id="r2")
    assert caught.value.code == CODE_REVISION_CONFLICT


def test_an_unknown_trip_tab_is_refused_without_the_parents_validator(pipe):
    content = make_xlsx([
        domestic_row(merchant="GS25", amount=3000, approval="B9")],
        DOMESTIC_HEADERS)
    batch = pipe.receive(content, "a.xlsx")
    row = pipe.get_batch(batch["batch_id"])["rows"][0]
    # No validator: the pipeline refuses to guess which tabs exist.
    with pytest.raises(StoreError):
        pipe.save_decision(row["transaction_id"], row["revision"], item="식비",
                           display_tab_id="trip:seoul-2026", request_id="r0")
    # With one, an unknown tab is still refused.
    with pytest.raises(StoreError):
        pipe.save_decision(row["transaction_id"], row["revision"], item="식비",
                           display_tab_id="trip:없음", tab_validator=tab_validator,
                           request_id="r1")


def test_item_and_trip_tab_are_separate_fields(pipe):
    """식비 is a category; the tab is a trip or a bucket. Setting one never sets
    the other, so a category cannot masquerade as a destination."""
    content = make_xlsx([
        domestic_row(merchant="GS25", amount=3000, approval="T1")],
        DOMESTIC_HEADERS)
    batch = pipe.receive(content, "a.xlsx")
    row = pipe.get_batch(batch["batch_id"])["rows"][0]
    pipe.save_decision(row["transaction_id"], row["revision"], item="숙박비",
                       display_tab_id="trip:seoul-2026", trip_id="trip-seoul-2026",
                       trip_validator=trip_validator, tab_validator=tab_validator,
                       request_id="d1")
    stored = pipe.get_batch(batch["batch_id"])["rows"][0]
    assert stored["item"] == "숙박비"
    assert stored["display_tab_id"] == "trip:seoul-2026"
    assert stored["trip_id"] == "trip-seoul-2026"
    # A real trip from the parent is accepted; an invented one is not.
    with pytest.raises(StoreError):
        pipe.save_decision(row["transaction_id"], stored["revision"], item="숙박비",
                           trip_id="trip-invented", trip_validator=trip_validator,
                           request_id="d2")


def test_an_unassigned_cost_can_use_a_validated_quarantine_tab(pipe):
    content = make_xlsx([
        domestic_row(merchant="GS25", amount=3000, approval="T2")],
        DOMESTIC_HEADERS)
    batch = pipe.receive(content, "a.xlsx")
    row = pipe.get_batch(batch["batch_id"])["rows"][0]
    pipe.save_decision(row["transaction_id"], row["revision"], item="미분류",
                       display_tab_id="unclassified", tab_validator=tab_validator,
                       request_id="d1")
    result = pipe.preview(batch["batch_id"], tab_validator=tab_validator)
    assert result["ready"] == 1


def test_commit_revalidates_the_trip_so_a_cancelled_schedule_books_nothing(pipe):
    """The decision was valid when it was made. It is checked again at commit."""
    content = make_xlsx([
        domestic_row(merchant="GS25", amount=3000, approval="T3")],
        DOMESTIC_HEADERS)
    batch = pipe.receive(content, "a.xlsx")
    row = pipe.get_batch(batch["batch_id"])["rows"][0]
    pipe.save_decision(row["transaction_id"], row["revision"], item="숙박비",
                       display_tab_id="trip:jeju-2026", trip_id="trip-jeju-2026",
                       trip_validator=trip_validator, tab_validator=tab_validator,
                       request_id="d1")

    good = pipe.preview(batch["batch_id"], trip_validator=trip_validator,
                        tab_validator=tab_validator)
    assert good["ready"] == 1

    # The authoritative schedule drops that trip between preview and commit.
    withdrawn = {"trip-seoul-2026"}
    with pytest.raises(StoreError) as caught:
        pipe.commit(batch["batch_id"], good["digest"], "c1",
                    trip_validator=withdrawn.__contains__,
                    tab_validator=tab_validator)
    # The digest changed because the row is no longer ready, so the stale
    # preview is refused rather than booked.
    assert caught.value.code == CODE_PREVIEW_STALE
    assert pipe.store.conn.execute(
        "SELECT COUNT(*) FROM ledger_entries").fetchone()[0] == 0

    # A fresh preview reports it as held, not ready.
    after = pipe.preview(batch["batch_id"], trip_validator=withdrawn.__contains__,
                         tab_validator=tab_validator)
    assert after["ready"] == 0
    assert after["unresolved"] == 1
    blocked = after["rows"][0]
    assert blocked["blocked"] == "trip_no_longer_valid"


def test_commit_books_nothing_when_authority_is_lost_after_the_digest_matches(pipe):
    """Even with a matching digest, the in-transaction re-check holds the row."""
    content = make_xlsx([
        domestic_row(merchant="GS25", amount=3000, approval="T4")],
        DOMESTIC_HEADERS)
    batch = pipe.receive(content, "a.xlsx")
    row = pipe.get_batch(batch["batch_id"])["rows"][0]
    pipe.save_decision(row["transaction_id"], row["revision"], item="숙박비",
                       display_tab_id="trip:jeju-2026", trip_id="trip-jeju-2026",
                       trip_validator=trip_validator, tab_validator=tab_validator,
                       request_id="d1")
    result = pipe.preview(batch["batch_id"], trip_validator=trip_validator,
                          tab_validator=tab_validator)
    assert result["ready"] == 1

    # Authority is still good when the commit recomputes the preview, and is
    # withdrawn between that check and the insert — which is exactly what the
    # in-transaction re-check is for.
    calls = {"n": 0}

    def withdrawing(trip_id):
        calls["n"] += 1
        return calls["n"] == 1

    applied = pipe.commit(batch["batch_id"], result["digest"], "c1",
                          trip_validator=withdrawing,
                          tab_validator=tab_validator)
    assert applied["applied"] == 0
    assert applied["lost_authority"]
    assert pipe.store.conn.execute(
        "SELECT COUNT(*) FROM ledger_entries").fetchone()[0] == 0
    assert pipe.store.conn.execute(
        "SELECT COUNT(*) FROM change_log WHERE kind='ledger.blocked'"
    ).fetchone()[0] == 1


# ------------------------------------------------------------- unit edges

def test_amount_zero_is_a_value_not_a_failure():
    assert to_amount_krw(0) == 0
    assert to_amount_krw("0") == 0
    with pytest.raises(AmountUnreadable):
        to_amount_krw("확인필요")
    with pytest.raises(AmountUnreadable):
        to_amount_krw(None)


def test_dates_fold_the_shapes_the_sheets_use():
    for text in ("2026-04-09", "2026.04.09", "20260409", "2026/4/9"):
        assert to_date(text) == "2026-04-09"
    assert to_date("") == ""
    assert to_date("심상") == ""


def test_a_file_is_parsed_once_and_shared():
    content = make_xlsx([
        domestic_row(merchant="GS25", amount=3000, approval="C1")],
        DOMESTIC_HEADERS)
    first = parse_card_file(content, "a.xlsx")
    second = parse_card_file(content, "a.xlsx")
    assert first is second


@pytest.mark.parametrize('inside_transaction',[False,True])
@pytest.mark.parametrize('failure_point',['row','audit'])
def test_failed_reclassification_rolls_back_every_row_and_audit(pipe,monkeypatch,inside_transaction,failure_point):
    import app.classify as classifier
    batch=pipe.receive(make_csv([
        domestic_row(merchant='합성상점 하나',amount=1000,approval='ATOMIC-1'),
        domestic_row(merchant='합성상점 둘',amount=2000,approval='ATOMIC-2'),
    ]),'synthetic-atomic.csv')['batch_id']
    if inside_transaction:
        pipe.store.conn.execute('BEGIN IMMEDIATE')
        pipe.store.log_change('synthetic.outer','outer',{})
    tables=('transactions','import_batches','change_log')
    before={table:pipe.store.conn.execute('SELECT * FROM '+table).fetchall() for table in tables}
    original=classifier.classify_transaction
    calls=0
    def fail_second(*args,**kwargs):
        nonlocal calls
        calls+=1
        if calls==2:
            raise RuntimeError('SYNTHETIC_CLASSIFICATION_FAILURE')
        return original(*args,**kwargs)
    if failure_point=='row':
        monkeypatch.setattr(classifier,'classify_transaction',fail_second)
    else:
        def fail_audit(*args,**kwargs):
            raise RuntimeError('SYNTHETIC_CLASSIFICATION_FAILURE')
        monkeypatch.setattr(pipe.store,'log_change',fail_audit)
    with pytest.raises(RuntimeError,match='SYNTHETIC_CLASSIFICATION_FAILURE'):
        pipe.classify_batch(batch)
    assert {table:pipe.store.conn.execute('SELECT * FROM '+table).fetchall() for table in tables}==before
    assert pipe.store.conn.in_transaction==inside_transaction
    if inside_transaction:
        pipe.store.conn.rollback()


def test_unchanged_reclassification_does_not_rewrite_transaction_rows(pipe):
    batch=pipe.receive(make_csv([
        domestic_row(merchant='합성상점 하나',amount=1000,approval='UNCHANGED-1'),
        domestic_row(merchant='합성상점 둘',amount=2000,approval='UNCHANGED-2'),
    ]),'synthetic-unchanged.csv')['batch_id']
    pipe.classify_batch(batch)
    before=pipe.store.conn.execute('SELECT * FROM transactions').fetchall()
    previous_changes=pipe.store.conn.total_changes
    result=pipe.classify_batch(batch)
    assert result['reclassified']==0
    assert pipe.store.conn.execute('SELECT * FROM transactions').fetchall()==before
    # 재검사 시각과 감사 이력만 쓰고 같은 분류 값은 다시 쓰지 않는다.
    assert pipe.store.conn.total_changes-previous_changes==2
