# COST 구형 OTA·개발 문서 보관함 (2026-10-23)

> **이 디렉터리의 모든 파일은 역사 자료입니다. 새 기능의 구현 지시, 최신 비즈니스 규칙, 배포 상태로 사용하지 마세요.** 각각 기존 문서 경로에서 원문을 보존한 사본이며, 오래된 링크/계획도 의도적으로 원문 그대로 포함됩니다.

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

**무손실 확인:** 이 11개 원문을 GitHub로 복사할 때 기존 파일 blob SHA가 보관본 blob SHA와 동일함을 확인했다. 기존 위치에는 새 정책 진입점 및 본 원문 링크가 있는 안내를 남겼다. 따라서 이전 링크는 삭제되지 않았다.

사진 파일 `docs/ota-first-ui-desktop.png`, `docs/ota-first-ui-mobile.png`은 바이너리이고 구형 UI 기록에 부속한 자료이므로 기존 경로에서 유지한다. 현재 구현 요구로 오인하지 않는다.

아카이브의 상대 링크는 원래 위치를 기준으로 작성됐기 때문에 이 폴더에서 일부가 바로 열리지 않을 수 있다. 그런 경우 옛 경로의 안내 페이지 또는 현재 단일 진입점을 사용한다.
