"""Asset ownership module for shared site shell and theme (RF-201/203).

Owns static CSS and JS loaded once from disk at module import time,
ensuring zero extra disk I/O on per-request rendering.
"""

from pathlib import Path
import json

from . import ui_icons

STATIC_DIR = Path(__file__).resolve().parent / "static"
CSS_DIR = STATIC_DIR / "css"
JS_DIR = STATIC_DIR / "js"

_SHELL_CSS_PATH = CSS_DIR / "site_shell.css"
_TOKENS_CSS_PATH = CSS_DIR / "tokens.css"
_COMPONENTS_CSS_PATH = CSS_DIR / "components.css"
_SHELL_JS_PATH = JS_DIR / "site_shell.js"
_THEME_CSS_PATH = CSS_DIR / "site_theme.css"
_THEME_JS_PATH = JS_DIR / "site_theme.js"

TOKENS_STYLE = _TOKENS_CSS_PATH.read_text(encoding="utf-8")
COMPONENTS_STYLE = _COMPONENTS_CSS_PATH.read_text(encoding="utf-8")
SHELL_STYLE = TOKENS_STYLE + "\n" + COMPONENTS_STYLE + "\n" + _SHELL_CSS_PATH.read_text(encoding="utf-8")
SHELL_SCRIPT = _SHELL_JS_PATH.read_text(encoding="utf-8").replace(
    '__ACTION_ICONS__', json.dumps(ui_icons.ICONS, ensure_ascii=True))
THEME_STYLE = _THEME_CSS_PATH.read_text(encoding="utf-8")
THEME_BOOTSTRAP = _THEME_JS_PATH.read_text(encoding="utf-8")
