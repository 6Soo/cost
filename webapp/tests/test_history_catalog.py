import sqlite3

from webapp import card_catalog, ota_catalog
from webapp.tests.test_card_catalog import stored
from webapp.tests.test_ota_catalog import data


def test_past_cards_are_preserved_but_not_counted_as_pending(stored, monkeypatch):
    monkeypatch.setenv('WEBLEDGER_REVIEW_FROM', '2026-04-01')
    ids = [r[0] for r in stored.conn.execute('SELECT transaction_id FROM transactions ORDER BY transaction_id')]
    for tid, day in zip(ids, ['2025-12-01', '2026-03-31', '2026-04-01']):
        stored.conn.execute('UPDATE transactions SET approval_date=? WHERE transaction_id=?', (day, tid))
    stored.conn.commit()
    before = stored.conn.execute('SELECT * FROM transactions ORDER BY transaction_id').fetchall()
    result = card_catalog.catalog(stored, {})
    assert result['total'] == result['all_count'] == 1
    assert result['months'] == ['2026-04']
    assert result['rows'][0]['transaction_id'] == ids[2]
    assert card_catalog.catalog(stored, {'month': ['2025-12']})['total'] == 0
    assert before == stored.conn.execute('SELECT * FROM transactions ORDER BY transaction_id').fetchall()


def test_ota_uses_service_period_and_keeps_unknown_and_cross_boundary(data, monkeypatch):
    board, sources = data
    monkeypatch.setenv('WEBLEDGER_REVIEW_FROM', '2026-04-01')
    path = sources['portal_databases'][0]
    with sqlite3.connect(path) as conn:
        conn.execute("UPDATE bookings SET service_start_on='2025-12-01',service_end_on='2025-12-03' WHERE id=1")
        conn.execute("UPDATE bookings SET service_start_on='2026-03-31',service_end_on='2026-04-02' WHERE id=2")
    before = path.read_bytes()
    result = ota_catalog.catalog(board, {}, sources=sources)
    assert result['all_count'] == result['total'] == 2
    assert result['unassigned_count'] == 2
    assert all(not r['starts_on'].startswith('2025') for r in result['rows'])
    assert result['months'] == ['2026-03']
    assert path.read_bytes() == before
