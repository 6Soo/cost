from pathlib import Path

import pytest


@pytest.fixture
def dist(tmp_path: Path) -> Path:
    """Minimal disposable UI build for tests importing the shared HTTP fixture."""
    root = tmp_path / "dist"
    (root / "assets").mkdir(parents=True)
    (root / "index.html").write_text('<main id="root"></main>', encoding="utf-8")
    (root / "assets" / "app.js").write_text("export {}", encoding="utf-8")
    return root
