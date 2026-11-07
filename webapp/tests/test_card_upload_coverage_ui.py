"""Owner card-history workspace reuses upload and coverage APIs without a second page."""
from webapp.card_history_assets import SCRIPT
from webapp.cards_all import _workspace_html


def test_card_history_owner_workspace_contains_upload_and_coverage_controls():
    html = _workspace_html({}, owner=True, csrf='synthetic-csrf')
    assert "id='card-upload-open'" in html and "id='card-coverage-open'" in html
    assert "id='card-upload-files'" in html and 'multiple' in html
    assert "id='card-coverage-summary'" in html
    assert 'X-CSRF-Token' in SCRIPT
    assert '/api/imports/upload-batch' in SCRIPT
    assert '/coverage/confirm' not in SCRIPT
    assert '/api/cards/coverage/summary' in SCRIPT
    assert "data-csrf='synthetic-csrf'" in html


def test_card_history_workspace_is_absent_for_non_owners():
    html = _workspace_html({}, owner=False, csrf='')
    assert "id='card-upload-open'" not in html
    assert 'data-card-history-workspace' not in html
    assert 'synthetic-csrf' not in html


def test_legacy_transaction_workspace_uses_card_detail_heading():
    from webapp.card_flow import page
    html = page('synthetic-csrf')
    assert '<h1>카드 거래 상세</h1>' in html
    assert 'aria-label="카드 거래 상세 도구"' in html
    assert '<h1>지출 정리</h1>' not in html
    assert 'coverage_id: hash' not in html
    assert "replaceWith('<span" not in html


def test_unverified_coverage_can_be_opened_for_explicit_review():
    """The dashboard exposes transaction-date gaps without a query-period form."""
    assert "data.coverage_state === 'needs_transactions'" in SCRIPT
    assert "거래일자 공백" in SCRIPT
    assert "조회기간" not in SCRIPT


def test_pending_coverage_renders_grouped_details_instead_of_23_open_rows():
    assert "'카드 식별 확인 필요'" in SCRIPT
    assert "' (표시용)'" in SCRIPT
    assert "for (const [label, files] of groups)" in SCRIPT
    assert "renderFile(file, group)" in SCRIPT
    assert "'거래일자가 없는 파일 '" in SCRIPT
    assert "'처리 결과'" in SCRIPT
    from webapp.cards_all import CARD_ALL_STYLE
    assert ".card-coverage-file-actions" in CARD_ALL_STYLE
    assert ".card-coverage-review" in CARD_ALL_STYLE
