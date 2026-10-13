"""An owner's booking trip assignment reaches the card row it names, and stops when revoked."""
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.ota_review import OtaReviewStore
from webapp import card_flow, ota_catalog
from webapp.card_flow import CardFlow
from webapp.ledger_store import LedgerStore

TRIP_CSV = ('Issuer,Card No,Card Type,Type,Merchant,Amount,Foreign Amount,Currency,Amount KRW,'
            'Date,Post Date,Authorization Code,Cancel,Status\n'
            '국민,1234,domestic,purchase,TRIP.COM,37000,,,37000,2026-10-01,2026-10-02,A777,,매입\n').encode()


class BookingAssignmentReachesTheCardRow(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.review_db = root / 'ota-review.sqlite'
        self.env = patch.dict(os.environ, {
            'WEBLEDGER_UNIFIED_DB': '1', 'WEBLEDGER_CARD_FLOW': '1',
            'WEBLEDGER_OTA_REVIEW_MODE': 'isolated', 'WEBLEDGER_OTA_REVIEW_DB': str(self.review_db)})
        self.env.start()
        self.board = LedgerStore(root / 'board.sqlite', seed_demo=False)
        self.flow = CardFlow(self.board)
        self.board.conn.execute("INSERT INTO trip_tabs(tab_id,display_key,starts_on,ends_on) VALUES "
                                "('trip-x','1001_합성','2026-09-30','2026-10-05')")
        self.board.conn.commit()
        self.batch = self.flow.pipeline.receive(TRIP_CSV, 'trip.csv')['batch_id']
        self.transaction_id, self.source_hash = self.board.conn.execute(
            "SELECT transaction_id, source_hash FROM transactions WHERE transaction_id IN "
            "(SELECT transaction_id FROM import_batch_rows WHERE batch_id=?)", (self.batch,)).fetchone()
        report = {'matches': [{
            'transaction_id': self.transaction_id, 'source_hash': self.source_hash, 'merchant': 'TRIP.COM',
            'provider': 'trip', 'booking_ref': 'B9', 'item': '숙박비', 'direction': 'purchase',
            'reservation_status': 'confirmed', 'period_conflict': False,
            'paid_on': '2026-10-02', 'paid_amount_krw': 37000}],
            'rules': [], 'type_only_candidates': [], 'unmatched_transactions': []}
        patcher = patch.object(CardFlow, '_ota_report', lambda self: report)
        patcher.start()
        self.addCleanup(patcher.stop)
        valid = patch.object(CardFlow, 'trip_valid', lambda self, tab: tab == 'trip-x')
        valid.start()
        self.addCleanup(valid.stop)

    def tearDown(self):
        self.board.close()
        self.env.stop()
        self.tmp.cleanup()

    def _row(self):
        return self.board.conn.execute(
            "SELECT classification_state, classification_source, display_tab_id, trip_id, item "
            "FROM transactions WHERE transaction_id=?", (self.transaction_id,)).fetchone()

    def test_assignment_applies_to_the_named_row_and_revocation_removes_it(self):
        store = OtaReviewStore(self.review_db)
        store.save_booking_trip(provider='trip', booking_ref='B9', trip_tab_id='trip-x', trip_code='1001_합성',
                                basis='이용기간이 여행 기간 안에 있음', expected_revision=0, user='owner')
        store.close()
        self.flow._classify(self.batch, transaction_ids=[self.transaction_id])
        state, source, tab, trip, item = self._row()
        self.assertEqual((state, source, tab, trip, item), ('classified', 'owner_booking', 'trip-x', 'trip-x', '숙박비'))

        store = OtaReviewStore(self.review_db)
        store.revoke_booking_trip(provider='trip', booking_ref='B9', expected_revision=1, user='owner')
        store.close()
        self.flow._classify(self.batch, transaction_ids=[self.transaction_id])
        self.assertNotEqual(self._row()[2], 'trip-x')

    def test_an_unverified_trip_is_not_applied_and_says_why(self):
        store = OtaReviewStore(self.review_db)
        store.save_booking_trip(provider='trip', booking_ref='B9', trip_tab_id='trip-z', trip_code='1002_없음',
                                basis='일정 확인 전', expected_revision=0, user='owner')
        store.close()
        self.flow._classify(self.batch, transaction_ids=[self.transaction_id])
        self.assertNotEqual(self._row()[2], 'trip-z')


    def test_a_confirmed_stay_inside_one_verified_trip_reaches_the_card_row_as_an_inference(self):
        entry = {'provider': 'trip', 'booking_ref': 'B9', 'period_trip': {'id': 'trip-x', 'name': '1001_합성', 'source': 'period'}}
        with patch.object(ota_catalog, '_index', lambda board, sources: {'entries': [entry]}),                 patch.object(ota_catalog, 'configured_sources', lambda board: {}):
            self.flow._classify(self.batch, transaction_ids=[self.transaction_id])
        state, source, tab, item = self._row()[0], self._row()[1], self._row()[2], self._row()[4]
        self.assertEqual((state, source, tab, item), ('classified', 'inference', 'trip-x', '숙박비'))

    def _inference_with_stay(self, starts_on, ends_on):
        from app.normalize import normalize_merchant
        from app.reconciliation import OWNER_AUTHORIZED_INFERENCE_ORIGIN
        self.flow.pipeline.save_rule({
            'conditions': {'merchant_normalized': normalize_merchant('TRIP.COM'), 'transaction_direction': 'purchase'},
            'optional': {'source_hash': self.source_hash, 'inferred_assignment': {
                'trip_id': 'trip-x', 'basis': '결제 뒤 가까운 여행', 'confidence': '낮음'}},
            'effects': {'item': '숙박비'}, 'origin': OWNER_AUTHORIZED_INFERENCE_ORIGIN, 'rule_id': 'inference-stay'})
        report = {'matches': [{
            'transaction_id': self.transaction_id, 'source_hash': self.source_hash, 'merchant': 'TRIP.COM',
            'provider': 'trip', 'booking_ref': 'B9', 'item': '숙박비', 'direction': 'purchase',
            'reservation_status': 'observed', 'period_conflict': False,
            'period': {'starts_on': starts_on, 'ends_on': ends_on}}],
            'rules': [], 'type_only_candidates': [], 'unmatched_transactions': []}
        with patch.object(CardFlow, '_ota_report', lambda self: report):
            self.flow._classify(self.batch, transaction_ids=[self.transaction_id])
        return self._row()[3]

    def test_an_inference_to_a_trip_outside_an_unconfirmed_stay_is_not_applied(self):
        self.assertEqual(self._inference_with_stay('2026-11-10', '2026-11-12'), '')

    def test_an_inference_to_a_trip_the_unconfirmed_stay_overlaps_still_applies(self):
        self.assertEqual(self._inference_with_stay('2026-10-04', '2026-10-07'), 'trip-x')


if __name__ == '__main__':
    unittest.main()
