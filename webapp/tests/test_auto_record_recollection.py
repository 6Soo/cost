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
