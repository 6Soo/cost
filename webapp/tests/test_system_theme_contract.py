# System theme contract targeted test for COST-THEME-001
# Scope: ledger_design.py common CSS tokens + light/dark media only
# No DB/Google/auth/JS/financial changes.

import re
from pathlib import Path

from webapp import ledger_design


def _ledger_source() -> str:
    """Runtime content of ledger_design styles and scripts."""
    return ledger_design.STYLE + "\n" + ledger_design.SCRIPT


def test_token_palette_light_a_and_dark_b_in_ledger_design():
    css = _ledger_source()
    # Light A token presence (spec §4.2)
    assert "--bg:#F8FAFC" in css, "light A page bg missing"
    assert "--ink:#0F172A" in css, "light A primary text missing"
    assert "--line:#E2E8F0" in css, "light A border missing"
    assert "--mut:#475569" in css, "light A secondary text missing"
    # Dark B token presence via media
    assert "@media(prefers-color-scheme:dark)" in css, "dark media query missing"
    dark_start = css.find("@media(prefers-color-scheme:dark)")
    dark_chunk = css[dark_start:dark_start + 1200]
    assert "--bg:#0F172A" in dark_chunk, "dark B page bg missing"
    assert "--ink:#F8FAFC" in dark_chunk, "dark B primary text missing"
    assert "--line:#334155" in dark_chunk, "dark B border missing"
    assert "--mut:#94A3B8" in dark_chunk, "dark B secondary text missing"


def test_no_manual_toggle_or_localstorage_in_css():
    css = _ledger_source()
    lower = css.lower()
    assert "localstorage" not in lower, "manual localStorage theme storage found"
    assert "toggle" not in lower or "class=\"toggle\"" not in lower, "manual toggle selector found"
    # No cookie/db toggle API references in CSS block
    assert "cookie" not in lower.split("<script")[0], "cookie reference in CSS block"


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
    # Synthetic fixture: media query defines different palette; no JS toggle needed.
    css = _ledger_source()
    light_bg = css.find("--bg:#F8FAFC")
    dark_bg = css.find("--bg:#0F172A")
    assert light_bg >= 0 and dark_bg > light_bg, "light/dark token ordering wrong for dynamic switch"


def test_synthetic_site_shell_theme_mobile_and_keyboard_accessibility():
    shell = Path("webapp/site_shell.py").read_text(encoding="utf-8")
    assert "--shell-bg:#F8FAFC" in shell and "--shell-ink:#0F172A" in shell
    assert "@media(prefers-color-scheme:dark){body.site-standalone,body:has(.site-topbar)" in shell
    assert "--shell-bg:#0F172A" in shell and "--shell-ink:#F8FAFC" in shell
    assert "background:var(--shell-paper,#fff)" in shell
    assert "width:min(300px,85vw,100%)" in shell
    assert "#nav a:focus-visible,#nav button:focus-visible" in shell
    assert "e.key==='Tab'" in shell and "e.key==='Escape'" in shell
    assert "close({restoreFocus:true})" in shell
    assert 'aria-controls="nav" aria-expanded="false"' in shell
    assert "let menuTrigger=null" in shell
    assert "if(open)menuTrigger=b" in shell
    assert "menuTrigger&&menuTrigger.getClientRects().length?menuTrigger" in shell
    assert "[...buttons].find(b=>b.getClientRects().length)" in shell
    assert "--shell-muted:#94A3B8" in shell and "--shell-warn:#FBBF24" in shell
    assert "#nav .nav-sec" in shell and "color:var(--shell-muted,#667085)" in shell
    assert "#nav .ct.warn{color:var(--shell-warn,#B54708)}" in shell


def test_synthetic_dark_palette_keeps_focus_and_status_contrast():
    css = _ledger_source()
    dark = css.split("@media(prefers-color-scheme:dark)", 1)[1].split("\n}", 1)[0]
    assert "--focus:#93C5FD" in dark
    assert "--grn-dk:#A7F3D0" in dark
    assert "--grn-hover:#166444" in dark
    assert "--grn-lt:#14532D" in dark
    assert "--warn:#FBBF24" in dark and "--neg:#FDA4AF" in dark
    assert ".btn.primary:hover{background:var(--grn-hover,var(--grn-dk))}" in css
