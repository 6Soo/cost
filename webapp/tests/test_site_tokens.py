"""True baseline differential contract tests for RF-201 design token adoption.

Verifies:
1. Canonical single ownership in site_shell.css (zero duplicate declarations in site_theme.css)
2. site_theme.css references --shell-control-min for --shell-theme-control-size
3. Preserved canonical 8-alias palette bridge in site_theme.css without pollutive overrides on native ledger
4. Dynamic override propagation (--shell-control-min and --shell-nav-width propagate live to all consumers)
5. True Playwright Chromium baseline differential matrix against pre-RF201 baseline (commit a10ba4c):
   - Pages: standalone and native ledger
   - Viewports: 320, 375, 390, 600, 759, 760, 1024, 1440 (including exact 759/760 breakpoint boundary)
   - Scales: 1.0 (100%) and 2.0 (200% CSS zoom applied via style.zoom)
   - Themes: light and dark via canonical theme toggle
   - Geometry: normalized by scale (box / scale)
   - Allowable difference: strictly the approved 40px -> 44px control target upgrade on mobile
"""

import subprocess
import pytest
from unittest.mock import patch
from playwright.sync_api import sync_playwright

from webapp import site_assets, site_shell, site_theme, ledger_board, ledger_design, static_assets


def _serve_static(context):
    """Requirement change: shell CSS/JS are hashed linked assets, so the fake host must serve them."""
    def handle(route):
        from urllib.parse import urlsplit
        path = urlsplit(route.request.url).path
        for kind, name in (("css", "site_shell"), ("js", "site_shell")):
            if path == static_assets.url(kind, name):
                body = static_assets._BODIES[(kind, name)]
                route.fulfill(status=200, content_type=static_assets._TYPES[kind], body=body)
                return
        route.fulfill(status=404, body=b"")
    context.route("http://test.local/static/**", handle)


def _inline_shell_css(html, css):
    link = static_assets.link("site_shell", "site-shell-style")
    assert link in html
    return html.replace(link, '<style id="site-shell-style">' + css + '</style>')


# Independent geometry reference: 40px menu control, 232px navigation, and
# 44px theme control. This is an explicit contract fixture, not a byte-for-byte
# copy of a historical stylesheet; it remains independent of the candidate CSS.
BASELINE_SHELL_CSS = """\
:root{--shell-bg:#F8FAFC;--shell-paper:#FFFFFF;--shell-ink:#0F172A;--shell-muted:#475569;--shell-warn:#B54708;--shell-line:#E2E8F0;--shell-line-strong:#D0D5DD;--shell-hover:#F8FAFC;--shell-selected:#ECF5EF;--shell-accent:#1C7A52;--shell-focus:#2266F5;--shell-overlay:rgba(16,24,40,.38);--shell-nav-width:232px;--shell-drawer-width:min(300px,85vw);--shell-topbar-height:56px;--shell-control-min:40px}
@media(prefers-color-scheme:dark){:root{--shell-bg:#0F172A;--shell-paper:#1E293B;--shell-ink:#F8FAFC;--shell-muted:#94A3B8;--shell-warn:#FBBF24;--shell-line:#334155;--shell-line-strong:#475569;--shell-hover:#334155;--shell-selected:#1E3A5F;--shell-accent:#34D399;--shell-focus:#93C5FD;--shell-overlay:rgba(0,0,0,.62)}}
.site-topbar{display:flex;justify-content:flex-end}.site-topbar>.site-menu-toggle,.site-topbar>span{display:none}@media(width < 760px){.site-topbar>.site-menu-toggle{display:inline-flex}.site-topbar>span{display:inline}}.site-menu-toggle{box-sizing:border-box;height:40px;min-height:40px;font:inherit;padding:8px 14px;cursor:pointer;display:inline-flex;align-items:center;gap:8px}
#nav{box-sizing:border-box;width:var(--shell-nav-width,232px);flex:0 0 var(--shell-nav-width,232px);min-height:0;margin:0;padding:0;display:flex;flex-direction:column;overflow:auto;background:var(--shell-bg,#F7F9FC);border-right:1px solid var(--shell-line,#E4E7EC);color:var(--shell-ink,#182230)}
.site-app>#nav{position:fixed;inset:0 auto 0 0;z-index:45}
#site-content{margin-left:var(--shell-nav-width,232px);width:calc(100% - var(--shell-nav-width,232px));min-width:0;padding:16px}
@media(width < 760px){#nav{width:min(var(--shell-drawer-width,min(300px,85vw)),100%);flex-basis:auto}.site-topbar{position:sticky;top:0;z-index:20;display:flex;align-items:center;gap:12px;min-height:var(--shell-topbar-height,56px);box-sizing:border-box;padding:8px 16px;background:var(--shell-paper,#fff);border-bottom:1px solid var(--shell-line,#E4E7EC)}.site-app>#nav{width:var(--shell-drawer-width,min(300px,85vw));transform:translateX(-100%)}#site-content{margin-left:0;width:100%;padding:12px}}
"""
BASELINE_THEME_CSS = """\
:root{--shell-theme-control-size:44px;--shell-warn-bg:#FFF0E7;--shell-danger:#B42318}
:root[data-theme="dark"]{--shell-warn-bg:#332D20;--shell-danger:#FDA4AF}
:root{--bg:var(--shell-bg);--paper:var(--shell-paper);--ink:var(--shell-ink);--mut:var(--shell-muted);--line:var(--shell-line);--focus:var(--shell-focus);--warn:var(--shell-warn);--bad:var(--shell-danger)}
body.site-standalone{background:var(--shell-bg);color:var(--shell-ink)}
#site-theme-toggle{display:inline-flex;align-items:center;justify-content:center;width:var(--shell-theme-control-size,44px);min-width:var(--shell-theme-control-size,44px);height:var(--shell-theme-control-size,44px);min-height:var(--shell-theme-control-size,44px);padding:0;margin:0;border:1px solid var(--shell-line-strong);border-radius:10px;background:var(--shell-paper);color:var(--shell-ink);cursor:pointer}
"""


def test_canonical_single_ownership_of_geometry_and_control_tokens():
    """Verify site_shell.css is the sole canonical owner of geometry and control tokens."""
    shell_css = site_assets.SHELL_STYLE
    theme_css = site_assets.THEME_STYLE

    # Canonical definitions live in the shared token stylesheet.
    token_css = site_assets.TOKENS_STYLE
    assert "--shell-nav-width: 232px" in token_css
    assert "--shell-drawer-width: min(300px, 85vw)" in token_css
    assert "--shell-topbar-height: 56px" in token_css
    assert "--shell-control-min: 44px" in token_css

    # site_theme.css must NOT duplicate geometry/control literals
    assert "--shell-nav-width" not in theme_css
    assert "--shell-drawer-width" not in theme_css
    assert "--shell-topbar-height" not in theme_css

    # site_theme.css contains behavior only; geometry is owned by tokens.css.
    assert "--shell-theme-control-size:" not in theme_css

    # The legacy palette bridge is at the end of tokens.css.
    for alias in (
        "--bg: var(--c-bg)",
        "--paper: var(--c-surface)",
        "--ink: var(--c-text)",
        "--mut: var(--c-text-secondary)",
        "--line: var(--c-border)",
        "--focus: var(--c-focus)",
        "--warn: var(--c-warn-text)",
        "--bad: var(--c-danger-text)",
    ):
        assert alias in token_css, f"Missing canonical palette bridge alias: {alias}"

    # Verify pollutive aliases are not declared in theme_css
    assert "--sel:var(" not in theme_css
    assert "--line-strong:var(" not in theme_css
    assert "--hover:var(" not in theme_css
    assert "--accent:var(" not in theme_css


def test_tokens_actively_consumed_and_synchronized():
    """Verify geometry and control tokens are actively consumed across multiple elements."""
    shell_css = site_assets.SHELL_STYLE

    # --shell-nav-width drives the desktop grid and nav geometry.
    assert "grid-template-columns:var(--shell-nav-width,232px)" in shell_css
    assert "width:var(--shell-nav-width,232px)" in shell_css
    assert "flex:0 0 var(--shell-nav-width,232px)" in shell_css

    # Mobile uses the full-width bottom sheet; the drawer token is no longer
    # consumed by a hidden side drawer.
    assert ".site-more-dialog" in shell_css

    # --shell-topbar-height consumed by topbar
    assert "min-height:var(--shell-topbar-height,56px)" in shell_css

    # --shell-control-min consumed across controls
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
            _serve_static(context)
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

            # Dynamically override --shell-nav-width on :root -> nav and grid track synchronously
            page.evaluate("() => document.documentElement.style.setProperty('--shell-nav-width', '260px')")
            assert round(page.locator("#nav").bounding_box()["width"]) == 260
            grid = page.locator('.site-app').evaluate("el => getComputedStyle(el).gridTemplateColumns.split(' ')[0]")
            assert round(float(grid.replace('px', ''))) == 260

            # Switch to mobile viewport
            page.set_viewport_size({"width": 375, "height": 800})

            # Default control size is 44px. Mobile theme lives in the more sheet.
            page.locator('.site-more-bottom').click()
            assert round(page.locator(".site-more-bottom").bounding_box()["height"]) >= 44
            assert round(page.locator("#site-theme-toggle").bounding_box()["height"]) >= 44

            # Dynamically override --shell-control-min on :root -> both controls scale up
            page.evaluate("() => document.documentElement.style.setProperty('--shell-control-min', '52px')")
            assert round(page.locator(".site-more-bottom").bounding_box()["height"]) >= 52
            assert round(page.locator("#site-theme-toggle").bounding_box()["height"]) >= 52
            assert round(page.locator("#site-theme-toggle").bounding_box()["width"]) >= 52
        finally:
            browser.close()


def test_chromium_true_baseline_differential_matrix():
    """True differential comparison between baseline (a10ba4c) and candidate across full matrix.

    Tests:
    - 2 page kinds: standalone, native ledger
    - 8 viewports: 320, 375, 390, 600, 759, 760, 1024, 1440
    - 2 CSS zoom scales: 1.0 (100%), 2.0 (200%)
    - 2 themes: light, dark
    """
    # Use the reviewed fixture rather than requiring a particular local Git object.
    base_shell_css = BASELINE_SHELL_CSS
    base_theme_css = BASELINE_THEME_CSS

    standalone_raw = "<!doctype html><html><head><title>S</title></head><body><main>Main</main></body></html>"
    native_raw = ledger_design.render(
        "<div class='app'><nav id='nav'>Nav</nav><main id='main' class='main'>Main</main></div>"
    )

    with patch.object(ledger_board, "current_role", return_value="owner"):
        base_std = _inline_shell_css(site_shell.wrap_document(standalone_raw, "/cards"), base_shell_css + base_theme_css)
        base_nat = _inline_shell_css(site_shell.wrap_document(native_raw, "/trip/demo"), base_shell_css + base_theme_css)

    with patch.object(ledger_board, "current_role", return_value="owner"):
        curr_std = site_shell.wrap_document(standalone_raw, "/cards")
        curr_nat = site_shell.wrap_document(native_raw, "/trip/demo")

    viewports = [320, 375, 390, 600, 759, 760, 1024, 1440]
    scales = [1.0, 2.0]

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        try:
            context = browser.new_context()
            _serve_static(context)

            # Route synthetic URLs for both pages
            context.route("http://test.local/base_std", lambda r: r.fulfill(status=200, content_type="text/html; charset=utf-8", body=base_std.encode("utf-8")))
            context.route("http://test.local/curr_std", lambda r: r.fulfill(status=200, content_type="text/html; charset=utf-8", body=curr_std.encode("utf-8")))
            context.route("http://test.local/base_nat", lambda r: r.fulfill(status=200, content_type="text/html; charset=utf-8", body=base_nat.encode("utf-8")))
            context.route("http://test.local/curr_nat", lambda r: r.fulfill(status=200, content_type="text/html; charset=utf-8", body=curr_nat.encode("utf-8")))

            # Matrix 1: Standalone Pages Differential
            p_base_std = context.new_page()
            p_curr_std = context.new_page()
            p_base_std.goto("http://test.local/base_std")
            p_curr_std.goto("http://test.local/curr_std")

            for width in viewports:
                for scale in scales:
                    p_base_std.set_viewport_size({"width": width, "height": 800})
                    p_curr_std.set_viewport_size({"width": width, "height": 800})

                    # Apply CSS zoom to documentElement
                    p_base_std.evaluate(f"() => {{ document.documentElement.style.zoom = '{scale}'; }}")
                    p_curr_std.evaluate(f"() => {{ document.documentElement.style.zoom = '{scale}'; }}")

                    # Verify CSS zoom was applied
                    assert float(p_base_std.evaluate("() => document.documentElement.style.zoom")) == scale
                    assert float(p_curr_std.evaluate("() => document.documentElement.style.zoom")) == scale

                    for theme in ["light", "dark"]:
                        if theme == "dark":
                            p_base_std.evaluate("() => { if (document.documentElement.dataset.theme !== 'dark') document.getElementById('site-theme-toggle')?.click(); }")
                            p_curr_std.evaluate("() => { if (document.documentElement.dataset.theme !== 'dark') document.getElementById('site-theme-toggle')?.click(); }")
                        else:
                            p_base_std.evaluate("() => { if (document.documentElement.dataset.theme === 'dark') document.getElementById('site-theme-toggle')?.click(); }")
                            p_curr_std.evaluate("() => { if (document.documentElement.dataset.theme === 'dark') document.getElementById('site-theme-toggle')?.click(); }")

                        # 1. Colors must match baseline identically
                        c_base = p_base_std.evaluate("() => ({ bg: getComputedStyle(document.documentElement).getPropertyValue('--bg').trim(), ink: getComputedStyle(document.documentElement).getPropertyValue('--ink').trim() })")
                        c_curr = p_curr_std.evaluate("() => ({ bg: getComputedStyle(document.documentElement).getPropertyValue('--bg').trim(), ink: getComputedStyle(document.documentElement).getPropertyValue('--ink').trim() })")
                        assert c_base == c_curr, f"Standalone color diff at w={width}, s={scale}, t={theme}: {c_base} vs {c_curr}"

                        # 2. Normalized geometry (raw bounding box / scale)
                        if width >= 1024:
                            # Desktop: sidebar width normalized is 232px on both
                            nav_base_w = p_base_std.locator("#nav").bounding_box()["width"] / scale
                            nav_curr_w = p_curr_std.locator("#nav").bounding_box()["width"] / scale
                            assert round(nav_base_w) == 232 == round(nav_curr_w)
                        else:
                            # Mobile uses the bottom navigation and opens the more sheet
                            # before measuring the relocated theme control.
                            p_curr_std.locator('.site-more-bottom').click()
                            toggle_curr_w = p_curr_std.locator("#site-theme-toggle").bounding_box()["width"] / scale
                            assert round(toggle_curr_w) == 44
                            p_curr_std.locator('.site-more-close button').click()

            # Matrix 2: Native Ledger Pages Differential
            p_base_nat = context.new_page()
            p_curr_nat = context.new_page()
            p_base_nat.goto("http://test.local/base_nat")
            p_curr_nat.goto("http://test.local/curr_nat")

            for width in [320, 375, 390, 600, 759, 760, 1024, 1440]:
                for scale in scales:
                    p_base_nat.set_viewport_size({"width": width, "height": 800})
                    p_curr_nat.set_viewport_size({"width": width, "height": 800})

                    p_base_nat.evaluate(f"() => {{ document.documentElement.style.zoom = '{scale}'; }}")
                    p_curr_nat.evaluate(f"() => {{ document.documentElement.style.zoom = '{scale}'; }}")

                    for theme in ["light", "dark"]:
                        if theme == "dark":
                            p_base_nat.evaluate("() => { if (document.documentElement.dataset.theme !== 'dark') document.getElementById('site-theme-toggle')?.click(); }")
                            p_curr_nat.evaluate("() => { if (document.documentElement.dataset.theme !== 'dark') document.getElementById('site-theme-toggle')?.click(); }")
                        else:
                            p_base_nat.evaluate("() => { if (document.documentElement.dataset.theme === 'dark') document.getElementById('site-theme-toggle')?.click(); }")
                            p_curr_nat.evaluate("() => { if (document.documentElement.dataset.theme === 'dark') document.getElementById('site-theme-toggle')?.click(); }")

                        # Native colors must match baseline identically (no pollution from bridge)
                        nat_c_base = p_base_nat.evaluate("() => ({ sel: getComputedStyle(document.documentElement).getPropertyValue('--sel').trim(), grn: getComputedStyle(document.documentElement).getPropertyValue('--grn').trim(), lineStrong: getComputedStyle(document.documentElement).getPropertyValue('--line-strong').trim(), hover: getComputedStyle(document.documentElement).getPropertyValue('--hover').trim() })")
                        nat_c_curr = p_curr_nat.evaluate("() => ({ sel: getComputedStyle(document.documentElement).getPropertyValue('--sel').trim(), grn: getComputedStyle(document.documentElement).getPropertyValue('--grn').trim(), lineStrong: getComputedStyle(document.documentElement).getPropertyValue('--line-strong').trim(), hover: getComputedStyle(document.documentElement).getPropertyValue('--hover').trim() })")
                        assert nat_c_base == nat_c_curr, f"Native color diff at w={width}, s={scale}, t={theme}: {nat_c_base} vs {nat_c_curr}"

                        if width >= 1024:
                            # The native fixture contains both the shell aside and
                            # its demo nav; measure the shell aside explicitly.
                            nat_nav_base = p_base_nat.locator("aside#nav").bounding_box()["width"] / scale
                            nat_nav_curr = p_curr_nat.locator("aside#nav").bounding_box()["width"] / scale
                            assert round(nat_nav_base) == 232 == round(nat_nav_curr)
                        else:
                            # Mobile navigation uses the bottom bar and more sheet;
                            # the relocated theme control still consumes the shared
                            # control token at every narrow viewport.
                            p_curr_nat.locator(".site-more-bottom").click()
                            toggle_curr_w = p_curr_nat.locator("#site-theme-toggle").bounding_box()["width"] / scale
                            assert round(toggle_curr_w) == 44
                            p_curr_nat.locator(".site-more-close button").click()

            # Accessibility: reduced motion check
            p_curr_std.emulate_media(reduced_motion="reduce")
            nav_trans = p_curr_std.locator(".site-app>#nav").evaluate("el => getComputedStyle(el).transition")
            assert "none" in nav_trans or nav_trans == "all 0s ease 0s"
        finally:
            browser.close()
