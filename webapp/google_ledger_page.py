"""Owner-only page for the Google trip view. Read-only except the owner's copy choice.

Serves only when WEBLEDGER_GOOGLE_LEDGER_SNAPSHOT names a snapshot file. Non-owners get a
403 and never a partial page. The page shows totals, check codes and sync status; it never
loads the private rows file. Copy choices are stored in a separate JSON with history and are
never written to Google.
"""

from __future__ import annotations

import datetime as dt
import html
import json
import os
import functools
import threading
import copy
from collections import Counter
from pathlib import Path
from urllib.parse import quote

from app import google_access, google_authority

_SETTINGS_LOCK = threading.RLock()
# The planned scheduler runs hourly. Missing two runs must not look like current verification.
MAX_SNAPSHOT_AGE_SECONDS = 2 * 60 * 60


def snapshot_for_display(snapshot: dict, *, now=None) -> dict:
    data = copy.deepcopy(snapshot)
    current = now or dt.datetime.now(google_authority.KST)
    stale = False
    for source in data.get('sources', {}).values():
        try:
            stamp = dt.datetime.fromisoformat(source.get('last_ok_at') or '')
            age = (current - stamp).total_seconds()
            expired = not -60 <= age <= MAX_SNAPSHOT_AGE_SECONDS
        except (ValueError, TypeError):
            expired = True
        if expired or source.get('stale') or source.get('status') != 'ok':
            source['stale'] = True
            source['error_code'] = source.get('error_code') or 'SYNC_DELAYED'
            stale = True
    if stale:
        for trip in data.get('trips', []):
            trip.update(verified=False, income_total=None, expense_total=None, net=None, closure_current=False)
            trip['review'] = sorted(set(trip.get('review', [])) | {'SOURCE_STALE'})
    return data


def _serialized(function):
    @functools.wraps(function)
    def wrapped(*args, **kwargs):
        with _SETTINGS_LOCK:
            return function(*args, **kwargs)
    return wrapped

ROUTES = ("/google-ledger", "/api/google-ledger", "/api/google-ledger/choice", "/api/google-ledger/grants",
          "/api/google-ledger/mapping",
          "/google-ledger/rows", "/api/google-ledger/rows")
REVIEW_LABELS = {
    "TOTAL_MISMATCH": "Google 합계와 행 합계가 다름",
    "TOTAL_RANGE_MISMATCH": "합계 수식 범위가 데이터 행과 다름",
    "TOTAL_FORMULA_UNCLEAR": "합계 수식을 찾지 못함",
    "TOTAL_NOT_CACHED": "합계 값이 없음",
    "AMOUNT_INVALID": "금액이 숫자가 아님",
    "AMOUNT_MISSING": "날짜는 있으나 금액이 없음",
    "AMOUNT_NOT_CACHED": "금액 수식 값이 없음",
    "FORMULA_ERROR": "수식 오류",
    "LAYOUT_NOT_STANDARD": "구형 양식 (자동 변환하지 않음)",
    "DUPLICATE_IN_BOTH": "메인과 보관에 모두 있음 (확인 대상)",
    "DUPLICATE_IN_SOURCE": "같은 탭 이름이 두 번 있음",
    "POSSIBLE_DUPLICATE": "이름이 비슷한 탭이 있음 (합산하지 않음)",
    "ARCHIVE_ONLY": "보관 장부에만 있음 (마감)",
    "COPY_NAME": "사본 이름 탭",
    "SOURCE_STALE": "마지막 정상 동기화 값",
}


def enabled() -> bool:
    """Fails closed: both the snapshot and the private rows must be configured."""
    return bool(os.environ.get("WEBLEDGER_GOOGLE_LEDGER_SNAPSHOT") and os.environ.get("WEBLEDGER_GOOGLE_LEDGER_ROWS"))


def owns_route(path: str) -> bool:
    return path in ROUTES


def _snapshot_path() -> Path:
    return Path(os.environ["WEBLEDGER_GOOGLE_LEDGER_SNAPSHOT"])


def _rows_path() -> Path:
    return Path(os.environ["WEBLEDGER_GOOGLE_LEDGER_ROWS"])


def owner_rows(rows: dict, key: str, source: str) -> dict | None:
    """Every row of one trip tab from one source, as stored in the private rows file. Owner only."""
    if source not in ("main", "archive"):
        raise ValueError("SOURCE_INVALID")
    tab = rows.get(source, {}).get("trips", {}).get(key)
    if tab is None:
        return None
    def income(block):
        # 수입 B:H = 거래일자, 이름, 닉네임, 예약금, 잔금, 추가금, 금액
        return [{"row": r["row"], "date": r["cells"].get("B"), "name": r["cells"].get("C"),
                 "nickname": r["cells"].get("D"), "deposit": r["cells"].get("E"),
                 "balance": r["cells"].get("F"), "extra": r["cells"].get("G"), "amount": r["amount"]}
                for r in block]

    def expense(block):
        # 지출 B:H = 거래일자, 항목(지급처), 내용(분류), 기간, 예약번호, 증빙유형, 금액
        return [{"row": r["row"], "date": r["cells"].get("B"), "payee": r["cells"].get("C"),
                 "category": r["cells"].get("D"), "period": r["cells"].get("E"),
                 "reservation": r["cells"].get("F"), "evidence": r["cells"].get("G"), "amount": r["amount"]}
                for r in block]
    return {"key": key, "source": source, "income": income(tab.get("income", [])),
            "expense": expense(tab.get("expense", []))}


def render_rows_html(detail: dict) -> str:
    esc = lambda value: html.escape(str(value or ""))

    def income_table(rows):
        body = "".join(
            f"<tr><td>{r['row']}</td><td>{esc(r['date'])}</td><td>{esc(r['name'])}</td><td>{esc(r['nickname'])}</td>"
            f"<td>{esc(r['deposit'])}</td><td>{esc(r['balance'])}</td><td>{esc(r['extra'])}</td>"
                f"<td>{_money(r['amount'])}</td></tr>" for r in rows)
        return ("<table><thead><tr><th>행</th><th>거래일자</th><th>이름</th><th>닉네임</th><th>예약금</th>"
                f"<th>잔금</th><th>추가금</th><th>금액</th></tr></thead><tbody>{body}</tbody></table>")

    def expense_table(rows):
        body = "".join(
            f"<tr><td>{r['row']}</td><td>{esc(r['date'])}</td><td>{esc(r['payee'])}</td><td>{esc(r['category'])}</td>"
            f"<td>{esc(r['period'])}</td><td>{esc(r['reservation'])}</td><td>{esc(r['evidence'])}</td>"
                f"<td>{_money(r['amount'])}</td></tr>" for r in rows)
        return ("<table><thead><tr><th>행</th><th>거래일자</th><th>지급처</th><th>분류</th><th>기간</th>"
                f"<th>예약번호</th><th>증빙</th><th>금액</th></tr></thead><tbody>{body}</tbody></table>")
    def total(rows):
        return sum(r['amount'] for r in rows) if all(type(r.get('amount')) is int for r in rows) else None
    income, expense = total(detail['income']), total(detail['expense'])
    verification = '검증됨' if detail.get('verified') else '미검증 · 행 합계는 확정 금액이 아닙니다'
    return ("<!doctype html><html lang='ko'><head><meta charset='utf-8'>"
            "<meta name='viewport' content='width=device-width,initial-scale=1'><title>행 상세</title>"
            "<style>table{border-collapse:collapse;width:100%;font-size:14px}td,th{border:1px solid #ccc;padding:4px}"
            "@media(max-width:600px){table{display:block;overflow-x:auto}}</style></head><body>"
            f"<h1>{html.escape(detail['key'])} ({html.escape(detail['source'])})</h1>"
            f"<p>{verification}</p><p>동기화 기준 {html.escape(str(detail.get('synced_at') or '미확인'))}</p>"
            f"<h2>수입 행 합계 {_money(income)}</h2>{income_table(detail['income'])}"
            f"<h2>지출 행 합계 {_money(expense)}</h2>{expense_table(detail['expense'])}</body></html>")


def choice_path(snapshot_path: Path) -> Path:
    return snapshot_path.with_name("google-canonical-choices.json")


def _read_settings(path: Path, default: dict) -> dict:
    try:
        data = json.loads(path.read_text(encoding='utf-8'))
    except FileNotFoundError:
        return default
    except (OSError, ValueError):
        raise google_authority.SnapshotError('SETTINGS_UNAVAILABLE') from None
    if not isinstance(data, dict):
        raise google_authority.SnapshotError('SETTINGS_UNAVAILABLE')
    return data


def load_choices(snapshot_path: Path) -> dict:
    data = _read_settings(choice_path(snapshot_path), {'choices': {}, 'history': []})
    choices = data.get('choices')
    if (not isinstance(choices, dict) or not isinstance(data.get('history'), list)
            or any(not isinstance(key, str) or value not in ('main', 'archive') for key, value in choices.items())):
        raise google_authority.SnapshotError('SETTINGS_UNAVAILABLE')
    return data


@_serialized
def record_choice(snapshot_path: Path, *, key: str, source: str, at: str) -> dict:
    """Records the owner's copy for a trip that exists in both books, with history. Never touches Google."""
    if source not in ("main", "archive"):
        raise ValueError("CHOICE_SOURCE_INVALID")
    data = load_choices(snapshot_path)
    previous = data["choices"].get(key)
    if previous == source:
        return data
    data["choices"][key] = source
    data["history"].append({"key": key, "from": previous, "to": source, "at": at})
    tmp = choice_path(snapshot_path).with_suffix(".json.tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, choice_path(snapshot_path))
    return data


# A copy choice never lifts these. They say the figures may be stale or the trip identity is uncertain.
OWNER_CHOICE_BLOCKERS = {"SOURCE_STALE", "POSSIBLE_DUPLICATE", "DUPLICATE_IN_SOURCE", "COPY_NAME"}


def _trip_for_owner(trip: dict, choices: dict, sources: dict) -> dict:
    """Applies the owner's copy choice. A choice selects which copy's figures count; it never clears a block."""
    chosen = choices.get(trip["key"])
    copies = trip.get("copies") or {}
    if chosen and not copies.get(chosen):
        return {**trip, 'chosen_source': None, 'verified': False, 'income_total': None,
                'expense_total': None, 'net': None, 'blocked_by': ['CHOSEN_COPY_MISSING']}
    if copies.get('main') and copies.get('archive') and chosen not in ('main', 'archive'):
        return {**trip, 'chosen_source': None, 'verified': False, 'income_total': None,
                'expense_total': None, 'net': None, 'blocked_by': ['CHOICE_REQUIRED']}
    if not chosen:
        return {**trip, "chosen_source": trip["canonical_source"]}
    copy = copies[chosen]
    blockers = set(trip["review"]) & OWNER_CHOICE_BLOCKERS
    if any(src.get("status") != "ok" or src.get("stale") for src in sources.values()):
        blockers.add("SOURCE_NOT_CURRENT")
    if not trip.get("closure_current"):
        blockers.add("CLOSURE_NOT_CURRENT")
    if copy["layout"] != "rev" or not (copy["income"]["verified"] and copy["expense"]["verified"]):
        blockers.add("COPY_NOT_VERIFIED")
    if blockers:
        return {**trip, "chosen_source": chosen, "income_total": None, "expense_total": None, "net": None,
                "verified": False, "blocked_by": sorted(blockers)}
    income, expense = copy["income"]["total"], copy["expense"]["total"]
    return {**trip, "chosen_source": chosen, "income_total": income, "expense_total": expense,
            "net": income - expense, "verified": True, "blocked_by": []}


def owner_payload(snapshot: dict, choices: dict) -> dict:
    trips = [_trip_for_owner(t, choices.get("choices", {}), snapshot["sources"]) for t in snapshot["trips"]]
    return {"synced_at": snapshot.get("synced_at"),
            "sources": {role: {k: src.get(k) for k in ("status", "error_code", "stale", "last_ok_at", "checked_at")}
                        for role, src in snapshot["sources"].items()},
            "trips": trips}


def _money(value) -> str:
    return "미확인" if value is None else f"{value:,}원"


def render_html(payload: dict, *, is_owner: bool = True, csrf: str = '') -> str:
    rows = []
    for trip in payload["trips"]:
        reasons = " / ".join(REVIEW_LABELS.get(code, code) for code in trip["review"]) or "확인 사항 없음"
        copies = trip.get("copies") or {}
        links = " ".join(
            f"<a href='/google-ledger/rows?key={quote(trip['key'])}&amp;source={role}'>{role} 상세</a>"
            for role in ("main", "archive") if copies.get(role))
        chosen = trip.get('chosen_source')
        choice = ''
        if is_owner and ((copies.get('main') and copies.get('archive'))
                         or 'CHOSEN_COPY_MISSING' in trip.get('blocked_by', [])):
            choice = '<p>' + ('정본: ' + html.escape(chosen) if chosen else '정본 선택 필요') + '</p>'
            if csrf:
                choice += ''.join(
                    f"<button type='button' data-choice='{html.escape(trip['key'], quote=True)}' "
                    f"data-source='{role}'>{role} 정본 선택</button>" for role in ('main', 'archive') if copies.get(role))
        elif not is_owner:
            links = (f"<a href='/google-ledger/rows?key={quote(trip['key'])}&amp;source={chosen}'>여행 상세</a>"
                     if chosen in ('main', 'archive') else '정본 선택 필요')
        rows.append(
            "<tr>"
            f"<td data-label='여행'>{html.escape(trip['key'])}<br>{links}{choice}</td>"
            f"<td data-label='마감'>{'마감' if trip['closure'] == 'closed' else '미마감' if trip['closure'] == 'open' else '확인 중'}</td>"
            f"<td data-label='수입'>{_money(trip['income_total'])}</td><td data-label='지출'>{_money(trip['expense_total'])}</td>"
            f"<td data-label='순수익'>{_money(trip['net'])}</td>"
            f"<td data-label='검증'>{'검증됨' if trip['verified'] else '미검증'}</td>"
            f"<td data-label='확인 사항'>{html.escape(reasons)}</td></tr>")
    sources = "".join(
        f"<li>{html.escape(role)}: {html.escape(str(src.get('status')))}"
        f"{' · ' + html.escape(str(src['error_code'])) if src.get('error_code') else ''}"
        f"{' · 마지막 정상 ' + html.escape(str(src['last_ok_at'] or '없음')) if 'last_ok_at' in src else ''}</li>"
        for role, src in payload["sources"].items())
    return (
        "<!doctype html><html lang='ko'><head><meta charset='utf-8'>"
        "<meta name='viewport' content='width=device-width,initial-scale=1'>"
        "<title>Google 확정 장부</title>"
        "<style>*{box-sizing:border-box}body{font-family:sans-serif;margin:16px;color:#182230;background:#f7f9fc}"
        "h1{font-size:24px}table{border-collapse:collapse;width:100%;font-size:14px;background:white}"
        "td,th{border:1px solid #e4e7ec;padding:10px;text-align:left;overflow-wrap:anywhere}"
        "a{color:#166444}button{font:inherit;padding:8px;cursor:pointer}"
        ".work-back{display:inline-flex;align-items:center;min-height:44px;padding:8px 12px;"
        "border:1px solid #d0d5dd;border-radius:8px;text-decoration:none;background:white}"
        "@media(max-width:759px){table,tbody,tr,td{display:block;width:100%}"
        "table{background:transparent}thead{position:absolute;width:1px;height:1px;overflow:hidden;clip:rect(0,0,0,0)}"
        "tr{margin-bottom:12px;border:1px solid #e4e7ec;border-radius:8px;background:white;padding:8px}"
        "td{border:0;padding:6px;display:grid;grid-template-columns:64px minmax(0,1fr);gap:6px}"
        "td::before{content:attr(data-label);font-size:12px;color:#667085}"
        "td:first-child{display:block;font-weight:600}td:first-child::before{display:none}"
        "td:first-child a,button{display:inline-flex;align-items:center;min-height:44px;margin:4px 8px 0 0}"
        "td p{margin:4px 0}td br{display:none}td[colspan]{display:block}"
        "li{overflow-wrap:anywhere}h1{font-size:22px}}"
        "</style></head><body>"
        "<nav aria-label='장부 이동'><a class='work-back' href='/board'>장부로 돌아가기</a></nav>"
        "<h1>Google 확정 장부</h1>"
        "<p>Google에서 읽어 온 정본입니다. COST 카드·영수증의 복사만으로 이 금액이 바뀌지는 않습니다.</p>"
        f"<p>기준 시각 {html.escape(str(payload['synced_at'] or '동기화 대기'))}</p><ul>{sources}</ul>"
        "<table><thead><tr><th>여행</th><th>마감</th><th>수입</th><th>지출</th><th>순수익</th>"
        "<th>검증</th><th>확인 사항</th></tr></thead>"
        f"<tbody>{''.join(rows) or '<tr><td colspan=\"7\">볼 수 있는 여행이 없습니다.</td></tr>'}</tbody></table>"
        "<p id='choice-status' role='status'></p>"
        + ("<script>const token=" + json.dumps(csrf) + ";"
           "document.querySelectorAll('[data-choice]').forEach(b=>b.onclick=async()=>{"
           "if(!confirm(b.dataset.source+' 사본을 이 여행의 정본으로 선택할까요? Google 원본은 변경하지 않습니다.'))return;"
           "const buttons=document.querySelectorAll('[data-choice]');buttons.forEach(x=>x.disabled=true);"
           "try{const r=await fetch('/api/google-ledger/choice',{method:'POST',headers:{'Content-Type':'application/json',"
           "'X-CSRF-Token':token},body:JSON.stringify({key:b.dataset.choice,source:b.dataset.source})});"
           "const j=await r.json();if(!r.ok)throw new Error(j.message||j.code);location.reload()}"
           "catch(e){document.getElementById('choice-status').textContent=e.message;buttons.forEach(x=>x.disabled=false)}});"
           "</script>" if is_owner and csrf else '') + "</body></html>")


def _send_unavailable(handler, path: str, code: str, message: str) -> None:
    if path.startswith('/api/'):
        handler._send_json({'code': code, 'message': message}, 503)
        return
    handler._send(
        "<!doctype html><html lang='ko'><head><meta charset='utf-8'>"
        "<meta name='viewport' content='width=device-width,initial-scale=1'>"
        "<title>Google 장부 동기화 확인</title><style>"
        "body{font-family:system-ui,sans-serif;margin:16px;line-height:1.6;color:#182230}"
        "h1{font-size:22px}a{display:inline-flex;align-items:center;min-height:44px;"
        "padding:8px 12px;margin:8px 8px 0 0;border:1px solid #d0d5dd;border-radius:8px;color:#166444}"
        "</style></head><body><h1>Google 장부를 아직 표시할 수 없어요</h1>"
        f"<p role='alert'>{html.escape(message)}</p>"
        "<p>확인되지 않은 금액은 표시하지 않습니다. 동기화 또는 연결 설정을 확인한 뒤 다시 열어 주세요.</p>"
        "<a href='/google-ledger'>다시 확인</a><a href='/board'>장부로 돌아가기</a>"
        "</body></html>", 503)


def caller(enforced: bool, session, is_owner_of, role_of=None) -> tuple[bool, str | None]:
    """Fail closed. Owner needs enforcement on and a confirmed owner session.

    A viewer is the account the access store currently lists as an active viewer. A deactivated or
    removed account has no role there, so its grants stay inert until it is reactivated.
    """
    if not enforced or session is None:
        return False, None
    if is_owner_of(session):
        return True, session.user_id
    if role_of is not None and role_of(session.user_id) == "viewer":
        return False, session.user_id
    return False, None


def mapping_path(snapshot_path: Path) -> Path:
    return snapshot_path.with_name("google-tab-mapping.json")


def load_mapping(snapshot_path: Path) -> dict:
    data = _read_settings(mapping_path(snapshot_path), {})
    if any(not isinstance(key, str) or not isinstance(value, str) or not value for key, value in data.items()):
        raise google_authority.SnapshotError('SETTINGS_UNAVAILABLE')
    return data


@_serialized
def set_mapping(snapshot_path: Path, *, key: str, tab_id: str | None, known_keys: set,
                known_tab_ids: set | None = None) -> dict:
    """Owner-only link between a Google trip key and the COST tab it is. None removes the link."""
    if key not in known_keys:
        raise ValueError("GOOGLE_TRIP_UNKNOWN")
    data = load_mapping(snapshot_path)
    if tab_id:
        if known_tab_ids is not None and tab_id not in known_tab_ids:
            raise ValueError("COST_TAB_UNKNOWN")
        if any(other != key and linked == tab_id for other, linked in data.items()):
            raise ValueError("COST_TAB_ALREADY_MAPPED")
        data[key] = str(tab_id)
    else:
        data.pop(key, None)
    tmp = mapping_path(snapshot_path).with_suffix(".json.tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, mapping_path(snapshot_path))
    return data


def grants_path(snapshot_path: Path) -> Path:
    return snapshot_path.with_name("google-viewer-grants.json")


def load_grants(snapshot_path: Path) -> dict:
    data = _read_settings(grants_path(snapshot_path), {'grants': {}, 'history': []})
    grants = data.get('grants')
    if (not isinstance(grants, dict) or not isinstance(data.get('history'), list)
            or any(not isinstance(user, str) or not isinstance(keys, list)
                   or any(not isinstance(key, str) or not key for key in keys) for user, keys in grants.items())):
        raise google_authority.SnapshotError('SETTINGS_UNAVAILABLE')
    return data


@_serialized
def set_grants(snapshot_path: Path, *, user_id: str, keys: list, granted: bool, at: str) -> dict:
    """Owner-only grant or revoke of Google trip keys for one account. Default is no access."""
    if (not user_id or type(granted) is not bool or not isinstance(keys, list)
            or not all(isinstance(k, str) and k for k in keys)):
        raise ValueError("GRANT_INVALID")
    data = load_grants(snapshot_path)
    current = set(data["grants"].get(user_id, []))
    current = current | set(keys) if granted else current - set(keys)
    data["grants"][user_id] = sorted(current)
    data["history"].append({"user_id": user_id, "keys": sorted(keys), "granted": granted, "at": at})
    tmp = grants_path(snapshot_path).with_suffix(".json.tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, grants_path(snapshot_path))
    return data


def viewer_allowed_keys(grants: dict, user_id: str, mapping: dict | None, visible_tabs: set | None) -> set:
    """Google trip keys this account may read: owner grant AND a COST tab link AND that tab visible now."""
    granted = set(grants.get("grants", {}).get(user_id, []))
    tabs = visible_tabs or set()
    links = mapping or {}
    counts = Counter(value for value in links.values() if isinstance(value, str) and value)
    return {key for key in granted if isinstance(links.get(key), str)
            and links[key] in tabs and counts[links[key]] == 1}


def viewer_payload(snapshot: dict, grants: dict, user_id: str, *, mapping: dict | None = None,
                   visible_tabs: set | None = None, choices: dict | None = None) -> dict:
    """Trip-level figures for the trips this account may read. Never copies, never source detail.

    Owner grant AND link to a COST tab AND that tab visible to the account. Without the link, a grant
    alone shows nothing, because the owner's grant could not otherwise be tied to the COST access rules.
    """
    allowed = viewer_allowed_keys(grants, user_id, mapping, visible_tabs)
    resolved = owner_payload(snapshot, choices or {'choices': {}})['trips']
    trips = google_access.visible_trips(resolved, is_owner=False, allowed_keys=allowed)
    selected = {trip['key']: trip.get('chosen_source') for trip in resolved}
    for trip in trips:
        trip['chosen_source'] = selected[trip['key']]
    return {"synced_at": snapshot.get("synced_at"),
            "sources": {role: {"status": src.get("status")} for role, src in snapshot["sources"].items()},
            "trips": trips}


def dispatch(handler, parsed, *, is_owner: bool, viewer_user_id: str | None = None, raw=None, csrf: str = "",
             query=None, viewer_tabs=None) -> bool:
    if not owns_route(parsed.path) or not enabled():
        return False
    if not is_owner and not viewer_user_id:
        handler._send_json({"code": "LOGIN_REQUIRED", "message": "로그인한 계정만 볼 수 있습니다"}, 403)
        return True
    if parsed.path in ("/api/google-ledger/choice", "/api/google-ledger/grants", "/api/google-ledger/mapping") and raw is None:
        handler._send_json({"code": "METHOD_NOT_ALLOWED"}, 405)
        return True
    if parsed.path in ("/api/google-ledger/choice", "/api/google-ledger/grants", "/api/google-ledger/mapping"):
        if not is_owner:
            handler._send_json({"code": "OWNER_ONLY", "message": "소유자만 바꿀 수 있습니다"}, 403)
            return True
        if not csrf or handler.headers.get("X-CSRF-Token") != csrf:
            handler._send_json({"code": "CSRF_REQUIRED", "message": "화면을 새로 연 뒤 다시 시도해 주세요"}, 403)
            return True
        try:
            body = json.loads(raw.decode("utf-8") or "{}")
            if not isinstance(body, dict):
                raise ValueError('INVALID_VALUE')
        except (UnicodeDecodeError, ValueError):
            handler._send_json({"code": "INVALID_VALUE"}, 400)
            return True
        now = dt.datetime.now(google_authority.KST).isoformat()
        try:
            if parsed.path.endswith("/mapping"):
                snapshot, _ = google_authority.load_consistent(_snapshot_path(), _rows_path())
                known = {t["key"] for t in snapshot["trips"]}
                from .ledger_board import _active_store
                board = _active_store()
                tabs = {t['tab_id'] for t in board.list_trips()} if board else set()
                set_mapping(_snapshot_path(), key=str(body.get("key", "")),
                            tab_id=str(body.get("tab_id") or "") or None, known_keys=known,
                            known_tab_ids=tabs)
            elif parsed.path.endswith("/choice"):
                snapshot, _ = google_authority.load_consistent(_snapshot_path(), _rows_path())
                key, source = str(body.get('key', '')), str(body.get('source', ''))
                trip = next((trip for trip in snapshot['trips'] if trip['key'] == key), None)
                if trip is None:
                    raise ValueError('GOOGLE_TRIP_UNKNOWN')
                copies = trip.get('copies') or {}
                if source not in ('main', 'archive') or not copies.get(source):
                    raise ValueError('CHOICE_COPY_UNAVAILABLE')
                record_choice(_snapshot_path(), key=key, source=source, at=now)
            else:
                if body.get('granted') is True:
                    snapshot, _ = google_authority.load_consistent(_snapshot_path(), _rows_path())
                    known = {t['key'] for t in snapshot['trips']}
                    keys = body.get('keys')
                    if not isinstance(keys, list) or any(not isinstance(key, str) or key not in known for key in keys):
                        raise ValueError('GOOGLE_TRIP_UNKNOWN')
                set_grants(_snapshot_path(), user_id=str(body.get("user_id", "")), keys=body.get("keys"),
                           granted=body.get("granted"), at=now)
        except google_authority.SnapshotError:
            handler._send_json({'code': 'SNAPSHOT_UNAVAILABLE'}, 503)
            return True
        except ValueError as error:
            handler._send_json({"code": str(error)}, 400)
            return True
        handler._send_json({"code": "OK"})
        return True
    if not is_owner and not viewer_user_id:
        handler._send_json({"code": "LOGIN_REQUIRED", "message": "로그인한 계정만 볼 수 있습니다"}, 403)
        return True
    if parsed.path.endswith("/rows"):
        key = ((query or {}).get("key") or [""])[0]
        source = ((query or {}).get("source") or [""])[0]
        try:
            snapshot, rows = google_authority.load_consistent(_snapshot_path(), _rows_path())
            snapshot = snapshot_for_display(snapshot)
            trip = next((t for t in owner_payload(snapshot, load_choices(_snapshot_path()))['trips']
                         if t['key'] == key), {})
            if not is_owner:
                # Direct URLs must follow both the current grant and the
                # canonical source resolved for the list in this request.
                allowed = viewer_allowed_keys(load_grants(_snapshot_path()), viewer_user_id,
                                              load_mapping(_snapshot_path()), viewer_tabs)
                if key not in allowed or source != trip.get('chosen_source'):
                    handler._send_json({"code": "NOT_FOUND"}, 404)
                    return True
            detail = owner_rows(rows, key, source)
            if detail is not None:
                detail.update(verified=bool(trip.get('verified') and trip.get('chosen_source') == source),
                              synced_at=snapshot.get('synced_at'), review=trip.get('review', []))
        except (google_authority.SnapshotError, ValueError):
            handler._send_json({"code": "ROWS_UNAVAILABLE", "message": "행 자료를 확인하지 못했습니다"}, 503)
            return True
        if detail is None:
            handler._send_json({"code": "NOT_FOUND"}, 404)
        elif parsed.path == "/api/google-ledger/rows":
            handler._send_json(detail)
        else:
            handler._send(render_rows_html(detail))
        return True
    try:
        snapshot, _ = google_authority.load_consistent(_snapshot_path(), _rows_path())
    except google_authority.SnapshotError as error:
        _send_unavailable(handler, parsed.path, error.code, '동기화 결과를 확인하지 못했습니다')
        return True
    snapshot = snapshot_for_display(snapshot)
    try:
        if is_owner:
            payload = owner_payload(snapshot, load_choices(_snapshot_path()))
        else:
            payload = viewer_payload(snapshot, load_grants(_snapshot_path()), viewer_user_id,
                                     mapping=load_mapping(_snapshot_path()), visible_tabs=viewer_tabs,
                                     choices=load_choices(_snapshot_path()))
    except google_authority.SnapshotError as error:
        _send_unavailable(handler, parsed.path, error.code, '권한 또는 정본 설정 파일을 확인해 주세요')
        return True
    if parsed.path == "/api/google-ledger":
        handler._send_json(payload)
    else:
        handler._send(render_html(payload, is_owner=is_owner, csrf=csrf if is_owner else ''))
    return True
