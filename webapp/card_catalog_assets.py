"""Asset ownership module for card catalog (RF-201).

Owns CATALOG_STYLE and CATALOG_SCRIPT loaded once from disk at module import time,
ensuring zero extra disk I/O on per-request rendering.
"""

from pathlib import Path

STATIC_DIR = Path(__file__).resolve().parent / "static"
CSS_DIR = STATIC_DIR / "css"
JS_DIR = STATIC_DIR / "js"

_CSS_PATH = CSS_DIR / "card_catalog.css"
_JS_PATH = JS_DIR / "card_catalog.js"

CATALOG_STYLE = _CSS_PATH.read_text(encoding="utf-8")
CATALOG_SCRIPT = _JS_PATH.read_text(encoding="utf-8")
