import copy
import json

import pytest

from app import ai_classification, p2_case
from tests.test_p2_case import prepared
from webapp.tests.test_autonomous_cleanup import setup


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
