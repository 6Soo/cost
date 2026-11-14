import itertools
import random

from app.ota_payments import match_ota_payment_events
from tests.card_pipeline.test_ota_payments import card, event


def _run(events, cards):
    return {r['ota_event_id']: r for r in match_ota_payment_events(events, cards)}


def _pair():
    return [event('e1', booking_ref='B-1', amount_krw=30000),
            event('e2', booking_ref='B-1', amount_krw=25000)]


def _card():
    return [card(transaction_id='card-a', amount_krw=25000)]


def _occupancy(results):
    owners = [r['transaction_id'] for r in results.values()
              if r.get('status') == 'MATCHED_AUTO' and r.get('transaction_id')]
    return len(owners) - len(set(owners))


def test_assigned_event_wins_card_in_either_event_order():
    outcomes = []
    for order in itertools.permutations(_pair()):
        results = _run(list(order), _card())
        assert _occupancy(results) == 0
        assert results['e2']['status'] == 'MATCHED_AUTO' and results['e2']['transaction_id'] == 'card-a'
        assert results['e1']['status'] != 'MATCHED_AUTO' and not results['e1'].get('transaction_id')
        outcomes.append({k: v.get('transaction_id') for k, v in results.items() if v['status'] == 'MATCHED_AUTO'})
    assert outcomes[0] == outcomes[1]


def test_no_card_is_double_occupied_for_random_orders():
    rng = random.Random(7)
    base = [event('e%d' % i, booking_ref='B-1', amount_krw=amount)
            for i, amount in enumerate([30000, 25000, 25000, 18000, 30000])]
    cards = [card(transaction_id='card-%d' % i, amount_krw=amount)
             for i, amount in enumerate([25000, 30000, 18000])]
    for _ in range(40):
        events = base[:]
        rng.shuffle(events)
        assert _occupancy(_run(events, cards)) == 0
