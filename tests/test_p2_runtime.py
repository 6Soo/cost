import copy
import json

import pytest

from app import ai_classification, p2_case
from tests.test_p2_case import prepared
from webapp.tests.test_autonomous_cleanup import setup, receive, make_weak_rows


def response(request, bundle):
    return dict(request_digest=request['digest'], more_evidence=[],
        execution=dict(kind='connected_agent', provider='codex', model='gpt-6.1-sol', run_id='synthetic'),
        results=[dict(transaction_id=c['transaction_id'], trip_id=c['trips'][0]['trip_id'], item='교통비',
                      service_start='2026-10-02', service_end='2026-10-03', evidence_refs=[],
                      rule_ids=['PROC-001'], basis='합성 원문 대조', uncertainty='합성 검증')
                 for c in request['cases']])


def test_service_and_evidence_metadata_saved_atomically_without_original_changes(setup):
    request, trips = prepared(setup)
    bundle = p2_case.assemble(setup.conn, trips, request)
    answer = response(request, bundle)
    before = setup.conn.execute('SELECT source_hash,amount_krw,raw_row_json FROM transactions').fetchall()
    result = ai_classification.apply(setup.conn, trips, request, answer, bundle=bundle, request_id='p2-synthetic')
    assert result['applied'] == 1
    assert setup.conn.execute('SELECT source_hash,amount_krw,raw_row_json FROM transactions').fetchall() == before
    basis = setup.conn.execute('SELECT classification_basis FROM transactions').fetchone()[0]
    assert '2026-10-02' in basis and 'PROC-001' in basis and 'synthetic' in basis
    audit = json.loads(setup.conn.execute("SELECT detail_json FROM change_log WHERE kind='card.classification_corrected'").fetchone()[0])
    assert audit['p2_metadata']['service_end'] == '2026-10-03'
    assert audit['p2_metadata']['case_digest'] == bundle['digest']
    assert ai_classification.apply(setup.conn, trips, request, answer, bundle=bundle, request_id='p2-synthetic')['replay']


def test_recorded_open_trip_item_only_correction_requires_explicit_opt_in(setup):
    from app import classification_correction
    from webapp.card_flow import CardFlow
    board = setup
    trip = board.create_trip(starts_on='2026-10-01', ends_on='2026-10-05',
                             destination='합성 여행', client_request_id='stage2-trip')
    trip = trip['tab_id']
    batch, rows = receive(board, 1)
    ids = make_weak_rows(board, batch, rows, trip, item='현지경비')
    CardFlow(board).auto_record(batch)
    tid = ids[0]
    cur = board.conn.execute('SELECT transaction_id,source_hash,revision,trip_id,display_tab_id FROM transactions WHERE transaction_id=?', (tid,))
    row = dict(zip((d[0] for d in cur.description), cur.fetchone()))
    correction = dict(transaction_id=tid, source_hash=row['source_hash'], revision=row['revision'],
                      trip_id=trip, item='식비', basis='합성 단계2', classification_source='ai_inference',
                      execution=dict(kind='connected_agent', provider='codex', model='gpt-6.1-sol', run_id='stage2'))
    cur = board.conn.execute('SELECT * FROM trip_tabs')
    trips = [dict(zip((d[0] for d in cur.description), r), trip_id=r[0]) for r in cur.fetchall()]
    with pytest.raises(ValueError, match='CORRECTION_PROTECTED'):
        classification_correction.preview(board.conn, [correction], trips)
    expected = classification_correction.preview(board.conn, [correction], trips, allow_recorded_ai=True)
    before = board.conn.execute('SELECT amount_krw,source_hash,raw_row_json,trip_id FROM transactions WHERE transaction_id=?', (tid,)).fetchone()
    result = classification_correction.apply(board.conn, expected, [correction], trips,
                                              request_id='stage2-recorded', allow_recorded_ai=True)
    assert result['applied'] == 1
    after = board.conn.execute('SELECT amount_krw,source_hash,raw_row_json,trip_id,item,classification_source FROM transactions WHERE transaction_id=?', (tid,)).fetchone()
    assert after[:4] == before and after[4:] == ('식비', 'ai_inference')
    replay = classification_correction.apply(board.conn, expected, [correction], trips,
                                              request_id='stage2-recorded', allow_recorded_ai=True)
    assert replay['replay'] is True and replay['applied'] == 0


@pytest.mark.parametrize('mutation', ['closed', 'manual', 'trip', 'amount'])
def test_recorded_p2_opt_in_keeps_protections(setup, mutation):
    from app import classification_correction
    from webapp.card_flow import CardFlow
    board = setup
    starts = '2026-06-01' if mutation == 'closed' else '2026-10-01'
    trip = board.create_trip(starts_on=starts, ends_on='2026-10-05', destination='합성',
                             client_request_id='protect-' + mutation)['tab_id']
    batch, rows = receive(board, 1)
    ids = make_weak_rows(board, batch, rows, trip, item='현지경비')
    CardFlow(board).auto_record(batch)
    tid = ids[0]
    if mutation == 'manual':
        board.conn.execute("UPDATE transactions SET classification_source='user_decision', decided_at='2026-10-01' WHERE transaction_id=?", (tid,))
        board.conn.commit()
    cur = board.conn.execute('SELECT * FROM transactions WHERE transaction_id=?', (tid,))
    row = dict(zip((d[0] for d in cur.description), cur.fetchone()))
    correction = dict(transaction_id=tid, source_hash=row['source_hash'], revision=row['revision'],
                      trip_id=('other-trip' if mutation == 'trip' else trip), item='식비', basis='합성',
                      classification_source='ai_inference', execution=dict(kind='connected_agent', provider='codex', model='gpt-6.1-sol', run_id='protect'))
    if mutation == 'amount':
        correction['amount_krw'] = 1
    cur = board.conn.execute('SELECT * FROM trip_tabs')
    trips = [dict(zip((d[0] for d in cur.description), r), trip_id=r[0]) for r in cur.fetchall()]
    with pytest.raises(ValueError):
        classification_correction.preview(board.conn, [correction], trips, allow_recorded_ai=True)


def test_recorded_quarter_q3_item_only_correction_is_allowed(setup):
    from app import classification_correction
    from webapp.card_flow import CardFlow
    board = setup
    batch, rows = receive(board, 1)
    ids = make_weak_rows(board, batch, rows, 'quarter:2026:4', item='현지경비')
    CardFlow(board).auto_record(batch)
    tid = ids[0]
    cur = board.conn.execute('SELECT * FROM transactions WHERE transaction_id=?', (tid,))
    row = dict(zip((d[0] for d in cur.description), cur.fetchone()))
    correction = dict(transaction_id=tid, source_hash=row['source_hash'], revision=row['revision'],
                      trip_id='quarter:2026:4', item='식비', basis='합성 분기',
                      classification_source='ai_inference', execution=dict(kind='connected_agent', provider='codex', model='gpt-6.1-sol', run_id='quarter'))
    cur = board.conn.execute('SELECT * FROM trip_tabs')
    trips = [dict(zip((d[0] for d in cur.description), r), trip_id=r[0]) for r in cur.fetchall()]
    expected = classification_correction.preview(board.conn, [correction], trips, allow_recorded_ai=True)
    assert expected['count'] == 1


@pytest.mark.parametrize('changes', [
    {'service_start': '2026-02-30'}, {'service_end': '2026-10-01'},
    {'evidence_refs': ['mail:unknown']}, {'rule_ids': ['INVENTED-999']},
    {'trip_id': 'fake-trip'}, {'item': 'fake-item'},
])
def test_invalid_metadata_rejected_before_any_write(setup, changes):
    request, trips = prepared(setup)
    bundle = p2_case.assemble(setup.conn, trips, request)
    answer = response(request, bundle)
    answer['results'][0].update(changes)
    before = '\n'.join(setup.conn.iterdump())
    with pytest.raises(ValueError):
        ai_classification.apply(setup.conn, trips, request, answer, bundle=bundle, request_id='bad')
    assert '\n'.join(setup.conn.iterdump()) == before


def test_raw_change_even_without_revision_invalidates_bundle(setup):
    request, trips = prepared(setup)
    bundle = p2_case.assemble(setup.conn, trips, request)
    setup.conn.execute("UPDATE transactions SET raw_row_json='{}'")
    with pytest.raises(ValueError, match='AI_CASE_STALE'):
        ai_classification.preview(setup.conn, trips, request, response(request, bundle), bundle=bundle)


def test_partial_more_evidence_cannot_apply(setup):
    request, trips = prepared(setup)
    bundle = p2_case.assemble(setup.conn, trips, request)
    answer = response(request, bundle)
    answer['results'] = []
    answer['more_evidence'] = [dict(kind='mail_search', transaction_id=request['cases'][0]['transaction_id'], query='예약', why='기간')]
    with pytest.raises(ValueError, match='AI_MORE_EVIDENCE_PENDING'):
        ai_classification.apply(setup.conn, trips, request, answer, bundle=bundle, request_id='pending')


def test_quarter_decision_without_actual_trip_is_supported(setup):
    from webapp.tests.test_autonomous_cleanup import receive, make_weak_rows
    batch, rows = receive(setup, 1)
    ids = make_weak_rows(setup, batch, rows, '', item='분기 기타비용')
    from app import automatic_classification
    plan = automatic_classification.plan(setup.conn, [], transaction_ids=ids)
    automatic_classification.apply(setup.conn, plan, [], transaction_ids=ids)
    request = ai_classification.prepare(setup.conn, [], ids)
    bundle = p2_case.assemble(setup.conn, [], request)
    answer = response(request, bundle)
    answer['results'][0]['item'] = '분기 기타비용'
    ai_classification.apply(setup.conn, [], request, answer, bundle=bundle, request_id='quarter')
    assert setup.conn.execute('SELECT display_tab_id,trip_id FROM transactions').fetchone() == ('quarter:2026:4', '')


def test_p2_period_reaches_existing_preview_and_actual_stay_label(setup, monkeypatch):
    from app import ledger
    from webapp import ledger_design, ledger_stay_evidence, ota_payment_review
    from webapp.read_scope import scoped
    request, trips = prepared(setup)
    bundle = p2_case.assemble(setup.conn, trips, request)
    answer = response(request, bundle)
    answer['results'][0]['item'] = '숙박비'
    ai_classification.apply(setup.conn, trips, request, answer, bundle=bundle, request_id='display-period')
    tid = request['cases'][0]['transaction_id']
    batch = setup.conn.execute('SELECT batch_id FROM transactions WHERE transaction_id=?',(tid,)).fetchone()[0]
    preview = ledger.preview(setup, batch, trip_validator=lambda _: True, tab_validator=lambda _: True)
    entry = next(row for row in preview['rows'] if row['transaction_id'] == tid)
    assert entry['service_period'] == '2026-10-02~2026-10-03'
    assert entry['ota_evidence']['execution']['model'] == 'gpt-6.1-sol'
    assert entry['occurred_on'] == '2026-10-03'  # Approval date stays original.
    monkeypatch.setattr(ota_payment_review, 'enabled', lambda: False)
    monkeypatch.setattr(ledger_design.board, '_active_store', lambda: setup)
    row = dict(row_id='card-'+tid, source_event_id=tid, item='숙박비',service_period='')
    before = setup.conn.total_changes
    @scoped
    def render():
        return ledger_design._stay_text(row)
    assert render() == '10월 2일(금) ~ 10월 3일(토) · 1박 · 예약 근거 추론'
    assert setup.conn.total_changes == before
    setup.conn.execute("INSERT INTO board_manual_overrides VALUES (?,'service_period','synthetic-empty-correction')", ('card-'+tid,))
    assert ledger_stay_evidence.period_for(row, ledger_stay_evidence.stay_index(setup)) == ''


@pytest.mark.parametrize('mutation', ['source', 'revision', 'item', 'run_id'])
def test_stale_or_forged_saved_period_is_not_displayed(setup, mutation):
    request, trips = prepared(setup)
    bundle = p2_case.assemble(setup.conn, trips, request)
    answer = response(request, bundle)
    answer['results'][0]['item'] = '숙박비'
    ai_classification.apply(setup.conn, trips, request, answer, bundle=bundle, request_id='period-stale')
    tid = request['cases'][0]['transaction_id']
    assert ai_classification.service_metadata(setup.conn, tid)['service_period']
    if mutation == 'source':
        setup.conn.execute("UPDATE transactions SET source_hash='changed'")
    elif mutation == 'revision':
        setup.conn.execute('UPDATE transactions SET revision=revision+1')
    elif mutation == 'item':
        setup.conn.execute("UPDATE transactions SET item='식비'")
    else:
        setup.conn.execute("UPDATE transactions SET classification_basis=replace(classification_basis,'synthetic','forged')")
    assert ai_classification.service_metadata(setup.conn, tid) == {}


def test_exact_ota_or_explicit_stored_period_wins_over_p2():
    from webapp import ledger_stay_evidence as stays
    inferred = dict(service_period='2026-10-02~2026-10-03',
        ota_evidence=dict(source='P2', kind='reservation_period_inferred', item='숙박비', source_hash='synthetic'))
    exact = dict(service_period='2026-10-04~2026-10-05', booking_ref='synthetic-booking', ota_evidence=dict(kind='exact'))
    combined = stays._with_p2({'synthetic': exact}, {'synthetic': inferred}, {})
    row = dict(row_id='card-synthetic', source_event_id='synthetic', item='숙박비')
    assert stays.period_for(row, combined) == '2026-10-04~2026-10-05'
    assert stays.period_for(dict(row, service_period='2026-10-06~2026-10-07'), combined) == '2026-10-06~2026-10-07'
    assert stays._with_p2({}, {'synthetic': inferred}, {'transactions': [dict(transaction_id='synthetic', period_conflict=True)]}) == {}
