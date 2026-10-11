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
from collections import Counter
from pathlib import Path
from urllib.parse import quote

from app import google_access, google_authority

_SETTINGS_LOCK = threading.RLock()


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
            f"<td>{r['amount']:,}원</td></tr>" for r in rows)
        return ("<table><thead><tr><th>행</th><th>거래일자</th><th>이름</th><th>닉네임</th><th>예약금</th>"
                f"<th>잔금</th><th>추가금</th><th>금액</th></tr></thead><tbody>{body}</tbody></table>")

    def expense_table(rows):
        body = "".join(
            f"<tr><td>{r['row']}</td><td>{esc(r['date'])}</td><td>{esc(r['payee'])}</td><td>{esc(r['category'])}</td>"
            f"<td>{esc(r['period'])}</td><td>{esc(r['reservation'])}</td><td>{esc(r['evidence'])}</td>"
            f"<td>{r['amount']:,}원</td></tr>" for r in rows)
        return ("<table><thead><tr><th>행</th><th>거래일자</th><th>지급처</th><th>분류</th><th>기간</th>"
                f"<th>예약번호</th><th>증빙</th><th>금액</th></tr></thead><tbody>{body}</tbody></table>")
    income = sum(r["amount"] for r in detail["income"])
    expense = sum(r["amount"] for r in detail["expense"])
    return ("<!doctype html><html lang='ko'><head><meta charset='utf-8'>"
            "<meta name='viewport' content='width=device-width,initial-scale=1'><title>행 상세</title>"
            "<style>table{border-collapse:collapse;width:100%;font-size:14px}td,th{border:1px solid #ccc;padding:4px}"
            "@media(max-width:600px){table{display:block;overflow-x:auto}}</style></head><body>"
            f"<h1>{html.escape(detail['key'])} ({html.escape(detail['source'])})</h1>"
            f"<h2>수입 {income:,}원</h2>{income_table(detail['income'])}"
            f"<h2>지출 {expense:,}원</h2>{expense_table(detail['expense'])}</body></html>")


def choice_path(snapshot_path: Path) -> Path:
    return snapshot_path.with_name("google-canonical-choices.json")


def load_choices(snapshot_path: Path) -> dict:
    path = choice_path(snapshot_path)
    if not path.exists():
        return {"choices": {}, "history": []}
    return json.loads(path.read_text(encoding="utf-8"))


@_serialized
def record_choice(snapshot_path: Path, *, key: str, source: str, at: str) -> dict:
    """Records the owner's copy for a trip that exists in both books, with history. Never touches Google."""
    if source not in ("main", "archive"):
        raise ValueError("CHOICE_SOURCE_INVALID")
    data = load_choices(snapshot_path)
    previous = data["choices"].get(key)
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
    if not chosen or not (copies.get("main") and copies.get("archive")) or chosen not in copies:
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


def render_html(payload: dict) -> str:
    rows = []
    for trip in payload["trips"]:
        reasons = " / ".join(REVIEW_LABELS.get(code, code) for code in trip["review"]) or "확인 사항 없음"
        copies = trip.get("copies") or {}
        links = " ".join(
            f"<a href='/google-ledger/rows?key={quote(trip['key'])}&amp;source={role}'>{role} 상세</a>"
            for role in ("main", "archive") if copies.get(role))
        rows.append(
            "<tr>"
            f"<td>{html.escape(trip['key'])}<br>{links}</td>"
            f"<td>{'마감' if trip['closure'] == 'closed' else '미마감' if trip['closure'] == 'open' else '확인 중'}</td>"
            f"<td>{_money(trip['income_total'])}</td><td>{_money(trip['expense_total'])}</td>"
            f"<td>{_money(trip['net'])}</td>"
            f"<td>{'검증됨' if trip['verified'] else '미검증'}</td>"
            f"<td>{html.escape(reasons)}</td></tr>")
    sources = "".join(
        f"<li>{html.escape(role)}: {html.escape(str(src.get('status')))}"
        f"{' · ' + html.escape(str(src['error_code'])) if src.get('error_code') else ''}"
        f"{' · 마지막 정상 ' + html.escape(str(src['last_ok_at'] or '없음')) if 'last_ok_at' in src else ''}</li>"
        for role, src in payload["sources"].items())
    return (
        "<!doctype html><html lang='ko'><head><meta charset='utf-8'>"
        "<meta name='viewport' content='width=device-width,initial-scale=1'>"
        "<title>Google 확정 장부 (owner)</title>"
        "<style>body{font-family:sans-serif;margin:12px}table{border-collapse:collapse;width:100%;font-size:14px}"
        "td,th{border:1px solid #ccc;padding:4px;text-align:left}@media(max-width:600px){table{display:block;overflow-x:auto}}"
        "</style></head><body>"
        "<h1>Google 확정 장부</h1>"
        f"<p>기준 시각 {html.escape(str(payload['synced_at']))}</p><ul>{sources}</ul>"
        "<table><thead><tr><th>여행</th><th>마감</th><th>수입</th><th>지출</th><th>순수익</th>"
        "<th>검증</th><th>확인 사항</th></tr></thead>"
        f"<tbody>{''.join(rows)}</tbody></table></body></html>")


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
    path = mapping_path(snapshot_path)
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


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
    path = grants_path(snapshot_path)
    if not path.exists():
        return {"grants": {}, "history": []}
    return json.loads(path.read_text(encoding="utf-8"))


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
                   visible_tabs: set | None = None) -> dict:
    """Trip-level figures for the trips this account may read. Never copies, never source detail.

    Owner grant AND link to a COST tab AND that tab visible to the account. Without the link, a grant
    alone shows nothing, because the owner's grant could not otherwise be tied to the COST access rules.
    """
    allowed = viewer_allowed_keys(grants, user_id, mapping, visible_tabs)
    trips = google_access.visible_trips(snapshot["trips"], is_owner=False, allowed_keys=allowed)
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
                record_choice(_snapshot_path(), key=str(body.get("key", "")), source=str(body.get("source", "")), at=now)
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
            if not is_owner:
                # A viewer reads the detail of an allowed trip only, under the same rule as the list.
                allowed = viewer_allowed_keys(load_grants(_snapshot_path()), viewer_user_id,
                                              load_mapping(_snapshot_path()), viewer_tabs)
                if key not in allowed:
                    handler._send_json({"code": "NOT_FOUND"}, 404)
                    return True
            detail = owner_rows(rows, key, source)
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
        handler._send_json({"code": error.code, "message": "동기화 결과를 확인하지 못했습니다"}, 503)
        return True
    if is_owner:
        payload = owner_payload(snapshot, load_choices(_snapshot_path()))
    else:
        payload = viewer_payload(snapshot, load_grants(_snapshot_path()), viewer_user_id,
                                 mapping=load_mapping(_snapshot_path()), visible_tabs=viewer_tabs)
    if parsed.path == "/api/google-ledger":
        handler._send_json(payload)
    else:
        handler._send(render_html(payload))
    return True
