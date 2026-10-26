"""Synthetic structural regression for expense/OTA visual consistency (no live data)."""
from webapp import ota_payment_review
from webapp import card_flow


def test_ota_owner_review_uses_semantic_tokens_and_collapsible_evidence():
    doc = ota_payment_review.render_import_section('synthetic-token')
    assert 'id="ota-review"' in doc
    assert 'class="ota-more"' in doc
    assert '예약·결제 근거 자세히 보기' in doc
    assert 'var(--shell-paper' in doc
    assert 'var(--shell-ink' in doc
    assert 'var(--shell-line' in doc
    assert 'var(--shell-accent' in doc
    assert '@media(width < 760px)' in doc
    assert '#ota-review .ota-overview' in doc
    assert '#ota-review button:focus-visible' in doc
    assert '금융 상태 보기' in doc
    assert 'data-preview=' in doc  # Existing guarded actions stay wired.


def test_kakao_merchant_key_is_read_only_review_classification():
    assert card_flow._refund_merchant_key("카카오T가승인_유페이") == "카카오택시"
    assert card_flow._refund_merchant_key("카카오T일반택시(법인)_0") == "카카오택시"
    assert card_flow._refund_merchant_key("카카오모빌리티 택시요금") == "카카오택시"
    assert card_flow._refund_merchant_key("카카오T대리") != "카카오택시"
    assert card_flow._refund_merchant_key("카카오페이") != "카카오택시"


def test_expense_cleanup_styles_keep_collapsed_refund_drilldown():
    import inspect
    src = inspect.getsource(card_flow)
    assert "cleanup-merchant-compare" in src
    assert "cleanup-kakao-inventory" in src
    assert "cleanup-compare-row" in src
    assert "원결제·취소 근거 자세히 보기" in src
    assert "aria-label='정리할 지출'" in src
