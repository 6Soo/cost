"""A person's board correction reaches the ledger row (M3 §11.5 manual-correction preservation).

`board_manual_overrides` records one field at a time; `review_decisions` records item, description and tab
together. `app.ledger.preview` used to read only the second, so a board-only correction was booked with the
automatic values while the screen kept the person's. These pin the manual value winning, per field.
"""
import json

import pytest

from app import ledger
from app.db import Store, StoreError
from tests.card_pipeline.test_batch_concurrency import batch


def _board_values(store, tid):
    row = store.conn.execute('SELECT payload_json FROM board_rows WHERE row_id=?',
                             ('card-' + tid,)).fetchone()
    return json.loads(row[0]) if row else {}


def _override(store, tid, field, event='manual'):
    store.conn.execute('INSERT OR REPLACE INTO board_manual_overrides(row_id, field, event_id)'
                       ' VALUES (?,?,?)', ('card-' + tid, field, event))
    store.conn.commit()


def _write_board(store, tid, **values):
    """Persist the person's value where the screen reads it, as `LedgerStore.save` does."""
    payload = _board_values(store, tid)
    payload.update(values)
    payload['revision'] = payload.get('revision', 1) + 1
    store.conn.execute('UPDATE board_rows SET payload_json=?, display_tab_id=?, revision=revision+1'
                       ' WHERE row_id=?',
                       (json.dumps(payload, ensure_ascii=False, sort_keys=True),
                        payload.get('display_tab_id'), 'card-' + tid))
    store.conn.execute('INSERT INTO board_revisions(row_id,revision,prev_json,new_json,event_id,'
                       'change_mode,actor,created_at,client_request_id) VALUES (?,?,?,?,?,?,?,?,?)',
                       ('card-' + tid, payload['revision'], '{}', json.dumps(payload),
                        'manual', 'exception', 'owner', '2026-11-19T00:00:00Z', 'synthetic-' + tid))
    store.conn.commit()


@pytest.fixture
def recorded(batch):
    """One classified card row with a board row (as `CardFlow.project` writes it), not yet in the ledger."""
    path, board, decisions = batch
    store = Store.open(str(path))
    tid = decisions[0]['transaction_id']
    board.conn.execute("UPDATE transactions SET item='숙박비', description='자동내용',"
                       " display_tab_id='trip-syn', trip_id='trip-syn',"
                       " classification_state='classified', classification_source='inference'"
                       " WHERE transaction_id=?", (tid,))
    payload = dict(row_id='card-' + tid, row_kind='expense', revision=1,
                   display_tab_id='trip-syn', item='숙박비', description='자동내용',
                   source_event_id=tid, confirmed_by='automatic')
    board.conn.execute("INSERT INTO board_rows(row_id,row_kind,display_tab_id,revision,payload_json)"
                       " VALUES (?,?,?,1,?)", ('card-' + tid, 'expense', 'trip-syn',
                                               json.dumps(payload, ensure_ascii=False, sort_keys=True)))
    board.conn.commit()
    yield store, tid
    store.close()


def test_board_item_and_attribution_are_booked_not_the_automatic_ones(recorded):
    store, tid = recorded
    _write_board(store, tid, item='수동항목', display_tab_id='trip-other', description='수동설명')
    _override(store, tid, 'item')
    _override(store, tid, 'display_tab_id')
    _override(store, tid, 'description')

    preview = ledger.preview(store, _batch_id(store),
                             trip_validator=lambda tab: tab in ('trip-syn', 'trip-other'),
                             tab_validator=lambda tab: tab in ('trip-syn', 'trip-other'))
    row, = [r for r in preview['rows'] if r['transaction_id'] == tid]
    assert (row['item'], row['description'], row['display_tab_id']) == (
        '수동항목', '수동설명', 'trip-other'), row

    ledger.commit(store, _batch_id(store), preview['digest'], 'synthetic-honours-manual',
                  trip_validator=lambda tab: tab in ('trip-syn', 'trip-other'),
                  tab_validator=lambda tab: tab in ('trip-syn', 'trip-other'))
    booked = store.conn.execute('SELECT item, description, display_tab_id, trip_id'
                                ' FROM ledger_entries WHERE transaction_id=?', (tid,)).fetchone()
    assert booked[:3] == ('수동항목', '수동설명', 'trip-other'), (
        'a person\'s board correction must reach the ledger row: %r' % (booked,))


def test_override_of_one_field_does_not_carry_a_other_field_from_the_payload(recorded):
    """Only the field a person corrected is merged; the transaction's own value stays for the rest."""
    store, tid = recorded
    _write_board(store, tid, item='수동항목')
    _override(store, tid, 'item')

    preview = ledger.preview(store, _batch_id(store),
                             trip_validator=lambda tab: tab == 'trip-syn',
                             tab_validator=lambda tab: tab == 'trip-syn')
    row, = [r for r in preview['rows'] if r['transaction_id'] == tid]
    assert row['item'] == '수동항목'
    assert row['display_tab_id'] == 'trip-syn', 'the automatic attribution is kept when nobody corrected it'


def test_legacy_override_table_without_a_field_column_is_not_read_as_a_field_correction(batch):
    """`app/manual_overrides` degrades the same way: no `field` means no field can be named."""
    path, board, decisions = batch
    store = Store.open(str(path))
    try:
        tid = decisions[0]['transaction_id']
        board.conn.execute("UPDATE transactions SET item='숙박비', display_tab_id='trip-syn',"
                           " trip_id='trip-syn', classification_state='classified',"
                           " classification_source='inference' WHERE transaction_id=?", (tid,))
        board.conn.commit()
        board.conn.execute('DROP TABLE board_manual_overrides')
        board.conn.execute('CREATE TABLE board_manual_overrides (row_id TEXT NOT NULL)')
        board.conn.execute('INSERT INTO board_manual_overrides VALUES (?)', ('card-' + tid,))
        board.conn.commit()
        preview = ledger.preview(store, _batch_id(store), trip_validator=lambda tab: tab == 'trip-syn',
                                 tab_validator=lambda tab: tab == 'trip-syn')
        row, = [r for r in preview['rows'] if r['transaction_id'] == tid]
        assert row['item'] == '숙박비', 'an unnamed override must not blank or invent a value'
    finally:
        store.close()


def _batch_id(store):
    return store.conn.execute('SELECT batch_id FROM import_batch_rows LIMIT 1').fetchone()[0]
