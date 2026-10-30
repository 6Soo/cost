# Reviewed temporary branch integration (2026-10-30)

The user requested checking and merging temporary branches rather than retaining archive branches.

45 previously unmerged refs contain 90 unique non-merge commits. 61 have exact stable patch equivalents in main. The remaining 29 were checked against the later implementations and current policy below. No additional valid runtime delta was identified.

The history merge explicitly uses the `ours` strategy after review: it joins the already integrated and superseded histories while keeping the current tree unchanged. It is not a new application of obsolete code. All these tips become main ancestors after normal PR merge, allowing branch deletion without backup refs.

Focused verification: 108 passed for refund replay, trip authority/provenance, cloud readiness, participant runtime, sheet linkage/projection and quarter assignment. No operating data writes.

| Reviewed commits | Resolution |
| --- | --- |
| `54f50ba` | Split and integrated as PR373 completion plus PR374 validated OTA facts; shared assignment verdict and invalid-fact tests retained. |
| `4417bd1` | Superseded by current finance mandatory best-trip inference and PR357 rerun; do not restore historical no-trip exemptions or skip verified refunds by old classification alone. |
| `a1d2bc8`, `cfd8e25` | Inverse historic cancellation experiment/revert; current manual/recorded-refund restoration and protected-source guards take precedence, never blanket-route historical cancellations. |
| `9eb4910`, `b54a94e`, `9142e25` | Current app/ledger.py retains locked post-digest/revision/ledger-fingerprint replay with stronger complete membership checks; refund group commit tests pass. |
| `8c9a0f7`, `a727950`, `e44689b` | Current provisional review and OTA projection preserve manual versus inferred provenance and classified refund destination; focused source/review tests pass. |
| `4fbff06` | Reject blanket inferred-refund auto-recording and 30-day broadening: current finance explicitly retains 14-day Kakao pairing plus financial/occupancy/manual guards; current validated-pair implementation wins. |
| `d1d9042` | Trip authority already repaired and delegated to webapp/card_trip_authority.py; focused authority test passes. Do not restore interrupted WIP wholesale. |
| `d96c775` | Cloud implementation superseded by current full-coverage verifier with duplicate-key, ID and calendar validation; cloud tests pass. |
| `4f756a5` | Shared OTA tokens/control size/mobile/focus declarations already present in current render_import_section; no missing UI delta. |
| `117e3db`, `1ca4586`, `aaa1ca0` | Current source classifier terminal-summary hardening, public snapshot DTO and classified inference contracts supersede old test edits. |
| `cf49378` | Current runtime checks include malformed schema/receipt handling, non-disclosing diagnostics, ready_for_receipt_check versus accepted, and real CLI status; participant tests pass. |
| `e4a28d1`, `189bbc2` | Current sheet reconciliation refreshes selected main/archive source before export and validates revision/digest plus COST context; later TSV adapter/source protection supersedes old draft. |
| `801fb62` | Current canonical store/engine adapter maps stable_key and user_override; stricter USER_CORRECTION_PROTECTED and request_context protections supersede alternate duplicate alias storage and silent manual-refresh draft. Link/projection tests pass. |
| `6249002`, `b8d0aaa` | Current CUV/SDD specification and status include subsequent implementation, acceptance and deployment; do not regress to CODE_NOT_CHANGED or OPEN status. |
| `be58c0f`, `3cd6f8e`, `1e9b81c`, `2276740`, `4632e45`, `9cceac8` | PR371 and PR373 already integrate quarter ASSIGNED status, common SQL/UI/completion verdict and human-readable provenance/conflict labels; consistency tests pass. |

Runtime and user working-copy changes remain distinct. The dirty primary checkout is not part of temporary worktree deletion. No old policy or stale acceptance claim is restored.
