import pytest

from webapp import ledger_board
from webapp.ledger_store import LedgerStore, SaveError


@pytest.fixture
def store(tmp_path):
    store = LedgerStore(tmp_path / 'board.sqlite')
    ledger_board.bind_store(store)
    yield store
    ledger_board.bind_store(None)
    store.close()


def rows(store):
    ids = ['expense-demo-c1', 'expense-demo-c4']
    return [{'row_id': rid, 'revision': store.get_row(rid)['revision']} for rid in ids]


def test_atomic_trip_edit_preserves_other_fields_and_replays(store):
    chosen = rows(store)
    before = [store.get_row(x['row_id']) for x in chosen]
    result = store.save_expense_trips_atomic(rows=chosen, target='trip-demo-b', client_request_id='bulk-test')
    assert result['count'] == 2
    for original in before:
        after = store.get_row(original['row_id'])
        assert after['display_tab_id'] == 'trip-demo-b'
        assert after['item'] == original['item']
        assert after['amount_krw'] == original['amount_krw']
        assert after['source_event_id'] == original['source_event_id']
        assert after['revision'] == original['revision'] + 1
    assert store.save_expense_trips_atomic(rows=chosen, target='trip-demo-b', client_request_id='bulk-test') == result
    with pytest.raises(SaveError) as err:
        store.save_expense_trips_atomic(rows=chosen, target='trip-demo-a', client_request_id='bulk-test')
    assert err.value.code == 'REQUEST_ID_REUSED'


def test_conflict_rolls_back_every_row(store):
    chosen = rows(store)
    before = [store.get_row(x['row_id']) for x in chosen]
    chosen[1]['revision'] += 1
    with pytest.raises(SaveError) as err:
        store.save_expense_trips_atomic(rows=chosen, target='trip-demo-b', client_request_id='bulk-conflict')
    assert err.value.code == 'EDIT_CONFLICT'
    assert [store.get_row(x['row_id']) for x in chosen] == before


def test_single_item_edit_does_not_lock_unchanged_trip_before_bulk_move(store):
    rid = 'expense-demo-c1'
    original = store.get_row(rid)
    store.save(row_id=rid, expected_revision=original['revision'],
               client_request_id='item-edit', change_mode='exception',
               changes={'item': '식비', 'display_tab_id': original['display_tab_id']})
    fields = {row[0] for row in store.conn.execute(
        'SELECT field FROM board_manual_overrides WHERE row_id=?', (rid,))}
    assert fields == {'item'}
    chosen = rows(store)
    result = store.save_expense_trips_atomic(
        rows=chosen, target='trip-demo-b', client_request_id='after-item-edit')
    assert result['count'] == 2
    assert store.get_row(rid)['display_tab_id'] == 'trip-demo-b'
    assert store.get_row(rid)['item'] == '식비'
    assert store.get_row(rid)['amount_krw'] == original['amount_krw']


def test_bulk_move_accepts_rows_already_in_destination_without_new_revision(store):
    chosen = rows(store)
    store.save(row_id='expense-demo-c3', expected_revision=1,
               client_request_id='seed-destination', change_mode='exception',
               changes={'display_tab_id': 'trip-demo-b'}, actor='automatic')
    other = store.get_row('expense-demo-c3')
    chosen.append({'row_id': other['row_id'], 'revision': other['revision']})
    assert other['display_tab_id'] == 'trip-demo-b'
    result = store.save_expense_trips_atomic(
        rows=chosen, target='trip-demo-b', client_request_id='mixed-destination')
    assert result['count'] == 3
    assert store.get_row(other['row_id']) == other
    assert all(store.get_row(row['row_id'])['display_tab_id'] == 'trip-demo-b'
               for row in chosen)


def test_item_edit_preserves_existing_manual_trip_protection(store):
    rid = 'expense-demo-c1'
    original = store.get_row(rid)
    store.conn.execute(
        'INSERT INTO board_manual_overrides(row_id,field,event_id) VALUES (?,?,?)',
        (rid, 'display_tab_id', 'existing-trip-decision'))
    store.conn.commit()
    store.save(row_id=rid, expected_revision=original['revision'],
               client_request_id='protected-item-edit', change_mode='exception',
               changes={'item': '식비', 'display_tab_id': original['display_tab_id']})
    assert store.conn.execute(
        'SELECT event_id FROM board_manual_overrides WHERE row_id=? AND field=?',
        (rid, 'display_tab_id')).fetchone()[0] == 'existing-trip-decision'
    with pytest.raises(SaveError) as err:
        store.save_expense_trips_atomic(
            rows=rows(store), target='trip-demo-b', client_request_id='protected-move')
    assert err.value.code == 'FIELD_READ_ONLY'
    assert store.get_row(rid)['display_tab_id'] == original['display_tab_id']


def test_manual_override_refuses_whole_batch(store):
    chosen = rows(store)
    before = [store.get_row(x['row_id']) for x in chosen]
    store.conn.execute("INSERT INTO board_manual_overrides(row_id,field,event_id) VALUES (?, 'display_tab_id', '')", (chosen[1]['row_id'],))
    store.conn.commit()
    with pytest.raises(SaveError) as err:
        store.save_expense_trips_atomic(rows=chosen, target='trip-demo-b', client_request_id='bulk-protected')
    assert err.value.code == 'FIELD_READ_ONLY'
    assert [store.get_row(x['row_id']) for x in chosen] == before


def test_three_rows_with_protected_row_leave_every_row_unchanged(store):
    chosen = rows(store)
    rid = 'expense-demo-c3'
    chosen.append({'row_id': rid, 'revision': store.get_row(rid)['revision']})
    before = [store.get_row(x['row_id']) for x in chosen]
    store.conn.execute("INSERT INTO board_manual_overrides(row_id,field,event_id) VALUES (?, 'display_tab_id', '')", (rid,))
    store.conn.commit()
    with pytest.raises(SaveError) as err:
        store.save_expense_trips_atomic(rows=chosen, target='trip-demo-b', client_request_id='bulk-three-protected')
    assert err.value.code == 'FIELD_READ_ONLY'
    assert [store.get_row(x['row_id']) for x in chosen] == before


def test_failure_during_second_write_rolls_back_first(store, monkeypatch):
    chosen = rows(store)
    before = [store.get_row(x['row_id']) for x in chosen]
    original = store.save
    calls = []

    def failing_save(**kwargs):
        calls.append(kwargs['row_id'])
        if len(calls) == 2:
            raise RuntimeError('synthetic write failure')
        return original(**kwargs)

    monkeypatch.setattr(store, 'save', failing_save)
    with pytest.raises(RuntimeError):
        store.save_expense_trips_atomic(rows=chosen, target='trip-demo-b', client_request_id='bulk-failure')
    assert len(calls) == 2
    assert [store.get_row(x['row_id']) for x in chosen] == before
    assert not store.conn.execute("SELECT 1 FROM board_requests WHERE client_request_id=?", ('bulk:bulk-failure',)).fetchone()


def test_first_archive_and_restore_create_valid_embedded_audit_chain(tmp_path, monkeypatch):
    monkeypatch.setenv('WEBLEDGER_UNIFIED_DB', '1')
    store = LedgerStore(tmp_path / 'archive.sqlite')
    try:
        store.save_trip_meta(tab_id='trip-demo-b', expected_revision=1,
                             client_request_id='first-archive', archived=True)
        store.save_trip_meta(tab_id='trip-demo-b', expected_revision=2,
                             client_request_id='restore', archived=False)
        events = store.conn.execute(
            "SELECT action FROM decision_events WHERE stream_id=? ORDER BY sequence_no",
            ('trip-trip-demo-b',)).fetchall()
        assert [row[0] for row in events] == ['propose', 'correct']
        assert store.ledger.verify_chain()['ok']
    finally:
        store.close()
