# Luna UI handoff — 2026-10-28

Starting baseline: `496cbbe9778e002bc4265f28b50da704d28f042c` (`origin/main`). First implementation commit: `5da0ca120a3df7df32b0c00bc8b73f130c2e879e`.

| Requirement | State | Evidence / remaining |
|---|---|---|
| RF201 | CODE_WRITTEN | Shared styles bind to live `.bar` filter form and `.arch-restore` form; state rules alias current `.status`, `.status.err`, `.f-msg.err`, `.copy-status.err`, `.cleanup-snapshot-stale`, and `.cleanup-snapshot-loading` consumers. Refund UI uses shared card/status components and ledger design tokens. |
| RF202 | TEST_PASSED | One sun/moon toggle, persisted manual choice, mobile 320/375/390 and desktop 760/1024/1440 verified. |
| RF203 | TEST_PASSED | Keyboard toggle/focus, light/dark color token behavior on actual `/board?tab=refunds`, reduced-motion spinner, and 200% CSS zoom at 375px passed in synthetic Chromium. |
| RF204 | TEST_PASSED | `refund_tab_ui.py` uses shared `ui-card`, heading, and `ui-state`; removed fragment-local inline CSS. Refund amount, group and filtering semantics compare to the prior renderer after normalizing only the intentional style/class migration. |
| RF205 | PARTIAL | Synthetic browser acceptance passed. Physical-device acceptance remains external and unperformed. |

Baseline audit used a detached clean worktree at exactly `496cbbe9778e002bc4265f28b50da704d28f042c`. All four previously reported failures reproduced (one wrong accessible label, one retired route, and two viewport subtests comparing active-link styling). The test expectations now match the real label (`여행 검색`), live routes (removed `/google-ledger` excluded), and compare neutral links while preserving active selection behavior. Full current browser file passes after these corrections.

Final targeted runs:

- `pytest webapp/tests/test_refund_tab_ui.py webapp/tests/test_site_shell_assets.py -q` → 13 passed.
- `pytest webapp/tests/test_site_shell_browser.py -q` → 7 passed, 16 subtests passed.
- Combined targeted run before the last CSS alias cleanup → 18 passed, 16 subtests passed; the final two commands above ran after that cleanup.

All tests use synthetic fixtures and temporary data. No production/customer source, operational DB, authentication, Google, insurance, push, PR, or deployment used. No full project suite run. `docs/session_handoff.md`, `docs/operations.md`, and `webapp/ledger_board.py` remain untouched.

Follow-up commit: `c1c76b19ac53e6496b5c4f62270b1e934dda4127`. Remaining external acceptance: physical device only.
