# COST 문서 지도

실행 기준은 [통합 명세](SPEC.md) 하나이며, 판정 규칙은 [규칙집](DECISION_POLICY.md)과 `policy/`에 둔다. 현재 사용자 요청과 실제 완료 상태는 [현재 상태](session_handoff.md), 운영 실행 근거는 [운영 기록](operations.md), 배정 상태는 [작업판](agents/BOARD.md)을 따른다.

문서의 설계·합성 검사·병합·운영 배포·실자료 수락은 서로 다르다. 과거 문서의 ACTIVE·대기·미완료를 새 실행 지시로 해석하지 않는다. 고객 원문·운영 사본·로컬 검수 로그는 이 지도나 Git에 옮기지 않는다.

## 기준과 현재 상태

- [COST 시작 안내](COST_V3_START_HERE.md)
- [COST 통합 명세](SPEC.md)
- [판정 규칙집](DECISION_POLICY.md)
- [현재 상태](session_handoff.md)
- [운영 기록](operations.md)
- [현재 작업판](agents/BOARD.md)
- [중간 관리자 지침](agents/MANAGER.md)

## 영역별 판정 규칙

- [업무 단계별 규칙 안내 — 11개 영역·규칙 ID 검색](policy/README.md)
- [판정의 공통 우선순위와 사용자 예외](DECISION_POLICY.md)
- [코드와 규칙이 다른 곳 — 실제 수정 전 재검증](policy/CODE_GAPS.md)

## 절차서

- [AI 분기 검수 교정 반영](playbooks/ai-review-apply.md)
- [일괄 기록 배치 owner 확인 표시 정정](playbooks/bulk-owner-confirmation-repair.md)
- [카드 원본 수집 — ego-browser 실행 안내](playbooks/card-downloads.md)
- [카드사 로그인 자동화](playbooks/card-login-automation.md)
- [카드 로그인 방식·조회경로 조사 — 하나카드·기업카드(IBK)](playbooks/card-login-research-20261111.md)
- [완료 기간 카드 정리](playbooks/closed-period-grouping.md)
- [코어 1차 전환 — P1 자동 분류 작성자를 Python에서 Rust로](playbooks/core-cutover.md)
- [dist141 자동 판정 출처 정정](playbooks/dist141-provenance-repair.md)
- [국민 기업카드 매입 수집 스크립트 사용](playbooks/kb-script-usage.md)
- [OTA 근거 기존 중복 압축](playbooks/ota-evidence-compaction.md)
- [OTA 포털 직접 수집 절차 (ego lite) — 2026-11-10](playbooks/ota-portal-collection.md)
- [OTA 수집 스크립트 사용법 — `collect_ota_portals.mjs`](playbooks/ota-script-usage.md)
- [카드 수입 뒤 증분 P2 1층](playbooks/p2-incremental.md)
- [일반 준비기간 추론 귀속 정리](playbooks/preparation-cost-grouping.md)
- [분기 검수](playbooks/quarter-review.md)
- [절차서](playbooks/README.md)
- [영수증 사진 판독](playbooks/receipt-reading.md)
- [확정 여행 종료일 근거 개정](playbooks/trip-schedule-revision.md)

## 설계

- [M4 COST 전체 UI 설계 — Plush UI](design/m4-plush-ui-20261116.md)
- [영수증 처리 변경 — 로컬 Paseo 선택·지속 처리·사용자 검수(구현 승인)](design/receipt-paseo-workflow-20261116.md)
- [M3 Rust 새 코어 — 착수용 설계안](design/m3-core.md)
- [M4 화면 수락 기준 — 2026-11-15 UI/UX 전체 검수 결과](design/m4-ui-requirements.md)

## 참조 명세 안내

- [옮겨진 문서](specs/finance.md)
- [옮겨진 문서](specs/ota.md)
- [옮겨진 문서](specs/platform.md)
- [docs/specs](specs/README.md)

## 검사·조사 근거

- [2026년 3분기 AI 분기 검수 보고](agents/artifacts/ai-quarter-review-2026Q3.md)
- [자동 기록 원자성·금액 묶음 정렬 확인 (2026-11-13)](agents/artifacts/amount-group-and-revision-20261113.md)
- [배포된 계약과 기존 검사 대조 (2026-11-12)](agents/artifacts/baseline-check-reconciliation-20261112.md)
- [카드 로그인 방식·조회경로 조사 — 하나카드·기업카드(IBK)](agents/artifacts/card-login-paths-20261111.md)
- [완료 기간 카드 정리 사본 예행 (2026-11-12)](agents/artifacts/closed-period-grouping-rehearsal-20261112.md)
- [전체 검사 결과 (2026-11-13)](agents/artifacts/full-suite-20261113.md)
- [하나카드 해외 이중수입 수정·정리 사본 예행 (2026-11-13, v5)](agents/artifacts/hana-double-import-fix-20261113.md)
- [일반 준비기간 추론 폐지 사본 검증 (2026-11-13)](agents/artifacts/no-preparation-cost-rehearsal-20261113.md)
- [OTA 이용일 경고 69건 마무리 조사 — 2026-11-12](agents/artifacts/ota-portal-warning-diagnostics-20261112.md)
- [P2 첫 묶음 제한 실행 — 호출 전 종료](agents/artifacts/p2-first-batch-20261111.md)
- [D1 — Windows P2 격리 실측 (2026-11-11)](agents/artifacts/p2-isolation-20261111.md)
- [P2 잠금·I/O 장애 수정과 운영 밖 검증](agents/artifacts/p2-lock-io-budgets-20261111.md)
- [분기 검수 때 볼 것 — 거래와 장부의 귀속이 서로 다른 건](agents/artifacts/p2-open-quarter-attribution-review-20261112.md)
- [영수증 페이지 UI·UX 검수와 구현 기준 (2026-11-15)](agents/artifacts/receipt-uiux-audit-20261115.md)
- [환불 표시 검사 대조표 (2026-11-13)](agents/artifacts/refund-display-check-reconciliation-20261113.md)
- [판정 규칙집 누락 감사 — 사용자 결정이 좁아지거나 반대 문구와 공존하는지](agents/artifacts/rule-narrowing-audit-20261113.md)
- [검토 화면 묶음 정리 (suite-g1, 2026-11-13)](agents/artifacts/suite-g1-20261113.md)
- [Google 장부 묶음 정리 (suite-g2) — 2026-11-13](agents/artifacts/suite-g2-20261113.md)
- [장부 화면 묶음 정리 (suite-g3, 2026-11-13)](agents/artifacts/suite-g3-20261113.md)
- [지출 정리·카드 묶음 정리 (2026-11-13) — suite-g4](agents/artifacts/suite-g4-20261113.md)
- [G5 묶음 정리 — 환불·예약·항공 (2026-11-13)](agents/artifacts/suite-g5-20261113.md)
- [기반·기타 묶음 검사 대조표 (2026-11-13)](agents/artifacts/suite-g6-20261113.md)
- [지출 정리·카드 묶음 2차 정리 (2026-11-13) — suite2-g4](agents/artifacts/suite2-g4-20261113.md)
- [Suite 3 기준 비교 원인 및 조정 (2026-11-13)](agents/artifacts/suite3-baseline-20261113.md)
- [여행 종료일 Google 동기화 (2026-11-13)](agents/artifacts/trip-end-date-sync-20261113.md)

## 제안(미승인 문서는 실행 지시 아님)

- [직원·가이드 지출 정산 — 대상과 결과 형식 제안](proposals/staff-guide-settlement-20261113.md)

## 이전 구현 계획(근거 보존)

- [P2 잠금·I/O 예산 수정 계획 (2026-11-11)](superpowers/plans/2026-11-11-p2-lock-io-budgets.md)
- [도구 없는 P2 런타임 실행 계획](superpowers/plans/2026-11-11-p2-tool-free-runtime.md)

## 기술 참조

- [Rust 코어 구성·개발 검사](../core/README.md)
- [웹 실행기·인증·합성 개발](../webapp/README.md)
- [과거 CSV 원장 도구와 일정 도메인](../ledger/README.md)
- [서버 밖 P2 1층 도구](../tools/p2_batch/README.md)
- [P2 2층 오프라인 도구](../tools/p2_layer2/README.md)
- [코어 다리(core bridge) 프로토콜](core-bridge-protocol.md)
- [Reviewed temporary branch integration (2026-10-30)](branch-integration-audit-20261030.md)
- [Google 지출표 7열 검토 의견 (2026-11-11, 1쪽)](agents/tax-ledger-review-20261111.md)

## 과거 기록

[보관함](history/README.md)에서 과거 명세·상태·운영·감사 원문을 찾는다. 과거 파일 경로는 보존하며 역사적 사실을 현재 완료 상태로 바꾸지 않는다.
