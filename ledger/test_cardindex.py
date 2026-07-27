# -*- coding: utf-8 -*-
"""Regression tests for the canonical card index."""
import unittest
from unittest.mock import patch

from ledger import cardindex


class BuildTripCardsTests(unittest.TestCase):
    def test_exposes_the_amount_and_cancellation_matching_view(self):
        raw = {
            'src': 'KBD',
            'co': '국민',
            'krw': -12_345,
            'cancel': True,
            'merchant': '테스트 가맹점',
        }

        with patch('ledger.cardindex.build_cards', return_value=[raw]):
            trip_cards = cardindex.build_trip_cards()

        self.assertEqual(trip_cards, [{**raw, 'amt': 12_345, 'cx': True}])
        self.assertNotIn('amt', raw)
        self.assertNotIn('cx', raw)

    def test_card_parser_has_every_source_needed_by_the_pipeline(self):
        cards = cardindex.build_trip_cards()

        self.assertTrue(cards)
        self.assertTrue({'KBD', 'KBO', 'HAN', 'CORP'}.issubset({c['src'] for c in cards}))
        self.assertTrue(all(abs(c['krw']) == c['amt'] for c in cards))
        self.assertTrue(all(c['cancel'] == c['cx'] for c in cards))
        order = {'KBO': 0, 'KBD': 1, 'HAN': 2, 'CORP': 3}
        self.assertEqual([order[c['src']] for c in cards], sorted(order[c['src']] for c in cards))


if __name__ == '__main__':
    unittest.main()
