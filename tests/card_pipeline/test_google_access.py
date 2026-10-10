from app.google_access import visible_trips

VIEW = [
    {"key": "0630_오제", "closure": "open", "closure_current": True, "income_total": 9, "expense_total": 4,
     "net": 5, "verified": True, "review": [], "canonical_source": "main", "copies": {"archive": {"sheet": "x"}}},
    {"key": "0107_대만", "closure": "closed", "closure_current": True, "income_total": 8, "expense_total": 3,
     "net": 5, "verified": True, "review": ["ARCHIVE_ONLY"], "canonical_source": "archive", "copies": {}},
]


def test_owner_sees_every_trip_with_both_copies():
    assert visible_trips(VIEW, is_owner=True, allowed_keys=set()) == VIEW


def test_default_deny_for_viewer_without_grants():
    assert visible_trips(VIEW, is_owner=False, allowed_keys=set()) == []


def test_viewer_sees_only_granted_trips_and_minimal_fields():
    (trip,) = visible_trips(VIEW, is_owner=False, allowed_keys={"0107_대만", "NOT-A-TRIP"})
    assert trip["key"] == "0107_대만"
    assert set(trip) == {"key", "closure", "closure_current", "income_total", "expense_total", "net",
                         "verified", "review"}
    assert "copies" not in trip and "canonical_source" not in trip
