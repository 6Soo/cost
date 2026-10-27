"""UI contract for the flight booking evidence page, with synthetic metadata only."""

from webapp.flight_passenger_page import _page


def test_booking_route_cards_keep_existing_workflows():
    html = _page("synthetic-csrf")
    for marker in (
        "fb-hero", "fb-summary", "fb-summary-item",
        "fb-itinerary", "fb-flight-card", "fb-flight-bar",
        "fb-route-stop", "fb-flight-facts",
        "가는편", "오는편", "탑승권·여정 정보",
        "/api/flight-passengers/name-search",
        "/api/cards/transactions/day",
        "/flight-passengers?view=participants",
        "manualDateFilter(candidates,candidateDay,b.booking_date_status)",
    ):
        assert marker in html
    assert "@media(max-width:600px)" in html
    assert "@media(prefers-color-scheme:dark)" in html
    assert "textContent=String(value" in html  # No untrusted reservation innerHTML.
