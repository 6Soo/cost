import json

from app.accounting_audit import audit_cards


def inputs():
    card=dict(transaction_id='syn',source_hash='hash',amount_krw=120,transaction_direction='purchase',
              approval_date='2026-07-12',item='숙박비',display_tab_id='A')
    entry=dict(card)
    payload=dict(amount_krw=120,source_fact_digest='hash',source_event_id='syn',item='숙박비',display_tab_id='A')
    board=dict(row_id='card-syn',display_tab_id='A',payload_json=json.dumps(payload))
    trips=[dict(tab_id='A',starts_on='2026-07-12',ends_on='2026-07-16')]
    return [card],[entry],[board],trips


def test_correct_financial_projections_have_no_findings_and_inputs_are_unchanged():
    data=inputs();before=json.dumps(data)
    assert audit_cards(*data)['finding_count']==0
    assert json.dumps(data)==before


def test_manual_difference_is_included_and_separate_from_financial_conflict():
    data=inputs();data[2][0]['display_tab_id']='B'
    payload=json.loads(data[2][0]['payload_json']);payload.update(display_tab_id='B',amount_krw=121)
    data[2][0]['payload_json']=json.dumps(payload)
    report=audit_cards(*data,manual_fields={('card-syn','display_tab_id')})
    assert report['counts']['BOARD_FINANCIAL_SOURCE_CONFLICT']==1
    assert report['categories']['manual_difference']==1
    assert report['financial_writes']==0


def test_unrecorded_completed_sources_and_open_sources_are_distinct():
    data=inputs();old=dict(data[0][0],transaction_id='old',approval_date='2026-01-01')
    report=audit_cards([*data[0],old],[],[],data[3])
    assert report['counts']=={'COMPLETED_SOURCE_UNRECORDED':1,'OPEN_SOURCE_UNRECORDED':1}


def test_duplicate_id_cannot_silently_disappear_and_refund_tab_is_not_a_refund():
    data=inputs();data[0][0]['display_tab_id']='refunds'
    report=audit_cards(data[0]*2,[],[],data[3])
    assert report['counts']['CARD_IDENTITY_REPEATED']==1
    assert report['counts']['REFUND_TAB_REQUIRES_ORIGINAL_EVIDENCE']==1


def test_manual_period_conflict_is_checked_against_actual_trip():
    data=inputs();payload=json.loads(data[2][0]['payload_json'])
    payload['service_period']=dict(starts_on='2026-08-06',ends_on='2026-08-11')
    data[2][0]['payload_json']=json.dumps(payload)
    assert audit_cards(*data,manual_fields={('card-syn','display_tab_id')})['counts']=={'SERVICE_PERIOD_OUTSIDE_TRIP':1}


def test_ledger_trip_and_board_attribution_splits_are_reported():
    data = inputs()
    data[1][0]['trip_id'] = 'ledger-trip'
    payload = json.loads(data[2][0]['payload_json'])
    payload['display_tab_id'] = 'board-tab'
    data[2][0]['display_tab_id'] = 'board-tab'
    data[2][0]['payload_json'] = json.dumps(payload)
    report = audit_cards(*data)
    assert report['counts']['LEDGER_CLASSIFICATION_DIFFERENCE'] == 1
    assert report['counts']['LEDGER_BOARD_ATTRIBUTION_SPLIT'] == 1


def test_missing_board_source_identity_is_a_source_gap():
    data = inputs()
    payload = json.loads(data[2][0]['payload_json'])
    payload.pop('source_fact_digest')
    payload.pop('source_event_id')
    data[2][0]['payload_json'] = json.dumps(payload)
    report = audit_cards(*data)
    assert report['counts']['BOARD_SOURCE_EVIDENCE_MISSING'] == 1
    assert 'BOARD_FINANCIAL_SOURCE_CONFLICT' not in report['counts']
