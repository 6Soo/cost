"""The saved booking index is keyed by the logic that decides it, so a rule change in any of those modules rebuilds it."""
from webapp import ota_catalog


def test_the_index_key_covers_the_portal_gate_and_defaults_that_decide_the_matches():
    for rel in ('app/ota_portal.py', 'app/ota_exact.py', 'app/ota_sources.py', 'app/booking_evidence.py',
                'app/ota_matching_defaults.py', 'config/ota-matching-defaults.json'):
        assert rel in ota_catalog._LOGIC_FILES, rel
