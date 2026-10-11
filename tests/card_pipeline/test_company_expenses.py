import pytest

from app import company_expenses, ledger
from app.db import Store, StoreError
from app.google_tsv_adapter import tsv_for_tab
from tests.card_pipeline.test_batch_concurrency import batch


def preview(store, batch_id):
    return ledger.preview(store, batch_id, tab_validator=lambda tab: tab == 'trip-syn')


def set_state(store, row, **changes):
    args = dict(transaction_id=row['transaction_id'], expected_revision=row['revision'],
                expected_exclusion_revision=0, excluded=True, confirmed=True,
                request_id='exclude-once', note='회사 경비 아님')
    args.update(changes)
    return company_expenses.set_excluded(store, **args)


def test_exclusion_and_undo_preserve_source_and_decisions_and_block_copy(batch):
    path, board, decisions = batch
    store = Store.open(str(path))
    row = decisions[0]
    store.conn.execute("UPDATE transactions SET item='식비', classification_state='classified', display_tab_id='trip-syn'")
    before = store.conn.execute('SELECT * FROM transactions').fetchall()
    batch_id = store.conn.execute('SELECT batch_id FROM transactions').fetchone()[0]
    old_preview = preview(store, batch_id)
    try:
        first = set_state(store, row)
        assert set_state(store, row) == first
        excluded = preview(store, batch_id)
        assert excluded['ready'] == 0
        assert excluded['excluded'] == 1
        assert excluded['digest'] != old_preview['digest']
        assert tsv_for_tab(excluded['rows'], 'trip-syn')['row_count'] == 0
        assert store.conn.execute('SELECT * FROM transactions').fetchall() == before
        assert store.conn.execute('SELECT COUNT(*) FROM review_decisions').fetchone()[0] == 0
        assert store.conn.execute('SELECT COUNT(*) FROM ledger_entries').fetchone()[0] == 0
        undone = set_state(store, row, excluded=False, expected_exclusion_revision=1, request_id='undo-once')
        assert undone['exclusion_revision'] == 2
        assert preview(store, batch_id)['ready'] == 1
        assert tsv_for_tab(preview(store, batch_id)['rows'], 'trip-syn')['row_count'] == 1
        assert len([e for e in store.changes(row['transaction_id']) if e['kind'] == 'transaction.company_exclusion']) == 2
    finally:
        store.close()


@pytest.mark.parametrize('changes,code', [({'confirmed': False}, 'EXCLUSION_CONFIRMATION_REQUIRED'),
                                        ({'expected_revision': 999}, 'REVISION_CONFLICT'),
                                        ({'expected_exclusion_revision': 999}, 'REVISION_CONFLICT')])
def test_invalid_approval_writes_nothing(batch, changes, code):
    path, board, decisions = batch
    store = Store.open(str(path))
    try:
        with pytest.raises(StoreError) as error:
            set_state(store, decisions[0], **changes)
        assert error.value.code == code
        assert company_expenses.states(store.conn) == {}
    finally:
        store.close()


def test_stale_undo_and_request_id_reuse_are_refused(batch):
    path, board, decisions = batch
    store = Store.open(str(path))
    try:
        set_state(store, decisions[0])
        with pytest.raises(StoreError) as error:
            set_state(store, decisions[0], excluded=False)
        assert error.value.code == 'REQUEST_ID_REUSED'
        with pytest.raises(StoreError) as error:
            set_state(store, decisions[0], excluded=False, request_id='stale-undo')
        assert error.value.code == 'REVISION_CONFLICT'
    finally:
        store.close()


def test_user_confirmed_row_is_not_overwritten(batch):
    path, board, decisions = batch
    store = Store.open(str(path))
    store.conn.execute('UPDATE transactions SET user_confirmed=1')
    try:
        with pytest.raises(StoreError) as error:
            set_state(store, decisions[0])
        assert error.value.code == 'EXCLUSION_PROTECTED'
        assert company_expenses.states(store.conn) == {}
    finally:
        store.close()


def test_source_change_stays_blocked_and_cannot_be_silently_restored(batch):
    path, board, decisions = batch
    store = Store.open(str(path))
    try:
        set_state(store, decisions[0])
        store.conn.execute("UPDATE transactions SET source_hash='changed-source'")
        batch_id = store.conn.execute('SELECT batch_id FROM transactions').fetchone()[0]
        assert preview(store, batch_id)['rows'][0]['blocked'] == 'exclusion_source_changed'
        with pytest.raises(StoreError) as error:
            set_state(store, decisions[0], excluded=False, expected_exclusion_revision=1, request_id='changed-undo')
        assert error.value.code == 'SOURCE_CONFLICT'
    finally:
        store.close()


def test_a_later_classification_does_not_prevent_undo_or_get_overwritten(batch):
    path, board, decisions = batch
    store = Store.open(str(path))
    try:
        set_state(store, decisions[0])
        store.conn.execute("UPDATE transactions SET user_confirmed=1, item='식비', revision=2")
        before = store.conn.execute('SELECT * FROM transactions').fetchall()
        set_state(store, decisions[0], excluded=False, expected_revision=2,
                  expected_exclusion_revision=1, request_id='confirmed-undo')
        assert store.conn.execute('SELECT * FROM transactions').fetchall() == before
    finally:
        store.close()


def test_audit_database_failure_rolls_back_exclusion_and_retry_works(batch):
    import sqlite3
    path, board, decisions = batch
    store = Store.open(str(path))
    try:
        store.conn.execute("CREATE TRIGGER fail_exclusion BEFORE INSERT ON change_log "
                           "WHEN NEW.kind='transaction.company_exclusion' BEGIN SELECT RAISE(ABORT, 'synthetic'); END")
        with pytest.raises(sqlite3.IntegrityError):
            set_state(store, decisions[0])
        assert company_expenses.states(store.conn) == {}
        assert store.conn.execute("SELECT COUNT(*) FROM requests WHERE scope='company_exclusion'").fetchone()[0] == 0
        store.conn.execute('DROP TRIGGER fail_exclusion')
        assert set_state(store, decisions[0])['excluded'] is True
    finally:
        store.close()


def test_booked_transaction_is_protected(batch):
    path, board, decisions = batch
    store = Store.open(str(path))
    try:
        store.conn.execute("UPDATE transactions SET item='식비', classification_state='classified'")
        batch_id = store.conn.execute('SELECT batch_id FROM transactions').fetchone()[0]
        p = ledger.preview(store, batch_id)
        ledger.commit(store, batch_id, p['digest'], request_id='book-before-exclusion')
        before = store.conn.execute('SELECT * FROM ledger_entries').fetchall()
        with pytest.raises(StoreError) as error:
            set_state(store, decisions[0])
        assert error.value.code == 'EXCLUSION_PROTECTED'
        assert store.conn.execute('SELECT * FROM ledger_entries').fetchall() == before
    finally:
        store.close()


def test_reading_legacy_schema_does_not_migrate_it():
    import sqlite3
    conn = sqlite3.connect(':memory:')
    try:
        assert company_expenses.states(conn) == {}
        assert conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall() == []
    finally:
        conn.close()
