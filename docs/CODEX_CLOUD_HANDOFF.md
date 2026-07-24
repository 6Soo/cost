# Codex Cloud 세션 인계서

작성 기준: 2026-07-25  
저장소: `6Soo/cost`

## 1. 클라우드 세션 시작 순서

1. 저장소의 기본 브랜치 `main`을 체크아웃하고 최신 커밋을 받는다.
2. 루트의 `AGENTS.md`를 읽는다.
3. `LOG.md` 맨 아래 최신 세션 핸드오프를 읽는다.
4. `CLAUDE.md`와 `docs/비용분류_지시사항_원장.md`를 읽는다.
5. 이 문서의 검증 명령을 실행해 로컬과 같은 결과가 재현되는지 확인한다.

비용·장부 작업은 `docs/비용분류_지시사항_원장.md`의 불변 원칙을 우선한다.
특히 카드 거래는 삭제하지 않고, 승인·취소·부분환불을 별도 이벤트로 보존한다.

## 2. 이번 스택의 범위

PR #8은 결제 사실, 예약, 여행 귀속, 분류 판정, 장부 전기를 분리한 SQLite 기반
도메인 모델과 P0 검토 기준선을 추가했다.

PR #9는 PR #8 위에서 다음을 완성했다.

- 안정적인 `card_event_id`와 append-only 결제 버전
- 변경 로그 기반 재생성, 백업·복원, 개인정보 허용목록
- P1 고신뢰 판정 재검증
- P2 취소·환불 관계 검토와 하나카드 동일 행 승인·취소 복원
- P3 미배정 전수 검토
- P4 OTA 공급자 판정
- P5 저신뢰·0원 거래 자동전기 차단
- P6 카드·수기·OTA 직접 적재와 병렬 워크북, 7개 전환 게이트

운영 Apps Script를 이 v2 DB로 전환한 것은 아니다. 사용자 승인 전까지 기존
v14/v76 계열 산출 경로가 운영 정본이며, v2는 병렬 검증 경로다.

## 3. 하나카드 승인·취소 교정

하나카드 G/H 원천은 한 행에 승인금액과 승인취소금액이 함께 존재할 수 있다.
이를 한 건으로 축약하면 승인이나 취소 중 하나가 사라지므로 다음 구조로 바꿨다.

- 원천행: `direct_source_records`에 1회 불변 저장
- 승인 이벤트: `event_role=approval`, 양수 금액
- 취소 이벤트: `event_role=cancellation`, 음수 금액
- 관계: 같은 원천행과 승인번호로 명시 연결

legacy에서 `0원 원행 + 음수 MISC`로 잘못 표현된 4쌍도 삭제 없이 복구했다.

| 금액 | 결과 |
|---:|---|
| 10,100원 | 양수 승인 + 음수 취소 |
| 90,415원 | 양수 승인 + 음수 취소 |
| 178,948원 | 양수 승인 + 음수 취소 |
| 357,262원 | 양수 승인 + 음수 취소 |

복구 합계는 636,725원이며 각 쌍의 순액은 0원이다. 과거 projection은 양수 승인을
누락하고 음수 취소만 남겼으므로, 전체 결제·배분 합계는 636,725원 증가한다.
이 차이는 회귀 보고서에서 `legacy_error_correction`으로 분리한다.

앞으로 사람이 검토할 대상은 구조적으로 자동화할 수 없는 다음 경우뿐이다.

- 원승인 자체가 조회기간 밖이거나 원천에 없음
- 승인번호·금액·날짜 증거가 서로 충돌함
- 동일 우선순위 후보가 여러 개라 유일하게 결정할 수 없음

## 4. 검증된 현재 상태

- 결제: 1,833건
- 결제 합계: 320,752,342원
- 활성 배분 합계: 320,752,342원
- 결제별 배분 불일치: 0건
- 직접 카드 원천: 5,237행
- 정규화 카드 이벤트: 5,328건
- 미연결 취소·환불:
  - 조회기간 밖 10건
  - 자료부족 1건(`TRIP-0419`)
  - 설명 없음 0건
- 미배정 잔여: 14건
- 0원 감사 대상: 5건
- 고신뢰·불확실 근거: 0건
- 공급자 미확정: 54건
- 전환 게이트: 7/7 통과
- 테스트: 29/29 통과

기계 판독 결과는 `ledger/baselines/p6_transition_gate_report.json`에 있다.

## 5. 재현 명령

Windows PowerShell 또는 Linux 셸에서 저장소 루트를 현재 디렉터리로 둔다.

```bash
python -m unittest discover -s ledger/tests
python -m ledger.domain.ledger_db --db /tmp/cost-ledger.db rebuild
python -m ledger.domain.ledger_db --db /tmp/cost-ledger.db validate
```

직접 원천 적재와 전환 게이트는 Python에서 `ledger.domain.direct_sources.import_all`
을 실행한 뒤 다음 명령으로 확인한다.

```bash
python -m ledger.domain.transition_gates \
  --db /tmp/cost-ledger.db \
  --baseline ledger/baselines/p05_latest_20260725/regression_totals.json \
  --output /tmp/p6_transition_gate_report.json
```

Windows에서는 `/tmp/...`를 `$env:TEMP` 아래 경로로 바꾼다. 기존 DB가
`event_role` 없는 직접 적재 스키마라면 in-place 수정하지 말고 `rebuild`로
불변 원천에서 재생성한다.

## 6. GitHub와 브랜치 상태

PR #8과 PR #9는 순서대로 `main`에 병합했으며 두 병합 브랜치는 삭제했다.

- PR #8 merge commit: `2882af5bb1695d4ce2911270bfd892931534fbcf`
- PR #9 merge commit: `7cf607023799bd2ffcb7e8bdb97b117761d1a624`
- 삭제된 원격 브랜치:
  - `feat/domain-separated-ledger-model`
  - `codex/pr8-plan-hardening`

별도 보존 대상:

- PR #7 `claude/code-review-branch-cleanup-lky6nc`
  - 최신 원장 재수취, 중복탭 배제, 카드 매칭·워크북 파이프라인 수정 17개를 포함한다.
  - 이번 v2 스택과 병합 계보가 다르므로 클라우드 세션에서 별도 재검증·통합한다.
- PR #5 `claude/expense-processing-automation-ivhg7j`
  - 충돌 상태의 draft PR이다.
  - PR #7과 일부 목적이 겹치지만 완전 포함 관계가 아니므로 자동 폐기하지 않았다.

클라우드 세션은 먼저 PR #7을 최신 `main`에 재배치하거나 필요한 커밋을 선별한 뒤,
PR #5의 고유 변경이 남아 있는지 비교한다. 증거 없이 두 PR을 닫거나 브랜치를
삭제하지 않는다.

## 7. 외부 연결과 보안

- GitHub 저장소: `6Soo/cost`
- Google Workspace 업무 계정: `kkokkohero6@gmail.com`
- 원장 Drive fileId: `1fhqNkhfiWTYr_U8QnFxlunijAIFPH3r8rPRR0DTPlKU`
- Gmail·Drive·Calendar 연결이 없더라도 커밋된 원천으로 테스트와 DB 재생성은 가능하다.
- 최신 메일 대사·Drive 원장 갱신에는 Google Workspace OAuth가 필요하다.
- PIN, 이메일, 전화번호, 생년월일, 여권정보 및 Gmail 원문은 저장소나 외부 LLM에
  올리지 않는다. OTA 적재는 허용목록과 redaction 검사를 통과해야 한다.

## 8. 클라우드 세션의 첫 작업

1. `main`에서 29개 테스트와 7개 게이트를 재현한다.
2. PR #7을 최신 `main`과 비교해 v2의 하나카드 이벤트 보존 원칙과 충돌하는
   “승인취소 스킵” 로직을 그대로 병합하지 않는다.
3. PR #7의 최신 원장·워크북 수정 중 필요한 부분을 v2 불변 이벤트 모델과 함께
   작동하도록 이식한다.
4. PR #5의 고유 변경을 확인하고, #7 또는 `main`에 이미 포함됐으면 근거를 남긴 뒤
   draft PR을 닫고 원격 브랜치를 정리한다.
5. 운영 전환은 사용자에게 병렬 결과와 잔여 애매 건을 보고하고 명시 승인을 받은
   뒤 수행한다.
