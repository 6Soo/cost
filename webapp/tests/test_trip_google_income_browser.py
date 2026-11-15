import datetime as dt
import json
import os
from unittest.mock import patch

from app import google_authority as ga
from webapp import access_control, google_ledger_page
from webapp.tests.test_google_canonical_workflow import healthy_snapshot
from webapp.tests.test_google_ledger_page import rows_doc
from webapp.tests.test_reserve_link import OWNER
from webapp.tests.test_reserve_link_browser import LinkBrowserFixture


class TripIncomeBrowserTests(LinkBrowserFixture):
    def test_owner_connects_income_then_reads_trip_and_original_rows_on_mobile(self):
        snapshot = healthy_snapshot()
        key = snapshot['trips'][0]['key']
        stamp = dt.datetime.now(ga.KST).isoformat()
        snapshot['synced_at'] = stamp
        for source in snapshot['sources'].values():
            source.update(last_ok_at=stamp, checked_at=stamp)
        snapshot_path, rows_path = self.tmp / 'google.json', self.tmp / 'rows.json'
        snapshot_path.write_text(json.dumps(snapshot), encoding='utf-8')
        ga._rows_file(rows_path, 'gen').write_text(json.dumps(rows_doc()), encoding='utf-8')
        google_ledger_page.record_choice(snapshot_path, key=key, source='main', at=stamp)
        env = patch.dict(os.environ, {
            'WEBLEDGER_GOOGLE_LEDGER_SNAPSHOT': str(snapshot_path),
            'WEBLEDGER_GOOGLE_LEDGER_ROWS': str(rows_path),
        })
        env.start()
        self.addCleanup(env.stop)
        trip = self.server.card_store.create_trip(starts_on='2026-10-05', ends_on='2026-10-09',
                                                  destination='Synthetic', client_request_id='income-trip-syn')
        google_ledger_page.set_mapping(snapshot_path, key=key, tab_id=trip['tab_id'], known_keys={key})
        context = self.browser.new_context(viewport={'width': 390, 'height': 844})
        self.addCleanup(context.close)
        context.set_extra_http_headers({access_control.SyntheticSessionAdapter.HEADER: OWNER})
        page = context.new_page()
        base = f'http://127.0.0.1:{self.port}'
        board_url = base + '/board?tab=' + trip['tab_id']
        page.goto(board_url)
        page.get_by_role('tab', name='수입', exact=True).click()
        panel = page.locator('#google-trip-income')
        self.assertIn('수입 1,000원', panel.inner_text())
        self.assertNotIn('확정 수입', panel.inner_text())
        self.assertIn('INCOME-NAME', panel.inner_text())
        self.assertLessEqual(page.evaluate('document.documentElement.scrollWidth'), 390)
        page.reload()
        page.get_by_role('tab', name='수입', exact=True).click()
        self.assertIn('INCOME-NAME', page.locator('#google-trip-income').inner_text())
        page.evaluate("document.querySelectorAll('#google-trip-income .income-detail').forEach(d=>d.open=true)")
        link = page.locator('#google-trip-income').get_by_role('link', name='수입·지출 원본 상세')
        self.assertEqual(link.get_attribute('href'), '/api/google-ledger/source?trip=' + trip['tab_id'])
        self.assertEqual(link.get_attribute('target'), '_blank')
        self.assertEqual(page.locator('#sum').get_by_text('수입', exact=True).count(), 1)
        self.assertEqual(self.server.card_store.conn.execute(
            "SELECT COUNT(*) FROM board_rows WHERE row_kind='income'").fetchone()[0], 0)

    def test_coherent_trip_board_layout_at_desktop_and_mobile_in_light_and_dark(self):
        snapshot = healthy_snapshot()
        # Use realistic wide monetary values: DOM text alone does not catch
        # an amount rendered as an ellipsis inside a compressed table cell.
        income_amount = 54840000
        snapshot['trips'][0]['copies']['main']['income'].update(
            total=income_amount, row_sum=income_amount, sheet_total=income_amount)
        income_rows = rows_doc()
        income_row = income_rows['sources']['main']['trips'][snapshot['trips'][0]['key']]['income'][0]
        income_row['amount'] = income_amount
        income_row['cells'].update(C='합성 참가자', E='1,360,000', F='53,480,000', G='0')
        key = snapshot['trips'][0]['key']
        stamp = dt.datetime.now(ga.KST).isoformat()
        snapshot['synced_at'] = stamp
        for source in snapshot['sources'].values():
            source.update(last_ok_at=stamp, checked_at=stamp)
        snapshot_path, rows_path = self.tmp / 'google.json', self.tmp / 'rows.json'
        snapshot_path.write_text(json.dumps(snapshot), encoding='utf-8')
        ga._rows_file(rows_path, 'gen').write_text(json.dumps(income_rows), encoding='utf-8')
        google_ledger_page.record_choice(snapshot_path, key=key, source='main', at=stamp)
        env = patch.dict(os.environ, {
            'WEBLEDGER_GOOGLE_LEDGER_SNAPSHOT': str(snapshot_path),
            'WEBLEDGER_GOOGLE_LEDGER_ROWS': str(rows_path),
        })
        env.start()
        self.addCleanup(env.stop)
        trip = self.server.card_store.create_trip(starts_on='2026-10-05', ends_on='2026-10-09',
                                                  destination='Synthetic', client_request_id='layout-trip-syn')
        google_ledger_page.set_mapping(snapshot_path, key=key, tab_id=trip['tab_id'], known_keys={key})

        base = f'http://127.0.0.1:{self.port}'
        board_url = base + '/board?tab=' + trip['tab_id']

        for scheme in ('light', 'dark'):
            for width, height in ((1280, 800), (900, 812), (800, 812), (760, 812), (375, 812), (320, 812)):
                with self.subTest(scheme=scheme, width=width):
                    context = self.browser.new_context(
                        viewport={'width': width, 'height': height},
                        color_scheme=scheme,
                    )
                    context.set_extra_http_headers({access_control.SyntheticSessionAdapter.HEADER: OWNER})
                    page = context.new_page()
                    page.goto(board_url)
                    page.get_by_role('tab', name='수입', exact=True).click()

                    # 1. Top summary shows coherent income, expense, and balance
                    sum_box = page.locator('#sum')
                    self.assertIn('수입', sum_box.inner_text())
                    self.assertIn('54,840,000원', sum_box.inner_text())
                    self.assertIn('지출', sum_box.inner_text())

                    # 2. Income panel header and badge
                    income_panel = page.locator('#google-trip-income')
                    summary_text = income_panel.locator('summary').inner_text()
                    self.assertTrue(summary_text.startswith('수입'))
                    self.assertIn('54,840,000원', summary_text)

                    # 3. Income table and attached subtotal footer
                    income_table = income_panel.locator('table')
                    self.assertEqual(income_table.count(), 1)
                    foot_label = income_table.locator('tfoot .income-foot-label')
                    self.assertIn('수입 행 합계', foot_label.inner_text())
                    self.assertEqual(income_table.locator('tfoot .income-total').inner_text(), '54,840,000원')

                    # 4. Unnested metadata bar
                    meta_bar = income_panel.locator('.income-meta-bar')
                    self.assertEqual(meta_bar.count(), 1)
                    self.assertIn('동기화', meta_bar.inner_text())
                    self.assertIn('장부 집계', meta_bar.inner_text())
                    orig_link = meta_bar.get_by_role('link', name='수입·지출 원본 상세')
                    self.assertTrue(orig_link.is_visible())

                    # 5. Expense table has no duplicate column headers
                    if width == 1280:
                        colhead_disp = page.locator('#tbl tbody.colhead').evaluate(
                            'el => window.getComputedStyle(el).display')
                        self.assertEqual(colhead_disp, 'none')

                    # 6. Viewport containment
                    self.assertLessEqual(page.evaluate('document.documentElement.scrollWidth'), width)
                    for cell in income_table.locator('tbody .income-total, tbody .income-breakdown:visible, tfoot .income-total').all():
                        self.assertLessEqual(cell.evaluate('el => el.scrollWidth'), cell.evaluate('el => el.clientWidth'))
                    if width >= 1024:
                        scroll = income_panel.locator('.google-income-scroll')
                        self.assertEqual(scroll.evaluate('el => getComputedStyle(el).overflowX'), 'auto')
                    else:
                        scroll = income_panel.locator('.google-income-scroll')
                        self.assertEqual(scroll.evaluate('el => getComputedStyle(el).overflowX'), 'visible')
                        self.assertLessEqual(scroll.evaluate('el => el.scrollWidth'), scroll.evaluate('el => el.clientWidth') + 8)
                    self.assertEqual(income_table.locator('tbody .income-total').first.inner_text(), '54,840,000원')
                    context.close()

    def test_discrepancy_warning_visibly_adjacent_without_artificial_balance(self):
        snapshot = healthy_snapshot()
        key = snapshot['trips'][0]['key']
        stamp = dt.datetime.now(ga.KST).isoformat()
        snapshot['synced_at'] = stamp
        for source in snapshot['sources'].values():
            source.update(last_ok_at=stamp, checked_at=stamp)
        # Introduce a sheet total that doesn't match rows total (2,000 != 1,000)
        snapshot['trips'][0]['copies']['main']['income'].update(
            total=2000, row_sum=2000, sheet_total=2000)
        snapshot_path, rows_path = self.tmp / 'google.json', self.tmp / 'rows.json'
        snapshot_path.write_text(json.dumps(snapshot), encoding='utf-8')
        ga._rows_file(rows_path, 'gen').write_text(json.dumps(rows_doc()), encoding='utf-8')
        google_ledger_page.record_choice(snapshot_path, key=key, source='main', at=stamp)
        env = patch.dict(os.environ, {
            'WEBLEDGER_GOOGLE_LEDGER_SNAPSHOT': str(snapshot_path),
            'WEBLEDGER_GOOGLE_LEDGER_ROWS': str(rows_path),
        })
        env.start()
        self.addCleanup(env.stop)
        trip = self.server.card_store.create_trip(starts_on='2026-10-05', ends_on='2026-10-09',
                                                  destination='Synthetic', client_request_id='gap-trip-syn')
        google_ledger_page.set_mapping(snapshot_path, key=key, tab_id=trip['tab_id'], known_keys={key})

        context = self.browser.new_context(viewport={'width': 1280, 'height': 800})
        self.addCleanup(context.close)
        context.set_extra_http_headers({access_control.SyntheticSessionAdapter.HEADER: OWNER})
        page = context.new_page()
        page.goto(f'http://127.0.0.1:{self.port}/board?tab=' + trip['tab_id'])
        page.get_by_role('tab', name='수입', exact=True).click()

        # Discrepancy alert is visibly present adjacent to income
        alert = page.locator('.income-discrepancy-alert')
        self.assertTrue(alert.is_visible())
        self.assertIn('일치하지 않습니다', alert.inner_text())

        # Top summary reports mismatch and does NOT fabricate artificial balance
        sum_box = page.locator('#sum')
        self.assertIn('장부 동기화 필요', sum_box.inner_text())
        self.assertIn('—', sum_box.inner_text())
