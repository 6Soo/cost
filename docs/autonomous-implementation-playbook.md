# 이전 문서 — autonomous-implementation-playbook.md

> **과거 구현·정책 기록입니다. 최신 COST V3 구현 지시가 아닙니다.** 이전 멀티에이전트 병렬 구현 절차을 기록하던 파일이며, 현재 목표 정책과 다른 `HOLD`/자동배정/전체 검증 지시가 포함될 수 있습니다.

- **공식 개발 진입점:** [COST V3 START HERE](COST_V3_START_HERE.md)
- **최신 OTA–카드 A 정책과 R0~R6:** [OTA 대사 통합 명세](ota-card-reconciliation-policy-a-v3.md)
- **V3 여행 귀속·AI·참가자:** [V3 상세 명세](cost-v3-inference-ai-passenger-nm-test-architecture.md)
- **보존한 과거 원문:** [autonomous-implementation-playbook.md](archive/ota-legacy-20261023/autonomous-implementation-playbook.md)

이전의 정책 표·실험 TODO와 당시 운영 건수를 최신 요구로 사용하지 마세요. **현재 코드의 실행 사실**은 해당 코드와 [운영 이력](operations.md)에서 확인합니다. 승인된 가맹점·날짜 허용·수동 결정의 실제 실행 값은 `config/ota-matching-defaults.json`과 저장된 사용자 규칙을 검증한 다음 새 명세에 따라 개편합니다.
