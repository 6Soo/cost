# 판정 규칙 — Google 장부

> [판정 규칙집](../DECISION_POLICY.md)의 영역별 상세 규칙이다. 핵심 원칙과 읽는 법은 규칙집 본문에 있다.
> 규칙 ID는 바꾸지 않는다. 규칙을 고칠 때는 같은 ID의 내용을 고치고 옛 내용을 "대체된 옛 규칙"에 남긴다.
> "출처"의 파일과 줄 번호는 커밋 `b0340d0d`(2026-11-10) 기준이다. 그 뒤 줄어든 `AGENTS.md`·`docs/COST_V3_START_HERE.md`의 줄은 `git show b0340d0d:<경로>`로 본다. 그때의 `docs/specs/<파일>`은 지금 `docs/history/specs-20261110/<파일>`에 있다(절차서 두 개는 `docs/playbooks/`).

### GGL-001 · 최종 회계 정본

*일반*

Google 여행 시트가 수입·지출·결산의 유일한 최종 회계 정본이며 사용자가 최종 반영·수정·마감한다. COST 지출표는 Google 반영 전 작업물이다.

- 출처: `docs/specs/development-status-20261104.md:36`, `docs/specs/core-workflow-remaining-implementation-20261030.md:7`, `docs/specs/google-ledger.md:39`, `docs/specs/google-ledger.md:41`, `docs/specs/google-ledger.md:177`

### GGL-002 · Google 자동 쓰기 금지

*보호*

COST는 Google 최종 장부에 회계 행을 자동 기록·수정·이동·삭제하지 않는다. 준비·미리보기·복사·대사·내부 연결 저장으로 이 권한을 확대하지 않는다.

- 출처: `AGENTS.md:9`, `AGENTS.md:47`, `AGENTS.md:62`, `docs/specs/uiux-full-audit-redesign-20261110.md:752`, `docs/specs/card-transaction-date-gaps-20261108.md:15`

### GGL-003 · 수입·이체 직접 입력

*보호*

수입·은행 이체는 사용자가 Google에 직접 입력하고 COST는 읽는다. 내부 COST 수입과 Google 수입을 합산·자동 복제·자동 기장하지 않는다.

- 출처: `docs/specs/participant-income-authority-and-drag-link-20261028.md:127`, `docs/specs/google-ledger.md:51`, `docs/specs/google-ledger.md:52`, `docs/specs/google-ledger.md:629`, `docs/specs/participants.md:374`

### GGL-004 · 카드·영수증 수동 반영

*일반*

카드·영수증 비용은 COST에서 검토한 뒤 사용자가 다중 셀 형식으로 복사해 Google 지출 영역에 붙여넣는다.

- 조건·예외: 복사 동작은 클립보드 출력이며 Google API 쓰기가 아니다.
- 출처: `docs/specs/unified-expense-action-queue-20261105.md:111`, `docs/specs/unified-expense-action-queue-20261105.md:308`, `docs/specs/core-workflow-remaining-implementation-20261030.md:38`, `docs/specs/google-ledger.md:53`, `docs/specs/google-ledger.md:165`

### GGL-005 · 독립된 완료 사실

*보호*

예약 관계·카드 결제 검증·여행 배정·분류·내부 기록·Google 반영·실제 환급은 독립된 사실이다. 복사 클릭이나 내부 처리 완료만으로 Google 반영·은행 환급 완료를 주장하지 않는다.

- 대체된 옛 규칙:
  - 사용자 확인함·대기/보류 작업의 화면·상태 계약은 폐지됨. 원문의 금융/원본/감사 보호 부분은 계속 유지한다. — AGENTS.md:21
  - 사용자 확인함·대기/보류 작업의 화면·상태 계약은 폐지됨. 원문의 금융/원본/감사 보호 부분은 계속 유지한다. — 2026-11-05, docs/specs/unified-expense-action-queue-20261105.md:266
  - 사용자 확인함·대기/보류 작업의 화면·상태 계약은 폐지됨. 원문의 금융/원본/감사 보호 부분은 계속 유지한다. — 2026-11-05, docs/specs/unified-expense-action-queue-20261105.md:403
- 출처: `AGENTS.md:21`, `AGENTS.md:42`, `AGENTS.md:44`, `docs/specs/card-destination-only-ux-20261108.md:10`, `docs/specs/cost-pr-only-implementation-brief-20261106.md:53`

### GGL-006 · 반영 재확인

*보호*

Google 반영은 이후 정상 읽기에서 실제 행·항목·금액·건수·합계를 확인한 범위로만 판정한다. 개별 동일성을 입증하지 못하면 반영 완료 사실을 만들지 않는다.

- 조건·예외: 그룹 건수 일치 표시는 개별 거래 동일성 검증과 다르다.
- 출처: `docs/specs/google-ledger.md:172`, `docs/specs/google-ledger.md:173`, `docs/history/ota-legacy.md:552`

### GGL-007 · 선택 사본 하나

*보호*

같은 여행의 집계·대조는 선택된 main 또는 archive 한 사본만 사용한다. 양쪽 수입·지출을 합산하거나 중복 집계하지 않는다.

- 조건·예외: 원본 ID·안정 여행 키·현재 sheetId와 선택 이력을 보존한다.
- 출처: `docs/specs/google-ledger.md:175`, `docs/specs/google-ledger.md:351`, `docs/specs/google-ledger.md:355`, `docs/specs/google-ledger.md:366`, `docs/specs/google-ledger.md:613`

### GGL-008 · 동시 존재 정본

*일반 · 결정 2026-10-11*

동일 실여행이 main과 archive에 동시에 있으면 금액 정본은 main을 기본으로 하고 사용자가 비교 후 수동 선택을 바꿀 수 있다. 그 선택은 이후 동기화에도 보존한다.

- 조건·예외: 두 사본이 같아도 중복 존재는 별도 사실로 남긴다.
- 출처: `docs/specs/google-ledger.md:350`, `docs/specs/google-ledger.md:347`, `docs/history/ota-legacy.md:541`

### GGL-009 · 마감의 근거

*일반 · 결정 2026-10-11*

보관 Google 장부에서 해당 실여행 탭이 정상 확인되면 마감 완료로 판단한다. 종료일·월/분기·결산 수식·main 자체 결산만으로 마감하지 않는다.

- 조건·예외: 동일 여행이 main에도 있더라도 마감 상태와 금액 정본 선택은 분리한다.
- 출처: `docs/specs/core-workflow-remaining-implementation-20261030.md:45`, `docs/specs/google-ledger.md:175`, `docs/specs/google-ledger.md:346`, `docs/specs/google-ledger.md:238`, `docs/specs/google-ledger.md:430`

### GGL-010 · 마감 시각과 불확실성

*보호 · 결정 2026-10-11*

보관본 첫 정상 관측 시각은 마감 감지 시각이며 실제 이동 시각으로 주장하지 않는다. 여행 식별이 모호하거나 archive 조회가 실패하면 새로 마감 완료를 확정하지 않는다.

- 조건·예외: 템플릿·총괄·기타비용·유사 이름 사본을 실여행 이동으로 오인하지 않는다.
- 출처: `docs/specs/google-ledger.md:348`, `docs/specs/google-ledger.md:349`

### GGL-011 · 마감 후 원본 보존

*보호*

마감·원본 선택 전환이 카드 원본·수동 교정·환불·OTA 연결 삭제나 자동 재마감을 유발하지 않는다. 자동 Google 수정·삭제 없이 변경 사실을 기록한다.

- 출처: `docs/specs/google-ledger.md:178`, `docs/specs/google-ledger.md:358`, `docs/specs/google-ledger.md:422`

### GGL-012 · 읽기 실패와 마지막 정상값

*보호*

원본 읽기·권한·파싱 실패 때 마지막 정상 snapshot과 시각·오류를 보존한다. 빈 장부로 덮거나 stale 값을 최신 확정 장부로 표시하지 않는다.

- 출처: `docs/specs/core-workflow-remaining-implementation-20261030.md:61`, `docs/specs/google-ledger.md:176`, `docs/specs/google-ledger.md:627`, `docs/history/ota-legacy.md:274`

### GGL-013 · 수입 블록 독립 검증

*일반*

수입 표시 여부는 선택 원본의 수입 블록 상태로 판정한다. 지출 검증만 실패했다면 정상 수입 행은 유지하되 전체 회계·수익 검증 실패는 분리한다.

- 조건·예외: 수입 금액·합계 자체가 미검증이면 확정 수입 합계를 표시하지 않는다.
- 출처: `docs/specs/google-ledger.md:625`, `docs/specs/google-ledger.md:626`, `docs/history/operations-through-20261027.md:1102`, `docs/history/ota-legacy.md:168`

### GGL-014 · 합계 근거 분리

*보호*

Google 합계 셀, 거래 행 합계, 채택 가능한 금액과 검증 플래그를 구분한다. 미검증 수입/차액이나 Google 미반영 후보를 확정 매출·순수익에 혼합하지 않는다.

- 조건·예외: 개별 금액·행 합계가 검증된 경우의 합계 수식 경고를 전체 검증 성공으로 오인하지 않는다.
- 출처: `docs/specs/review-all-uncommitted-release-20261108.md:11`, `docs/specs/google-ledger.md:42`, `docs/specs/google-ledger.md:187`, `docs/history/implementation-and-audits.md:1252`, `docs/history/implementation-and-audits.md:1286`

### GGL-015 · 원본 차이

*보호*

Google 최종금액과 COST 원본이 다르면 차이를 표시하고 두 원문을 보존한다. 원본 카드 금액 수정·조용한 역동기화·수기 셀 덮어쓰기를 하지 않는다.

- 출처: `docs/specs/sheet-manual-expense-dedup-20261029.md:18`, `docs/specs/sheet-manual-expense-dedup-20261029.md:54`, `docs/specs/sheet-manual-expense-dedup-20261029.md:81`, `docs/specs/sheet-manual-expense-dedup-20261029.md:87`, `docs/specs/google-ledger.md:174`

### GGL-016 · 여행 식별

*보호*

여행은 기존 Google 여행 탭에서만 선택하고 종료일이 없으면 다음 여행 직전일까지로 한다. 안정 여행 키와 파일별 현재 sheetId를 분리하며 제목 유사성·달력상 분기로 다른 여행이나 사본을 합치지 않는다.

- 조건·예외: 여행은 Google 탭에서만 가져오고 종료일이 없으면 다음 여행 직전일까지로 한다.
- 출처: `소유자 지시 메모:trip-source-google-only.md:11`, `docs/specs/trip-flight-booking-overview-20261028.md:48`, `docs/specs/google-ledger.md:354`, `docs/specs/participants.md:381`, `docs/specs/participants.md:420`

### GGL-017 · 읽기 신선도

*일반*

Google 원본의 확인 시각·마지막 정상 시각·stale·실패를 구분한다. 주기 읽기를 실제 최신 회계 사실의 검증 성공과 혼동하지 않는다.

- 조건·예외: 읽기·캐시 갱신이 불필요한 원본/업무 DB 쓰기를 만들지 않는다.
- 출처: `docs/specs/google-ledger.md:73`, `docs/history/ota-legacy.md:599`

### GGL-018 · 허용 원본 인증 읽기

*보호*

허용된 Google 원본만 기존 인증으로 읽기 전용 조회·내보내기한다. 외부 리다이렉트·무인증 공개 fallback을 허용하지 않는다.

- 출처: `docs/specs/google-ledger.md:185`, `docs/history/ota-legacy.md:312`, `docs/history/ota-legacy.md:345`

### GGL-019 · owner/viewer 권한

*보호*

전체 COST 작업·원본은 기본 owner만 접근하며 viewer는 계정별 허용 여행의 확정 Google 회계 내용만 읽는다. 계정 생성이나 시트 이동으로 권한을 확대하지 않는다.

- 조건·예외: viewer/public 응답·JS 전역·로그에 타 여행·개인 원문을 노출하지 않는다. 고객 원문과 개인정보는 Git·공개 보고서·외부 모델에 무단 전송하지 않는다.
- 출처: `docs/specs/google-expense-mn-reconciliation-20261030.md:46`, `docs/specs/refactor-master-20261027.md:25`, `docs/specs/google-ledger.md:400`, `docs/specs/google-ledger.md:405`, `docs/specs/google-ledger.md:419`

### GGL-020 · M:N 금액 그룹 대조

*일반 · 결정 2026-10-30*

동일한 실제 여행 ID와 정확한 signed 원화 금액으로 COST·Google 지출을 그룹화하고 모든 m×n 후보 관계를 조회한다. 날짜·가맹점·분류·메모를 이 표시용 관계의 키로 요구하지 않는다.

- 조건·예외: 개별 거래 동일성 확정이나 중복 제거·자동 완료·복사 제외의 근거가 아니다.
- 출처: `docs/specs/google-expense-mn-reconciliation-20261030.md:5`, `docs/specs/google-expense-mn-reconciliation-20261030.md:15`, `docs/specs/google-expense-mn-reconciliation-20261030.md:16`, `docs/specs/google-expense-mn-reconciliation-20261030.md:21`, `docs/specs/google-ledger.md:671`

### GGL-021 · M:N 건수 판정

*일반 · 결정 2026-10-30*

양쪽 정상 최신 snapshot과 유효 여행 매핑에서 m>0이며 m=n이면 그룹 건수 일치, m>0·n=0이면 미기록, m=0·n>0이면 Google 전용으로 판정한다.

- 조건·예외: 건수 불일치는 부분 대조이며 임의 일부 행을 1:1 확정하지 않는다.
- 출처: `docs/specs/google-expense-mn-reconciliation-20261030.md:17`, `docs/specs/core-workflow-remaining-implementation-20261030.md:37`

### GGL-022 · 대조 불가

*보호*

Google 조회/권한·여행 매핑·파싱·신선도·통화/금액·지출 영역이 검증되지 않으면 대조 불가로 처리한다. 금액이 비슷하다고 정확 일치를 만들지 않는다.

- 출처: `docs/specs/google-expense-mn-reconciliation-20261030.md:20`, `docs/specs/sheet-manual-expense-dedup-20261029.md:50`

### GGL-023 · 대조 대상 실제 지출

*보호 · 결정 2026-10-30*

Google 대조에는 실제 지출 영역의 유효 원행만 사용하고 수입·합계·소계·빈 템플릿·수식 요약·중복 projection 행은 제외한다.

- 조건·예외: 실제 반복 결제는 각각 보존하며 원본 행 ID를 유지한다.
- 출처: `docs/specs/google-expense-mn-reconciliation-20261030.md:22`, `docs/specs/google-expense-mn-reconciliation-20261030.md:37`, `docs/specs/google-ledger.md:330`, `docs/specs/participants.md:499`, `docs/specs/ui.md:125`

### GGL-024 · 표시용 대조 비쓰기

*보호 · 결정 2026-10-30*

M:N 그룹 관계와 후보 표시는 읽기 전용이다. 확정 외래키·수동 결정·금융 링크·원문·복사 대상·완료 여부를 자동 변경하지 않는다.

- 조건·예외: 값·원본 선택·stale 상태가 변하면 관계 표시를 재계산한다.
- 출처: `docs/specs/google-expense-mn-reconciliation-20261030.md:40`, `docs/history/product-and-handoffs.md:486`

### GGL-025 · 수기 동일성 판정

*일반 · 결정 2026-10-29*

같은 유효 여행의 Google 수기 지출과 COST 원행은 정확 금액·통화·부호 및 날짜 의미·가맹점·설명·예약/카드 단서를 종합해 유일한 동일 거래임이 증명될 때만 연결한다.

- 조건·예외: 표시용 M:N 후보 관계만으로 수기 동일성을 확정하지 않는다.
- 출처: `docs/specs/sheet-manual-expense-dedup-20261029.md:35`, `docs/specs/sheet-manual-expense-dedup-20261029.md:37`, `docs/specs/sheet-manual-expense-dedup-20261029.md:39`

### GGL-026 · 수기 연결 예외와 충돌

*보호 · 결정 2026-10-29*

승인번호·카드 정보가 없어도 충분한 복합 근거로 유일하면 수기 동일 거래를 연결한다. 반복 결제·결제대행사 공통 표기·합산/분할·복수 후보·점유/원본 충돌은 자동 확정하지 않는다.

- 조건·예외: 날짜 허용 오차나 환율 추정만으로 정확 일치를 만들지 않는다.
- 출처: `docs/specs/sheet-manual-expense-dedup-20261029.md:40`, `docs/specs/sheet-manual-expense-dedup-20261029.md:41`, `docs/specs/sheet-manual-expense-dedup-20261029.md:42`

### GGL-027 · 기존 수기행 중복 복사 차단

*보호 · 결정 2026-10-29*

MATCHED_MANUAL 또는 MATCHED_EXISTING으로 확인한 지출은 신규 출력에서 제외하고 원문을 유지한다. REVIEW_CONFLICT·SOURCE_UNAVAILABLE도 중복 위험을 해소하기 전 신규 복사 대상으로 만들지 않는다.

- 조건·예외: M:N 표시용 그룹 일치와 실제 중복 제외 판정은 별개다.
- 출처: `docs/specs/card-and-sheet-reconciliation-status-20261029.md:11`, `docs/specs/sheet-manual-expense-dedup-20261029.md:20`, `docs/specs/sheet-manual-expense-dedup-20261029.md:46`, `docs/specs/sheet-manual-expense-dedup-20261029.md:47`, `docs/specs/sheet-manual-expense-dedup-20261029.md:50`

### GGL-028 · 연결과 내용 차이

*보호*

수기 동일성이 확정돼도 항목·날짜·메모 내용 차이는 보존·표시하고 원문 셀을 덮지 않는다. 내용 차이만으로 중복 지출 행을 추가하지 않는다.

- 출처: `docs/specs/card-and-sheet-reconciliation-status-20261029.md:11`, `docs/specs/sheet-manual-expense-dedup-20261029.md:109`

### GGL-029 · 수기 연결 영속 이력

*보호 · 결정 2026-10-29*

수기 행↔COST 거래 연결은 안정 거래/여행 ID·행 키/원문 fingerprint·근거·연결/재검증 시각·revision·감사 출처와 함께 로컬에 보존한다.

- 조건·예외: Google 열/메타데이터에 ID를 자동 기록하지 않는다.
- 출처: `docs/specs/sheet-manual-expense-dedup-20261029.md:61`, `docs/specs/sheet-manual-expense-dedup-20261029.md:62`, `docs/specs/sheet-manual-expense-dedup-20261029.md:64`

### GGL-030 · 복사 직전 재검증

*보호 · 결정 2026-10-30*

복사 전 최신 선택 Google snapshot과 수기행 대조를 수행하고 명확한 신규 지출만 출력한다. 원본 범위·revision/fingerprint가 달라지면 재대조한다.

- 조건·예외: snapshot이 stale·불완전·권한 오류이면 성공으로 처리하지 않는다.
- 출처: `docs/specs/lean-card-ota-core-20261030.md:25`, `docs/specs/sheet-manual-expense-dedup-20261029.md:10`, `docs/specs/sheet-manual-expense-dedup-20261029.md:77`, `docs/specs/sheet-manual-expense-dedup-20261029.md:79`, `docs/history/session_handoff-through-20261107.md:959`

### GGL-031 · 동시 복사 멱등

*보호*

동시 작업과 재전송은 기존 잠금·멱등·원자 연결 경로로 보호한다. 타임아웃·부분 실패 시 실제 적용 여부를 재확인하고 중복 기록하지 않는다.

- 출처: `docs/history/ota-legacy.md:313`, `docs/history/implementation-and-audits.md:1601`

### GGL-032 · 표준 출력 계약

*보호 · 결정 2026-10-11*

복사는 공식 양식_rev의 B:H 7열 계약을 따르고 현재 여행/구간의 검토된 실제 지출만 출력한다. 수입·수식·합계·기존 수기 이체 영역을 침범하지 않는다.

- 조건·예외: 양식의 열 의미·데이터 영역은 format_notes에 보존한다. 실제 지출 한 건당 한 행을 유지하고 서로 다른 실제 결제를 합산 출력하지 않는다.
- 대체된 옛 규칙:
  - 과거 실험은 여러 비용 후보의 합산 TSV 한 행 출력을 허용했다. 현재는 실제 한 결제의 복수 증빙인 경우에만 통합하고 서로 다른 결제는 각각 출력한다. — docs/specs/receipts.md:38
- 출처: `docs/specs/trip-header-alignment-20261105.md:7`, `docs/specs/ledger-sort-insurance-followup-20261030.md:5`, `docs/specs/open-pr-development-execution-20261030.md:5`, `docs/specs/google-ledger.md:96`, `docs/specs/google-ledger.md:98`

### GGL-033 · 구형 양식 복사 차단

*보호 · 결정 2026-10-11*

레거시 B:I 비연속 등 비표준 시트에 표준 7열 복사를 허용하거나 임의 레거시 변환을 만들지 않는다. 실제 헤더·영역이 표준 계약을 만족해야 복사한다.

- 조건·예외: 읽기 지원과 신규 출력 지원은 구별한다.
- 출처: `docs/specs/google-ledger.md:98`, `docs/specs/google-ledger.md:165`, `docs/specs/google-ledger.md:294`, `docs/specs/google-ledger.md:319`, `docs/specs/google-ledger.md:329`

### GGL-034 · 불확실 예약번호 금지

*보호*

추론·묶음 순서 배정만 있는 예약번호는 장부와 Google F열에 확정값으로 출력하지 않는다. 검증된 개별 예약번호만 전달한다.

- 조건·예외: 검증 서비스 기간과 파생 근거는 별도로 보존할 수 있다.
- 출처: `docs/specs/ota.md:88`, `docs/history/implementation-and-audits.md:926`, `docs/history/product-and-handoffs.md:1523`

### GGL-035 · 분기 비용 복사 목적지

*일반*

분기 기타비용은 원문 날짜의 연도·분기로 복사 목적지를 계산하되 원래 여행 귀속·금액은 보존한다. 기타비용 탭은 지출 전용이며 여행/수입 탭으로 만들지 않는다.

- 출처: `docs/specs/finance.md:171`, `docs/history/operations-through-20261027.md:1085`, `docs/history/operations-through-20261027.md:1087`

### GGL-036 · 개인카드 상환 중복

*보호*

개인카드 영수증 비용과 사후 상환 이체의 중복은 사용자가 Google 기존 내역을 보고 판단한다. COST가 자동 대사·상계·제외·별도 정산을 만들지 않는다.

- 출처: `docs/specs/google-ledger.md:127`, `docs/history/ota-legacy.md:473`

### GGL-037 · 수입 관계와 금액 분리

*보호 · 결정 2026-10-28*

참가자↔수입 연결은 로컬 관계 결정일 뿐 수입/이체 원장 수정·금액 자동 분배·행 생성·완납 확인이 아니다.

- 조건·예외: 금액은 선택된 Google 정본 사실만 사용한다.
- 출처: `docs/specs/insurance-trip-review-ux-20261031.md:8`, `docs/specs/implementation-status-audit-20261028.md:47`, `docs/specs/insurance-participant-integration-20261028.md:106`, `docs/specs/participant-income-authority-and-drag-link-20261028.md:82`, `docs/specs/participant-income-authority-and-drag-link-20261028.md:124`

### GGL-038 · 수입 합계 고유 원행

*보호*

수입 합계는 원본 수입행을 한 번씩만 합산하고 H 총액과 E:G 구성액을 중복 가산하지 않는다. 여러 참가자와 공동 연결돼도 금액을 복제하지 않는다.

- 조건·예외: 취소·환불·추가입금·실제 0원을 원문대로 보존한다.
- 출처: `docs/specs/participants.md:529`, `docs/specs/participants.md:530`

### GGL-039 · 항공권 정보 비회계

*보호*

항공권 요약은 별도 정보이며 수입/지출 합계·비용 장부·Google 복사·회계 CSV/TSV의 새 행으로 포함하지 않는다.

- 조건·예외: 예약과 카드 결제가 검증된 기존 실제 비용 원행은 별개다.
- 출처: `docs/specs/trip-flight-booking-overview-20261028.md:20`, `docs/specs/trip-flight-booking-overview-20261028.md:141`

### GGL-040 · 알 수 없는 증빙

*보호*

검증되지 않은 증빙값을 임의로 카드 등으로 바꾸거나 원문에 없는 증빙 종류를 만들어 출력하지 않는다. 날짜·금액·중복·내부 차단 오류는 복사에서 제외한다.

- 조건·예외: 기존 시트의 실제 증빙 표기값을 먼저 검증한다.
- 출처: `docs/specs/ledger-date-copy-hints-20261107.md:11`, `docs/specs/google-ledger.md:166`, `docs/history/session_handoff-through-20261107.md:20`, `docs/history/operations-20261028-20261107.md:1171`

### GGL-041 · 법인카드 비용 근거

*보호*

법인카드 비용은 국내·해외 매입 확정 자료로 판단하고 승인 내역은 보조 증거로 둔다. 승인·매입·동일 파일 재수신으로 비용을 중복 계상하지 않는다.

- 출처: `docs/specs/google-ledger.md:90`, `docs/specs/google-ledger.md:91`

### GGL-042 · 영수증 환산

*일반 · 결정 2026-10-11*

현금·회사 경비로 인정한 개인카드 영수증의 JPY는 1엔당 10원으로 간편 환산한다. 법인카드 실제 청구 KRW는 이 환율로 대체하지 않는다.

- 조건·예외: 원금·적용 환율·환산값을 구분한다. 입력의 Google 영역 분류를 그대로 유지한다.
- 출처: `docs/specs/google-ledger.md:136`

### GGL-043 · 여행 동률

*일반*

동일 조건의 실제 여행 후보가 둘 이상이면 수입-비용 차액이 큰 여행을 우선하고 근거와 당시 정본 금액 지문을 기록한다.

- 조건·예외: 사용자 수동 귀속·실제 이용기간·금융 보호가 우선한다.
- 출처: `docs/specs/participants.md:98`

### GGL-044 · 판정 실행 근거

*보호 · 결정 2026-11-05*

자동 판단은 실제 provider/model/run_id와 원본·시트/여행·규칙 지문, 근거·불확실성·출처를 보존한다.

- 조건·예외: P2 판단을 사용자 답변이나 실제 금융 사실로 위장하지 않는다.
- 출처: `docs/specs/autonomous-expense-cleanup-20261105.md:48`, `docs/specs/autonomous-expense-cleanup-20261105.md:57`
