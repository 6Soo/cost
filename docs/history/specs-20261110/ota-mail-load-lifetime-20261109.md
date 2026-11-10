# OTA mail load lifetime — 2026-11-09

Scope: complete the PC investigation's remaining OTA memory/CPU fix and leave a
COST PR. Process ownership and emergency-wrapper migration already merged in
[PR #754](https://github.com/6Soo/cost/pull/754); they are not reimplemented here.
This PR does not restart operating tasks, merge itself, or deploy.

## Cause and behavior

The message loader retained every observed message in `_BODY_TEXT`, including
superseded observations of the same ID. It also retained full comparison bodies
until the load ended. Store loading eagerly collected every source scope, and
integrity checks joined entire canonical JSON representations in memory.
Concurrent cache misses could each parse the same source before publishing.

Keep only the last canonical message/body per ID, compare content digests, and
publish body entries only after the complete load succeeds. Iterate verified
store scopes instead of collecting them all, stream the existing canonical JSON
hash, and serialize each memo's lookup/fill. Collection counts, ordering,
conflict/hash failures, caller copies and source invalidation retain their
existing meaning. An older snapshot can still decode its own payload after its
body cache is replaced. Source scope loading still decodes one complete revision;
this is not a constant-memory parser for arbitrarily large individual sources.

## Reproducible synthetic measurement

Windows, Python 3.14, fresh process per phase. Same fixture before/after: 80 unique
messages observed in four source scopes (320 observations), each with 128 KiB of
synthetic attachment metadata. No operating source is opened. Baseline checkout
`3b22f027` has the same mail/store/catalog/reconcile modules as main `db7ce995`.

| Phase | Peak private bytes before → after | Peak working set bytes before → after | CPU seconds before → after | Wall seconds before → after |
| --- | --- | --- | --- | --- |
| Catalog | 503541760 → 450428928 | 125976576 → 92258304 | 2.640625 → 2.515625 | 3.721563 → 3.785509 |
| Reconcile | 507183104 → 453758976 | 129904640 → 96538624 | 3.062500 → 2.750000 | 5.553878 → 4.021766 |

Retained body entries: 320 → 80 in both phases. Both return 80 rows, identical
normalized result digests, and unchanged source bytes. Source SHA-256:
`5d8b379cfdcf32a36b99a99882efca73cc934cfeeb277e04d8cb6348513bb0b0`.
Catalog result: `4754942c51d779e020765e68f5d3c8aeb775205d8977d0a42ad0c265e63f7a38`.
Reconcile result: `310929166451406e170a2ad0df54c2d18e830a7e9f69377018585f93d0e8eb14`.
These are single-run samples under varying machine load, not p50/p95 claims.
Catalog wall time did not improve in this sample. Memory fell about 11%; this
does not establish resolution of operating 1.5 GB workers or a long-term leak.

Run the candidate's tool from PowerShell, using a new dedicated fixture path:

```powershell
python tools/benchmark_ota_mail_load.py --fixture C:/AX/tmp/ota-mail-synthetic --phase create
python tools/benchmark_ota_mail_load.py --fixture C:/AX/tmp/ota-mail-synthetic --root C:/path/to/baseline --phase catalog --output C:/AX/tmp/catalog-before.json
python tools/benchmark_ota_mail_load.py --fixture C:/AX/tmp/ota-mail-synthetic --phase catalog --output C:/AX/tmp/catalog-after.json
python tools/benchmark_ota_mail_load.py --fixture C:/AX/tmp/ota-mail-synthetic --root C:/path/to/baseline --phase reconcile --output C:/AX/tmp/reconcile-before.json
python tools/benchmark_ota_mail_load.py --fixture C:/AX/tmp/ota-mail-synthetic --phase reconcile --output C:/AX/tmp/reconcile-after.json
```

Creation refuses an existing directory; measurement requires its synthetic marker
and unchanged source hash. The tool writes only its synthetic fixture/request/
result files and optional measurement reports. Compare status, rows, source hash,
result hash and source_unchanged before interpreting resource differences.

## Validation and remaining acceptance

- Initial candidate `00d16813`: impact QA 246 passed, 4 subtests passed, skip 0,
  compile passed. Includes financial exact-link/refund/Google-readonly/access
  protections and ten synthetic browser cases.
- Initial expanded adjacent mail/store/registry run: 87 passed, one failed. The failure,
  `test_registered_missing_source_blocks_new_classification_without_writes`,
  also fails on baseline `3b22f027` (DID NOT RAISE StoreError). It concerns missing
  sources blocking all expense classification, an obsolete pre-DEST expectation.
  The updated regression retains the evidence-stage rejection and zero-write
  assertion, then verifies public classification completes in the payment quarter
  while preserving original financial fields, the missing-source diagnostic and
  empty booking authority. Four missing-source cases pass; the initial red result
  is retained separately. No test is skipped or removed from impact selection.
- Final SHA impact QA is recorded in the PR. No customer source, financial
  original, Google ledger, authentication setting or operating task is changed.
- Operating peak memory/CPU, restart/crash lifecycle acceptance and long-running
  leak behavior remain unverified by this PR. Deployment and its data safety
  gates belong to the release owner after review.
