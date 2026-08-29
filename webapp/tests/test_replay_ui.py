from __future__ import annotations

import json
import re
import shutil
import tempfile
import threading
import unittest
import urllib.parse
import urllib.request
from pathlib import Path

from webapp.operator_ledger import OperatorLedger
from webapp.server import WebApp, serve

from .fixtures import demo_axes, build_demo_snapshot


class ReplayTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="cost-replay-"))
        self.fix = build_demo_snapshot(self.tmp)
        self.ledger = OperatorLedger.create(self.tmp / "op.sqlite")

    def tearDown(self):
        self.ledger.close()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_materialize_deterministic(self):
        self.ledger.append(
            stream_id="TX-0001",
            action="propose",
            target_direct_event_key="TX-0001",
            axes=demo_axes(allocation_target="0417_아오모리"),
            rationale="p",
        )
        self.ledger.append(
            stream_id="TX-0001",
            action="correct",
            axes=demo_axes(account="식비"),
            rationale="fix",
        )
        one = json.dumps(self.ledger.materialize(), sort_keys=True)
        two = json.dumps(self.ledger.materialize(), sort_keys=True)
        self.assertEqual(one, two)


class ShadowUiTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="cost-ui-"))
        self.fix = build_demo_snapshot(self.tmp)
        self.ledger = OperatorLedger.create(self.tmp / "op.sqlite")
        self.app = WebApp(
            self.fix["descriptor_path"],
            ledger=self.ledger,
            include_writes=True,
        )
        self.server = serve(self.app, port=0)
        threading.Thread(
            target=self.server.serve_forever, daemon=True
        ).start()
        self.base = f"http://127.0.0.1:{self.server.server_address[1]}"

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.ledger.close()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _token(self):
        with urllib.request.urlopen(f"{self.base}/propose") as res:
            html_body = res.read().decode("utf-8")
        match = re.search(r"name='csrftoken' value='([0-9a-f]+)'", html_body)
        self.assertIsNotNone(match)
        return match.group(1)

    def _post(self, fields, origin=None):
        data = urllib.parse.urlencode(fields).encode("utf-8")
        request = urllib.request.Request(
            f"{self.base}/api/propose", data=data, method="POST"
        )
        if origin:
            request.add_header("Origin", origin)
        try:
            with urllib.request.urlopen(request) as res:
                return res.status, res.read().decode("utf-8")
        except urllib.error.HTTPError as err:
            return err.code, err.read().decode("utf-8")

    def test_preview_shows_shadow_change(self):
        self.ledger.append(
            stream_id="TX-0001",
            action="propose",
            target_direct_event_key="TX-0001",
            axes=demo_axes(vat_tag="불공제_해외"),
            rationale="shadow override",
        )
        diff = self.app.shadow_preview()
        self.assertGreaterEqual(diff["changed_count"], 1)
        with urllib.request.urlopen(f"{self.base}/history") as res:
            body = res.read().decode("utf-8")
        self.assertIn("TX-0001", body)

    def test_post_without_csrf_rejected(self):
        status, _ = self._post({"stream_id": "X", "account": "숙박비",
                                "cost_type": "여행원가", "rationale": "r"})
        self.assertEqual(status, 403)

    def test_post_with_foreign_origin_rejected(self):
        token = self._token()
        status, _ = self._post(
            {"stream_id": "X", "account": "숙박비",
             "cost_type": "여행원가", "rationale": "r",
             "csrftoken": token},
            origin="http://evil.example",
        )
        self.assertEqual(status, 403)

    def test_post_with_valid_token_records_event(self):
        token = self._token()
        status, body = self._post(
            {"stream_id": "TX-0009",
             "target_direct_event_key": "TX-0009",
             "account": "숙박비",
             "cost_type": "여행원가",
             "allocation_target": "0417_아오모리",
             "vat_tag": "",
             "rationale": "ui smoke",
             "csrftoken": token},
        )
        self.assertEqual(status, 200)
        payload = json.loads(body)
        self.assertTrue(payload["created"])
        events = self.ledger.all_events()
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["stream_id"], "TX-0009")

    def test_invalid_axes_post_returns_400(self):
        token = self._token()
        status, _ = self._post(
            {"stream_id": "Y", "account": "", "cost_type": "여행원가",
             "rationale": "bad", "csrftoken": token},
        )
        self.assertEqual(status, 400)


if __name__ == "__main__":
    unittest.main()
