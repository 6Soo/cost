"""Shared shell mobile header keeps navigation and theme control in one row."""
from webapp import site_shell


def test_standalone_header_theme_is_inline_not_before_menu():
    doc = '<!doctype html><html><head><title>Flight</title></head><body><main>예약</main></body></html>'
    html = site_shell.wrap_document(doc, '/flight-passengers')
    header = html.split('<header class="site-topbar">', 1)[1].split('</header>', 1)[0]
    assert 'site-menu-toggle' in header
    assert 'COST 업무 메뉴' in header
    assert 'site-theme-toggle' in header
    assert html.count('id="site-theme-toggle"') == 1
    assert 'site-topbar>.site-theme-bar' in html
