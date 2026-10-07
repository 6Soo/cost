import pytest

from app.ota_payments import OtaSourcesError, build_ota_payment_events, match_ota_payment_events
from app.ota_review import OtaReviewStore


def event(identity='evt', **changes):
    value = dict(ota_event_id=identity, provider='agoda', booking_ref='BOOK12345',
                 item='숙박비',
                 event_type='charge', paid_on='2026-08-01', amount=30000,
                 currency='KRW', amount_krw=30000, card_last4='1234',
                 evidence_status='paid_verified', payment_status='paid',
                 source_digest='a' * 64, source_ids=['mail:1'])
    value.update(changes)
    return value


def card(identity='card-a', **changes):
    value = dict(transaction_id=identity, source_hash='b' * 64, merchant='UNKNOWN',
                 merchant_normalized='unknown', issuer='issuer-x', card_tail='1234',
                 approval_date='2026-08-01', transaction_direction='purchase', amount_krw=30000)
    value.update(changes)
    return value


def test_i_global_card_event_matching_is_one_to_one():
    results = match_ota_payment_events([event('one'), event('two', source_ids=['mail:2'])], [card()])
    assert len([item for item in results if item.get('transaction_id')]) <= 1
    assert any(item['status'] == 'HOLD_AMBIGUOUS' for item in results)


def test_j_manual_link_is_persisted_in_explicit_review_database(tmp_path):
    store = OtaReviewStore(tmp_path / 'review.sqlite')
    try:
        preview = store.preview(event(), card())
        result = store.confirm(event(), card(), preview['preview_digest'],
                               request_id='request-1', user='owner', allocations={})
        assert result['status'] == 'MATCHED_USER'
        assert store.links()['evt']['transaction_id'] == 'card-a'
        assert store.event_snapshots()['evt']['ota_event_id'] == 'evt'
        assert store.active_rules() == []
    finally:
        store.close()


@pytest.mark.parametrize('allocations', [pytest.param('omitted', id='omitted'),
                                         pytest.param(None, id='none')])
def test_confirm_requires_an_explicit_global_allocation_snapshot(tmp_path, allocations):
    store = OtaReviewStore(tmp_path / 'review.sqlite')
    try:
        candidate, transaction = event(), card()
        preview = store.preview(candidate, transaction)
        kwargs = {} if allocations == 'omitted' else {'allocations':allocations}
        with pytest.raises(ValueError, match='GLOBAL_ALLOCATIONS_REQUIRED'):
            store.confirm(candidate, transaction, preview['preview_digest'], request_id='no-allocations',
                          user='owner', **kwargs)
        assert store.links() == {}
    finally:
        store.close()


def test_confirm_accepts_explicit_empty_global_allocation_snapshot(tmp_path):
    store = OtaReviewStore(tmp_path / 'review.sqlite')
    try:
        candidate, transaction = event(), card()
        preview = store.preview(candidate, transaction)
        result = store.confirm(candidate, transaction, preview['preview_digest'],
                               request_id='empty-allocations', user='owner', allocations={})
        assert result['status'] == 'MATCHED_USER'
    finally:
        store.close()


def test_k_stale_preview_is_rejected_after_evidence_changes(tmp_path):
    store = OtaReviewStore(tmp_path / 'review.sqlite')
    try:
        before, after = event(), event(amount_krw=31000, amount=31000, source_digest='c'*64)
        preview = store.preview(before, card())
        with pytest.raises(ValueError, match='STALE_PREVIEW'):
            store.confirm(after, card(), preview['preview_digest'],
                          request_id='request-stale', user='owner', allocations={})
    finally:
        store.close()


def test_l_proposal_is_inactive_until_explicit_narrow_approval(tmp_path):
    store = OtaReviewStore(tmp_path / 'review.sqlite')
    try:
        preview = store.preview(event(), card())
        store.confirm(event(), card(), preview['preview_digest'], request_id='r', user='owner', allocations={})
        proposals = store.proposals()
        assert len(proposals) == 1
        assert store.active_rules() == []
        result = store.answer_proposal(proposals[0]['proposal_id'], 'once', user='owner')
        assert result['active'] is False
    finally:
        store.close()


def test_m_incremental_refresh_targets_changed_sources_and_preserves_manual_link(tmp_path):
    store = OtaReviewStore(tmp_path / 'review.sqlite')
    try:
        original = event()
        preview = store.preview(original, card())
        store.confirm(original, card(), preview['preview_digest'], request_id='r', user='owner', allocations={})
        changed = event(source_digest='c'*64)
        results = store.refresh([changed], [card()], changed_event_ids=['evt'])
        assert results[0]['status'] == 'MATCHED_USER'
        assert results[0]['evidence_changed'] is True
        assert results[0]['transaction_id'] == 'card-a'
    finally:
        store.close()


def test_changed_booking_amount_and_card_facts_keep_source_identity_manual_link(tmp_path):
    store = OtaReviewStore(tmp_path / 'review.sqlite')
    try:
        original = event()
        preview = store.preview(original, card())
        store.confirm(original, card(), preview['preview_digest'], request_id='source-change', user='owner', allocations={})
        changed = event(booking_ref='CORRECTED-BOOKING', amount=31000,
                       amount_krw=31000, card_last4='9876', source_digest='c'*64)
        changed['ota_event_id'] = original['ota_event_id']
        results = store.refresh([changed], [card()], changed_event_ids=['evt'])
        assert results[0]['status'] == 'MATCHED_USER'
        assert results[0]['transaction_id'] == 'card-a'
        assert results[0]['evidence_changed'] is True
    finally:
        store.close()


def test_missing_source_keeps_manual_link_and_blocks_card_reuse(tmp_path):
    store = OtaReviewStore(tmp_path / 'review.sqlite')
    try:
        original = event()
        preview = store.preview(original, card())
        store.confirm(original, card(), preview['preview_digest'], request_id='source-gone', user='owner', allocations={})
        other = event('other')
        results = store.refresh([other], [card()])
        missing = next(result for result in results if result['ota_event_id'] == 'evt')
        reused = next(result for result in results if result['ota_event_id'] == 'other')
        assert missing['status'] == 'MATCHED_USER'
        assert missing['evidence_missing'] is True
        assert store.event_snapshots()['evt']['_evidence_missing'] is True
        assert store.event_snapshots()['evt']['amount_krw'] == 30000
        assert reused['transaction_id'] is None
    finally:
        store.close()


def test_incomplete_source_guard_does_not_delete_persisted_manual_snapshot(tmp_path):
    store = OtaReviewStore(tmp_path / 'review.sqlite')
    try:
        original = event()
        preview = store.preview(original, card())
        store.confirm(original, card(), preview['preview_digest'], request_id='guard-link', user='owner', allocations={})
        with pytest.raises(OtaSourcesError, match='OTA_SOURCES_INCOMPLETE'):
            build_ota_payment_events({'mail_directories':[], 'portal_databases':[],
                                      'missing':[{'kind':'mail_directory'}]})
        assert store.links()['evt']['transaction_id'] == 'card-a'
        assert store.links()['evt']['status'] == 'MATCHED_USER'
    finally:
        store.close()


def test_source_that_stops_verifying_payment_keeps_snapshot_and_marks_evidence_missing(tmp_path):
    store = OtaReviewStore(tmp_path / 'review.sqlite')
    try:
        original = event()
        preview = store.preview(original, card())
        store.confirm(original, card(), preview['preview_digest'], request_id='source-invalid', user='owner', allocations={})
        changed = event(event_type='reservation', evidence_status='not_card_charge',
                        payment_status='unknown', amount_krw=None, source_digest='c'*64)
        results = store.refresh([changed], [card()], changed_event_ids=['evt'])
        linked = next(result for result in results if result['ota_event_id'] == 'evt')
        assert linked['status'] == 'MATCHED_USER'
        assert linked['event_type'] == 'charge'
        assert linked['transaction_id'] == 'card-a'
        assert linked['evidence_missing'] is True
        assert linked['evidence_changed'] is True
    finally:
        store.close()


def test_incremental_card_refresh_returns_only_events_relevant_to_changed_row(tmp_path):
    store = OtaReviewStore(tmp_path / 'review.sqlite')
    try:
        relevant = event('relevant')
        unrelated = event('unrelated', paid_on='2026-08-04')
        results = store.refresh([relevant, unrelated], [card(), card('other-card',
            approval_date='2026-08-04')], changed_transaction_ids=['card-a'])
        assert [item['ota_event_id'] for item in results] == ['relevant']
    finally:
        store.close()


def test_approved_narrow_proposal_becomes_a_versioned_active_rule(tmp_path):
    store = OtaReviewStore(tmp_path / 'review.sqlite')
    try:
        preview = store.preview(event(), card())
        store.confirm(event(), card(), preview['preview_digest'], request_id='approve-r', user='owner', allocations={})
        proposal = store.proposals()[0]
        answer = store.answer_proposal(proposal['proposal_id'], 'approve', user='owner')
        assert answer['active'] is True
        assert len(store.active_rules()) == 1
        assert store.active_rules()[0]['version'] == 1
        rule = store.active_rules()[0]
        assert rule['created_at']
        assert rule['source_event_id'] == 'evt'
        assert rule['source_transaction_id'] == 'card-a'
        assert rule['user_confirmation']['user'] == 'owner'
        assert rule['active'] is True
    finally:
        store.close()


def test_edit_reissues_a_pending_narrow_proposal_without_activating_it(tmp_path):
    store = OtaReviewStore(tmp_path / 'review.sqlite')
    try:
        preview = store.preview(event(), card())
        store.confirm(event(), card(), preview['preview_digest'], request_id='edit-r', user='owner', allocations={})
        proposal = store.proposals()[0]
        answer = store.answer_proposal(proposal['proposal_id'], 'edit', user='owner',
            conditions={'provider':'agoda', 'item':'숙박비', 'issuer':'issuer-x',
                        'card_last4':'1234', 'date_lag_days':1})
        assert answer['active'] is False
        assert answer['new_proposal_id']
        assert len(store.proposals()) == 2
        assert store.active_rules() == []
    finally:
        store.close()


def test_existing_non_review_database_is_rejected_before_schema_changes(tmp_path):
    import sqlite3
    path = tmp_path / 'board.sqlite'
    with sqlite3.connect(path) as conn:
        conn.execute('CREATE TABLE transactions(id TEXT)')
    with pytest.raises(ValueError, match='REVIEW_DATABASE_NOT_ISOLATED'):
        OtaReviewStore(path)


def test_read_only_store_inspection_does_not_create_database(tmp_path):
    path = tmp_path / 'get-review.sqlite'
    store = OtaReviewStore(path)
    try:
        assert store.links() == {}
        assert store.event_snapshots() == {}
        assert not path.exists()
    finally:
        store.close()


def test_proposal_get_does_not_migrate_an_existing_review_database(tmp_path):
    import sqlite3
    path = tmp_path / 'old-review.sqlite'
    with sqlite3.connect(path) as conn:
        conn.execute("""CREATE TABLE ota_review_proposals(
            proposal_id TEXT PRIMARY KEY, event_id TEXT NOT NULL, transaction_id TEXT NOT NULL,
            conditions_json TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'pending',
            answer_json TEXT, user TEXT NOT NULL)""")
    store = OtaReviewStore(path)
    try:
        assert store.proposals() == []
        columns = {row[1] for row in store.conn.execute("PRAGMA table_info(ota_review_proposals)")}
        assert 'review_warning' not in columns
    finally:
        store.close()


def test_confirm_rejects_card_already_allocated_by_auto_or_legacy_match(tmp_path):
    store = OtaReviewStore(tmp_path / 'review.sqlite')
    try:
        preview = store.preview(event(), card())
        with pytest.raises(ValueError, match='CARD_ALREADY_LINKED'):
            store.confirm(event(), card(), preview['preview_digest'], request_id='occupied',
                          user='owner', allocations={'card-a':'auto-event'})
    finally:
        store.close()


def test_ui_amount_delta_condition_is_accepted_only_with_narrow_identity(tmp_path):
    store = OtaReviewStore(tmp_path / 'review.sqlite')
    try:
        preview = store.preview(event(), card())
        store.confirm(event(), card(), preview['preview_digest'], request_id='delta', user='owner', allocations={})
        proposal = store.proposals()[0]
        answer = store.answer_proposal(proposal['proposal_id'], 'approve', user='owner', conditions={
            'provider':'agoda', 'item':'숙박비', 'issuer':'issuer-x', 'card_last4':'1234',
            'amount_delta_krw':1000, 'date_lag_days':1})
        assert answer['active'] is True
        assert store.active_rules()[0]['conditions']['amount_delta_krw'] == 1000
    finally:
        store.close()


@pytest.mark.parametrize('approval_date', ['2026-08-03', '2026-07-30'])
@pytest.mark.parametrize('answer_action,expected_status', [('approve','MATCHED_AUTO'), ('once','HOLD_NO_CARD')])
def test_signed_manual_delta_proposal_only_applies_after_approval(
        tmp_path, approval_date, answer_action, expected_status):
    store = OtaReviewStore(tmp_path / f'{answer_action}.sqlite')
    try:
        original = event(amount=279013, amount_krw=279013)
        transaction = card(amount_krw=275013, approval_date=approval_date)
        preview = store.preview(original, transaction)
        result = store.confirm(original, transaction, preview['preview_digest'],
                               request_id=f'delta-{answer_action}', user='owner', allocations={})
        assert result['proposal_conditions']['amount_delta_krw'] == -4000
        assert result['proposal_conditions']['date_lag_days'] == 2
        assert result['proposal_review_warnings'] == []
        proposal = store.proposals()[0]
        assert proposal['conditions'] == result['proposal_conditions']
        answer = store.answer_proposal(proposal['proposal_id'], answer_action, user='owner')
        assert answer['active'] is (answer_action == 'approve')
        next_event = event('next-payment', amount=279013, amount_krw=279013,
                           source_digest='c'*64, source_ids=['mail:next'])
        next_card = card('next-card', amount_krw=275013, approval_date=approval_date)
        matched = match_ota_payment_events([next_event], [next_card], rules=store.active_rules())[0]
        assert matched['status'] == expected_status
    finally:
        store.close()


def test_unsupported_delta_and_lag_require_proposal_edit_before_approval(tmp_path):
    store = OtaReviewStore(tmp_path / 'unsupported.sqlite')
    try:
        original = event(amount=50000, amount_krw=50000)
        transaction = card(amount_krw=35000, approval_date='2026-08-10')
        preview = store.preview(original, transaction)
        result = store.confirm(original, transaction, preview['preview_digest'],
                               request_id='unsupported', user='owner', allocations={})
        proposal = store.proposals()[0]
        assert proposal['review_warnings'] == [
            'amount_delta_out_of_supported_range', 'date_lag_out_of_supported_range']
        assert result['proposal_review_warnings'] == proposal['review_warnings']
        with pytest.raises(ValueError, match='PROPOSAL_REQUIRES_EDIT'):
            store.answer_proposal(proposal['proposal_id'], 'approve', user='owner')
        edited = store.answer_proposal(proposal['proposal_id'], 'edit', user='owner', conditions={
            'provider':'agoda', 'item':'숙박비', 'issuer':'issuer-x', 'card_last4':'1234',
            'amount_delta_krw':-4000, 'date_lag_days':2})
        assert edited['active'] is False
        assert store.active_rules() == []
        revised = next(p for p in store.proposals() if p['proposal_id'] == edited['new_proposal_id'])
        assert revised['review_warnings'] == []
    finally:
        store.close()
