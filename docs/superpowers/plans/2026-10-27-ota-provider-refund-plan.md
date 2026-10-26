# OTA provider scope and zero refund implementation plan

> For agentic workers: execute the approved scope inline, one final independent review. User AGENTS authorizes routine implementation, targeted checks, PR merge and deployment without renewed approval; preserve the existing workspace.

**Spec:** User 2026-10-27 screenshots and requests: remove unrelated OTA comparisons in engine/UI, Trip events only against Trip-related merchants, show actual amounts, inspect linked full refund stuck in review. Existing full-offset policy: `app/ledger.py:REFUND_TAB`.

**Goal / changed behavior:** Match/search uses provider compatibility before amount comparisons; the cleanup view shows actual card and OTA payment amounts. Classified, linked full-offset groups no longer wait for an automatic trip selection. No operating transaction/ledger/Google writes.

**Architecture:** Reuse shared alias rules in `app/ota_payments.py`; preserve explicit links and unfiltered date browsing. Filter historical unconfirmed candidate notes in `webapp/card_flow.py` using the same compatibility predicate. Remove only automatic `trip_needed` for a complete, linked full refund; leave core commit and all persisted holds intact.

**Global constraints:** Windows PowerShell/UTF8. No customer source/identifiers in Git or delegated context. No migrations, broad regression, import, reclassification or live commit. No arbitrary FX conversion. Existing manual/frozen links remain occupied.

**Review focus:** Approved provider aliases and unknown processors; same-card cross-provider collisions; historical snapshot notes and missing metadata; partial/excess/multi-refund and cross-batch groups; persisted holds/exclusions and immutable source/decisions.

## Tasks and completion gates

1. Add synthetic engine tests in `tests/card_pipeline/test_ota_provider_scope.py`: cross-provider rows must never be candidates, rejected amount comparisons or auto matches; Trip with unknown merchant and matching last4 must not auto match, but Trip merchant aliases still work. Watch RED, implement shared provider predicate and early filtering in exact/search/pair checks, run this file and relevant matching/defaults tests once.
2. Add cleanup rendering tests in `webapp/tests/test_cleanup_ota_contract.py`: legacy cross-provider rejects disappear; Trip note shows card KRW and OTA native amount/currency, including missing fields and escaping. Watch RED, implement in `_index_ota_display_candidates`, verify rendering reads do not write.
3. Add tests in `webapp/tests/test_cleanup_refund_display.py`: classified full refund with blank trip can preview both rows in refunds; partial/excess, active holds, source conflict and absent batch member remain blocked. Watch RED, remove only automatic trip hold in `CardFlow.automatic_holds`. Verify pair source/decisions unchanged and synthetic group commit stays atomic/idempotent using existing tests.
4. Review fixed diff independently using code/synthetic data only. Commit/push/PR/merge after required targeted checks. Reuse verified release/restore procedure, audit Git blobs, pin SHA, health/ready/protected GET and changed view smoke once. Record actual results and remaining external blockers in operations/current handoff. No document-only redeployment.

## Evidence / ledger

- Investigation: candidate search compares amount before provider, `_has_corroborator` has unconditional Trip fallback. Both linked full refund rows are classified, unassigned, unrecorded, with no persisted review hold; net zero link exists. `automatic_holds` adds `trip_needed` to original and propagates it to the pair.
- RED: new targeted scope showed 10 failed / 8 passed (wrong-provider automatic links, missing amounts, full-offset trip hold reproduced).
- GREEN: scope/cleanup/refund files 36 passed. Adjacent matching/defaults/refund integration 149 passed / 1 failed; the one fixture intentionally allowed Agoda→Trip, so its allowed merchant was corrected to Agoda under the new policy; its focused rerun passed with UI/index checks (20 passed / 38 deselected). Backend/snapshot action boundary checks 23 passed / 33 deselected.
- Matcher policy version now participates in snapshot input keys; no parser version bump or source changes. Legacy amount-mismatch comparisons no longer count as valid payment candidates. Manual/automatic established result history remains visible.
- No whole regression or operating transaction/ledger writes. Existing untracked open-work plan remains untouched. Pending: final independent review and pinned deployment/smoke/evidence.
- Independent review confirmed undated inference/scheduled-card bypasses; both were separately reproduced RED and fixed before amount checks. Follow-up tests: provider/inference 34 passed; exact/scheduled 35 passed, 2 legacy Trip-unrelated expectations updated to related Trip fixtures with explicit unrelated rejection. Original `classification_needed` refund inheritance is pre-existing and preserved; the only removed original hold is automatic `trip_needed`.
- Delivery: PR #135 merged and release `909e4ad4ffc3ca4786d61a8b01686101406c79c7` deployed. 953 files blob verified, task/process SHA aligned, health/ready 200 and protected API 401. Protection hashes for 13 tables across two DBs unchanged. Implementation/review/host checks COMPLETE; final authenticated screen/375px PARTIAL due Aside navigation then Page.enable timeouts. See operations/current handoff for precise resume boundary; no real ledger changes.
