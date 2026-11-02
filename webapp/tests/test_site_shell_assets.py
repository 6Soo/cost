"""Targeted contract test for site shell & theme static assets (RF-201/203).

Verifies:
1. Pure asset ownership in webapp/site_assets.py and static files
2. Zero extra disk I/O per wrap_document render (preloaded on module import)
3. Bit-for-bit equivalence and constant re-export preservation
4. CSS cascade order and token coverage
"""

from pathlib import Path
import json
from unittest.mock import patch

from webapp import site_assets, site_shell, site_theme, ui_icons


def test_site_assets_module_owns_static_files():
    """Verify site_assets loads from webapp/static/css and webapp/static/js."""
    css_dir = Path("webapp/static/css")
    js_dir = Path("webapp/static/js")
    assert (css_dir / "site_shell.css").is_file()
    assert (js_dir / "site_shell.js").is_file()
    assert (css_dir / "site_theme.css").is_file()
    assert (js_dir / "site_theme.js").is_file()

    assert site_assets.SHELL_STYLE == (css_dir / "site_shell.css").read_text(encoding="utf-8")
    assert site_assets.SHELL_SCRIPT == (js_dir / "site_shell.js").read_text(encoding="utf-8").replace(
        '__ACTION_ICONS__', json.dumps(ui_icons.ICONS, ensure_ascii=True))
    assert site_assets.THEME_STYLE == (css_dir / "site_theme.css").read_text(encoding="utf-8")
    assert site_assets.THEME_BOOTSTRAP == (js_dir / "site_theme.js").read_text(encoding="utf-8")


def test_reexport_preserves_public_constants_identically():
    """Verify site_shell and site_theme re-export identical asset strings."""
    assert site_shell.STYLE is site_assets.SHELL_STYLE
    assert site_shell.SCRIPT is site_assets.SHELL_SCRIPT
    assert site_theme.STYLE is site_assets.THEME_STYLE
    assert site_theme.BOOTSTRAP is site_assets.THEME_BOOTSTRAP


def test_zero_disk_io_on_document_wrap():
    """Verify wrap_document performs zero filesystem reads per invocation."""
    import webapp.ledger_design  # Prewarm modules so import-time loads have completed
    with patch("pathlib.Path.read_text", side_effect=AssertionError("Unexpected disk read during render!")):
        with patch("pathlib.Path.read_bytes", side_effect=AssertionError("Unexpected disk read during render!")):
            with patch("builtins.open", side_effect=AssertionError("Unexpected disk read during render!")):
                with patch("webapp.ledger_design._nav_html", return_value="<aside id='nav'></aside>"):
                    html = site_shell.wrap_document(
                        "<!doctype html><html><head><title>Test</title></head><body><main>Content</main></body></html>",
                        "/cards/all"
                    )
    assert 'id="site-shell-style"' in html
    assert 'id="site-theme-toggle"' in html


def test_css_cascade_order_and_tokens_preserved():
    """Verify cascade order in <head>: site_shell.STYLE followed by site_theme.STYLE."""
    doc = "<!doctype html><html><head><title>T</title></head><body><main>M</main></body></html>"
    with patch("webapp.ledger_design._nav_html", return_value="<aside id='nav'></aside>"):
        wrapped = site_shell.wrap_document(doc, "/cards")

    style_block = wrapped.split('<style id="site-shell-style">', 1)[1].split('</style>', 1)[0]
    # Shell style precedes theme style
    shell_part, theme_part = style_block.split(':root{--shell-theme-control-size:var(--shell-control-min,44px)', 1)
    assert "--shell-bg:#F8FAFC" in shell_part
    assert "@media(prefers-color-scheme:dark){:root{--shell-bg:#0F172A" in shell_part
    assert "@media(prefers-reduced-motion:reduce)" in shell_part
    assert "--bg:var(--shell-bg)" in theme_part
    assert "#site-theme-toggle" in theme_part


def test_shared_components_alias_live_ledger_and_review_consumers():
    css = Path("webapp/static/css/ledger_design.css").read_text(encoding="utf-8")
    assert ".ui-form,.arch-restore" in css
    assert ".bar{display:flex" in css  # Existing GET filter form
    assert ".ui-card,.refund-card" in css
    assert ".ui-state,.status" in css
    assert ".ui-state--error,.status.err,.f-msg.err,.copy-status.err" in css
    assert ".ui-state--stale,.cleanup-snapshot-stale" in css
    assert ".ui-state--loading,.cleanup-snapshot-loading,.copy-status.loading" in css
    assert "prefers-reduced-motion:reduce){.ui-state[aria-busy=true]::before,.cleanup-snapshot-loading::before" in css
