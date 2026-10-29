"""Regression for a Gotogate payment incorrectly classified as quarter residual."""
from app.ota_matching_defaults import provider_for_merchant
from app.classify import _card3820_residual


def test_gotogate_inicis_descriptor_resolves_provider():
    assert provider_for_merchant("이니시스(일반)-고투게이트코리아유") == "gotogate"
    assert provider_for_merchant("GOTOGATE") == "gotogate"


def test_gotogate_3820_does_not_become_quarter_residual():
    row = dict(card_tail="3820", transaction_kind="purchase",
               transaction_direction="purchase", amount_krw=612714,
               approval_date="2026-10-01",
               merchant="이니시스(일반)-고투게이트코리아유")
    verdict = dict(classification_source="default", trip_id="", item="기타경비",
                   classification_state="classified", classification_basis="")
    assert _card3820_residual(row, verdict) == verdict
