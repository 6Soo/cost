"""공통 셸: 주요 소유자 화면이 320·390px에서 가로로 넘치지 않고 제목·브랜드가 중복되지 않는다. 합성 자료만 쓴다."""
import re
import threading

import pytest

from tools.run_synthetic_preview import preview_server
from webapp import ledger_board

try:
    from playwright.sync_api import sync_playwright
except ImportError:  # pragma: no cover
    sync_playwright = None

ROUTES = ('/', '/trips', '/board?tab={tab}', '/board?tab=quarter%3A2026%3A4', '/board?tab=refunds',
          '/cards/all', '/cards/all?panel=upload', '/cards/all?panel=coverage', '/ota', '/receipts',
          '/receipts?trip={tab}', '/participants?trip={tab}', '/expense/new?tab={tab}',
          '/income/new?tab={tab}', '/export', '/access/admin', '/reserve-links')
BRAND = '숲길여행 회계'


@pytest.mark.skipif(sync_playwright is None, reason='playwright is not installed')
def test_owner_screens_fit_phone_widths_and_share_one_brand():
    with preview_server() as server:
        threading.Thread(target=server.serve_forever, daemon=True).start()
        tab = next(iter(ledger_board.live_trips(include_archived=True)))['tab_id']
        base = f'http://127.0.0.1:{server.server_address[1]}'
        with sync_playwright() as api:
            browser = api.chromium.launch()
            try:
                for width in (320, 390):
                    page = browser.new_page(viewport={'width': width, 'height': 720})
                    page.goto(base + '/preview')
                    for route in ROUTES:
                        path = route.format(tab=tab)
                        assert page.goto(base + path).status == 200, path
                        scroll = page.evaluate('document.documentElement.scrollWidth')
                        assert scroll <= width, (path, width, scroll)
                        title = page.title()
                        assert not re.fullmatch(re.escape(BRAND) + r'\s*·\s*' + re.escape(BRAND), title), (path, title)
                        assert title.endswith(' · ' + BRAND) and title != ' · ' + BRAND, (path, title)
                        visible_brand = page.locator('.site-topbar >> text=' + BRAND)
                        assert visible_brand.count() <= 1, path
                        h1 = page.locator('h1').first.inner_text().strip()
                        assert title == h1 + ' · ' + BRAND, (path, title, h1)
                        # Skip link is the first focus stop.
                        page.keyboard.press('Tab')
                        assert page.evaluate('document.activeElement.className') == 'skip-link', path
                        page.evaluate('document.activeElement.blur()')
                    page.close()
            finally:
                browser.close()
