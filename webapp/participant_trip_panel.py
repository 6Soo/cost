"""Owner-only participant and income-link projection embedded in a trip ledger."""

from __future__ import annotations

import html
import os
from urllib.parse import urlencode


def _esc(value) -> str:
    return html.escape("" if value is None else str(value), quote=True)


def _slice(items, offset: int, limit: int = 20):
    page = list(items or [])[offset:offset + limit]
    more = offset + limit < len(items or [])
    return page, more


def project(state: dict, *, income_offset: int = 0, participant_offset: int = 0,
            search: str = "") -> dict:
    """Build a bounded view without changing the reconciler's source state."""
    needle = search.strip().casefold()
    from . import google_ledger_page as google
    def display_row(row):
        return dict(row, date=row.get('date') or (row.get('cells') or {}).get('B'))
    rows = sorted([row for row in state.get('income_rows') or []
                   if not google.is_unconfirmed_income_row(display_row(row))],
                  key=lambda row: google.transaction_date_sort_key(display_row(row)))
    people = [person for person in (state.get("roster") or {}).get("participants") or []
              if person.get("active", True) and person.get("state") == "confirmed"]
    linked_ids = {person['participant_id'] for person in state.get('participants') or []
                  if person.get('links')}
    people = [person for person in people if person.get('participant_id') not in linked_ids]
    unlinked_count = len(people)
    if needle:
        rows = [row for row in rows if needle in str(row.get("name") or "").casefold()
                or needle in str(row.get("nickname") or "").casefold()]
        people = [person for person in people
                  if needle in str(person.get("display_name") or "").casefold()
                  or needle in str(person.get("nickname") or "").casefold()]
    # Keep the complete income list visible for reconciliation. Participant cards
    # remain paginated independently.
    shown_rows = rows
    rows_more = False
    income_rows_page = rows
    participant_offset = min(max(0, participant_offset), max(0, (len(people) - 1) // 20 * 20))
    shown_people, people_more = _slice(people, participant_offset)
    links_by_ref = {}
    for person in state.get("participants") or []:
        for link in person.get("links") or []:
            links_by_ref.setdefault(link["income_ref"], []).append(
                {"participant_id": person["participant_id"],
                 "name": person.get("display_name") or "", "method": link.get("method")})
    return {"rows": shown_rows, "rows_more": rows_more,
            "participants": shown_people, "participants_more": people_more,
            "selectable_participants": people, "unlinked_participant_count": unlinked_count,
            "income_rows_page": income_rows_page,
            "links_by_ref": links_by_ref, "row_count": len(rows),
            "participant_count": len(people), "search": search,
            "income_offset": income_offset, "participant_offset": participant_offset}


def _review_markup(state, data):
    """Masked text evidence is displayed without creating confirmed people."""
    from .google_ledger_page import is_refunded_income
    review = state.get('insurance_review') or {}
    if state.get('configured') and not review.get('available'):
        return ''
    by_ref = {}
    evidence_by_ref = {}
    truncated = False
    for contract in review.get('contracts') or []:
        for row in contract.get('rows') or []:
            truncated = truncated or row.get('candidate_count', 0) > len(row.get('matches') or [])
            for match in row.get('matches') or []:
                by_ref.setdefault(match.get('ref'), []).append(row)
                evidence_by_ref.setdefault(match.get('ref'), []).append((contract, row, match))
    counts = review.get('counts') or {}
    if state.get('configured') and not counts.get('contracts'):
        return ''
    if review.get('available'):
        notice = (f"일정·연결 기준 명단 {int(counts.get('rows', 0))}건 · "
                  f"글자 일치 {int(counts.get('matched', 0))}건 · "
                  f"후보 확인 {int(counts.get('ambiguous', 0))}건")
    else:
        notice = review.get('message') or '보험 명단 자료 연결을 확인해 주세요.'
    templates, evidence = [], []
    for income in data['income_rows_page']:
        if is_refunded_income(income):
            continue
        ref = income['ref']
        if data['links_by_ref'].get(ref):
            continue  # Explicit confirmed participant links always win.
        hits = by_ref.get(ref, [])
        if not review.get('available') or counts.get('source_unavailable'):
            label = '보험·수입 자료 확인 필요'
        elif not counts.get('contracts'):
            label = '해당 여행 명단 확인 필요'
        elif len(hits) == 1 and hits[0].get('match_state') == 'matched':
            label = '글자 일치 · ' + str(hits[0].get('masked_name') or '')
        elif hits:
            label = f"보험 명단 후보 {len(hits)}건"
        elif truncated:
            label = '후보 목록 확인 필요'
        else:
            label = '글자 일치 없음'
        generation = (state.get('google') or {}).get('generation') or ''
        status_html = f"<span class='insurance-review-status'>{_esc(label)}</span>"
        if hits:
            evidence_id = f'insurance-evidence-{len(evidence)}'
            status_html = (f"<button type='button' class='insurance-review-status insurance-candidate-button' "
                           f"data-insurance-evidence='{evidence_id}' aria-haspopup='dialog'>{_esc(label)}"
                           "</button>")
            cards = []
            for contract, row, match in evidence_by_ref.get(ref, []):
                reason = ('보이는 글자가 수입 이름·닉네임과 일치합니다.'
                          if row.get('match_state') == 'matched' else
                          '여러 기록에 글자가 맞아 한 사람으로 정할 수 없습니다.')
                if row.get('mask_length_unknown'):
                    reason += ' 가림 기호의 글자 수는 확인되지 않았습니다.'
                cards.append("<li><strong>" + _esc(row.get('masked_name') or '가림 이름 없음')
                             + "</strong><p>보험 기간 " + _esc(contract.get('travel_start'))
                             + ' – ' + _esc(contract.get('travel_end')) + '</p><p>'
                             + _esc(reason) + '</p></li>')
            income_label = _esc(income.get('name') or income.get('nickname') or '이름 미기재')
            amount = income.get('amount')
            amount_label = f'{amount:,}원' if isinstance(amount, int) else '금액 미기재'
            evidence.append(f"<template id='{evidence_id}'>"
                            f"<p class='insurance-selected-income'><strong>{income_label}</strong> · "
                            f"{_esc((income.get('cells') or {}).get('B'))} · {_esc(amount_label)}</p>"
                            f"<ul class='insurance-candidate-list'>{''.join(cards)}</ul>"
                            "<p>보험 원문과 수입 기록을 비교해 주세요. 가림 이름의 글자 일치만으로 "
                            "참가자 연결이나 가입 완료를 확정하지 않습니다.</p>"
                            f"<a class='btn' href='/participants/insurance-match?{_esc(urlencode({'trip': state.get('trip_id') or ''}))}'>"
                            "이 여행 수입으로 전체 보험 명단 대조하기</a></template>")
        templates.append(f"<template class='participant-income-status' data-income-ref='{_esc(ref)}' "
                         f"data-google-generation='{_esc(generation)}'>"
                         f"{status_html}</template>")
    contracts = ''.join(
        "<li><span>" + _esc(contract.get('travel_start')) + '–' + _esc(contract.get('travel_end'))
        + "</span><span>" + ('가입 완료·기간 종료 이력' if contract.get('insurance_status') == 'completed_or_expired'
                             else '가입 상태 확인 필요') + '</span></li>'
        for contract in review.get('contracts') or [])
    return ("<div class='insurance-review-summary'><p>" + _esc(notice) + '</p>'
            + ("<ul class='insurance-review-contracts'>" + contracts + '</ul>' if contracts else '') + '</div>'
            + ''.join(templates) + ''.join(evidence)
            + "<dialog class='insurance-candidate-dialog' id='insurance-candidate-dialog' aria-labelledby='insurance-candidate-title'>"
              "<header><h2 id='insurance-candidate-title'>보험 명단 후보 비교</h2>"
              "<button type='button' class='btn' data-insurance-close autofocus aria-label='후보 비교 닫기'>닫기</button></header>"
              "<div data-insurance-evidence-content></div></dialog>")


def render(state: dict, *, csrf: str = "", income_offset: int = 0,
           participant_offset: int = 0, search: str = "") -> str:
    """Render names only after the caller has established owner access."""
    from .google_ledger_page import is_refunded_income
    match_href = '/participants/insurance-match?' + urlencode({'trip': state.get('trip_id') or ''})
    match_link = f"<p><a class='btn' href='{_esc(match_href)}'>보험 명단 상세</a></p>"
    data = project(state, income_offset=income_offset,
                   participant_offset=participant_offset, search=search)
    participant_offset = data['participant_offset']
    review_html = _review_markup(state, data)
    if not state.get("configured"):
        return ("<details class='participant-trip-panel' id='participant-trip-panel'>"
                "<summary>보험가입내역</summary><div class='participant-trip-content'>"
                + review_html + match_link
                + "<p class='participant-review-note'>가림 이름의 글자 대조 결과입니다. 참가자 확정·입금 수령을 확인한 결과는 아닙니다.</p>"
                + '</div></details>')
    google = state.get("google") or {}
    roster = state.get("roster") or {}
    counts = state.get("counts") or {}
    status = ("보험가입 확정 명단" if roster.get("scope") == "complete"
              else "부분 명단 · 전체 인원은 확정하지 않음")
    if not google.get("available"):
        status += " · Google 수입 자료 확인 필요"
    links_by_ref = data["links_by_ref"]
    rows = []
    for row in data["rows"]:
        connected = links_by_ref.get(row["ref"], [])
        if connected:
            labels = {'manual': '직접 연결', 'masked_name_match': '자동 · 앞뒤 글자 일치'}
            label = " · ".join(_esc(item["name"]) + ' (' + labels.get(item.get('method'), '이름 대조') + ')' for item in connected)
            state_label = f"✓ {len(connected)}명 연결 · {label}"
        elif not google.get("available"):
            state_label = "확인 필요 · 수입 자료 최신성 확인"
        else:
            state_label = "미연결"
        actions = "".join(
            f"<form method='post' action='/api/participants/unlink'>"
            f"<input type='hidden' name='csrf' value='{_esc(csrf)}'>"
            f"<input type='hidden' name='trip' value='{_esc(state.get('trip_id'))}'>"
            f"<input type='hidden' name='input_fingerprint' value='{_esc(state.get('input_fingerprint'))}'>"
            f"<input type='hidden' name='participant_id' value='{_esc(item['participant_id'])}'>"
            f"<input type='hidden' name='income_ref' value='{_esc(row['ref'])}'>"
            f"<button type='submit'>{_esc(item['name'])} 연결 해제</button></form>"
            for item in connected)
        if is_refunded_income(row):
            status_markup = "<span class='participant-link-status'>환불완료</span>"
        elif connected:
            names = ' · '.join(_esc(item['name']) for item in connected)
            status_markup = (
                "<details class='participant-link-details'>"
                f"<summary><span>✓ {len(connected)}명 연결 · {names}</span></summary>"
                f"<div class='participant-link-actions'><p>{label}</p>{actions}</div></details>")
        else:
            status_markup = f"<span class='participant-link-status'>{state_label}</span>"
        rows.append(f"<template class='participant-income-status' data-income-ref='{_esc(row['ref'])}'>"
                    f"{status_markup}</template>")
    people = []
    for person in data["participants"]:
        person_id = person.get("participant_id") or ""
        name = _esc(person.get("display_name"))
        disabled = '' if google.get('available') and data['income_rows_page'] else ' disabled'
        people.append(
            f"<li draggable='true' data-participant='{_esc(person_id)}'"
            f"data-name='{name}'><span class='drag-handle' aria-hidden='true'>⠿</span>"
            f"<button type='button' class='participant-select' data-select-participant='{_esc(person_id)}'{disabled}>{name}</button>"
            "</li>")
    if not people:
        empty = ('검색 결과가 없습니다.' if search else
                 '모든 참가자가 수입에 연결되어 있습니다.' if data['unlinked_participant_count'] == 0
                 and counts.get('roster_confirmed', 0) else '연결할 참가자가 없습니다. 보험 명단을 확인해 주세요.')
        people.append(f"<li class='participant-empty'>{empty}</li>")
    fingerprint = _esc(state.get("input_fingerprint"))
    trip = _esc(state.get("trip_id"))
    selector_options = "".join(
        f"<option value='{_esc(person.get('participant_id'))}'>"
        f"{_esc(person.get('display_name'))}</option>"
        for person in data["selectable_participants"])
    search_form = (
        "<form method='get' action='/board#participant-trip-panel' class='participant-trip-search'>"
        f"<input type='hidden' name='tab' value='{trip}'>"
        f"<label>이름 검색 <input type='search' name='participant_q' value='{_esc(search)}' maxlength='80' placeholder='이름 또는 닉네임'></label>"
        "<button type='submit'>검색</button>"
        + (f"<a class='btn' href='/board?{_esc(urlencode({'tab':state.get('trip_id') or ''}))}#participant-trip-panel'>초기화</a>" if search else '')
        + "</form>")
    def page_url(**overrides):
        query = {"tab": state.get("trip_id"), "participant_q": search,
                 "participant_offset": participant_offset}
        query.update(overrides)
        return _esc("/board?" + urlencode(query) + '#participant-trip-panel')
    paging = (f"<a class='btn' href='{page_url(participant_offset=max(0, participant_offset - 20))}'>이전 참가자</a>" if participant_offset else '')
    if data['participants_more']:
        paging += f"<a class='btn' href='{page_url(participant_offset=participant_offset + 20)}'>다음 참가자</a>"
    linking_available = bool(selector_options and data['income_rows_page'] and google.get('available'))
    link_form = (
        "<form method='post' action='/api/participants/link' class='participant-keyboard-link' data-link-confirm>"
        f"<input type='hidden' name='csrf' value='{_esc(csrf)}'><input type='hidden' name='trip' value='{trip}'>"
        f"<input type='hidden' name='input_fingerprint' value='{fingerprint}'>"
        "<label>보험 참가자 <select name='participant_id' required><option value=''>참가자 선택</option>"
        f"{selector_options}</select></label>"
        "<label>연결할 수입 <select name='income_ref' required><option value=''>수입 선택</option>"
        + "".join(_income_option(row) for row in data['income_rows_page']) + "</select></label>"
        "<button type='submit'>수입에 연결</button></form>" if linking_available else '')
    return (
        "<details class='participant-trip-panel' id='participant-trip-panel' aria-label='보험가입내역'>"
        "<summary>보험가입내역</summary><div class='participant-trip-content'>"
        "<dl class='participant-metrics'>"
        f"<div><dt>참가 확정</dt><dd>{int(counts.get('roster_confirmed', 0))}명</dd></div>"
        f"<div><dt>수입 연결</dt><dd>{int(counts.get('linked', 0))}명</dd></div>"
        f"<div><dt>연결할 참가자</dt><dd>{data['unlinked_participant_count']}명</dd></div></dl>"
        + (f"<p class='participant-review-note'>{_esc(status)}</p>" if roster.get('scope') != 'complete' or not google.get('available') else '')
        + "<div class='participant-toolbar'>" + search_form
        + "<div class='participant-source-links'>"
        f"<a class='btn' href='{_esc(match_href)}'>보험 명단 상세</a>"
        f"<a class='btn' href='/participants?{_esc(urlencode({'trip':state.get('trip_id') or ''}))}'>전체 연결 관리</a></div></div>"
        f"{''.join(rows)}{review_html}"
        "<h3>수입 미연결 참가자</h3>"
        f"<ul class='participant-cards' aria-describedby='participant-link-help'>{''.join(people)}</ul>"
        f"<nav class='participant-paging' aria-label='미연결 참가자 목록'>{paging}</nav>"
        + ("<p id='participant-link-help' class='participant-review-note'>참가자와 수입을 아래에서 선택해 연결하세요. 참가자 이름을 누르거나 수입 표의 보험 열로 끌어놓을 수도 있습니다.</p>" if linking_available else "<p id='participant-link-help' class='participant-review-note'></p>")
        + f"{link_form}<p role='status' class='participant-write-status' aria-live='polite'></p>"
        "<dialog id='participant-link-confirm' aria-labelledby='participant-link-confirm-text'>"
        "<form method='dialog'><p id='participant-link-confirm-text'></p>"
        "<button value='cancel'>취소</button><button value='confirm'>연결 확인</button>"
        "</form></dialog></div></details>")


def shell(*, trip_id: str) -> str:
    """Closed placeholder contains no participant names or reconciliation data."""
    from . import participant_income_page
    auto = participant_income_page.store_path().is_file() or bool(
        os.environ.get('WEBLEDGER_INSURANCE_REVIEW_MANIFEST') or
        os.environ.get('WEBLEDGER_PARTICIPANT_SYNC_CONFIG'))
    return ("<details class='participant-trip-panel' id='participant-trip-panel' "
            f"data-trip='{_esc(trip_id)}' data-auto-load='{int(auto)}' aria-busy='false' aria-label='보험가입내역'>"
            "<summary>보험가입내역</summary>"
            "<div class='participant-trip-content' data-participant-content>"
            "<div class='insurance-loading' role='status'><span class='insurance-loading-dot' aria-hidden='true'></span>"
            "<div><strong>보험 명단 대조 준비</strong><p>명단을 열면 이 여행의 수입 이름과 비교합니다.</p></div></div>"
            "</div></details>")


def _income_option(row: dict) -> str:
    amount = f"{int(row['amount']):,}원" if isinstance(row.get("amount"), int) else "공란"
    return (f"<option value='{_esc(row.get('ref'))}'>"
            f"{_esc(row.get('name') or row.get('nickname') or '이름 미확인')} · "
            f"{_esc((row.get('cells') or {}).get('B'))} · {_esc(amount)}</option>")


def controls_from_query(query: dict) -> dict:
    def offset(key):
        try:
            value = int((query.get(key) or ["0"])[0])
        except (TypeError, ValueError):
            value = 0
        return min(max(value, 0), 100000)
    return {"income_offset": offset("participant_income_offset"),
            "participant_offset": offset("participant_offset"),
            "search": str((query.get("participant_q") or [""])[0])[:80]}


def attach_row_refs(rows: list[dict], *, source: str, sheet: str) -> list[dict]:
    """Add canonical read identity to display rows (never mutate Google source)."""
    from app.participant_income import income_ref
    return [dict(row, participant_income_ref=income_ref(source, sheet, row.get("row")))
            for row in rows]
