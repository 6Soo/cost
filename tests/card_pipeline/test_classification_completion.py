import sqlite3

from app.automatic_classification import classification_completion


TRIP = [{'trip_id': 'trip-a', 'starts_on': '2026-01-01', 'ends_on': '2026-01-03'}]


def _db(rows):
    db = sqlite3.connect(':memory:')
    db.executescript('''
      CREATE TABLE import_batch_rows(batch_id TEXT, transaction_id TEXT);
      CREATE TABLE transactions(
        transaction_id TEXT, transaction_direction TEXT, transaction_kind TEXT,
        classification_state TEXT, classification_source TEXT, classification_basis TEXT,
        item TEXT, trip_id TEXT, display_tab_id TEXT, decided_at TEXT);
    ''')
    for row in rows:
        db.execute('INSERT INTO transactions VALUES (?,?,?,?,?,?,?,?,?,?)', row)
        db.execute('INSERT INTO import_batch_rows VALUES (?,?)', ('batch', row[0]))
    return db


def _row(tid, *, source='', basis='', trip='trip-a', decided=None, direction='purchase', kind='purchase'):
    return (tid, direction, kind, 'classified', source, basis, 'food', trip, trip, decided)


def test_completion_requires_nature_and_authoritative_trip_and_preserves_manual():
    db = _db([_row('manual', source='user_decision', decided='2026-10-29T00:00:00Z'),
              _row('nature', kind='', trip='trip-a'), _row('deleted', trip='gone')])
    result = classification_completion(db, 'batch', TRIP)
    assert result['complete'] is False
    by_id = {row['transaction_id']: row for row in result['rows']}
    assert by_id['manual']['complete'] is True
    assert by_id['nature']['blocked_by'] == ['TRANSACTION_NATURE_UNCONFIRMED']
    assert by_id['deleted']['blocked_by'] == ['TRIP_INVALID_OR_MISSING']


def test_auto_requires_evidence_and_rejects_provisional_or_tie():
    db = _db([_row('auto', source='inference', basis='AUTO_INFERRED · high confidence'),
              _row('tie', source='inference', basis='AUTO_INFERRED · tie'),
              _row('provisional', source='inference', basis='AUTO_INFERRED · provisional')])
    result = classification_completion(db, 'batch', TRIP)
    by_id = {row['transaction_id']: row for row in result['rows']}
    assert [by_id[name]['complete'] for name in ('auto', 'tie', 'provisional')] == [True, False, False]
    assert result['audit']['source'] and result['audit']['version'] and result['audit']['at']
