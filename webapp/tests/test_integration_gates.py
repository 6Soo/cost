import json
import os
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path
from unittest.mock import patch

from webapp import ledger_board

OWNER = object()
REGIONS = {"regions": [{"box": [0, 0, 100, 100], "merchant": "라멘집", "date": "2027-08-03", "currency": "JPY",
                        "total": 1234, "payment": "cash", "confidence": 0.95}]}


class GateTests(unittest.TestCase):
    """Access enforcement on: a request is owner only when its own session says so."""

    def setUp(self):
        self._dir = tempfile.TemporaryDirectory()
        self._env = patch.dict(os.environ, {'WEBLEDGER_UNIFIED_DB': '1', 'WEBLEDGER_CARD_FLOW': '1',
                                            'WEBLEDGER_REVIEW_FROM': '',
                                            'WEBLEDGER_RECEIPTS_STORE': str(Path(self._dir.name) / 'receipts.json')})
        self._env.start()
        self._previous = ledger_board._STORE
        ledger_board.bind_access(None)
        self.server = ledger_board.serve(port=0, db_path=Path(self._dir.name) / 'board.sqlite',
                                         with_worker=False, seed_demo=False)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base = f'http://127.0.0.1:{self.server.server_address[1]}'
        self.session = None
        patches = [
            patch.object(ledger_board, 'ACCESS_ENFORCEMENT', True),
            patch.object(ledger_board, 'current_session', side_effect=lambda headers, cookies=None: self.session),
            patch.object(ledger_board, 'is_owner_session', side_effect=lambda s: s is OWNER),
            patch.object(ledger_board.Handler, '_phase7_get', return_value=False),
            patch.object(ledger_board.Handler, '_phase7_write', return_value=False),
        ]
        self._patches = patches
        for item in patches:
            item.start()

    def tearDown(self):
        for item in self._patches:
            item.stop()
        self.server.shutdown()
        self.server.server_close()
        self.server.card_store.close()
        self.thread.join(timeout=3)
        ledger_board.bind_store(self._previous)
        self._env.stop()
        self._dir.cleanup()

    def call(self, method, path, body=None):
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(self.base + path, data=data, method=method)
        req.add_header('Content-Type', 'application/json')
        req.add_header('X-CSRF-Token', ledger_board.CSRF_TOKEN)
        try:
            with urllib.request.urlopen(req) as response:
                return response.status, response.read().decode('utf-8')
        except urllib.error.HTTPError as error:
            return error.code, error.read().decode('utf-8')

    def test_owner_session_can_write_a_receipt_scan(self):
        self.session = OWNER
        status, body = self.call('POST', '/api/receipts/scan', REGIONS)
        self.assertEqual(status, 200, body)
        self.assertEqual(json.loads(body)['added'], 1)

    def test_no_session_is_refused_on_write_and_read(self):
        self.session = None
        status, body = self.call('POST', '/api/receipts/scan', REGIONS)
        self.assertEqual((status, json.loads(body)['code']), (403, 'OWNER_ONLY'))
        status, body = self.call('GET', '/api/receipts')
        self.assertEqual((status, json.loads(body)['code']), (403, 'OWNER_ONLY'))

    def test_owner_page_loads_and_anonymous_page_does_not(self):
        self.session = OWNER
        self.assertEqual(self.call('GET', '/receipts')[0], 200)
        self.session = None
        self.assertEqual(self.call('GET', '/receipts')[0], 403)
