import datetime as dt
import json
import os
from unittest.mock import patch

from app import google_authority as ga
from webapp import access_control, google_ledger_page, google_ledger_actions
from webapp.tests.test_google_canonical_workflow import healthy_snapshot
from webapp.tests.test_google_ledger_page import rows_doc
from webapp.tests.test_reserve_link import OWNER
from webapp.tests.test_reserve_link_browser import LinkBrowserFixture


class GoogleActionsBrowserTests(LinkBrowserFixture):
    def test_sync_real_http_worker_reload_and_failure_retry(self):
        snapshot = healthy_snapshot()
        stamp = dt.datetime.now(ga.KST).isoformat()
        snapshot['synced_at'] = stamp
        for source in snapshot['sources'].values():
            source.update(last_ok_at=stamp, checked_at=stamp)
        snapshot_path, rows_path = self.tmp / 'google.json', self.tmp / 'rows.json'
        snapshot_path.write_text(json.dumps(snapshot), encoding='utf-8')
        ga._rows_file(rows_path, 'gen').write_text(json.dumps(rows_doc()), encoding='utf-8')
        key = snapshot['trips'][0]['key']
        google_ledger_page.record_choice(snapshot_path, key=key, source='main', at=stamp)
        trip = self.server.card_store.create_trip(starts_on='2026-10-05', ends_on='2026-10-09',
            destination='Synthetic', client_request_id='actions-synthetic')
        google_ledger_page.set_mapping(snapshot_path, key=key, tab_id=trip['tab_id'], known_keys={key})
        with patch.dict(os.environ, {'WEBLEDGER_GOOGLE_LEDGER_SNAPSHOT': str(snapshot_path),
                                    'WEBLEDGER_GOOGLE_LEDGER_ROWS': str(rows_path)}):
            context = self.browser.new_context(viewport={'width': 390, 'height': 844})
            self.addCleanup(context.close)
            context.set_extra_http_headers({access_control.SyntheticSessionAdapter.HEADER: OWNER})
            page = context.new_page()
            page.goto(f'http://127.0.0.1:{self.port}/board?tab=' + trip['tab_id'])
            calls = []
            def sync(*args, **kwargs):
                calls.append(1)
                return snapshot
            with patch.object(google_ledger_actions.ga, 'sync', sync):
                with page.expect_navigation():
                    page.locator('[data-google-sync]').click()
                self.assertEqual(len(calls), 1)
            self.assertFalse(page.locator('[data-google-sync]').is_disabled())
            with patch.object(google_ledger_actions.ga, 'sync', side_effect=OSError('private path')):
                page.locator('[data-google-sync]').click()
                page.wait_for_function("document.querySelector('[data-google-sync-status]').textContent.includes('마지막 정상')")
                self.assertFalse(page.locator('[data-google-sync]').is_disabled())
                self.assertNotIn('private path', page.locator('[data-google-sync-status]').inner_text())
            self.assertLessEqual(page.evaluate('document.documentElement.scrollWidth'), 390)
            # Real HTTP route rejects a missing CSRF token before starting another worker.
            response = context.request.post(f'http://127.0.0.1:{self.port}/api/google-ledger/sync', data='{}')
            self.assertEqual(response.status, 403)
            with patch.object(google_ledger_actions, 'source_url', return_value='https://docs.google.com/spreadsheets/d/fixed/edit#gid=42'):
                response = context.request.get(f'http://127.0.0.1:{self.port}/api/google-ledger/source?trip=' + trip['tab_id'], max_redirects=0)
                self.assertEqual(response.status, 302)
                self.assertTrue(response.headers['location'].endswith('#gid=42'))
