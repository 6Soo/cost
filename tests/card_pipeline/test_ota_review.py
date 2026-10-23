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


def test_manual_event_id_crosswalk_is_persisted_with_the_user_confirmation(tmp_path):
    path = tmp_path / 'crosswalk.sqlite'
    store = OtaReviewStore(path)
    try:
        current = event('pay-current')
        current['source_digest'] = 'same-source-proof'
        preview = store.preview(current, card())
        store.confirm(current, card(), preview['preview_digest'], request_id='crosswalk-confirm',
                      user='owner', allocations={}, id_crosswalk={'legacy-event': 'pay-current'})
        assert store.event_crosswalks() == {
            'legacy-event': {'current_event_id': 'pay-current', 'evidence_digest': 'same-source-proof'}
        }
    finally:
        store.close()
    # Reopening simulates a later source collection/request: the pin and its
    # evidence-bound ID mapping must survive independently of the process.
    reopened = OtaReviewStore(path)
    try:
        assert reopened.links()['pay-current']['transaction_id'] == 'card-a'
        assert reopened.event_crosswalks() == {
            'legacy-event': {'current_event_id': 'pay-current', 'evidence_digest': 'same-source-proof'}
        }
    finally:
        reopened.close()


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


def test_user_approved_dynamic_provider_alias_is_versioned_and_used(tmp_path):
    store = OtaReviewStore(tmp_path / 'user-alias.sqlite')
    try:
        current_event = event(card_last4=None)
        current_card = card(merchant='SYNTHETIC OTA', merchant_normalized='synthetic ota')
        preview = store.preview(current_event, current_card)
        store.confirm(current_event, current_card, preview['preview_digest'],
                      request_id='alias-link', user='synthetic-owner', allocations={})
        proposal = store.proposals()[0]
        alias_conditions = {"rule_kind":"provider_alias", "provider":"agoda",
            "alias":"synthetic ota", "approval_source":"manual_review_link", "alias_version":1}
        once = store.answer_proposal(proposal['proposal_id'], 'once', user='synthetic-owner')
        assert once['active'] is False
        assert store.active_rules() == []
        # A separate pending proposal is created by the same confirmed link
        # below to test explicit alias approval rather than one-time use.
        second_event = event('evt-alias-second', card_last4=None)
        second_card = card('card-second', merchant='SYNTHETIC OTA',
                      merchant_normalized='synthetic ota')
        second_preview = store.preview(second_event, second_card)
        store.confirm(second_event, second_card, second_preview['preview_digest'],
                      request_id='alias-link-2', user='synthetic-owner', allocations={})
        pending = next(p for p in store.proposals() if p['status'] == 'pending')
        answer = store.answer_proposal(pending['proposal_id'], 'approve', user='synthetic-owner',
                                       conditions=alias_conditions)
        assert answer['active'] is True
        active = store.active_rules()[0]
        assert active['conditions'] == alias_conditions
        result = match_ota_payment_events([current_event], [current_card], rules=store.active_rules())
        assert result[0]['status'] == 'MATCHED_AUTO'
    finally:
        store.close()


def test_percent_discount_rule_is_inactive_until_explicit_approve_and_once_stays_local(tmp_path):
    conditions = {"provider":"agoda", "item":"숙박비", "merchant_normalized":"unknown",
        "issuer":"issuer-x", "card_last4":"1234", "payment_method":"credit",
        "valid_from":"2026-08-01", "valid_to":"2026-08-31", "minimum_amount_krw":10000,
        "discount_rate_bps":1000, "discount_cap_krw":5000, "rounding_mode":"half_up"}
    store = OtaReviewStore(tmp_path / 'percent-rule.sqlite')
    try:
        original, transaction = event(), card(payment_method='credit')
        preview = store.preview(original, transaction)
        store.confirm(original, transaction, preview['preview_digest'], request_id='percent',
                      user='synthetic-owner', allocations={})
        proposal = store.proposals()[0]
        assert store.active_rules() == []
        once = store.answer_proposal(proposal['proposal_id'], 'once', user='synthetic-owner')
        assert once['active'] is False
        assert store.active_rules() == []
        # A second explicit link supplies a separately pending approval record.
        second_event = event('evt-percent-approved')
        second_card = card('card-percent-approved', payment_method='credit')
        second_preview = store.preview(second_event, second_card)
        store.confirm(second_event, second_card, second_preview['preview_digest'],
                      request_id='percent-approved', user='synthetic-owner', allocations={})
        pending = next(p for p in store.proposals() if p['status'] == 'pending')
        approved = store.answer_proposal(pending['proposal_id'], 'approve', user='synthetic-owner',
                                         conditions=conditions)
        assert approved['active'] is True
        next_event = event('evt-percent-next', card_last4='1234')
        next_card = card('card-percent-next', amount_krw=27000, payment_method='credit')
        assert match_ota_payment_events([next_event], [next_card],
               rules=store.active_rules())[0]['status'] == 'MATCHED_AUTO'
    finally:
        store.close()


def test_frozen_group_order_survives_new_card_and_get_does_not_reallocate(tmp_path):
    store = OtaReviewStore(tmp_path / 'frozen-group.sqlite')
    try:
        events = [event('evt-a', booking_ref='BOOK-A'), event('evt-b', booking_ref='BOOK-B')]
        cards = [card('card-a', authorization_number='AUTH-A'),
                 card('card-b', authorization_number='AUTH-B')]
        initial = match_ota_payment_events(events, cards)
        mapping = {row['ota_event_id']: row['transaction_id'] for row in initial}
        frozen = store.confirm_group_order(
            [row['ota_event_id'] for row in initial], [row['transaction_id'] for row in initial],
            mapping, user='synthetic-owner', order_snapshot=initial[0]['group_order_snapshot'],
            request_id='freeze-group-synthetic-001')
        assert frozen['status'] == 'frozen'
        replay = store.confirm_group_order(
            [row['ota_event_id'] for row in initial], [row['transaction_id'] for row in initial],
            mapping, user='synthetic-owner', order_snapshot=initial[0]['group_order_snapshot'],
            request_id='freeze-group-synthetic-001')
        assert replay == frozen
        with pytest.raises(ValueError, match='GROUP_ORDER_REQUEST_REPLAY_CONFLICT'):
            store.confirm_group_order(
                [row['ota_event_id'] for row in initial], [row['transaction_id'] for row in initial],
                dict(reversed(list(mapping.items()))), user='different-synthetic-owner', replace=True,
                order_snapshot=initial[0]['group_order_snapshot'], request_id='freeze-group-synthetic-001')
        count_before = store.conn.execute('SELECT COUNT(*) FROM ota_review_group_pins').fetchone()[0]
        assert store.group_pins()[0]['mapping'] == mapping
        assert store.conn.execute('SELECT COUNT(*) FROM ota_review_group_pins').fetchone()[0] == count_before
        changed = match_ota_payment_events(events, cards + [card('card-c', authorization_number='AUTH-C')],
                                           frozen_groups=store.group_pins())
        assert {row['status'] for row in changed} == {'HOLD_GROUP_CHANGED'}
        assert all(row.get('transaction_id') is None for row in changed)
        assert all(row['frozen_mapping'] == mapping for row in changed)
        reordered_events = [event('evt-a', booking_ref='BOOK-Z'), event('evt-b', booking_ref='BOOK-A')]
        reordered = match_ota_payment_events(reordered_events, cards, frozen_groups=store.group_pins())
        assert {row['status'] for row in reordered} == {'HOLD_GROUP_CHANGED'}
        assert all(row['review_warning'] == 'confirm_group_reallocation' for row in reordered)
        replacement = reordered[0]['proposed_mapping']
        replaced = store.confirm_group_order(
            [row['ota_event_id'] for row in reordered], [row['transaction_id'] for row in initial],
            replacement, user='synthetic-owner', replace=True,
            order_snapshot=reordered[0]['group_order_snapshot'],
            request_id='replace-group-order-synthetic-001')
        assert replaced['version'] == 2
        assert store.group_pins()[0]['order_snapshot'] == reordered[0]['group_order_snapshot']
        confirmed = match_ota_payment_events(reordered_events, cards, frozen_groups=store.group_pins())
        assert {row['status'] for row in confirmed} == {'MATCHED_AUTO'}
        assert {row['allocation_basis'] for row in confirmed} == {'frozen_user_confirmed_order'}
    finally:
        store.close()


def test_frozen_group_edge_change_warns_and_keeps_all_pinned_cards_reserved():
    store = OtaReviewStore(':memory:')
    try:
        events = [event('edge-a', booking_ref='BOOK-A', authorization_number='AUTH-A'),
                  event('edge-b', booking_ref='BOOK-B', authorization_number='AUTH-B')]
        cards = [card('edge-card-a', authorization_number='AUTH-A'),
                 card('edge-card-b', authorization_number='AUTH-B')]
        initial = match_ota_payment_events(events, cards)
        mapping = {row['ota_event_id']:row['transaction_id'] for row in initial}
        store.confirm_group_order(
            [row['ota_event_id'] for row in initial], [row['transaction_id'] for row in initial],
            mapping, user='synthetic-owner', order_snapshot=initial[0]['group_order_snapshot'],
            request_id='freeze-edge-synthetic-001')
        changed_events = [dict(row, authorization_scheme='synthetic-v1') for row in events]
        changed_cards = [dict(row, authorization_scheme='synthetic-v1') for row in cards]
        changed = match_ota_payment_events(changed_events, changed_cards, frozen_groups=store.group_pins())
        assert {row['status'] for row in changed} == {'HOLD_GROUP_CHANGED'}
        assert all(row['transaction_id'] is None for row in changed)
        assert all(row['frozen_mapping'] == mapping for row in changed)
        assert all(set(row['reserved_card_ids']) == {'edge-card-a', 'edge-card-b'} for row in changed)
        assert all(row['review_warning'] == 'confirm_group_reallocation' for row in changed)
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


def test_acceptance_07_saved_delta_rules_keep_exact_and_delta_edges_in_their_own_scope(tmp_path):
    store = OtaReviewStore(tmp_path / 'synthetic-rule-scope.sqlite')
    try:
        scopes = [
            (event('rule-room', provider='agoda', item='room', amount=100000, amount_krw=100000,
                   card_last4='2042'), card('rule-room-source', merchant_normalized='agoda.com',
                   card_tail='2042', amount_krw=96000), -4000),
            (event('rule-hotel', provider='booking', item='hotel', amount=100000, amount_krw=100000,
                   card_last4='9999'), card('rule-hotel-source', merchant_normalized='booking.com',
                   card_tail='9999', amount_krw=98000), -2000),
        ]
        for index, (candidate, transaction, delta) in enumerate(scopes):
            preview = store.preview(candidate, transaction)
            confirmed = store.confirm(candidate, transaction, preview['preview_digest'],
                request_id=f'scope-source-{index}', user='synthetic-owner', allocations={})
            conditions = {'provider':candidate['provider'], 'item':candidate['item'],
                'merchant_normalized':transaction['merchant_normalized'], 'issuer':'issuer-x',
                'card_last4':transaction['card_tail'], 'currency':'KRW', 'event_type':'charge',
                'amount_delta_krw':delta}
            store.answer_proposal(confirmed['proposal_id'], 'approve', user='synthetic-owner',
                                  conditions=conditions)
        rules = store.active_rules()
        assert len(rules) == 2
        assert {rule['conditions']['item'] for rule in rules} == {'room', 'hotel'}
        assert {rule['conditions']['provider'] for rule in rules} == {'agoda', 'booking'}
        assert store.conn.execute('SELECT COUNT(*) FROM ota_review_rules WHERE active=1').fetchone()[0] == 2
        candidates = [event('rule-room-next', provider='agoda', item='room', amount=100000,
                            amount_krw=100000, card_last4='2042'),
                      event('rule-hotel-next', provider='booking', item='hotel', amount=100000,
                            amount_krw=100000, card_last4='9999'),
                      event('rule-other-item', provider='agoda', item='flight', amount=100000,
                            amount_krw=100000, card_last4='7777')]
        transactions = [card('room-exact', merchant_normalized='agoda.com', card_tail='2042', amount_krw=100000),
                       card('room-delta', merchant_normalized='agoda.com', card_tail='2042', amount_krw=96000),
                       card('hotel-exact', merchant_normalized='booking.com', card_tail='9999', amount_krw=100000),
                       card('hotel-delta', merchant_normalized='booking.com', card_tail='9999', amount_krw=98000),
                       card('other-exact', merchant_normalized='agoda.com', card_tail='7777', amount_krw=100000),
                       card('other-delta', merchant_normalized='agoda.com', card_tail='7777', amount_krw=96000)]
        results = {row['ota_event_id']:row for row in match_ota_payment_events(candidates, transactions, rules=rules)}
        assert results['rule-room-next']['status'] == 'HOLD_PARTIAL_GROUP'
        assert set(results['rule-room-next']['candidates']) == {'room-exact', 'room-delta'}
        assert results['rule-hotel-next']['status'] == 'HOLD_PARTIAL_GROUP'
        assert set(results['rule-hotel-next']['candidates']) == {'hotel-exact', 'hotel-delta'}
        assert results['rule-other-item']['status'] == 'MATCHED_AUTO'
        assert results['rule-other-item']['transaction_id'] == 'other-exact'
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
        assert result['proposal_conditions']['date_lag_days'] == (2 if approval_date > '2026-08-01' else -2)
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
