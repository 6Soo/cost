"""화면 연결이 실제 예약 날짜·여행·중복 없는 비용 기록으로 이어지는지 확인한다."""
from types import SimpleNamespace

from app.ota_mail import ledger_metadata
from app.ota_core_projection import extend_report
from webapp import ota_payment_review
from webapp.card_flow import CardFlow
from webapp.ledger_store import LedgerStore


def test_core_ordered_pair_reaches_classification_preview_and_ledger(tmp_path, monkeypatch):
    monkeypatch.setenv('WEBLEDGER_UNIFIED_DB', '1')
    monkeypatch.setenv('WEBLEDGER_CARD_FLOW', '1')
    monkeypatch.setenv('WEBLEDGER_OTA_REVIEW_DB', str(tmp_path / 'review.sqlite'))
    monkeypatch.delenv('WEBLEDGER_REVIEW_CONFIG', raising=False)
    board = LedgerStore(tmp_path / 'board.sqlite', seed_demo=False)
    try:
        flow = CardFlow(board)
        board.conn.execute("INSERT INTO trip_tabs(tab_id,display_key,starts_on,ends_on) VALUES "
                           "('trip-x','1104_합성','2026-11-04','2026-11-10')")
        board.conn.commit()
        csv = ('Issuer,Card No,Card Type,Type,Merchant,Amount,Foreign Amount,Currency,Amount KRW,'
               'Date,Post Date,Authorization Code,Cancel,Status\n'
               '하나,4595,domestic,purchase,TRIP.COM,90121,,,90121,2026-09-23,2026-09-24,SYN-1,,매입\n').encode()
        batch = flow.pipeline.receive(csv, 'synthetic.csv')['batch_id']
        cursor = board.conn.execute('SELECT * FROM transactions')
        card = dict(zip([c[0] for c in cursor.description], cursor.fetchone()))
        tid = card['transaction_id']
        card['ota_inference_eligible'] = True
        event = {'ota_event_id': 'synthetic-event', 'provider': 'trip', 'booking_ref': 'SYN-BOOK',
                 'event_type': 'charge', 'paid_on': '2026-09-23', 'payment_status': 'paid',
                 'evidence_status': 'paid_verified', 'reservation_status': 'confirmed', 'item': '숙박비',
                 'amount_krw': 90121, 'amount': 90121, 'currency': 'KRW',
                 'source_digest': 'a' * 64, 'evidence_kind': 'authenticated_payment_mail',
                 'service_period': {'starts_on': '2026-11-06', 'ends_on': '2026-11-07'}}
        data = {'events': [event], 'transactions': [card], 'results': [
            {'ota_event_id': event['ota_event_id'], 'status': 'MATCHED_AUTO', 'transaction_id': tid,
             'allocation_basis': 'auto_stable_order'}]}
        raw = {'matches': [], 'rules': [], 'type_only_candidates': [], 'unmatched_transactions': []}
        current = {'data': data, 'results': data['results'], 'links': {}}
        monkeypatch.setattr(ota_payment_review, 'enabled', lambda: True)
        monkeypatch.setattr(ota_payment_review, 'snapshot_service', lambda _: SimpleNamespace(
            held=lambda: (current, True)))
        monkeypatch.setattr(flow, '_compute_ota_report', lambda: raw)
        monkeypatch.setattr(flow, 'trip_valid', lambda tab: tab == 'trip-x')
        monkeypatch.setattr(flow, 'tab_valid', lambda tab: tab == 'trip-x')
        monkeypatch.setattr(flow, 'retail_trip', lambda *args, **kwargs: 'trip-x')
        flow._classify(batch, transaction_ids=[tid])
        row = board.conn.execute('SELECT classification_state,trip_id FROM transactions WHERE transaction_id=?',
                                 (tid,)).fetchone()
        assert tuple(row) == ('classified', 'trip-x')
        options = dict(trip_validator=flow.trip_valid, tab_validator=flow.tab_valid,
                       entry_metadata=flow.preview_metadata())
        preview = flow.pipeline.preview(batch, **options)
        target = next(r for r in preview['rows'] if r['transaction_id'] == tid)
        assert target['booking_ref'] == 'SYN-BOOK'
        assert target['ota_evidence']['kind'] == 'ordered_group'
        assert target['service_period'] == '2026-11-06~2026-11-07'
        assert target['occurred_on'] == '2026-11-06'
        recorded = flow.pipeline.commit(batch, preview['digest'], 'synthetic-record',
                                       projection=flow.project, **options)
        assert recorded['applied'] == 1
        expense = board.conn.execute('SELECT payload_json FROM board_rows WHERE row_id=?', ('card-' + tid,)).fetchone()
        import json
        payload = json.loads(expense[0])
        assert payload['occurred_on'] == '2026-11-06' and payload['reservation_no'] == 'SYN-BOOK'
        assert payload['source_approval_date'] == '2026-09-23'
        repeated = flow.pipeline.commit(batch, preview['digest'], 'synthetic-record',
                                       projection=flow.project, **options)
        assert repeated == recorded
        assert board.conn.execute('SELECT count(*) FROM ledger_entries').fetchone()[0] == 1
        next_preview = flow.pipeline.preview(batch, **options)
        assert next(r for r in next_preview['rows'] if r['transaction_id'] == tid)['occurred_on'] == '2026-11-06'
        assert raw['matches'] == [] and raw['rules'] == []
    finally:
        board.close()


def test_completed_inference_keeps_booking_metadata_without_becoming_exact():
    fact = {'transaction_id': 'card', 'source_hash': 'source', 'provider': 'agoda',
            'booking_ref': 'SYN-BOOK', 'item': '숙박비', 'reservation_status': 'completed',
            'period': {'starts_on': '2026-10-14', 'ends_on': '2026-10-16'},
            'source_sha256': 'a' * 64, 'inferred_link': True, 'paid_on': None}
    result = ledger_metadata({'matches': [fact]}, dict(fact, transaction_direction='purchase'))
    assert result['booking_ref'] == 'SYN-BOOK'
    assert result['ota_evidence']['kind'] == 'inferred'
    assert result['ota_evidence']['payment_date_verified'] is False
    assert fact['paid_on'] is None


def test_same_booking_payment_receipt_gains_verified_service_period_only():
    from copy import deepcopy
    old = dict(transaction_id='card', source_hash='source', provider='booking', booking_ref='SYN',
               item='숙박비', period=None, reservation_status='observed', source_sha256='receipt',
               direction='purchase', merchant='BOOKING.COM')
    event = dict(ota_event_id='event', provider='booking', booking_ref='SYN', item='숙박비',
                 event_type='charge', payment_status='paid', evidence_status='paid_verified',
                 reservation_status='observed', source_digest='period-proof',
                 service_period={'starts_on': '2026-08-14', 'ends_on': '2026-08-15'})
    card = dict(transaction_id='card', source_hash='source', merchant='BOOKING.COM',
                transaction_direction='purchase', ota_inference_eligible=True)
    data = dict(events=[event], transactions=[card], links={}, results=[
        dict(ota_event_id='event', transaction_id='card', status='MATCHED_AUTO')])
    report = dict(matches=[old], rules=[], type_only_candidates=[])
    original = deepcopy(report)
    result = extend_report(report, data)
    assert len(result['matches']) == 1
    assert result['matches'][0]['period'] == event['service_period']
    assert result['matches'][0]['source_digests'] == ['period-proof', 'receipt']
    assert result['matches'][0]['source_sha256'] == 'receipt'
    assert result['rules'][0]['optional']['source_hash'] == 'source'
    assert report == original
    ambiguous = dict(report, matches=[old, dict(old, booking_ref='OTHER')])
    assert extend_report(ambiguous, data) == ambiguous
    for changes in ({'booking_ref': 'OTHER'}, {'reservation_status': 'cancelled'},
                    {'source_hash': 'different'}, {'period_conflict': True},
                    {'period': {'starts_on': '2026-09-01', 'ends_on': '2026-09-02'}}):
        protected = dict(report, matches=[dict(old, **changes)])
        assert extend_report(protected, data) == protected
