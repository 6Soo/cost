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
