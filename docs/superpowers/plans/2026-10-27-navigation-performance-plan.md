# Navigation read performance implementation plan

> For agentic workers: execute inline; final independent review. Follow user AGENTS for targeted verification and authorized PR merge/pinned deployment. Preserve workspace and existing user files.

**Spec:** User explicitly requests Aside REPL navigation measurements, root cause diagnosis and fixes for slow page transitions. Preserve auth, financial guards, customer originals, decisions and read-only GET behavior.

**Goal:** Reduce server wait in OTA/import pages and prevent avoidable expensive work from queueing other menus. No financial policy, data or schema changes.

**Architecture:** Keep server DB serialization intact. Reuse projection index within one `automatic_holds` call; inspect the catalog index build/signature before choosing its minimal fix. Read-only scopes never outlive a request. Stale display, if used, must be visibly labeled; strict write/detail validation remains fresh.

**Evidence:** Aside actual link clicks: cards 1.440s (TTFB .919s), OTA 16.795s (TTFB 16.359s), receipts .791s (TTFB .269s), board 2.307s (TTFB 1.855s), import 23.768s (TTFB 23.232s). Source-copy cleanup profile 10.812s: `automatic_holds` 8.636s; 1,374 `_projection_index` calls repeatedly aggregate all board rows, 7.494s. Background full OTA worker is separate and must not be triggered by profiling.

## Tasks / single verification boundary

1. Add synthetic guard-parity/query-count regressions to `webapp/tests/test_navigation_read_performance.py`, watch fail, reuse one index in `automatic_holds` without changing matching rules. Preserve transaction identity, signed legacy key and fresh next-call state. Verify with existing relevant projection/refund checks; compare the same source copy profile after changes once.
2. Identify catalog profile hot path. Add targeted regression before modifying it; keep changes to reads, no migrations/financial writes. Verify only catalog/profile-adjacent tests.
3. Review complete branch independently (code and synthetic evidence only), commit/PR/merge, fixed-SHA deployment with existing restore evidence and one health/protected-route smoke. Repeat exact Aside link routes once and record TTFB/DOM separately. Record results in operations/current handoff. No whole pytest/browser suite or actual ledger writes.

**Review focus:** projection source/decisions freshness; manual/financial/refund guards unchanged; catalog freshness labeling and write validation; thread/board ownership and lock order; no source contents or credentials in profiling outputs/Git.

## Implementation / evidence ledger

- Root causes: per-row projection version aggregate, repeated refund display matching/count checks, catalog GET legacy fallback when central snapshot is pending, startup prewarm holding the publication lock, and identical trip boundary calculation inside every booking iteration.
- RED reproduced each new performance contract. Changes reuse projection once per batch hold scan and refund display data once per render, use fresh canonical snapshot or pending state, move index computation behind a separate builder lock, serve visibly provisional catalog while refreshing, and compute trip handover boundaries once per build. Strict detail/write lookups remain synchronous and fresh; global server DB serialization is unchanged.
- Same source-copy cleanup profile: 10.812s before / 2.092s final, projection scans 1,374 → 2; catalog foreground after 0.723s. Initial cold catalog profile was stopped when full legacy fallback was identified; a subsequent synchronous no-fallback build still took 114.753s under cProfile (mail parsing 82s and repeated boundaries 27.5s), confirming the need for asynchronous list reads. These are profile timings, not browser acceptance numbers.
- Verification: projection/refund boundary checks 19 passed; catalog/booking/performance checks 31 passed; after bulk refund optimization 39 passed / 4 failed. One old unlinked copy assertion also fails at baseline cb7c575 and remains out of scope. Three old async tests were updated to seed a complete index explicitly and then passed (3 passed / 22 deselected). Final performance/catalog selection: 19 passed. No full regression.
- Independent review identified disk serialization/save and stale-file loading still under the publication lock. Moved both outside that lock while retaining the single builder lock and atomic file replacement. Added build/save contention regression (save failed before fix); relevant concurrency/stale/save selection: 6 passed. Reviewer follow-up found no actionable issues. Financial projection/duplicate/existing-ledger selection: 18 passed, 8 subtests passed; save failure preservation test passed.
- PR #139 merged and pinned Windows deployment completed at a08cb815aa54be08a8361892a6fec3802aed616b. Release 956 blobs match; runtime/task SHA, health/ready 200, protected API 401 verified. Two DBs / 13 protected table content/schema hashes unchanged. See operations latest entry for evidence.
- Local profiles/copy under `.local-archive/navigation-20261027`, never Git. Existing untracked 2026-10-26 plan preserved. Actual after-deployment expense page observed, but Aside Page.navigate then Runtime.evaluate timeouts prevented five-menu timing: NOT_MEASURED / PARTIAL. Next command: Aside attach a working COST tab, snapshot nav then actual link clicks and navigation timing for the same five routes. Do not repeat successful tests/deployment or claim browser performance acceptance from profiles.

## Retry / remaining board bottleneck

- User requested retry; existing COST tab now responds. Actual #139 after-click/TTFB/DOM ms: cards 3221/2594/2867, OTA 8874/3284/3527 (Aside readiness wait 4311ms), receipts 5057/4118/4295, board 7517/6907/7111, cleanup 2968/2563/2725. Same browser health GET 215ms. Cleanup/OTA server wait improved, while common request contention and board computation remain observable; do not claim every page became faster from this sample.
- Board source-copy profile: 126 list_tab_rows calls (every tab read for both income and expense), 3.456s. Share tab reads only inside existing read_scope; copy rows before display projection, preserve next-render freshness. After profile 63 calls, 1.152s (timings include variable host load; call reduction is deterministic).
- New synthetic test failed for duplicate calls before fix then passed, with identity/amount/revision parity and SQLite dump unchanged. Read scope selection 2 passed; adjacent refund display/split/allocation/remainder selection 15 passed plus 3 subtests. No full suite or source migration. Pending independent review, pinned deployment and exact menu click acceptance.

## Cold-start contention discovered during acceptance

- #141 deployed bc7cd0bb993576e92c3417b2da02a825e0cba615; actual first cards click returned524. Rolled back to prior a08cb815aa54be08a8361892a6fec3802aed616b with task/process/health/ready/401 verified. A further import request on a08 also queued (ready timed out8s), so the shared-row change is not established as the cause. Two old-release reconciliation child processes left after deployment were identity/ancestry checked and stopped; current listener was excluded. No original/DB files removed.
- Read-only py-spy stacks on a08: catalog startup parsing mail on an active GIL thread, import inside pipeline preview→tab_valid→trip_valid→get_trip, another HTTP request awaiting store_lock. Later sample had no active request/prewarm thread. This establishes overlap and shared request queueing, not a financial policy defect.
- Preview repeatedly validates identical trips/tabs and may reread schedule evidence per transaction. Cache only the bound validators local to one read-only cleanup render; actual write validators and next render remain current. New synthetic RED16 calls→GREEN2, changed validation seen on next render, DB dump unchanged. Cleanup/refund selection15 passed. Pending independent review and final deployment/menu timing. Keep previous acceptance explicitly incomplete until actual clicks pass.
