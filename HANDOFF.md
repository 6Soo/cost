# Luna ops worker handoff

Base SHA: `496cbbe9778e002bc4265f28b50da704d28f042c` (matches origin/main at start).

Scope RF003/005/109/301. Planned owned paths: `tools/runtime_preflight.py`, `tools/verify_lightweight_runtime.py`, `tools/run_lightweight_deployment.ps1`, `config/ops_entrypoints.json`, `tests/test_runtime_preflight.py`, and this handoff. Do not modify Supervisor-owned docs/session_handoff.md, docs/operations.md, or config/ledger_board.py.

- CODE_WRITTEN: pending.
- TEST_PASSED: pending targeted synthetic/temp-only tests.
- External blocks: no production host, operations DB, source data, credentials, Google, or insurance access permitted; no push/PR/deploy.
- Required controls: explicit CLI contract, fail-closed guard classification, duplicate launcher convergence, source-data exclusion checks, data-root/secret/feature-flag preflight.
- Final diff / commit / command: pending.
