# 판정 규칙 — 여행 귀속

> [판정 규칙집](../DECISION_POLICY.md)의 영역별 상세 규칙이다. 핵심 원칙과 읽는 법은 규칙집 본문에 있다.
> 규칙 ID는 바꾸지 않는다. 규칙을 고칠 때는 같은 ID의 내용을 고치고 옛 내용을 "대체된 옛 규칙"에 남긴다.
> "출처"의 파일과 줄 번호는 커밋 `b0340d0d`(2026-11-10) 기준이다. 그 뒤 줄어든 `AGENTS.md`·`docs/COST_V3_START_HERE.md`의 줄은 `git show b0340d0d:<경로>`로 본다. 그때의 `docs/specs/<파일>`은 지금 `docs/history/specs-20261110/<파일>`에 있다(절차서 두 개는 `docs/playbooks/`).

### TRIP-001 · 여행 생성 원천

*일반 · 결정 2026-10-13*

여행은 Google 스프레드시트의 실제 여행 탭에서만 만든다. 예약 시스템·보험 명단·지명·추론으로 새 여행이나 가짜 여행 ID를 만들지 않는다.

- 대체된 옛 규칙:
  - reserve에서 확보한 여행 목록과 해당 모집글의 전체 댓글 수를 읽는다. — 2026-10-03, docs/specs/finance.md:295
  - 답글·후기·완료 공지를 모집글로 사용하지 않는다. — 2026-10-03, docs/specs/finance.md:295
  - 댓글이 5개 이상이고 명시 출발일이 한국 날짜로 오늘 이후인 여행을 출발 예정으로 분류해 장부의 여행 목록에 등록한다. — 2026-10-03, docs/specs/finance.md:295
  - 같은 게시판과 같은 연도의 여행은 한 번만 등록한다. — 2026-10-03, docs/specs/finance.md:297
  - 그 밖에 3건
- 출처: `docs/specs/uiux-full-audit-redesign-20261110.md:76`, `docs/history/provisional-assignment-review-first-20261028.md:80`, `docs/specs/participant-income-authority-and-drag-link-20261028.md:24`, `docs/specs/trip-flight-booking-overview-20261028.md:23`, `docs/specs/refactor-master-20261027.md:302`

### TRIP-002 · 여행 제목과 연도

*일반*

연도와 명시 종료일은 Google 시트 최상단 제목에서, 시작일은 여행 탭 이름의 날짜에서 읽는다. 명시 종료일을 하루 줄이지 않는다.

- 조건·예외: 소유자가 별도 확정한 연도·일정 예외는 우선한다.
- 출처: `docs/specs/finance.md:246`, `소유자 지시 메모:trip-source-google-only.md:15`, `docs/history/product-and-handoffs.md:91`, `docs/specs/finance.md:106`, `docs/specs/finance.md:328`

### TRIP-003 · 종료일 없는 연속 여행

*일반*

종료일이 없거나 당일여행 표기인 여행은 다음 여행 시작일의 전날까지로 계산하며 명시 종료일과 같은 효력으로 검증한다. 다음 여행이 바뀌면 다시 계산하되 수동 종료일은 보존하고, 다음 여행이 없으면 종료일을 만들지 않는다.

- 조건·예외: 담당자와 연도별 범위 안에서 계산한다. 같은 시작일만 있는 경우에는 뒤의 서로 다른 시작일이 필요하다.
- 대체된 옛 규칙:
  - 야쿠시마(1127_야쿠시마_), 몽골(0712_몽골), 8월 북해도(0813_북해도)는 시트가 있으나 제목·헤더에 종료일이 없고 항공편 문구의 날짜뿐이라 추정하지 않는다. — 2026-10-09, docs/history/operations-through-20261027.md:1282
  - 몽골과 8월 북해도의 종료일도 아직 authoritative source로 확인하지 못했으므로 추정하지 않는다. — 2026-10-09, docs/history/operations-through-20261027.md:1291
  - 도고·야쿠시마처럼 보관 자료에도 명시 일정이 없거나 몽골·8월 북해도처럼 종료일 authority가 없는 경우에는 추정하지 않고 HOLD를 유지한다. — 2026-10-08, docs/specs/finance.md:219
- 출처: `docs/specs/trip-flight-booking-overview-20261028.md:48`, `AGENTS.md:45`, `소유자 지시 메모:owner-rules.md:3`, `소유자 지시 메모:owner-rules.md:9`, `소유자 지시 메모:trip-source-google-only.md:15`

### TRIP-004 · 담당자별 여행 식별

*일반 · 결정 2026-11-01*

여행 키와 연속기간 계산은 담당자·연도·원본 탭의 범위를 보존한다. 담당자 이름만으로 카드 전체를 같은 여행에 일괄 귀속하지 않는다.

- 출처: `docs/specs/andre-multi-owner-ledger-20261101.md:15`, `docs/specs/andre-multi-owner-ledger-20261101.md:16`, `docs/specs/andre-multi-owner-ledger-20261101.md:17`, `docs/specs/andre-multi-owner-ledger-20261101.md:22`

### TRIP-005 · Google 탭에 없는 기존 여행

*일반 · 결정 2026-11-11*

Google 탭에 연결되지 않은 기존 여행(예약 시스템 출처, 화면에서 수동 생성)은 같은 날짜·행선지의 Google 탭이 있으면 그 여행으로 합친다. 맞는 Google 탭이 없으면 거기 배정된 지출을 다시 판정한다(다른 실제 여행 또는 분기 기타비용).

- 조건·예외: 옛 여행 기록과 수정 이력은 지우지 않는다. 수동 교정으로 그 여행에 넣은 지출은 분기 검수 목록에 올리고 자동으로 옮기지 않는다. Google 탭에 없는 여행을 새 여행의 원천으로 쓰지 않는다.
- 코드와 다른 점: 운영 DB에 Google 연결이 없는 여행이 남아 있다. 합치기와 재판정은 M2에서 한다.
- 대체된 옛 규칙:
  - Google 연결이 없는 기존 여행은 사용자의 정리 결정이 있을 때까지 그대로 둔다. — 2026-11-10·11 사용자 결정으로 대체
- 출처: `소유자 지시 메모:trip-source-google-only.md:15`, `docs/specs/finance.md:297`

### TRIP-006 · 검증된 여행 조건

*보호*

자동 귀속은 유효한 식별자·일정과 Google 정본 매핑 또는 검증된 일정 권위 근거가 있는 실제 여행에만 한다. 삭제·보관·비활성·일정 충돌·역전·원천 불일치 여행은 후보에서 제외한다.

- 코드와 다른 점: app/trip_selection.py:40의 canonical_trip_periods는 형식·플래그를 검사하며 종료일이 여전히 없는 마지막 여행도 사전에 남긴다. 이 helper만으로 Google 원본·digest·종료일 완전 검증을 충족했다고 볼 수 없다.
- 출처: `docs/specs/ota.md:528`, `docs/specs/finance.md:244`, `docs/specs/finance.md:340`, `docs/specs/finance.md:342`, `docs/specs/finance.md:343`

### TRIP-007 · 일정 근거 재검증

*보호*

여행 권위와 원본 digest는 독립 분류·미리보기·기록 시점마다 다시 검증한다. 같은 요청 안에서만 검증 결과를 공유하며 원본 파일 변경 시 명시 일정도 재검증한다.

- 출처: `docs/history/operations-through-20261027.md:316`, `docs/history/operations-through-20261027.md:397`, `docs/history/ota-legacy.md:1378`, `docs/history/ota-legacy.md:124`, `docs/specs/finance.md:460`

### TRIP-008 · 일정 근거 재연결

*보호*

최신 원본의 같은 시트·같은 위치에 동일한 명시 연도·기간 제목이 있고 기존 권위와 충돌하지 않을 때만 근거 경로와 digest를 재연결한다. 제목 변경·삭제·이동·수식·근거 훼손이나 최신 시트 누락을 과거 사본으로 덮지 않는다.

- 조건·예외: 종료일 누락은 연속기간 규칙으로 해결할 수 있는 경우와 구분한다.
- 출처: `docs/history/operations-through-20261027.md:397`, `docs/specs/finance.md:215`, `docs/history/ota-legacy.md:1575`

### TRIP-009 · 여행 신원과 정본 매핑

*보호*

원본 파일·탭명과 회계 여행의 안정된 신원을 구분하며 이름 유사성이나 사본 표기만으로 여행을 합치지 않는다. 연도·매핑·원본 대응이 불명확하면 비교·집계 권위를 임의 확정하지 않는다.

- 출처: `docs/specs/sheet-manual-expense-dedup-20261029.md:28`, `docs/specs/insurance-participant-integration-20261028.md:128`, `docs/history/ota-legacy.md:476`, `docs/history/ota-legacy.md:504`, `docs/history/ota-legacy.md:505`

### TRIP-010 · 여행 마감 판정

*일반*

마감은 동일 실제 여행 시트가 메인에서 보관 장부로 이동하여 정상 조회된 사실로 판정한다. 종료일 경과·COST 분류 완료·TSV 복사는 마감 증거가 아니며 보관 스냅샷 실패·stale도 최신 마감으로 표시하지 않는다.

- 조건·예외: 동일 여행이 양쪽에 존재하는 경우에는 정본 중복 규칙을 함께 적용한다.
- 출처: `docs/specs/core-workflow-remaining-implementation-20261030.md:45`, `docs/history/ota-legacy.md:475`, `docs/history/ota-legacy.md:506`

### TRIP-011 · 메인·보관 중복 정본

*보호 · 결정 2026-10-11*

동일 회계 여행이 메인과 보관에 함께 있으면 메인을 기본 정본으로 선택하고 한 번만 집계한다. 사용자가 두 사본을 비교하여 정본을 조정할 수 있으며 선택·변경 이력을 보존하고 Google에는 쓰지 않는다.

- 출처: `docs/history/ota-legacy.md:475`, `docs/history/ota-legacy.md:506`, `docs/history/ota-legacy.md:541`, `docs/specs/google-ledger.md:350`, `docs/specs/google-ledger.md:355`

### TRIP-012 · 회계 분기 경계 예외

*사용자 예외 · 결정 2026-10-25*

소유자가 정한 회계 분기 경계에서는 2026년 아키타 여행을 2분기 마지막, 6월 말 출발 오제 여행을 3분기 첫 여행으로 취급한다. 출발일의 달력 분기로 회계 분기나 보관 원본을 기계 선택하지 않는다.

- 조건·예외: 이 여행의 회계 경계 예외를 일반 거래의 결제일 분기 계산으로 확대하지 않는다.
- 출처: `docs/history/product-and-handoffs.md:484`, `docs/history/product-and-handoffs.md:607`, `docs/specs/google-ledger.md:283`, `docs/specs/google-ledger.md:613`, `docs/specs/google-ledger.md:616`

### TRIP-013 · 템플릿 연도 예외

*사용자 예외 · 결정 2026-10-11*

소유자가 확인한 하쿠산·야쿠시마의 이듬해 출발 여행은 이전 연도 템플릿 문구가 남아 있어도 2027년 여행으로 취급한다. 다른 여행의 연도까지 같은 예외로 바꾸지 않는다.

- 출처: `docs/specs/google-ledger.md:286`

### TRIP-014 · 수동 귀속 최우선

*보호 · 결정 2026-10-23*

거래별 사용자의 실제 여행 이동·명시 귀속·수동 예외를 자동 추론보다 먼저 적용한다. 재수집·재대사·AI·미래 학습 규칙이 수동 귀속을 덮어쓰지 않으며 AI 실패도 저장된 이동을 취소하지 않는다.

- 출처: `docs/history/provisional-assignment-review-first-20261028.md:41`, `docs/history/provisional-assignment-review-first-20261028.md:81`, `docs/specs/trip-flight-booking-overview-20261028.md:183`, `docs/history/product-and-handoffs.md:790`, `docs/specs/refactor-master-20261027.md:302`

### TRIP-015 · 수동 이동 서버 검증

*보호*

여행 이동은 owner·same-origin/CSRF·실제 거래·유효 대상 여행·현재 revision·중복 요청키를 검증한 단일 감사 저장 경로로 수행한다. 원본 금액·날짜·ID와 금융 연결은 유지한다.

- 출처: `docs/specs/inline-bulk-expense-edit-20261102.md:14`, `docs/specs/inline-bulk-expense-edit-20261102.md:24`, `docs/history/product-and-handoffs.md:2021`, `docs/specs/refactor-master-20261027.md:107`, `docs/specs/ui.md:495`

### TRIP-016 · 수동 이동 즉시 반영

*일반*

사용자는 AI 응답이나 질문 답변을 기다리지 않고 거래를 다른 여행으로 이동할 수 있다. 저장 후 이전 목록·새 목록·합계를 갱신하고 이전 귀속·시각·근거를 남기며 실패 시 입력과 오류를 유지한다.

- 조건·예외: Google 복사 여부가 모호하면 중복 경고는 별도로 표시하며 내부 귀속 교정은 유지한다.
- 출처: `docs/specs/inline-bulk-expense-edit-20261102.md:14`, `docs/specs/participants.md:46`, `docs/specs/participants.md:53`, `docs/specs/participants.md:60`

### TRIP-017 · 소수 귀속 교정의 복구

*보호 · 결정 2026-10-29*

소수 거래의 여행·항목 교정은 revision·원자 저장·변경 전 값·교정 이력으로 되돌릴 수 있게 한다. 거래·기기록 장부·표시 행의 귀속을 함께 맞추되 단순 이동에 전체 백업·서버 중지를 반복하지 않는다.

- 출처: `AGENTS.md:31`, `docs/COST_V3_START_HERE.md:76`, `docs/history/operations-20261028-20261107.md:1288`, `docs/history/session_handoff-through-20261107.md:1120`, `docs/specs/finance.md:67`

### TRIP-018 · 대량 귀속 변경 안전 게이트

*보호 · 결정 2026-10-29*

대량 재처리·삭제·스키마/금융 원본 변경 등 이력만으로 복구하기 어려운 변경은 백업·별도 복원 검증·단일 작성자·원본/preview digest 대조·원자성·범위 밖 불변 확인을 거친다. 일반 코드 배포 권한을 실제 DB·금융·Google 쓰기로 확대하지 않는다.

- 출처: `AGENTS.md:41`, `AGENTS.md:62`, `docs/history/product-and-handoffs.md:1781`

### TRIP-019 · 일괄 여행 이동

*보호 · 결정 2026-11-02*

일괄 변경은 기본적으로 선택 거래의 여행만 바꾸고 항목·설명·금액·원본·예약/환불 링크를 유지한다. 서버가 전체 대상의 권한·revision·보호 조건을 확인하여 전부 성공 또는 전부 취소하고 멱등 요청키로 중복 적용을 막는다.

- 출처: `docs/specs/inline-bulk-expense-edit-20261102.md:19`, `docs/specs/inline-bulk-expense-edit-20261102.md:20`, `docs/specs/inline-bulk-expense-edit-20261102.md:25`

### TRIP-020 · 자동·수동 분류 완료

*일반 · 결정 2026-10-29*

유효한 항목·귀속·설명과 출처·근거를 저장하면 자동·수동 모두 분류 완료다. 낮은 신뢰도나 과거 잠정 표현을 이유로 완료를 취소하거나 별도 확정·승인 대기를 만들지 않는다.

- 대체된 옛 규칙:
  - OTA는 90일 경과 자동 숨김을 허용하지 않으며, 유효한 단서가 적어도 여행을 잠정 배정해 사용자가 검토·교정한다. — 2026-10-28, docs/COST_V3_START_HERE.md:48
  - 해결 가능한 보류는 근거가 적어도 최선 후보를 빠르게 잠정 배정한 다음 사용자가 검토해 교정하는 기존 제품 대원칙을 우선한다. — 2026-10-28, docs/history/provisional-assignment-review-first-20261028.md:8
  - 소수 근거에서도 우선 배정: 유효한 단일 최선 여행 후보가 있고 사용자 결정/금융 보호 충돌이 없으면 낮은 신뢰도라도 AUTO_PROVISIONAL로 배정한다. — 2026-10-28, docs/history/provisional-assignment-review-first-20261028.md:27
  - 사용자 검토 후 교정: 자동 배정은 확정이 아니라 검토 전 임시 판단. — 2026-10-28, docs/history/provisional-assignment-review-first-20261028.md:28
  - 그 밖에 14건
- 출처: `docs/history/operations-20261028-20261107.md:978`, `docs/history/provisional-assignment-review-first-20261028.md:3`, `docs/specs/card-upload-full-reconciliation-20261029.md:10`, `docs/specs/finance.md:91`, `docs/specs/finance.md:92`

### TRIP-021 · P1·P2 여행 판단

*일반 · 결정 2026-11-08*

기존 규칙과 코드로 먼저 처리하고 남은 분류는 P2가 관련 자료를 대조해 근거·불확실성과 함께 완료한다. 낮은 점수·추가 단서 부족·AI 실패/미설정을 사람의 분류 질문이나 작업함으로 전가하지 않는다.

- 대체된 옛 규칙:
  - 추천 금지, 근거대로 자동 배정 — 확인 대기 추천 대신 자동 배정 또는 미배정. — C:/Users/kkokk/.claude/projects/C--AX-cost/memory/MEMORY.md:7
  - Process the owner wants: 자동 배정 → 사용자가 월별로 장부를 확인하고 오류를 발견하면 수정. — C:/Users/kkokk/.claude/projects/C--AX-cost/memory/feedback-auto-assign-monthly-review.md:8
  - 근거가 없으면 미배정으로 둔다. — 2026-10-14, C:/Users/kkokk/.claude/projects/C--AX-cost/memory/feedback-no-recommendation.md:8
  - 여행을 추천한 뒤 소유자의 확정을 기다리는 흐름을 만들지 않는다. — 2026-10-14, C:/Users/kkokk/.claude/projects/C--AX-cost/memory/feedback-no-recommendation.md:8
  - 그 밖에 42건
- 출처: `AGENTS.md:40`, `AGENTS.md:41`, `AGENTS.md:43`, `docs/COST_V3_START_HERE.md:78`, `docs/history/ota-legacy.md:1690`

### TRIP-022 · 여행 후보 없음의 최종 귀속

*일반 · 결정 2026-11-08*

P1/P2가 실제 여행을 우선 평가한 뒤에도 해결되지 않는 정상 일반 비용은 원문 결제일, 없으면 유효한 매입일의 분기 기타비용으로 종결한다. 여행·분기를 창작하거나 날짜 오류를 오늘 날짜로 대체하지 않는다.

- 조건·예외: 원본 오류·날짜/금액 오류·중복·미해결 환불 등 내부 금융 안전 제약은 별도다.
- 대체된 옛 규칙:
  - 유효 여행이 없으면 여행을 창작하지 않고 비용 항목 분류만 완료한다. — 2026-10-29, docs/specs/finance.md:88
  - trip:<유효 여행> → ASSIGNED. — docs/specs/lean-card-ota-core-20261030.md:29
  - 실제 여행도 분기 탭도 아닌 빈 값/무효 ID → UNASSIGNED. — docs/specs/lean-card-ota-core-20261030.md:31
- 출처: `docs/specs/uiux-full-audit-redesign-20261110.md:77`, `AGENTS.md:5`, `docs/session_handoff.md:188`, `docs/specs/card-destination-only-ux-20261108.md:8`, `docs/specs/card-destination-only-ux-20261108.md:9`

### TRIP-023 · 폐지된 분류 대기 UI

*일반 · 결정 2026-11-10*

귀속 결과는 실제 여행 또는 분기 기타비용으로 보여 주며 사용자 작업함·질문 대기·보류 해제·미배정/미분류 상태·필터·카운터·배지·처리 CTA를 제공하지 않는다. 거래 상세 수정은 완료 귀속의 자율 교정이다.

- 대체된 옛 규칙:
  - 후보가 없으면 미분류 화면을 열고 명시적으로 선택한 여행은 유지한다. — 2026-11-05, docs/history/operations-20261028-20261107.md:178
  - 정상 환불 탭은 분류 완료이고 환불 선택값·미배정 필터도 일치한다. — 2026-10-29, docs/history/operations-20261028-20261107.md:960
  - 순액 0원 환불 묶음을 카드의 미배정보다 우선 표시·링크하고 미배정 필터/건수에서 제외한다. — 2026-10-29, docs/history/operations-20261028-20261107.md:1297
  - 카드 거래일과 OTA 이용기간을 각각 적용하며 미배정 집계·월 필터에서도 제외한다. — 2026-10-13, docs/history/operations-through-20261027.md:1037
  - 그 밖에 18건
- 출처: `docs/specs/card-destination-only-ux-20261108.md:7`, `docs/specs/card-destination-only-ux-20261108.md:9`, `docs/specs/card-destination-only-ux-20261108.md:14`, `docs/specs/finance.md:3`, `docs/specs/lean-card-ota-core-20261030.md:61`

### TRIP-024 · 원본 오류의 내부 차단

*보호 · 결정 2026-11-08*

원본·금액·날짜 오류, 파싱 충돌, 실제 중복·초과환불·미해결 금융 관계는 내부 안전 차단과 사실 기반 설명을 유지한다. 분류 종결만으로 가짜 분기·비용·금융 성공을 만들지 않는다.

- 출처: `docs/history/ota-legacy.md:1021`, `docs/specs/card-destination-only-ux-20261108.md:9`, `docs/specs/card-destination-only-ux-20261108.md:10`, `docs/specs/lean-card-ota-core-20261030.md:31`, `docs/specs/ota.md:88`

### TRIP-025 · 내부 안전 잠금 보존

*보호 · 결정 2026-11-08*

사용자 보류 UI는 폐지하되 transaction_review_holds 등 기존 내부 금융 안전 잠금·보호 데이터·감사 이력은 보존한다. 귀속 후보나 가져오기만으로 잠금·환불 보호를 해제하지 않는다.

- 대체된 옛 규칙:
  - 가져오기를 보류 해제로 해석하지 않으며 해제는 사용자가 명시적으로 수행한다. — 2026-10-08, docs/specs/finance.md:217
- 출처: `docs/history/session_handoff-through-20261107.md:210`, `docs/specs/finance.md:100`, `docs/history/product-and-handoffs.md:1100`, `docs/specs/finance.md:217`

### TRIP-026 · 독립 사실의 구분

*일반 · 결정 2026-11-08*

OTA 예약 관계·실제 카드 결제 검증·여행 귀속·COST 내부 기록·Google 반영·실제 은행 환급은 독립된 사실이다. 추론 귀속이나 예약 묶음이 다른 축의 금융 완료를 증명한다고 표시하지 않는다.

- 출처: `AGENTS.md:44`, `docs/history/implementation-and-audits.md:501`, `docs/history/product-and-handoffs.md:98`, `docs/history/product-and-handoffs.md:1880`, `docs/specs/card-upload-full-reconciliation-20261029.md:39`

### TRIP-027 · 정상 카드 내부 경비 준비

*보호 · 결정 2026-10-23*

금융상 유효한 실제 카드 매입이 유효 여행에 귀속되어 있으면 OTA EXACT/INFERRED/UNLINKED 차이나 예약번호·결제일 누락만으로 COST 내부 경비 준비·미리보기를 막지 않는다. 중복·원본 충돌·취소/환불·기기록 보호는 유지한다.

- 출처: `docs/history/product-and-handoffs.md:791`, `docs/history/operations-through-20261027.md:786`, `docs/specs/ota.md:527`, `docs/history/product-and-handoffs.md:1323`, `docs/specs/ota.md:225`

### TRIP-028 · 귀속 근거와 불확실성

*일반 · 결정 2026-10-29*

자동 귀속은 추론 출처·근거·신뢰도·날짜 거리·대안·정책/가중치 버전을 기록하고 수동 확정이나 실제 이용 사실로 위장하지 않는다. 같은 입력에는 입력 순서와 무관하게 같은 결과를 내며 오배정 교정률과 금융 보호를 함께 평가한다.

- 대체된 옛 규칙:
  - 여행 귀속: USER_ASSIGNED / AUTO_EVIDENCED / AUTO_INFERRED / NO_AUTHORIZED_TRIP; 낮은 추론도 유효 여행이 있으면 귀속; 수동 이동 절대 우선. — docs/specs/ota.md:82
- 출처: `docs/history/implementation-and-audits.md:532`, `docs/history/product-and-handoffs.md:105`, `docs/history/session_handoff-through-20261107.md:1006`, `docs/specs/finance.md:460`, `docs/specs/participants.md:98`

### TRIP-029 · 일반 카드 후보 순위

*일반 · 결정 2026-10-31 · 개정 2026-11-12 · 개정 2026-11-13(3분기 검수)*

기존 유효 귀속을 먼저 유지하고 새 일반 카드 추론은 국내외 적합성이 맞으며 카드 이용일을 포함하는 여행 안에서 사용 국가 일치(TRIP-044)·가맹점 지역명·수입-비용 차액을 이 순서로 비교한다. 어느 기간에도 들지 않으면 PROC-004의 결제일 분기 기타비용으로 끝낸다. 예약 이용기간·수동 교정·범위가 명시된 사용자 예외가 우선한다.

- 조건·예외: "기존 유효 귀속 유지"는 P1 재실행이 귀속을 흔들지 않게 하는 규칙이다. 분기 검수(PROC-068)에서는 폐지된 준비기간·날짜 근접 추론으로 붙은 귀속(카드 이용일이 여행 기간 밖인 일반 현장 지출)과 국내외·사용 국가가 맞지 않는 귀속을 현행 규칙으로 다시 판정한다. 준비 숙박 특례(TRIP-042), 예약 이용기간, 환불의 원결제 따르기, 사용자 예외는 그대로 둔다.
- 예 (2026년 3분기 검수): 여행 종료 다음 날 국내에서 쓴 식비·지하철, 출발 사흘 전 택시처럼 예약 근거 없이 날짜 근접만으로 여행에 붙어 있던 일반 지출을 결제일 분기 기타비용으로 교정했다.

- 대체된 옛 규칙:
  - 기존 유효 귀속을 먼저 유지하고 새 일반 카드 추론은 국내외 적합성이 맞으며 카드 이용일을 포함하는 여행 안에서 가맹점 지역명·수입-비용 차액을 비교한다. — 2026-11-12 (2026-11-13 3분기 검수에서 사용 국가 일치 순서와 검수 재판정 범위를 명시)
  - 기존 유효 귀속을 먼저 유지하고 새 추론은 실제 여행의 국내외 적합성·이용일과 일정 거리·가맹점 지역명·수입-비용 차액을 비교한다. 날짜 거리를 지역명보다 먼저 보며 준비기간 후보가 있으면 해당 다음 여행을 평가한다. — 소유자 결정 2026-11-12 밤으로 대체.
  - 2026-10-30 오분류 교정: 현지 카드 사용의 여행 후보는 기존의 명시 국가 목록에 맞는 여행이 있으면 그 범위에서 이용일과 여행 기간의 거리부터 비교한다. — 2026-10-29, docs/specs/finance.md:79
- 출처: `docs/history/implementation-and-audits.md:532`, `docs/specs/participants.md:96`, `docs/specs/finance.md:88`, `docs/specs/finance.md:100`, `app/automatic_classification.py:147`

### TRIP-030 · 일반 카드 동률 해소

*일반 · 결정 2026-10-29*

같은 조건의 실제 여행이 여러 개면 검증된 수입-비용 차액이 큰 여행을 우선하고, 그래도 같은 점수면 일정·안정된 여행 ID 순서로 하나를 고른다. AUTO_INFERRED/낮음과 동률 사유·당시 근거를 남기며 돈 부족을 이유로 비용을 재분배하지 않는다.

- 조건·예외 (2026-11-13 3분기 검수): "같은 조건"에는 국내외 구분과 사용 국가 일치(TRIP-044)가 들어간다. 사용 국가가 행선지와 맞는 여행과 맞지 않는 여행은 같은 조건이 아니므로 차액으로 비교하지 않는다.
- 대체된 옛 규칙:
  - 낮은 점수라도 유일한 최선 후보는 CLASSIFIED, 사실상 동률은 CONFLICT_REVIEW, 후보가 없으면 UNASSIGNED_NO_VALID_TRIP를 반환할 수 있으나, 이는 후보 평가 결과다. — 2026-10-29, docs/specs/finance.md:100
- 출처: `소유자 지시 메모:owner-rules.md:15`, `docs/history/product-and-handoffs.md:99`, `docs/history/product-and-handoffs.md:1341`, `docs/specs/finance.md:88`, `docs/specs/finance.md:100`

### TRIP-031 · 카드 이용일과 날짜 누락

*일반 · 결정 2026-10-29*

카드 여행 귀속일은 이용일, 없으면 승인일이며 매입일을 서비스 이용일로 바꾸지 않는다. 날짜 단서 없이 실제 여행을 추론할 때는 가장 최근 시작한 유효 여행을 약한 기본값으로 사용하고 원문 날짜는 그대로 둔다.

- 조건·예외: 분기 기타비용 계산만은 최신 정책이 유효한 매입일 대체를 허용한다. 날짜 자체가 오류인 원행은 내부 차단한다.
- 출처: `AGENTS.md:45`, `소유자 지시 메모:owner-rules.md:10`, `docs/history/product-and-handoffs.md:93`, `docs/specs/finance.md:88`, `docs/specs/finance.md:108`

### TRIP-032 · 빈 여행 복원

*일반 · 결정 2026-10-29*

빈 여행은 현재 장부의 유효 여행, 가장 최근 저장한 유효 여행, 기존 장부 기록의 유효 여행, 새 추론 순서로 복원한다. override·decided_at·기본 빈 값만으로 사용자의 미배정 의도를 추정하거나 과거 이력을 삭제·위조하지 않는다.

- 출처: `AGENTS.md:41`, `docs/history/operations-20261028-20261107.md:960`, `docs/history/operations-20261028-20261107.md:968`, `docs/history/session_handoff-through-20261107.md:1005`, `docs/history/session_handoff-through-20261107.md:1192`

### TRIP-033 · 기록된 자동 귀속 교정

*일반 · 결정 2026-11-03*

명시적인 카드 재분류에서 최신 중앙 대사의 원본 해시·유효 결제·이용기간·실제 여행을 검증하면 기기록 자동 추론 귀속만 예약 이용기간에 맞게 원자 교정한다. 수동 결정·수동 필드·owner 기장·금융 보호를 유지하고 단순 조회·재시작·무관한 가져오기는 이동하지 않는다.

- 조건·예외: 거래·장부·표시 귀속과 이력은 같은 트랜잭션에서 저장한다.
- 출처: `docs/history/session_handoff-through-20261107.md:401`, `docs/specs/recorded-booking-period-correction-20261103.md:9`, `docs/specs/recorded-booking-period-correction-20261103.md:11`, `docs/specs/remaining-acceptance-20261030.md:28`, `소유자 지시 메모:feedback-classify-records-automatically.md:15`

### TRIP-034 · 재시작과 기분류 유지

*일반 · 결정 2026-11-01*

분류 성공 뒤 내부 기록 전에 중단되면 저장된 항목·여행·강한 근거를 유지하고 기록만 재개한다. 재시작 때문에 이미 여행이 있는 과거 거래 전체를 재분류하지 않는다.

- 출처: `docs/history/operations-20261028-20261107.md:630`, `docs/specs/card-completion-recurrence-20261101.md:10`, `docs/specs/ota-missing-trip-completion-20261102.md:5`, `docs/specs/ota-missing-trip-completion-20261102.md:27`

### TRIP-035 · 조회·미리보기 무쓰기

*보호*

일반 조회·건수 집계·탭 이동·미리보기·선택 동작 자체는 귀속·금융·장부·Google을 변경하지 않는다. 쓰기는 승인된 요청과 단일 저장 경로에서만 수행하고 멱등성·revision·동시 실행 보호를 유지한다.

- 출처: `docs/specs/ui.md:522`, `docs/specs/ui.md:524`, `docs/specs/finance.md:146`, `docs/specs/flight-passenger-trip-grouping-20261105.md:8`

### TRIP-036 · 예약 이용기간 우선

*일반 · 결정 2026-10-29*

검증된 OTA 실제 이용기간이 있으면 카드 결제일·승인일 근접성보다 우선해 여행을 고른다. 저장된 여행 이름이나 과거 추론이 이용기간과 맞지 않으면 기간으로 다시 찾되 사용자 명시 귀속은 보존한다.

- 출처: `AGENTS.md:45`, `소유자 지시 메모:owner-rules.md:11`, `소유자 지시 메모:owner-rules.md:13`, `docs/history/implementation-and-audits.md:91`, `docs/history/product-and-handoffs.md:94`

### TRIP-037 · OTA 장부 날짜

*일반*

OTA 장부 날짜는 실제 이용일인 체크인·픽업·출발일을 사용하고 이용일이 없을 때만 결제일을 쓴다. 이미 기록한 장부 날짜는 이 규칙으로 소급 변경하지 않으며 같은 예약의 카드·캐시 부분은 같은 예약 참조로 묶어 보여 준다.

- 출처: `소유자 지시 메모:owner-rules.md:12`, `docs/specs/finance.md:110`

### TRIP-038 · 예약 이용기간 사실 보존

*보호*

이용기간 누락·시작일만 있는 안내·충돌은 미확인 부분을 그대로 남긴다. 결제일·가맹점 지명·파일명·보험 행사기간으로 실제 숙박일·퇴실일·항공 구간·새 여행을 만들지 않는다.

- 조건·예외: 정상 카드의 별도 여행 추론과 내부 준비는 막지 않으며 실제 이용 사실을 확정하지 않는다.
- 출처: `docs/specs/ota.md:22`, `docs/specs/ota.md:38`, `docs/specs/finance.md:246`, `docs/history/ota-legacy.md:1212`, `docs/specs/finance.md:327`

### TRIP-039 · 숙박 밤 경계

*일반*

숙박은 체크인일부터 체크아웃 전날까지의 밤으로 비교하고 여행의 밤은 시작일부터 종료일 전날까지다. 여행 시작일 체크아웃·종료일 체크인은 해당 여행 숙박 밤과 겹치지 않으며 전체 숙박 포함은 체크인≥시작일·체크아웃≤종료일이다.

- 출처: `docs/specs/finance.md:331`, `app/reconciliation.py:3`

### TRIP-040 · 항공 이용일 경계

*일반*

항공은 출발일과 도착일을 모두 이용일로 포함한다. 여행 종료일에 출발하는 귀국편은 그 여행과 겹치며 숙박 밤 계산을 항공 이용일 계산으로 재사용하지 않는다.

- 출처: `docs/specs/finance.md:332`

### TRIP-041 · 이용기간 여행 순위

*일반*

예약 이용기간 전체를 덮는 검증 여행을 먼저 고르고, 없으면 겹치는 숙박 밤 또는 항공 이용일이 가장 많은 여행, 그다음 수입-비용 차액이 큰 여행을 고른다. 개별 서비스의 내부 동률은 마지막 카드 완료 단계와 구분한다.

- 조건·예외: 금융상 정상 일반 카드의 최종 귀속은 별도의 결정적 동률 규칙과 분기 종결을 따른다.
- 코드와 다른 점: app/reconciliation.py:116의 stay_trip은 덮음/겹침/차액까지 동률이면 None을 반환한다. 이 내부 미선택 결과와 finance.md:88의 정상 카드 마지막 단계 일정·ID 선택은 계층을 구분해야 한다. 이번 읽기만으로 최종 사용자 화면에 대기가 남는다고 단정하지 않는다.
- 대체된 옛 규칙:
  - 겹침은 서비스 시작일과 여행 시작일 일치, 최근 여행 시작일, 늦은 종료일 순서이며 동률은 보류한다. — 2026-10-04, docs/specs/finance.md:244
- 출처: `docs/history/provisional-assignment-review-first-20261028.md:65`, `docs/specs/finance.md:352`, `docs/specs/participants.md:98`, `app/reconciliation.py:116`, `docs/specs/finance.md:244`

### TRIP-042 · 준비 숙박

*일반*

체크아웃이 다음 여행 시작일 이하이고 체크인이 직전 검증 여행 종료일 이후이며 어떤 여행과도 밤을 공유하지 않는 숙박은 가장 가까운 다음 여행의 준비 숙박으로 귀속한다. 간격 제한을 임의 추가하지 않는다.

- 조건·예외: 숙박 특례의 같은 시작일 동률은 내부에서 선택되지 않을 수 있으며 일반 카드 마지막 귀속은 별도 해소한다.
- 코드와 다른 점: app/reconciliation.py:106의 prep_trip 자체는 체크아웃 이후 가장 가까운 시작일만 확인하며 직전 여행 종료/밤 비중첩 조건은 함수 안에서 검사하지 않는다. 같은 시작일 후보가 여러 개면 None을 반환한다. 호출자와 마지막 카드 귀속 경로의 보완 여부는 이 입력으로 확정하지 않는다.
- 출처: `docs/specs/finance.md:112`, `docs/history/product-and-handoffs.md:2021`, `docs/history/product-and-handoffs.md:97`, `docs/specs/finance.md:333`, `docs/specs/participants.md:69`

### TRIP-043 · 모든 항목의 준비기간

*일반 · 결정 2026-11-01 · 개정 2026-11-12*

일반 준비기간 추론은 폐지한다. 예약 이용기간도 없고 카드 이용일이 어느 여행 기간에도 들지 않는 일반 지출은 결제일 분기 기타비용으로 끝낸다(PROC-004). 수동 교정·환불의 원결제 따르기·예약 이용기간 귀속·기간 내 카드 이용일 귀속·범위가 명시된 사용자 예외와 TRIP-042 준비 숙박 특례는 유지한다.

- 조건·예외: 지정 카드 국내 잔여 분기 규칙·기간 예외와 정상 원본·환불 보호를 유지한다.
- 대체된 옛 규칙:
  - 실제 이용기간·수동 귀속을 먼저 유지하고 같은 국내외 구분의 여행 안이면 기간 귀속을 유지한다. 여행 사이 빈 기간의 모든 카드 비용 항목은 가장 가까운 다음 검증 여행의 준비 비용으로 추론하고 그 근거를 남기며 여행 기간·원문 날짜를 늘리지 않는다. — 소유자 결정 2026-11-12 밤으로 대체.
  - 옛 규칙 출처: `docs/history/operations-20261028-20261107.md:621`, `docs/history/session_handoff-through-20261107.md:678`, `docs/specs/finance.md:112`, `docs/specs/finance.md:333`, `docs/specs/finance.md:629`
- 출처: 소유자 결정 2026-11-12 밤, `docs/DECISION_POLICY.md` §3.2·§6.1, `docs/policy/process.md` PROC-004.

### TRIP-044 · 국내외 구분

*일반 · 결정 2026-10-31 · 개정 2026-11-13(3분기 검수)*

현지 카드 사용은 국내와 해외를 구분하고 같은 구분의 검증 여행 기간을 우선한다. 카드 이용일을 포함하는 해외 여행이 여럿이면 거래의 사용 국가(국가 코드, 없으면 통화)가 행선지 국가와 같은 여행을 먼저 고르고, 그런 여행이 없거나 여럿일 때만 가맹점 지역명·수입-비용 차액(TRIP-029·TRIP-030)으로 넘어간다. 사용 국가가 맞는 여행이 없으면 사용 국가와 여행 국가는 달라도 되며 외화·해외 구분이 있으면 국가 코드가 없어도 해외 거래로 처리한다.

- 조건·예외: 국내 현장 거래를 해외 여행으로 넣지 않고 해외 현장 거래를 국내 여행으로 넣지 않는다. 맞는 구분의 여행이 그 날에 없으면 결제일 분기 기타비용으로 끝낸다(PROC-004). 검증된 예약 이용기간과 수동 예외가 우선한다. 예약·온라인·결제대행 거래에는 이 지역 필터를 적용하지 않는다(TRIP-045).
- 예 (2026년 3분기 검수): 기간이 겹치는 일본 여행과 싱가포르 여행이 있을 때 일본 가맹점의 엔화 현장 결제가 수입-비용 차액 기준으로 싱가포르 여행에 붙어 있었다. 사용 국가가 맞는 일본 여행으로 교정했다. 국내 여행 기간에 지정 카드로 쓴 위안화·달러 결제가 그 국내 여행에 붙어 있던 것은 분기 기타비용으로 교정했다.
- 대체된 옛 규칙:
  - 해외 거래의 사용 국가와 여행 국가는 달라도 되며 외화·해외 구분이 있으면 국가 코드가 없어도 해외 거래로 처리한다. — 2026-10-31 (기간이 겹치는 해외 여행 중 사용 국가가 맞는 여행이 따로 있을 때의 순서가 없어 2026-11-13 개정)
  - 편의점·마트: 실제 승인일과 원본 사용 국가가 검증된 여행 일정에 맞을 때 해당 여행의 식비로 분류한다. — 2026-10-03, docs/specs/finance.md:262
  - 업종을 모르는 현지 거래: 같은 국가의 명시 여행 기간에 사용한 거래는 현지경비로 제안한다. — 2026-10-03, docs/specs/finance.md:263
  - 저장된 가맹점 현지 사용 규칙 (travel_country): 카드 사용 국가와 날짜에 맞는 검증된 여행이 있으면 그 여행이다(retail_trip). — docs/specs/finance.md:355
  - 새 행선지는 현지 사용으로 배정되지 않는다. — docs/specs/finance.md:423
  - 그 밖에 2건
- 출처: `docs/history/operations-20261028-20261107.md:1334`, `docs/history/session_handoff-through-20261107.md:933`, `docs/specs/finance.md:627`, `docs/specs/finance.md:628`, `docs/specs/finance.md:629`

### TRIP-045 · 예약·온라인과 현지 사용 구분

*보호 · 결정 2026-10-31*

예약·온라인·PG 거래의 가맹점 국가나 결제일을 실제 이용국가·이용일로 해석하지 않는다. 예약 이용기간 검증을 먼저 하고 일반 현지 사용만 국내외 지역 필터를 적용한다.

- 대체된 옛 규칙:
  - 예약·온라인 결제는 현지 사용으로 보지 않고 booking_evidence_needed로 둔다. — docs/specs/finance.md:356
- 출처: `docs/specs/finance.md:273`, `app/trip_selection.py:80`, `docs/specs/finance.md:356`

### TRIP-046 · 가맹점 규칙과 거래 추론

*일반*

가맹점의 일반 항목 규칙만으로 미래 여행까지 복제하지 않는다. 거래의 명시 예약 귀속·검증 예약 증거·허용 범위 재사용 규칙을 먼저 적용하고 여행이 비어 있을 때만 약한 거래별 추론을 보완한다.

- 조건·예외: 수동 거래별 이동이 언제나 우선한다. 특정 공급자 이름만으로 상품 성격이나 실제 예약 신원을 확정하지 않는다.
- 출처: `docs/specs/participants.md:95`, `docs/history/ota-legacy.md:1344`, `docs/history/ota-legacy.md:590`, `docs/specs/finance.md:353`, `docs/specs/finance.md:354`

### TRIP-047 · 근거가 여럿일 때

*일반 · 결정 2026-11-11*

더 강한 근거가 있으면 약한 근거는 쓰지 않는다. 판정의 근거와 확신은 가장 강한 근거의 것만 적는다(예: 예약 메일의 이용기간이 있으면 업종·결제일 근접 추론은 적지 않는다). 서로 다른 항목·여행을 가리키는 근거가 충돌하면 강한 근거를 따르고 충돌이 있었다는 사실을 불확실성에 적는다.

- 조건·예외: 근거의 강약: 수동 교정 > 예약번호·원승인번호 같은 정확 근거 > 예약 이용기간 > 업종·가맹점 용도·날짜 근접 추론. 금융 원본·예약 신원·사용자 결정의 충돌 보호는 풀지 않는다.
- 대체된 옛 규칙:
  - 같은 결론의 근거가 여럿이면 보수적인(낮은) 확신을 고른다. — 2026-11-10·11 사용자 결정으로 대체
- 출처: `docs/specs/finance.md:351`, `docs/specs/finance.md:360`, `docs/history/operations-through-20261027.md:379`

### TRIP-048 · 취소·충돌 예약 근거 제외

*보호*

취소된 예약이나 실제 이용기간 누락·충돌·무겹침 근거를 실제 이용 여행의 확정 증거로 사용하지 않는다. 검증된 원결제 연결은 별도로 보존하고 철회된 예약 귀속·낡은 추론이 다시 활성화되지 않게 한다.

- 조건·예외: 정상 카드의 별도 공통 추론·분기 종결과 결제 대사 결과는 별개다.
- 출처: `docs/history/provisional-assignment-review-first-20261028.md:78`, `docs/specs/ota.md:721`, `docs/history/product-and-handoffs.md:2021`, `docs/specs/ota.md:613`, `docs/history/ota-legacy.md:1355`

### TRIP-049 · 묶음 여행과 예약 신원

*보호 · 결정 2026-11-01*

같은 날짜·정확 금액의 반복 결제 묶음이 같은 숙박 종류·이용기간이면 해당 여행의 비용 귀속을 정할 수 있으나 행마다 임의 예약번호를 배분하지 않는다. M:N 관계에서 다른 여행·기간 충돌이 있으면 여행 귀속을 별도 판단하고 실제 거래 다중도를 보존한다.

- 코드와 다른 점: docs/history/ota-legacy.md:1246은 포털 _identical_group_matches가 묶음에 행별 예약번호를 붙이는 과거 구현 차이를 보고한다. 현재 코드 실행 여부를 재검증한 사실로 보지 않는다.
- 대체된 옛 규칙:
  - 부분 묶음의 개별 여행 및 장부 배정은 구분 근거가 확보될 때까지 보류한다. — docs/history/ota-legacy.md:1007
  - 부분 묶음은 양쪽 건수와 ID 전체를 보존하고 개별 연결·장부 배정을 차단한다. — docs/history/ota-legacy.md:1038
- 출처: `docs/history/ota-legacy.md:1246`, `docs/specs/participants.md:241`, `docs/specs/finance.md:230`, `docs/specs/finance.md:236`, `docs/specs/finance.md:269`

### TRIP-050 · 환불의 귀속 상속

*보호 · 결정 2026-10-29*

정상 원결제에 검증 연결된 취소·부분환불은 원결제의 항목·여행을 따르고 원행·부호·금액·링크는 보존한다. 이미 있는 수동 환불 귀속은 덮지 않으며 한쪽이 내부 차단이면 묶음 기록도 원자 보호한다.

- 조건·예외: 예약 취소·여행 분리 결정이 있으면 실제 이용 여행에 되붙이지 않는다. 연결이나 분류 완료는 은행 환급 완료가 아니다.
- 출처: `docs/specs/finance.md:11`, `docs/specs/finance.md:89`, `docs/specs/finance.md:93`, `docs/specs/finance.md:217`, `docs/specs/finance.md:236`

### TRIP-051 · 환불 탭과 전액 취소 완료

*일반 · 결정 2026-10-29*

정상 환불 탭의 기존 귀속은 실제 여행으로 강제하지 않고 환불 탭으로 복원한다. 검증된 전액취소 쌍은 순액0의 분류 완료로 취급하며 별도 확정 버튼이나 실제 은행 환급 완료를 만들지 않는다.

- 조건·예외: 분기 기타비용으로 비용을 새로 생성하지 않으며 원결제·환불 원행은 보존한다.
- 출처: `docs/specs/finance.md:93`, `docs/specs/finance.md:95`, `docs/specs/finance.md:155`

### TRIP-052 · 캐시·포인트 비용

*보호*

예약의 캐시·포인트 사용분도 비용으로 기장하며 카드 결제 동반 여부로 제외하지 않는다. 취소·환불된 예약은 이 경로로 기장하지 않고 비카드의 별도 검증 조건을 적용한다.

- 출처: `docs/specs/finance.md:113`, `docs/history/product-and-handoffs.md:96`, `docs/specs/finance.md:111`

### TRIP-053 · 캐시 사용의 여행 검증

*보호*

캐시 사용분도 카드와 같은 과정으로 귀속한다(ITEM-019). 이용일을 덮는 검증 여행이 하나면 그 여행, 여럿이면 카드와 같은 동률 규칙(PROC-021)으로 하나를 고르고, 없으면 결제일 기준 분기 기타비용으로 끝낸다. 준비 숙박은 검증된 숙박 배정 경로를 사용하며 취소·환불 예약은 기장하지 않는다. 비카드 특례의 미충족을 일반 카드 귀속과 섞어 금융 성공으로 표시하지 않는다.

- 코드와 다른 점: app/ota_cash_use.py는 이용일을 덮는 여행이 여럿이면 목적지로 좁히거나 unclassified로 남기고, 없으면 준비 숙박 또는 unclassified로 남겨 PROC-021 동률 해소·분기 기타비용 종결과 다르다.
- 대체된 옛 규칙:
  - 캐시 사용분은 이용일을 덮는 검증 여행이 하나일 때만 그 여행으로 귀속한다(여럿·부재는 미배정). 카드용 분기 종결로 이 차이를 임의 해소하지 않는다. — 2026-11-11 ITEM-019 결정에 따라 대체(2026-11-13 정렬)
- 출처: `docs/specs/finance.md:111`, `app/ota_cash_use.py:95`

### TRIP-054 · 캐시 비용 환산

*일반*

자료에 원화 환산액이 있으면 그 금액을 쓰고 엔화만 있으면 100엔=1,000원 간편환율을 쓴다. 이 비용 환산을 카드와 예약의 정확 금액 결제 검증으로 사용하지 않는다.

- 조건·예외: 캐시·포인트 사용 비용에 한정한다.
- 출처: `docs/specs/finance.md:111`

### TRIP-055 · 대장 항공권 신원

*보호 · 결정 2026-10-10*

서명·출처가 검증된 메일/전자항공권의 실제 탑승자가 reservation의 active 대장 실명·항공권 영문명과 정확히 일치할 때만 대장 업무 항공권 후보로 본다. 부분 이름·한글 로마자 추정·단순 가맹점/목적지로 신원을 확정하지 않는다.

- 출처: `docs/history/ota-legacy.md:1529`, `docs/specs/finance.md:183`, `docs/specs/finance.md:196`, `docs/specs/finance.md:204`

### TRIP-056 · 대장 항공권 업무 목적

*보호 · 결정 2026-10-10*

대장 담당 실제 여행과 전체 항공 여정·공항·날짜·담당자를 대조해 사전 출국·귀국·여행 사이 포지셔닝·중도 합류/이탈의 업무 목적이 하나의 여행으로 설명될 때 귀속한다. 단순 직전/다음 여행 고정이나 날짜 근접만으로 정하지 않고 여행 기간을 늘리지 않는다.

- 조건·예외: 대장 항공료의 특수 증빙 게이트이며 일반 카드 최종 분류·고객 항공권 조회 projection과 구분한다.
- 출처: `docs/specs/finance.md:185`, `docs/specs/finance.md:187`, `docs/specs/finance.md:188`, `docs/specs/finance.md:189`, `docs/specs/finance.md:190`

### TRIP-057 · 대장 항공권 공항 대응

*보호 · 결정 2026-10-10*

대장 항공권 귀속은 검증된 공항·여행지 대응표에 있는 공항만 여행 destination과 대조하고 설정된 일정 간격 한도를 적용한다. 근거가 약하거나 대응표에 없는 공항은 임의 대응시키지 않는다.

- 출처: `docs/history/operations-through-20261027.md:1200`, `docs/specs/finance.md:205`

### TRIP-058 · 대장 여행 브리지

*보호 · 결정 2026-10-10*

대장 신원·담당 여행은 reservation이 정본이고 COST 회계 일정 권위는 COST가 유지한다. 등록 키 또는 여행 코드와 날짜의 정확·유일 대응으로만 브리지하며 제목·목적지·날짜 유사성만으로 연결하지 않는다.

- 조건·예외: 기존 reserve 식별자는 읽기 전용 대응 근거이며 새 COST 여행 생성 허가가 아니다.
- 출처: `docs/history/ota-legacy.md:1529`, `docs/specs/finance.md:207`, `docs/specs/finance.md:208`

### TRIP-059 · 대장 authority 신선도

*보호 · 결정 2026-10-10*

대장 항공권을 새로 귀속하거나 기록할 때 reservation authority가 이번 확인에서 fresh이고 마지막 성공이 90초 이내여야 한다. 기존 추론 행도 같은 여행·authority digest·신선 스냅샷을 다시 검증하며 10분 화면 표시 유예를 쓰기 권한으로 사용하지 않는다.

- 출처: `docs/history/ota-legacy.md:1533`, `docs/history/ota-legacy.md:1535`, `docs/specs/finance.md:208`

### TRIP-060 · 대장 항공권 혼합 운임

*보호 · 결정 2026-10-10*

대장 외 승객이 섞인 예약 전체 금액을 대장 비용으로 자동 귀속하지 않는다. 인별 운임이 확인되지 않으면 혼합 승객 보호, 확인되어도 카드 전체 한 행 기록 구조에서는 부분 운임 보호를 유지한다.

- 출처: `docs/specs/finance.md:196`, `docs/specs/finance.md:209`

### TRIP-061 · 대장 항공권 스냅샷

*보호 · 결정 2026-10-10*

신원·담당 여행·일정·메일·파서·공항표 입력 지문이 바뀌면 기존 대장 항공권 미리보기를 stale로 거부한다. 신선 스냅샷의 ATTRIBUTED만 카드 분류가 소비하고 결과에는 이름 대신 판정·여행·근거 해시를 남긴다.

- 출처: `docs/history/ota-legacy.md:1530`, `docs/specs/finance.md:206`

### TRIP-062 · 항공 예약 최초 출발 여행

*일반 · 결정 2026-10-28*

항공권 예약은 최초 실제 가는편 첫 구간의 출발 현지 일자를 기준으로 출발 여행 하나에 귀속한다. 연속 여행으로 귀국일이 첫 여행 종료일을 넘어도 예약 전체를 첫 출발 여행에 두고 귀국일·메일 수신일·결제일로 재선택하지 않는다.

- 예: 같은 예약으로 연속 두 여행을 이용해도 예약은 처음 출발한 여행 한 곳에만 보인다.
- 출처: `docs/specs/ota.md:8`, `docs/history/product-and-handoffs.md:1751`, `docs/specs/trip-flight-booking-overview-20261028.md:18`, `docs/specs/trip-flight-booking-overview-20261028.md:19`, `docs/specs/trip-flight-booking-overview-20261028.md:21`

### TRIP-063 · 항공 예약 귀속 우선순위

*일반 · 결정 2026-10-28*

항공권 목록의 여행 투영은 명시 사용자 예약 귀속, 검증된 예약↔카드/OTA 회계 여행, 검증된 대장 브리지, 최초 출발일·목적지 추론 순으로 재사용한다. 각 관계는 실제 공급자·예약 참조로 검증하고 금액 근접성만으로 PNR을 만들지 않는다.

- 조건·예외: 명확한 다음 여행 출국편이면 그 출발 여행이 우선하며 임의 ±N일 편의 규칙은 추가하지 않는다.
- 출처: `docs/specs/flight-passenger-trip-grouping-20261105.md:8`, `docs/specs/trip-flight-booking-overview-20261028.md:18`, `docs/specs/trip-flight-booking-overview-20261028.md:46`, `docs/specs/trip-flight-booking-overview-20261028.md:47`, `docs/specs/trip-flight-booking-overview-20261028.md:49`

### TRIP-064 · 항공 예약 여정 충돌

*보호 · 결정 2026-10-28*

항공 예약의 출발일 누락·여정/승객 구간 충돌·서로 다른 회계 여행 관계는 원본 검증 근거로 남긴다. 명시 사용자 귀속과 계산 출발일이 달라도 사용자 값을 자동 덮지 않으며 근거 부족을 실제 탑승·예약 확정으로 만들지 않는다.

- 조건·예외: 읽기 전용 항공 예약 관계 검증 결과이며 정상 카드에 폐지된 분류 대기 업무를 다시 만들지 않는다.
- 출처: `docs/specs/flight-passenger-trip-grouping-20261105.md:8`, `docs/specs/trip-flight-booking-overview-20261028.md:23`, `docs/specs/trip-flight-booking-overview-20261028.md:41`, `docs/specs/trip-flight-booking-overview-20261028.md:43`, `docs/specs/trip-flight-booking-overview-20261028.md:50`

### TRIP-065 · 항공권 조회와 회계 분리

*보호 · 결정 2026-10-28*

항공권 여행 조회·그룹 표시가 금융 거래·회계 분류·참가자 신원·Google 장부를 쓰거나 재기장하지 않는다. 항공권 예약 정보는 금액 합계·지출 TSV에 넣지 않고 예약번호별 한 번만 표시하며 다른 예약은 별개 평가한다.

- 출처: `docs/specs/flight-passenger-trip-grouping-20261105.md:7`, `docs/specs/trip-flight-booking-overview-20261028.md:20`, `docs/specs/trip-flight-booking-overview-20261028.md:22`, `docs/specs/trip-flight-booking-overview-20261028.md:37`, `docs/specs/trip-flight-booking-overview-20261028.md:87`

### TRIP-066 · 항공권 목록 페이지 일관성

*일반 · 결정 2026-11-05*

항공권 검색 결과는 현재 귀속 여행별 제목·건수·장부 링크로 묶고 여행명·귀속 근거 revision이 바뀌면 오래된 다음 페이지를 거부한다. 원본 읽기 실패를 예약 없음으로 표시하지 않는다.

- 출처: `docs/specs/flight-passenger-trip-grouping-20261105.md:9`

### TRIP-067 · 영수증 여행 선택

*보호*

영수증 등록에서는 사용자가 이번 영수증의 기존 여행을 직접 선택하며 AI가 여행명을 추론하지 않는다. 미선택·삭제·권한 없는 여행이면 저장·분류를 막고 선택 오류를 안내한다.

- 출처: `docs/specs/receipt-unified-upload-ux-20261105.md:26`, `docs/specs/receipts.md:32`

### TRIP-068 · 영수증 묶음

*보호*

영수증을 실제 한 결제로 묶을 때는 같은 여행·날짜·업체·통화·결제수단·확정 분류의 비용 후보를 사용자가 선택한다. 원본과 개별 금액을 남기고 묶음 해제가 가능해야 한다.

- 출처: `docs/specs/receipts.md:38`

### TRIP-069 · 제주 지정 카드 범위

*사용자 예외 · 결정 2026-11-03 · 개정 2026-11-12*

2026년 9월 9일 시작 제주 여행은 소유자가 지정한 카드 지출만 후보로 허용한다. 다른 카드는 예약 이용일·국내외·기간·동률의 현행 규칙으로 다시 고르며 지정 카드 전체를 제주로 강제하거나 다른 연도로 확대하지 않는다.

- 조건·예외: 이 예외는 기존 제주 귀속보다 우선해 여행만 교정하고 항목·설명·수동 결정 이력·원본·금액·금융 관계를 보존한다. 검증 연결된 취소/환불도 같은 여행으로 함께 이동한다.
- 대체된 옛 규칙:
  - 2026년 9월 9일 시작 제주 여행은 소유자가 지정한 카드 지출만 후보로 허용한다. 다른 카드는 예약 이용일·국내외·기간·준비기간·동률의 기존 규칙으로 다시 고르며 지정 카드 전체를 제주로 강제하거나 다른 연도로 확대하지 않는다. — 소유자 결정 2026-11-12 밤으로 대체.
- 출처: `docs/specs/finance.md:9`, `docs/specs/finance.md:10`, `docs/specs/finance.md:11`, `docs/specs/finance.md:12`, `docs/specs/jeju-ota-card-scope-20261103.md:3`

### TRIP-070 · 싱가포르 카드 기간 예외

*사용자 예외 · 결정 2026-10-12*

소유자 지정 카드의 2026년 9월 19~24일 거래는 등록 일정과 보존 지시가 일치하는 유효 싱가포르 여행이 하나일 때 그 여행으로 귀속한다. 이 기간에는 분기 잔여 비용보다 우선하되 다른 연도·카드·기간으로 확대하지 않는다.

- 조건·예외: 기존 항목을 유지하고 일반 사용내역의 항목이 없을 때 현지경비를 쓴다. 금융·원본·회사 제외 보호를 유지하며 이 예외 분류만으로 실제 기록·Google 쓰기를 실행하지 않는다.
- 출처: `docs/specs/finance.md:112`, `docs/history/session_handoff-through-20261107.md:1080`, `docs/specs/finance.md:164`, `docs/specs/finance.md:166`, `docs/specs/finance.md:357`

### TRIP-071 · 지정 카드 국내 잔여 비용

*사용자 예외 · 결정 2026-10-12 · 개정 2026-11-12*

소유자가 지정한 카드의 국내 잔여 정상 구매는 기존 대사·수동 결정·예약 이용기간·여행 규칙을 먼저 적용한 뒤 거래일의 연도·분기 기타비용으로 분류한다. 거래일이 없으면 유효한 매입일을 사용하고 날짜를 읽을 수 없으면 내부 안전 차단한다.

- 조건·예외: 싱가포르 기간 예외·해외 실제 여행 귀속은 보존한다. 일반 준비기간 추론은 TRIP-043 개정에 따라 폐지하며 명시된 준비 숙박 특례는 유지한다. 다른 카드나 기간으로 예외를 확대하지 않는다.
- 대체된 옛 규칙:
  - 조건·예외: 싱가포르 기간 예외·해외 실제 여행 및 준비기간 귀속은 별도로 보존한다. 다른 카드나 기간으로 예외를 확대하지 않는다. — 소유자 결정 2026-11-12 밤으로 대체.
- 출처: `docs/history/ota-legacy.md:172`, `docs/specs/finance.md:171`, `docs/specs/finance.md:173`, `docs/specs/finance.md:365`, `docs/specs/lean-card-ota-core-20261030.md:41`

### TRIP-072 · 후쿠타케 가맹점 예외

*사용자 예외 · 결정 2026-11-03*

FUKUTAKE FOUNDATION은 미술관 입장료이며 결제일인 이용일, 없으면 승인일 당일 또는 이후 출발하는 실제 세토우치 여행 중 가장 가까운 출발일에 귀속한다. 오늘·매입일·과거 동명 여행·다른 여행으로 대체하지 않는다.

- 조건·예외: 수동 교정·원본 충돌·중복·취소/환불 보호를 유지한다.
- 출처: `docs/specs/finance.md:261`, `app/trip_selection.py:10`

### TRIP-073 · 다이소 공통경비 예외

*사용자 예외 · 결정 2026-10-03*

아성다이소는 소유자 지정 일반 사무용품비·공통 경비로 분류하고 실제 여행으로 자동 귀속하지 않는다.

- 출처: `docs/specs/finance.md:265`

### TRIP-074 · 유럽 귀속 지역 예외

*사용자 예외 · 결정 2026-10-03*

소유자가 해당 배치에 지정한 조지아·카자흐스탄 현지 거래는 기존 유럽 여행에 귀속하는 원행별 예외로 처리한다. 원문 결제일·유럽 명시 일정은 유지하고 다른 연도·여행·미래 거래로 확대하지 않는다.

- 조건·예외: 예외 귀속은 실제 이용일·취소·실탑승·금융 결제를 확정하지 않는다.
- 출처: `docs/history/operations-through-20261027.md:304`, `docs/history/operations-through-20261027.md:316`, `docs/specs/finance.md:275`, `docs/specs/finance.md:290`

### TRIP-075 · 유럽 명시 일정 예외

*사용자 예외 · 결정 2026-10-03*

사용자 지시로 정한 기존 유럽 여행의 일정은 취소되지 않은 숙박 예약들의 명시 이용기간으로 확인하며 취소 숙박은 기간 산정에서 제외한다. 체크아웃은 하루 줄이지 않고 근거 원문·digest를 보존한다.

- 조건·예외: 기존 여행 일정에 관한 명시 예외이며 숙박 자료로 새 여행을 자동 생성하는 일반 규칙이 아니다.
- 출처: `docs/specs/finance.md:277`

### TRIP-076 · 산림치유원 귀속 예외

*사용자 예외 · 결정 2026-11-12*

소유자가 지정한 국립진안고원산림치유원 카드 결제 15건(예약 이용기간 2026-08-25~08-26)은 `0823_화순`에 귀속한다. 예약 기간과 카드 결제의 연결은 LINK-002로 별도 검증하며, 이 귀속 결정만으로 실제 결제·예약 유지·이용 완료를 만들지 않는다.

- 조건·예외: 해당 가맹점·배치의 사용자 결정이며 일반 숙박 증빙이나 다른 거래에 무제한 확장하지 않는다.
- 대체된 옛 규칙: 소유자가 지시한 해당 거래를 지리적으로 가까운 기존 호남 여행에 귀속한다. — 2026-11-09, 2026-11-12 소유자 결정으로 대체
- 출처: `docs/session_handoff.md:114`

### TRIP-077 · 일정 변경과 기존 여행 통합

*일반 · 결정 2026-10-29*

소유자가 같은 여행의 일정 변경이라고 설명하면 현재 Google 여행 탭과 제목 기간을 확인하고 현재 여행으로 귀속을 모은다. 이전 여행은 원본·교정 이력을 보존해 보관하고 이름 유사성만으로 다른 여행을 합치지 않는다.

- 출처: `docs/specs/finance.md:73`

### TRIP-078 · 분기 목적지 의미

*일반 · 결정 2026-11-08*

분기 기타비용은 실제 여행과 동등한 귀속 완료 목적지이며 실제 여행 ID로 위장하지 않는다. 원문 거래일의 연도·분기로 계산하고 분기 비용 구분을 여행 일정 근거로 사용하지 않는다.

- 출처: `docs/specs/lean-card-ota-core-20261030.md:23`, `docs/specs/lean-card-ota-core-20261030.md:30`, `docs/specs/core-workflow-remaining-implementation-20261030.md:44`, `docs/history/operations-through-20261027.md:1087`, `docs/specs/finance.md:173`

### TRIP-079 · 분기 표시와 공유 판정

*일반 · 결정 2026-11-10*

분기 귀속은 내부 ID 대신 연도·분기 기타비용 이름으로 표시하고 저장 ID는 보존한다. 카드 목록·상세·업로드 결과·장부는 같은 읽기 전용 귀속 판정을 사용하며 표시명 변경이 원행·귀속을 쓰지 않는다.

- 코드와 다른 점: lean-card-ota-core-20261030.md:17은 당시 completion_for_row/미배정 필터가 실여행 ID만 유효하게 취급할 수 있던 구현 차이를 지적한다. 이는 당시 진단이며 현재 코드의 미해결 결함으로 단정하지 않는다.
- 출처: `docs/specs/lean-card-ota-core-20261030.md:17`, `docs/specs/lean-card-ota-core-20261030.md:24`, `docs/specs/lean-card-ota-core-20261030.md:37`, `docs/specs/ui.md:109`, `docs/specs/ui.md:111`

### TRIP-080 · 귀속 표시 용어

*일반 · 결정 2026-11-10*

표시는 귀속과 여행, 출처는 자동/수동으로 표현하고 코드 추론·AI 추론의 세부 차이는 상세 근거에만 쓴다. 서버가 지원하지 않는 필터 값을 만들지 않으며 관계 필터를 카드 분류 대기 상태로 사용하지 않는다.

- 출처: `docs/specs/uiux-full-audit-redesign-20261110.md:212`, `docs/specs/uiux-full-audit-redesign-20261110.md:389`, `docs/specs/uiux-full-audit-redesign-20261110.md:395`, `docs/specs/uiux-full-audit-redesign-20261110.md:396`, `docs/specs/uiux-full-audit-redesign-20261110.md:574`

### TRIP-081 · Google 수동 복사 경계

*보호 · 결정 2026-11-08*

COST는 Google 최종 장부에 자동 쓰지 않으며 내부 귀속·비용 준비와 사용자의 Google 붙여넣기를 구분한다. 추정 예약번호는 Google 복사 예약번호 칸에 확정값으로 넣지 않고 중복 기록·정본 신선도·합계 검증을 유지한다.

- 출처: `docs/specs/ota.md:88`, `docs/specs/ota.md:249`, `docs/specs/participants.md:29`, `docs/specs/participants.md:60`, `docs/specs/recorded-booking-period-correction-20261103.md:11`

### TRIP-082 · 금융 원본·기존 관계 보존

*보호 · 결정 2026-11-08*

여행 귀속·UI·일반화 규칙은 원본 바이트·행·금액·통화·ID·승인번호·예약/환불 링크·수동 교정·감사 이력·권한·원자성을 바꾸지 않는다. 정상 원행의 다중도와 기기록 비용의 중복 방지를 유지한다.

- 조건·예외: 이미 승인된 명시 교정은 기존 보호 경로로만 수행한다. 사용자 확인·실제 환급·참가자 신원을 창작하지 않는다.
- 출처: `AGENTS.md:3`, `AGENTS.md:41`, `AGENTS.md:45`, `docs/history/ota-legacy.md:472`, `docs/history/product-and-handoffs.md:1452`

### TRIP-083 · 규칙 일반화 범위

*일반 · 결정 2026-10-29*

원행별 추론·교정을 무제한 일반화하거나 같은 상호라는 이유만으로 임의 여행 전체에 적용하지 않는다. 승인된 업무 계약 안의 반복 규칙 코드화·검증은 자율 수행하되 새 정책·권한 결정은 별도이며 적용 범위·예외·반례를 보존한다.

- 대체된 옛 규칙:
  - 자동 배정 후 월별 검토 (승인 대기 금지) — OTA 묶음·별칭을 승인받지 않고 자동 배정, 사용자는 월별 장부에서 수정. — C:/Users/kkokk/.claude/projects/C--AX-cost/memory/MEMORY.md:8
  - 트립닷컴 가맹점 승인 금지 (할인 단위 자동 배정) — 트립 결제는 가맹점별 별칭 승인 없이 날짜·금액·유일 후보로 배정 제안. — C:/Users/kkokk/.claude/projects/C--AX-cost/memory/MEMORY.md:9
  - 사용자 승인 전 일반화 규칙은 적용하지 않는다. — 2026-10-23, docs/history/product-and-handoffs.md:80
  - 이동 후 비동기 AI가 근거를 분석해 예상 답변 1/2, 직접 입력 3을 제시하고, 필요 시 추가 질문 후 미리보기 가능한 재사용 규칙을 제안한다. — 2026-10-23, docs/history/product-and-handoffs.md:80
  - 그 밖에 1건
- 출처: `소유자 지시 메모:feedback-trip-no-per-merchant-approval.md:11`, `소유자 지시 메모:feedback-trip-no-per-merchant-approval.md:15`, `docs/specs/google-ledger.md:94`, `docs/specs/google-ledger.md:150`, `docs/specs/participants.md:49`

### TRIP-084 · 자동 판단과 교정 학습 분리

*보호 · 결정 2026-10-29*

자동으로 추론한 여행·P2 결과는 사용자 답변이나 수동 교정 사례로 기록·학습하지 않는다. 명시 사용자 교정과 출처를 구분하고 단일 추론을 사실인 일반 규칙으로 승격하지 않는다.

- 출처: `docs/history/operations-20261028-20261107.md:960`, `docs/specs/finance.md:89`, `docs/specs/finance.md:91`

### TRIP-085 · 원행 추론의 범위

*보호 · 결정 2026-10-03*

거래별 추론 규칙은 현재 원행 hash·예약 이용기간 조건에 묶고 다른 날짜·금액·미래 거래로 자동 확대하지 않는다. 같은 사실의 재실행은 동일 귀속과 사용자 수정을 유지한다.

- 출처: `docs/history/ota-legacy.md:1252`, `docs/specs/finance.md:284`, `docs/specs/finance.md:286`

### TRIP-086 · AI 귀속 원자 적용

*보호 · 결정 2026-11-02*

P2는 제한된 기존 여행·항목 중에서 판단하고 원본/버전/문맥 digest와 실제 실행 메타데이터를 검증한 preview/apply 경로로 원자 적용한다. 코드 기본값을 AI가 검토했다고 표시하지 않는다.

- 출처: `docs/specs/unified-expense-action-queue-20261105.md:206`, `docs/specs/status-and-inference-stages-20261102.md:10`

### TRIP-087 · 과거 기간 동일 분류

*일반 · 결정 2026-10-29*

완료 자료의 귀속은 PROC-072를 먼저 적용한다. 완료 기간 여행에 이미 귀속된 완료 자료는 그대로 두며, 열린 여행의 근거 없는 귀속만 기존 분기 기타비용 구조로 정리한다. 그 밖의 과거 거래에는 일반 규칙을 적용한다.

- 대체된 옛 규칙 (2026-11-12 PROC-072):
  - 과거 거래도 일반 규칙·실제 근거로 검토하며 새 배치와 옛 배치를 구분하거나 preserved·완료기간만으로 분류·귀속 검토에서 제외하지 않는다. 명시 화면/전기 기간 필터는 보존한다.

- 대체된 옛 규칙:
  - 2025년과 2026년 1분기 자료는 이전 합의대로 원본을 보존하고 신규 카드·OTA 검토 목록과 미배정 집계에서 제외한다. — 2026-10-13, docs/specs/finance.md:159
  - 정리 완료 기간(review_from, 운영 2026-04-01) 이전 거래는 preserved로 두고 분류하지 않는다. — docs/specs/finance.md:350
- 출처: `docs/specs/finance.md:18`, `docs/history/session_handoff-through-20261107.md:1014`, `소유자 지시 메모:feedback-classify-records-automatically.md:15`, `docs/specs/finance.md:159`, `docs/specs/finance.md:350`

### TRIP-088 · OTA 오래된 예약 유지

*일반 · 결정 2026-10-28*

미해결 OTA 예약을 90일 경과만으로 자동 숨김·보관·완료 처리하지 않는다. 실제 귀속·금융 관계는 근거와 현재 규칙으로 판단한다.

- 출처: `docs/history/provisional-assignment-review-first-20261028.md:8`, `docs/specs/ota-review-queue-performance-20261027.md:22`

### TRIP-089 · 결제일 미상과 여행 증거

*보호 · 결정 2026-11-01*

결제일을 모르는 예약도 검증된 이용기간으로 여행 귀속만 판단할 수 있으며 원문 결제일은 공란을 유지한다. 결제일 없는 관계는 최신 M:N 계약을 따르고 예약 하나의 유일성을 일반 여행 귀속 전제로 강제하지 않는다.

- 코드와 다른 점: app/ota_inference.py:50과 config/ota-matching-defaults.json:57의 구형 Agoda 경로는 verified portal·상호 유일성·정확 끝자리/금액을 요구한다. 입력의 2026-11-01 M:N 최신 관계 계약을 이 구형 코드의 1:1 한도로 축소하지 않는다. 이 영역 입력만으로 새 M:N 경로 전체를 검증하지 않았다.
- 대체된 옛 규칙:
  - 결제일이 없는 다른 공급자와 조건 미달 거래는 종전 규칙대로 보류한다. — 2026-10-21, docs/specs/finance.md:338
  - 결제일이 없는 아고다 연결에 관한 2026-10-21 사용자 승인: 전체 자료에서 정확한 카드 끝자리·원문 금액으로 카드와 예약이 서로 유일하게 대응하고, 검증된 이용기간이 있으며 취소·환불·기간 충돌이 없으면 ota_inference.unique_pairs로 추론 연결한다. — 2026-10-21, docs/specs/finance.md:338
  - 기존 기록·사용자 결정·보류·점유된 카드는 제외하고, 기장된 카드도 유일성 검사에는 포함한다. — 2026-10-21, docs/specs/finance.md:338
  - 소유자의 규칙(docs/business_rules.md 81행, 119행)은 결제일 일치를 조건으로 하므로 근거가 없으면 배정할 수 없다. — C:/Users/kkokk/.claude/projects/C--AX-cost/memory/feedback-payment-date-evidence.md:13
  - 그 밖에 2건
- 출처: `docs/specs/ota-undated-many-to-many-20261101.md:15`, `docs/specs/ota.md:613`, `docs/specs/finance.md:338`, `app/ota_inference.py:50`, `config/ota-matching-defaults.json:57`

### TRIP-090 · 예약 자료 추가 조회

*보호*

카드 조회 시작일보다 예약 메일이 먼저 도착할 수 있으므로 필요한 예약 근거는 예약 참조로 날짜 제한 없이 보관 메일을 추가 대조한다. 이용기간 누락을 결제일로 채우지 않고 과거 조사 보고서를 권위로 자동 승격하지 않는다.

- 출처: `docs/history/operations-through-20261027.md:1318`, `docs/history/ota-legacy.md:1302`, `docs/history/ota-legacy.md:1366`, `docs/specs/finance.md:277`

### TRIP-091 · 일반 업무 공통경비

*일반*

구독·통신·사무용품·일반 업무 공통경비는 억지로 실제 여행에 넣지 않고 공통경비로 처리한다. 취소·환불은 원래 부호를 보존하고 일반 비용과 구분한다.

- 조건·예외: 정상 카드의 최종 표시 목적지는 유효한 분기 기타비용 규칙을 따른다.
- 출처: `docs/specs/finance.md:286`

### TRIP-092 · 여행 간 참가·수입 불이동

*보호 · 결정 2026-10-28*

같은 사람이 다른 여행에도 참여해도 여행별 참가·입금 관계를 독립 관리한다. 보험 명단이나 항공권 여행 투영 때문에 수입·보험·고객 신원을 다른 여행으로 자동 이동하거나 확정하지 않는다.

- 출처: `docs/specs/participant-income-authority-and-drag-link-20261028.md:150`, `docs/specs/participants.md:205`, `docs/specs/participants.md:420`

### TRIP-093 · 정상 거래 내부 자동 기록

*보호 · 결정 2026-10-13*

항목과 실제 여행 또는 분기 목적지가 정해지고 원본·중복·일정 권위·회사 제외·내부 잠금·OTA/환불 묶음 검사를 통과하면 승인된 owner 요청의 기존 경로에서 COST 내부 장부에 기록한다. 분류 저장과 내부 기록 가능 여부는 별개이며 조회 API나 Google 자동 쓰기로 확대하지 않는다.

- 조건·예외: 기록된 자동 귀속의 교정은 최신 명시 재분류 계약을 따르고 중복 전기는 금지한다.
- 출처: `docs/history/operations-20261028-20261107.md:978`, `docs/specs/finance.md:146`, `docs/specs/finance.md:236`

### TRIP-094 · 현장 결제 날짜 표시

*일반 · 결정 2026-11-10*

여행 시작 전날부터 여행 기간 안의 직접 숙박·렌터카 현장 결제는 카드 이용일 근거로 표시할 수 있으나 실제 숙박 일수는 추론하지 않는다. 예약·PG·국내 여행사·마켓·ARS·렌터카 중개 채널은 직접 현장 결제로 취급하지 않는다.

- 조건·예외: 이 표시 보완은 카드 원문 이용일을 고치거나 새 예약 이용기간·여행 귀속·금융 연결을 만드는 규칙이 아니다.
- 출처: `docs/session_handoff.md:14`, `docs/session_handoff.md:66`

### TRIP-095 · 완결 스냅샷 표시와 쓰기

*보호 · 결정 2026-11-10*

OTA 재계산 중에는 마지막 완결 세대의 이용일 표시를 유지할 수 있으나 쓰기·연결에는 계속 fresh 근거가 필요하다. 읽기 표시의 지속성을 새 귀속·기록 권한으로 간주하지 않는다.

- 출처: `docs/session_handoff.md:66`

### TRIP-096 · Google 실제 여행 비교 경계

*보호 · 결정 2026-10-30*

Google 지출과의 비교·중복 검사는 정본 매핑이 검증된 같은 실제 여행 안에서 수행한다. 분기 기타비용이나 귀속이 없는 행을 이름 유사성만으로 다른 여행으로 옮겨 비교하지 않는다.

- 출처: `docs/specs/google-expense-mn-reconciliation-20261030.md:11`, `docs/specs/sheet-manual-expense-dedup-20261029.md:28`

### TRIP-097 · 메일 취소 사실

*보호*

취소 완료 제목과 실제 취소 근거는 예약의 실제 이용 여행 증거에서 제외하되 단순 취소 정책 안내는 취소 완료로 보지 않는다. 메일만으로 실제 카드 환불 장부 행이나 은행 환급 완료를 만들지 않는다.

- 출처: `docs/history/ota-legacy.md:1364`

### TRIP-098 · 화순 여행 종료일

*사용자 예외 · 결정 2026-11-13*

2026년 8월 23일에 시작한 화순 여행(`0823_화순`)의 실제 종료일은 2026년 8월 26일이다. 8월 26일의 현지 지출은 이 여행의 비용이다. 2026-10-04 소유자 답변으로 만든 일정 증거의 8월 23~25일은 숙박 기간을 물은 것이었고 여행 기간으로는 이 결정이 대체한다.

- 조건·예외: 이 여행에만 적용한다. Google 여행 탭의 기간(제목에 종료일이 없어 지출 행에서 읽은 8월 26일)과 TRIP-003(종료일이 없으면 다음 여행 시작 전날까지)의 결과와 같다. 8월 26일 밤 숙박처럼 다음 여행의 준비 숙박(TRIP-042)으로 이미 귀속된 것은 옮기지 않는다. 지정 카드 잔여 규칙(TRIP-071)과 수동 교정은 그대로 우선한다.
- 코드와 다른 점: 운영 `trip_tabs`의 종료일은 아직 8월 25일이다. 여행 종료일을 바꾸는 정식 경로가 없다([코드와 규칙이 다른 곳](CODE_GAPS.md)). 판정과 분기 검수에서는 이 규칙의 8월 26일을 쓴다.
- 예 (2026년 3분기 검수): 8월 26일에 같은 지역에서 같은 카드로 쓴 식비·택시·관람료 16건을 기간 밖 지출로 옮기지 않고 이 여행에 뒀다.
- 출처: `2026-11-13 사용자 결정(3분기 AI 검수 질문 1)`, `docs/agents/artifacts/ai-quarter-review-2026Q3.md`
