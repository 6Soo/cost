"""Safari image capture regression: no customer photos or external model calls."""
from webapp import receipt_review


def test_receipt_page_can_upload_iphone_heic_and_multiple_photos():
    html = receipt_review.render_html(
        {"images": [], "candidates": [], "holds": []},
        csrf="test-csrf",
        trips=[{"id": "test-trip", "name": "합성 여행"}],
    )
    assert "type='file' multiple accept='image/*'" in html
    assert "normalizeReceiptImage=async file" in html
    assert "canvas.toBlob(resolve,'image/jpeg',quality)" in html
    assert "body:await normalizeReceiptImage(f)" in html
    assert "for(const f of files)" in html
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
    assert "Muse로 영수증 자동 찾기" not in html if not __import__(
        "app.opencode_receipt_vision", fromlist=["enabled"]
    ).enabled() else True
