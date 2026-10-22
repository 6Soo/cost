# COST — 현재 세션 인수 (2026-10-23)

> **활성 인계 파일입니다.** 기존 장문의 세션/운영 기록은 [2026-10-23 보관 전문](archive/ota-legacy-20261023/session_handoff.md)에 한 글자도 빠짐없이 보존했습니다. 이전 세션의 TODO를 현재 구현 과제로 자동 재실행하지 마세요.

## 지금 반드시 읽을 문서

1. [COST V3 단일 구현 진입점](COST_V3_START_HERE.md) — 가장 높은 목표 정책 권위, 단계별 작업 범위, 현재/미구현 구분.
2. [OTA–카드 정책 A 통합 구현](ota-card-reconciliation-policy-a-v3.md) — R0 진단부터 R6 전환까지.
3. [V3 사용자 수정·AI 대화·탑승자 명세](cost-v3-inference-ai-passenger-nm-test-architecture.md) — OTA 링크와 여행 A→B·학습은 독립.
4. [운영 상태 증거](operations.md) — 당시 실제 릴리스·검증, 최신 라이브 상태는 다시 확인.
5. [사용자 확정 회계 규칙](reconciliation-rules.md) 및 [Google 최종 정본 계약](target-workflow-google-authority.md).

## 현재 작업 상태

- **GitHub [PR #87](https://github.com/6Soo/cost/pull/87):** 사용자 확정 V3 정책/명세·문서 통합 및 N:M `30000` vs `30000.00` Decimal 금액 정규화 코드/합성 테스트. **main 미병합·미배포, 새 합성 테스트 미실행.**
- **운영 코드 현황:** 이전 정확 매칭/OTA-first 경로가 병존하고 OTA 링크 미확정에 따른 비용 HOLD가 일부 존재. 새 정책 A는 **문서화됐으나 구현/배포 전**.
- **다음 실행 과제 R0:** `tools/audit_ota_card_coverage.py`의 읽기 전용 후보·추출 탈락·원본 계보/ID 충돌·legacy diff 진단과 합성 표적 테스트. 실운영 원본 접근 전에는 실제 미매칭 건수·정확도 수치 단정 불가.
- **이어갈 작업:** R1 출처/ID, R2 날짜 없는 후보·공통 alias, R3 단일 matcher/N:M, R4 정상 카드 독립 비용 readiness, R5 수동 여행 이동·AI 1/2/3 대화 및 항공권 참가, R6 단계별 cutover.
- **절대 보존:** 실제 매입/중복/취소/환불/수동 links·여행 배정·기록된 원장/원본, 개인정보 최소화, Google 직접 쓰기 금지, 단일 writer, 작은 표적 테스트와 실제 검증 여부 구분.

`docs/archive/`, `docs/history/`, 과거 `ota-first-*`, 오래된 자율 실행 계획과 보관된 회고는 이 날짜의 제품 목표가 아니며 **현재 구현을 지시하는 문서가 아닙니다.**
