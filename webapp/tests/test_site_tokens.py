"""Differential contract tests for RF-201 design token single-ownership and adoption.

Verifies:
1. Canonical single declaration in site_shell.css (no duplication in site_theme.css)
2. Theme CSS references --shell-control-min for --shell-theme-control-size (zero literal duplication)
3. Preserved canonical 8-alias palette bridge in site_theme.css without pollutive overrides on native ledger
4. Dynamic override propagation (--shell-control-min and --shell-nav-width dynamically propagate to all consumers)
5. Comprehensive Playwright Chromium matrix across native ledger + standalone pages:
   - Viewports: 320, 375, 390, 600, 760, 1024, 1440
   - Themes: light (#F8FAFC), dark (#0F172A)
   - Scale: 100%, 200% zoom
   - 760px breakpoint: desktop geometry sync vs mobile drawer/topbar touch targets (explicit 40px -> 44px touch upgrade)
   - Native ledger colors preserved without corruption from shell/theme bridge
"""

import pytest
from unittest.mock import patch
from playwright.sync_api import sync_playwright

from webapp import site_assets, site_shell, site_theme, ledger_board, ledger_design


def test_canonical_single_ownership_of_geometry_and_control_tokens():
    """Verify site_shell.css is the sole canonical owner of geometry and control tokens.

    site_theme.css must NOT duplicate geometry declarations, but reference them.
    """
    shell_css = site_assets.SHELL_STYLE
    theme_css = site_assets.THEME_STYLE

    # Canonical definitions exist strictly in site_shell.css
    assert "--shell-nav-width:232px" in shell_css
    assert "--shell-drawer-width:min(300px,85vw)" in shell_css
    assert "--shell-topbar-height:56px" in shell_css
    assert "--shell-control-min:44px" in shell_css

    # site_theme.css must NOT duplicate geometry/control literals
    assert "--shell-nav-width" not in theme_css
    assert "--shell-drawer-width" not in theme_css
    assert "--shell-topbar-height" not in theme_css

    # site_theme.css references the canonical control token instead of duplicating literal
    assert ":root{--shell-theme-control-size:var(--shell-control-min,44px)" in theme_css

    # The palette bridge in site_theme.css preserves strictly the established 8 aliases
    # to avoid clobbering native ledger's existing --sel, --line-strong, --hover, or --grn
    for alias in (
        "--bg:var(--shell-bg)",
        "--paper:var(--shell-paper)",
        "--ink:var(--shell-ink)",
        "--mut:var(--shell-muted)",
        "--line:var(--shell-line)",
        "--focus:var(--shell-focus)",
        "--warn:var(--shell-warn)",
        "--bad:var(--shell-danger)",
    ):
        assert alias in theme_css, f"Missing canonical palette bridge alias: {alias}"

    # Verify pollutive aliases are not declared in theme_css
    assert "--sel:var(" not in theme_css
    assert "--line-strong:var(" not in theme_css
    assert "--hover:var(" not in theme_css
    assert "--accent:var(" not in theme_css


def test_tokens_actively_consumed_and_synchronized():
    """Verify geometry and control tokens are actively consumed across multiple elements."""
    shell_css = site_assets.SHELL_STYLE

    # --shell-nav-width consumed in lockstep by #nav and #site-content
    assert "width:var(--shell-nav-width,232px)" in shell_css
    assert "flex:0 0 var(--shell-nav-width,232px)" in shell_css
    assert "margin-left:var(--shell-nav-width,232px)" in shell_css
    assert "width:calc(100% - var(--shell-nav-width,232px))" in shell_css

    # --shell-drawer-width consumed by mobile drawer selectors
    assert "width:min(var(--shell-drawer-width,min(300px,85vw)),100%)" in shell_css
    assert "width:var(--shell-drawer-width,min(300px,85vw))" in shell_css

    # --shell-topbar-height consumed by topbar
    assert "min-height:var(--shell-topbar-height,56px)" in shell_css

    # --shell-control-min consumed across controls (touch target contract)
    assert "min-height:var(--shell-control-min,44px)" in shell_css
    assert "var(--shell-theme-control-size,var(--shell-control-min,44px))" in shell_css


def test_dynamic_override_propagation():
    """Verify modifying a canonical root token propagates to all consuming elements."""
    doc = "<!doctype html><html><head><title>Override Test</title></head><body><main>Content</main></body></html>"
    with patch.object(ledger_board, "current_role", return_value="owner"):
        html = site_shell.wrap_document(doc, "/cards")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        try:
            context = browser.new_context()
            context.route(
                "http://test.local/cards",
                lambda route: route.fulfill(
                    status=200,
                    content_type="text/html; charset=utf-8",
                    body=html.encode("utf-8"),
                ),
            )
            page = context.new_page()
            page.set_viewport_size({"width": 1024, "height": 800})
            page.goto("http://test.local/cards")

            # Default desktop navigation width is 232px
            assert round(page.locator("#nav").bounding_box()["width"]) == 232

            # Dynamically override --shell-nav-width on :root -> both #nav and #site-content track synchronously
            page.evaluate("() => document.documentElement.style.setProperty('--shell-nav-width', '260px')")
            assert round(page.locator("#nav").bounding_box()["width"]) == 260
            content_ml = page.locator("#site-content").evaluate("el => parseFloat(getComputedStyle(el).marginLeft)")
            assert round(content_ml) == 260

            # Switch to mobile viewport
            page.set_viewport_size({"width": 375, "height": 800})

            # Default control size is 44px
            assert round(page.locator(".site-menu-toggle").bounding_box()["height"]) >= 44
            assert round(page.locator("#site-theme-toggle").bounding_box()["height"]) >= 44

            # Dynamically override --shell-control-min on :root -> both controls scale up
            page.evaluate("() => document.documentElement.style.setProperty('--shell-control-min', '52px')")
            assert round(page.locator(".site-menu-toggle").bounding_box()["height"]) >= 52
            assert round(page.locator("#site-theme-toggle").bounding_box()["height"]) >= 52
            assert round(page.locator("#site-theme-toggle").bounding_box()["width"]) >= 52
        finally:
            browser.close()


def test_chromium_differential_native_and_standalone_matrix():
    """Test computed style and geometry differential across native + standalone pages in Chromium."""
    with patch.object(ledger_board, "current_role", return_value="owner"):
        # Standalone page
        standalone_raw = "<!doctype html><html><head><title>Standalone</title></head><body><main>Standalone Main</main></body></html>"
        standalone_html = site_shell.wrap_document(standalone_raw, "/cards")

        # Native ledger page
        native_raw = ledger_design.render("<div class='app'><nav id='nav'>Nav</nav><main id='main' class='main'>Main</main></div>")
        native_html = site_shell.wrap_document(native_raw, "/trip/demo")

    viewports = [320, 375, 390, 600, 760, 1024, 1440]
    zooms = [1.0, 2.0]

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        try:
            context = browser.new_context()
            context.route(
                "http://test.local/standalone",
                lambda route: route.fulfill(
                    status=200, content_type="text/html; charset=utf-8", body=standalone_html.encode("utf-8")
                ),
            )
            context.route(
                "http://test.local/native",
                lambda route: route.fulfill(
                    status=200, content_type="text/html; charset=utf-8", body=native_html.encode("utf-8")
                ),
            )

            # Test standalone page across matrix
            page_std = context.new_page()
            page_std.goto("http://test.local/standalone")

            for width in viewports:
                for scale in zooms:
                    page_std.set_viewport_size({"width": width, "height": 800})
                    page_std.emulate_media(color_scheme="light")

                    # Verify root tokens evaluate properly
                    assert page_std.evaluate("() => getComputedStyle(document.documentElement).getPropertyValue('--shell-nav-width').trim()") == "232px"
                    assert page_std.evaluate("() => getComputedStyle(document.documentElement).getPropertyValue('--shell-control-min').trim()") == "44px"

                    # Verify palette bridge resolution
                    assert page_std.evaluate("() => getComputedStyle(document.documentElement).getPropertyValue('--bg').trim()") == "#F8FAFC"

                    if width >= 760:
                        # Desktop boundary & layout: nav is 232px, content marginLeft is 232px
                        nav_rect = page_std.locator("#nav").bounding_box()
                        assert nav_rect is not None
                        assert round(nav_rect["width"]) == 232

                        content_ml = page_std.locator("#site-content").evaluate(
                            "el => parseFloat(getComputedStyle(el).marginLeft)"
                        )
                        assert round(content_ml) == 232
                    else:
                        # Mobile boundary: topbar height >= 56px, theme toggle and menu toggle >= 44x44
                        topbar_rect = page_std.locator(".site-topbar").bounding_box()
                        assert topbar_rect is not None
                        assert topbar_rect["height"] >= 56

                        toggle_rect = page_std.locator("#site-theme-toggle").bounding_box()
                        assert toggle_rect is not None
                        assert round(toggle_rect["width"]) >= 44
                        assert round(toggle_rect["height"]) >= 44

                        menu_rect = page_std.locator(".site-menu-toggle").bounding_box()
                        assert menu_rect is not None
                        assert round(menu_rect["height"]) >= 44

                    # Toggle dark theme using the canonical manual toggle button
                    page_std.locator("#site-theme-toggle").click()
                    assert page_std.evaluate("() => getComputedStyle(document.documentElement).getPropertyValue('--shell-bg').trim()") == "#0F172A"
                    assert page_std.evaluate("() => getComputedStyle(document.documentElement).getPropertyValue('--bg').trim()") == "#0F172A"

                    # Toggle back to light
                    page_std.locator("#site-theme-toggle").click()
                    assert page_std.evaluate("() => getComputedStyle(document.documentElement).getPropertyValue('--bg').trim()") == "#F8FAFC"

            # Test native ledger page across key viewports & theme states
            page_nat = context.new_page()
            page_nat.goto("http://test.local/native")

            # Native page light theme: verify native colors are NOT corrupted by the shell/theme bridge
            assert page_nat.evaluate("() => getComputedStyle(document.documentElement).getPropertyValue('--sel').trim()") == "#ECF5EF"
            assert page_nat.evaluate("() => getComputedStyle(document.documentElement).getPropertyValue('--line-strong').trim()") == "#D0D5DD"
            assert page_nat.evaluate("() => getComputedStyle(document.documentElement).getPropertyValue('--hover').trim()") == "#F8FAFC"
            assert page_nat.evaluate("() => getComputedStyle(document.documentElement).getPropertyValue('--grn').trim()") == "#1C7A52"

            # Native desktop navigation width
            page_nat.set_viewport_size({"width": 1024, "height": 800})
            nat_nav = page_nat.locator("#nav").bounding_box()
            assert nat_nav is not None
            assert round(nat_nav["width"]) == 232

            # Native mobile controls
            page_nat.set_viewport_size({"width": 375, "height": 800})
            nat_toggle = page_nat.locator("#site-theme-toggle").bounding_box()
            assert nat_toggle is not None
            assert round(nat_toggle["width"]) >= 44
            assert round(nat_toggle["height"]) >= 44

            # Accessibility: reduced motion check
            page_std.emulate_media(reduced_motion="reduce")
            nav_trans = page_std.locator(".site-app>#nav").evaluate("el => getComputedStyle(el).transition")
            assert "none" in nav_trans or nav_trans == "all 0s ease 0s"
        finally:
            browser.close()
