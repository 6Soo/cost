"""The saved booking index is keyed by the logic that decides it, so a rule change in any of those modules rebuilds it."""
from webapp import ota_catalog


def test_snapshot_key_changes_when_matcher_policy_changes(monkeypatch):
    from types import SimpleNamespace
    from webapp import ota_payment_review
    payments = SimpleNamespace(PARSER_VERSION=7, MATCHER_VERSION=1)
    backend = SimpleNamespace(store=SimpleNamespace(), sources={}, payments=payments,
                              _transactions=lambda: [], board=None)
    monkeypatch.setattr(ota_payment_review, '_guide_input_digest', lambda _: 'synthetic')
    before = ota_payment_review.input_key_for(backend)
    payments.MATCHER_VERSION = 2
    assert ota_payment_review.input_key_for(backend) != before


def test_the_index_key_covers_the_portal_gate_and_defaults_that_decide_the_matches():
    for rel in ('app/ota_portal.py', 'app/ota_exact.py', 'app/ota_sources.py', 'app/booking_evidence.py',
                'app/ota_matching_defaults.py', 'config/ota-matching-defaults.json'):
        assert rel in ota_catalog._LOGIC_FILES, rel
