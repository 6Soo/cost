"""Authenticated, same-origin serving for the opt-in React UI.

Only the build output is reachable. Business reads and writes remain in the
existing authenticated APIs; this module never projects ledger data into HTML.
"""
from __future__ import annotations

import mimetypes
import os
from pathlib import Path
from urllib.parse import parse_qs, unquote


DIST = Path(__file__).resolve().parents[1] / "frontend" / "dist"
PRIMARY_ROUTES = frozenset({
    "/", "/trips", "/board", "/cards/all", "/ota", "/flight-passengers",
    "/receipts", "/access", "/access/admin", "/access/admin/profile",
    "/google-ledger", "/review", "/participants", "/participants/insurance-match",
    "/reserve-links", "/export", "/expense", "/expense/new", "/income", "/income/new", "/rules",
})
_ASSET_TYPES = {
    ".js": "text/javascript; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".woff2": "font/woff2",
    ".woff": "font/woff",
    ".svg": "image/svg+xml",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
    ".ico": "image/x-icon",
}


def owns_route(path: str) -> bool:
    return path == "/ui" or path.startswith("/ui/")


def dispatch_primary(handler, parsed, *, board, dist: Path | None = None) -> bool:
    """Serve browser pages at their established URLs, preserving non-page clients.

    Old form/detail links explicitly request legacy=1; their original handlers
    still enforce the same login, role and financial protections.
    """
    if parsed.path not in PRIMARY_ROUTES:
        return False
    # Hosted composition enables the primary UI. Embedded legacy servers retain
    # their existing renderer for integrations and rollback verification.
    if os.environ.get("WEBLEDGER_PRIMARY_UI") != "1":
        return False
    if "text/html" not in handler.headers.get("Accept", "").lower():
        return False
    query = parse_qs(parsed.query)
    if query.get("legacy") == ["1"]:
        return False
    # Existing participant-name/alias/trip correction links must keep their
    # full form. The new participant linking tab uses view=links explicitly.
    if parsed.path == "/participants" and "trip" in query and "view" not in query:
        return False
    # Unauthenticated development-mode fixtures keep their original renderer.
    # Production sessions and their refusal handling use the same gate as /ui/.
    if not board.ACCESS_ENFORCEMENT:
        return False
    return dispatch(handler, parsed._replace(path="/ui/"), board=board, dist=dist,
                    primary_path=parsed.path)


def _primary_tab_visible(board, session, tab_id: str) -> bool:
    """Check a primary board deep link without revealing other viewers' trips."""
    if tab_id == "refunds":
        return True
    is_owner = getattr(board, "is_owner_session", None)
    owner = bool(is_owner(session)) if callable(is_owner) else False
    if tab_id == "unclassified":
        return owner
    store_factory = getattr(board, "_active_store", None)
    store = store_factory() if callable(store_factory) else None
    if store is None or not hasattr(store, "list_trips"):
        return False
    trips = [trip for trip in store.list_trips(include_archived=True)
             if not trip.get("deleted")]
    existing = {str(trip.get("tab_id") or "") for trip in trips}
    if owner:
        return tab_id in existing
    access_factory = getattr(board, "access_store", None)
    access = access_factory() if callable(access_factory) else None
    if access is None:
        return False
    allowed = set(access.visible_tabs(session.user_id))
    return tab_id in existing and tab_id in allowed


def dispatch(handler, parsed, *, board, dist: Path | None = None,
             primary_path: str | None = None) -> bool:
    """Serve a UI request after validating the actual board session.

    ``board`` is the ledger_board module, whose require_session function is also
    used by the protected business routes. AccessError goes to its usual refusal
    handler. Enforcement-off development mode never grants anonymous access here.
    """
    if not owns_route(parsed.path):
        return False
    session = board.require_session(handler.headers, handler._cookies())
    if session is None:
        handler._send_json({"code": "AUTH_REQUIRED"}, code=401)
        return True
    if primary_path == "/board":
        query = parse_qs(parsed.query, keep_blank_values=True)
        tab_id = (query.get("tab") or query.get("trip") or [""])[0]
        if tab_id and not _primary_tab_visible(board, session, str(tab_id)):
            handler._send_json({"code": "NOT_FOUND"}, code=404)
            return True
    if parsed.path == "/ui":
        handler.send_response(308)
        handler.send_header("Location", "/ui/" + ("?" + parsed.query if parsed.query else ""))
        handler.send_header("Cache-Control", "no-store")
        handler.send_header("Content-Length", "0")
        handler.end_headers()
        return True

    root = (dist if dist is not None else DIST).resolve()
    relative = unquote(parsed.path[len("/ui/"):])
    # Reject Windows separators, drive syntax, nulls and dot traversal before
    # resolving; resolve additionally contains symlink/junction escapes.
    if any(part in (".", "..") for part in relative.split("/")) or any(
        char in relative for char in ("\\", ":", "\x00")
    ) or relative.startswith("/"):
        handler._send_json({"code": "NOT_FOUND"}, code=404)
        return True
    target = (root / relative).resolve()
    if not target.is_relative_to(root):
        handler._send_json({"code": "NOT_FOUND"}, code=404)
        return True
    suffix = target.suffix.lower()
    is_asset = bool(suffix) and relative != "index.html"
    if is_asset and suffix not in _ASSET_TYPES:
        handler._send_json({"code": "NOT_FOUND"}, code=404)
        return True
    if not is_asset and relative not in ("", "index.html"):
        page_path = "/" + relative
        if page_path not in PRIMARY_ROUTES:
            handler._send_json({"code": "NOT_FOUND"}, code=404)
            return True
    if not is_asset:
        target = root / "index.html"
    if not target.is_file():
        handler._send_json({"code": "UI_ASSET_MISSING" if is_asset else "UI_NOT_BUILT",
                            "message": "화면 파일을 준비하지 못했어요"},
                           code=404 if is_asset else 503)
        return True
    content = target.read_bytes()
    content_type = _ASSET_TYPES.get(suffix) if is_asset else "text/html; charset=utf-8"
    handler.send_response(200)
    handler.send_header("Content-Type", content_type or mimetypes.guess_type(target.name)[0])
    handler.send_header("Content-Length", str(len(content)))
    handler.send_header("Cache-Control", "no-store")
    handler.send_header("X-Content-Type-Options", "nosniff")
    handler.send_header("Referrer-Policy", "same-origin")
    handler.end_headers()
    handler.wfile.write(content)
    return True
