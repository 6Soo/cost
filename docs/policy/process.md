# 판정 규칙 — 처리 원칙

> [판정 규칙집](../DECISION_POLICY.md)의 영역별 상세 규칙이다. 핵심 원칙과 읽는 법은 규칙집 본문에 있다.
> 규칙 ID는 바꾸지 않는다. 규칙을 고칠 때는 같은 ID의 내용을 고치고 옛 내용을 "대체된 옛 규칙"에 남긴다.

### PROC-001 · P1 선행·P2 판정 완료

*일반 · 결정 2026-11-10*

기존 코드와 승인된 업무 규칙인 P1을 먼저 적용하고, 남은 정상 거래는 P2가 원본·메일·장부·기존 결정을 대조하여 최선의 분류와 근거·불확실성을 저장해 끝낸다.

- 조건·예외: 정상 거래의 분류 경로이며 내부 금융 보호를 해제하는 권한이 아니다.
- 대체된 옛 규칙:
  - AI 호출은 새 카드 처리 흐름에 없다. — docs/history/ota-legacy.md:126
  - 규칙과 이전 사용자 결정, 명확한 업종으로 분류하고 나머지를 사람에게 질문한다. — docs/history/ota-legacy.md:126
- 출처: `MERGE.md:20`, `docs/specs/card-destination-only-ux-20261108.md:8`, `docs/specs/finance.md:3`, `docs/specs/autonomous-expense-cleanup-20261105.md:47`, `docs/specs/autonomous-expense-cleanup-20261105.md:48`

### PROC-002 · 전 원행 자동 평가

*일반 · 결정 2026-11-05*

새 원행은 구매·취소·환불·음수·중복·회사 경비·원본 오류를 포함해 모두 P1 평가를 받는다. 사용자의 반복 지시 없이 시작하며 P2 대상은 P1 결과와 기존 결정 이력으로 산출한다.

- 조건·예외: 특정 기본 비용 항목만 대상으로 삼아 신규 거래를 누락하지 않는다.
- 대체된 옛 규칙:
  - 최신 승인 요청은 카드 지출정리 건수를 사용자가 반복 확인하지 않아도 P1→P2가 처리하고, 실제 사용자 판단만 최종 표시하는 것이다. — 2026-11-05, docs/specs/autonomous-expense-cleanup-20261105.md:5
- 출처: `docs/specs/autonomous-expense-cleanup-20261105.md:39`, `docs/specs/autonomous-expense-cleanup-20261105.md:71`, `docs/specs/finance.md:35`, `docs/specs/unified-expense-action-queue-20261105.md:190`, `docs/specs/unified-expense-action-queue-20261105.md:203`

### PROC-003 · 작업함·질문 대기 폐지

*일반 · 결정 2026-11-10*

정상 거래 판정을 사용자 확인함·P3 질문/답변·보류·미배정·미분류·처리필요 상태로 남기지 않는다. 메뉴·필터·카운터·배지·CTA와 이를 새 이름으로 만든 대기열도 제공하지 않는다.

- 조건·예외: 사용자는 완료된 귀속을 분기 검수에서 교정한다. 내부 금융 안전 잠금은 별도로 보존한다.
- 대체된 옛 규칙:
  - 미배정 상태를 사용자 분류 보호 상태로 유지한다. — 2026-11-06, docs/specs/cost-pr-only-implementation-brief-20261106.md:70
  - 새로운 P3 질문은 사람만 답할 수 있는 구체적인 사실이 있고 재검증/안전 소비 경로가 있을 때만 /my-actions에 단일 그룹으로 등록한다. — 2026-11-06, docs/specs/cost-pr-only-implementation-brief-20261106.md:70
  - 내 확인 필요 0건과 금융 대사 원행 6건은 합법적으로 공존한다. — 2026-11-06, docs/specs/cost-pr-only-implementation-brief-20261106.md:71
  - P1 안전 처리 뒤 진짜 P3를 노출한다. — 2026-11-06, docs/specs/cost-pr-only-implementation-brief-20261106.md:141
  - 그 밖에 143건
- 출처: `MERGE.md:20`, `docs/specs/uiux-full-audit-redesign-20261110.md:87`, `docs/specs/uiux-full-audit-redesign-20261110.md:753`, `docs/specs/card-destination-only-ux-20261108.md:7`, `docs/specs/card-destination-only-ux-20261108.md:9`

### PROC-004 · 분기 기타비용 종결

*일반 · 결정 2026-11-10*

실제 여행 귀속을 P1/P2로 우선하고, 끝내 해소되지 않은 일반 비용은 원문 결제일이 속한 분기 기타비용으로 종결한다. 기존 자료의 읽기 투영에도 실제 여행 또는 기타비용 귀속을 적용한다.

- 조건·예외: 원문 결제일이 없으면 유효한 매입일을 사용한다. AI 미설정·실패도 사용자 질문으로 전가하지 않는다.
- 대체된 옛 규칙:
  - 후보가 없거나 유효하지 않으면 UNASSIGNED_NO_VALID_TRIP. — 2026-10-28, docs/history/provisional-assignment-review-first-20261028.md:80
  - 권위 여행 자체가 없을 때 미배정으로 남긴다. — 2026-10-23, docs/specs/finance.md:113
  - 여행 authority 자체가 전혀 없으면 NO_TRIP_AUTHORITY; 후보가 0개면 NEEDS_CANDIDATE로 남긴다. — 2026-10-23, docs/specs/participants.md:86
  - 여행 후보가 없는 상태를 별도 미완료 출력으로 남긴다. — 2026-10-23, docs/specs/participants.md:86
  - 그 밖에 7건
- 출처: `docs/specs/uiux-full-audit-redesign-20261110.md:87`, `docs/specs/card-destination-only-ux-20261108.md:8`, `docs/specs/card-destination-only-ux-20261108.md:9`, `docs/specs/cost-pr-only-implementation-brief-20261106.md:3`

### PROC-005 · 원본 오류의 내부 차단

*보호 · 결정 2026-11-08*

날짜 미상·금액 오류·원본 충돌은 내부 안전 차단과 사실에 맞는 설명으로 남긴다. 임의의 오늘 날짜·분기·성공·금융 기록을 만들지 않고 작업함으로 보내지 않는다.

- 조건·예외: 정상 거래의 분기 종결을 원본 오류의 허위 해결로 확대하지 않는다.
- 출처: `docs/specs/card-destination-only-ux-20261108.md:8`, `docs/specs/card-destination-only-ux-20261108.md:9`

### PROC-006 · 낮은 신뢰도는 설명

*일반 · 결정 2026-11-05*

낮은 신뢰도·추가 예약 단서 부족·후보 동률은 근거와 불확실성으로 표시한다. 이미 저장된 유효한 분류를 미완료로 되돌리거나 추가 확정을 요구하지 않는다.

- 조건·예외: 원본 오류·금융 보호 충돌은 별도 내부 검증 대상으로 유지한다. 후보 평가의 CONFLICT_REVIEW/UNASSIGNED_NO_VALID_TRIP는 내부 중간 결과이며 사용자 분류 대기 상태가 아니다.
- 대체된 옛 규칙:
  - 신뢰도 높은 자동 여행 추론은 즉시 분류 완료로 인정한다. — 2026-10-29, docs/specs/card-upload-full-reconciliation-20261029.md:21
  - 단 실제 유효 여행 ID, 거래 성격 확정, 근거가 있는 단일 우세 후보, 기존 수동 결정/잠금 비침해, 동률·충돌 부재를 모두 요구한다. — 2026-10-29, docs/specs/card-upload-full-reconciliation-20261029.md:21
  - 근거 없는 숫자 임계값이나 모델 확률만으로 완료 금지. — 2026-10-29, docs/specs/card-upload-full-reconciliation-20261029.md:21
  - 높은 신뢰도의 자동 추론만 분류 완료를 허용한다. — 2026-10-29, docs/specs/card-upload-full-reconciliation-20261029.md:29
  - 그 밖에 8건
- 출처: `docs/specs/autonomous-expense-cleanup-20261105.md:51`, `docs/specs/unified-expense-action-queue-20261105.md:140`, `docs/specs/unified-expense-action-queue-20261105.md:194`, `docs/specs/status-and-inference-stages-20261102.md:32`, `docs/specs/ui.md:9`

### PROC-007 · 추천 대신 자동 배정

*일반 · 결정 2026-10-29*

유효한 실제 여행 후보가 있으면 최선의 한 여행에 자동 배정하고 선택 근거와 불확실성을 남긴다. 추천을 보여 준 뒤 사용자 확정을 기다리는 흐름을 만들지 않는다.

- 조건·예외: 낮은 신뢰도나 복수 후보라는 이유만으로 기본 미배정하지 않는다.
- 대체된 옛 규칙:
  - 사용 가능한 여행 단서로 여행을 잠정 상태로 고른다. — 2026-10-28, docs/history/provisional-assignment-review-first-20261028.md:30
  - waiting_source/evidence_missing 거래의 여행 귀속을 잠정 상태로만 진행한다. — 2026-10-28, docs/history/provisional-assignment-review-first-20261028.md:133
  - 여행 귀속을 잠정 상태로 둔다. — 2026-10-28, docs/specs/ota-review-queue-performance-20261027.md:22
  - AUTO_PROVISIONAL 여행을 제안/적용하고 사용자 검토를 받는다. — 2026-10-28, docs/specs/ota-review-queue-performance-20261027.md:22
  - 그 밖에 1건
- 출처: `docs/specs/finance.md:65`, `docs/specs/finance.md:113`, `docs/specs/participants.md:45`, `docs/specs/participants.md:86`, `AGENTS.md:43`

### PROC-008 · 분류되면 완료

*일반 · 결정 2026-11-02*

자동·수동 모두 항목·귀속·설명과 출처·근거가 저장되면 분류 완료다. 잠정 후 승인·확정/미확정·확정 대기를 추가하지 않으며, 내부 장부 미기록도 분류 미완료로 간주하지 않는다.

- 조건·예외: 귀속은 최신 계약의 실제 여행 또는 분기 기타비용이다. 정상 환불 탭은 여행 ID가 비어 있어도 완료다.
- 대체된 옛 규칙:
  - 기존 AUTO_PROVISIONAL은 조건 미달 시 계속 미완료; 조건 충족 시 명시적 확정 자동결정으로 기록해야 완료로 인정한다. — 2026-10-29, docs/specs/card-upload-full-reconciliation-20261029.md:21
  - 여행 성격 둘 다 별도 확정돼야 완료로 처리한다. — 2026-10-29, docs/specs/card-upload-full-reconciliation-20261029.md:29
  - 여행 귀속을 잠정 배정 상태로 유지한다. — 2026-10-28, docs/COST_V3_START_HERE.md:48
  - 낮은 근거의 자동 귀속을 잠정 배정 뒤 사용자 검토 상태로 둔다. — 2026-10-28, docs/history/provisional-assignment-review-first-20261028.md:8
- 출처: `docs/history/operations-20261028-20261107.md:531`, `docs/history/session_handoff-through-20261107.md:583`, `docs/specs/card-upload-full-reconciliation-20261029.md:10`, `docs/specs/finance.md:40`, `docs/specs/finance.md:56`

### PROC-009 · 상태·판정 출처 분리

*일반 · 결정 2026-11-02*

자동·코드 추론·AI 추론·직접 입력의 출처를 분류 결과와 따로 보존한다. 기존 inference/auto_inferred나 코드 재검토 표식은 코드 추론이며 AI 실행 증거로 취급하지 않는다.

- 조건·예외: provisional_assignment 같은 호환 이름이나 decided/decided_at 필드만으로 잠정·미확정 상태를 만들지 않는다.
- 출처: `docs/specs/finance.md:14`, `docs/specs/status-and-inference-stages-20261102.md:8`, `docs/specs/status-and-inference-stages-20261102.md:10`, `docs/specs/status-and-inference-stages-20261102.md:32`, `docs/COST_V3_START_HERE.md:77`

### PROC-010 · 실제 AI 실행 증거

*보호 · 결정 2026-11-05*

AI 검토 완료는 기존 연결 에이전트의 실제 실행과 자료 대조가 확인된 때만 표시한다. provider/model/run_id, 요청 digest, 결과 근거·불확실성과 원본 버전 검증 정보를 남긴다.

- 조건·예외: 코드 기본값·모델 미실행·합성 성공을 AI의 운영 검토 성공으로 표시하지 않는다.
- 출처: `docs/specs/autonomous-expense-cleanup-20261105.md:48`, `docs/specs/unified-expense-action-queue-20261105.md:208`, `docs/specs/status-and-inference-stages-20261102.md:32`

### PROC-011 · AI 결과 원자 적용

*보호 · 결정 2026-11-05*

P2 결과는 허용된 기존 여행·비용 항목 안에서만 검증해 preview/apply 경로로 원자 적용한다. 요청·원본·revision·문맥 digest가 일치해야 하며 stale 결과로 새 결정을 덮지 않는다.

- 조건·예외: 원본 금액·ID·수동 결정·환불 링크를 모델이 임의 변경하지 않는다.
- 출처: `docs/specs/unified-expense-action-queue-20261105.md:206`, `docs/specs/unified-expense-action-queue-20261105.md:244`, `docs/specs/status-and-inference-stages-20261102.md:10`, `docs/specs/participants.md:139`, `docs/specs/participants.md:175`

### PROC-012 · P2에 주는 자료

*일반 · 결정 2026-11-10*

P2 에이전트(구독 프론티어 모델)에는 판정에 필요한 원문 전체를 줄 수 있다: 카드 원행, 관련 메일·포털 원문, 과거 같은 가맹점의 판정. 무료 모델에는 고객 원문을 주지 않는다.

- 조건·예외: 원문은 P2 실행의 사건 폴더에만 넣는다. Git·보고서·PR·일반 로그에는 옮기지 않는다(통합 명세 §6, §13).
- 코드와 다른 점: app/ai_classification.py의 prepare()는 가맹점 이름과 원문 없이 날짜·국가·후보 여행만 넘긴다. M2에서 사건 폴더 방식으로 바꾼다.
- 대체된 옛 규칙:
  - 연결 AI 요청에는 비식별 특징만 전달하고 고객명·카드번호·예약번호·원문 메모 등 민감 원문은 제외한다. — 2026-11-10·11 사용자 결정으로 대체
- 출처: `docs/specs/uiux-full-audit-redesign-20261110.md:756`, `docs/specs/autonomous-expense-cleanup-20261105.md:48`, `docs/specs/autonomous-expense-cleanup-20261105.md:58`, `docs/specs/receipt-unified-upload-ux-20261105.md:49`, `AGENTS.md:17`

### PROC-013 · P2 실행 모델

*보호 · 결정 2026-11-10*

P2는 구독 에이전트 CLI로 실행한다. `codex/gpt-6.1-sol`이 기본이고 `claude/opus`가 대체다. 건당 과금되는 API·새 키·승인되지 않은 유료 자원으로 자동 전환하지 않는다.

- 조건·예외: 한도·실패는 대기와 재시도로 처리한다. 무료 모델로의 교체는 작업 유형별 확인을 거친 뒤에만 한다(통합 명세 §11.4).
- 코드와 다른 점: app/connected_agent_provider.py는 무료 OpenCode 모델만 허용한다. M2에서 실행기를 바꾼다.
- 대체된 옛 규칙:
  - 기존 승인된 연결 에이전트·프로바이더 계약만 사용한다. — 2026-11-10·11 사용자 결정으로 대체
- 출처: `docs/specs/autonomous-expense-cleanup-20261105.md:58`, `docs/specs/status-and-inference-stages-20261102.md:11`, `docs/specs/participants.md:144`, `docs/specs/participants.md:175`, `docs/specs/google-ledger.md:77`

### PROC-014 · 추론을 사용자 사실로 기록 금지

*보호 · 결정 2026-11-05*

AI의 판단·예약 근거·예상 답변을 사용자 확인·직접 답변·예약 유지·실제 환급 확인으로 저장하거나 보고하지 않는다. 추론 출처와 실제 사용자 답변을 구분한다.

- 조건·예외: 사용자가 실제 선택·확인하지 않은 제안은 사용자 사실이 아니다.
- 출처: `docs/specs/unified-expense-action-queue-20261105.md:240`, `docs/specs/unified-expense-action-queue-20261105.md:347`, `docs/specs/finance.md:50`, `docs/specs/finance.md:81`, `docs/specs/finance.md:91`

### PROC-015 · 추론의 수동 학습 금지

*보호 · 결정 2026-10-29*

새로 추론한 여행이나 AUTO_TRIP_INFERRED 결과를 수동 교정 사례·수동 규칙 학습 근거로 취급하지 않는다. 과거 결정·override 이력도 삭제하거나 위조하지 않는다.

- 조건·예외: P2 사례의 검증 가능한 코드 승격은 별도 절차이며 사용자 답변으로 위장하는 학습은 금지한다.
- 출처: `docs/specs/finance.md:89`, `docs/specs/finance.md:95`, `docs/history/operations-20261028-20261107.md:960`, `docs/history/operations-20261028-20261107.md:968`

### PROC-016 · 수동 교정 최우선

*보호 · 결정 2026-11-05*

사용자가 명시적으로 선택·이동·수정한 유효 귀속과 수동 링크·제외 결정을 자동 수집·재분류·AI·재사용 규칙이 덮어쓰지 않는다. 해당 귀속의 변경은 사용자의 명시 동작으로만 수행한다.

- 조건·예외: 빈 필드나 override의 존재만으로 만들어 낸 사용자 의도는 보호할 수동 결정으로 간주하지 않는다.
- 출처: `docs/specs/autonomous-expense-cleanup-20261105.md:47`, `docs/specs/unified-expense-action-queue-20261105.md:195`, `docs/specs/finance.md:50`, `docs/specs/finance.md:56`, `docs/specs/finance.md:89`

### PROC-017 · 즉시 수동 이동

*일반 · 결정 2026-10-23*

사용자는 완료된 비용 행을 다른 유효 여행으로 즉시 이동할 수 있다. 저장·화면 반영에 AI 응답·학습·규칙 작성·질문 답변을 요구하지 않으며 모델 실패로 이동을 취소하지 않는다.

- 조건·예외: 긴 대사 조사·전체 재학습·무관한 전체 회귀로 한 행의 교정을 막지 않는다.
- 예: 자동으로 여행 A에 배정된 비용을 사용자가 B로 옮기면 AI가 실패해도 B에 유지한다.
- 출처: `docs/specs/participants.md:46`, `docs/specs/participants.md:51`, `docs/specs/participants.md:53`, `docs/history/product-and-handoffs.md:80`, `docs/specs/finance.md:458`

### PROC-018 · 빈 여행 복원 순서

*일반 · 결정 2026-10-29*

비어 있는 여행은 현재 장부의 유효 여행, 가장 최근 저장한 유효 여행, 기존 장부 기록의 유효 여행, 새 추론 순서로 복원·배정한다. 기존 환불 탭 귀속은 여행으로 강제 변경하지 않고 환불 탭으로 복원한다.

- 조건·예외: 유효한 수동 항목·귀속과 과거 이력은 보존한다.
- 출처: `docs/specs/finance.md:89`

### PROC-019 · 미배정 의도 오인 금지

*보호 · 결정 2026-10-29*

분류 이력·review_decisions·board_manual_overrides·decided_at의 존재 또는 빈 여행·unclassified 기본값만으로 사용자가 미배정을 선택했다고 추정하지 않는다.

- 조건·예외: 실제로 입력된 유효한 항목·여행의 보호와 구분한다.
- 출처: `docs/specs/finance.md:89`, `AGENTS.md:41`

### PROC-020 · 비용 항목 추론 순서

*일반 · 결정 2026-11-05*

기존 확정 항목과 메일·규칙 엔진의 구체적 근거를 먼저 적용하고, 부족하면 카드사 업종→서비스 용도 단어→해외 현지 사용→업무 카드 기본값 순으로 추론한다. 단서 부족은 기타경비, 해외 사용은 현지경비, 원결제 미식별 취소는 취소·환불로 채운다.

- 조건·예외: 미분류라는 항목으로 이름만 바꾸지 않으며 출처·선택 근거·불확실성을 저장한다.
- 예: 기존 항목이 없고 해외 현지 사용 단서만 있으면 현지경비로 분류한다.
- 출처: `docs/specs/unified-expense-action-queue-20261105.md:197`, `docs/specs/card-upload-full-reconciliation-20261029.md:29`, `docs/specs/finance.md:85`, `docs/specs/finance.md:86`, `docs/specs/finance.md:87`

### PROC-021 · 결정적 동률 해소

*일반 · 결정 2026-10-29*

실제 여행 후보를 공통 점수·우선순위로 비교하고 동률도 결정적인 일정·ID 순서로 한 후보를 고른다. 동일 조건의 수입-비용 차액 규칙을 사용할 때는 선택 이유와 당시 권위 금액 지문을 남긴다.

- 조건·예외: 입력 순서에 따라 결과가 달라지지 않으며 점수·동률 자체를 사용자 승인 대기로 바꾸지 않는다.
- 출처: `docs/specs/finance.md:100`, `docs/specs/participants.md:96`, `docs/specs/participants.md:98`, `소유자 지시 메모:feedback-auto-assign-monthly-review.md:12`, `소유자 지시 메모:feedback-no-recommendation.md:12`

### PROC-022 · 여행·고객 창작 금지

*보호 · 결정 2026-10-29*

추론은 현재 권위 목록에 존재하는 실제 여행만 사용하며, 없는 여행·가짜 ID·고객 신원을 만들어 귀속을 완성하지 않는다.

- 조건·예외: 유효 여행을 고를 수 없는 정상 일반 비용은 최신 분기 기타비용 규칙으로 종결한다.
- 출처: `docs/specs/card-upload-full-reconciliation-20261029.md:14`, `docs/specs/finance.md:100`, `docs/history/provisional-assignment-review-first-20261028.md:80`, `docs/specs/participants.md:86`, `docs/history/product-and-handoffs.md:1341`

### PROC-023 · 이용기간 우선

*일반 · 결정 2026-10-29*

여행 귀속에는 이용일을 사용하고 OTA의 검증된 service_period가 있으면 승인일 근접보다 우선한다. 기존 여행 종료일·준비 숙박 등 승인된 기간 규칙을 재사용한다.

- 조건·예외: 매입일을 이용일로 위조하지 않는다. 확인 가능한 이용일을 반복 질문하지 않는다.
- 출처: `docs/specs/finance.md:100`, `docs/specs/participants.md:98`, `소유자 지시 메모:owner-rules.md:13`

### PROC-024 · 분류·금융 사실 구별

*보호 · 결정 2026-11-08*

분류 완료, 예약↔카드의 실제 동일성, 취소·부분환불 연결, COST 내부 기록, Google 반영, 실제 은행 환급·실제 이용 완료를 별개 사실로 판단한다. 한 결과만으로 다른 결과를 완료 처리하지 않는다.

- 조건·예외: 여행 점수나 자동 귀속은 신원·예약·결제의 증명이 아니다.
- 예: 카드 취소 쌍의 순액이 0이어도 은행 입금 완료를 별도로 확인한 것은 아니다.
- 출처: `docs/specs/card-destination-only-ux-20261108.md:10`, `docs/specs/cost-pr-only-implementation-brief-20261106.md:70`, `docs/specs/autonomous-expense-cleanup-20261105.md:40`, `docs/specs/autonomous-expense-cleanup-20261105.md:51`, `docs/specs/finance.md:5`

### PROC-025 · 실제 수행만 보고

*보호 · 결정 2026-11-08*

조회·근거 확인·분류 교정·연결·내부 장부 기록·Google 반영·실제 환급을 실제 수행 범위대로 보고한다. 기존 연결을 조회한 것만으로 새 쓰기를 했다고 하거나 개별 완료를 전체 완료로 확대하지 않는다.

- 조건·예외: 미기록이면 그 사실과 다음 기록 경로를 남긴다. 조회 실패를 0건으로 감추지 않는다.
- 출처: `docs/operations.md:172`, `docs/session_handoff.md:195`, `docs/specs/cost-pr-only-implementation-brief-20261106.md:71`, `docs/specs/cost-pr-only-implementation-brief-20261106.md:141`, `docs/specs/unified-expense-action-queue-20261105.md:80`

### PROC-026 · 같은 질문 반복 금지

*일반 · 결정 2026-10-29*

기존 자료·이전 사용자 답변·계산·대조로 해결되는 사실은 다시 묻지 않는다. 확인한 사실·결정의 근거와 적용 범위를 보존해 재사용하고 정상 연결·완료 교정을 반복 제시하지 않는다.

- 조건·예외: 분류에 필요 없는 수수료 명칭이나 실제 환급 확인을 분류의 선행조건으로 만들지 않는다.
- 예: 이미 정상인 전액 취소 쌍은 연결 확인·순액 0·이번 쓰기 없음으로 정리한다.
- 출처: `docs/specs/finance.md:48`, `docs/specs/finance.md:52`, `docs/specs/finance.md:75`, `AGENTS.md:37`, `docs/COST_V3_START_HERE.md:74`

### PROC-027 · 새 권한·본질 정책만 확인

*보호 · 결정 2026-11-05*

기존 승인 범위를 벗어나는 새 권한·인증·본질적인 업무 정책이 실제로 필요할 때만 그 행동의 필수 결정을 확인한다. 확인된 사실·직접 얻을 수 없는 필수 사실·답에 따라 달라질 처리를 제시하고 독립 작업은 계속한다.

- 조건·예외: 정상 카드 분류를 위한 P3 작업함·질문 대기를 되살리지 않는다. 단순 구현 선택·재승인·낮은 신뢰도는 확인 사유가 아니다.
- 대체된 옛 규칙:
  - 승인된 업무 계약 안의 규칙 코드화·검증은 P1/P2/P3 원칙에 따라 자율 수행하고, 새로운 업무 정책·권한 결정만 P3로 올린다. — 2026-10-29, docs/COST_V3_START_HERE.md:82
- 출처: `docs/specs/autonomous-expense-cleanup-20261105.md:61`, `docs/specs/autonomous-qa-20261102.md:53`, `docs/specs/finance.md:48`, `docs/specs/finance.md:65`

### PROC-028 · 승인 범위 교정 즉시 실행

*일반 · 결정 2026-10-29*

기존 근거와 승인된 규칙으로 판단 가능한 비용 항목·여행 귀속 교정은 바로 처리한다. 이미 승인된 업무에 단순 변경 승인을 추가하지 않고 다음 거래를 계속 검토한다.

- 조건·예외: 현재 지시가 다음 건이면 완료 건을 다시 묻지 않는다. 신규 금융·외부 쓰기 권한으로 확대하지 않는다.
- 대체된 옛 규칙:
  - 규칙 변경은 소유자 승인 뒤에 적용한다. — 2026-10-15, C:/Users/kkokk/.claude/projects/C--AX-cost/memory/feedback-trip-no-per-merchant-approval.md:15
- 출처: `docs/specs/finance.md:50`, `docs/specs/finance.md:54`, `docs/specs/finance.md:75`, `docs/specs/finance.md:85`, `AGENTS.md:40`

### PROC-029 · 검증 후 P1 코드 승격

*일반 · 결정 2026-10-29*

P2의 처리·교정과 실제 사용자 결정에서 재사용 조건·판단 근거·적용 범위·예외를 추출한다. 원본 보호·반례·회귀 검증을 통과한 반복 가능한 유형을 코드 규칙으로 승격하여 이후 P1이 처리하게 한다.

- 조건·예외: 승인된 업무 계약 안의 코드화·검증은 자율 수행한다. 일회성 추론의 즉시 일반화·수동 교정 덮어쓰기·추론의 사용자 답변 위장은 금지한다.
- 대체된 옛 규칙:
  - 기존 정책대로 최종 일반화는 사용자의 승인이 있어야 하고, 승인 범위(가맹점/기간/여행) 외에 적용 금지. — 2026-10-28, docs/history/provisional-assignment-review-first-20261028.md:89
  - 사용자 승인 전 일반화 규칙은 적용하지 않는다. — 2026-10-23, docs/history/product-and-handoffs.md:80
- 출처: `docs/specs/finance.md:40`, `docs/specs/finance.md:50`, `AGENTS.md:37`, `docs/COST_V3_START_HERE.md:74`, `docs/history/session_handoff-through-20261107.md:1040`

### PROC-030 · 범위 없는 일반화 금지

*보호 · 결정 2026-11-05*

한 거래의 예외·수동 교정·과거 수기 장부·같은 업체라는 사실을 모든 여행·미래 거래의 증거로 일반화하지 않는다. 재사용하려면 조건·범위·예외와 실제 원행 증거를 구분한다.

- 조건·예외: 거래별 추론은 해당 원행 hash에 묶고 다른 날짜·금액·원행으로 자동 확대하지 않는다.
- 출처: `docs/specs/unified-expense-action-queue-20261105.md:334`, `docs/history/provisional-assignment-review-first-20261028.md:89`, `docs/specs/google-ledger.md:150`, `docs/specs/finance.md:500`, `docs/specs/finance.md:242`

### PROC-031 · 사용자 재사용 규칙의 명시 범위

*보호 · 결정 2026-11-05*

사용자가 직접 저장하는 재사용 규칙은 이번 거래만의 교정과 구분하고, 명시한 조건·기존/미래 적용 범위에만 적용한다. 이번 건만 선택한 사실로 미래 규칙을 만들지 않는다.

- 조건·예외: 이는 승인된 업무 계약 안의 자율 코드 승격에 형식적 승인을 요구하는 규칙이 아니다. 폐지된 질문 화면은 복원하지 않는다.
- 출처: `docs/specs/unified-expense-action-queue-20261105.md:334`, `docs/specs/participants.md:169`, `docs/specs/google-ledger.md:94`, `docs/specs/finance.md:503`, `docs/specs/finance.md:504`

### PROC-032 · 비활성 규칙 거부

*보호*

수동 재사용 규칙은 비활성·철회 상태면 승인 이력이 있어도 적용하지 않는다. active 표지만으로 사용자 승인 사실을 만들지 않는다.

- 조건·예외: 명시 승인을 필요로 하는 수동 규칙 저장 경로에 적용하며 일반 P1 코드 규칙과 구분한다.
- 출처: `docs/history/ota-legacy.md:729`, `docs/history/ota-legacy.md:731`, `docs/history/ota-legacy.md:1025`

### PROC-033 · 수동 OTA 차이 규칙의 한정

*보호*

사용자가 명시 저장한 OTA 금액·날짜 차이 규칙은 제공자·항목과 가맹점 또는 카드 범위가 지정된 동일 조건에만 적용한다. 차이의 원인을 할인·결제수단으로 임의 확정하지 않는다.

- 조건·예외: 승인 근거와 범위를 검증하는 보호 규칙이다. 과거의 제안·질문 대기 UI를 새로 요구하지 않는다.
- 출처: `docs/history/ota-legacy.md:731`, `docs/history/ota-legacy.md:906`

### PROC-034 · 기존 자료 먼저 대조

*일반 · 결정 2026-11-05*

원본 카드·보관 예약/취소 메일·포털 조사·OTA 이벤트·영수증·현재 Google 읽기 여행·수동 결정을 필요한 범위에서 함께 대조한다. 관련 환불 그룹까지 보고 한 행만 고립시켜 판단하지 않는다.

- 조건·예외: 등록 자료 읽기 실패를 자료 부재로 간주하지 않고, 오래되거나 누락된 스냅샷은 완전한 근거로 승격하지 않는다.
- 출처: `docs/specs/unified-expense-action-queue-20261105.md:204`, `docs/specs/finance.md:65`, `docs/history/operations-through-20261027.md:316`, `docs/specs/ota.md:531`, `docs/specs/participants.md:44`

### PROC-035 · 보고서 비식별 보호

*보호 · 결정 2026-11-05*

고객 원문·카드 식별값·예약번호·이름·토큰을 Git·일반 로그·보고서·외부 모델로 복사하지 않는다. 외부 전달은 비식별 상태 코드·건수 등 최소 정보로 제한한다.

- 조건·예외: 공유 식별자가 필요하면 서버 비밀키 기반 가명화를 사용하며 짧은 예약번호의 단순 해시로 대체하지 않는다.
- 출처: `docs/specs/autonomous-expense-cleanup-20261105.md:60`, `docs/specs/refactor-master-20261027.md:25`, `docs/specs/google-ledger.md:606`, `docs/specs/ota.md:273`, `AGENTS.md:30`

### PROC-036 · 원본·감사 이력 불변

*보호 · 결정 2026-11-08*

자동 판정·교정은 원본 금액·날짜·ID·원문·기존 사용자 결정과 감사 이력을 보존한다. 원본 수정 명령을 분류 교정으로 실행하거나 보존 자료·보호 테이블을 삭제하지 않는다.

- 조건·예외: 변경 가능한 분류·귀속·설명과 불변 원본을 구분한다.
- 출처: `docs/specs/card-destination-only-ux-20261108.md:10`, `docs/specs/finance.md:3`, `docs/specs/unified-expense-action-queue-20261105.md:3`, `AGENTS.md:5`, `docs/specs/autonomous-expense-cleanup-20261105.md:59`

### PROC-037 · 내부 금융 잠금 유지

*보호 · 결정 2026-11-05*

transaction_review_holds와 원행 hash 검증 등 내부 금융 안전 잠금은 보존한다. 잠금은 코드의 자동 검증 조건이 충족될 때만 해소하며, 답변 저장·재분류만으로 지우지 않는다.

- 조건·예외: 사용자에게 보류 상태·보류 해제·확인 체크박스를 제공하지 않는다. 잠금은 분류 대기 업무가 아니다.
- 대체된 옛 규칙:
  - 사용자가 자료 확인을 마쳤다는 별도 선택을 한 경우에만 같은 답변 저장 트랜잭션에서 해제한다. — 2026-10-04, docs/history/operations-through-20261027.md:237
  - 답변 저장이나 재분류만으로 해제하지 않으며, 자료 확인 후 사용자가 명시적으로 해제해야 한다. — 2026-10-04, docs/specs/finance.md:227
  - 사용자의 구체적 답변 후 P1/P2를 자동 재실행한다는 P3 답변 소비 흐름. — 2026-11-05, AGENTS.md:38
- 출처: `docs/specs/autonomous-expense-cleanup-20261105.md:3`, `docs/specs/finance.md:5`, `docs/specs/status-and-inference-stages-20261102.md:5`, `docs/specs/unified-expense-action-queue-20261105.md:351`, `docs/specs/unified-expense-action-queue-20261105.md:353`

### PROC-038 · 금융 연결 보호

*보호 · 결정 2026-11-05*

분류 자동화가 원본 오류·실제 중복·원결제 경합·초과환불·불완전 환불 묶음·수동 링크·회사 경비 제외·이미 기록된 행을 침해하지 않게 한다. 예약 ID 부족이나 낮은 추론으로 금융 연결을 창작하거나 보호를 해제하지 않는다.

- 조건·예외: 여행 귀속 완료와 정확 결제·환불 검증은 독립이다.
- 출처: `docs/specs/autonomous-expense-cleanup-20261105.md:73`, `docs/specs/unified-expense-action-queue-20261105.md:101`, `docs/specs/unified-expense-action-queue-20261105.md:352`, `docs/specs/autonomous-qa-20261102.md:53`, `docs/specs/card-upload-full-reconciliation-20261029.md:10`

### PROC-039 · 환불 묶음 원자성

*보호 · 결정 2026-10-13*

새로 기록하는 환불은 원결제와 취소·부분환불의 전체 구성원을 함께 검증하고 원자 기록한다. 문제가 있는 묶음은 내부 차단하되 같은 파일의 무관한 정상 거래까지 막지 않는다.

- 조건·예외: 일부 구성원만 기록해 묶음 보호를 우회하지 않는다.
- 출처: `docs/specs/finance.md:148`, `docs/history/operations-through-20261027.md:237`

### PROC-040 · 소수 교정의 복구

*보호 · 결정 2026-10-29*

소수 자동분류 교정은 원본 hash·revision·미리보기 digest를 확인하고 단일 DB 트랜잭션으로 거래·기존 장부·화면 귀속을 맞춘다. 변경 전 값과 에이전트 근거를 남겨 해당 변경을 되돌릴 수 있게 한다.

- 조건·예외: 새 장부·금융 링크·Google 쓰기나 대량 재처리 게이트 우회로 확대하지 않는다. 위험에 맞지 않는 전체 백업·서버 중지를 매번 반복하지 않는다.
- 출처: `docs/specs/finance.md:81`, `docs/COST_V3_START_HERE.md:76`, `docs/history/ota-legacy.md:120`

### PROC-041 · 위험별 데이터 게이트

*보호 · 결정 2026-11-05*

대량 재처리·삭제·스키마/금융 원본 변경·여러 저장소 변경처럼 이력만으로 복구하기 어려운 쓰기는 별도 승인 범위와 백업·복원·단일 작성자 게이트를 확인한다. 코드 수정·배포만으로 과거 원본을 소급 변경하지 않는다.

- 조건·예외: 이미 승인된 개별 분류·여행 교정과 새로운 운영 쓰기를 구분한다.
- 출처: `docs/specs/autonomous-expense-cleanup-20261105.md:59`, `docs/specs/autonomous-expense-cleanup-20261105.md:61`, `docs/specs/finance.md:96`, `docs/specs/google-ledger.md:606`

### PROC-042 · Google 최종 장부 읽기만

*보호 · 결정 2026-11-10*

COST는 Google 최종 장부에 자동으로 쓰지 않는다. 분류 완료·내부 기록·복사 버튼·사용자의 붙여넣기 표시만으로 Google 반영을 확정하지 않는다.

- 조건·예외: 사용자 직접 복사·기존 외부 쓰기 권한 경계를 유지한다.
- 출처: `docs/specs/uiux-full-audit-redesign-20261110.md:87`, `docs/specs/autonomous-expense-cleanup-20261105.md:59`, `docs/specs/unified-expense-action-queue-20261105.md:355`, `docs/specs/autonomous-qa-20261102.md:53`, `docs/specs/finance.md:96`

### PROC-043 · 읽기·preview 무쓰기

*보호 · 결정 2026-11-02*

조회·preview·진단은 실제 DB 쓰기와 외부 호출을 실행하지 않는다. P1 선행 평가가 필요하면 읽기 전용 DB의 메모리 사본을 사용한다.

- 조건·예외: 명시 적용·쓰기 경로와 읽기 재평가를 분리한다.
- 출처: `docs/specs/status-and-inference-stages-20261102.md:11`, `docs/specs/status-and-inference-stages-20261102.md:30`, `docs/specs/refactor-master-20261027.md:25`

### PROC-044 · 지문 기반 멱등 재평가

*일반 · 결정 2026-11-05*

거래·원행 hash/revision·여행/Google 세대·규칙/판단 코드 지문이 같은 완료 검토는 반복 호출하지 않는다. 근거·정책 지문 변경 또는 명시 재검토 때만 재평가하고 재실행 결과는 무변경이어야 한다.

- 조건·예외: 순서 변경·재시작·재접속 때문에 같은 효과를 중복 적용하지 않는다.
- 출처: `docs/specs/autonomous-expense-cleanup-20261105.md:47`, `docs/specs/autonomous-expense-cleanup-20261105.md:57`, `docs/specs/unified-expense-action-queue-20261105.md:205`, `docs/specs/finance.md:83`, `docs/specs/finance.md:284`

### PROC-045 · 기술 실패는 내부 처리

*일반 · 결정 2026-11-05*

P2 미실행·timeout·한도·잘못된 응답·오래된 원본·코드 결함은 내부 재시도·진단으로 처리한다. 실제 재시도 없이 자동 처리 중·AI 검토 성공이라고 표시하거나 사용자 보류 해제 업무로 전가하지 않는다.

- 조건·예외: 일반 비용의 최종 귀속은 여행 우선·분기 기타비용 규칙을 따른다. 금융 보호 실패는 숨기지 않는다.
- 출처: `docs/specs/autonomous-expense-cleanup-20261105.md:3`, `docs/specs/autonomous-expense-cleanup-20261105.md:39`, `docs/specs/autonomous-expense-cleanup-20261105.md:57`, `docs/specs/finance.md:5`, `docs/specs/unified-expense-action-queue-20261105.md:80`

### PROC-046 · 반복 실패의 코드 개선

*일반 · 결정 2026-11-05*

같은 유형의 미처리·실패가 반복되면 에이전트가 코드 결함을 조사·수정·검증하고, 바뀐 판단 코드 fingerprint로 영향 거래를 재평가한다.

- 조건·예외: 금융 정책·원본 사실·새 권한 문제를 코드 결함으로 위장해 보호를 우회하지 않는다.
- 대체된 옛 규칙:
  - 금융 정책·원본 사실·새 권한이 필요한 문제는 코드 결함으로 위장하지 말고 필요한 한 가지 사용자 판단만 작업함에 올린다. — 2026-11-05, docs/specs/unified-expense-action-queue-20261105.md:220
- 출처: `docs/specs/unified-expense-action-queue-20261105.md:212`, `docs/specs/unified-expense-action-queue-20261105.md:219`

### PROC-047 · 개선 효과·판정 감사

*일반 · 결정 2026-11-05*

자동/AI 처리·실패·재시도·교정·규칙 승격의 시간·소스·근거·불확실성·관련 버전을 추적한다. 반복 질문과 재발 원인, P1 확대와 사용자 개입 감소를 실제 건수·검증 근거로 평가한다.

- 조건·예외: 고객 원문은 일반 로그·Git에 넣지 않으며 기존 기록을 재사용한다. 기존 원문 Q/A가 정본이며 요약은 복원 가능한 캐시로 취급한다.
- 출처: `docs/specs/autonomous-expense-cleanup-20261105.md:60`, `docs/specs/finance.md:52`, `AGENTS.md:42`, `docs/specs/participants.md:168`, `docs/specs/participants.md:482`

### PROC-048 · 연령으로 자동 숨김 금지

*일반 · 결정 2026-10-29*

오래된 OTA나 과거 거래를 90일·180일·연도 경과만으로 자동 완료·폐기·보관해 검토 대상에서 빼지 않는다. 과거 거래도 일반 규칙과 실제 근거로 처리한다.

- 조건·예외: 명시적인 조회·전기 미리보기 기간 필터는 허용하되 거래 상태를 바꾸지 않는다.
- 대체된 옛 규칙:
  - 운영 검토 범위는 2026-04-01 이후다. — docs/specs/finance.md:454
  - 완료된 이전 기간은 원본과 처리 이력을 내부 보존하고 목록, 질문, 미리보기와 신규 전기에서 제외한다. — docs/specs/finance.md:454
- 출처: `docs/specs/finance.md:18`, `docs/specs/ota-review-queue-performance-20261027.md:22`, `docs/specs/owner-product-decisions-20261028.md:12`, `docs/history/provisional-assignment-review-first-20261028.md:8`, `docs/history/provisional-assignment-review-first-20261028.md:29`

### PROC-049 · 영수증 외부 AI 명시 실행

*보호*

영수증 외부 AI 분석은 현재 모델 가용성·비용·개인정보 전송 동의를 확인한 뒤 owner가 명시 실행한 경우에만 호출한다. 인증·CSRF·저장 사진 소유 검증과 승인된 자료 범위를 지킨다.

- 조건·예외: 과거 특정 모델의 무료 이용·기존 동의를 현재의 포괄 전송 권한으로 간주하지 않는다. 과거 CLI·특정 모델·무료 설정을 현재 사실로 단정하지 않는다.
- 대체된 옛 규칙:
  - 특정 고정 Muse 모델·OpenCode 호출 설정을 현재 영수증 분석 경로로 단정한다. — docs/specs/receipts.md:34
- 출처: `docs/specs/receipts.md:24`, `docs/specs/receipts.md:58`, `docs/specs/receipts.md:59`, `docs/specs/receipts.md:62`

### PROC-050 · 모델 출력은 검증 데이터

*보호*

영수증/OCR·AI 응답은 검증할 후보 데이터이며 비용 확정·카드 결제·Google 수정 명령이 아니다. 이미지나 응답 속 지시를 운영 명령·SQL·코드로 실행하지 않는다.

- 조건·예외: 카드 정상 거래의 P2 판정 완료와 원본을 새로 읽어 만드는 OCR 후보를 구분한다.
- 대체된 옛 규칙:
  - AI 응답 검증 실패를 사용자 대기/재질문 상태로 처리한다. — 2026-10-23, docs/specs/participants.md:165
- 출처: `docs/specs/receipts.md:35`, `docs/specs/receipts.md:60`, `docs/specs/receipts.md:61`

### PROC-051 · 영수증 AI 실패 시 직접 입력

*일반*

영수증 AI 분석 실패·빈 결과·AI 미설정에도 원본 확인과 직접 입력 경로를 유지한다.

- 조건·예외: 실패를 성공 처리하거나 유료 모델에 자동 재시도하지 않는다.
- 대체된 옛 규칙:
  - OCR 신뢰도가 낮거나 총액이 불명확하면 HOLD. — 2026-10-11, docs/specs/google-ledger.md:117
- 출처: `docs/specs/receipts.md:63`

### PROC-052 · AI 실행의 최소 권한

*보호*

영수증 분석 모델은 격리된 임시 작업 디렉터리·읽기 전용 전용 에이전트로 실행하고 파일·셸·웹·MCP의 임의 호출을 차단한다.

- 조건·예외: 첨부된 승인 사진 이외의 다른 원본·DB·API 접근으로 확대하지 않는다.
- 출처: `docs/specs/receipts.md:60`

### PROC-053 · 영수증 비용 중복 보호

*보호 · 결정 2026-11-05*

영수증 교정은 기존 원본 SHA·revision 검증을 재사용하고 현금·개인카드·법인카드 구분과 카드 거래 중복 비용 방지를 유지한다. 별도 지시가 없으면 물품 목록을 자동으로 여러 비용 행으로 쪼개지 않는다.

- 조건·예외: 통화별 기존 금액 처리와 사용자 직접 Google 복사 경로를 유지한다.
- 출처: `docs/specs/receipt-unified-upload-ux-20261105.md:49`, `docs/specs/google-ledger.md:117`

### PROC-054 · 영향 범위 검증

*보호 · 결정 2026-11-02*

규칙 변경·교정은 바뀐 조건과 직접 영향 경계·반례를 검증한다. 이미 유효하게 통과한 무관한 전체 대사·OTA 회귀를 관성적으로 반복하지 않는다.

- 조건·예외: 실제 고객 저장·권한·중복 제출 검증은 격리 합성 자료에서 수행하고 합성 검증과 실제 원본 수락을 구분한다.
- 출처: `docs/specs/autonomous-qa-20261102.md:53`, `docs/specs/core-workflow-remaining-implementation-20261030.md:55`, `docs/history/provisional-assignment-review-first-20261028.md:90`, `docs/specs/google-ledger.md:151`, `docs/specs/finance.md:104`

### PROC-055 · 단일 작성자

*보호 · 결정 2026-11-02*

같은 원본·DB·배포의 작성자는 하나로 유지하고 병렬 작업은 파일 소유권을 분리한다.

- 조건·예외: 기존 사용자 변경과 원본을 보존한다.
- 출처: `docs/specs/autonomous-qa-20261102.md:53`

### PROC-056 · 폐지 진입점 무쓰기

*보호 · 결정 2026-11-10*

기존 /my-actions GET은 인증 후 /cards/all로 이동하고 질문 화면을 렌더링하지 않는다. 작업 답변 POST/API는 인증·CSRF 보호 후 410으로 끝내며 새 작업 등록·답변 소비 worker를 중단한다.

- 조건·예외: 기존 task 이력은 감사 자료로 보존한다.
- 출처: `docs/specs/uiux-full-audit-redesign-20261110.md:753`, `docs/specs/card-destination-only-ux-20261108.md:16`

### PROC-057 · 수동 이동 동시성 보호

*보호 · 결정 2026-10-23*

수동 이동은 owner·same-origin/CSRF·실존 거래·권위 여행·revision·요청 ID를 검사해 결정과 감사 이력을 원자 저장한다. 같은 요청 ID의 동일 payload는 기존 결과를 반환하고 다른 payload 재사용·충돌은 거부하며 전부 rollback한다.

- 조건·예외: 자동 AI 호출과 네트워크 작업은 저장 커밋 밖에서 수행한다.
- 대체된 옛 규칙:
  - 수동 이동 감사에 reason_status='pending_ai'를 저장하고 사후 AI 질문 대기를 만드는 요구. — 2026-10-23, docs/specs/participants.md:107
- 출처: `docs/specs/participants.md:106`, `docs/specs/participants.md:107`, `docs/specs/participants.md:108`, `docs/specs/participants.md:109`

### PROC-058 · 명시 재검토와 신선도

*일반 · 결정 2026-11-02*

사용자가 재검토를 지시하면 --reconsider 경로로 자동 결과도 원본·항목·업종·예약 이용기간과 다시 대조한다. 이전의 유효 여행 없음 설명을 면제 사유로 쓰지 않되 사용자 결정과 기기록 유효 귀속을 우선한다.

- 조건·예외: 충분한 코드 분류는 매번 재검토하지 않는다. 원본·권위 여행·사용자 결정·금융 상태 지문이 바뀐 검토 캐시는 거부한다.
- 출처: `docs/specs/status-and-inference-stages-20261102.md:30`, `docs/specs/finance.md:83`, `docs/history/operations-through-20261027.md:316`, `docs/specs/finance.md:460`, `docs/history/ota-legacy.md:895`

### PROC-059 · 사전승인·요청·입금 구별

*보호 · 결정 2026-10-29*

명시 사전승인액·예약번호·이용기간을 자료로 보존하되 사전승인을 실제 결제로 표시하지 않는다. 환불 요청 메일은 요청 근거이며 카드 취소 원행·실제 은행 입금과 구분한다.

- 조건·예외: 취소 메일의 수신시각 오류만으로 취소 사실 전체를 버리지 않는다.
- 출처: `docs/specs/finance.md:71`

### PROC-060 · 환불 연결과 분류 완료

*보호 · 결정 2026-11-05*

동일 카드/발급사의 원승인번호로 정상 원결제 하나가 검증되면 여러 취소·부분환불을 연결하고 원결제의 항목·여행을 따른다. 전액환불 순액 0은 환불쌍 분류 완료이며 별도 확정 버튼을 요구하지 않는다.

- 조건·예외: 원승인번호 부재만으로 기존 승인된 정확대응 경로를 막지 않으며 원본 오류·중복·초과환불·원자 기록 보호를 유지한다.
- 출처: `docs/specs/unified-expense-action-queue-20261105.md:101`, `docs/specs/card-upload-full-reconciliation-20261029.md:17`, `docs/specs/finance.md:71`, `docs/specs/finance.md:93`

### PROC-061 · 원문 미상과 0 구별

*보호*

원화 금액 등 원문 사실이 없으면 미확인으로 남기고 0원이나 다른 자료의 값으로 만들어 넣지 않는다. 보고서에서 빠진 카드 사실을 추측해 채우지 않고 연결 원행의 직접 필드를 대조한다.

- 조건·예외: 자료 존재·부분 report와 정확 카드 결제 검증을 구분한다.
- 출처: `docs/history/ota-legacy.md:895`, `docs/history/ota-legacy.md:906`

### PROC-062 · 이름·별칭 범위 보호

*보호 · 결정 2026-10-28*

동일 영문명·별칭을 전 여행·전 사람의 동일 고객으로 일반화하지 않는다. 확인된 고객 ID·출처 범위와 사용자가 명시한 별칭 범위에만 적용하고 다른 여행의 고객을 자동 병합하지 않는다.

- 조건·예외: 신원 후보·별칭 제안은 카드 여행 추천·승인 대기와 별개이며 실제 신원 확정으로 위장하지 않는다.
- 예: 같은 영문 이름이 보여도 다른 여행의 고객 레코드를 자동 병합하지 않는다.
- 출처: `docs/specs/participant-income-authority-and-drag-link-20261028.md:94`, `docs/specs/participant-income-authority-and-drag-link-20261028.md:134`, `docs/specs/participant-income-authority-and-drag-link-20261028.md:177`, `docs/specs/participants.md:209`, `docs/history/product-and-handoffs.md:1344`

### PROC-063 · 수입 차액 임의 재분배 금지

*보호 · 결정 2026-10-23*

기존 수입-비용 차액 동률 규칙은 후보 선택 근거로만 사용한다. 특정 여행에 돈이 부족하다는 이유로 금액을 임의 재분배하는 새 정책은 만들지 않는다.

- 조건·예외: 금액 자체는 원본 불변이다.
- 출처: `docs/specs/participants.md:98`

### PROC-064 · 공통 판정 엔진 우선

*일반 · 결정 2026-10-28*

여행 귀속은 공급자별 무한 예외 대신 공통 후보 생성·ranker·정책 버전·교정 로그로 관리한다. 공급자별 예외는 실제 파싱·금융 식별에 필요한 최소 범위에 둔다.

- 조건·예외: 사용자 교정과 실제 증거로 규칙 개선 전후를 검증한다.
- 출처: `docs/specs/owner-product-decisions-20261028.md:12`, `docs/history/provisional-assignment-review-first-20261028.md:33`, `docs/history/provisional-assignment-review-first-20261028.md:86`

### PROC-065 · 원문이 바뀐 연결 보존

*보호 · 결정 2026-11-01*

원문·근거 변경 후에도 기존 수동 연결·검증된 exact 연결을 새 추론으로 덮지 않는다. stale 근거는 재검증하며 보고서 digest와 canonical 근거가 검증되는 기존 연결은 보존한다.

- 조건·예외: 개별 예약·거래 유일성을 모든 M:N 관계의 일반 성립 조건으로 만들지 않는다.
- 대체된 옛 규칙:
  - 각 이벤트와 거래의 유일한 연결만 pin합니다. — docs/history/ota-legacy.md:895
- 출처: `docs/specs/ota.md:14`, `docs/specs/ota.md:525`, `docs/history/ota-legacy.md:850`, `docs/history/ota-legacy.md:895`

### PROC-066 · 내부 자동 기록의 안전 경로

*일반 · 결정 2026-10-23*

분류 후 내부 기록이 승인되고 기존 보호 검사를 통과하면 기존 원자 미리보기·기록 경로와 거래 ID 중복 방지로 기록한다. 새 배치·옛 배치라는 이유만으로 처리 기준을 달리하지 않는다.

- 조건·예외: 분류 완료와 실제 기록 성공은 별도로 검증한다. 이미 기록된 행을 여행 검증 변경만으로 자동 이동하지 않는다.
- 대체된 옛 규칙:
  - OTA-first 연결이 확정되지 않은 OTA 카드 거래의 ota_authority_unresolved를 내부 기록의 일괄 차단 조건으로 둔다. — 2026-10-15, C:/Users/kkokk/.claude/projects/C--AX-cost/memory/feedback-classify-records-automatically.md:15
- 출처: `docs/specs/finance.md:135`, `docs/specs/finance.md:146`, `소유자 지시 메모:feedback-classify-records-automatically.md:11`, `소유자 지시 메모:feedback-classify-records-automatically.md:15`, `docs/specs/finance.md:148`

### PROC-067 · 가맹점별 재승인 금지

*사용자 예외 · 결정 2026-10-15*

승인된 Trip.com 예약·카드 처리 원칙을 적용할 때 가맹점 별칭이 달라졌다는 이유만으로 매번 승인을 받지 않는다. 기존 날짜·금액·후보 판정 규칙을 먼저 재사용한다.

- 조건·예외: 이 원칙만으로 금액 차이를 할인으로 확정하거나 정확 금융 연결 보호를 완화하지 않는다. 1,000원 단위 할인 언급은 단서이며 특정 거래의 할인 원인·금융 연결을 증명하지 않는다.
- 출처: `소유자 지시 메모:feedback-trip-no-per-merchant-approval.md:11`, `소유자 지시 메모:feedback-trip-no-per-merchant-approval.md:15`

### PROC-068 · 분기 검수로 교정

*일반 · 결정 2026-11-10*

정상 거래는 P1 또는 P2가 판정을 끝내며 사용자는 분기 검수에서 잘못된 귀속을 교정한다.

- 조건·예외: 검수가 자동 판정의 승인·확정 선행조건은 아니다.
- 대체된 옛 규칙:
  - 자동 배정 → 사용자가 월별로 장부를 확인하고 오류를 발견하면 수정. — 2026-10-14, C:/Users/kkokk/.claude/projects/C--AX-cost/memory/feedback-auto-assign-monthly-review.md:8
  - 자동 배정 후 월별 검토 (승인 대기 금지) — OTA 묶음·별칭을 승인받지 않고 자동 배정, 사용자는 월별 장부에서 수정. — 2026-10-14, C:/Users/kkokk/.claude/projects/C--AX-cost/memory/MEMORY.md:8
- 출처: `MERGE.md:20`

### PROC-069 · 세무 판단과 분류 분리

*일반 · 결정 2026-10-04*

부가세 신고 판단은 자동 비용 분류 완료의 선행조건으로 요구하지 않는다.

- 조건·예외: 세무 판단이 끝났다고 추론하거나 금융·세무 사실을 창작하지 않는다.
- 출처: `docs/specs/finance.md:250`

### PROC-070 · 비카드 특례 별도 검증

*보호 · 결정 2026-10-23*

캐시·포인트 등 비카드 비용은 해당 승인 특례를 별도로 검증한다.

- 조건·예외: 정상 카드의 여행 추론 계약만으로 비카드 비용의 금융 사실을 확정하지 않는다.
- 출처: `docs/specs/finance.md:113`, `docs/history/product-and-handoffs.md:98`

### PROC-071 · 검증된 결제 예정 예약 예외

*사용자 예외 · 결정 2026-10-16*

실제 카드 매입이 입증된 예정 결제는 최신 권한 스냅샷의 scheduled_card_ids와 승인된 전용 평가 조건을 만족하면 OTA 미해소 잠금을 통과시킬 수 있다.

- 조건·예외: 날짜·금액·카드 일치와 충돌 없음이 필요하며 일반 원본·중복·환불 보호를 해제하지 않는다.
- 출처: `docs/specs/ota.md:190`, `소유자 지시 메모:feedback-classify-records-automatically.md:15`
