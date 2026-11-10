"""Synthetic design contract checks for the OTA and reservation owner screens."""

from webapp.card_catalog import CATALOG_STYLE
from webapp.ota_catalog import OTA_STYLE
from webapp.reserve_link_ui import _DOCUMENT


def test_catalog_and_ota_styles_follow_system_theme_and_keep_accessible_focus():
    assert "prefers-color-scheme:dark" not in CATALOG_STYLE
    assert "--cc-surface" in CATALOG_STYLE
    assert ":focus-visible" in CATALOG_STYLE
    assert "prefers-color-scheme:dark" not in OTA_STYLE
    assert ".ota-badge.ok" in OTA_STYLE
    assert ".ota-badge.bad" in OTA_STYLE
    assert ":focus-visible" in OTA_STYLE


def test_card_catalog_filters_and_popover_use_theme_tokens_without_fixed_light_colors():
    assert "--cc-surface:var(--c-surface)" in CATALOG_STYLE
    assert "--cc-border:var(--c-border)" in CATALOG_STYLE
    assert "--cc-text:var(--c-text)" in CATALOG_STYLE
    assert "--cc-soft:var(--c-surface-sunken)" in CATALOG_STYLE
    assert ".card-catalog #card-filters" in CATALOG_STYLE
    assert "#card-filters{display:flex" in CATALOG_STYLE
    assert "background:var(--cc-surface);border:1px solid var(--cc-border)" in CATALOG_STYLE
    assert ".card-catalog .header-menu" in CATALOG_STYLE
    assert "border:1px solid var(--cc-border);border-radius:var(--r-lg);background:var(--cc-surface)" in CATALOG_STYLE
    assert "color:var(--cc-text)" in CATALOG_STYLE
    assert ".card-catalog .header-menu h2{font-size:var(--t-caption);color:var(--cc-muted);" in CATALOG_STYLE
    assert ".card-catalog .filter-option:hover{background:var(--cc-soft)}" in CATALOG_STYLE
    filters_rule = CATALOG_STYLE.split("#card-filters{", 1)[1].split("}", 1)[0]
    popup_rule = CATALOG_STYLE.split(".header-menu{", 1)[1].split("}", 1)[0]
    assert "background:#fff" not in filters_rule
    assert "background:#fff" not in popup_rule
    assert "#E4E7EC" not in filters_rule + popup_rule


def test_reservation_link_ui_has_dark_tokens_mobile_layout_and_large_controls():
    assert "@import url('/static/css/tokens.css')" in _DOCUMENT
    assert "--bg:var(--c-bg)" in _DOCUMENT
    assert "prefers-color-scheme" not in _DOCUMENT
    assert "@media (max-width:375px)" in _DOCUMENT
    assert "min-height:44px" in _DOCUMENT
    assert ":focus-visible" in _DOCUMENT
    assert 'id="saveBtn"' in _DOCUMENT
    assert 'id="applyBtn"' in _DOCUMENT


def test_reservation_link_ui_does_not_add_manual_theme_preference_storage():
    assert "localStorage" not in _DOCUMENT
    assert "theme-toggle" not in _DOCUMENT
    assert "prefers-color-scheme" not in _DOCUMENT
