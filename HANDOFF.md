# Trip flight booking read projection handoff

- Baseline: `origin/main` and initial `HEAD` were `496cbbe9778e002bc4265f28b50da704d28f042c`.
- Worker branch: `feat/luna-flights-20261028`.
- Scope: TF-001~TF-008 implementation helpers and synthetic tests for `docs/specs/trip-flight-booking-overview-20261028.md`.
- No customer records, operational database, credentials, Google data, or live insurance data were read or written.

## Requirement status

| ID | State | Result / remaining boundary |
| --- | --- | --- |
| TF-001 | CODE_WRITTEN | Existing source adapter inspection shows the worker index is Trip.com only (`app/flight_evidence.py`); other provider coverage was not measured against live mail, and no unsupported-provider adapter was invented. |
| TF-002 | CODE_WRITTEN | Pure resolver supports explicit user assignment precedence and rejects multiple authority trip IDs. Supervisor must provide verified authority maps from existing booking/card sources. |
| TF-003 | TEST_PASSED | First outbound segment/leg controls a single trip assignment; sequential trips and open-ended trip boundary covered. |
| TF-004 | CODE_WRITTEN | Projection consumes caller-held worker passenger index and generation; no collection or reconciliation is initiated by the helper. |
| TF-005 | TEST_PASSED | Read-only GET helper, owner/allowed-trip gate, 20 default / 100 max pagination, generation-bound cursor, stale-source response and cancellation/conflict states covered synthetically. Route wiring remains supervisor-owned. |
| TF-006 | CODE_WRITTEN | Lazy, escaped, textContent-based section renderer and pagination client added. `ledger_design.py` wiring remains supervisor-owned. |
| TF-007 | BLOCKED | No verified unsupported-provider source coverage was available within this worker's allowed evidence; therefore no adapter was added. |
| TF-008 | PARTIAL | Synthetic tests and code review passed. Browser, deployed read-only shadow, live coverage and deployment are outside this assignment; no operational data was accessed. |

## Files

- `app/trip_flight_assignment.py`: pure assignment policy.
- `webapp/trip_flight_read.py`: booking projection, API contract, access and cursor helpers.
- `webapp/trip_flight_ui.py`: lazy accessible markup/client renderer.
- `webapp/tests/test_trip_flight_read.py`: synthetic policy/API/UI tests.
- Existing `webapp/flight_passenger_page.py` was already present at baseline and contains the completed passenger assignment/search page. It was preserved without edits; expose `trip_flight_read.dispatch` through this existing route dispatcher rather than replacing it.

## Supervisor wiring patch

In `webapp/ledger_board.py`, in both GET and method-dispatch paths adjacent to the existing `flight_passenger_page.dispatch(...)` calls, add the trip-flight GET dispatcher. For GET, derive `viewer = _ACCESS.viewer_for_session(...)` using the same local accessor used by the adjacent Google/participant routes, then:

```python
from . import trip_flight_read
board = _active_store()
snapshot = None
if board is not None:
    service = getattr(board, "_flight_booking_service", None)
    if service is not None:
        current, state = service.display_context()
        snapshot = dict(current or {}, fresh=bool(state.get("fresh")), generation=state.get("generation"))
allowed = _ACCESS.visible_tabs(viewer) if viewer and _ACCESS else set()
if trip_flight_read.dispatch(self, parsed, board=board,
        is_owner=_participant_owner_request(), allowed_trip_ids=allowed,
        query=query, snapshot=snapshot):
    return
```

Use the equivalent `raw=raw` dispatch position in the non-GET method path to enforce GET-only behavior. Keep the existing signed session and trip visibility checks authoritative. Do not call `passenger_index_for()` from this GET route because it can request a worker refresh. `flight_booking_index.service_for(board)` may be used only by the existing background/prewarm path; the API route should read `display_context()` as above.

To add the section in `webapp/ledger_design.py`, only after the actual trip tab has passed `_is_trip_tab(tab_id)`, append `trip_flight_ui.render_flight_section(tab_id)` to the page's trip body and include `trip_flight_ui.CLIENT_SCRIPT` in that page document. This does not alter the expense rows, totals, copy/export paths, or other tabs. Summary counts can be wired from a separately authorized read projection; do not parse mail on initial page render.

Trip period adapter should pass stored fields as-is: `starts_on` and `ends_on` from `board.live_trips(include_archived=True)`. To supply authority, prepare maps keyed by the projection's `booking_key` from verified direct booking/card relations only; amount similarity, merchant names, or passenger names are not evidence. For explicit manual confirmation, preserve the confirmed tab ID and pass it in `user_assignments`; a changed departure then appears as `assignment_conflict` without moving the booking.

## Verification

- `python -m pytest webapp/tests/test_trip_flight_read.py -q` — 9 passed.
- `python -m compileall -q app/trip_flight_assignment.py webapp/trip_flight_read.py webapp/trip_flight_ui.py` — passed.
- `git diff --check` — passed.
- No browser, full-suite, database, or operational verification was run.

## Resume

Review this handoff, integrate only the public helper wiring in supervisor-owned `ledger_board.py` and `ledger_design.py`, then add the authorized authority-map adapter and exercise its protected integration boundary using synthetic/temp data. Re-run `python -m pytest webapp/tests/test_trip_flight_read.py -q` plus the directly affected route/UI tests. This worker did not push, create a PR, or deploy.
