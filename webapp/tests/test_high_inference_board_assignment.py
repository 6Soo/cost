"""Existing unassigned expenses inherit only verified high-confidence card trips."""
import json
import sqlite3
from types import SimpleNamespace

from webapp.card_flow import assign_existing_local_expenses


def setup_case(*, source_trip="tour1", confidence="높음", override=False):
    conn = sqlite3.connect(":memory:")
    conn.execute("""CREATE TABLE transactions (
      transaction_id TEXT, merchant TEXT, card_kind TEXT, approval_date TEXT,
      posting_date TEXT, issuer TEXT, raw_row_json TEXT, trip_id TEXT,
      classification_source TEXT, classification_basis TEXT,
      transaction_direction TEXT, duplicate_of TEXT, conflict_reason TEXT,
      parse_error TEXT, card_tail TEXT, approval_number TEXT)""")
    conn.execute("""CREATE TABLE board_rows (
      row_id TEXT, revision INTEGER, payload_json TEXT,
      row_kind TEXT, display_tab_id TEXT)""")
    conn.execute("CREATE TABLE board_manual_overrides(row_id TEXT, field TEXT)")
    conn.execute("CREATE TABLE review_decisions(transaction_id TEXT)")
    conn.execute("CREATE TABLE transaction_review_holds(transaction_id TEXT)")
    conn.execute("CREATE TABLE transaction_company_exclusions(transaction_id TEXT, excluded INTEGER)")
    conn.execute("INSERT INTO transactions VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                 ("tx1","테스트 항공","domestic","2026-10-01","2026-10-01",
                  "국민","{}",source_trip,"inference",
                  "추론 배정 · "+confidence+" · 검증된 예약", "purchase",None,"","","1234","A1"))
    conn.execute("INSERT INTO board_rows VALUES(?,?,?,?,?)",
                 ("b1",1,json.dumps({"item":"항공료"}),"expense",None))
    if override:
        conn.execute("INSERT INTO board_manual_overrides VALUES(?,?)", ("b1","display_tab_id"))
    calls = []
    def save(**kw):
        calls.append(kw)
    flow=SimpleNamespace(board=SimpleNamespace(conn=conn, save=save),
                         trip_valid=lambda tid: tid=="tour1")
    return conn,flow,calls


def test_high_inference_fills_existing_ledger_without_new_user_navigation():
    conn,flow,calls=setup_case()
    assert assign_existing_local_expenses(flow)==1
    assert len(calls)==1
    assert calls[0]["changes"]["display_tab_id"]=="tour1"
    assert calls[0]["actor"]=="automatic"
    assert conn.execute("SELECT display_tab_id FROM board_rows").fetchone()[0] is None
    conn.close()


def test_stale_trip_or_low_confidence_does_not_overwrite():
    for opts in ({"source_trip":"missing"},{"confidence":"낮음"},{"override":True}):
        conn,flow,calls=setup_case(**opts)
        assert assign_existing_local_expenses(flow)==0
        assert not calls
        conn.close()
