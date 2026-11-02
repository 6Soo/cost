"""Display-only insurance applicability; never change trips, people or links."""
from app.rules import trip_region
from . import read_scope


def is_domestic(trip):
    return bool(trip and not trip.get('deleted') and trip_region(trip) == 'KR')


def domestic_trip(trip_id):
    from . import ledger_board as board

    def resolve():
        trips = [t for t in board.live_trips(include_archived=True)
                 if t.get('tab_id') == trip_id and not t.get('deleted')]
        return len(trips) == 1 and is_domestic(trips[0])
    return read_scope.remember(('domestic_insurance', trip_id), resolve)


def notice():
    # No lazy-panel id, loading hooks, or alert semantics for a normal N/A state.
    return "<p class='meta trip-insurance-not-applicable'>국내여행 · 보험 가입 대상 아님</p>"
