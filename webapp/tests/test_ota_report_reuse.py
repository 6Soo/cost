"""OTA 대사 결과는 한 조회 안에서 한 번만 계산하고, 메일 파싱은 자료 지문이 같을 때 재사용한다."""
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app import ota_mail
from webapp.card_flow import CardFlow
from webapp.ledger_store import LedgerStore


class OtaReportReuseTests(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.env = patch.dict(os.environ, {'WEBLEDGER_UNIFIED_DB': '1'})
        self.env.start()
        self.board = LedgerStore(Path(self.tmp.name) / 'board.sqlite', seed_demo=False)
        self.flow = CardFlow(self.board)

    def tearDown(self):
        self.board.close()
        self.env.stop()
        self.tmp.cleanup()

    def test_one_state_request_reconciles_ota_once(self):
        calls = []
        with patch.object(CardFlow, '_compute_ota_report', lambda self: calls.append(1) or {'ok': True}):
            # The legacy fallback report carries a read-only provenance marker.
            expected = {'ok': True, '_reconciliation_authority': 'legacy_fallback_feature_disabled'}
            self.flow._request_report = []
            self.assertEqual(self.flow._ota_report(), expected)
            self.assertEqual(self.flow._ota_report(), expected)
            self.assertEqual(len(calls), 1)
            self.flow._request_report = None
            self.flow._ota_report()
            self.flow._ota_report()
            self.assertEqual(len(calls), 3)

    def test_state_request_clears_its_memo_when_done(self):
        with patch.object(CardFlow, '_state', lambda self, batch_id: self._request_report):
            self.assertEqual(self.flow.state('any'), [])
        self.assertIsNone(self.flow._request_report)

    def test_mail_side_is_read_once_per_source_key(self):
        ota_mail._MAIL_SIDE_MEMO.clear()
        with patch.object(ota_mail, 'load_messages_from', return_value=({}, {})) as loader:
            ota_mail.match_mail([], [], source_key='a')
            ota_mail.match_mail([], [], source_key='a')
            self.assertEqual(loader.call_count, 1)
            ota_mail.match_mail([], [], source_key='b')
            self.assertEqual(loader.call_count, 2)
        ota_mail._MAIL_SIDE_MEMO.clear()
