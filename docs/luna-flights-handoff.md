# Trip flight booking read projection handoff

- Baseline: `origin/main` and initial `HEAD` were `496cbbe9778e002bc4265f28b50da704d28f042c`.
- Prior worker commit: `d37875f47c54117bf40ecd5af16120688aa4a18f`.
- Worker branch: `feat/luna-flights-20261028`.
- Scope: TF-001~TF-008 read implementation and synthetic integration for `docs/specs/trip-flight-booking-overview-20261028.md`.
- No customer records, operational database, credentials, Google data, or live insurance data were read or written.

## Requirement status

| ID | State | Result / remaining boundary |
| --- | --- | --- |
| TF-001 | PARTIAL | Existing authenticated worker index is Trip.com only (`app/flight_evidence.py`). Unsupported providers remain unmeasured because no real mail coverage was accessed. |
| TF-002 | TEST_PASSED | Read-only adapter reads explicit booking trip rules from SQLite `mode=ro` with `query_only`; it also reuses the strict existing USER_CONFIRMED booking/card helper and joins exact transaction IDs to card ledger rows. No merchant/amount/name matching is used as PNR authority. Multiple trip authorities become CONFLICT. |
| TF-003 | TEST_PASSED | Outbound-labelled leg is preferred even when return appears first; sequential trips and open-ended trip boundary are covered. |
| TF-004 | TEST_PASSED | Read-only route consumes a fresh worker `display_context()` snapshot; list/detail, permission, cursor and authority revision share a composite generation. It never requests a worker refresh. |
| TF-005 | TEST_PASSED | Actual `/api/trips/{tab_id}/flight-bookings` route integrated at `_phase7_get`, with owner/visible-trip checks, 20 item maximum, generation-bound cursor and selected detail. Stale source returns 503; source generation mismatch returns 409; invalid limits return 400. |
| TF-006 | PARTIAL | Public `trip_flight_ui.render_trip_flights(tab_id)` returns collapsed initial HTML plus the lazy list/detail client. `ledger_board.py` passes `participant_query=query`, but the participant worker's matching `ledger_design.page` signature is not present in this checkout yet; UI integration awaits that owned change. |
| TF-007 | BLOCKED | No verified unsupported-provider source coverage was available within this worker's allowed evidence; therefore no adapter was added. |
| TF-008 | PARTIAL | Synthetic browser and signed HTTP tests passed. Live shadow, real source coverage and deployment were not run; no operational data was accessed. |

## Files

- `app/trip_flight_assignment.py`: pure assignment policy.
- `webapp/trip_flight_read.py`: booking projection, API contract, access and cursor helpers.
- `webapp/trip_flight_ui.py`: lazy accessible markup/client renderer.
- `webapp/tests/test_trip_flight_read.py`: synthetic policy/API/UI tests.
- `webapp/tests/test_trip_flight_ui_browser.py`: synthetic browser lazy-load/detail/HTML injection test.
- `webapp/tests/test_signed_session_http.py`: signed owner/viewer/anonymous/method and `/board` query forwarding integration.
- Existing `webapp/flight_passenger_page.py` was already present at baseline and contains the completed passenger assignment/search page. It was preserved without edits; expose `trip_flight_read.dispatch` through this existing route dispatcher rather than replacing it.

## Integrated routing and remaining UI hook

`webapp/ledger_board.py` now dispatches the route inside `_phase7_get`, using the request's signed session and `viewer_visible_tabs(session)`. The API reads only the flight worker's held `display_context()` and lazily extracts authority after trip access succeeds. `_phase7_write` refuses viewer writes with 403 and owner non-GET methods with 405. The no-enforcement fallback also routes to the fail-closed helper.

The public UI hook for the participant worker to call after `_is_trip_tab(tab_id)` is `trip_flight_ui.render_trip_flights(tab_id)`. It emits the collapsed `<section class="trip-flight">…</section>` and its script. No initial mail parse or API fetch occurs until expansion. Keep this section outside expense rows/totals/copy/export.

`ledger_board.py` now passes `participant_query=query` to `ledger_design.page(...)` for `/board` requests, as requested for the participant worker pagination contract. At this checkout the `ledger_design.page` signature has not yet been extended with `participant_query`; the handoff assumes that worker's pending change lands before combined integration. A synthetic route test verifies the query argument reaches the page call.

## Verification

- `python -m pytest webapp/tests/test_trip_flight_read.py webapp/tests/test_trip_flight_ui_browser.py webapp/tests/test_signed_session_http.py::SignedSessionHttpTests::test_trip_flight_booking_route_uses_signed_trip_visibility_and_snapshot -q` — 19 passed after route forwarding, stale-detail, authority read-only, 20-item limit, browser lazy-load and injection checks.
- `python -m compileall -q app/trip_flight_assignment.py webapp/trip_flight_read.py webapp/trip_flight_ui.py webapp/ledger_board.py webapp/tests/test_trip_flight_read.py webapp/tests/test_trip_flight_ui_browser.py webapp/tests/test_signed_session_http.py` — passed.
- `git diff --check` — passed.
- The browser test uses only synthetic API payloads; the authority DB test uses a temporary synthetic SQLite file and verifies its bytes do not change.
- No full suite, live mail, operational database, read-only production shadow, or deployment verification was run.

## Resume

Participant worker should land `ledger_design.page(..., participant_query=None)` so the already-wired `/board` request can consume its pagination state. Other-provider coverage remains the only source-coverage block. Main merge/deployment belong to supervisor. This worker did not push, create a PR, or deploy.

## Supervisor review corrections

Cold reads now start the existing background worker without synchronous parsing; opaque trip IDs are URL encoded/decoded; missing or invalid configured authority fails closed. Invalid trip periods are excluded before open-period boundaries and ambiguous overlapping trips remain conflicts. Stale UI state resets for retry and concurrent loads are blocked.

Affected read, synthetic browser, and signed HTTP route tests: **24 passed**. `git diff --check` passed. The real ledger UI still requires the participant signature and public hook integration; this branch must not deploy standalone. No live data or deployment was used.
