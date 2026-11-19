# COST 문서 지도 — 현재 실행 기준

**한 작업에 필요한 문서만 선택적으로 읽는다.** 전체 `docs/`와 과거 로그는 기본 입력이 아니다. 실행 상태, 정책, 운영 배포, 역사 기록은 서로 다른 정보이며 한 문서에 재복사하지 않는다.

## 현행 정본

| 확인 대상 | 문서 | 읽는 시점 |
| --- | --- | --- |
| 지금 상태·승인/차단·다음 작업 | [현재 상태](session_handoff.md) | 모든 작업 시작·종료 |
| 목표·로드맵·시스템 구조·보호 | [통합 명세](SPEC.md) | 관련 절만 |
| 판정의 우선순위와 규칙 | [판정 규칙집](DECISION_POLICY.md) + [영역별 색인](policy/README.md) | 판정·분류·정산 변경 시 |
| 운영 배포 SHA·백업·복구 | [운영 기록](operations.md) | 배포·이관·운영 장애 시 |
| 실행 방식·역할·검수 | [AGENTS.md](../AGENTS.md) | 구현·검수 |
| 반복하는 실무 절차 | [절차서 목록](playbooks/README.md) | 해당 절차 실행 시 |

## 경량화의 공식 실행 순서

[통합 명세 §10의 경량화 트랙](SPEC.md#10-로드맵)에 L1 문서 정리 → L2 장부 조회 통합 → L3 중복 구현 퇴역 → L4 테스트·검수 단순화 → L5 M5/M6 비용·범위 판단을 두었다. 각 단계는 통합 명세의 수락 기준과 기존 승인 범위를 따른다.

## 과거 자료와 호환 경로

- [Git 이력의 이전 인계 원문](https://github.com/6Soo/cost/blob/9a953e276824a6bd62d354075e753d122c7cbef1/docs/session_handoff.md) · [이전 작업판 원문](https://github.com/6Soo/cost/blob/9a953e276824a6bd62d354075e753d122c7cbef1/docs/agents/BOARD.md) · [이전 관리자 지침](https://github.com/6Soo/cost/blob/9a953e276824a6bd62d354075e753d122c7cbef1/docs/agents/MANAGER.md)
- [과거 기록·명세 보관함](history/README.md) · [기존 경량화 정적 감사](audits/repository-lightweight-review-20261118.md)
- [작업판 호환 안내](agents/BOARD.md) · [관리자 문서 호환 안내](agents/MANAGER.md) · [옛 시작 안내](COST_V3_START_HERE.md)

과거 기록의 READY·ACTIVE·미구현 표시는 **현재 지시가 아니다**. 기존 커밋·배포·실자료 검증 상태를 혼동하지 않는다. 고객 원문·인증 정보·운영 사본은 문서와 Git에 싣지 않는다.
