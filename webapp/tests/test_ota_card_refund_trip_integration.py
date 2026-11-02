"""Synthetic integration of OTA payment evidence, card refunds, and trip assignment."""
import os
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.ota_payments import match_ota_payment_events
from app.ota_review import OtaReviewStore
from app.ota_payments import build_ota_payment_events
from tests.card_pipeline.test_booking_mail import message
from webapp.card_flow import CardFlow
from webapp.ledger_store import LedgerStore


class OtaCardRefundTripIntegration(unittest.TestCase):
    def test_booking_payment_pin_trip_assignment_and_refund_source_protection(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            review_db = root / 'review.sqlite'
            env = patch.dict(os.environ, {
                'WEBLEDGER_UNIFIED_DB': '1', 'WEBLEDGER_CARD_FLOW': '1',
                'WEBLEDGER_OTA_REVIEW_MODE': 'isolated',
                'WEBLEDGER_OTA_REVIEW_DB': str(review_db),
                'WEBLEDGER_OTA_MAIL_DIR': str(root / 'ota-mail')})
            env.start()
            mail_dir = root / 'ota-mail'
            mail_dir.mkdir()
            booking_ref = 'BOOKSYN12345'
            confirmation = message(
                f'예약 번호: {booking_ref}\n체크인: 2026년 10월 3일\n체크아웃: 2026년 10월 5일',
                subject='[예약 확정 안내] 합성 숙소 예약이 확정되었습니다',
                identity='synthetic-confirmation', sent='2026-10-01')
            payment = message(
                f'예약번호: {booking_ref}\n총 금액 100,000원',
                subject='[Trip.com] 결제 완료 안내', identity='synthetic-payment',
                sent='2026-10-01')
            (mail_dir / 'gmail-synthetic.json').write_text(
                json.dumps({'responses': [confirmation, payment]}, ensure_ascii=False),
                encoding='utf-8')
            board = LedgerStore(root / 'board.sqlite', seed_demo=False)
            review = None
            try:
                board.conn.execute("INSERT INTO trip_tabs(tab_id,display_key,starts_on,ends_on) "
                                   "VALUES ('trip-syn','synthetic trip','2026-09-30','2026-10-08')")
                board.conn.commit()
                csv = ('Issuer,Card No,Card Type,Type,Merchant,Amount,Foreign Amount,Currency,Amount KRW,'
                       'Date,Post Date,Authorization Code,Cancel,Status\n'
                       '국민,1234,domestic,purchase,TRIP.COM,100000,,,100000,2026-10-01,2026-10-02,A100,,매입\n'
                       '국민,1234,domestic,purchase,TRIP.COM,70000,,,70000,2026-10-03,2026-10-04,C200,,매입\n').encode()
                flow = CardFlow(board)
                batch = flow.pipeline.receive(csv, 'synthetic-ota-refund.csv')['batch_id']
                board.conn.execute("UPDATE transactions SET transaction_direction='cancellation', "
                                   "amount_krw=-70000, original_approval_number='100' "
                                   "WHERE approval_number='200'")
                board.conn.commit()
                rows = board.conn.execute(
                    "SELECT transaction_id,source_hash,approval_number,amount_krw FROM transactions "
                    "WHERE transaction_id IN (SELECT transaction_id FROM import_batch_rows WHERE batch_id=?) "
                    "ORDER BY approval_number", (batch,)).fetchall()
                purchase, refund = rows
                purchase_id, purchase_source = purchase[0], purchase[1]
                refund_id, refund_source = refund[0], refund[1]

                sources = {'mail_directories': [mail_dir], 'portal_databases': [],
                           'reference_documents': [], 'missing': [], 'diagnostics': []}
                events = build_ota_payment_events(sources)
                event = next(item for item in events if item.get('booking_ref') == booking_ref
                             and item.get('event_type') == 'charge')
                self.assertEqual(event['evidence_status'], 'paid_verified')
                self.assertEqual((event['amount_krw'], event['paid_on']), (100000, '2026-10-01'))
                self.assertEqual(event['service_period'],
                                 {'starts_on': '2026-10-03', 'ends_on': '2026-10-05'})
                reservation = {**event, 'ota_event_id':'reservation-only', 'event_type':'reservation',
                               'evidence_status':'pending', 'payment_status':'scheduled', 'amount_krw':None}
                card = {'transaction_id':purchase_id, 'issuer':'국민', 'merchant':'TRIP.COM',
                        'merchant_normalized':'trip.com', 'card_tail':'1234',
                        'approval_date':'2026-10-02', 'transaction_direction':'purchase',
                        'amount_krw':100000, 'source_hash':purchase_source}
                pending = match_ota_payment_events([reservation], [card])[0]
                self.assertEqual((pending['status'], pending['transaction_id']), ('PENDING_PAYMENT', None))

                review = OtaReviewStore(review_db)
                preview = review.preview(event, card)
                review.confirm(event, card, preview['preview_digest'], request_id='synthetic-pin',
                               user='synthetic-owner', allocations={})
                self.assertEqual(review.links()[event['ota_event_id']]['transaction_id'], purchase_id)
                pinned = match_ota_payment_events([event], [card, {**card, 'transaction_id':'better-card'}],
                                                  existing_links=review.links())[0]
                self.assertEqual((pinned['transaction_id'], pinned['status']), (purchase_id, 'MATCHED_USER'))
                review.save_booking_trip(provider='trip', booking_ref=booking_ref,
                                         trip_tab_id='trip-syn', trip_code='synthetic trip',
                                         basis='합성 예약 배정 근거', expected_revision=0, user='synthetic-owner')
                review.close()

                isolated_sources = {
                    'mail_directories': [mail_dir], 'portal_databases': [],
                    'reference_documents': [], 'registered': {'mail_directories': [],
                        'portal_databases': [], 'reference_documents': []},
                    'missing': [], 'diagnostics': [], 'manifest_path': str(root / 'ota-sources.json'),
                    'manifest_present': False, 'manifest_stamp': None,
                }
                with patch.object(flow, '_ota_sources', return_value=isolated_sources), \
                     patch.object(flow, '_held_ota_snapshot', return_value=(None, False)), \
                     patch.object(CardFlow, 'trip_valid', lambda _self, tab: tab == 'trip-syn'):
                    report = flow._compute_ota_report()
                    self.assertEqual(len(report['matches']), 1,
                                     {'unmatched': report.get('unmatched_transactions'),
                                      'facts': report.get('authenticated_facts'),
                                      'sources': report.get('mail_source_errors'),
                                      'inventory': report.get('ota_source_inventory'),
                                      'gate': report.get('evidence_gate')})
                    self.assertEqual(report['matches'][0]['booking_ref'], booking_ref)
                    self.assertEqual(report['matches'][0]['transaction_id'], purchase_id)
                    flow._classify(batch, transaction_ids=[purchase_id])
                classified = board.conn.execute(
                    "SELECT classification_source,display_tab_id,trip_id FROM transactions WHERE transaction_id=?",
                    (purchase_id,)).fetchone()
                self.assertEqual(tuple(classified), ('owner_booking','trip-syn','trip-syn'))

                flow.pipeline.save_decision(refund_id, board.conn.execute(
                    'SELECT revision FROM transactions WHERE transaction_id=?',(refund_id,)).fetchone()[0],
                    item='숙박비', display_tab_id='trip-syn', trip_id='trip-syn',
                    request_id='classify-synthetic-refund', tab_validator=lambda _tab: True,
                    trip_validator=lambda _trip: True)
                result = flow.pipeline.preview(batch, tab_validator=lambda _tab: True,
                                              trip_validator=lambda _trip: True)
                refund_row = next(row for row in result['rows'] if row['transaction_id'] == refund_id)
                self.assertEqual(refund_row['refund_link']['counterpart_id'], purchase_id)
                self.assertEqual((refund_row['amount_krw'], refund_row['refund_link']['refund_krw']),
                                 (-70000, -70000))
                persisted = board.conn.execute(
                    "SELECT source_hash,amount_krw,original_approval_number,transaction_direction "
                    "FROM transactions WHERE transaction_id=?", (refund_id,)).fetchone()
                self.assertEqual(tuple(persisted), (refund_source,-70000,'100','cancellation'))
                self.assertGreater(result['ready'], 0)
                original = board.conn.execute(
                    'SELECT source_hash,amount_krw,transaction_direction FROM transactions WHERE transaction_id=?',
                    (purchase_id,)).fetchone()
                self.assertEqual(tuple(original), (purchase_source, 100000, 'purchase'))
            finally:
                if review is not None:
                    review.close()
                board.close()
                env.stop()


if __name__ == '__main__':
    unittest.main()
