import unittest
from copy import deepcopy

from webapp import ledger_design as design


class LedgerRowIconTests(unittest.TestCase):
    def test_known_merchants_use_local_assets_without_changing_rows(self):
        for merchant, asset in (("AGODA.COM EN RESORT", "agoda.png"),
                                ("트립닷컴(구)_NICE", "trip.png"),
                                ("대표_카카오페이-트립닷컴", "trip.png"),
                                ("TRIP.COM", "trip.png")):
            row = {"source_merchant": merchant, "amount": 12345,
                   "item": "숙박비", "reservation_no": "123"}
            original = deepcopy(row)
            markup = design._merchant_icon(row)
            self.assertIn(f"src='/assets/ota/{asset}'", markup)
            self.assertIn("alt=''", markup)
            self.assertNotIn("https:", markup)
            self.assertIn("<svg", design._category_icon(row))
            self.assertEqual(row, original)

    def test_unknown_or_notes_do_not_claim_brand_identity(self):
        for row in ({"source_merchant": "NOTAGODA"},
                    {"source_merchant": "TRIP.COM.EVIL"},
                    {"description": "AGODA", "source_merchant": "Unknown"},
                    {"source_merchant": "<script>alert(1)</script>"}):
            markup = design._merchant_icon(row)
            self.assertNotIn("<img", markup)
            self.assertIn("<svg", markup)
            self.assertNotIn("<script", markup)

    def test_assets_have_fixed_allowlist_and_valid_signatures(self):
        agoda, mime = design.ota_asset('agoda.png')
        self.assertEqual(mime, 'image/png')
        self.assertTrue(agoda.startswith(b'\x89PNG\r\n\x1a\n'))
        trip, mime = design.ota_asset('trip.png')
        self.assertEqual(mime, 'image/png')
        self.assertTrue(trip.startswith(b'\x89PNG\r\n\x1a\n'))
        for name in ('../agoda.png', '%2e%2e/agoda.png', 'x/agoda.png',
                     '/agoda.png', 'unknown.png', None):
            self.assertIsNone(design.ota_asset(name))
