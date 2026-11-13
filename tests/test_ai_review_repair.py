import json
import sqlite3

import pytest

from app import ai_review_repair as repair
from app import automatic_classification as p1
from webapp.tests.test_automatic_classification_completion import setup, TRIPS

REVIEWER = dict(provider='claude', model='claude-fable-5-2', effort='high')
REVIEW_ID = 'ai-quarter-review-2026Q3'


def prepare(c):
    c.execute("UPDATE transactions SET approval_date='2026-09-30',classification_state='classified',"
              "classification_source='inference',item='식비',trip_id='A',display_tab_id='A',"
              "classification_basis='AUTO_INFERRED · 합성 추론',decided_at=NULL")
    c.commit()


def make_manifest(corrections):
    return dict(review_id=REVIEW_ID, reviewer=dict(REVIEWER), corrections=corrections)


def correction_for(c, tid, tab, item='식비', basis='TRIP-001 · 합성 근거'):
    row = repair._state(c, tid)['transaction']
    return dict(transaction_id=tid, source_hash=row['source_hash'], revision=row['revision'],
                display_tab_id=tab, item=item, basis=basis)


def add_projection(c, tid, batch):
    row = repair._state(c, tid)['transaction']
    c.execute('INSERT INTO ledger_entries(transaction_id,batch_id,item,description,display_tab_id,trip_id,'
              'amount_krw,merchant,occurred_on,transaction_direction,source_hash,committed_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)',
              (tid, batch, row['item'], 'synthetic', row['display_tab_id'], row['trip_id'],
               row['amount_krw'], row['merchant'], row['approval_date'], row['transaction_direction'],
               row['source_hash'], 'synthetic'))
    payload = dict(item=row['item'], description='synthetic', display_tab_id=row['display_tab_id'],
                   trip_id=row['trip_id'], classification_state=row['classification_state'],
                   classification_source=row['classification_source'],
                   classification_basis=row['classification_basis'], confirmed_by='automatic', revision=1)
    c.execute("INSERT INTO board_rows(row_id,row_kind,display_tab_id,revision,payload_json) VALUES (?,'expense',?,1,?)",
              ('card-' + tid, row['display_tab_id'], json.dumps(payload)))
    c.commit()


def test_trip_move_syncs_transaction_ledger_board(setup):
    c, batch = setup[0].conn, setup[2]
    prepare(c)
    tid = setup[3][0]['transaction_id']
    add_projection(c, tid, batch)
    manifest = make_manifest([correction_for(c, tid, 'B', item='숙박비')])
    plan = repair.preview(c, TRIPS, manifest)
    assert plan['summary']['to_apply'] == 1
    assert plan['summary']['kinds'] == {'trip_to_trip': 1}
    financial = repair._financial_state(c)
    result = repair.apply(c, plan, TRIPS, manifest, request_id='synthetic-trip-move')
    assert result['applied_this_run'] == 1
    state = repair._state(c, tid)
    assert state['transaction']['trip_id'] == 'B'
    assert state['transaction']['display_tab_id'] == 'B'
    assert state['transaction']['item'] == '숙박비'
    assert state['transaction']['classification_source'] == 'ai_inference'
    assert state['transaction']['classification_state'] == 'classified'
    assert state['transaction']['classification_basis'].startswith('AI_REVIEW · ')
    assert REVIEW_ID in state['transaction']['classification_basis']
    assert state['ledger']['display_tab_id'] == 'B' and state['ledger']['trip_id'] == 'B'
    assert state['ledger']['item'] == '숙박비'
    assert state['board']['display_tab_id'] == 'B'
    payload = json.loads(state['board']['payload_json'])
    assert payload['trip_id'] == 'B' and payload['classification_source'] == 'ai_inference'
    assert payload['classification_basis'].startswith('AI_REVIEW · ')
    assert repair._financial_state(c) == financial


def test_quarter_move_forces_item_and_clears_trip(setup):
    c, batch = setup[0].conn, setup[2]
    prepare(c)
    tid = setup[3][0]['transaction_id']
    add_projection(c, tid, batch)
    manifest = make_manifest([correction_for(c, tid, 'quarter:2026:3', item='숙박비')])
    plan = repair.preview(c, TRIPS, manifest)
    assert plan['summary']['kinds'] == {'trip_to_quarter': 1}
    repair.apply(c, plan, TRIPS, manifest, request_id='synthetic-quarter-move')
    state = repair._state(c, tid)
    assert state['transaction']['item'] == '분기 기타비용'
    assert state['transaction']['trip_id'] == ''
    assert state['transaction']['display_tab_id'] == 'quarter:2026:3'
    assert state['ledger']['trip_id'] == '' and state['ledger']['item'] == '분기 기타비용'
    payload = json.loads(state['board']['payload_json'])
    assert payload['trip_id'] == '' and payload['item'] == '분기 기타비용'
    assert plan['summary']['quarter_increases'] == {'quarter:2026:3': 1}


def test_item_only_change_within_same_trip(setup):
    c, batch = setup[0].conn, setup[2]
    prepare(c)
    tid = setup[3][0]['transaction_id']
    add_projection(c, tid, batch)
    manifest = make_manifest([correction_for(c, tid, 'A', item='교통비')])
    plan = repair.preview(c, TRIPS, manifest)
    assert plan['summary']['kinds'] == {'item_only': 1}
    repair.apply(c, plan, TRIPS, manifest, request_id='synthetic-item-only')
    state = repair._state(c, tid)
    assert state['transaction']['item'] == '교통비'
    assert state['transaction']['trip_id'] == 'A'
    assert state['ledger']['item'] == '교통비'
    assert json.loads(state['board']['payload_json'])['item'] == '교통비'


def test_quarter_to_trip_move(setup):
    c = setup[0].conn
    prepare(c)
    tid = setup[3][0]['transaction_id']
    c.execute("UPDATE transactions SET trip_id='',display_tab_id='quarter:2026:3',item='분기 기타비용' WHERE transaction_id=?", (tid,))
    c.commit()
    manifest = make_manifest([correction_for(c, tid, 'B')])
    plan = repair.preview(c, TRIPS, manifest)
    assert plan['summary']['kinds'] == {'quarter_to_trip': 1}
    repair.apply(c, plan, TRIPS, manifest, request_id='synthetic-q2t')
    assert repair._state(c, tid)['transaction']['trip_id'] == 'B'


@pytest.mark.parametrize('kind', [
    'manual_decided', 'manual_source', 'review_hold', 'company_excluded',
    'duplicate', 'conflict', 'parse_error', 'closed_period', 'stale_hash',
    'stale_revision', 'projection_mismatch', 'invalid_target', 'closed_current',
])
def test_exclusion_reasons(setup, kind):
    c = setup[0].conn
    prepare(c)
    tid = setup[3][0]['transaction_id']
    row = repair._state(c, tid)['transaction']
    expected = 'MANUAL_OR_USER_EXCEPTION'
    if kind == 'manual_decided':
        c.execute("UPDATE transactions SET decided_at='synthetic' WHERE transaction_id=?", (tid,))
    elif kind == 'manual_source':
        c.execute("UPDATE transactions SET classification_source='user_decision' WHERE transaction_id=?", (tid,))
    elif kind == 'review_hold':
        expected = 'REVIEW_HOLD'
        c.execute('INSERT INTO transaction_review_holds VALUES (?,?,?,?)', (tid, row['source_hash'], 'user_hold', 'synthetic'))
    elif kind == 'company_excluded':
        expected = 'COMPANY_EXCLUDED'
        c.execute('INSERT INTO transaction_company_exclusions VALUES (?,?,1,1,?,?)', (tid, row['source_hash'], 'synthetic', 'synthetic'))
    elif kind == 'duplicate':
        expected = 'SOURCE_PROTECTED'
        c.execute("UPDATE transactions SET duplicate_of='other' WHERE transaction_id=?", (tid,))
    elif kind == 'conflict':
        expected = 'SOURCE_PROTECTED'
        c.execute("UPDATE transactions SET conflict_reason='synthetic' WHERE transaction_id=?", (tid,))
    elif kind == 'parse_error':
        expected = 'SOURCE_PROTECTED'
        c.execute("UPDATE transactions SET parse_error='synthetic' WHERE transaction_id=?", (tid,))
    elif kind == 'closed_period':
        expected = 'CLOSED_CARD_PERIOD'
        c.execute("UPDATE transactions SET approval_date='2026-03-01' WHERE transaction_id=?", (tid,))
    elif kind == 'closed_current':
        expected = 'CLOSED_CARD_PERIOD'
        c.execute("UPDATE transactions SET trip_id='CLOSED',display_tab_id='CLOSED' WHERE transaction_id=?", (tid,))
    c.commit()
    corr = correction_for(c, tid, 'B')
    if kind == 'stale_hash':
        expected = 'STALE'
        corr['source_hash'] = 'wrong-hash'
    elif kind == 'stale_revision':
        expected = 'STALE'
        corr['revision'] = row['revision'] + 99
    elif kind == 'projection_mismatch':
        expected = 'PROJECTION_ATTRIBUTION_DISAGREEMENT'
        add_projection(c, tid, setup[2])
        c.execute("UPDATE ledger_entries SET display_tab_id='B' WHERE transaction_id=?", (tid,))
        c.commit()
    elif kind == 'invalid_target':
        expected = 'INVALID_TARGET'
        corr['display_tab_id'] = 'NONEXISTENT'
    trips = TRIPS + [dict(trip_id='CLOSED', starts_on='2026-01-01', ends_on='2026-01-05')]
    manifest = make_manifest([corr])
    plan = repair.preview(c, trips, manifest)
    assert plan['summary']['to_apply'] == 0
    assert plan['summary']['excluded'].get(expected, 0) == 1


def test_inconsistent_current_attribution_is_projection_disagreement(setup):
    c = setup[0].conn
    prepare(c)
    tid = setup[3][0]['transaction_id']
    c.execute("UPDATE transactions SET trip_id='A',display_tab_id='B' WHERE transaction_id=?", (tid,))
    c.commit()
    manifest = make_manifest([correction_for(c, tid, 'B')])
    plan = repair.preview(c, TRIPS, manifest)
    assert plan['summary']['to_apply'] == 0
    assert plan['summary']['excluded'].get('PROJECTION_ATTRIBUTION_DISAGREEMENT') == 1


def test_invalid_quarter_target(setup):
    c = setup[0].conn
    prepare(c)
    tid = setup[3][0]['transaction_id']
    # payment date 2026-09-30 → quarter:2026:3; targeting Q4 is invalid
    manifest = make_manifest([correction_for(c, tid, 'quarter:2026:4')])
    plan = repair.preview(c, TRIPS, manifest)
    assert plan['summary']['excluded'].get('INVALID_TARGET') == 1
    # Q2 is before the open boundary
    manifest2 = make_manifest([correction_for(c, tid, 'quarter:2026:2')])
    plan2 = repair.preview(c, TRIPS, manifest2)
    assert plan2['summary']['excluded'].get('INVALID_TARGET') == 1


def test_duplicate_correction_fails(setup):
    c = setup[0].conn
    prepare(c)
    tid = setup[3][0]['transaction_id']
    corr = correction_for(c, tid, 'B')
    manifest = make_manifest([corr, dict(corr)])
    with pytest.raises(ValueError, match='DUPLICATE_CORRECTION'):
        repair.preview(c, TRIPS, manifest)


def test_refund_group_moves_when_all_members_present(setup):
    from webapp.tests.test_closed_period_grouping import refund_pair
    c, purchase, refund = refund_pair(setup)
    # Move both to open period for AI review eligibility
    c.execute("UPDATE transactions SET approval_date='2026-09-30',classification_state='classified',"
              "classification_source='inference',item='식비',trip_id='A',display_tab_id='A',"
              "classification_basis='AUTO_INFERRED · 합성',decided_at=NULL WHERE transaction_id IN (?,?)", (purchase, refund))
    c.commit()
    manifest = make_manifest([correction_for(c, purchase, 'B'), correction_for(c, refund, 'B')])
    plan = repair.preview(c, TRIPS, manifest)
    assert {purchase, refund} <= {t['tid'] for t in plan['targets']}
    assert plan['summary']['refund_move_rows'] == 2
    assert plan['summary']['refund_move_groups'] == 1
    financial = repair._financial_state(c)
    repair.apply(c, plan, TRIPS, manifest, request_id='synthetic-refund')
    assert repair._state(c, purchase)['transaction']['trip_id'] == 'B'
    assert repair._state(c, refund)['transaction']['trip_id'] == 'B'
    assert repair._financial_state(c) == financial


def test_refund_group_excluded_when_partial(setup):
    from webapp.tests.test_closed_period_grouping import refund_pair
    c, purchase, refund = refund_pair(setup)
    c.execute("UPDATE transactions SET approval_date='2026-09-30',classification_state='classified',"
              "classification_source='inference',item='식비',trip_id='A',display_tab_id='A',"
              "classification_basis='AUTO_INFERRED · 합성',decided_at=NULL WHERE transaction_id IN (?,?)", (purchase, refund))
    c.commit()
    # Only purchase in manifest, refund missing → whole group excluded
    manifest = make_manifest([correction_for(c, purchase, 'B')])
    plan = repair.preview(c, TRIPS, manifest)
    assert purchase not in {t['tid'] for t in plan['targets']}
    assert plan['summary']['excluded'].get('REFUND_INELIGIBLE_MEMBER', 0) >= 1


def test_refund_group_excluded_when_destination_differs(setup):
    from webapp.tests.test_closed_period_grouping import refund_pair
    c, purchase, refund = refund_pair(setup)
    c.execute("UPDATE transactions SET approval_date='2026-09-30',classification_state='classified',"
              "classification_source='inference',item='식비',trip_id='A',display_tab_id='A',"
              "classification_basis='AUTO_INFERRED · 합성',decided_at=NULL WHERE transaction_id IN (?,?)", (purchase, refund))
    c.commit()
    manifest = make_manifest([correction_for(c, purchase, 'B'), correction_for(c, refund, 'quarter:2026:3')])
    plan = repair.preview(c, TRIPS, manifest)
    assert not {purchase, refund} & {t['tid'] for t in plan['targets']}
    assert plan['summary']['excluded'].get('REFUND_DESTINATION_DISAGREEMENT', 0) == 2


def test_financial_tables_unchanged(setup):
    c = setup[0].conn
    prepare(c)
    financial = repair._financial_state(c)
    tids = [r['transaction_id'] for r in setup[3]]
    manifest = make_manifest([correction_for(c, tid, 'B') for tid in tids])
    plan = repair.preview(c, TRIPS, manifest)
    repair.apply(c, plan, TRIPS, manifest, request_id='synthetic-financial')
    assert repair._financial_state(c) == financial
    # source fields preserved
    for tid in tids:
        row = repair._state(c, tid)['transaction']
        assert row['amount_krw'] > 0 and row['source_hash']


def test_preview_is_read_only(setup):
    c = setup[0].conn
    prepare(c)
    before = '\n'.join(c.iterdump())
    tid = setup[3][0]['transaction_id']
    manifest = make_manifest([correction_for(c, tid, 'B')])
    repair.preview(c, TRIPS, manifest)
    assert '\n'.join(c.iterdump()) == before


def test_digest_mismatch_rejected(setup):
    c = setup[0].conn
    prepare(c)
    tid = setup[3][0]['transaction_id']
    manifest = make_manifest([correction_for(c, tid, 'B')])
    plan = repair.preview(c, TRIPS, manifest)
    bad = dict(plan, digest='0' * 64)
    with pytest.raises(ValueError, match='AI_REVIEW_PREVIEW_STALE'):
        repair.apply(c, bad, TRIPS, manifest, request_id='synthetic-stale')


def test_replay_returns_zero_changes(setup):
    c = setup[0].conn
    prepare(c)
    tid = setup[3][0]['transaction_id']
    manifest = make_manifest([correction_for(c, tid, 'B')])
    plan = repair.preview(c, TRIPS, manifest)
    repair.apply(c, plan, TRIPS, manifest, request_id='synthetic-replay')
    result = repair.apply(c, plan, TRIPS, manifest, request_id='synthetic-replay')
    assert result['replay'] is True and result['applied_this_run'] == 0
    assert repair.replay(c, 'synthetic-replay')['to_apply'] == 1


def test_request_conflict_on_different_digest(setup):
    c = setup[0].conn
    prepare(c)
    tid = setup[3][0]['transaction_id']
    manifest = make_manifest([correction_for(c, tid, 'B')])
    plan = repair.preview(c, TRIPS, manifest)
    repair.apply(c, plan, TRIPS, manifest, request_id='synthetic-conflict')
    manifest2 = make_manifest([correction_for(c, tid, 'B', item='교통비')])
    plan2 = repair.preview(c, TRIPS, manifest2)
    with pytest.raises(ValueError, match='AI_REVIEW_REQUEST_CONFLICT'):
        repair.apply(c, plan2, TRIPS, manifest2, request_id='synthetic-conflict')


def test_restore_reverts_and_stale_restore_rejected(setup):
    c, batch = setup[0].conn, setup[2]
    prepare(c)
    tid = setup[3][0]['transaction_id']
    add_projection(c, tid, batch)
    before = repair._state(c, tid)
    manifest = make_manifest([correction_for(c, tid, 'B', item='숙박비')])
    plan = repair.preview(c, TRIPS, manifest)
    repair.apply(c, plan, TRIPS, manifest, request_id='synthetic-restore')
    # Restore
    rplan = repair.restore_preview(c, 'synthetic-restore')
    assert rplan['summary']['restore'] == 1
    repair.restore(c, rplan, 'synthetic-restore')
    after = repair._state(c, tid)
    assert {k: v for k, v in after['transaction'].items() if k != 'revision'} == \
           {k: v for k, v in before['transaction'].items() if k != 'revision'}
    assert after['ledger'] == before['ledger']
    # Board payload restored (revision differs)
    a, b = json.loads(after['board']['payload_json']), json.loads(before['board']['payload_json'])
    assert {k: v for k, v in a.items() if k != 'revision'} == {k: v for k, v in b.items() if k != 'revision'}
    # Stale restore: edit after apply then try restore
    manifest2 = make_manifest([correction_for(c, tid, 'B')])
    plan2 = repair.preview(c, TRIPS, manifest2)
    repair.apply(c, plan2, TRIPS, manifest2, request_id='synthetic-restore2')
    c.execute("UPDATE transactions SET item='변경' WHERE transaction_id=?", (tid,))
    c.commit()
    with pytest.raises(ValueError, match='AI_REVIEW_RESTORE_STALE'):
        repair.restore_preview(c, 'synthetic-restore2')


def test_no_change_excluded(setup):
    c = setup[0].conn
    prepare(c)
    tid = setup[3][0]['transaction_id']
    manifest = make_manifest([correction_for(c, tid, 'B')])
    plan = repair.preview(c, TRIPS, manifest)
    repair.apply(c, plan, TRIPS, manifest, request_id='synthetic-nochange')
    # Same target again with updated revision → NO_CHANGE
    manifest2 = make_manifest([correction_for(c, tid, 'B')])
    plan2 = repair.preview(c, TRIPS, manifest2)
    assert plan2['summary']['to_apply'] == 0
    assert plan2['summary']['excluded'].get('NO_CHANGE') == 1


def test_manifest_in_repository_rejected(tmp_path, monkeypatch):
    import tools.apply_ai_quarter_review as tool
    monkeypatch.setattr(tool, 'REPO_ROOT', tmp_path)
    inside = tmp_path / 'manifest.json'
    inside.write_text('{"review_id":"x","reviewer":{"provider":"a","model":"b","effort":"high"},"corrections":[]}', encoding='utf-8')
    with pytest.raises(ValueError, match='MANIFEST_IN_REPOSITORY'):
        tool.load_manifest(inside)
    outside = tmp_path.parent / 'outside-manifest.json'
    outside.write_text('{"review_id":"x","reviewer":{"provider":"a","model":"b","effort":"high"},"corrections":[]}', encoding='utf-8')
    loaded = tool.load_manifest(outside)
    assert loaded['review_id'] == 'x'
    outside.unlink()


def test_mid_apply_failure_is_atomic(setup):
    c = setup[0].conn
    prepare(c)
    tid = setup[3][0]['transaction_id']
    manifest = make_manifest([correction_for(c, tid, 'B')])
    plan = repair.preview(c, TRIPS, manifest)
    before = '\n'.join(c.iterdump())
    c.execute("CREATE TEMP TRIGGER reject_ai BEFORE UPDATE ON transactions WHEN OLD.transaction_id='" + tid +
              "' BEGIN SELECT RAISE(ABORT,'synthetic failure'); END")
    with pytest.raises(sqlite3.IntegrityError, match='synthetic failure'):
        repair.apply(c, plan, TRIPS, manifest, request_id='synthetic-atomic')
    assert '\n'.join(c.iterdump()) == before


def test_excess_refund_group_excluded(setup):
    from webapp.tests.test_closed_period_grouping import refund_pair
    c, purchase, refund = refund_pair(setup)
    c.execute("UPDATE transactions SET approval_date='2026-09-30',classification_state='classified',"
              "classification_source='inference',item='식비',trip_id='A',display_tab_id='A',"
              "classification_basis='AUTO_INFERRED · 합성',decided_at=NULL WHERE transaction_id IN (?,?)", (purchase, refund))
    c.execute('UPDATE transactions SET amount_krw=amount_krw-500 WHERE transaction_id=?', (refund,))
    c.commit()
    manifest = make_manifest([correction_for(c, purchase, 'B'), correction_for(c, refund, 'B')])
    plan = repair.preview(c, TRIPS, manifest)
    assert not {purchase, refund} & {t['tid'] for t in plan['targets']}
    assert plan['summary']['excluded'].get('REFUND_UNVERIFIED_OR_EXCESS') == 2


@pytest.mark.parametrize('kind', ['review_decision', 'board_override'])
def test_manual_history_and_override_exclude(setup, kind):
    c = setup[0].conn
    prepare(c)
    tid = setup[3][0]['transaction_id']
    if kind == 'review_decision':
        c.execute('INSERT INTO review_decisions(transaction_id,revision,item,description,display_tab_id,note,reuse_rule,decided_at) '
                  "VALUES (?,99,'식비','','A','',0,'synthetic')", (tid,))
    else:
        c.execute("INSERT INTO board_manual_overrides(row_id,field,event_id) VALUES (?,'item','synthetic')", ('card-' + tid,))
    c.commit()
    manifest = make_manifest([correction_for(c, tid, 'B')])
    plan = repair.preview(c, TRIPS, manifest)
    assert plan['summary']['to_apply'] == 0
    assert plan['summary']['excluded'].get('MANUAL_OR_USER_EXCEPTION') == 1


def test_quarter_to_quarter_reports_net_changes(setup):
    c = setup[0].conn
    prepare(c)
    tid = setup[3][0]['transaction_id']
    c.execute("UPDATE transactions SET trip_id='',display_tab_id='quarter:2026:4',item='분기 기타비용' WHERE transaction_id=?", (tid,))
    c.commit()
    manifest = make_manifest([correction_for(c, tid, 'quarter:2026:3')])
    plan = repair.preview(c, TRIPS, manifest)
    assert plan['summary']['kinds'] == {'quarter_to_quarter': 1}
    assert plan['summary']['quarter_increases'] == {'quarter:2026:3': 1, 'quarter:2026:4': -1}


def test_summary_has_no_identifiers_or_amounts(setup):
    c = setup[0].conn
    prepare(c)
    tids = [r['transaction_id'] for r in setup[3]]
    manifest = make_manifest([correction_for(c, tid, 'B') for tid in tids])
    plan = repair.preview(c, TRIPS, manifest)
    text = json.dumps(plan['summary'], ensure_ascii=False)
    for tid in tids:
        assert tid not in text
    assert 'SYNTHETIC' not in text and '1000' not in text
    assert plan['summary']['manifest_rows'] == 5 and plan['summary']['to_apply'] == 5


def test_digest_binds_manifest_and_financial_state(setup):
    c = setup[0].conn
    prepare(c)
    tid = setup[3][0]['transaction_id']
    manifest = make_manifest([correction_for(c, tid, 'B')])
    plan = repair.preview(c, TRIPS, manifest)
    other = make_manifest([correction_for(c, tid, 'B', basis='TRIP-002 · 다른 근거')])
    assert repair.preview(c, TRIPS, other)['digest'] != plan['digest']
    # _financial_state binds the refund graph and protection records; a new hold
    # on a non-target row must move the digest.
    other_row = repair._state(c, setup[3][1]['transaction_id'])['transaction']
    c.execute('INSERT INTO transaction_review_holds VALUES (?,?,?,?)',
              (other_row['transaction_id'], other_row['source_hash'], 'user_hold', 'synthetic'))
    c.commit()
    assert repair.preview(c, TRIPS, manifest)['digest'] != plan['digest']
