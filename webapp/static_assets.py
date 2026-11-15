"""Content-hashed static CSS/JS bundles shared by every page.

The bundles are built once at import. A page references `/static/<kind>/<name>.<hash8>.<ext>`;
the hash changes whenever the bytes change, so the URL can be cached for a year.
Nothing here reads a store, so these requests are answered outside `store_lock`.
"""

import hashlib
import re
from pathlib import Path

from . import ledger_design_assets, site_assets

_STATIC_DIR = Path(__file__).resolve().parent / "static"
_TYPES = {"css": "text/css; charset=utf-8", "js": "text/javascript; charset=utf-8"}
_PLAIN_DIRS = {"css": _STATIC_DIR / "css", "js": _STATIC_DIR / "js"}
_HASHED_RE = re.compile(r"^/static/(css|js)/([a-z_]+)\.([0-9a-f]{8})\.(css|js)$")
_PLAIN_RE = re.compile(r"^/static/(css|js)/([a-z_]+)\.(css|js)$")

_BUNDLES = {
    ("css", "ledger_design"): ledger_design_assets.STYLE,
    ("js", "ledger_design"): ledger_design_assets.SCRIPT,
    ("css", "site_shell"): site_assets.SHELL_STYLE + site_assets.THEME_STYLE,
    ("js", "site_shell"): site_assets.SHELL_SCRIPT,
}
_BODIES = {key: text.encode("utf-8") for key, text in _BUNDLES.items()}
_HASHES = {key: hashlib.sha256(body).hexdigest()[:8] for key, body in _BODIES.items()}

IMMUTABLE = "public, max-age=31536000, immutable"


def url(kind: str, name: str) -> str:
    return f"/static/{kind}/{name}.{_HASHES[(kind, name)]}.{kind}"


def link(name: str, element_id: str = "") -> str:
    ident = f' id="{element_id}"' if element_id else ""
    return f'<link{ident} rel="stylesheet" href="{url("css", name)}">'


def script(name: str) -> str:
    return f'<script src="{url("js", name)}"></script>'


def _respond(handler, code: int, body: bytes, content_type: str, cache: str) -> None:
    handler.send_response(code)
    handler.send_header("Content-Type", content_type)
    handler.send_header("Content-Length", str(len(body)))
    handler.send_header("Cache-Control", cache)
    handler.send_header("X-Content-Type-Options", "nosniff")
    handler.end_headers()
    handler.wfile.write(body)


def owns_path(path: str) -> bool:
    return path.startswith("/static/")


def dispatch(handler, path: str) -> bool:
    """Answer every /static/ request, including misses, without touching a store."""
    if not owns_path(path):
        return False
    hashed = _HASHED_RE.match(path)
    if hashed:
        kind, name, digest, ext = hashed.groups()
        key = (kind, name)
        if kind == ext and key in _BODIES:
            # An old page naming a retired hash still gets working bytes, but never a long cache.
            cache = IMMUTABLE if digest == _HASHES[key] else "no-store"
            _respond(handler, 200, _BODIES[key], _TYPES[kind], cache)
            return True
    plain = _PLAIN_RE.match(path)
    if plain and plain.group(1) == plain.group(3):
        kind, name, _ = plain.groups()
        file = _PLAIN_DIRS[kind] / f"{name}.{kind}"
        if file.is_file():
            # Unhashed names (the `@import` in older page templates) must revalidate soon.
            _respond(handler, 200, file.read_bytes(), _TYPES[kind], "public, max-age=300")
            return True
    _respond(handler, 404, b"Not found", "text/plain; charset=utf-8", "no-store")
    return True
