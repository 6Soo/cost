# 판정 규칙 — 장부 기록

> [판정 규칙집](../DECISION_POLICY.md)의 영역별 상세 규칙이다. 핵심 원칙과 읽는 법은 규칙집 본문에 있다.
> 규칙 ID는 바꾸지 않는다. 규칙을 고칠 때는 같은 ID의 내용을 고치고 옛 내용을 "대체된 옛 규칙"에 남긴다.
> "출처"의 파일과 줄 번호는 커밋 `b0340d0d`(2026-11-10) 기준이다. 그 뒤 줄어든 `AGENTS.md`·`docs/COST_V3_START_HERE.md`의 줄은 `git show b0340d0d:<경로>`로 본다. 그때의 `docs/specs/<파일>`은 지금 `docs/history/specs-20261110/<파일>`에 있다(절차서 두 개는 `docs/playbooks/`).

### REC-001 · 판정 완료

*일반 · 결정 2026-11-08*

P1 기존 규칙을 먼저 적용하고 남은 문맥은 P2가 원본·메일·장부·기존 결정을 대조해 분류를 완료한다. 자동/수동 분류 모두 완료이며 낮은 신뢰만으로 승인·분류 대기를 만들지 않는다.

- 조건·예외: 정상 거래는 실제 여행 또는 유효한 분기 기타비용으로 종결하고 사용자는 분기 검수에서 교정한다.
- 대체된 옛 규칙:
  - Only hold rows that have no evidence at all (no card candidate). — C:/Users/kkokk/.claude/projects/C--AX-cost/memory/feedback-auto-assign-monthly-review.md:12
  - If there is no evidence, leave it unassigned. — C:/Users/kkokk/.claude/projects/C--AX-cost/memory/feedback-no-recommendation.md:8
  - 근거가 있으면 추천 대기 없이 자동 배정하고 근거가 전혀 없을 때만 미배정으로 둔다. — C:/Users/kkokk/.claude/projects/C--AX-cost/memory/feedback-no-recommendation.md:8
  - Use "unassigned" only when there is no basis at all. — C:/Users/kkokk/.claude/projects/C--AX-cost/memory/feedback-no-recommendation.md:12
  - 그 밖에 6건
- 출처: `docs/specs/finance.md:56`, `docs/specs/finance.md:45`, `AGENTS.md:43`, `소유자 지시 메모:feedback-classify-records-automatically.md:15`, `소유자 지시 메모:feedback-auto-assign-monthly-review.md:8`

### REC-002 · 분류와 내부 기록

*일반*

승인된 분류 실행은 금융 적격 거래를 기존 자동 기록 경로로 이어 처리한다. 파일 수신·파싱·분류 완료·실제 내부 기록 여부는 별도 사실로 판정한다.

- 조건·예외: 낮은 추론 신뢰만으로 기록을 막지 않으며 실제 기록은 ledger_entries로 확인한다.
- 출처: `소유자 지시 메모:feedback-classify-records-automatically.md:15`, `소유자 지시 메모:feedback-auto-deploy-on-change.md:15`, `소유자 지시 메모:feedback-classify-records-automatically.md:11`, `docs/specs/finance.md:464`, `docs/card_downloads.md:65`

### REC-003 · 자동 판정 출처

*보호*

자동·수동 출처, 근거·불확실성·처리 이력을 보존한다. P2 판단을 사용자가 답하거나 개별 예약/환급을 확인한 것으로 기록하지 않는다.

- 조건·예외: 단일 추론을 미래의 사실로 일반화하지 않는다.
- 출처: `AGENTS.md:37`, `AGENTS.md:42`, `docs/specs/finance.md:81`, `docs/specs/finance.md:83`, `docs/specs/finance.md:148`

### REC-004 · 최선 실제 여행

*일반 · 결정 2026-11-08*

정상 원행에 실제 여행 후보가 있으면 최선 후보에 AUTO_INFERRED로 우선 배정하고 수동 이동을 우선한다. 동률은 문서화한 결정 순서로 처리하며 없는 여행을 만들지 않는다.

- 조건·예외: 실제 금융 오류·중복·환불·수동 교정 보호는 유지한다.
- 대체된 옛 규칙:
  - 댓글이 5개 이상이고 명시 출발일이 한국 날짜로 오늘 이후인 여행을 출발 예정으로 분류해 장부의 여행 목록에 등록한다. — docs/specs/finance.md:295
- 출처: `소유자 지시 메모:feedback-auto-assign-monthly-review.md:12`, `소유자 지시 메모:feedback-no-recommendation.md:12`, `docs/specs/finance.md:288`, `docs/specs/finance.md:295`, `docs/history/product-and-handoffs.md:80`

### REC-005 · 기존 여행 복원 순서

*일반 · 결정 2026-10-29*

빈 여행은 현재 장부의 유효 여행→가장 최근 저장한 유효 여행→기존 기록의 유효 여행→새 추론 순서로 복원한다. 최초 기록값으로 현재 사용자 수정·해제를 덮지 않는다.

- 조건·예외: 이미 유효한 배정·항목·회사 제외는 보존한다.
- 출처: `docs/specs/finance.md:89`, `docs/specs/finance.md:90`, `docs/history/operations-20261028-20261107.md:968`, `docs/history/operations-through-20261027.md:1485`

### REC-006 · 배정 날짜와 기간

*일반*

카드 여행 배정은 이용일, 없으면 승인일을 사용하며 매입일로 대체하지 않는다. 실제 예약 이용기간은 결제일 추론보다 우선한다.

- 조건·예외: 기존 원행·수동 교정·검증된 여행 권위를 보존한다.
- 출처: `소유자 지시 메모:owner-rules.md:10`, `소유자 지시 메모:owner-rules.md:11`, `docs/specs/finance.md:286`

### REC-007 · 기록된 자동 귀속 교정

*일반 · 결정 2026-11-03*

명시 카드 재분류에서 최신 예약 원문·검증 결제·이용기간·실제 여행을 확인하면 기록된 자동 추론만 원자적으로 교정할 수 있다.

- 조건·예외: 수동 결정·owner 기장·환불/원결제·원본 오류·stale/충돌 근거는 제외한다.
- 대체된 옛 규칙:
  - 이미 기록된 행은 여행 검증이 바뀌어도 자동으로 옮기지 않는다. — 2026-10-16, C:/Users/kkokk/.claude/projects/C--AX-cost/memory/feedback-classify-records-automatically.md:15
  - 기록된 거래의 배정은 건드리지 않는다. — docs/history/ota-legacy.md:1251
- 출처: `소유자 지시 메모:feedback-classify-records-automatically.md:15`, `docs/specs/recorded-booking-period-correction-20261103.md:11`, `docs/history/session_handoff-through-20261107.md:401`, `docs/history/ota-legacy.md:1251`

### REC-008 · 기기록 수동 보호

*보호*

기기록·수동 결정·수동 제외·검증된 금융 링크·원본·금액·ID를 자동 추론과 새 규칙으로 덮어쓰거나 중복 기록하지 않는다.

- 조건·예외: 문서가 허용한 기록된 자동 추론의 명시 교정은 별도 예외다.
- 출처: `docs/specs/unified-expense-action-queue-20261105.md:195`, `docs/specs/inline-bulk-expense-edit-20261102.md:24`, `docs/specs/ota-missing-trip-completion-20261102.md:27`, `docs/specs/python-refactor-followup-20261102.md:13`, `docs/specs/card-completion-recurrence-20261101.md:12`

### REC-009 · 일반 기록 적격

*보호*

장부 기록은 분류·유효 여행/탭·필수 금액·날짜/가맹점·항목과 금융 보호 검증을 모두 통과해야 한다. 원본 오류·중복·초과환불·회사 제외·내부 금융 잠금은 차단한다.

- 조건·예외: OTA 관계 미확정·낮은 여행 신뢰만으로 정상 매입의 내부 준비를 막는 과거 조건은 대체됐다.
- 대체된 옛 규칙:
  - 취소 정산·부분 환불 미확인·사용자 보류·예약과 결제 연결 미확정은 일반 비용 기록에서 제외한다. — 2026-10-04, docs/specs/finance.md:227
- 출처: `소유자 지시 메모:feedback-classify-records-automatically.md:15`, `docs/specs/card-destination-only-ux-20261108.md:9`, `docs/specs/unified-expense-action-queue-20261105.md:144`, `docs/specs/unified-expense-action-queue-20261105.md:352`, `app/ledger.py:16`

### REC-010 · 미리보기 신선도

*보호*

기록 시 최신 미리보기 digest·revision·원문과 여행/탭 권위를 잠금 안에서 다시 검증한다. 변경되면 stale 요청을 거부하고 재평가한다.

- 조건·예외: 미리보기에서 보호한 행과 실제 기록 projection이 같아야 한다.
- 출처: `docs/specs/google-expense-mn-reconciliation-20261030.md:45`, `docs/specs/finance.md:252`, `docs/specs/finance.md:460`, `docs/specs/finance.md:485`, `app/ledger.py:608`

### REC-011 · 원자 기록과 감사

*보호*

거래·장부·요청 결과·감사 이력은 같은 원자 트랜잭션으로 저장한다. 중간 오류면 전체를 되돌리며 호출자 트랜잭션은 저장점으로 보호한다.

- 출처: `docs/specs/finance.md:148`, `docs/specs/finance.md:252`, `docs/specs/cloud-mail-cutover.md:77`, `app/ledger.py:11`, `docs/history/operations-through-20261027.md:393`

### REC-012 · 거래 중복 기록 방지

*보호*

같은 transaction_id는 한 번만 기록한다. 거래 ID/source_event_id가 없는 과거 행만 카드사·카드·승인번호·일자·부호 금액·거래 종류가 모두 같은지 비교해 중복을 막는다.

- 조건·예외: 원문 hash만으로 실제 복수 거래를 합치지 않는다.
- 출처: `docs/specs/unified-expense-action-queue-20261105.md:184`, `docs/specs/expense-cleanup-status-filter-actions-20261028.md:119`, `docs/specs/finance.md:492`, `docs/specs/finance.md:238`, `app/ledger.py:9`

### REC-013 · 재요청 멱등

*보호*

같은 요청 재시도는 거래·결정·이력을 늘리지 않는다. 저장 성공 뒤 상태 조회 실패는 저장 실패와 구분하며 기존 결과를 재사용한다.

- 출처: `docs/specs/finance.md:94`, `docs/specs/sheet-manual-expense-dedup-20261029.md:78`, `docs/specs/finance.md:462`, `docs/specs/ui.md:124`, `docs/history/ota-legacy.md:311`

### REC-014 · 환불 구성원 원자성

*보호 · 결정 2026-10-29*

원결제·취소·부분환불은 전체 구성원을 검증해 원자적으로 기록한다. 불완전·차단 묶음은 기록하지 않고 같은 파일의 무관한 정상 거래는 계속 처리한다.

- 조건·예외: 현재 허용된 부분 기기록 묶음 보완과 이미 기록한 행의 중복 방지를 구분한다.
- 대체된 옛 규칙:
  - 전체 미기록은 원자적 기록, 전체 기록은 no-op, 일부 기록은 `REFUND_PAIR_PARTIALLY_BOOKED`, 묶음 누락과 막힌 묶음은 `REFUND_GROUP_INCOMPLETE`로 거부한다. — 2026-10-10, docs/history/operations-through-20261027.md:1230
- 출처: `docs/specs/unified-expense-action-queue-20261105.md:307`, `docs/specs/finance.md:94`, `docs/specs/finance.md:148`, `docs/history/session_handoff-through-20261107.md:757`, `docs/history/operations-through-20261027.md:1020`

### REC-015 · 검증 순액 0 환불

*일반 · 결정 2026-10-28*

inferred가 아닌 검증된 전액 환불·순액 0 묶음은 실제 금융/수동 잠금이 없을 때 분류·여행 placeholder만 제거하고 기존 기록 경로로 전체를 처리한다.

- 조건·예외: 원본 오류·원결제 중복·초과환불·실제 수동/금융 잠금·기록 없는 legacy 투영은 보호한다.
- 출처: `docs/specs/refund-reconciliation-remediation-20261028.md:21`, `webapp/card_flow.py:1681`, `docs/history/session_handoff-through-20261107.md:1064`

### REC-016 · 환불 배속 상속

*일반*

검증 환불의 항목·여행·탭이 비었으면 원결제 또는 이미 기록된 반대편의 유효 배속을 상속한다. 실제 차단·초과환불·부분환불의 배속충돌은 유지한다.

- 조건·예외: 검증된 전액 순액 0은 단순 배속 차이를 부분환불 충돌로 오인하지 않는다. 전액 상쇄의 단순 배속 차이는 부분환불용 충돌로 차단하지 않는다.
- 출처: `app/ledger.py:355`, `app/ledger.py:396`, `app/ledger.py:409`

### REC-017 · 환불 재전송 예외

*보호 · 결정 2026-10-29*

환불 기록 성공 후 새 요청 ID로 같은 미리보기를 재전송해도 성공 범위·성공 직후 미리보기·전체 구성원 revision·실제 장부 내용이 잠금 안에서 일치할 때만 applied=0으로 응답한다.

- 조건·예외: 금액·사용자 결정·묶음 멤버 변경·새 잠금·임의 digest·성공 근거 없는 응답에는 적용하지 않는다.
- 출처: `docs/specs/finance.md:94`, `docs/history/operations-20261028-20261107.md:959`

### REC-018 · 환불 범위 확장

*보호*

일반 기록 미리보기는 해당 접수 파일 범위에 한정한다. 검증된 순액 0 전액 환불 자동기록만 다른 파일의 구성원까지 확장하며 inferred 관계는 확장하지 않는다.

- 출처: `docs/specs/card-completion-recurrence-20261101.md:11`, `app/ledger.py:38`

### REC-019 · 기기록 전액환불 표시 이동

*일반 · 결정 2026-10-13*

이미 기록한 전액 환불은 모든 구성원이 같은 여행에 기록돼 있고 저장 금액 합계가 0일 때만 여행 목록의 표시를 옮긴다.

- 조건·예외: 표시 이동이 신규 기록·실제 환급 확인은 아니다.
- 출처: `docs/specs/finance.md:157`, `docs/history/operations-through-20261027.md:1035`

### REC-020 · OTA 미확정과 기록 준비

*일반*

정상 카드 매입은 OTA 예약 연결이 추론/미연결이거나 결제일이 없어도 최선의 실제 여행으로 귀속해 내부 비용 준비를 허용한다.

- 조건·예외: 원본 오류·실제 중복·미해결 취소/환불·점유 등 금융 차단은 유지한다.
- 대체된 옛 규칙:
  - 자동결제 예정 예약은 2026-10-16 소유자 결정 A에 따라 최신 권한 스냅샷(`scheduled_card_ids`)에서 이 보류를 통과한다([[project-agoda-scheduled-charge-rows]]). — 2026-10-16, C:/Users/kkokk/.claude/projects/C--AX-cost/memory/feedback-classify-records-automatically.md:15
  - authority에서는 OTA-first 연결이 확정되지 않은 OTA 카드 거래를 장부 미리보기에서 보류한다. — 2026-10-09, docs/history/operations-through-20261027.md:1280
  - 코어가 확정하지 않은 OTA 거래는 새로 기록하지 않는다. — 2026-10-16, docs/history/ota-legacy.md:1276
  - 기록을 막는 조건은 사용자 보류, 환불 짝 불완전, 여행 검증 실패, 권위 모드의 미해결 OTA이며, 자동 결제 예정 예외는 최신 권위 스냅샷 조건을 따른다. — 2026-10-16, C:/Users/kkokk/.claude/projects/C--AX-cost/memory/feedback-classify-records-automatically.md:15
  - 그 밖에 2건
- 출처: `docs/specs/unified-expense-action-queue-20261105.md:197`, `docs/specs/ota.md:74`, `docs/history/product-and-handoffs.md:210`, `docs/history/product-and-handoffs.md:73`, `docs/history/product-and-handoffs.md:2003`

### REC-021 · 관계별 완료 사실

*보호*

예약 관계·카드 결제 검증·분류·내부 기록·Google 반영·실제 은행 환급은 각각 증거로 판단한다. 조회·순액·대사 완료·분류 완료를 실제 기록/환급으로 승격하지 않는다.

- 출처: `docs/specs/cost-pr-only-implementation-brief-20261106.md:70`, `docs/specs/card-upload-management-ux-20261105.md:35`, `docs/specs/unified-expense-action-queue-20261105.md:101`, `docs/specs/python-refactor-followup-results-20261102.md:42`, `docs/specs/ota-undated-many-to-many-20261101.md:13`

### REC-022 · 메일만으로 비용 금지

*보호*

OTA 예약·취소 메일만으로 카드 비용이나 환불 장부 행을 생성하지 않는다. 실제 카드 원행을 한 번만 집계하고 추가 청구·환불도 개별 금융 증거를 확인한다.

- 출처: `docs/specs/finance.md:111`, `docs/specs/finance.md:527`, `docs/history/operations-through-20261027.md:926`, `docs/history/ota-legacy.md:1356`, `docs/history/product-and-handoffs.md:96`

### REC-023 · 회사 경비 제외

*보호*

사용자가 회사 경비에서 제외한 거래는 장부와 복사 대상에서 제외하되 원본·결정 이력을 보존한다. 제외 근거 source_hash가 바뀌면 예전 결정을 새 원문에 적용하지 않는다.

- 조건·예외: 기기록·환불 묶음 등 이 경로의 기존 금지 조건은 유지한다.
- 출처: `docs/specs/expense-cleanup-status-filter-actions-20261028.md:86`, `app/ledger.py:99`, `app/ledger.py:101`, `docs/history/ota-legacy.md:311`

### REC-024 · 실제 장부와 staging

*일반*

카드 접수·staging·장부 미리보기는 실제 내부 기록과 구별한다. 합계는 실제 장부 행과 유효 수입 배분만 집계하며 staging을 중복 합산하지 않는다.

- 출처: `docs/history/operations-through-20261027.md:109`, `docs/history/ota-legacy.md:150`

### REC-025 · 자동 기록의 실행 계기

*보호*

자동 기록은 기존 승인된 변경 요청 경로에서 실행하고 조회로 미완료 행을 복구·기록하지 않는다. 이미 배정한 거래는 근거를 유지하며 기록만 재개할 수 있다.

- 조건·예외: 신규 무승인 전기 루프를 만들지 않는다.
- 출처: `docs/specs/ota-missing-trip-completion-20261102.md:5`, `docs/specs/ota-missing-trip-completion-20261102.md:27`, `docs/specs/finance.md:504`, `webapp/card_flow.py:1705`, `docs/history/operations-20261028-20261107.md:631`

### REC-026 · 내부 금융 잠금

*보호 · 결정 2026-11-08*

P2 실패·stale 자료·코드 오류·원본 충돌·장부 잠금은 시스템 진단/재시도 또는 내부 안전 잠금으로 보존한다. 사용자 보류 해제·완료 승인·기록 확정 작업을 만들지 않는다.

- 조건·예외: 내부 원본·금액·중복·환불 보호는 폐지되지 않는다.
- 대체된 옛 규칙:
  - 가져오기를 보류 해제로 해석하지 않으며 해제는 사용자가 명시적으로 수행한다. — 2026-10-08, docs/specs/finance.md:217
  - 자동 기록과 일반 장부 기록의 보호 조건을 맞추고 보류 자동 해제를 막는다. — 2026-10-20, docs/history/implementation-and-audits.md:568
- 출처: `소유자 지시 메모:feedback-classify-records-automatically.md:15`, `docs/specs/unified-expense-action-queue-20261105.md:103`, `docs/specs/unified-expense-action-queue-20261105.md:242`, `docs/specs/unified-expense-action-queue-20261105.md:381`, `docs/history/session_handoff-through-20261107.md:1205`

### REC-027 · 원행과 반대편 보존

*보호*

취소·환불 원행과 원결제를 별개 행으로 보존하고 차액으로 원금액을 덮지 않는다. 승인 취소만으로 새 환불 비용을 만들지 않는다.

- 출처: `docs/specs/finance.md:217`, `docs/specs/finance.md:538`, `docs/specs/finance.md:565`

### REC-028 · 표시 날짜 보존

*보호*

자동 분류·OTA 근거 보완만으로 기존 장부의 기록 날짜를 바꾸지 않는다. 원문 날짜와 서비스 기간 및 추론 근거는 별도로 보존한다.

- 조건·예외: 명시 귀속 교정의 허용 범위를 날짜 변경으로 확대하지 않는다.
- 출처: `docs/specs/finance.md:110`, `docs/history/product-and-handoffs.md:95`

### REC-029 · 기록된 OTA 메타데이터

*보호*

검증된 최신 OTA 예약번호·서비스 기간·출처 digest만 미리보기와 재검증을 거쳐 장부 메타데이터로 전달한다. 묶음/추론 관계만으로 개별 예약번호를 확정하지 않는다.

- 조건·예외: 원문/취소/기간/연결 충돌이 있으면 해당 근거 필드를 비운다. 본문에서 purchase·출처 digest·취소/기간/연결 상태가 검증된 메타데이터만 사용한다. 같은 예약의 검증 기간 보완은 기존 원문 source digest를 유지하고 추가 근거 digest를 함께 보존한다.
- 출처: `webapp/tests/test_ota_core_recording.py:114`, `docs/specs/toyoko-collection-audit-20261103.md:12`, `app/ota_mail.py:971`, `app/ota_mail.py:978`, `app/ota_mail.py:1002`

### REC-030 · 귀속 교정 복구

*보호 · 결정 2026-10-29*

소수 거래의 여행·항목 교정은 revision·미리보기 digest와 원자 저장을 사용하고 변경 전 값·이력으로 되돌릴 수 있게 한다.

- 조건·예외: 원본/금액/삭제까지 바꾸는 작업은 단순 이동 범위가 아니다.
- 출처: `docs/specs/finance.md:67`

### REC-031 · 읽기 순액과 파생값

*보호*

환불 합계·순액·대사 projection은 읽기 전용 파생값이며 금융 원문·기장/환급 사실을 바꾸지 않는다.

- 조건·예외: 새 원문·스냅샷이 생기면 최신 값으로 재계산한다.
- 출처: `docs/specs/finance.md:141`, `docs/history/operations-20261028-20261107.md:1009`, `docs/history/operations-through-20261027.md:645`, `docs/history/operations-through-20261027.md:941`

### REC-032 · 구조화 AI 결과

*보호 · 결정 2026-11-02*

AI 결과는 기존의 유효 여행·항목, 원본/버전/문맥 digest와 실행 메타데이터를 검증한 뒤 원자 적용한다.

- 조건·예외: 수동 교정·원본·금액·금융 링크를 AI가 임의 변경하지 않는다.
- 출처: `docs/specs/status-and-inference-stages-20261102.md:10`

### REC-033 · 신규 거래만 기록

*보호 · 결정 2026-10-29*

기존 거래와 대조한 후 명확한 신규 지출만 기존 권한·금융 보호 기록 경로로 보낸다. 모호한 중복 후보는 기록·삭제·강제 병합하지 않는다.

- 조건·예외: 충분한 복합 근거로 유일성이 증명되면 원승인번호 부재만으로 자동 연결을 막지 않는다.
- 출처: `docs/specs/card-upload-full-reconciliation-20261029.md:54`, `docs/specs/sheet-manual-expense-dedup-20261029.md:19`, `docs/specs/sheet-manual-expense-dedup-20261029.md:20`, `docs/card_downloads.md:64`, `docs/history/ota-legacy.md:1007`

### REC-034 · 이관과 재업로드

*보호*

동일 파일 재업로드는 기존 처리 결과를 반환하고 CSV↔XLS 형식 변화만으로 새 거래를 만들지 않는다. 사용자 확정값·실제 서로 다른 거래·승인/취소/환불을 보존한다.

- 출처: `docs/specs/finance.md:490`, `docs/specs/finance.md:450`

### REC-035 · 원문·권한 보호

*보호*

원본·금액·ID·사용자 결정·중복·환불·OTA exact/manual link·권한·CSRF·원자성을 유지한다. 기록 경로의 UI 변경이나 성능 최적화로 이 경계를 약화하지 않는다.

- 조건·예외: 고객 원문·계정/폴더 ID·비밀값은 Git·보고서·공개 로그에 포함하지 않는다.
- 출처: `AGENTS.md:60`, `docs/specs/autonomous-expense-cleanup-20261105.md:60`, `docs/specs/card-upload-management-ux-20261105.md:332`, `docs/specs/cleanup-export-conflicts-20261105.md:5`, `docs/specs/finance.md:12`

### REC-036 · Google 사본과 마감

*일반 · 결정 2026-10-11*

보관 Google 장부에서 실여행 탭을 확인해야 마감 완료로 판단한다. 동일 여행이 메인/보관에 공존하면 마감 상태와 금액 정본 선택을 분리하고 한 사본만 집계한다.

- 조건·예외: 메인 정본 기본·사용자 선택 유지이며 읽기 실패를 새 마감 완료로 바꾸지 않는다.
- 출처: `docs/specs/andre-multi-owner-ledger-20261101.md:18`, `docs/specs/google-ledger.md:283`, `docs/specs/google-ledger.md:175`, `docs/specs/google-ledger.md:73`, `docs/specs/google-ledger.md:176`

### REC-037 · 원본 확인과 처리 구분

*보호*

원본 검사·분석·파일 접수 성공은 장부 기록 완료가 아니다. 실제 신규·기록·보호 차단·실패 결과를 구분하고 허위 성공을 만들지 않는다.

- 출처: `docs/specs/card-upload-management-ux-20261105.md:144`, `docs/specs/eight-card-review-20261102.md:22`, `docs/specs/card-upload-full-reconciliation-20261029.md:27`, `docs/specs/card-upload-full-reconciliation-20261029.md:28`, `docs/specs/finance.md:524`

### REC-038 · 규칙 활성 상태

*보호*

비활성·철회 규칙은 과거 승인자 기록이 있어도 적용하지 않는다.

- 조건·예외: active=False 또는 inactive/revoked를 우선한다.
- 출처: `docs/history/ota-legacy.md:729`

### REC-039 · 사전승인과 실숙박비

*일반 · 결정 2026-11-10*

현장결제+카드 보증 예약의 사전승인은 실제 현장 숙박비와 구분한다. 검증된 같은 금액 취소 원행과 함께 순액을 계산하며 환급 완료는 별도 증거로만 판정한다.

- 조건·예외: 제안된 자동 보강은 구현 완료가 아니며 실제 현장 숙박비는 해당 실제 결제 원행으로 처리한다.
- 출처: `docs/specs/ota-portal-browser-collection-20261110.md:67`

### REC-040 · 대장 항공권 신선도

*보호*

대장 항공권 귀속·기록은 이번 요청에서 정상 읽은 reservation authority와 마지막 성공 90초 이내 조건을 만족해야 한다.

- 조건·예외: Google 여행 정본과 사용자 수동 결정은 보존한다.
- 출처: `docs/specs/finance.md:208`

### REC-041 · 금융 결제 연결 근거

*보호*

개별 결제 동일성은 검증된 원문·금액/통화·날짜 또는 승인된 무날짜 근거와 점유 조건으로 판정한다. 수동 연결도 owner·CSRF·최신 미리보기 검증과 실제 금융 충돌 차단을 통과해야 한다.

- 조건·예외: 외화 하루 차이는 기존 승인된 exact 예외에 한정하고 KRW·±2일로 확대하지 않는다. 이용기간을 아는 예약을 결제월의 다른 여행에 넣지 않는다.
- 출처: `app/ota_exact.py:13`, `app/ota_exact.py:82`, `tests/card_pipeline/test_ota_exact_gate.py:29`, `tests/card_pipeline/test_ota_exact_gate.py:58`, `tests/card_pipeline/test_ota_exact_gate.py:85`

### REC-042 · 영수증 간편 환산의 의미

*보호*

영수증의 JPY 간편 환율은 소유자의 내부 작성 기준이며 카드사 청구액이나 세무상 법정환율이 아니다. 실제 카드 원화 금액은 보존한다.

- 조건·예외: 원문 JPY·적용 환율·산출 KRW를 분리한다.
- 출처: `docs/specs/google-ledger.md:139`

### REC-043 · 수집 기간과 금융 사실 분리

*보호 · 결정 2026-11-08*

수집 기간 계산·조회 증빙 확인은 거래 분류·장부 기록·실제 환급을 만들지 않는다. 빈 파일만으로 임의 조회기간을 확인 처리하지 않고 재확인은 멱등적으로 처리하며 다른 파일의 성공·원본·거래·장부는 보존한다.

- 조건·예외: 최신 수집 현황은 파일별 최초~최종 거래일 범위의 카드사별 합집합을 사용하되 원문 조회 완료 증빙과 구분한다.
- 대체된 옛 규칙:
  - 과거 수집 현황의 기본 계산·관리 화면에 한정해 대체됨: 끝4자리만 같거나 카드사가 불명확하면 다른 카드의 커버리지를 합치지 않는다. (실제 조회 완료 증빙과 원본 보호는 유지) — 2026-11-02, docs/specs/finance.md:26
  - 과거 수집 현황의 기본 계산·관리 화면에 한정해 대체됨: 조회 범위 확정: 다운로드 파일의 신뢰할 수 있는 조회 조건 메타데이터에서 기간·조회 기준을 파싱하면 제안한다. (실제 조회 완료 증빙과 원본 보호는 유지) — 2026-11-02, docs/specs/finance.md:27
  - 과거 수집 현황의 기본 계산·관리 화면에 한정해 대체됨: 카드별 시작 관리일과 최신 확인 구간 이후까지의 미확인 구간을 표시한다. (실제 조회 완료 증빙과 원본 보호는 유지) — 2026-11-02, docs/specs/finance.md:29
  - 과거 수집 현황의 기본 계산·관리 화면에 한정해 대체됨: 과거는 기본 ‘확인 여부 미상’으로 두고 향후 근거 있는 재조회/사용자 확인 시에만 상태를 승격한다. (실제 조회 완료 증빙과 원본 보호는 유지) — 2026-11-02, docs/specs/finance.md:31
- 출처: `docs/specs/card-upload-management-ux-20261105.md:145`, `docs/specs/finance.md:28`, `docs/specs/finance.md:30`
