from playwright.sync_api import sync_playwright

from webapp import google_ledger_page as gl
from webapp.tests.test_google_mapping_integrity import app
from webapp.tests import test_google_viewer_http as existing


def test_settings_are_owner_only_and_do_not_guess_connections(app):
    status, body = app.call('/google-ledger', existing.OWNER)
    assert status == 200
    assert 'id="google-settings"' in body
    assert app.trip in body
    assert existing.VIEWER in body
    assert not gl.mapping_path(app.snapshot).exists()
    assert not gl.grants_path(app.snapshot).exists()
    status, body = app.call('/google-ledger', existing.VIEWER)
    assert status == 200
    assert 'id="google-settings"' not in body
    assert existing.OTHER not in body


def test_owner_can_link_grant_reload_and_revoke_in_mobile_browser(app):
    app.link_and_assign(existing.VIEWER, app.trip)
    with sync_playwright() as api:
        browser = api.chromium.launch()
        try:
            page = browser.new_page(viewport={'width': 375, 'height': 812},
                extra_http_headers={existing.access_control.SyntheticSessionAdapter.HEADER: existing.OWNER})
            page.on('dialog', lambda dialog: dialog.accept())
            page.goto(f'http://127.0.0.1:{app.port}/google-ledger')
            page.locator('#google-settings summary').click()
            page.locator('#settings-key').select_option('0630_오제')
            page.locator('#settings-tab').select_option(app.trip)
            page.locator('#mapping-save').click()
            page.get_by_role('status').filter(has_text='여행 연결을 저장했습니다').wait_for()
            page.reload()
            page.locator('#google-settings summary').click()
            page.locator('#settings-key').select_option('0630_오제')
            assert page.locator('#settings-tab').input_value() == app.trip
            page.locator('#settings-viewer').select_option(existing.VIEWER)
            page.locator('#grant-add').click()
            page.get_by_role('status').filter(has_text='열람을 허용했습니다').wait_for()
            assert '0630_오제' in gl.load_grants(app.snapshot)['grants'][existing.VIEWER]
            status, body = app.call('/api/google-ledger', existing.VIEWER)
            assert status == 200 and '0630_오제' in body
            assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
            page.locator('#grant-remove').click()
            page.get_by_role('status').filter(has_text='열람 허용을 철회했습니다').wait_for()
            status, body = app.call('/api/google-ledger', existing.VIEWER)
            assert status == 200 and '0630_오제' not in body
        finally:
            browser.close()
