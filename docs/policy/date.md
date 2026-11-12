# 판정 규칙 — 이용기간·날짜

> [판정 규칙집](../DECISION_POLICY.md)의 영역별 상세 규칙이다. 핵심 원칙과 읽는 법은 규칙집 본문에 있다.
> 규칙 ID는 바꾸지 않는다. 규칙을 고칠 때는 같은 ID의 내용을 고치고 옛 내용을 "대체된 옛 규칙"에 남긴다.
> "출처"의 파일과 줄 번호는 커밋 `b0340d0d`(2026-11-10) 기준이다. 그 뒤 줄어든 `AGENTS.md`·`docs/COST_V3_START_HERE.md`의 줄은 `git show b0340d0d:<경로>`로 본다. 그때의 `docs/specs/<파일>`은 지금 `docs/history/specs-20261110/<파일>`에 있다(절차서 두 개는 `docs/playbooks/`).

### DATE-001 · 여행 생성·연도 원천

*일반 · 결정 2026-10-23*

여행은 Google 시트 탭에서만 만들고 연도·명시 종료일은 시트 최상단 제목에서, 시작일은 탭의 날짜에서 읽는다. 다른 안내·보험·결제일·과거 사본으로 새 여행이나 일정을 만들지 않는다.

- 코드와 다른 점: app/google_authority.py:300은 제목 연도가 없으면 BASE_YEAR, 제목 종료일이 없으면 비용 행 기간의 최종 종료일을 읽는 것으로 추출됐다. 제목 원천과 다음 여행 전날 규칙 외의 fallback이어서 문서 규칙으로 승격하지 않는다.
- 대체된 옛 규칙:
  - 댓글 수와 미래 출발일에 따라 reserve 모집글에서 여행을 등록하던 과거 경로는 Google 탭만으로 만드는 최신 원천 계약으로 대체된다. — 2026-10-03, docs/specs/finance.md:295
  - 댓글 수와 미래 출발일에 따라 reserve 모집글에서 여행을 등록하던 과거 경로는 Google 탭만으로 만드는 최신 원천 계약으로 대체된다. — 2026-10-03, docs/specs/finance.md:297
  - 댓글 수와 미래 출발일에 따라 reserve 모집글에서 여행을 등록하던 과거 경로는 Google 탭만으로 만드는 최신 원천 계약으로 대체된다. — 2026-10-03, docs/specs/finance.md:297
- 출처: `docs/specs/finance.md:106`, `AGENTS.md:45`, `app/google_authority.py:300`, `소유자 지시 메모:trip-source-google-only.md:15`, `docs/history/product-and-handoffs.md:91`

### DATE-002 · 열린 종료일

*일반 · 결정 2026-10-23*

Google 제목에 종료일이 없으면 같은 범위의 다음 여행 시작일 전날을 종료일로 사용하고 명시 종료일과 같은 효력으로 검증한다. 다음 여행이 바뀌면 재계산하되 수동 종료일은 보존하고, 다음 여행도 없으면 종료일을 비워 검증 완료로 만들지 않는다.

- 대체된 옛 규칙:
  - 제목에 명시 종료일이 없다는 이유만으로 다음 여행 전날의 종료일까지 인정하지 않던 과거 차단은 열린 종료일 계약으로 대체된다. — 2026-10-09, docs/history/operations-through-20261027.md:1282
  - 제목에 명시 종료일이 없다는 이유만으로 다음 여행 전날의 종료일까지 인정하지 않던 과거 차단은 열린 종료일 계약으로 대체된다. — 2026-10-09, docs/history/operations-through-20261027.md:1291
  - 제목에 명시 종료일이 없다는 이유만으로 다음 여행 전날의 종료일까지 인정하지 않던 과거 차단은 열린 종료일 계약으로 대체된다. — 2026-10-08, docs/specs/finance.md:219
- 출처: `docs/specs/trip-flight-booking-overview-20261028.md:48`, `docs/specs/finance.md:107`, `소유자 지시 메모:owner-rules.md:3`, `app/reconciliation.py:40`, `docs/history/product-and-handoffs.md:92`

### DATE-003 · 담당자·연도 경계

*보호 · 개정 2026-11-12*

다음 여행을 이용하는 종료일 계산과 명시된 준비 숙박 특례는 같은 담당자와 연도 안에서 수행한다. 일반 준비기간 추론은 DATE-040에 따라 폐지한다. 같은 이름·일정이라도 담당자가 다르면 다른 여행이며 수동 담당자·종료일·정본 선택은 보존한다.


- 대체된 옛 규칙:
  - 다음 여행을 이용하는 종료일·준비기간 추론은 같은 담당자와 연도 안에서 수행한다. 같은 이름·일정이라도 담당자가 다르면 다른 여행이며 수동 담당자·종료일·정본 선택은 보존한다. — 소유자 결정 2026-11-12 밤으로 대체.
- 출처: `docs/specs/andre-multi-owner-ledger-20261101.md:17`, `docs/specs/andre-multi-owner-ledger-20261101.md:22`, `app/google_authority.py:581`

### DATE-004 · 여행 일정 권위 검증

*보호*

여행 배정에는 원천·연도·시작일·종료 의미·digest가 검증된 실제 여행만 사용한다. Google 연결 스냅샷의 기간 또는 검증된 일정 권한 기록과 일치해야 하며 명시 일정 충돌을 다른 근거로 덮지 않는다.

- 출처: `docs/history/product-and-handoffs.md:103`, `docs/history/operations-through-20261027.md:1291`, `docs/specs/finance.md:215`, `docs/history/operations-through-20261027.md:1372`, `docs/history/operations-through-20261027.md:397`

### DATE-005 · 과거 원본의 사용 한계

*보호*

최신 원본에 없는 여행 시트를 과거 사본으로 자동 복원하지 않는다. 원본 제목·위치·연도·기간의 동일성이 검증되는 범위에서만 근거 경로와 digest를 최신 원본에 연결한다.

- 출처: `docs/history/ota-legacy.md:1575`, `docs/specs/finance.md:215`

### DATE-006 · 외부 여행 브리지

*보호*

reservation 여행과 COST 회계 여행은 제목·목적지·날짜 유사성만으로 연결하지 않는다. 등록 식별자 또는 검증된 여행 코드와 정확한 일정이 일치하고 후보가 유일해야 한다.

- 출처: `docs/specs/finance.md:207`

### DATE-007 · 여행 마감의 업무 사건

*일반 · 결정 2026-10-11*

여행 마감은 Google 보관 장부에서 적법한 실제 여행 탭이 정상 확인될 때 판정한다. 종료일·회계 수식·분류 완료·TSV 복사만으로 마감하지 않고 식별이나 조회가 불확실하면 새 마감 판단을 하지 않는다.

- 출처: `docs/specs/core-workflow-remaining-implementation-20261030.md:45`, `docs/specs/google-ledger.md:175`, `docs/specs/google-ledger.md:346`, `docs/specs/google-ledger.md:430`, `docs/specs/google-ledger.md:348`

### DATE-008 · 마감 감지 시각

*보호 · 결정 2026-10-11*

동기화에서 보관 여행 탭을 처음 확인한 한국 시각은 마감 감지 시각으로 기록할 수 있다. 이를 Google에서 실제 이동한 정확한 시각으로 주장하지 않는다.

- 출처: `docs/specs/google-ledger.md:348`

### DATE-009 · 사용자 회계 분기 경계

*사용자 예외 · 결정 2026-10-25*

사용자가 지정한 여행의 회계 분기와 기존 자동·수동 보관 장부 mapping을 우선한다. 6월 말 출발해 7월로 이어지는 지정 여행을 출발일만으로 달력 2분기에 넣지 않는다.

- 예: 6월 말 출발해 7월까지 이어지는 지정 여행은 사용자 결정에 따라 회계상 3분기로 처리한다.
- 출처: `docs/history/product-and-handoffs.md:607`, `docs/specs/google-ledger.md:283`, `docs/specs/google-ledger.md:593`, `docs/history/product-and-handoffs.md:1051`, `docs/specs/google-ledger.md:697`

### DATE-010 · 비용 분기와 여행 일정 구별

*일반*

분기 기타비용 설명·복사 목적지는 원문 날짜의 연도와 분기를 기준으로 계산하되 여행 일정의 근거로 사용하지 않는다. 거래 날짜와 회계 여행의 사용자 분기 예외는 별개로 검증하고 화면 표기만으로 데이터를 고치지 않는다.

- 출처: `docs/specs/lean-card-ota-core-20261030.md:33`, `docs/history/operations-through-20261027.md:1087`, `docs/specs/finance.md:173`

### DATE-011 · 카드 여행 배정 날짜

*일반 · 결정 2026-10-23*

카드 여행 배정·대사 날짜는 원본 이용일을 우선하고 없으면 승인일을 쓴다. 매입일은 이 날짜의 대체값이 아니며 원본에 없는 이용일·승인일을 만들어 채우지 않는다.

- 대체된 옛 규칙:
  - 이용일·승인일이 없으면 매입일을 일반 카드 배정 날짜로 사용한다는 과거 UI fallback은 소유자의 매입일 배정 금지에 종속된다. — 2026-10-24, docs/history/implementation-and-audits.md:1401
- 출처: `docs/specs/finance.md:108`, `docs/specs/finance.md:324`, `docs/specs/finance.md:325`, `소유자 지시 메모:owner-rules.md:10`, `app/reconciliation.py:1`

### DATE-012 · 매입일의 처리 목적

*일반*

승인일이 없는 행은 허용된 처리 날짜로 매입일을 사용할 수 있지만 원본 승인일을 채우거나 카드 여행 배정·결제 대사 날짜로 승격하지 않는다. 분기 기타비용과 파일 공백 계산은 각각 명시된 별도 fallback을 따른다.

- 조건·예외: 처리 날짜·분기 계산·수집 공백 계산과 카드 이용일을 구분한다.
- 출처: `docs/history/ota-legacy.md:1203`

### DATE-013 · 카드 최종 분기 귀속

*일반 · 결정 2026-11-08*

P1/P2가 실제 여행을 우선 판단한 뒤 해소되지 않은 정상 일반 구매는 원문 결제일, 없으면 유효한 매입일의 해당 분기 기타비용으로 종결한다. 날짜 오류·미상은 내부 보호와 사실 설명을 남기며 오늘 날짜·가짜 분기·가짜 성공을 만들지 않는다.

- 대체된 옛 규칙:
  - 특정 카드 잔여 거래만 분기 기타비용으로 처리하고 날짜 해석 실패를 사용자 보류 업무로 남기던 계약은 정상 일반 비용의 최종 귀속과 내부 안전 차단으로 대체된다. — 2026-10-12, docs/specs/finance.md:171
- 출처: `docs/specs/card-destination-only-ux-20261108.md:8`, `docs/specs/card-destination-only-ux-20261108.md:9`, `docs/specs/review-all-uncommitted-release-20261108.md:10`, `AGENTS.md:5`, `app/quarter_costs.py:18`

### DATE-014 · 원문 날짜·금융 불변

*보호*

분류·추론·표시 보완은 원본 날짜·금액·통화·거래 ID·승인번호·금융 출처와 사용자 결정을 수정하지 않는다. 동일 원행은 보존하며 예약 관계·여행 귀속·기장·실제 환급·Google 반영을 구분한다.

- 출처: `docs/specs/upload-audit-recovery-20261105.md:4`, `docs/specs/recorded-booking-period-correction-20261103.md:11`, `docs/specs/python-refactor-followup-results-20261102.md:42`, `docs/specs/ota-undated-many-to-many-20261101.md:28`, `docs/specs/python-refactor-20261101.md:7`

### DATE-015 · 동일 날짜 복수 실거래

*보호 · 결정 2026-10-11*

날짜·가맹점·금액·카드가 같아도 다른 승인번호·원행 또는 실제 결제는 각각 보존한다. 날짜 일치만으로 사건을 병합하거나 여러 거래를 한 비용 행으로 합산하지 않는다.

- 출처: `docs/specs/inline-bulk-expense-edit-20261102.md:17`, `docs/specs/finance.md:69`, `docs/history/product-and-handoffs.md:1828`, `docs/specs/google-ledger.md:97`, `docs/specs/google-ledger.md:365`

### DATE-016 · 결제 사건의 안정 식별

*보호*

결제 사건 식별에는 검증된 공급자·계정·실제 결제 identity를 사용한다. 관측 시각·변동 금액·날짜·파일 경로만으로 동일 결제를 만들지 않고, 단일 결제가 증명되지 않는 복수 사건은 보존한다.

- 출처: `docs/history/implementation-and-audits.md:148`, `docs/history/ota-legacy.md:672`

### DATE-017 · 기간 근거의 변경 검증

*보호*

기간·예약번호·OTA 출처 근거는 원문 hash와 최신 digest/revision에 묶고 원천이 바뀌면 오래된 미리보기를 무효화한다. 동일 원행에 한정된 추론을 다른 날짜·금액·미래 거래로 일반화하지 않는다.

- 출처: `docs/history/operations-through-20261027.md:1526`, `docs/history/operations-through-20261027.md:1527`, `docs/specs/finance.md:284`, `docs/specs/finance.md:456`, `docs/specs/finance.md:466`

### DATE-018 · 수동 귀속과 날짜 보존

*보호*

유효한 수동 여행 교정·정본·종료일·원문 날짜는 자동 추론보다 우선한다. 저장된 유효 귀속을 재사용하고, 수동 이동은 이전 귀속·근거·시각을 남기며 금융 원행은 유지한다.

- 출처: `docs/specs/toyoko-collection-audit-20261103.md:12`, `docs/specs/finance.md:83`, `docs/specs/sheet-manual-expense-dedup-20261029.md:18`, `docs/specs/sheet-manual-expense-dedup-20261029.md:54`, `docs/history/operations-20261028-20261107.md:968`

### DATE-019 · 기장 날짜 보존

*보호*

이미 기장된 장부 날짜는 새 예약 근거·분류·원천 갱신만으로 자동 변경하지 않는다. 허용된 명시 재분류의 자동 추론 귀속 교정은 별도 보호 계약을 따른다.

- 출처: `docs/history/product-and-handoffs.md:95`, `docs/specs/finance.md:110`, `docs/specs/finance.md:338`

### DATE-020 · 기록된 자동 추론의 기간 교정

*일반*

명시 카드 재분류에서는 중앙 대사의 최신 원본 hash·유효 결제·이용기간·실제 여행이 검증되면 기록된 자동 추론 귀속을 예약 이용기간에 맞게 원자적으로 교정한다. 수동 결정·owner 기장·금융 보호·날짜 미상이나 다른 기간은 보존한다.

- 조건·예외: 자동 추론만 교정하며 원본 날짜·금액·금융 링크는 변경하지 않는다.
- 출처: `docs/specs/recorded-booking-period-correction-20261103.md:9`, `docs/history/session_handoff-through-20261107.md:401`, `docs/history/session_handoff-through-20261107.md:413`, `docs/history/operations-20261028-20261107.md:849`, `docs/history/session_handoff-through-20261107.md:1005`

### DATE-021 · OTA 결제 날짜의 근거

*일반*

OTA 실제 결제일은 인증된 결제 완료 메일의 한국 시간 발송일 또는 원문에 명시된 실제 청구일을 사용한다. 같은 결제일·금액 예약 묶음의 메일 기반 날짜는 서명 검증된 메일 발송일로 판단하고, 근거가 없으면 날짜를 비운 채 허용된 무날짜 연결을 평가한다.

- 조건·예외: 예약 확인·수신 시각을 일반 결제일로 바꾸지 않는다. 포털 명시 결제 정보와 카드 명세는 각각 검증 가능한 별도 근거다.
- 출처: `소유자 지시 메모:feedback-payment-date-evidence.md:3`, `소유자 지시 메모:MEMORY.md:12`, `소유자 지시 메모:feedback-payment-date-evidence.md:11`, `소유자 지시 메모:feedback-payment-date-evidence.md:15`, `docs/history/ota-legacy.md:677`

### DATE-022 · 결제일 대용 금지

*보호 · 결정 2026-10-16*

환불 불가 기한·취소 정책 날짜·결제기한·관측 시각·오늘 결제됨·투숙 완료·체크인·예약일·카드 매입일은 실제 OTA 결제일이 아니다. 원문에 결제일이 없으면 빈값을 유지한다.

- 출처: `docs/specs/ota.md:7`, `docs/history/operations-20261028-20261107.md:1017`, `docs/history/product-and-handoffs.md:327`, `docs/specs/ota.md:190`, `docs/specs/finance.md:271`

### DATE-023 · 동일일·동일통화 정확금액 연결

*일반 · 결정 2026-10-29*

검증된 결제의 실제 결제일과 카드 이용일이 같고 같은 통화의 원문 금액이 정확히 같으면 추가 카드 끝자리·결제 ID·승인 가맹점 별칭이 없다는 이유만으로 연결을 막지 않는다. 원문 충돌·중복·기존 수동 연결은 보호한다.

- 대체된 옛 규칙:
  - 동일 결제일·동일통화 정확금액 연결에 추가 카드/업체/별칭·유일한 1:1을 필수로 요구하던 부분은 2026-10-29 결정으로 대체된다. 실제 원문 충돌은 보호한다. — docs/history/ota-legacy.md:979
  - 동일 결제일·동일통화 정확금액 연결에 추가 카드/업체/별칭·유일한 1:1을 필수로 요구하던 부분은 2026-10-29 결정으로 대체된다. 실제 원문 충돌은 보호한다. — docs/history/ota-legacy.md:981
- 출처: `docs/specs/finance.md:69`, `docs/specs/ota.md:30`, `docs/history/session_handoff-through-20261107.md:1138`, `docs/history/ota-legacy.md:979`, `docs/history/ota-legacy.md:981`

### DATE-024 · 명시 결제일의 허용 차이

*일반 · 결정 2026-10-16*

명시 결제일이 있는 대사는 원화는 같은 날, 외화는 하루 이내 차이를 허용하고 그 밖의 차이는 승인된 업체별 날짜 방향·범위만 허용한다. 근사 환율·임의 날짜 확장으로 정확 연결을 만들지 않는다.

- 출처: `docs/history/ota-legacy.md:1219`, `docs/history/ota-legacy.md:976`, `docs/history/ota-legacy.md:977`, `docs/history/ota-legacy.md:1225`, `docs/history/ota-legacy.md:1353`

### DATE-025 · 승인된 날짜 차이 범위

*일반*

날짜 차이는 카드 날짜에서 OTA 결제일을 뺀 부호 있는 값으로 보존하고 승인된 최소~최대 범위의 양끝을 포함해 평가한다. 제공자·상품·가맹점/카드·통화·방향·적용 기간을 벗어나 규칙을 재사용하지 않는다.

- 조건·예외: 표시된 날짜·차액을 할인이나 결제 원인의 사실로 단정하지 않는다.
- 출처: `docs/history/ota-legacy.md:784`, `docs/history/ota-legacy.md:1098`, `docs/history/ota-legacy.md:1101`, `docs/specs/participants.md:241`, `docs/history/ota-legacy.md:710`

### DATE-026 · 무날짜 OTA M:N 연결

*일반 · 결정 2026-11-01*

결제일이 없어도 가맹점명/확장명·같은 통화의 정확 금액·카드 끝4가 일치하면 OTA↔카드 관계를 M:N으로 보존한다. 상호 유일성·양쪽 건수 동일을 요구하거나 개별 예약 하나를 임의 선택하지 않고, 원문 날짜는 공란으로 유지한다.

- 대체된 옛 규칙:
  - 실제 결제일이 없다는 이유만으로 카드 후보·관계를 일괄 차단하던 계약은 조건을 갖춘 무날짜 M:N 연결 범위에서 폐지됐다. — C:/Users/kkokk/.claude/projects/C--AX-cost/memory/feedback-payment-date-evidence.md:13
  - 실제 결제일이 없다는 이유만으로 카드 후보·관계를 일괄 차단하던 계약은 조건을 갖춘 무날짜 M:N 연결 범위에서 폐지됐다. — C:/Users/kkokk/.claude/projects/C--AX-cost/memory/web-ledger-release-cutover.md:67
  - 실제 결제일이 없다는 이유만으로 카드 후보·관계를 일괄 차단하던 계약은 조건을 갖춘 무날짜 M:N 연결 범위에서 폐지됐다. — 2026-10-22, docs/history/implementation-and-audits.md:674
  - 실제 결제일이 없다는 이유만으로 카드 후보·관계를 일괄 차단하던 계약은 조건을 갖춘 무날짜 M:N 연결 범위에서 폐지됐다. — 2026-10-22, docs/history/operations-through-20261027.md:866
  - 그 밖에 17건
- 출처: `docs/specs/ota-undated-many-to-many-20261101.md:7`, `docs/specs/ota-undated-many-to-many-20261101.md:15`, `docs/specs/ota-undated-many-to-many-20261101.md:28`, `AGENTS.md:35`, `docs/specs/ota.md:14`

### DATE-027 · 무날짜 후보 검색 경계

*일반*

OTA 또는 카드 결제일이 없어도 정확 금액·통화·끝4·가맹점 등의 근거로 후보를 검색할 수 있다. 날짜는 UNKNOWN으로 남기고 명시 불일치와 구별하며 설정·인덱스 범위 안에서만 탐색한다.

- 조건·예외: 전체 기간의 무제한 조합이나 날짜 없는 할인 차액의 정확금액 승격은 금지한다.
- 출처: `docs/specs/ota.md:209`, `docs/specs/ota.md:213`

### DATE-028 · 무날짜 정확금액 보호

*보호 · 결정 2026-11-01*

무날짜 연결은 원문 통화와 금액의 정확 일치를 요구한다. 할인 차액이나 다른 통화를 같은 금액으로 승격하지 않고 관계 연결만으로 개별 예약 결제·금융 배분·기장·환급을 확정하지 않는다.

- 출처: `docs/specs/ota-undated-many-to-many-20261101.md:28`, `docs/specs/ota-undated-many-to-many-20261101.md:33`, `docs/specs/participants.md:241`

### DATE-029 · 예정일 대사 소유자 예외

*사용자 예외 · 결정 2026-10-16*

Agoda 자동결제 예정 예약의 예정일과 카드 이용일이 같고 원문 총액·카드 끝자리·가맹점이 일치하며 예약과 원행이 일대일이고 취소·환불·다른 점유가 없으면 승인된 예정일 대사를 인정한다. 예약 이용기간으로 여행을 별도 판단한다.

- 출처: `docs/history/ota-legacy.md:1267`, `소유자 지시 메모:project-agoda-scheduled-charge-rows.md:11`, `소유자 지시 메모:project-agoda-scheduled-charge-rows.md:17`, `소유자 지시 메모:web-ledger-release-cutover.md:79`, `docs/specs/finance.md:257`

### DATE-030 · 예정과 실제 결제의 구분

*보호*

자동결제 예정일·PayLaterInfo 존재는 청구 완료가 아니다. 실제 카드 거래로 별도 검증된 예정일 대사도 예정일 근거를 표시하며 결제 완료 영수증이나 환급 증거라고 부르지 않는다.

- 조건·예외: API에서 청구일이 제공되지 않으면 결제일을 비운다. 포털 수집 절차의 상호유일 추론 서술은 소유자의 M:N 관계 계약을 일반적으로 폐지하지 않는다.
- 출처: `docs/specs/ota-portal-browser-collection-20261110.md:32`, `docs/history/ota-legacy.md:1344`

### DATE-031 · 직접 결제의 증명과 예약 상태

*보호*

예약 확정·예정·사전승인은 실제 결제 완료와 구분한다. 명시 결제일 충돌·검증 실패를 결제 완료로 승격하지 않으며 항공 결제는 인증 원문에 명시된 결제 사실을 따른다.

- 출처: `docs/specs/airline-mail-collection-20261105.md:6`, `docs/specs/finance.md:71`, `docs/specs/ota-review-queue-performance-20261027.md:114`, `docs/specs/ota.md:523`, `docs/history/operations-through-20261027.md:866`

### DATE-032 · 정상 카드의 독립 비용 준비

*보호 · 결정 2026-10-23*

정상 카드가 유효한 실제 여행에 배정됐다면 OTA 결제일 누락·정확 예약번호 매칭 실패·추정 상태만으로 내부 비용 준비를 막지 않는다. 중복·원본 충돌·미해결 취소/환불 보호를 유지하고 추정 예약번호는 확정값으로 내보내지 않는다.

- 대체된 옛 규칙:
  - 불균형 그룹이라는 이유만으로 카드↔예약 관계를 보류하던 부분은 2026-11-01 M:N 계약으로 대체된다. 원본·환불 보호와 개별 결제 사실의 분리는 유지한다. — 2026-10-23, docs/history/product-and-handoffs.md:1323
- 출처: `docs/history/implementation-and-audits.md:922`, `docs/specs/ota.md:245`, `docs/specs/participants.md:29`, `docs/history/product-and-handoffs.md:73`, `docs/history/product-and-handoffs.md:1273`

### DATE-033 · OTA 여행 판단은 이용기간 우선

*일반 · 결정 2026-10-23*

예약 이용기간이 있으면 카드·OTA 결제일의 근접성보다 먼저 그 기간의 실제 여행을 판단한다. 카드 결제일을 체크인·픽업·출발일로 저장하거나 알려진 예약 기간을 다른 달의 결제일 추론으로 덮지 않는다.

- 대체된 옛 규칙:
  - 결제일만으로 어떤 여행 추론도 불가능하다는 일괄 해석은 정상 카드의 약한 추론 허용으로 대체된다. 결제일이 예약 이용일을 증명하지 못한다는 보호는 유지한다. — 2026-10-20, docs/history/implementation-and-audits.md:593
- 출처: `docs/specs/finance.md:79`, `docs/history/provisional-assignment-review-first-20261028.md:65`, `docs/specs/ota.md:528`, `AGENTS.md:45`, `docs/specs/finance.md:286`

### DATE-034 · OTA 장부 날짜

*일반 · 결정 2026-10-23*

새 OTA 예약 비용의 장부 날짜는 체크인·픽업·출발 이용일을 우선하고 이용일이 없을 때만 결제일을 사용한다. 같은 예약의 카드 부분과 캐시 부분은 예약 단위 근거를 보존해 함께 식별한다.

- 출처: `소유자 지시 메모:owner-rules.md:12`, `app/reconciliation.py:27`, `docs/history/product-and-handoffs.md:95`, `app/ota_cash_use.py:91`, `app/reconciliation.py:28`

### DATE-035 · 캐시·포인트 이용일 귀속

*일반*

캐시·포인트 비용은 이용일 기준으로 기장하고 취소·환불 예약은 기장하지 않는다. 유일한 검증 여행이 이용일을 덮으면 그 여행을 사용하며, 복수·부재 상황의 적용 순서는 아래 충돌을 해소하기 전 임의 확정하지 않는다.

- 참고: 귀속 방법은 ITEM의 "캐시·포인트 지출의 귀속" 규칙을 따른다(카드와 같은 과정).
- 조건·예외: 비카드 캐시·포인트 특례.
- 대체된 옛 규칙:
  - 캐시 비용의 이용일을 덮는 여행이 하나면 그 여행에 두고 없거나 복수이면 미배정으로 둔다는 과거 표현 중 사용자에게 미배정 상태를 보여 주는 부분은 폐지됐다. 비카드 귀속 검증 자체는 보존한다. — 2026-10-23, docs/history/product-and-handoffs.md:96
  - 캐시 비용의 이용일을 덮는 여행이 하나면 그 여행에 두고 없거나 복수이면 미배정으로 둔다는 과거 표현 중 사용자에게 미배정 상태를 보여 주는 부분은 폐지됐다. 비카드 귀속 검증 자체는 보존한다. — docs/specs/finance.md:111
- 출처: `docs/history/product-and-handoffs.md:96`, `app/ota_cash_use.py:3`, `docs/specs/finance.md:410`, `docs/specs/finance.md:111`

### DATE-036 · 숙박 원문과 밤의 경계

*일반*

체크인·체크아웃 원문 날짜와 여행 제목 종료일은 그대로 보존한다. 숙박 겹침·밤수는 체크인 포함, 체크아웃 제외로 계산하므로 여행 종료일 체크인과 시작일 체크아웃은 그 여행과 겹치지 않는다.

- 조건·예외: 여행 종료일은 마지막 이용일을 포함하되 숙박의 체크아웃 날에는 새 숙박 밤을 더하지 않는다. 코드의 인접 여행 경계 밤 계산도 원문 체크아웃 날짜를 하루 줄이는 근거로 쓰지 않는다.
- 출처: `docs/history/ota-legacy.md:1355`, `docs/specs/finance.md:277`, `docs/specs/finance.md:328`, `docs/specs/finance.md:331`, `app/reconciliation.py:6`

### DATE-037 · 항공 이용일 양끝

*일반*

항공은 실제 출발일과 도착일을 모두 이용일로 보고 여행 종료일 출발 귀국편도 해당 여행과 겹치는 것으로 판단한다. 숙박의 체크아웃 제외·밤수 계산을 항공에 재사용하지 않는다.

- 출처: `docs/specs/finance.md:332`, `docs/specs/finance.md:333`, `소유자 지시 메모:web-ledger-release-cutover.md:45`

### DATE-038 · 숙박 여행의 우선순위

*일반 · 결정 2026-10-23*

취소되지 않은 예약은 확정 메일 여부와 무관하게 검증된 이용기간으로 여행을 배정한다. 전체 기간을 덮는 여행, 겹치는 밤 수, 수입-비용 차액 순으로 고르고 숙박의 최종 동률은 기존 보호 규칙을 따른다.

- 조건·예외: 카드 최종 귀속은 이후 최선 실제 여행 규칙으로 끝내며, 숙박 core 동률 결과를 사용자 분류 대기 상태로 노출하지 않는다.
- 대체된 옛 규칙:
  - 확정 예약만 자동 배정하고 결제 후 30일을 넘으면 추론 배정을 중단하던 제한은 observed 예약의 기간 배정과 거리 제한 제거로 대체된다. — C:/Users/kkokk/.claude/projects/C--AX-cost/memory/web-ledger-release-cutover.md:49
  - 서비스 시작일 일치·최근 시작일·늦은 종료일을 일반 우선순위로 쓰던 과거 규칙은 현행 기간 포함·공유 밤·차액 우선순위에 종속된다. — 2026-10-04, docs/specs/finance.md:244
- 출처: `docs/specs/finance.md:352`, `docs/specs/finance.md:372`, `app/reconciliation.py:119`, `소유자 지시 메모:web-ledger-release-cutover.md:49`, `docs/specs/finance.md:244`

### DATE-039 · 준비 숙박

*일반*

어느 여행과도 밤을 공유하지 않는 숙박은 체크아웃이 다음 여행 시작일 이하이고 체크인이 직전 검증 여행 종료일 이후이면 가장 가까운 다음 여행의 준비 숙박으로 판단한다. 기간 제한은 두지 않고 숙박 동률 보호는 유지한다.

- 조건·예외: 항공을 숙박처럼 다음 여행으로 이월하지 않으며 실제 이용기간·수동 배정·금융 보호가 우선한다.
- 대체된 옛 규칙:
  - 숙박의 core 동률 보호는 유지하지만 그 결과를 카드 사용자에게 미배정·질문 대기 업무로 보여 주는 표현은 폐지됐다. — 2026-10-23, docs/history/product-and-handoffs.md:97
  - 숙박의 core 동률 보호는 유지하지만 그 결과를 카드 사용자에게 미배정·질문 대기 업무로 보여 주는 표현은 폐지됐다. — docs/specs/finance.md:333
- 출처: `docs/specs/finance.md:112`, `docs/history/product-and-handoffs.md:97`, `docs/specs/finance.md:409`, `app/reconciliation.py:130`, `docs/specs/finance.md:333`

### DATE-040 · 모든 비용의 준비기간

*일반 · 결정 2026-11-01 · 개정 2026-11-12*

일반 준비기간 추론은 폐지한다. 예약 이용기간이 없고 카드 이용일이 어느 여행 기간에도 들지 않는 일반 지출은 결제일이 속한 분기 기타비용으로 끝낸다(PROC-004). 실제 예약 이용기간·수동 교정·환불 원결제·명시된 사용자 예외와 DATE-039 준비 숙박 특례는 그 범위 안에서 유지한다.

- 조건·예외: 숙박은 기존 밤 단위 조건과 동률 보호를 유지하며 카드 잔여 분기·사용자 국가 예외도 보존한다.
- 대체된 옛 규칙:
  - 같은 국내·해외 구분의 검증 여행 사이 빈 기간의 카드 비용은 항목에 관계없이 가장 가까운 다음 여행의 준비 비용으로 추론한다. 실제 예약 이용기간·수동 배정이 우선하고 카드 원문 날짜나 여행 종료일을 늘리지 않는다. — 소유자 결정 2026-11-12 밤으로 대체.
  - 옛 규칙 출처: `docs/specs/finance.md:112`, `docs/specs/python-refactor-20261101.md:7`, `docs/history/operations-20261028-20261107.md:621`, `docs/specs/finance.md:333`, `docs/specs/finance.md:629`
- 출처: 소유자 결정 2026-11-12 밤, `docs/DECISION_POLICY.md` §3.2·§6.1, `docs/policy/process.md` PROC-004.

### DATE-041 · 현지 사용의 날짜 판단

*일반*

현지 카드 사용은 검증된 사용 국가와 실제 이용일의 여행 기간 거리를 지역명보다 먼저 평가한다. 같은 날짜에 두 여행이 닿으면 수입-비용 차액 등 승인된 근거를 사용하고, 예약·온라인·PG 결제를 현지 사용으로 바꾸지 않는다.

- 조건·예외: 지명이 같다는 이유로 수개월 전 여행을 우선하지 않는다.
- 출처: `docs/history/session_handoff-through-20261107.md:933`, `docs/history/operations-20261028-20261107.md:1310`, `docs/specs/finance.md:79`, `docs/specs/finance.md:262`, `docs/specs/finance.md:273`

### DATE-042 · 약한 카드 추론의 완료

*일반 · 결정 2026-10-29*

금융적으로 정상인 카드 비용은 근거가 약하거나 날짜 거리가 멀어도 기존 유효 귀속을 우선하고 최선의 실제 여행에 AUTO_INFERRED로 배정해 근거·신뢰도·날짜 거리를 남긴다. 날짜 단서가 없으면 승인된 실제 여행 기본값을 사용하고 원문 이용일을 만들지 않는다.

- 대체된 옛 규칙:
  - 단서가 약하거나 후보 동점이라는 이유로 정상 카드의 귀속을 미배정·잠정 승인·사용자 질문 대기 상태에 남기던 절차는 최선 실제 여행의 완료 귀속으로 대체된다. — 2026-10-19, docs/history/operations-through-20261027.md:998
  - 단서가 약하거나 후보 동점이라는 이유로 정상 카드의 귀속을 미배정·잠정 승인·사용자 질문 대기 상태에 남기던 절차는 최선 실제 여행의 완료 귀속으로 대체된다. — 2026-10-13, docs/history/operations-through-20261027.md:1043
  - 단서가 약하거나 후보 동점이라는 이유로 정상 카드의 귀속을 미배정·잠정 승인·사용자 질문 대기 상태에 남기던 절차는 최선 실제 여행의 완료 귀속으로 대체된다. — 2026-10-12, docs/history/ota-legacy.md:150
  - 단서가 약하거나 후보 동점이라는 이유로 정상 카드의 귀속을 미배정·잠정 승인·사용자 질문 대기 상태에 남기던 절차는 최선 실제 여행의 완료 귀속으로 대체된다. — docs/history/provisional-assignment-review-first-20261028.md:45
  - 그 밖에 1건
- 출처: `docs/specs/finance.md:83`, `docs/specs/finance.md:88`, `소유자 지시 메모:owner-rules.md:13`, `docs/specs/finance.md:100`, `docs/history/session_handoff-through-20261107.md:1006`

### DATE-043 · 저장된 기간 추론의 유효성

*보호*

저장된 여행 이름의 규칙도 현재 검증된 예약 이용기간과 겹쳐야 사용하고, 이름 변경·잘못된 기존 추론은 기간으로 다시 찾는다. 취소·기간 충돌·맞는 여행 없음·수동 배정·철회된 예약 규칙은 근거에서 제외한다.

- 조건·예외: 사용자 국가 예외와 활성 수동 예약 귀속은 보존한다. 유효한 저장 추론은 결제일과 여행 시작일의 거리를 제한하지 않는다.
- 출처: `docs/specs/remaining-acceptance-20261030.md:28`, `docs/history/product-and-handoffs.md:2021`, `docs/history/ota-legacy.md:1378`, `docs/specs/finance.md:362`, `docs/specs/finance.md:363`

### DATE-044 · 공통 숙박기간의 제안

*일반*

같은 결제일·금액의 숙박 후보들이 같은 유효 이용기간을 가리키면 공통 기간과 후보 수를 보존할 수 있다. 특정 예약번호를 임의로 고르거나 공통기간만으로 개별 예약 결제·장부 날짜를 확정하지 않는다.

- 조건·예외: 기간 불일치·관련 취소 후보는 공통기간 근거를 무효화한다. M:N 관계 성립과 개별 기간 메타데이터의 보호는 별개다.
- 코드와 다른 점: tests/card_pipeline/test_same_day_lodging_group.py:59는 레거시 카드 수>예약 수이면 공통기간을 제공하지 않는다고 기대한다. 최신 문서는 건수 차이만으로 관계를 끊지 말라고 하므로, 관계는 유지하고 기간 제안 경로의 추가 제약으로 분리해 검토해야 한다.
- 출처: `docs/specs/ota-undated-many-to-many-20261101.md:15`, `docs/history/ota-legacy.md:1382`, `docs/specs/finance.md:230`, `app/ota_mail.py:493`, `tests/card_pipeline/test_same_day_lodging_group.py:59`

### DATE-045 · 취소와 기간 충돌 보호

*보호*

같은 예약의 이용기간이 충돌하면 첫 메일이나 과거 추론을 임의 선택하지 않고 해당 기간을 여행 근거로 사용하지 않는다. 취소·환불 관측은 날짜가 달라도 관련 active 공통기간을 막되 검증된 원결제 관계와 원문 관측은 보존한다.

- 대체된 옛 규칙:
  - 기간 불일치의 보호는 유지하지만 카드의 복수 여행 후보를 사용자 동률 검토·질문 대기에 남기는 절차는 폐지됐다. — 2026-10-28, docs/specs/ota.md:721
  - 기간 불일치의 보호는 유지하지만 카드의 복수 여행 후보를 사용자 동률 검토·질문 대기에 남기는 절차는 폐지됐다. — 2026-10-28, docs/specs/ota.md:721
- 출처: `docs/history/session_handoff-through-20261107.md:1134`, `docs/specs/ota.md:721`, `docs/history/product-and-handoffs.md:327`, `docs/specs/finance.md:363`, `app/ota_mail.py:747`

### DATE-046 · 동일 예약의 기간 보완

*일반*

기간이 없는 결제 관측은 같은 공급자·예약번호의 인증된 단일 유효 예약기간으로 보완할 수 있다. 다른 예약·기존 기간·취소·환불·원문/digest 충돌·낡은 링크는 보존하고 기간을 결제일로 대체하지 않는다.

- 조건·예외: M:N 표시 보완은 모든 관련 관측의 완전한 기간이 같아야 하며 개별 금융 배분을 주장하지 않는다.
- 출처: `docs/specs/ledger-service-date-investigation-20261109.md:28`, `docs/history/implementation-and-audits.md:403`, `docs/history/operations-through-20261027.md:1496`, `docs/history/operations-through-20261027.md:1527`, `docs/history/operations-through-20261027.md:1368`

### DATE-047 · 수집된 예약의 기간 검증

*보호*

포털·메일의 예약 식별·이용기간·실제 결제액·카드 관찰·상태와 원문 hash를 각각 검증한다. 예약 생성일·결제일·이용기간이 다르므로 체크인 날짜나 고정 결제 선행기간만으로 대상 수집을 제외하지 않는다.

- 출처: `docs/history/provisional-assignment-review-first-20261028.md:71`, `docs/specs/finance.md:203`, `docs/history/ota-legacy.md:1370`, `docs/history/ota-legacy.md:1380`, `docs/history/ota-legacy.md:1384`

### DATE-048 · 특정 지역의 미래 여행 귀속

*사용자 예외 · 결정 2026-10-03*

지정 FUKUTAKE 비용은 이용일, 없으면 승인일 당일 또는 이후 출발하는 실제 세토우치 여행 중 출발일이 가장 가까운 여행으로 귀속한다. 오늘 날짜·매입일·과거 여행·다른 지역 여행으로 대체하지 않는다.

- 출처: `docs/specs/finance.md:261`

### DATE-049 · 지정 항공료 이용일

*사용자 예외 · 결정 2026-10-03*

지정 여행사 항공료의 이용일은 인증된 skyticket 구매 완료 메일의 명시 출발일로 판단한다. 결제일·수신일을 출발일로 바꾸지 않고 원문 카드와 결제 근거를 별도로 검증한다.

- 출처: `docs/specs/finance.md:266`, `docs/specs/finance.md:269`

### DATE-050 · 사용자 국가·기간 예외

*사용자 예외 · 결정 2026-10-03*

사용자가 특정 해외 거래를 기존 다른 지역 여행에 배정한 예외는 보존한다. 그 여행의 명시 숙박 일정과 원문 결제일을 바꾸지 않고 다른 연도·미래 거래로 일반화하지 않는다.

- 출처: `docs/specs/finance.md:290`

### DATE-051 · 환불의 선후 날짜

*일반 · 결정 2026-10-16*

승인번호가 없는 해외 취소는 같은 카드·가맹점·원문 통화·외화 금액의 앞선 구매를 승인된 최대 기간 안에서 찾고, 반복되면 날짜순으로 구매 하나와 취소 하나씩 대응시킨다.

- 조건·예외: 해당 승인번호 없는 취소 경로의 최대 기간은 설정상 365일이며 원승인번호로 검증된 별도 1:N 연결에 이 기간을 확대 적용하지 않는다.
- 출처: `docs/specs/finance.md:141`, `docs/specs/finance.md:563`, `소유자 지시 메모:web-ledger-release-cutover.md:75`

### DATE-052 · 원승인번호 환불의 날짜 창

*보호*

같은 카드·발급사의 원승인번호로 검증된 환불 연결에는 가맹점명 동일이나 14일 진단 창을 필수로 추가하지 않는다. 날짜·동액/이액의 검토 순서만으로 실제 환급·가승인 해제를 확정하지 않는다.

- 출처: `docs/history/product-and-handoffs.md:309`, `docs/history/product-and-handoffs.md:654`

### DATE-053 · 승인번호 없는 동일일 환불

*일반 · 결정 2026-10-29*

원승인번호가 없어도 같은 발급사·카드·가맹점·이용일·정확 원화 금액의 양수·음수 원행이 상호 유일하게 대응하면 취소·환불 쌍으로 연결한다. 실제 은행 환급은 별도 사실이다.

- 출처: `docs/specs/finance.md:61`, `docs/history/operations-20261028-20261107.md:1304`, `docs/history/session_handoff-through-20261107.md:1087`

### DATE-054 · 2025년 취소 분류 예외

> PROC-072의 하위 사례다. 카드 완료 기간 제외는 목록 필터가 아니라 판정 진입 조건이며, 확정 근거 예외와 기존 완료 여행 보존이 우선한다.

*사용자 예외 · 결정 2026-10-16*

소유자가 지정한 2025년 취소의 연도는 취소 이용일, 없으면 매입일로 판단해 지정 과거 항목으로 묶는다. 이 과거 예외를 일반 카드의 여행 배정 날짜나 매입일 대사 허용으로 확대하지 않는다.

- 조건·예외: 해당 과거 취소의 상태·원금·날짜·여행과 원거래 항목은 보존한다.
- 출처: `소유자 지시 메모:project-2025-unpaired-cancels.md:11`, `소유자 지시 메모:project-2025-unpaired-cancels.md:15`

### DATE-055 · 매입 자료 수집 범위

*일반*

국민 매입 자료는 매입일 기준으로 조회하고 기간 갱신 때 겹치는 구간을 다시 검증한다. 지연 매입·취소의 원거래가 빠졌으면 더 넓은 매입 기간을 조회하며 원승인일이 조회 범위 밖이라는 이유로 매입 행을 버리지 않는다.

- 조건·예외: 조회 가능 최대 기간·최종 종료일은 실제 카드사 화면에서 확인한다. 과거 특정 재다운로드 범위는 일반 기간 규칙으로 복제하지 않는다.
- 출처: `docs/specs/finance.md:551`, `docs/specs/finance.md:555`, `소유자 지시 메모:project-2025-unpaired-cancels.md:17`, `소유자 지시 메모:project-2025-unpaired-cancels.md:21`

### DATE-056 · 승인 전용 파일 거절

*보호 · 결정 2026-10-08*

매입 확정이 필요한 가져오기 경로에서 승인방식 열만 있고 매입일 열이 없는 승인내역 XLS는 승인 전용 파일로 거절하고 이력만 보존한다. 원본에 없는 매입일을 이용일로 합성하지 않는다.

- 출처: `docs/history/operations-through-20261027.md:1136`, `docs/specs/finance.md:490`

### DATE-057 · 가짜 매입일 충돌의 판별

*보호*

기존 parser가 이용일을 매입일로 대체한 사실은 원본 bytes의 hash·행 source_hash·실제 헤더로만 증명한다. 발급사·카드·승인번호·이용일·금액을 함께 검증하고 실제 명시 날짜·복수 원거래·수동 결정·기장 보호를 유지한다.

- 출처: `docs/specs/cleanup-export-conflicts-20261105.md:4`, `docs/specs/cleanup-export-conflicts-20261105.md:5`, `docs/history/operations-20261028-20261107.md:268`, `docs/history/operations-20261028-20261107.md:269`, `docs/history/session_handoff-through-20261107.md:300`

### DATE-058 · 잘못된 취소 메일 날짜

*보호*

인증 취소 메일의 수신 날짜가 잘못돼도 취소 사실·환불 요청은 보존한다. 사전승인액이나 예약 기간만으로 실제 결제·환급·금융 연결을 확정하지 않는다.

- 출처: `docs/history/session_handoff-through-20261107.md:1134`

### DATE-059 · 이용기간 기준 과거 판정

*일반 · 결정 2026-10-13*

과거 완료 범위를 판단할 때 카드는 원문 거래일, OTA는 실제 이용기간을 적용한다. 미래 이용·기준일을 넘는 기간·기간 충돌·날짜 미상은 과거 결제일만으로 제외하거나 과거 완료로 단정하지 않는다.

- 출처: `docs/specs/finance.md:159`, `docs/history/operations-through-20261027.md:1037`

### DATE-060 · 최초 인증 메일 수신일

*일반 · 결정 2026-10-27*

항공권에 별도 명시 예약일이 없으면 같은 공급자·예약번호의 인증 메일 중 최초 mailbox internal_date를 한국 날짜로 바꿔 FIRST_RECEIVED로 사용한다. 명시 예약일·날짜 충돌이 우선하며 공급사 원본 예약 생성일·발권일·결제일이라고 표현하지 않는다.

- 대체된 옛 규칙:
  - 메일 수신일이 있다는 이유만으로도 예약일 탐색 대안 사용을 전부 금지하던 과거 문구는 승인된 동일 공급자·예약번호의 최초 인증 수신일 범위에서 대체된다. — 2026-10-27, docs/history/product-and-handoffs.md:358
  - 메일 수신일이 있다는 이유만으로도 예약일 탐색 대안 사용을 전부 금지하던 과거 문구는 승인된 동일 공급자·예약번호의 최초 인증 수신일 범위에서 대체된다. — 2026-10-27, docs/history/product-and-handoffs.md:366
- 출처: `docs/specs/refactor-master-20261027.md:184`, `docs/specs/finance.md:104`, `docs/specs/ui.md:631`, `AGENTS.md:46`, `app/flight_evidence.py:116`

### DATE-061 · 최초 수신시각 유효성

*보호*

최초 수신일 근거에는 같은 공급자·예약에 명확히 귀속되는 인증 메일과 유효한 mailbox 수신시각만 사용한다. 미인증·다른 예약·다중 번호 귀속 불명·무효 수신시각은 제외하고 발신 Date·본문 날짜·Received 헤더로 대신하지 않는다.

- 조건·예외: 코드 추출값은 internal_date/internalDate가 12~13자리 밀리초이며 한국 날짜 연도 2000~2100이다. 두 필드가 함께 존재하며 값이 다르면 제외한다.
- 출처: `docs/history/operations-through-20261027.md:541`, `docs/specs/ui.md:628`, `docs/specs/ui.md:631`, `app/flight_evidence.py:97`, `app/flight_evidence.py:101`

### DATE-062 · 명시 예약일의 의미 검증

*보호*

명시 항공 예약일은 실제 예약 생성·완료 사건을 뜻하는 원문 라벨과 유효한 달력 날짜를 검증해 읽는다. API 필드명만으로 의미를 보장하지 않고 발권일·출발일·일반 날짜·결제일을 예약일로 추정하지 않는다.

- 출처: `docs/history/product-and-handoffs.md:252`, `docs/history/product-and-handoffs.md:365`, `docs/history/product-and-handoffs.md:366`

### DATE-063 · 예약일·여정 충돌 우선

*보호*

여러 인증 근거의 명시 예약일 또는 여정이 충돌하면 자동 카드 조회 날짜를 비운다. 최초 수신일을 표시할 수 있어도 충돌을 지우거나 그 날짜로 자동 조회를 재개하지 않는다.

- 출처: `docs/specs/flight-passenger-trip-grouping-20261105.md:11`, `docs/specs/flight-booking-compact-spa-20261104.md:22`, `docs/specs/flight-booking-focused-spa-ux-20261104.md:27`, `AGENTS.md:46`, `app/flight_evidence.py:77`

### DATE-064 · 최초 수신 근거 갱신

*보호*

더 이른 인증 수신 근거·원본 변경이 생기면 기준 날짜와 digest/revision을 바꾸고 재검증한다. 새 날짜가 생겼다는 이유로 항공 예약이나 카드 연결을 추가 생성하지 않는다.

- 출처: `docs/specs/ui.md:631`, `tests/card_pipeline/test_flight_first_received_day.py:59`

### DATE-065 · 항공 날짜 자동 조회 조건

*일반*

카드가 연결되지 않은 예약은 검증된 명시 예약일 또는 승인된 FIRST_RECEIVED 당일의 카드 원행을 탐색할 수 있다. 최신 근거·시간대·예약 귀속이 유효하고 취소·날짜/여정 충돌·기존 연결이 없어야 한다.

- 조건·예외: 두 날짜 근거가 모두 없으면 임의 후보를 생성하지 않고 직접 날짜 조회를 제공한다.
- 대체된 옛 규칙:
  - 명시 원본 예약일만 자동 일별 조회의 근거로 허용하던 부분은 2026-10-27 승인된 FIRST_RECEIVED까지 확대됐다. 충돌·취소·미검증 보호는 유지한다. — 2026-10-27, docs/history/product-and-handoffs.md:255
  - 명시 원본 예약일만 자동 일별 조회의 근거로 허용하던 부분은 2026-10-27 승인된 FIRST_RECEIVED까지 확대됐다. 충돌·취소·미검증 보호는 유지한다. — 2026-10-27, docs/history/product-and-handoffs.md:255
  - 명시 원본 예약일만 자동 일별 조회의 근거로 허용하던 부분은 2026-10-27 승인된 FIRST_RECEIVED까지 확대됐다. 충돌·취소·미검증 보호는 유지한다. — 2026-10-27, docs/history/product-and-handoffs.md:266
  - 명시 원본 예약일만 자동 일별 조회의 근거로 허용하던 부분은 2026-10-27 승인된 FIRST_RECEIVED까지 확대됐다. 충돌·취소·미검증 보호는 유지한다. — 2026-10-27, docs/history/product-and-handoffs.md:891
  - 그 밖에 10건
- 출처: `docs/specs/flight-booking-compact-spa-20261104.md:16`, `docs/history/product-and-handoffs.md:255`, `docs/history/product-and-handoffs.md:266`, `docs/specs/ui.md:631`, `docs/specs/ui.md:636`

### DATE-066 · 동일 날짜 카드 전수 조회

*보호*

일별 카드 조회는 금액·가맹점으로 미리 숨기지 않고 해당 날짜의 취소·환불·중복·다른 예약 점유 원행까지 모두 접근 가능하게 제공한다. 페이징·총건수·선택 가능 여부를 구분하며 일부 페이지를 전체라고 표시하지 않는다.

- 출처: `docs/history/operations-through-20261027.md:632`, `docs/history/implementation-and-audits.md:983`, `docs/history/product-and-handoffs.md:475`, `docs/specs/ui.md:665`, `docs/specs/ui.md:681`

### DATE-067 · 사용자 날짜는 조회 필터

*보호*

사용자가 직접 고른 날짜는 이번 카드 원행 조회 필터이며 예약일·결제일·연결 확정값으로 저장하거나 승격하지 않는다. 조회 날짜의 의미와 출처를 분리해 표시한다.

- 출처: `docs/specs/flight-booking-focused-spa-ux-20261104.md:27`, `docs/history/product-and-handoffs.md:360`, `docs/history/product-and-handoffs.md:368`, `docs/specs/ui.md:653`, `docs/specs/ui.md:683`

### DATE-068 · 항공 일별 조회의 확장 금지

*보호*

항공 예약일 당일 카드 전수 조회는 승인된 날짜 하나를 기준으로 한다. ±1일 확장은 사용자가 명시 선택한 필터에서만 허용하며 일반 외화 대사의 하루 허용을 이 조회에 자동 적용하지 않는다.

- 출처: `docs/specs/flight-booking-focused-spa-ux-20261104.md:28`, `docs/history/product-and-handoffs.md:374`, `docs/specs/ui.md:681`

### DATE-069 · 날짜 후보와 결제 사실 분리

*보호*

이름·날짜·금액 유사성이나 카드 후보 조회만으로 항공 예약 완료·사람·탑승·결제·카드 연결·기장·여행 귀속을 확정하지 않는다. 검증된 실제 연결만 연결된 카드로 표시하고 한 결제를 예약 전체 결제로 확대하지 않는다.

- 출처: `docs/specs/flight-booking-compact-spa-20261104.md:15`, `docs/specs/flight-booking-compact-spa-20261104.md:23`, `docs/specs/flight-booking-focused-spa-ux-20261104.md:25`, `docs/specs/flight-booking-focused-spa-ux-20261104.md:26`, `docs/history/product-and-handoffs.md:367`

### DATE-070 · 항공 검색의 기간

*일반*

항공 날짜 검색은 검증된 최초~최종 여정 출발일의 양끝을 포함한다. 연도·월이 생략된 입력은 해당 일자가 있는 여행을 찾되 예약일·카드일을 운항 날짜로 대체하지 않는다.

- 출처: `docs/specs/flight-route-date-search-20261104.md:5`, `docs/history/operations-20261028-20261107.md:305`

### DATE-071 · 항공 검색의 미상·충돌

*보호*

편도는 확인된 하루만 날짜 검색에 사용하고 날짜 없는 자료는 날짜 검색에서 제외한다. 충돌 자료는 검증된 연속 기간으로 합성하지 않고 명시 개별 출발일만 검색한다.

- 출처: `docs/specs/flight-route-date-search-20261104.md:5`

### DATE-072 · 항공 예약의 첫 출발 여행

*일반 · 결정 2026-10-28*

연속 여행에 걸친 한 항공 예약 전체는 첫 실제 출발 여행에 귀속한다. 귀국일이 첫 여행 종료일을 넘어도 귀국일·메일 수신일·결제일로 다른 여행에 재배정하거나 뒤 구간을 복제하지 않는다.

- 출처: `docs/specs/ota.md:8`, `docs/specs/trip-flight-booking-overview-20261028.md:19`, `docs/specs/trip-flight-booking-overview-20261028.md:36`, `docs/specs/trip-flight-booking-overview-20261028.md:42`, `docs/specs/trip-flight-booking-overview-20261028.md:145`

### DATE-073 · 항공 출발일 경계의 후보 구분

*일반*

같은 출발일을 포함한 여행이 여러 개면 기존 사용자 귀속·검증 카드/OTA 관계·여행 시작일 일치·목적지/노선 근거로 구분한다. 앞 여행 종료일과 다음 여행 시작일이 같은 날에 명확한 다음 여행 출국편이면 다음 여행을 우선한다.

- 조건·예외: 담당자·일정·노선의 본질 충돌은 사실로 남기며 카드의 일반 최종 귀속과 항공 목록 projection을 구분한다.
- 대체된 옛 규칙:
  - 후보 불확실성을 사용자 HOLD/미해결 작업으로 노출하던 표현은 폐지됐다. 미검증 항공 관계를 확정하지 않는 보호는 유지한다. — 2026-10-10, docs/specs/finance.md:194
  - 후보 불확실성을 사용자 HOLD/미해결 작업으로 노출하던 표현은 폐지됐다. 미검증 항공 관계를 확정하지 않는 보호는 유지한다. — docs/specs/trip-flight-booking-overview-20261028.md:182
- 출처: `docs/specs/flight-passenger-trip-grouping-20261105.md:8`, `docs/specs/trip-flight-booking-overview-20261028.md:23`, `docs/specs/trip-flight-booking-overview-20261028.md:46`, `docs/specs/trip-flight-booking-overview-20261028.md:47`, `docs/specs/trip-flight-booking-overview-20261028.md:94`

### DATE-074 · 항공 목록 귀속과 금융 저장 분리

*보호*

항공권 목록의 첫 출발 여행 projection은 돈 거래의 새 여행 분류를 자동 저장한다는 뜻이 아니다. 출발일 변경이 수동 귀속과 다르면 충돌을 보이고 수동 결정을 조용히 덮지 않는다.

- 출처: `docs/specs/trip-flight-booking-overview-20261028.md:55`, `docs/specs/trip-flight-booking-overview-20261028.md:97`

### DATE-075 · 항공 구간의 원문 계보

*보호*

왕복·다구간은 leg label·실제 날짜·공항 연쇄로 순서를 검증하고 최신 여정 및 원문 변경 계보를 보존한다. 돌아오는편 변경이나 날짜 차이만으로 새 예약·새 결제를 만들지 않는다.

- 출처: `docs/specs/ota.md:8`, `docs/specs/ota.md:5`, `docs/specs/trip-flight-booking-overview-20261028.md:41`, `docs/specs/trip-flight-booking-overview-20261028.md:184`, `docs/specs/trip-flight-booking-overview-20261028.md:145`

### DATE-076 · 항공 이용일 표시

*일반*

장부 항공료·항공권은 저장 이용기간을 먼저 표시하고 없으면 저장 예약번호에 대응하는 검증된 항공/OTA 근거의 실제 출발일들을 중복 없이 표시한다. 실제 출발일 목록을 숙박 밤수로 표현하지 않으며 근거가 없으면 날짜 미상을 사실대로 설명한다.

- 조건·예외: 설명 문자열의 번호만으로 저장 예약 관계를 만들지 않는다.
- 출처: `docs/specs/ledger-service-date-investigation-20261109.md:24`, `docs/specs/ledger-flight-service-dates-20261105.md:7`

### DATE-077 · 표시용 마지막 완결 세대

*일반*

장부 이용일은 재계산·재시도 중 마지막 완결 세대가 있으면 표시용으로 유지할 수 있다. 쓰기·연결·금융 경로는 계속 fresh 근거를 요구하고 처음 완결 세대가 없으면 확인된 날짜를 창작하지 않는다.

- 대체된 옛 규칙:
  - 장부 이용일 화면 표시까지 fresh 세대만 요구하던 범위는 2026-11-10 마지막 완결 세대 표시 허용으로 대체된다. 금융 경로의 fresh 조건은 유지한다. — 2026-11-05, docs/specs/ledger-flight-service-dates-20261105.md:7
- 출처: `docs/specs/ledger-flight-service-dates-20261105.md:28`

### DATE-078 · 표시 기간의 수동 교정 보호

*보호*

명시 수동 공란·입력값·다른 저장 예약번호는 표시 보완보다 우선한다. stale·취소·불완전 달력 날짜·출처 없는 근거·원문 충돌로 이용기간을 보완하거나 없는 숙박 밤수를 추론하지 않는다.

- 출처: `docs/specs/ledger-service-date-investigation-20261109.md:24`, `docs/specs/ledger-service-date-investigation-20261109.md:45`, `docs/specs/ledger-flight-service-dates-20261105.md:9`, `docs/history/operations-20261028-20261107.md:127`, `docs/history/session_handoff-through-20261107.md:165`

### DATE-079 · 현장 결제일 표시

*보호*

직접 가맹점의 숙박·렌터카는 허용된 여행 날짜 범위 안의 카드 이용일을 현장 결제로 표시할 수 있다. 예약·PG·국내 여행사·마켓·ARS·렌터카 중개사는 예약 채널로 구분하고 현장 결제일에서 실제 숙박 일수·이용기간을 만들어 내지 않는다.

- 조건·예외: 현재 인계 원문의 같은 날 후속 #790은 현장 결제 표시 범위를 여행 시작 전날까지 확장했다. 이는 표시 규칙이며 여행 일정·금융 링크를 바꾸지 않는다.
- 출처: `docs/session_handoff.md:14`, `docs/session_handoff.md:66`

### DATE-080 · 예약만 있는 기간 추론

*일반*

인증 예약 확인서의 공급자·예약일·원문 금액·카드 끝자리가 일치하는 근거는 허용된 읽기 전용 기간 추론에 사용할 수 있다. 예약 ID와 공급자 예약번호를 구분하고 RESERVATION_ONLY를 실제 결제로 승격하지 않는다.

- 조건·예외: 금융 비교는 원문 통화·청구액 계약을 별도로 따른다.
- 출처: `docs/session_handoff.md:96`

### DATE-081 · 휴양시설 안내의 날짜 한계

*보호 · 결정 2026-10-30*

숲나들e 등 안내에 시작일만 있으면 퇴실일·종료일은 미상으로 유지하고 결제기한을 이용일·실제 결제일로 바꾸지 않는다. 안내만으로 예약번호·금액·기간·카드 결제를 새로 만들지 않는다.

- 출처: `docs/specs/ota.md:20`, `docs/specs/ota.md:22`, `docs/history/session_handoff-through-20261107.md:951`, `docs/specs/ota.md:38`, `docs/history/operations-20261028-20261107.md:1027`

### DATE-082 · 휴양시설의 근접 날짜 진단

*일반*

휴양시설명·주소 지자체와 발송일/이용일 전후 7일의 카드는 낮은 확신의 진단 후보로만 제공한다. 명시 금액 일치·차이·미상은 구분하며 진단 날짜만으로 결제 관계를 확정하지 않는다.

- 조건·예외: 기존 검증 여행만 후보로 사용하며 금융·수동 결정·원문을 유지한다.
- 출처: `docs/specs/ota.md:44`, `docs/history/operations-20261028-20261107.md:1017`, `docs/history/product-and-handoffs.md:1778`

### DATE-083 · 영수증 취소일 의미

*보호*

NICE 영수증은 명시 결제일을 읽고 취소일이 명시되지 않으면 발송일만 표시한다. 없는 이용기간·예약번호·카드 끝자리를 만들지 않으며 일반 날짜 일치만으로 카드 결제를 확정하지 않는다.

- 출처: `docs/specs/ota.md:46`

### DATE-084 · Trip 사전승인·현장 비용 분리

*보호*

Trip 현장결제·카드 보증 예약은 사전승인과 호텔에서 실제 치른 숙박비를 구분한다. 실제 숙박비는 호텔 현장결제 카드 원행이 담당하며 사전승인·취소·환불의 기간 표시를 실제 환급 완료로 확장하지 않는다.

- 출처: `docs/specs/ota-portal-browser-collection-20261110.md:67`

### DATE-085 · 나중결제 예약 재수집

*일반 · 결정 2026-11-10*

나중결제 예약은 청구 뒤 근거가 추가되므로 이미 받은 예약도 주 1회 또는 큰 여행 직후 다시 조회한다. 새 관측이 생겨도 기존 결제일·기간·수동 연결을 근거 없이 덮지 않는다.

- 출처: `docs/specs/ota-portal-browser-collection-20261110.md:84`

### DATE-086 · 카드 날짜 미상의 보존

*일반 · 결정 2026-11-10*

유효한 날짜가 없는 저장 카드 원행도 버리거나 합치지 않고 접근 가능하게 남긴다. 날짜를 오늘로 채우거나 연도 필터 뒤에 숨기지 않으며 사용자 질문 상태 대신 날짜 원문 부재라는 사실을 설명한다.

- 대체된 옛 규칙:
  - 날짜 없는 원행을 사용자 확인 필요·보류 상태와 대기 섹션으로 표현하던 부분은 폐지됐다. 날짜 미상 원행의 조회·금융 보호는 보존한다. — 2026-10-24, docs/history/implementation-and-audits.md:1516
  - 날짜 없는 원행을 사용자 확인 필요·보류 상태와 대기 섹션으로 표현하던 부분은 폐지됐다. 날짜 미상 원행의 조회·금융 보호는 보존한다. — 2026-10-24, docs/history/implementation-and-audits.md:1558
  - 날짜 없는 원행을 사용자 확인 필요·보류 상태와 대기 섹션으로 표현하던 부분은 폐지됐다. 날짜 미상 원행의 조회·금융 보호는 보존한다. — docs/specs/card-upload-full-reconciliation-20261029.md:37
  - 날짜 없는 원행을 사용자 확인 필요·보류 상태와 대기 섹션으로 표현하던 부분은 폐지됐다. 날짜 미상 원행의 조회·금융 보호는 보존한다. — docs/specs/ui.md:123
  - 그 밖에 1건
- 출처: `docs/specs/uiux-full-audit-redesign-20261110.md:376`, `docs/specs/uiux-full-audit-redesign-20261110.md:575`, `docs/specs/uiux-full-audit-redesign-20261110.md:588`, `docs/specs/card-upload-full-reconciliation-20261029.md:37`, `docs/specs/ui.md:352`

### DATE-087 · 카드 날짜·시간 정렬

*일반*

카드 거래는 이용일 오름차순, 실제 이용시간 오름차순, 안정 거래 ID 순으로 정렬한다. 시간이 없으면 같은 날짜의 시간 있는 거래 뒤에 두고 00:00을 합성하지 않는다.

- 조건·예외: 원본 전체 날짜·시각과 출처를 보존한다.
- 출처: `docs/history/implementation-and-audits.md:1525`, `docs/history/implementation-and-audits.md:1512`, `docs/specs/ui.md:103`, `docs/specs/ui.md:106`

### DATE-088 · 유효한 연도의 전체 조회

*일반*

연도 선택은 유효한 원본 이용일의 연도에서 유도하고 명세가 지정한 2026년은 데이터가 없어도 제공한다. 다른 연도·미래 연도를 버리지 않으며 연도 전체·선택 월의 기존 조회 범위를 유지한다.

- 조건·예외: 연도 전체와 월 URL 호환은 유지하되 사용자 확인 대기 상태는 되살리지 않는다.
- 출처: `docs/specs/ui.md:21`, `docs/history/session_handoff-through-20261107.md:1147`, `docs/specs/ui.md:93`

### DATE-089 · 숙박 이용일 정렬

*일반 · 결정 2026-11-06*

장부 숙박 정렬은 저장 service_period 또는 검증된 기존 카드 예약 근거의 이용 시작일을 사용한다. 잘못된·역전·기존 허용 기간 초과·없는 날짜는 숙박 그룹 끝에 두고 동률은 입력 순서를 유지한다.

- 조건·예외: 결제일로 숙박 이용일을 추정하지 않는다.
- 출처: `docs/specs/expense-display-order-20261106.md:6`

### DATE-090 · 카드 파일별 기본 기간

*일반 · 결정 2026-11-08*

수집 공백은 파일·카드사별 첫~마지막 유효 거래일 전체를 하나의 연속 기본 기간으로 만든 뒤 계산한다. 한 파일 내부의 거래 없는 날짜는 공백으로 세지 않는다.

- 예: 한 파일은 1~10일, 다른 파일은 15~20일이면 공백은 11~14일 한 구간이다.
- 출처: `docs/specs/card-transaction-date-gaps-20261108.md:5`, `docs/specs/card-transaction-date-gaps-20261108.md:9`, `docs/operations.md:134`, `docs/session_handoff.md:159`, `docs/specs/card-upload-management-ux-20261105.md:308`

### DATE-091 · 카드사별 파일 기간 합집합

*일반 · 결정 2026-11-08*

같은 카드사의 모든 카드 파일 기본 기간은 겹치거나 바로 이어지면 합쳐 파일 사이 빈 구간만 공백으로 표시한다. 카드사가 다르면 합치지 않고 카드사가 없는 자료는 파일별로 분리한다.

- 대체된 옛 규칙:
  - 개별 거래 날짜의 합집합으로 내부 무거래일까지 공백으로 세던 중간 규칙은 파일별 연속 기간 합집합으로 대체됐다. — 2026-11-08, docs/operations.md:150
  - 개별 거래 날짜의 합집합으로 내부 무거래일까지 공백으로 세던 중간 규칙은 파일별 연속 기간 합집합으로 대체됐다. — 2026-11-08, docs/session_handoff.md:172
  - 공백 화면을 카드 식별자·조회축별로만 분리하고 다른 카드 파일의 범위를 합치지 않던 이전 표시 계약은 같은 카드사 전체 파일 합집합으로 대체됐다. 원본 조회 증빙의 식별은 유지한다. — 2026-11-02, docs/specs/finance.md:26
  - 공백 화면을 카드 식별자·조회축별로만 분리하고 다른 카드 파일의 범위를 합치지 않던 이전 표시 계약은 같은 카드사 전체 파일 합집합으로 대체됐다. 원본 조회 증빙의 식별은 유지한다. — docs/specs/card-upload-management-ux-20261105.md:44
  - 그 밖에 4건
- 출처: `docs/operations.md:150`, `docs/session_handoff.md:172`, `docs/specs/card-upload-management-ux-20261105.md:44`, `docs/specs/card-upload-management-ux-20261105.md:98`, `docs/specs/card-upload-management-ux-20261105.md:230`

### DATE-092 · 수집 공백의 날짜·추정 한계

*보호 · 결정 2026-11-08*

파일 공백 계산은 기존 approval_date의 이용/승인/거래일 매핑을 사용하고 비어 있으면 posting_date를 쓴다. 잘못된 날짜는 제외하며 전체 양끝 바깥이나 파일 사이 빈 구간을 실제 자료 누락으로 단정하지 않는다.

- 출처: `docs/specs/card-transaction-date-gaps-20261108.md:10`, `docs/specs/card-transaction-date-gaps-20261108.md:11`, `docs/operations.md:180`, `docs/specs/finance.md:27`, `docs/specs/finance.md:29`

### DATE-093 · 옛 조회기간 화면 대체

*일반 · 결정 2026-11-08*

조회기간 확인·관리 시작일 폼 대신 카드사별 파일 기간과 파일 사이 공백을 제공한다. 기간 업로드는 카드사·날짜 맥락을 유지하고 긴 구간은 접되 파일 상세·처리 결과는 남긴다.

- 대체된 옛 규칙:
  - 관리 시작일·조회축별 확인 상태·수동 조회기간 확인 폼을 사용자 공백 관리의 기준으로 삼던 화면 계약은 폐지됐다. 기존 증빙·API·감사 자료는 삭제하지 않는다. — docs/specs/card-upload-management-ux-20261105.md:33
  - 관리 시작일·조회축별 확인 상태·수동 조회기간 확인 폼을 사용자 공백 관리의 기준으로 삼던 화면 계약은 폐지됐다. 기존 증빙·API·감사 자료는 삭제하지 않는다. — docs/specs/card-upload-management-ux-20261105.md:99
  - 관리 시작일·조회축별 확인 상태·수동 조회기간 확인 폼을 사용자 공백 관리의 기준으로 삼던 화면 계약은 폐지됐다. 기존 증빙·API·감사 자료는 삭제하지 않는다. — docs/specs/card-upload-management-ux-20261105.md:110
  - 관리 시작일·조회축별 확인 상태·수동 조회기간 확인 폼을 사용자 공백 관리의 기준으로 삼던 화면 계약은 폐지됐다. 기존 증빙·API·감사 자료는 삭제하지 않는다. — docs/specs/card-upload-management-ux-20261105.md:112
  - 그 밖에 17건
- 출처: `docs/specs/card-transaction-date-gaps-20261108.md:14`, `docs/operations.md:180`, `docs/session_handoff.md:217`, `docs/specs/card-upload-management-ux-20261105.md:31`, `docs/specs/card-upload-management-ux-20261105.md:33`

### DATE-094 · 기본 파일기간과 원본 증빙 구분

*보호 · 결정 2026-11-08*

파일 첫~마지막 거래일은 공백 표시의 기본 기간으로 사용하되 카드사 원본이 실제 그 전체를 조회했다는 금융 증빙으로 새 확정하지 않는다. 원본 조회 조건·0건 조회 증빙·기존 보호 API와 감사 이력은 유지한다.

- 대체된 옛 규칙:
  - 거래일 최소/최대를 어떤 조회기간 표시에도 사용하지 못하게 하던 이전 UI 제한은 2026-11-08 파일 기본기간 계산 범위에서 대체됐다. 실제 원본 조회 완료를 허위 확정하지 않는 보호는 유지한다. — docs/specs/card-upload-management-ux-20261105.md:33
  - 거래일 최소/최대를 어떤 조회기간 표시에도 사용하지 못하게 하던 이전 UI 제한은 2026-11-08 파일 기본기간 계산 범위에서 대체됐다. 실제 원본 조회 완료를 허위 확정하지 않는 보호는 유지한다. — docs/specs/card-upload-management-ux-20261105.md:66
  - 거래일 최소/최대를 어떤 조회기간 표시에도 사용하지 못하게 하던 이전 UI 제한은 2026-11-08 파일 기본기간 계산 범위에서 대체됐다. 실제 원본 조회 완료를 허위 확정하지 않는 보호는 유지한다. — docs/specs/card-upload-management-ux-20261105.md:177
  - 거래일 최소/최대를 어떤 조회기간 표시에도 사용하지 못하게 하던 이전 UI 제한은 2026-11-08 파일 기본기간 계산 범위에서 대체됐다. 실제 원본 조회 완료를 허위 확정하지 않는 보호는 유지한다. — docs/specs/cost-pr-only-implementation-brief-20261106.md:63
  - 그 밖에 3건
- 출처: `docs/specs/cost-pr-only-implementation-brief-20261106.md:63`, `docs/specs/card-upload-management-ux-20261105.md:232`, `docs/specs/card-upload-management-ux-20261105.md:280`, `docs/specs/card-upload-management-ux-20261105.md:33`, `docs/specs/finance.md:26`

### DATE-095 · Google 비용 대조와 날짜

*일반 · 결정 2026-10-30*

같은 실제 여행 ID와 같은 부호·통화의 지출 금액이면 COST↔Google M:N 대조 관계를 생성한다. 거래일·기입일·가맹점·메모 차이는 관계 후보 제거·순위의 조건이 아니고 참고 비교로만 표시한다.

- 대체된 옛 규칙:
  - Google 비용 관계를 날짜·가맹점의 추가 일치와 유일한 1:1 대응으로만 성립시키던 계약은 같은 여행·금액의 M:N 대조로 대체됐다. 날짜 의미와 금융 원행은 참고 정보로 보존한다. — 2026-10-26, docs/history/product-and-handoffs.md:486
  - Google 비용 관계를 날짜·가맹점의 추가 일치와 유일한 1:1 대응으로만 성립시키던 계약은 같은 여행·금액의 M:N 대조로 대체됐다. 날짜 의미와 금융 원행은 참고 정보로 보존한다. — docs/specs/sheet-manual-expense-dedup-20261029.md:19
  - Google 비용 관계를 날짜·가맹점의 추가 일치와 유일한 1:1 대응으로만 성립시키던 계약은 같은 여행·금액의 M:N 대조로 대체됐다. 날짜 의미와 금융 원행은 참고 정보로 보존한다. — docs/specs/sheet-manual-expense-dedup-20261029.md:37
  - Google 비용 관계를 날짜·가맹점의 추가 일치와 유일한 1:1 대응으로만 성립시키던 계약은 같은 여행·금액의 M:N 대조로 대체됐다. 날짜 의미와 금융 원행은 참고 정보로 보존한다. — docs/specs/sheet-manual-expense-dedup-20261029.md:39
  - 그 밖에 2건
- 출처: `docs/specs/google-expense-mn-reconciliation-20261030.md:7`, `docs/specs/google-expense-mn-reconciliation-20261030.md:16`, `docs/specs/google-expense-mn-reconciliation-20261030.md:37`, `docs/specs/google-expense-mn-reconciliation-20261030.md:61`, `docs/specs/sheet-manual-expense-dedup-20261029.md:19`

### DATE-096 · Google 수입 원문 보호

*보호*

Google 수입 원행의 날짜·금액·이름·셀 값은 최종 정본이다. 보험 명단 지연이나 다른 날짜 근거로 COST가 입금일을 수정하거나 Google에 다시 쓰지 않는다.

- 출처: `docs/specs/participant-income-authority-and-drag-link-20261028.md:26`, `docs/specs/participant-income-authority-and-drag-link-20261028.md:97`, `docs/specs/participants.md:497`, `docs/specs/participants.md:531`

### DATE-097 · 영수증 날짜와 중복 방지

*보호*

카드에 연결됐던 영수증은 상호·날짜 교정이나 카드 원행의 일시적 소실 후에도 원래 식별 근거를 유지한다. 날짜가 같다는 이유로 여러 증빙을 자동 병합하거나 현금 비용으로 재계상하지 않는다.

- 조건·예외: 명시 실제 한 결제 묶음은 별도 영수증 계약을 따른다.
- 출처: `docs/history/ota-legacy.md:332`, `docs/specs/google-ledger.md:131`, `docs/specs/receipts.md:37`, `docs/specs/receipts.md:38`

### DATE-098 · 교정 권한과 원문 날짜

*보호*

근거가 명확한 항목·여행 교정은 승인 범위에서 수행하되 카드 행 이용일은 화면에서 직접 고치는 사실로 취급하지 않는다. 숙박일·예약 유지·은행 환급이 확인되지 않았다면 주문번호·결제일로 이를 만들어 내지 않는다.

- 출처: `docs/specs/ota-portal-browser-collection-20261110.md:11`, `docs/operations.md:84`, `docs/operations.md:104`, `docs/session_handoff.md:114`, `docs/specs/finance.md:246`

### DATE-099 · 동일 예약의 새 관측 보존

*보호*

동일 source identity의 금액·날짜·카드·예약 참조·digest가 달라져도 기존 사용자 연결·점유를 조용히 지우지 않는다. 새 관측은 변경 경고와 함께 보존하며 날짜가 없는 새 관측으로 기존 검증된 예정일 연결을 강등하지 않는다.

- 출처: `docs/history/product-and-handoffs.md:896`, `docs/history/operations-through-20261027.md:977`, `docs/specs/ota.md:712`, `docs/specs/participants.md:243`, `docs/history/ota-legacy.md:704`

### DATE-100 · Trip 할인·날짜 판단의 범위

*일반 · 결정 2026-10-15*

Trip 결제는 반복 가맹점별 별칭 승인을 요구하지 말고 실제 날짜·정확 금액 또는 승인된 할인 단위·유효 후보 근거로 판단한다. 날짜 차이·할인 원인을 사실로 창작하지 않고 최신 동일일·동액 및 M:N 허용 범위는 유지한다.

- 출처: `docs/history/ota-legacy.md:1228`, `소유자 지시 메모:MEMORY.md:9`, `소유자 지시 메모:feedback-trip-no-per-merchant-approval.md:15`

### DATE-101 · 토요코인 예약 기간 추론

*일반*

토요코인 등 승인된 예약 후보는 지점·숙박 시점·원문 통화와 금액을 검증해 허용된 기간 추론으로 표시할 수 있다. 결제일 미상과 결제 검증 미완료를 유지하고 후보들을 개별 실제 결제로 임의 확정하지 않는다.

- 조건·예외: 모든 후보 기간이 같다는 표시 보호와 수동 공란·취소·원문 충돌 보호를 유지한다.
- 출처: `docs/history/implementation-and-audits.md:922`

### DATE-102 · 부분 환불의 여행 근거

*보호*

여행 비용에 속하는 부분 환불은 실제 예약 이용기간 또는 사용자가 지정한 여행을 근거로 원결제와 함께 판단한다. 원금·환불액·분기 비용·기존 사용자 귀속을 원문 날짜 추론만으로 바꾸지 않는다.

- 출처: `docs/history/ota-legacy.md:1471`

### DATE-103 · 대조 후보의 날짜 의미

*일반*

원문 실제 결제일과 카드 날짜가 모두 검증되고 동일일 또는 승인된 차이 정책에 맞을 때 관련 금액 차이 진단을 보여 준다. 제공자만 같고 날짜가 없거나 무관한 거절을 해당 카드의 결제 오류로 오표시하지 않는다.

- 조건·예외: 기존 exact/무날짜 관계 matcher와 별도의 화면 진단 경로다.
- 출처: `docs/history/product-and-handoffs.md:329`, `docs/history/product-and-handoffs.md:850`

### DATE-104 · 항공 조회 DTO의 오염 배제

*보호*

도시 필드로 잘못 추출된 날짜·문장은 항공 조회 DTO에서 배제하고 검증된 공항 코드 등 기존 근거로 표시한다. 원문·취소·충돌 경고는 유지하고 날짜를 복구한 사실로 꾸미지 않는다.

- 출처: `docs/specs/expense-flight-priority-fix-20261104.md:5`, `docs/history/operations-20261028-20261107.md:297`

### DATE-105 · 렌터카 픽업·반납 기간

*일반*

Klook 등 검증된 렌터카 확인서의 명시 픽업·반납일을 이용기간으로 사용한다. 예약일·결제일·카드일을 임의로 인수·반납 날짜로 바꾸지 않는다.

- 조건·예외: 양식의 유일 날짜·순방향·허용 기간 범위는 format_notes에서 구분한다.
- 출처: `docs/session_handoff.md:18`

### DATE-106 · 내보내기 날짜 보호

*보호*

선택된 현재 여행 지출만 공식 양식으로 복사하며 잘못된 날짜·금액·증빙·중복은 제외 수와 사유를 알린다. 알 수 없는 증빙을 카드로 바꾸거나 날짜 정규화 불가를 날짜 일치로 세지 않는다.

- 출처: `docs/history/operations-20261028-20261107.md:1171`, `docs/history/product-and-handoffs.md:1982`, `docs/specs/google-ledger.md:98`, `docs/specs/google-ledger.md:642`

### DATE-107 · 날짜 표시와 전체 원문

*일반*

장부 날짜는 같은 해이면 MM-DD, 다른 해가 섞이면 YY-MM-DD로 표시하고 전체 원문 날짜는 title 등에 보존한다. 카드의 연도/월 조회는 각각 월·일/일 표시를 사용하되 실제 시간과 날짜 의미를 보존한다.

- 조건·예외: 화면별 표시 계약을 공통 표시 유틸리티로 적용한다. 원문 날짜는 바꾸지 않는다.
- 출처: `docs/specs/uiux-full-audit-redesign-20261110.md:360`, `docs/specs/ui.md:19`, `docs/history/session_handoff-through-20261107.md:1094`

### DATE-108 · 금액 차이 원인 비약 금지

*보호*

거래 미리보기의 OTA 금액·카드 금액·실제 차액·날짜·방향은 확인된 값으로 보존한다. 할인·시차 등 차이 원인을 추측해 사실로 적거나 원문 날짜를 규칙에 맞게 바꾸지 않는다.

- 대체된 옛 규칙:
  - 제안 질문·사용자 승인 대기 화면을 필수 처리 단계로 두던 표현은 폐지됐다. 실제 차액과 날짜 조건의 기록 및 원인 비약 금지는 보존한다. — 2026-10-08, docs/history/ota-legacy.md:850
  - 제안 질문·사용자 승인 대기 화면을 필수 처리 단계로 두던 표현은 폐지됐다. 실제 차액과 날짜 조건의 기록 및 원인 비약 금지는 보존한다. — docs/history/ota-legacy.md:906
  - 제안 질문·사용자 승인 대기 화면을 필수 처리 단계로 두던 표현은 폐지됐다. 실제 차액과 날짜 조건의 기록 및 원인 비약 금지는 보존한다. — docs/history/ota-legacy.md:1026
- 출처: `docs/history/ota-legacy.md:849`, `docs/history/ota-legacy.md:850`, `docs/history/ota-legacy.md:906`, `docs/history/ota-legacy.md:1026`
