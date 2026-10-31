import copy

from webapp.insurance_income_match_service import build_state, _income_context


def inputs():
    review = {'fingerprint': 'manifest-fp', 'contracts': [{
        'contract_key': 'opaque-contract', 'travel_start': '2026-10-01', 'travel_end': '2026-10-05',
        'cost_trip_id': None, 'already_registered': False, 'insurance_status': 'completed_or_expired',
        'rows': [{'review_row_id': 'opaque-row', 'masked_name': '가*다'}]}]}
    trips = [{'tab_id': 'trip-a', 'display_key': '합성 여행', 'starts_on': '2026-10-01', 'ends_on': '2026-10-06'},
             {'tab_id': 'trip-b', 'display_key': '별도 여행', 'starts_on': '2026-11-01', 'ends_on': '2026-11-06'}]
    context = {'rows_by_trip': {tid: [{'ref': tid+'|1', 'fingerprint': tid+'-fp', 'name': '가나다',
                                    'nickname': '', 'trip_id': tid, 'trip_name': tid, 'amount': 1000}]
                               for tid in ('trip-a', 'trip-b')},
               'blocked_trip_ids': set(), 'generation': 'generation-one', 'mapping': {}, 'choices': {}}
    return review, trips, context


def test_period_scoped_matching_and_explicit_trip_filter_do_not_mutate_sources():
    review, trips, context = inputs()
    original = copy.deepcopy((review, trips, context))
    result = build_state(review=review, trips=trips, context=context)
    row = result['contracts'][0]['rows'][0]
    assert row['match_state'] == 'matched'
    assert row['matches'][0]['trip_id'] == 'trip-a'
    selected = build_state({'trip': ['trip-b']}, review=review, trips=trips, context=context)
    assert selected['contracts'][0]['rows'][0]['matches'][0]['trip_id'] == 'trip-b'
    assert selected['fingerprint'] != result['fingerprint']
    assert (review, trips, context) == original


def test_missing_source_is_not_reported_as_no_match_or_unique_from_partial_data():
    review, trips, context = inputs()
    context['blocked_trip_ids'] = {'trip-a'}
    result = build_state(review=review, trips=trips, context=context)
    assert result['code'] == 'PARTIAL'
    assert result['counts']['source_unavailable'] == 1
    assert result['contracts'][0]['rows'][0]['match_state'] == 'source_unavailable'
    assert result['counts']['matched'] == result['counts']['unmatched'] == 0


def test_unknown_mapping_does_not_search_unrelated_trip():
    review, trips, context = inputs()
    review['contracts'][0]['cost_trip_id'] = 'trip-missing'
    result = build_state(review=review, trips=trips, context=context)
    assert result['counts']['source_unavailable'] == 1


def test_all_existing_trips_used_only_when_no_period_candidate_and_ambiguity_kept():
    review, trips, context = inputs()
    review['contracts'][0]['travel_start'] = '2025-01-01'
    review['contracts'][0]['travel_end'] = '2025-01-03'
    result = build_state(review=review, trips=trips, context=context)
    assert result['contracts'][0]['rows'][0]['match_state'] == 'ambiguous'
    assert result['contracts'][0]['rows'][0]['candidate_count'] == 2


def test_no_configuration_and_invalid_trip_fail_without_reading_income(monkeypatch):
    monkeypatch.delenv('WEBLEDGER_INSURANCE_REVIEW_MANIFEST', raising=False)
    assert build_state()['code'] == 'REVIEW_NOT_CONFIGURED'
    review, trips, context = inputs()
    assert build_state({'trip': ['not-a-trip']}, review=review, trips=trips, context=context)['code'] == 'INVALID_FILTER'


def test_fingerprint_changes_when_income_generation_or_cell_fingerprint_changes():
    review, trips, context = inputs()
    first = build_state(review=review, trips=trips, context=context)['fingerprint']
    context['generation'] = 'generation-two'
    second = build_state(review=review, trips=trips, context=context)['fingerprint']
    assert first != second
    context['rows_by_trip']['trip-a'][0]['fingerprint'] = 'changed-name'
    assert build_state(review=review, trips=trips, context=context)['fingerprint'] != second


def test_consistent_original_income_rows_match_even_without_separate_name_index(monkeypatch):
    from app import google_authority
    from webapp import google_ledger_page as google
    calls = []
    monkeypatch.setattr(google, 'enabled', lambda: True)
    monkeypatch.setattr(google, 'snapshot_path', lambda: 'synthetic-snapshot')
    monkeypatch.setattr(google, 'rows_path', lambda: 'synthetic-rows')
    def consistent(*args):
        calls.append(True)
        return {'rows_generation': 'one'}, {}
    monkeypatch.setattr(google_authority, 'load_consistent', consistent)
    monkeypatch.setattr(google, 'load_mapping', lambda path: {'sheet-one': 'trip-a'})
    monkeypatch.setattr(google, 'load_choices', lambda path: {})
    monkeypatch.setattr(google, 'snapshot_for_display', lambda snapshot: snapshot)
    monkeypatch.setattr(google, 'owner_payload', lambda snapshot, choices: {
        'trips': [{'key': 'sheet-one', 'chosen_source': 'main'}],
        'sources': {'main': {'status': 'ok', 'stale': False}}})
    monkeypatch.setattr(google, 'owner_income_names', lambda *args: None)
    monkeypatch.setattr(google, 'owner_rows', lambda *args: {
        'income': [{'row': 5, 'date': '2026-09-01', 'name': '가나다', 'nickname': '합성', 'amount': None}]})
    review, trips, _ = inputs()
    context = _income_context(trips[:1])
    result = build_state(review=review, trips=trips[:1], context=context)
    assert calls == [True]
    assert result['counts']['matched'] == 1
    assert result['contracts'][0]['rows'][0]['matches'][0]['amount'] is None


def test_source_generation_failure_returns_safe_unavailable(monkeypatch):
    from webapp import insurance_income_match_service as service
    from app.google_authority import SnapshotError
    def mismatched(trips):
        raise SnapshotError('GENERATION_MISMATCH')
    monkeypatch.setattr(service, '_income_context', mismatched)
    review, trips, _ = inputs()
    result = build_state(review=review, trips=trips)
    assert result['available'] is False
    assert result['code'] == 'MATCH_SOURCE_UNAVAILABLE'


def test_contract_filter_scopes_api_and_counts_but_keeps_filter_choices():
    review, trips, context = inputs()
    second = copy.deepcopy(review['contracts'][0])
    second['contract_key'] = 'second-contract'
    review['contracts'].append(second)
    result = build_state({'contract_key': ['second-contract']}, review=review, trips=trips, context=context)
    assert [c['contract_key'] for c in result['contracts']] == ['second-contract']
    assert result['counts']['contracts'] == result['counts']['rows'] == 1
    assert len(result['contract_options']) == 2


def test_availability_and_trip_scope_changes_invalidate_result_fingerprint():
    review, trips, context = inputs()
    first = build_state(review=review, trips=trips, context=context)['fingerprint']
    context['blocked_trip_ids'] = {'trip-a'}
    assert build_state(review=review, trips=trips, context=context)['fingerprint'] != first


def test_inferred_period_miss_offers_other_trip_as_review_only_and_respects_explicit_scope():
    review, trips, context = inputs()
    context['rows_by_trip']['trip-a'][0]['name'] = '다른이'
    result = build_state(review=review, trips=trips, context=context)
    row = result['contracts'][0]['rows'][0]
    assert row['match_state'] == 'ambiguous' and row['outside_trip_scope']
    assert row['matches'][0]['trip_id'] == 'trip-b'
    assert result['counts']['matched'] == result['counts']['unmatched'] == 0
    selected = build_state({'trip': ['trip-a']}, review=review, trips=trips, context=context)
    assert selected['counts']['unmatched'] == 1
    review['contracts'][0]['cost_trip_id'] = 'trip-a'
    assert build_state(review=review, trips=trips, context=context)['counts']['unmatched'] == 1
