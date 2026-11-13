from webapp import card_flow, ledger_design, site_shell


def test_desktop_navigation_and_main_are_independent_viewport_scrollers():
    css = ledger_design.STYLE

    assert ".app{display:flex;height:100dvh;min-height:0;overflow:hidden}" in css
    assert "display:flex;flex-direction:column;min-height:0;overflow:auto" in css
    assert ".main{flex:1 1 auto;min-width:0;min-height:0;contain:layout;overflow:auto;background:var(--paper)}" in css


def test_mobile_menu_trigger_stays_visible_in_main_scrollport():
    css = ledger_design.STYLE
    mobile = css.split("@media (width < 760px){", 1)[1]

    assert "#btn-menu{display:inline-flex" in mobile
    assert ".bar{position:sticky;top:0;z-index:3;background:var(--paper)}" in mobile
    assert ".tw thead th{top:var(--mobile-bar-height,0px)}" in mobile
    assert "main.style.setProperty('--mobile-bar-height',stickyBar.getBoundingClientRect().height+'px')" in ledger_design.SCRIPT
    assert ".nav-mask{display:block;position:fixed;inset:0;z-index:44" in mobile
    assert ".nav.open{transform:none}" in mobile


def test_import_document_wrapper_adds_sticky_mobile_navigation():
    page = card_flow.page("synthetic-csrf").replace(
        "</main>", "<section id=\"expense-cleanup\">합성 지출</section></main>", 1)
    document = site_shell.wrap_document(page, "/import")

    # The unified shell (PR-3) replaced the old site-menu-toggle topbar with a
    # sticky topbar plus a fixed bottom navigation; the page content survives.
    assert '<header class="site-topbar">' in document
    assert 'site-bottom-nav' in document
    assert ".site-topbar{position:sticky;top:0;z-index:30" in site_shell.STYLE
    assert ".site-bottom-nav{position:fixed" in site_shell.STYLE
    assert 'id="expense-cleanup"' in document
