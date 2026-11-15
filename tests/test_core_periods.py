"""Bridge `periods` command: the columns it passes are the ones Rust reads, and its facts reproduce Python's verified period."""
import re
from pathlib import Path

from tools.core_bridge import periods
from tools.core_bridge.cli import handle
from tools.core_bridge.golden import _card, _event

RUST = Path(__file__).resolve().parents[1] / 'core' / 'crates' / 'core' / 'src' / 'period.rs'


def _rust_keys(name):
    body = re.search(rf'const {name}: \[&str; \d+\] = \[(.*?)\];', RUST.read_text(encoding='utf-8'), re.S).group(1)
    return tuple(re.findall(r'"([a-z_0-9]+)"', body))


def test_bridge_columns_match_the_rust_rule():
    assert periods.FACT_KEYS == _rust_keys('FACT_KEYS')
    assert periods.EVENT_KEYS == _rust_keys('EVENT_KEYS')
    assert periods.CARD_KEYS == _rust_keys('CARD_KEYS')


def _snapshot():
    event = _event('syn-e1', item='숙박비', reservation_status='confirmed')
    card = _card('syn-t1', source_hash='syn-hash-syn-t1')
    result = {'ota_event_id': 'syn-e1', 'transaction_id': 'syn-t1', 'status': 'MATCHED_AUTO'}
    return {'events': [event], 'transactions': [card], 'results': [result], 'links': {}}


def test_periods_returns_facts_and_the_python_verified_period_without_source_text():
    row = {'row_id': 'card-syn-t1', 'service_period': '', 'reservation_no': ''}
    response = handle('periods', {'data': _snapshot(), 'manual': [], 'rows': [row]}, sha='')
    assert response['ok']
    assert response['result']['verified'] == {'card-syn-t1': '2026-10-01~2026-10-03'}
    candidate = response['result']['facts']['syn-t1'][0]
    assert set(candidate['fact']) <= set(periods.FACT_KEYS)
    assert 'merchant' not in candidate['fact'] and 'amount_krw' not in candidate['card']
    assert candidate['manual'] is False and candidate['event_blocked'] is False


def test_manual_override_is_carried_as_a_flag():
    response = handle('periods', {'data': _snapshot(), 'manual': ['card-syn-t1']}, sha='')
    assert response['result']['facts']['syn-t1'][0]['manual'] is True
    assert 'verified' not in response['result']


def _pair():
    receipt = _event('syn-e1', item='', service_period=None, reservation_status='confirmed')
    stated = _event('syn-e2', item='', event_type='reservation', evidence_status='booking_only',
                    payment_status='pending', reservation_status='confirmed')
    card = _card('syn-t1', source_hash='syn-hash-syn-t1')
    result = {'ota_event_id': 'syn-e1', 'transaction_id': 'syn-t1', 'status': 'MATCHED_AUTO'}
    return {'events': [receipt, stated], 'transactions': [card], 'results': [result], 'links': {}}


def test_evidence_merges_inferred_periods_flights_and_p2_without_source_text():
    data = _pair()
    data['passengers'] = {'SYN-BOOK-1': {'legs': [{'departure_on': '2026-10-05'}, {'departure_on': '2026-10-01'}],
                                         'source_digests': ['syn-d1'], 'cancellation_status': 'NONE'}}
    p2 = periods.p2_index([{'transaction_id': 'syn-t2', 'service_period': '2026-10-04~2026-10-06', 'run_id': 'syn-run-1',
                            'model': 'syn-model', 'source_hash': 'syn-hash-syn-t2', 'item': '숙박비',
                            'decision_revision': 1, 'evidence_refs': ['mail text that must not travel']}])
    data['transactions'].append(_card('syn-t2', source_hash='syn-hash-syn-t2'))
    evidence = periods.evidence_from_snapshot(data, {'card-syn-t3'}, p2)
    assert evidence['syn-t1']['inferred']['basis'] == 'reservation_only'
    assert evidence['syn-t1']['inferred']['period'] == '2026-10-01~2026-10-03'
    assert evidence['syn-t1']['candidates'][0]['fact']['transaction_id'] == 'syn-t1'
    assert evidence['syn-t2']['inferred']['basis'] == 'p2_run'
    assert evidence['syn-t2']['candidates'] == []
    assert evidence['syn-t2']['inferred']['p2']['evidence_ref_count'] == 1
    assert evidence[periods.FLIGHTS_KEY] == {'days': {'SYN-BOOK-1': ['2026-10-01', '2026-10-05']}, 'manual': ['syn-t3']}
    assert 'mail text' not in str(evidence)


def test_evidence_without_inference_keeps_the_candidate_list_shape():
    evidence = periods.evidence_from_snapshot(_snapshot(), set())
    assert isinstance(evidence['syn-t1'], list) and periods.FLIGHTS_KEY not in evidence


def test_found_reports_verified_inferred_and_none_in_the_rule_order():
    rows = [{'row_id': 'card-syn-t1', 'service_period': '', 'reservation_no': '', 'item': '숙박비'}]
    found = periods.found_from_snapshot(_pair(), set(), rows)
    assert found == {'card-syn-t1': {'kind': 'inferred', 'period': '2026-10-01~2026-10-03', 'basis': 'reservation_only'}}
    assert periods.found_from_snapshot(_pair(), {'card-syn-t1'}, rows)['card-syn-t1']['kind'] == 'none'
    stored = [dict(rows[0], service_period='2026-09-01~2026-09-02')]
    assert periods.found_from_snapshot(_pair(), set(), stored)['card-syn-t1']['kind'] == 'verified'
