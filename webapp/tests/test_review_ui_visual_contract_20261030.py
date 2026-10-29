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
        page.set_content(html)
        for width in (320, 390, 760, 1440):
            page.set_viewport_size({"width": width, "height": 800})
            for theme in ("light", "dark"):
                page.emulate_media(color_scheme=theme)
                for zoom in ("1", "2"):
                    page.evaluate("(value)=>document.documentElement.style.zoom=value", zoom)
                    assert page.evaluate("document.documentElement.scrollWidth<=innerWidth+1"), (width, theme, zoom)
                    assert page.locator(".row-card").is_visible()
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
