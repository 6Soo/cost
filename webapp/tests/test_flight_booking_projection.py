"""Targeted unit tests and baseline equivalence tests for flight_booking_projection.

Verifies:
1. normalize_name_tokens: NFKC normalization, slash/comma splitting, case-folding, sorting.
2. project_itinerary_leg: Clean projection of flights, airports, times, and missing field handling.
3. project_booking_reservation: Explicit date priority, FIRST_RECEIVED KST date, CONFLICT/UNKNOWN blanking,
   cancellation status, conflict flag, and linked_cards identity preservation.
4. query_booking_reservations: In-memory filtering, stable departure_on/booking_ref sorting,
   revision calculation, and pagination.
5. Early validation without IO, lazy source_status evaluation (0 calls when verified),
   and _name_key dynamic monkeypatch dispatch.
6. Baseline differential equivalence against flight_passenger_page._name_search on main commit ed48263.
"""
from __future__ import annotations

import ast
import json
from pathlib import Path
import subprocess
from types import SimpleNamespace
from typing import Any, Dict
from unittest.mock import MagicMock, patch

import pytest

from webapp import flight_booking_index, flight_booking_projection, flight_passenger_page


def _synthetic_index():
    return {
        "SYNTH-100": {
            "source_digests": ["sha-synthetic-a"],
            "digest": "digest-100",
            "passengers": [{"surname": "KIM", "given_name": "ALPHA"}],
            "legs": [
                {
                    "label": "가는 편",
                    "origin_city": "서울",
                    "destination_city": "도쿄",
                    "departure_on": "2026-11-10",
                    "segments": [
                        {
                            "departure_airport": "ICN",
                            "arrival_airport": "NRT",
                            "departure_time": "09:10",
                            "arrival_time": "11:30",
                            "flight_number": "SYN123",
                        }
                    ],
                }
            ],
            "cancellation_status": "NONE",
            "conflict": False,
            "booking_date_status": "EXPLICIT_LABEL",
            "reserved_on": "2026-10-02",
            "booking_card_day": "2026-10-02",
            "booking_date_evidence": [{"timestamp": "2026-10-02T01:00:00Z"}],
        },
        "SYNTH-200": {
            "source_digests": ["sha-synthetic-b"],
            "digest": "digest-200",
            "passengers": [{"surname": "KIM", "given_name": "ALPHA"}],
            "legs": [
                {
                    "label": "오는 편",
                    "origin_city": "도쿄",
                    "destination_city": "서울",
                    "departure_on": "2026-11-15",
                    "segments": [],
                }
            ],
            "cancellation_status": "CANCELLED",
            "conflict": False,
            "booking_date_status": "FIRST_RECEIVED",
            "reserved_on": "2026-10-03",
            "booking_card_day": "2026-10-03",
            "booking_date_evidence": [{"timestamp": "2026-10-03T02:00:00+09:00"}],
        },
        "SYNTH-CONFLICT": {
            "source_digests": ["sha-synthetic-c"],
            "digest": "digest-conflict",
            "passengers": [{"surname": "KIM", "given_name": "ALPHA"}],
            "legs": [],
            "cancellation_status": "NONE",
            "conflict": True,
            "booking_date_status": "CONFLICT",
            "reserved_on": "",
            "booking_card_day": "",
        },
        "SYNTH-NO-DIGEST": {
            # Unverified evidence without source_digests must be excluded
            "passengers": [{"surname": "KIM", "given_name": "ALPHA"}],
        },
        "SYNTH-OTHER": {
            "source_digests": ["sha-synthetic-d"],
            "digest": "digest-other",
            "passengers": [{"surname": "PARK", "given_name": "BETA"}],
            "legs": [],
            "cancellation_status": "NONE",
            "conflict": False,
        },
    }


@pytest.fixture(scope="module")
def baseline_name_search_fn():
    """Extract and compile _name_search from public main commit ed48263."""
    proc = subprocess.run(
        ["git", "show", "ed48263:webapp/flight_passenger_page.py"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=True,
    )
    tree = ast.parse(proc.stdout)
    func_node = next(
        node for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == "_name_search"
    )
    mod = ast.Module(body=[func_node], type_ignores=[])
    ast.fix_missing_locations(mod)

    ns: Dict[str, Any] = dict(flight_passenger_page.__dict__)
    exec(compile(mod, "<baseline_ed48263_name_search>", "exec"), ns)
    return ns["_name_search"]


def test_normalize_name_tokens():
    assert flight_booking_projection.normalize_name_tokens("  Alpha / KIM ") == ("alpha", "kim")
    assert flight_booking_projection.normalize_name_tokens("KIM, ALPHA") == ("alpha", "kim")
    assert flight_booking_projection.normalize_name_tokens("Hong, Gil / Dong") == ("dong", "gil", "hong")
    assert flight_booking_projection.normalize_name_tokens("Hong-Gil.Dong") == ("honggildong",)
    assert flight_booking_projection.normalize_name_tokens("") == ()
    assert flight_booking_projection.normalize_name_tokens(None) == ()


def test_project_itinerary_leg():
    raw_leg = {
        "label": "가는편",
        "origin_city": "서울",
        "destination_city": "오사카",
        "departure_on": "2026-12-01",
        "segments": [
            {
                "flight_number": "OZ123",
                "departure_airport": "GMP",
                "departure_time": "08:00",
                "arrival_airport": "KIX",
                "arrival_time": "09:40",
                "extra_field": "ignored",
            }
        ],
        "ignored_key": "val",
    }
    projected = flight_booking_projection.project_itinerary_leg(raw_leg)
    assert projected["label"] == "가는편"
    assert projected["origin_city"] == "서울"
    assert projected["destination_city"] == "오사카"
    assert projected["departure_on"] == "2026-12-01"
    assert len(projected["segments"]) == 1
    seg = projected["segments"][0]
    assert seg == {
        "flight_number": "OZ123",
        "departure_airport": "GMP",
        "departure_time": "08:00",
        "arrival_airport": "KIX",
        "arrival_time": "09:40",
    }


def test_project_booking_reservation_dates_flags_and_identity():
    # 1. EXPLICIT_LABEL preserves date
    res_explicit = flight_booking_projection.project_booking_reservation(
        "REF1",
        {
            "booking_date_status": "EXPLICIT_LABEL",
            "reserved_on": "2026-10-01",
            "booking_card_day": "2026-10-01",
            "cancellation_status": "NONE",
            "conflict": False,
        },
        "KIM ALPHA",
    )
    assert res_explicit["reserved_on"] == "2026-10-01"
    assert res_explicit["booking_card_day"] == "2026-10-01"
    assert res_explicit["cancelled"] is False
    assert res_explicit["conflict"] is False

    # 2. FIRST_RECEIVED preserves KST date
    res_first = flight_booking_projection.project_booking_reservation(
        "REF2",
        {
            "booking_date_status": "FIRST_RECEIVED",
            "reserved_on": "2026-10-02",
            "booking_card_day": "2026-10-02",
            "cancellation_status": "CANCELLED",
            "conflict": False,
        },
        "KIM ALPHA",
    )
    assert res_first["reserved_on"] == "2026-10-02"
    assert res_first["booking_card_day"] == "2026-10-02"
    assert res_first["cancelled"] is True

    # 3. CONFLICT blanks dates
    res_conflict = flight_booking_projection.project_booking_reservation(
        "REF3",
        {
            "booking_date_status": "CONFLICT",
            "reserved_on": "2026-10-03",
            "booking_card_day": "2026-10-03",
            "cancellation_status": "NONE",
            "conflict": True,
        },
        "KIM ALPHA",
    )
    assert res_conflict["reserved_on"] == ""
    assert res_conflict["booking_card_day"] == ""
    assert res_conflict["conflict"] is True

    # 4. UNKNOWN blanks dates
    res_unknown = flight_booking_projection.project_booking_reservation(
        "REF4",
        {
            "booking_date_status": "UNKNOWN",
            "reserved_on": "2026-10-04",
            "booking_card_day": "2026-10-04",
        },
        "KIM ALPHA",
    )
    assert res_unknown["reserved_on"] == ""
    assert res_unknown["booking_card_day"] == ""

    # 5. linked_cards identity is preserved (no list copy coercion)
    sample_cards = [{"transaction_id": "tx1", "amount_krw": 50000}]
    res_cards = flight_booking_projection.project_booking_reservation(
        "REF5", {}, "KIM", linked_cards=sample_cards
    )
    assert res_cards["linked_cards"] is sample_cards


def test_query_booking_reservations_filtering_and_sorting():
    index = _synthetic_index()
    res = flight_booking_projection.query_booking_reservations(index, "alpha kim")
    assert res["total"] == 3
    # Sorted by departure_on descending: SYNTH-200 (2026-11-15) > SYNTH-100 (2026-11-10) > SYNTH-CONFLICT (no legs)
    assert [r["booking_ref"] for r in res["reservations"]] == ["SYNTH-200", "SYNTH-100", "SYNTH-CONFLICT"]
    assert res["reservations"][0]["cancelled"] is True
    assert res["reservations"][1]["cancelled"] is False
    assert res["reservations"][2]["conflict"] is True
    assert res["source_status"] == "VERIFIED"

    # Searching other name
    res_park = flight_booking_projection.query_booking_reservations(index, "beta")
    assert res_park["total"] == 1
    assert res_park["reservations"][0]["booking_ref"] == "SYNTH-OTHER"

    # Invalid names fail closed
    with pytest.raises(ValueError, match="INVALID_NAME"):
        flight_booking_projection.query_booking_reservations(index, "   ")
    with pytest.raises(ValueError, match="INVALID_NAME"):
        flight_booking_projection.query_booking_reservations(index, "///,,,")

    # Invalid cursors fail closed
    with pytest.raises(ValueError, match="INVALID_CURSOR"):
        flight_booking_projection.query_booking_reservations(index, "alpha", offset=-1)
    with pytest.raises(ValueError, match="INVALID_CURSOR"):
        flight_booking_projection.query_booking_reservations(index, "alpha", offset=10, revision=None)


def test_query_booking_reservations_revision_and_source_changed():
    index = _synthetic_index()
    res = flight_booking_projection.query_booking_reservations(index, "alpha kim")
    rev = res["revision"]
    assert isinstance(rev, str) and len(rev) == 64

    # Matching revision passes
    res2 = flight_booking_projection.query_booking_reservations(index, "alpha kim", revision=rev)
    assert res2["revision"] == rev

    # Mismatched revision raises SOURCE_CHANGED
    with pytest.raises(LookupError, match="SOURCE_CHANGED"):
        flight_booking_projection.query_booking_reservations(index, "alpha kim", revision="stale-revision")


def test_name_search_pre_validation_zero_io():
    """INVALID_NAME and INVALID_CURSOR must be raised before any IO or card index lookup."""
    board = SimpleNamespace(path="board.sqlite")
    with patch("webapp.flight_booking_index.passenger_index_for") as mock_passenger, \
         patch("webapp.flight_passenger_page._confirmed_card_index") as mock_cards:

        # 1. Invalid name: raises ValueError, 0 IO calls
        with pytest.raises(ValueError, match="INVALID_NAME"):
            flight_passenger_page._name_search(board, "   ")
        mock_passenger.assert_not_called()
        mock_cards.assert_not_called()

        # 2. Invalid cursor: raises ValueError, 0 IO calls
        with pytest.raises(ValueError, match="INVALID_CURSOR"):
            flight_passenger_page._name_search(board, "KIM", offset=-5)
        mock_passenger.assert_not_called()
        mock_cards.assert_not_called()

        with pytest.raises(ValueError, match="INVALID_CURSOR"):
            flight_passenger_page._name_search(board, "KIM", offset=100, revision=None)
        mock_passenger.assert_not_called()
        mock_cards.assert_not_called()


def test_lazy_source_status_evaluation_zero_calls_on_verified():
    """source_status(board) must NOT be called when index already contains verified evidence."""
    index = _synthetic_index()
    board = SimpleNamespace(path="board.sqlite")

    with patch("webapp.flight_booking_index.passenger_index_for", return_value=index), \
         patch("webapp.flight_passenger_page._confirmed_card_index", return_value={}), \
         patch("webapp.flight_booking_index.source_status") as mock_status:

        res = flight_passenger_page._name_search(board, "KIM")
        assert res["source_status"] == "VERIFIED"
        mock_status.assert_not_called()  # EXACTLY 0 CALLS

    # When index is unverified, source_status must be called once as fallback
    empty_index = {"REF": {"passengers": []}}
    with patch("webapp.flight_booking_index.passenger_index_for", return_value=empty_index), \
         patch("webapp.flight_passenger_page._confirmed_card_index", return_value={}), \
         patch("webapp.flight_booking_index.source_status", return_value="LOADING") as mock_status:

        res_empty = flight_passenger_page._name_search(board, "KIM")
        assert res_empty["source_status"] == "LOADING"
        mock_status.assert_called_once()


def test_name_key_monkeypatch_dynamic_dispatch(monkeypatch):
    """Monkeypatching _name_key on flight_passenger_page must dynamically affect token matching."""
    index = {
        "REF-CUSTOM": {
            "source_digests": ["sha-cust"],
            "digest": "digest-cust",
            "passengers": [{"surname": "ALIAS", "given_name": "NAME"}],
            "legs": [],
        }
    }
    board = SimpleNamespace(path="board.sqlite")

    # Custom normalizer that recognizes a special token
    def custom_name_key(val):
        if "special" in str(val).lower():
            return ("matched_token",)
        return flight_booking_projection.normalize_name_tokens(val)

    monkeypatch.setattr(flight_passenger_page, "_name_key", custom_name_key)

    with patch("webapp.flight_booking_index.passenger_index_for", return_value=index), \
         patch("webapp.flight_passenger_page._confirmed_card_index", return_value={}):

        # Searching 'special' should match because custom_name_key maps it
        # and if passenger full_name doesn't map, it won't match, unless passenger also maps
        res_no = flight_passenger_page._name_search(board, "special")
        assert res_no["total"] == 0

        # Now passenger has 'special' in surname
        index["REF-CUSTOM"]["passengers"][0]["surname"] = "SPECIAL_USER"
        res_yes = flight_passenger_page._name_search(board, "special")
        assert res_yes["total"] == 1
        assert res_yes["reservations"][0]["booking_ref"] == "REF-CUSTOM"


def test_escape_csrf_json_helper():
    token = flight_passenger_page._escape_csrf_json("csrf</script><script>alert(1)</script>")
    assert "</script>" not in token
    assert r"\u003c/script>" in token
    assert flight_passenger_page._escape_csrf_json("") == '""'
    assert flight_passenger_page._escape_csrf_json(None) == '""'


def test_baseline_equivalence_with_main_ed48263(baseline_name_search_fn):
    """Verify that delegated flight_passenger_page._name_search matches ed48263 baseline 1:1."""
    index = _synthetic_index()
    board = SimpleNamespace(
        _flight_booking_service=None,
        path="synthetic.sqlite",
    )

    with patch("webapp.flight_booking_index.passenger_index_for", return_value=index), \
         patch("webapp.flight_passenger_page._confirmed_card_index", return_value={}), \
         patch("webapp.flight_booking_index.source_status", return_value="VERIFIED"):

        baseline_res = baseline_name_search_fn(board, "alpha kim")
        curr_page_res = flight_passenger_page._name_search(board, "alpha kim")
        curr_proj_res = flight_booking_projection.query_booking_reservations(index, "alpha kim")

        assert baseline_res == curr_page_res
        assert baseline_res == curr_proj_res

        # Test single token match
        assert baseline_name_search_fn(board, "KIM") == flight_passenger_page._name_search(board, "KIM")

        # Test other passenger
        assert baseline_name_search_fn(board, "BETA") == flight_passenger_page._name_search(board, "BETA")

        # Test empty index
        with patch("webapp.flight_booking_index.passenger_index_for", return_value={}), \
             patch("webapp.flight_booking_index.source_status", return_value="UNAVAILABLE"):
            assert baseline_name_search_fn(board, "KIM") == flight_passenger_page._name_search(board, "KIM")


def test_fail_on_second_query_normalization(monkeypatch):
    """Ensure query name normalization happens exactly once and is not re-computed inside the helper."""
    board = SimpleNamespace(path="board.sqlite")
    index = _synthetic_index()

    calls = []
    def counting_name_key(val):
        calls.append(val)
        if len([c for c in calls if c == "alpha kim"]) > 1:
            raise AssertionError("Query name normalized more than once!")
        return flight_booking_projection.normalize_name_tokens(val)

    monkeypatch.setattr(flight_passenger_page, "_name_key", counting_name_key)

    with patch("webapp.flight_booking_index.passenger_index_for", return_value=index), \
         patch("webapp.flight_passenger_page._confirmed_card_index", return_value={}):
        res = flight_passenger_page._name_search(board, "alpha kim")
        assert res["total"] == 3
        # "alpha kim" was normalized exactly once
        assert calls.count("alpha kim") == 1


def test_cards_ref_to_none_identity_and_value_preserved(baseline_name_search_fn, monkeypatch):
    """cards.get returning None or a specific object must be preserved exactly without coercion."""
    index = _synthetic_index()
    board = SimpleNamespace(path="board.sqlite")
    specific_list = [{"transaction_id": "tx1"}]
    cards_map = {
        "SYNTH-100": None,           # explicitly mapped to None
        "SYNTH-200": specific_list,  # mapped to specific object
    }

    monkeypatch.setattr(flight_passenger_page, "_confirmed_card_index", lambda b, idx: cards_map)
    monkeypatch.setitem(baseline_name_search_fn.__globals__, "_confirmed_card_index", lambda b, idx: cards_map)

    with patch("webapp.flight_booking_index.passenger_index_for", return_value=index), \
         patch("webapp.flight_booking_index.source_status", return_value="VERIFIED"):

        base_res = baseline_name_search_fn(board, "alpha kim")
        curr_res = flight_passenger_page._name_search(board, "alpha kim")

        # Compare baseline vs current
        assert base_res == curr_res
        # SYNTH-100's linked_cards must be None in both
        assert curr_res["reservations"][1]["booking_ref"] == "SYNTH-100"
        assert curr_res["reservations"][1]["linked_cards"] is None
        assert base_res["reservations"][1]["linked_cards"] is None
        # SYNTH-200's linked_cards must preserve exact identity in both
        assert curr_res["reservations"][0]["booking_ref"] == "SYNTH-200"
        assert curr_res["reservations"][0]["linked_cards"] is specific_list
        assert base_res["reservations"][0]["linked_cards"] is specific_list
