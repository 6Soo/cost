from copy import deepcopy
from unittest.mock import patch

from webapp import ledger_board as board, ledger_design


def trip(key, starts_on, **extra):
    return dict(tab_id=key, display_key=key, destination="Synthetic", starts_on=starts_on,
                ends_on=starts_on, **extra)


def render(trips, selected="", query="", role="owner", allowed=()):
    with patch.object(board, "live_trips", return_value=trips), \
         patch.object(board, "current_role", return_value=role), \
         patch.object(board, "viewer_visible_tabs", return_value=set(allowed)), \
         patch.object(board, "current_request_session", return_value=None), \
         patch.object(board, "_unclassified_rows", return_value=[]):
        return ledger_design.nav_region(selected, query)


def test_june_25_inclusive_moves_to_last_previous_trips_without_mutating_records():
    trips = [trip("early", "2026-04-01"), trip("boundary", "2026-06-25"),
             trip("later", "2026-06-26"), trip("next-year", "2027-06-25"),
             trip("unknown", ""), trip("invalid", "2026-02-31"),
             trip("old-archived", "2026-06-01", archived=True),
             trip("deleted", "2026-06-20", deleted=True)]
    before = deepcopy(trips)
    html = render(trips)
    main, previous = html.split("<details", 1)
    for key in ("early", "boundary", "old-archived"):
        assert f"tab={key}" not in main
        assert f"tab={key}" in previous
    for key in ("later", "next-year", "unknown", "invalid"):
        assert f"tab={key}" in main
        assert f"tab={key}" not in previous
    assert "이전 여행" in previous
    assert 'id="previous-trips"' in previous
    assert html.endswith("</details></div>")
    assert "tab=deleted" not in html
    assert trips == before


def test_selected_or_searched_previous_trip_stays_collapsed_and_viewer_cannot_see_other_trips():
    trips = [trip("allowed-old", "2026-06-25"), trip("secret-old", "2026-06-24")]
    html = render(trips, selected="allowed-old", role="viewer", allowed=("allowed-old",))
    assert '<details id="previous-trips">' in html
    assert '<details id="previous-trips" open' not in html
    assert 'secret-old' not in html
    assert 'aria-pressed="true"' in html
    html = render(trips, query="allowed-old")
    assert '<details id="previous-trips">' in html
    assert '<details id="previous-trips" open' not in html
    assert 'tab=secret-old' not in html
