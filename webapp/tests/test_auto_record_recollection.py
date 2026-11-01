from webapp.tests.test_card_automatic_ux import flow, make_csv, domestic_row  # noqa: F401  (shared fixture)


def test_recollecting_the_same_statement_keeps_one_entry_and_the_user_move(flow):
    f, batch, trip = flow
    other = f.board.create_trip(starts_on='2026-04-08', ends_on='2026-04-12', destination='합성 교토',
                                client_request_id='trip-other')['tab_id']
    assert f.auto_record(batch)['auto_recorded'] == 1
    f.board.conn.execute('UPDATE transactions SET display_tab_id=?,trip_id=? WHERE amount_krw=188808', (other, other))
    f.board.conn.commit()
    again = f.pipeline.receive(make_csv([
        domestic_row(merchant='합성 AGODA A', amount=89891, approval='UX1', date='2026-04-01'),
        domestic_row(merchant='합성 AGODA B', amount=188808, approval='UX2', date='2026-04-01'),
    ]), 'ux-again.csv')['batch_id']
    f.auto_record(again)
    assert f.board.conn.execute('SELECT COUNT(*), SUM(amount_krw) FROM ledger_entries').fetchone() == (1, 188808)
    assert f.board.conn.execute("SELECT COUNT(*) FROM transactions WHERE amount_krw IN (89891,188808)").fetchone()[0] == 2
    assert f.board.conn.execute("SELECT display_tab_id FROM transactions WHERE amount_krw=188808").fetchone()[0] == other


def test_auto_record_recovers_legacy_booking_classification_before_preview(flow, monkeypatch):
    f, batch, _ = flow
    c = f.board.conn
    pending = f.pipeline.get_batch(batch)['rows'][0]['transaction_id']
    c.execute("UPDATE transactions SET merchant='Booking.com90000000001',"
              "merchant_normalized='booking.com90000000001',card_tail='3820',transaction_kind='purchase',"
              "classification_state='needs_review',classification_source='booking_evidence_needed',"
              "item='',trip_id='',display_tab_id='' WHERE transaction_id=?", (pending,))
    other = f.pipeline.receive(make_csv([
        domestic_row(merchant='SYNTHETIC OTHER BATCH', amount=1010,
                     approval='UNTOUCHED', date='2026-04-01')]), 'other.csv')['batch_id']
    raw = c.execute('SELECT transaction_id,source_hash,raw_row_json,amount_krw,approval_date,posting_date FROM transactions ORDER BY transaction_id').fetchall()
    other_before = f.pipeline.get_batch(other)['rows']
    c.commit()
    monkeypatch.setattr(f, '_ota_report', lambda: None)
    monkeypatch.setattr(f, '_held_ota_snapshot', lambda: (None, False))
    # GETs remain read-only even when a historical batch still needs completion.
    f.state(batch)
    assert c.execute('SELECT classification_state FROM transactions WHERE transaction_id=?', (pending,)).fetchone()[0] == 'needs_review'
    result = f.auto_record(batch)
    assert c.execute('SELECT classification_state,item,display_tab_id FROM transactions WHERE transaction_id=?', (pending,)).fetchone() == (
        'classified', '분기 기타비용', 'quarter:2026:2')
    assert c.execute('SELECT decided_at FROM transactions WHERE transaction_id=?', (pending,)).fetchone()[0] is None
    assert not c.execute('SELECT 1 FROM review_decisions WHERE transaction_id=?', (pending,)).fetchone()
    assert f.pipeline.get_batch(other)['rows'] == other_before
    assert c.execute('SELECT transaction_id,source_hash,raw_row_json,amount_krw,approval_date,posting_date FROM transactions ORDER BY transaction_id').fetchall() == raw
    after = c.execute('SELECT * FROM transactions ORDER BY transaction_id').fetchall()
    board_count = c.execute('SELECT COUNT(*) FROM board_rows').fetchone()[0]
    assert f.auto_record(batch)['auto_recorded'] == 0
    assert c.execute('SELECT COUNT(*) FROM board_rows').fetchone()[0] == board_count
    assert c.execute('SELECT * FROM transactions ORDER BY transaction_id').fetchall() == after


def test_auto_record_does_not_reclassify_protected_pending_rows(flow, monkeypatch):
    f, batch, _ = flow
    c = f.board.conn
    rows = f.pipeline.get_batch(batch)['rows']
    c.execute("UPDATE transactions SET classification_state='needs_review',classification_source='booking_evidence_needed',item=''")
    c.execute('INSERT INTO transaction_review_holds VALUES (?,?,?,?)',
              (rows[0]['transaction_id'], rows[0]['source_hash'], 'user_hold', 'synthetic'))
    c.execute("UPDATE transactions SET parse_error='synthetic' WHERE transaction_id=?", (rows[1]['transaction_id'],))
    c.commit()
    before = c.execute('SELECT * FROM transactions ORDER BY transaction_id').fetchall()
    monkeypatch.setattr(f, '_classify', lambda *a, **k: (_ for _ in ()).throw(AssertionError('protected row reclassified')))
    assert f.auto_record(batch)['auto_recorded'] == 0
    assert c.execute('SELECT * FROM transactions ORDER BY transaction_id').fetchall() == before
