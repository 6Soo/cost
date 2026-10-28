"""Asset ownership module for the real review UI (RF-201/203).

Owns the static review document template loaded once from disk at module import time,
ensuring zero extra disk I/O on per-request rendering.
"""

from pathlib import Path

TEMPLATES_DIR = Path(__file__).resolve().parent / "static" / "templates"
TEMPLATE_PATH = TEMPLATES_DIR / "real_review.html"

_DOCUMENT = TEMPLATE_PATH.read_text(encoding="utf-8")
