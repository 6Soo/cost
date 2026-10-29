"""Synthetic visual and keyboard contract for the standalone review UI."""

from webapp.review_ui import render_review_ui


def test_review_ui_responsive_theme_zoom_and_keyboard_contract():
    from playwright.sync_api import sync_playwright

    html = render_review_ui().replace(
        '<div id="rows"></div>',
        '<div id="rows"><article class="row-card">'
        '<h2 class="row-title">Synthetic merchant with a deliberately long label</h2>'
        '<div class="panels"><section class="panel"><h3>Source evidence</h3>'
        '<p class="field"><span class="label">Reference:</span> '
        'SYNTHETIC_REFERENCE_ABCDEFGHIJKLMNOPQRSTUVWXYZ_0123456789</p></section>'
        '<section class="panel"><h3>Candidate</h3><div class="candidate-box">'
        'Synthetic candidate detail that should wrap inside the card.</div></section></div>'
        '<fieldset class="decision-group"><legend>Review decision</legend>'
        '<label class="decision-option"><input type="radio" name="decision" value="keep">Keep</label>'
        '</fieldset></article></div>',
    )

    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        page = browser.new_page(color_scheme="light", viewport={"width": 320, "height": 800})
        page.route("http://review.test/", lambda route: route.fulfill(
            body=html, content_type="text/html; charset=utf-8"
        ))
        page.goto("http://review.test/")
        theme_button = page.locator("#site-theme-toggle")
        assert theme_button.count() == 1
        assert theme_button.get_attribute("aria-label") == "다크모드로 전환"
        theme_button.focus()
        page.keyboard.press("Enter")
        assert page.locator("html").get_attribute("data-theme") == "dark"
        page.emulate_media(color_scheme="light")
        assert page.locator("html").get_attribute("data-theme") == "dark"
        for width in (320, 390, 760, 1440):
            page.set_viewport_size({"width": width, "height": 800})
            for theme in ("light", "dark"):
                current = page.locator("html").get_attribute("data-theme")
                if current != theme:
                    theme_button.focus()
                    page.keyboard.press("Enter")
                assert page.locator("html").get_attribute("data-theme") == theme
                assert theme_button.get_attribute("aria-label") == (
                    "다크모드로 전환" if theme == "light" else "라이트모드로 전환"
                )
                assert page.locator("[data-theme-icon]:visible").count() == 1
                page.emulate_media(color_scheme="dark" if theme == "light" else "light")
                assert page.locator("html").get_attribute("data-theme") == theme
                for zoom in ("1", "2"):
                    page.evaluate("(value)=>document.documentElement.style.zoom=value", zoom)
                    assert page.evaluate("document.documentElement.scrollWidth<=innerWidth+1"), (width, theme, zoom)
                    assert page.locator(".row-card").is_visible()
                    assert page.locator("#site-theme-toggle").is_visible()
                page.evaluate("document.documentElement.style.zoom='1'")
            assert page.locator(".decision-option").evaluate(
                "element=>parseFloat(getComputedStyle(element).minHeight)>=44"
            )

        page.set_viewport_size({"width": 390, "height": 800})
        page.locator("#reloadBtn").focus()
        assert page.locator("#reloadBtn").evaluate("element=>element===document.activeElement")
        assert page.locator("#reloadBtn").evaluate(
            "element=>getComputedStyle(element).outlineStyle!=='none'"
        )
        # The standalone page correctly disables export until its model loads;
        # enable it here to exercise the next keyboard stop without a backend.
        page.locator("#exportBtn").evaluate("element=>element.disabled=false")
        page.keyboard.press("Tab")
        assert page.locator("#exportBtn").evaluate("element=>element===document.activeElement")
        assert page.locator("#exportBtn").evaluate("element=>getComputedStyle(element).outlineStyle!=='none'")
        browser.close()


def test_receipt_screen_manual_theme_and_zoom_with_shared_shell():
    from unittest.mock import patch
    from webapp import ledger_board, ledger_design, receipt_review, site_shell
    from playwright.sync_api import sync_playwright

    candidate = {
        "identity": "synthetic-receipt", "date": "2026-10-12", "merchant": "합성 상호",
        "currency": "JPY", "total_jpy": 2345, "total_original": 2345,
        "payment": "cash", "payee": "합성 지급처", "category": "식비",
        "trip_id": "trip-synthetic", "group_id": None, "image_sha": "a" * 64,
        "hold": None, "amount_krw": 23450,
    }
    original = receipt_review.render_html(
        {"candidates": [candidate], "holds": [], "images": []},
        csrf="synthetic-csrf", trips=[{"id": "trip-synthetic", "name": "합성 여행"}],
    )
    with patch.object(ledger_board, "current_role", return_value="owner"), patch.object(
        ledger_design, "nav_region", return_value=""
    ):
        document = site_shell.wrap_document(original, "/receipts")

    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        page = browser.new_page(color_scheme="light", viewport={"width": 320, "height": 812})
        page.route("https://receipt.test/**", lambda route: route.fulfill(
            body=document, content_type="text/html; charset=utf-8"
        ))
        page.goto("https://receipt.test/receipts")
        toggle = page.locator("#site-theme-toggle")
        assert toggle.count() == 1
        assert page.locator("[data-merchant='synthetic-receipt']").is_visible()

        toggle.focus()
        page.keyboard.press("Enter")
        assert page.locator("html").get_attribute("data-theme") == "dark"
        page.emulate_media(color_scheme="light")
        page.wait_for_function("document.documentElement.dataset.theme==='dark'")
        toggle.focus()
        page.keyboard.press("Enter")
        assert page.locator("html").get_attribute("data-theme") == "light"
        page.emulate_media(color_scheme="dark")
        page.wait_for_function("document.documentElement.dataset.theme==='light'")

        for width in (320, 390, 759, 760, 1024, 1440):
            page.set_viewport_size({"width": width, "height": 812})
            assert page.evaluate("document.documentElement.scrollWidth<=innerWidth"), width
        page.set_viewport_size({"width": 640, "height": 812})
        page.evaluate("document.documentElement.style.zoom='200%'")
        assert page.locator("[data-merchant='synthetic-receipt']").is_visible()
        assert page.evaluate("document.documentElement.scrollWidth<=innerWidth")
        assert page.locator("#status[role=status][aria-live=polite]").count() == 1
        browser.close()
