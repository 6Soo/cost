"""Synthetic Kakao same-card amount pairing; no production financial data."""
import sqlite3

from app.partial_refund import refund_links, refund_group, _kakao_amount_links, read_only_scope


def database():
    db = sqlite3.connect(":memory:")
    db.execute("""CREATE TABLE transactions (
      transaction_id TEXT, transaction_direction TEXT, issuer TEXT,
      card_tail TEXT, merchant TEXT, merchant_normalized TEXT,
      amount_krw INTEGER, approval_date TEXT, posting_date TEXT,
      approval_number TEXT, original_approval_number TEXT,
      duplicate_of TEXT, conflict_reason TEXT, parse_error TEXT,
      foreign_currency TEXT, foreign_amount TEXT
    )""")
    return db


def row(db, tid, direction, merchant, amount, day="2026-10-02",
        tail="1234", original="", approval=""):
    db.execute("""INSERT INTO transactions
      (transaction_id,transaction_direction,issuer,card_tail,merchant,
       merchant_normalized,amount_krw,approval_date,posting_date,
       approval_number,original_approval_number,duplicate_of,conflict_reason,
       parse_error,foreign_currency,foreign_amount)
       VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
       (tid,direction,"국민",tail,merchant,merchant,amount,day,day,
        approval,original,None,"","","",""))


def test_unique_kakao_names_differ_auto_pair_readonly():
    db=database()
    row(db,"pay","purchase","카카오T실요금_유페이",9800)
    row(db,"cancel","cancellation","카카오T가승인_유페이",-9800,day="2026-10-03")
    before=list(db.iterdump())
    link=_kakao_amount_links(db,set(),{"cancel"})["cancel"]
    assert link["original_id"]=="pay"
    assert link["basis"]=="kakao_same_card_exact_amount"
    assert link["net_krw"]==0 and link["refund_count"]==1
    assert refund_group(db,"pay")==["pay","cancel"]
    assert refund_links(db,["cancel"])["cancel"]["original_id"]=="pay"
    with read_only_scope():
        assert refund_links(db,["cancel"])["cancel"]["original_id"]=="pay"
    assert list(db.iterdump())==before


def test_competing_originals_and_refunds_hold():
    db=database()
    row(db,"pay1","purchase","카카오택시",9800)
    row(db,"pay2","purchase","카카오쇼핑",9800)
    row(db,"cancel","cancellation","카카오T가승인",-9800)
    assert _kakao_amount_links(db,set(),{"cancel"})=={}
    db2=database()
    row(db2,"pay","purchase","카카오택시",9800)
    row(db2,"r1","cancellation","카카오T가승인",-9800)
    row(db2,"r2","cancellation","카카오택시취소",-9800)
    assert _kakao_amount_links(db2,set(),{"r1","r2"})=={}


def test_cross_card_non_kakao_and_future_payment_excluded():
    db=database()
    row(db,"other","purchase","카카오택시",9800,tail="9999")
    row(db,"nonkakao","purchase","일반택시",9800)
    row(db,"future","purchase","카카오택시",9800,day="2026-10-04")
    row(db,"cancel","cancellation","카카오T가승인",-9800)
    assert _kakao_amount_links(db,set(),{"cancel"})=={}


def test_trace_reports_existing_engine_without_writes_or_identifiers():
    from tools.trace_airline_cancellation import inspect
    db = database()
    row(db, 'private-payment', 'purchase', 'Synthetic Air', 1200, approval='A1')
    row(db, 'private-refund', 'cancellation', 'Synthetic Air', -1200, original='A1')
    before = list(db.iterdump())
    result = inspect(db, merchant='Synthetic Air', amount=1200, day='2026-10-02')
    assert result['matching_cancellations'] == 1
    assert result['diagnostics'][0]['matched_by_existing_engine'] is True
    assert 'private-' not in str(result)
    assert list(db.iterdump()) == before
