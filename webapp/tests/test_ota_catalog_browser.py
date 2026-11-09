import json
import os
from unittest.mock import patch

from webapp import access_control
from webapp.tests.test_ota_catalog import source_database
from webapp.tests.test_reserve_link import OWNER
from webapp.tests.test_reserve_link_browser import LinkBrowserFixture


class OtaCatalogBrowserTests(LinkBrowserFixture):
    def test_mobile_dark_row_labels_have_readable_contrast(self):
        source = self.tmp / 'ota-dark.sqlite'
        source_database(source)
        env = patch.dict(os.environ, {
            'WEBLEDGER_OTA_SOURCES_JSON': json.dumps({'portal_databases': [str(source)], 'mail_directories': []}),
            'WEBLEDGER_REVIEW_CONFIG': '',
        })
        env.start()
        self.addCleanup(env.stop)
        context = self.browser.new_context(viewport={'width': 390, 'height': 844}, color_scheme='dark')
        self.addCleanup(context.close)
        context.set_extra_http_headers({access_control.SyntheticSessionAdapter.HEADER: OWNER})
        page = context.new_page()
        page.goto(f'http://127.0.0.1:{self.port}/ota')
        cell = page.locator('main.card-catalog tbody tr td[data-label]').first
        cell.wait_for(state='visible')
        contrast = cell.evaluate('''element => {
          const rgb = s => s.match(/[\\d.]+/g).slice(0, 3).map(Number);
          const lum = c => c.map(x => { x /= 255; return x <= .04045 ? x / 12.92 : ((x + .055) / 1.055) ** 2.4; })
            .reduce((sum, x, i) => sum + x * [.2126, .7152, .0722][i], 0);
          const foreground = lum(rgb(getComputedStyle(element, '::before').color));
          const background = lum(rgb(getComputedStyle(element.closest('tr')).backgroundColor));
          return (Math.max(foreground, background) + .05) / (Math.min(foreground, background) + .05);
        }''')
        self.assertGreaterEqual(contrast, 4.5)

    def test_empty_state_message_stays_wide_at_mobile(self):
        env = patch.dict(os.environ, {
            'WEBLEDGER_OTA_SOURCES_JSON': json.dumps({'portal_databases': [], 'mail_directories': []}),
            'WEBLEDGER_REVIEW_CONFIG': '',
        })
        env.start()
        self.addCleanup(env.stop)
        context = self.browser.new_context(viewport={'width': 390, 'height': 844})
        self.addCleanup(context.close)
        context.set_extra_http_headers({access_control.SyntheticSessionAdapter.HEADER: OWNER})
        page = context.new_page()
        page.goto(f'http://127.0.0.1:{self.port}/ota')
        page.get_by_text('조회된 OTA 예약이 없습니다.', exact=False).wait_for(state='visible')
        cell = page.locator('main.card-catalog tbody td[colspan="7"]')
        self.assertIn('조회된 OTA 예약이 없습니다.', cell.inner_text())
        self.assertLess(cell.bounding_box()['height'], 100)

    def test_shared_menu_all_unassigned_search_and_header_filters(self):
        source = self.tmp / 'ota.sqlite'
        source_database(source)
        env = patch.dict(os.environ, {
            'WEBLEDGER_OTA_SOURCES_JSON': json.dumps({'portal_databases': [str(source)], 'mail_directories': []}),
            'WEBLEDGER_REVIEW_CONFIG': '',
        })
        env.start()
        self.addCleanup(env.stop)
        original = source.read_bytes()
        before = self.server.card_store.conn.total_changes
        for width in (390, 760, 1440):
            with self.subTest(width=width):
                context = self.browser.new_context(viewport={'width': width, 'height': 900})
                self.addCleanup(context.close)
                context.set_extra_http_headers({access_control.SyntheticSessionAdapter.HEADER: OWNER})
                page = context.new_page()
                page.goto(f'http://127.0.0.1:{self.port}/board')
                if width < 760:
                    page.get_by_role('button', name='전체 메뉴 열기', exact=True).click()
                self.assertEqual(page.locator('#nav a[href="/ota"]').count(), 1)
                self.assertEqual(page.locator('#nav a[href*="state=unassigned"]').count(), 0)
                page.locator('#nav').get_by_role('link', name='OTA 내역', exact=False).click()
                self.assertEqual(page.locator('#nav').count(), 1)
                self.assertIn('전체 3건', page.inner_text('#card-count'))
                rows = page.locator('main.card-catalog > table tbody tr')
                self.assertEqual(rows.count(), 3)
                self.assertIn('2026-10-01', rows.first.inner_text())
                self.assertEqual(
                    rows.first.locator('td').first.evaluate('e=>getComputedStyle(e).display'),
                    'grid' if width < 1024 else 'table-cell')
                page.locator('main').get_by_role('link', name='여행 연결 없음', exact=True).click()
                self.assertEqual(rows.count(), 1)
                self.assertIn('BOOK-1', rows.inner_text())
                self.assertNotIn('BOOK-2', rows.inner_text())
                page.get_by_label('OTA 내역 검색').fill('BOOK-1')
                page.get_by_role('button', name='검색', exact=True).click()
                self.assertEqual(rows.count(), 1)
                page.reload()
                self.assertEqual(page.get_by_label('OTA 내역 검색').input_value(), 'BOOK-1')
                self.assertEqual(page.locator('input[name="state"]').input_value(), 'unassigned')
                page.get_by_role('link', name='초기화', exact=True).click()
                page.get_by_role('button', name='이용일', exact=True).click()
                with page.expect_navigation():
                    page.locator("#filter-date [data-filter='sort'][data-value='asc']").click()
                self.assertIn('2026-10-01', rows.first.inner_text())
                page.get_by_role('button', name='이용일', exact=True).click()
                with page.expect_navigation():
                    page.get_by_role('button', name='2026-11월', exact=True).click()
                self.assertEqual(rows.count(), 1)
                self.assertIn('BOOK-1', rows.inner_text())
                self.assertLessEqual(page.evaluate('document.documentElement.scrollWidth'), width)
                context.close()
        self.assertEqual(source.read_bytes(), original)
        self.assertEqual(self.server.card_store.conn.total_changes, before)

    def test_long_trip_assignment_badge_wraps_without_sideways_overflow_at_390(self):
        import sqlite3
        source = self.tmp / 'ota-long.sqlite'
        conn = sqlite3.connect(source)
        conn.executescript('''
            CREATE TABLE bookings(id INTEGER PRIMARY KEY, provider TEXT, booking_number TEXT,
              product_type TEXT, label TEXT, service_start_on TEXT, service_end_on TEXT, status TEXT);
            CREATE TABLE allocation_targets(id INTEGER PRIMARY KEY, target_type TEXT, code TEXT, name TEXT);
            CREATE TABLE booking_target_links(booking_id INTEGER, target_id INTEGER, link_status TEXT);
        ''')
        long_trip = '합성 긴 여행 이름 ' + '가' * 60
        conn.execute('INSERT INTO bookings VALUES (?,?,?,?,?,?,?,?)',
                     (1, 'agoda', 'LONG-1', 'lodging', '합성 긴 예약 이름 ' + '나' * 60,
                      '2026-11-01', '2026-11-03', 'confirmed'))
        conn.execute("INSERT INTO allocation_targets VALUES (1,'trip','trip-long',?)", (long_trip,))
        conn.execute("INSERT INTO booking_target_links VALUES (1,1,'confirmed')")
        conn.commit()
        conn.close()
        env = patch.dict(os.environ, {
            'WEBLEDGER_OTA_SOURCES_JSON': json.dumps({'portal_databases': [str(source)], 'mail_directories': []}),
            'WEBLEDGER_REVIEW_CONFIG': '',
        })
        env.start()
        self.addCleanup(env.stop)
        context = self.browser.new_context(viewport={'width': 390, 'height': 844})
        self.addCleanup(context.close)
        context.set_extra_http_headers({access_control.SyntheticSessionAdapter.HEADER: OWNER})
        page = context.new_page()
        page.goto(f'http://127.0.0.1:{self.port}/ota')
        badge = page.locator('td[data-label="여행 배정"] .ota-badge.trip')
        badge.wait_for(state='visible')
        self.assertTrue(badge.is_visible())
        self.assertIn('합성 긴 여행 이름', badge.inner_text())
        self.assertLessEqual(page.evaluate('document.documentElement.scrollWidth'), 390)
