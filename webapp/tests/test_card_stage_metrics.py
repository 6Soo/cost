"""Card timing must leave output/source data and request boundaries intact."""
import json
import pytest

from app import request_metrics as metrics
from webapp import cards_all, card_transactions
from webapp.tests.test_cards_all import card_db_path


@pytest.mark.parametrize('query,operation', [
    ({'year': ['2026']}, 'first_render'),
    ({'year': ['2026'], 'q': ['PRIVATE-QUERY-SENTINEL']}, 'card_search'),
    ({'year': ['2026'], 'month': ['1']}, 'first_render'),
    ({'year': ['2026'], 'undated': ['1']}, 'first_render'),
])
def test_real_card_reads_preserve_output_and_database(card_db_path, monkeypatch, query, operation):
    from pathlib import Path
    window = metrics.MetricsWindow()
    monkeypatch.setattr(metrics, '_REGISTRY', window)
    before = Path(card_db_path).read_bytes()
    expected = cards_all._cards_all_page(query, db_path=card_db_path)
    assert window.summary() == {}  # No card scope, no phase samples.
    actual = cards_all.cards_all_page(query, db_path=card_db_path)
    assert actual == expected
    assert Path(card_db_path).read_bytes() == before
    summary = window.summary()
    for stage in ('db_connect', 'card_query', 'trip_labels', 'card_render'):
        assert summary[f'{operation}.{stage}']['samples'] > 0
        assert summary[f'{operation}.{stage}']['p95_ms'] >= 0
    safe = json.dumps(summary)
    assert 'PRIVATE-QUERY-SENTINEL' not in safe
    assert str(card_db_path) not in safe
    assert 'SELECT' not in safe and 'transaction_id' not in safe
    card_transactions.available_years(card_db_path)
    assert window.summary() == summary  # The page scope was reset.


def test_nested_scope_and_failed_reads_do_not_leak_or_create_success_samples(monkeypatch):
    window = metrics.MetricsWindow()
    monkeypatch.setattr(metrics, '_REGISTRY', window)

    @metrics.card_stage('card_query')
    def read(*, fail=False):
        if fail:
            raise ValueError('PRIVATE-EXCEPTION-SENTINEL')
        return 42

    with metrics.card_scope('first_render'):
        assert read() == 42
        with pytest.raises(ValueError, match='PRIVATE-EXCEPTION'):
            with metrics.card_scope('card_search'):
                read(fail=True)
        assert read() == 42
    assert read() == 42
    assert window.summary()['first_render.card_query']['samples'] == 2
    assert 'card_search.card_query' not in window.summary()
    assert 'PRIVATE-EXCEPTION' not in json.dumps(window.summary())
