"""Provider isolation uses synthetic events/cards only."""
import pytest

from app.ota_payments import match_ota_payment_events, pair_check, search_card_candidates
from tests.card_pipeline.test_ota_matching_defaults import event, card


@pytest.mark.parametrize('provider,merchant', [
    ('trip', 'AGODA_NICE-Agoda'), ('trip', 'BOOKING.COM'), ('trip', 'KLOOK'),
    ('agoda', 'Trip.com Tokyo JP'), ('booking', 'Trip.com Tokyo JP'),
    ('klook', 'Trip.com Tokyo JP'),
])
def test_provider_scope_excludes_cross_provider_before_amount_comparison(provider, merchant):
    ota = event(provider=provider)
    row = card(merchant=merchant, merchant_normalized=merchant.casefold())
    assert match_ota_payment_events([ota], [row])[0]['transaction_id'] is None
    assert pair_check(ota, row) is not None
    for amount in (30000, 85621):
        row['amount_krw'] = amount
        search = search_card_candidates(ota, [row])
        assert search['comparisons'] == 0
        assert search['candidates'] == []
        assert search.get('rejected', []) == []


@pytest.mark.parametrize('merchant', ['UNRELATED MERCHANT', 'nottrip.commercial'])
def test_unknown_merchant_requires_same_day_exact_amount_or_other_approved_evidence(merchant):
    ota = event(provider='trip')
    row = card(merchant=merchant, merchant_normalized=merchant.casefold())
    assert match_ota_payment_events([ota], [row])[0]['transaction_id'] == 'card-1'
    assert pair_check(ota, row) is None

    # An unrecognized descriptor alone is not an approved lag or discount rule.
    for changed in ({'approval_date': '2026-09-05'}, {'amount_krw': 85621},
                    {'card_tail': '9999'}):
        candidate = {**row, **changed}
        assert match_ota_payment_events([ota], [candidate])[0]['transaction_id'] is None
        assert pair_check(ota, candidate) is not None


@pytest.mark.parametrize('merchant', ['Trip.com Tokyo JP', '대표_카카오페이-트립닷컴', '나이스정보통신'])
def test_trip_related_merchants_still_match(merchant):
    row = card(merchant=merchant, merchant_normalized=merchant.casefold())
    assert match_ota_payment_events([event()], [row])[0]['transaction_id'] == row['transaction_id']


def test_scheduled_payment_gate_also_excludes_another_ota_brand():
    from app import ota_exact
    from app.ota_portal import SCHEDULED_CARD_DATE_EVIDENCE
    scheduled = event(provider='agoda', evidence_kind=SCHEDULED_CARD_DATE_EVIDENCE,
                      scheduled_on='2026-09-04')
    assert ota_exact._match_reason(scheduled, card(), {}, []) == 'provider'
