# 문서 보관함

현재 작업은 [시작 안내](../COST_V3_START_HERE.md)와 [현재 상태](../session_handoff.md)에서 확인한다. 이 보관함은 과거 원문을 찾기 위한 곳이며 실행 큐가 아니다. 기록 당시의 미구현·READY·HOLD·배포 SHA를 현재 사실로 재사용하지 않는다.

## 보관 묶음

| 찾는 정보 | 문서 |
| --- | --- |
| 2026-11-10까지의 주제별 명세 112개와 인계 문서 | [과거 명세](specs-20261110/README.md) |
| 정책 변경·예전 상태표·세션 인계 | [제품·인계](product-and-handoffs.md) |
| 변경별 구현 계획·검토·테스트·화면 감사 | [구현·감사](implementation-and-audits.md) |
| 2026-10-27까지 실제 배포·운영 검증 전문 | [운영 이력](operations-through-20261027.md) |
| 2026-10-28~11-07 직전 릴리스·배포 기록 | [운영 기록 10/28~11/07](operations-20261028-20261107.md) |
| 2026-11-07 이전 인계·상태표 | [이전 인계](session_handoff-through-20261107.md) |
| 은퇴한 OTA-first 정책·실험·옛 실행 계획 | [구형 OTA](ota-legacy.md) |
| 2026-10-29 계약으로 대체된 잠정 여행 귀속 설계 | [이전 PA-01~06 명세](provisional-assignment-review-first-20261028.md) |

## 정리 원칙

중복 진입점은 시작/현재 상태/운영 문서로 통합했다. 상세 명세는 `specs`의 주제별 일곱 문서로 모았고, 기존 본문은 내용과 출처를 보존해 절별로 옮겼다. Markdown 링크는 새 파일·절로 연결한다. 당시 경로가 본문에 문자로 남아 있으면 아래 표에서 찾는다. 고객 원본·JSON 증거·미추적 사용자 계획은 이동하거나 통합하지 않았다.

통합 전 Markdown87개(그중 docs80개)를 통합 후21개(docs15개)로 줄였다. 기존 미추적 Markdown과 원본 수집용 TXT/JSON은 이 집계에서 제외한다. 시작 안내·현재 상태·운영 기록을 먼저 읽고 필요한 명세 절만 확인한다.

## 옛 경로 찾기

| 통합 전 파일 | 보존 위치 |
| --- | --- |
| `AGENTS.md` | [해당 절](product-and-handoffs.md#src-agents-md) |
| `README.md` | [해당 절](product-and-handoffs.md#src-readme-md) |
| `docs/COST_PENDING_WORK_AND_FLIGHT_BOOKING_DATE_20261027.md` | [해당 절](product-and-handoffs.md#src-docs-cost-pending-work-and-flight-booking-date-20261027-md) |
| `docs/COST_PRODUCT_DECISIONS_AND_DEV_BACKLOG_20261026.md` | [해당 절](product-and-handoffs.md#src-docs-cost-product-decisions-and-dev-backlog-20261026-md) |
| `docs/COST_READY_DEV_QUEUE_20261026.md` | [해당 절](product-and-handoffs.md#src-docs-cost-ready-dev-queue-20261026-md) |
| `docs/COST_SESSION_CLOSE_HANDOFF_20261027.md` | [해당 절](product-and-handoffs.md#src-docs-cost-session-close-handoff-20261027-md) |
| `docs/COST_SUPERVISOR_V2_CHECKPOINT.md` | [해당 절](product-and-handoffs.md#src-docs-cost-supervisor-v2-checkpoint-md) |
| `docs/COST_UNRESOLVED_AND_COSMETIC_ONLY_AUDIT_20261027.md` | [해당 절](product-and-handoffs.md#src-docs-cost-unresolved-and-cosmetic-only-audit-20261027-md) |
| `docs/COST_V3_CURRENT_HANDOFF.md` | [해당 절](product-and-handoffs.md#src-docs-cost-v3-current-handoff-md) |
| `docs/COST_V3_START_HERE.md` | [해당 절](product-and-handoffs.md#src-docs-cost-v3-start-here-md) |
| `docs/access-and-top3-demo.md` | [해당 절](specs-20261110/google-ledger.md#src-docs-access-and-top3-demo-md) |
| `docs/agoda-aside-collection-plan.md` | [해당 절](implementation-and-audits.md#src-docs-agoda-aside-collection-plan-md) |
| `docs/agoda-aside-execution.md` | [해당 절](implementation-and-audits.md#src-docs-agoda-aside-execution-md) |
| `docs/architecture.md` | [해당 절](specs-20261110/platform.md#src-docs-architecture-md) |
| `docs/archive/ota-legacy-20261023/README.md` | [해당 절](ota-legacy.md#src-docs-archive-ota-legacy-20261023-readme-md) |
| `docs/archive/ota-legacy-20261023/architecture.md` | [해당 절](ota-legacy.md#src-docs-archive-ota-legacy-20261023-architecture-md) |
| `docs/archive/ota-legacy-20261023/autonomous-cycle-checkpoint.md` | [해당 절](ota-legacy.md#src-docs-archive-ota-legacy-20261023-autonomous-cycle-checkpoint-md) |
| `docs/archive/ota-legacy-20261023/autonomous-implementation-playbook.md` | [해당 절](ota-legacy.md#src-docs-archive-ota-legacy-20261023-autonomous-implementation-playbook-md) |
| `docs/archive/ota-legacy-20261023/ota-first-core.md` | [해당 절](ota-legacy.md#src-docs-archive-ota-legacy-20261023-ota-first-core-md) |
| `docs/archive/ota-legacy-20261023/ota-first-isolated-review-pilot.md` | [해당 절](ota-legacy.md#src-docs-archive-ota-legacy-20261023-ota-first-isolated-review-pilot-md) |
| `docs/archive/ota-legacy-20261023/ota-first-ui.md` | [해당 절](ota-legacy.md#src-docs-archive-ota-legacy-20261023-ota-first-ui-md) |
| `docs/archive/ota-legacy-20261023/ota-first-verification-plan.md` | [해당 절](ota-legacy.md#src-docs-archive-ota-legacy-20261023-ota-first-verification-plan-md) |
| `docs/archive/ota-legacy-20261023/ota-matching-rule-defaults.md` | [해당 절](ota-legacy.md#src-docs-archive-ota-legacy-20261023-ota-matching-rule-defaults-md) |
| `docs/archive/ota-legacy-20261023/ota-matching-terms.md` | [해당 절](ota-legacy.md#src-docs-archive-ota-legacy-20261023-ota-matching-terms-md) |
| `docs/archive/ota-legacy-20261023/ota_mail.md` | [해당 절](ota-legacy.md#src-docs-archive-ota-legacy-20261023-ota-mail-md) |
| `docs/archive/ota-legacy-20261023/session_handoff.md` | [해당 절](ota-legacy.md#src-docs-archive-ota-legacy-20261023-session-handoff-md) |
| `docs/autonomous-cycle-checkpoint.md` | [해당 절](ota-legacy.md#src-docs-autonomous-cycle-checkpoint-md) |
| `docs/autonomous-implementation-playbook.md` | [해당 절](ota-legacy.md#src-docs-autonomous-implementation-playbook-md) |
| `docs/business_rules.md` | [해당 절](specs-20261110/finance.md#src-docs-business-rules-md) |
| `docs/card-all-transactions-and-ui-design-system-spec-v1.md` | [해당 절](specs-20261110/ui.md#src-docs-card-all-transactions-and-ui-design-system-spec-v1-md) |
| `docs/card-ui-audit-v2-20261025.md` | [해당 절](implementation-and-audits.md#src-docs-card-ui-audit-v2-20261025-md) |
| `docs/card_downloads.md` | [해당 절](specs-20261110/finance.md#src-docs-card-downloads-md) |
| `docs/card_pipeline.md` | [해당 절](specs-20261110/finance.md#src-docs-card-pipeline-md) |
| `docs/cleanup-resolution-20261023.md` | [해당 절](implementation-and-audits.md#src-docs-cleanup-resolution-20261023-md) |
| `docs/company-expense-exclusion.md` | [해당 절](specs-20261110/finance.md#src-docs-company-expense-exclusion-md) |
| `docs/cost-v3-inference-ai-passenger-nm-test-architecture.md` | [해당 절](specs-20261110/participants.md#src-docs-cost-v3-inference-ai-passenger-nm-test-architecture-md) |
| `docs/design/cost-saas-ui-refresh.md` | [해당 절](specs-20261110/ui.md#src-docs-design-cost-saas-ui-refresh-md) |
| `docs/design/icon-license.md` | [해당 절](specs-20261110/ui.md#src-docs-design-icon-license-md) |
| `docs/design/ota-icons.md` | [해당 절](specs-20261110/ui.md#src-docs-design-ota-icons-md) |
| `docs/expense-bulk-audit-20261025.md` | [해당 절](implementation-and-audits.md#src-docs-expense-bulk-audit-20261025-md) |
| `docs/expense-cleanup-navigation-spec.md` | [해당 절](specs-20261110/ui.md#src-docs-expense-cleanup-navigation-spec-md) |
| `docs/expense-cleanup-ota-diagnosis-20261024.md` | [해당 절](implementation-and-audits.md#src-docs-expense-cleanup-ota-diagnosis-20261024-md) |
| `docs/expense-cleanup-task-index.md` | [해당 절](implementation-and-audits.md#src-docs-expense-cleanup-task-index-md) |
| `docs/flight-booking-verification-spec-20261026.md` | [해당 절](specs-20261110/ui.md#src-docs-flight-booking-verification-spec-20261026-md) |
| `docs/google-authority-sync-readiness.md` | [해당 절](specs-20261110/google-ledger.md#src-docs-google-authority-sync-readiness-md) |
| `docs/google-workbook-layout.md` | [해당 절](specs-20261110/google-ledger.md#src-docs-google-workbook-layout-md) |
| `docs/handoff/session-20261020-booking-evidence.md` | [해당 절](implementation-and-audits.md#src-docs-handoff-session-20261020-booking-evidence-md) |
| `docs/history/handoff-through-20261007.md` | [해당 절](operations-through-20261027.md#src-docs-history-handoff-through-20261007-md) |
| `docs/history/operations-through-20261007.md` | [해당 절](operations-through-20261027.md#src-docs-history-operations-through-20261007-md) |
| `docs/operations.md` | [해당 절](operations-through-20261027.md#src-docs-operations-md) |
| `docs/ota-card-reconciliation-policy-a-v3.md` | [해당 절](specs-20261110/ota.md#src-docs-ota-card-reconciliation-policy-a-v3-md) |
| `docs/ota-first-core.md` | [해당 절](ota-legacy.md#src-docs-ota-first-core-md) |
| `docs/ota-first-isolated-review-pilot.md` | [해당 절](ota-legacy.md#src-docs-ota-first-isolated-review-pilot-md) |
| `docs/ota-first-ui.md` | [해당 절](ota-legacy.md#src-docs-ota-first-ui-md) |
| `docs/ota-first-verification-plan.md` | [해당 절](ota-legacy.md#src-docs-ota-first-verification-plan-md) |
| `docs/ota-first-verification-report.md` | [해당 절](ota-legacy.md#src-docs-ota-first-verification-report-md) |
| `docs/ota-matching-rule-defaults.md` | [해당 절](ota-legacy.md#src-docs-ota-matching-rule-defaults-md) |
| `docs/ota-matching-terms.md` | [해당 절](ota-legacy.md#src-docs-ota-matching-terms-md) |
| `docs/ota-resolution-execution.md` | [해당 절](implementation-and-audits.md#src-docs-ota-resolution-execution-md) |
| `docs/ota-unified-store.md` | [해당 절](specs-20261110/ota.md#src-docs-ota-unified-store-md) |
| `docs/ota_mail.md` | [해당 절](ota-legacy.md#src-docs-ota-mail-md) |
| `docs/participant-income-reconciliation-spec.md` | [해당 절](specs-20261110/participants.md#src-docs-participant-income-reconciliation-spec-md) |
| `docs/participant-income-task-index.md` | [해당 절](implementation-and-audits.md#src-docs-participant-income-task-index-md) |
| `docs/receipt-muse-opencode.md` | [해당 절](specs-20261110/receipts.md#src-docs-receipt-muse-opencode-md) |
| `docs/reconciliation-rules.md` | [해당 절](specs-20261110/finance.md#src-docs-reconciliation-rules-md) |
| `docs/schema-rehearsal.md` | [해당 절](specs-20261110/platform.md#src-docs-schema-rehearsal-md) |
| `docs/session-takeover-20261012.md` | [해당 절](implementation-and-audits.md#src-docs-session-takeover-20261012-md) |
| `docs/session_handoff.md` | [해당 절](product-and-handoffs.md#src-docs-session-handoff-md) |
| `docs/superpowers/plans/2026-10-24-toyoko-reservation-links.md` | [해당 절](implementation-and-audits.md#src-docs-superpowers-plans-2026-10-24-toyoko-reservation-links-md) |
| `docs/superpowers/plans/2026-10-26-flight-manual-date-filter.md` | [해당 절](implementation-and-audits.md#src-docs-superpowers-plans-2026-10-26-flight-manual-date-filter-md) |
| `docs/superpowers/plans/2026-10-26-manual-theme-toggle.md` | [해당 절](implementation-and-audits.md#src-docs-superpowers-plans-2026-10-26-manual-theme-toggle-md) |
| `docs/superpowers/plans/2026-10-27-card-review-latency.md` | [해당 절](implementation-and-audits.md#src-docs-superpowers-plans-2026-10-27-card-review-latency-md) |
| `docs/superpowers/plans/2026-10-27-flight-search-integration.md` | [해당 절](implementation-and-audits.md#src-docs-superpowers-plans-2026-10-27-flight-search-integration-md) |
| `docs/superpowers/plans/2026-10-27-navigation-performance-plan.md` | [해당 절](implementation-and-audits.md#src-docs-superpowers-plans-2026-10-27-navigation-performance-plan-md) |
| `docs/superpowers/plans/2026-10-27-ota-provider-refund-plan.md` | [해당 절](implementation-and-audits.md#src-docs-superpowers-plans-2026-10-27-ota-provider-refund-plan-md) |
| `docs/superpowers/plans/2026-10-27-pending-work-release.md` | [해당 절](implementation-and-audits.md#src-docs-superpowers-plans-2026-10-27-pending-work-release-md) |
| `docs/superpowers/plans/2026-10-27-review-fixes-integration.md` | [해당 절](implementation-and-audits.md#src-docs-superpowers-plans-2026-10-27-review-fixes-integration-md) |
| `docs/superpowers/plans/2026-10-27-unified-trip-ledger.md` | [해당 절](implementation-and-audits.md#src-docs-superpowers-plans-2026-10-27-unified-trip-ledger-md) |
| `docs/target-workflow-google-authority.md` | [해당 절](specs-20261110/google-ledger.md#src-docs-target-workflow-google-authority-md) |
| `docs/trip-booking-mail-investigation.md` | [해당 절](operations-through-20261027.md#src-docs-trip-booking-mail-investigation-md) |
| `docs/trip-income-visibility-and-ledger-match-spec-20261025.md` | [해당 절](specs-20261110/google-ledger.md#src-docs-trip-income-visibility-and-ledger-match-spec-20261025-md) |
| `docs/ui-audit-20261024.md` | [해당 절](implementation-and-audits.md#src-docs-ui-audit-20261024-md) |
| `webapp/DESIGN_REVIEW.md` | [해당 절](implementation-and-audits.md#src-webapp-design-review-md) |
