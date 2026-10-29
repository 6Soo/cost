from webapp import card_flow


class _Board:
    pass


def test_trip_facade_delegates_authority_with_live_module_callbacks(monkeypatch):
    flow = object.__new__(card_flow.CardFlow)
    flow.board = _Board()
    seen = {}

    def fake(owner, trip_id, **callbacks):
        seen.update(callbacks)
        assert owner is flow
        return trip_id == "synthetic-trip"

    monkeypatch.setattr(card_flow.card_trip_authority, "trip_valid", fake)
    assert flow.trip_valid("synthetic-trip")
    assert seen["google_periods"] is card_flow._google_periods
    assert seen["trip_authority"] is card_flow._trip_authority
    assert seen["unchanged_workbook_schedule"] is card_flow._unchanged_workbook_schedule


def test_assignment_facade_delegates_to_extracted_services(monkeypatch):
    flow = object.__new__(card_flow.CardFlow)
    calls = []

    def fake_retail(owner, transaction, country, *, google_nets):
        calls.append(("retail", owner, transaction, country, google_nets))
        return "synthetic-retail"

    def fake_booking(owner, transaction, period, *, google_nets):
        calls.append(("booking", owner, transaction, period, google_nets))
        return "synthetic-booking"

    monkeypatch.setattr(card_flow.card_trip_authority, "retail_trip", fake_retail)
    monkeypatch.setattr(card_flow.card_trip_authority, "booking_trip", fake_booking)
    assert flow.retail_trip({"approval_date": "2026-01-01"}, "JP") == "synthetic-retail"
    assert flow.booking_trip({}, {"starts_on": "2026-01-01", "ends_on": "2026-01-02"}) == "synthetic-booking"
    assert [call[0] for call in calls] == ["retail", "booking"]
    assert all(call[-1] is card_flow._google_nets for call in calls)
