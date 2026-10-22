# COST 구형 OTA·개발 문서 보관함 (2026-10-23)

> **이 디렉터리의 모든 파일은 역사 자료입니다. 새 기능의 구현 지시, 최신 비즈니스 규칙, 배포 상태로 사용하지 마세요.** 11개 문서는 기존 텍스트·실행 기록을 보존한 사본입니다. 이동 이후 정상 탐색을 위해 **일부 상대 링크 경로만 수정**했습니다.

## 지금 개발할 때 읽을 문서

- **단일 현행 진입점:** [COST V3 START HERE](../../COST_V3_START_HERE.md)
- **OTA 매칭·readiness·R0~R6:** [OTA–카드 정책 A](../../ota-card-reconciliation-policy-a-v3.md)
- **여행 추론·사용자 교정·AI 대화·항공권:** [V3 기능 명세](../../cost-v3-inference-ai-passenger-nm-test-architecture.md)
- **실제 운영 이력:** [operations.md](../../operations.md)

## 변경하지 않고 보존한 원본 11개

| 파일 | 당시 내용 | 취급 |
| --- | --- | --- |
| [ota-first-core.md](ota-first-core.md) | 초기 OTA-first 코어·HOLD 계약 | 구형 설계 |
| [ota-first-isolated-review-pilot.md](ota-first-isolated-review-pilot.md) | 10월 9일 격리 파일럿 | 역사 검증 |
| [ota-first-ui.md](ota-first-ui.md) | 구형 검토 UI 계약 | 구형 설계 |
| [ota-first-verification-plan.md](ota-first-verification-plan.md) | 10월 8일 실험 계획 | 완료/과거 계획 |
| [ota-matching-terms.md](ota-matching-terms.md) | 결제일 exact gate·날짜 규칙 | 구형 규칙 |
| [ota-matching-rule-defaults.md](ota-matching-rule-defaults.md) | 업체별 매칭 defaults 제안·계약 | 구형 설계/역사 |
| [ota_mail.md](ota_mail.md) | OTA 메일 조사·검증 진행 기록 | 과거 실행 |
| [autonomous-implementation-playbook.md](autonomous-implementation-playbook.md) | 예전 멀티에이전트 작업 지시 | 실행 금지/역사 |
| [autonomous-cycle-checkpoint.md](autonomous-cycle-checkpoint.md) | 이전 에이전트 누적 체크포인트 | 실행 금지/역사 |
| [architecture.md](architecture.md) | 구형 패키지/정본 설명 | 구형 구조 |
| [session_handoff.md](session_handoff.md) | 정리 이전 누적 인계 | 과거 이력 |

**원본 보존 확인:** 최초 아카이브 생성 시 11개 원본과 보관본의 Git blob SHA 일치를 검증했습니다. 이후 8개 보관본의 **상대 링크 28곳만 새 위치에 맞춰 교정**했으므로 현재 보관본의 blob SHA는 일부 변경됐습니다. 최초 무변경 원본은 squash 병합 커밋 [f8ccd13](https://github.com/6Soo/cost/commit/f8ccd13aecdbc00b116c52bb8e4b3bb6f94c9a50)의 Git 이력으로 복원할 수 있습니다. 업무 규칙/실행 증거/원본 내용은 재작성하지 않았습니다.

사진 파일 `docs/ota-first-ui-desktop.png`, `docs/ota-first-ui-mobile.png`은 바이너리이고 구형 UI 기록에 부속한 자료이므로 기존 경로에서 유지한다. 현재 구현 요구로 오인하지 않는다.

**링크 점검:** 문서를 옮긴 후 끊어진 상대 링크(운영 기록·AGENTS·OTA 검증 보고서·UI 스크린샷 및 과거 인계)를 현재 경로로 보정했습니다. 보관 문서 내부의 과거 TODO/코드 버전/금액은 최신 상태로 해석하지 않습니다.
