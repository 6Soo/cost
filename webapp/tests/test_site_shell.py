from unittest.mock import patch

from webapp import ledger_design, site_shell, ledger_board


def test_standalone_pages_share_navigation_without_changing_page_scripts():
    original = '<html><head><title>Card</title></head><body><main><input id="amount"></main><script>const saved=1;</script></body></html>'
    with patch.object(ledger_board, 'current_role', return_value='owner'), patch('webapp.ledger_design._nav_html', return_value='<aside id="nav">Menu</aside><div id="nav-mask" hidden></div>'):
        result = site_shell.wrap_document(original, '/cards')
    assert result.count('id="nav"') == 1
    assert 'id="amount"' in result and 'const saved=1;' in result
    assert 'id="site-content"' in result and 'site-menu-toggle' in result
    assert site_shell.wrap_document(result, '/cards') == result


def test_native_pages_keep_their_existing_navigation_and_fragments_stay_fragments():
    original = "<html><head></head><body><div class='app'><aside id='nav'></aside><main id='main'>ledger</main></div></body></html>"
    result = site_shell.wrap_document(original, '/board')
    assert result.count("id='nav'") == 1
    assert 'id="site-content"' not in result
    assert '<main id=\'main\'>' in result
    assert site_shell.wrap_document('<section>partial</section>', '/board') == '<section>partial</section>'


def test_shell_theme_tokens_cover_native_navigation_documents():
    assert ':root{--shell-bg:#F8FAFC' in site_shell.STYLE
    assert '@media(prefers-color-scheme:dark){:root{--shell-bg:#0F172A' in site_shell.STYLE
    assert 'body.site-standalone,body:has(.site-topbar)' not in site_shell.STYLE


def test_browser_shell_tracks_system_theme_and_mobile_menu_keyboard():
    from playwright.sync_api import sync_playwright

    original = '<!doctype html><html><head><title>Synthetic shell</title></head><body><main>내용</main></body></html>'
    with patch.object(ledger_board, 'current_role', return_value='owner'):
        document = site_shell.wrap_document(original, '/cards')

    with sync_playwright() as api:
        browser = api.chromium.launch(headless=True)
        try:
            page = browser.new_page(viewport={'width': 375, 'height': 812})
            page.set_content(document)
            page.emulate_media(color_scheme='light')
            assert page.locator(':root').evaluate(
                "element => getComputedStyle(element).getPropertyValue('--shell-bg').trim()") == '#F8FAFC'
            page.emulate_media(color_scheme='dark')
            assert page.locator(':root').evaluate(
                "element => getComputedStyle(element).getPropertyValue('--shell-bg').trim()") == '#0F172A'

            toggle = page.get_by_role('button', name='전체 메뉴 열기')
            assert toggle.is_visible()
            toggle.focus()
            page.keyboard.press('Enter')
            assert page.locator('#nav').evaluate("element => element.classList.contains('open')")
            page.keyboard.press('Escape')
            assert not page.locator('#nav').evaluate("element => element.classList.contains('open')")
            assert toggle.evaluate('element => document.activeElement === element')

            page.set_viewport_size({'width': 759, 'height': 812})
            assert toggle.is_visible()
            page.set_viewport_size({'width': 1280, 'height': 900})
            assert not toggle.is_visible()
        finally:
            browser.close()


def test_public_login_and_forbidden_pages_never_gain_private_navigation():
    document = '<html><body>Login</body></html>'
    assert site_shell.wrap_document(document, '/auth/google/start') == document
    assert site_shell.wrap_document(document, '/demo') == document
    assert site_shell.wrap_document(document, '/cards', status=403) == document


def test_brand_links_home_and_side_menu_has_no_standalone_home():
    for role in ('owner', 'viewer'):
        with patch.object(ledger_board, 'current_role', return_value=role), patch.object(
                ledger_design, 'nav_region', return_value=''):
            html = ledger_design._nav_html('', '')
        assert "<a class='brand brand-link' href='/'" in html
        assert '숲길여행 회계' in html
        assert html.count("href='/'") == 1
        assert '>홈</span></a>' not in html


def test_brand_link_keeps_hover_and_focus_styles():
    assert 'a.brand:hover' in ledger_design.STYLE
    assert 'a.brand:focus-visible' in ledger_design.STYLE
    assert 'a.brand{min-height:44px' in ledger_design.STYLE
    assert '#nav a.brand:hover' in site_shell.STYLE
    assert '#nav a.brand:focus-visible' in site_shell.STYLE
    assert '#nav a.brand{min-height:44px' in site_shell.STYLE


def test_flight_passenger_link_is_owner_only_and_feature_gated():
    with patch.object(ledger_board, 'current_role', return_value='owner'), \
            patch('webapp.flight_passenger_page.enabled', return_value=True):
        owner = ledger_design._nav_html('', '')
    with patch.object(ledger_board, 'current_role', return_value='viewer'), \
            patch('webapp.flight_passenger_page.enabled', return_value=True):
        viewer = ledger_design._nav_html('', '')
    with patch.object(ledger_board, 'current_role', return_value='owner'), \
            patch('webapp.flight_passenger_page.enabled', return_value=False):
        disabled = ledger_design._nav_html('', '')
    assert "href='/flight-passengers'" in owner
    assert "href='/flight-passengers'" not in viewer
    assert "href='/flight-passengers'" not in disabled


def test_cleanup_preserves_errors_confirmation_and_scripts():
    original = ("<p>자동 추출은 연결되지 않았습니다. 사진을 보고 입력하세요.</p>"
                "<p role='alert'>자동 추출은 연결되지 않았습니다. 설정을 확인하세요.</p>"
                "<p>원본 이미지가 전송됩니다. 동의 후 실행하세요.</p>"
                "<button disabled>저장 준비 중</button>"
                "<script>const csrf='synthetic';const message='<p>자동 추출은 연결되지 않았습니다.</p>';</script>")
    result=site_shell.clean_static_help(original)
    assert '사진을 보고 입력하세요' not in result
    assert '저장 준비 중' not in result
    assert "role='alert'" in result and '원본 이미지가 전송됩니다' in result
    assert "const csrf='synthetic'" in result and "const message='<p>자동 추출" in result


def test_home_omits_unavailable_features_instead_of_placeholder_cards():
    with patch.object(ledger_board,'current_role',return_value='owner'), \
         patch('webapp.receipt_review.enabled',return_value=False), \
         patch('webapp.google_ledger_page.enabled',return_value=False):
        body=ledger_design.work_menu_html()
    assert '영수증 처리' not in body and '확정 장부' not in body
    assert '설정 필요' not in body and '미연결' not in body
    assert "href='/import'" in body and "href='/ota'" in body and "href='/cards'" not in body
    assert '<small>' not in body
