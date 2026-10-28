# Luna UI handoff — 2026-10-28

Start: `origin/main` = `496cbbe9778e002bc4265f28b50da704d28f042c`; branch `feat/luna-ui-20261028`.

| Requirement | State | Evidence / remaining |
|---|---|---|
| RF201 | CODE_WRITTEN | `ledger_design.css` provides reusable form/filter/error/stale/loading styles; no existing consumer markup changed. |
| RF202 | CODE_WRITTEN | Theme remains one sun/moon toggle; reduced-motion rule added. |
| RF203 | TEST_PASSED | Asset contract and keyboard choice/persistence, both theme modes, reduced-motion preference, touch target and widths 320/390/760/1024/1440: targeted command passed (6 tests, 5 subtests). |
| RF204 | PARTIAL | Shared inline state styles implemented. This checkout has `webapp/refund_tab_ui.py`, not assigned `webapp/refund_review.py`; no unowned UI module modified. |
| RF205 | PARTIAL | Synthetic browser matrix only; 200% zoom and physical-device acceptance not established. |

Validation: `pytest webapp/tests/test_site_shell_assets.py webapp/tests/test_site_shell_browser.py::SiteShellBrowserTests::test_theme_keyboard_motion_and_responsive_contract webapp/tests/test_site_shell_browser.py::SiteShellBrowserTests::test_theme_override_and_reduced_motion -q` → 6 passed, 5 subtests passed.

Broader targeted run `pytest webapp/tests/test_site_shell_assets.py webapp/tests/test_site_shell_browser.py -q` → 9 passed, 4 failed, 13 subtests passed. Failures: an existing Korean label rendered as mojibake in `get_by_label`, `/google-ledger` returned 404, and the shared-sidebar visual comparison found route-dependent selected-link background on `/cards` versus `/import`. Those fixtures/routes/classes were not changed in this work; failure reproduction on an untouched baseline was not performed, so treat them as unresolved baseline candidates rather than proven baseline failures.

No production/customer source, operational database, authentication, Google, or insurance access/write. No push, PR, or deployment. No full-suite run. Synthetic fixtures only.

`docs/session_handoff.md`, `docs/operations.md`, `webapp/ledger_board.py` were not modified. Remaining acceptance: inspect/attach shared state classes to owned consumers when the correct refund UI ownership is supplied; 200% zoom and physical device acceptance. No baseline was updated.
