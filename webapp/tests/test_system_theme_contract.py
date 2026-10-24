# System theme contract targeted test for COST-THEME-001
# Scope: ledger_design.py common CSS tokens + light/dark media only
# No DB/Google/auth/JS/financial changes.

import re

LEDGER = "webapp/ledger_design.py"


def test_token_palette_light_a_and_dark_b_in_ledger_design():
    with open(LEDGER, "r", encoding="utf-8", errors="ignore") as f:
        css = f.read()
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
    with open(LEDGER, "r", encoding="utf-8", errors="ignore") as f:
        css = f.read()
    lower = css.lower()
    assert "localstorage" not in lower, "manual localStorage theme storage found"
    assert "toggle" not in lower or "class=\"toggle\"" not in lower, "manual toggle selector found"
    # No cookie/db toggle API references in CSS block
    assert "cookie" not in lower.split("<script")[0], "cookie reference in CSS block"


def test_common_selectors_use_token_variables():
    with open(LEDGER, "r", encoding="utf-8", errors="ignore") as f:
        css = f.read()
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
    with open(LEDGER, "r", encoding="utf-8", errors="ignore") as f:
        css = f.read()
    light_bg = css.find("--bg:#F8FAFC")
    dark_bg = css.find("--bg:#0F172A")
    assert light_bg >= 0 and dark_bg > light_bg, "light/dark token ordering wrong for dynamic switch"
