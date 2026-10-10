"""Synthetic coverage for the OTA review mode switch and the authority ledger guard.

Holds are read from the reconciled snapshot, never from a reconciliation on the preview path.
"""
import os
from types import SimpleNamespace
from unittest import mock

import pytest

from webapp import card_flow, ota_payment_review as review

ISOLATED = {"WEBLEDGER_OTA_REVIEW_MODE": "isolated", "WEBLEDGER_OTA_REVIEW_DB": "C:/synthetic/review.sqlite"}
AUTHORITY = dict(ISOLATED, WEBLEDGER_OTA_AUTHORITY="authority")


class FakeBackend:
    def __init__(self, transactions, pins=(), fail=False):
        self._transactions_rows = transactions
        self._fail = fail
        self.store = SimpleNamespace(group_pins=lambda: list(pins))
        self.closed = False

    def _transactions(self):
        if self._fail:
            raise RuntimeError("board unreadable")
        return self._transactions_rows

    def close(self):
        self.closed = True


class FakeService:
    def __init__(self, current, fresh=True):
        self._held = (current, fresh)

    def held(self):
        return self._held


def snapshot(results, links=None):
    return {"results": results, "links": links or {}, "public": {}, "generation": 1, "key": "k"}


def flow():
    value = card_flow.CardFlow.__new__(card_flow.CardFlow)
    value.board = SimpleNamespace()
    value._ota_group_holds_cache = None
    return value


def holds_with(env, backend, service):
    with mock.patch.dict(os.environ, env, clear=True), \
         mock.patch.object(review.CoreOtaPaymentBackend, "from_host", return_value=backend), \
         mock.patch.object(review, "snapshot_service", return_value=service):
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
    holds = holds_with(ISOLATED, FakeBackend(CARDS), FakeService(snapshot(RESULTS)))
    assert set(holds) == {"grouped"}


def test_authority_mode_holds_unresolved_ota_cards_but_not_settled_or_ordinary_rows():
    holds = holds_with(AUTHORITY, FakeBackend(CARDS), FakeService(snapshot(RESULTS)))
    assert set(holds) == {"grouped", "open"}
    assert holds["open"]["kind"] == "ota_authority_unresolved"
    assert holds["grouped"]["kind"] == "ota_group_review"


def test_manual_matches_settle_a_card_in_authority_mode():
    results = RESULTS + [{"ota_event_id": "e3", "transaction_id": "open", "status": "MATCHED_USER"}]
    assert set(holds_with(AUTHORITY, FakeBackend(CARDS), FakeService(snapshot(results)))) == {"grouped"}


def test_without_a_snapshot_authority_holds_every_ota_card():
    holds = holds_with(AUTHORITY, FakeBackend(CARDS), FakeService(None, fresh=False))
    assert set(holds) == {"settled", "open", "grouped"}


def test_without_a_snapshot_isolated_mode_also_holds_every_ota_card():
    holds = holds_with(ISOLATED, FakeBackend(CARDS), FakeService(None, fresh=False))
    assert set(holds) == {"settled", "open", "grouped"}


def test_stale_snapshot_grants_no_new_automatic_link_but_keeps_held_links():
    service = FakeService(snapshot(RESULTS, links={"e1": "settled"}), fresh=False)
    holds = holds_with(AUTHORITY, FakeBackend(CARDS), service)
    assert "settled" not in holds
    assert set(holds) == {"open", "grouped"}


def test_legacy_mode_adds_nothing_and_never_opens_the_backend():
    with mock.patch.dict(os.environ, {}, clear=True), \
         mock.patch.object(review.CoreOtaPaymentBackend, "from_host", side_effect=AssertionError("opened")):
        assert flow().ota_group_holds() == {}


def test_a_board_failure_in_authority_mode_fails_closed():
    backend = FakeBackend(CARDS, fail=True)
    with pytest.raises(RuntimeError):
        holds_with(AUTHORITY, backend, FakeService(snapshot(RESULTS)))
    assert backend.closed
