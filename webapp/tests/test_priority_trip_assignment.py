import copy

from app.classify import classify_transaction
from webapp.card_flow import CardFlow
from webapp.ledger_store import LedgerStore
from webapp.tests.test_expense_cleanup import card_rows


def test_classification_pipeline_uses_priority_rule_and_preview_keeps_booking_blank(tmp_path, monkeypatch):
    from webapp import card_flow
    board = LedgerStore(tmp_path / 'pipeline.sqlite', seed_demo=False)
    try:
        flow, batch, rows = card_rows(board, 1)
        trip = board.create_trip(starts_on='2026-10-01', ends_on='2026-10-05', destination='합성', client_request_id='pipeline')
        board.conn.execute("UPDATE transactions SET item='숙박비',merchant='합성호텔',merchant_normalized='합성호텔',display_tab_id='unclassified'")
        board.conn.commit()
        raw = board.conn.execute('SELECT raw_row_json,amount_krw,approval_date FROM transactions').fetchall()
        monkeypatch.setattr(flow, 'trip_valid', lambda target: target == trip['tab_id'])
        monkeypatch.setattr(flow, 'ota_group_holds', lambda: {})
        monkeypatch.setattr(flow, '_held_ota_snapshot', lambda: (None, False))
        monkeypatch.setattr(flow, '_evidence_period_assignments', lambda *args: [])
        monkeypatch.setattr(flow, '_guide_airfare_rules', lambda *args: [])
        flow._classify(batch)
        row = flow.pipeline.get_batch(batch)['rows'][0]
        assert row['trip_id'] == trip['tab_id'] and row['item'] == '숙박비'
        preview = flow.pipeline.preview(batch, trip_validator=flow.trip_valid, tab_validator=flow.tab_valid)
        assert not preview['rows'][0].get('blocked')
        assert preview['ready'] == 1
        assert not preview['rows'][0].get('booking_ref')
        assert not preview['rows'][0].get('reservation_no')
        before = board.conn.execute('SELECT * FROM transactions').fetchall()
        flow._classify(batch)
        assert board.conn.execute('SELECT * FROM transactions').fetchall() == before
        assert board.conn.execute('SELECT raw_row_json,amount_krw,approval_date FROM transactions').fetchall() == raw
        assert board.conn.execute('SELECT COUNT(*) FROM ledger_entries').fetchone()[0] == 0
        # 여행 후보 규칙이 현재 업종 규칙의 항목과 설명을 오래된 값으로 되돌리면 안 된다.
        regular = {'conditions': {'merchant_normalized': '합성호텔', 'transaction_direction': 'purchase'},
                   'optional': {}, 'effects': {'item': '식비', 'description': '사용자 업종 규칙'}, 'rule_id': 'category'}
        fallback = flow._fallback_trip_assignments(batch, set(), None, set())
        verdict = classify_transaction(dict(rows[0], merchant='합성호텔', merchant_normalized='합성호텔'),
                                       rules=[regular, *fallback], trip_resolver=flow.retail_trip)
        assert verdict['item'] == '식비' and verdict['description'] == '사용자 업종 규칙'
        saved = flow.pipeline.commit(batch, preview['digest'], 'priority-save',
                                     projection=flow.project, trip_validator=flow.trip_valid,
                                     tab_validator=flow.tab_valid)
        assert flow.pipeline.commit(batch, preview['digest'], 'priority-save',
                                    projection=flow.project, trip_validator=flow.trip_valid,
                                    tab_validator=flow.tab_valid) == saved
        assert board.conn.execute('SELECT COUNT(*) FROM ledger_entries').fetchone()[0] == 1
        assert board.conn.execute('SELECT COUNT(*) FROM board_rows').fetchone()[0] == 1
        assert not __import__('json').loads(board.conn.execute('SELECT payload_json FROM board_rows').fetchone()[0])['reservation_no']
    finally:
        board.close()


def test_unlinked_card_gets_existing_trip_without_confirming_booking_and_preserves_guards(tmp_path, monkeypatch):
    board = LedgerStore(tmp_path / 'priority.sqlite', seed_demo=False)
    try:
        flow, batch, rows = card_rows(board, 5)
        old = board.create_trip(starts_on='2026-08-01', ends_on='2026-08-05', destination='합성', client_request_id='old')
        near = board.create_trip(starts_on='2026-10-01', ends_on='2026-10-05', destination='합성', client_request_id='near')
        monkeypatch.setattr(flow, 'trip_valid', lambda target: target in (old['tab_id'], near['tab_id']))
        monkeypatch.setattr(flow, 'ota_group_holds', lambda: {rows[4]['transaction_id']: {'kind': 'frozen'}})
        board.conn.execute("UPDATE transactions SET item='숙박비',merchant='합성 호텔',merchant_normalized='합성호텔',display_tab_id='unclassified'")
        board.conn.execute("UPDATE transactions SET classification_source='user_decision' WHERE transaction_id=?", (rows[1]['transaction_id'],))
        board.conn.execute("UPDATE transactions SET duplicate_of=? WHERE transaction_id=?", (rows[0]['transaction_id'], rows[2]['transaction_id']))
        board.conn.execute("INSERT INTO transaction_review_holds(transaction_id,source_hash,kind,reason) VALUES (?,?,?,?)",
                           (rows[3]['transaction_id'], rows[3]['source_hash'], 'evidence_pending', 'synthetic'))
        board.conn.commit()
        before = board.conn.execute('SELECT * FROM transactions ORDER BY transaction_id').fetchall()
        rules = flow._fallback_trip_assignments(batch, set(), None, set())
        assert len(rules) == 1
        inference = rules[0]['optional']['inferred_assignment']
        assert inference['trip_id'] == near['tab_id'] and inference['confidence'] == '낮음'
        transaction = dict(rows[0], merchant='합성 호텔', merchant_normalized='합성호텔')
        verdict = classify_transaction(transaction, rules=rules, trip_resolver=flow.retail_trip)
        assert verdict['trip_id'] == near['tab_id'] and verdict['classification_source'] == 'inference'
        assert 'AUTO_INFERRED' in verdict['classification_basis']
        assert '예약' not in verdict['description']
        assert flow._fallback_trip_assignments(batch, {rows[0]['source_hash']}, None, set()) == []
        assert flow._fallback_trip_assignments(batch, set(), set(), set()) == []
        assert board.conn.execute('SELECT * FROM transactions ORDER BY transaction_id').fetchall() == before
        assert board.conn.execute('SELECT COUNT(*) FROM ledger_entries').fetchone()[0] == 0
        board.conn.execute("UPDATE transactions SET card_tail='3820' WHERE transaction_id=?", (rows[0]['transaction_id'],))
        assert flow._fallback_trip_assignments(batch, set(), None, set()) == []
        board.conn.execute("UPDATE transactions SET card_tail='1234' WHERE transaction_id=?", (rows[0]['transaction_id'],))
        dated = {'data': {'events': [{'ota_event_id': 'known-period', 'service_period': {'starts_on': '2026-12-01'}}],
                          'results': [{'ota_event_id': 'known-period', 'candidate_search': {
                              'candidates': [{'transaction_id': rows[0]['transaction_id']}]}}]}}
        monkeypatch.setattr(flow, '_held_ota_snapshot', lambda: (dated, True))
        assert flow._fallback_trip_assignments(batch, set(), None, set()) == []
    finally:
        board.close()


def test_toyoko_canonical_reservation_period_assigns_trip_but_not_booking_identity(tmp_path, monkeypatch):
    board = LedgerStore(tmp_path / 'reservation.sqlite', seed_demo=False)
    try:
        flow, batch, rows = card_rows(board, 1)
        card = dict(rows[0], ota_inference_eligible=True)
        trip = board.create_trip(starts_on='2026-10-01', ends_on='2026-10-05', destination='합성', client_request_id='stay')
        event = dict(ota_event_id='synthetic', provider='toyoko', event_type='reservation',
                     evidence_status='reservation_only', reservation_status='confirmed', item='숙박비',
                     service_period={'starts_on': '2026-10-03', 'ends_on': '2026-10-06'})
        result = dict(ota_event_id='synthetic', status='RESERVATION_ONLY', candidate_search={
            'status': 'CANDIDATES_FOUND', 'candidates': [{'transaction_id': card['transaction_id'], 'resolution_allowed': False}]})
        snapshot = {'data': {'events': [event], 'transactions': [card], 'results': [result]}}
        monkeypatch.setattr(flow, '_held_ota_snapshot', lambda: (snapshot, True))
        monkeypatch.setattr(flow, 'trip_valid', lambda target: target == trip['tab_id'])
        rules = flow._canonical_candidate_period_assignments({card['source_hash']}, set(), None, set())
        assert len(rules) == 1
        assert rules[0]['optional']['inferred_assignment']['trip_id'] == trip['tab_id']
        assert set(rules[0]['effects']) == {'item'}
        before = copy.deepcopy(snapshot)
        event['reservation_status'] = 'cancelled'
        assert flow._canonical_candidate_period_assignments({card['source_hash']}, set(), None, set()) == []
        event['reservation_status'] = 'confirmed'
        assert snapshot == before
        assert board.conn.execute('SELECT COUNT(*) FROM ledger_entries').fetchone()[0] == 0
    finally:
        board.close()
