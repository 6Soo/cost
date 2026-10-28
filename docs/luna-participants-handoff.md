# Participant and trip-flight integration handoff

Base 496cbbe; participant checkpoint 356b918, real table corrections f3c68ad. The feature branch merges immutable flights through 0cd571f. The subsequent hook commit connects the existing public flight renderer after expenses and supplies the matching participant_query page signature.

## Implemented

Actual trip order is Google income, lazy insurance gallery, expenses, collapsed flight bookings. There is one real income table. Its virtual insurance cells receive link states and unlink controls after owner-only expansion. Both keyboard and drag selection require explicit confirmation and reuse the existing fingerprinted owner/CSRF endpoint; successful JSON writes reload the board rather than navigate to JSON. Failure keeps the page and shows an error. No new financial or Google write path is added.

Initial insurance HTML contains no roster names and performs no roster reconciliation. Expansion uses existing read-only participant reconciliation, bounded 20 income rows/20 confirmed active participants and bounded search/paging. No pending/inactive participant can be selected. Paging encodes opaque IDs and lazy requests preserve controls. Canonical Google row identities are attached to display copies, leaving the source untouched. Income amounts and verification gates remain intact; browser fixtures supply real cached formula totals rather than bypassing the gate.

## Verification

Combined participant projection/HTTP/browser, flight read/browser, signed flight route: **61 passed**. Includes synthetic 375px real board lazy loading, single income table, drag cancel without writes, confirmed POST200, board URL retained and the new link reflected in synthetic state, plus readonly authority and stale generation boundaries. No actual customer data, Google writes, registration, production database, deployment, push or PR performed. `git diff --check` passed.

## Remaining boundaries

Supervisor owns normal main PR integration and SHA deployment. This bundle must be tested against latest main shared styles and route changes before deployment. Unsupported flight providers and production source coverage are unmeasured. Actual insurer evidence and production participant transfer remain separate operational approvals. Provisional assignment UI and authenticated correction-proposal API are separate unfinished scope, not completed by this bundle.
