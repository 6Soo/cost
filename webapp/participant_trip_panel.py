"""Owner-only participant and income-link projection embedded in a trip ledger."""

from __future__ import annotations

import html
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
    rows = list(state.get("income_rows") or [])
    people = [person for person in (state.get("roster") or {}).get("participants") or []
              if person.get("active", True) and person.get("state") == "confirmed"]
    if needle:
        rows = [row for row in rows if needle in str(row.get("name") or "").casefold()
                or needle in str(row.get("nickname") or "").casefold()]
        people = [person for person in people
                  if needle in str(person.get("display_name") or "").casefold()
                  or needle in str(person.get("nickname") or "").casefold()]
    shown_rows, rows_more = _slice(rows, income_offset)
    income_rows_page, _ = _slice(rows, income_offset)
    shown_people, people_more = _slice(people, participant_offset)
    links_by_ref = {}
    for person in state.get("participants") or []:
        for link in person.get("links") or []:
            links_by_ref.setdefault(link["income_ref"], []).append(
                {"participant_id": person["participant_id"],
                 "name": person.get("display_name") or "", "method": link.get("method")})
    return {"rows": shown_rows, "rows_more": rows_more,
            "participants": shown_people, "participants_more": people_more,
            "income_rows_page": income_rows_page,
            "links_by_ref": links_by_ref, "row_count": len(rows),
            "participant_count": len(people), "search": search,
            "income_offset": income_offset, "participant_offset": participant_offset}


def render(state: dict, *, csrf: str = "", income_offset: int = 0,
           participant_offset: int = 0, search: str = "") -> str:
    """Render names only after the caller has established owner access."""
    if not state.get("configured"):
        return "<section class='participant-trip-panel'><h2>보험가입내역</h2><p>참가 저장소를 확인할 수 없습니다.</p></section>"
    data = project(state, income_offset=income_offset,
                   participant_offset=participant_offset, search=search)
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
            label = " · ".join(_esc(item["name"]) + (" (직접 연결)" if item.get("method") == "manual" else " (이름 대조)") for item in connected)
            state_label = f"✓ {len(connected)}명 연결 · {label}"
        elif not google.get("available"):
            state_label = "확인 필요 · 수입 자료 최신성 확인"
        else:
            state_label = "미연결 · 보험 미가입을 뜻하지 않음"
        actions = "".join(
            f"<form method='post' action='/api/participants/unlink'>"
            f"<input type='hidden' name='csrf' value='{_esc(csrf)}'>"
            f"<input type='hidden' name='trip' value='{_esc(state.get('trip_id'))}'>"
            f"<input type='hidden' name='input_fingerprint' value='{_esc(state.get('input_fingerprint'))}'>"
            f"<input type='hidden' name='participant_id' value='{_esc(item['participant_id'])}'>"
            f"<input type='hidden' name='income_ref' value='{_esc(row['ref'])}'>"
            f"<button type='submit'>{_esc(item['name'])} 연결 해제</button></form>"
            for item in connected)
        rows.append(f"<template class='participant-income-status' data-income-ref='{_esc(row['ref'])}'>"
                    f"<span>{state_label}</span>{actions}</template>")
    people = []
    for person in data["participants"]:
        person_id = person.get("participant_id") or ""
        linked = any(person_id == link["participant_id"]
                     for links in links_by_ref.values() for link in links)
        name = _esc(person.get("display_name"))
        people.append(
            f"<li draggable='true' data-participant='{_esc(person_id)}'"
            f"data-name='{name}'><span class='drag-handle' aria-hidden='true'>⠿</span>"
            f"<strong>{name}</strong><span>{'수입 연결됨' if linked else '수입 미연결'}</span>"
            "</li>")
    if not people:
        people.append("<li>확정 참가자가 없거나 명단을 확인할 수 없습니다.</li>")
    fingerprint = _esc(state.get("input_fingerprint"))
    trip = _esc(state.get("trip_id"))
    selector_options = "".join(
        f"<option value='{_esc(person.get('participant_id'))}'>"
        f"{_esc(person.get('display_name'))}</option>"
        for person in data["participants"])
    search_form = (
        "<form method='get' action='/board' class='participant-trip-search'>"
        f"<input type='hidden' name='tab' value='{trip}'>"
        f"<label>이름 검색 <input type='search' name='participant_q' value='{_esc(search)}' maxlength='80'></label>"
        "<button>검색</button></form>")
    def page_url(**overrides):
        query = {"tab": state.get("trip_id"), "participant_q": search,
                 "participant_income_offset": income_offset,
                 "participant_offset": participant_offset}
        query.update(overrides)
        return _esc("/board?" + urlencode(query))
    row_more = (f"<a class='btn' href='{page_url(participant_income_offset=income_offset + 20)}'>수입 다음 20건</a>"
                if data["rows_more"] else "")
    person_more = (f"<a class='btn' href='{page_url(participant_offset=participant_offset + 20)}'>참가자 다음 20명</a>"
                   if data["participants_more"] else "")
    return (
        "<details class='participant-trip-panel' id='participant-trip-panel' aria-label='보험가입내역'>"
        "<summary>보험가입내역 · 확정 참가자·수입 연결</summary><div class='participant-trip-content'>"
        "<h2>보험가입내역</h2>"
        f"<p>{_esc(status)} · 참가 확정 {counts.get('roster_confirmed', 0)}명 · "
        f"수입 연결 {counts.get('linked', 0)}명 · 미연결 수입 {counts.get('unlinked_income_rows', 0)}건</p>"
        f"{search_form}{''.join(rows)}{row_more}"
        "<p role='status' class='participant-write-status'></p>"
        "<h3>확정 참가자 · 수입 연결</h3>"
        f"<ul class='participant-cards' aria-describedby='participant-link-help'>{''.join(people)}</ul>"
        f"{person_more}<p id='participant-link-help'>보험 참가자 카드를 수입 표의 보험 등록 열로 끌어놓을 수 있습니다. 연결을 시작하려면 수입 행의 연결 버튼을 사용해 주세요.</p>"
        f"<form method='post' action='/api/participants/link' class='participant-keyboard-link' data-link-confirm hidden>"
        f"<input type='hidden' name='csrf' value='{_esc(csrf)}'><input type='hidden' name='trip' value='{trip}'>"
        f"<input type='hidden' name='input_fingerprint' value='{fingerprint}'>"
        "<label>수입 행 <select name='income_ref'>" + "".join(
            _income_option(row) for row in data["income_rows_page"]) + "</select></label>"
        f"<label>보험 참가자 <select name='participant_id'>{selector_options}</select></label>"
        "<button type='submit'>선택한 참가자 연결</button></form>"
        "<dialog id='participant-link-confirm' aria-labelledby='participant-link-confirm-text'>"
        "<form method='dialog'><p id='participant-link-confirm-text'></p>"
        "<button value='cancel'>취소</button><button value='confirm'>연결 확인</button>"
        "</form></dialog></div></details>")


def shell(*, trip_id: str) -> str:
    """Closed placeholder contains no participant names or reconciliation data."""
    return ("<details class='participant-trip-panel' id='participant-trip-panel' "
            f"data-trip='{_esc(trip_id)}' aria-label='보험가입내역'>"
            "<summary>보험가입내역 · 참가자 연결 보기</summary>"
            "<div class='participant-trip-content' data-participant-content>"
            "<p role='status'>참가자 정보를 불러오는 중입니다.</p></div></details>")


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
