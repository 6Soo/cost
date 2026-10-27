"""Contract: OTA review starts closed and does not fetch until requested."""
from webapp.ota_payment_review import render_import_section


def test_ota_review_is_lazy_and_expandable():
    html = render_import_section("csrf-test")
    assert '<details id="ota-review"' in html
    assert '<summary id="ota-title"' in html
    assert "if(root.open)loadSnapshot();" in html
    assert "if(!root.open)return;" in html
    assert "location.hash==='#ota-review'" in html
    assert "root.addEventListener('toggle'" in html
    assert "/api/imports/ota" in html
    assert '<div id="ota-events"></div>' in html
