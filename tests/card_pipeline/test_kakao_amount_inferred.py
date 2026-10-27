"""Synthetic Kakao same-card amount pairing; no production financial data."""
import sqlite3

from app.partial_refund import refund_links, refund_group


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
    link=refund_links(db,["cancel"])["cancel"]
    assert link["original_id"]=="pay"
    assert link["basis"]=="kakao_same_card_exact_amount_inferred"
    assert link["net_krw"]==0 and link["refund_count"]==1
    assert refund_group(db,"pay")==["pay","cancel"]
    assert list(db.iterdump())==before


def test_competing_originals_and_refunds_hold():
    db=database()
    row(db,"pay1","purchase","카카오택시",9800)
    row(db,"pay2","purchase","카카오쇼핑",9800)
    row(db,"cancel","cancellation","카카오T가승인",-9800)
    assert refund_links(db,["cancel"])=={}
    db2=database()
    row(db2,"pay","purchase","카카오택시",9800)
    row(db2,"r1","cancellation","카카오T가승인",-9800)
    row(db2,"r2","cancellation","카카오택시취소",-9800)
    assert refund_links(db2,["r1","r2"])=={}


def test_cross_card_non_kakao_and_future_payment_excluded():
    db=database()
    row(db,"other","purchase","카카오택시",9800,tail="9999")
    row(db,"nonkakao","purchase","일반택시",9800)
    row(db,"future","purchase","카카오택시",9800,day="2026-10-04")
    row(db,"cancel","cancellation","카카오T가승인",-9800)
    assert refund_links(db,["cancel"])=={}
