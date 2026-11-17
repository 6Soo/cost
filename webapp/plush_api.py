"""Authenticated JSON projections for the COST Plush UI.

This module is intentionally a read projection and descriptor layer.  Existing
write handlers remain the authority for CSRF, idempotency, revision checks and
logout cookie handling; Plush only advertises those fixed actions to the UI.
"""

from __future__ import annotations

import datetime as _dt
import re
import uuid
from decimal import Decimal, InvalidOperation
from typing import Any
from urllib.parse import parse_qs, quote, unquote

from . import plush_projection as projection
from . import plush_periods


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


def _board_instance(board: Any) -> Any:
    """Accept the LedgerStore instance; tolerate a module adapter in tests."""
    if board is not None and hasattr(board, "list_tab_rows"):
        return board
    active = getattr(board, "_active_store", None)
    return active() if callable(active) else board


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
            "display_title": "내부 보호 · 이전 귀속 결과", "starts_on": "", "ends_on": "",
            "tab_kind": "other", "archived": False, "visual_closed": False,
        }
        return trip, list(board.list_tab_rows(None))
    trip = next((item for item in trips if str(item.get("tab_id")) == tab_id), None)
    if trip is None:
        raise _ProjectionError("RESOURCE_NOT_FOUND", "없는 여행이에요", 404)
    if not owner:
        access.require_view_tab(session.user_id, tab_id)
    return trip, list(board.list_tab_rows(tab_id))


def _source_income(board, access, session, owner, tab_id):
    from . import plush_income
    return plush_income.load(tab_id, owner=owner, session=session,
                             visible_tabs=set() if owner else set(access.visible_tabs(session.user_id)))


def _with_income(rows, source):
    ids = {row.get('row_id') for row in rows}
    return [*rows, *(row for row in source['rows'] if row['row_id'] not in ids)]


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
        income = _source_income(board, access, session, owner, trip['tab_id'])
        rows = _with_income(rows, income)
        summary = _trip_summary(board, trip, rows)
        summary['income_source'] = {key: value for key, value in income.items() if key != 'rows'}
        summaries.append(summary)
    capabilities = ["ledger.read", "row.read", "transactions.read"]
    if owner:
        capabilities.extend(("ledger.write", "admin.read", "export.write", "receipt.read"))
    receipt_enabled = False
    if owner:
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
    income = _source_income(board, access, session, owner, str(trip.get('tab_id') or ''))
    rows = _with_income(rows, income)
    if board is not None and hasattr(board, "projected"):
        rows = [board.projected(row) for row in rows]
    rows = plush_periods.annotate(rows, board)
    all_rows = list(rows)
    kind = _first(query, "kind")
    if kind and kind not in {"expense", "income"}:
        raise _ProjectionError("INVALID_VALUE", "kind이 올바르지 않아요", 400)
    kind_rows = all_rows
    if kind:
        kind_rows = [row for row in all_rows if ("income" if row.get("row_kind") == "income" else "expense") == kind]
    rows = list(kind_rows)
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
    read_only = (not owner) or closed or trip.get("tab_id") == "unclassified"
    return {
        "trip": _trip_summary(board, trip, all_rows),
        "income_source": {key: value for key, value in income.items() if key != 'rows'},
        "rows": [projection.ledger_row(row, read_only=read_only or row.get('google_income', False)) for row in selected],
        "total_count": len(rows),
        "page": page,
        "page_size": page_size,
        "filtered_total": projection.money(sum(projection._display_amount(row) for row in rows)),
        "total": projection.money(sum(projection._display_amount(row) for row in kind_rows)),
        "closed": closed,
    }


def _row_detail(ledger_board: Any, access: Any, session: Any, board: Any,
                query: dict[str, list[str]]) -> dict[str, Any]:
    row_id = _first(query, "id") or _first(query, "row")
    if not row_id or board is None:
        raise _ProjectionError("RESOURCE_NOT_FOUND", "없는 행이에요", 404)
    row = board.get_row(unquote(row_id)) if hasattr(board, "get_row") else None
    if row is None and row_id.startswith('google-income|'):
        parts = row_id.split('|')
        if len(parts) == 4:
            owner = _owner(ledger_board, access, session)
            source = _source_income(board, access, session, owner, parts[1])
            row = next((r for r in source['rows'] if r['row_id'] == row_id), None)
    if row is None:
        raise _ProjectionError("RESOURCE_NOT_FOUND", "없는 행이에요", 404)
    owner = _owner(ledger_board, access, session)
    tab_id = str(row.get("display_tab_id") or "")
    if not owner:
        access.require_view_tab(session.user_id, tab_id)
    trip = next((item for item in _visible_trips(board, access, session, owner)
                 if str(item.get("tab_id")) == tab_id), None)
    closed = bool((trip or {}).get("visual_closed") or (trip or {}).get("archived"))
    read_only = (not owner) or closed or tab_id in {"", "unclassified"} or row.get("revision") is None
    display_row = board.projected(row) if hasattr(board, "projected") else row
    display_row = plush_periods.annotate([display_row], board)[0]
    fields = []
    actions = []
    if owner and not read_only:
        fields = _row_edit_fields(row, _visible_trips(board, access, session, owner),
                                  display_row=display_row)
        save_fields = [*fields, {
            "name": "expected_revision", "label": "revision", "type": "hidden",
            "value": row.get("revision"), "required": True,
        }]
        if not row.get("is_allocation"):
            save_fields.append({
                "name": "change_mode", "label": "변경 이유", "type": "select",
                "value": "exception", "required": True,
                "options": [
                    {"value": "exception", "label": "예외 사항"},
                    {"value": "rule_change", "label": "규칙 변경"},
                ],
            })
        save_fields.append({
            "name": "client_request_id", "label": "요청 ID", "type": "hidden",
            "value": uuid.uuid4().hex, "required": True,
        })
        actions.append({
            "id": "row-save", "label": "거래 저장", "method": "POST",
            "href": f"/api/rows/{_quote(row_id)}/save", "encoding": "json",
            "csrf": "header", "response": "json", "fields": save_fields,
        })
        actions.append({
            "id": "row-lineage", "label": "거래 이력", "method": "GET",
            "href": f"/api/rows/{_quote(row_id)}/lineage", "encoding": "form",
            "csrf": "none", "response": "json",
        })
    # Keep source detail unprojected for provenance, but make the row shown to
    # the user follow the exact same correction projection as the ledger list.
    return {
        "row": projection.ledger_row(display_row, read_only=read_only),
        "source": projection.safe_source(row) if owner else None,
        "decision": projection.safe_decision(row) if owner else None,
        "history": list(board.list_history(row_id)) if owner and not row.get('google_income') and hasattr(board, "list_history") else [],
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


def _row_edit_fields(row: dict[str, Any], trips: list[dict[str, Any]], *,
                     display_row: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    """Mirror the existing store's editable-field allowlist."""
    from .board_render_helpers import editable_fields

    kind = str(row.get("row_kind") or "expense")
    source = str(row.get("source_kind") or "")
    names, _fixed = editable_fields(kind, source, bool(row.get("is_allocation")))
    types = {
        "occurred_on": "date", "amount_krw": "number", "display_tab_id": "select",
    }
    labels = {
        "display_tab_id": "여행", "occurred_on": "날짜", "amount_krw": "금액(원)",
        "item": "항목", "description": "내용", "operator_note": "메모",
        "customer_id": "고객 ID", "customer_name": "고객명", "nickname": "별칭",
        "income_kind": "수입 구분",
    }
    result = []
    shown = display_row if isinstance(display_row, dict) else row
    display_names = {
        "occurred_on": "display_occurred_on",
        "amount_krw": "display_amount_krw",
    }
    for name in names:
        item = {"name": name, "label": labels.get(name, name),
                "type": types.get(name, "text")}
        displayed_name = display_names.get(name)
        value = (shown.get(displayed_name) if displayed_name and shown.get(displayed_name) is not None
                 else shown.get(name))
        if name in shown or (displayed_name and displayed_name in shown):
            if value is not None:
                item["value"] = value
        if name == "display_tab_id":
            item["options"] = [
                {"value": str(trip.get("tab_id") or ""),
                 "label": str(trip.get("display_title") or trip.get("display_key") or trip.get("tab_id") or "")}
                for trip in trips
                if trip.get("tab_id") and not trip.get("archived")
                and not trip.get("visual_closed") and not trip.get("deleted")
            ]
        result.append(item)
    return result


def _transaction_actions() -> list[dict[str, Any]]:
    return [_descriptor(
        action_id="card-upload-batch", label="카드 파일 업로드", method="POST",
        href="/api/imports/upload-batch", encoding="multipart", csrf="header",
        response="json", fields=[
            {"name": "files", "label": "카드 파일", "type": "file",
             "accept": ".xls,.xlsx,.csv", "multiple": True, "required": True},
        ],
    )]


def _page_values(query: dict[str, list[str]], *, default_size: int = 50) -> tuple[int, int]:
    try:
        page = int(_first(query, "page", "1"))
        page_size = int(_first(query, "page_size", str(default_size)))
    except ValueError:
        raise _ProjectionError("INVALID_VALUE", "페이지 값이 올바르지 않아요", 400)
    if page < 1 or page_size < 1 or page_size > 200:
        raise _ProjectionError("INVALID_VALUE", "페이지 값이 올바르지 않아요", 400)
    return page, page_size


def _card_transaction_page(ledger_board: Any, query: dict[str, list[str]], *,
                           page: int, page_size: int, search: str) -> dict[str, Any]:
    from . import card_transactions

    try:
        period = _first(query, "period")
        if period:
            if not re.fullmatch(r"\d{4}(?:-(?:0[1-9]|1[0-2]))?", period):
                raise ValueError
            year = int(period[:4])
            if not 2000 <= year <= 2100:
                raise ValueError
            month = int(period[5:]) if len(period) == 7 else None
        else:
            year = int(_first(query, "year", "2026"))
            if year < 2000 or year > 2100:
                raise ValueError
            month_text = _first(query, "month")
            month = int(month_text) if month_text else None
            if month is not None and not 1 <= month <= 12:
                raise ValueError
    except ValueError:
        raise _ProjectionError("INVALID_VALUE", "연도·월 값이 올바르지 않아요", 400)

    db_path = ledger_board._get_card_db_path()
    card = _first(query, "card").strip()
    # The legacy /cards/all page accepts card_kind in URLs but does not use it
    # as a source filter. Keep that compatibility behavior; card identity is
    # selected by the existing `card` key.
    filters = {"card": card, "search": search}
    summary = card_transactions.year_summary(db_path=db_path, year=year, **filters)
    months = summary.get("months") or {}
    undated = _first(query, "undated").strip().lower() in {"1", "true", "on"}
    if undated:
        total_count = int(summary.get("undated_count", 0) or 0)
    else:
        total_count = (int(months.get(month, 0) or 0) if month is not None
                       else sum(int(value or 0) for value in months.values()))
    offset = (page - 1) * page_size
    limit = offset + page_size
    collected: list[dict[str, Any]] = []
    cursor = _first(query, "undated_cursor" if undated else "cursor") or None
    if cursor and re.fullmatch(r"(?:\d{4}-\d{2}-\d{2}(?:[T ].*)?)?\|.+", cursor) is None:
        cursor = None
    if undated and cursor and not cursor.startswith("0000-00-00|"):
        cursor = None
    while len(collected) < limit and len(collected) < total_count:
        per_page = min(500, limit - len(collected))
        if undated:
            result = card_transactions.undated_list(
                db_path=db_path, year=year, cursor=cursor, per_page=per_page,
                known_total=total_count, **filters)
        elif month is None:
            result = card_transactions.search_for_year(
                db_path=db_path, year=year, cursor=cursor, per_page=per_page,
                known_total=total_count, **filters)
        else:
            result = card_transactions.list_for_month(
                db_path=db_path, year=year, month=month, cursor=cursor,
                per_page=per_page, **filters)
        batch = result.get("items") or []
        if not batch:
            break
        collected.extend(batch)
        if not result.get("has_more"):
            break
        next_cursor = result.get("cursor")
        if not next_cursor or next_cursor == cursor:
            break
        cursor = next_cursor

    page_items = collected[offset:limit]
    rows = []
    for item in page_items:
        foreign_amount = item.get("foreign_amount")
        if foreign_amount is not None:
            try:
                source_amount = format(Decimal(str(foreign_amount)), "f")
            except (InvalidOperation, TypeError, ValueError):
                source_amount = str(foreign_amount)
        else:
            source_amount = None
        rows.append({
            "id": str(item.get("transaction_id") or ""),
            "date": str(item.get("approval_date") or item.get("use_date") or ""),
            "merchant": str(item.get("merchant") or ""),
            "description": str(item.get("description") or ""),
            "amount": projection.money(item.get("amount_krw")),
            "amount_krw": projection.money(item.get("amount_krw")),
            "currency": "KRW",
            "foreign_amount": source_amount,
            "foreign_currency": str(item.get("foreign_currency") or "") or None,
            "status": str(item.get("classification_state") or ""),
            "trip": str(item.get("display_tab_id") or item.get("trip_id") or ""),
            "card": str(item.get("card_label") or ""),
        })
    return {"rows": rows, "total_count": total_count, "page": page,
            "page_size": page_size, "status": None}


def _ota_transaction_page(board: Any, query: dict[str, list[str]], *,
                          page: int, search: str) -> dict[str, Any]:
    from . import ota_catalog

    try:
        data = ota_catalog.catalog(board, query, allow_stale=True)
    except Exception:
        return {"rows": [], "total_count": 0, "page": page,
                "page_size": ota_catalog.PAGE_SIZE,
                "status": {"code": "SOURCE_UNAVAILABLE", "message": "OTA 예약 자료를 조회할 수 없습니다."}}
    rows = []
    for item in data.get("rows") or []:
        provider = str(item.get("provider") or "")
        booking_ref = str(item.get("booking_ref") or "")
        trip_names = [str(trip.get("name") or "") for trip in item.get("trips") or []
                      if isinstance(trip, dict) and trip.get("name")]
        rows.append({
            "id": f"{provider}:{booking_ref}",
            "provider": provider,
            "booking_ref": booking_ref,
            "source_href": (ota_catalog.detail_url(provider, booking_ref)
                            if provider and booking_ref else None),
            "date": str(item.get("starts_on") or ""),
            "merchant": str((ota_catalog.PROVIDERS.get(provider) or provider)),
            "description": str(item.get("label") or ""),
            "period": str(item.get("period") or ""),
            "trip": ", ".join(trip_names),
            "status": str(item.get("status") or ""),
            "card_count": int(item.get("card_count") or 0),
        })
    status = None
    warnings = data.get("warnings") or []
    if warnings:
        status = {"code": "SOURCE_WARNING", "message": "OTA 자료 일부를 확인하지 못했습니다."}
    return {"rows": rows, "total_count": int(data.get("total") or 0),
            "page": int(data.get("page") or page),
            "page_size": int(ota_catalog.PAGE_SIZE), "status": status}


def _flight_transaction_page(ledger_board: Any, board: Any,
                             query: dict[str, list[str]], *, page: int,
                             page_size: int, search: str) -> dict[str, Any]:
    from . import trip_flight_read

    try:
        snapshot = ledger_board._held_flight_snapshot(board)
        index = ((snapshot or {}).get("data") or {}).get("passengers") if (snapshot or {}).get("fresh") else None
        if index is None:
            return {"rows": [], "total_count": 0, "page": page, "page_size": page_size,
                    "status": {"code": "SOURCE_UNAVAILABLE", "message": "확인된 항공권 자료를 조회할 수 없습니다."}}
        trips = _visible_trips(board, None, None, True)
        rules = trip_flight_read.read_booking_trip_rules()
        links = trip_flight_read.confirmed_booking_card_links(board, index)
        expense_rows = trip_flight_read.confirmed_card_trip_rows(board, links)
        user_assignments, authorities, authority_revision = trip_flight_read.build_authority_maps(
            index, trips, booking_trip_rules=rules, confirmed_card_links=links,
            expense_rows=expense_rows)
        import hashlib

        generation = hashlib.sha256((str((snapshot or {}).get("generation") or "")
                                     + authority_revision).encode()).hexdigest()
        projected = trip_flight_read.project_trip_bookings(
            index, trips, source_generation=generation,
            user_assignments=user_assignments, authority_trip_ids=authorities,
            evidence_status="FRESH")
    except Exception:
        return {"rows": [], "total_count": 0, "page": page, "page_size": page_size,
                "status": {"code": "SOURCE_UNAVAILABLE", "message": "확인된 항공권 자료를 조회할 수 없습니다."}}

    trip_id = _first(query, "trip") or _first(query, "tab")
    visible_ids = {str(trip.get("tab_id") or "") for trip in trips}
    if trip_id and trip_id not in visible_ids:
        raise _ProjectionError("RESOURCE_NOT_FOUND", "없는 여행이에요", 404)
    rows = []
    for item in projected.get("bookings") or []:
        if trip_id and item.get("assigned_trip_tab_id") != trip_id:
            continue
        trip = next((trip for trip in trips
                     if str(trip.get("tab_id") or "") == str(item.get("assigned_trip_tab_id") or "")), {})
        row = {
            "id": str(item.get("booking_key") or ""),
            "date": str(item.get("outbound_departure_on") or ""),
            "merchant": str(item.get("provider") or ""),
            "description": str(item.get("route_summary") or ""),
            "booking_ref": str(item.get("booking_ref") or ""),
            "trip": str(trip.get("display_title") or trip.get("display_key") or trip.get("tab_id") or ""),
            "passenger_count": int(item.get("passenger_count") or 0),
            "status": str(item.get("booking_status") or ""),
            "evidence_status": str(item.get("evidence_status") or ""),
        }
        if search.casefold() in " ".join(str(value) for value in row.values()).casefold():
            rows.append(row)
    total_count = len(rows)
    offset = (page - 1) * page_size
    return {"rows": rows[offset:offset + page_size], "total_count": total_count,
            "page": page, "page_size": page_size, "status": None}


def _transactions(ledger_board: Any, access: Any, session: Any, board: Any,
                  query: dict[str, list[str]]) -> dict[str, Any]:
    if not _owner(ledger_board, access, session):
        from . import access_control

        raise access_control.AccessError(access_control.ACTION_FORBIDDEN,
                                         "이 동작은 owner만 할 수 있어요", status=403)
    view = _first(query, "view", "cards")
    if view not in _VIEWS:
        raise _ProjectionError("INVALID_VALUE", "거래 종류가 올바르지 않아요", 400)
    page, page_size = _page_values(query)
    q = _first(query, "q").strip()
    status = None
    columns: list[dict[str, str]]
    total_count = 0
    response_page = page
    response_size = page_size
    rows: list[dict[str, Any]] = []
    if view == "cards":
        try:
            data = _card_transaction_page(ledger_board, query, page=page,
                                          page_size=page_size, search=q)
        except _ProjectionError:
            raise
        except Exception:
            data = {"rows": [], "total_count": 0, "page": page, "page_size": page_size}
            status = {"code": "SOURCE_UNAVAILABLE", "message": "카드 거래 자료를 조회할 수 없습니다."}
        rows = list(data.get("rows") or [])
        total_count = int(data.get("total_count") or 0)
        status = status or data.get("status")
        response_page, response_size = int(data.get("page") or page), int(data.get("page_size") or page_size)
        columns = [
            {"key": "date", "label": "날짜"}, {"key": "merchant", "label": "가맹점"},
            {"key": "description", "label": "내용"}, {"key": "amount", "label": "금액(원)"},
            {"key": "foreign_amount", "label": "원통화 금액"},
            {"key": "foreign_currency", "label": "원통화"},
            {"key": "status", "label": "상태"},
        ]
    elif view == "ota":
        data = _ota_transaction_page(board, query, page=page, search=q)
        rows = list(data.get("rows") or [])
        total_count = int(data.get("total_count") or 0)
        response_page, response_size = int(data.get("page") or page), int(data.get("page_size") or page_size)
        status = data.get("status")
        columns = [
            {"key": "date", "label": "이용일"}, {"key": "merchant", "label": "예약처"},
            {"key": "description", "label": "예약"}, {"key": "period", "label": "기간"},
            {"key": "trip", "label": "여행"}, {"key": "status", "label": "상태"},
            {"key": "card_count", "label": "연결 카드"},
            {"key": "source_href", "label": "예약 상세·교정(기존 화면)"},
        ]
    elif view == "refunds":
        from . import refund_tab, refund_tab_ui

        kind = _first(query, "kind").strip()
        saved = {row.get("source_event_id"): row
                 for row in ledger_board._expense_rows()}
        groups = refund_tab_ui.filter_refund_groups(
            refund_tab.groups(board), query=q, kind=kind, saved=saved,
        )
        all_rows = []
        for group in groups:
            if not group:
                continue
            original_id = str(group[0].get("transaction_id") or "")
            refund_basis = group[0].get("refund_basis")
            inferred = bool(group[0].get("inferred"))
            ordered_group = [group[0]] + sorted(group[1:], key=lambda row: (
                not bool(row.get("occurred_on")), row.get("occurred_on") or "",
                row.get("transaction_id") or "",
            ))
            for index, item in enumerate(ordered_group):
                transaction_id = str(item.get("transaction_id") or "")
                role = "original" if index == 0 else "refund"
                role_label = "원결제" if index == 0 else "환불"
                relation = f"{role_label} · 원결제 {original_id}"
                if refund_basis:
                    relation += f" · {refund_basis}"
                if inferred:
                    relation += " · 추론 연결 · 환급 완료 아님"
                saved_row = saved.get(transaction_id)
                source_href = (
                    f"/row?id={quote(str(saved_row['row_id']), safe='')}"
                    f"&back={quote('/board?tab=refunds', safe='')}"
                    if isinstance(saved_row, dict) and saved_row.get("row_id")
                    else "/cards/all"
                )
                all_rows.append({
                    "id": transaction_id, "transaction_id": transaction_id,
                    "refund_group_key": original_id,
                    "refund_role": role, "refund_role_label": role_label,
                    "refund_basis": refund_basis,
                    "refund_group_inferred": inferred,
                    "refund_group_size": len(group),
                    "refund_relation": relation,
                    "source_href": source_href,
                    "date": item.get("occurred_on") or "",
                    "merchant": item.get("merchant") or "", "description": item.get("item") or "",
                    "amount": projection.money(item.get("amount_krw")), "status": "refund-group",
                })
        total_count = len(all_rows)
        start = (page - 1) * page_size
        rows = all_rows[start:start + page_size]
        columns = [
            {"key": "date", "label": "날짜"}, {"key": "merchant", "label": "가맹점"},
            {"key": "description", "label": "내용"}, {"key": "amount", "label": "금액"},
            {"key": "refund_role_label", "label": "구분"},
            {"key": "refund_group_key", "label": "원결제 ID"},
            {"key": "refund_basis", "label": "연결 근거"},
            {"key": "refund_relation", "label": "원결제·환불 관계"},
            {"key": "source_href", "label": "원결제·환불 상세(기존 화면)"},
            {"key": "status", "label": "상태"},
        ]
    elif view == "flights":
        data = _flight_transaction_page(ledger_board, board, query, page=page,
                                        page_size=page_size, search=q)
        rows = list(data.get("rows") or [])
        total_count = int(data.get("total_count") or 0)
        response_page, response_size = int(data.get("page") or page), int(data.get("page_size") or page_size)
        status = data.get("status")
        columns = [
            {"key": "date", "label": "출발일"}, {"key": "merchant", "label": "제공자"},
            {"key": "booking_ref", "label": "예약 번호"}, {"key": "description", "label": "구간"},
            {"key": "trip", "label": "여행"}, {"key": "passenger_count", "label": "인원"},
            {"key": "status", "label": "예약 상태"},
        ]
    else:
        raise _ProjectionError("INVALID_VALUE", "거래 종류가 올바르지 않아요", 400)
    return {
        "view": view, "columns": columns, "rows": rows,
        "total_count": total_count, "page": response_page, "page_size": response_size,
        "actions": _transaction_actions() if view == "cards" else [],
        **({"status": status} if status else {}),
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
        for field in fields:
            if (field.get("name") == "client_request_id"
                    and field.get("type") == "hidden" and not field.get("value")):
                field["value"] = uuid.uuid4().hex
        item["fields"] = fields
    if disabled:
        item["disabled"] = True
        item["reason"] = reason or "현재 사용할 수 없습니다."
    return item


def _safe_rule_record(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        return None
    result = {key: value[key] for key in (
        "rule_id", "version", "base_rule_version", "status", "apply_existing",
        "apply_future", "learning_case_id", "created_at", "updated_at",
    ) if key in value}
    body = value.get("rule") if isinstance(value.get("rule"), dict) else value
    safe_rule = {key: body[key] for key in (
        "conditions", "optional_conditions", "effects", "scope", "exceptions",
        "note", "learning_case_id",
    ) if key in body}
    if safe_rule:
        result["rule"] = safe_rule
    return result


def _safe_rule_preview(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        return None
    plan = value.get("plan") if isinstance(value.get("plan"), dict) else {}
    counts = plan.get("counts") if isinstance(plan.get("counts"), dict) else {}
    candidates = plan.get("candidates") if isinstance(plan.get("candidates"), list) else []
    excluded = plan.get("excluded") if isinstance(plan.get("excluded"), list) else []
    amounts = plan.get("amounts") if isinstance(plan.get("amounts"), dict) else {}
    safe_plan = {
        "counts": {key: counts[key] for key in (
            "matched_rows", "included_rows", "excluded_rows") if key in counts},
        "candidates": [{key: candidate[key] for key in (
            "row_id", "from_tab_id", "to_tab_id", "amount_krw") if key in candidate}
            for candidate in candidates if isinstance(candidate, dict)],
        "excluded": [{key: entry[key] for key in ("row_id", "reason") if key in entry}
                     for entry in excluded if isinstance(entry, dict)],
        "amounts": {
            str(tab_id): {key: bucket[key] for key in (
                "before", "moving_out", "moving_in", "after") if key in bucket}
            for tab_id, bucket in amounts.items() if isinstance(bucket, dict)
        },
    }
    result = {key: value[key] for key in (
        "preview_id", "rule_id", "apply_existing", "apply_future") if key in value}
    result["plan"] = safe_plan
    return result


def _safe_rule_conversation(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        return None
    result = {key: value[key] for key in (
        "conversation_id", "case_id", "rule_id", "rule_version", "active_provider",
        "active_model_id", "state", "turn_count", "created_at", "updated_at",
    ) if key in value}
    result["turns"] = []
    turns = value.get("turns") if isinstance(value.get("turns"), list) else []
    for turn in turns[-20:]:
        if not isinstance(turn, dict):
            continue
        safe_turn = {key: turn[key] for key in (
            "turn_id", "state", "state_label", "adopted_provider", "reason_code",
            "is_real_call", "switch_count", "created_at",
        ) if key in turn}
        review = turn.get("owner_review")
        if isinstance(review, dict) and "reason" in review:
            safe_turn["owner_review"] = {"reason": review["reason"]}
        result["turns"].append(safe_turn)
    return result


def _safe_rule_dialog_page(board: Any, case_id: str) -> dict[str, Any]:
    if not hasattr(board, "dialog_page_state"):
        raise _ProjectionError("STORE_UNBOUND", "저장소가 연결되지 않았어요", 503)
    state = board.dialog_page_state(case_id)
    if not isinstance(state, dict):
        state = {}
    row_id = state.get("row_id")
    source_row = board.get_row(str(row_id)) if row_id and hasattr(board, "get_row") else None
    current_row = None
    if source_row is not None:
        shown = board.projected(source_row) if hasattr(board, "projected") else source_row
        if isinstance(shown, dict):
            current_row = {key: shown[key] for key in ("item", "description")
                           if key in shown}
    questions = state.get("questions") if isinstance(state.get("questions"), list) else []
    safe_questions = [{key: question[key] for key in (
        "question_id", "question_key", "prompt", "options", "answer", "answered")
        if key in question} for question in questions if isinstance(question, dict)]
    provider = state.get("provider") if isinstance(state.get("provider"), dict) else {}
    safe_provider = {key: provider[key] for key in (
        "provider", "model", "is_real_call", "is_real_model_call", "network_call",
        "note", "mode_label") if key in provider}
    pending = state.get("pending_draft") if isinstance(state.get("pending_draft"), dict) else {}
    pending_rule = _safe_rule_record({"rule": pending.get("rule")}) if pending.get("rule") else None
    safe_pending = {key: pending[key] for key in (
        "rule_id", "turn_id", "provider", "confirmed") if key in pending}
    if pending_rule:
        safe_pending["rule"] = pending_rule.get("rule")
    draft_error = pending.get("draft_error")
    if isinstance(draft_error, dict) and draft_error.get("code"):
        safe_pending["draft_error"] = {"code": str(draft_error["code"])}
    rule = _safe_rule_record(state.get("rule"))
    row_revision = state.get("row_revision")
    if row_revision is None and current_row:
        row_revision = current_row.get("revision")
    return {
        "case_id": str(state.get("case_id") or case_id),
        "case_exists": source_row is not None,
        "row_id": str(row_id or ""),
        "row_revision": row_revision,
        "dialog_state": str(state.get("dialog_state") or "not_started"),
        "questions": safe_questions,
        "answers": dict(state.get("answers") or {}) if isinstance(state.get("answers"), dict) else {},
        "open_questions": list(state.get("open_questions") or []),
        "note": str(state.get("note") or ""),
        "should_not_create_rule": bool(state.get("should_not_create_rule")),
        "one_off": bool(state.get("one_off")),
        "provider": safe_provider,
        "conversation": _safe_rule_conversation(state.get("conversation")),
        "pending_draft": safe_pending,
        "rule": rule,
        "last_preview": _safe_rule_preview(state.get("last_preview")),
        "row": current_row,
    }


def _google_text(value: Any, *, limit: int = 96) -> str | None:
    if not isinstance(value, str) or not value or len(value) > limit:
        return None
    if any(ord(char) < 32 for char in value):
        return None
    return value


def _google_amount(value: Any) -> str | None:
    return str(value) if type(value) is int else None


def _google_codes(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item for item in value[:64]
            if isinstance(item, str) and 0 < len(item) <= 80
            and all(char.isupper() or char.isdigit() or char == "_" for char in item)]


def _google_copy_projection(copy: Any, *, source_current: bool = True) -> dict[str, Any]:
    if not isinstance(copy, dict):
        return {"present": False, "layout": None, "verified": False,
                "income_total": None, "expense_total": None, "flags": []}
    income = copy.get("income") if isinstance(copy.get("income"), dict) else {}
    expense = copy.get("expense") if isinstance(copy.get("expense"), dict) else {}
    layout = _google_text(copy.get("layout"), limit=32)
    flags = _google_codes(copy.get("flags"))
    if not source_current and "SOURCE_STALE" not in flags:
        flags.append("SOURCE_STALE")
    return {
        "present": True,
        "layout": layout,
        "verified": source_current and income.get("verified") is True and expense.get("verified") is True,
        "income_total": _google_amount(income.get("total")) if source_current else None,
        "expense_total": _google_amount(expense.get("total")) if source_current else None,
        "flags": flags,
    }


def _admin_google(board: Any) -> dict[str, Any]:
    from . import google_ledger_page
    from app import google_authority

    try:
        enabled = bool(google_ledger_page.enabled())
    except Exception:
        enabled = False

    result: dict[str, Any] = {
        "title": "Google 장부 비교",
        "columns": [
            {"key": "key", "label": "Google 여행"},
            {"key": "kind", "label": "유형"},
            {"key": "closure", "label": "마감"},
            {"key": "income_total", "label": "수입"},
            {"key": "expense_total", "label": "지출"},
            {"key": "net", "label": "차액"},
            {"key": "verified", "label": "검증"},
            {"key": "review", "label": "확인 사항"},
        ],
        "rows": [],
        "actions": [_descriptor(
            action_id="google-sync", label="Google 장부 새로 읽기", method="POST",
            href="/api/google-ledger/sync", fields=[
                {"name": "client_request_id", "label": "요청 ID", "type": "hidden"},
            ], disabled=not enabled,
            reason="Google 장부 연결이 설정되지 않았습니다.",
        )],
        "data": {
            "enabled": enabled,
            "available": False,
            "synced_at": None,
            "sources": {},
            "settings": {"editable": False, "connections": [], "copy_choices": [],
                         "viewer_grants": [], "tabs": []},
        },
    }
    if not enabled:
        result["status"] = {"code": "NOT_CONFIGURED", "message": "Google 장부 연결이 설정되지 않았습니다."}
        return result

    try:
        snapshot, _private_rows = google_ledger_page._load_consistent_measured(
            google_ledger_page._snapshot_path(), google_ledger_page._rows_path())
        choices = google_ledger_page.load_choices(google_ledger_page._snapshot_path())
        mapping = google_ledger_page.load_mapping(google_ledger_page._snapshot_path())
        grants = google_ledger_page.load_grants(google_ledger_page._snapshot_path())
        snapshot = google_ledger_page.snapshot_for_display(snapshot)
        payload = google_ledger_page.owner_payload(snapshot, choices)
        raw_trips = payload.get("trips") if isinstance(payload.get("trips"), list) else []
        trips = {key: trip for trip in raw_trips if isinstance(trip, dict)
                 and (key := _google_text(trip.get("key"), limit=200))}
        trip_keys = set(trips)
        source_states = payload.get("sources") if isinstance(payload.get("sources"), dict) else {}

        try:
            local_trips = board.list_trips(include_archived=True) if board is not None else []
        except Exception:
            local_trips = []
        tabs: dict[str, dict[str, Any]] = {}
        for trip in local_trips if isinstance(local_trips, list) else []:
            if not isinstance(trip, dict):
                continue
            tab_id = _google_text(trip.get("tab_id"), limit=200)
            if not tab_id:
                continue
            label = (trip.get("display_title") or trip.get("display_key")
                     or trip.get("destination") or tab_id)
            tabs[tab_id] = {"tab_id": tab_id, "label": str(label)[:160]}

        connection_counts: dict[str, int] = {}
        for tab_id in mapping.values():
            valid_id = _google_text(tab_id, limit=200)
            if valid_id:
                connection_counts[valid_id] = connection_counts.get(valid_id, 0) + 1
        connections = []
        for key in sorted(trip_keys):
            tab_id = _google_text(mapping.get(key), limit=200)
            if tab_id:
                connections.append({
                    "trip_key": key, "tab_id": tab_id,
                    "tab_label": tabs.get(tab_id, {}).get("label"),
                })

        raw_choices = choices.get("choices") if isinstance(choices, dict) else {}
        copy_choices = [{"trip_key": key, "source": source}
                        for key, source in sorted(raw_choices.items())
                        if key in trip_keys and source in google_authority.SPREADSHEET_IDS]
        raw_grants = grants.get("grants") if isinstance(grants, dict) else {}
        viewer_grants = [{"user_id": user_id,
                          "trip_keys": sorted({key for key in keys if key in trip_keys})}
                         for user_id, keys in sorted(raw_grants.items())
                         if isinstance(user_id, str) and isinstance(keys, list)
                         and any(key in trip_keys for key in keys)]

        rows = []
        for key in sorted(trip_keys):
            trip = trips[key]
            raw_copies = trip.get("copies") if isinstance(trip.get("copies"), dict) else {}
            copy_roles = ("andre_main",) if trip.get("owner_id") == "andre" else ("main", "archive")
            copies = {}
            for source in copy_roles:
                state = source_states.get(source) if isinstance(source_states.get(source), dict) else {}
                source_current = state.get("status") == "ok" and state.get("stale") is not True
                copies[source] = _google_copy_projection(
                    raw_copies.get(source), source_current=source_current)
            chosen = trip.get("chosen_source")
            chosen = chosen if chosen in google_authority.SPREADSHEET_IDS else None
            tab_id = _google_text(mapping.get(key), limit=200)
            has_tab = tab_id in tabs if tab_id else False
            source_href = None
            reconciliation_href = None
            copy_href = None
            if tab_id and has_tab:
                reconciliation_href = (
                    f"/api/google-ledger/expense-reconciliation?trip={_quote(tab_id)}&page=1")
                copy_href = f"/api/board/tsv?tab={_quote(tab_id)}&kind=ex"
                if (chosen and copies[chosen]["present"] and connection_counts.get(tab_id) == 1):
                    source_href = f"/api/google-ledger/source?trip={_quote(tab_id)}"
            closure = trip.get("closure")
            closure = closure if closure in {"open", "closed", "unknown"} else "unknown"
            kind = trip.get("kind") if trip.get("kind") in {"trip", "quarter"} else "trip"
            rows.append({
                "key": key,
                "kind": kind,
                "closure": closure,
                "closure_current": trip.get("closure_current") is True,
                "chosen_source": chosen,
                "verified": trip.get("verified") is True,
                "blocked_by": _google_codes(trip.get("blocked_by")),
                "review": _google_codes(trip.get("review")),
                "income_total": _google_amount(trip.get("income_total")),
                "expense_total": _google_amount(trip.get("expense_total")),
                "net": _google_amount(trip.get("net")),
                "connected_tab_id": tab_id,
                "source_href": source_href,
                "reconciliation_href": reconciliation_href,
                "copy_href": copy_href,
                "copies": copies,
            })

        safe_sources = {}
        for source in google_authority.SPREADSHEET_IDS:
            status = source_states.get(source) if isinstance(source_states.get(source), dict) else {}
            safe_sources[source] = {
                "status": _google_text(status.get("status"), limit=32),
                "error_code": _google_text(status.get("error_code"), limit=80),
                "stale": status.get("stale") is True,
                "last_ok_at": _google_text(status.get("last_ok_at"), limit=64),
                "checked_at": _google_text(status.get("checked_at"), limit=64),
            }
        result["rows"] = rows
        result["data"] = {
            "enabled": enabled,
            "available": True,
            "synced_at": _google_text(payload.get("synced_at"), limit=64),
            "sources": safe_sources,
            "settings": {
                "editable": False,
                "connections": connections,
                "copy_choices": copy_choices,
                "viewer_grants": viewer_grants,
                "tabs": sorted(tabs.values(), key=lambda item: item["label"]),
            },
        }
    except Exception:
        result["status"] = {
            "code": "SNAPSHOT_UNAVAILABLE",
            "message": "Google 장부 비교 자료를 확인하지 못했어요.",
        }
    return result


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
        connections = []
        connection_actions = []
        connection_action_rows = []
        connected_person_ids = set()
        for item in access.list_accounts():
            account_row = {key: item.get(key) for key in (
                "user_id", "display_name", "email", "role", "is_active",
                "session_generation", "created_at", "updated_at") if key in item}
            connection = access.active_connection(item["user_id"])
            account_row.update({
                "connection_status": connection.get("status") if connection else "unlinked",
                "connection_id": connection.get("connection_id") if connection else None,
                "connection_revision": connection.get("revision") if connection else None,
                "reservation_person_id": connection.get("reservation_person_id") if connection else None,
                "reservation_person_label": connection.get("reservation_person_label") if connection else None,
            })
            accounts.append(account_row)
            if not connection:
                continue
            connection_id = str(connection.get("connection_id") or "")
            connected_person_id = str(connection.get("reservation_person_id") or "")
            connected_person_ids.add(connected_person_id)
            connections.append({key: connection.get(key) for key in (
                "connection_id", "user_id", "reservation_person_id",
                "reservation_person_label", "status", "revision",
            )})
            connection_action_rows.append({
                "user_id": str(item.get("user_id") or ""),
                "display_name": str(item.get("display_name") or ""),
                "connection_id": connection_id,
                "reservation_person_label": str(connection.get("reservation_person_label") or ""),
                "revision": connection.get("revision"),
            })

        connection_labels = []
        for row in connection_action_rows:
            display_name = row["display_name"] or row["user_id"] or "계정"
            person_label = row["reservation_person_label"]
            base = f"{display_name} · {person_label}" if person_label else display_name
            connection_labels.append(base)
        connection_label_counts = {
            label: connection_labels.count(label) for label in set(connection_labels)
        }
        for row, base in zip(connection_action_rows, connection_labels):
            label = f"{base} 연결 해지"
            if connection_label_counts[base] > 1:
                label = f"{base} · {row['user_id'] or row['connection_id']} 연결 해지"
            connection_actions.append(_descriptor(
                action_id=f"connection-revoke-{_quote(row['connection_id'])}",
                label=label, method="POST", href="/access/decision", fields=[
                    {"name": "action", "label": "동작", "type": "hidden", "value": "revoke",
                     "required": True},
                    {"name": "connection_id", "label": "연결 ID", "type": "hidden",
                     "value": row["connection_id"], "required": True},
                    {"name": "expected_revision", "label": "revision", "type": "hidden",
                     "value": row["revision"], "required": True},
                    {"name": "client_request_id", "label": "요청 ID", "type": "hidden",
                     "required": True},
                ],
            ))

        pending = access.pending_applications()
        pending_applications = [{key: application.get(key) for key in (
            "application_id", "user_id", "requested_name", "nickname", "status", "revision",
        )} for application in pending]
        people = access.list_reservation_persons()
        reservation_persons = []
        reservation_options = []
        for person in people:
            person_id = person.get("reservation_person_id")
            display_name = str(person.get("display_name") or "")
            disambiguator = str(person.get("disambiguator") or "")
            label = f"{display_name} ({disambiguator})" if disambiguator else display_name
            reservation_persons.append({
                "reservation_person_id": person_id,
                "display_name": display_name,
                "disambiguator": disambiguator,
                "is_active": person.get("is_active") is True,
                "label": label,
            })
            if (person.get("is_active") is True and person_id
                    and person_id not in connected_person_ids):
                reservation_options.append({"value": person_id, "label": label})

        decision_labels = []
        for application in pending:
            requested_name = str(application.get("requested_name") or "").strip()
            nickname = str(application.get("nickname") or "").strip()
            if requested_name and nickname and nickname != requested_name:
                decision_labels.append(f"{requested_name} ({nickname})")
            else:
                decision_labels.append(requested_name or nickname
                                       or str(application.get("user_id") or "신청자"))
        decision_label_counts = {
            label: decision_labels.count(label) for label in set(decision_labels)
        }

        decision_actions = []
        for application, base in zip(pending, decision_labels):
            application_id = str(application.get("application_id") or "")
            if not application_id:
                continue
            label = f"{base} 접근 신청 결정"
            if decision_label_counts[base] > 1:
                label = (f"{base} · {application.get('user_id') or application_id} "
                         "접근 신청 결정")
            decision_actions.append(_descriptor(
                action_id=f"application-decision-{_quote(application_id)}",
                label=label, method="POST", href="/access/decision", fields=[
                    {"name": "action", "label": "결정", "type": "select", "value": "approve",
                     "required": True, "options": [
                         {"value": "approve", "label": "승인"},
                         {"value": "reject", "label": "거절"},
                     ]},
                    {"name": "application_id", "label": "신청 ID", "type": "hidden",
                     "value": application_id, "required": True},
                    {"name": "expected_revision", "label": "revision", "type": "hidden",
                     "value": application.get("revision"), "required": True},
                    {"name": "reservation_person_id", "label": "예약 담당자", "type": "select",
                     "value": reservation_options[0]["value"] if reservation_options else None,
                     "options": reservation_options},
                    {"name": "reason", "label": "거절 사유", "type": "text"},
                    {"name": "client_request_id", "label": "요청 ID", "type": "hidden",
                     "required": True},
                ],
            ))

        return {
            "title": "계정·권한", "columns": [
                {"key": "display_name", "label": "이름"}, {"key": "role", "label": "역할"},
                {"key": "is_active", "label": "활성"},
                {"key": "connection_status", "label": "연결 상태"},
                {"key": "reservation_person_label", "label": "예약 담당자"},
            ], "rows": accounts, "data": {
                "pending_applications": pending_applications,
                "reservation_persons": reservation_persons,
                "connections": connections,
            }, "actions": [
                _descriptor(action_id="application-create", label="접근 신청", method="POST",
                             href="/access/applications", fields=[
                                 {"name": "requested_name", "label": "이름", "type": "text", "required": True},
                                 {"name": "nickname", "label": "별칭", "type": "text"},
                                 {"name": "description", "label": "설명", "type": "text"},
                                 {"name": "client_request_id", "label": "요청 ID", "type": "hidden", "required": True},
                             ]),
                *decision_actions,
                *connection_actions,
            ]
        }
    if view == "profile":
        profile = board.owner_profile() if board is not None and hasattr(board, "owner_profile") else {}
        fields = [
            {"name": "company_name", "label": "회사명", "type": "text", "value": profile.get("company_name") or ""},
            {"name": "assignee_name", "label": "기본 담당자", "type": "text", "value": profile.get("assignee_name") or ""},
            {"name": "expected_revision", "label": "revision", "type": "number", "value": profile.get("revision"), "required": True},
            {"name": "client_request_id", "label": "요청 ID", "type": "hidden", "required": True},
        ]
        return {"title": "기본 정보", "data": profile, "fields": fields, "actions": [
            _descriptor(action_id="profile-save", label="기본 정보 저장", method="POST",
                         href="/api/owner-profile", fields=fields)
        ]}
    if view == "google":
        return _admin_google(board)
    from . import real_review

    service = real_review.active_service()
    if service is None:
        code = getattr(real_review, "_CONFIG_ERROR", "") or real_review.CODE_UNAVAILABLE
        data = {"available": False}
        status = {"code": str(code), "message": "실제 자료 검토를 진행할 수 없어요."}
    else:
        try:
            data = {"available": True, **service.state_only_payload()}
            status = None
        except real_review.RealReviewError as exc:
            data = {"available": False}
            status = {"code": exc.code, "message": "실제 자료 검토를 진행할 수 없어요."}
        except Exception:
            data = {"available": False}
            status = {"code": real_review.CODE_INTERNAL, "message": "실제 자료 검토를 진행할 수 없어요."}
    result = {"title": "AI 분기 검수", "data": data, "actions": [
        _descriptor(action_id="review-model", label="검수 상태 조회", method="GET",
                    href="/api/review/model?state_only=1", encoding="form",
                    csrf="none", response="json")
    ]}
    if status:
        result["status"] = status
    return result


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
    if view == "expense-new":
        if board is None:
            raise _ProjectionError("STORE_UNBOUND", "저장소가 연결되지 않았어요", 503)
        trips = _visible_trips(board, access, session, True)
        fields = [
            {"name": "display_tab_id", "label": "여행", "type": "select",
             "options": [{"value": "", "label": "기타 비용"}] + [
                 {"value": str(trip.get("tab_id") or ""),
                  "label": str(trip.get("display_title") or trip.get("display_key") or trip.get("tab_id") or "")}
                 for trip in trips if trip.get("tab_id") and not trip.get("archived")
                 and not trip.get("visual_closed") and not trip.get("deleted")
             ]},
            {"name": "occurred_on", "label": "거래일자", "type": "date", "required": True},
            {"name": "pay_method", "label": "지급 수단", "type": "select", "required": True,
             "options": [{"value": "현금", "label": "현금"}, {"value": "계좌이체", "label": "계좌이체"}]},
            {"name": "item", "label": "분류", "type": "text"},
            {"name": "description", "label": "내용", "type": "text"},
            {"name": "amount_krw", "label": "금액(원)", "type": "number", "required": True},
            {"name": "operator_note", "label": "메모", "type": "text"},
            {"name": "client_request_id", "label": "요청 ID", "type": "hidden", "required": True},
        ]
        return {"title": "수기 지출 추가", "fields": fields, "actions": [
            _descriptor(action_id="manual-expense-create", label="지출 저장", method="POST",
                        href="/api/expenses/manual", fields=fields)
        ]}
    if view == "income-new":
        if board is None:
            raise _ProjectionError("STORE_UNBOUND", "저장소가 연결되지 않았어요", 503)
        trips = _visible_trips(board, access, session, True)
        fields = [
            {"name": "display_tab_id", "label": "여행", "type": "select",
             "options": [{"value": "", "label": "여행 선택"}] + [
                 {"value": str(trip.get("tab_id") or ""),
                  "label": str(trip.get("display_title") or trip.get("display_key") or trip.get("tab_id") or "")}
                 for trip in trips if trip.get("tab_id") and not trip.get("archived")
                 and not trip.get("visual_closed") and not trip.get("deleted")
             ]},
            {"name": "occurred_on", "label": "거래일자", "type": "date"},
            {"name": "amount_krw", "label": "금액(원)", "type": "number", "required": True},
            {"name": "income_kind", "label": "입금 종류", "type": "select", "required": True,
             "options": [
                 {"value": "deposit", "label": "예약금"},
                 {"value": "balance", "label": "잔금"},
                 {"value": "additional", "label": "추가금"},
             ]},
            {"name": "customer_name", "label": "이름", "type": "text"},
            {"name": "nickname", "label": "닉네임", "type": "text"},
            {"name": "operator_note", "label": "메모", "type": "text"},
            {"name": "client_request_id", "label": "요청 ID", "type": "hidden", "required": True},
        ]
        return {"title": "수기 수입 추가", "fields": fields, "actions": [
            _descriptor(action_id="direct-income-create", label="수입 저장", method="POST",
                        href="/api/income", fields=fields)
        ]}
    if view == "rules":
        if board is None or not hasattr(board, "list_rules"):
            raise _ProjectionError("STORE_UNBOUND", "저장소가 연결되지 않았어요", 503)
        rules = list(board.list_rules())
        rows = []
        for entry in rules:
            rule = entry.get("rule") if isinstance(entry.get("rule"), dict) else {}
            conditions = rule.get("conditions") if isinstance(rule.get("conditions"), dict) else {}
            effects = rule.get("effects") if isinstance(rule.get("effects"), dict) else {}
            rows.append({
                "rule_id": str(entry.get("rule_id") or ""),
                "version": entry.get("version"),
                "status": str(entry.get("status") or ""),
                "merchant": str(conditions.get("merchant_normalized") or ""),
                "card_kind": str(conditions.get("card_kind") or ""),
                "transaction_direction": str(conditions.get("transaction_direction") or ""),
                "item": str(effects.get("item") or ""),
                "apply_existing": bool(entry.get("apply_existing")),
                "apply_future": bool(entry.get("apply_future")),
            })
        case_id = _first(query, "case").strip()
        data = {"total_count": len(rows), "case_id": case_id}
        actions = [_descriptor(
            action_id="classification-rules-list", label="규칙 목록 새로 읽기", method="GET",
            href="/api/classification/rules", encoding="form", csrf="none",
            response="json")]
        if case_id:
            if len(case_id) > 256:
                raise _ProjectionError("INVALID_VALUE", "case 값이 올바르지 않아요", 400)
            data["case_dialog"] = _safe_rule_dialog_page(board, case_id)
            actions.append(_descriptor(
                action_id="classification-rule-dialog-state", label="규칙 대화 상태 읽기",
                method="GET", href=f"/api/classification/dialog?case_id={_quote(case_id)}",
                encoding="form", csrf="none", response="json"))
        return {"title": "규칙 보조", "columns": [
            {"key": "merchant", "label": "가맹점"},
            {"key": "card_kind", "label": "카드 종류"},
            {"key": "transaction_direction", "label": "거래 구분"},
            {"key": "item", "label": "비용 항목"},
            {"key": "status", "label": "상태"},
        ], "rows": rows, "data": data, "actions": actions}
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
        board = _board_instance(board)
        ledger_board, access, session = _auth(handler)
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
