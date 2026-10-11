import pytest

from app.google_tsv import COLUMNS, expense_tsv


def row(transaction_id, **overrides):
    base = {"transaction_id": transaction_id, "date": "2027-08-02", "payee": "PAYEE-A", "category": "식비",
            "period": "", "reservation_no": "", "evidence": "card", "amount_krw": 10000, "status": "ready"}
    base.update(overrides)
    return base


def test_seven_columns_in_contract_order_one_row_per_transaction():
    result = expense_tsv([row("t1", period="2027-08-01~02", reservation_no="R-1", evidence="receipt")], layout="rev")
    assert len(COLUMNS) == 7
    assert result["tsv"] == "2027-08-02\tPAYEE-A\t식비\t2027-08-01~02\tR-1\t영수증\t10000\n"
    assert result["row_count"] == 1 and result["total_krw"] == 10000 and result["held"] == []


def test_refund_stays_a_separate_row_and_is_not_netted():
    result = expense_tsv([row("t1"), row("t2", amount_krw=-4000, category="식비")], layout="rev")
    assert result["row_count"] == 2
    assert result["total_krw"] == 6000
    assert "\t-4000" in result["tsv"]


def test_not_ready_and_invalid_rows_are_held_with_reason():
    result = expense_tsv([
        row("a", status="blocked"),
        row("b", amount_krw=1.5),
        row("c", evidence="cash"),
        row("d", date="2027-02-30"),
        row("e", payee=""),
        row("", ),
    ], layout="rev")
    assert result["row_count"] == 0 and result["tsv"] == ""
    reasons = {h["transaction_id"]: h["reason"] for h in result["held"]}
    assert reasons == {"a": "NOT_READY", "b": "AMOUNT_INVALID", "c": "EVIDENCE_UNKNOWN",
                       "d": "DATE_INVALID", "e": "FIELD_MISSING", "": "ID_MISSING"}


def test_same_transaction_twice_is_held_not_pasted_twice():
    result = expense_tsv([row("t1"), row("t1"), row("t2")], layout="rev")
    assert result["row_count"] == 1
    assert [h["reason"] for h in result["held"]] == ["DUPLICATE_ID", "DUPLICATE_ID"]


@pytest.mark.parametrize("payee", ["=HYPERLINK(\"x\")", "+1", "-2", "@cmd"])
def test_formula_like_text_is_neutralized(payee):
    result = expense_tsv([row("t1", payee=payee)], layout="rev")
    assert result["tsv"].split("\t")[1] == "'" + payee


def test_tabs_and_newlines_cannot_break_the_paste_row():
    result = expense_tsv([row("t1", payee="A\tB\nC")], layout="rev")
    assert result["tsv"].count("\n") == 1 and result["tsv"].split("\t")[1] == "A B C"


def test_non_standard_target_layout_is_refused():
    with pytest.raises(ValueError, match="TARGET_LAYOUT_NOT_STANDARD"):
        expense_tsv([row("t1")], layout="legacy")


@pytest.mark.parametrize('invalid,reason', [({'transaction_id': []}, 'ID_INVALID'),
                                           ({'transaction_id': '  '}, 'ID_MISSING'),
                                           ({'evidence': []}, 'EVIDENCE_UNKNOWN')])
def test_malformed_identity_and_evidence_are_held_without_losing_valid_rows(invalid, reason):
    result = expense_tsv([{**row('bad'), **invalid}, row('good')], layout='rev')
    assert result['row_count'] == 1 and result['total_krw'] == 10000
    assert result['held'][0]['reason'] == reason
    assert result['tsv'] == expense_tsv([row('good')], layout='rev')['tsv']


def test_date_object_is_held_instead_of_crashing_the_copy():
    import datetime as dt
    result = expense_tsv([row('bad', date=dt.date(2027, 8, 2)), row('good')], layout='rev')
    assert result['row_count'] == 1
    assert result['held'] == [{'transaction_id': 'bad', 'reason': 'DATE_INVALID'}]
