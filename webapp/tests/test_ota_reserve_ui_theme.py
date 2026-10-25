"""Synthetic design contract checks for the OTA and reservation owner screens."""

from webapp.card_catalog import CATALOG_STYLE
from webapp.ota_catalog import OTA_STYLE
from webapp.reserve_link_ui import _DOCUMENT


def test_catalog_and_ota_styles_follow_system_theme_and_keep_accessible_focus():
    assert "prefers-color-scheme:dark" in CATALOG_STYLE
    assert "--cc-surface" in CATALOG_STYLE
    assert ":focus-visible" in CATALOG_STYLE
    assert "prefers-color-scheme:dark" in OTA_STYLE
    assert ".ota-badge.ok" in OTA_STYLE
    assert ".ota-badge.bad" in OTA_STYLE
    assert ":focus-visible" in OTA_STYLE


def test_reservation_link_ui_has_dark_tokens_mobile_layout_and_large_controls():
    assert "prefers-color-scheme: dark" in _DOCUMENT
    assert "@media (max-width:375px)" in _DOCUMENT
    assert "min-height:44px" in _DOCUMENT
    assert ":focus-visible" in _DOCUMENT
    assert 'id="saveBtn"' in _DOCUMENT
    assert 'id="applyBtn"' in _DOCUMENT


def test_reservation_link_ui_does_not_add_manual_theme_preference_storage():
    assert "localStorage" not in _DOCUMENT
    assert "theme-toggle" not in _DOCUMENT
    assert "prefers-color-scheme" in _DOCUMENT
