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
    page = review.read_page(flow, batch, state='automatic')
    assert page['total'] == 23 and len(page['items']) == 20 and page['has_more']
    assert all(row['decision']['trip_id'] == trip and row['decision']['status'] == 'CLASSIFIED'
               for row in page['items'])
    assert all(row['decision']['assignment_source'] == 'automatic' for row in page['items'])
    assert not any(row['decided'] for row in flow.pipeline.get_batch(batch)['rows'])
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
    flow.board.conn.execute("UPDATE transactions SET classification_state='needs_review',item='' WHERE transaction_id=?",
                           (rows[3]['transaction_id'],))
    flow.board.conn.execute('INSERT INTO transaction_review_holds VALUES (?,?,?,?)',
                            (ids[0], rows[0]['source_hash'], 'evidence_pending', 'synthetic'))
    page = review.read_page(flow, batch)
    indexed = {row['transaction_id']: row for row in page['items']}
    if rows[2]['transaction_id'] not in indexed:
        indexed.update({row['transaction_id']: row for row in review.read_page(flow, batch, offset=20)['items']})
    if rows[3]['transaction_id'] not in indexed:
        indexed.update({row['transaction_id']: row for row in review.read_page(flow, batch, offset=20)['items']})
    assert indexed[ids[0]]['decision']['status'] == 'CLASSIFIED'
    assert indexed[ids[0]]['decision']['assignment_source'] == 'manual'
    assert indexed[ids[0]]['decision']['trip_id'] == trip
    assert indexed[ids[0]]['protected'] and not indexed[ids[0]]['can_propose']
    assert indexed[ids[0]]['decision']['protection_reason']
    assert indexed[rows[2]['transaction_id']]['decision']['status'] == 'UNASSIGNED_NO_VALID_TRIP'
    assert indexed[rows[3]['transaction_id']]['decision']['status'] == 'CONFLICT_REVIEW'
    assert flow.board.conn.execute('SELECT trip_id FROM transactions WHERE transaction_id=?',
                                   (rows[2]['transaction_id'],)).fetchone()[0] == ''


def test_empty_manual_trip_is_not_presented_as_intentional_unassigned(setup_review):
    flow, trip, batch, rows = setup_review
    flow.board.conn.execute(
        "UPDATE transactions SET classification_source='user_decision', trip_id='', display_tab_id='' "
        "WHERE transaction_id=?", (rows[2]['transaction_id'],))

    page = review.read_page(flow, batch)
    row = next(item for item in page['items'] if item['transaction_id'] == rows[2]['transaction_id'])

    assert row['decision']['status'] == 'UNASSIGNED_NO_VALID_TRIP'
    assert row['decision']['assignment_source'] != 'manual'


def test_refund_bucket_and_financial_hold_keep_classification_complete(setup_review, monkeypatch):
    flow, trip, batch, rows = setup_review
    refund_id = rows[2]['transaction_id']
    held_id = rows[3]['transaction_id']
    flow.board.conn.execute(
        "UPDATE transactions SET display_tab_id='refunds', trip_id='', classification_state='classified', item='취소·환불' "
        "WHERE transaction_id=?", (refund_id,))
    flow.board.conn.execute(
        "UPDATE transactions SET trip_id=?, display_tab_id=?, classification_state='classified', item='교통비' "
        "WHERE transaction_id=?", (trip, trip, held_id))
    monkeypatch.setattr(flow, 'ota_group_holds', lambda: {held_id})

    page = review.read_page(flow, batch)
    indexed = {item['transaction_id']: item for item in page['items']}
    if held_id not in indexed:
        indexed.update({item['transaction_id']: item
                        for item in review.read_page(flow, batch, offset=20)['items']})

    refund = indexed[refund_id]['decision']
    held = indexed[held_id]['decision']
    assert refund['status'] == 'CLASSIFIED' and refund['trip_id'] == ''
    assert held['status'] == 'CLASSIFIED' and held['financial_hold']
    assert indexed[held_id]['protected']
    assert refund_id not in {item['transaction_id'] for item in review.read_page(flow, batch, state='unassigned')['items']}


def test_inferred_trip_with_manual_category_keeps_automatic_trip_source(setup_review):
    flow, trip, batch, rows = setup_review
    identity = rows[2]['transaction_id']
    flow.board.conn.execute(
        "UPDATE transactions SET classification_source='user_decision',"
        "classification_basis='AUTO_TRIP_INFERRED synthetic' WHERE transaction_id=?", (identity,))
    automatic = review.read_page(flow, batch, state='automatic')
    items = automatic['items'] + review.read_page(flow, batch, state='automatic', offset=20)['items']
    row = next(item for item in items if item['transaction_id'] == identity)
    assert row['decision']['assignment_source'] == 'automatic'
    assert not row['can_propose']
    assert identity not in {item['transaction_id'] for item in review.read_page(flow, batch, state='manual')['items']}


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
    trips[1]['archived'] = True
    assert rank_trip_candidates(card_trip_candidates({'approval_date':'2026-10-03'}, trips),
                                trips=trips)['trip_id'] == 'A'


def test_owner_review_measurement_failure_rolls_back_decision_and_audit(setup_review):
    flow, trip, batch, rows = setup_review
    store = flow.pipeline.store
    row = rows[0]
    original = store.log_change
    def fail(kind, *args):
        original(kind, *args)
        if kind == 'trip_assignment.reviewed':
            raise RuntimeError('synthetic measurement failure')
    before = store.conn.execute('SELECT revision,classification_source FROM transactions WHERE transaction_id=?',
                                 (row['transaction_id'],)).fetchone()
    with patch.object(store, 'log_change', side_effect=fail), pytest.raises(RuntimeError):
        flow.pipeline.save_decision(row['transaction_id'], row['revision'], item='food', trip_id=trip,
            trip_validator=flow.trip_valid, request_id='atomic-measurement')
    assert store.conn.execute('SELECT revision,classification_source FROM transactions WHERE transaction_id=?',
                               (row['transaction_id'],)).fetchone() == before
    assert store.conn.execute("SELECT COUNT(*) FROM change_log WHERE kind='trip_assignment.reviewed'").fetchone()[0] == 0
    assert store.conn.execute('SELECT COUNT(*) FROM review_decisions').fetchone()[0] == 0


def test_owner_hold_replay_and_original_refund_protection(setup_review):
    flow, trip, batch, rows = setup_review
    store = flow.pipeline.store
    row = rows[0]
    args = dict(transaction_id=row['transaction_id'], revision=row['revision'], request_id='synthetic-hold-request')
    before = store.conn.execute('SELECT amount_krw,source_hash,trip_id FROM transactions WHERE transaction_id=?',
                                (row['transaction_id'],)).fetchone()
    result = corrections.hold_for_review(store, batch, **args)
    assert result['status'] == 'HELD'
    assert corrections.hold_for_review(store, batch, **args) == result
    assert store.conn.execute("SELECT COUNT(*) FROM change_log WHERE kind='trip_review.held'").fetchone()[0] == 1
    assert store.conn.execute('SELECT amount_krw,source_hash,trip_id FROM transactions WHERE transaction_id=?',
                               (row['transaction_id'],)).fetchone() == before
    with pytest.raises(ValueError, match='CORRECTION_STALE'):
        corrections.hold_for_review(store, batch, **dict(args, request_id='another-hold-request'))
    original, refund = rows[1:3]
    approval = store.conn.execute('SELECT approval_number FROM transactions WHERE transaction_id=?',
                                  (original['transaction_id'],)).fetchone()[0]
    store.conn.execute("UPDATE transactions SET transaction_direction='cancellation',original_approval_number=? "
                       "WHERE transaction_id=?", (approval, refund['transaction_id']))
    with pytest.raises(ValueError, match='CORRECTION_STALE'):
        corrections.hold_for_review(store, batch, transaction_id=original['transaction_id'],
                                    revision=original['revision'], request_id='original-refund-hold')


def test_financial_snapshot_holds_cannot_be_bypassed_by_forged_proposal_selection(setup_review):
    flow, trip, batch, rows = setup_review
    ids = confirm_two(flow, trip, rows)
    store = flow.pipeline.store
    with pytest.raises(ValueError, match='PROTECTED'):
        corrections.propose_from_current_decisions(store, batch, ids, protected_transaction_ids=[ids[0]])
    proposal = corrections.propose_from_current_decisions(store, batch, ids)
    with pytest.raises(ValueError, match='PROTECTED'):
        corrections.approve_stored_proposal(store, batch, proposal['id'], approved_by='synthetic-owner',
            trips=review.authoritative_trips(flow), protected_transaction_ids=[ids[0]])
    assert store.conn.execute('SELECT COUNT(*) FROM cost_classification_rules').fetchone()[0] == 0


def test_worker_ota_decision_is_sanitized_and_never_changes_payment_identity(setup_review):
    from types import SimpleNamespace
    from copy import deepcopy
    from webapp import ota_payment_review as ota
    flow, trip, batch, rows = setup_review
    event = {'ota_event_id':'synthetic-ota', 'provider':'agoda', 'verified_portal_snapshot':True,
             'reservation_status':'confirmed', 'event_type':'charge', 'payment_status':'unverified',
             'service_period':{'starts_on':'2026-10-02','ends_on':'2026-10-04'}}
    original = deepcopy(event)
    decisions = ota._provisional_trip_decisions(SimpleNamespace(board=flow.board), [event], [], [])
    assert decisions['synthetic-ota']['trip_id'] == trip
    assert decisions['synthetic-ota']['status'] == 'CLASSIFIED'
    assert event == original
    public = ota.public_snapshot({'events':[dict(event, provisional_assignment=dict(
        decisions['synthetic-ota'], unknown_customer_payload='SENTINEL'))]})['events'][0]
    assert public['payment_status'] == 'unverified'
    assert 'SENTINEL' not in json.dumps(public)
    manual_row = dict(rows[0], classification_source='user_decision', trip_id='')
    result = [{'ota_event_id':'synthetic-ota','status':'MATCHED_USER','transaction_id':rows[0]['transaction_id']}]
    assert ota._provisional_trip_decisions(SimpleNamespace(board=flow.board), [event], [manual_row], result)[
        'synthetic-ota']['status'] == 'CLASSIFIED'
    mail = dict(event, verified_portal_snapshot=False, evidence_kind='authenticated_payment_mail',
                source_digest='a' * 64, reservation_status='observed')
    assert ota._provisional_trip_decisions(SimpleNamespace(board=flow.board), [mail], [], [])["synthetic-ota"][
        'trip_id'] == trip
    assert ota._provisional_trip_decisions(SimpleNamespace(board=flow.board), [dict(mail, evidence_changed=True)],
        [], [])["synthetic-ota"]['status'] == 'FINANCIAL_HOLD'
    assert not ota._provisional_trip_decisions(SimpleNamespace(board=flow.board),
        [dict(mail, source_digest='')], [], [])


def test_import_has_one_review_flow_and_does_not_write(setup_review):
    from webapp import card_flow
    flow, _, _, _ = setup_review

    class Handler:
        def _send(self, body, status=200):
            self.result = status, body

    handler = Handler()
    before = list(flow.board.conn.iterdump())
    with patch('webapp.ledger_board._active_store', return_value=flow.board), \
            patch('webapp.ota_payment_review.enabled', return_value=False):
        assert card_flow.dispatch(handler, urlsplit('/import'), query={})
    status, html = handler.result
    assert status == 200
    assert html.count('id="card-review-detail"') == 1
    assert 'id="provisional-trip-review"' not in html
    assert '분류되면 완료입니다' not in html
    assert '검사를 통과한 거래는 자동 반영했습니다' not in html
    assert list(flow.board.conn.iterdump()) == before


def test_real_browser_owner_review_paging_pending_approval_and_hold(tmp_path, monkeypatch):
    import threading
    from playwright.sync_api import sync_playwright
    from webapp import ledger_board
    monkeypatch.setenv('WEBLEDGER_UNIFIED_DB', '1')
    monkeypatch.setenv('WEBLEDGER_CARD_FLOW', '1')
    monkeypatch.setenv('WEBLEDGER_REVIEW_FROM', '')
    monkeypatch.setenv('WEBLEDGER_OTA_REVIEW_MODE', '')
    previous = ledger_board._STORE
    ledger_board.bind_access(None)
    server = ledger_board.serve(port=0, db_path=tmp_path/'browser.sqlite', with_worker=False, seed_demo=False)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        board = server.card_store
        trip = board.create_trip(starts_on='2026-10-01', ends_on='2026-10-05',
                                 destination='Synthetic trip', client_request_id='browser-trip')['tab_id']
        monkeypatch.setattr(CardFlow, 'trip_valid', lambda self, identity: identity == trip)
        flow = CardFlow(board)
        content = CARD.splitlines(keepends=True)[0] + b''.join(
            CARD.splitlines(keepends=True)[1].replace(b'A123', f'BROW{i:03}'.encode()) for i in range(23))
        batch = flow.pipeline.receive(content, 'synthetic-browser.csv')['batch_id']
        board.conn.execute("UPDATE transactions SET item='food',classification_state='classified',"
                           "classification_source='inference',trip_id=?,display_tab_id=?", (trip, trip))
        rows = sorted(flow.pipeline.get_batch(batch)['rows'], key=lambda row: row['transaction_id'])
        confirm_two(flow, trip, rows)
        refund_identity = rows[-1]['transaction_id']
        board.conn.execute("UPDATE transactions SET display_tab_id='refunds',trip_id='' WHERE transaction_id=?",
                           (refund_identity,))
        base = f'http://127.0.0.1:{server.server_address[1]}'
        with sync_playwright() as api:
            browser = api.chromium.launch(headless=True)
            try:
                page = browser.new_page(viewport={'width':375,'height':812})
                page.set_default_timeout(8000)
                page.goto(base+'/import')
                assert page.locator('#provisional-trip-review').count() == 0
                # Retain coverage for the standalone component and protected APIs.
                csrf = page.evaluate('csrf')
                page.set_content(review.render(csrf))
                root = page.locator('#provisional-trip-review')
                assert root.locator('[data-trip-items] li').count() == 0
                root.locator('summary').first.click()
                root.locator('[data-trip-items] li').nth(19).wait_for()
                assert root.locator('[data-trip-items] li').count() == 20
                assert '분류 완료' in root.inner_text()
                assert '자동 잠정' not in root.inner_text()
                assert '사용자 확정' not in root.inner_text()
                root.locator('[data-trip-next]').click()
                page.wait_for_function("document.querySelectorAll('[data-trip-items] li').length===3")
                refund_select = root.locator(f'li[data-transaction="{refund_identity}"] select')
                assert refund_select.input_value() == 'refunds'
                assert refund_select.locator('option:checked').inner_text() == '환불'
                root.locator('[data-trip-state]').select_option('manual')
                root.locator('[data-trip-correction]').nth(1).wait_for()
                for checkbox in root.locator('[data-trip-correction]').all():
                    checkbox.check()
                root.locator('[data-trip-propose]').click()
                root.locator('[data-trip-proposals] article button').wait_for()
                assert board.conn.execute('SELECT COUNT(*) FROM cost_classification_rules').fetchone()[0] == 0
                page.once('dialog', lambda dialog: dialog.accept())
                root.locator('[data-trip-proposals] article button').click()
                page.wait_for_function("document.querySelector('[data-trip-message]').textContent.includes('제한 규칙을 저장')")
                assert board.conn.execute('SELECT COUNT(*) FROM cost_classification_rules').fetchone()[0] == 2
                root.locator('[data-trip-state]').select_option('automatic')
                root.locator('[data-trip-items] li').nth(19).wait_for()
                row = root.locator('[data-trip-items] li').first
                identity = row.get_attribute('data-transaction')
                page.once('dialog', lambda dialog: dialog.accept())
                row.get_by_role('button', name='검토 보류', exact=True).click()
                page.wait_for_function("id=>{const n=[...document.querySelectorAll('[data-trip-items] li')].find(n=>n.dataset.transaction===id);return n?.textContent.includes('분류 완료')&&n.textContent.includes('검토 보류')&&n.querySelector('button[type=submit]').disabled}", arg=identity)
                assert board.conn.execute('SELECT kind FROM transaction_review_holds WHERE transaction_id=?',
                                           (identity,)).fetchone()[0] == 'user_hold'
                form = root.locator('[data-trip-items] li form').filter(
                    has=page.locator('button[type=submit]:enabled')).first
                changed_id = form.locator('..').get_attribute('data-transaction')
                dialogs = []
                page.on('dialog', lambda dialog: (dialogs.append(dialog.message), dialog.dismiss()))
                with page.expect_response(lambda response: response.url.endswith('/decision') and response.request.method == 'POST') as saved:
                    form.locator('button[type=submit]').click()
                assert saved.value.status == 200
                assert dialogs == []
                assert board.conn.execute('SELECT classification_source FROM transactions WHERE transaction_id=?',
                                           (changed_id,)).fetchone()[0] == 'user_decision'
                assert board.conn.execute("SELECT COUNT(*) FROM change_log WHERE kind='trip_assignment.reviewed'").fetchone()[0] == 3
                for width in (320, 390, 760, 1440):
                    page.set_viewport_size({'width':width,'height':900})
                    page.emulate_media(color_scheme='dark' if width == 390 else 'light')
                    assert page.evaluate('document.documentElement.scrollWidth <= innerWidth + 1')
                page.evaluate("document.body.style.zoom='2'")
                assert root.locator('summary').first.is_visible()
                assert page.url.startswith(base+'/import')
            finally:
                browser.close()
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
        server.card_store.close()
        ledger_board.bind_store(previous)
