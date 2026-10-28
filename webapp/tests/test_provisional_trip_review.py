import json
from unittest.mock import patch
from urllib.parse import urlsplit

import pytest

from app import trip_correction_review as corrections
from app.provisional_assignment import card_trip_candidates, rank_trip_candidates
from webapp.card_flow import CardFlow
from webapp.ledger_store import LedgerStore
from webapp import provisional_trip_review as review
from webapp.tests.test_card_flow import CARD


@pytest.fixture
def setup_review(tmp_path, monkeypatch):
    monkeypatch.setenv('WEBLEDGER_UNIFIED_DB', '1')
    monkeypatch.setenv('WEBLEDGER_CARD_FLOW', '1')
    board = LedgerStore(tmp_path / 'synthetic.sqlite', seed_demo=False)
    trip = board.create_trip(starts_on='2026-10-01', ends_on='2026-10-05',
                             destination='Synthetic trip', client_request_id='synthetic-trip')['tab_id']
    monkeypatch.setattr(CardFlow, 'trip_valid', lambda self, identity: identity == trip)
    flow = CardFlow(board)
    content = CARD.splitlines(keepends=True)[0] + b''.join(
        CARD.splitlines(keepends=True)[1].replace(b'A123', f'TEST{i:03}'.encode()) for i in range(23))
    batch = flow.pipeline.receive(content, 'synthetic.csv')['batch_id']
    board.conn.execute("UPDATE transactions SET item='food',classification_state='classified',"
                       "classification_source='inference',classification_basis='synthetic basis',"
                       "trip_id=?,display_tab_id=?", (trip, trip))
    rows = flow.pipeline.get_batch(batch)['rows']
    yield flow, trip, batch, rows
    board.close()


def confirm_two(flow, trip, rows):
    for index, row in enumerate(rows[:2]):
        flow.pipeline.save_decision(row['transaction_id'], row['revision'], item='food',
            trip_id=trip, display_tab_id=trip, trip_validator=flow.trip_valid,
            tab_validator=flow.tab_valid, request_id=f'synthetic-decision-{index}')
    return [row['transaction_id'] for row in rows[:2]]


def test_bounded_read_generation_and_source_identity_are_preserved(setup_review):
    flow, trip, batch, rows = setup_review
    before = flow.board.conn.execute('SELECT transaction_id,source_hash,amount_krw,revision FROM transactions').fetchall()
    page = review.read_page(flow, batch, state='provisional')
    assert page['total'] == 23 and len(page['items']) == 20 and page['has_more']
    assert all(row['decision']['trip_id'] == trip and row['decision']['status'] == 'AUTO_PROVISIONAL'
               for row in page['items'])
    assert 'source_hash' not in page['items'][0]
    following = review.read_page(flow, batch, offset=20, generation=page['generation'])
    assert len(following['items']) == 3 and not following['has_more']
    assert not set(row['transaction_id'] for row in page['items']) & set(row['transaction_id'] for row in following['items'])
    assert flow.board.conn.execute('SELECT transaction_id,source_hash,amount_krw,revision FROM transactions').fetchall() == before
    confirm_two(flow, trip, rows)
    with pytest.raises(ValueError, match='SOURCE_CHANGED'):
        review.read_page(flow, batch, offset=20, generation=page['generation'])


def test_no_get_assignment_and_manual_choice_survives_hold(setup_review):
    flow, trip, batch, rows = setup_review
    ids = confirm_two(flow, trip, rows)
    flow.board.conn.execute("UPDATE transactions SET trip_id='',display_tab_id='' WHERE transaction_id=?", (rows[2]['transaction_id'],))
    flow.board.conn.execute('INSERT INTO transaction_review_holds VALUES (?,?,?,?)',
                            (ids[0], rows[0]['source_hash'], 'evidence_pending', 'synthetic'))
    page = review.read_page(flow, batch)
    indexed = {row['transaction_id']: row for row in page['items']}
    if rows[2]['transaction_id'] not in indexed:
        indexed.update({row['transaction_id']: row for row in review.read_page(flow, batch, offset=20)['items']})
    assert indexed[ids[0]]['decision']['status'] == 'USER_CONFIRMED'
    assert indexed[ids[0]]['decision']['trip_id'] == trip
    assert indexed[ids[0]]['protected'] and not indexed[ids[0]]['can_propose']
    assert indexed[rows[2]['transaction_id']]['decision']['status'] == 'UNASSIGNED_NO_VALID_TRIP'
    assert flow.board.conn.execute('SELECT trip_id FROM transactions WHERE transaction_id=?',
                                   (rows[2]['transaction_id'],)).fetchone()[0] == ''


def test_pending_storage_approval_and_replay_do_not_reclassify_transactions(setup_review):
    flow, trip, batch, rows = setup_review
    store = flow.pipeline.store
    ids = confirm_two(flow, trip, rows)
    before = store.conn.execute('SELECT transaction_id,revision,item,trip_id,source_hash,amount_krw FROM transactions').fetchall()
    proposal = corrections.propose_from_current_decisions(store, batch, ids)
    assert corrections.propose_from_current_decisions(store, batch, ids) == proposal
    assert len(corrections.pending_proposals(store, batch)['items']) == 1
    assert store.conn.execute('SELECT COUNT(*) FROM cost_classification_rules').fetchone()[0] == 0
    result = corrections.approve_stored_proposal(store, batch, proposal['id'], approved_by='synthetic-owner',
                                                 trips=review.authoritative_trips(flow))
    assert result['status'] == 'APPROVED'
    assert corrections.approve_stored_proposal(store, batch, proposal['id'], approved_by='synthetic-owner',
                                               trips=review.authoritative_trips(flow))['status'] == 'ALREADY_APPROVED'
    assert not corrections.pending_proposals(store, batch)['items']
    assert store.conn.execute('SELECT COUNT(*) FROM cost_classification_rules').fetchone()[0] == 2
    assert store.conn.execute('SELECT transaction_id,revision,item,trip_id,source_hash,amount_krw FROM transactions').fetchall() == before
    with pytest.raises(ValueError, match='PROPOSAL_BATCH_MISMATCH'):
        corrections.approve_stored_proposal(store, 'wrong-batch', proposal['id'], approved_by='synthetic-owner', trips=[])


def test_stale_correction_and_pending_audit_failure_roll_back(setup_review):
    flow, trip, batch, rows = setup_review
    store = flow.pipeline.store
    ids = confirm_two(flow, trip, rows)
    original = store.log_change
    def fail_after_append(*args):
        original(*args)
        raise RuntimeError('synthetic audit failure')
    with patch.object(store, 'log_change', side_effect=fail_after_append), pytest.raises(RuntimeError):
        corrections.propose_from_current_decisions(store, batch, ids)
    assert not corrections.pending_proposals(store, batch)['items']
    proposal = corrections.propose_from_current_decisions(store, batch, ids)
    store.conn.execute('UPDATE transactions SET revision=revision+1 WHERE transaction_id=?', (ids[0],))
    with pytest.raises(ValueError, match='CORRECTION_STALE'):
        corrections.approve_stored_proposal(store, batch, proposal['id'], approved_by='synthetic-owner',
                                            trips=review.authoritative_trips(flow))
    assert store.conn.execute('SELECT COUNT(*) FROM cost_classification_rules').fetchone()[0] == 0


def test_actual_dispatch_owner_csrf_and_explicit_approval_boundaries(setup_review):
    flow, trip, batch, rows = setup_review
    ids = confirm_two(flow, trip, rows)
    class Handler:
        headers = {'X-CSRF-Token': 'synthetic-csrf'}
        def _send_json(self, body, status=200):
            self.result = status, body
    handler = Handler()
    path = urlsplit(f'/api/imports/{batch}/trip-review/proposals')
    args = dict(board=flow.board, query={}, raw=json.dumps({'action':'propose','transaction_ids':ids}).encode(), csrf='synthetic-csrf')
    with patch('webapp.ledger_board.current_role', return_value='viewer'), patch.object(review, 'authoritative_trips') as authority:
        assert review.dispatch(handler, path, **args)
        assert handler.result[0] == 403
        authority.assert_not_called()
    with patch('webapp.ledger_board.current_role', return_value='owner'):
        review.dispatch(handler, path, **dict(args, csrf=''))
        assert handler.result == (403, {'code':'CSRF_REQUIRED'})
        review.dispatch(handler, path, **args)
        assert handler.result[0] == 200
        proposal = handler.result[1]
        review.dispatch(handler, path, **dict(args, raw=json.dumps({'action':'approve','proposal_id':proposal['id']}).encode()))
        assert handler.result[0] == 422
        assert flow.board.conn.execute('SELECT COUNT(*) FROM cost_classification_rules').fetchone()[0] == 0
        review.dispatch(handler, path, **dict(args, raw=json.dumps({'action':'approve','proposal_id':proposal['id'],'confirmed':True,
            'proposal': {'scope': {'trip_id':'forged'}}}).encode()))
        assert handler.result[0] == 200


def test_equal_semantic_card_candidates_do_not_use_id_as_tiebreaker():
    trips = [dict(trip_id=identity, starts_on='2026-10-01', ends_on='2026-10-05') for identity in ('A', 'B')]
    candidates = card_trip_candidates({'merchant':'synthetic', 'approval_date':'2026-10-03'}, trips)
    assert rank_trip_candidates(candidates, trips=trips)['status'] == 'CONFLICT_REVIEW'
