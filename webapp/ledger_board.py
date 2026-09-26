"""Phase 1 synthetic ledger board.

Read-only trial screen built from the synthetic C1~I3 fixture defined in
WEB_LEDGER_DETAILED_CONTRACT section 9. No source reading, no persistence,
no AI, no real reservation links. Every page states that data is synthetic.

Expected fixture totals (contract):
  trip A income 1000000, expense 180000, profit 820000
  customer U1 800000, U2 200000; unclassified 30000 (not in A expense)
"""

from __future__ import annotations

import html
import json
import secrets
import uuid
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import parse_qs, urlparse

CSRF_TOKEN = secrets.token_hex(16)
_STORE = None
_IMPORTER = None


def bind_store(store) -> None:
    global _STORE
    _STORE = store


def bind_importer(importer) -> None:
    global _IMPORTER
    _IMPORTER = importer


def live_trips(include_archived: bool = False):
    if _STORE is None:
        return [dict(t) for t in TRIPS]
    return _STORE.list_trips(include_archived=include_archived)


def valid_tab_ids() -> set:
    return {t["tab_id"] for t in live_trips(include_archived=True)}


def _all_tab_ids() -> list:
    return [t["tab_id"] for t in live_trips(include_archived=True)]


def _with_display_amount(rows):
    if _STORE is None:
        return rows
    for r in rows:
        if "display_amount_krw" not in r:
            projected = _STORE.projected(r)
            r["display_amount_krw"] = projected["display_amount_krw"]
            r["display_occurred_on"] = projected["display_occurred_on"]
        elif "display_occurred_on" not in r:
            r["display_occurred_on"] = _STORE.display_occurred_on(r)
    return rows


def _shown_date(row) -> str:
    return row.get("display_occurred_on", row["occurred_on"])


def _expense_rows():
    if _STORE is None:
        return [dict(r) for r in EXPENSES]
    seen = {r["row_id"] for r in EXPENSES}
    out = []
    for r in EXPENSES:
        saved = _STORE.get_row(r["row_id"])
        out.append(saved if saved is not None else dict(r))
    for tab in _all_tab_ids() + [None]:
        for saved in _STORE.list_tab_rows(tab):
            if saved["row_kind"] == "expense" and saved["row_id"] not in seen:
                seen.add(saved["row_id"])
                out.append(saved)
    return _with_display_amount(out)


def _income_rows():
    if _STORE is None:
        return [dict(r) for r in INCOMES]
    out = []
    for r in INCOMES:
        saved = _STORE.get_row(r["row_id"])
        out.append(saved if saved is not None else dict(r))
    if _STORE is not None:
        seen = {r["row_id"] for r in INCOMES}
        for tab in _all_tab_ids() + [None]:
            for saved in _STORE.list_tab_rows(tab):
                if saved["row_kind"] == "income" and saved["row_id"] not in seen:
                    seen.add(saved["row_id"])
                    out.append(saved)
    return _with_display_amount(out)


def _trip_totals(tab_id: str):
    if _STORE is None:
        return {
            "income": trip_income_total(tab_id),
            "expense": trip_expense_total(tab_id),
            "profit": trip_profit(tab_id),
        }
    return _STORE.tab_totals(tab_id)


def _unclassified_rows():
    return [r for r in _expense_rows() if r["display_tab_id"] is None]


def _income_total(rows) -> int:
    linked = _STORE.linked_bank_row_ids() if _STORE is not None else set()
    return sum(
        _shown_amount(r) for r in rows if r["row_id"] not in linked
    )

SYNTHETIC_MARK = "합성 자료"

TRIPS = (
    {"tab_id": "trip-demo-a", "display_key": "0408_예시여행A", "starts_on": "2026-04-08", "ends_on": "2026-04-14", "destination": "예시여행A"},
    {"tab_id": "trip-demo-b", "display_key": "0420_예시여행B", "starts_on": "2026-04-20", "ends_on": "2026-04-23", "destination": "예시여행B"},
)

EXPENSES = (
    {
        "row_id": "expense-demo-c1", "display_tab_id": "trip-demo-a",
        "occurred_on": "2026-04-09", "item": "숙박비", "description": "예시 숙소",
        "service_period": "2026-04-09~2026-04-10", "reservation_no": "",
        "evidence_type": "카드", "amount_krw": 100000,
        "source_kind": "카드", "source_event_id": "SRC-C1",
        "classification_state": "auto_classified",
        "classification_basis": "정규화 가맹점·카드 종류·거래 방향 후보 A",
    },
    {
        "row_id": "expense-demo-c2", "display_tab_id": "trip-demo-a",
        "occurred_on": "2026-04-10", "item": "숙박비", "description": "예시 숙소 취소",
        "service_period": "2026-04-09~2026-04-10", "reservation_no": "",
        "evidence_type": "카드", "amount_krw": -20000,
        "source_kind": "카드", "source_event_id": "SRC-C2",
        "classification_state": "auto_classified",
        "classification_basis": "원천 확인 취소 사건, 부호 보존",
    },
    {
        "row_id": "expense-demo-c3", "display_tab_id": None,
        "occurred_on": "2026-04-11", "item": "교통비", "description": "예시 이동",
        "service_period": "", "reservation_no": "",
        "evidence_type": "카드", "amount_krw": 30000,
        "source_kind": "카드", "source_event_id": "SRC-C3",
        "classification_state": "unclassified",
        "classification_basis": "목적지 없음, 분류대기",
    },
    {
        "row_id": "expense-demo-c4", "display_tab_id": "trip-demo-a",
        "occurred_on": "2026-04-09", "item": "숙박비", "description": "예시 숙소",
        "service_period": "2026-04-09~2026-04-10", "reservation_no": "",
        "evidence_type": "카드", "amount_krw": 100000,
        "source_kind": "카드", "source_event_id": "SRC-C4",
        "classification_state": "auto_classified",
        "classification_basis": "C1과 날짜·가맹점 동일, 원천 거래 ID 상이, 별도 사건",
    },
)

INCOMES = (
    {
        "row_id": "income-demo-i1", "display_tab_id": "trip-demo-a",
        "occurred_on": "2026-04-01", "customer_id": "U1",
        "customer_name": "김예시", "nickname": "예시별명",
        "income_kind": "deposit", "event_type": "receipt", "amount_krw": 500000,
        "source_kind": "직접 입력", "source_event_id": "INC-I1",
    },
    {
        "row_id": "income-demo-i2", "display_tab_id": "trip-demo-a",
        "occurred_on": "2026-04-05", "customer_id": "U1",
        "customer_name": "김예시", "nickname": "예시별명",
        "income_kind": "balance", "event_type": "receipt", "amount_krw": 300000,
        "source_kind": "직접 입력", "source_event_id": "INC-I2",
    },
    {
        "row_id": "income-demo-i3", "display_tab_id": "trip-demo-a",
        "occurred_on": "2026-04-06", "customer_id": "U2",
        "customer_name": "김예시", "nickname": "다른별명",
        "income_kind": "deposit", "event_type": "receipt", "amount_krw": 200000,
        "source_kind": "직접 입력", "source_event_id": "INC-I3",
    },
)

INCOME_KIND_LABEL = {"deposit": "예약금", "balance": "잔금", "additional": "추가금"}


def esc(value) -> str:
    return html.escape("" if value is None else str(value), quote=True)


def trip_income_total(tab_id: str) -> int:
    return sum(r["amount_krw"] for r in INCOMES if r["display_tab_id"] == tab_id)


def trip_expense_total(tab_id: str) -> int:
    return sum(r["amount_krw"] for r in EXPENSES if r["display_tab_id"] == tab_id)


def trip_profit(tab_id: str) -> int:
    return trip_income_total(tab_id) - trip_expense_total(tab_id)


def customer_total(customer_id: str, tab_id: str) -> int:
    return sum(
        r["amount_krw"]
        for r in INCOMES
        if r["customer_id"] == customer_id and r["display_tab_id"] == tab_id
    )


def unclassified_expenses():
    return [r for r in EXPENSES if r["display_tab_id"] is None]


def unclassified_total() -> int:
    return sum(r["amount_krw"] for r in unclassified_expenses())


def find_row(row_id: str):
    if _STORE is not None:
        allocation = _STORE.get_allocation_display(row_id)
        if allocation is not None:
            return ("income", allocation)
    for r in _expense_rows():
        if r["row_id"] == row_id:
            return ("expense", r)
    for r in _income_rows():
        if r["row_id"] == row_id:
            return ("income", r)
    if _STORE is not None:
        hidden = _STORE.get_row(row_id)
        if hidden is not None:
            hidden["display_amount_krw"] = _STORE.display_amount(hidden)
            hidden["display_occurred_on"] = _STORE.display_occurred_on(hidden)
            return (hidden["row_kind"], hidden)
    return (None, None)


def split_page(source_id: str) -> str:
    top = (
        "<div class='top'><h1>웹 장부"
        f"<span class='synth'>{SYNTHETIC_MARK}</span></h1>"
        "<p><a href='/board'>장부</a> · <a href='/import'>카드 가져오기</a> · "
        "<a href='/export'>선택 탭 출력</a> · <a href='/trips'>여행 관리</a></p></div>"
    )
    if _STORE is None:
        return layout("배분 편집", f"{top}<div class='wrap'><div class='body'><p>저장소가 없어요.</p></div></div>")
    source = _STORE.get_row(source_id)
    if source is None or source["row_kind"] != "income":
        return layout("배분 편집", f"{top}<div class='wrap'><div class='body'><p>없는 수입 행이에요.</p></div></div>")
    reflected = _STORE.display_amount(source)
    allocs = _STORE.active_allocations(source_id)
    remainder = reflected - sum(a["amount_krw"] for a in allocs)
    def tab_options(current):
        cur = current or "unclassified"
        out = (
            f"<option value='unclassified'{' selected' if cur == 'unclassified' else ''}>"
            "분류대기(미배정 배분)</option>"
        )
        for t in live_trips():
            selected = " selected" if cur == t["tab_id"] else ""
            out += f"<option value='{esc(t['tab_id'])}'{selected}>{esc(t['display_key'])}</option>"
        return out
    rows_html = ""
    for i, a in enumerate(list(allocs) + [{}, {}]):
        aid = a.get("allocation_id", "")
        rows_html += (
            f"<tr><td><input name='alc_{i}_id' value='{esc(aid)}' readonly></td>"
            f"<td><input name='alc_{i}_customer' value='{esc(a.get('customer_name', ''))}'></td>"
            f"<td><select name='alc_{i}_tab'>{tab_options(a.get('display_tab_id'))}</select></td>"
            f"<td><select name='alc_{i}_kind'>"
            + "".join(
                f"<option value='{k}'{' selected' if a.get('income_kind') == k else ''}>"
                f"{esc(INCOME_KIND_LABEL[k])}</option>"
                for k in ("deposit", "balance", "additional")
            ) +
            "</td>"
            f"<td><input name='alc_{i}_amount' value='{esc(a.get('amount_krw', ''))}'></td></tr>"
        )
    principal_fields = ""
    if source.get("source_kind") == "직접 입력":
        principal_fields = (
            "<p><label>원금(선택, 배분안과 함께 저장)</label>"
            f"<input name='new_principal_amount' value='{source['amount_krw']}'></p>"
            "<p class='muted'>은행 원천은 정정 경로에서 배분안과 함께 조정해요.</p>"
        )
    body = (
        "<div class='body'><h2>입금 나누기</h2>"
        f"<p>원천 입금액 {source['amount_krw']:,}원 · 현재 장부 반영액 {reflected:,}원 · "
        f"배분한 금액 {reflected - remainder:,}원 · 남은 금액 {remainder:,}원</p>"
        f"<form method='post' action='/api/income/{esc(source_id)}/allocations'>"
        f"<input type='hidden' name='csrf' value='{CSRF_TOKEN}'>"
        f"<input type='hidden' name='expected_source_revision' value='{source['revision']}'>"
        f"<input type='hidden' name='client_request_id' value='{uuid.uuid4().hex}'>"
        f"<input type='hidden' name='row_count' value='{len(allocs) + 2}'>"
        f"{principal_fields}"
        "<div class='scrollx'><table><tr><th>배분 ID</th><th>고객</th><th>여행</th>"
        f"<th>종류</th><th>금액</th></tr>{rows_html}</table></div>"
        "<p class='muted'>금액이 빈 행은 제외돼요. 합계가 반영액을 넘으면 저장하지 않아요. "
        "같은 입금의 배분 표시 날짜는 원천 날짜를 함께 써요.</p>"
        "<button type='submit'>배분안 저장</button></form>"
        f"<p><a href='/row?id={esc(source_id)}'>원천 상세로</a></p></div>"
    )
    return layout("배분 편집", f"{top}<div class='wrap'>{body}</div>")


def history_html(row_id: str) -> str:
    if _STORE is None:
        return ""
    items = _STORE.list_history(row_id)
    if not items:
        return "<h3>변경 이력</h3><p class='muted'>아직 저장된 변경이 없어요.</p>"
    lis = "".join(
        f"<li>rev {h['revision']} · {esc(h['change_mode'])} · {esc(h['actor'])} · "
        f"{esc(h['created_at'])} · 사건 {esc(h['event_id'] or '감사 기록 대기')}</li>"
        for h in items
    )
    status = _STORE.revert_status(row_id)
    if status["revertible"]:
        revert_html = (
            "<h3>직전 수정 되돌리기</h3>"
            f"<form method='post' action='/api/rows/{esc(row_id)}/revert'>"
            f"<input type='hidden' name='csrf' value='{CSRF_TOKEN}'>"
            f"<input type='hidden' name='expected_revision' value='{items[-1]['revision']}'>"
            f"<input type='hidden' name='client_request_id' value='{uuid.uuid4().hex}'>"
            "<button type='submit'>직전 수정 되돌리기</button></form>"
        )
    else:
        revert_html = (
            "<h3>직전 수정 되돌리기</h3>"
            f"<p class='muted'>{esc(status['reason'])}</p>"
        )
    return f"<h3>변경 이력</h3><ul>{lis}</ul>{revert_html}"


def allocation_revert_status(allocation):
    from .ledger_store import SaveError

    if allocation is None:
        return {"revertible": False, "reason": "없는 배분 행이에요"}
    stored = _STORE.get_allocation(allocation["row_id"])
    if stored is not None:
        allocation = {**allocation, **stored}
    if not allocation.get("active"):
        return {"revertible": False, "reason": "비활성 배분은 되돌릴 수 없어요"}
    source = _STORE.get_row(allocation["source_row_id"])
    if source is None:
        return {"revertible": False, "reason": "원천 입금 행이 없어요"}
    if source["revision"] != allocation["source_revision"]:
        return {"revertible": False, "reason": "원천 입금이 바뀌어서 최신 상태를 확인해 주세요"}
    try:
        changes, history = _STORE._allocation_revert_changes(allocation)
    except SaveError as exc:
        return {"revertible": False, "reason": str(exc)}
    return {
        "revertible": True,
        "reason": None,
        "changes": changes,
        "expected_source_revision": source["revision"],
        "history": history,
    }


def allocation_history_html(allocation) -> str:
    rows = _STORE.conn.execute(
        "SELECT created_at, client_request_id, reverts_event_id, event_id"
        " FROM income_allocation_history WHERE allocation_id=? ORDER BY id DESC",
        (allocation["row_id"],),
    ).fetchall()
    items = "".join(
        f"<li>{esc(created_at)} · 요청 {esc(request_id)} · "
        f"사건 {esc(event_id or '대기')} · 되돌림 대상 {esc(reverts_event_id or '-')}</li>"
        for created_at, request_id, reverts_event_id, event_id in rows
    )
    status = allocation_revert_status(allocation)
    if status["revertible"]:
        changes = " · ".join(
            f"{esc(field)}={esc(value)}"
            for field, value in sorted(status["changes"].items())
        )
        revert_html = (
            "<h3>이 배분 행 되돌리기</h3>"
            f"<p class='muted'>되돌릴 값: {changes}</p>"
            f"<form method='post' action='/api/rows/{esc(allocation['row_id'])}/revert'>"
            f"<input type='hidden' name='csrf' value='{CSRF_TOKEN}'>"
            f"<input type='hidden' name='expected_revision' value='{status['expected_source_revision']}'>"
            f"<input type='hidden' name='client_request_id' value='{uuid.uuid4().hex}'>"
            "<button type='submit'>이 배분 행 되돌리기</button></form>"
        )
    else:
        revert_html = (
            "<h3>이 배분 행 되돌리기</h3>"
            f"<p class='muted'>{esc(status['reason'])}</p>"
        )
    history = f"<ul>{items}</ul>" if items else "<p class='muted'>아직 이 배분 행의 변경 이력이 없어요.</p>"
    return f"<h3>배분 행 변경 이력</h3>{history}{revert_html}"


def allocation_detail_body(allocation, edit: bool) -> str:
    source = _STORE.get_row(allocation["source_row_id"])
    reflected = _STORE.display_amount(source) if source is not None else 0
    trips = list(live_trips(include_archived=True))
    current_tab = allocation.get("display_tab_id")
    if current_tab is not None and not any(t["tab_id"] == current_tab for t in trips):
        trips.append({"tab_id": current_tab, "display_key": "삭제된 여행"})
    tab_options = (
        "<option value='unclassified'"
        f"{' selected' if current_tab is None else ''}>분류대기(미배정 배분)</option>"
        + "".join(
            f"<option value='{esc(t['tab_id'])}'"
            f"{' selected' if current_tab == t['tab_id'] else ''}>{esc(t['display_key'])}</option>"
            for t in trips
        )
    )
    kind_options = "".join(
        f"<option value='{kind}'{' selected' if allocation.get('income_kind') == kind else ''}>"
        f"{esc(INCOME_KIND_LABEL[kind])}</option>"
        for kind in ("deposit", "balance", "additional")
    )
    if edit:
        form = (
            "<h3>배분 행 편집</h3>"
            f"<form method='post' action='/api/rows/{esc(allocation['row_id'])}/save'>"
            f"<input type='hidden' name='csrf' value='{CSRF_TOKEN}'>"
            f"<input type='hidden' name='expected_revision' value='{source['revision']}'>"
            f"<input type='hidden' name='client_request_id' value='{uuid.uuid4().hex}'>"
            f"<p><label>고객 ID</label><input name='customer_id' value='{esc(allocation.get('customer_id') or '')}'></p>"
            f"<p><label>고객 이름</label><input name='customer_name' value='{esc(allocation.get('customer_name', ''))}'></p>"
            f"<p><label>닉네임</label><input name='nickname' value='{esc(allocation.get('nickname', ''))}'></p>"
            f"<p><label>여행</label><select name='display_tab_id'>{tab_options}</select></p>"
            f"<p><label>입금 종류</label><select name='income_kind'>{kind_options}</select></p>"
            f"<p><label>거래일자</label><input value='{esc(allocation['occurred_on'])}' readonly></p>"
            f"<p><label>배분 금액</label><input value='{esc(allocation['amount_krw'])}' readonly></p>"
            "<p class='muted'>고객 정보·여행·입금 종류만 바꿀 수 있어요. 날짜와 금액은 전체 배분 편집에서 원천 규칙에 따라 조정해요.</p>"
            "<button type='submit'>배분 행 저장</button> "
            f"<a href='/row?id={esc(allocation['row_id'])}'>취소</a></form>"
        )
    else:
        form = f"<p><a href='/row?id={esc(allocation['row_id'])}&edit=1'>배분 행 편집</a></p>"
    links = (
        f"<p><a href='/income/{esc(allocation['source_row_id'])}/split'>전체 배분안 편집</a> · "
        f"<a href='/row?id={esc(allocation['source_row_id'])}'>원천 상세</a></p>"
    )
    return (
        f"<h2>입금 배분 {esc(allocation.get('customer_name', ''))} {_shown_amount(allocation):,}원</h2>"
        f"<ul><li>배분 ID: {esc(allocation['row_id'])}</li>"
        f"<li>원천 입금 {reflected:,}원 중 이 배분 {_shown_amount(allocation):,}원</li>"
        f"<li>입금 종류: {esc(INCOME_KIND_LABEL.get(allocation.get('income_kind'), ''))}</li></ul>"
        f"{form}{links}{allocation_history_html(allocation)}"
    )


STYLE = (
    "<style>body{font-family:'Malgun Gothic',sans-serif;margin:0;background:#f4f5f7;color:#222}"
    ".top{background:#fff;border-bottom:1px solid #ddd;padding:10px 16px;position:sticky;top:0;z-index:5}"
    ".top h1{font-size:18px;margin:0}.synth{display:inline-block;background:#fff4d6;border:1px solid #e0b800;"
    "font-size:12px;padding:1px 8px;border-radius:10px;margin-left:8px}"
    ".wrap{display:flex;min-height:calc(100vh - 57px)}"
    ".tabs{width:240px;flex:none;background:#fff;border-right:1px solid #ddd;overflow-y:auto;padding:8px}"
    ".tab{display:block;border:1px solid transparent;border-radius:8px;padding:10px;margin-bottom:6px;"
    "color:#222;text-decoration:none}.tab.sel{border-color:#3182f6;background:#eef4ff}"
    ".tab .amt{font-size:20px;font-weight:bold}.tab small{color:#666}"
    ".body{flex:1;min-width:0;padding:16px}.card{background:#fff;border-radius:12px;padding:16px;margin-bottom:12px}"
    ".big{font-size:28px;font-weight:bold}.muted{color:#666;font-size:13px}"
    "table{border-collapse:collapse;width:100%}td,th{border:1px solid #e2e2e2;padding:8px;font-size:14px;text-align:left}"
    "th{background:#f7f8fa}.num{text-align:right;font-variant-numeric:tabular-nums}"
    ".scrollx{overflow-x:auto}.detail{width:420px;flex:none;background:#fff;border-left:1px solid #ddd;"
    "padding:16px;overflow-y:auto}input,select{font-size:14px;padding:6px;width:100%;box-sizing:border-box}"
    ".rowbtn{font-size:13px;padding:4px 10px}.btnprep{background:#eee;border:1px solid #ccc;border-radius:8px;"
    "padding:8px 14px;font-size:14px;color:#666}.search{font-size:14px;padding:8px;width:100%;box-sizing:border-box}"
    "@media (max-width:760px){.wrap{flex-direction:column}.tabs{width:auto;border-right:none;border-bottom:1px solid #ddd;"
    "max-height:220px}.detail{width:auto;border-left:none;border-top:1px solid #ddd}}"
    "</style>"
)


def layout(title: str, body: str) -> str:
    return (
        "<!doctype html><html lang='ko'><head><meta charset='utf-8'>"
        "<meta name='viewport' content='width=device-width,initial-scale=1'>"
        f"<title>{esc(title)}</title>{STYLE}</head><body>{body}</body></html>"
    )


def tabs_html(selected: str, query: str = "") -> str:
    expenses = _expense_rows()
    items = []
    for t in live_trips():
        if query and query not in (t["display_key"] + t["destination"]):
            continue
        cls = "tab sel" if t["tab_id"] == selected else "tab"
        totals = _trip_totals(t["tab_id"])
        items.append(
            f"<a class='{cls}' href='/board?tab={esc(t['tab_id'])}'>"
            f"<div>{esc(t['display_key'])}</div>"
            f"<div class='amt'>{totals['income']:,}원</div>"
            f"<small>지출 {totals['expense']:,}원</small></a>"
        )
    if _STORE is not None:
        archived = [t for t in live_trips(include_archived=True) if t["archived"]]
        if archived and not query:
            links = "".join(
                f"<a class='tab' href='/board?tab={esc(t['tab_id'])}'>"
                f"<div>{esc(t['display_key'])} (보관)</div></a>"
                for t in archived
            )
            items.append(f"<div class='muted'>보관된 여행</div>{links}")
    unc = [r for r in expenses if r["display_tab_id"] is None]
    unc_total = sum(_shown_amount(r) for r in unc)
    if not query or query in "분류대기":
        cls = "tab sel" if selected == "unclassified" else "tab"
        items.append(
            f"<a class='{cls}' href='/board?tab=unclassified'>"
            f"<div>분류대기</div><div class='amt'>{len(unc)}건</div>"
            f"<small>미배정 {unc_total:,}원</small></a>"
        )
    return "".join(items) if items else "<p class='muted'>여행 탭을 추가해 주세요</p>"


def board_page(tab_id: str, query: str = "") -> str:
    trip = next((t for t in live_trips(include_archived=True) if t["tab_id"] == tab_id), None)
    if tab_id == "unclassified":
        rows = _unclassified_rows()
        unc_total = sum(_shown_amount(r) for r in rows)
        inc_rows = [r for r in _income_rows() if r["display_tab_id"] is None]
        head = "<h2>분류대기</h2><p class='muted'>분류를 기다리는 내역이에요. 전체 장부가 확정됐다는 뜻이 아니에요.</p>"
        tables = income_table(inc_rows) + expense_table(rows)
        summary = f"<div class='card'><span class='muted'>미배정</span><div class='big'>{unc_total:,}원</div></div>"
    elif trip is None:
        head = "<h2>여행을 선택해 주세요</h2>"
        tables = ""
        summary = ""
    else:
        incomes = [r for r in _income_rows() if r["display_tab_id"] == tab_id]
        expenses = [r for r in _expense_rows() if r["display_tab_id"] == tab_id]
        totals = _trip_totals(tab_id)
        linked = _STORE.linked_bank_row_ids() if _STORE is not None else set()
        billed = [r for r in incomes if r["row_id"] not in linked]
        customers = sorted({r["customer_id"] for r in billed})
        cust_lines = "".join(
            f"<div>{esc(next(r['customer_name'] for r in billed if r['customer_id'] == c))} "
            f"({esc(c)}): <b>{sum(_shown_amount(r) for r in billed if r['customer_id'] == c):,}원</b></div>"
            for c in customers
        )
        head = f"<h2>{esc(trip['display_key'])} <span class='muted'>{esc(trip['starts_on'])}~{esc(trip['ends_on'])}</span></h2>"
        meta_line = ""
        if _STORE is not None and trip.get("prepared_on"):
            meta_line = (
                f"<p class='muted'>작성일 {esc(trip['prepared_on'])} · 담당자 "
                f"{esc(trip.get('prepared_by_name', ''))}"
                + (" · 보관됨" if trip.get("archived") else "")
                + " · <a href='/trips'>여행 관리</a></p>"
            )
        head += meta_line
        summary = (
            "<div class='card'><span class='muted'>수입 합계</span>"
            f"<div class='big'>{totals['income']:,}원</div>"
            "<span class='muted'>지출 합계</span>"
            f"<div class='big'>{totals['expense']:,}원</div>"
            "<span class='muted'>회사수익인식</span>"
            f"<div class='big'>{totals['profit']:,}원</div>"
            f"<p class='muted'>수입 {len(incomes)}건 · 지출 {len(expenses)}건</p></div>"
            f"<div class='card'><h3>고객별 합계</h3>{cust_lines}</div>"
        )
        tables = income_table(incomes) + expense_table(expenses)
    top = (
        "<div class='top'><h1>웹 장부"
        f"<span class='synth'>{SYNTHETIC_MARK}</span></h1>"
        "<p><a href='/board'>장부</a> · <a href='/import'>카드 가져오기</a> · "
        "<a href='/export'>선택 탭 출력</a> · <a href='/trips'>여행 관리</a></p></div>"
    )
    side = (
        "<div class='tabs'>"
        f"<form method='get' action='/board'><input class='search' name='q' placeholder='여행 검색' value='{esc(query)}'></form>"
        f"{tabs_html(tab_id, query)}</div>"
    )
    return layout("웹 장부", f"{top}<div class='wrap'>{side}<div class='body'>{head}{summary}{tables}</div></div>")


def income_new_page() -> str:
    options = "".join(
        f"<option value='{esc(t['tab_id'])}'>{esc(t['display_key'])}</option>" for t in live_trips()
    )
    top = (
        "<div class='top'><h1>웹 장부"
        f"<span class='synth'>{SYNTHETIC_MARK}</span></h1>"
        "<p><a href='/board'>장부</a> · <a href='/import'>카드 가져오기</a> · "
        "<a href='/export'>선택 탭 출력</a> · <a href='/trips'>여행 관리</a></p></div>"
    )
    body = (
        "<div class='body'><h2>수입 직접 입력</h2>"
        f"<form method='post' action='/api/income'>"
        f"<input type='hidden' name='csrf' value='{CSRF_TOKEN}'>"
        f"<input type='hidden' name='client_request_id' value='{uuid.uuid4().hex}'>"
        f"<p><label>여행</label><select name='display_tab_id'>{options}</select></p>"
        "<p><label>거래일자</label><input name='occurred_on' placeholder='2026-04-01'></p>"
        "<p><label>금액(원)</label><input name='amount_krw'></p>"
        "<p><label>입금 종류</label><select name='income_kind'>"
        "<option value='deposit'>예약금</option><option value='balance'>잔금</option>"
        "<option value='additional'>추가금</option></select></p>"
        "<p><label>이름</label><input name='customer_name'></p>"
        "<p><label>닉네임</label><input name='nickname'></p>"
        "<p><label>메모</label><input name='operator_note'></p>"
        "<button type='submit'>저장</button></form></div>"
    )
    return layout("수입 직접 입력", f"{top}<div class='wrap'>{body}</div>")


def expense_new_page() -> str:
    options = "".join(
        f"<option value='{esc(t['tab_id'])}'>{esc(t['display_key'])}</option>" for t in live_trips()
    )
    top = (
        "<div class='top'><h1>웹 장부"
        f"<span class='synth'>{SYNTHETIC_MARK}</span></h1>"
        "<p><a href='/board'>장부</a> · <a href='/import'>카드 가져오기</a> · "
        "<a href='/export'>선택 탭 출력</a> · <a href='/trips'>여행 관리</a></p></div>"
    )
    body = (
        "<div class='body'><h2>수기 지출 추가 (현금·계좌이체)</h2>"
        f"<form method='post' action='/api/expenses/manual'>"
        f"<input type='hidden' name='csrf' value='{CSRF_TOKEN}'>"
        f"<input type='hidden' name='client_request_id' value='{uuid.uuid4().hex}'>"
        f"<p><label>여행</label><select name='display_tab_id'>{options}</select></p>"
        "<p><label>거래일자</label><input name='occurred_on' placeholder='2026-04-01'></p>"
        "<p><label>지급 수단</label><select name='pay_method'>"
        "<option value='현금'>현금</option><option value='계좌이체'>계좌이체</option></select></p>"
        "<p><label>항목</label><input name='item'></p>"
        "<p><label>내용</label><input name='description'></p>"
        "<p><label>금액(원, 환불은 음수)</label><input name='amount_krw'></p>"
        "<p><label>메모</label><input name='operator_note'></p>"
        "<button type='submit'>저장</button></form></div>"
    )
    return layout("수기 지출 추가", f"{top}<div class='wrap'>{body}</div>")


def trips_page(preview_tab: str = "") -> str:
    top = (
        "<div class='top'><h1>웹 장부"
        f"<span class='synth'>{SYNTHETIC_MARK}</span></h1>"
        "<p><a href='/board'>장부</a> · <a href='/import'>카드 가져오기</a> · "
        "<a href='/export'>선택 탭 출력</a></p></div>"
    )
    if _STORE is None:
        body = "<div class='body'><p>저장소가 연결되지 않았어요.</p></div>"
        return layout("여행 관리", f"{top}<div class='wrap'>{body}</div>")
    cards = []
    for t in live_trips(include_archived=True):
        if t.get("deleted"):
            continue
        try:
            kind = "보관됨" if t["archived"] else "활성"
            preview = _STORE.preview_tab_delete(t["tab_id"])
            counts = (f"수입 {preview['income_count']}건 {preview['income_total']:,}원 · "
                      f"지출 {preview['expense_count']}건 {preview['expense_total']:,}원")
        except Exception as exc:
            counts = f"조회 실패: {esc(str(exc))}"
        cards.append(
            "<div class='card'>"
            f"<h3>{esc(t['display_key'])} <span class='muted'>{kind} · rev {t['revision']}</span></h3>"
            f"<p class='muted'>{esc(t['starts_on'])}~{esc(t['ends_on'])} · {esc(t['destination'])}</p>"
            f"<p class='muted'>작성일 {esc(t['prepared_on'])} · 담당자 {esc(t['prepared_by_name'])}</p>"
            f"<p>{counts}</p>"
            f"<form method='post' action='/api/trips/{esc(t['tab_id'])}/meta'>"
            f"<input type='hidden' name='csrf' value='{CSRF_TOKEN}'>"
            f"<input type='hidden' name='expected_revision' value='{t['revision']}'>"
            f"<input type='hidden' name='client_request_id' value='{uuid.uuid4().hex}'>"
            f"<p><label>표시 이름</label><input name='display_key' value='{esc(t['display_key'])}'></p>"
            f"<p><label>작성일</label><input name='prepared_on' value='{esc(t['prepared_on'])}'></p>"
            f"<p><label>담당자</label><input name='prepared_by_name' value='{esc(t['prepared_by_name'])}'></p>"
            "<button type='submit'>정보 저장</button></form>"
            f"<form method='post' action='/api/trips/{esc(t['tab_id'])}/meta'>"
            f"<input type='hidden' name='csrf' value='{CSRF_TOKEN}'>"
            f"<input type='hidden' name='expected_revision' value='{t['revision']}'>"
            f"<input type='hidden' name='client_request_id' value='{uuid.uuid4().hex}'>"
            f"<input type='hidden' name='archived' value='{'0' if t['archived'] else '1'}'>"
            f"<button type='submit'>{'복원' if t['archived'] else '보관'}</button></form>"
            f"<p><a href='/trips?preview_tab={esc(t['tab_id'])}'>삭제 미리보기</a></p>"
            "</div>"
        )
    preview_html = ""
    if preview_tab:
        try:
            preview = _STORE.preview_tab_delete(preview_tab)
            dest_options = "".join(
                f"<option value='{esc(t['tab_id'])}'>{esc(t['display_key'])}</option>"
                for t in live_trips() if t["tab_id"] != preview_tab
            )
            snapshot_json = esc(json.dumps(preview["snapshot"], ensure_ascii=False,
                                           sort_keys=True, default=str))
            preview_html = (
                "<div class='card'><h3>삭제 미리보기</h3>"
                f"<p>{esc(preview['display_key'])}: 수입 {preview['income_count']}건 "
                f"{preview['income_total']:,}원 · 지출 {preview['expense_count']}건 "
                f"{preview['expense_total']:,}원 · 배분 {preview['allocation_count']}건 · "
                f"대기 규칙 {preview['waiting_rules']}건</p>"
                f"<form method='post' action='/api/trips/{esc(preview_tab)}/delete'>"
                f"<input type='hidden' name='csrf' value='{CSRF_TOKEN}'>"
                f"<input type='hidden' name='client_request_id' value='{uuid.uuid4().hex}'>"
                f"<input type='hidden' name='snapshot' value='{snapshot_json}'>"
                "<p><label>처리 방법</label><select name='mode'>"
                "<option value='move-unclassified'>분류대기로 이동</option>"
                "<option value='move-trip'>다른 여행으로 이동</option></select></p>"
                f"<p><label>목적지</label><select name='destination'>{dest_options}</select></p>"
                "<button type='submit'>내역 이동 후 삭제 확정</button></form>"
                "<p class='muted'>원천·이력·과거 출력은 지우지 않고 화면 탭만 없앱니다. "
                "확정 시점에 장부가 바뀌었으면 처음부터 다시 확인합니다.</p></div>"
            )
        except Exception as exc:
            preview_html = f"<div class='card'><p>미리보기 실패: {esc(str(exc))}</p></div>"
    body = f"<div class='body'><h2>여행 관리</h2>{preview_html}{''.join(cards)}</div>"
    return layout("여행 관리", f"{top}<div class='wrap'>{body}</div>")


def export_page() -> str:
    options = "".join(
        f"<label><input type='checkbox' name='tab_ids' value='{esc(t['tab_id'])}' checked> "
        f"{esc(t['display_key'])}</label><br>" for t in live_trips()
    )
    archived = ""
    if _STORE is not None:
        arch = [t for t in live_trips(include_archived=True) if t["archived"]]
        if arch:
            archived = "<h3>보관된 여행</h3>" + "".join(
                f"<label><input type='checkbox' name='tab_ids' value='{esc(t['tab_id'])}'> "
                f"{esc(t['display_key'])} (보관)</label><br>" for t in arch
            )
    top = (
        "<div class='top'><h1>웹 장부"
        f"<span class='synth'>{SYNTHETIC_MARK}</span></h1>"
        "<p><a href='/board'>장부</a> · <a href='/import'>카드 가져오기</a> · "
        "<a href='/export'>선택 탭 출력</a> · <a href='/trips'>여행 관리</a></p></div>"
    )
    counts = ""
    progress_note = ""
    jobs_html = ""
    if _STORE is not None:
        from .card_import import CardImporter

        lines = []
        for t in live_trips(include_archived=True):
            rows = _STORE.list_tab_rows(t["tab_id"])
            inc = sum(1 for r in rows if r["row_kind"] == "income")
            exp = sum(1 for r in rows if r["row_kind"] == "expense")
            lines.append(
                f"<li>{esc(t['display_key'])}: 수입 {inc}행 · 지출 {exp}행"
                + (" (보관)" if t["archived"] else "") + "</li>")
        unc = _STORE.list_tab_rows(None)
        unc_inc = sum(1 for r in unc if r["row_kind"] == "income")
        unc_exp = sum(1 for r in unc if r["row_kind"] != "income")
        lines.append(f"<li>분류대기: 수입 {unc_inc}행 · 지출 {unc_exp}행 (출력에 들어가지 않아요)</li>")
        counts = f"<ul>{''.join(lines)}</ul>"
        try:
            importer = CardImporter(_STORE.conn, _STORE)
            states = set()
            for (batch_id,) in _STORE.conn.execute(
                    "SELECT batch_id FROM card_import_batches").fetchall():
                progress = importer.progress(batch_id)
                if progress:
                    states.add(progress["status"])
            if "reconciling" in states or "parsing" in states:
                progress_note = ("<p class='muted'>내역을 가져오는 중입니다. "
                                 "현재 저장된 내용만 포함합니다.</p>")
        except Exception:
            pass
        from .sheets_export import list_jobs

        jobs = list_jobs(_STORE.conn)
        if jobs:
            items = "".join(
                f"<li>{esc(j['created_at'])} · {len(j['tab_ids'])}개 탭 · "
                f"<a href='/api/exports/{esc(j['job_id'])}/download'>다운로드</a></li>"
                for j in jobs
            )
            jobs_html = f"<h3>최근 출력</h3><ul>{items}</ul>"
    body = (
        "<div class='body'><h2>선택 탭 출력</h2>"
        f"<form method='post' action='/api/exports/xlsx'>"
        f"<input type='hidden' name='csrf' value='{CSRF_TOKEN}'>"
        f"<input type='hidden' name='client_request_id' value='{uuid.uuid4().hex}'>"
        f"{options}{archived}"
        "<p class='muted'>저장된 장부 버전으로 출력해요. 미저장 초안은 서버에 없어서 섞이지 않아요. "
        "미확정 행도 화면대로 들어가고 파일에는 상태 표시를 넣지 않아요.</p>"
        f"{progress_note}"
        "<button type='submit'>출력</button></form>"
        f"<h3>범위 안내</h3>{counts}"
        f"{jobs_html}"
        f"<p class='muted'>양식 {esc('매출자료 양식_rev')} 구조를 복제해요. 회사·제목·작성 정보는 합성 예시예요.</p></div>"
    )
    return layout("선택 탭 출력", f"{top}<div class='wrap'>{body}</div>")


def import_page() -> str:
    top = (
        "<div class='top'><h1>웹 장부"
        f"<span class='synth'>{SYNTHETIC_MARK}</span></h1>"
        "<p><a href='/board'>장부</a> · <a href='/import'>카드 가져오기</a> · "
        "<a href='/export'>선택 탭 출력</a> · <a href='/trips'>여행 관리</a></p></div>"
    )
    body = (
        "<div class='body'><h2>카드 가져오기 (합성 프로필)</h2>"
        "<p class='muted'>합성 CSV만 받아요. 실제 카드 파일 형식은 프로필 확인 뒤에 연결해요.</p>"
        f"<input type='file' id='f' accept='.csv'>"
        f"<button id='up'>올리기</button><p id='msg' class='muted'></p>"
        "<div id='res'></div>"
        "<h2>은행 가져오기 (합성 프로필)</h2>"
        "<p class='muted'>합성 은행 CSV만 받아요. 실제 은행 양식은 확인 뒤에 연결해요. 출금은 수입으로 올리지 않아요.</p>"
        f"<input type='file' id='bf' accept='.csv'>"
        f"<button id='bup'>올리기</button><p id='bmsg' class='muted'></p>"
        "<div id='bres'></div>"
        "<p><a href='/income/new'>수입 직접 입력</a> · <a href='/expense/new'>수기 지출 추가</a></p>"
        "<script>"
        f"const csrf='{CSRF_TOKEN}';"
        "document.getElementById('up').onclick=async()=>{"
        "const f=document.getElementById('f').files[0];if(!f){return;}"
        "const m=document.getElementById('msg');m.textContent='읽는 중';"
        "const r=await fetch('/api/imports',{method:'POST',"
        "headers:{'Content-Type':'text/csv','X-Filename':encodeURIComponent(f.name),'X-CSRF-Token':csrf},"
        "body:f});"
        "if(!r.ok){const e=await r.json().catch(()=>({}));"
        "m.textContent='실패: '+(e.message||r.status)+' — 다시 올리면 이어서 처리해요.';return;}"
        "const j=await r.json();"
        "m.textContent='접수됐어요. 가져오는 동안 장부와 여기서 진행을 볼 수 있어요.';"
        "let p={};"
        "for(let i=0;i<120;i++){"
        "const q=await fetch('/api/imports/'+j.batch_id);"
        "if(!q.ok){m.textContent='진행 조회 실패 — 새로고침 뒤 다시 확인해 주세요.';return;}"
        "p=(await q.json()).result||{};"
        "if(p.status&&p.status!=='reconciling'&&p.status!=='parsing'&&p.status!=='processing')break;"
        "m.textContent='분류 중(가져온 행부터 장부에 보여요)...';"
        "await new Promise(s=>setTimeout(s,500));}"
        "if(p.status==='reconciling'||p.status==='parsing'||p.status==='processing'){"
        "m.textContent='아직 처리 중이에요. 잠시 뒤 새로고침하면 이어져요.';return;}"
        "m.textContent='완료';"
        "document.getElementById('res').innerHTML="
        "'<p>원본 '+p.source_rows+'행 · 새 사건 '+p.new_events+'건 · 여행 배치 '+p.placed_trips"
        "+'건 · 분류대기 '+p.placed_unclassified+'건 · 오류 '+p.parse_errors+'건 · 충돌 '+p.conflicts+'건</p>'"
        "+'<p><a href=\"/board\">여행 탭에서 보기</a> · <a href=\"/board?tab=unclassified\">분류대기 열기</a></p>';};"
        "document.getElementById('bup').onclick=async()=>{"
        "const f=document.getElementById('bf').files[0];if(!f){return;}"
        "const m=document.getElementById('bmsg');m.textContent='읽는 중';"
        "const r=await fetch('/api/bank-imports',{method:'POST',"
        "headers:{'Content-Type':'text/csv','X-Filename':encodeURIComponent(f.name),'X-CSRF-Token':csrf},"
        "body:f});const j=await r.json();"
        "m.textContent='완료';"
        "document.getElementById('bres').innerHTML="
        "'<p>원본 '+j.result.source_rows+'행 · 새 입금 '+j.result.new_events+'건 · 제외 '+j.result.excluded_rows+'건</p>'"
        "+'<p><a href=\"/board?tab=unclassified\">분류대기 열기</a></p>';};"
        "</script></div>"
    )
    return layout("카드 가져오기", f"{top}<div class='wrap'>{body}</div>")


def _shown_amount(row) -> int:
    return row.get("display_amount_krw", row["amount_krw"])


def income_table(rows) -> str:
    trs = "".join(
        f"<tr><td>{esc(_shown_date(r))}</td><td>{esc(r['customer_name'])}</td>"
        f"<td>{esc(r['nickname'])}</td>"
        f"<td class='num'>{_shown_amount(r) if r['income_kind'] == 'deposit' else ''}</td>"
        f"<td class='num'>{_shown_amount(r) if r['income_kind'] == 'balance' else ''}</td>"
        f"<td class='num'>{_shown_amount(r) if r['income_kind'] == 'additional' else ''}</td>"
        f"<td class='num'>{_shown_amount(r):,}</td>"
        f"<td><a href='/row?id={esc(r['row_id'])}'>상세</a></td></tr>"
        for r in rows
    )
    return (
        "<div class='card'><h3>수입 내용</h3><div class='scrollx'><table>"
        "<tr><th>거래일자</th><th>이름</th><th>닉네임</th><th>예약금</th><th>잔금</th>"
        f"<th>추가금</th><th>금액</th><th></th></tr>{trs}</table></div></div>"
    ).format(trs=trs if trs else "<tr><td colspan='8' class='muted'>아직 입력한 입금이 없어요</td></tr>")


def expense_table(rows) -> str:
    trs = "".join(
        f"<tr><td>{esc(_shown_date(r))}</td><td>{esc(r['item'])}</td>"
        f"<td>{esc(r['description'])}</td><td>{esc(r['service_period'])}</td>"
        f"<td style='font-family:monospace'>{esc(r['reservation_no'])}</td>"
        f"<td>{esc(r['evidence_type'])}</td><td class='num'>{_shown_amount(r):,}</td>"
        f"<td><a href='/row?id={esc(r['row_id'])}'>상세</a> "
        f"<a href='/row?id={esc(r['row_id'])}&edit=1'>편집</a></td></tr>"
        for r in rows
    )
    return (
        "<div class='card'><h3>지출 내용</h3><div class='scrollx'><table>"
        "<tr><th>거래일자</th><th>항목</th><th>내용</th><th>기간</th><th>예약번호</th>"
        f"<th>증빙유형</th><th>금액(원)</th><th></th></tr>{trs}</table></div></div>"
    ).format(trs=trs if trs else "<tr><td colspan='8' class='muted'>아직 연결된 지출이 없어요</td></tr>")


def detail_page(row_id: str, edit: bool = False) -> str:
    kind, row = find_row(row_id)
    if row is None:
        return layout("행 없음", "<div class='top'><h1>웹 장부</h1></div><div class='body'><p>행이 없어요. 목록으로 돌아가 주세요.</p></div>")
    if row.get("is_allocation") and _STORE is not None:
        body = allocation_detail_body(row, edit)
        top = (
            "<div class='top'><h1>웹 장부"
            f"<span class='synth'>{SYNTHETIC_MARK}</span></h1></div>"
        )
        return layout("배분 행 상세", f"{top}<div class='wrap'><div class='body'>{body}<p><a href='/board'>목록으로</a></p></div></div>")
    if kind == "expense":
        info = (
            f"<li>원천: {esc(row['source_kind'])} {esc(row['source_event_id'])}</li>"
            f"<li>분류 근거: {esc(row['classification_basis'])}</li>"
            f"<li>분류 상태: {esc(row['classification_state'])} (표시만 일반 행)</li>"
        )
        if edit:
            if _STORE is None:
                form = (
                    "<h3>행 편집 (저장 준비 중)</h3>"
                    "<p class='muted'>저장소가 연결되지 않았어요. 서버를 작업 DB와 함께 실행해 주세요.</p>"
                    "<button class='btnprep' disabled>저장 준비 중</button>"
                )
            else:
                options = (
                    "<option value='unclassified'"
                    f"{' selected' if row['display_tab_id'] is None else ''}>"
                    "분류대기</option>"
                    + "".join(
                        f"<option value='{esc(t['tab_id'])}'"
                        f"{' selected' if row['display_tab_id'] == t['tab_id'] else ''}>"
                        f"{esc(t['display_key'])}</option>"
                        for t in live_trips()
                    )
                )
                if row.get("source_kind") == "수기":
                    extra_fields = (
                        f"<p><label>거래일자</label><input name='occurred_on' value='{esc(row['occurred_on'])}'></p>"
                        f"<p><label>금액(원)</label><input name='amount_krw' value='{esc(row['amount_krw'])}'></p>"
                    )
                    fixed_note = "원천 식별자는 고정 필드라 바꿀 수 없어요."
                else:
                    extra_fields = ""
                    fixed_note = "거래일자·금액·원천 식별자·가맹점 원문은 고정 필드라 바꿀 수 없어요."
                form = (
                    "<h3>행 편집</h3>"
                    f"<form method='post' action='/api/rows/{esc(row_id)}/save'>"
                    f"<input type='hidden' name='csrf' value='{CSRF_TOKEN}'>"
                    f"<input type='hidden' name='expected_revision' value='{row.get('revision', 1)}'>"
                    f"<input type='hidden' name='client_request_id' value='{uuid.uuid4().hex}'>"
                    f"<p><label>여행 배정</label><select name='display_tab_id'>{options}</select></p>"
                    f"<p><label>항목</label><input name='item' value='{esc(row['item'])}'></p>"
                    f"<p><label>내용</label><input name='description' value='{esc(row['description'])}'></p>"
                    f"{extra_fields}"
                    f"<p><label>메모</label><input name='operator_note' value='{esc(row.get('operator_note', ''))}'></p>"
                    "<p><label>변경 이유</label><select name='change_mode'>"
                    "<option value='exception'>예외 사항</option>"
                    "<option value='rule_change'>규칙 변경</option></select></p>"
                    f"<p class='muted'>{fixed_note}</p>"
                    "<button type='submit'>저장</button> "
                    "<a href='/row?id=" + esc(row_id) + "'>취소</a></form>"
                )
        else:
            form = f"<p><a href='/row?id={esc(row_id)}&edit=1'>편집</a></p>"
        body = (
            f"<h2>지출 {esc(row['description'])} {row['amount_krw']:,}원</h2>"
            f"<ul>{info}</ul>"
            f"<p>메모: {esc(row.get('operator_note') or '없음')}</p>"
            f"{form}{history_html(row_id)}"
        )
    else:
        info = (
            f"<li>원천: {esc(row['source_kind'])} {esc(row['source_event_id'])}</li>"
            f"<li>입금 종류: {esc(INCOME_KIND_LABEL.get(row['income_kind'], ''))}</li>"
            f"<li>사건 구분: {esc(row['event_type'])}</li>"
        )
        extra = ""
        if _STORE is not None and row.get("source_kind") == "은행":
            corrections = _STORE.list_corrections(row_id)
            if corrections:
                lis = "".join(
                    f"<li>{esc(c['corrected_amount_krw'])}원"
                    + (f" · {esc(c['corrected_occurred_on'])}" if c.get("corrected_occurred_on") else "")
                    + f" · {esc(c['reason'])} · {esc(c['created_at'])}</li>"
                    for c in corrections
                )
                extra = f"<h3>정정 기록</h3><ul>{lis}</ul>"
            extra += (
                "<h3>장부 정정</h3>"
                f"<form method='post' action='/api/income/{esc(row_id)}/correct'>"
                f"<input type='hidden' name='csrf' value='{CSRF_TOKEN}'>"
                f"<input type='hidden' name='expected_revision' value='{row.get('revision', 1)}'>"
                f"<input type='hidden' name='client_request_id' value='{uuid.uuid4().hex}'>"
                "<p><label>장부 표시 금액</label><input name='corrected_amount_krw'></p>"
                "<p><label>장부 표시 날짜(선택)</label><input name='corrected_occurred_on' placeholder='2026-04-02'></p>"
                "<p><label>이유</label><input name='reason'></p>"
                "<button type='submit'>정정 기록</button></form>"
                "<p class='muted'>은행 원본은 그대로 두고 장부 표시만 바꿔요.</p>"
            )
        elif _STORE is not None and row.get("source_kind") == "직접 입력":
            options = (
                "<option value='unclassified'"
                f"{' selected' if row['display_tab_id'] is None else ''}>"
                "분류대기</option>"
                + "".join(
                    f"<option value='{esc(t['tab_id'])}'"
                    f"{' selected' if row['display_tab_id'] == t['tab_id'] else ''}>"
                    f"{esc(t['display_key'])}</option>"
                    for t in live_trips()
                )
            )
            kind_options = "".join(
                f"<option value='{k}'{' selected' if row['income_kind'] == k else ''}>"
                f"{esc(INCOME_KIND_LABEL[k])}</option>"
                for k in ("deposit", "balance", "additional")
            )
            links = _STORE.conn.execute(
                "SELECT bank_batch_id, bank_row_index FROM income_source_links WHERE row_id=?",
                (row_id,),
            ).fetchall()
            link_lines = "".join(
                f"<li>은행 원천 {esc(b)} #{i}</li>" for b, i in links
            )
            link_info = f"<h3>연결된 은행 원천</h3><ul>{link_lines}</ul>" if link_lines else ""
            candidates = _STORE.find_bank_candidates(row_id)
            cand_lines = "".join(
                f"<li>{esc(c['occurred_on'])} · {esc(c['customer_name'])} · "
                f"{c['amount_krw']:,}원 · {esc(c['row_id'])}</li>"
                for c in candidates
            )
            cand_info = (
                "<h3>중복 후보(미확정, 합산 제외 아님)</h3><ul>{cand_lines}</ul>"
                if cand_lines else ""
            ).format(cand_lines=cand_lines)
            lock_note = (
                "<p class='muted'>은행 원천 연결 뒤에는 날짜·금액을 여기서 바꿀 수 없어요. 은행 정정 경로를 써 주세요.</p>"
                if links else ""
            )
            if edit:
                extra = (
                    "<h3>행 편집</h3>"
                    f"<form method='post' action='/api/rows/{esc(row_id)}/save'>"
                    f"<input type='hidden' name='csrf' value='{CSRF_TOKEN}'>"
                    f"<input type='hidden' name='expected_revision' value='{row.get('revision', 1)}'>"
                    f"<input type='hidden' name='client_request_id' value='{uuid.uuid4().hex}'>"
                    f"<p><label>여행 배정</label><select name='display_tab_id'>{options}</select></p>"
                    f"<p><label>거래일자</label><input name='occurred_on' value='{esc(row['occurred_on'])}'></p>"
                    f"<p><label>금액(원)</label><input name='amount_krw' value='{esc(row['amount_krw'])}'></p>"
                    f"<p><label>입금 종류</label><select name='income_kind'>{kind_options}</select></p>"
                    f"<p><label>이름</label><input name='customer_name' value='{esc(row['customer_name'])}'></p>"
                    f"<p><label>닉네임</label><input name='nickname' value='{esc(row.get('nickname', ''))}'></p>"
                    f"<p><label>메모</label><input name='operator_note' value='{esc(row.get('operator_note', ''))}'></p>"
                    "<p><label>변경 이유</label><select name='change_mode'>"
                    "<option value='exception'>예외 사항</option>"
                    "<option value='rule_change'>규칙 변경</option></select></p>"
                    f"{lock_note}"
                    "<button type='submit'>저장</button> "
                    "<a href='/row?id=" + esc(row_id) + "'>취소</a></form>"
                )
            else:
                extra = f"<p><a href='/row?id={esc(row_id)}&edit=1'>편집</a></p>"
            extra += (
                f"{link_info}{cand_info}"
                "<h3>은행 원천 연결</h3>"
                f"<form method='post' action='/api/income/{esc(row_id)}/link-bank'>"
                f"<input type='hidden' name='csrf' value='{CSRF_TOKEN}'>"
                f"<input type='hidden' name='expected_revision' value='{row.get('revision', 1)}'>"
                f"<input type='hidden' name='client_request_id' value='{uuid.uuid4().hex}'>"
                "<p><label>은행 배치 ID</label><input name='bank_batch_id'></p>"
                "<p><label>은행 행 번호</label><input name='bank_row_index'></p>"
                "<button type='submit'>연결</button></form>"
            )
        elif edit:
            extra = "<p class='muted'>은행 원천 행은 정정 경로로만 바꿀 수 있어요.</p>"
        else:
            extra = f"<p><a href='/row?id={esc(row_id)}&edit=1'>편집</a></p>"
        if _STORE is not None:
            if row.get("is_allocation"):
                source = _STORE.get_row(row["source_row_id"])
                reflected = _STORE.display_amount(source) if source else 0
                extra = (
                    "<h3>한 입금에서 배분된 내역</h3>"
                    f"<p class='muted'>원천 입금 {reflected:,}원 중 이 배분 {_shown_amount(row):,}원. "
                    "배분액은 배분 편집에서만 바꿔요.</p>"
                    f"<p><a href='/income/{esc(row['source_row_id'])}/split'>배분 편집 열기</a> · "
                    f"<a href='/row?id={esc(row['source_row_id'])}'>원천 상세</a></p>"
                )
            elif row.get("is_remainder"):
                source = _STORE.get_row(row["source_row_id"])
                reflected = _STORE.display_amount(source) if source else 0
                extra = (
                    "<h3>미배분 잔액</h3>"
                    f"<p class='muted'>원천 입금 반영액 {reflected:,}원 중 아직 나누지 않은 금액이에요. "
                    "독립 입금 사건이 아니에요.</p>"
                    f"<p><a href='/income/{esc(row['source_row_id'])}/split'>배분 편집 열기</a></p>"
                )
            elif row["row_id"] in _STORE.split_source_ids():
                allocs = _STORE.active_allocations(row["row_id"])
                remainder = _STORE.split_remainder(row["row_id"])
                lines = "".join(
                    f"<li>{esc(a['customer_name'])} · "
                    f"{esc(next((t['display_key'] for t in live_trips(include_archived=True) if t['tab_id'] == a['display_tab_id']), '분류대기'))} · "
                    f"{esc(INCOME_KIND_LABEL.get(a['income_kind'], ''))} · {a['amount_krw']:,}원</li>"
                    for a in allocs
                )
                extra = (
                    "<h3>한 입금에서 배분된 내역</h3>"
                    f"<ul>{lines}</ul>"
                    f"<p class='muted'>미배분 잔액 {remainder:,}원. 원금은 합계에 넣지 않아요.</p>"
                    f"<p><a href='/income/{esc(row_id)}/split'>배분 편집 열기</a></p>"
                )
            elif not edit:
                extra += f"<p><a href='/income/{esc(row_id)}/split'>입금 나누기</a></p>"
        body = f"<h2>수입 {esc(row['customer_name'])} {_shown_amount(row):,}원</h2><ul>{info}</ul>{extra}"
    top = (
        "<div class='top'><h1>웹 장부"
        f"<span class='synth'>{SYNTHETIC_MARK}</span></h1></div>"
    )
    return layout("행 상세", f"{top}<div class='wrap'><div class='body'>{body}<p><a href='/board'>목록으로</a></p></div></div>")


STATUS_FOR_CODE = {
    "EDIT_CONFLICT": 409,
    "REQUEST_ID_REUSED": 409,
    "FIELD_READ_ONLY": 422,
    "INVALID_VALUE": 422,
    "TARGET_NOT_ASSIGNABLE": 422,
    "DELETE_PREVIEW_STALE": 409,
    "CSRF_REQUIRED": 403,
}


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):  # keep test output quiet
        pass

    def _send(self, text: str, code: int = 200) -> None:
        data = text.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _send_json(self, value: dict, code: int = 200) -> None:
        data = json.dumps(value, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        query = parse_qs(parsed.query)
        if parsed.path in ("/", "/board"):
            tab = query.get("tab", ["trip-demo-a"])[0]
            self._send(board_page(tab, query.get("q", [""])[0]))
        elif parsed.path == "/row":
            row_id = query.get("id", [""])[0]
            self._send(detail_page(row_id, edit=query.get("edit", [""])[0] == "1"))
        elif parsed.path == "/import":
            self._send(import_page())
        elif parsed.path == "/income/new":
            self._send(income_new_page())
        elif parsed.path == "/expense/new":
            self._send(expense_new_page())
        elif parsed.path == "/export":
            self._send(export_page())
        elif parsed.path.startswith("/api/exports/") and parsed.path.endswith("/download"):
            self._send_export_file(parsed.path.rsplit("/", 2)[-2])
            return
        elif parsed.path.startswith("/api/exports/"):
            from .sheets_export import get_job

            if _STORE is None:
                self._send_json({"code": "STORE_UNBOUND", "message": "저장소가 연결되지 않았어요"}, code=503)
                return
            job = get_job(_STORE.conn, parsed.path.rsplit("/", 1)[-1])
            if job is None:
                self._send_json({"code": "NOT_FOUND", "message": "없는 작업이에요"}, code=404)
                return
            self._send_json(job, code=200)
        elif parsed.path.startswith("/income/") and parsed.path.endswith("/split"):
            parts = parsed.path.strip("/").split("/")
            self._send(split_page(parts[1] if len(parts) == 3 else ""))
        elif parsed.path == "/trips":
            self._send(trips_page(query.get("preview_tab", [""])[0]))
        elif parsed.path.startswith("/api/imports/"):
            if _IMPORTER is None:
                self._send_json({"code": "STORE_UNBOUND", "message": "저장소가 연결되지 않았어요"}, code=503)
                return
            progress = _IMPORTER.progress(parsed.path.rsplit("/", 1)[-1])
            if progress is None:
                self._send_json({"code": "NOT_FOUND", "message": "없는 작업이에요"}, code=404)
                return
            self._send_json(progress, code=200)
        else:
            self._send(layout("없음", "<p>없는 주소예요.</p>"), code=404)

    def do_POST(self) -> None:
        from .card_import import ImportError as CardImportError
        from .income_ledger import BankImporter, BankImportError
        from .ledger_store import SaveError

        parsed = urlparse(self.path)
        parts = parsed.path.strip("/").split("/")
        length = int(self.headers.get("Content-Length") or 0)
        if length > 5 * 1024 * 1024:
            self._send_json({"code": "TOO_LARGE", "message": "요청이 너무 커요"}, code=413)
            return
        content_type = self.headers.get("Content-Type") or ""
        raw = self.rfile.read(length) if length else b""

        def read_payload():
            if "application/json" in content_type:
                try:
                    return json.loads(raw.decode("utf-8") or "{}")
                except (ValueError, UnicodeDecodeError):
                    raise SaveError("INVALID_VALUE", "요청을 읽을 수 없어요")
            try:
                form = parse_qs(raw.decode("utf-8"), keep_blank_values=True)
            except UnicodeDecodeError:
                raise SaveError("INVALID_VALUE", "요청을 읽을 수 없어요")
            return {k: (v if len(v) > 1 else v[0]) for k, v in form.items()}

        def check_csrf(payload):
            token = payload.get("csrf") or self.headers.get("X-CSRF-Token") or ""
            if token != CSRF_TOKEN:
                raise SaveError("CSRF_REQUIRED", "확인 토큰이 없어요")

        if parsed.path == "/api/imports":
            if _IMPORTER is None:
                self._send_json({"code": "STORE_UNBOUND", "message": "저장소가 연결되지 않았어요"}, code=503)
                return
            token = self.headers.get("X-CSRF-Token") or ""
            if token != CSRF_TOKEN:
                self._send_json({"code": "CSRF_REQUIRED", "message": "확인 토큰이 없어요"}, code=403)
                return
            from urllib.parse import unquote

            filename = unquote(self.headers.get("X-Filename") or "upload.csv")
            try:
                received = _IMPORTER.receive(raw, filename)
                progress = _IMPORTER.progress(received["batch_id"])
                result = (progress or {}).get("result") or received.get("result") or {}
                self._send_json({"batch_id": received["batch_id"],
                                 "reused": received["reused"],
                                 "status": (progress or {}).get("status", "reconciling"),
                                 "result": result}, code=200)
            except CardImportError as exc:
                self._send_json({"code": exc.code, "message": str(exc)}, code=422)
            return
        if len(parts) != 4 or parts[0] != "api" or parts[1] != "rows" or parts[3] != "save":
            if parsed.path == "/api/income":
                self._handle_income_create(read_payload, check_csrf, content_type)
                return
            if parsed.path == "/api/expenses/manual":
                self._handle_manual_expense(read_payload, check_csrf, content_type)
                return
            if parsed.path == "/api/bank-imports":
                from urllib.parse import unquote

                self._handle_bank_import(
                    raw, unquote(self.headers.get("X-Filename") or "bank.csv"))
                return
            if len(parts) == 4 and parts[0] == "api" and parts[1] == "income" and parts[3] == "correct":
                self._handle_bank_correct(parts[2], read_payload, check_csrf, content_type)
                return
            if len(parts) == 4 and parts[0] == "api" and parts[1] == "income" and parts[3] == "link-bank":
                self._handle_bank_link(parts[2], read_payload, check_csrf)
                return
            if len(parts) == 4 and parts[0] == "api" and parts[1] == "trips" and parts[3] == "meta":
                self._handle_trip_meta(parts[2], read_payload, check_csrf, content_type)
                return
            if len(parts) == 4 and parts[0] == "api" and parts[1] == "trips" and parts[3] == "delete":
                self._handle_trip_delete(parts[2], read_payload, check_csrf, content_type)
                return
            if len(parts) == 4 and parts[0] == "api" and parts[1] == "rows" and parts[3] == "revert":
                self._handle_revert(parts[2], read_payload, check_csrf, content_type)
                return
            if len(parts) == 4 and parts[0] == "api" and parts[1] == "income" and parts[3] == "allocations":
                self._handle_allocations(parts[2], read_payload, check_csrf, content_type)
                return
            if parsed.path == "/api/exports/xlsx":
                self._handle_export(read_payload, check_csrf, content_type)
                return
            self._send_json({"code": "NOT_FOUND", "message": "없는 주소예요"}, code=404)
            return
        if _STORE is None:
            self._send_json({"code": "STORE_UNBOUND", "message": "저장소가 연결되지 않았어요"}, code=503)
            return
        try:
            payload = read_payload()
            check_csrf(payload)
            expected_revision = int(payload.get("expected_revision", ""))
        except SaveError as exc:
            self._send_json({"code": exc.code, "message": str(exc)},
                            code=STATUS_FOR_CODE.get(exc.code, 422))
            return
        except (TypeError, ValueError):
            self._send_json({"code": "INVALID_VALUE", "message": "revision이 필요해요"}, code=422)
            return
        kind, current_row = find_row(parts[2])
        if current_row is None:
            self._send_json({"code": "INVALID_VALUE", "message": "없는 행이에요"}, code=422)
            return
        if current_row.get("is_allocation"):
            allowed = ("customer_id", "customer_name", "nickname",
                       "display_tab_id", "income_kind")
            meta = ("csrf", "expected_revision", "client_request_id")
            blocked = [key for key in payload if key not in allowed and key not in meta]
            if blocked:
                self._send_json(
                    {"code": "FIELD_READ_ONLY",
                     "message": f"{blocked[0]}는 배분 행에서 수정할 수 없어요"},
                    code=422,
                )
                return
            changes = {key: payload[key] for key in allowed if key in payload}
            try:
                result = _STORE.update_allocation(
                    allocation_id=parts[2],
                    expected_source_revision=expected_revision,
                    changes=changes,
                    client_request_id=str(payload.get("client_request_id") or ""),
                    actor="owner",
                )
            except SaveError as exc:
                self._send_json({"code": exc.code, "message": str(exc)},
                                code=STATUS_FOR_CODE.get(exc.code, 422))
                return
            if "application/json" in content_type:
                self._send_json(result, code=200)
            else:
                self.send_response(303)
                self.send_header("Location", f"/row?id={parts[2]}")
                self.end_headers()
            return
        source = current_row.get("source_kind", "")
        if kind == "expense" and source in ("카드", ""):
            allowed = ("display_tab_id", "item", "description", "operator_note")
        elif kind == "expense":
            allowed = ("display_tab_id", "item", "description", "operator_note",
                        "occurred_on", "amount_krw")
        elif source == "은행":
            allowed = ("customer_id", "customer_name", "nickname",
                        "display_tab_id", "operator_note", "income_kind")
        else:
            allowed = ("display_tab_id", "income_kind", "customer_id", "customer_name",
                        "nickname", "occurred_on", "amount_krw", "operator_note")
        meta = ("csrf", "expected_revision", "client_request_id", "change_mode")
        if kind == "expense" and source in ("카드", ""):
            fixed = ("amount_krw", "occurred_on", "source_event_id",
                     "source_kind", "merchant", "reservation_no")
        elif kind == "expense":
            fixed = ("source_event_id", "source_kind", "merchant", "reservation_no")
        elif source == "은행":
            fixed = ("amount_krw", "occurred_on", "source_event_id", "source_kind")
        else:
            fixed = ("source_event_id", "source_kind")
        blocked = [k for k in payload if k in fixed]
        if blocked:
            self._send_json(
                {"code": "FIELD_READ_ONLY",
                 "message": f"{blocked[0]}는 고정 필드라 바꿀 수 없어요"}, code=422)
            return
        unknown = [k for k in payload if k not in allowed and k not in meta]
        if unknown:
            self._send_json(
                {"code": "INVALID_VALUE",
                 "message": f"허용하지 않은 필드예요: {unknown[0]}"}, code=422)
            return
        changes = {k: payload[k] for k in allowed if k in payload}
        if "amount_krw" in changes:
            raw_amount = changes["amount_krw"]
            if isinstance(raw_amount, bool):
                self._send_json({"code": "INVALID_VALUE",
                                 "message": "금액은 정수 원화로 입력해 주세요"}, code=422)
                return
            try:
                changes["amount_krw"] = int(str(raw_amount).replace(",", ""))
            except (TypeError, ValueError):
                self._send_json({"code": "INVALID_VALUE",
                                 "message": "금액은 정수 원화로 입력해 주세요"}, code=422)
                return
        try:
            result = _STORE.save(
                row_id=parts[2],
                expected_revision=expected_revision,
                client_request_id=str(payload.get("client_request_id") or ""),
                change_mode=str(payload.get("change_mode") or ""),
                changes=changes,
                actor="owner",
            )
        except SaveError as exc:
            self._send_json({"code": exc.code, "message": str(exc)},
                            code=STATUS_FOR_CODE.get(exc.code, 422))
            return
        if "application/json" in content_type:
            self._send_json(result, code=200)
        else:
            self.send_response(303)
            self.send_header("Location", f"/row?id={parts[2]}")
            self.end_headers()

    def _handle_income_create(self, read_payload, check_csrf, content_type) -> None:
        from .ledger_store import SaveError

        try:
            payload = read_payload()
            check_csrf(payload)
            try:
                amount = int(str(payload.get("amount_krw", "")).replace(",", ""))
            except (TypeError, ValueError):
                raise SaveError("INVALID_VALUE", "금액은 정수 원화로 입력해 주세요")
            result = _STORE.create_direct_income(
                fields={
                    "display_tab_id": payload.get("display_tab_id") or None,
                    "occurred_on": str(payload.get("occurred_on") or ""),
                    "amount_krw": amount,
                    "income_kind": str(payload.get("income_kind") or ""),
                    "customer_id": payload.get("customer_id") or None,
                    "customer_name": str(payload.get("customer_name") or ""),
                    "nickname": str(payload.get("nickname") or ""),
                    "memo": str(payload.get("operator_note") or ""),
                },
                client_request_id=str(payload.get("client_request_id") or ""),
                actor="owner",
            )
        except SaveError as exc:
            self._send_json({"code": exc.code, "message": str(exc)},
                            code=STATUS_FOR_CODE.get(exc.code, 422))
            return
        if "application/json" in content_type:
            self._send_json(result, code=200)
        else:
            self.send_response(303)
            self.send_header("Location", f"/row?id={result['row_id']}")
            self.end_headers()

    def _handle_manual_expense(self, read_payload, check_csrf, content_type) -> None:
        from .ledger_store import SaveError

        try:
            payload = read_payload()
            check_csrf(payload)
            try:
                amount = int(str(payload.get("amount_krw", "")).replace(",", ""))
            except (TypeError, ValueError):
                raise SaveError("INVALID_VALUE", "금액은 정수 원화로 입력해 주세요")
            result = _STORE.create_manual_expense(
                fields={
                    "display_tab_id": payload.get("display_tab_id") or None,
                    "occurred_on": str(payload.get("occurred_on") or ""),
                    "pay_method": str(payload.get("pay_method") or ""),
                    "item": str(payload.get("item") or ""),
                    "description": str(payload.get("description") or ""),
                    "amount_krw": amount,
                    "memo": str(payload.get("operator_note") or ""),
                },
                client_request_id=str(payload.get("client_request_id") or ""),
                actor="owner",
            )
        except SaveError as exc:
            self._send_json({"code": exc.code, "message": str(exc)},
                            code=STATUS_FOR_CODE.get(exc.code, 422))
            return
        if "application/json" in content_type:
            self._send_json(result, code=200)
        else:
            self.send_response(303)
            self.send_header("Location", f"/row?id={result['row_id']}")
            self.end_headers()

    def _handle_bank_import(self, raw: bytes, filename: str) -> None:
        from .income_ledger import BankImporter, BankImportError

        if _STORE is None:
            self._send_json({"code": "STORE_UNBOUND", "message": "저장소가 연결되지 않았어요"}, code=503)
            return
        token = self.headers.get("X-CSRF-Token") or ""
        if token != CSRF_TOKEN:
            self._send_json({"code": "CSRF_REQUIRED", "message": "확인 토큰이 없어요"}, code=403)
            return
        try:
            importer = BankImporter(_STORE.conn, _STORE)
            received = importer.receive(raw, filename)
            self._send_json({"batch_id": received["batch_id"],
                             "reused": received["reused"],
                             "result": received["result"]}, code=200)
        except BankImportError as exc:
            self._send_json({"code": exc.code, "message": str(exc)}, code=422)

    def _handle_revert(self, row_id, read_payload, check_csrf, content_type) -> None:
        from .ledger_store import SaveError

        try:
            payload = read_payload()
            check_csrf(payload)
            try:
                expected_revision = int(payload.get("expected_revision", ""))
            except (TypeError, ValueError):
                raise SaveError("INVALID_VALUE", "revision이 필요해요")
            result = _STORE.revert_row(
                row_id=row_id,
                expected_revision=expected_revision,
                client_request_id=str(payload.get("client_request_id") or ""),
                actor="owner",
            )
        except SaveError as exc:
            self._send_json({"code": exc.code, "message": str(exc)},
                            code=STATUS_FOR_CODE.get(exc.code, 422))
            return
        if "application/json" in content_type:
            self._send_json(result, code=200)
        else:
            self.send_response(303)
            self.send_header("Location", f"/row?id={row_id}")
            self.end_headers()

    def _handle_allocations(self, source_id, read_payload, check_csrf, content_type) -> None:
        from .ledger_store import SaveError

        try:
            payload = read_payload()
            check_csrf(payload)
            try:
                expected_revision = int(payload.get("expected_source_revision", ""))
            except (TypeError, ValueError):
                raise SaveError("INVALID_VALUE", "revision이 필요해요")
            if isinstance(payload.get("allocations"), list):
                plan = payload["allocations"]
            else:
                try:
                    count = int(payload.get("row_count", 0))
                except (TypeError, ValueError):
                    raise SaveError("INVALID_VALUE", "배분안이 올바르지 않아요")
                plan = []
                for i in range(count):
                    raw_amount = str(payload.get(f"alc_{i}_amount") or "").strip()
                    if not raw_amount:
                        continue
                    try:
                        amount = int(raw_amount.replace(",", ""))
                    except ValueError:
                        raise SaveError("INVALID_VALUE", "배분액은 정수 원화로 입력해 주세요")
                    tab = payload.get(f"alc_{i}_tab") or None
                    if tab == "unclassified":
                        tab = None
                    plan.append({
                        "allocation_id": str(payload.get(f"alc_{i}_id") or ""),
                        "customer_name": str(payload.get(f"alc_{i}_customer") or ""),
                        "display_tab_id": tab,
                        "income_kind": str(payload.get(f"alc_{i}_kind") or ""),
                        "amount_krw": amount,
                    })
            new_principal = None
            if str(payload.get("new_principal_amount") or "").strip():
                try:
                    new_principal = {
                        "amount_krw": int(str(payload["new_principal_amount"]).replace(",", "")),
                    }
                except ValueError:
                    raise SaveError("INVALID_VALUE", "원금은 정수 원화로 입력해 주세요")
            result = _STORE.save_allocations(
                source_row_id=source_id,
                expected_source_revision=expected_revision,
                allocations=plan,
                client_request_id=str(payload.get("client_request_id") or ""),
                new_principal=new_principal,
                actor="owner",
            )
        except SaveError as exc:
            self._send_json({"code": exc.code, "message": str(exc)},
                            code=STATUS_FOR_CODE.get(exc.code, 422))
            return
        if "application/json" in content_type:
            self._send_json(result, code=200)
        else:
            self.send_response(303)
            self.send_header("Location", f"/row?id={source_id}")
            self.end_headers()

    def _send_export_file(self, job_id: str) -> None:
        from urllib.parse import quote

        from .sheets_export import file_sha256, get_job

        if _STORE is None:
            self._send_json({"code": "STORE_UNBOUND", "message": "저장소가 연결되지 않았어요"}, code=503)
            return
        job = get_job(_STORE.conn, job_id)
        if job is None or not job.get("output_path"):
            self._send_json({"code": "NOT_FOUND", "message": "없는 작업이에요"}, code=404)
            return
        path = job["output_path"]
        try:
            if file_sha256(path) != (job.get("output_sha256") or ""):
                self._send_json({"code": "EXPORT_CHANGED",
                                 "message": "출력 파일이 바뀌었어요. 다시 출력해 주세요"}, code=410)
                return
            with open(path, "rb") as handle:
                data = handle.read()
        except OSError:
            self._send_json({"code": "NOT_FOUND", "message": "출력 파일이 없어요"}, code=404)
            return
        name = job.get("output_path", "ledger.xlsx").rsplit("/", 1)[-1].rsplit("\\", 1)[-1]
        self.send_response(200)
        self.send_header("Content-Type",
                         "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Content-Disposition",
                         f"attachment; filename*=UTF-8''{quote(name)}")
        self.end_headers()
        self.wfile.write(data)

    def _handle_export(self, read_payload, check_csrf, content_type) -> None:
        import os
        from pathlib import Path

        from .ledger_store import SaveError
        from .sheets_export import (build_workbook, file_sha256, get_job,
                                    publish_workbook, record_job)

        try:
            payload = read_payload()
            check_csrf(payload)
            raw_tabs = payload.get("tab_ids")
            if isinstance(raw_tabs, str):
                raw_tabs = [raw_tabs]
            tab_ids = [t for t in (raw_tabs or []) if isinstance(t, str)]
            valid = {t["tab_id"] for t in live_trips(include_archived=True)}
            if not tab_ids or any(t not in valid for t in tab_ids):
                raise SaveError("INVALID_VALUE", "출력할 여행을 골라 주세요")
            seen = set()
            ordered = [t for t in tab_ids if not (t in seen or seen.add(t))]
            job_id = f"xlsx-{payload.get('client_request_id') or uuid.uuid4().hex}"
            existing = get_job(_STORE.conn, job_id)
            if existing:
                if existing["tab_ids"] != ordered:
                    raise SaveError("REQUEST_ID_REUSED", "같은 요청 ID로 다른 내용을 보냈어요")
                if "application/json" in content_type:
                    self._send_json(existing, code=200)
                else:
                    self.send_response(303)
                    self.send_header(
                        "Location", f"/api/exports/{job_id}/download")
                    self.end_headers()
                return
            wb, manifest = build_workbook(_STORE, ordered)
            output_dir = (os.environ.get("WEBLEDGER_EXPORT_DIR", "webledger-exports") or "").strip()
            stem = f"ledger-{manifest['input_snapshot_sha256'][:12]}"
            try:
                target, manifest = publish_workbook(
                    wb, manifest, output_dir or "webledger-exports", stem)
            except FileExistsError:
                candidate = Path(output_dir or "webledger-exports") / f"{stem}.xlsx"
                if (candidate.is_file()
                        and file_sha256(str(candidate)) == manifest.get("output_sha256")):
                    target = candidate
                else:
                    target, manifest = publish_workbook(
                        wb, manifest, output_dir or "webledger-exports",
                        f"{stem}-{job_id[-8:]}")
            manifest["output_path"] = str(target)
            record_job(_STORE.conn, job_id=job_id, tab_ids=ordered,
                       manifest=manifest, status="ready")
            job = get_job(_STORE.conn, job_id)
        except SaveError as exc:
            self._send_json({"code": exc.code, "message": str(exc)},
                            code=STATUS_FOR_CODE.get(exc.code, 422))
            return
        if "application/json" in content_type:
            self._send_json(job, code=200)
        else:
            self.send_response(303)
            self.send_header("Location", f"/api/exports/{job_id}/download")
            self.end_headers()

    def _handle_trip_meta(self, tab_id, read_payload, check_csrf, content_type) -> None:
        from .ledger_store import SaveError

        try:
            payload = read_payload()
            check_csrf(payload)
            try:
                expected_revision = int(payload.get("expected_revision", ""))
            except (TypeError, ValueError):
                raise SaveError("INVALID_VALUE", "revision이 필요해요")
            kwargs = {}
            for key in ("display_key", "prepared_on", "prepared_by_name"):
                if key in payload:
                    kwargs[key] = payload[key]
            if "archived" in payload:
                value = payload["archived"]
                kwargs["archived"] = str(value).strip().lower() not in ("", "0", "false", "no")
            result = _STORE.save_trip_meta(
                tab_id=tab_id, expected_revision=expected_revision,
                client_request_id=str(payload.get("client_request_id") or ""),
                actor="owner", **kwargs,
            )
        except SaveError as exc:
            self._send_json({"code": exc.code, "message": str(exc)},
                            code=STATUS_FOR_CODE.get(exc.code, 422))
            return
        if "application/json" in content_type:
            self._send_json(result, code=200)
        else:
            self.send_response(303)
            self.send_header("Location", "/trips")
            self.end_headers()

    def _handle_trip_delete(self, tab_id, read_payload, check_csrf, content_type) -> None:
        from .ledger_store import SaveError

        try:
            payload = read_payload()
            check_csrf(payload)
            try:
                snapshot = json.loads(payload.get("snapshot") or "{}")
                expected_revision = int(snapshot.get("tab_revision", ""))
            except (TypeError, ValueError):
                raise SaveError("DELETE_PREVIEW_STALE", "미리보기부터 다시 확인해 주세요")
            mode = str(payload.get("mode") or "move-unclassified")
            destination = str(payload.get("destination") or "") or None
            if mode == "move-trip" and not destination:
                raise SaveError("TARGET_NOT_ASSIGNABLE", "옮길 여행을 골라 주세요")
            result = _STORE.apply_tab_delete(
                tab_id=tab_id, expected_revision=expected_revision,
                mode=mode, destination=destination,
                snapshot=snapshot,
                client_request_id=str(payload.get("client_request_id") or ""),
                actor="owner",
            )
        except SaveError as exc:
            self._send_json({"code": exc.code, "message": str(exc)},
                            code=STATUS_FOR_CODE.get(exc.code, 422))
            return
        if "application/json" in content_type:
            self._send_json(result, code=200)
        else:
            self.send_response(303)
            self.send_header("Location", "/trips")
            self.end_headers()

    def _handle_bank_correct(self, row_id, read_payload, check_csrf, content_type) -> None:
        from .ledger_store import SaveError

        try:
            payload = read_payload()
            check_csrf(payload)
            try:
                amount = int(str(payload.get("corrected_amount_krw", "")).replace(",", ""))
            except (TypeError, ValueError):
                raise SaveError("INVALID_VALUE", "정정 금액은 정수 원화로 입력해 주세요")
            try:
                expected_revision = int(payload.get("expected_revision", ""))
            except (TypeError, ValueError):
                raise SaveError("INVALID_VALUE", "revision이 필요해요")
            date_value = str(payload.get("corrected_occurred_on") or "").strip() or None
            result = _STORE.correct_bank_income(
                row_id=row_id,
                corrected_amount_krw=amount,
                corrected_occurred_on=date_value,
                reason=str(payload.get("reason") or ""),
                client_request_id=str(payload.get("client_request_id") or ""),
                expected_revision=expected_revision,
                actor="owner",
            )
        except SaveError as exc:
            self._send_json({"code": exc.code, "message": str(exc)},
                            code=STATUS_FOR_CODE.get(exc.code, 422))
            return
        if "application/json" in content_type:
            self._send_json(result, code=200)
        else:
            self.send_response(303)
            self.send_header("Location", f"/row?id={row_id}")
            self.end_headers()

    def _handle_bank_link(self, row_id, read_payload, check_csrf) -> None:
        from .ledger_store import SaveError

        try:
            payload = read_payload()
            check_csrf(payload)
            try:
                expected_revision = int(payload.get("expected_revision", ""))
            except (TypeError, ValueError):
                raise SaveError("INVALID_VALUE", "revision이 필요해요")
            result = _STORE.link_bank_source(
                row_id=row_id,
                bank_batch_id=str(payload.get("bank_batch_id") or ""),
                bank_row_index=int(payload.get("bank_row_index", -1)),
                expected_revision=expected_revision,
                client_request_id=str(payload.get("client_request_id") or ""),
            )
        except (SaveError, TypeError, ValueError) as exc:
            code = exc.code if isinstance(exc, SaveError) else "INVALID_VALUE"
            self._send_json({"code": code, "message": str(exc)},
                            code=STATUS_FOR_CODE.get(code, 422))
            return
        self._send_json(result, code=200)


def serve(port: int = 8751, db_path=None, with_worker: bool = True) -> HTTPServer:
    import os

    from .card_import import CardImporter, CardWorker
    from .ledger_store import LedgerStore

    if db_path is None:
        db_path = os.environ.get("WEBLEDGER_DB", "webledger.work.sqlite")
    store = LedgerStore(db_path)
    bind_store(store)
    bind_importer(CardImporter(store.conn, store))
    server = HTTPServer(("127.0.0.1", port), Handler)
    worker = None
    if with_worker:
        worker = CardWorker(db_path)
        worker.start()
    server.card_worker = worker
    server.card_store = store
    return server


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8751)
    args = parser.parse_args()
    httpd = serve(args.port)
    print(f"ledger board on http://127.0.0.1:{args.port}/board (synthetic)")
    httpd.serve_forever()
