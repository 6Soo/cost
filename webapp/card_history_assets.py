"""Card-history-only workspace assets, loaded once per process."""
from pathlib import Path

_JS = Path(__file__).resolve().parent / "static" / "js" / "card_history_workspace.js"
SCRIPT = _JS.read_text(encoding="utf-8")
