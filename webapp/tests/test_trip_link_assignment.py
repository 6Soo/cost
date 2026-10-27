"""Payment linkage and travel assignment are independently evidenced decisions."""
from copy import deepcopy

import pytest

from app import ota_payments
from webapp import card_flow
from webapp.card_flow import CardFlow
from webapp.ledger_store import LedgerStore


@pytest.mark.parametrize('valid_trip', [True, False])
def test_exact_trip_payment_assigns_only_an_authoritative_service_period_trip(tmp_path, monkeypatch, valid_trip):
    monkeypatch.setenv('WEBLEDGER_UNIFIED_DB', '1')
    monkeypatch.setenv('WEBLEDGER_CARD_SCHEMA_POLICY', 'create')
    monkeypatch.setenv('WEBLEDGER_OTA_REVIEW_DB', str(tmp_path / 'synthetic-review.sqlite'))
    monkeypatch.setattr(card_flow, '_google_nets', lambda: {})
    board = LedgerStore(tmp_path / 'synthetic.sqlite', seed_demo=False)
    try:
        flow = CardFlow(board)
        board.conn.execute("INSERT INTO trip_tabs(tab_id,display_key,starts_on,ends_on) VALUES "
                           "('synthetic-trip','1104_합성','2026-11-04','2026-11-10')")
        board.conn.commit()
        csv = ('Issuer,Card No,Card Type,Type,Merchant,Amount,Foreign Amount,Currency,Amount KRW,'
               'Date,Post Date,Authorization Code,Cancel,Status\n'
               '하나,1234,domestic,purchase,TRIP.COM,45000,,,45000,2026-09-23,2026-09-24,SYNTHETIC,,매입\n').encode()
        batch = flow.pipeline.receive(csv, 'synthetic.csv')['batch_id']
        cur = board.conn.execute('SELECT * FROM transactions')
        card = dict(zip([column[0] for column in cur.description], cur.fetchone()))
        card['ota_inference_eligible'] = True
        event = dict(ota_event_id='synthetic-event', provider='trip', booking_ref='SYNTHETIC-BOOKING',
                     event_type='charge', paid_on='2026-09-23', payment_status='paid',
                     evidence_status='paid_verified', amount=45000, amount_krw=45000, currency='KRW',
                     card_last4='1234', reservation_status='confirmed', item='숙박비',
                     source_digest='synthetic-digest', service_period={'starts_on': '2026-11-05', 'ends_on': '2026-11-07'})
        results = ota_payments.match_ota_payment_events([event], [card])
        assert results[0]['status'] == 'MATCHED_AUTO'
        snapshot = {'results': results, 'data': {'events': [event], 'transactions': [card], 'results': results, 'links': {}}}
        original = deepcopy(snapshot)
        monkeypatch.setattr(flow, '_held_ota_snapshot', lambda: (snapshot, True))
        monkeypatch.setattr(flow, '_ota_report', lambda: flow._canonical_snapshot_report(snapshot))
        monkeypatch.setattr(flow, 'trip_valid', lambda tid: valid_trip and tid == 'synthetic-trip')
        monkeypatch.setattr(flow, '_booking_trip_rules', lambda: {})
        monkeypatch.setattr(flow, '_booking_period_assignments', lambda *args: [])
        monkeypatch.setattr(flow, '_evidence_period_assignments', lambda *args: [])
        monkeypatch.setattr(flow, '_guide_airfare_rules', lambda *args: [])
        monkeypatch.setattr(flow, 'ota_group_holds', lambda: {})
        before = board.conn.execute('SELECT raw_row_json,amount_krw,approval_date FROM transactions').fetchall()
        flow._classify(batch)
        row = flow.pipeline.get_batch(batch)['rows'][0]
        if valid_trip:
            assert row['trip_id'] == 'synthetic-trip'
            assert row['classification_source'] == 'rule'
            # Service period wins over the card's earlier payment date.
            assert row['item'] == '숙박비'
        else:
            assert row.get('trip_id') in ('', None)
        assert snapshot == original
        assert board.conn.execute('SELECT raw_row_json,amount_krw,approval_date FROM transactions').fetchall() == before
        assert board.conn.execute('SELECT COUNT(*) FROM ledger_entries').fetchone()[0] == 0
        assert results[0]['status'] == 'MATCHED_AUTO'  # Travel authority never rewrites the payment verdict.
    finally:
        board.close()
