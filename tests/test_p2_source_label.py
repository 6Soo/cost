"""AI provenance remains distinct in the card list and shared detail renderer."""
import pytest
from webapp import cards_all


@pytest.mark.parametrize('source,label', [
    ('ai_inference', 'AI 판정'), ('code_inference', '자동'),
    ('inference', '자동'), ('auto_inferred', '자동'), ('manual', '수동'),
    ('user_decision', '수동'), ('guide_airfare_evidence', '자동'),
])
def test_source_in_list_and_detail(source, label):
    row = dict(transaction_id='SYNTHETIC', merchant='합성 식당', amount_krw=12000,
               trip_id='SYNTHETIC-TRIP', item='식비', classification_source=source,
               classification_state='classified', use_date='2026-11-01')
    original = dict(row)
    assert f'>{label}</span>' in cards_all._classification_chip(row)
    assert label in cards_all.card_detail_html(row)
    assert label in cards_all._render_month_rows([row])
    assert row == original
    if source == 'ai_inference':
        assert cards_all._get_trip_display('SYNTHETIC-TRIP', source).endswith(' · AI 판정')
        assert '>자동</span>' not in cards_all._classification_chip(row)
