"""UI contract for the flight booking evidence page, with synthetic metadata only."""

from webapp.flight_passenger_page import _page


def test_booking_route_cards_keep_existing_workflows():
    html = _page("synthetic-csrf")
    for marker in (
        "fb-hero", "fb-summary", "fb-summary-item",
        "fb-itinerary", "fb-flight-card", "fb-flight-bar",
        "fb-route-stop", "fb-trip-group", "fb-reservation-warning",
        "가는편", "오는편", "탑승권·여정 정보",
        "/api/flight-passengers/name-search",
        "/api/cards/transactions/day",
        "/api/cards/transactions/detail",
        "manualDateFilter(candidates,candidateDay,b.booking_date_status)",
    ):
        assert marker in html
    assert "@media(max-width:600px)" in html
    assert "@import url('/static/css/tokens.css')" in html
    assert "@media(prefers-color-scheme:dark)" not in html
    assert "textContent=String(value" in html  # No untrusted reservation innerHTML.
    assert "/flight-passengers?view=participants" not in html
