"""An explicit OTA review can replace a recorded automatic calendar guess."""
import json

import pytest

from app import automatic_classification as policy
from webapp.tests.test_automatic_classification_completion import setup


@pytest.mark.parametrize('protection', ['', 'manual', 'hold', 'refund', 'refund_original', 'source', 'stale_source', 'owner_record'])
@pytest.mark.parametrize('entrypoint', ['policy', 'runtime', 'stale_snapshot'])
def test_recorded_calendar_guess_yields_to_booking_period_atomically(setup, monkeypatch, protection, entrypoint):
    board, flow, batch, rows = setup
    first = board.create_trip(starts_on='2026-10-01', ends_on='2026-10-05',
                              destination='Payment', client_request_id='payment')['tab_id']
    second = board.create_trip(starts_on='2026-10-10', ends_on='2026-10-13',
                               destination='Stay', client_request_id='stay')['tab_id']
    monkeypatch.setattr(flow, 'trip_valid', lambda _: True)
    tid = rows[0]['transaction_id']
    c = board.conn
    c.execute("UPDATE transactions SET classification_state='classified',classification_source='inference',"
              "item='숙박비',trip_id=?,display_tab_id=? WHERE transaction_id=?", (first, first, tid))
    preview = flow.pipeline.preview(batch, trip_validator=lambda _: True, tab_validator=lambda _: True)
    flow.pipeline.commit(batch, preview['digest'], 'record', trip_validator=lambda _: True,
                         tab_validator=lambda _: True, projection=flow.project)
    payload = json.loads(c.execute('SELECT payload_json FROM board_rows WHERE row_id=?', ('card-'+tid,)).fetchone()[0])
    payload['confirmed_by'] = 'automatic'
    c.execute('UPDATE board_rows SET payload_json=? WHERE row_id=?', (json.dumps(payload), 'card-'+tid))
    if protection == 'manual':
        c.execute("INSERT INTO board_manual_overrides VALUES (?,'display_tab_id','manual')", ('card-'+tid,))
    elif protection == 'hold':
        c.execute("INSERT INTO transaction_review_holds VALUES (?,?,'user_hold','hold')", (tid, rows[0]['source_hash']))
    elif protection == 'refund':
        c.execute("UPDATE board_rows SET display_tab_id='refunds' WHERE row_id=?", ('card-'+tid,))
    elif protection == 'source':
        c.execute("UPDATE transactions SET classification_source='user_decision' WHERE transaction_id=?", (tid,))
    elif protection == 'owner_record':
        payload['confirmed_by'] = 'owner'
        c.execute('UPDATE board_rows SET payload_json=? WHERE row_id=?', (json.dumps(payload), 'card-'+tid))
    elif protection == 'refund_original':
        c.execute("UPDATE transactions SET transaction_direction='cancellation',original_approval_number=?,issuer=?,card_tail=? WHERE transaction_id=?",
                  (rows[0]['approval_number'], rows[0]['issuer'], rows[0]['card_tail'], rows[1]['transaction_id']))
    c.commit()
    trips = [dict(trip_id=first, starts_on='2026-10-01', ends_on='2026-10-05'),
             dict(trip_id=second, starts_on='2026-10-10', ends_on='2026-10-13')]
    evidence = {tid: dict(source_hash='stale' if protection == 'stale_source' else rows[0]['source_hash'],
                         trip_id=second, item='숙박비', basis='예약 이용기간 2026-10-13~2026-10-14')}
    options = dict(transaction_ids={tid}, reconsider=True, evidence=evidence)
    raw = c.execute('SELECT source_hash,raw_row_json,amount_krw,approval_date,posting_date FROM transactions WHERE transaction_id=?', (tid,)).fetchone()
    date = c.execute('SELECT occurred_on FROM ledger_entries WHERE transaction_id=?', (tid,)).fetchone()
    plan = policy.plan(c, trips, **options)
    assert c.execute('SELECT trip_id FROM transactions WHERE transaction_id=?', (tid,)).fetchone()[0] == first
    if entrypoint == 'policy':
        policy.apply(c, plan, trips, **options)
    else:
        from webapp.card_classification_completion import correct_recorded_booking_periods
        event = dict(ota_event_id='booking', event_type='charge', payment_status='paid', evidence_status='paid_verified')
        current = {'data': {'events': [event]}}
        fact = dict(transaction_id=tid, source_hash=evidence[tid]['source_hash'], source_sha256='a'*64,
                    ota_event_id='booking', item='숙박비', reservation_status='confirmed',
                    period=dict(starts_on='2026-10-13', ends_on='2026-10-14'))
        monkeypatch.setattr(flow, '_held_ota_snapshot', lambda: (current, entrypoint != 'stale_snapshot'))
        monkeypatch.setattr(flow, '_canonical_snapshot_report', lambda _: {'matches': [fact]})
        correct_recorded_booking_periods(flow, batch, {tid})
    target = first if protection or entrypoint == 'stale_snapshot' else second
    assert c.execute('SELECT trip_id FROM transactions WHERE transaction_id=?', (tid,)).fetchone()[0] == target
    assert c.execute('SELECT trip_id,display_tab_id FROM ledger_entries WHERE transaction_id=?', (tid,)).fetchone() == (target,target)
    record = c.execute('SELECT display_tab_id,payload_json,revision FROM board_rows WHERE row_id=?', ('card-'+tid,)).fetchone()
    assert record[0] == ('refunds' if protection == 'refund' else target)
    assert raw == c.execute('SELECT source_hash,raw_row_json,amount_krw,approval_date,posting_date FROM transactions WHERE transaction_id=?', (tid,)).fetchone()
    assert date == c.execute('SELECT occurred_on FROM ledger_entries WHERE transaction_id=?', (tid,)).fetchone()
    if not protection and entrypoint != 'stale_snapshot':
        assert json.loads(record[1])['revision'] == record[2]
        assert c.execute("SELECT COUNT(*) FROM board_revisions WHERE row_id=? AND client_request_id LIKE 'booking-period-%'", ('card-'+tid,)).fetchone()[0] == 1
        assert c.execute("SELECT COUNT(*) FROM change_log WHERE kind='card.booking_trip_correction'").fetchone()[0] == 1
        if entrypoint == 'policy':
            assert policy.plan(c, trips, **options)['summary']['to_classify'] == 0
        else:
            assert correct_recorded_booking_periods(flow, batch, {tid}) == 0


def test_booking_correction_rolls_back_all_projections_on_write_failure(setup, monkeypatch):
    # Exercise the successful scenario's writes under a failing audit insert.
    board, _, _, _ = setup
    board.conn.execute("CREATE TRIGGER fail_booking_audit BEFORE INSERT ON change_log "
                       "WHEN NEW.kind='card.booking_trip_correction' BEGIN SELECT RAISE(ABORT,'audit failed'); END")
    with pytest.raises(Exception, match='audit failed'):
        test_recorded_calendar_guess_yields_to_booking_period_atomically(setup, monkeypatch, '', 'policy')
    # The setup performed by the scenario commits; the correction transaction is rolled back.
    assert board.conn.execute("SELECT COUNT(*) FROM board_revisions WHERE client_request_id LIKE 'booking-period-%'").fetchone()[0] == 0
    assert board.conn.execute("SELECT COUNT(*) FROM transactions WHERE classification_basis LIKE '%예약 이용기간 근거 우선:%'").fetchone()[0] == 0
