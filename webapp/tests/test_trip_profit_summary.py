"""여행별 손익 전체 표(`/trips/profit`)와 XLSX 내보내기. 합성 자료와 합성 계정만 쓴다."""
import io
import json
import os
import threading
import urllib.error
import urllib.request

import pytest
from openpyxl import load_workbook

from webapp import access_control
from webapp import ledger_board as board_mod
from webapp import trip_profit_summary as tps
from webapp.ledger_store import LedgerStore

OWNER = "syn-owner-u4"
VIEWER = "syn-staff-u4"


class Server:
    def __init__(self, tmp_path, *, with_access=True):
        self.prev_db = os.environ.get("WEBLEDGER_DB")
        os.environ["WEBLEDGER_DB"] = str(tmp_path / "u4.sqlite")
        self.store = LedgerStore(tmp_path / "u4.sqlite", seed_demo=False)
        self.access = access_control.attach_to_ledger_store(self.store) if with_access else None
        board_mod.bind_store(self.store)
        self.server = board_mod.serve(port=0, with_worker=False)
        self.port = self.server.server_address[1]
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        if with_access:
            access_control.bind_synthetic_sessions(True)
            board_mod.bind_access(self.access)
            self.access.ensure_owner(OWNER)
            self.access.create_account(user_id=VIEWER, role=access_control.ROLE_VIEWER, display_name="직원")
        self.n = 0

    def close(self):
        board_mod.bind_access(None)
        access_control.bind_sessions(access_control.UnboundSessionAdapter())
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)
        board_mod.bind_store(None)
        self.store.close()
        if self.prev_db is None:
            os.environ.pop("WEBLEDGER_DB", None)
        else:
            os.environ["WEBLEDGER_DB"] = self.prev_db

    def get(self, path, user=OWNER):
        headers = {access_control.SyntheticSessionAdapter.HEADER: user} if user else {}
        request = urllib.request.Request(f"http://127.0.0.1:{self.port}{path}", headers=headers)
        try:
            with urllib.request.urlopen(request, timeout=10) as response:
                return response.status, dict(response.headers), response.read()
        except urllib.error.HTTPError as exc:
            return exc.code, dict(exc.headers), exc.read()

    def trip(self, name, start, end):
        self.n += 1
        made = self.store.create_trip(starts_on=start, ends_on=end, destination=name, display_key=name,
                                      client_request_id=f"u4-trip-{self.n}")
        return made["tab_id"] if "tab_id" in made else made["trip"]["tab_id"]

    def row(self, tab_id, kind, amount, *, basis="합성 근거", state="classified"):
        self.n += 1
        row_id = f"{kind[:3]}-u4-{self.n}"
        payload = dict(occurred_on="2026-05-10", item="식비" if kind == "expense" else "수입", description="합성",
                       amount_krw=amount, source_kind="카드" if kind == "expense" else "직접",
                       classification_state=state, classification_basis=basis, customer_id="c1",
                       customer_name="합성고객", nickname="", income_kind="예약금", event_type="receipt")
        self.store.conn.execute(
            "INSERT INTO board_rows(row_id,row_kind,display_tab_id,revision,payload_json) VALUES (?,?,?,?,?)",
            (row_id, kind, tab_id, 1, json.dumps(payload, ensure_ascii=False)))
        self.store.conn.commit()
        return row_id


@pytest.fixture
def srv(tmp_path):
    server = Server(tmp_path)
    try:
        yield server
    finally:
        server.close()


def three_trips(srv):
    a = srv.trip("합성A", "2026-05-01", "2026-05-05")
    b = srv.trip("합성B", "2026-06-01", "2026-06-04")
    c = srv.trip("합성C", "2026-07-01", "2026-07-03")
    srv.row(a, "income", 300000)
    srv.row(a, "income", 200000)
    srv.row(a, "expense", 100000)
    srv.row(a, "expense", 50000)
    srv.row(b, "income", 700000)
    srv.row(b, "expense", 900000)  # 손실 여행: 차액이 음수여도 그대로 보인다
    srv.row(c, "expense", 40000)  # 수입 행 없음
    return a, b, c


def api_tabs(srv):
    status, _, body = srv.get("/api/tabs")
    assert status == 200
    return {t["tab_id"]: t for t in json.loads(body)["tabs"]}


def xlsx_rows(body):
    sheet = load_workbook(io.BytesIO(body)).active
    return sheet.title, [list(r) for r in sheet.iter_rows(values_only=True)]


def test_table_values_equal_api_tabs_for_three_or_more_trips(srv):
    a, b, c = three_trips(srv)
    tabs = api_tabs(srv)
    rows = {r["tab_id"]: r for r in tps.build_rows(
        store=srv.store, trips=board_mod.live_trips(include_archived=True),
        totals_fn=board_mod._trip_totals, review_fn=board_mod.row_needs_review,
        conflict_fn=board_mod.row_has_conflict, google=None)}
    assert len(rows) >= 3
    for tab_id in (a, b):
        assert rows[tab_id]["income"] == tabs[tab_id]["income_krw"]
        assert rows[tab_id]["expense"] == tabs[tab_id]["expense_krw"]
        assert rows[tab_id]["profit"] == tabs[tab_id]["profit_krw"]
    assert (rows[a]["income"], rows[a]["expense"], rows[a]["profit"]) == (500000, 150000, 350000)
    assert rows[b]["profit"] == -200000
    # 수입 행이 없는 여행: 지출은 API와 같고, 수입·차액은 0이 아니라 빈 칸이다.
    assert rows[c]["expense"] == tabs[c]["expense_krw"] == 40000
    assert rows[c]["income"] is None and rows[c]["profit"] is None
    assert rows[c]["note"] == tps.INCOME_UNKNOWN
    assert rows[a]["note"] == ""


def test_http_page_and_xlsx_match_and_blank_income_is_not_zero(srv):
    a, b, c = three_trips(srv)
    tabs = api_tabs(srv)
    status, headers, body = srv.get("/trips/profit")
    assert status == 200
    page = body.decode("utf-8")
    assert "수입 확인 필요" in page and "합성A" in page and "/trips/profit/export.xlsx" in page
    status, headers, body = srv.get("/trips/profit/export.xlsx")
    assert status == 200
    assert headers["Content-Type"] == tps.XLSX_TYPE
    assert "attachment" in headers["Content-Disposition"]
    title, table = xlsx_rows(body)
    assert title == "여행별 손익"
    assert table[0] == list(tps.HEADER)
    by_name = {r[0]: r for r in table[1:]}
    assert {"합성A", "합성B", "합성C"} <= set(by_name)
    for tab_id, name in ((a, "합성A"), (b, "합성B")):
        row = by_name[name]
        assert row[2:5] == [tabs[tab_id]["income_krw"], tabs[tab_id]["expense_krw"], tabs[tab_id]["profit_krw"]]
    missing = by_name["합성C"]
    assert missing[2] is None and missing[4] is None and missing[3] == 40000
    assert missing[7] == tps.INCOME_UNKNOWN
    assert missing[2] != 0


def _rows(srv, google_income_fn=None):
    kwargs = {} if google_income_fn is None else dict(google_income_fn=google_income_fn)
    return {r["tab_id"]: r for r in tps.build_rows(
        store=srv.store, trips=board_mod.live_trips(include_archived=True), totals_fn=board_mod._trip_totals,
        review_fn=board_mod.row_needs_review, conflict_fn=board_mod.row_has_conflict, google=None, **kwargs)}


def test_google_verified_income_fills_a_trip_without_ledger_income_like_the_trip_screen(srv):
    a, b, c = three_trips(srv)
    summaries = {c: {"show_rows": True, "amount": 90000, "verified": True}}
    rows = _rows(srv, lambda tab: summaries.get(tab))
    assert (rows[c]["income"], rows[c]["expense"], rows[c]["profit"]) == (90000, 40000, 50000)
    assert rows[c]["income_source"] == "google" and rows[c]["note"] == ""
    # 장부에 수입 행이 있는 여행은 Google 값이 있어도 장부 값을 쓴다(여행 화면과 같은 우선순위).
    summaries[a] = {"show_rows": True, "amount": 1, "verified": True}
    rows = _rows(srv, lambda tab: summaries.get(tab))
    assert rows[a]["income"] == 500000 and rows[a]["income_source"] == "ledger"


@pytest.mark.parametrize("summary", [None, {"show_rows": False, "amount": 90000, "verified": False},
                                     {"show_rows": False, "amount": 90000, "numeric_gap": True}])
def test_unverified_google_income_stays_blank(srv, summary):
    _, _, c = three_trips(srv)
    row = _rows(srv, lambda tab: summary)[c]
    assert row["income"] is None and row["profit"] is None and row["note"] == tps.INCOME_UNKNOWN


def test_http_export_uses_the_google_income_the_trip_screen_would_show(srv, monkeypatch):
    from webapp import google_ledger_page
    _, _, c = three_trips(srv)
    monkeypatch.setattr(google_ledger_page, "get_trip_income_summary",
                        lambda tab: {"show_rows": True, "amount": 90000} if tab == c else None)
    _, table = xlsx_rows(srv.get("/trips/profit/export.xlsx")[2])
    row = next(r for r in table[1:] if r[0] == "합성C")
    assert row[2:5] == [90000, 40000, 50000] and row[7] in (None, "")


def test_open_count_counts_rows_a_person_still_has_to_decide(srv):
    a, _, _ = three_trips(srv)
    srv.row(a, "expense", 1000, basis="", state="unclassified")
    srv.row(a, "expense", 2000, basis="", state="classified")
    row = next(r for r in tps.build_rows(
        store=srv.store, trips=board_mod.live_trips(include_archived=True), totals_fn=board_mod._trip_totals,
        review_fn=board_mod.row_needs_review, conflict_fn=board_mod.row_has_conflict, google=None)
        if r["tab_id"] == a)
    assert row["open_rows"] == 2
    tab = api_tabs(srv)[a]
    assert row["open_rows"] == tab["needs_review_rows"]


def test_deleted_and_non_trip_tabs_are_left_out(srv):
    a, _, _ = three_trips(srv)
    trips = [dict(t) for t in board_mod.live_trips(include_archived=True)]
    trips.append(dict(trips[0], tab_id="quarter:2026:2", display_key="분기", tab_kind="other"))
    trips.append(dict(trips[0], tab_id="gone", display_key="삭제됨", deleted=True))
    rows = tps.build_rows(store=srv.store, trips=trips, totals_fn=board_mod._trip_totals,
                          review_fn=board_mod.row_needs_review, conflict_fn=board_mod.row_has_conflict, google=None)
    names = {r["trip"] for r in rows}
    assert {"합성A", "합성B", "합성C"} <= names
    assert "분기" not in names and "삭제됨" not in names


def test_formula_text_in_a_trip_name_is_neutralised_in_xlsx_and_page(srv):
    names = ["=HYPERLINK(\"http://x\",\"a\")", "+SUM(1,1)", "-2+3", "@cmd", "\t=1+1"]
    for i, name in enumerate(names):
        srv.trip(name, f"2026-0{i + 1}-01", f"2026-0{i + 1}-02")
    status, _, body = srv.get("/trips/profit/export.xlsx")
    assert status == 200
    sheet = load_workbook(io.BytesIO(body)).active
    texts = [row[0] for row in sheet.iter_rows(min_row=2, values_only=True)]
    assert len(texts) >= len(names)
    for value in texts:
        assert not value.lstrip(" \t\r\n").startswith(("=", "+", "-", "@")), value
    for cell in sheet["A"][1:]:
        assert cell.data_type != "f"
    srv.trip("<b>합성태그</b>", "2026-08-01", "2026-08-02")
    page = srv.get("/trips/profit")[2].decode("utf-8")
    assert "&lt;b&gt;합성태그" in page and "<b>합성태그" not in page


def test_only_the_owner_can_read_page_or_export(srv):
    three_trips(srv)
    for path in ("/trips/profit", "/trips/profit/export.xlsx"):
        status, _, body = srv.get(path, user=VIEWER)
        assert status in (403, 404), path
        assert "합성A" not in body.decode("utf-8", "replace")
        status, _, body = srv.get(path, user=None)
        assert status == 401, path
        assert "합성A" not in body.decode("utf-8", "replace")


def test_server_without_access_enforcement_refuses_everyone(tmp_path):
    server = Server(tmp_path, with_access=False)
    try:
        server.trip("합성A", "2026-05-01", "2026-05-05")
        for path in ("/trips/profit", "/trips/profit/export.xlsx"):
            status, _, body = server.get(path, user=None)
            assert status == 403 and b"OWNER_ONLY" in body
            assert "합성A" not in body.decode("utf-8", "replace")
    finally:
        server.close()


def test_the_page_only_answers_get(srv):
    request = urllib.request.Request(
        f"http://127.0.0.1:{srv.port}/trips/profit", data=b"{}", method="POST",
        headers={access_control.SyntheticSessionAdapter.HEADER: OWNER, "Content-Type": "application/json"})
    with pytest.raises(urllib.error.HTTPError) as caught:
        urllib.request.urlopen(request, timeout=10)
    assert caught.value.code in (403, 404, 405)


def test_export_page_links_to_the_table(srv):
    status, _, body = srv.get("/export")
    assert status == 200
    assert "/trips/profit" in body.decode("utf-8")


def test_duplicate_company_excluded_and_conflicting_rows_stay_out_of_expense(tmp_path, monkeypatch):
    """카드 기록 단계의 보호(중복·회사 제외·원본 충돌)를 통과한 행만 지출에 든다."""
    from tests.card_pipeline.fixtures import make_csv, domestic_row
    from webapp.card_flow import CardFlow

    monkeypatch.setenv("WEBLEDGER_UNIFIED_DB", "1")
    monkeypatch.setenv("WEBLEDGER_REVIEW_FROM", "")
    srv = Server(tmp_path)
    try:
        tab = srv.trip("합성D", "2026-10-01", "2026-10-05")
        flow = CardFlow(srv.store)
        monkeypatch.setattr(flow, "trip_valid", lambda _t: True)
        monkeypatch.setattr(flow, "tab_valid", lambda _t: True)
        batch = flow.pipeline.receive(make_csv([
            domestic_row(merchant=f"SYNTHETIC SHOP {i}", amount=amount, approval=f"U4-{i}", date="2026-10-03")
            for i, amount in enumerate((10000, 20000, 30000, 40000, 50000))]), "u4.csv")["batch_id"]
        ids = [r["transaction_id"] for r in flow.pipeline.get_batch(batch)["rows"]]
        assert len(ids) == 5
        conn = srv.store.conn
        conn.execute("UPDATE transactions SET classification_state='classified',item='식비',"
                     "classification_source='user_decision',classification_basis='합성 근거',"
                     "trip_id=?,display_tab_id=?", (tab, tab))
        conn.execute("UPDATE transactions SET duplicate_of=? WHERE transaction_id=?", (ids[0], ids[1]))
        conn.execute("UPDATE transactions SET conflict_reason='합성 충돌' WHERE transaction_id=?", (ids[3],))
        source_hash = conn.execute("SELECT source_hash FROM transactions WHERE transaction_id=?",
                                   (ids[2],)).fetchone()[0]
        conn.execute("INSERT INTO transaction_company_exclusions(transaction_id,source_hash,excluded,revision,note,"
                     "updated_at) VALUES (?,?,1,1,'합성 제외','synthetic')", (ids[2], source_hash))
        conn.commit()
        assert flow.auto_record(batch)["auto_recorded"] >= 1
        booked = {r[0] for r in conn.execute("SELECT transaction_id FROM ledger_entries")}
        assert booked == {ids[0], ids[4]}
        rows = tps.build_rows(
            store=srv.store, trips=board_mod.live_trips(include_archived=True), totals_fn=board_mod._trip_totals,
            review_fn=board_mod.row_needs_review, conflict_fn=board_mod.row_has_conflict, google=None)
        row = next(r for r in rows if r["tab_id"] == tab)
        assert row["expense"] == 10000 + 50000
        assert row["expense"] == api_tabs(srv)[tab]["expense_krw"]
        _, table = xlsx_rows(srv.get("/trips/profit/export.xlsx")[2])
        assert [r[3] for r in table[1:] if r[0] == "합성D"] == [60000]
    finally:
        srv.close()


def test_google_label_states(monkeypatch):
    assert tps._google_label("t", None) == tps.GOOGLE_UNAVAILABLE
    assert tps._google_label("t", {}) == tps.GOOGLE_UNLINKED
    assert tps._google_label("t", {"t": True}) == tps.GOOGLE_VERIFIED
    assert tps._google_label("t", {"t": False}) == tps.GOOGLE_UNVERIFIED


def test_google_verification_reads_snapshot_and_requires_every_linked_tab(monkeypatch, tmp_path):
    from app import google_authority
    from webapp import google_ledger_page as google

    monkeypatch.setattr(google, "enabled", lambda: True)
    monkeypatch.setattr(google, "snapshot_path", lambda: tmp_path / "snapshot.json")
    monkeypatch.setattr(google, "rows_path", lambda: tmp_path / "rows.json")
    monkeypatch.setattr(google_authority, "load_consistent", lambda *_: ({"trips": []}, {}))
    monkeypatch.setattr(google, "load_mapping", lambda _p: {"k1": "tab-a", "k2": "tab-b", "k3": "tab-b", "k4": ""})
    monkeypatch.setattr(google, "load_choices", lambda _p: {})
    monkeypatch.setattr(google, "snapshot_for_display", lambda s: s)
    monkeypatch.setattr(google, "owner_payload", lambda *_: {"trips": [
        {"key": "k1", "verified": True}, {"key": "k2", "verified": True}, {"key": "k3", "verified": False}]})
    assert tps.google_verification_by_tab() == {"tab-a": True, "tab-b": False}
    monkeypatch.setattr(google_authority, "load_consistent",
                        lambda *_: (_ for _ in ()).throw(google_authority.SnapshotError("synthetic")))
    assert tps.google_verification_by_tab() is None
    monkeypatch.setattr(google, "enabled", lambda: False)
    assert tps.google_verification_by_tab() is None


def test_the_module_writes_nothing(srv):
    three_trips(srv)
    conn = srv.store.conn

    def fingerprint():
        return [conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
                for t in ("board_rows", "board_revisions", "trip_tabs", "change_log")
                if conn.execute("SELECT 1 FROM sqlite_master WHERE name=?", (t,)).fetchone()]

    before = fingerprint()
    srv.get("/trips/profit")
    srv.get("/trips/profit/export.xlsx")
    assert fingerprint() == before
