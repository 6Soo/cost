# 판정 규칙 — 수집·원본

> [판정 규칙집](../DECISION_POLICY.md)의 영역별 상세 규칙이다. 핵심 원칙과 읽는 법은 규칙집 본문에 있다.
> 규칙 ID는 바꾸지 않는다. 규칙을 고칠 때는 같은 ID의 내용을 고치고 옛 내용을 "대체된 옛 규칙"에 남긴다.

### SRC-001 · 원본 불변

*보호*

카드 원행·금액·통화·날짜·식별자와 원본 파일을 보존한다. 분류·귀속 교정은 원문 수정과 분리해 이력으로 남긴다.

- 출처: `AGENTS.md:5`, `AGENTS.md:30`, `AGENTS.md:35`, `AGENTS.md:41`, `docs/specs/autonomous-expense-cleanup-20261105.md:59`

### SRC-002 · 개인정보 외부 전송

*보호*

고객 원문·개인정보·카드 식별자·인증값·비공개 원본을 Git·공개 보고서·일반 로그·허가되지 않은 외부 모델에 전송하지 않는다.

- 출처: `AGENTS.md:30`, `docs/specs/remaining-workspace-integration-20261108.md:35`, `docs/specs/review-all-uncommitted-release-20261108.md:5`, `docs/specs/cost-pr-only-implementation-brief-20261106.md:138`, `docs/specs/airline-mail-collection-20261105.md:10`

### SRC-003 · 인증 보호

*보호*

인증 우회·보안 입력 속성 변경·저장 암호 조회·반복 인증 제출을 하지 않는다. 암호·OTP·개인키는 읽거나 출력하지 않는다.

- 출처: `AGENTS.md:30`, `docs/card_downloads.md:18`, `docs/card_downloads.md:20`, `docs/card_downloads.md:21`

### SRC-004 · 수집 범위

*보호*

카드 수집은 사용자가 지정한 카드사·자료 종류·기간에 한정한다. 원본 다운로드 허가는 금융 DB 입력·장부 기록·새 연결 허가로 확대하지 않는다.

- 출처: `docs/specs/sheet-manual-expense-dedup-20261029.md:80`, `docs/specs/finance.md:543`, `docs/card_downloads.md:5`, `docs/card_downloads.md:57`, `docs/card_downloads.md:65`

### SRC-005 · 매입 원본 우선

*일반*

비용과 취소 전표는 국내·해외 매입 원본으로 판정한다. 승인 내역은 보조 증거이며 승인과 매입을 합쳐 비용을 늘리지 않는다.

- 출처: `docs/specs/finance.md:527`, `docs/specs/finance.md:565`, `docs/specs/participants.md:44`, `docs/history/operations-through-20261027.md:219`, `docs/history/product-and-handoffs.md:1340`

### SRC-006 · 매입일 조회

*일반*

매입 자료는 매입일 기준으로 겹치는 기간을 재조회하며 지연 매입·취소가 의심되면 범위를 넓힌다. 원승인일이 조회기간 밖이어도 해당 매입 행은 보존한다.

- 조건·예외: 카드사별 조회 기준을 동일하다고 가정하지 않는다.
- 출처: `소유자 지시 메모:project-2025-unpaired-cancels.md:17`, `docs/specs/finance.md:555`, `docs/card_downloads.md:32`, `docs/card_downloads.md:9`, `docs/card_downloads.md:34`

### SRC-007 · 다운로드 파일 보존

*보호*

새 다운로드는 기존 원본을 덮어쓰지 않고 보존한다. 실제 파일 형식·파일명·보존 경로·크기·SHA-256을 검증해 원본 확보 여부를 판정한다.

- 출처: `docs/specs/finance.md:597`, `docs/card_downloads.md:50`, `docs/card_downloads.md:54`

### SRC-008 · 국내 취소 해석

*일반*

국내 거래는 승인금액과 상태를 함께 읽고, 국내외 승인구분을 취소 상태로 오인하지 않는다. 취소번호와 원승인번호는 분리 보존한다.

- 출처: `docs/specs/finance.md:560`

### SRC-009 · 해외 청구 금액

*보호*

해외 비용은 원본 총결제금액을 사용하고 결제원금·수수료를 별도 보존하며 총액=원금+수수료를 검사한다. 수수료 재가산이나 임의 환율 재계산을 하지 않는다.

- 조건·예외: 영수증 현금·승인 개인카드의 JPY×10 환산과 법인카드 청구 원화는 구분한다.
- 출처: `docs/specs/finance.md:561`, `docs/specs/google-ledger.md:137`, `docs/specs/google-ledger.md:138`, `docs/card_downloads.md:56`, `docs/history/ota-legacy.md:474`

### SRC-010 · 해외 취소 방향

*일반*

해외 취소는 원문 결제방법 등 실제 취소 근거로 식별한다. 원문은 유지하고 정규화된 취소 효과만 음수로 표현하며 상세 취소행을 누락하지 않는다.

- 출처: `docs/specs/finance.md:562`, `docs/card_downloads.md:56`

### SRC-011 · 승인 취소와 환불

*보호*

승인 취소와 취소매입은 별개 사실이다. 매입되지 않은 승인 취소를 새 환불 비용으로 만들거나 환불 효과를 두 번 계상하지 않는다.

- 조건·예외: 대응 양수 원행·실제 매입 환불의 증거가 필요하다.
- 출처: `docs/specs/finance.md:61`, `docs/specs/finance.md:538`, `docs/specs/finance.md:579`, `docs/history/session_handoff-through-20261107.md:1088`, `docs/history/operations-through-20261027.md:647`

### SRC-012 · 승인번호 없는 거래

*보호*

해외 원본의 승인번호 부재는 정상일 수 있으므로 번호를 만들지 않는다. 동일 원본 재수신은 파일 해시와 행 위치로 구분하고 실제 복수 거래의 다중도는 보존한다.

- 조건·예외: 같은 날짜·가맹점·금액이라는 이유만으로 합치지 않는다.
- 출처: `docs/specs/finance.md:563`, `docs/specs/finance.md:564`, `docs/card_downloads.md:56`, `docs/history/operations-through-20261027.md:35`, `docs/history/operations-through-20261027.md:150`

### SRC-013 · 원천 동일성과 재수신

*보호*

동일 파일·동일 원천행 재수신은 기존 결과를 재사용한다. 다른 파일의 동일 거래는 원행을 덮지 않고 출처 관계만 추가하며 동일 ID의 다른 원문은 충돌로 처리한다.

- 조건·예외: 파일 포맷만 바뀐 CSV/XLS도 거래 동일성으로 대조한다.
- 출처: `docs/specs/finance.md:266`, `docs/specs/card-upload-management-ux-20261105.md:212`, `docs/specs/card-upload-management-ux-20261105.md:265`, `docs/specs/unified-expense-action-queue-20261105.md:184`, `docs/specs/card-upload-full-reconciliation-20261029.md:54`

### SRC-014 · 업로드 대사 집계

*일반*

원천행은 기존 일치·신규·충돌/모호·파일 내부 중복으로 구분하며 확실한 신규만 등록한다. 원천행 수와 고유 거래 수를 구분하고 중복 저장을 만들지 않는다.

- 출처: `docs/specs/card-upload-management-ux-20261105.md:87`, `docs/specs/unified-expense-action-queue-20261105.md:192`, `docs/specs/upload-results-recovery-20261105.md:14`, `docs/specs/jeju-ota-card-scope-20261103.md:18`, `docs/specs/card-upload-full-reconciliation-20261029.md:15`

### SRC-015 · 다른 거래 종류

*일반*

현금서비스·리버설 등은 원문과 금액을 보존해 별도로 판정한다. 모든 행을 일반 여행 비용이나 환불로 자동 간주하지 않는다.

- 출처: `docs/specs/finance.md:566`

### SRC-016 · 조회 공백 계산

*일반 · 결정 2026-11-08*

수집 현황의 기본 범위는 파일별 최초~최종 거래일 전체이며 같은 카드사의 모든 카드 파일 범위를 합집합한다. 파일 내부 무거래일을 제외하고 떨어진 파일 범위 사이만 공백으로 계산한다.

- 조건·예외: 실제 카드사 조회 완료 증빙을 새로 확정하는 규칙이 아니다.
- 예: 파일 A의 거래가 1일·10일, 파일 B가 15일·20일이면 파일 범위는 1~10일·15~20일이고 공백은 11~14일이다.
- 대체된 옛 규칙:
  - 과거 수집 현황의 기본 범위 계산·관리 방식에 한정해 대체됨: 카드사·끝4자리 표시 그룹별 첫/마지막 거래일 내부만 계산하며, 정상 미사용일일 수 있으므로 자료 누락으로 단정하지 않는다. (원문 조회 조건·실제 조회 완료 증빙 보호는 유지) — 2026-11-08, docs/operations.md:180
  - 과거 수집 현황의 기본 범위 계산·관리 방식에 한정해 대체됨: 기존 조회기간과 대조해 누락·겹침·중복·확인 불가 구간을 구분한다. (원문 조회 조건·실제 조회 완료 증빙 보호는 유지) — 2026-11-05, docs/specs/card-upload-management-ux-20261105.md:30
  - 과거 수집 현황의 기본 범위 계산·관리 방식에 한정해 대체됨: 거래일 최소·최대값으로 조회기간을 추정하지 않는다. (원문 조회 조건·실제 조회 완료 증빙 보호는 유지) — 2026-11-05, docs/specs/card-upload-management-ux-20261105.md:33
  - 과거 수집 현황의 기본 범위 계산·관리 방식에 한정해 대체됨: 거래일 MIN/MAX로 조회기간을 추정하지 않으며, 0건 조회도 카드·기간·기준·전체조회 증거가 있으면 유효하다. (원문 조회 조건·실제 조회 완료 증빙 보호는 유지) — 2026-11-05, docs/specs/card-upload-management-ux-20261105.md:34
  - 그 밖에 16건
- 출처: `docs/specs/card-transaction-date-gaps-20261108.md:5`, `docs/specs/card-transaction-date-gaps-20261108.md:9`, `docs/specs/card-transaction-date-gaps-20261108.md:11`, `docs/specs/card-upload-management-ux-20261105.md:30`, `docs/specs/card-upload-management-ux-20261105.md:33`

### SRC-017 · 조회 공백 날짜축

*일반 · 결정 2026-11-08*

파일 범위 계산은 approval_date를 우선하고 비어 있으면 posting_date를 사용하며 잘못된 날짜는 제외한다.

- 조건·예외: 여행 배정 날짜와 실제 결제일의 의미를 바꾸지 않는다.
- 출처: `docs/specs/card-transaction-date-gaps-20261108.md:10`

### SRC-018 · 조회 공백 경계

*보호 · 결정 2026-11-08*

공백 계산에서 다른 카드사는 합치지 않고 카드사 미상 자료는 파일별로 분리한다. 전체 양끝 바깥을 누락으로 추정하거나 파일 사이 공백을 실제 자료 누락으로 확정하지 않는다.

- 조건·예외: 겹치거나 바로 이어지는 범위는 합친다.
- 출처: `docs/specs/card-transaction-date-gaps-20261108.md:11`, `docs/specs/card-transaction-date-gaps-20261108.md:12`

### SRC-019 · 조회 증빙 보존

*보호 · 결정 2026-11-08*

원문 조회 조건과 실제 거래 발생기간은 서로 다른 사실로 보존한다. 공백 계산은 기존 조회 증빙·원행 중복·금융 집계를 바꾸거나 조회 완료를 소급 생성하지 않는다.

- 조건·예외: 최신 파일 범위 계산은 기존 증빙 테이블·보호 API의 보존과 양립한다.
- 출처: `docs/specs/card-transaction-date-gaps-20261108.md:12`, `docs/specs/card-transaction-date-gaps-20261108.md:15`, `docs/specs/card-coverage-pending-review-ux-20261107.md:16`, `docs/specs/card-upload-management-ux-20261105.md:29`, `docs/specs/card-upload-management-ux-20261105.md:42`

### SRC-020 · 조회 증빙 적격

*보호*

실제 조회 완료 증빙은 명시적 기간·기준·카드 식별·전체조회·정상 파싱이 검증될 때만 인정한다. 빈 파일·부분 다운로드·제한조회·식별 충돌·파싱 오류만으로 정상 증빙을 만들지 않는다.

- 조건·예외: 수집 현황의 파일 MIN/MAX 기본 범위와 별개의 증거 검증 계약이다.
- 출처: `docs/specs/card-coverage-pending-review-ux-20261107.md:9`, `docs/specs/card-coverage-pending-review-ux-20261107.md:10`, `docs/specs/card-coverage-pending-review-ux-20261107.md:18`, `docs/specs/card-upload-management-ux-20261105.md:32`, `docs/specs/card-upload-management-ux-20261105.md:209`

### SRC-021 · 성공 파일 독립 보존

*보호*

중복 업로드는 새 거래를 만들지 않으며 한 파일 실패가 다른 파일의 성공이나 증빙을 지우지 않는다. 파일별 실패·재시도 결과는 구분한다.

- 출처: `docs/specs/cost-pr-only-implementation-brief-20261106.md:55`, `docs/specs/receipt-unified-upload-ux-20261105.md:46`, `docs/specs/finance.md:30`

### SRC-022 · 원문 관측 버전

*보호*

동일 출처 식별자·동일 원문은 재삽입하지 않는다. 변경된 원문은 별도 관측/revision으로 추가해 원문·정규화 해시·출처·관측시각·파서 버전과 과거 이력을 보존한다.

- 조건·예외: 관측 중복 제거를 실제 복수 결제 제거로 확대하지 않는다.
- 출처: `docs/specs/ota.md:20`, `docs/specs/ota.md:22`, `docs/specs/ota.md:679`, `docs/specs/ota.md:680`, `docs/specs/ota.md:714`

### SRC-023 · 예약과 이벤트 식별

*보호*

예약 통합 키는 공급자·계정·예약번호이며 상태 변화·상충 금액·기간·취소·환불은 이벤트로 보존한다. 결제 이벤트 ID에는 변경 가능한 금액·날짜·카드 끝자리·예약 참조·digest를 넣지 않는다.

- 출처: `docs/history/implementation-and-audits.md:150`, `docs/history/implementation-and-audits.md:212`, `docs/history/ota-legacy.md:672`

### SRC-024 · 출처 사본 통합

*보호*

복구 사본은 동일 원본 record ID와 결제 근거가 검증될 때만 합친다. 메일·포털 등 서로 다른 출처는 공통 검증 payment ID 또는 명시 출처 연결 근거가 있을 때만 합친다.

- 조건·예외: 경로·로컬 숫자 ID만 같다는 이유로 별도 자료를 합치지 않는다.
- 출처: `docs/specs/ota.md:544`, `docs/specs/ota.md:158`, `docs/specs/ota.md:312`, `docs/history/ota-legacy.md:675`, `docs/history/ota-legacy.md:676`

### SRC-025 · 원본 계보

*보호*

최초 증거의 lineage와 기존 이벤트 ID·사용자 pin을 유지하며 출처 경로 변경을 새 결제로 세지 않는다. 교차 식별이 미해결이면 기존 연결을 유지하고 미해결 사실을 남긴다.

- 출처: `docs/specs/andre-multi-owner-ledger-20261101.md:16`, `docs/specs/ota.md:158`, `docs/specs/ota.md:294`, `docs/specs/ota.md:683`, `docs/history/implementation-and-audits.md:139`

### SRC-026 · 원문 보관 위치

*보호*

기존 원본 파일·메일·포털 행은 이동·삭제·덮어쓰기하지 않고 참조한다. 원문 JSON 추가 메타데이터와 파서 이력도 보존한다.

- 출처: `docs/specs/ota.md:679`, `docs/specs/ota.md:682`, `docs/history/product-and-handoffs.md:1593`, `docs/history/operations-through-20261027.md:1291`, `docs/history/operations-through-20261027.md:1316`

### SRC-027 · 참고 자료 권위

*보호*

해시가 적힌 보고서·과거 사본·참고 문서는 원문과 인증 근거를 검증하기 전 결제·일정 권위로 승격하지 않는다.

- 조건·예외: 최신 원본 또는 동등한 공식 일정 근거가 필요하다.
- 출처: `docs/specs/finance.md:222`, `docs/specs/finance.md:279`, `docs/specs/ota.md:685`, `docs/history/ota-legacy.md:1320`, `docs/history/ota-legacy.md:1554`

### SRC-028 · 원본 소실

*보호*

원본이 사라지거나 검증에 실패하면 저장 snapshot과 근거 누락·변경 상태를 반환한다. 과거 자료를 최신으로 표시하거나 실패를 예약 없음으로 바꾸지 않는다.

- 출처: `docs/specs/ota-review-queue-performance-20261027.md:146`, `docs/specs/trip-flight-booking-overview-20261028.md:148`, `docs/history/operations-through-20261027.md:478`, `docs/history/ota-legacy.md:704`, `docs/history/product-and-handoffs.md:1953`

### SRC-029 · 원문 금액과 빈값

*보호*

외화 원문 금액·통화·소수 정밀도·빈 날짜·빈 카드 식별자는 원문대로 유지한다. 환산값·카드 원행·관측시각을 써서 원문에 없는 값을 채우지 않는다.

- 조건·예외: 승인일·매입일·서비스 기간을 미상의 OTA 실제 결제일 대용으로 넣지 않는다.
- 출처: `docs/specs/flight-booking-compact-spa-20261104.md:22`, `docs/specs/ota.md:32`, `docs/specs/finance.md:448`, `docs/specs/google-ledger.md:640`, `docs/specs/google-ledger.md:642`

### SRC-030 · 미지원 자료

*보호*

미검증 취소·캐시·복합 결제 형식은 원문과 미지원 이유를 남긴다. 사실을 창작하거나 임의 정규화로 지원 형식에 맞추지 않는다.

- 출처: `docs/specs/ota.md:201`, `docs/history/implementation-and-audits.md:924`, `docs/history/implementation-and-audits.md:234`

### SRC-031 · 메일 공급자 검증

*보호*

메일은 발신 인증과 예약·결제·이용기간·원문 digest를 대조하고 공급자별 결제 해석을 분리한다. 단순 예약 안내·예정 결제를 결제 영수증으로 승격하지 않는다.

- 조건·예외: 변경·취소 메일도 같은 공급자·예약의 계보로 묶는다.
- 출처: `docs/specs/airline-mail-collection-20261105.md:5`, `docs/history/operations-through-20261027.md:370`, `docs/history/operations-through-20261027.md:1526`, `docs/history/operations-through-20261027.md:1532`, `docs/history/ota-legacy.md:1350`

### SRC-032 · 예약 관측과 금융 사실

*보호*

예약 원문 수집·관측 적재는 결제 확정·금융 링크·장부 기록·실제 환급 확인이 아니다.

- 출처: `docs/specs/ota.md:26`, `docs/history/product-and-handoffs.md:1108`

### SRC-033 · M:N 예약 관계

*일반 · 결정 2026-11-01*

OTA↔카드 관계는 M:N이며 결제일 미상도 가맹점명/확장명·같은 통화 정확 금액·끝4가 일치하면 연결한다. 관계 건수나 예약별 유일성으로 제한하지 않고 카드 원행은 한 번만 집계한다.

- 조건·예외: 명시 카드·공급자 충돌·원본 오류·수동 링크·환불 보호는 유지한다.
- 대체된 옛 규칙:
  - 결제일이 없는 아고다 연결에 관한 2026-10-21 사용자 승인: 전체 자료에서 정확한 카드 끝자리·원문 금액으로 카드와 예약이 서로 유일하게 대응하고, 검증된 이용기간이 있으며 취소·환불·기간 충돌이 없으면 `ota_inference.unique_pairs`로 추론 연결한다. — 2026-10-21, docs/specs/finance.md:338
- 출처: `AGENTS.md:35`, `docs/specs/unified-expense-action-queue-20261105.md:41`, `docs/specs/ota-undated-many-to-many-20261101.md:13`, `docs/specs/finance.md:338`, `docs/history/session_handoff-through-20261107.md:724`

### SRC-034 · 검증 결제의 날짜 금액 연결

*일반 · 결정 2026-10-29*

검증된 결제일과 카드 이용일이 같고 같은 통화 원문 금액이 정확히 일치하면 추가 카드 끝자리·payment ID 부재만으로 연결을 막지 않는다.

- 조건·예외: 명시된 발급사·카드·동형 승인번호 충돌, 다른 공급자·중복·원문 오류·기존 점유는 차단한다.
- 대체된 옛 규칙:
  - 정상 원행의 발급사·카드 끝4자리 존재, 같은 승인번호·이용일·금액, 기존 전역 유일성/중복/점유 보호를 모두 충족한 경우에만 기존 코어가 카드 결제를 연결한다. — 2026-10-28, docs/specs/ota.md:46
  - 발신 도메인 인증, 예약번호, 실제 원화 결제액, 결제일과 원본 카드 행의 유일한 일치를 확인한다. — 2026-10-03, docs/specs/finance.md:269
- 출처: `docs/specs/finance.md:69`, `docs/specs/ota.md:30`, `docs/specs/ota.md:46`, `docs/specs/finance.md:269`, `docs/history/product-and-handoffs.md:896`

### SRC-035 · 예약별 사실 비약 금지

*보호*

동액 예약 묶음·객실별/합계 예약·반복 결제의 수량이나 합계 일치는 개별 예약↔결제 동일성을 증명하지 않는다. 실제 원행·개별 식별 근거를 보존하고 예약번호를 임의 배분하지 않는다.

- 조건·예외: M:N 관계 성립과 개별 결제 증명을 구분한다.
- 출처: `docs/specs/participants.md:335`, `docs/history/implementation-and-audits.md:1028`, `docs/history/ota-legacy.md:784`, `docs/history/implementation-and-audits.md:923`, `docs/history/ota-legacy.md:1266`

### SRC-036 · 명시 금융 충돌

*보호*

발급사·카드·동형 결제 ID 충돌, 설명되지 않은 금액/통화 불일치, 구매·환불 방향 모순, 중복·원본 오류·기존 점유는 자동 연결/기록에서 차단한다.

- 조건·예외: 낮은 여행 추론 신뢰와 실제 금융 충돌은 구분한다.
- 출처: `docs/specs/cleanup-read-performance-20261102.md:7`, `docs/specs/ota-undated-many-to-many-20261101.md:13`, `docs/specs/core-workflow-remaining-implementation-20261030.md:29`, `docs/specs/finance.md:69`, `docs/specs/ota.md:40`

### SRC-037 · 수동 및 점유 우선

*보호*

기존 사용자 OTA pin·수동 여행 이동·frozen group·수동 override와 점유 관계를 자동 대사·추론이 덮어쓰거나 재사용하지 않는다.

- 출처: `docs/specs/sheet-manual-expense-dedup-20261029.md:66`, `docs/specs/ota.md:613`, `docs/specs/finance.md:242`, `docs/specs/participants.md:47`, `docs/specs/participants.md:100`

### SRC-038 · 연결 추론과 내부 준비 분리

*일반*

정상 매입 원행의 금융 적격성과 여행이 확인되면 OTA 관계가 정확·추론·미연결 중 어느 것이어도 내부 비용 준비/미리보기를 허용한다. OTA 근거 자체를 못 읽어 금융 적격성을 판정할 수 없는 경우는 정상으로 간주하지 않는다.

- 조건·예외: 중복·원본 충돌·미해결 취소/환불은 보호한다.
- 대체된 옛 규칙:
  - 막힌 연결: 자동 배정하지 않고 사유와 함께 미연결로 둔다. — docs/history/ota-legacy.md:1252
  - 이용기간을 아는 행은 막힌 연결의 추론 배정도 막는다(결제 월로 다른 여행을 고르지 않는다, 2026-10-03 추론 규칙). — docs/history/ota-legacy.md:1252
- 출처: `docs/specs/ota.md:86`, `docs/specs/ota.md:245`, `docs/history/provisional-assignment-review-first-20261028.md:42`, `docs/history/provisional-assignment-review-first-20261028.md:53`, `docs/history/provisional-assignment-review-first-20261028.md:133`

### SRC-039 · 날짜 사용 목적

*일반*

카드 여행 배정은 이용일, 없으면 승인일을 사용하며 매입일을 이용일로 바꾸지 않는다. 실제 OTA 이용기간은 결제일 추론보다 우선한다.

- 조건·예외: 파일 공백 계산과 분기 기타비용의 명시 매입일 fallback은 별도 계약이다.
- 출처: `AGENTS.md:45`, `docs/specs/finance.md:88`, `docs/specs/finance.md:159`, `docs/specs/finance.md:108`, `docs/specs/finance.md:456`

### SRC-040 · 여행 권위

*일반*

여행은 검증된 Google 여행 탭에서만 선택하고 원문 제목의 연도·기간과 수동 교정을 보존한다. 종료일이 없으면 다음 여행 직전일까지이며 없는 여행이나 기간을 만들지 않는다.

- 조건·예외: 과거 모집글 댓글 수만으로 여행을 만들던 경로는 현재 여행 생성 권위가 아니다.
- 대체된 옛 규칙:
  - 여행글 등록 자체로 금액 내역을 만들지 않으며 기존 카드 원문과 분류 결과는 보존한다. — 2026-10-27, docs/history/operations-through-20261027.md:325
  - 답글·후기·완료 공지를 모집글로 사용하지 않는다. — docs/specs/finance.md:295
  - 등록 후 댓글이 5개 미만으로 줄거나 일정이 바뀌면 확인 필요 표시를 남기고 여행과 비용을 삭제하지 않는다. — docs/specs/finance.md:299
- 출처: `AGENTS.md:45`, `docs/specs/finance.md:112`, `docs/specs/finance.md:215`, `docs/specs/finance.md:297`, `docs/specs/finance.md:295`

### SRC-041 · 분기 종결

*일반 · 결정 2026-11-08*

P1/P2로 실제 여행에 귀속시키고 해결되지 않은 정상 일반 비용은 원문 결제일, 없으면 유효한 매입일의 분기 기타비용으로 종결한다. 원본 날짜/금액 오류가 있으면 가짜 분기를 만들지 않고 내부 안전 차단을 남긴다.

- 조건·예외: 금융 보호 잠금·수동 결정·실제 여행의 우선순위는 유지한다.
- 대체된 옛 규칙:
  - 모호한 귀속은 HOLD하며 원문 날짜·금액·거래 ID를 규칙으로 변경하지 않는다. — docs/specs/google-ledger.md:93
  - 유효 후보 없음·실제 동률·원문 충돌·수동 보류는 해결할 근거가 필요한 상태로 유지한다. — 2026-10-29, docs/specs/finance.md:92
  - `CONFLICT_REVIEW`; 동점 후보·원본 날짜 충돌·확정된 다른 권위 충돌; 거래·후보는 보여 주되 임의 최종 배정 금지 — 2026-10-28, docs/history/provisional-assignment-review-first-20261028.md:45
  - 두 여행 A/B가 같은 날, 보조 근거 없이 동률 → `CONFLICT_REVIEW`, 임의 한 곳 자동 쓰기 금지. — 2026-10-28, docs/history/provisional-assignment-review-first-20261028.md:167
  - 그 밖에 5건
- 출처: `docs/specs/card-destination-only-ux-20261108.md:8`, `docs/specs/card-transaction-date-gaps-20261108.md:14`, `docs/specs/finance.md:3`, `docs/specs/review-all-uncommitted-release-20261108.md:10`, `docs/specs/card-upload-management-ux-20261105.md:33`

### SRC-042 · 이전 기간 보존

*사용자 예외 · 결정 2026-10-13*

이미 완료한 이전 기간은 원본과 처리 이력을 보존하며 신규 카드·OTA 검토와 신규 전기에서 제외한다.

- 조건·예외: 문서에서 정한 2025년 및 2026년 1분기 완료 자료에 한정한다.
- 출처: `docs/specs/finance.md:159`, `docs/specs/finance.md:454`

### SRC-043 · 원문 결속 내부 잠금

*보호 · 결정 2026-11-08*

내부 금융 안전 잠금은 거래 ID·원문 hash·금융 사유에 결속한다. 원문 변경·환불/중복 충돌을 자동 또는 사용자 해제 화면으로 우회하지 않는다.

- 조건·예외: 충분한 근거와 현재 버전 검증을 통과하면 시스템이 해당 원인을 해결한다.
- 출처: `docs/specs/card-destination-only-ux-20261108.md:10`, `docs/specs/finance.md:5`, `docs/specs/unified-expense-action-queue-20261105.md:144`, `docs/specs/unified-expense-action-queue-20261105.md:323`, `docs/specs/eight-card-review-20261102.md:23`

### SRC-044 · 반복 요청 멱등

*보호*

같은 client_request_id와 같은 입력은 동일 결과를 돌리고 다른 입력 재사용은 오류로 처리한다. 원본 ID·hash·revision·사건 종류 기준으로 중복 처리와 감사 이벤트 중복을 막는다.

- 출처: `docs/specs/participant-income-authority-and-drag-link-20261028.md:108`, `docs/specs/participants.md:108`, `docs/specs/participants.md:480`, `docs/specs/participants.md:569`, `docs/history/ota-legacy.md:332`

### SRC-045 · 신선도와 내용 지문

*보호*

입력 변경은 SHA-256·원문 digest·신뢰 가능한 버전으로 판정하며 mtime만으로 동일성을 보증하지 않는다. 근거·여행 권위·규칙 버전 변경 시 영향을 받는 판정을 재평가한다.

- 출처: `docs/specs/autonomous-expense-cleanup-20261105.md:46`, `docs/specs/unified-expense-action-queue-20261105.md:244`, `docs/specs/webledger-idle-io-optimization-20261105.md:21`, `docs/specs/webledger-idle-io-optimization-20261105.md:65`, `docs/specs/refactor-master-20261027.md:109`

### SRC-046 · 읽기 부수효과 금지

*보호*

조회·목록·집계만으로 원본·분류·여행/참가자 연결·금융 링크·Google을 쓰거나 재기장하지 않는다.

- 조건·예외: 실제 변경은 기존 승인된 쓰기 경로에서만 수행한다.
- 출처: `docs/specs/participants.md:9`, `docs/history/operations-through-20261027.md:658`, `docs/history/operations-through-20261027.md:1127`, `docs/history/ota-legacy.md:156`, `docs/history/ota-legacy.md:165`

### SRC-047 · 원본 상세 접근

*보호*

원본 상세는 해당 원문의 개인정보까지 볼 권한이 있는 사용자에게만 제공한다. 허용되지 않은 viewer/public 응답·브라우저 전역·로그에 원문을 노출하지 않는다.

- 출처: `docs/specs/unified-expense-action-queue-20261105.md:167`, `docs/specs/participant-income-authority-and-drag-link-20261028.md:126`, `docs/specs/trip-flight-booking-overview-20261028.md:167`, `docs/specs/google-ledger.md:422`, `docs/specs/google-ledger.md:679`

### SRC-048 · 원문 충돌 저장 실패

*보호*

파일 교체·JSON·레코드 구조 검증 실패 시 원본을 초기화하지 않고 안전하게 실패한다. 같은 식별자의 다른 원문이나 설치 경합 실패도 기존 원문을 삭제하지 않는다.

- 출처: `docs/specs/cloud-mail-cutover.md:67`, `docs/specs/cloud-mail-cutover.md:77`, `docs/specs/ota.md:679`, `docs/history/ota-legacy.md:271`, `docs/history/product-and-handoffs.md:1875`

### SRC-049 · 금융 링크와 원본 독립

*보호*

OTA 모듈은 카드 원행 ID·금액·날짜를 수정하지 않으며 원본·예약 관계·분류·사용자 답변을 구분해 저장한다.

- 출처: `docs/specs/google-ledger.md:195`, `docs/specs/google-ledger.md:332`, `docs/specs/ota.md:247`, `docs/history/ota-legacy.md:120`

### SRC-050 · 이벤트 근거 보존

*보호*

이벤트별 카드 후보와 근거를 거래 ID만으로 중복 제거하지 않는다. 하나의 카드가 여러 이벤트에 제시될 수 있어도 비용 집계와 실제 점유는 한 원행 기준으로 보호한다.

- 출처: `docs/specs/ota-review-queue-performance-20261027.md:138`, `docs/history/product-and-handoffs.md:1789`, `docs/history/product-and-handoffs.md:1009`, `docs/history/product-and-handoffs.md:1390`

### SRC-051 · 항공권 날짜 근거

*일반 · 결정 2026-10-27*

명시 예약 생성일이 없는 항공권은 같은 공급자·예약번호의 인증 보관 메일 중 최초 수신일을 한국 날짜로 사용하고 최초 수신일 기준임을 구분한다. 공급사의 원본 생성일·결제일로 표시하지 않는다.

- 조건·예외: 명시 날짜·취소·여정/원문 충돌과 기존 수동 연결을 우선한다.
- 출처: `docs/specs/ui.md:631`, `docs/specs/ui.md:636`, `docs/specs/ui.md:652`, `docs/history/product-and-handoffs.md:38`, `docs/history/product-and-handoffs.md:227`

### SRC-052 · 항공권 여정 계보

*보호*

변경·취소 메일은 공급자+예약번호의 계보로 묶고 이벤트 ID·digest·최신 여정을 보존한다. 숫자를 맞추려고 없는 항공권을 만들거나 한 여정을 여행 간 중복 분할하지 않는다.

- 출처: `docs/specs/ota.md:5`, `docs/specs/trip-flight-booking-overview-20261028.md:21`, `docs/specs/trip-flight-booking-overview-20261028.md:43`, `docs/specs/trip-flight-booking-overview-20261028.md:53`, `docs/specs/trip-flight-booking-overview-20261028.md:64`

### SRC-053 · 금융 보호 불변

*보호*

자동화·화면 변경·성능 최적화로 원본·금액·ID·수동 교정·중복·환불·기존 금융 링크·권한·원자성 보호를 약화하지 않는다. 모든 신규 원행은 수집·무결성·동일성·금융 관계 검증을 거쳐 P1/P2가 판정한다.

- 출처: `docs/specs/uiux-full-audit-redesign-20261110.md:751`, `docs/specs/ledger-service-date-investigation-20261109.md:30`, `docs/specs/cost-pr-only-implementation-brief-20261106.md:70`, `docs/specs/airline-mail-collection-20261105.md:3`, `docs/specs/autonomous-expense-cleanup-20261105.md:49`

### SRC-054 · 무번호 해외 취소 짝

*보호 · 결정 2026-10-16*

승인번호 없는 취소는 같은 카드·가맹점·외화 통화·정확 외화 금액의 구매와 날짜 순서대로 짝짓는다. 대응 구매가 없거나 남는 취소·원문 충돌은 내부 금융 검증 대상으로 남긴다.

- 조건·예외: 원승인번호로 원결제가 검증된 1:N 환불에는 무번호 거래의 일대일 순서 규칙을 확장하지 않는다.
- 출처: `docs/specs/finance.md:563`

### SRC-055 · 미매입 자료와 형식

*보호*

매입 자료 입력 경로는 CSV·XLSX·바이너리 XLS를 읽되 매입일 없는 승인내역을 매입 비용으로 가져오지 않는다. 형식만 바뀐 재수신으로 새 거래를 만들지 않는다.

- 조건·예외: 승인 내역의 보조 증거 보존과 매입 비용 등록을 구분한다.
- 출처: `docs/specs/finance.md:490`, `docs/specs/finance.md:584`, `docs/history/operations-through-20261027.md:1136`

### SRC-056 · 참가 원본 항목 ID

*보호*

참가 명단은 roster_id+source_item_id와 원문 지문으로 식별하고 재촬영·순서 변경에도 identity를 유지한다. 이름이나 행 번호만 영구 ID로 쓰지 않는다.

- 조건·예외: 같은 배치 ID에 다른 내용은 충돌로 처리한다.
- 출처: `docs/specs/participant-income-authority-and-drag-link-20261028.md:125`, `docs/specs/participants.md:481`, `docs/specs/participants.md:500`

### SRC-057 · 명단 최소 정보

*보호*

구조화 참가 명단은 필요한 이름·명시 별칭·영문명·안정 항목 ID·원본 위치·증빙 지문만 전달한다. 주민번호·생년월일·전화·성별·여권은 수신하지 않는다.

- 조건·예외: 원본 사진은 비공개 로컬 보관 경계를 따른다.
- 출처: `docs/specs/participants.md:415`, `docs/specs/participants.md:416`

### SRC-058 · 이름 동일성 제한

*보호*

원본에 적힌 별칭 또는 사용자가 검증한 한글/영문명 관계만 사용한다. 유사발음·성만 일치·부분문자열·자동 역변환·한글 내부 공백 삭제로 동일인을 확정하지 않는다.

- 조건·예외: 공급자 항공권의 별도 토큰 정규화 계약을 사람 신원 확정으로 확대하지 않는다.
- 출처: `docs/specs/google-ledger.md:643`, `docs/specs/participants.md:509`

### SRC-059 · 수입 부재와 금액

*보호*

이름만 추가한 참가자에게 금액·날짜를 만들지 않으며 입금 기록 부재를 미납/완납 증거로 쓰지 않는다. 원본 수입행을 한 번만 집계하고 총액과 구성액을 이중 가산하지 않는다.

- 조건·예외: 이름 인덱스가 없거나 stale이면 부재 판정을 유보한다.
- 출처: `docs/specs/participant-income-authority-and-drag-link-20261028.md:111`, `docs/specs/participant-income-authority-and-drag-link-20261028.md:143`, `docs/specs/participants.md:395`, `docs/specs/participants.md:486`, `docs/specs/participants.md:493`

### SRC-060 · 수기 지출 동일성

*보호 · 결정 2026-10-29*

같은 유효 여행의 정확 금액·통화·부호와 날짜 의미·가맹점·설명·카드/예약 단서로 유일성이 입증될 때만 수기행을 같은 거래로 연결한다. 다른 여행·반복 결제·금액/통화 충돌·점유는 합치지 않는다.

- 조건·예외: 표시용 M:N 후보 관계는 실제 동일성 확정과 별개다.
- 출처: `docs/specs/sheet-manual-expense-dedup-20261029.md:12`, `docs/specs/sheet-manual-expense-dedup-20261029.md:19`, `docs/specs/sheet-manual-expense-dedup-20261029.md:20`, `docs/specs/sheet-manual-expense-dedup-20261029.md:21`, `docs/specs/sheet-manual-expense-dedup-20261029.md:28`

### SRC-061 · Google 표시용 M:N 대조

*일반 · 결정 2026-10-30*

선택된 동일 여행과 정확한 signed 금액으로 모든 지출 후보 관계를 만들고 정상 최신 양쪽 건수가 같을 때 그룹 건수 일치로 본다. 이 관계로 개별 거래를 확정·합치거나 금융 원문을 쓰지 않는다.

- 조건·예외: 실제 반복 결제는 독립 유지하고 stale·원본 변경 시 재계산한다.
- 출처: `docs/specs/google-expense-mn-reconciliation-20261030.md:7`, `docs/specs/google-expense-mn-reconciliation-20261030.md:15`, `docs/specs/google-expense-mn-reconciliation-20261030.md:17`, `docs/specs/google-expense-mn-reconciliation-20261030.md:18`, `docs/specs/google-expense-mn-reconciliation-20261030.md:19`

### SRC-062 · Google 사본 선택 보호

*보호 · 결정 2026-10-11*

실제 같은 여행이 main/archive 양쪽에 있으면 main을 기본 금액 정본으로 하되 사용자 선택을 유지하고 한 사본만 집계한다. 유사 제목·다른 소유자·템플릿을 같은 여행으로 합치지 않는다.

- 조건·예외: 보관본 존재에 따른 마감 상태와 금액 정본 선택은 별개다.
- 출처: `docs/specs/google-ledger.md:175`, `docs/specs/google-ledger.md:350`, `docs/specs/google-ledger.md:287`, `docs/specs/google-ledger.md:347`, `docs/specs/google-ledger.md:351`

### SRC-063 · 외부 AI 전송·비용

*보호*

승인된 영수증 분석은 명시 실행에서만 외부 전송하며 유료 모델로 자동 재시도하지 않는다. 후보 검토 중 자동 재호출을 하지 않고 실패·빈 결과에는 직접 입력 경로를 유지한다.

- 조건·예외: 정해진 기존 비용·날짜·유효 여행 등 파생 필드만 허용한 분류 요청에 원문 식별자를 추가하지 않는다.
- 출처: `docs/specs/receipt-unified-upload-ux-20261105.md:48`, `docs/specs/receipts.md:36`, `docs/specs/receipts.md:63`

### SRC-064 · 예정일과 실제 결제일

*보호*

동액 예약 묶음의 결제일은 서명 검증된 예약 확인 메일의 해당 계약상 발송일 근거로 판정한다. 환불불가 기한·수집/관측 시각·오늘 결제 표시를 실제 결제일로 대체하지 않는다.

- 조건·예외: 공급자별 승인된 날짜 근거에 한정하고 항공권 최초 수신일 규칙을 결제일로 확대하지 않는다.
- 출처: `소유자 지시 메모:feedback-payment-date-evidence.md:11`

### SRC-065 · 추론 기간 보완

*보호*

원문 금액이 없으면 검증된 지점·숙박기간의 유일 관계를 낮은 신뢰의 기간 근거로만 사용할 수 있다. 이를 정확 결제 연결·실제 금액·예약번호 확정으로 승격하지 않는다.

- 조건·예외: 기존 원행·예약 identity와 최신 digest가 일치하고 취소·기간 충돌이 없어야 한다.
- 출처: `docs/history/implementation-and-audits.md:922`, `docs/history/ota-legacy.md:1340`, `docs/history/ota-legacy.md:1366`, `docs/history/implementation-and-audits.md:937`

### SRC-066 · 항공권 당일 후보

*보호 · 결정 2026-11-04*

항공권 날짜 기반 후보는 선택한 날짜의 원행을 읽는 조회이며 자동 ±1일 확대·근사 금액 매칭·원본 없는 연결을 하지 않는다.

- 조건·예외: 같은 날의 취소/환불·중복·기점유 거래도 사실대로 보여주되 금융 차단 거래는 선택/확정할 수 없다.
- 출처: `docs/specs/flight-booking-focused-spa-ux-20261104.md:28`, `docs/specs/ui.md:652`, `docs/specs/ui.md:682`

### SRC-067 · 영수증 미검증 값

*보호*

영수증의 결제수단·총액·원본 영역이 검증되지 않으면 현금/법인카드나 확정 비용으로 임의 처리하지 않는다. 잘림·겹침·복수 카드 후보·매입 미도착은 해당 근거를 확인하되 원문과 성공 항목을 보존한다.

- 조건·예외: 모든 정상 거래 완료 원칙은 금액/결제 사실을 창작하는 허가가 아니다.
- 출처: `docs/specs/receipt-unified-upload-ux-20261105.md:47`, `docs/specs/google-ledger.md:115`, `docs/specs/google-ledger.md:128`, `docs/specs/google-ledger.md:129`
