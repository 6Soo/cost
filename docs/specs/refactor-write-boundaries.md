# RF-001 R0 write-boundary map

Status: **PARTIAL — static source map, manual/runtime confirmation open.** This document and `tools/audit_write_boundaries.py` inspect source text only. They do not connect to application databases, read customer records, or establish runtime behavior.

## Evidence map

| Flow | Source evidence | Static boundary / controls | Manual confirmation |
|---|---|---|---|
| Representative card save | `webapp/card_flow.py:1560` (`persist_card_trip_move` is a concrete card mutation example); `webapp/ledger_board.py:243` (`require_session`); `webapp/ledger_store.py:6703` (`_finalize_board_request`) | HTTP entry is in board; persistence and request replay are in store. AST CLI reports callable decorators and literal SQL candidates. | Resolve exact route-to-store call chain, CSRF, expected revision semantics, request key scope, and audit event atomicity. |
| OTA preview / confirm | `webapp/ota_payment_review.py:1100` (`preview`), `:1116` (`confirm`), `:1157` (`confirm_group_order`) | Preview and confirm are separate service methods; confirm accepts request ID and user. | Confirm route authorization/CSRF and exact persistence/audit sink remain manual checks. |
| Travel movement | `webapp/card_flow.py:1527` (`_trip_move_origin_revision`), `:1548` (`_trip_move_is_current`), `:1560` (`persist_card_trip_move`); `webapp/ledger_board.py:5323` (`_handle_trip_meta`) | Revision-aware move candidates exist; the CLI cannot prove which HTTP route reaches them. | Verify stale revision rejection and audit event linkage for the specific move path. |
| Refund | `webapp/card_flow.py:1866` (`refund_group_views`, projection); `webapp/ota_payment_review.py:1116` (`confirm`) | Projection name alone is not a refund write. | Exact refund mutation route, CSRF, idempotency, and audit sink remain open pending call-chain tracing. |
| Login / access | `webapp/ledger_board.py:243` (`require_session`); `webapp/access_control.py:445` (`session_for`), `:719` (`ensure_owner`), `:896` (`require_owner`); `webapp/ops.py:1366` (`_synthetic_sessions_allowed`) | Session, owner bootstrap, and owner authorization are distinct source operations. | Confirm middleware/decorator ordering, CSRF validation, cookie attributes, and owner bootstrap configuration without reading secrets. |
| Google read | `webapp/ledger_board.py:327` (`google_oidc_connection_state`); `webapp/ledger_store.py` read APIs; `webapp/access_control.py` viewer projection/role controls | Read path must remain distinct from COST writes to final Google ledger. | Concrete Google view-to-provider call path and absence of write calls remain manual checks. |

## Source facts and limits

The relevant protected implementation is concentrated in the six target modules named above. `access_control.py` defines role/session/access rules and schema constraints; `ledger_store.py` contains transactional SQL, revision/request tables, and audit/outbox helpers; `ops.py` includes health and recovery/readiness helpers. These observations describe source structure, not a verified end-to-end route.

Use the CLI to generate a machine-readable candidate inventory:

```powershell
python tools/audit_write_boundaries.py --pretty
```

The output deliberately separates `STATIC_CANDIDATE`, `STATIC_NONWRITE`, and `OPEN_QUESTION`. It does not claim that a decorator protects a route merely because its name resembles an auth control. F-strings, aliases, dynamic dispatch, indirect calls, framework hooks, and transaction behavior require manual confirmation. R1 runtime/DTO extraction is outside this R0 artifact.

## Completion gate

R0 source mapping is partial until each representative path above has an exact route → authorization/CSRF → validation/revision/idempotency → persistence/audit-sink chain with path and line references manually verified. No customer-source files, secrets, or live databases are inputs to the audit tool.
