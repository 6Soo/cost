"""Asset ownership module for shared site shell and theme (RF-201/203).

Owns static CSS and JS loaded once from disk at module import time,
ensuring zero extra disk I/O on per-request rendering.
"""

from pathlib import Path

STATIC_DIR = Path(__file__).resolve().parent / "static"
CSS_DIR = STATIC_DIR / "css"
JS_DIR = STATIC_DIR / "js"

_SHELL_CSS_PATH = CSS_DIR / "site_shell.css"
_SHELL_JS_PATH = JS_DIR / "site_shell.js"
_THEME_CSS_PATH = CSS_DIR / "site_theme.css"
_THEME_JS_PATH = JS_DIR / "site_theme.js"

SHELL_STYLE = _SHELL_CSS_PATH.read_text(encoding="utf-8")
SHELL_SCRIPT = _SHELL_JS_PATH.read_text(encoding="utf-8")
THEME_STYLE = _THEME_CSS_PATH.read_text(encoding="utf-8")
THEME_BOOTSTRAP = _THEME_JS_PATH.read_text(encoding="utf-8")
