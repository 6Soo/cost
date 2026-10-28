"""Render helpers and display projections for ledger board screens.

Extracted under RF-102 to separate HTML rendering, display formatting,
allocation details, history presentations, and editable field contracts
from the core ledger board request handler.
"""
from __future__ import annotations

import html
import uuid
from typing import Any, Callable, Dict, List, Optional, Set, Tuple

INCOME_KIND_LABEL = {"deposit": "예약금", "balance": "잔금", "additional": "추가금"}


def _active_store():
    from . import ledger_board
    return ledger_board._active_store()


def _csrf_token():
    from . import ledger_board
    return getattr(ledger_board, "CSRF_TOKEN", "")


def _live_trips(*args, **kwargs):
    from . import ledger_board
    return ledger_board.live_trips(*args, **kwargs)


def _shown_amount(row):
    from . import ledger_board
    return ledger_board._shown_amount(row)


def _shown_date(row):
    from . import ledger_board
    return ledger_board._shown_date(row)


def _find_row(row_id):
    from . import ledger_board
    return ledger_board.find_row(row_id)


def _layout(title, body):
    from . import ledger_board
    return ledger_board.layout(title, body)


def esc(value) -> str:
    return html.escape("" if value is None else str(value), quote=True)


def editable_fields(kind: str, source: str, is_allocation: bool = False):
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


def learning_case_id(row_id: str, *, store=None) -> str:
    """The newest learning case of a row, or an empty string."""
    if store is None:
        store = _active_store()
    if store is None:
        return ""
    try:
        found = store.conn.execute(
            "SELECT case_id FROM board_learning_cases WHERE row_id=?"
            " ORDER BY created_at DESC LIMIT 1", (row_id,)).fetchone()
    except Exception:
        return ""
    return "" if found is None else found[0]


def rule_dialog_link(row_id: str, *, store=None) -> str:
    """Small link to the rule dialog when the row has a learning case."""
    case_id = learning_case_id(row_id, store=store)
    if not case_id:
        return ""
    return f"<p><a href='/rules?case={esc(case_id)}'>규칙 대화 상자</a></p>"


def allocation_revert_status(allocation, *, store=None):
    from .ledger_store import SaveError

    if store is None:
        store = _active_store()
    if allocation is None:
        return {"revertible": False, "reason": "행을 찾지 못했어요"}
    if store is None:
        return {"revertible": False, "reason": "저장소가 연결되지 않았어요."}
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


def allocation_history_html(allocation, *, store=None, csrf_token=None) -> str:
    if store is None:
        store = _active_store()
    if csrf_token is None:
        csrf_token = _csrf_token()
    if store is None:
        return "<h3>입금 배분 이력</h3><p class='muted'>저장소가 연결되지 않았어요.</p>"
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


def allocation_detail_body(allocation, edit: bool, *, store=None, csrf_token=None, trips=None, shown_amount=None) -> str:
    if store is None:
        store = _active_store()
    if csrf_token is None:
        csrf_token = _csrf_token()
    if trips is None:
        trips = list(_live_trips(include_archived=True))
    if shown_amount is None:
        shown_amount = _shown_amount
    source = store.get_row(allocation["source_row_id"])
    reflected = store.display_amount(source) if source is not None else 0
    trips = list(trips)
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
        f"<h2>입금 배분 {esc(allocation.get('customer_name', ''))} {shown_amount(allocation):,}원</h2>"
        f"<ul><li>배분 ID: {esc(allocation['row_id'])}</li>"
        f"<li>원천 입금 {reflected:,}원 중 이 배분 {shown_amount(allocation):,}원</li>"
        f"<li>입금 종류: {esc(INCOME_KIND_LABEL.get(allocation.get('income_kind'), ''))}</li></ul>"
        f"{form}{links}{allocation_history_html(allocation, store=store, csrf_token=csrf_token)}"
    )


def history_html(row_id: str, *, store=None, csrf_token=None) -> str:
    if store is None:
        store = _active_store()
    if csrf_token is None:
        csrf_token = _csrf_token()
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
            "바뀌었습니다. 이 저장은 장부에 반영되지 않았습니다. "
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


def split_page(source_id: str, *, store=None, csrf_token=None, trips=None) -> str:
    if store is None:
        store = _active_store()
    if csrf_token is None:
        csrf_token = _csrf_token()
    if trips is None:
        trips = _live_trips()
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
        for t in trips:
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


def income_table(rows, *, shown_date=None, shown_amount=None) -> str:
    if shown_date is None:
        shown_date = _shown_date
    if shown_amount is None:
        shown_amount = _shown_amount
    trs = "".join(
        f"<tr><td>{esc(shown_date(r))}</td><td>{esc(r['customer_name'])}</td>"
        f"<td>{esc(r['nickname'])}</td>"
        f"<td class='num'>{shown_amount(r) if r['income_kind'] == 'deposit' else ''}</td>"
        f"<td class='num'>{shown_amount(r) if r['income_kind'] == 'balance' else ''}</td>"
        f"<td class='num'>{shown_amount(r) if r['income_kind'] == 'additional' else ''}</td>"
        f"<td class='num'>{shown_amount(r):,}</td>"
        f"<td><a href='/row?id={esc(r['row_id'])}'>상세</a></td></tr>"
        for r in rows
    )
    return (
        "<div class='card'><h3>수입 내용</h3><div class='scrollx'><table>"
        "<tr><th>거래일자</th><th>이름</th><th>닉네임</th><th>예약금</th><th>잔금</th>"
        f"<th>추가금</th><th>금액</th><th></th></tr>{trs}</table></div></div>"
    ).format(trs=trs if trs else "<tr><td colspan='8' class='muted'>아직 입력한 입금이 없어요</td></tr>")


def expense_table(rows, *, shown_date=None, shown_amount=None) -> str:
    if shown_date is None:
        shown_date = _shown_date
    if shown_amount is None:
        shown_amount = _shown_amount
    trs = "".join(
        f"<tr><td>{esc(shown_date(r))}</td><td>{esc(r['item'])}</td>"
        f"<td>{esc(r['description'])}</td><td>{esc(r['service_period'])}</td>"
        f"<td style='font-family:monospace'>{esc(r['reservation_no'])}</td>"
        f"<td>{esc(r['evidence_type'])}</td><td class='num'>{shown_amount(r):,}</td>"
        f"<td><a href='/row?id={esc(r['row_id'])}'>상세</a> "
        f"<a href='/row?id={esc(r['row_id'])}&edit=1'>편집</a></td></tr>"
        for r in rows
    )
    return (
        "<div class='card'><h3>지출 내용</h3><div class='scrollx'><table>"
        "<tr><th>거래일자</th><th>항목</th><th>내용</th><th>기간</th><th>예약번호</th>"
        f"<th>증빙유형</th><th>금액(원)</th><th></th></tr>{trs}</table></div></div>"
    ).format(trs=trs if trs else "<tr><td colspan='8' class='muted'>아직 연결된 지출이 없어요</td></tr>")


def detail_page(
    row_id: str,
    edit: bool = False,
    *,
    store=None,
    find_row_fn=None,
    csrf_token=None,
    trips=None,
    all_trips=None,
    shown_amount=None,
    layout_fn=None,
) -> str:
    if store is None:
        store = _active_store()
    if find_row_fn is None:
        find_row_fn = _find_row
    if csrf_token is None:
        csrf_token = _csrf_token()
    if trips is None:
        trips = _live_trips()
    if all_trips is None:
        all_trips = list(_live_trips(include_archived=True))
    if shown_amount is None:
        shown_amount = _shown_amount
    if layout_fn is None:
        layout_fn = _layout
    kind, row = find_row_fn(row_id)
    from . import ledger_design

    if row is None:
        return layout_fn("행 없음", "<div class='top'><h1>웹 장부</h1></div><div class='body'><p>행이 없어요.</p></div>")
    from . import ledger_design

    if row.get("is_allocation") and store is not None:
        body = allocation_detail_body(row, edit, store=store, csrf_token=csrf_token, trips=all_trips, shown_amount=shown_amount)
        return ledger_design.render(ledger_design.shell(
            "배분 행 상세", tab_id=row.get("display_tab_id") or "",
            heading=f"배분 {esc(row_id)}", body=(
                f"<div class='sect'>{body}"
                "<p><a href='/board'>목록으로</a></p></div>")))
    if kind == "expense":
        info = (
            f"<li>원천: {esc(row['source_kind'])} {esc(row['source_event_id'])}</li>"
            f"<li>분류 근거: {esc(row['classification_basis'])}</li>"
            f"<li>분류 상태: {esc(row['classification_state'])} (표시만 일반 행)</li>"
            f"<li>여행 revision {esc(str(row.get('revision', 1)))}</li>"
        )
        if edit:
            if store is None:
                form = (
                    "<h3>행 편집 (저장 준비 중)</h3>"
                    "<p class='muted'>저장소가 연결되지 않았어요.</p>"
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
                        for t in trips
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
                    f"<input type='hidden' name='return_to' value='{esc('/row?id=' + row_id + ('&edit=1' if edit else ''))}'>"
                    f"<input type='hidden' name='csrf' value='{csrf_token}'>"
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
            f"{form}{history_html(row_id, store=store, csrf_token=csrf_token)}"
        )
    else:
        info = (
            f"<li>원천: {esc(row['source_kind'])} {esc(row['source_event_id'])}</li>"
            f"<li>입금 종류: {esc(INCOME_KIND_LABEL.get(row['income_kind'], ''))}</li>"
            f"<li>사건 구분: {esc(row['event_type'])}</li>"
        )
        extra = ""
        if store is not None and row.get("source_kind") == "은행":
            corrections = store.list_corrections(row_id)
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
                f"<input type='hidden' name='csrf' value='{csrf_token}'>"
                f"<input type='hidden' name='expected_revision' value='{row.get('revision', 1)}'>"
                f"<input type='hidden' name='client_request_id' value='{uuid.uuid4().hex}'>"
                "<p><label>장부 표시 금액</label><input name='corrected_amount_krw'></p>"
                "<p><label>장부 표시 날짜(선택)</label><input name='corrected_occurred_on' placeholder='2026-04-02'></p>"
                "<p><label>이유</label><input name='reason'></p>"
                "<button type='submit'>정정 기록</button></form>"
                "<p class='muted'>은행 원본은 그대로 두고 장부 표시만 바꿔요.</p>"
            )
        elif store is not None and row.get("source_kind") == "직접 입력":
            options = (
                "<option value='unclassified'"
                f"{' selected' if row['display_tab_id'] is None else ''}>"
                "분류대기</option>"
                + "".join(
                    f"<option value='{esc(t['tab_id'])}'"
                    f"{' selected' if row['display_tab_id'] == t['tab_id'] else ''}>"
                    f"{esc(t['display_key'])}</option>"
                    for t in trips
                )
            )
            kind_options = "".join(
                f"<option value='{k}'{' selected' if row['income_kind'] == k else ''}>"
                f"{esc(INCOME_KIND_LABEL[k])}</option>"
                for k in ("deposit", "balance", "additional")
            )
            links = store.conn.execute(
                "SELECT bank_batch_id, bank_row_index FROM income_source_links WHERE row_id=?",
                (row_id,),
            ).fetchall()
            link_lines = "".join(
                f"<li>은행 원천 {esc(b)} #{i}</li>" for b, i in links
            )
            link_info = f"<h3>연결된 은행 원천</h3><ul>{link_lines}</ul>" if link_lines else ""
            candidates = store.find_bank_candidates(row_id)
            cand_lines = "".join(
                f"<li>{esc(c['occurred_on'])} · {esc(c['customer_name'])} · "
                f"{c['amount_krw']:,}원 · {esc(c['row_id'])}</li>"
                for c in candidates
            )
            cand_info = (
                "<h3>중복 후보(판단 전, 합산 제외 아님)</h3><ul>{cand_lines}</ul>"
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
                    f"<input type='hidden' name='return_to' value='{esc('/row?id=' + row_id + ('&edit=1' if edit else ''))}'>"
                    f"<input type='hidden' name='csrf' value='{csrf_token}'>"
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
                f"<input type='hidden' name='csrf' value='{csrf_token}'>"
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
        if store is not None:
            if row.get("is_allocation"):
                source = store.get_row(row["source_row_id"])
                reflected = store.display_amount(source) if source else 0
                extra = (
                    "<h3>한 입금에서 배분된 내역</h3>"
                    f"<p class='muted'>원천 입금 {reflected:,}원 중 이 배분 {shown_amount(row):,}원. "
                    "배분액은 배분 편집에서만 바꿔요.</p>"
                    f"<p><a href='/income/{esc(row['source_row_id'])}/split'>배분 편집 열기</a> · "
                    f"<a href='/row?id={esc(row['source_row_id'])}'>원천 상세</a></p>"
                )
            elif row.get("is_remainder"):
                source = store.get_row(row["source_row_id"])
                reflected = store.display_amount(source) if source else 0
                extra = (
                    "<h3>미배분 잔액</h3>"
                    f"<p class='muted'>원천 입금 반영액 {reflected:,}원 중 아직 나누지 않은 금액이에요. "
                    "독립 입금 사건이 아니에요.</p>"
                    f"<p><a href='/income/{esc(row['source_row_id'])}/split'>배분 편집 열기</a></p>"
                )
            elif row["row_id"] in store.split_source_ids():
                allocs = store.active_allocations(row["row_id"])
                remainder = store.split_remainder(row["row_id"])
                lines = "".join(
                    f"<li>{esc(a['customer_name'])} · "
                    f"{esc(next((t['display_key'] for t in all_trips if t['tab_id'] == a['display_tab_id']), '분류대기'))} · "
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
        body = f"<h2>수입 {esc(row['customer_name'])} {shown_amount(row):,}원</h2><ul>{info}</ul>{extra}"

    return ledger_design.render(ledger_design.shell(
        "행 상세", tab_id=row.get("display_tab_id") or "",
        heading=f"거래 {esc(row_id)}",
        meta=(f"<span>구분 <b>{'수입' if kind == 'income' else '지출'}</b></span>"
              + ("<span><a href='/trips'>여행 관리</a></span>" if kind != "income" else "")),
        body=(f"<div class='sect'>{body}{rule_dialog_link(row_id, store=store)}"
              "<p><a href='/board'>목록으로</a></p></div>")))

