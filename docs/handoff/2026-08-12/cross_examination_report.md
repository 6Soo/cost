# Cross-Examination Report — Whole-Pipeline Redesign

**Date:** 2026-08-12  
**Scope:** `ledger/` pipeline code, schema, tests, and de-identified docs; no `ledger/data` rows or PII were read.  
**Branch:** `codex/p07-canonical-cutover-candidate` (`243fb8240eddbbcd71133c0788f8561064c5a2e4`)  
**Authoring slot:** Kimi Code CLI independent audit

---

## 1. Executive Summary

The current candidate is correctly fail-closed at **Gate6** and must not be promoted to production.  Sol’s technical findings about Gate6, the live-OTA manifest gap, card-parser integrity, and the large non-final Gate5 population are accurate.  Terra correctly diagnoses the missing closed approval state machine and the dry-run nature of owner review.  Luna’s proposal to split Gate5 into a triage gate (`G5T`) and a final gate (`G5F`) is the right structural direction, but it is **not safe by itself** unless it also removes arbitrary thresholds and guarantees that no provisional decision can ever produce an allocation or journal entry.

A safe synthesis is possible, but only as a **conditional plan** with exact invariants, gate conditions, and rollback rules.

---

## 2. Peer Positions and Claim Register

### 2.1 Sol — FAIL findings

| Claim | Disposition | Evidence / Reasoning |
|---|---|---|
| Gate6 has no success path | **Accepted** | `transition_gates_v2.py:3096` sets `passed = False` unconditionally after the diff is computed.  Tests confirm: a matching baseline with zero diff still returns `direct_baseline_authority_unavailable` (`test_verified_baseline_cannot_pass_without_event_diff`). |
| Live OTA bypasses the manifest | **Accepted** | `direct_sources.py:452-454` and `direct_high_coverage_classifier.py:756` import `ota_mail_live_index.json` when present, but `ota_mail_live` is **not** in `transition_gates_v2.REQUIRED_INPUTS` (`transition_gates_v2.py:72-76`).  A live mailbox can therefore alter classification without changing the input manifest hash. |
| Card parsing silently converts malformed amounts to zero / drops rows | **Accepted** | `cardindex.py:11-13` (`i(x)`) and `ingest.py:15-17` (`rn(x)`) swallow exceptions and return `0`; rows whose required amount is `0` are skipped (`cardindex.py:34,42,55,67`).  Malformed amounts therefore disappear silently. |
| Manual/policy paths violate current standing rules | **Accepted mechanism; conditional count** | `direct_high_coverage_classifier.py:3490-3491` returns `confirmed` for any path in `CONFIRMED_TRAVEL_TARGET_PATHS`, which includes `manual_travel_tab_exact` (`direct_high_coverage_classifier.py:195`).  This conflicts with `docs/비용분류_지시사항_원장.md` A-최신-여행분류예외, which allows manual travel-tab matches only as `needs_review` until the owner confirms.  The reported figure of “1,005” manual-confirmed paths could not be independently counted without reading data rows. |
| Gate5 passes with ~59 % non-final | **Accepted** | Latest handoff reports `final_count=2184`, `nonfinal_count=3144`, `candidate_payment_count=5328` (`docs/handoff/2026-08-12/01_current_state.md`).  Gate5 reports `accepted_with_auto_provisional_queue` because `untriaged_nonfinal_keys` is empty, not because the rows are final. |
| Posting / schema authority gaps | **Accepted** | HAN equality depends on an external `master_ledger.csv` and `han_master_authority.json` (`han_master_candidate.py`); Gate6 depends on an external baseline; the owner-review package is explicitly dry-run (`direct_owner_review.py:278`). |

### 2.2 Terra — shadow-builder / state-machine critique

| Claim | Disposition | Evidence / Reasoning |
|---|---|---|
| System is a safe shadow builder, not an end-to-end state machine | **Partially accepted** | The run is non-posting while `status='building'` and `direct_candidate_payments` is empty until validation passes (`direct_projection_schema.sql:878-885`).  However, the gate sequence is already a state machine; the missing piece is a closed approval state machine feeding Gate6 and an idempotent outbox. |
| Owner review is a dry-run | **Accepted** | `direct_owner_review.py:278` returns `dry_run_structurally_valid_not_authorized` and keeps `authority_ready_count=0`. |
| Gate6 / P07 are disconnected | **Accepted** | `p07_manifest.py` verifies artifact hashes and HAN equality, but it never consumes or validates the Gate6 baseline/approved-transition authority.  The baseline is supplied to `build_gate_report` but the manifest does not bind it. |
| Closed snapshots + approval state machine + idempotent outbox are required | **Conditional** | Necessary but not sufficient.  They must be accompanied by a non-circular bootstrap for the first baseline and by explicit rules that prevent provisional rows from being posted. |

### 2.3 Luna — redesign plan PASS, narrow G5T

| Claim | Disposition | Evidence / Reasoning |
|---|---|---|
| Redesign plan PASS but current candidate blocked | **Accepted** | The architectural plan is sound; the current candidate is blocked at Gate6 (`direct_baseline_unavailable`) and the HAN equality package is `applied=false` (`docs/handoff/2026-08-12/01_current_state.md`). |
| Narrow Gate5 triage retained as `G5T`, split from `G5F` | **Conditional** | Safe only if `G5T` is forbidden from creating allocations/postings and its result is never treated as cutover-ready.  A mere rename keeps the misleading `PASS` label. |
| Use `AuthorityClaim`/`QueueItem` with no provisional allocation/posting | **Accepted as principle** | Matches the standing instruction that `needs_review` rows must not flow to allocation, posting, or reporting (`docs/비용분류_지시사항_원장.md` A-최신-여행분류예외). |

---

## 3. Challenged Claims

### 3.1 A narrow `G5T` PASS is not automatically safe

Luna is correct that separating triage from final approval is the right architecture.  The challenge is on the **labeling**: the current Gate5 already behaves like `G5T` internally (it routes non-final rows into queues), but it reports a single `PASS` that can be mistaken for cutover readiness.  A safe `G5T` must:

- emit `triage_pass`, not `passed`;
- keep `auto_provisional` and `needs_review` decisions out of `allocation_plans`, `cost_allocations`, and `journal_entries`;
- require a separate `G5F` gate that passes only when `final_count == candidate_payment_count`.

Without these conditions, narrowing the gate just renames the risk.

### 3.2 Percentage thresholds are not evidence-based

Gate5 and the classifier use hard-coded constants:

- `TRAVEL_UNASSIGNED_ACCEPTANCE_LIMIT = 5` (`transition_gates_v2.py:124`)
- `human_question_group_max = 10` (`transition_gates_v2.py:2842`)
- `OTA_AMOUNT_TOLERANCE_RATIO = 0.02` (`direct_high_coverage_classifier.py:131`)

None of these is derived from an approved baseline or from explicit owner reasoning.  The standing instruction explicitly forbids “general ±2 %” as evidence (`docs/비용분류_지시사항_원장.md` A-최신).  Any claim that these thresholds are justified by the data is rejected; they must be replaced by baseline-relative limits or explicit owner-approved bounds.

### 3.3 A baseline can be bootstrapped without circular authority

Terra’s call for a baseline is necessary, but a first baseline cannot require a prior approved baseline.  A **genesis baseline** solves the circularity:

- The initial baseline maps every current event to a fail-closed terminal state (`여행_미배정`, `기타비용`, or `취소환불` where appropriate).
- It is approved once by the owner as a signed manifest.
- Every subsequent run diffs against the latest approved baseline; each changed or added event requires an approved transition artifact.

This is non-circular because the genesis state makes no claim about correct classification—it only records the starting point.

### 3.4 Externalizing dictionaries reduces risk only with governance

Moving hard-coded merchant/region dictionaries (`EXPLICIT_DOMESTIC_NONTRAVEL`, `REGION_COUNTRIES`, `KNOWN_DIRECT_TRAVEL_TOKENS`, etc.) into JSON config files reduces code-change churn, but it does not reduce semantic risk by itself.  Without versioned config, regression tests, and owner approval for config changes, the risk is simply moved from code to an ungoverned config file.

---

## 4. Minimum Safe Synthesis Plan

### 4.1 Invariants

| ID | Invariant |
|---|---|
| I1 | **Source immutability.** Every input is byte-hashed before parsing; no source that can alter classification may bypass the input manifest. |
| I2 | **Amount integrity.** The card parser rejects non-numeric required amounts; zero-amount rows are flagged in a review queue, not silently dropped. |
| I3 | **Manual non-evidence.** Manual travel-tab matches produce `needs_review` decisions only.  `confirmed` allocation_target requires verified external evidence (OTA/lodging/cancellation authority) or an owner-approved transition. |
| I4 | **Lossless partition.** Every payment is in exactly one of `{final, human_question, auto_provisional, untriaged}`; no overlaps. |
| I5 | **No provisional posting.** Decisions with `needs_review` or `auto_provisional` status have no active `allocation_plans`, `cost_allocations`, or `journal_entries`. |
| I6 | **Baseline lineage.** The first baseline is a genesis fail-closed state.  Later runs diff against the latest approved baseline; every changed/added event is covered by a signed approved transition. |
| I7 | **Config governance.** Merchant/region dictionaries live in version-controlled config; changes require regression tests and owner approval. |

### 4.2 Gate Conditions

| Gate | Condition |
|---|---|
| G1 | Same as today, plus add `ota_mail_live_index.json` to `REQUIRED_INPUTS` so live OTA is hashed and mandatory. |
| G2–G4 | Same as today, plus enforce I2 (malformed amounts fail ingestion, not drop silently). |
| G5T (triage) | `partition_gap_count == 0`; `untriaged_nonfinal_keys` empty; `travel_unassigned` unique-key count within a baseline-derived limit (genesis limit = 5); human-question groups within a baseline-derived limit (genesis = 10); all `auto_provisional` decisions are `needs_review` and have no allocations.  Result label must be `triage_pass`, never `passed`. |
| G5F (final) | `final_count == candidate_payment_count`; `auto_provisional_count == 0`; every resolved payment has three confirmed axes produced by independent promotion; allocation sums equal payment amounts; no finality vetoes remain. |
| G6 | `integrity_ok`; comparable baseline present; diff is empty **or** every changed/added event has a valid approved transition whose `after_semantic_sha256` matches the current run.  Only then set `passed = True`. |
| G7 | Same freshness/code-bundle check as today. |
| HAN equality | External authority required for activation; dev environment may use a mock that is explicitly blocked from `applied=true`. |

### 4.3 Rollback Conditions

| ID | Rollback Rule |
|---|---|
| R1 | Any gate failure keeps `run.status` in `building` or `failed`; no activation; no journal entries; no manifest state `candidate_ready_for_shadow` except for a `G5T`-only run. |
| R2 | A `G5T`-only run cannot be promoted to `passed`; the activation pointer must be rejected. |
| R3 | Any change to code, schema, config dictionaries, or parser logic invalidates the previous baseline; a new genesis baseline or owner re-approval is required. |
| R4 | After activation, contradictory evidence is handled by appending a superseding approved transition; sealed historical runs are never mutated. |

### 4.4 Verification Steps Before Promotion

1. Add unit tests that `G5T` can pass while `G5F` fails on the same candidate.
2. Add a unit test that Gate6 can pass with a zero-diff genesis baseline.
3. Add a unit test that Gate6 rejects any unapproved diff.
4. Add card-parser tests that malformed required amounts raise an error instead of returning `0`.
5. Add regression tests for dictionary config changes.
6. Require independent Sol/Luna re-verification of the full gate matrix before any `passed` promotion.

---

## 5. VERDICT

**Current candidate status: FAIL**

Gate6 has no implemented success path; Gate5 reports `PASS` while 59 % of payments are non-final; manual and OTA-tolerance paths can produce `confirmed` decisions that conflict with the standing instructions; live OTA and malformed-amount parsing bypass source-integrity checks; HAN equality and Gate6 depend on missing external authority.

**Synthesis plan verdict: PASS (conditional on exact implementation)**

The minimum safe synthesis plan in §4 satisfies the standing instructions and reconciles the peer findings, provided every invariant, gate condition, and rollback condition is implemented exactly as written and independently re-verified.
