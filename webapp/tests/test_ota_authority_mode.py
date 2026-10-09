"""Synthetic coverage for the OTA review mode switch and the authority ledger guard."""
import os
from types import SimpleNamespace
from unittest import mock

import pytest

from webapp import card_flow, ota_payment_review as review

ISOLATED = {"WEBLEDGER_OTA_REVIEW_MODE": "isolated", "WEBLEDGER_OTA_REVIEW_DB": "C:/synthetic/review.sqlite"}
AUTHORITY = dict(ISOLATED, WEBLEDGER_OTA_AUTHORITY="authority")


class FakeBackend:
    def __init__(self, transactions, results, pins=()):
        self._payload = ([], transactions, {}, results)
        self.store = SimpleNamespace(group_pins=lambda: list(pins))
        self.closed = False

    def _data(self):
        return self._payload

    def close(self):
        self.closed = True


def flow():
    value = card_flow.CardFlow.__new__(card_flow.CardFlow)
    value.board = SimpleNamespace()
    value._ota_group_holds_cache = None
    return value


def holds_with(env, backend):
    with mock.patch.dict(os.environ, env, clear=True), \
         mock.patch.object(review.CoreOtaPaymentBackend, "from_host", return_value=backend):
        return flow().ota_group_holds()


CARDS = [{"transaction_id": "settled", "merchant": "AGODA.COM"},
         {"transaction_id": "open", "merchant": "AGODA.COM"},
         {"transaction_id": "grouped", "merchant": "Trip.com"},
         {"transaction_id": "grocery", "merchant": "합성마트"}]
RESULTS = [{"ota_event_id": "e1", "transaction_id": "settled", "status": "MATCHED_AUTO"},
           {"ota_event_id": "e2", "transaction_id": "grouped", "status": "HOLD_AMBIGUOUS", "reserved_card_ids": ["grouped"]}]


@pytest.mark.parametrize("env,expected", [({}, "legacy"),
                                          ({"WEBLEDGER_OTA_AUTHORITY": "authority"}, "legacy"),
                                          (ISOLATED, "isolated"), (AUTHORITY, "authority"),
                                          (dict(ISOLATED, WEBLEDGER_OTA_AUTHORITY="shadow"), "isolated")])
def test_mode_resolution_needs_the_isolated_configuration(env, expected):
    with mock.patch.dict(os.environ, env, clear=True):
        assert review.mode() == expected
        assert review.authority() == (expected == "authority")


def test_isolated_mode_only_holds_contested_groups():
    holds = holds_with(ISOLATED, FakeBackend(CARDS, RESULTS))
    assert set(holds) == {"grouped"}


def test_authority_mode_holds_unresolved_ota_cards_but_not_settled_or_ordinary_rows():
    holds = holds_with(AUTHORITY, FakeBackend(CARDS, RESULTS))
    assert set(holds) == {"grouped", "open"}
    assert holds["open"]["kind"] == "ota_authority_unresolved"
    assert holds["grouped"]["kind"] == "ota_group_review"


def test_manual_matches_settle_a_card_in_authority_mode():
    results = RESULTS + [{"ota_event_id": "e3", "transaction_id": "open", "status": "MATCHED_USER"}]
    assert set(holds_with(AUTHORITY, FakeBackend(CARDS, results))) == {"grouped"}


def test_legacy_mode_adds_nothing_and_never_opens_the_backend():
    with mock.patch.dict(os.environ, {}, clear=True), \
         mock.patch.object(review.CoreOtaPaymentBackend, "from_host", side_effect=AssertionError("opened")):
        assert flow().ota_group_holds() == {}


def test_a_backend_failure_in_authority_mode_fails_closed():
    class Broken(FakeBackend):
        def _data(self):
            raise RuntimeError("sources unreadable")

    backend = Broken(CARDS, RESULTS)
    with pytest.raises(RuntimeError):
        holds_with(AUTHORITY, backend)
    assert backend.closed
