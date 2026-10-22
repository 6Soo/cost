# OTA-first verification plan

1. Development runs targeted synthetic tests only. Core and UI writers have disjoint ownership.
2. Coordinator alone runs operational verification locally, with SQLite mode=ro and query_only. No private source data is supplied to delegated agents.
3. Before verification, record all operating transaction/user-confirmation/hold/ledger tables and all registered source file digests. Legacy exact baseline contains 200 unique card transactions and 734 ledger rows.
4. Extract canonical OTA events from source evidence independently of card transactions. Build migration links only after event identity/source digest/provider/booking/amount/direction have been checked against the already verified legacy exact link. Preserve these links, do not recompute different cards.
5. Verify all 200 bindings reproduced, incorrect replacements=0, global duplicate assignments=0. A failed parity gate forbids production authority cutover. Report genuine evidence gaps without making up payment dates or monetary events.
6. Count all events by actual charge/refund/pending/noncharge. Count OTA event HOLD states independently from old unmatched card rows. Reconcile each of the 177 old unmatched card rows to an evidence-backed event or to an explicit no-monetary-evidence residual. Never assert 177 cards = 177 payments without proof.
7. Verify manual confirmation, preview digest stale protection, original inputs unchanged, linked-card reuse blocked, manual links persist across refreshed evidence, no automatic active rules, narrow explicit rule approval, once-only choice, incremental new-card/source refresh in synthetic tests.
8. At 390x844 and 1440x900, a local synthetic HTTP browser test checks all 12 same-date rows, original columns, connected-card labels, preview difference, manual confirmation, proposal status, and zero horizontal overflow. Real customer browser sessions are not part of this task.
9. After the final targeted tests and read-only parity pass, execute full regression once in isolated checkout. Preserve exact log/exit code. No repeated full regression.
10. Compare operating code/protected files/source digests/business tables after all work. Record production cutover=false, commit=false, push=false. Current production checkout remains 37bd457341d68185d533a243eada64162537f943 plus preserved unrelated working changes.
