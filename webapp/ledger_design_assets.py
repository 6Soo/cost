"""Assets and static stylesheets for the ledger design layer (RF-201/202).

Pure asset ownership module: owns STYLE and SCRIPT loaded once from disk
at module import time, ensuring zero extra disk I/O on per-request rendering.
"""

from pathlib import Path

STATIC_DIR = Path(__file__).resolve().parent / "static"
CSS_DIR = STATIC_DIR / "css"
JS_DIR = STATIC_DIR / "js"

_CSS_PATH = CSS_DIR / "ledger_design.css"
_TOKENS_CSS_PATH = CSS_DIR / "tokens.css"
_COMPONENTS_CSS_PATH = CSS_DIR / "components.css"
_JS_PATH = JS_DIR / "ledger_design.js"

TOKENS_STYLE = _TOKENS_CSS_PATH.read_text(encoding="utf-8")
COMPONENTS_STYLE = _COMPONENTS_CSS_PATH.read_text(encoding="utf-8")
STYLE = TOKENS_STYLE + "\n" + COMPONENTS_STYLE + "\n" + _CSS_PATH.read_text(encoding="utf-8")
SCRIPT = _JS_PATH.read_text(encoding="utf-8")
