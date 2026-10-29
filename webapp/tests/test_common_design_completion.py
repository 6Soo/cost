"""Synthetic convergence checks for the standalone OTA/config presentation boundary."""

from webapp import ota_payment_review, site_assets, site_shell, site_theme


def test_shared_shell_assets_are_the_only_standalone_shell_source():
    assert site_shell.STYLE is site_assets.SHELL_STYLE
    assert site_shell.SCRIPT is site_assets.SHELL_SCRIPT
    assert "--shell-control-min:44px" in site_shell.STYLE
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
