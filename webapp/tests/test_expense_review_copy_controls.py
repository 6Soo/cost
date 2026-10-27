"""UI regression: expense review must not append per-trip Google copy buttons."""
from pathlib import Path

def test_review_table_does_not_append_unrelated_trip_copy_controls():
    source = (Path(__file__).resolve().parents[1] / "card_flow.py").read_text(encoding="utf-8")
    assert "구글 지출 7열 복사</button></p>').join('')" not in source
    # The separate quarterly export and delegated click action are retained.
    assert "quarter-copy" in source
    assert "data-google-copy" in source
    assert "비용 항목" in source or "data-edit" in source
