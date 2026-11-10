# 과거 명세 (2026-11-10 보관)

> 이 폴더의 문서는 **근거 기록**이다. 작업 지시가 아니다. 실행 정본은 [통합 명세](../../SPEC.md)와 [판정 규칙집](../../DECISION_POLICY.md)이다.

- 2026-11-10까지 `docs/specs/`에 있던 명세 전부와 `docs/luna-*-handoff.md` 인계 문서를 옮겨 왔다. 내용은 고치지 않았고 상대 링크만 새 위치에 맞췄다.
- 문서 안의 ACTIVE·READY·IMPLEMENTING·미구현 표시, "최신 결정", "현재 정본" 같은 표현은 작성 당시의 상태다. 지금의 상태는 [현재 상태](../../session_handoff.md)에서 확인한다.
- 여기 흩어져 있던 판정 규칙은 규칙집으로 옮겼다. 규칙집의 각 규칙 "출처"에 적힌 `docs/specs/<파일>:<줄>`은 이 폴더의 같은 이름 파일을 가리킨다(줄 번호는 커밋 `b0340d0d` 기준).
- 두 문서는 절차서로 쓰고 있어 `docs/playbooks/`로 옮겼다: [카드 원본 수집 안내](../../playbooks/card-downloads.md), [OTA 포털 직접 수집 절차](../../playbooks/ota-portal-collection.md).
- 코드 주석 몇 곳과 `ledger/README.md`, `webapp/README.md`가 옛 경로(`docs/specs/…`)를 가리킨다. 같은 이름으로 이 폴더에 있다. 문서 전용 검사 범위 밖의 파일이라 이번에 고치지 않았고, M2의 코드 변경 때 함께 고친다.

## 자주 찾던 문서

| 주제 | 문서 |
| --- | --- |
| 금융·카드·여행 배정 | [finance.md](finance.md) |
| OTA 대사 | [ota.md](ota.md) |
| Google 장부 | [google-ledger.md](google-ledger.md) |
| 화면·항공권·디자인 | [ui.md](ui.md) |
| 참가자·여행 교정 | [participants.md](participants.md) |
| 영수증 | [receipts.md](receipts.md) |
| 구조·플랫폼 | [platform.md](platform.md) |
| 전체 UI/UX 감사·재설계(정보구조는 통합 명세 §11.2가 이어받음) | [uiux-full-audit-redesign-20261110.md](uiux-full-audit-redesign-20261110.md) |
