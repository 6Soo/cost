# COST — 현재 세션 인수 (2026-10-23)

> **최신 재개 상태는 [COST V3 CURRENT HANDOFF](COST_V3_CURRENT_HANDOFF.md)가 우선합니다.** 이 파일은 짧은 세션 안내이며 이전 장문의 세션/운영 기록은 [2026-10-23 보관 전문](archive/ota-legacy-20261023/session_handoff.md)에 보존했습니다. 이전 TODO를 자동 재실행하지 마세요.

## 지금 반드시 읽을 문서

1. [**COST V3 최신 단일 재개 문서**](COST_V3_CURRENT_HANDOFF.md) — 두 저장소 현재 SHA, CI 실패, Reservation Production READY, 운영 미검증과 다음 작업 큐.
2. [COST V3 단일 구현 진입점](COST_V3_START_HERE.md) — 가장 높은 목표 정책 권위, 단계별 작업 범위, 현재 코드와 운영 상태 구분.
3. [OTA–카드 정책 A 통합 구현](ota-card-reconciliation-policy-a-v3.md) — R0 진단부터 R6 전환까지.
4. [V3 사용자 수정·AI 대화·탑승자 명세](cost-v3-inference-ai-passenger-nm-test-architecture.md) — OTA 링크와 여행 A→B·학습은 독립.
5. [운영 상태 증거](operations.md) — 당시 실제 릴리스·검증, 최신 라이브 상태는 다시 확인.
6. [사용자 확정 회계 규칙](reconciliation-rules.md) 및 [Google 최종 정본 계약](target-workflow-google-authority.md).

## 현재 작업 상태 (2026-10-23 후속 갱신)

- **단일 정확한 재개 큐:** [CURRENT HANDOFF §3](COST_V3_CURRENT_HANDOFF.md#3-미완료미검증-작업-큐-재개-우선순위). 아래 문장 대신 최신 Git/CI/배포와 동 문서의 우선순위를 따른다.
- **COST 주요 코드 기준 커밋:** 0bd6e93 (이후 문서 전용 커밋 추가). R0~R6·N:M·R5-B COST 어댑터 및 합성 종단 테스트까지 개발 반영됐다고 보고됐다. COST 운영 호스트에 V3 전체 배포됐는지는 확인되지 않았다.
- **Reservation:** PR #22는 2026-10-23 cc4e325로 main 병합 및 **Vercel Production READY** 확인. 사용자 요청에 따른 배포. 참가자 후보 API의 실제 운영 비밀설정 및 인증·원본 조회 성공은 별도 미검증.
- **CI:** Reservation cc4e325 Actions run 39936103139의 smoke는 PASS, unit은 FAIL. 기존 masterDataQueue 기준선 실패와 동일 원인인지 CI 로그로 확인하고 실제 버그면 수정해야 한다.
- **남은 단계:** (P0) Reservation unit 실패 원인 분석 및 필요한 수정, (P1) 사용자 권한 경계의 읽기 전용 운영 토큰·실연동 검증, (P2) COST 실제 운영 V3 SHA/신규 필수 갭 확인. R6 안전 복구 fallback은 의도적으로 유지.
- **안전:** 금융 중복·환불·원본 충돌, 수동 links/여행 배정, 기장 결과·원본, 개인정보 최소화, Google 직접 쓰기 금지, 단일 writer, 기존 로컬 미커밋·미추적 파일을 보존한다.
- **지난 운영 이력:** [operations.md](operations.md) 및 [cleanup-resolution-20261023.md](cleanup-resolution-20261023.md)의 그 시점 숫자/기장 결과를 새 작업으로 재실행하지 않는다.

`docs/archive/`, `docs/history/`, 과거 `ota-first-*`, 오래된 자율 실행 계획과 보관된 회고는 이 날짜의 제품 목표가 아니며 **현재 구현을 지시하는 문서가 아닙니다.**
