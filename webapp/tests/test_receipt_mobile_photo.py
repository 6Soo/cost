"""Safari image capture regression: no customer photos or external model calls."""
from webapp import receipt_review


def test_receipt_page_can_upload_iphone_heic_and_multiple_photos():
    html = receipt_review.render_html(
        {"images": [], "candidates": [], "holds": []},
        csrf="test-csrf",
        trips=[{"id": "test-trip", "name": "합성 여행"}],
    )
    assert "type='file' multiple accept='image/*,application/pdf,.pdf'" in html
    assert "normalizeReceiptImage=async file" in html
    assert "canvas.toBlob(resolve,'image/jpeg',quality)" in html
    assert "await normalizeReceiptImage(file)" in html
    assert "for(const file of files)" in html
    assert "id='pdf-file'" not in html
    assert "id='upload-results'" in html
    assert "/api/receipts/pdf" in html
    assert "id='selected-trip'" in html
    assert "id='status' role='status' aria-live='polite'" in html
    assert html.count("id='status'") == 1


def test_receipt_upload_remains_owner_and_csrf_scoped():
    html = receipt_review.render_html(
        {"images": [], "candidates": [], "holds": []},
        csrf="synthetic-only",
        trips=[],
    )
    assert "X-CSRF-Token" in html
    assert "/api/receipts/image" in html


def test_disabled_vision_does_not_offer_an_unusable_analysis_checkbox(monkeypatch):
    monkeypatch.setattr(receipt_review.opencode_receipt_vision, 'enabled', lambda: False)
    html = receipt_review.render_html(
        {'images': ['a' * 64], 'candidates': [], 'holds': []}, csrf='test', trips=[])
    main = html.split('<main>', 1)[1].split('</main>', 1)[0]
    assert "class='photo-check'" not in main
    assert "data-manual-image=" in main
