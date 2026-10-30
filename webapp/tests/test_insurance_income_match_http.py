import json
import unittest
from unittest.mock import patch

from webapp.tests import test_signed_session_http as signed
from webapp.tests.test_insurance_income_match_page import state


class InsuranceMatchHttpTests(unittest.TestCase):
    setUp = signed.SignedSessionHttpTests.setUp
    tearDown = signed.SignedSessionHttpTests.tearDown
    request = signed.SignedSessionHttpTests.request
    cookie = signed.SignedSessionHttpTests.cookie

    def test_signed_roles_get_only_and_no_store_before_source_access(self):
        with patch('webapp.insurance_income_match_service.build_state', return_value=state()) as loader:
            for user, expected in ((None, 401), (signed.VIEWER, 403), (signed.OWNER, 200)):
                for path in ('/participants/insurance-match', '/api/participants/insurance-match'):
                    loader.reset_mock()
                    code, body, headers = self.request(path, cookie=self.cookie(user) if user else None)
                    self.assertEqual(code, expected, body)
                    self.assertEqual(headers.get('Cache-Control'), 'no-store')
                    self.assertEqual(loader.call_count, int(user == signed.OWNER))
                    if user != signed.OWNER:
                        self.assertNotIn('private-ref-1', body)
                        self.assertNotIn('김*람', body)
            loader.reset_mock()
            code, _, _ = self.request('/api/participants/insurance-match',
                                      cookie=self.cookie(signed.OWNER), payload={})
            self.assertEqual(code, 405)
            loader.assert_not_called()

    def test_source_errors_have_real_status_and_hide_private_exception(self):
        with patch('webapp.insurance_income_match_service.build_state', side_effect=OSError('private.pdf')):
            for path in ('/participants/insurance-match', '/api/participants/insurance-match'):
                code, body, _ = self.request(path, cookie=self.cookie(signed.OWNER))
                self.assertEqual(code, 503)
                self.assertNotIn('private.pdf', body)
