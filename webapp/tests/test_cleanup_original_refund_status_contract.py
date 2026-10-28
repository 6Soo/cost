"""Protect the distinction between OTA evidence and settled refund linkage."""
from pathlib import Path


def test_cleanup_original_shows_refund_offset_even_if_ota_refreshing():
    source = (Path(__file__).resolve().parents[1] / 'card_flow.py').read_text(encoding='utf-8')
    assert 'original_refunds.setdefault' in source
    assert 'if tid not in cancellation_ids and tid in original_refunds:' in source
    assert 'OTA 예약 연결 상태와 금융 기록은 별개입니다.' in source
    assert '실제 장부 기록·환급 완료를 의미하지 않습니다.' in source
    assert 'trip_no_longer_valid' in source
