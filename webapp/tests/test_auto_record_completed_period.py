from unittest.mock import patch
from webapp.card_flow import CardFlow, reclassify_pending
from webapp.tests.test_card_automatic_ux import flow, make_csv, domestic_row  # noqa: F401  (shared fixture)


def _closed_batch(f):
    """2025 purchase, 2025 cancellation, 2026Q1 purchase, completed-trip purchase, open purchase."""
    c = f.board.conn
    done = f.board.create_trip(starts_on='2026-03-10', ends_on='2026-03-14', destination='합성 완료 여행',
                               client_request_id='trip-done')['tab_id']
    batch = f.pipeline.receive(make_csv([
        domestic_row(merchant='합성 A', amount=11111, approval='CP1', date='2025-10-03'),
        domestic_row(merchant='합성 B', amount=22222, approval='CP2', date='2025-11-03'),
        domestic_row(merchant='합성 C', amount=33333, approval='CP3', date='2026-02-10'),
        domestic_row(merchant='합성 D', amount=44444, approval='CP4', date='2026-03-12'),
        domestic_row(merchant='합성 E', amount=55555, approval='CP5', date='2026-07-02'),
    ]), 'closed.csv')['batch_id']
    ids = {r[0]: r[1] for r in c.execute('SELECT amount_krw,transaction_id FROM transactions '
                                         'JOIN import_batch_rows b USING(transaction_id) WHERE b.batch_id=?', (batch,))}
    c.execute("UPDATE transactions SET item='숙박비',classification_state='classified',display_tab_id='',trip_id=''"
              " WHERE transaction_id IN (%s)" % ','.join("'%s'" % t for t in ids.values()))
    c.execute("UPDATE transactions SET transaction_direction='cancellation',amount_krw=-22222 WHERE transaction_id=?",
              (ids[22222],))
    c.execute('UPDATE transactions SET display_tab_id=?,trip_id=? WHERE transaction_id=?', (done, done, ids[44444]))
    c.execute("UPDATE transactions SET display_tab_id='quarter:2025:4',trip_id='' WHERE transaction_id=?", (ids[11111],))
    c.execute("UPDATE transactions SET display_tab_id='quarter:2026:1',trip_id='' WHERE transaction_id=?", (ids[33333],))
    c.execute("UPDATE transactions SET item='분기 기타비용',display_tab_id='quarter:2026:3',trip_id='' WHERE transaction_id=?",
              (ids[55555],))
    c.commit()
    return batch, ids


def _booked(f):
    return {r[0] for r in f.board.conn.execute('SELECT transaction_id FROM ledger_entries')}


def test_auto_record_skips_completed_periods_and_completed_trip_but_books_open(flow):
    f, _, _ = flow
    with patch.object(CardFlow, '_held_ota_snapshot', return_value=(None, False)):
        batch, ids = _closed_batch(f)
        result = f.auto_record(batch)
    booked = _booked(f)
    assert ids[55555] in booked
    assert not booked & {ids[a] for a in (11111, 22222, 33333, 44444)}
    assert not f.board.conn.execute("SELECT 1 FROM board_rows WHERE row_id IN (%s)" % ','.join(
        "'card-%s'" % ids[a] for a in (11111, 22222, 33333, 44444))).fetchone()
    assert result['completed_period_excluded'] == 4
    assert result['exclusion_reason'] == 'PROC-072_COMPLETED_PERIOD'
    assert result['auto_recorded'] == 1


def test_rule_forward_application_does_not_record_completed_periods(flow, monkeypatch):
    f, _, _ = flow
    with patch.object(CardFlow, '_held_ota_snapshot', return_value=(None, False)):
        batch, ids = _closed_batch(f)
        monkeypatch.setattr(CardFlow, '_classify', lambda *a, **k: None)
        reclassify_pending(f.board)
    assert not _booked(f) & {ids[a] for a in (11111, 22222, 33333, 44444)}


def test_open_period_replay_is_unchanged_and_zero(flow):
    f, batch, _ = flow
    assert f.auto_record(batch)['auto_recorded'] == 2
    again = f.auto_record(batch)
    assert again['auto_recorded'] == 0 and 'completed_period_excluded' not in again
