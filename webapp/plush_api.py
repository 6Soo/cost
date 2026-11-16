"""Authenticated JSON projections for the COST Plush UI.

This module is intentionally a read projection and descriptor layer.  Existing
write handlers remain the authority for CSRF, idempotency, revision checks and
logout cookie handling; Plush only advertises those fixed actions to the UI.
"""

from __future__ import annotations

import datetime as _dt
import json
from typing import Any
from urllib.parse import parse_qs, unquote

from . import plush_projection as projection


ROUTES = (
    "/api/plush/bootstrap",
    "/api/plush/home",
    "/api/plush/ledger",
    "/api/plush/row",
    "/api/plush/transactions",
    "/api/plush/admin",
    "/api/plush/auxiliary",
)
_VIEWS = {"cards", "ota", "refunds", "flights"}
_ADMIN_VIEWS = {"accounts", "profile", "google", "review"}
_SORTS = {
    "date_desc", "date_asc", "merchant_asc", "merchant_desc",
    "amount_desc", "amount_asc",
}


def owns_route(path: str) -> bool:
    return path in ROUTES


def _send(handler: Any, value: dict, code: int = 200) -> None:
    sender = getattr(handler, "_send_json", None)
    if not callable(sender):
        raise RuntimeError("handler must provide _send_json")
    try:
        sender(value, code=code)
    except TypeError:
        sender(value, code)


def _error(handler: Any, code: str, message: str, status: int) -> bool:
    _send(handler, {"code": code, "message": message}, status)
    return True


def _query(parsed: Any) -> dict[str, list[str]]:
    supplied = getattr(parsed, "query", None)
    if isinstance(supplied, dict):
        return supplied
    return parse_qs(str(supplied or ""), keep_blank_values=True)


def _first(query: dict[str, list[str]], key: str, default: str = "") -> str:
    value = query.get(key, [default])
    if isinstance(value, (list, tuple)):
        return str(value[0] if value else default)
    return str(value)


def _auth(handler: Any):
    """Resolve the same signed/synthetic session used by ``ledger_board``."""
    from . import ledger_board

    headers = getattr(handler, "headers", {})
    cookies = None
    cookie_reader = getattr(handler, "_cookies", None)
    if callable(cookie_reader):
        cookies = cookie_reader()
    session = ledger_board.require_session(headers, cookies)
    access = ledger_board.access_store()
    if access is None:
        from . import access_control

        raise access_control.AccessError("AUTH_REQUIRED", "다시 로그인해 주세요", status=401)
    return ledger_board, access, session


def _owner(ledger_board: Any, access: Any, session: Any) -> bool:
    return bool(ledger_board.is_owner_session(session))


def _visible_trips(board: Any, access: Any, session: Any, owner: bool) -> list[dict[str, Any]]:
    if board is None:
        return []
    trips = list(board.list_trips(include_archived=True))
    if owner:
        return [trip for trip in trips if not trip.get("deleted")]
    allowed = set(access.visible_tabs(session.user_id))
    return [trip for trip in trips if trip.get("tab_id") in allowed and not trip.get("deleted")]


def _trip_for_query(board: Any, access: Any, session: Any, owner: bool,
                    query: dict[str, list[str]]) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    if board is None:
        raise _ProjectionError("STORE_UNBOUND", "저장소가 연결되지 않았어요", 503)
    tab_id = _first(query, "tab") or _first(query, "trip")
    trips = _visible_trips(board, access, session, owner)
    if not tab_id:
        tab_id = str(trips[0].get("tab_id") if trips else "")
    if tab_id == "unclassified":
        if not owner:
            raise _ProjectionError("RESOURCE_NOT_FOUND", "없는 여행이에요", 404)
        trip = {
            "tab_id": "unclassified", "display_key": "unclassified",
            "display_title": "분류대기", "starts_on": "", "ends_on": "",
            "tab_kind": "other", "archived": False, "visual_closed": False,
        }
        return trip, list(board.list_tab_rows(None))
    trip = next((item for item in trips if str(item.get("tab_id")) == tab_id), None)
    if trip is None:
        raise _ProjectionError("RESOURCE_NOT_FOUND", "없는 여행이에요", 404)
    if not owner:
        access.require_view_tab(session.user_id, tab_id)
    return trip, list(board.list_tab_rows(tab_id))


def _trip_summary(board: Any, trip: dict[str, Any], rows: list[dict[str, Any]]) -> dict[str, Any]:
    # The store's displayed amount/date projection is authoritative.  This
    # fallback is only for test doubles that expose plain rows.
    if board is not None and hasattr(board, "projected"):
        rows = [board.projected(row) for row in rows]
    return projection.trip_summary(trip, rows)


def _bootstrap(ledger_board: Any, access: Any, session: Any, board: Any) -> dict[str, Any]:
    owner = _owner(ledger_board, access, session)
    if board is None:
        raise _ProjectionError("STORE_UNBOUND", "저장소가 연결되지 않았어요", 503)
    trips = _visible_trips(board, access, session, owner)
    summaries = []
    for trip in trips:
        rows = list(board.list_tab_rows(trip["tab_id"]))
        summaries.append(_trip_summary(board, trip, rows))
    capabilities = ["ledger.read", "row.read", "transactions.read"]
    if owner:
        capabilities.extend(("ledger.write", "admin.read", "export.write", "receipt.read"))
    try:
        from . import receipt_review

        receipt_enabled = bool(receipt_review.enabled())
    except Exception:
        receipt_enabled = False
    return {
        "role": "owner" if owner else "viewer",
        "csrf": str(ledger_board.CSRF_TOKEN),
        "trips": summaries,
        "capabilities": capabilities,
        "receipt_enabled": receipt_enabled,
        "screen_titles": {
            "home": "홈", "trips": "여행", "ledger": "장부",
            "transactions": "거래", "receipts": "영수증", "admin": "관리",
        },
    }


def _home(ledger_board: Any, access: Any, session: Any, board: Any) -> dict[str, Any]:
    result = _bootstrap(ledger_board, access, session, board)
    # No synthetic success is reported.  Existing worker queues can be added by
    # the supervisor when their durable read projection is available.
    result.pop("role", None)
    result.pop("csrf", None)
    result.pop("capabilities", None)
    result.pop("receipt_enabled", None)
    result.pop("screen_titles", None)
    result["jobs"] = []
    result["updated_at"] = _dt.datetime.now(_dt.timezone.utc).isoformat()
    return result


def _row_search(row: dict[str, Any], board: Any) -> str:
    if board is not None and hasattr(board, "projected"):
        row = board.projected(row)
    return projection.search_text(row)


def _ledger(ledger_board: Any, access: Any, session: Any, board: Any,
            query: dict[str, list[str]]) -> dict[str, Any]:
    owner = _owner(ledger_board, access, session)
    trip, rows = _trip_for_query(board, access, session, owner, query)
    if board is not None and hasattr(board, "projected"):
        rows = [board.projected(row) for row in rows]
    all_rows = list(rows)
    kind = _first(query, "kind")
    if kind and kind not in {"expense", "income"}:
        raise _ProjectionError("INVALID_VALUE", "kind이 올바르지 않아요", 400)
    if kind:
        rows = [row for row in rows if ("income" if row.get("row_kind") == "income" else "expense") == kind]
    text = _first(query, "q").strip().casefold()
    if text:
        rows = [row for row in rows if text in _row_search(row, None)]
    sort = _first(query, "sort", "date_desc")
    if sort not in _SORTS:
        raise _ProjectionError("INVALID_VALUE", "정렬 조건이 올바르지 않아요", 400)

    def key(row: dict[str, Any]):
        shown = projection.ledger_row(row)
        if sort.startswith("date"):
            return (shown["date"], shown["id"])
        if sort.startswith("merchant"):
            return (shown["merchant"].casefold(), shown["id"])
        try:
            amount = int(shown["amount"])
        except ValueError:
            amount = 0
        return (amount, shown["id"])

    rows.sort(key=key, reverse=sort.endswith("_desc"))
    try:
        page = int(_first(query, "page", "1"))
        page_size = int(_first(query, "page_size", "50"))
    except ValueError:
        raise _ProjectionError("INVALID_VALUE", "페이지 값이 올바르지 않아요", 400)
    if page < 1 or page_size < 1 or page_size > 200:
        raise _ProjectionError("INVALID_VALUE", "페이지 값이 올바르지 않아요", 400)
    start = (page - 1) * page_size
    selected = rows[start:start + page_size]
    closed = bool(trip.get("visual_closed") or trip.get("archived"))
    read_only = (not owner) or closed
    return {
        "trip": _trip_summary(board, trip, all_rows),
        "rows": [projection.ledger_row(row, read_only=read_only) for row in selected],
        "total_count": len(rows),
        "page": page,
        "page_size": page_size,
        "filtered_total": projection.money(sum(projection._display_amount(row) for row in rows)),
        "total": projection.money(sum(projection._display_amount(row) for row in all_rows)),
        "closed": closed,
    }


def _row_detail(ledger_board: Any, access: Any, session: Any, board: Any,
                query: dict[str, list[str]]) -> dict[str, Any]:
    row_id = _first(query, "id") or _first(query, "row")
    if not row_id or board is None:
        raise _ProjectionError("RESOURCE_NOT_FOUND", "없는 행이에요", 404)
    row = board.get_row(unquote(row_id)) if hasattr(board, "get_row") else None
    if row is None:
        raise _ProjectionError("RESOURCE_NOT_FOUND", "없는 행이에요", 404)
    owner = _owner(ledger_board, access, session)
    tab_id = str(row.get("display_tab_id") or "")
    if not owner:
        access.require_view_tab(session.user_id, tab_id)
    trip = next((item for item in _visible_trips(board, access, session, owner)
                 if str(item.get("tab_id")) == tab_id), None)
    closed = bool((trip or {}).get("visual_closed") or (trip or {}).get("archived"))
    read_only = (not owner) or closed
    fields = []
    actions = []
    if owner and not read_only:
        fields = [
            {"name": "occurred_on", "label": "날짜", "type": "date", "value": row.get("occurred_on") or ""},
            {"name": "item", "label": "항목", "type": "text", "value": row.get("item") or ""},
            {"name": "description", "label": "내용", "type": "text", "value": row.get("description") or ""},
            {"name": "operator_note", "label": "메모", "type": "text"},
        ]
        actions.append({
            "id": "row-save", "label": "거래 저장", "method": "POST",
            "href": f"/api/rows/{_quote(row_id)}/save", "encoding": "json",
            "csrf": "header", "response": "json", "fields": fields,
        })
        actions.append({
            "id": "row-lineage", "label": "거래 이력", "method": "GET",
            "href": f"/api/rows/{_quote(row_id)}/lineage", "encoding": "form",
            "csrf": "none", "response": "json",
        })
    return {
        "row": projection.ledger_row(row, read_only=read_only),
        "source": projection.safe_source(row) if owner else None,
        "decision": projection.safe_decision(row) if owner else None,
        "history": list(board.list_history(row_id)) if owner and hasattr(board, "list_history") else [],
        "lineage": [projection.safe_source(row)] if owner else [],
        "detail": projection.safe_detail(row) if owner else {},
        "expected_revision": row.get("revision"),
        "edit_fields": fields,
        "read_only": read_only,
        "actions": actions,
    }


def _quote(value: Any) -> str:
    from urllib.parse import quote

    return quote(str(value or ""), safe="")


def _transaction_actions() -> list[dict[str, Any]]:
    return []


def _transactions(ledger_board: Any, access: Any, session: Any, board: Any,
                  query: dict[str, list[str]]) -> dict[str, Any]:
    if not _owner(ledger_board, access, session):
        from . import access_control

        raise access_control.AccessError(access_control.ACTION_FORBIDDEN,
                                         "이 동작은 owner만 할 수 있어요", status=403)
    view = _first(query, "view", "cards")
    if view not in _VIEWS:
        raise _ProjectionError("INVALID_VALUE", "거래 종류가 올바르지 않아요", 400)
    try:
        page = max(1, int(_first(query, "page", "1")))
        page_size = min(200, max(1, int(_first(query, "page_size", "50"))))
    except ValueError:
        raise _ProjectionError("INVALID_VALUE", "페이지 값이 올바르지 않아요", 400)
    q = _first(query, "q").strip()
    rows: list[dict[str, Any]] = []
    status = None
    columns: list[dict[str, str]]
    if view == "cards":
        from . import card_transactions

        try:
            year = int(_first(query, "year", "2026"))
            month = int(_first(query, "month", "1"))
            data = card_transactions.list_for_month(
                db_path=ledger_board._get_card_db_path(), year=year, month=month,
                per_page=500, search=q)
        except (TypeError, ValueError):
            raise _ProjectionError("INVALID_VALUE", "연도·월 값이 올바르지 않아요", 400)
        except Exception:
            data = {"items": []}
            status = {"code": "SOURCE_UNAVAILABLE", "message": "카드 거래 자료를 조회할 수 없습니다."}
        for item in data.get("items") or []:
            rows.append({
                "id": item.get("transaction_id"), "date": item.get("approval_date") or "",
                "merchant": item.get("merchant") or "", "description": item.get("description") or "",
                "amount": projection.money(item.get("amount_krw")),
                "currency": item.get("foreign_currency") or "KRW",
                "status": item.get("classification_state") or "",
                "trip": item.get("display_tab_id") or item.get("trip_id") or "",
                "card": item.get("card_label") or "",
            })
        columns = [
            {"key": "date", "label": "날짜"}, {"key": "merchant", "label": "가맹점"},
            {"key": "description", "label": "내용"}, {"key": "amount", "label": "금액"},
            {"key": "status", "label": "상태"},
        ]
    elif view == "refunds":
        from . import refund_tab

        for group in refund_tab.groups(board):
            for item in group:
                text = " ".join(str(item.get(k) or "") for k in ("merchant", "item", "occurred_on"))
                if q.casefold() not in text.casefold():
                    continue
                rows.append({
                    "id": item.get("transaction_id"), "date": item.get("occurred_on") or "",
                    "merchant": item.get("merchant") or "", "description": item.get("item") or "",
                    "amount": projection.money(item.get("amount_krw")), "status": "refund-group",
                })
        columns = [
            {"key": "date", "label": "날짜"}, {"key": "merchant", "label": "가맹점"},
            {"key": "description", "label": "내용"}, {"key": "amount", "label": "금액"},
            {"key": "status", "label": "상태"},
        ]
    else:
        # OTA and flight candidate stores have their own source contracts.  Do
        # not flatten HTML or unverified source files into a fake table.
        columns = [
            {"key": "date", "label": "날짜"}, {"key": "merchant", "label": "가맹점"},
            {"key": "description", "label": "내용"}, {"key": "amount", "label": "금액"},
        ]
        status = {"code": "SOURCE_UNAVAILABLE", "message": "현재 거래 자료를 조회할 수 없습니다."}
    start = (page - 1) * page_size
    return {
        "view": view, "columns": columns, "rows": rows[start:start + page_size],
        "total_count": len(rows), "page": page, "page_size": page_size,
        "actions": _transaction_actions(), **({"status": status} if status else {}),
    }


def _descriptor(*, action_id: str, label: str, method: str, href: str,
                encoding: str = "json", csrf: str = "header", response: str = "json",
                fields: list[dict[str, Any]] | None = None, disabled: bool = False,
                reason: str = "") -> dict[str, Any]:
    item = {
        "id": action_id, "label": label, "method": method, "href": href,
        "encoding": encoding, "csrf": csrf, "response": response,
    }
    if fields:
        item["fields"] = fields
    if disabled:
        item["disabled"] = True
        item["reason"] = reason or "현재 사용할 수 없습니다."
    return item


def _admin(ledger_board: Any, access: Any, session: Any, board: Any,
           query: dict[str, list[str]]) -> dict[str, Any]:
    if not _owner(ledger_board, access, session):
        from . import access_control

        raise access_control.AccessError(access_control.ACTION_FORBIDDEN,
                                         "관리자 화면은 owner만 볼 수 있어요", status=403)
    view = _first(query, "view", "accounts")
    if view not in _ADMIN_VIEWS:
        raise _ProjectionError("INVALID_VALUE", "관리 화면이 올바르지 않아요", 400)
    if view == "accounts":
        accounts = []
        for item in access.list_accounts():
            accounts.append({key: item.get(key) for key in (
                "user_id", "display_name", "email", "role", "is_active",
                "session_generation", "created_at", "updated_at") if key in item})
        return {
            "title": "계정·권한", "columns": [
                {"key": "display_name", "label": "이름"}, {"key": "role", "label": "역할"},
                {"key": "is_active", "label": "활성"},
            ], "rows": accounts, "actions": [
                _descriptor(action_id="application-create", label="접근 신청", method="POST",
                             href="/access/applications", fields=[
                                 {"name": "requested_name", "label": "이름", "type": "text", "required": True},
                                 {"name": "nickname", "label": "별칭", "type": "text"},
                                 {"name": "description", "label": "설명", "type": "text"},
                                 {"name": "client_request_id", "label": "요청 ID", "type": "hidden", "required": True},
                             ]),
                _descriptor(action_id="application-decision", label="접근 결정", method="POST",
                             href="/access/decision", fields=[
                                 {"name": "action", "label": "동작", "type": "select", "required": True,
                                  "options": [{"value": "approve", "label": "승인"}, {"value": "reject", "label": "거절"}, {"value": "revoke", "label": "해지"}]},
                                 {"name": "application_id", "label": "신청 ID", "type": "text"},
                                 {"name": "connection_id", "label": "연결 ID", "type": "text"},
                                 {"name": "expected_revision", "label": "revision", "type": "number", "required": True},
                                 {"name": "reservation_person_id", "label": "예약자 ID", "type": "text"},
                                 {"name": "reason", "label": "사유", "type": "text"},
                                 {"name": "client_request_id", "label": "요청 ID", "type": "hidden", "required": True},
                             ]),
            ]
        }
    if view == "profile":
        profile = board.owner_profile() if board is not None and hasattr(board, "owner_profile") else {}
        fields = [
            {"name": "company_name", "label": "회사명", "type": "text", "value": profile.get("company_name") or ""},
            {"name": "default_assignee", "label": "기본 담당자", "type": "text", "value": profile.get("default_assignee") or ""},
            {"name": "expected_revision", "label": "revision", "type": "number", "value": profile.get("revision"), "required": True},
            {"name": "client_request_id", "label": "요청 ID", "type": "hidden", "required": True},
        ]
        return {"title": "기본 정보", "data": profile, "fields": fields, "actions": [
            _descriptor(action_id="profile-save", label="기본 정보 저장", method="POST",
                         href="/api/owner-profile", fields=fields)
        ]}
    if view == "google":
        try:
            enabled = bool(__import__("webapp.google_ledger_page", fromlist=["enabled"]).enabled())
        except Exception:
            enabled = False
        return {"title": "Google 장부 연결", "data": {"enabled": enabled}, "actions": [
            _descriptor(action_id="google-sync", label="Google 장부 새로 읽기", method="POST",
                        href="/api/google-ledger/sync", fields=[
                            {"name": "client_request_id", "label": "요청 ID", "type": "hidden"},
                        ], disabled=not enabled, reason="Google 장부 연결이 설정되지 않았습니다."),
        ]}
    return {"title": "AI 분기 검수", "data": {"available": False}, "actions": [
        _descriptor(action_id="review-model", label="검수 상태 조회", method="GET",
                    href="/api/review/model", encoding="form", csrf="none", response="json")
    ]}


def _auxiliary(ledger_board: Any, access: Any, session: Any, board: Any,
               query: dict[str, list[str]]) -> dict[str, Any]:
    if not _owner(ledger_board, access, session):
        from . import access_control

        raise access_control.AccessError(access_control.ACTION_FORBIDDEN,
                                         "보조 화면은 owner만 볼 수 있어요", status=403)
    view = _first(query, "view", "export")
    if view == "export":
        return {"title": "내보내기", "actions": [
            _descriptor(action_id="board-tsv", label="장부 TSV 다운로드", method="GET",
                        href="/api/board/tsv", encoding="form", csrf="none", response="json"),
            _descriptor(action_id="exports-xlsx", label="XLSX 내보내기", method="POST",
                        href="/api/exports/xlsx", fields=[
                            {"name": "tab_ids", "label": "여행", "type": "hidden", "multiple": True, "required": True},
                            {"name": "client_request_id", "label": "요청 ID", "type": "hidden", "required": True},
                        ]),
        ]}
    if view == "insurance":
        return {"title": "참가자·보험", "actions": [
            _descriptor(action_id="insurance-state", label="보험 대조 조회", method="GET",
                        href="/api/participants/insurance-match", encoding="form", csrf="none", response="json")
        ]}
    if view == "participants":
        return {"title": "참가자", "actions": [
            _descriptor(action_id="participants-state", label="참가자 대조 조회", method="GET",
                        href="/api/participants/state", encoding="form", csrf="none", response="json")
        ]}
    if view == "flight":
        return {"title": "항공권", "fields": [
            {"name": "booking_ref", "label": "예약 번호", "type": "text", "required": True},
            {"name": "tour_id", "label": "여행 ID", "type": "text"},
        ], "actions": [
            _descriptor(action_id="flight-candidates", label="탑승객 후보 조회", method="GET",
                        href="/api/flight-passengers/candidates", encoding="form", csrf="none", response="json")
        ]}
    if view == "reserve-links":
        return {"title": "예약 연결", "actions": [
            _descriptor(action_id="reserve-plan", label="예약 연결 계획", method="GET",
                        href="/api/reserve-link/plan", encoding="form", csrf="none", response="json"),
            _descriptor(action_id="reserve-state", label="예약 연결 상태", method="GET",
                        href="/api/reserve-link/state", encoding="form", csrf="none", response="json"),
        ]}
    raise _ProjectionError("INVALID_VALUE", "보조 화면이 올바르지 않아요", 400)


class _ProjectionError(Exception):
    def __init__(self, code: str, message: str, status: int):
        super().__init__(message)
        self.code, self.message, self.status = code, message, status


def dispatch(handler: Any, parsed: Any, *, board: Any, raw: bytes | None = None,
             content_type: str | None = None) -> bool:
    """Handle one authenticated Plush GET.  Return ``False`` for other paths."""
    path = getattr(parsed, "path", "")
    if path not in ROUTES:
        return False
    if raw is not None or str(getattr(handler, "command", "GET")).upper() != "GET":
        return False
    try:
        ledger_board, access, session = _auth(handler)
        owner = _owner(ledger_board, access, session)
        query = _query(parsed)
        if path == "/api/plush/bootstrap":
            result = _bootstrap(ledger_board, access, session, board)
        elif path == "/api/plush/home":
            result = _home(ledger_board, access, session, board)
        elif path == "/api/plush/ledger":
            result = _ledger(ledger_board, access, session, board, query)
        elif path == "/api/plush/row":
            result = _row_detail(ledger_board, access, session, board, query)
        elif path == "/api/plush/transactions":
            result = _transactions(ledger_board, access, session, board, query)
        elif path == "/api/plush/admin":
            result = _admin(ledger_board, access, session, board, query)
        else:
            result = _auxiliary(ledger_board, access, session, board, query)
        _send(handler, result)
        return True
    except _ProjectionError as exc:
        return _error(handler, exc.code, exc.message, exc.status)
    except Exception as exc:
        from . import access_control

        if isinstance(exc, access_control.AccessError):
            return _error(handler, exc.code, exc.message, exc.status or 403)
        # Do not expose source paths, SQL or customer values in a projection
        # error.  The existing server logs the exception at its outer boundary.
        return _error(handler, "INTERNAL_ERROR", "요청을 처리하지 못했어요", 500)
