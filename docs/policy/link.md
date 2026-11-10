# 판정 규칙 — OTA↔카드 연결

> [판정 규칙집](../DECISION_POLICY.md)의 영역별 상세 규칙이다. 핵심 원칙과 읽는 법은 규칙집 본문에 있다.
> 규칙 ID는 바꾸지 않는다. 규칙을 고칠 때는 같은 ID의 내용을 고치고 옛 내용을 "대체된 옛 규칙"에 남긴다.
> "출처"의 파일과 줄 번호는 커밋 `b0340d0d`(2026-11-10) 기준이다. 그 뒤 줄어든 `AGENTS.md`·`docs/COST_V3_START_HERE.md`의 줄은 `git show b0340d0d:<경로>`로 본다. 그때의 `docs/specs/<파일>`은 지금 `docs/history/specs-20261110/<파일>`에 있다(절차서 두 개는 `docs/playbooks/`).

### LINK-001 · 독립된 판정 사실

*보호*

예약 관계·카드 결제 검증·여행 귀속·내부 기록·Google 반영·실제 환급은 독립된 근거로 판단한다. 어느 한 단계의 성공으로 다른 단계의 완료를 선언하지 않는다.

- 조건·예외: 예약 존재·발권·실제 이용·보험·참가자 확정도 각각 구분한다.
- 출처: `docs/specs/ota.md:14`, `docs/specs/ota-undated-many-to-many-20261101.md:13`, `docs/specs/lean-card-ota-core-20261030.md:7`, `AGENTS.md:35`, `AGENTS.md:44`

### LINK-002 · 연결의 기본 조건

*일반 · 결정 2026-11-11*

OTA 예약과 카드 결제는 **가맹점명(원문·확장명·승인된 별칭)과 같은 통화의 정확한 금액**이 일치하고, 여기에 **카드 끝 4자리 또는 결제일 중 하나**가 더 일치하면 연결한다. 원문에 없는 결제일이나 끝자리는 만들어 넣지 않고 비워 둔다.

- 조건·예외: 끝자리나 결제일이 "없는 것"과 "다르다고 적힌 것"은 다르다. 예약과 카드의 끝자리가 서로 다르다고 명시돼 있거나 공급자·통화·금액·방향(구매/환불)이 충돌하면 연결하지 않는다. 중복·원문 오류 원행과 수동 연결·고정 묶음은 보호한다. 할인 차액이 있는 금액을 정확 금액으로 취급하지 않는다. 예약과 카드가 서로 유일해야 한다는 조건은 요구하지 않는다(M:N).
- 코드와 다른 점: app/ota_inference.py와 config/ota-matching-defaults.json, tests/test_ota_inference.py에 Agoda 전용 "상호 유일" 조건이 남아 있다. 끝자리가 없고 결제일만 맞는 경우의 연결은 app/ota_payments.py에서 확인이 필요하다. docs/specs/ota-portal-browser-collection-20261110.md:32의 "상호 유일 추론에만 맡긴다"는 이 규칙으로 대체한다.
- 대체된 옛 규칙:
  - 결제일 없는 Agoda 예약은 카드 끝자리·정확 금액으로 예약과 카드가 서로 유일할 때만 연결한다. — 2026-11-10·11 사용자 결정으로 대체
  - Agoda 자동 결제 예정은 청구가 아니며 청구일이 API에 없으면 결제일을 비워 두고 카드 끝자리·정확 금액 상호 유일 추론에만 맡긴다. — 2026-11-10, docs/specs/ota-portal-browser-collection-20261110.md:32
  - Agoda 결제일 미상은 기존 app/ota_inference.py::unique_pairs를 우선 검증한다. — 2026-10-27, docs/specs/ota-review-queue-performance-20261027.md:90
  - Agoda 결제일 미상 후보는 하나라는 이유만으로 금융 확정하지 않고 가승인·환불은 별도 원장 규칙을 따른다. — 2026-10-27, docs/specs/ota-review-queue-performance-20261027.md:90
  - 그 밖에 26건
- 출처: `docs/specs/ota-portal-browser-collection-20261110.md:32`, `docs/specs/ota.md:14`, `docs/specs/ota-undated-many-to-many-20261101.md:28`, `app/ota_payments.py:1259`, `app/ota_inference.py:51`

### LINK-003 · M:N 관계 보존

*일반 · 결정 2026-11-01*

조건에 맞는 OTA↔카드 edge를 모두 M:N 연결 성분으로 보존하고 개별 예약 하나의 유일성·양쪽 건수 동일을 요구하지 않는다. 하나의 예약이나 카드를 임의 선택하거나 실제 예약·이벤트를 합치지 않는다.

- 조건·예외: 전역 수동점유·고정 그룹·명시 충돌 보호는 그대로 적용한다.
- 예: 한 카드와 두 예약의 조건이 맞으면 두 관계를 유지하고 카드 금액은 한 번만 센다.
- 코드와 다른 점: 레거시 app/ota_portal.py:326와 test_portal_identical_bookings.py:38의 동수량 제한은 구형 경로에 남아 있다. 관계 자체를 미연결로 돌리는 근거로 적용하지 말고 금융 배분과 분리해 재검토해야 한다.
- 대체된 옛 규칙:
  - 반복 결제는 전체 건수 대조와 안정 순서 배정을 사용하고 부분 묶음은 임의 연결하지 않는다. — 2026-10-29, docs/specs/ota.md:30
  - 반복 결제는 기존 전체 건수 대조와 안정 순서 배정을 사용하며 부분 묶음은 임의로 연결하지 않는다. — 2026-10-29, docs/specs/ota.md:30
  - 결제 solver의 유일성·점유·수동 pin 검사는 독립적으로 유지한다. — 2026-10-28, docs/specs/ota.md:721
  - 2:3의 그룹 수량 불일치는 확정 금지. — 2026-10-26, docs/history/product-and-handoffs.md:1466
  - 그 밖에 22건
- 출처: `docs/specs/ota.md:14`, `docs/specs/ota-undated-many-to-many-20261101.md:29`, `AGENTS.md:35`, `tests/card_pipeline/test_ota_mn_relations.py:58`, `app/ota_payment_relations.py:17`

### LINK-004 · 카드 원행 단일 집계

*보호 · 결정 2026-11-01*

같은 카드 실원행은 OTA·카드·영수증의 여러 증빙이나 여러 예약 관계가 있어도 비용과 카드 합계에 한 번만 포함한다. 재수집·복구 사본·반복 업로드로 실제 거래나 비용을 늘리지 않는다.

- 조건·예외: 별도 실제 원행·승인번호가 있는 동액 거래는 다중도를 보존한다.
- 출처: `docs/specs/ota.md:14`, `docs/specs/ota-undated-many-to-many-20261101.md:13`, `docs/specs/ota-undated-many-to-many-20261101.md:29`, `docs/specs/ota-undated-many-to-many-20261101.md:30`, `docs/specs/google-expense-mn-reconciliation-20261030.md:22`

### LINK-005 · 예약 합계와 그룹 잔액

*일반 · 결정 2026-11-01*

같은 예약의 복수 관측은 실제 결제 identity를 검증해 중복 제거하고, 명시 identity가 없거나 충돌하면 예약 근거 합계를 미확인으로 둔다. 카드 합계는 원행별 한 번 계산하며 비교 가능한 그룹 잔액은 균형·금액 차이·미확인을 구분한다.

- 조건·예외: 원문 이벤트는 합계 계산 때문에 병합·수정하지 않는다.
- 출처: `docs/specs/ota-undated-many-to-many-20261101.md:30`, `docs/history/session_handoff-through-20261107.md:724`, `tests/card_pipeline/test_ota_mn_relations.py:142`, `tests/card_pipeline/test_ota_mn_relations.py:152`, `app/ota_payment_relations.py:69`

### LINK-006 · 관계와 금융 배분 분리

*보호 · 결정 2026-11-01*

M:N 관계와 금액·건수 차이는 그대로 표시하되 그룹 순서 배정이나 관계 수를 개별 카드↔예약의 결제 identity 증명으로 쓰지 않는다. 검증되지 않은 transaction_id·예약번호별 금융 배분은 만들지 않는다.

- 조건·예외: 금융 적격 카드의 비용 준비·여행 귀속은 별도로 판단한다.
- 대체된 옛 규칙:
  - 단, 포털 동일 묶음의 1:1 예약 연결(`app/ota_portal.py` `_identical_group_matches`)은 아직 예약번호를 행마다 붙인다. — 2026-10-16, docs/history/ota-legacy.md:1246
- 출처: `docs/specs/ota-undated-many-to-many-20261101.md:23`, `docs/history/session_handoff-through-20261107.md:1139`, `docs/history/provisional-assignment-review-first-20261028.md:143`, `docs/history/product-and-handoffs.md:1466`, `docs/specs/ota.md:526`

### LINK-007 · 취소 후 관계 보존

*일반 · 결정 2026-11-01*

나중에 예약이 취소되거나 환불 관측이 생겨도 검증된 원결제 사실과 기존 카드 관계·카드 건수는 유지한다. 취소 상태·여행 이용 근거·환급 결정은 관계와 분리한다.

- 조건·예외: 특정 항공사 취소 증빙이 기존 paid 증거와 충돌하는 경우는 증빙 충돌 보호를 별도로 따른다.
- 출처: `docs/specs/ota-undated-many-to-many-20261101.md:13`, `docs/specs/ota-undated-many-to-many-20261101.md:31`, `docs/history/operations-through-20261027.md:1284`, `docs/specs/finance.md:269`, `tests/card_pipeline/test_ota_payments.py:254`

### LINK-008 · 수동 결정 우선

*보호*

사용자의 수동 여행 이동·예약 pin·확정 결제 링크·장부 교정·제외 결정은 자동 추론·재정렬·새 자료·새 규칙으로 덮어쓰지 않는다. 변경 필요성은 이력과 현재 근거 차이로 남긴다.

- 조건·예외: 폐지된 사용자 보류 해제 UI와 별개로 원본 충돌·환불·중복 등 내부 금융 잠금은 보호한다.
- 출처: `docs/specs/lean-card-ota-core-20261030.md:32`, `docs/history/operations-20261028-20261107.md:960`, `docs/specs/trip-flight-booking-overview-20261028.md:22`, `docs/specs/ota.md:38`, `docs/history/provisional-assignment-review-first-20261028.md:32`

### LINK-009 · 금융 원본 불변

*보호*

OTA 판정·수집·화면 표시로 카드 원문 금액·통화·날짜·ID·승인번호·방향·불변 해시와 이미 기록한 장부를 수정·삭제하지 않는다.

- 조건·예외: 실제 추출 오류 교정은 원본·identity를 보존하는 별도 표적 경로를 사용한다.
- 출처: `docs/specs/card-upload-management-ux-20261105.md:332`, `docs/specs/python-refactor-followup-20261102.md:13`, `docs/specs/card-upload-latency-20261102.md:10`, `docs/history/session_handoff-through-20261107.md:518`, `docs/history/operations-20261028-20261107.md:468`

### LINK-010 · 금융 부적격 카드 제외

*보호*

실제 중복·파싱 오류·원문 충돌, 명시 카드/발급사/동일 체계 승인번호 불일치, 다른 공급자, 설명되지 않은 통화·금액·구매/환불 방향 충돌은 자동·수동 결제 연결을 막는다.

- 조건·예외: 카드는 설명을 위해 표시할 수 있으나 서버에서도 선택과 배정을 차단한다. 단순 결제 identity 미확정은 금융 오류와 구분한다.
- 출처: `docs/specs/ota-undated-many-to-many-20261101.md:13`, `docs/specs/ota.md:30`, `docs/specs/finance.md:69`, `docs/specs/ota.md:191`, `docs/specs/ota.md:217`

### LINK-011 · 정상 카드 비용 준비

*일반 · 결정 2026-10-23*

카드가 금융상 적격이고 실제 여행에 귀속되면 OTA 링크가 EXACT·INFERRED·UNLINKED이거나 결제일이 없어도 내부 비용 준비·미리보기를 허용한다. OTA 자료 읽기 실패만으로 비용 분류를 대기로 남기지 않는다.

- 조건·예외: 카드 원본 자체를 읽지 못했거나 중복·원문 오류·미해결 환불 위험이 있으면 금융 검증을 통과한 것으로 가정하지 않는다.
- 대체된 옛 규칙:
  - 게이트 대상: 기존 OTA 대사가 "연결"로 보는 거래 중, 아직 장부에 기록되지 않았고 사용자·소유자 결정이 없고 보존 상태가 아닌 거래(`app/ota_exact.py`의 `open_transaction_ids`). — 2026-10-16, docs/history/ota-legacy.md:1251
  - 이미 저장된 행별 추론 규칙은 건드리지 않는다. — 2026-10-16, docs/history/ota-legacy.md:1252
  - 이용기간을 아는 행은 막힌 연결의 추론 배정도 막는다(결제 월로 다른 여행을 고르지 않는다, 2026-10-03 추론 규칙). — 2026-10-16, docs/history/ota-legacy.md:1252
  - 막힌 연결: 자동 배정하지 않고 사유와 함께 미연결로 둔다. — 2026-10-16, docs/history/ota-legacy.md:1252
  - 그 밖에 3건
- 출처: `docs/specs/unified-expense-action-queue-20261105.md:197`, `docs/history/operations-20261028-20261107.md:967`, `docs/specs/refactor-master-20261027.md:302`, `docs/history/product-and-handoffs.md:801`, `docs/history/product-and-handoffs.md:1452`

### LINK-012 · 원본 카드 없는 비용 생성 금지

*보호*

예약 확정·포털/메일 관측·예정 결제·추가 OTA 증거만으로 카드 거래나 카드 비용 행을 만들지 않는다. 수집·파서는 사실을 추출하며 금융 결정을 새로 생성하지 않는다.

- 조건·예외: 비카드 캐시·포인트 비용은 별도 승인 계약을 따른다.
- 출처: `docs/specs/ota.md:523`, `docs/specs/ota.md:565`, `docs/specs/ota.md:88`, `docs/specs/ota.md:201`, `docs/specs/ota.md:247`

### LINK-013 · 실제 결제·환불 사건

*일반*

명시 실제 결제 완료가 검증된 charge와 명시 완료 환불만 카드 금전 대조 대상으로 삼는다. 예약 확정·예정 결제·가격 인상 통지·환불 요청·취소 안내는 실제 결제로 승격하지 않고 별도 이벤트로 보존한다.

- 조건·예외: 원결제 하나에 복수 실제 결제·추가 청구·환불 이벤트를 보존하며 취소 통지만으로 charge를 삭제하지 않는다.
- 출처: `docs/specs/finance.md:71`, `docs/specs/ota-review-queue-performance-20261027.md:22`, `docs/history/ota-legacy.md:1211`, `docs/history/ota-legacy.md:678`, `docs/history/ota-legacy.md:688`

### LINK-014 · 실제 결제일 의미

*보호*

실제 결제일은 원문에 명시된 청구 날짜만 사용하고, 관측 시각·수집일·이용기간·예약일·취소 기한·카드 승인일·'오늘 결제됨'으로 합성하지 않는다. 날짜가 없다는 것과 명시 날짜가 충돌한다는 것을 구분한다.

- 조건·예외: 예약일 보완용 최초 메일 수신일과 예정일 대사 예외는 각각 별도 의미로 표시한다.
- 대체된 옛 규칙:
  - 같은 결제일·금액 예약 묶음(M:N)의 결제일 근거는 서명 검증된 예약 확인 메일의 발송일뿐이다. — 2026-10-16, C:/Users/kkokk/.claude/projects/C--AX-cost/memory/feedback-payment-date-evidence.md:11
  - 묶음 판정에는 메일 발송일만 쓴다(`app/ota_mail.py` `shared_lodging_stay`). — 2026-10-16, C:/Users/kkokk/.claude/projects/C--AX-cost/memory/feedback-payment-date-evidence.md:15
  - 메일이 없으면 자동 배정하지 않고 "결제일 근거 없음"으로 보고한다. — 2026-10-16, C:/Users/kkokk/.claude/projects/C--AX-cost/memory/feedback-payment-date-evidence.md:15
  - 실제 결제일: OTA가 고객 카드에 실제로 청구한 날: 결제 완료 메일의 발송일(한국 시간, `app/ota_mail.py`의 `sent_day`). — 2026-10-16, docs/history/ota-legacy.md:1210
- 출처: `docs/session_handoff.md:136`, `docs/history/product-and-handoffs.md:1489`, `docs/specs/ota.md:190`, `docs/history/ota-legacy.md:677`, `docs/specs/ota.md:684`

### LINK-015 · 카드 날짜 기준

*일반*

카드 대조 날짜는 카드 원본의 이용일이며 이용일이 없으면 승인일을 사용한다. 매입일은 실제 사용일/승인일을 채우거나 OTA 이용일을 만드는 근거로 쓰지 않는다.

- 조건·예외: 원본 사용일이 없을 때 매입일을 처리 날짜로 표시하는 것과 결제 증명은 구분한다.
- 대체된 옛 규칙:
  - OTA 결제일과 카드 승인일을 비교한다. — 2026-10-08, docs/history/ota-legacy.md:976
- 출처: `docs/history/product-and-handoffs.md:93`, `docs/history/ota-legacy.md:1198`, `docs/history/ota-legacy.md:1199`, `docs/history/ota-legacy.md:1200`, `docs/history/ota-legacy.md:1202`

### LINK-016 · 날짜 허용 범위

*일반 · 결정 2026-10-16*

알려진 결제일의 KRW는 원칙적으로 같은 카드 이용일을, 외화는 소유자가 승인한 전후 1일을 허용한다. 그 밖의 날짜 차이는 명시 승인된 공급자별 부호 있는 범위 안에서만 허용한다.

- 조건·예외: 차이는 카드 날짜−OTA 결제일로 기록하며 음수/양수 방향을 뒤집지 않는다. 양끝 포함 min/max와 구형 scalar를 한 규칙에 함께 저장하지 않는다.
- 출처: `docs/specs/ota.md:30`, `docs/specs/ota.md:212`, `docs/history/ota-legacy.md:1219`, `docs/history/ota-legacy.md:1225`, `docs/history/ota-legacy.md:1264`

### LINK-017 · 원화·외화 정확 금액

*일반*

원화는 OTA 원문 청구액과 카드 청구 총액을, 외화는 같은 통화의 원문 외화액을 유한 수치로 정확히 비교한다. 환율 추산·반올림·우연한 원화 일치로 외화 근거를 만들지 않는다.

- 조건·예외: 동일 외화액이면 원화 환율·수수료 차이만으로 거부하지 않는다. 무효 금액/근거 없음과 명시 불일치는 구분한다.
- 출처: `docs/specs/ota.md:32`, `docs/specs/finance.md:69`, `docs/history/product-and-handoffs.md:896`, `docs/history/product-and-handoffs.md:1117`, `docs/history/implementation-and-audits.md:924`

### LINK-018 · 결제대행 표기일 때의 연결

*일반 · 결정 2026-11-11*

카드 가맹점이 결제대행사 이름으로 찍혀 공급자 이름과 직접 맞출 수 없는 경우에 한해, 검증된 실제 결제일과 카드 이용일이 같고 같은 통화의 원문 금액이 정확히 같으면 연결한다. 그 밖의 경우에는 LINK-002대로 가맹점명 일치가 필수다.

- **잠정(사용자 확인 대기):** LINK-002(가맹점명과 금액은 필수)와 이 규칙(2026-10-29, 가맹점 별칭 없이 같은 날·같은 금액으로 연결)이 겹친다. 결제대행 표기에만 이 규칙을 남기는 것으로 잠정 정리했다. 다른 선택지: 이 규칙을 없애고 결제대행 표기는 P2가 판정한다.
- 조건·예외: 명시된 카드·발급사·공급자·승인번호가 충돌하면 연결하지 않는다. 수동 연결·원문 오류 보호는 유지한다. 외화의 하루 차이나 할인 차액으로 넓히지 않는다.
- 대체된 옛 규칙:
  - 검증된 실제 결제일과 카드 이용일이 같고 같은 통화의 원문 금액이 정확히 같으면 카드 끝자리·결제 ID·승인 가맹점 별칭이 없어도 연결한다(가맹점 조건 없음). — 2026-11-10·11 사용자 결정으로 대체
  - 카드 끝자리가 없는 OTA도 나머지 묶음 근거와 승인 alias가 충분하고 카드 후보가 하나면 포함하되 원문 끝자리를 채우지 않는다. — 2026-10-23, docs/history/ota-legacy.md:1004
  - 카드 끝자리가 없는 OTA는 승인 alias 또는 승인 규칙이 필요하며 Trip.com은 2026-10-15 결정에 따라 날짜·금액·유일 후보로 판단한다. — 2026-10-16, docs/history/ota-legacy.md:1228
  - 업체 근거: 카드 끝자리가 없는 OTA 결제는 승인된 가맹점 별칭, 또는 승인된 규칙이 있어야 한다. — 2026-10-16, docs/history/ota-legacy.md:1228
  - 그 밖에 4건
- 출처: `docs/specs/ota.md:30`, `docs/specs/finance.md:69`, `app/ota_payments.py:1184`, `docs/history/ota-legacy.md:1228`, `docs/history/ota-legacy.md:981`

### LINK-019 · 카드 정보의 출처

*보호*

OTA 원문에 명시된 발급사·카드 끝4는 카드 원행과 일치해야 한다. 원문에 번호가 없으면 미제공으로 남기고 카드 후보의 끝자리를 OTA 관측 사실로 역주입하지 않는다.

- 조건·예외: 명시 카드 끝4는 숫자 네 자리인지 확인하며 승인된 발급사 별칭만 같은 발급사로 해석한다.
- 출처: `docs/specs/ota.md:32`, `docs/specs/finance.md:69`, `docs/history/session_handoff-through-20261107.md:1140`, `docs/history/operations-20261028-20261107.md:937`, `docs/history/implementation-and-audits.md:120`

### LINK-020 · 비교 가능한 결제 ID

*보호*

승인번호·결제 ID는 양쪽이 같은 의미·namespace·scheme으로 검증된 경우에만 비교한다. 같은 체계의 명시 ID가 다르면 막고, 다른 체계의 문자열 차이만으로 충돌을 만들지 않는다.

- 조건·예외: booking_ref만으로 결제 identity 보강 근거를 만들지 않는다.
- 출처: `docs/specs/ota.md:211`, `docs/history/ota-legacy.md:1227`, `docs/history/ota-legacy.md:690`, `docs/history/ota-legacy.md:981`, `docs/history/ota-legacy.md:1058`

### LINK-021 · 공급자·가맹점 근거

*일반*

가맹점 원문·정규명·확장명과 등록 공급자 이름 또는 승인 별칭을 함께 확인하며 명시 다른 OTA 공급자는 배제한다. 승인 별칭은 승인 상태·출처·버전을 갖추고 완전 토큰 경계로 해석한다.

- 조건·예외: 발급사 별칭도 독립 승인·버전·출처가 필요하고 비활성·철회 별칭은 사용하지 않는다. 별칭만으로 여행·상품을 정하지 않는다. Trip은 가맹점별 반복 승인을 요구하지 않고 승인된 날짜·정확/항공 차액 조건으로 판단한다.
- 대체된 옛 규칙:
  - 클룩 가맹점 별칭 `klook`은 아직 승인하지 않았다. — 2026-10-14, docs/history/ota-legacy.md:1174
  - 넓은 `트립닷컴`은 승인하지 않았다. — 2026-10-09, docs/history/ota-legacy.md:1146
- 출처: `docs/specs/ota-undated-many-to-many-20261101.md:28`, `config/ota-matching-defaults.json:40`, `docs/history/product-and-handoffs.md:896`, `docs/history/operations-through-20261027.md:632`, `docs/history/product-and-handoffs.md:1489`

### LINK-022 · Trip 항공 차액 예외

*사용자 예외 · 결정 2026-10-15*

Trip.com 항공권 KRW 구매는 card−OTA 차액이 −1,000원부터 −10,000원까지 정확히 1,000원 단위일 때 승인 차액 예외를 적용한다. 실제 할인 원인이 확인됐다고 쓰지 않는다.

- 조건·예외: 숙박·다른 상품·다른 공급자·환불·무날짜 정확 금액 조건으로 확대하지 않으며 나머지 카드·날짜·통화·방향 검증은 유지한다. 승인 계약은 행사 기간·결제수단 제한 없이 재사용한다.
- 출처: `docs/history/ota-legacy.md:991`, `docs/history/ota-legacy.md:995`, `docs/history/ota-legacy.md:997`, `docs/history/ota-legacy.md:1144`, `docs/history/ota-legacy.md:992`

### LINK-023 · 전역 배정과 정확 금액 우선

*일반*

금융 배분에서는 유효 edge를 유지한 전역 최대 연결을 구한 뒤 정확 금액 edge를 차액 edge보다 우선하고 안정 순서를 적용한다.

- 조건·예외: 후보 수집 단계에서 유효한 할인 edge를 지우거나 동률인 개별 카드를 임의 선택하지 않는다. M:N 관계 보존과 배분은 별개다.
- 출처: `docs/history/ota-legacy.md:996`, `docs/history/ota-legacy.md:1022`, `docs/history/ota-legacy.md:1101`, `tests/card_pipeline/test_ota_matching_defaults.py:210`, `tests/card_pipeline/test_ota_matching_defaults.py:224`

### LINK-024 · 승인된 좁은 규칙

*일반*

차액·날짜 규칙은 provider·item에 merchant 또는 issuer+끝4를 결합한 좁은 조건과 명시 승인 증거가 있어야 적용한다. 비활성·철회 규칙은 승인 이력이 있어도 적용하지 않는다.

- 조건·예외: 정액 차액은 부호 있는 정수 −10,000~+10,000원, 날짜는 승인된 −7~+7일 범위로 제한하며 bool·실수·숫자 문자열을 정수로 받아들이지 않는다.
- 출처: `docs/history/ota-legacy.md:710`, `docs/history/ota-legacy.md:729`, `docs/history/ota-legacy.md:731`, `docs/history/ota-legacy.md:906`, `docs/history/ota-legacy.md:1101`

### LINK-025 · 비율 할인 규칙

*일반*

비율 할인은 공급자·상품·결제수단·적용기간·최소 결제액·할인율·상한·원 단위 계산법이 확인되고 승인된 경우에만 적용한다. 계산한 할인액의 음수가 실제 card−OTA 차액과 정확히 맞아야 한다.

- 조건·예외: 부족한 조건을 만들지 않으며 할인율은 정수 1~10,000bp, 계산은 명시 floor·half_up·ceiling과 상한을 따른다.
- 출처: `docs/history/ota-legacy.md:997`, `docs/history/ota-legacy.md:1023`, `docs/history/ota-legacy.md:1090`, `tests/card_pipeline/test_ota_matching_defaults.py:80`, `tests/card_pipeline/test_ota_matching_defaults.py:112`

### LINK-026 · 한 번 연결과 재사용 규칙

*일반*

한 번의 수동 연결은 해당 건만 저장하며 규칙을 자동 활성화하지 않는다. 재사용 규칙은 조건을 보여 준 뒤 명시 승인한 범위만 저장하고 편집은 새 pending 제안으로 남긴다.

- 조건·예외: once는 다음 거래에 적용하지 않고 일반 기본값 선택도 미래 제안의 포괄 승인이 아니다. 기존 사용자 확정에 소급 적용하지 않는다.
- 출처: `소유자 지시 메모:feedback-trip-no-per-merchant-approval.md:15`, `docs/history/ota-legacy.md:708`, `docs/history/ota-legacy.md:710`, `docs/history/ota-legacy.md:718`, `docs/history/ota-legacy.md:722`

### LINK-027 · 같은날 전체 카드 후보

*일반*

검증된 결제일 또는 승인된 예약일 기준 카드 검색은 해당 날짜의 모든 원행을 표시하며 가맹점·금액으로 미리 숨기지 않는다. 연결·취소·환불·부적격 사유를 표시하고 실제 선택 가능 여부는 별도 검사한다.

- 조건·예외: 후보 열람은 결제 연결 확정이 아니며 전체 행을 페이지 이동으로 접근할 수 있어야 한다.
- 출처: `docs/history/ota-legacy.md:684`, `docs/history/ota-legacy.md:720`, `docs/history/ota-legacy.md:897`, `docs/history/ota-legacy.md:904`, `docs/history/ota-legacy.md:977`

### LINK-028 · 전역 점유 보호

*보호*

최신 전체 자동·수동·legacy·고정 그룹·예약 관계의 카드 점유를 확인하고 다른 사용자 연결이 소유한 카드를 재사용하지 않는다. 현재 입력에서 사라진 event의 저장 링크도 점유를 유지한다.

- 조건·예외: confirm에는 전체 allocations를 반드시 전달하고 생략/None은 GLOBAL_ALLOCATIONS_REQUIRED로 거부한다. 전체 확인 후 명시한 빈 map만 허용한다.
- 출처: `docs/history/product-and-handoffs.md:1928`, `docs/history/ota-legacy.md:1020`, `docs/history/ota-legacy.md:686`, `docs/history/ota-legacy.md:708`, `docs/history/ota-legacy.md:717`

### LINK-029 · 수동 연결 미리보기

*보호*

결제 수동 연결은 현재 검증된 근거·정상 카드·미점유 상태를 확인한 미리보기와 명시 저장의 두 단계로 수행한다. snapshot 세대·event·카드·규칙·점유·revision·evidence digest가 저장 직전까지 같아야 한다.

- 조건·예외: 변경되면 409 STALE_EVIDENCE 또는 StalePreviewError로 전체 거부하고 현재 근거를 다시 읽는다. 수동 연결을 장부 기록으로 간주하지 않는다.
- 출처: `docs/history/ota-legacy.md:704`, `docs/history/ota-legacy.md:708`, `docs/history/ota-legacy.md:722`, `docs/history/ota-legacy.md:897`, `docs/history/ota-legacy.md:1100`

### LINK-030 · 수동 링크 근거 변경

*보호*

같은 안정 identity의 원문·날짜·금액·카드·예약번호가 바뀌거나 사라져도 기존 수동 링크·카드 점유·저장 snapshot은 보존하고 evidence_changed/evidence_missing을 표시한다.

- 조건·예외: 원래 선택을 삭제하거나 다른 카드로 자동 이동하지 않으며 현재 유효성과 보존 이력을 구분한다.
- 출처: `docs/specs/ota.md:525`, `docs/history/ota-legacy.md:704`, `docs/history/ota-legacy.md:893`, `docs/history/ota-legacy.md:986`, `docs/history/ota-legacy.md:1028`

### LINK-031 · 고정 그룹 불변

*보호*

사용자가 고정한 그룹은 구성원·근거 지문·후보 edge·순서를 보존한다. 새 카드·이벤트·근거 변경으로 signature가 달라지면 기존 카드 점유를 유지하고 변경 경고를 남긴다.

- 조건·예외: GET·재정렬·재대사만으로 고정 배분을 바꾸지 않는다.
- 출처: `docs/specs/ota.md:228`, `docs/history/ota-legacy.md:1040`, `tests/card_pipeline/test_ota_matching_defaults.py:404`, `app/ota_payments.py:1979`

### LINK-032 · 부분 그룹과 임시 점유

*보호 · 결정 2026-11-01*

부분·경합 그룹은 모든 원래 OTA/카드 ID와 대응 수량·차이를 보존한다. 관계를 지우거나 임의 개별 배분을 저장하지 않으며 기존 고정 점유와 금융 잠금을 보호한다.

- 조건·예외: 요청 중 후보 점유와 영구 allocation을 구분한다. 그룹 전체의 명시 확인을 거친 경우만 고정 그룹 allocation으로 저장한다.
- 대체된 옛 규칙:
  - 부분 묶음의 개별 여행·장부 배정은 구분 근거가 생길 때까지 보류하고 카드를 다른 연결에 중복 사용하지 않는다. — 2026-10-23, docs/history/ota-legacy.md:1007
  - 부분 묶음의 개별 여행 및 장부 배정은 구분 근거가 확보될 때까지 보류한다. — 2026-10-08, docs/history/ota-legacy.md:1007
  - 부분 묶음은 양쪽 건수와 ID 전체를 보존하고 개별 연결·장부 배정을 차단한다. — 2026-10-08, docs/history/ota-legacy.md:1038
  - OTA 2건과 카드 1건의 기존 HOLD_AMBIGUOUS 상태도 유지하면서 2:1 건수, 대응 수와 카드 예약을 표시한다. — 2026-10-08, docs/history/ota-legacy.md:1038
- 출처: `docs/specs/ota.md:526`, `docs/specs/ota.md:225`, `docs/specs/ota.md:226`, `docs/history/product-and-handoffs.md:1279`, `docs/history/ota-legacy.md:979`

### LINK-033 · 안정 순서의 의미

*일반 · 결정 2026-10-23*

구분할 개별 결제 증거가 없는 반복 그룹의 회계 배분은 예약번호→이벤트 ID, 카드 승인번호→거래 ID의 안정 순서를 사용한다. 반드시 순서 배정이라고 표시하고 개별 결제 증명으로 표시하지 않는다.

- 조건·예외: 원래 예약 이용기간·수동 고정은 보존한다. 나중의 개별 근거로 차이가 드러나도 조용히 재배정하지 않는다.
- 출처: `docs/history/ota-legacy.md:1002`, `docs/history/ota-legacy.md:1003`, `docs/history/ota-legacy.md:1009`, `docs/history/ota-legacy.md:1010`, `docs/history/ota-legacy.md:1011`

### LINK-034 · 결제 관측 중복 병합

*보호*

메일·포털의 여러 관측은 공통 검증 결제 ID나 명시 source binding이 같은 실물 결제임을 증명할 때만 결제 하나로 묶는다. 같은 예약·날짜·금액·카드·digest라는 이유만으로 병합하지 않는다.

- 조건·예외: 서로 다른 결제 ID는 별도 사건으로 보존하고 여러 출처 digest·계보를 유지한다.
- 출처: `docs/specs/ota.md:419`, `docs/history/ota-legacy.md:675`, `docs/history/ota-legacy.md:676`, `docs/history/ota-legacy.md:1018`, `docs/history/implementation-and-audits.md:152`

### LINK-035 · 안정 identity·계보

*보호*

원본 관측 identity와 논리 결제 identity를 분리하고 복원·경로 이동에도 안정한 source lineage와 기존 event ID crosswalk를 보존한다. 금액·날짜·카드·예약번호·관측시각·경로 같은 가변 필드를 실물 결제 ID로 쓰지 않는다.

- 조건·예외: 새 자료는 공급자·계정·검증된 예약/결제 identity namespace를 쓰며 복구 사본은 동일 원본 계보가 입증될 때만 합친다.
- 출처: `docs/specs/ota.md:158`, `docs/specs/ota.md:160`, `docs/specs/ota.md:162`, `docs/specs/ota.md:163`, `docs/history/implementation-and-audits.md:148`

### LINK-036 · 수집 원본·revision 보존

*보호*

OTA 원본과 source revision·원문 해시·수집 계보·추가 메타데이터를 보존하고 현재 revision으로 조회한다. 이전 파일·DB·revision을 지우거나 런타임에서 중복 원천으로 다시 세지 않는다.

- 조건·예외: 원문은 무손실 보관하고 정규 JSON의 압축 전 해시를 검증한다. 관측 저장을 결제 생성으로 취급하지 않는다.
- 출처: `docs/specs/lean-card-ota-core-20261030.md:21`, `docs/history/operations-through-20261027.md:1532`, `docs/specs/ota.md:679`, `docs/specs/ota.md:680`, `docs/specs/ota.md:682`

### LINK-037 · 자료 완전성

*보호*

등록된 메일·포털·참고자료 전체를 읽고 하나라도 읽기 실패하면 일부만으로 새 권위 자동 연결을 만들지 않는다. 읽기 실패와 실제 근거 부재를 구분하고 기존 저장 수동·legacy 결정은 보존한다.

- 조건·예외: 참고자료도 inventory 완전성에는 포함하지만 그 자체를 결제 증거로 승격하지 않는다.
- 출처: `docs/specs/finance.md:178`, `docs/history/ota-legacy.md:668`, `docs/history/ota-legacy.md:670`, `docs/history/ota-legacy.md:1027`, `docs/history/ota-legacy.md:1036`

### LINK-038 · 중앙 대사 정본

*일반*

동일 입력 snapshot으로 코어 대사기가 후보·거절 사유·관계를 한 번 계산하고 카드·OTA·분류·비용 준비·상세는 그 결과를 공유한다. 화면별 독립 matcher로 다시 판정하지 않는다.

- 조건·예외: 새 snapshot 세대·원문/설정 해시·matcher 버전이 바뀌면 해당 캐시를 무효화한다.
- 출처: `docs/history/session_handoff-through-20261107.md:527`, `docs/specs/python-refactor-results-20261101.md:17`, `docs/specs/ota-undated-many-to-many-20261101.md:31`, `docs/specs/card-completion-recurrence-20261101.md:11`, `docs/specs/lean-card-ota-core-20261030.md:22`

### LINK-039 · stale fallback 경계

*보호*

fresh 중앙 snapshot이 있으면 legacy 결과를 버리고 중앙 정본만 사용한다. 중앙 snapshot이 없거나 stale일 때만 기존 수동 결정·복구 기능을 보존하는 제한적 fallback을 쓰며 그 이유를 표시한다.

- 조건·예외: 진단 전용 legacy_exact_bindings를 웹 정본에 합치지 않으며 fallback으로 신규 fresh 결정을 덮지 않는다.
- 출처: `docs/specs/ota.md:531`, `docs/specs/ota.md:568`, `docs/specs/ota.md:359`, `docs/specs/ota.md:361`, `docs/history/product-and-handoffs.md:1274`

### LINK-040 · legacy exact 바인딩 검증

*보호*

기존 exact binding을 중앙 사건에 옮길 때 검증 exact 근거·provider·예약·digest 교집합과 카드 원행의 통화·금액·끝4·방향을 실제로 대조한다. 유일한 동일 사건에만 pin하며 더 잘 맞는 새 카드로 재추론하지 않는다.

- 조건·예외: report에 없는 카드 사실을 만들지 않고 source 변경·금액 충돌이면 보존 이력과 현재 유효성을 구분한다.
- 출처: `docs/history/ota-legacy.md:695`, `docs/history/ota-legacy.md:697`, `docs/history/ota-legacy.md:895`, `tests/card_pipeline/test_ota_payments.py:239`

### LINK-041 · 읽기 경로의 무변경

*보호*

GET·조회는 refresh 쓰기·DB 생성·디렉터리/스키마 생성·자동 재배정을 하지 않는다. 예약 목록이나 읽기 전용 화면에서 전체 결제 재대사를 수행하지 않는다.

- 조건·예외: DB가 없으면 없는 상태로 반환하고 새 연결을 만들지 않는다.
- 출처: `docs/history/operations-through-20261027.md:1207`, `docs/history/ota-legacy.md:891`, `docs/history/ota-legacy.md:1370`, `tests/card_pipeline/test_ota_review.py:379`, `tests/card_pipeline/test_ota_review.py:490`

### LINK-042 · 보안·원자 저장

*보호*

실제 링크/교정 저장은 owner·비어 있지 않은 CSRF·expected revision·evidence digest·멱등성·전역 점유를 검사하고 원자적으로 저장한다. 동시에 바뀐 근거는 전체 저장을 거절한다.

- 조건·예외: 예약 관계 확인도 같은 트랜잭션에서 기존 결제·그룹·다른 관계 점유를 다시 확인한다.
- 출처: `docs/specs/remaining-workspace-integration-20261108.md:18`, `docs/specs/webledger-idle-io-optimization-20261105.md:75`, `docs/specs/autonomous-expense-cleanup-20261105.md:59`, `docs/specs/autonomous-qa-20261102.md:53`, `docs/specs/ota.md:299`

### LINK-043 · 공개 데이터 최소화

*보호*

공개/비권한 응답·JS 전역·URL·로그·Git·PR·외부 AI에 고객 이름·예약번호·카드번호·원문·토큰·민감 경로를 누출하지 않는다. 필요한 owner DTO만 allowlist로 내보낸다.

- 조건·예외: 고객 원문·토큰 URL·private provenance는 비공개 로컬 증거에만 보존하고 검색은 owner 전용 no-store로 제공한다.
- 출처: `docs/specs/ota-portal-browser-collection-20261110.md:10`, `docs/specs/status-and-inference-stages-20261102.md:30`, `docs/specs/autonomous-expense-cleanup-20261105.md:48`, `docs/specs/toyoko-collection-audit-20261103.md:15`, `docs/specs/jeju-ota-card-scope-20261103.md:12`

### LINK-044 · 판정 근거와 불확실성

*일반*

MATCH/MISMATCH/UNKNOWN 신호·출처·policy version·명시 충돌·후보 순위를 구분하고 INFERRED를 실제 결제 확정으로 표시하지 않는다. 코드 추론과 AI 추론·수동 확인의 출처를 구분한다.

- 조건·예외: 검증된 정답 표본 없이는 점수를 실제 확률·precision/recall로 부르지 않고 자료/원행/실제 결제 사건 집계 분모를 구분한다.
- 출처: `docs/history/session_handoff-through-20261107.md:413`, `docs/history/session_handoff-through-20261107.md:457`, `docs/history/operations-20261028-20261107.md:1350`, `docs/history/product-and-handoffs.md:1880`, `docs/history/operations-20261028-20261107.md:1120`

### LINK-045 · 판정 완료와 교정

*일반 · 결정 2026-11-10*

정상 거래는 P1 또는 P2가 판정을 마치고 사용자는 분기 검수에서 교정한다. 사용자 작업함·질문 대기·미분류·분류 대기·확정 대기·보류 해제 화면과 상태를 다시 만들지 않는다.

- 조건·예외: 폐지 대상은 사용자 대기 UX이며 중복·원본 충돌·환불 짝 등 내부 금융 안전 잠금과 실제 사실 미확인은 보존한다.
- 대체된 옛 규칙:
  - 원결제 1건과 여러 취소·부분환불, 같은 예약의 여러 OTA 이벤트, 한 영수증과 카드 거래가 같은 질문을 요구하면 각각 별도 작업으로 세지 않는다. — 2026-11-05, docs/specs/unified-expense-action-queue-20261105.md:233
  - OTA 예약·카드 연결: 연결이 실제 비용 귀속/환불 판단에 필수이고 기존 자료로 결정할 수 없을 때: 관련 예약·결제·취소 근거를 같은 작업에 묶음. — 2026-11-05, docs/specs/unified-expense-action-queue-20261105.md:263
  - OTA 예약 검토: 예약 근거·연결 상세. — 2026-11-05, docs/specs/unified-expense-action-queue-20261105.md:364
  - 사람 판단이 필요한 경우 같은 작업 카드의 근거 탭으로 연결. — 2026-11-05, docs/specs/unified-expense-action-queue-20261105.md:364
  - 그 밖에 18건
- 출처: `docs/specs/uiux-full-audit-redesign-20261110.md:751`, `docs/specs/lean-card-ota-core-20261030.md:61`, `docs/specs/finance.md:75`, `docs/specs/ota-review-queue-performance-20261027.md:50`, `docs/specs/ota-review-queue-performance-20261027.md:56`

### LINK-046 · 자료 노후만으로 숨기지 않기

*일반 · 결정 2026-10-28*

미해결 OTA 자료는 90일이 지났다는 이유만으로 완료·archive·숨김 처리하지 않고 목록·검색에서 계속 접근 가능하게 둔다.

- 조건·예외: 별도로 소유자가 완료 자료로 지정한 2025년·2026년 1분기 범위의 신규 검토 제외는 다른 정책이다.
- 출처: `docs/history/provisional-assignment-review-first-20261028.md:8`, `docs/history/provisional-assignment-review-first-20261028.md:173`

### LINK-047 · 보존 완료 기간 제외

*사용자 예외*

소유자가 보존 완료로 정한 2025년과 2026년 1분기 자료는 원본을 보존하며 신규 카드·OTA 검토 목록에서 제외한다. 카드에는 원본 거래일, OTA에는 실제 이용기간을 적용한다.

- 조건·예외: 단순 90일 경과 숨김으로 일반화하지 않고 과거 자료·관계·결정을 삭제하지 않는다.
- 출처: `docs/specs/finance.md:159`, `docs/history/operations-through-20261027.md:1037`, `app/ota_mail.py:758`

### LINK-048 · 실제 여행 우선 귀속

*일반 · 결정 2026-11-08*

정상 카드에 실제 권위 여행 후보가 있으면 낮은 신뢰·동률이어도 최선 후보에 AUTO_INFERRED로 귀속하고 근거·불확실성을 남긴다. 여행은 창작하지 않으며 후보가 없으면 승인된 분기 기타비용 귀속을 적용한다.

- 조건·예외: 수동 이동이 최우선이며 비용 분류 완료를 개별 OTA 결제·실제 이용·환급 완료로 해석하지 않는다.
- 코드와 다른 점: tests/card_pipeline/test_ota_inference.py:137은 여행 동률을 CONFLICT_REVIEW로 남긴다. 현재 정상 카드의 최선 여행/분기 목적지 판정과 내부 금융 잠금을 구분하고 사용자 분류 대기 상태로 쓰지 않아야 한다.
- 대체된 옛 규칙:
  - 정상 여행 후보가 없으면 여행은 창작하지 않고 비용 항목 분류만 완료한다. — 2026-10-29, docs/specs/finance.md:88
  - 캐시 사용 예약은 이용일을 덮는 검증 여행이 하나면 그 여행에, 없거나 여러 개면 미배정에 두며 취소·환불 예약은 기장하지 않는다. — 2026-10-29, docs/specs/finance.md:111
  - 이용일을 덮는 검증된 여행이 하나뿐이면 그 여행에, 없거나 여러 개면 미배정에 둔다(`app/ota_cash_use.py`). — 2026-10-29, docs/specs/finance.md:111
  - authoritative 여행 자체가 없을 때만 미배정하고 여행을 창작하지 않는다. — 2026-10-29, docs/specs/finance.md:113
  - 그 밖에 6건
- 출처: `docs/specs/autonomous-expense-cleanup-20261105.md:73`, `docs/specs/finance.md:88`, `docs/specs/finance.md:95`, `docs/specs/finance.md:113`, `tests/card_pipeline/test_ota_inference.py:137`

### LINK-049 · 이용기간 우선·여행 순위

*일반*

검증된 예약 이용기간·출발일은 결제일 근접성·가맹점 지명·잔여 비용 기본 규칙보다 여행 귀속에 우선한다. 수동 결정 다음으로 검증 예약 연결과 실제 여행 일정을 대조한다.

- 조건·예외: 기간 전체를 덮는 여행, 겹치는 밤 수, 승인된 동률 순위·수입−비용 차액 등을 적용하되 수동 교정·금융 보호는 유지한다.
- 출처: `docs/specs/recorded-booking-period-correction-20261103.md:9`, `docs/specs/remaining-acceptance-20261030.md:28`, `docs/specs/lean-card-ota-core-20261030.md:41`, `docs/specs/finance.md:79`, `docs/specs/finance.md:95`

### LINK-050 · 이용기간 사실 보존

*보호*

체크인·체크아웃·픽업·반납·출발 등은 검증된 예약 원문에서 읽고 종료일을 임의로 하루 줄이거나 없는 기간을 만들지 않는다. 취소·기간 충돌은 원결제와 별개로 기간의 유효성을 표시한다.

- 조건·예외: 기간이 미확인/충돌이면 첫 메일·카드 결제일을 대신 쓰지 않는다. 정상 카드 최종 귀속 판정은 별도 최선 후보 규칙을 따른다.
- 출처: `docs/operations.md:104`, `docs/history/session_handoff-through-20261107.md:413`, `docs/history/product-and-handoffs.md:1342`, `docs/history/ota-legacy.md:1010`, `docs/history/ota-legacy.md:1355`

### LINK-051 · 장부 날짜·결제수단

*일반*

OTA 예약의 장부 날짜는 체크인·픽업·출발 등 이용일이며 이용일이 없을 때만 결제일을 쓴다. 한 예약의 카드·캐시는 같은 예약번호로 묶되 별도 지불수단과 비용 근거를 보존한다.

- 조건·예외: 이미 기록된 날짜는 자동 변경하지 않고 서로 다른 날짜 의미는 출처로 구분한다.
- 출처: `docs/specs/finance.md:110`, `docs/history/product-and-handoffs.md:95`, `소유자 지시 메모:owner-rules.md:12`

### LINK-052 · 캐시·포인트 비용

*사용자 예외*

AgodaCash·Klook 포인트·TripCoin 등 사용분은 카드 결제가 함께 있든 없든 별도 비용으로 반영하며 적립과 사용을 구분한다. 원문 원화 환산액을 우선하고 엔화만 있으면 승인 간편환율 100엔=1,000원을 쓴다.

- 조건·예외: 취소·환불 예약은 기장하지 않으며 비카드 여행 검증 특례를 일반 카드 결제 확정으로 확대하지 않는다.
- 출처: `docs/specs/finance.md:111`, `docs/specs/finance.md:113`, `docs/history/product-and-handoffs.md:96`, `docs/history/implementation-and-audits.md:124`, `docs/history/implementation-and-audits.md:163`

### LINK-053 · 확정 메타데이터 투영

*보호*

카드별 예약번호는 현재 검증된 개별 연결의 활성 예약 identity가 유일하고 근거 digest가 있을 때만 장부 메타데이터로 전달한다. 순서 배정·여러 개별 결과 경합·취소·충돌은 예약번호 확정 근거로 쓰지 않는다.

- 조건·예외: 개별 번호가 불명확하면 비우고 검증 공통 이용기간만 표시할 수 있다.
- 출처: `docs/specs/ota.md:224`, `docs/history/ota-legacy.md:1338`, `docs/history/ota-legacy.md:1340`

### LINK-054 · 미리보기 digest·원자 기록

*보호*

예약번호·이용기간·OTA provenance를 미리보기 digest에 포함하고 기록 때 새 resolver의 최신 근거와 다시 비교한다. 달라지면 PREVIEW_STALE로 거절하며 검증된 행을 그대로 projection한다.

- 조건·예외: 예약번호·기간은 기존 board_rows payload, 근거는 classification_basis에 보존하며 ledger_entries를 불필요하게 확장하지 않는다.
- 출처: `docs/history/operations-through-20261027.md:1368`, `docs/history/ota-legacy.md:1340`, `docs/history/operations-through-20261027.md:77`, `docs/history/operations-through-20261027.md:78`, `docs/history/operations-through-20261027.md:81`

### LINK-055 · 이용기간 표시 보완

*일반*

기존 M:N MATCHED_GROUP의 모든 관련 관측 기간이 완전하고 동일하거나 검증 개별 연결에서 기간 메타데이터만 비어 있을 때만 이용기간 표시를 보완한다. 개별 결제·예약번호·장부 사실을 새로 확정하지 않는다.

- 조건·예외: 순서 배분·취소/환불·충돌·stale·불완전/서로 다른 기간·수동 빈값·다른 저장 예약번호·기존 기간은 보호한다.
- 출처: `docs/specs/ledger-flight-service-dates-20261105.md:7`, `docs/specs/ledger-flight-service-dates-20261105.md:25`, `docs/specs/toyoko-collection-audit-20261103.md:12`, `docs/specs/ledger-sort-insurance-followup-20261030.md:5`, `docs/history/implementation-and-audits.md:532`

### LINK-056 · Google 경계

*보호*

COST는 Google 최종 장부를 자동으로 쓰지 않으며 사용자가 검토 후 직접 붙여넣는다. 추정·미확정 예약번호는 복사 예약번호 열에 넣지 않고 정상 비용 행은 유지한다.

- 조건·예외: 실제 Google 반영·은행 환급은 별도 확인 없이 완료로 표시하지 않는다.
- 출처: `docs/history/product-and-handoffs.md:1467`, `docs/specs/ota.md:530`, `docs/specs/ota.md:573`, `docs/history/operations-through-20261027.md:786`, `docs/specs/ota.md:74`

### LINK-057 · Google 대조 예약번호

*보호*

웹 장부와 Google 지출의 예약번호 일치는 확인된 실제 예약번호가 완전히 같을 때만 인정한다. 빈값·placeholder·추정 ID는 일치로 보지 않는다.

- 조건·예외: 비용·날짜 의미·서비스 기간이 다른 경우 추가 근거를 비교하고 금액만으로 1:1을 단정하지 않는다.
- 출처: `docs/specs/sheet-manual-expense-dedup-20261029.md:28`, `docs/specs/sheet-manual-expense-dedup-20261029.md:39`, `docs/specs/google-ledger.md:645`

### LINK-058 · 원승인번호 1:N 환불

*일반 · 결정 2026-10-29*

같은 발급사·카드의 원승인번호가 하나의 정상 원결제를 가리키면 여러 취소·부분환불을 모두 그 원결제에 연결한다. 개별 취소 금액을 보존하고 gross·refunds_total·net 및 full/partial/excess를 파생한다.

- 조건·예외: 원결제 중복·원문 오류·초과 환불·내부 금융 잠금은 보호하며 연결만으로 은행 환급·Google·OTA 예약 이용을 확정하지 않는다.
- 출처: `docs/specs/unified-expense-action-queue-20261105.md:104`, `docs/specs/unified-expense-action-queue-20261105.md:196`, `docs/specs/finance.md:71`, `docs/specs/refactor-master-20261027.md:303`, `docs/history/product-and-handoffs.md:655`

### LINK-059 · 승인번호 없는 환불 짝

*일반 · 결정 2026-10-29*

원승인번호가 없어도 동일 발급사·카드·가맹점·이용일·정확 원화 금액의 양수/음수 원행이 유일하게 대응하면 취소·환불 쌍으로 연결한다.

- 조건·예외: 다른 근거 유형을 원승인번호 연결이라고 표시하지 않고 실제 환급 완료와 분리한다.
- 출처: `docs/specs/finance.md:61`, `docs/history/operations-through-20261027.md:542`

### LINK-060 · 업무 수행 보고

*보호*

근거 조회·새 연결·분류 교정·실제 내부 저장·Google 반영·실제 환급을 수행한 범위대로 각각 보고한다. 이미 있는 연결을 조회한 것을 새 적용으로 쓰거나 일부 완료를 전체 완료로 확대하지 않는다.

- 조건·예외: 정상 전액취소 쌍의 연결 확인·순액0과 이번 쓰기0을 구분한다.
- 출처: `docs/specs/finance.md:75`, `docs/specs/ota.md:281`, `docs/history/operations-through-20261027.md:1530`, `docs/history/implementation-and-audits.md:163`

### LINK-061 · 메일 발신 인증

*일반 · 결정 2026-11-11*

사용자가 직접 수집한 메일은 공급자와 관계없이 발신 서명 확인 없이 근거로 쓴다. 발신 주소의 도메인이 등록된 공급자 도메인(또는 그 하위 도메인)과 맞는지만 본다.

- 조건·예외: `trip.com.example`처럼 공급자 도메인 뒤에 다른 이름이 붙은 유사 도메인은 받지 않는다. 서명된 발송일·실제 수신 시각·수신 지연은 서로 다른 값으로 구분한다.
- 대체된 옛 규칙:
  - 직접 수집 메일의 발신 서명 면제는 숲나들e 메일에만 적용한다. — 2026-11-10·11 사용자 결정으로 대체
- 출처: `docs/history/operations-20261028-20261107.md:287`, `docs/specs/ota.md:36`, `app/ota_mail.py:176`, `app/ota_mail.py:173`, `app/ota_mail.py:180`

### LINK-062 · 메일 충돌·중복

*보호*

같은 메일 ID의 재수집은 중복 제거하되 본문·인증 헤더가 다르면 충돌로 중단하고 적재를 롤백한다. 첨부 정보 보완은 원본 본문·인증 일치 범위에서만 허용한다.

- 조건·예외: 같은 거래의 같은 원문 중복과 서로 다른 실제 거래 다중도를 구분한다.
- 출처: `docs/specs/ota.md:680`, `docs/history/ota-legacy.md:1302`, `docs/history/ota-legacy.md:1357`, `docs/history/ota-legacy.md:1380`, `docs/history/operations-through-20261027.md:370`

### LINK-063 · 예약 identity와 그룹

*보호*

예약 identity는 공급자·계정·검증 예약번호·source lineage로 구분한다. 다른 공급자·계정의 같은 번호와 단순 이름·동액·근접 날짜만으로 예약을 합치지 않는다.

- 조건·예외: 암호화 URL 토큰·로컬 결제 solver 그룹 ID를 검증 예약번호나 예약 그룹 키로 쓰지 않는다.
- 출처: `docs/specs/trip-flight-booking-overview-20261028.md:185`, `docs/specs/ota.md:48`, `docs/specs/ota-review-queue-performance-20261027.md:138`, `docs/specs/ota-review-queue-performance-20261027.md:62`, `docs/specs/ota-review-queue-performance-20261027.md:165`

### LINK-064 · 예약 컨테이너와 사건

*일반*

검증된 같은 예약은 표시 컨테이너만 공유하며 그 아래 여러 charge·installment·amendment·cancellation·refund의 원본 ID·금액·통화·의미를 보존한다.

- 조건·예외: 검증 동일 통화의 순액만 파생 표시하고 예약 하나라는 이유로 실제 여러 결제를 하나로 줄이지 않는다.
- 출처: `docs/specs/ota.md:48`, `docs/specs/ota-review-queue-performance-20261027.md:64`, `docs/history/implementation-and-audits.md:152`, `docs/history/ota-legacy.md:668`, `docs/history/ota-legacy.md:975`

### LINK-065 · 메일 기간 보강 수집

*일반*

카드 조회기간보다 앞선 예약 메일도 있을 수 있으므로 기간 근거가 누락된 검증 예약은 공급자·예약번호로 날짜 제한 없이 확정·변경·취소·결제 메일을 추가 조회한다. 인증된 같은 예약의 기간 근거를 결제 이벤트에 결합한다.

- 조건·예외: 기간 충돌은 보존하고 카드 결제일로 이용기간을 대체하지 않는다. 메일 검색 결과만으로 포털 근거 부재를 단정하지 않는다.
- 출처: `docs/history/operations-through-20261027.md:937`, `docs/history/operations-through-20261027.md:1496`, `docs/history/operations-through-20261027.md:1526`, `docs/history/operations-through-20261027.md:1527`, `docs/history/ota-legacy.md:1324`

### LINK-066 · 메일·포털 충돌 우선순위

*보호*

기존 예약 메일은 오래된 포털 기록보다 우선하되 같은 실물 결제의 명시 사실이 충돌하면 어느 쪽도 임의로 정상 확정하지 않는다. 새 관측이 더 최신이라는 이유로 사용자 결정이나 충돌을 덮지 않는다.

- 조건·예외: 시간에 따른 예정→완료 상태 변화와 같은 시점 금액·기간 충돌을 구분하며 취소 이후 정상 복귀도 검토한다.
- 출처: `docs/specs/finance.md:109`, `docs/history/operations-through-20261027.md:913`, `docs/history/operations-through-20261027.md:926`, `docs/specs/ota.md:684`, `docs/history/implementation-and-audits.md:150`

### LINK-067 · 포털 원문 검증

*보호*

포털 자료는 identity·service_period·payment claim·card observation·lifecycle의 다섯 evidence role과 원문 hash를 검증한다. 부족하거나 원문 해시가 다르면 확정 자료로 쓰지 않는다.

- 조건·예외: 확인하지 않은 collection_model 등 필드를 파서 통과를 위해 만들지 않으며 미지원 양식은 실제 표본을 확인하고 확장한다.
- 출처: `docs/history/implementation-and-audits.md:124`, `docs/history/ota-legacy.md:1324`, `docs/history/implementation-and-audits.md:86`, `app/ota_portal.py:44`, `app/ota_portal.py:165`

### LINK-068 · 포털 결제 의미

*일반*

포털 예약/투숙 완료만으로 paid를 만들지 않고 양의 유한 카드 결제액·minor units 및 실제 결제 관측을 확인한다. '오늘 결제됨'은 표시 사실로 보존하되 날짜를 채우지 않는다.

- 조건·예외: 기존 canonical/legacy paid 분기는 공급자별 명시 상태·collection model의 검증 요건을 지킨다.
- 출처: `docs/specs/finance.md:71`, `docs/specs/ota-review-queue-performance-20261027.md:56`, `docs/history/implementation-and-audits.md:118`, `docs/history/implementation-and-audits.md:154`, `docs/history/ota-legacy.md:1216`

### LINK-069 · 예정일 카드 대사 예외

*사용자 예외 · 결정 2026-10-16*

Agoda 예정 자동결제는 실제 카드 원행의 이용일=명시 예정일, 양의 KRW 총액·끝4·가맹점·purchase 방향이 맞고 확정·비취소·비환불 상태이며 예약과 카드가 상호 유일할 때 승인 예외로 연결한다. 예정 안내 자체를 결제 영수증이라고 부르지 않는다.

- 조건·예외: base+taxes가 있으면 gross와 같아야 하고 source conflict는 upcoming→confirmed 진행만 허용한다. 다른 링크 점유 카드는 제외한다.
- 출처: `docs/specs/ota.md:190`, `docs/history/implementation-and-audits.md:161`, `소유자 지시 메모:project-agoda-scheduled-charge-rows.md:17`, `docs/history/ota-legacy.md:1211`, `docs/history/ota-legacy.md:1267`

### LINK-070 · 예정결제 snapshot 신선도

*보호 · 결정 2026-10-16*

운영 authority 경로에서 예정일 연결을 비용 준비에 쓰는 경우 최신 snapshot의 scheduled_card_ids만 인정한다. 오래된 snapshot으로 새 예정 결제 연결을 인정하지 않는다.

- 조건·예외: 기존 사용자 결정을 덮지 않고 다른 결과에 이미 점유된 원행은 제외한다.
- 출처: `소유자 지시 메모:project-agoda-scheduled-charge-rows.md:15`, `docs/history/ota-legacy.md:1267`, `소유자 지시 메모:feedback-classify-records-automatically.md:15`

### LINK-071 · Agoda 비용 항목

*사용자 예외 · 결정 2026-10-04*

소유자가 정한 Agoda 표기 가맹점 그룹의 비용 항목은 숙박비로 재사용한다. 항목 분류와 여행·예약번호·실제 결제 identity 연결은 별도로 판단한다.

- 조건·예외: 취소·환불과 기존 수동 교정을 보호하고 금액이나 날짜를 바꾸지 않는다.
- 출처: `docs/history/ota-legacy.md:1344`, `docs/specs/finance.md:257`

### LINK-072 · Trip·Klook 상품 분류

*일반*

Trip.com·Klook·결제대행 이름만으로 항공·숙박·교통 항목을 정하지 않고 검증 예약 상품을 대조한다. 복수 후보가 모두 같은 상품 종류일 때만 공통 항목을 제안한다.

- 조건·예외: 개별 예약번호·이용기간이 불확실한 경우 공통 항목 분류와 결제 identity를 분리한다.
- 출처: `docs/specs/python-refactor-followup-results-20261102.md:58`, `소유자 지시 메모:feedback-trip-no-per-merchant-approval.md:15`, `docs/history/ota-legacy.md:1354`, `docs/specs/finance.md:264`, `tests/card_pipeline/test_booking_mail.py:76`

### LINK-073 · 공통 숙박기간

*일반*

동액의 여러 숙박 예약 후보가 모두 같은 검증 이용기간이고 취소·기간 충돌이 없으면 공통 기간과 후보 수를 보존해 여행/숙박 표시를 보완할 수 있다. 개별 예약번호를 임의 선택하지 않는다.

- 조건·예외: M:N 관계 보존과 개별 결제 검증은 별개이며 원래 기간을 덮지 않는다.
- 출처: `docs/specs/ledger-service-date-investigation-20261109.md:28`, `docs/specs/ledger-service-date-investigation-20261109.md:30`, `docs/specs/ota.md:224`, `소유자 지시 메모:project-ota-mn-open-items.md:11`, `docs/history/ota-legacy.md:1246`

### LINK-074 · 취소·정책·환불 구분

*보호*

취소 완료·요청·취소 정책·위약금 안내·환불 예정·완료 환불을 구분한다. 취소 통지 수신시각이 잘못돼도 확인된 취소 사실을 버리지 않고 원결제·카드 취소 원행은 별도 보존한다.

- 조건·예외: 취소된 이용기간을 실제 이용 여행의 확정 근거로 쓰지 않으며 원문 충돌은 별도 검토한다.
- 코드와 다른 점: tests/card_pipeline/test_airline_payment_mail.py:87은 항공사 취소 통지에서 기존 paid 근거를 evidence_conflict로 두고 검증을 중지한다. 일반 취소 예약의 이미 검증된 charge·관계 유지 규칙과 다르므로 신규 검증 중지와 과거 원결제/관계 삭제를 구분해야 한다.
- 출처: `docs/specs/finance.md:71`, `docs/history/operations-through-20261027.md:895`, `docs/history/operations-through-20261027.md:904`, `docs/history/operations-through-20261027.md:926`, `docs/history/implementation-and-audits.md:660`

### LINK-075 · Klook 온라인 실결제

*일반*

Klook 렌터카·티켓은 포인트 사용 후 실제 온라인 카드 결제액만 대조하고 현장 잔금·보증금·무료 티켓 수령 안내 금액을 더하지 않는다.

- 조건·예외: 유료 교통 예약에 딸린 0원 안내는 명시 상품명·0원이 확인될 때만 별도 구매에서 제외한다. 다른 상품/결제액이 있으면 근거를 분리한다.
- 출처: `docs/history/ota-legacy.md:1352`, `docs/specs/finance.md:271`, `tests/card_pipeline/test_booking_mail.py:23`, `tests/card_pipeline/test_booking_mail.py:31`, `tests/card_pipeline/test_booking_mail.py:62`

### LINK-076 · Trip 렌터카

*일반*

Trip 렌터카는 명시 온라인 선결제액·실제 결제 성공 근거를 카드 대조에 사용한다. 총액·보증금만으로 결제 완료를 주장하지 않으며 실제 결제 실패 통지가 있으면 paid로 만들지 않는다.

- 조건·예외: 조건부 고객센터 안내만으로 실제 선결제 근거를 무효화하지 않는다. 인수·반납 기간은 원문 유효 날짜만 사용한다.
- 출처: `tests/card_pipeline/test_ota_trip_rental_mail.py:30`, `tests/card_pipeline/test_ota_trip_rental_mail.py:43`, `tests/card_pipeline/test_ota_trip_rental_mail.py:63`, `tests/card_pipeline/test_ota_trip_rental_mail.py:83`, `tests/card_pipeline/test_ota_trip_rental_mail.py:93`

### LINK-077 · Booking 영수증

*일반*

Booking.com은 명시 실제 영수증 결제일과 온라인 실결제액을 읽고 현장 세금은 분리한다. 명시 결제일 관측이 충돌하면 검증 charge로 승격하지 않는다.

- 조건·예외: 예정 영수증은 실제 paid가 아니다. 외화는 올바른 소수점·천 단위 구분으로 같은 통화 금액을 비교한다.
- 출처: `docs/history/operations-through-20261027.md:866`, `docs/history/operations-through-20261027.md:937`, `docs/history/ota-legacy.md:1353`, `tests/card_pipeline/test_ota_payments.py:613`, `tests/card_pipeline/test_ota_payments.py:633`

### LINK-078 · Trip 가격 인상

*보호*

Trip 가격 인상 통지는 예약 근거이며 명시 최신 총액의 순서와 원결제 근거가 있을 때만 차액 후보를 계산한다. 카드 날짜·금액이 맞더라도 통지만으로 실제 charge·자동 결제 링크를 만들지 않는다.

- 조건·예외: 취소 예약·숙박기간 변경·원결제 없는 경우 차액 결제 후보를 만들지 않는다.
- 출처: `tests/card_pipeline/test_trip_price_change_charge.py:55`, `tests/card_pipeline/test_trip_price_change_charge.py:60`, `tests/card_pipeline/test_trip_price_change_charge.py:70`, `tests/card_pipeline/test_trip_price_change_charge.py:83`, `app/ota_payments.py:1344`

### LINK-079 · 숲나들e 인증 예외

*사용자 예외 · 결정 2026-10-28*

소유자가 수집한 숲나들e 예약·취소 안내는 공식 발신 도메인 경계를 확인한 뒤 예약 근거로 사용하고 DKIM 부재만으로 업무 대기로 두지 않는다.

- 조건·예외: SPF/DKIM은 참고 기록이며 다른 공급자의 인증 정책을 이 예외로 바꾸지 않는다.
- 출처: `docs/specs/ota.md:36`

### LINK-080 · 번호 없는 예약 관측

*보호 · 결정 2026-10-30*

숲나들e의 실제 공급자 예약번호가 없으면 booking_ref를 비우고 개별 안내·source revision별 예약 관측으로 보존한다. 내부 event 조회 키·주문번호를 실제 예약번호로 만들지 않는다.

- 조건·예외: 서로 다른 번호 없는 안내를 합치거나 취소·카드 후보를 전파하지 않고 종료일이 없으면 미확인으로 둔다.
- 출처: `docs/specs/ota.md:20`, `docs/specs/ota.md:22`, `docs/history/session_handoff-through-20261107.md:951`, `docs/specs/ota.md:38`, `docs/specs/ota.md:48`

### LINK-081 · 숲나들e 카드 후보

*사용자 예외 · 결정 2026-10-28*

숲나들e 후보는 시설명 또는 안내 주소의 지자체 군/시청 가맹점과 발송일/이용일 전후7일을 대조한다. 공통 휴양시설 가맹점은 낮은 확신 후보로만 보여 주고 시설·금액 미확인을 표시한다.

- 조건·예외: 후보 자체는 금융 연결·카드 점유·기장 권한이 없으며 중복·원문 오류·환불/취소·금융 잠금·기존 점유를 보호한다.
- 출처: `docs/specs/ota.md:40`, `docs/specs/ota.md:44`

### LINK-082 · 숲나들e 관계 저장

*보호 · 결정 2026-10-28*

숲나들e 예약 관계는 미리보기·revision·원문 digest·멱등성·점유 보호를 거쳐 별도 저장하며 결제 검증·여행·기장·환급 완료로 승격하지 않는다. 시설·객실·출처 변경은 stale로 표시하고 이력을 보존한다.

- 조건·예외: 원결제 환불 관계와 내부 금융 보호 대상은 자동 관계로 덮지 않는다.
- 출처: `docs/specs/ota.md:44`

### LINK-083 · NICE 휴양림 결제 근거

*사용자 예외 · 결정 2026-10-28*

인증된 NICE 휴양림 카드 영수증의 실제 결제는 같은 발급사·카드 끝4·승인번호·이용일·정확 원화 금액과 전역 점유·원문 정상성을 모두 검증해 기존 코어로 연결한다.

- 조건·예외: 주문번호를 예약번호로 쓰거나 카드 끝4·이용기간을 만들지 않는다. 취소 안내는 예약 취소/은행 환급 완료와 다른 관측이다.
- 출처: `docs/specs/ota.md:26`, `docs/specs/ota.md:46`, `app/ota_payments.py:1226`

### LINK-084 · Toyoko 예약 관계 추론

*사용자 예외 · 결정 2026-10-24*

Toyoko는 지점·숙박기간·원문 통화/금액이 맞고 전체 자료에서 상호 유일한 경우 자동 예약 추론 관계를 표시한다. 금액이 원문에 없더라도 지점·기간의 상호 유일 근거만 있으면 낮은 신뢰의 관계로 표시할 수 있다.

- 조건·예외: 결제일 미확인·payment_verified=false를 유지하고 객실별 예약과 합계 예약을 별도 실제 결제로 세지 않는다. 경합/명시 불일치는 정확 연결로 승격하지 않는다.
- 출처: `docs/history/product-and-handoffs.md:1121`, `docs/history/implementation-and-audits.md:533`, `docs/history/implementation-and-audits.md:911`, `docs/history/implementation-and-audits.md:922`, `docs/history/implementation-and-audits.md:923`

### LINK-085 · Toyoko 관계 저장 보호

*보호*

Toyoko 사용자가 확인한 예약 관계는 전용 review 저장소·이력에 보존하며 기존 결제·그룹·다른 예약 관계 점유를 저장 트랜잭션 안에서 재검사한다. 근거 변경·소실 뒤에도 선택을 보존하고 결제 검증으로 바꾸지 않는다.

- 조건·예외: 금액/지점 미확인과 명시 금액 불일치를 구분하고 카드 원본·수동 여행·추론 번호 Google 복사 금지·금융 잠금을 지킨다.
- 출처: `docs/history/product-and-handoffs.md:1115`, `docs/history/product-and-handoffs.md:1119`, `docs/history/product-and-handoffs.md:1121`, `docs/history/implementation-and-audits.md:925`, `docs/history/implementation-and-audits.md:926`

### LINK-086 · 포털 조회 권한

*보호 · 결정 2026-11-10*

Agoda·Trip.com·Booking.com 수집은 ego lite의 예약 계정 로그인 세션에서 읽기 전용 내부 API 조회로 수행한다. 예약 변경·취소·결제·메시지·다른 계정 로그인/보안 우회를 하지 않는다.

- 조건·예외: 인증이 필요하면 사용자에게 넘기며 메일함 인증과 Trip 별도 예약 검색 인증은 구분한다. 이전 IAB 화면 증거는 보존한다.
- 대체된 옛 규칙:
  - Agoda 수집은 전용 Paseo IAB 세션만 사용한다. — 2026-10-23, docs/history/product-and-handoffs.md:108
- 출처: `AGENTS.md:49`, `docs/specs/ota-portal-browser-collection-20261110.md:3`, `docs/specs/ota-portal-browser-collection-20261110.md:7`, `docs/specs/ota-portal-browser-collection-20261110.md:8`, `docs/history/product-and-handoffs.md:1094`

### LINK-087 · 포털 수집 한도

*일반 · 결정 2026-11-10*

포털 목록 요청은 최대5회, 상세 요청은 최대3회까지 재시도하고 동시 요청은6개 이하로 제한한다. 로그인·보안 확인 실패는 우회하지 않는다.

- 조건·예외: 일부 수집 실패를 전체 근거 없음이나 성공으로 위장하지 않는다.
- 출처: `docs/specs/ota-portal-browser-collection-20261110.md:9`

### LINK-088 · 포털 상세 identity 검증

*보호 · 결정 2026-11-10*

포털 목록의 예약 identity와 상세의 실제 예약번호가 일치할 때만 저장한다. 이전 화면 수집은 해당 예약번호와 상세 진입 버튼을 함께 확인한 증거를 유지한다.

- 조건·예외: 상세가 다른 예약이면 저장하지 않고 해당 항목을 중단한다. 결제 근거가 불완전한 예약도 예약 목록에는 조회할 수 있다.
- 출처: `docs/history/product-and-handoffs.md:108`, `docs/history/implementation-and-audits.md:110`

### LINK-089 · Agoda API 카드 결제

*일반 · 결정 2026-11-10*

Agoda API의 카드 결제 줄만 실제 청구 근거로 해석하고 음수 환급·조정 줄은 구매 charge에 넣지 않고 내부 환불 검토 대상으로 분리한다. PayLaterInfo/자동결제 예정은 청구가 아니며 pay-hotel은 숙소 현장 결제다.

- 조건·예외: API에 실제 청구일이 없으면 비워 두고 원문 금액·통화를 환산해 카드에 맞추지 않는다. 무날짜 연결 조건은 해당 규칙과 미해결 범위 질문을 따른다.
- 출처: `docs/specs/ota-portal-browser-collection-20261110.md:31`, `docs/specs/ota-portal-browser-collection-20261110.md:32`, `docs/specs/ota-portal-browser-collection-20261110.md:33`

### LINK-090 · Agoda 취소 비용

*일반 · 결정 2026-11-10*

Agoda 취소 상세는 총 청구액·취소 수수료·환불액을 구분한다. 환불이 있으면 내부 환불 검증 대상으로 두고 전액이 수수료로 남는 근거가 있으면 취소 예약의 실제 비용으로 본다.

- 조건·예외: 취소·환불 완료를 원문·카드 근거 없이 만들지 않는다.
- 출처: `docs/specs/ota-portal-browser-collection-20261110.md:34`

### LINK-091 · Booking 가맹점 상품 예외

*사용자 예외 · 결정 2026-11-10*

소유자가 확인한 Booking.com 뒤 숫자11자리의 원화 가맹점은 항공권, BKG*BOOKING.COM HOTEL의 엔화 결제는 숙소로 구분한다. 숙소 화면의 원화 요금이 환산값이면 정확 대사에 숙소 통화 금액의 원문 근거를 요구한다.

- 조건·예외: 해당 확인된 가맹점 형식을 넘겨 Booking이라는 이름만으로 모든 상품을 분류하지 않는다.
- 출처: `docs/specs/ota-portal-browser-collection-20261110.md:50`, `docs/specs/ota-portal-browser-collection-20261110.md:74`

### LINK-092 · Trip 현장결제 사전승인

*일반 · 결정 2026-11-10*

Trip 호텔 payType=5의 카드 사전승인은 현장 결제를 보증하는 금액이며 실제 숙박비와 구분한다. 카드 취소 원행과 환불 완료 근거를 별도로 비교하고 실제 현장 숙박비는 호텔 현장결제 카드 원행으로 판단한다.

- 조건·예외: 일부 환불 관측·사전승인 문구만으로 원문 금액·분류·숙박 합계를 자동 변경하거나 순액0으로 만들지 않는다.
- 출처: `docs/specs/ota-portal-browser-collection-20261110.md:63`, `docs/specs/ota-portal-browser-collection-20261110.md:64`, `docs/specs/ota-portal-browser-collection-20261110.md:67`, `docs/session_handoff.md:47`, `docs/session_handoff.md:48`

### LINK-093 · 항공 예약일 보완

*일반 · 결정 2026-10-27*

항공권의 별도 명시 예약일이 없으면 같은 공급자·예약번호의 보관 인증 메일 중 최초 mailbox internal_date를 한국 날짜로 바꿔 '최초 메일 수신일 기준'이라고 표시한다.

- 조건·예외: 명시 예약일·충돌을 우선하고 다른 예약·귀속 불명 복수 예약번호·인증 실패·유효 수신시각 없는 메일은 제외한다. 발송일/발권일/출발일/결제일은 예약일과 구분한다.
- 출처: `docs/COST_V3_START_HERE.md:80`, `docs/history/product-and-handoffs.md:227`, `docs/history/product-and-handoffs.md:866`, `docs/history/operations-through-20261027.md:541`, `docs/history/operations-through-20261027.md:594`

### LINK-094 · 항공 후보와 실제 연결

*보호*

항공 검색은 근거 조회이며 이름·날짜·금액 근접성만으로 PNR·실탑승·결제·참가자·여행·비용을 확정하지 않는다. 연결된 카드는 같은 예약/결제 사건의 검증된 관계로 실제 식별된 것만 표시한다.

- 조건·예외: 미연결 시 검증 예약일 또는 승인 FIRST_RECEIVED 날짜의 모든 카드 원행을 후보로 보여 주며 날짜 불명확하면 무작위 전체 목록을 보여 주지 않는다. 날짜 선택은 예약일·연결 확정이 아니다.
- 출처: `docs/specs/flight-booking-focused-spa-ux-20261104.md:26`, `docs/specs/flight-booking-focused-spa-ux-20261104.md:34`, `docs/specs/toyoko-collection-audit-20261103.md:12`, `docs/specs/finance.md:79`, `docs/specs/trip-flight-booking-overview-20261028.md:37`

### LINK-095 · 제주항공 근거

*사용자 예외 · 결정 2026-11-03*

제주항공 인증 메일 또는 소유자가 직접 수집한 원본 여정확인서를 근거로 예약번호·명시 승인번호·실제 결제일·결제액을 읽는다. 마스킹 결제 토큰 끝자리를 발급사 카드 끝4로 간주하지 않는다.

- 조건·예외: 명시 결제일·동액·제주항공 가맹점으로 대조하고 예약일/수신일을 실제 결제일로 바꾸지 않는다. 취소·원문 충돌·수동 링크·환불을 보호한다.
- 출처: `docs/specs/ota.md:5`, `docs/specs/ota.md:7`, `docs/specs/ota.md:8`, `tests/card_pipeline/test_airline_payment_mail.py:17`

### LINK-096 · 제주항공 변경 관측

*사용자 예외 · 결정 2026-11-03*

제주항공 변경 메일의 같은 승인번호 원결제 반복은 기존 결제의 재관측으로 보고 실제 카드 원행별 한 번만 집계한다. 명시 추가 결제는 별도 관측·identity로 보존해 연결한다.

- 조건·예외: 여행은 가는편 출발일을 쓰며 돌아오는편 변경만으로 새 예약·결제를 만들지 않는다.
- 출처: `docs/specs/ota.md:5`, `docs/specs/ota.md:6`, `docs/specs/ota.md:8`, `tests/card_pipeline/test_airline_payment_mail.py:140`

### LINK-097 · Asiana 결제일 없는 후보

*일반*

결제일·끝4가 없는 Asiana 발권 메일은 아시아나 공급자 가맹점의 동일 금액 카드와 상호1:1일 때만 제한된 후보로 표시한다. 이를 실제 결제일이나 paid 확정으로 바꾸지 않는다.

- 조건·예외: 일반 무날짜 끝4 매칭 경로와 구분하고 다른 공급자 카드로 연결하지 않는다.
- 출처: `docs/session_handoff.md:16`, `tests/card_pipeline/test_airline_payment_mail.py:21`

### LINK-098 · Skyticket 실제 결제액

*일반*

Skyticket 해외 항공 구매 안내는 명시 합계 결제액을 카드 근거로 사용하고 항공권 소계만 있는 양식은 실제 결제 증거로 사용하지 않는다.

- 조건·예외: 주식회사 어드벤처코리아 확장 가맹점은 승인된 공급자 별칭으로 해석한다.
- 출처: `config/ota-matching-defaults.json:41`, `tests/card_pipeline/test_airline_payment_mail.py:32`, `tests/card_pipeline/test_airline_payment_mail.py:56`

### LINK-099 · 예약 목록과 카드 목록

*일반*

예약 목록과 카드 원행의 집계·등록 권위를 구분하고 같은 snapshot의 관계를 상세에서 공유한다. 예약 목록은 읽기 전용이며 예약/결제/이용/취소 상태·원문 근거 유무를 각각 설명한다.

- 조건·예외: 화면 재설계·합쳐진 표시를 금융 로직 변경·새 연결/장부 적용으로 해석하지 않는다. 카드당 최대2개 안내 요약은 전체 당일 카드 후보 목록의 접근 범위를 제한하는 규칙이 아니다.
- 출처: `docs/specs/uiux-full-audit-redesign-20261110.md:751`, `docs/specs/cost-pr-only-implementation-brief-20261106.md:40`, `docs/specs/cost-pr-only-implementation-brief-20261106.md:72`, `docs/specs/unified-expense-action-queue-20261105.md:39`, `docs/specs/unified-expense-action-queue-20261105.md:41`

### LINK-100 · 진단 검색 범위

*보호*

결제일 미상 후보 검색은 설정·인덱스로 범위를 제한하고 무제한 카테시안 비교를 하지 않는다. 검색 한도를 넘으면 SEARCH_LIMIT_EXCEEDED와 미완료 사실을 반환한다.

- 조건·예외: 코드의 기본 비교 한도250,000은 운영 구현값이며 검색 미완료를 후보없음/완료로 위장하지 않는다.
- 출처: `docs/specs/ota.md:213`, `app/ota_payments.py:1415`

### LINK-101 · 외부 결제 근거 공백

*보호*

자료가 있으나 비교 가능한 결제 증거가 없으면 결제 사실의 미확인·후보 경합·통화 근거 부족·원문 충돌을 구분한다. 이 공백을 임의 금융 링크·결제 완료·환급 사실로 채우지 않는다.

- 조건·예외: 정상 카드의 항목·여행/분기 비용 판정과 비용 준비는 계속 진행한다.
- 출처: `docs/specs/core-workflow-remaining-implementation-20261030.md:29`, `docs/specs/core-workflow-remaining-implementation-20261030.md:30`, `docs/history/session_handoff-through-20261107.md:899`, `docs/history/product-and-handoffs.md:1791`, `docs/specs/ota-review-queue-performance-20261027.md:113`

### LINK-102 · 명시 분할결제

*보호*

분할 결제는 명시 payment ID·분할 내역이 확인될 때만 별도 모델로 보존한다. 총액이 맞는다는 이유로 합산·분할·할인액을 만들거나 여러 실거래를 병합하지 않는다.

- 조건·예외: 한 예약의 여러 실제 결제 사건은 각각 유지한다.
- 출처: `docs/specs/ota.md:227`, `docs/history/implementation-and-audits.md:161`, `docs/history/ota-legacy.md:1344`, `docs/specs/finance.md:257`

### LINK-103 · 통화 근거 부족의 수동 연결

*사용자 예외 · 결정 2026-10-29*

자동 환율 대사가 불가능한 서로 다른 통화 자료라도 사용자가 확인한 개별 관계는 원문 외화액과 카드 원화액을 그대로 보존하는 수동 연결로 저장할 수 있다.

- 조건·예외: 자동 환율 규칙을 만들거나 외화값을 채우지 않으며 owner·preview digest·revision·전역 점유 보호를 따른다.
- 출처: `docs/specs/ota.md:32`, `tests/card_pipeline/test_ota_same_day_amount.py:84`

### LINK-104 · 표적 재대사

*일반*

새 카드 가져오기 뒤에는 해당 batch의 신규 transaction_id만 증분 refresh에 전달하고 신규 예약 증거와 직접 관련된 미해결 사건만 재대사한다. 저장된 사용자 결정을 바꾸지 않는다.

- 조건·예외: 관련 카드/기간 근거가 부족한 금융 사실은 미확인으로 보존하며 정상 비용 판정의 대기로 확대하지 않는다.
- 출처: `docs/specs/unified-expense-action-queue-20261105.md:204`, `docs/history/operations-through-20261027.md:915`, `docs/history/implementation-and-audits.md:161`, `docs/specs/finance.md:222`, `docs/history/ota-legacy.md:893`

### LINK-105 · 내부 저장소 단일 작성 경로

*보호*

OTA 링크는 기존 검토 저장소와 승인된 저장 경로를 재사용하고 중복 writer·테이블·무승인 자동 전기 루프를 만들지 않는다. 조회·연결 저장·장부 기록의 외부 효과를 구분한다.

- 조건·예외: 운영 실제 자료 이전·마이그레이션·대량 재처리는 별도 승인 범위를 확인한다.
- 출처: `docs/specs/webledger-idle-io-optimization-20261105.md:60`, `docs/specs/ota.md:294`, `docs/history/ota-legacy.md:893`, `docs/history/ota-legacy.md:1042`, `docs/specs/finance.md:466`

### LINK-106 · 레거시 실행 설정과 진단

*일반*

레거시·isolated·authority 실행 모드와 자료 경로 선택은 구현 설정으로 구분하고 현재 중앙 snapshot의 authority/fallback 이유를 표시한다. health 응답만으로 실제 OTA 재대사 수행을 증명하지 않는다.

- 조건·예외: 구형 authority 가드가 OTA 미확정만으로 정상 카드 비용 준비를 막던 계약은 최신 A 정책에 의해 대체됐다.
- 대체된 옛 규칙:
  - authority 가드: 스냅샷이 없으면 OTA 카드 전부를 보류한다. — 2026-10-10, docs/history/operations-through-20261027.md:1213
  - authority에서는 OTA-first 연결이 확정되지 않은 OTA 카드 거래를 장부 미리보기에서 보류한다. — 2026-10-09, docs/history/operations-through-20261027.md:1280
  - 기록을 막는 것은 소유자 보류(review_hold), 환불 짝 불완전, 여행 검증 실패, 운영 OTA authority 모드의 `ota_authority_unresolved`(OTA-first 연결이 확정되지 않은 OTA 카드 거래)다. — C:/Users/kkokk/.claude/projects/C--AX-cost/memory/feedback-classify-records-automatically.md:15
- 출처: `소유자 지시 메모:project-agoda-scheduled-charge-rows.md:17`, `docs/history/operations-through-20261027.md:1213`, `docs/history/operations-through-20261027.md:1280`, `docs/history/ota-legacy.md:1376`, `소유자 지시 메모:feedback-classify-records-automatically.md:15`

### LINK-107 · 합성 검증·실제 적용 구분

*보호*

개발 검증은 합성 fixture로 수행하고 고객 원문·예약번호·카드 ID를 외부 모델·Git·로그로 내보내지 않는다. 코드/검증 결과와 실제 운영 적용·금융 쓰기 완료는 각각 근거로 보고한다.

- 조건·예외: 권한 없는 운영 실증이나 일회성 처리 결과를 보편 금융 규칙으로 확대하지 않는다.
- 출처: `docs/specs/ui.md:368`, `docs/history/product-and-handoffs.md:1119`, `docs/history/product-and-handoffs.md:1323`
