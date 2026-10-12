from copy import deepcopy
import pytest
from webapp import quarter_ledger as ql
from tests.card_pipeline.test_quarter_costs import row


@pytest.fixture
def target(monkeypatch):
    trip = {'key': '3분기_기타비용', 'kind': 'quarter', 'verified': True,
            'chosen_source': 'main', 'copies': {'main': {'layout': 'rev', 'ledger_year': 2026}}}
    monkeypatch.setattr(ql.google, 'enabled', lambda: True)
    monkeypatch.setattr(ql.google, '_snapshot_path', lambda: None)
    monkeypatch.setattr(ql.google_authority, 'load_snapshot', lambda p: {})
    monkeypatch.setattr(ql.google, 'snapshot_for_display', lambda s: s)
    monkeypatch.setattr(ql.google, 'load_choices', lambda p: {})
    monkeypatch.setattr(ql.google, 'owner_payload', lambda *a: {'trips': [trip]})
    return trip


def test_only_matching_year_and_available_quarter_can_be_copied(target):
    originals = [row(), dict(row(), transaction_id='oct', approval_date='2026-10-01')]
    options = ql.targets(originals)
    assert options[0]['available'] and not options[1]['available']
    state = {'rows': originals, 'preview': {'rows': [dict(row(), merchant='Synthetic', occurred_on='2026-09-30', blocked=None)]}}
    before = deepcopy(state)
    result = ql.export(state, 'quarter:2026:3')
    assert result['row_count'] == 1 and '3' in result['destination']['href']
    with pytest.raises(ValueError, match='NOT_READY'):
        ql.export(state, 'quarter:2026:4')
    target['copies']['main']['ledger_year'] = 2025
    assert not ql.targets(originals)[0]['available']
    target['copies']['main']['ledger_year'] = 2026
    target['verified'] = False
    assert not ql.targets(originals)[0]['available']
    assert state == before
