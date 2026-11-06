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
    assert '/coverage/confirm' in SCRIPT
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
