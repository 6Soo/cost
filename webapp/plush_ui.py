"""Authenticated, same-origin serving for the opt-in React UI.

Only the build output is reachable. Business reads and writes remain in the
existing authenticated APIs; this module never projects ledger data into HTML.
"""
from __future__ import annotations

import mimetypes
from pathlib import Path
from urllib.parse import unquote


DIST = Path(__file__).resolve().parents[1] / "frontend" / "dist"
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


def dispatch(handler, parsed, *, board, dist: Path | None = None) -> bool:
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
