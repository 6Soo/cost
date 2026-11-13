"""High confidence evidence and a persisted travel assignment are distinct."""
from pathlib import Path

def test_high_inference_without_persisted_trip_is_not_shown_as_assigned():
    source=(Path(__file__).resolve().parents[1]/"card_flow.py").read_text(encoding="utf-8")
    # ORIGIN refactor(08486b88): the stale high-inference display is gated on the persisted basis map, not source=='inference'.
    assert "if tid in basis_by_card:" in source
    assert "if '추론 배정 · 높음' in basis_text:" in source
    assert "과거 추론 근거는 높음이지만 현재 여행 배정값이 비어 있습니다." in source
    assert "재분류 시 유효한 여행 ID가 검증되면 자동 배정합니다." in source
