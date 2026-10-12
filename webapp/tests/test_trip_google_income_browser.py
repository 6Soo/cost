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
        context = self.browser.new_context(viewport={'width': 390, 'height': 844})
        self.addCleanup(context.close)
        context.set_extra_http_headers({access_control.SyntheticSessionAdapter.HEADER: OWNER})
        page = context.new_page()
        base = f'http://127.0.0.1:{self.port}'
        board_url = base + '/board?tab=' + trip['tab_id']
        page.goto(board_url)
        panel = page.locator('#google-trip-income')
        self.assertIn('미연결', panel.inner_text())
        panel.get_by_role('link', name='수입 장부 연결 설정').click()
        page.locator('#google-settings').evaluate('(el) => el.open = true')
        self.assertEqual(page.input_value('#settings-tab'), trip['tab_id'])
        page.select_option('#settings-key', key)
        self.assertEqual(page.input_value('#settings-tab'), trip['tab_id'])
        page.on('dialog', lambda dialog: dialog.accept())
        page.click('#mapping-save')
        page.wait_for_function("document.querySelector('#settings-status').textContent.includes('저장했습니다')")
        page.get_by_role('link', name='선택한 여행으로 돌아가기').click()
        self.assertEqual(page.url, board_url)
        panel = page.locator('#google-trip-income')
        self.assertIn('Google 확정 수입 1,000원', panel.inner_text())
        self.assertIn('INCOME-NAME', panel.inner_text())
        self.assertLessEqual(page.evaluate('document.documentElement.scrollWidth'), 390)
        page.reload()
        self.assertIn('INCOME-NAME', page.locator('#google-trip-income').inner_text())
        page.locator('#google-trip-income').get_by_role('link', name='수입·지출 원본 상세').click()
        self.assertIn('INCOME-NAME', page.inner_text('body'))
        self.assertTrue(page.url.endswith('#income'))
        self.assertEqual(self.server.card_store.conn.execute(
            "SELECT COUNT(*) FROM board_rows WHERE row_kind='income'").fetchone()[0], 0)
