"""Server-rendered upload document exposes query coverage without executing writes."""
from webapp.card_flow import page


def test_upload_document_contains_summary_and_accessible_form_builder():
    html = page('synthetic-csrf')
    assert 'id="coverage-summary"' in html
    assert 'function appendCoverageForm' in html
    assert '조회 시작일' in html and '조회 종료일' in html
    assert '관리 시작일 (선택)' in html


def test_page_contains_no_source_hash_as_coverage_id_protocol():
    html = page('synthetic-csrf')
    assert 'coverage_id: hash' not in html
    assert "replaceWith('<span" not in html
