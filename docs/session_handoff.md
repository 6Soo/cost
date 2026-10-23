# COST — 현재 세션 인수 (2026-10-23)

> **활성 인계 파일입니다.** 기존 장문의 세션/운영 기록은 [2026-10-23 보관 전문](archive/ota-legacy-20261023/session_handoff.md)에 한 글자도 빠짐없이 보존했습니다. 이전 세션의 TODO를 현재 구현 과제로 자동 재실행하지 마세요.

## 지금 반드시 읽을 문서

1. [COST V3 단일 구현 진입점](COST_V3_START_HERE.md) — 가장 높은 목표 정책 권위, 단계별 작업 범위, 현재 코드와 운영 상태 구분.
2. [OTA–카드 정책 A 통합 구현](ota-card-reconciliation-policy-a-v3.md) — R0 진단부터 R6 전환까지.
3. [V3 사용자 수정·AI 대화·탑승자 명세](cost-v3-inference-ai-passenger-nm-test-architecture.md) — OTA 링크와 여행 A→B·학습은 독립.
4. [운영 상태 증거](operations.md) — 당시 실제 릴리스·검증, 최신 라이브 상태는 다시 확인.
5. [사용자 확정 회계 규칙](reconciliation-rules.md) 및 [Google 최종 정본 계약](target-workflow-google-authority.md).

## 현재 작업 상태 (2026-10-23 갱신)

- **COST main:** `f52533e`이며 `origin/main`에 반영됐다. 최근 변경은 R3 snapshot 소비 경로 정렬, R4 지출 준비 흐름, R5-B 참가자 owner UI·adapter, R6 대량 재분류의 중앙 OTA 조회 연결이다.
- **Reservation [초안 PR #22](https://github.com/6Soo/reservation/pull/22):** 읽기 전용 후보 API와 별도 `TURSO_READONLY_AUTH_TOKEN` 연결. 합성 HTTP→COST 브라우저→SQLite 저장/stale 재확정과 Vercel Preview를 확인했다. `main`은 자동 배포 대상이라 병합하지 않았다.
- **실서비스 차단:** 운영 내부 API 토큰 및 별도 읽기 전용 DB 자격증명이 없어 운영 인증 요청과 실제 자료 검증은 하지 않았다. 예약 서비스 설정·배포 승인은 운영 권한자가 수행해야 한다.
- **R1~R6/N:M 코드 작업:** 승인 명세 기준 표적·합성 검증과 Git 반영을 완료했다. R6는 오래된 snapshot 복구 fallback을 남기되 fresh canonical 결과를 덮지 못하게 했고, 대량 재분류도 중앙 `_ota_report`를 사용한다.
- **다음 실행:** 기존 R0/R1~R6 작업을 반복하지 않는다. 이 문서와 작업 큐의 증거를 재사용하고, 새 필수 결함이 확인되면 해당 소비 경로부터 표적 수정한다.
- **절대 보존:** 실제 매입/중복/취소/환불/수동 links·여행 배정·기록된 원장/원본, 개인정보 최소화, Google 직접 쓰기 금지, 단일 writer, 작은 표적 테스트와 실제 검증 여부 구분.

`docs/archive/`, `docs/history/`, 과거 `ota-first-*`, 오래된 자율 실행 계획과 보관된 회고는 이 날짜의 제품 목표가 아니며 **현재 구현을 지시하는 문서가 아닙니다.**
