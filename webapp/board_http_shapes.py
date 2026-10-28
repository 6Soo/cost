"""HTTP input parsing and response shaping helpers for ledger board.

Extracted under RF-102 to separate HTTP request payload decoding, cookie parsing,
parameter validation, and response envelope formatting (JSON, HTML, binary, redirects,
form errors) from ledger_board request handling.
"""
from __future__ import annotations

import http.cookies
import json
from typing import Any, Callable, Dict, List, Optional, Tuple
from urllib.parse import parse_qs, urlsplit

# Standard HTTP status mapping for error codes
STATUS_FOR_CODE: Dict[str, int] = {
    # The first block is the vocabulary of DETAILED_CONTRACT 4.3.
    "AUTH_REQUIRED": 401,
    "ACTION_FORBIDDEN": 403,
    "RESOURCE_NOT_FOUND": 404,
    "TEMPORARILY_UNAVAILABLE": 503,
    "INTERNAL_ERROR": 500,
    # Phase 6 provider configuration.
    "PROVIDER_CONFIG_UNBOUND": 503,
    "EDIT_CONFLICT": 409,
    "REQUEST_ID_REUSED": 409,
    # An export naming an assignee whose origin was never recorded. Refused whole
    # rather than produced with a marker on the sheet.
    "ASSIGNEE_UNCONFIRMED": 409,
    "FIELD_READ_ONLY": 422,
    "INVALID_VALUE": 422,
    "TARGET_NOT_ASSIGNABLE": 422,
    "CSRF_REQUIRED": 403,
    "PREVIEW_STALE": 409,
    "REFUND_PAIR_PARTIALLY_BOOKED": 409,
    "REFUND_GROUP_INCOMPLETE": 409,
    "DELETE_PREVIEW_STALE": 409,
    "RULE_FIELD_NOT_ALLOWED": 422,
    "RULE_EFFECT_FORBIDDEN": 422,
    "RULE_SCOPE_INCOMPLETE": 422,
    "RULE_CONDITION_TYPE": 422,
    "RULE_OPERATOR_NOT_ALLOWED": 422,
    "RULE_TEMPLATE_FORBIDDEN": 422,
    "RULE_SUPERSEDED": 409,
    "RULE_ONE_OFF": 422,
    "DIALOG_STALE": 409,
    "DIALOG_CLOSED": 409,
}


def parse_cookies(headers: Any) -> Any:
    """The request's cookies, parsed once per request.

    BaseHTTPRequestHandler.headers is an email.message.Message, which
    keeps repeated headers, so a second Cookie line is appended rather
    than replacing the first. A client can send two, and reading only the
    first would let it hide a cookie from the check.
    """
    jar = http.cookies.SimpleCookie()
    if headers is None:
        return jar
    try:
        getter = getattr(headers, "get_all", None)
        raw_list = getter("Cookie") if callable(getter) else headers.get("Cookie")
        if isinstance(raw_list, str):
            raw_list = [raw_list]
        for raw in (raw_list or []):
            jar.load(raw)
    except (AttributeError, http.cookies.CookieError):
        return {}
    return jar


def check_content_length(headers: Any, max_bytes: int = 5 * 1024 * 1024) -> int:
    """Validate Content-Length header against maximum byte limit.

    Returns the integer length, or raises ValueError("TOO_LARGE") if it exceeds max_bytes.
    """
    length = int(headers.get("Content-Length") or 0) if headers else 0
    if length > max_bytes:
        raise ValueError("TOO_LARGE")
    return length


def parse_request_payload(content_type: str, raw: bytes) -> dict:
    """Parse JSON or URL-encoded form request body.

    Raises SaveError('INVALID_VALUE', '요청을 읽을 수 없어요') on malformed input.
    """
    from .ledger_store import SaveError

    if "application/json" in (content_type or ""):
        try:
            return json.loads(raw.decode("utf-8") or "{}")
        except (ValueError, UnicodeDecodeError):
            raise SaveError("INVALID_VALUE", "요청을 읽을 수 없어요")
    try:
        form = parse_qs(raw.decode("utf-8"), keep_blank_values=True)
    except UnicodeDecodeError:
        raise SaveError("INVALID_VALUE", "요청을 읽을 수 없어요")
    return {k: (v if len(v) > 1 else v[0]) for k, v in form.items()}


def validate_year_param(
    year_str: Optional[str],
    default: int = 2026,
    min_year: int = 2000,
    max_year: int = 2100,
) -> int:
    """Validate year parameter for card transaction queries."""
    val = default if year_str is None else year_str
    try:
        year = int(val)
    except (TypeError, ValueError):
        raise ValueError("year must be an integer")
    if year < min_year or year > max_year:
        raise ValueError("year out of range")
    return year


def validate_month_param(month_str: Optional[str]) -> Optional[int]:
    """Validate month parameter for card transaction queries."""
    if month_str is None:
        return None
    try:
        month = int(month_str)
    except (TypeError, ValueError):
        raise ValueError("month must be an integer")
    if month < 1 or month > 12:
        raise ValueError("month must be 1-12")
    return month


def validate_cursor_param(cursor: Optional[str]) -> Optional[str]:
    """Validate cursor parameter format ('date|id') for card transaction queries."""
    if cursor is None:
        return None
    parts = cursor.split("|", 1)
    if len(parts) != 2 or not parts[0] or not parts[1]:
        raise ValueError("invalid cursor format")
    c_date, c_id = parts
    if not (c_date and c_date[0:4].isdigit() and len(c_date) >= 10):
        raise ValueError("invalid cursor date")
    return cursor


def platform_probe(path: str, *, store: Any, db_path: str = "") -> Tuple[int, dict]:
    """Answer a platform probe: no auth, no data, a real answer either way.

    `/healthz` never fails while the process is running, which is what a
    restart policy needs. `/readyz` fails when the working database is
    missing or has no schema, so a platform stops sending traffic to a
    process that cannot answer a request -- and the reason is named in a
    fixed vocabulary rather than by its output.
    """
    body = {"ok": True, "probe": path.lstrip("/")}
    if path == "/healthz":
        return 200, body
    problems = []
    if store is None:
        problems.append("store_not_bound")
    else:
        db_path = str(getattr(store, "path", db_path))
        try:
            conn = store.conn
            tables = {r[0] for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'")}
        except Exception:  # noqa: BLE001 - an unusable store is not ready
            tables = set()
            problems.append("database_unreadable")
        for required in ("board_rows", "trip_tabs"):
            if required not in tables:
                problems.append(f"missing_table:{required}")
    body["ok"] = not problems
    if problems:
        body["problems"] = sorted(problems)
    return (200 if body["ok"] else 503), body


def send_json(
    handler: Any,
    value: dict,
    code: int = 200,
    extra_headers: Optional[dict] = None,
) -> None:
    """Send JSON response envelope with no-store caching."""
    data = json.dumps(value, ensure_ascii=False).encode("utf-8")
    handler.send_response(code)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Content-Length", str(len(data)))
    handler.send_header("Cache-Control", "no-store")
    for header_name, header_value in (extra_headers or {}).items():
        handler.send_header(header_name, header_value)
    handler.end_headers()
    handler.wfile.write(data)


def send_html(
    handler: Any,
    text: str,
    code: int = 200,
    *,
    wrap_document_fn: Optional[Callable[[str, str, int], str]] = None,
    decorate_fn: Optional[Callable[[str], str]] = None,
    access_enforcement: bool = False,
    has_session: bool = False,
) -> None:
    """Send HTML response envelope with social preview decoration and site shell."""
    if decorate_fn is not None:
        text = decorate_fn(text)
    if (not access_enforcement or has_session) and wrap_document_fn is not None:
        text = wrap_document_fn(text, getattr(handler, "path", "/"), status=code)
    data = text.encode("utf-8")
    try:
        handler.send_response(code)
        handler.send_header("Content-Type", "text/html; charset=utf-8")
        handler.send_header("Content-Length", str(len(data)))
        handler.send_header("Cache-Control", "no-store")
        handler.end_headers()
        handler.wfile.write(data)
    except (ConnectionAbortedError, ConnectionResetError, BrokenPipeError):
        handler.close_connection = True


def send_bytes(
    handler: Any,
    body: bytes,
    content_type: str,
    cache_control: str = "public, max-age=604800",
) -> None:
    """Send binary response envelope with caching header."""
    handler.send_response(200)
    handler.send_header("Content-Type", content_type)
    handler.send_header("Content-Length", str(len(body)))
    handler.send_header("Cache-Control", cache_control)
    handler.end_headers()
    handler.wfile.write(body)


def send_redirect(
    handler: Any,
    location: str,
    cookie: Optional[str] = None,
    code: int = 303,
    cache_control: str = "no-store",
    referrer_policy: str = "no-referrer",
) -> None:
    """Send HTTP redirect envelope."""
    handler.send_response(code)
    handler.send_header("Location", location)
    if cookie:
        handler.send_header("Set-Cookie", cookie)
    handler.send_header("Cache-Control", cache_control)
    if referrer_policy:
        handler.send_header("Referrer-Policy", referrer_policy)
    handler.end_headers()


def send_auth_page(
    handler: Any,
    title: str,
    body: str,
    code: int = 200,
    refusal: str = "",
    *,
    meta_header: str = "",
) -> None:
    """Send minimal authentication/refusal HTML page."""
    marker = f'<p data-refusal="{refusal}"></p>' if refusal else ""
    data = (f"<!doctype html><html lang='ko'><head><meta charset=utf-8><title>{title}</title>"
            f"{meta_header}</head><body>{marker}{body}</body></html>").encode("utf-8")
    handler.send_response(code)
    handler.send_header("Content-Type", "text/html; charset=utf-8")
    handler.send_header("Content-Length", str(len(data)))
    handler.send_header("Cache-Control", "no-store")
    handler.send_header("Referrer-Policy", "no-referrer")
    handler.end_headers()
    handler.wfile.write(data)


def send_form_error(
    handler: Any,
    code: str,
    message: str,
    payload: dict,
    return_to: str,
    row_id: str = "",
    *,
    local_path_fn: Callable[[str], str],
    find_row_fn: Callable[[str], Tuple[Any, Any]],
    valid_tab_ids_fn: Callable[[], Any],
    default_tab_fn: Callable[[], str],
    editable_fields_fn: Callable[[str, str, bool], Tuple[Any, Any]],
    status_map: Dict[str, int],
    page_fn: Callable[..., Any],
    render_fn: Callable[[Any], str],
) -> None:
    """Answer a refused plain form post with the screen, in HTML."""
    target = local_path_fn(return_to) or "/board"
    parts = urlsplit(target)
    query = parse_qs(parts.query)
    row_id = row_id or ""
    tab = query.get("tab", [""])[0] or ""
    if row_id and not tab:
        _kind, found = find_row_fn(row_id)
        if found is not None:
            tab = found.get("display_tab_id") or ""
    if tab not in ("unclassified", "refunds") and tab not in valid_tab_ids_fn():
        tab = default_tab_fn()
    draft = {}
    if row_id and payload:
        kind, current = find_row_fn(row_id)
        if current is not None:
            allowed, _fixed = editable_fields_fn(
                kind, current.get("source_kind", ""),
                bool(current.get("is_allocation")))
            for key, value in payload.items():
                if key not in allowed:
                    continue
                if value is None or isinstance(value, (str, int, float)):
                    draft[key] = "" if value is None else str(value)
    fragment = page_fn(
        tab, query.get("q", [""])[0], query.get("kind", [""])[0],
        row_id, error=f"{code}: {message}",
        archived=query.get("arch", [""])[0], draft=draft, back=target)
    body = render_fn(fragment).encode("utf-8")
    handler.send_response(status_map.get(code, 422))
    handler.send_header("Content-Type", "text/html; charset=utf-8")
    handler.send_header("Content-Length", str(len(body)))
    handler.send_header("Cache-Control", "no-store")
    handler.send_header("Referrer-Policy", "no-referrer")
    handler.end_headers()
    handler.wfile.write(body)


def refuse_amount(
    handler: Any,
    is_form: bool,
    payload: dict,
    row_id: str = "",
    *,
    send_form_error_fn: Callable[..., None],
    send_json_fn: Callable[..., None],
) -> None:
    """Answer an invalid amount refusal either as HTML form error or JSON 422."""
    if is_form:
        send_form_error_fn(
            "INVALID_VALUE", "금액은 정수 원화로 입력해 주세요",
            payload, str(payload.get("return_to") or ""),
            row_id)
        return
    send_json_fn({
        "code": "INVALID_VALUE",
        "field": "amount_krw",
        "message": "금액은 정수 원화로 입력해 주세요",
    }, code=422)
