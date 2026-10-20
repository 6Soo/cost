"""관리자 전용 참가자·수입 대조 화면.

이 화면은 실명·참가 표시·원본 경로를 담는다. 소유자만 볼 수 있고, 일반 열람자·
공개 데모·기존 장부 API·XLSX에는 이 화면의 내용을 넣지 않는다. Google의 수입 행과
금액은 읽기만 하고 바꾸지 않는다.

모든 쓰기는 화면 지문을 반드시 요구한다. 지문이 없거나 현재 입력과 다르면 저장하지
않고, 참가자의 현재 여행·현재 정본에 실제로 있는 수입 행인지 확인한 뒤 한
트랜잭션으로 결정과 이력을 함께 남긴다.
"""

from __future__ import annotations

import html
import json
from pathlib import Path

from app import google_authority
from app import participant_income as income
from app import participant_roster as roster
from . import google_ledger_page

ROUTES = ("/participants", "/api/participants/state", "/api/participants/link",
          "/api/participants/unlink", "/api/participants/participant")
WRITE_ROUTES = ("/api/participants/link", "/api/participants/unlink",
                "/api/participants/participant")

STATE_LABELS = {
    income.STATE_NAME_MATCH: "참가 확정 · 이름 일치",
    income.STATE_INCOME_PRESENT: "참가 확정 · 수입 명단 있음 · 입금액 미기재",
    income.STATE_NO_INCOME: "참가 확정 · 수입 명단 없음",
    income.STATE_NEEDS_CHECK: "참가 확정 · 연결 확인 필요",
    income.STATE_MANUAL: "참가 확정 · 수동 연결",
    income.STATE_JOINT: "참가 확정 · 공동 입금 · 개인별 금액 미확정",
    income.STATE_UNVERIFIED: "참가 확정 · 확인 대기",
    income.STATE_NOT_IN_ROSTER: "명단에서 확인 안 됨",
    income.STATE_REVIEWED: "명단에서 확인 안 됨 · 검토 완료",
}

BLOCKING_LABELS = {
    "ROSTER_INCOMPLETE": "전체 명단 미수신",
    "TRANSCRIPTION_PENDING": "판독 대기 항목 있음",
    "CONNECTION_PENDING": "연결 확인 대상 있음",
    "INCOME_UNCLASSIFIED": "명단과 미연결 수입 있음",
    "INPUT_CHANGED": "Google 수입 확인 대기",
    "CORRECTION_PENDING": "이름 정정 확인 필요",
    "DUPLICATE_UNRESOLVED": "같은 이름 참가자 확인 필요",
}

#: 참가자 근거 설명. 내부 상태 문자열을 그대로 보여 주지 않는다.
PARTICIPANT_EVIDENCE = {
    "confirmed": "명단으로 참가 확정",
    "correction_pending": "이름이 바뀌어 정정 확인 필요",
    "merged": "같은 사람으로 확인되어 다른 참가자에 합쳐짐",
}

#: 이름 인덱스를 못 읽는 이유.
INDEX_BLOCKERS = {
    "CHOSEN_COPY_MISSING": "선택한 장부 사본을 찾지 못함",
    "CHOICE_REQUIRED": "사용할 장부 사본을 선택해야 함",
    "COPY_NOT_VERIFIED": "선택한 장부 사본이 검증되지 않음",
    "SOURCE_NOT_CURRENT": "Google 동기화가 최신이 아님",
    "CLOSURE_NOT_CURRENT": "여행 마감 상태가 최신이 아님",
    "INCOME_INDEX_UNAVAILABLE": "이름 인덱스를 쓸 수 없음",
    "TRIP_NOT_LINKED": "여행이 Google 장부와 연결되지 않음",
}


def owns_route(path: str) -> bool:
    return path in ROUTES


def store_path() -> Path:
    return roster.default_db_path()


def open_store(*, readonly: bool = False):
    """참가 저장소. 없으면 준비되지 않은 상태로 남는다.

    읽기 경로는 스키마를 만들지 않는다. 준비된 저장소를 읽기만 한다.
    """
    path = store_path()
    if not path.exists():
        return None
    if readonly:
        store = roster.ParticipantStore.open_readonly(path)
    else:
        store = roster.ParticipantStore.open(path)
        income.ensure_decision_schema(store.conn)
    return store


def google_context(trip_id: str) -> dict:
    """이 여행의 선택된 Google 정본과 이름 인덱스. 읽을 수 없으면 빈 상태로 둔다."""
    context = {"key": "", "source": "", "index": None, "synced_at": "", "generation": "",
               "stale": False, "rows_total": None, "sheet_total": None, "available": False,
               "verified": False, "blocked_by": [], "amount_rows": []}
    if not google_ledger_page.enabled():
        context["blocked_by"] = ["INCOME_INDEX_UNAVAILABLE"]
        return context
    try:
        path = google_ledger_page.snapshot_path()
        mapping = google_ledger_page.load_mapping(path)
        keys = [key for key, tab_id in mapping.items() if tab_id == trip_id]
        if len(keys) != 1:
            context["blocked_by"] = ["TRIP_NOT_LINKED"]
            return context
        key = keys[0]
        snapshot, rows = google_authority.load_consistent(path, google_ledger_page.rows_path())
        display = google_ledger_page.snapshot_for_display(snapshot)
        # 정본 선택은 기존 소유자 계약을 그대로 쓴다. 사본이 하나뿐인 여행도 연결된다.
        payload = google_ledger_page.owner_payload(display, google_ledger_page.load_choices(path))
        trip = next((item for item in payload["trips"] if item["key"] == key), None)
        if trip is None:
            context["blocked_by"] = ["TRIP_NOT_LINKED"]
            return context
        source = trip.get("chosen_source")
        blocked = list(trip.get("blocked_by") or [])
        if source not in ("main", "archive"):
            context["blocked_by"] = blocked or ["INCOME_INDEX_UNAVAILABLE"]
            return context
        index = google_ledger_page.owner_income_names(rows, key, source)
        detail = google_ledger_page.owner_rows(rows, key, source)
        amount_rows = list((detail or {}).get("income") or [])
        rows_total = None
        if detail is not None:
            amounts = [row.get("amount") for row in amount_rows]
            rows_total = sum(int(value) for value in amounts if isinstance(value, int))
        source_record = (display.get("sources") or {}).get(source) or {}
        stale = bool(source_record.get("stale")) or source_record.get("status") != "ok"
        available = bool(index and index.get("available")) and not stale
        if not available and not blocked:
            blocked = ["INCOME_INDEX_UNAVAILABLE"]
        context.update({
            "key": key, "source": source, "index": index,
            "synced_at": snapshot.get("synced_at"), "generation": snapshot.get("rows_generation"),
            "stale": stale, "rows_total": rows_total, "sheet_total": trip.get("income_total"),
            "available": available, "verified": bool(trip.get("verified")),
            "blocked_by": blocked, "amount_rows": amount_rows,
        })
    except (google_authority.SnapshotError, ValueError, OSError):
        context["blocked_by"] = ["INCOME_INDEX_UNAVAILABLE"]
        return context
    return context


def build_state(trip_id: str, *, store=None) -> dict:
    """한 여행의 참가·수입 대조 상태."""
    opened = store is None
    handle = store if store is not None else open_store(readonly=True)
    if handle is None:
        return {"trip_id": trip_id, "configured": False, "participants": [], "unlinked_income": [],
                "counts": {}, "completion": {"complete": False, "blocked_by": ["STORE_UNAVAILABLE"]},
                "input_fingerprint": "", "google": google_context(trip_id), "roster": {},
                "income_rows": [], "decisions": []}
    try:
        people = handle.participants(trip_id)
        batches = [batch for batch in handle.batches() if batch["trip_id"] == trip_id]
        pending = sum(len(batch["result"].get("pending_items") or []) for batch in batches)
        scope = ""
        complete = False
        if batches:
            scope = batches[-1]["scope"]
            complete = scope == "complete" and not pending
        context = google_context(trip_id)
        index = context.get("index") or {}
        rows = income.income_rows_from_trip(index=index, amount_rows=context.get("amount_rows") or [],
                                            source=context.get("source") or "main",
                                            sheet=context.get("key") or "")
        decisions = income.decisions_for_trip(handle.conn, trip_id)
        roster_version = income.roster_version_of(people, pending_items=pending, scope=scope)
        result = income.reconcile(
            trip_id=trip_id, participants=people, income_rows=rows,
            index_available=bool(context.get("available")), decisions=decisions,
            roster_version=roster_version, google_generation=context.get("generation") or "",
            roster_complete=complete, transcription_pending=pending)
        return {"trip_id": trip_id, "configured": True, "participants": result["participants"],
                "unlinked_income": result["unlinked_income"], "counts": result["counts"],
                "completion": result["completion"], "input_fingerprint": result["input_fingerprint"],
                "roster_version": result["roster_version"], "rule_version": result["rule_version"],
                "google": context, "income_rows": rows, "decisions": decisions,
                "roster_total_declared": result.get("roster_total_declared", False),
                "roster": {"batches": batches, "scope": scope, "pending": pending,
                           "participants": people}}
    finally:
        if opened and handle is not None:
            handle.close()


def _money(value) -> str:
    if value is None:
        return ""
    return f"{int(value):,}원"


def _amount_cell(value) -> str:
    """공란과 0원을 구분해 보여 준다. 0원은 0원으로 남는다."""
    if value is None or value == "":
        return "공란"
    if isinstance(value, bool):
        return html.escape(str(value))
    if isinstance(value, (int, float)):
        return f"{int(value):,}원"
    text = str(value).strip()
    return html.escape(text) if text else "공란"


def _trip_options(current: str) -> list[tuple[str, str]]:
    """연결 수정 후보 여행. 실제 여행과 Google 연결을 함께 확인한다."""
    mapped = google_mapped_trips()
    try:
        from .ledger_board import _active_store
        board = _active_store()
        if board is None:
            return []
        options = []
        for trip in board.list_trips(include_archived=True):
            tab_id = trip.get("tab_id")
            if not tab_id or trip.get("deleted"):
                continue
            if mapped and tab_id not in mapped:
                continue
            options.append((tab_id, trip.get("display_key") or trip.get("tab_id") or ""))
        return options
    except Exception:
        return []


def google_mapped_trips() -> set:
    """Google 장부와 연결된 여행 id."""
    if not google_ledger_page.enabled():
        return set()
    try:
        mapping = google_ledger_page.load_mapping(google_ledger_page.snapshot_path())
    except Exception:
        return set()
    return {tab_id for tab_id in mapping.values() if tab_id}


def render_page(state: dict, *, csrf: str = "") -> str:
    """참가 대조표. 이름만 있는 참가자는 날짜·금액이 비어 있다."""
    esc = lambda value: html.escape("" if value is None else str(value))
    counts = state.get("counts") or {}
    google = state.get("google") or {}
    completion = state.get("completion") or {}
    blocked = " / ".join(BLOCKING_LABELS.get(code, code) for code in completion.get("blocked_by") or [])
    index_note = " / ".join(INDEX_BLOCKERS.get(code, code) for code in google.get("blocked_by") or [])
    scope = (state.get("roster") or {}).get("scope")
    total_note = ("전체 명단 수신 · 인원 확정 가능" if state.get("roster_total_declared")
                  else "부분 명단 · 전체 인원을 확정하지 않음")
    summary = (
        f"<p class='small'>명단으로 참가 확정 {counts.get('roster_confirmed', 0)}명 · {esc(total_note)} · "
        f"수입 연결 인원 {counts.get('linked', 0)}명 · "
        f"이름만 있는 인원 {counts.get('name_only', 0)}명 · "
        f"연결 확인 대상 {counts.get('needs_check', 0)}명 · "
        f"명단과 미연결 수입 행 {counts.get('unlinked_income_rows', 0)}건 · "
        f"검토 완료 수입 행 {counts.get('reviewed_income_rows', 0)}건 · "
        f"마지막 Google 확인 {esc(google.get('synced_at') or '확인 대기')}</p>")
    status = ("참가·수입 대조 완료" if completion.get("complete")
              else f"참가·수입 대조 진행 중 · {esc(blocked)}")
    if index_note:
        status = f"{status} · Google 수입 {esc(index_note)}"

    def hidden():
        return (f"<input type='hidden' name='csrf' value='{esc(csrf)}'>"
                f"<input type='hidden' name='trip' value='{esc(state.get('trip_id'))}'>"
                f"<input type='hidden' name='input_fingerprint' value='{esc(state.get('input_fingerprint'))}'>")

    income_options = "".join(
        f"<option value='{esc(row['ref'])}'>수입 {esc(row.get('row'))}행 · "
        f"{esc(row.get('name') or '이름 미확인')} · "
        f"{_amount_cell(row.get('amount'))}</option>" for row in state.get("income_rows") or [])
    people = state.get("participants") or []
    trip_options = _trip_options(state.get("trip_id") or "")

    rows = []
    for entry in people:
        label = STATE_LABELS.get(entry["state"], entry["state"])
        links = entry.get("links") or []
        detail = []
        for link in links:
            row = link["row"]
            cells = row.get("cells") or {}
            total = row.get("amount")
            detail.append(
                f"<div class='small'>수입 {esc(row.get('row'))}행"
                f"{(' · ' + esc(cells.get('B'))) if cells.get('B') else ''} · "
                f"{esc(row.get('name') or '')} · 예약금 {_amount_cell(cells.get('E'))}"
                f" · 잔금 {_amount_cell(cells.get('F'))} · 추가금 {_amount_cell(cells.get('G'))} · "
                f"총액 {_amount_cell(total)}"
                f"<form method='post' action='/api/participants/unlink'>"
                f"{hidden()}<input type='hidden' name='participant_id' value='{esc(entry['participant_id'])}'>"
                f"<input type='hidden' name='income_ref' value='{esc(link['income_ref'])}'>"
                f"<button type='submit'>해제</button></form></div>")
        for ref in entry.get("candidate_refs") or []:
            if any(link["income_ref"] == ref for link in links):
                continue
            detail.append(
                f"<form method='post' action='/api/participants/link' class='small'>"
                f"{hidden()}<input type='hidden' name='participant_id' value='{esc(entry['participant_id'])}'>"
                f"<input type='hidden' name='income_ref' value='{esc(ref)}'>"
                f"<button type='submit'>수입 {esc(ref.split('|')[-1])}행 연결</button></form>")
        # 이름이 다른 대리입금·공동입금도 여기서 직접 고를 수 있다.
        detail.append(
            f"<form method='post' action='/api/participants/link' class='small'>"
            f"{hidden()}<input type='hidden' name='participant_id' value='{esc(entry['participant_id'])}'>"
            f"<select name='income_ref'>{income_options}</select>"
            f"<label><input type='checkbox' name='joint' value='1'> 공동 입금</label>"
            f"<button type='submit'>선택한 수입 행 연결</button></form>")
        others = [item for item in people if item["participant_id"] != entry["participant_id"]]
        if others:
            same_options = "".join(
                f"<option value='{esc(item['participant_id'])}'>{esc(item['display_name'])}</option>"
                for item in others)
            detail.append(
                f"<form method='post' action='/api/participants/participant' class='small'>"
                f"{hidden()}<input type='hidden' name='action' value='same_person'>"
                f"<input type='hidden' name='participant_id' value='{esc(entry['participant_id'])}'>"
                f"<select name='other_participant_id'>{same_options}</select>"
                f"<button type='submit'>같은 사람으로 확인</button></form>")
            # 동명이인일 수 있다. 서로 다른 사람이라고 확인하면 인원이 확정된다.
            same_name = [item for item in others
                         if income.normalize_name(item["display_name"])
                         == income.normalize_name(entry["display_name"])]
            if same_name:
                separate_options = "".join(
                    f"<option value='{esc(item['participant_id'])}'>{esc(item['display_name'])}</option>"
                    for item in same_name)
                detail.append(
                    f"<form method='post' action='/api/participants/participant' class='small'>"
                    f"{hidden()}<input type='hidden' name='action' value='separate'>"
                    f"<input type='hidden' name='participant_id' value='{esc(entry['participant_id'])}'>"
                    f"<select name='other_participant_id'>{separate_options}</select>"
                    f"<button type='submit'>서로 다른 사람으로 확인</button></form>")
        if trip_options:
            remap = ("<select name='target_trip'>" + "".join(
                f"<option value='{esc(tab)}'{' selected' if tab == state.get('trip_id') else ''}>"
                f"{esc(label)}</option>" for tab, label in trip_options) + "</select>")
            detail.append(
                f"<form method='post' action='/api/participants/participant' class='small'>"
                f"{hidden()}<input type='hidden' name='action' value='remap'>"
                f"<input type='hidden' name='participant_id' value='{esc(entry['participant_id'])}'>"
                f"{remap}<input name='reason' placeholder='사유'>"
                f"<button type='submit'>여행 연결 수정</button></form>")
        detail.append(
            f"<form method='post' action='/api/participants/participant' class='small'>"
            f"{hidden()}<input type='hidden' name='action' value='rename'>"
            f"<input type='hidden' name='participant_id' value='{esc(entry['participant_id'])}'>"
            f"<input name='name' value='{esc(entry['display_name'])}' placeholder='이름 정정'>"
            f"<input name='reason' placeholder='사유'>"
            f"<button type='submit'>이름 정정</button></form>"
            f"<form method='post' action='/api/participants/participant' class='small'>"
            f"{hidden()}<input type='hidden' name='action' value='alias'>"
            f"<input type='hidden' name='participant_id' value='{esc(entry['participant_id'])}'>"
            f"<input name='alias' value='{esc(entry.get('nickname') or '')}' placeholder='확인된 별칭'>"
            f"<button type='submit'>별칭 확인</button></form>")
        evidence = PARTICIPANT_EVIDENCE.get(entry.get("participant_state") or "confirmed",
                                            "명단 확인")
        rows.append(
            f"<tr><td>{esc(entry['display_name'])}"
            f"{(' · ' + esc(entry['nickname'])) if entry.get('nickname') else ''}</td>"
            f"<td>참가 확정</td><td>{esc(label)}</td>"
            f"<td>{''.join(detail)}</td>"
            f"<td>{esc(evidence)}</td></tr>")

    unlinked = []
    for row in state.get("unlinked_income") or []:
        cells = row.get("cells") or {}
        label = STATE_LABELS.get(row.get("state") or income.STATE_NOT_IN_ROSTER, "")
        review = (f"<form method='post' action='/api/participants/link' class='small'>{hidden()}"
                  f"<input type='hidden' name='decision' value='reviewed'>"
                  f"<input type='hidden' name='income_ref' value='{esc(row['ref'])}'>"
                  f"<input name='reason' placeholder='검토 사유'>"
                  f"<button type='submit'>검토 완료로 표시</button></form>"
                  if row.get("state") == income.STATE_NOT_IN_ROSTER else
                  esc(row.get("review_reason") or ""))
        unlinked.append(
            f"<tr><td>{esc(row.get('name'))}</td><td>{esc(row.get('nickname'))}</td>"
            f"<td>{esc(label)}</td>"
            f"<td>{_amount_cell(cells.get('E'))} / {_amount_cell(cells.get('F'))} / {_amount_cell(cells.get('G'))}</td>"
            f"<td>{_amount_cell(row.get('amount'))}</td>"
            f"<td>{esc(row.get('ref'))}</td><td>{review}</td></tr>")

    table = ("<table><caption>참가자 대조</caption><thead><tr><th>이름/닉네임</th><th>참가 상태</th>"
             "<th>수입 연결 상태</th><th>원본 수입 행·사용자 결정</th><th>참가 근거</th></tr></thead>"
             f"<tbody>{''.join(rows) or '<tr><td colspan=\"5\">등록된 참가자가 없습니다.</td></tr>'}"
             "</tbody></table>")
    other = ("<table><caption>명단에서 확인 안 됨</caption><thead><tr><th>이름</th><th>닉네임</th>"
             "<th>상태</th><th>예약금/잔금/추가금</th><th>총액</th><th>원본</th><th>검토</th></tr></thead>"
             f"<tbody>{''.join(unlinked) or '<tr><td colspan=\"7\">없음</td></tr>'}</tbody></table>")
    total = _money(google.get("rows_total")) if google.get("rows_total") is not None else "확인 안 됨"
    total_note = ""
    if google.get("rows_total") is not None and not google.get("verified"):
        total_note = " · Google 합계가 검증되지 않아 확정 입금액이 아닙니다"
    footer = (f"<p class='small'>Google 수입 행 합계 {total} · 합계는 Google 회계 합계이며 "
              f"명단에서 만든 금액이 아닙니다{esc(total_note)}.</p>")
    body = (f"<div class='body'><h1>참가자·수입 대조</h1><p>{status}</p>{summary}{footer}"
            f"{table}{other}</div>")
    return ("<!doctype html><html lang='ko'><head><meta charset='utf-8'>"
            "<meta name='viewport' content='width=device-width,initial-scale=1'>"
            "<title>참가자·수입 대조</title></head>" + body + "</html>")


def _payload(raw, content_type: str = "") -> dict:
    if raw is None:
        return {}
    text = raw.decode("utf-8", "replace")
    if "application/json" in (content_type or ""):
        try:
            body = json.loads(text or "{}")
        except ValueError:
            return {}
        return body if isinstance(body, dict) else {}
    from urllib.parse import parse_qs
    try:
        form = parse_qs(text, keep_blank_values=True)
    except ValueError:
        return {}
    return {key: (value[0] if isinstance(value, list) else value) for key, value in form.items()}


def _csrf_ok(handler, payload: dict, csrf: str) -> bool:
    token = payload.get("csrf") or handler.headers.get("X-CSRF-Token") or ""
    return bool(csrf) and token == csrf


def dispatch(handler, parsed, *, is_owner: bool, raw=None, csrf: str = "", query=None,
             content_type: str = "") -> bool:
    """참가 대조 경로. 소유자만 처리한다."""
    if not owns_route(parsed.path):
        return False
    if not is_owner:
        handler._send_json({"code": "ACTION_FORBIDDEN", "message": "소유자만 볼 수 있습니다"}, 403)
        return True
    query = query or {}
    if parsed.path in WRITE_ROUTES:
        payload = _payload(raw, content_type)
        trip_id = str(payload.get("trip") or query.get("trip", [""])[0] or "")
        if not _csrf_ok(handler, payload, csrf):
            handler._send_json({"code": "CSRF_REQUIRED",
                                "message": "화면을 새로 연 뒤 다시 시도해 주세요"}, 403)
            return True
        store = open_store()
        if store is None:
            handler._send_json({"code": "STORE_UNAVAILABLE",
                                "message": "참가 저장소가 준비되지 않았어요"}, 503)
            return True
        try:
            result = _write(store, parsed.path, trip_id, payload)
        except income.ReconciliationError as exc:
            status = 409 if exc.code == "STALE_RECONCILIATION" else 422
            handler._send_json({"code": exc.code, "message": exc.message}, status)
            return True
        except roster.RosterError as exc:
            handler._send_json({"code": exc.code, "message": exc.message}, 422)
            return True
        finally:
            store.close()
        handler._send_json({"code": "OK", "result": result})
        return True

    trip_id = str(query.get("trip", [""])[0] or "")
    state = build_state(trip_id)
    if parsed.path == "/api/participants/state":
        handler._send_json(state)
        return True
    handler._send(render_page(state, csrf=csrf))
    return True


def _require_fingerprint(presented: str, current: str) -> None:
    if not presented:
        raise income.ReconciliationError("INVALID_VALUE", "화면 지문이 필요해요")
    if not current:
        raise income.ReconciliationError("INVALID_VALUE", "대조 상태를 읽지 못했어요")
    if presented != current:
        raise income.ReconciliationError("STALE_RECONCILIATION", "화면이 오래됐어요. 다시 확인해 주세요")


def _participant_in_trip(state: dict, participant_id: str) -> dict:
    for entry in state.get("participants") or []:
        if entry["participant_id"] == participant_id:
            return entry
    raise income.ReconciliationError("PARTICIPANT_NOT_FOUND", "이 여행의 참가자가 아니에요")


def _write(store, path: str, trip_id: str, payload: dict) -> dict:
    """사용자 결정. Google 원문과 금액은 건드리지 않는다."""
    action = str(payload.get("action") or "")
    participant_id = str(payload.get("participant_id") or "")
    income_ref = str(payload.get("income_ref") or "")
    reason = str(payload.get("reason") or "")
    presented = str(payload.get("input_fingerprint") or "")
    with store.transaction():
        state = build_state(trip_id, store=store)
        current = state.get("input_fingerprint") or ""
        _require_fingerprint(presented, current)
        if path == "/api/participants/participant":
            _participant_in_trip(state, participant_id)
            if action == "rename":
                return roster.correct_participant_name(store, participant_id,
                                                       str(payload.get("name") or ""),
                                                       reason=reason, decided_by="owner")
            if action == "remap":
                target = str(payload.get("target_trip") or "")
                _require_trip(target)
                return roster.remap_participant_trip(store, participant_id, target,
                                                     reason=reason, decided_by="owner")
            if action == "alias":
                return roster.add_participant_alias(store, participant_id,
                                                     str(payload.get("alias") or ""),
                                                     decided_by="owner")
            if action == "same_person":
                other = str(payload.get("other_participant_id") or "")
                _participant_in_trip(state, other)
                return roster.confirm_same_person(store, participant_id, other,
                                                  decided_by="owner")
            if action == "separate":
                other = str(payload.get("other_participant_id") or "")
                _participant_in_trip(state, other)
                return income.save_decision(
                    store.conn, participant_id=participant_id,
                    income_ref=f"{income.PARTICIPANT_PAIR_PREFIX}{other}",
                    decision=income.DECISION_SEPARATE, trip_id=trip_id,
                    link_method="separate", reason=reason, decided_by="owner",
                    presented_fingerprint=presented, current_fingerprint=current,
                    expected_revision=_decision_revision(
                        state, participant_id,
                        f"{income.PARTICIPANT_PAIR_PREFIX}{other}"))
            raise income.ReconciliationError("INVALID_VALUE", "알 수 없는 동작이에요")

        decision = str(payload.get("decision") or "")
        if not decision:
            decision = income.DECISION_LINKED if path.endswith("/link") else income.DECISION_UNLINKED
        if decision not in (income.DECISION_LINKED, income.DECISION_UNLINKED, income.DECISION_REVIEWED):
            raise income.ReconciliationError("INVALID_VALUE", "결정 값이 맞지 않아요")
        fingerprint = ""
        for row in state.get("income_rows") or []:
            if row["ref"] == income_ref:
                fingerprint = row["fingerprint"]
        if not fingerprint:
            # 현재 정본에 실제로 있는 수입 행이어야 한다.
            raise income.ReconciliationError("INCOME_ROW_UNKNOWN", "현재 장부에 없는 수입 행이에요")
        if decision == income.DECISION_REVIEWED:
            participant_id = ""
        else:
            _participant_in_trip(state, participant_id)
        expected = _decision_revision(state, participant_id, income_ref)
        result = income.save_decision(store.conn, participant_id=participant_id, income_ref=income_ref,
                                      decision=decision, trip_id=trip_id,
                                      link_method="manual" if decision != income.DECISION_REVIEWED
                                      else "review",
                                      joint=bool(payload.get("joint")), reason=reason,
                                      income_fingerprint=fingerprint, decided_by="owner",
                                      presented_fingerprint=presented, current_fingerprint=current,
                                      expected_revision=expected)
        # 결정이 반영된 실제 대조 상태를 한 번 더 계산해 이력으로 남긴다.
        # 명단 범위가 아니라 실제 명단 버전과 Google 세대를 함께 기록한다.
        latest = build_state(trip_id, store=store)
        income.record_run(store.conn, trip_id=trip_id,
                          roster_version=latest.get("roster_version") or "",
                          google_generation=(latest.get("google") or {}).get("generation") or "",
                          result=latest)
        return result


def _decision_revision(state: dict, participant_id: str, income_ref: str) -> int | None:
    for decision in state.get("decisions") or []:
        if decision.get("income_ref") == income_ref and decision.get("participant_id") == participant_id:
            return int(decision.get("revision") or 0)
    return None


def _require_trip(trip_id: str) -> None:
    """연결 수정 대상이 실제로 있고 Google과 연결된 여행인지 확인한다."""
    if not trip_id:
        raise income.ReconciliationError("TRIP_UNKNOWN", "여행이 필요해요")
    try:
        from .ledger_board import _active_store
        board = _active_store()
    except Exception:
        board = None
    if board is None:
        raise income.ReconciliationError("STORE_UNBOUND", "여행 목록을 읽을 수 없어요")
    found = False
    for trip in board.list_trips(include_archived=True):
        if trip.get("tab_id") == trip_id and not trip.get("deleted"):
            found = True
            break
    if not found:
        raise income.ReconciliationError("TRIP_UNKNOWN", "그런 여행이 없어요")
    mapped = google_mapped_trips()
    if mapped and trip_id not in mapped:
        raise income.ReconciliationError("TRIP_UNKNOWN", "Google 장부와 연결되지 않은 여행이에요")
