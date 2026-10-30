"""소유자 전용 보험 명단의 가림 이름과 기존 수입 이름 대조 화면."""
from __future__ import annotations

import html
from decimal import Decimal, InvalidOperation

ROUTES = ("/participants/insurance-match", "/api/participants/insurance-match")
PAGE_PATH = ROUTES[0]
PAGE_SIZE = 50

STATE_LABELS = {
    "matched": "글자 일치",
    "unique": "글자 일치",
    "ambiguous": "후보 여러 건",
    "unmatched": "일치 없음",
    "no_visible_letters": "보이는 글자 없음",
    "source_unavailable": "수입 자료 확인 필요",
}


def owns_route(path: str) -> bool:
    return path in ROUTES


def _escape(value) -> str:
    return html.escape("" if value is None else str(value), quote=True)


def _amount(value) -> str:
    if value is None or value == "":
        return "금액 미기재"
    try:
        number = Decimal(str(value))
        if not number.is_finite():
            return _escape(value)
        return f"{number:,}원"
    except (InvalidOperation, TypeError, ValueError):
        return _escape(value)


def render_page(state: dict, *, query=None) -> str:
    query = query or {}
    selected_contract = str(query.get("contract_key", [""])[0] or "")
    selected_trip = str(query.get("trip", [""])[0] or "")
    contracts = list(state.get("contracts") or [])
    visible = [c for c in contracts if (not selected_contract or c.get("contract_key") == selected_contract)
               and (not selected_trip or any(str(t.get("trip_id") or "") == selected_trip
                                             for t in c.get("trip_options") or []))]
    status = ("대조 완료" if state.get("available") and state.get("code") == "OK" else
              "일부 수입 자료 확인 필요" if state.get("available") else "대조 자료를 사용할 수 없음")
    summary_counts = state.get("counts") or {}
    summary = " · ".join(f"{label} {int(summary_counts.get(key, 0) or 0)}건" for key, label in (
        ("contracts", "계약"), ("rows", "명단 행"), ("matched", "글자 일치"),
        ("ambiguous", "후보 여러 건"), ("unmatched", "일치 없음"),
        ("no_visible_letters", "보이는 글자 없음"), ("source_unavailable", "수입 자료 확인 필요")))
    options = ["<option value=''>전체 계약</option>"]
    for index, contract in enumerate(state.get('contract_options', contracts), start=1):
        key = str(contract.get("contract_key") or "")
        row_count = contract.get('row_count', len(contract.get("rows") or []))
        label = (f"{contract.get('travel_start') or '기간 미기재'}–"
                 f"{contract.get('travel_end') or '기간 미기재'} · 계약 {index} · {row_count}건")
        options.append(f"<option value='{_escape(key)}'{ ' selected' if key == selected_contract else ''}>{_escape(label)}</option>")
    trips = {}
    for contract in contracts:
        for trip in contract.get("trip_options") or []:
            tid = str(trip.get("trip_id") or "")
            if tid:
                trips.setdefault(tid, str(trip.get("trip_name") or tid))
    trip_options = ["<option value=''>전체 여행</option>"] + [
        f"<option value='{_escape(tid)}'{ ' selected' if tid == selected_trip else ''}>{_escape(name)}</option>"
        for tid, name in trips.items()]
    cards = []
    for contract_index, contract in enumerate(visible):
        rows = list(contract.get("rows") or [])
        contract_id = f"contract-{contract_index}"
        row_markup = []
        for index, row in enumerate(rows):
            state_key = str(row.get("match_state") or "unmatched")
            label = STATE_LABELS.get(state_key, "일치 없음")
            candidates = list(row.get("matches") or [])
            match = candidates[0] if state_key in ("matched", "unique") and candidates else None
            def candidate_detail(item):
                trip_name = item.get("trip_name") or item.get("trip_id") or "여행 미기재"
                return (f"<div class='match-detail'><strong>{_escape(item.get('name'))}</strong>"
                        f"{(' · ' + _escape(item.get('nickname'))) if item.get('nickname') else ''}"
                        f"<br>여행 {_escape(trip_name)} · 날짜 {_escape(item.get('date') or '미기재')}"
                        f" · 금액 {_amount(item.get('amount'))}</div>")
            details = candidate_detail(match) if match else ""
            if state_key == "ambiguous" and candidates:
                choices = "".join(f"<option value='{i}'>{_escape(c.get('name') or '이름 미기재')}"
                                   f"{(' · ' + _escape(c.get('date'))) if c.get('date') else ''}</option>"
                                   for i, c in enumerate(candidates))
                details = (f"<label>후보 살펴보기 <select class='candidate-choice' aria-label='수입 후보 선택'>{choices}</select></label>"
                           + "".join(f"<div class='candidate-panel' data-candidate='{i}'"
                                    f"{' hidden' if i else ''}>{candidate_detail(c)}</div>"
                                    for i, c in enumerate(candidates)))
            row_markup.append(
                f"<tr><th scope='row'>{_escape(row.get('masked_name') or '가림 이름 없음')}</th>"
                f"<td><span class='state'>{label}</span></td><td>{int(row.get('candidate_count', len(candidates)) or 0)}건</td>"
                f"<td>{details or '표시할 수입 후보가 없습니다.'}</td></tr>")
        pages = max(1, (len(rows) + PAGE_SIZE - 1) // PAGE_SIZE)
        pager = (f"<nav class='pager' aria-label='명단 페이지' data-page-size='{PAGE_SIZE}'>"
                 f"<button type='button' class='prev' aria-label='이전 페이지'>이전</button>"
                 f"<span aria-live='polite'>1 / {pages} · 전체 {len(rows)}건</span>"
                 f"<button type='button' class='next' aria-label='다음 페이지'>다음</button></nav>")
        raw_insurance_status = contract.get("insurance_status")
        insurance_status = ("가입 완료 또는 기간 종료(조회 자료)"
                            if raw_insurance_status == "completed_or_expired"
                            else "상태 확인 필요")
        scope_label = contract.get("scope_label")
        cards.append(
            f"<section class='contract' data-contract='{contract_id}'><h2>보험 계약 · 여행 기간 "
            f"{_escape(contract.get('travel_start'))}–{_escape(contract.get('travel_end'))}</h2>"
            f"<p>상태: {insurance_status} · 전체 {len(rows)}건</p>"
            f"{('<p>' + _escape(scope_label) + '</p>') if scope_label else ''}"
            f"{pager}<div class='table-wrap'><table><caption>가림 이름과 기존 수입 이름 글자 대조</caption>"
            f"<thead><tr><th scope='col'>보험 명단 가림 이름</th><th scope='col'>대조 상태</th>"
            f"<th scope='col'>수입 후보</th><th scope='col'>기존 수입 기록</th></tr></thead>"
            f"<tbody>{''.join(row_markup) or '<tr><td colspan=\"4\">표시할 명단 행이 없습니다.</td></tr>'}</tbody></table></div></section>")
    error = ""
    if not state.get("available") or state.get("code") != "OK":
        error = (f"<div class='error' role='status'><strong>{_escape(status)}</strong> · "
                 f"{_escape(state.get('message') or '자료 상태를 확인해 주세요')}"
                 f" · 상태 코드 {_escape(state.get('code') or 'UNKNOWN')}</div>")
        freshness = state.get("inputs_freshness")
        if freshness:
            error += f"<p class='error'>자료 최신성: {_escape(freshness)}</p>"
    body = ("<main class='content'><h1>보험 명단 · 수입 글자 대조</h1>"
            "<p class='notice'>보험 명단의 가려진 글자와 기존 수입 기록의 이름을 비교한 결과입니다. "
            "글자 대조는 보험 가입 완료나 현금 수령을 확인하지 않습니다. 후보 살펴보기는 이 화면에서만 동작합니다.</p>"
            f"<p class='summary'>{_escape(summary)}</p>{error}"
            "<form method='get' class='filters'><label>보험 계약 <select name='contract_key'>" + ''.join(options) +
            "</select></label><label>여행 <select name='trip'>" + ''.join(trip_options) +
            "</select></label><button type='submit'>필터 적용</button></form>" +
            (''.join(cards) if cards else "<p>조건에 맞는 명단이 없습니다.</p>") +
            "</main><script>(function(){document.querySelectorAll('.contract').forEach(function(section){"
            "var rows=Array.from(section.querySelectorAll('tbody tr')), pager=section.querySelector('.pager'),"
            "size=Number(pager.dataset.pageSize), page=0, label=pager.querySelector('span');"
            "function show(){rows.forEach(function(row,i){row.hidden=i<page*size||i>=(page+1)*size});"
            "label.textContent=(page+1)+' / '+Math.max(1,Math.ceil(rows.length/size))+' · 전체 '+rows.length+'건';"
            "pager.querySelector('.prev').disabled=page===0;pager.querySelector('.next').disabled=(page+1)*size>=rows.length}"
            "pager.querySelector('.prev').addEventListener('click',function(){page=Math.max(0,page-1);show()});"
            "pager.querySelector('.next').addEventListener('click',function(){page++;show()});show();"
            "section.querySelectorAll('.candidate-choice').forEach(function(select){select.addEventListener('change',function(){"
            "select.closest('tr').querySelectorAll('.candidate-panel').forEach(function(panel){panel.hidden=panel.dataset.candidate!==select.value})})})"
            "})})();</script>")
    return ("<!doctype html><html lang='ko'><head><meta charset='utf-8'>"
            "<meta name='viewport' content='width=device-width,initial-scale=1'><title>보험 명단 · 수입 글자 대조</title>"
            "<style>.content{max-width:1180px;margin:auto;padding:1rem}.notice,.error,.summary{padding:.8rem;border-radius:.5rem;background:var(--shell-paper)}"
            ".error{background:var(--shell-warn-bg,var(--shell-paper))}.filters{display:flex;gap:1rem;flex-wrap:wrap;margin:1rem 0}.filters label{display:grid;gap:.3rem;min-width:0;max-width:100%}.filters select{min-width:0;max-width:100%}"
            ".contract{margin:2rem 0}.table-wrap{overflow-x:auto}table{border-collapse:collapse;width:100%;min-width:760px}"
            "th,td{border:1px solid var(--shell-line);padding:.65rem;text-align:left;vertical-align:top;overflow-wrap:anywhere}"
            ".match-detail{margin:.3rem 0}.pager{display:flex;gap:.75rem;align-items:center;margin:.75rem 0}"
            "button,select{font:inherit;padding:.4rem;min-height:44px}button:focus-visible,select:focus-visible{outline:2px solid var(--shell-focus);outline-offset:2px}.state{font-weight:600}@media(max-width:640px){.content{padding:.65rem}}</style>"
            f"</head><body>{body}</body></html>")


def dispatch(handler, parsed, *, is_owner: bool, query=None, raw=None, csrf: str = "",
             state_loader=None) -> bool:
    if not owns_route(parsed.path):
        return False
    if not is_owner:
        handler._send_json({"code": "ACTION_FORBIDDEN", "message": "소유자만 볼 수 있습니다"}, 403)
        return True
    if raw is not None or str(getattr(handler, "command", "GET")).upper() != "GET":
        handler._send_json({"code": "METHOD_NOT_ALLOWED", "message": "조회만 할 수 있습니다"}, 405)
        return True
    query = query or {}
    if state_loader is None:
        from . import insurance_income_match_service
        state_loader = insurance_income_match_service.build_state
    try:
        state = state_loader(query=query)
    except Exception:
        state = {"available": False, "code": "SOURCE_UNAVAILABLE",
                 "message": "보험 명단 또는 수입 자료를 불러올 수 없습니다", "counts": {}, "contracts": []}
    if parsed.path == ROUTES[1]:
        handler._send_json(state, 200 if state.get("available") else 400 if state.get('code') == 'INVALID_FILTER' else 503)
    else:
        document = render_page(state, query=query)
        handler._send(document, 200 if state.get("available") else
                      400 if state.get('code') == 'INVALID_FILTER' else 503)
    return True
