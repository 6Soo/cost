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


def test_card_management_is_primary_and_gap_upload_is_contextual():
    html = page('synthetic-csrf')
    assert 'id="card-coverage-management"' in html
    assert 'id="coverage-overview"' in html
    assert 'id="coverage-new-file"' in html
    assert 'id="coverage-upload-target"' in html
    assert 'function beginCoverageGap(card,period)' in html
    assert '이 기간 자료 추가' in html
    assert '관리 시작일 설정' in html
    assert 'coverage-summary' in html
    assert '조회기간이 실제로 확인' in html
    assert html.index('id="card-coverage-management"') < html.index('id="newupload"')
    assert '카드별 조회 기간</summary>' not in html


def test_card_management_uses_text_nodes_for_file_names_and_preserves_query_boundaries():
    html = page('synthetic-csrf')
    assert 'const coverageNode=(tag,value,cls)' in html
    assert 'coverageUploadTarget' in html
    assert 'ev.card_id===target.card_id&&ev.date_basis===target.date_basis' in html
    assert '기간을 자동으로 사실로 채우지 않습니다.' in html
    assert '거래 발생기간:' in html
