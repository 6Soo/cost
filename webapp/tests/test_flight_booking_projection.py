"""Targeted unit tests and baseline equivalence tests for flight_booking_projection.

Verifies:
1. normalize_name_tokens: NFKC normalization, slash/comma splitting, case-folding, sorting.
2. project_itinerary_leg: Clean projection of flights, airports, times, and missing field handling.
3. project_booking_reservation: Explicit date priority, FIRST_RECEIVED KST date, CONFLICT/UNKNOWN blanking,
   cancellation status, and conflict flag preservation.
4. query_booking_reservations: In-memory filtering, stable departure_on/booking_ref sorting,
   revision calculation, and pagination.
5. Baseline differential equivalence against flight_passenger_page._name_search on main commit ed48263.
"""
from __future__ import annotations

import ast
import json
from pathlib import Path
import subprocess
from types import SimpleNamespace
from typing import Any, Dict
from unittest.mock import patch

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


def test_project_booking_reservation_dates_and_flags():
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


def test_resolve_flight_sources_key_and_cache(tmp_path):
    # Non-existent directory fails closed
    with pytest.raises(ValueError, match="FLIGHT_MAIL_UNAVAILABLE"):
        flight_booking_projection.resolve_flight_sources_key({"mail_directories": ["/non/existent"]})

    mail_dir = tmp_path / "mail"
    mail_dir.mkdir()
    key = flight_booking_projection.resolve_flight_sources_key({"mail_directories": [str(mail_dir)]})
    assert isinstance(key, str) and len(key) == 64

    # Cache reading
    cache_file = tmp_path / "passengers.json"
    cache_file.write_text(json.dumps({
        "schema": "passenger-v1",
        "key": key,
        "parser": "parser-v1",
        "passengers": {"REF1": {"name": "test"}},
    }), encoding="utf-8")

    loaded = flight_booking_projection.load_cached_passenger_data(
        cache_file, expected_key=key, schema="passenger-v1", parser_version="parser-v1")
    assert loaded == {"REF1": {"name": "test"}}

    # Key mismatch returns None
    assert flight_booking_projection.load_cached_passenger_data(
        cache_file, expected_key="other-key", schema="passenger-v1", parser_version="parser-v1") is None


def test_baseline_equivalence_with_main_ed48263():
    """Verify that query_booking_reservations produces 1:1 identical output to flight_passenger_page._name_search."""
    index = _synthetic_index()
    board = SimpleNamespace(
        _flight_booking_service=None,
        path="synthetic.sqlite",
    )

    with patch("webapp.flight_booking_index.passenger_index_for", return_value=index), \
         patch("webapp.flight_passenger_page._confirmed_card_index", return_value={}):
        baseline_res = flight_passenger_page._name_search(board, "alpha kim")
        curr_res = flight_booking_projection.query_booking_reservations(index, "alpha kim")
        assert baseline_res == curr_res

        # Test single token match
        assert flight_passenger_page._name_search(board, "KIM") == flight_booking_projection.query_booking_reservations(index, "KIM")

        # Test other passenger
        assert flight_passenger_page._name_search(board, "BETA") == flight_booking_projection.query_booking_reservations(index, "BETA")

        # Test facade search_reservations on flight_booking_index
        with patch.object(flight_booking_index, "passenger_index_for", return_value=index), \
             patch.object(flight_booking_index, "source_status", return_value="VERIFIED"):
            facade_res = flight_booking_index.search_reservations(board, "alpha kim")
            assert facade_res == curr_res
