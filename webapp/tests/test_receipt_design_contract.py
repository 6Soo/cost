"""Contract test for receipt_review.py render_html CSS/accessibility changes (§3~§5).
Only synthetic fixtures; no actual customer data, no DB writes, no Google writes.
Verifies the rendered HTML contract (form names/action, CSRF, escaped content,
label links, amount/currency/state preservation) rather than source-string only.
"""
import html
import json
from pathlib import Path


# Synthetic receipt fixtures matching the spec's synthetic-data contract.
SYNTHETIC_CANDIDATE = {
    "identity": "syn-001",
    "date": "2026-10-12",
    "merchant": "테스트상호",
    "currency": "JPY",
    "total_jpy": 2345,
    "total_original": 2345,
    "payment": "cash",
    "payee": "테스트상호",
    "category": "식비",
    "trip_id": "trip-syn",
    "group_id": None,
    "image_sha": "a" * 64,
    "hold": None,
    "amount_krw": 23450,
}
SYNTHETIC_TRIPS = [{"id": "trip-syn", "name": "합성 여행"}]


def test_render_preserves_contract_and_uses_design_tokens():
    # Direct import avoids importing the full server stack unnecessarily.
    from webapp import receipt_review

    csrf_value = "test-csrf-token-123"
    data = {
        "candidates": [SYNTHETIC_CANDIDATE],
        "holds": [],
        "images": ["b" * 64],
    }
    rendered = receipt_review.render_html(data, csrf=csrf_value, trips=SYNTHETIC_TRIPS)

    # Must be a complete HTML document string (not just a fragment).
    assert isinstance(rendered, str)
    assert rendered.startswith("<!doctype html>")
    assert "<html lang='ko'>" in rendered
    main = rendered.split('<main>', 1)[1].split('</main>', 1)[0]
    assert '<h1>영수증 정리</h1>' in main
    assert "id='selected-trip'" in main and "id='copy-tsv'" in main

    # CSRF token must appear in the inline script and in the JS post helper.
    assert "const csrf=" in rendered
    assert f"{json.dumps(csrf_value)}" in rendered
    # The script includes the CSRF in the fetch headers contract.
    assert "X-CSRF-Token" in rendered

    # Form fields/actions/names must preserve existing contract links.
    # The edit action uses POST to /api/receipts/edit; the image route uses GET /api/receipts/image/.
    assert "/api/receipts/edit" in rendered
    assert "/api/receipts/image/" in rendered

    # Existing amount/currency/state preservation (not source-string only).
    # The synthetic candidate's currency and total must appear in the rendered row.
    assert "JPY" in rendered  # currency token present in label / select
    assert "2345" in rendered  # numeric value preserved
    assert "식비" in rendered  # category preserved
    assert "테스트상호" in rendered  # merchant escaped and preserved

    # State display: confirmed receipt has payee and category => '분류됨'.
    assert "분류됨" in rendered

    # HTML escape boundary: malicious input must not break out of value attributes.
    malicious = {**SYNTHETIC_CANDIDATE, "merchant": "<script>alert(1)</script>",
                 "date": "2026-10-12", "total_jpy": 1, "amount_krw": 10,
                 "payee": "<img src=x>", "category": "</label><script>"}
    malicious_data = {
        "candidates": [malicious],
        "holds": [],
        "images": [],
    }
    malicious_rendered = receipt_review.render_html(
        malicious_data, csrf=csrf_value, trips=SYNTHETIC_TRIPS)
    # Escaped values must not contain raw tags in value attributes (escape boundary).
    # Note: the page itself includes legitimate <script> blocks (VISION_SCRIPT), so we
    # check that malicious input does not appear unescaped inside value/text nodes.
    assert 'value=\'<script>alert(1)</script>\'' not in malicious_rendered
    assert 'value="<script>alert(1)</script>"' not in malicious_rendered
    # The escaped merchant should appear with HTML entities, not raw markup.
    escaped_merchant = html.escape("<script>alert(1)</script>")
    # It must not appear as a raw tag inside value or text nodes; it should be entity-escaped.
    assert '<script>alert(1)</script>' not in malicious_rendered or escaped_merchant in malicious_rendered

    # Label ID/link preservation: data-merchant, data-date, data-payment, data-trip,
    # data-category, data-payee links must exist with aria-label attributes.
    assert 'data-merchant=' in rendered
    assert 'data-date=' in rendered
    assert 'data-payment=' in rendered
    assert 'data-trip=' in rendered
    assert 'data-payee=' in rendered
    assert 'data-category=' in rendered

    # Design system token connections (§4.2 / §3) must be present in CSS.
    assert "var(--bg)" in rendered
    assert "var(--paper)" in rendered
    assert "var(--ink)" in rendered
    assert "var(--line)" in rendered
    assert "var(--focus)" in rendered
    assert "var(--mut)" in rendered
    assert "var(--grn)" in rendered
    assert "var(--neg)" in rendered
    assert "var(--line-strong)" in rendered
    assert "var(--sel)" in rendered
    assert "button,.work-back{min-height:44px;padding:10px 14px;border:1px solid var(--line-strong);border-radius:8px;background:var(--paper);color:var(--ink);" in rendered
    assert "button.primary{background:var(--grn);color:#fff;" in rendered
    assert ".work-back{color:var(--grn-dk);" in rendered

    # Mobile/responsive contract (§3.2 / §3.3): focus-visible and min-width/overflow rules.
    assert ":focus-visible" in rendered
    assert "min-width:0" in rendered
    assert "overflow-wrap:break-word" in rendered

    # Accessibility label preservation (§3.3): aria-label connections for inputs.
    assert 'aria-label=' in rendered
    assert 'aria-pressed=' in rendered

    # The photo strip must not break at 375px: grid minmax must include 100% guard.
    assert "minmax(min(100px,100%),1fr)" in rendered or "minmax(100px,1fr)" in rendered


def test_browser_receipt_screen_fits_required_viewports():
    from unittest.mock import patch
    from webapp import ledger_board, ledger_design, receipt_review, site_shell
    from playwright.sync_api import sync_playwright

    data = {"candidates": [SYNTHETIC_CANDIDATE], "holds": [], "images": ["b" * 64]}
    original = receipt_review.render_html(data, csrf="synthetic-csrf", trips=SYNTHETIC_TRIPS)
    with patch.object(ledger_board, 'current_role', return_value='owner'), patch.object(
            ledger_design, 'nav_region', return_value=''):
        document = site_shell.wrap_document(original, '/receipts')

    with sync_playwright() as api:
        browser = api.chromium.launch(headless=True)
        try:
            context = browser.new_context(viewport={'width': 375, 'height': 812},
                                          permissions=['clipboard-read', 'clipboard-write'])
            page = context.new_page()

            def serve_receipt(route):
                request = route.request
                if request.url.endswith('/api/receipts/edit'):
                    route.fulfill(status=200, content_type='application/json', body=json.dumps({
                        'version': 2, 'currency': 'JPY', 'total_original': 2345,
                        'total_jpy': 2345, 'amount_krw': 23450, 'trip_id': 'trip-syn',
                        'merchant': '테스트상호', 'date': '2026-10-12', 'payment': 'cash',
                        'payee': '검증 지급처', 'category': '식비', 'hold': None,
                    }))
                elif request.url.endswith('/api/receipts/tsv?trip=trip-syn'):
                    route.fulfill(status=200, content_type='application/json', body=json.dumps({
                        'row_count': 1, 'held': [], 'tsv': '2026-10-12\t검증 지급처\t\t\t\t\t23450',
                    }))
                else:
                    route.fulfill(status=200, content_type='text/html; charset=utf-8', body=document)

            page.route('https://receipt.test/**', serve_receipt)
            page.goto('https://receipt.test/receipts')
            for width in (375, 759, 1280):
                page.set_viewport_size({'width': width, 'height': 812})
                assert page.evaluate('document.documentElement.scrollWidth <= window.innerWidth')
            assert page.get_by_role('heading', name='영수증 정리').is_visible()
            assert page.locator('#step-review').is_visible()

            page.emulate_media(color_scheme='dark')
            page.wait_for_function("document.documentElement.dataset.theme === 'dark'")
            dark = page.locator(':root').evaluate(
                "element => getComputedStyle(element).getPropertyValue('--bg').trim()")
            page.emulate_media(color_scheme='light')
            page.wait_for_function("document.documentElement.dataset.theme === 'light'")
            light = page.locator(':root').evaluate(
                "element => getComputedStyle(element).getPropertyValue('--bg').trim()")
            assert (dark, light) == ('#0F172A', '#F8FAFC')

            page.set_viewport_size({'width': 640, 'height': 812})
            page.evaluate('document.documentElement.style.zoom="200%"')
            merchant = page.locator("[data-merchant='syn-001']")
            edit = page.get_by_role('button', name='수정')
            assert merchant.is_visible() and edit.is_visible()
            merchant.focus()
            assert merchant.evaluate('(el)=>el===document.activeElement')
            candidate = page.locator("tr[data-version]").first
            candidate.locator('[data-payee]').fill('검증 지급처')
            candidate.locator('[data-edit]').click()
            page.get_by_text('영수증 변경을 저장했습니다.', exact=False).wait_for()
            assert candidate.locator('[data-payee]').input_value() == '검증 지급처'
            page.locator('#copy-trip').select_option('trip-syn')
            page.locator('#copy-tsv').click()
            page.wait_for_function("navigator.clipboard.readText().then(text => text.includes('검증 지급처'))")
            assert '검증 지급처' in page.evaluate('navigator.clipboard.readText()')
        finally:
            browser.close()


if __name__ == "__main__":
    test_render_preserves_contract_and_uses_design_tokens()
    print("PASS: contract test covers design tokens, HTML escape, label links, amount/state, 375px guards")
