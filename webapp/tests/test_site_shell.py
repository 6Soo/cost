from unittest.mock import patch

from webapp import site_shell, ledger_board


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


def test_public_login_and_forbidden_pages_never_gain_private_navigation():
    document = '<html><body>Login</body></html>'
    assert site_shell.wrap_document(document, '/auth/google/start') == document
    assert site_shell.wrap_document(document, '/demo') == document
    assert site_shell.wrap_document(document, '/cards', status=403) == document
