"""Synthetic convergence checks for the standalone OTA/config presentation boundary."""

from webapp import ota_payment_review, site_assets, site_shell, site_theme


def test_shared_shell_assets_are_the_only_standalone_shell_source():
    assert site_shell.STYLE is site_assets.SHELL_STYLE
    assert site_shell.SCRIPT is site_assets.SHELL_SCRIPT
    assert "--shell-control-min: 44px" in site_assets.TOKENS_STYLE
    assert "#site-theme-toggle" in site_theme.STYLE


def test_ota_review_uses_shared_tokens_and_responsive_control_contract():
    html = ota_payment_review.render_import_section("synthetic-csrf")
    assert "var(--shell-paper" in html
    assert "var(--shell-control-min,44px)" in html
    assert "@media(width < 420px)" in html
    assert "focus-visible" in html
    assert "min-width:0" in html


def test_ota_review_preserves_safe_action_contract():
    html = ota_payment_review.render_import_section("synthetic-csrf")
    assert 'data-ota-review' in html
    assert 'id="ota-queue-filter"' in html
    assert 'id="ota-events"' in html
    assert 'id="ota-page-prev"' in html


def test_ota_controls_remain_visible_and_keyboard_accessible_across_sizes():
    from playwright.sync_api import sync_playwright
    import re
    section = re.sub(r'<script>[\s\S]*?</script>', '', ota_payment_review.render_import_section('synthetic-csrf'))
    with sync_playwright() as engine:
        browser = engine.chromium.launch(headless=True)
        try:
            page = browser.new_page()
            page.set_default_timeout(3000)
            page.set_content('<style>'+site_shell.STYLE+site_theme.STYLE+'</style>'+section)
            page.locator('#ota-review').evaluate('(node)=>node.open=true')
            page.locator('#ota-events').evaluate("node=>node.innerHTML='<article class=ota-event><h3>SYNTHETIC_LONG_REFERENCE_ABCDEFGHIJKLMNOPQRSTUVWXYZABCDEFGHIJKLMNOPQRSTUVWXYZ</h3><div class=ota-actions><button>Synthetic review</button></div></article>'")
            for width in (320, 390, 760, 1440):
                page.set_viewport_size({'width': width, 'height': 900})
                for theme in ('light', 'dark'):
                    page.locator('html').evaluate('(node,theme)=>node.dataset.theme=theme', theme)
                    for zoom in ('1', '2'):
                        page.locator('body').evaluate('(node,zoom)=>node.style.zoom=zoom', zoom)
                        assert page.evaluate('document.documentElement.scrollWidth<=innerWidth+1'), (width, theme, zoom)
                        button = page.get_by_role('button', name='Synthetic review', exact=True)
                        assert button.evaluate('node=>getComputedStyle(node).minHeight') == '44px'
            page.locator('body').evaluate("node=>node.style.zoom='1'")
            button.focus()
            assert button.evaluate('node=>node===document.activeElement')
        finally:
            browser.close()
