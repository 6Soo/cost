"""OTA 캐시 사용분 행: 같은 예약번호와 증빙 종류로 장부에 남고, 같은 요청은 한 번만 기록된다."""
import tempfile
import unittest
from pathlib import Path

from webapp.ledger_store import LedgerStore


class OtaCashLedgerRowTests(unittest.TestCase):
    def test_cash_row_keeps_its_booking_number_and_evidence_and_replays_once(self):
        store = LedgerStore(Path(tempfile.mkdtemp()) / "webledger.sqlite", seed_demo=False)
        self.addCleanup(store.close)
        trip = store.create_trip(starts_on="2026-09-27", ends_on="2026-10-01", destination="북큐슈",
                                 display_key="0927_북큐슈", client_request_id="trip-north")
        fields = {"display_tab_id": trip["tab_id"], "occurred_on": "2026-09-28", "amount_krw": 19835,
                  "item": "렌터카", "description": "klook FBQ214585 캐시 사용분",
                  "evidence_type": "클룩 포인트", "reservation_no": "FBQ214585",
                  "service_period": "2026-09-28", "memo": "자료 원화 금액"}
        first = store.create_manual_expense(fields=fields, client_request_id="ota-cash-klook-FBQ214585")
        again = store.create_manual_expense(fields=fields, client_request_id="ota-cash-klook-FBQ214585")
        self.assertEqual(first["row_id"], again["row_id"])
        row = store.get_row(first["row_id"])
        payload = row["payload"] if isinstance(row, dict) and "payload" in row else row
        self.assertEqual(payload["reservation_no"], "FBQ214585")
        self.assertEqual(payload["evidence_type"], "클룩 포인트")
        self.assertEqual(payload["amount_krw"], 19835)
        self.assertEqual(payload["occurred_on"], "2026-09-28")
