import itertools
import random

from app.ota_payments import match_ota_payment_events
from tests.card_pipeline.test_ota_payments import card, event


def _rule(delta):
    return {'conditions': {'provider': 'agoda', 'item': '숙박비', 'issuer': 'issuer-x', 'card_last4': '1234',
                           'amount_delta_krw': delta, 'date_lag_days': 0},
            'status': 'active', 'approved_by': 'owner'}


def _run(events, cards, rules):
    return {r['ota_event_id']: r for r in match_ota_payment_events(events, cards, rules=rules)}


def _double_occupied(results):
    owners = [r['transaction_id'] for r in results.values()
              if r.get('status') == 'MATCHED_AUTO' and r.get('transaction_id')]
    return len(owners) - len(set(owners))


def test_unassigned_event_with_approved_delta_edge_does_not_take_the_assigned_card():
    events = [event('x', booking_ref='B-1', amount=279013, amount_krw=279013),
              event('y', booking_ref='B-2', amount=275013, amount_krw=275013)]
    cards = [card('c', amount_krw=275013)]
    for order in itertools.permutations(events):
        results = _run(list(order), cards, [_rule(-4000)])
        assert _double_occupied(results) == 0
        assert results['y']['status'] == 'MATCHED_AUTO' and results['y']['transaction_id'] == 'c'
        assert results['x']['status'] != 'MATCHED_AUTO' or not results['x'].get('transaction_id')


def test_no_card_is_double_occupied_for_random_events_with_approved_delta_edges():
    rng = random.Random(11)
    rules = [_rule(-4000), _rule(-2000)]
    for _ in range(300):
        amounts = [rng.choice([275013, 277013, 279013]) for _ in range(rng.randint(2, 4))]
        events = [event('e%d' % i, booking_ref='B-%d' % rng.randint(1, 2), amount=a, amount_krw=a)
                  for i, a in enumerate(amounts)]
        cards = [card('c%d' % i, amount_krw=a)
                 for i, a in enumerate(rng.sample([275013, 277013, 273013], rng.randint(1, 2)))]
        assert _double_occupied(_run(events, cards, rules)) == 0
