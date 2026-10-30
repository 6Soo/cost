import unittest
from unittest.mock import patch

from webapp import ledger_board as board
from webapp.tests import test_signed_session_http as signed


class ExpenseAmountGroupHttpTests(unittest.TestCase):
    setUp = signed.SignedSessionHttpTests.setUp
    tearDown = signed.SignedSessionHttpTests.tearDown
    request = signed.SignedSessionHttpTests.request
    cookie = signed.SignedSessionHttpTests.cookie

    def test_real_owner_board_loads_groups_and_others_never_read_private_rows(self):
        trip = board._active_store().create_trip(starts_on='2026-11-07', ends_on='2026-11-10',
            destination='합성도시', client_request_id='synthetic-gemn-trip')
        state = {'available': True, 'reason': '', 'last_success_at': '2026-10-30',
                 'by_cost_id': {}, 'summary': {'google_only': 1}, 'groups': [{
                     'group_id': 'opaque', 'trip_id': trip['tab_id'], 'amount_krw': 50000,
                     'status': 'google_only', 'cost_count': 0, 'google_count': 1,
                     'candidate_count': 0, 'cost_rows': [],
                     'google_rows': [{'ref': 'GOOGLE-PRIVATE-SYNTHETIC'}]}]}
        with patch('webapp.expense_amount_group_service.build_state', return_value=state) as loader:
            for user in (None, signed.VIEWER, signed.OWNER):
                loader.reset_mock()
                code, body, headers = self.request('/board?tab=' + trip['tab_id'],
                    cookie=self.cookie(user) if user else None)
                self.assertEqual(headers.get('Cache-Control'), 'no-store')
                if user == signed.OWNER:
                    self.assertEqual(code, 200, body)
                    self.assertIn('GOOGLE-PRIVATE-SYNTHETIC', body)
                    self.assertEqual(loader.call_count, 1)
                else:
                    self.assertNotIn('GOOGLE-PRIVATE-SYNTHETIC', body)
                    loader.assert_not_called()
