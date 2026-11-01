"""Google ledger over real HTTP with real synthetic sessions.

The sessions come from the same synthetic adapter the phase-7 tests use: a header names the
account, the access store decides the role, and every request goes through the board's own
do_GET. Nothing here calls a route function directly.
"""

import datetime as dt
import json
import os
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path
from unittest.mock import patch

from app import google_authority as ga
from webapp import access_control
from webapp import google_ledger_page as gl
from webapp import ledger_board as board_mod
from webapp.ledger_store import LedgerStore
from webapp.tests.test_google_ledger_browser import workbook, empty_workbook

OWNER = "syn-owner-O"
VIEWER = "syn-viewer-V"
OTHER = "syn-viewer-X"
NOW = dt.datetime(2026, 10, 11, 9, 0, tzinfo=ga.KST)


class GoogleViewerHttpTests(unittest.TestCase):
    def setUp(self):
        self._dir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        root = Path(self._dir.name)
        main = workbook("0630_오제", ("ALICE-NAME", "ALI", 900000), ("PAYEE-SHOP", "식비", 120000))
        archive = workbook("0107_대만", ("BOB-NAME", "BOB", 300000), ("SHOP-B", "교통비", 50000))
        self.snapshot, self.rows = root / 'google-snapshot.json', root / 'google-rows-private.json'
        ga.sync(self.snapshot, self.rows, fetcher=self._fetcher({"main": main, "archive": archive}), now=NOW)
        self._env = patch.dict(os.environ, {
            'WEBLEDGER_GOOGLE_LEDGER_SNAPSHOT': str(self.snapshot),
            'WEBLEDGER_GOOGLE_LEDGER_ROWS': str(self.rows),
            'WEBLEDGER_DB': str(root / 'phase.sqlite')})
        self._env.start()
        self.store = LedgerStore(root / 'phase.sqlite')
        self.access = access_control.attach_to_ledger_store(self.store)
        board_mod.bind_store(self.store)
        self.server = board_mod.serve(port=0, with_worker=False)
        self.port = self.server.server_address[1]
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        access_control.bind_synthetic_sessions(True)
        board_mod.bind_access(self.access)
        self.trip = self.store.create_trip(starts_on='2026-10-10', ends_on='2026-10-13', destination='합성 여행',
                                           client_request_id='viewer-trip')['tab_id']
        self.access.ensure_owner(OWNER)
        self.access.create_account(user_id=VIEWER, role=access_control.ROLE_VIEWER)
        self.access.create_account(user_id=OTHER, role=access_control.ROLE_VIEWER)

    def tearDown(self):
        board_mod.bind_access(None)
        access_control.bind_sessions(access_control.UnboundSessionAdapter())
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)
        board_mod.bind_store(None)
        self.store.close()
        self._env.stop()
        self._dir.cleanup()

    @staticmethod
    def _fetcher(books):
        books = {'andre_main': empty_workbook(), **books}
        def fetch(url):
            for role, sheet_id in ga.SPREADSHEET_IDS.items():
                if sheet_id in url:
                    return books[role]
            raise AssertionError(url)
        return fetch

    def call(self, path, user=None, method='GET', payload=None):
        headers = {}
        data = None
        if user:
            headers[access_control.SyntheticSessionAdapter.HEADER] = user
        if payload is not None:
            data = json.dumps(dict(payload, csrf=board_mod.CSRF_TOKEN)).encode('utf-8')
            headers['Content-Type'] = 'application/json'
        request = urllib.request.Request(f'http://127.0.0.1:{self.port}{path}', data=data, headers=headers,
                                         method=method)
        try:
            with urllib.request.urlopen(request) as response:
                return response.status, response.read().decode('utf-8')
        except urllib.error.HTTPError as error:
            return error.code, error.read().decode('utf-8')

    def link_and_assign(self, user, tab):
        """A real link: application, approval against a reservation person, then a trip assignment."""
        person = f'rp-{user}'
        self.access.register_reservation_person(reservation_person_id=person, display_name=f'이름 {user}',
                                                nickname='닉')
        self.call('/access/applications', user, 'POST',
                  {'action': 'create', 'requested_name': f'이름 {user}', 'nickname': '닉',
                   'client_request_id': f'app-{user}'})
        status, body = self.call('/access/applications', user, 'POST',
                                 {'action': 'create', 'client_request_id': f'probe-{user}'})
        application_id = json.loads(body)['result']['application_id']
        self.call('/access/decision', OWNER, 'POST',
                  {'action': 'approve', 'application_id': application_id, 'expected_revision': 1,
                   'reservation_person_id': person, 'client_request_id': f'dec-{user}'})
        self.access.apply_assignment_snapshot(
            user_id=user, items=[{'tab_id': tab, 'snapshot_revision': 1, 'state': access_control.ASSIGN_ACTIVE}],
            source_version='src-1', validity=access_control.DEFAULT_VALIDITY, now=None, complete=False)

    def grant_and_link(self, user, key, tab):
        gl.set_grants(self.snapshot, user_id=user, keys=[key], granted=True, at='t')
        gl.set_mapping(self.snapshot, key=key, tab_id=tab, known_keys={'0630_오제', '0107_대만'})

    def test_owner_sees_every_trip_and_the_detail_over_http(self):
        status, body = self.call('/api/google-ledger/rows?key=0630_%EC%98%A4%EC%A0%9C&source=main', OWNER)
        self.assertEqual(status, 200, body)
        self.assertIn('ALICE-NAME', body)

    def test_removed_google_ledger_routes_do_not_claim_http_instrumentation(self):
        from app import request_metrics
        before = request_metrics.summary()
        self.assertFalse(gl.owns_route('/google-ledger'))
        self.assertFalse(gl.owns_route('/api/google-ledger'))
        self.assertEqual(request_metrics.summary(), before)

    def test_canonical_read_seam_measures_mock_loader_without_source_values(self):
        from app import request_metrics
        from unittest.mock import patch
        sentinel = 'SENTINEL_PRIVATE_CUSTOMER'
        snapshot = {'generation': 7, 'trips': [{'key': sentinel}], 'rule_version': 'rules_v1'}
        rows = {'private': sentinel}
        before = request_metrics.summary().get('google_canonical_read.google_read', {}).get('samples', 0)
        with patch.object(gl.google_authority, 'load_consistent', return_value=(snapshot, rows)) as loader:
            actual = gl._load_consistent_measured(self.snapshot, self.rows)
        loader.assert_called_once_with(self.snapshot, self.rows)
        self.assertEqual(actual, (snapshot, rows))
        after = request_metrics.summary()['google_canonical_read.google_read']
        self.assertEqual(after['samples'], before + 1)
        self.assertEqual(after['rows'], 1)
        self.assertNotIn(sentinel, json.dumps(request_metrics.summary()))
        self.assertNotIn(str(self.snapshot), json.dumps(request_metrics.summary()))

    def test_a_viewer_sees_only_the_granted_linked_and_visible_trip(self):
        self.link_and_assign(VIEWER, self.trip)
        self.grant_and_link(VIEWER, '0630_오제', self.trip)
        status, body = self.call('/api/google-ledger', VIEWER)
        self.assertEqual(status, 200, body)
        keys = [t['key'] for t in json.loads(body)['trips']]
        self.assertEqual(keys, ['0630_오제'])
        self.assertNotIn('copies', body)
        self.assertNotIn('0107_대만', body)

    def test_a_viewer_reads_the_income_and_expense_detail_of_the_allowed_trip_only(self):
        self.link_and_assign(VIEWER, self.trip)
        self.grant_and_link(VIEWER, '0630_오제', self.trip)
        status, body = self.call('/api/google-ledger/rows?key=0630_%EC%98%A4%EC%A0%9C&source=main', VIEWER)
        self.assertEqual(status, 200, body)
        self.assertIn('ALICE-NAME', body)
        self.assertIn('PAYEE-SHOP', body)
        status, body = self.call('/api/google-ledger/rows?key=0107_%EB%8C%80%EB%A7%8C&source=archive', VIEWER)
        self.assertIn(status, (403, 404))
        self.assertNotIn('BOB-NAME', body)

    def test_anonymous_and_ungranted_viewers_are_refused(self):
        self.link_and_assign(VIEWER, self.trip)
        self.grant_and_link(VIEWER, '0630_오제', self.trip)
        for path in ('/google-ledger', '/api/google-ledger', '/google-ledger/rows?key=0630_%EC%98%A4%EC%A0%9C&source=main'):
            status, body = self.call(path)
            self.assertIn(status, (401, 403, 404), path)
            self.assertNotIn('ALICE-NAME', body)
        status, body = self.call('/api/google-ledger', OTHER)
        self.assertEqual(json.loads(body)['trips'], [])

    def test_revoking_the_owner_grant_or_the_cost_assignment_ends_access_at_once(self):
        self.link_and_assign(VIEWER, self.trip)
        self.grant_and_link(VIEWER, '0630_오제', self.trip)
        gl.set_grants(self.snapshot, user_id=VIEWER, keys=['0630_오제'], granted=False, at='t2')
        self.assertEqual(json.loads(self.call('/api/google-ledger', VIEWER)[1])['trips'], [])
        gl.set_grants(self.snapshot, user_id=VIEWER, keys=['0630_오제'], granted=True, at='t3')
        self.assertEqual(len(json.loads(self.call('/api/google-ledger', VIEWER)[1])['trips']), 1)
        self.access.apply_assignment_snapshot(
            user_id=VIEWER, items=[{'tab_id': self.trip, 'snapshot_revision': 2,
                                    'state': access_control.ASSIGN_REVOKED}],
            source_version='src-2', validity=access_control.DEFAULT_VALIDITY, now=None, complete=False)
        self.assertEqual(json.loads(self.call('/api/google-ledger', VIEWER)[1])['trips'], [])

    def test_a_deactivated_viewer_loses_access_on_the_next_request(self):
        self.link_and_assign(VIEWER, self.trip)
        self.grant_and_link(VIEWER, '0630_오제', self.trip)
        self.assertEqual(len(json.loads(self.call('/api/google-ledger', VIEWER)[1])['trips']), 1)
        self.access.set_account_active(user_id=VIEWER, is_active=False)
        status, body = self.call('/api/google-ledger', VIEWER)
        self.assertNotIn('ALICE-NAME', body)
        self.assertNotEqual(status, 200)

    def test_the_ordinary_cost_board_policy_is_unchanged_for_a_viewer(self):
        self.link_and_assign(VIEWER, self.trip)
        self.grant_and_link(VIEWER, '0630_오제', self.trip)
        self.assertEqual(self.call('/board', VIEWER)[0], 200)
        self.assertEqual(self.call('/access/admin', VIEWER)[0], 403)
