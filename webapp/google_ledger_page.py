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
from pathlib import Path

from app import google_authority

ROUTES = ("/google-ledger", "/api/google-ledger", "/api/google-ledger/choice")
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
    return bool(os.environ.get("WEBLEDGER_GOOGLE_LEDGER_SNAPSHOT"))


def owns_route(path: str) -> bool:
    return path in ROUTES


def _snapshot_path() -> Path:
    return Path(os.environ["WEBLEDGER_GOOGLE_LEDGER_SNAPSHOT"])


def choice_path(snapshot_path: Path) -> Path:
    return snapshot_path.with_name("google-canonical-choices.json")


def load_choices(snapshot_path: Path) -> dict:
    path = choice_path(snapshot_path)
    if not path.exists():
        return {"choices": {}, "history": []}
    return json.loads(path.read_text(encoding="utf-8"))


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


def _trip_for_owner(trip: dict, choices: dict) -> dict:
    """Applies the owner's copy choice only where both books hold the trip."""
    chosen = choices.get(trip["key"])
    copies = trip.get("copies") or {}
    if chosen and copies.get("main") and copies.get("archive") and chosen in copies:
        copy = copies[chosen]
        verified = copy["layout"] == "rev" and copy["income"]["verified"] and copy["expense"]["verified"]
        if verified:
            income, expense = copy["income"]["total"], copy["expense"]["total"]
            return {**trip, "chosen_source": chosen, "income_total": income, "expense_total": expense,
                    "net": income - expense, "verified": True}
        return {**trip, "chosen_source": chosen, "income_total": None, "expense_total": None, "net": None,
                "verified": False}
    return {**trip, "chosen_source": trip["canonical_source"]}


def owner_payload(snapshot: dict, choices: dict) -> dict:
    trips = [_trip_for_owner(t, choices.get("choices", {})) for t in snapshot["trips"]]
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
        rows.append(
            "<tr>"
            f"<td>{html.escape(trip['key'])}</td>"
            f"<td>{'마감' if trip['closure'] == 'closed' else '미마감' if trip['closure'] == 'open' else '확인 중'}</td>"
            f"<td>{_money(trip['income_total'])}</td><td>{_money(trip['expense_total'])}</td>"
            f"<td>{_money(trip['net'])}</td>"
            f"<td>{'검증됨' if trip['verified'] else '미검증'}</td>"
            f"<td>{html.escape(reasons)}</td></tr>")
    sources = "".join(
        f"<li>{html.escape(role)}: {html.escape(str(src['status']))}"
        f"{' · ' + html.escape(str(src['error_code'])) if src['error_code'] else ''}"
        f" · 마지막 정상 {html.escape(str(src['last_ok_at'] or '없음'))}</li>"
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


def dispatch(handler, parsed, *, is_owner: bool, raw=None, csrf: str = "") -> bool:
    if not owns_route(parsed.path) or not enabled():
        return False
    if not is_owner:
        handler._send_json({"code": "OWNER_ONLY", "message": "소유자만 볼 수 있습니다"}, 403)
        return True
    if parsed.path == "/api/google-ledger/choice":
        if raw is None or not csrf or handler.headers.get("X-CSRF-Token") != csrf:
            handler._send_json({"code": "CSRF_REQUIRED", "message": "화면을 새로 연 뒤 다시 시도해 주세요"}, 403)
            return True
        body = json.loads(raw.decode("utf-8") or "{}")
        try:
            record_choice(_snapshot_path(), key=str(body.get("key", "")), source=str(body.get("source", "")),
                          at=dt.datetime.now(google_authority.KST).isoformat())
        except ValueError as error:
            handler._send_json({"code": str(error)}, 400)
            return True
        handler._send_json({"code": "OK"})
        return True
    try:
        snapshot = json.loads(_snapshot_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        handler._send_json({"code": "SNAPSHOT_UNAVAILABLE", "message": "동기화 결과를 읽지 못했습니다"}, 503)
        return True
    payload = owner_payload(snapshot, load_choices(_snapshot_path()))
    if parsed.path == "/api/google-ledger":
        handler._send_json(payload)
    else:
        handler._send(render_html(payload))
    return True
