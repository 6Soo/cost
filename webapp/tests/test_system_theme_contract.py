# System theme contract targeted test for COST-THEME-001
# Scope: ledger_design.py common CSS tokens + light/dark media only
# No DB/Google/auth/JS/financial changes.

import re

from webapp import ledger_design, ledger_design_assets, site_assets, site_shell, site_theme


def _ledger_source() -> str:
    """Runtime content of ledger_design styles and scripts."""
    return ledger_design.STYLE + "\n" + ledger_design.SCRIPT


def test_token_palette_light_a_and_dark_b_in_ledger_design():
    css = _ledger_source()
    # Semantic tokens are now owned by tokens.css and included before the
    # ledger stylesheet.
    assert "--c-bg: #F8FAFC" in css
    assert "--c-text: #0F172A" in css
    assert "--c-border: #E2E8F0" in css
    assert "--c-text-secondary: #475569" in css
    assert "@media (prefers-color-scheme: dark)" in css
    assert "--c-bg: #0F172A" in css
    assert "--c-text: #F8FAFC" in css
    assert "--c-border: #334155" in css
    assert "--c-text-secondary: #CBD5E1" in css


def test_no_manual_toggle_or_localstorage_in_css():
    # The sole manual theme control belongs to the shared shell and is backed
    # by its browser-only bootstrap. No page-specific toggle is introduced.
    assert site_shell.BUTTON.count('id="site-theme-toggle"') == 1
    assert 'data-theme-icon="light"' in site_shell.BUTTON
    assert 'data-theme-icon="dark"' in site_shell.BUTTON
    assert 'aria-label="다크모드로 전환"' in site_shell.BUTTON
    assert 'localStorage' in site_theme.BOOTSTRAP
    assert 'localstorage' not in site_assets.SHELL_STYLE.lower()
    assert 'localstorage' not in site_assets.THEME_STYLE.lower()


def test_common_selectors_use_token_variables():
    css = _ledger_source()
    # Syntactic: core common selectors reference tokens, not hardcoded hex only
    checks = [
        ("body background", r"body\{[^}]*background:var\(--bg\)"),
        ("focus accent", r"outline:2px solid var\(--focus\)"),
        ("panel/bg usage", r"background:var\(--bg\)"),
        ("border usage", r"border:1px solid var\(--line\)"),
    ]
    for name, pat in checks:
        assert re.search(pat, css), f"common selector token linkage missing: {name}"


def test_synthetic_light_dark_dynamic_switch_by_media():
    # Shared palette follows the system by default; the manual theme bootstrap
    # then applies the persisted user choice independently of system changes.
    css = site_assets.SHELL_STYLE + "\n" + site_assets.THEME_STYLE
    assert "@media (prefers-color-scheme: dark)" in css
    assert "--shell-bg: var(--c-bg)" in css
    assert "--shell-ink: var(--c-text)" in css
    assert "root.dataset.theme=theme" in site_theme.BOOTSTRAP
    assert "root.style.colorScheme=theme" in site_theme.BOOTSTRAP
    assert "cost-theme" in site_theme.BOOTSTRAP


def test_synthetic_site_shell_theme_mobile_and_keyboard_accessibility():
    shell = site_assets.SHELL_STYLE + "\n" + site_assets.SHELL_SCRIPT
    assert "--shell-bg: var(--c-bg)" in shell and "--shell-ink: var(--c-text)" in shell
    assert "--c-bg: #0F172A" in shell and "--c-text: #F8FAFC" in shell
    assert "background:var(--shell-paper,#fff)" in shell
    assert "width:min(var(--shell-drawer-width,min(300px,85vw)),100%)" in shell
    assert "#nav a:focus-visible,#nav button:focus-visible" in shell
    assert "e.key==='Tab'" in shell and "e.key==='Escape'" in shell
    assert 'aria-controls="nav" aria-expanded="false"' in site_shell.MENU_TOGGLE
    assert "--c-text-tertiary: #94A3B8" in shell and "--c-warn-text: #FBBF24" in shell
    assert "#nav .nav-sec" in shell and "color:var(--shell-muted,#667085)" in shell
    assert "#nav .ct.warn{color:var(--shell-warn,#B54708)}" in shell


def test_synthetic_dark_palette_keeps_focus_and_status_contrast():
    css = ledger_design_assets.STYLE
    shell_css = site_assets.SHELL_STYLE
    theme_css = site_assets.THEME_STYLE
    assert "--c-focus: #93C5FD" in shell_css
    assert "--grn-dk: var(--c-accent-solid-hover)" in css
    assert "--grn-hover: var(--c-accent-solid-hover)" in css
    assert "--grn-lt: var(--c-accent-subtle)" in css
    assert "--warn: var(--c-warn-text)" in css and "--neg: var(--c-danger-text)" in css
    assert ".btn.primary:hover{background:var(--c-accent-solid-hover)" in css
    assert "--shell-danger" not in theme_css
