"""Integration coverage for company-expense exclusion and ledger APIs."""

import sqlite3

import pytest

from app import company_expenses, ledger
from app.db import Store, StoreError
from app.google_tsv_adapter import tsv_for_tab
from app.review import save_decision
from tests.card_pipeline.test_batch_concurrency import batch


TAB = "trip-syn"
TAB_OK = lambda tab: tab == TAB
TRIP_OK = lambda _trip: True


def _preview(store, batch_id):
    return ledger.preview(store, batch_id, tab_validator=TAB_OK,
                          trip_validator=TRIP_OK)


def _batch_row(store, batch_id):
    row = store.conn.execute(
        "SELECT t.transaction_id, t.revision, t.source_hash, t.raw_row_json, "
        "t.amount_krw FROM transactions t JOIN import_batch_rows b "
        "ON b.transaction_id=t.transaction_id WHERE b.batch_id=?", (batch_id,)
    ).fetchone()
    return dict(zip(("transaction_id", "revision", "source_hash", "raw_row_json", "amount_krw"), row))


def _exclude(store, row, *, excluded, revision, request_id):
    return company_expenses.set_excluded(
        store, transaction_id=row["transaction_id"],
        expected_revision=row["revision"], expected_exclusion_revision=revision,
        excluded=excluded, confirmed=True, request_id=request_id,
        note="합성 통합 테스트")


def test_excluded_row_stays_out_of_preview_and_tsv_then_undo_books_user_decision(batch):
    path, board, _decisions = batch
    store = Store.open(str(path))
    try:
        batch_id = store.conn.execute("SELECT batch_id FROM import_batches").fetchone()[0]
        original = _batch_row(store, batch_id)
        store.conn.execute("UPDATE transactions SET item='meal', classification_state='classified', display_tab_id=?", (TAB,))
        before_exclusion = _preview(store, batch_id)
        assert before_exclusion['ready'] == 1
        _exclude(store, original, excluded=True, revision=0, request_id="exclude")

        with pytest.raises(StoreError) as stale:
            ledger.commit(store, batch_id, before_exclusion['digest'], 'stale-before-exclusion',
                          tab_validator=TAB_OK, trip_validator=TRIP_OK)
        assert stale.value.code == 'PREVIEW_STALE'
        assert store.conn.execute("SELECT COUNT(*) FROM ledger_entries").fetchone()[0] == 0

        hidden = _preview(store, batch_id)
        assert hidden["ready"] == 0
        assert hidden["excluded"] == 1
        assert tsv_for_tab(hidden["rows"], TAB)["row_count"] == 0
        excluded_commit = ledger.commit(
            store, batch_id, hidden["digest"], "commit-while-excluded",
            tab_validator=TAB_OK, trip_validator=TRIP_OK)
        assert excluded_commit["applied"] == 0
        assert store.conn.execute("SELECT COUNT(*) FROM ledger_entries").fetchone()[0] == 0

        # A real user decision made while the row is excluded must survive undo.
        save_decision(store, original["transaction_id"], original["revision"],
                      item="식비", description="합성 회의 식사", display_tab_id=TAB,
                      tab_validator=TAB_OK, request_id="decision")
        decided = _batch_row(store, batch_id)
        assert decided["transaction_id"] == original["transaction_id"]
        assert decided["source_hash"] == original["source_hash"]
        assert decided["raw_row_json"] == original["raw_row_json"]
        assert decided["amount_krw"] == original["amount_krw"]
        decision_history = store.conn.execute(
            "SELECT transaction_id, revision, item, description, display_tab_id "
            "FROM review_decisions").fetchall()

        _exclude(store, decided, excluded=False, revision=1, request_id="undo")
        ready = _preview(store, batch_id)
        assert ready["ready"] == 1
        assert tsv_for_tab(ready["rows"], TAB)["row_count"] == 1
        result = ledger.commit(store, batch_id, ready["digest"], "commit-after-undo",
                               tab_validator=TAB_OK, trip_validator=TRIP_OK)
        assert result["applied"] == 1
        assert ledger.commit(store, batch_id, ready['digest'], 'commit-after-undo',
                             tab_validator=TAB_OK, trip_validator=TRIP_OK) == result
        assert store.conn.execute(
            "SELECT transaction_id, amount_krw FROM ledger_entries"
        ).fetchone() == (original["transaction_id"], original["amount_krw"])
        assert store.conn.execute(
            "SELECT item, description, display_tab_id FROM transactions WHERE transaction_id=?",
            (original["transaction_id"],)).fetchone() == ("식비", "합성 회의 식사", TAB)
        assert store.conn.execute(
            "SELECT transaction_id, revision, item, description, display_tab_id "
            "FROM review_decisions").fetchall() == decision_history
    finally:
        store.close()


def test_commit_rejects_preview_staled_by_a_later_user_decision(batch):
    path, board, _decisions = batch
    store = Store.open(str(path))
    try:
        batch_id = store.conn.execute("SELECT batch_id FROM import_batches").fetchone()[0]
        row = _batch_row(store, batch_id)
        save_decision(store, row["transaction_id"], row["revision"], item="식비",
                      display_tab_id=TAB, tab_validator=TAB_OK, request_id="decision-one")
        current = _batch_row(store, batch_id)
        previewed = _preview(store, batch_id)
        save_decision(store, current["transaction_id"], current["revision"], item="교통비",
                      display_tab_id=TAB, tab_validator=TAB_OK, request_id="decision-two")

        with pytest.raises(StoreError) as caught:
            ledger.commit(store, batch_id, previewed["digest"], "stale-commit",
                          tab_validator=TAB_OK, trip_validator=TRIP_OK)
        assert caught.value.code == "PREVIEW_STALE"
        assert store.conn.execute("SELECT COUNT(*) FROM ledger_entries").fetchone()[0] == 0
        assert store.conn.execute(
            "SELECT item FROM transactions WHERE transaction_id=?", (row["transaction_id"],)
        ).fetchone()[0] == "교통비"
    finally:
        store.close()


def test_commit_database_failure_rolls_back_and_same_request_can_retry(batch):
    path, board, _decisions = batch
    store = Store.open(str(path))
    try:
        batch_id = store.conn.execute("SELECT batch_id FROM import_batches").fetchone()[0]
        row = _batch_row(store, batch_id)
        save_decision(store, row["transaction_id"], row["revision"], item="식비",
                      display_tab_id=TAB, tab_validator=TAB_OK, request_id="decision")
        ready = _preview(store, batch_id)
        store.conn.execute(
            "CREATE TRIGGER fail_ledger_insert BEFORE INSERT ON ledger_entries "
            "BEGIN SELECT RAISE(ABORT, 'synthetic ledger failure'); END")

        with pytest.raises(sqlite3.IntegrityError, match="synthetic ledger failure"):
            ledger.commit(store, batch_id, ready["digest"], "retryable-commit",
                          tab_validator=TAB_OK, trip_validator=TRIP_OK)
        assert store.conn.execute("SELECT COUNT(*) FROM ledger_entries").fetchone()[0] == 0
        assert store.conn.execute(
            "SELECT COUNT(*) FROM requests WHERE request_id='retryable-commit'"
        ).fetchone()[0] == 0
        after_failure = _batch_row(store, batch_id)
        assert after_failure["transaction_id"] == row["transaction_id"]
        assert after_failure["source_hash"] == row["source_hash"]
        assert after_failure["raw_row_json"] == row["raw_row_json"]
        assert after_failure["amount_krw"] == row["amount_krw"]

        store.conn.execute("DROP TRIGGER fail_ledger_insert")
        done = ledger.commit(store, batch_id, ready["digest"], "retryable-commit",
                             tab_validator=TAB_OK, trip_validator=TRIP_OK)
        assert done["applied"] == 1
        assert ledger.commit(store, batch_id, ready["digest"], "retryable-commit",
                             tab_validator=TAB_OK, trip_validator=TRIP_OK) == done
        assert store.conn.execute("SELECT COUNT(*) FROM ledger_entries").fetchone()[0] == 1
    finally:
        store.close()


def test_linked_refund_group_cannot_be_excluded():
    from tests.card_pipeline.test_partial_refund import build

    pipe, batch_id = build()
    try:
        rows = pipe.get_batch(batch_id)["rows"]
        from app.partial_refund import refund_links
        row_ids = [row["transaction_id"] for row in rows]
        assert len(refund_links(pipe.store.conn, row_ids)) == 1
        for row in rows:
            with pytest.raises(StoreError) as caught:
                company_expenses.set_excluded(
                    pipe.store, transaction_id=row["transaction_id"],
                    expected_revision=row["revision"], expected_exclusion_revision=0,
                    excluded=True, confirmed=True,
                    request_id="exclude-refund-" + row["approval_number"])
            assert caught.value.code == "EXCLUSION_PROTECTED"
        assert company_expenses.states(pipe.store.conn) == {}
        assert pipe.store.conn.execute("SELECT COUNT(*) FROM ledger_entries").fetchone()[0] == 0
        assert pipe.store.conn.execute(
            "SELECT approval_number, amount_krw FROM transactions ORDER BY approval_number"
        ).fetchall() == [("100", 1000000), ("200", -700000)]
        assert pipe.store.conn.execute(
            "SELECT COUNT(*) FROM review_decisions").fetchone()[0] == 0
    finally:
        pipe.store.close()


def test_refund_imported_after_exclusion_cannot_book_negative_cost_alone():
    from tests.card_pipeline.test_partial_refund import HEADER, OK, build

    pipe, original_batch = build(refunds=())
    try:
        original = pipe.get_batch(original_batch)['rows'][0]
        before = pipe.store.conn.execute('SELECT * FROM transactions').fetchall()
        excluded = _exclude(pipe.store, original, excluded=True, revision=0, request_id='exclude-before-refund')
        header = HEADER.rstrip('\n') + ',Original Authorization\n'
        refund = ('국민,1234,domestic,cancellation,합성항공,300000,,,300000,'
                  '2026-10-03,2026-10-04,C200,취소,취소,100\n')
        received = pipe.receive((header + refund).encode('utf-8'), 'late-refund.csv')
        batch_id = received['batch_id']
        pipe.classify_batch(batch_id)
        previewed = pipe.preview(batch_id, tab_validator=OK, trip_validator=OK)
        assert previewed['ready'] == 0
        assert previewed['rows'][0]['amount_krw'] == -300000
        assert previewed['rows'][0]['blocked'] == 'refund_original_missing'
        assert tsv_for_tab(previewed['rows'], 'unclassified')['row_count'] == 0
        assert pipe.commit(batch_id, previewed['digest'], 'late-refund-commit',
                           tab_validator=OK, trip_validator=OK)['applied'] == 0
        assert _exclude(pipe.store, original, excluded=True, revision=0, request_id='exclude-before-refund') == excluded
        with pytest.raises(StoreError) as protected:
            _exclude(pipe.store, original, excluded=False, revision=1, request_id='undo-after-refund')
        assert protected.value.code == 'EXCLUSION_PROTECTED'
        assert pipe.store.conn.execute('SELECT * FROM transactions WHERE transaction_id=?',
                                       (original['transaction_id'],)).fetchall() == before
        assert pipe.store.conn.execute('SELECT COUNT(*) FROM ledger_entries').fetchone()[0] == 0
    finally:
        pipe.store.close()
