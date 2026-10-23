from webapp import card_flow, ledger_design, site_shell


def test_desktop_navigation_and_main_are_independent_viewport_scrollers():
    css = ledger_design.STYLE

    assert ".app{display:flex;height:100dvh;min-height:0}" in css
    assert "display:flex;flex-direction:column;min-height:0;overflow:auto" in css
    assert ".main{flex:1 1 auto;min-width:0;overflow:auto;background:var(--paper)}" in css


def test_mobile_menu_trigger_stays_visible_in_main_scrollport():
    css = ledger_design.STYLE
    mobile = css.split("@media (max-width:759px){", 1)[1]

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

    assert '<header class="site-topbar"><button' in document
    assert 'class="site-menu-toggle"' in document
    assert 'aria-controls="nav" aria-expanded="false"' in document
    assert ".site-topbar{position:sticky;top:0;z-index:20" in site_shell.STYLE
    assert 'document.querySelectorAll(\'.site-menu-toggle,#btn-menu\')' in site_shell.SCRIPT
    assert 'id="expense-cleanup"' in document
