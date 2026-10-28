"""Render helpers and display projections for ledger board screens.

Extracted under RF-102 to separate HTML rendering, display formatting,
allocation details, history presentations, and editable field contracts
from the core ledger board request handler.
"""
from __future__ import annotations

import html
import uuid
from typing import Any, Callable, Dict, List, Optional, Tuple

INCOME_KIND_LABEL = {"deposit": "예약금", "balance": "잔금", "additional": "추가금"}


def esc(value: Any) -> str:
    """Escape value for safe HTML insertion."""
    return html.escape("" if value is None else str(value), quote=True)


def editable_fields(kind: str, source: str, is_allocation: bool = False) -> Tuple[Tuple[str, ...], Tuple[str, ...]]:
    """The (changeable, fixed) field names for a row.

    The save endpoint and the edit form both read this, so the form can never
    offer a field the endpoint would refuse.
    """
    if is_allocation:
        # An allocation row refuses anything outside its own list, so it has no
        # separate fixed list to publish.
        return (("customer_id", "customer_name", "nickname",
                 "display_tab_id", "income_kind"), ())
    if kind == "expense" and source in ("카드", ""):
        return (("display_tab_id", "item", "description", "operator_note"),
                ("amount_krw", "occurred_on", "source_event_id", "source_kind",
                 "merchant", "reservation_no"))
    if kind == "expense":
        return (("display_tab_id", "item", "description", "operator_note",
                 "occurred_on", "amount_krw"),
                ("source_event_id", "source_kind", "merchant", "reservation_no"))
    if source == "은행":
        return (("customer_id", "customer_name", "nickname",
                 "display_tab_id", "operator_note", "income_kind"),
                ("amount_krw", "occurred_on", "source_event_id", "source_kind"))
    return (("display_tab_id", "income_kind", "customer_id", "customer_name",
             "nickname", "occurred_on", "amount_krw", "operator_note"),
            ("source_event_id", "source_kind"))


def learning_case_id(row_id: str, *, store: Any) -> str:
    """The newest learning case of a row, or an empty string."""
    if store is None:
        return ""
    try:
        found = store.conn.execute(
            "SELECT case_id FROM board_learning_cases WHERE row_id=?"
            " ORDER BY created_at DESC LIMIT 1", (row_id,)).fetchone()
    except Exception:
        return ""
    return "" if found is None else found[0]


def rule_dialog_link(row_id: str, *, store: Any) -> str:
    """Small link to the rule dialog when the row has a learning case."""
    case_id = learning_case_id(row_id, store=store)
    if not case_id:
        return ""
    return f"<p><a href='/rules?case={esc(case_id)}'>규칙 대화 열기</a></p>"


def allocation_revert_status(allocation: Optional[Dict[str, Any]], *, store: Any) -> Dict[str, Any]:
    from .ledger_store import SaveError

    if allocation is None:
        return {"revertible": False, "reason": "없는 배분 행이에요"}
    stored = store.get_allocation(allocation["row_id"])
    if stored is not None:
        allocation = {**allocation, **stored}
    if not allocation.get("active"):
        return {"revertible": False, "reason": "비활성 배분은 되돌릴 수 없어요"}
    source = store.get_row(allocation["source_row_id"])
    if source is None:
        return {"revertible": False, "reason": "원천 입금 행이 없어요"}
    if source["revision"] != allocation["source_revision"]:
        return {"revertible": False, "reason": "원천 입금이 바뀌어서 최신 상태를 확인해 주세요"}
    try:
        changes, history = store._allocation_revert_changes(allocation)
    except SaveError as exc:
        return {"revertible": False, "reason": str(exc)}
    return {
        "revertible": True,
        "reason": None,
        "changes": changes,
        "expected_source_revision": source["revision"],
        "history": history,
    }


def allocation_history_html(
    allocation: Dict[str, Any],
    *,
    store: Any,
    csrf_token: str,
) -> str:
    rows = store.conn.execute(
        "SELECT created_at, client_request_id, reverts_event_id, event_id"
        " FROM income_allocation_history WHERE allocation_id=? ORDER BY id DESC",
        (allocation["row_id"],),
    ).fetchall()
    items = "".join(
        f"<li>{esc(created_at)} · 요청 {esc(request_id)} · "
        f"사건 {esc(event_id or '대기')} · 되돌림 대상 {esc(reverts_event_id or '-')}</li>"
        for created_at, request_id, reverts_event_id, event_id in rows
    )
    status = allocation_revert_status(allocation, store=store)
    if status["revertible"]:
        changes = " · ".join(
            f"{esc(field)}={esc(value)}"
            for field, value in sorted(status["changes"].items())
        )
        revert_html = (
            "<h3>이 배분 행 되돌리기</h3>"
            f"<p class='muted'>되돌릴 값: {changes}</p>"
            f"<form method='post' action='/api/rows/{esc(allocation['row_id'])}/revert'>"
            f"<input type='hidden' name='csrf' value='{csrf_token}'>"
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


def allocation_detail_body(
    allocation: Dict[str, Any],
    edit: bool,
    *,
    store: Any,
    csrf_token: str,
    trips_fn: Callable[[], List[Dict[str, Any]]],
    shown_amount_fn: Callable[[Dict[str, Any]], int],
) -> str:
    source = store.get_row(allocation["source_row_id"])
    reflected = store.display_amount(source) if source is not None else 0
    trips = list(trips_fn())
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
            f"<input type='hidden' name='csrf' value='{csrf_token}'>"
            f"<input type='hidden' name='expected_revision' value='{source['revision']}'>"
            f"<input type='hidden' name='client_request_id' value='{uuid.uuid4().hex}'>"
            f"<p><label>고객 ID</label><input name='customer_id' value='{esc(allocation.get('customer_id') or '')}'></p>"
            f"<p><label>고객 이름</label><input name='customer_name' value='{esc(allocation.get('customer_name', ''))}'></p>"
            f"<p><label>닉네임</label><input name='nickname' value='{esc(allocation.get('nickname', ''))}'></p>"
            f"<p><label>여행</label><select name='display_tab_id'>{tab_options}</select></p>"
            f"<p><label>입금 종류</label><select name='income_kind'>{kind_options}</select></p>"
            f"<p><label>거래일자</label><input value='{esc(allocation['occurred_on'])}' readonly></p>"
            f"<p><label>배분 금액</label><input value='{esc(allocation['amount_krw'])}' readonly></p>"
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
        f"<h2>입금 배분 {esc(allocation.get('customer_name', ''))} {shown_amount_fn(allocation):,}원</h2>"
        f"<ul><li>배분 ID: {esc(allocation['row_id'])}</li>"
        f"<li>원천 입금 {reflected:,}원 중 이 배분 {shown_amount_fn(allocation):,}원</li>"
        f"<li>입금 종류: {esc(INCOME_KIND_LABEL.get(allocation.get('income_kind'), ''))}</li></ul>"
        f"{form}{links}{allocation_history_html(allocation, store=store, csrf_token=csrf_token)}"
    )


def history_html(
    row_id: str,
    *,
    store: Any,
    csrf_token: str,
) -> str:
    if store is None:
        return ""
    items = store.list_history(row_id)
    if not items:
        return "<h3>변경 이력</h3><p class='muted'>직접 수정된 변경이 없어요</p>"
    lis = "".join(
        f"<li>rev {h['revision']} · {esc(h['change_mode'])} · {esc(h['actor'])} · "
        f"{esc(h['created_at'])} · 요청 {esc(h['event_id'] or '감사 기록 없음')}</li>"
        for h in items
    )
    # APP_SPEC 9 lists `충돌` among the states told apart in the row detail, and
    # DETAILED 3.2 says the row edit screen shows the conflict with a way to
    # re-edit from the latest revision. A conflict clears on the next save.
    conflict_html = ""
    try:
        conflict = store.row_conflict(row_id)
    except Exception:
        conflict = None
    if conflict:
        conflict_html = (
            "<h3>충돌</h3><p class='muted'>revision "
            f"{esc(str(conflict.get('expected_revision')))}로 저장을 시도했지만 "
            f"이 행은 revision {esc(str(conflict.get('current_revision')))}까지 "
            "바뀌었습니다. 이 저장액은 장부에 반영되지 않았습니다. "
            "최신 값을 확인한 뒤 다시 저장해 주세요.</p>")
    status = store.revert_status(row_id)
    if status["revertible"]:
        revert_html = (
            "<h3>직전 수정 되돌리기</h3>"
            f"<form method='post' action='/api/rows/{esc(row_id)}/revert'>"
            f"<input type='hidden' name='csrf' value='{csrf_token}'>"
            f"<input type='hidden' name='expected_revision' value='{items[-1]['revision']}'>"
            f"<input type='hidden' name='client_request_id' value='{uuid.uuid4().hex}'>"
            "<button type='submit'>직전 수정 되돌리기</button></form>"
        )
    else:
        revert_html = (
            "<h3>직전 수정 되돌리기</h3>"
            f"<p class='muted'>{esc(status['reason'])}</p>"
        )
    return (f"<h3>변경 이력</h3><ul>{lis}</ul>{conflict_html}{revert_html}")


def split_page(
    source_id: str,
    *,
    store: Any,
    csrf_token: str,
    trips_fn: Callable[[], List[Dict[str, Any]]],
) -> str:
    from . import ledger_design

    if store is None:
        return ledger_design.render(ledger_design.shell(
            '배분 추정', tab_id='', heading='배분 추정',
            body="<div class='sect'><p>저장소가 연결되지 않았어요.</p></div>"))
    source = store.get_row(source_id)
    if source is None or source["row_kind"] != "income":
        return ledger_design.render(ledger_design.shell(
            '배분 편집', tab_id='', heading='배분 편집',
            body="<div class='sect'><p>없는 수입 행이에요.</p></div>"))
    reflected = store.display_amount(source)
    allocs = store.active_allocations(source_id)
    remainder = reflected - sum(a["amount_krw"] for a in allocs)
    def tab_options(current):
        cur = current or "unclassified"
        out = (
            f"<option value='unclassified'{' selected' if cur == 'unclassified' else ''}>"
            "분류대기(미배정 배분)</option>"
        )
        for t in trips_fn():
            selected = " selected" if cur == t["tab_id"] else ""
            out += f"<option value='{esc(t['tab_id'])}'{selected}>{esc(t['display_key'])}</option>"
        return out
    rows_html = ""
    for i, a in enumerate(list(allocs) + [{}, {}]):
        aid = a.get("allocation_id", "")
        rows_html += (
            f"<tr><td data-label='배분 ID'>"
            f"<input name='alc_{i}_id' value='{esc(aid)}' readonly></td>"
            f"<td data-label='고객'>"
            f"<input name='alc_{i}_customer' value='{esc(a.get('customer_name', ''))}'></td>"
            f"<td data-label='여행'>"
            f"<select name='alc_{i}_tab'>{tab_options(a.get('display_tab_id'))}</select></td>"
            f"<td data-label='종류'><select name='alc_{i}_kind'>"
            + "".join(
                f"<option value='{k}'{' selected' if a.get('income_kind') == k else ''}>"
                f"{esc(INCOME_KIND_LABEL[k])}</option>"
                for k in ("deposit", "balance", "additional")
            ) +
            "</td>"
            f"<td data-label='금액'>"
            f"<input name='alc_{i}_amount' value='{esc(a.get('amount_krw', ''))}'>"
            "</td></tr>"
        )
    principal_fields = ""
    if source.get("source_kind") == "직접 입력":
        principal_fields = (
            "<p><label>원금(선택, 배분안과 함께 저장)</label>"
            f"<input name='new_principal_amount' value='{source['amount_krw']}'></p>"
        )
    body = (
        "<div class='sect'><h2>입금 나누기</h2>"
        f"<p>원천 입금액 {source['amount_krw']:,}원 · 현재 장부 반영액 {reflected:,}원 · "
        f"배분한 금액 {reflected - remainder:,}원 · 남은 금액 {remainder:,}원</p>"
        f"<form method='post' action='/api/income/{esc(source_id)}/allocations'>"
        f"<input type='hidden' name='csrf' value='{csrf_token}'>"
        f"<input type='hidden' name='expected_source_revision' value='{source['revision']}'>"
        f"<input type='hidden' name='client_request_id' value='{uuid.uuid4().hex}'>"
        f"<input type='hidden' name='row_count' value='{len(allocs) + 2}'>"
        f"{principal_fields}"
        "<table class='alloc'>"
        "<colgroup><col style='width:150px'><col><col style='width:230px'>"
        "<col style='width:120px'><col style='width:140px'></colgroup>"
        "<thead><tr><th scope='col'>배분 ID</th><th scope='col'>고객</th>"
        "<th scope='col'>여행</th><th scope='col'>종류</th><th scope='col'>금액</th>"
        f"</tr></thead><tbody>{rows_html}</tbody></table>"
        "<p class='muted'>금액이 빈 행은 제외돼요. 합계가 반영액을 넘으면 저장하지 않아요. "
        "같은 입금의 배분 표시 날짜는 원천 날짜를 함께 써요.</p>"
        "<button type='submit'>배분안 저장</button></form>"
        f"<p><a href='/row?id={esc(source_id)}'>원천 상세로</a></p></div>"
    )
    return ledger_design.render(ledger_design.shell(
        '배분 추정', tab_id='', heading='배분 추정', body=body))


def income_table(
    rows: List[Dict[str, Any]],
    *,
    shown_date_fn: Callable[[Dict[str, Any]], str],
    shown_amount_fn: Callable[[Dict[str, Any]], int],
) -> str:
    trs = "".join(
        f"<tr><td>{esc(shown_date_fn(r))}</td><td>{esc(r['customer_name'])}</td>"
        f"<td>{esc(r['nickname'])}</td>"
        f"<td class='num'>{shown_amount_fn(r) if r['income_kind'] == 'deposit' else ''}</td>"
        f"<td class='num'>{shown_amount_fn(r) if r['income_kind'] == 'balance' else ''}</td>"
        f"<td class='num'>{shown_amount_fn(r) if r['income_kind'] == 'additional' else ''}</td>"
        f"<td class='num'>{shown_amount_fn(r):,}</td>"
        f"<td><a href='/row?id={esc(r['row_id'])}'>상세</a></td></tr>"
        for r in rows
    )
    return (
        "<div class='card'><h3>수입 내용</h3><div class='scrollx'><table>"
        "<tr><th>거래일자</th><th>이름</th><th>닉네임</th><th>예약금</th><th>잔금</th>"
        f"<th>추가금</th><th>금액</th><th></th></tr>{trs}</table></div></div>"
    ).format(trs=trs if trs else "<tr><td colspan='8' class='muted'>아직 입력한 입금이 없어요</td></tr>")


def expense_table(
    rows: List[Dict[str, Any]],
    *,
    shown_date_fn: Callable[[Dict[str, Any]], str],
    shown_amount_fn: Callable[[Dict[str, Any]], int],
) -> str:
    trs = "".join(
        f"<tr><td>{esc(shown_date_fn(r))}</td><td>{esc(r['item'])}</td>"
        f"<td>{esc(r['description'])}</td><td>{esc(r['service_period'])}</td>"
        f"<td style='font-family:monospace'>{esc(r['reservation_no'])}</td>"
        f"<td>{esc(r['evidence_type'])}</td><td class='num'>{shown_amount_fn(r):,}</td>"
        f"<td><a href='/row?id={esc(r['row_id'])}'>상세</a> "
        f"<a href='/row?id={esc(r['row_id'])}&edit=1'>편집</a></td></tr>"
        for r in rows
    )
    return (
        "<div class='card'><h3>지출 내용</h3><div class='scrollx'><table>"
        "<tr><th>거래일자</th><th>항목</th><th>내용</th><th>기간</th><th>예약번호</th>"
        f"<th>증빙유형</th><th>금액(원)</th><th></th></tr>{trs}</table></div></div>"
    ).format(trs=trs if trs else "<tr><td colspan='8' class='muted'>아직 연결된 지출이 없어요</td></tr>")
