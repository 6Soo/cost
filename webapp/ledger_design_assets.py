"""Assets and static resources for the ledger design layer (RF-201/202).

Pure asset ownership module: manages font files, OTA brand icons, design tokens,
and modular CSS/JS stylesheets. Assets are loaded once at module import and
cached in memory so no disk I/O occurs on per-request rendering.
"""

from pathlib import Path

# Paths to static asset directories
STATIC_DIR = Path(__file__).resolve().parent / "static"
FONT_DIR = STATIC_DIR / "fonts"
OTA_DIR = STATIC_DIR / "ota"
CSS_DIR = STATIC_DIR / "css"
JS_DIR = STATIC_DIR / "js"

# Explicit allowlists for security and path-traversal prevention
OTA_ASSETS = {
    "agoda.png": "image/png",
    "trip.png": "image/png",
}

STATIC_ASSETS = {
    "PretendardVariable.woff2": "font/woff2",
    "OFL.txt": "text/plain; charset=utf-8",
}

FONT_FAMILY = "Pretendard Variable"

# Load CSS & JS assets once into memory to avoid per-request disk reads
_CSS_PATH = CSS_DIR / "ledger_design.css"
_JS_PATH = JS_DIR / "ledger_design.js"

STYLE = _CSS_PATH.read_text(encoding="utf-8")
SCRIPT = _JS_PATH.read_text(encoding="utf-8")

STYLE_BYTES = STYLE.encode("utf-8")
SCRIPT_BYTES = SCRIPT.encode("utf-8")

# In-memory caches for static font and image assets (zero disk I/O on hot paths)
_STATIC_CACHE: dict[str, tuple[bytes, str]] = {}
_OTA_CACHE: dict[str, tuple[bytes, str]] = {}


def static_asset(name: str) -> tuple[bytes, str] | None:
    """Return (bytes, content_type) for an allowed font asset, or None."""
    if not isinstance(name, str) or name not in STATIC_ASSETS:
        return None
    cached = _STATIC_CACHE.get(name)
    if cached is not None:
        return cached
    path = FONT_DIR / name
    if path.parent.resolve() != FONT_DIR.resolve():
        return None
    if not path.is_file():
        return None
    result = (path.read_bytes(), STATIC_ASSETS[name])
    _STATIC_CACHE[name] = result
    return result


def ota_asset(name: str) -> tuple[bytes, str] | None:
    """Return (bytes, content_type) for an allowed OTA image asset, or None."""
    if not isinstance(name, str) or name not in OTA_ASSETS:
        return None
    cached = _OTA_CACHE.get(name)
    if cached is not None:
        return cached
    path = OTA_DIR / name
    if not path.is_file() or path.resolve().parent != OTA_DIR.resolve():
        return None
    result = (path.read_bytes(), OTA_ASSETS[name])
    _OTA_CACHE[name] = result
    return result


def css_asset(name: str = "ledger_design.css") -> tuple[bytes, str] | None:
    """Return (bytes, 'text/css; charset=utf-8') for a known CSS asset."""
    if name == "ledger_design.css":
        return STYLE_BYTES, "text/css; charset=utf-8"
    path = CSS_DIR / name
    if path.parent.resolve() != CSS_DIR.resolve() or not path.is_file():
        return None
    return path.read_bytes(), "text/css; charset=utf-8"


def js_asset(name: str = "ledger_design.js") -> tuple[bytes, str] | None:
    """Return (bytes, 'text/javascript; charset=utf-8') for a known JS asset."""
    if name == "ledger_design.js":
        return SCRIPT_BYTES, "text/javascript; charset=utf-8"
    path = JS_DIR / name
    if path.parent.resolve() != JS_DIR.resolve() or not path.is_file():
        return None
    return path.read_bytes(), "text/javascript; charset=utf-8"
