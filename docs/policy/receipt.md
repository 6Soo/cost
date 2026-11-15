# 판정 규칙 — 영수증

> [판정 규칙집](../DECISION_POLICY.md)의 영역별 상세 규칙이다. 핵심 원칙과 읽는 법은 규칙집 본문에 있다.
> 규칙 ID는 바꾸지 않는다. 규칙을 고칠 때는 같은 ID의 내용을 고치고 옛 내용을 "대체된 옛 규칙"에 남긴다.
> "출처"의 파일과 줄 번호는 커밋 `b0340d0d`(2026-11-10) 기준이다. 그 뒤 줄어든 `AGENTS.md`·`docs/COST_V3_START_HERE.md`의 줄은 `git show b0340d0d:<경로>`로 본다. 그때의 `docs/specs/<파일>`은 지금 `docs/history/specs-20261110/<파일>`에 있다(절차서 두 개는 `docs/playbooks/`).

### RCPT-001 · 원본 저장과 판정 구분

*보호*

영수증 업로드 성공은 원본 저장 완료이며 AI 분석·비용 등록·카드 대사·Google 기장 완료가 아니다. 인식 성공도 비용 확정으로 승격하지 않는다.

- 출처: `docs/specs/receipt-unified-upload-ux-20261105.md:47`, `docs/history/ota-legacy.md:118`, `docs/history/ota-legacy.md:199`

### RCPT-002 · 사진·PDF 원본

*보호 · 결정 2026-11-05*

사진·PDF는 SHA·바이트와 PDF 원본↔페이지 관계를 보존한다. 페이지 이미지 hash가 같아도 원본 파일과 페이지를 같은 자료로 간주하지 않는다.

- 조건·예외: PDF는 기존 최대 5MiB·10페이지 제한을 따른다.
- 출처: `docs/specs/receipt-unified-upload-ux-20261105.md:44`, `docs/specs/receipt-unified-upload-ux-20261105.md:45`, `docs/specs/receipt-unified-upload-ux-20261105.md:102`

### RCPT-003 · 파일별 실패 독립

*보호*

혼합 다중 파일은 파일별 성공·실패·재시도·중복 상태를 유지한다. 한 파일 실패가 다른 파일의 성공을 덮거나 같은 원본을 중복 비용으로 만들지 않는다.

- 출처: `docs/specs/receipt-unified-upload-ux-20261105.md:46`

### RCPT-004 · 다중 영수증 분리

*일반*

A4 이미지/PDF 안의 서로 다른 실물 영수증은 개별 후보로 분리한다. 잘림·겹침·경계 불명확은 원문을 보존해 해당 후보만 확인하며 누락·중복 생성을 막는다.

- 조건·예외: 물품별 자동 분해와 실물 영수증별 분리를 구분한다.
- 출처: `docs/specs/google-ledger.md:114`, `docs/specs/google-ledger.md:115`

### RCPT-005 · 영수증별 한 비용

*일반 · 결정 2026-10-11*

별도 지시가 없으면 영수증 한 장은 비용 한 건이다. 품목 목록을 자동으로 여러 비용행으로 분해하지 않는다.

- 조건·예외: 서로 다른 실제 결제는 날짜·업체·금액이 같아도 독립적으로 보존한다.
- 출처: `docs/specs/google-ledger.md:365`, `docs/specs/google-ledger.md:117`, `docs/history/ota-legacy.md:580`

### RCPT-006 · 분석 후보와 원문

*보호*

상호·날짜·금액·통화·결제수단·원본 위치를 후보로 읽고 원본 이미지·추출텍스트·환산값을 분리 보존한다. 모델 출력은 검증할 데이터이며 비용 확정 명령이 아니다.

- 조건·예외: 같은 이미지 재처리로 중복 후보를 늘리지 않는다.
- 출처: `docs/specs/google-ledger.md:118`, `docs/specs/participants.md:484`, `docs/specs/participants.md:611`, `docs/specs/receipts.md:36`

### RCPT-007 · 합계 판독

*보호*

영수증 최종 결제금액은 합계·지급 현금·거스름돈·세금·할인·취소를 구분해 판독한다. 총액/통화가 불명확하면 임의 0원이나 확정 비용을 만들지 않는다.

- 조건·예외: 정상 거래 분류 완료 원칙으로 미검증 금액을 창작하지 않는다.
- 출처: `docs/specs/google-ledger.md:116`, `docs/specs/google-ledger.md:117`

### RCPT-008 · 재처리 멱등

*보호*

같은 원문 내용 지문의 파싱·추출 사실은 재사용하고 같은 이미지 재입력·분석으로 비용 후보와 출력행을 중복 생성하지 않는다.

- 출처: `docs/specs/google-ledger.md:118`, `docs/history/operations-through-20261027.md:1243`

### RCPT-009 · 현금 영수증

*일반*

현금 영수증은 독립 지출 후보로 처리하고 최종 Google 증빙은 실제 영수증으로 출력한다.

- 조건·예외: 검증된 거래 값·중복 보호·사용자 직접 복사 계약을 따른다.
- 출처: `docs/specs/google-ledger.md:126`, `docs/specs/google-ledger.md:127`

### RCPT-010 · 개인카드 비용 인정

*일반*

개인카드 영수증은 사용자가 회사 경비로 인정한 경우 독립 비용 후보가 된다. 법인카드 매입 거래 및 사후 상환 이체와 구분한다.

- 조건·예외: 회사 경비 인정 자체를 이름·OCR 결과로 대신 결정하지 않는다.
- 출처: `docs/specs/google-ledger.md:55`, `docs/specs/google-ledger.md:127`

### RCPT-011 · 법인카드 증빙 연결

*보호*

법인카드 영수증은 기존 매입 거래를 대표 비용으로 두고 증빙/설명만 연결한다. 이미 기록된 카드 매입과 동일 거래면 두 번째 비용행을 만들지 않는다.

- 조건·예외: 카드 매입과 승인 증거·영수증을 별도 비용으로 누적하지 않는다.
- 출처: `docs/specs/core-workflow-remaining-implementation-20261030.md:5`, `docs/specs/google-ledger.md:97`, `docs/specs/google-ledger.md:128`, `docs/specs/receipts.md:39`, `docs/history/ota-legacy.md:471`

### RCPT-012 · 카드 청구 KRW 우선

*보호*

법인카드 비용은 카드 실제 청구 원화와 원금·수수료를 보존한다. 영수증 JPY 간편 환산값으로 덮거나 환산액을 추가 비용으로 기록하지 않는다.

- 출처: `docs/specs/google-ledger.md:92`, `docs/specs/google-ledger.md:128`

### RCPT-013 · JPY 간편 환산

*일반 · 결정 2026-10-11*

현금·회사 경비로 인정한 개인카드 영수증은 JPY 1엔당 KRW 10원으로 간편 환산한다. 엔화 원금·적용 환율·산출 원화를 구분해 보존한다.

- 조건·예외: 법인카드 실제 청구 원화 및 세무상 법정환율과 다르다.
- 출처: `docs/specs/google-ledger.md:136`, `docs/specs/google-ledger.md:137`

### RCPT-014 · 원화 영수증

*일반*

KRW 영수증은 검증된 원화 금액 그대로 처리하고 JPY 간편 환율을 적용하지 않는다.

- 조건·예외: 원문 통화와 금액을 먼저 검증한다.
- 출처: `docs/specs/receipts.md:39`, `docs/history/ota-legacy.md:313`

### RCPT-015 · 늦게 도착한 카드 근거

*보호*

독립 영수증 비용 후보와 같은 법인카드 근거가 나중에 도착하면 중복 복사를 차단하고 원문·기존 연결 식별 근거를 유지한다. 카드가 잠시 보이지 않거나 상호/일자가 바뀌어도 현금 비용으로 재계상하지 않는다.

- 조건·예외: 증빙으로 연결할 때 새 비용을 추가하지 않는다.
- 출처: `docs/history/ota-legacy.md:183`, `docs/history/ota-legacy.md:244`, `docs/history/ota-legacy.md:332`

### RCPT-016 · 중복 의심과 미검증

*보호*

카드 매입 미도착·복수 후보·금액 불일치·중복 의심·기록 보호가 있으면 독립 비용으로 추가하지 않고 내부 근거 검증을 유지한다.

- 조건·예외: 낮은 OCR 신뢰와 실제 금융 중복 위험을 구분한다.
- 출처: `docs/history/ota-legacy.md:262`, `docs/history/ota-legacy.md:287`

### RCPT-017 · 이력 조회 실패와 복사

*보호*

복사 이력을 읽지 못하면 중복 위험을 확인한 뒤 허용된 복사 경로로만 진행한다. 클립보드 성공과 복사 이력 저장 실패는 구분한다.

- 조건·예외: 사실 확인 없이 중복 안전을 보증하지 않는다.
- 출처: `docs/history/ota-legacy.md:272`

### RCPT-018 · 원본별 실제 거래 출력

*일반 · 결정 2026-10-11*

실제 카드/영수증 결제 한 건은 지출 한 행으로 출력하며 서로 다른 실제 결제를 묶지 않는다. 동일 카드 매입의 영수증은 그 행의 증빙으로만 붙인다.

- 조건·예외: 같은 실제 결제의 여러 증빙을 하나의 비용으로 다루는 것과 구분한다.
- 출처: `docs/specs/google-ledger.md:228`, `docs/specs/google-ledger.md:365`, `docs/history/ota-legacy.md:471`

### RCPT-019 · 개인카드 사후 상환

*보호*

개인카드 영수증을 기록한 뒤 회사가 이체 상환해도 사용자가 Google 기존 비용을 확인해 중복을 피한다. COST는 상환 이체를 자동 대사·상계·수정하지 않는다.

- 출처: `docs/specs/google-ledger.md:58`, `docs/specs/google-ledger.md:230`

### RCPT-020 · 외부 AI 명시 실행

*보호 · 결정 2026-11-05*

외부 AI/OCR 전송은 승인된 owner의 명시적 분석 실행과 해당 전송 동의가 있을 때만 한다. 업로드만으로 영수증·개인정보를 자동 전송하지 않는다.

- 조건·예외: 과거 특정 모델 승인을 모든 외부 모델 허가로 확대하지 않는다.
- 출처: `AGENTS.md:17`, `docs/specs/receipt-unified-upload-ux-20261105.md:49`, `docs/specs/google-ledger.md:119`

### RCPT-021 · AI 호출 권한

*보호*

AI 호출은 owner·CSRF·저장 사진 소유 검증을 통과한 요청에 한정한다.

- 출처: `docs/specs/full-ux-audit-20261101.md:22`, `docs/specs/receipts.md:62`

### RCPT-022 · AI 격리

*보호*

승인된 원본 하나만 분석에 전달하고 읽기 전용 격리 에이전트로 파일·shell·웹·MCP 작업을 차단한다. 영수증 이미지의 지시를 운영 명령으로 실행하지 않는다.

- 조건·예외: 모델 출력은 금융/장부 쓰기 명령이 아니다.
- 출처: `docs/specs/receipts.md:59`, `docs/specs/receipts.md:60`

### RCPT-023 · AI 실패 수동 입력

*일반 · 결정 2026-11-05*

AI가 미설정·실패·타임아웃·빈 결과를 반환하면 원본 미리보기와 직접 입력 경로를 유지한다.

- 조건·예외: 오류를 분석 완료나 비용 등록 성공으로 표시하지 않는다.
- 출처: `docs/specs/receipt-unified-upload-ux-20261105.md:48`

### RCPT-024 · 여행 선택 권한

*보호*

영수증 판독 모델은 여행명을 추론·생성하지 않는다. 사진에 적힌 여행명은 읽은 그대로 옮기고, 대상 여행은 사용자 지정이 먼저이며 없을 때만 RCPT-030으로 정한다.

- 조건·예외: P1/P2 카드 귀속 계약과 별도인 영수증 모델의 권한 범위다.
- 대체된 옛 규칙:
  - 영수증의 대상 여행은 사용자가 지정한다. — 2026-11-15 소유자 지시로 사진 상단 여행명 자동 분류를 허용(RCPT-030). 모델이 여행을 추론하지 않는다는 보호는 유지한다.
- 출처: `docs/specs/receipts.md:33`

### RCPT-025 · 개인정보와 원본 접근

*보호*

영수증 사진·PDF·실명·금액·비밀값은 Git·공개 PR/CI 아티팩트·무권한 viewer 응답에 포함하지 않는다.

- 조건·예외: 원본은 비공개 보호 저장소에서 권한 있는 사용자만 접근한다.
- 출처: `docs/specs/receipt-unified-upload-ux-20261105.md:75`, `docs/specs/participant-income-authority-and-drag-link-20261028.md:119`, `docs/specs/google-ledger.md:406`, `docs/history/session_handoff-through-20261107.md:943`, `docs/history/operations-through-20261027.md:755`

### RCPT-026 · Google 수동 경로

*보호*

영수증 비용은 COST 검토 후 사용자가 Google에 복사해 붙여넣는다. 영수증 등록·후보 저장·복사는 Google 자동 쓰기 권한을 만들지 않는다.

- 출처: `AGENTS.md:47`, `docs/specs/ota.md:26`, `docs/specs/google-ledger.md:51`, `docs/specs/google-ledger.md:54`, `docs/specs/google-ledger.md:68`

### RCPT-027 · 메일 사실과 영수증 구분

*보호*

예약 안내·연결된 메일·예정 결제는 실제 결제 영수증과 구분한다. 개별 금융 증거 없이 취소·추가 청구·가승인을 확정 비용이나 환급으로 해석하지 않는다.

- 조건·예외: 같은 예약·명시 결제일·통화·금액과 출처를 확인한다.
- 출처: `docs/history/operations-20261028-20261107.md:1311`, `docs/history/product-and-handoffs.md:317`, `docs/history/product-and-handoffs.md:366`, `docs/history/operations-through-20261027.md:866`, `docs/history/ota-legacy.md:1362`

### RCPT-028 · 보존되는 금융 경계

*보호*

영수증 분석·등록·UI 변경으로 카드 중복·환불·수동 교정·원본·권한·원자성 보호를 완화하지 않는다.

- 대체된 옛 규칙:
  - 사용자 확인함·대기/보류 작업의 화면·상태 계약은 폐지됨. 원문의 금융/원본/감사 보호 부분은 계속 유지한다. — 2026-11-05, docs/specs/unified-expense-action-queue-20261105.md:330
- 출처: `docs/specs/receipt-unified-upload-ux-20261105.md:6`, `docs/specs/unified-expense-action-queue-20261105.md:140`, `docs/specs/unified-expense-action-queue-20261105.md:204`, `docs/specs/unified-expense-action-queue-20261105.md:330`, `docs/specs/open-pr-development-execution-20261030.md:7`

### RCPT-029 · 참가 명단 원본 최소화

*보호 · 결정 2026-10-28*

구조화 참가 명단에는 주민번호·생년월일·전화번호·여권·성별을 전달하지 않는다. 민감 정보가 포함될 수 있는 원본 사진은 기존 비공개 보관소에서만 제한 접근한다.

- 조건·예외: 입력 area가 영수증인 원문 보호 진술의 분류를 그대로 유지한다.
- 출처: `docs/specs/insurance-participant-integration-20261028.md:53`

### RCPT-030 · 사진 상단 여행명 자동 분류

*일반 · 결정 2026-11-15*

영수증은 여행을 지정하지 않아도 올릴 수 있으며, 사진 상단(위쪽 약 20%)에 적힌 여행명이 Google 시트 여행 탭 이름(`0625_아키타`)과 정확히 한 여행으로 맞으면 그 여행에 귀속한다. 여행명이 없거나 여러 여행에 맞으면 영수증 날짜가 기간에 드는 여행이 하나일 때만 그 여행으로 하고, 그래도 못 정하면 여행 미정으로 둔다.

- 조건·예외: 우선순위는 사용자 지정(`manual`) > 상단 여행명(`header_text`) > 영수증 날짜(`date`)다. 숫자 접두·밑줄·공백·전각 차이와 지역명만 쓴 경우를 같은 이름으로 본다. 판정 출처와 인식한 원문 여행명은 후보에 저장하고 렌더 때 다시 계산하지 않는다. 여행명 줄은 상호로 읽지 않는다. 종료일 없는 여행은 다음 여행 직전일까지로 본다. 새 확인 화면을 만들지 않으며 미정은 후보 표의 여행 선택으로 고친다.
- 예시: 상단 `0625_아키타`, 날짜 2027-06-26 → 아키타 여행(`header_text`). 상단 `도쿄`만 있고 도쿄 여행이 둘이면 날짜가 든 쪽(`date`), 둘 다 들면 미정.
- 출처: 소유자 지시 2026-11-15
