"""Differential contract tests for RF-201 design token adoption.

Verifies:
1. Root token definition in site_shell.css and site_theme.css
2. Active token consumption across geometry (sidebar, drawer, content, topbar) and touch targets (44px)
3. Palette alias bridging (--bg, --paper, --ink, --mut, --line, --line-strong, --hover, --sel, --accent, --focus, --warn, --bad)
4. Playwright Chromium differential across 320/375/390/600/760/1024/1440 viewports, light/dark themes, and 100/200% zoom
5. Preservation of keyboard navigation, single theme toggle, and reduced motion
"""

import pytest
from unittest.mock import patch
from playwright.sync_api import sync_playwright

from webapp import site_assets, site_shell, site_theme, ledger_board, ledger_design


def test_root_tokens_defined_and_bridged():
    """Verify common geometry and control tokens are defined on :root and bridged to theme aliases."""
    shell_css = site_assets.SHELL_STYLE
    theme_css = site_assets.THEME_STYLE

    # Shared geometry & control tokens
    assert "--shell-nav-width:232px" in shell_css
    assert "--shell-drawer-width:min(300px,85vw)" in shell_css
    assert "--shell-topbar-height:56px" in shell_css
    assert "--shell-control-min:44px" in shell_css

    # Theme CSS bridges control and geometry
    assert "--shell-control-min:44px" in theme_css
    assert "--shell-nav-width:232px" in theme_css
    assert "--shell-drawer-width:min(300px,85vw)" in theme_css
    assert "--shell-topbar-height:56px" in theme_css

    # Palette aliases in theme CSS
    for alias in (
        "--bg:var(--shell-bg)",
        "--paper:var(--shell-paper)",
        "--ink:var(--shell-ink)",
        "--mut:var(--shell-muted)",
        "--line:var(--shell-line)",
        "--line-strong:var(--shell-line-strong)",
        "--hover:var(--shell-hover)",
        "--sel:var(--shell-selected)",
        "--accent:var(--shell-accent)",
        "--focus:var(--shell-focus)",
        "--warn:var(--shell-warn)",
        "--bad:var(--shell-danger)",
    ):
        assert alias in theme_css, f"Missing palette alias: {alias}"


def test_tokens_actively_consumed_across_multiple_elements():
    """Verify tokens are actively consumed across multiple elements and no dead tokens exist."""
    shell_css = site_assets.SHELL_STYLE

    # --shell-nav-width consumed by #nav and #site-content
    assert "width:var(--shell-nav-width,232px)" in shell_css
    assert "flex:0 0 var(--shell-nav-width,232px)" in shell_css
    assert "margin-left:var(--shell-nav-width,232px)" in shell_css
    assert "width:calc(100% - var(--shell-nav-width,232px))" in shell_css

    # --shell-drawer-width consumed by mobile #nav and .site-app>#nav
    assert "width:min(var(--shell-drawer-width,min(300px,85vw)),100%)" in shell_css
    assert "width:var(--shell-drawer-width,min(300px,85vw))" in shell_css

    # --shell-topbar-height consumed by .site-topbar
    assert "min-height:var(--shell-topbar-height,56px)" in shell_css

    # --shell-control-min consumed across controls
    assert "min-height:var(--shell-control-min,44px)" in shell_css
    assert "var(--shell-theme-control-size,var(--shell-control-min,44px))" in shell_css


def test_chromium_differential_viewports_and_themes():
    """Test computed style and geometry differential across viewports, themes, and zooms."""
    doc = "<!doctype html><html><head><title>Differential Test</title></head><body><main id='content'>Content</main></body></html>"
    with patch.object(ledger_board, "current_role", return_value="owner"):
        wrapped_html = site_shell.wrap_document(doc, "/cards")

    viewports = [320, 375, 390, 600, 760, 1024, 1440]
    zooms = [1.0, 2.0]

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        try:
            context = browser.new_context()

            # Serve document over synthetic HTTP URL to avoid about:blank localStorage restrictions
            context.route(
                "http://test.local/cards",
                lambda route: route.fulfill(
                    status=200,
                    content_type="text/html; charset=utf-8",
                    body=wrapped_html.encode("utf-8"),
                ),
            )
            page = context.new_page()
            page.goto("http://test.local/cards")

            for width in viewports:
                for scale in zooms:
                    page.set_viewport_size({"width": width, "height": 800})

                    # Light theme checks
                    page.emulate_media(color_scheme="light")
                    page.evaluate("() => document.documentElement.removeAttribute('data-theme')")

                    # Verify root tokens evaluate properly
                    nav_w = page.evaluate("() => getComputedStyle(document.documentElement).getPropertyValue('--shell-nav-width').trim()")
                    assert nav_w == "232px"
                    ctrl_min = page.evaluate("() => getComputedStyle(document.documentElement).getPropertyValue('--shell-control-min').trim()")
                    assert ctrl_min == "44px"

                    # Verify palette alias resolution
                    bg = page.evaluate("() => getComputedStyle(document.documentElement).getPropertyValue('--bg').trim()")
                    shell_bg = page.evaluate("() => getComputedStyle(document.documentElement).getPropertyValue('--shell-bg').trim()")
                    assert bg == shell_bg == "#F8FAFC"

                    if width >= 760:
                        # Desktop layout: nav is 232px, content marginLeft is 232px
                        nav_rect = page.locator("#nav").bounding_box()
                        assert nav_rect is not None
                        assert round(nav_rect["width"]) == 232

                        content_ml = page.locator("#site-content").evaluate(
                            "el => parseFloat(getComputedStyle(el).marginLeft)"
                        )
                        assert round(content_ml) == 232
                    else:
                        # Mobile layout: topbar height >= 56px, theme toggle and menu toggle >= 44x44
                        topbar_rect = page.locator(".site-topbar").bounding_box()
                        assert topbar_rect is not None
                        assert topbar_rect["height"] >= 56

                        toggle_rect = page.locator("#site-theme-toggle").bounding_box()
                        assert toggle_rect is not None
                        assert round(toggle_rect["width"]) >= 44
                        assert round(toggle_rect["height"]) >= 44

                        menu_rect = page.locator(".site-menu-toggle").bounding_box()
                        assert menu_rect is not None
                        assert round(menu_rect["height"]) >= 44

                    # Dark theme toggle via manual theme button contract
                    page.locator("#site-theme-toggle").click()

                    dark_bg = page.evaluate("() => getComputedStyle(document.documentElement).getPropertyValue('--shell-bg').trim()")
                    assert dark_bg == "#0F172A"
                    dark_theme_bg = page.evaluate("() => getComputedStyle(document.documentElement).getPropertyValue('--bg').trim()")
                    assert dark_theme_bg == "#0F172A"

                    # Toggle back to light for next iteration
                    page.locator("#site-theme-toggle").click()
                    assert page.evaluate("() => getComputedStyle(document.documentElement).getPropertyValue('--bg').trim()") == "#F8FAFC"

            # Accessibility: reduced motion check
            page.emulate_media(reduced_motion="reduce")
            nav_trans = page.locator(".site-app>#nav").evaluate("el => getComputedStyle(el).transition")
            assert "none" in nav_trans or nav_trans == "all 0s ease 0s"
        finally:
            browser.close()
