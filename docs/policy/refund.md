# 판정 규칙 — 환불·취소

> [판정 규칙집](../DECISION_POLICY.md)의 영역별 상세 규칙이다. 핵심 원칙과 읽는 법은 규칙집 본문에 있다.
> 규칙 ID는 바꾸지 않는다. 규칙을 고칠 때는 같은 ID의 내용을 고치고 옛 내용을 "대체된 옛 규칙"에 남긴다.
> "출처"의 파일과 줄 번호는 커밋 `b0340d0d`(2026-11-10) 기준이다. 그 뒤 줄어든 `AGENTS.md`·`docs/COST_V3_START_HERE.md`의 줄은 `git show b0340d0d:<경로>`로 본다. 그때의 `docs/specs/<파일>`은 지금 `docs/history/specs-20261110/<파일>`에 있다(절차서 두 개는 `docs/playbooks/`).

### RFND-001 · 사실과 완료 단계 분리

*보호 · 결정 2026-11-08*

환불 요청·예약 취소·카드 취소 원행·원결제 연결·COST 내부 기록·Google 반영·실제 은행 환급은 각각 증거로 판정한다. 예약 취소나 분류·연결 완료만으로 환불 원행·순액 0·입금·기장을 만들지 않는다.

- 출처: `docs/specs/card-destination-only-ux-20261108.md:10`, `docs/specs/unified-expense-action-queue-20261105.md:104`, `docs/specs/finance.md:96`, `docs/specs/finance.md:5`, `docs/specs/unified-expense-action-queue-20261105.md:145`

### RFND-002 · 환불 완료 표현 판정

*보호*

환불 처리 중·예정·부정·요청 문구는 완료된 환불로 승격하지 않는다. 취소 안내·예정 결제·예약 확정도 실제 결제·환급 증명이 아니다.

- 출처: `docs/session_handoff.md:91`, `docs/specs/ota.md:523`

### RFND-003 · 원행과 순잔액 보존

*보호 · 결정 2026-10-29*

원결제와 각 취소·환불의 원본 금액·부호·날짜·ID·원문·다중도는 보존한다. 순잔액은 파생값이며 원결제 금액을 덮거나 환불 원행을 합쳐 삭제하지 않는다.

- 대체된 옛 규칙:
  - 개별 부분환불 전표를 찾지 못해 전체 여행 배정을 멈춘 당시 상태. 후속 원문에서 실제 취소 전표를 확인했으므로 현재 미확인 규칙으로 재사용하지 않는다. — 2026-10-04, docs/specs/finance.md:234
- 출처: `docs/specs/finance.md:93`, `docs/specs/finance.md:155`, `app/partial_refund.py:10`, `docs/specs/finance.md:196`, `docs/specs/ui.md:108`

### RFND-004 · 원승인번호 1:N 연결

*일반 · 결정 2026-10-29*

동일한 알려진 발급사·카드와 원승인번호가 유일한 정상 원결제를 가리키면 그 번호의 모든 취소·부분환불을 연결한다. 취소 건수·가맹점명·금액 차이·일반 추론 기간창만으로 링크를 강등하지 않고 기장 허용은 별도 검증한다.

- 조건·예외: 번호 후보 전역 유일성과 정상 원본이 필요하다. 초과환불 링크의 유지와 장부 차단은 별개다.
- 출처: `docs/specs/finance.md:93`, `docs/specs/finance.md:71`, `AGENTS.md:44`, `app/partial_refund.py:155`, `tests/card_pipeline/test_refund_inference_runtime.py:111`

### RFND-005 · 원승인번호 정규화

*보호*

원승인번호의 바깥 공백·탭·개행만 제거해 같은 키로 비교하며 숫자를 바꾸거나 유사 매칭하지 않는다. 정규화 후 원결제 후보가 여러 개면 오류 후보를 포함해 모호하므로 연결하지 않는다.

- 출처: `app/partial_refund.py:112`, `tests/card_pipeline/test_refund_approval_padding.py:72`, `tests/card_pipeline/test_refund_inference_runtime.py:171`, `docs/history/operations-through-20261027.md:515`, `tests/card_pipeline/test_refund_approval_padding.py:39`

### RFND-006 · 공통 금융 보호

*보호 · 결정 2026-11-08*

원본 오류·중복·원결제 후보 경합·점유·초과환불·기존 수동 교정·내부 금융 안전 잠금·묶음 원자성·장부 중복 보호는 자동 연결과 분류에서도 유지한다. 모호하거나 충돌한 원거래를 임의로 묶지 않는다.

- 출처: `docs/specs/card-destination-only-ux-20261108.md:10`, `docs/specs/finance.md:61`, `docs/history/operations-20261028-20261107.md:1304`, `docs/specs/finance.md:155`, `docs/specs/finance.md:93`

### RFND-007 · 원승인번호 없는 원화 연결

*일반 · 결정 2026-10-29*

원승인번호가 없어도 동일 발급사·카드·가맹점·이용일·정확한 원화 금액의 양수와 음수 원행이 양방향으로 유일 대응하면 자동 연결을 완료하고 출처·대조 근거를 표시한다. 번호 부재만으로 추가 승인·추론 대기를 만들지 않는다.

- 대체된 옛 규칙:
  - 원승인번호 없는 동액 추론은 읽기 전용 후보로만 보이고 금융 연결·상쇄에는 넣지 않는다. — 2026-10-27, docs/history/operations-through-20261027.md:480
  - 원승인번호가 없으면 금액 대조가 맞아도 별도 발급사 증빙 또는 사용자 검토 없이는 금융 연결을 확정하지 않는다. — 2026-10-28, docs/specs/refund-reconciliation-remediation-20261028.md:30
- 출처: `docs/specs/finance.md:61`, `app/partial_refund.py:341`, `docs/history/operations-20261028-20261107.md:1304`, `tests/card_pipeline/test_refund_inference_runtime.py:26`, `tests/card_pipeline/test_refund_inference_runtime.py:139`

### RFND-008 · 카카오 택시 동액 연결

*일반 · 결정 2026-10-29*

승인된 카카오 택시 가맹점 계열 표기 변형은 같은 발급사·카드·정확 금액과 양방향 유일성이 성립하고 구매일로부터 0~14일 이내면 자동 연결한다. 택시 계열에 대리·주차·바이크·퀵을 합치지 않는다.

- 조건·예외: 당일과 14일째 포함, 미래 구매와 15일째 제외. 다른 서비스는 동일 표기라는 이유만으로 택시 계열 예외에 합치지 않는다.
- 코드와 다른 점: app/partial_refund.py:317은 양쪽 상호에 카카오가 있으면 먼저 14일 후보를 만들고 :325에서 family 일치만 검사한다. 따라서 동일한 비택시 카카오 상호도 14일 연결될 수 있어, :278의 동일 상호는 당일·택시 변형만 14일이라는 설명보다 넓다. family가 다른 경쟁 후보도 collision에 먼저 포함돼 정상 연결을 보수적으로 막을 수 있다.
- 출처: `docs/specs/finance.md:61`, `app/partial_refund.py:278`, `app/partial_refund.py:317`, `app/partial_refund.py:263`, `app/partial_refund.py:325`

### RFND-009 · 전역 양방향 유일성

*보호*

현재 조회 파일·페이지·요청 취소만 보아 유일성을 만들지 않는다. 모든 경쟁 연결 후보와 오류·중복·충돌·이미 점유된 원행을 유일성 계산에 포함하고 경합이면 연결하지 않는다.

- 출처: `app/partial_refund.py:282`, `tests/card_pipeline/test_refund_inference_runtime.py:58`, `docs/specs/finance.md:61`, `tests/card_pipeline/test_kakao_amount_inferred.py:53`, `tests/card_pipeline/test_refund_inference_runtime.py:81`

### RFND-010 · 해소되지 않은 참조와 구매 부재

*보호 · 결정 2026-10-29*

정상 원승인 참조가 명시됐으나 해소되지 않은 취소를 동액 추론으로 우회하지 않는다. 대응 양수 원행이 없는 취소·미매입 취소에는 임의 링크를 만들지 않는다.

- 출처: `docs/specs/finance.md:61`, `tests/card_pipeline/test_partial_refund.py:167`

### RFND-011 · 승인번호 없는 외화 연결 조건

*일반 · 결정 2026-10-16*

승인번호 없는 외화 취소는 같은 발급사·카드·가맹점·외화 통화·정확 외화 금액의 선행 구매와만 짝짓는다. 같은 외화끼리 비교하고 미화 환산액이나 임의 환율로 대체하지 않는다.

- 조건·예외: 최대 365일·구매 일대일 소진·기존 원승인 연결 우선 보호를 함께 적용한다.
- 출처: `docs/specs/finance.md:141`, `docs/specs/finance.md:563`, `app/partial_refund.py:204`, `tests/card_pipeline/test_refund_foreign_pairs.py:33`, `tests/card_pipeline/test_refund_foreign_pairs.py:85`

### RFND-012 · 외화 짝의 기간과 날짜

*일반 · 결정 2026-10-16*

외화 구매는 취소보다 늦지 않고 설정된 최대 365일 범위 안에 있어야 한다. 현재 구현은 저장된 approval_date가 있으면 사용하고 없으면 posting_date로 짝 계산 날짜를 정하며 원문 날짜를 채워 만들지 않는다.

- 조건·예외: 이는 환불 짝 계산의 날짜 기준이며 여행 이용일로 매입일을 새로 쓰는 승인이 아니다.
- 출처: `docs/specs/finance.md:141`, `app/partial_refund.py:192`, `app/partial_refund.py:230`, `config/refund-pairing.json:5`, `tests/card_pipeline/test_refund_foreign_pairs.py:70`

### RFND-013 · 복수 외화의 순서와 점유

*일반 · 결정 2026-10-16*

동일 조건의 외화 구매·취소가 여러 개면 날짜 순서대로 구매 하나에 취소 하나씩 짝짓고 이미 원승인번호 또는 다른 외화 쌍이 점유한 구매를 재사용하지 않는다. 쓸 구매가 없는 취소는 미연결로 보존한다.

- 출처: `docs/specs/finance.md:141`, `tests/card_pipeline/test_refund_foreign_pairs.py:64`, `tests/card_pipeline/test_refund_foreign_pairs.py:49`, `tests/card_pipeline/test_refund_foreign_pairs.py:56`, `tests/card_pipeline/test_refund_inference_runtime.py:105`

### RFND-014 · 남는 외화 취소의 개수 보호

*보호 · 결정 2026-10-16*

같은 조건 구매가 있으나 짝짓고 남은 외화 취소는 개별로 기록하지 않고 구매·취소 개수 묶음의 내부 금융 보호로 관리한다. 명세와 개수를 대조한 뒤 기록하며 구매가 없거나 원승인번호가 있는 취소에 이 개수 묶음을 임의 적용하지 않는다.

- 예: 동일 조건 구매보다 취소가 많으면 남은 취소를 같은 구매에 재사용하지 않고 개수 묶음으로 남긴다.
- 출처: `docs/specs/finance.md:141`, `app/partial_refund.py:349`, `webapp/card_flow.py:1701`, `tests/card_pipeline/test_refund_foreign_pairs.py:100`, `tests/card_pipeline/test_refund_foreign_pairs.py:108`

### RFND-015 · 외화 환불의 원화 잔액

*일반 · 결정 2026-10-16*

같은 외화 원금액의 구매·취소라도 원화 청구액 차이는 환율·수수료 차이에 따른 순잔액으로 보존한다. 차액을 없애거나 별도 근거 없이 위약금·실제 환급 완료로 바꾸지 않는다.

- 조건·예외: 외화 원금액 일치의 원화 환산 차이는 원화 원승인번호 경로의 초과환불 판정과 구별한다.
- 출처: `docs/specs/finance.md:141`, `docs/specs/finance.md:563`, `app/partial_refund.py:241`, `app/partial_refund.py:9`, `tests/card_pipeline/test_refund_foreign_pairs.py:40`

### RFND-016 · 외화 짝 설정

*일반*

현재 외화 짝짓기 설정의 enabled가 꺼져 있으면 승인번호 없는 외화 자동 연결을 만들지 않는다.

- 조건·예외: 문서의 소유자 결정이 아니라 설정에 관한 구현 후보이며 임의 비활성화 권한을 뜻하지 않는다.
- 출처: `tests/card_pipeline/test_refund_foreign_pairs.py:123`

### RFND-017 · 누적 환불과 파생 상태

*일반*

원승인번호로 연결된 모든 취소·부분환불을 합산해 원결제 금액에 더한 순잔액을 공통으로 계산한다. 순잔액 0은 full, 양수는 partial, 음수는 excess로 구별하고 각 원행 금액은 유지한다.

- 출처: `app/partial_refund.py:161`, `app/partial_refund.py:167`, `docs/specs/finance.md:93`, `tests/card_pipeline/test_partial_refund.py:120`

### RFND-018 · 초과환불 기록 차단

*보호 · 결정 2026-10-29*

원승인번호 경로에서 누적 환불이 원결제보다 크면 원결제와 모든 취소를 refund_exceeds_original로 차단한다. 원승인 연결 자체와 장부 기록의 허용 여부를 구분한다.

- 출처: `docs/specs/finance.md:93`, `app/ledger.py:392`, `tests/card_pipeline/test_partial_refund.py:113`

### RFND-019 · 환불 귀속 상속

*보호 · 결정 2026-10-29*

검증된 연결 환불은 원결제의 항목·구분·여행을 따르되 이미 입력된 수동 값과 기존 기록을 덮지 않고 빈 값만 이어받는다. 이미 기록된 한쪽이 있으면 그 유효 귀속을 기준으로 누락 구성원을 보완한다.

- 출처: `docs/specs/finance.md:93`, `docs/specs/finance.md:217`, `app/ledger.py:396`

### RFND-020 · 부분환불 귀속 충돌

*보호*

부분환불의 항목·표시 탭·여행이 원결제와 충돌하면 양쪽을 refund_pair_mismatch로 보호하고 임의로 덮어 맞추지 않는다.

- 출처: `app/ledger.py:409`, `tests/card_pipeline/test_partial_refund.py:132`, `docs/specs/finance.md:155`

### RFND-021 · 부분환불 여행 비용

*일반 · 결정 2026-10-29*

잔액이 남는 부분환불은 원결제와 함께 원결제 여행에 표시하고 그 순잔액을 여행 비용으로 유지한다. 취소된 예약이라는 이유만으로 원결제 전체와 잔여 이용 비용을 일괄 분리하지 않는다.

- 대체된 옛 규칙:
  - 취소된 예약과 확인된 환불은 일괄적으로 여행에서 분리한다. — 2026-10-04, docs/specs/finance.md:236
  - 취소·환불된 예약과 확인된 환불은 일괄적으로 여행에서 분리한다. — docs/specs/finance.md:236
- 출처: `docs/specs/finance.md:93`, `docs/specs/finance.md:155`, `docs/specs/finance.md:217`

### RFND-022 · 전액환불 분류 완료

*일반 · 결정 2026-10-29*

원결제와 연결된 모든 환불 원행의 전체 합계가 정확히 0일 때 전액환불쌍으로 분류 완료하고 읽기 전용 환불 탭에 모은다. 여행 ID가 비어 있어도 완료이며 별도 분류 확정 버튼을 요구하지 않는다.

- 대체된 옛 규칙:
  - 환불 탭은 원승인번호로 연결된 전액환불만 허용한다. — 2026-10-13, docs/history/operations-through-20261027.md:1035
  - 금융 기록 보호와 별도로 사용자 검토 보류 상태를 표시한다. — 2026-10-29, docs/specs/finance.md:95
- 출처: `docs/specs/finance.md:93`, `docs/specs/finance.md:95`, `docs/specs/finance.md:155`, `docs/specs/finance.md:89`, `app/ledger.py:420`

### RFND-023 · 기록된 전액환불의 표시

*보호 · 결정 2026-10-13*

이미 기록된 전액환불은 모든 구성원이 기록돼 있고 같은 여행이며 저장 금액 합계가 0일 때만 기존 여행의 표시 목록에서 환불 탭으로 옮긴다. 한쪽만 기록됐거나 여행이 다르면 기존 기록을 숨기지 않는다.

- 출처: `docs/specs/finance.md:157`

### RFND-024 · 미기록 전액환불 조회

*보호 · 결정 2026-10-13*

미기록 전액환불은 환불 탭에서 미기록으로 표시한다. 조회·분류 완료·탭 이동만으로 내부 기장·확정·은행 환급을 수행했다고 해석하지 않는다.

- 출처: `docs/specs/finance.md:157`

### RFND-025 · 묶음 원자 기록

*보호*

새 환불 묶음은 원결제와 연결된 모든 취소를 함께 검증하고 원자적으로 한 번 기록한다. 어느 구성원도 기록되지 않은 묶음에서 일부만 준비되거나 범위에서 빠졌으면 거부하고 중간 실패 시 전체를 롤백한다.

- 예: 원결제와 여러 부분환불은 각각의 원행을 유지한 하나의 기록 묶음이다.
- 출처: `docs/specs/finance.md:148`, `app/ledger.py:535`, `tests/card_pipeline/test_partial_refund.py:148`, `docs/history/operations-through-20261027.md:1254`, `tests/card_pipeline/test_partial_refund.py:82`

### RFND-026 · 부분 기기록 묶음 보완

*보호 · 결정 2026-10-29*

원결제 또는 취소가 먼저 기록된 환불 묶음은 이미 기록된 행을 재삽입하지 않고 빠진 구성원만 함께 보완한다. 기존 기기록·금융 보호와 전체 묶음 검증은 유지한다.

- 출처: `docs/specs/finance.md:94`, `tests/card_pipeline/test_partial_refund.py:212`, `tests/card_pipeline/test_partial_refund.py:234`, `tests/card_pipeline/test_partial_refund.py:223`

### RFND-027 · 환불 기록 재전송

*보호 · 결정 2026-10-29*

성공한 환불 묶음의 같은 미리보기를 새 요청 ID로 재전송하면 잠금 안에서 실제 성공 기록·성공 직후 미리보기·전체 revision·실제 장부가 모두 일치할 때만 applied=0으로 응답한다. 금액·결정·장부·멤버·잠금 변경이나 성공 증명 없는 digest는 거부한다.

- 출처: `docs/specs/finance.md:94`, `tests/card_pipeline/test_partial_refund.py:202`

### RFND-028 · 미리보기 무효화와 범위 검증

*보호*

미리보기 뒤 원결제·취소 결정 또는 묶음 revision이 바뀌면 전체 기록을 PREVIEW_STALE로 거부한다. 전체 배치 digest 일부를 그룹 digest로 재사용하거나 환불 아닌 거래를 그룹으로 기록하지 않는다.

- 출처: `docs/specs/finance.md:94`, `tests/card_pipeline/test_partial_refund.py:327`, `tests/card_pipeline/test_partial_refund.py:387`, `tests/card_pipeline/test_partial_refund.py:391`

### RFND-029 · 파일 간 환불 묶음 확장

*보호 · 결정 2026-10-28 · 개정 2026-11-13(3분기 검수)*

명시적으로 허용한 검증 묶음 경로만 서버가 원승인번호·순잔액·모든 구성원·실제 출처 배치를 다시 결정해 다른 파일의 원결제와 취소를 함께 읽고 기록한다. 대상은 둘이다. (가) 순액 0인 검증 전액 상쇄. (나) 추론이 아닌 원승인번호 연결(RFND-004)로 원결제 하나가 유일하게 특정되고 순잔액이 양수인 부분환불. 부분환불은 원결제의 유효 귀속(실제 여행 또는 분기 기타비용)으로 기록하며, 원결제가 이미 기록돼 있으면 다시 넣지 않고 빠진 취소만 그 귀속으로 보완한다(RFND-019, RFND-021, RFND-026). 일반 파일 미리보기는 원래 범위를 유지하며 빠진 구성원이 있으면 기록하지 않는다.

- 조건·예외: (나)는 원승인번호 연결에만 적용한다. 원승인번호 없는 동액·외화·택시 연결(RFND-007, RFND-008, RFND-011)과 추론 링크는 넓히지 않는다. 다음 가운데 하나라도 해당하면 묶음 전체를 기록하지 않는다. 누적 환불이 원결제보다 크다(RFND-018). 구성원에 원본 오류·중복·원본 충돌·내부 금융 잠금·회사 경비 제외가 있다(RFND-006, RFND-034). 취소의 항목·탭·여행이 원결제와 다르다(RFND-020). 원결제에 유효 귀속이 없다(환불 탭·미분류 포함. 부분환불은 환불 탭에 두지 않는다, RFND-022). 같은 원승인번호의 취소를 모든 파일에서 다시 읽어 함께 검증하고(RFND-009, RFND-025) 미리보기 digest·요청 ID·서버 재검증·재전송 멱등(RFND-027, RFND-028, RFND-030)은 전액 경로와 같다. 금액·부호·원문·ID와 수동 귀속은 바꾸지 않는다. PROC-072의 완료 자료 제외가 먼저다.
- 예 (2026년 3분기 검수): 7월 말에 결제한 숙박 2건이 8월 초 여행에 기록된 뒤, 같은 원승인번호의 부분 취소 2건이 10월 매입 파일로 들어왔다. 취소는 원결제 여행으로 분류됐지만 원결제가 다른 파일에 있어 기록되지 못했고, 그 여행의 숙박비가 환불액만큼 크게 남았다. 같은 원인의 미기록 묶음이 4분기 여행 귀속분에도 2건 있었다.
- 코드와 다른 점: `app/ledger.py`의 `_ready_rows`·`scope_group`, `webapp/card_flow.py`의 `automatic_holds`, `webapp/refund_cleanup_action.py`는 순액 0 전액 묶음만 다른 파일로 확장한다. 부분환불의 취소는 `refund_original_missing`으로 남는다.
- 대체된 옛 규칙:
  - 명시적으로 허용한 검증 전액 상쇄 경로만 서버가 원승인번호·순액 0·모든 구성원·실제 출처 배치를 다시 결정해 다른 파일의 원결제와 취소를 함께 읽고 기록한다. 일반 파일 미리보기는 원래 범위를 유지하며 빠진 구성원이 있으면 기록하지 않는다. — 2026-10-28 (다른 파일로 뒤늦게 들어온 부분환불을 기록할 경로가 없어 RFND-021·RFND-026의 결과와 어긋나 2026-11-13 개정)
- 출처: 분기 AI 검수 2026-11-13, `docs/specs/refund-inline-existing-repair-20261028.md:18`, `webapp/tests/test_verified_cross_batch_refunds.py:70`, `webapp/tests/test_verified_cross_batch_refunds.py:112`, `tests/card_pipeline/test_partial_refund.py:289`

### RFND-030 · 묶음 기록 권한과 쓰기 범위

*보호 · 결정 2026-10-28*

환불 묶음 적용은 owner 권한·CSRF·검증된 digest·요청 ID·서버 재검증을 요구하고 해당 묶음만 commit한다. 타 카드행·원문·Google 최종 장부·실제 환급 완료 상태는 수정하지 않는다.

- 출처: `docs/specs/refund-inline-existing-repair-20261028.md:18`

### RFND-031 · 환불 조회의 무쓰기

*보호 · 결정 2026-10-16*

환불 짝 계산과 미리보기는 읽기 전용이다. 이를 실행하거나 재수집한 것만으로 기존 장부·금융 링크·원행을 변경하거나 비용을 늘리지 않는다.

- 출처: `docs/specs/finance.md:141`, `docs/specs/ota.md:522`

### RFND-032 · 미연결 취소의 분류

*일반 · 결정 2026-11-08*

원결제가 식별되지 않은 취소도 취소·환불 항목으로 분류를 끝내고 출처·근거·불확실성을 보존한다. 연결이나 실제 환급을 창작하지 않으며 음수 원행은 이용일 근거가 없다는 경고 대신 취소·환불로 표시한다.

- 출처: `docs/specs/finance.md:3`, `docs/specs/finance.md:86`, `docs/session_handoff.md:70`, `docs/specs/finance.md:173`

### RFND-033 · 분류와 금융 대사 구별

*보호 · 결정 2026-10-29*

분류가 완료돼도 취소의 원결제 미연결·불완전 환불 묶음 등 금융 미결은 독립적으로 남긴다. 분류 완료율을 모든 금융 처리·기장·환급 완료로 보고하지 않는다.

- 출처: `docs/specs/card-upload-full-reconciliation-20261029.md:39`, `docs/specs/finance.md:96`, `소유자 지시 메모:feedback-classify-records-automatically.md:15`

### RFND-034 · 내부 금융 잠금 보존

*보호 · 결정 2026-11-08*

내부 금융 안전 잠금은 원행 ID·원문 hash에 묶어 보존하며 재분류·가져오기·사용자 작업 화면 폐지만으로 풀지 않는다. 연결 묶음 한쪽에 유효 잠금이 있으면 다른 쪽도 함께 기록을 차단하되 사용자 보류·해제 UI와 P3 작업함은 만들지 않는다.

- 대체된 옛 규칙:
  - 환불 질문을 내 확인 필요 작업함으로 모은다. — 2026-11-05, AGENTS.md:38
  - 환불 그룹마다 action_group_key를 만들어 카드 원행에 없는 필수 사실을 사용자 작업으로 올린다. — 2026-11-05, docs/specs/unified-expense-action-queue-20261105.md:102
  - 사용자가 보류를 명시적으로 해제해야 하며 가져오기·답변 저장으로는 해제하지 않는다. — 2026-10-08, docs/specs/finance.md:217
- 출처: `docs/specs/finance.md:3`, `docs/specs/finance.md:5`, `docs/specs/card-destination-only-ux-20261108.md:10`, `AGENTS.md:42`, `docs/specs/finance.md:227`

### RFND-035 · 보호의 거래별 한정

*보호*

문제 있는 환불 묶음은 내부 금융 검증으로 막되 같은 파일의 관련 없는 정상 거래까지 함께 막지 않는다.

- 출처: `docs/specs/finance.md:148`

### RFND-036 · 과거 취소 연도 항목 예외

*사용자 예외 · 결정 2026-10-16*

2025년 짝 없는 취소의 연도 묶음은 PROC-072의 하위 사례다. 취소 이용일, 없으면 매입일을 기준으로 2025년 항목에 묶으며 원본·금액·날짜·ID·기존 완료 여행·감사 이력을 보존한다. 완료 자료를 반복 재판정하지 않고 환불 짝·초과환불 보호도 풀지 않는다.

- 대체된 옛 규칙 (2026-11-12 PROC-072):
  - 2025년 취소는 취소 이용일, 없으면 매입일이 2025년인 범위에서 소유자가 정한 2025년 항목으로 묶는다. 원거래·금액·날짜·여행·감사 이력을 보존하고 반복 사용자 짝 질문을 만들지 않는다.

- 조건·예외: PROC-072의 완료 자료 제외가 먼저다. 기존 수동 교정·금융 보호를 유지한다.
- 출처: `소유자 지시 메모:project-2025-unpaired-cancels.md:11`, `소유자 지시 메모:project-2025-unpaired-cancels.md:21`, `docs/specs/finance.md:18`

### RFND-037 · OTA 관계와 카드 원행 수

*일반 · 결정 2026-11-01*

OTA와 카드의 조건 일치 관계는 M:N으로 보존하고 개별 예약 유일성·양쪽 건수 일치를 요구하지 않는다. 결제일이 없으면 원문 날짜를 창작하지 않고 같은 통화 정확 금액·가맹점·끝자리 등 승인된 조건으로 연결하되 카드 원행은 한 번만 집계한다.

- 대체된 옛 규칙:
  - 메일 발송일 근거가 없으면 M:N 자동 배정을 하지 않는다. — 2026-10-16, C:/Users/kkokk/.claude/projects/C--AX-cost/memory/feedback-payment-date-evidence.md:15
  - 카드 원행 수가 예약 수보다 많으면 같은 기간 묶음 연결을 막는다. — 2026-10-16, C:/Users/kkokk/.claude/projects/C--AX-cost/memory/project-ota-mn-open-items.md:11
- 출처: `docs/specs/ota.md:14`, `docs/specs/ota-undated-many-to-many-20261101.md:9`, `docs/specs/ota-undated-many-to-many-20261101.md:13`

### RFND-038 · OTA 취소 다중관계 보호

*보호 · 결정 2026-11-01*

취소·환불의 N:M 관계는 구매 대사와 별도로 보호하고 0원 소계·부분환불 이력·기존 수동 링크·고정 그룹을 유지한다. 취소 예약의 관계·카드 건수를 없애거나 관계 연결만으로 여행·환급 결정을 바꾸지 않는다.

- 출처: `docs/specs/ota-undated-many-to-many-20261101.md:31`, `docs/specs/ota-undated-many-to-many-20261101.md:13`, `docs/specs/ota.md:228`, `docs/specs/ota.md:526`

### RFND-039 · OTA 자동 대사의 실제 충돌

*보호*

구매·환불 방향 모순, 명시 카드·공급자 충돌, 통화·금액의 설명되지 않은 불일치, 중복·파싱 오류·점유는 자동 대사의 금융 차단 사유로 유지한다. 여행 추론으로 이 충돌을 해제하지 않는다.

- 출처: `docs/specs/ota.md:217`, `docs/specs/finance.md:61`

### RFND-040 · 통화 정밀도와 원화 보존

*보호*

원화·외화 대조는 유한 Decimal로 하며 실제 카드 원화 매입액을 OTA 환산값으로 덮지 않는다. 외화 소수를 정수화하거나 금액 파싱 실패를 0원으로 만들지 않는다.

- 출처: `docs/specs/ota.md:191`, `docs/specs/finance.md:240`

### RFND-041 · 직접 관측의 상태 충돌

*보호*

OTA 직접 관측을 저장한 사실만으로 결제·환불을 생성하지 않는다. 기간·카드·금액 충돌이나 취소 이후 정상 상태로 돌아오는 충돌은 내부 보호 대상으로 남긴다.

- 출처: `docs/specs/ota.md:683`, `docs/specs/ota.md:684`

### RFND-042 · 비용 준비와 OTA 연결 독립

*보호*

원본·중복·원결제·부분취소·환불 누락·기록 중복은 비용 준비의 필수 금융 검사다. 정상 카드는 OTA 스냅샷 오류·결제일 미상·예약 링크 EXACT/INFERRED/UNLINKED 차이만으로 막거나 숨기지 않으며 금융 충돌은 별도로 전달한다.

- 출처: `docs/specs/ota.md:245`, `docs/specs/ota.md:247`, `docs/specs/ota.md:527`, `docs/specs/ota.md:74`, `docs/specs/ota.md:304`

### RFND-043 · 여행 추론과 결제 관계 독립

*보호 · 결정 2026-10-28*

예약 이용기간으로 여행 후보를 계산해도 결제·환불 관계를 바꾸지 않는다. 결제 solver의 점유·수동 pin·실제 충돌 보호는 독립적으로 유지한다.

- 출처: `docs/specs/ota.md:721`, `docs/specs/finance.md:100`

### RFND-044 · 추론 링크와 검증 링크 구별

*보호 · 결정 2026-10-29*

단순 비교 후보나 INFERRED 링크만으로 개별 예약의 실제 결제·환불·장부 기록·항목/여행 상속을 확정하지 않는다. 최신 정확 금액 자동 연결 조건을 충족한 링크는 automatic·inferred=false로 처리하며 옛 추론 후보 제한과 구별한다.

- 출처: `docs/specs/finance.md:61`, `docs/specs/ota.md:219`, `app/ledger.py:377`, `app/partial_refund.py:280`

### RFND-045 · 결제중계 비교 후보

*일반 · 결정 2026-10-29*

같은 카드·14일 이내의 승인된 카카오 택시와 유페이 결제중계 명칭은 원결제 비교 후보로 볼 수 있으나 그 후보 표시 자체는 자동 금융 링크나 환급 증명이 아니다. 실제 연결에는 원승인번호 또는 최신 승인된 정확 금액 대조 조건이 필요하다.

- 조건·예외: 카카오페이·선물·주차·대리·다른 카드·기간은 이 결제중계 후보 확장 범위가 아니다.
- 출처: `docs/specs/refund-reconciliation-remediation-20261028.md:22`, `docs/specs/finance.md:61`, `webapp/tests/test_verified_cross_batch_refunds.py:156`

### RFND-046 · 취소 메일과 환불 요청

*보호 · 결정 2026-10-29*

취소 메일의 수신시각 오류만으로 취소 사실을 버리지 않는다. 환불 요청·위약금 또는 환불 가능 안내는 요청·조건의 근거이며 실제 카드 취소 원행이나 입금 완료의 증명이 아니다.

- 출처: `docs/specs/finance.md:71`, `docs/specs/finance.md:235`

### RFND-047 · 사전승인 증거

*일반 · 결정 2026-10-29*

숙박 사전승인은 실제 결제 완료와 구별한다. 온라인 사전 결제 문구가 없더라도 명시 사전승인액·예약·이용기간을 보존하고 정상 카드 원행의 날짜·금액과 대조한다.

- 출처: `docs/specs/finance.md:71`

### RFND-048 · 현장결제 보증과 환불

*일반 · 결정 2026-11-10*

Trip.com 현장결제 숙소의 카드 사전승인은 보증으로 구별한다. 같은 금액의 실제 카드 취소와 짝지어 순액 0을 표시할 수 있으나 실제 숙박비는 호텔 현장결제 원행이 담당하고 보증을 숙박비로 중복 합산하지 않는다.

- 출처: `docs/specs/ota-portal-browser-collection-20261110.md:67`

### RFND-049 · 포털 음수와 환불 관측

*보호 · 결정 2026-11-10*

Agoda 포털 결제 목록에 부분 환급·조정의 음수 줄이 있으면 정상 결제로 사용하지 않고 환불 근거의 내부 검토로 처리한다. 취소 예약의 청구·수수료·환불액은 분리하고 환불 관측을 실제 카드 환불 완료로 승격하지 않는다.

- 출처: `docs/specs/ota-portal-browser-collection-20261110.md:31`, `docs/specs/ota-portal-browser-collection-20261110.md:34`

### RFND-050 · 취소 수수료 실제 비용

*일반 · 결정 2026-11-10*

Agoda 취소 상세에서 청구액 전액이 취소 수수료로 남고 환불액이 없다는 근거가 있으면 취소 예약의 실제 비용으로 취급한다. 카드 원행과 구별하며 부분환불 잔액을 근거 없이 수수료로 추정하지 않는다.

- 조건·예외: 청구 전액이 수수료로 남고 환불액이 없다는 명시 근거가 필요하다. H65의 예외 절을 분리해 다른 후보와 입력 진술 1개를 공유한다.
- 출처: `docs/specs/ota-portal-browser-collection-20261110.md:34`

### RFND-051 · 캐시 포인트의 취소 제외

*일반*

캐시·포인트 비용을 카드 결제와 함께 또는 단독으로 기장하더라도 취소·환불된 예약에는 그 캐시 비용 기장을 적용하지 않는다.

- 출처: `docs/specs/finance.md:111`

### RFND-052 · 취소 예약 이용기간 제한

*일반*

취소된 예약은 정상 숙박 이용을 뒷받침하는 예약 기간 근거로 사용하지 않는다. 취소되지 않은 예약의 이용기간과 권위 일정으로 여행 근거를 판단하며 취소 상태·원문·관계는 보존한다.

- 출처: `docs/specs/finance.md:352`, `docs/specs/finance.md:277`

### RFND-053 · 저장된 예약 추론 무효화

*보호*

예약이 취소되면 그 예약을 근거로 저장된 여행 추론을 재사용하지 않는다. 사용자 수동 배정과 문서가 명시한 사용자 예외는 보존하고 취소 사실만으로 카드 금융 관계를 창작하지 않는다.

- 출처: `docs/specs/finance.md:363`

### RFND-054 · 취소 정산 자료의 역할

*보호*

비용 금액과 취소 전표는 국내 매입·해외 매입 원본으로 각각 확인하고 승인 내역은 최근 승인·승인취소·매입 전 거래의 보조 증거로 보존한다. 세 자료를 그대로 합산해 비용으로 기록하지 않는다.

- 출처: `docs/specs/finance.md:527`

### RFND-055 · 승인 취소와 매입 취소

*보호*

승인 취소와 매입 취소는 서로 다른 상태다. 승인 취소만 읽어 정산 환불이 모두 반영됐다고 판단하지 않으며 미매입 승인 취소를 새 환불 비용으로 기록하지 않는다.

- 출처: `docs/specs/finance.md:538`

### RFND-056 · 승인 매입 중복 효과 금지

*보호*

승인과 매입의 같은 결제는 출처가 둘인 하나의 거래다. 매입 원본 금액을 비용으로 사용하고 승인액을 추가 전기하지 않으며 승인 취소·취소매입의 환불 효과도 두 번 기록하지 않는다.

- 출처: `docs/specs/finance.md:565`

### RFND-057 · 취소 부호와 원문 분리

*보호*

취소 효과는 음수로 정규화하되 원본 파일·원문 금액은 그대로 보존한다. 해외 취소매출 원문이 양수라는 이유로 구매로 오인하거나 원본을 고치지 않는다.

- 출처: `docs/specs/finance.md:562`, `docs/specs/finance.md:448`

### RFND-058 · 취소 상세와 번호 구분

*보호*

국내 취소의 취소번호와 원승인번호를 별도로 보존하고 승인구분을 취소 상태로 해석하지 않는다. 카드 화면 요약 취소금액이 0이어도 상세 취소 원행을 누락하지 않는다.

- 출처: `docs/specs/finance.md:560`, `docs/specs/finance.md:562`

### RFND-059 · 매입 기간과 지연 취소

*보호*

조회 범위 밖 원승인일이라는 이유로 해당 매입·취소 행을 버리지 않는다. 지연 매입·취소 누락이 의심되면 매입일 기준의 겹치는 구간이나 더 넓은 기간을 다시 조회해 검증한다.

- 출처: `docs/specs/finance.md:555`

### RFND-060 · 동일값 복수 거래 보존

*보호*

외화 원본의 모든 열 값이 같더라도 실제 복수 거래의 개수를 보존하고 삭제·병합하지 않는다. 동일 원본 재수집 방지는 파일 해시·원본 행 위치로 하고 파일 간 연결도 다중도와 근거를 보존한다.

- 출처: `docs/specs/finance.md:564`

### RFND-061 · 장부 거래 식별과 중복 보호

*보호*

장부는 source_event_id로 같은 거래를 먼저 찾는다. 거래 ID 없는 과거 장부 행은 카드사·카드 끝자리·승인번호·날짜·부호 있는 금액·거래 종류가 모두 같을 때만 중복 차단하며 서로 다른 승인·취소·환불 원행을 보존한다.

- 출처: `docs/specs/finance.md:492`

### RFND-062 · 회사 경비 제외와 환불

*보호*

회사 경비 제외 경로로 환불 묶음·중복·충돌·잠금 거래나 기존 기장·사용자 결정 거래를 새로 제외하지 않는다. Google에 이미 붙여넣은 행을 자동 수정·삭제하지 않는다.

- 출처: `docs/specs/finance.md:614`

### RFND-063 · 특수 거래 종류

*보호*

현금서비스·리버설 등 특수 거래는 원문·금액·거래 종류를 보존하고 별도로 판정한다. 모두 일반 여행 비용이나 환불로 자동 처리하지 않는다.

- 출처: `docs/specs/finance.md:566`

### RFND-064 · 항공료 귀속의 환불 보호

*보호*

대장 항공료 근거를 자동 반영할 때 기존 사용자 확정 거래와 환불을 건드리지 않는다. 취소·부분환불·전액환불 원행과 기존 금융 관계를 항공권 귀속과 별도로 보존한다.

- 출처: `docs/specs/finance.md:206`, `docs/specs/finance.md:196`

### RFND-065 · 여행 교정과 환불 연결 보존

*보호 · 결정 2026-11-03*

승인된 원결제 여행 교정에서는 연결된 취소·환불도 같은 귀속으로 맞추되 기존 수동 항목·설명·원본·금액·ID·금융 관계·기기록 보호를 유지한다. 소수 교정은 revision·원자 저장·변경 전 값과 이력으로 복구하고 대량·삭제·금융 원본 변경만 별도 복구 게이트를 적용한다.

- 조건·예외: 입력 출처의 특정 여행 교정 결정을 일반 금융 링크 변경 권한으로 확대하지 않는다.
- 출처: `docs/specs/finance.md:11`, `docs/specs/finance.md:67`

### RFND-066 · 검토 보고의 실제 수행 범위

*일반 · 결정 2026-10-29*

이미 정상인 전액취소 쌍은 연결 확인·순액 0·이번 쓰기 없음으로 보고하고 같은 사실을 다시 질문하지 않는다. 미기록은 미기록으로, 기장은 실제 성공한 범위로 보고하며 조회를 새 연결·새 기록·전체 업무 완료로 표현하지 않는다.

- 출처: `docs/specs/finance.md:75`

### RFND-067 · 필터와 조회의 보호 불변

*보호 · 결정 2026-10-28*

필터 클릭과 조회는 금융 자료에 쓰지 않으며 취소·부분환불·초과환불·원본 충돌·기존 수동 교정을 해제하거나 실제 환급 완료로 표시하지 않는다.

- 출처: `docs/specs/expense-cleanup-status-filter-actions-20261028.md:163`

### RFND-068 · Google 최종 장부 쓰기 금지

*보호*

환불 연결·분류·내부 기록을 수행해도 COST가 Google 최종 장부를 자동으로 쓰지 않는다. Google 반영 사실은 사용자가 실제 반영한 근거와 구별해 보고한다.

- 출처: `docs/specs/finance.md:96`, `docs/specs/card-and-sheet-reconciliation-status-20261029.md:13`

### RFND-069 · 지정 취소 예약 분리 예외

*사용자 예외 · 결정 2026-10-04*

소유자가 개별 취소 예약을 여행에서 분리하라고 명시한 범위는 기존 결정을 유지하고 자동 재분류로 덮지 않는다. 지정된 취소 사전 숙박을 맞추려고 여행 시작일을 변경하지 않는다.

- 조건·예외: finance.md:231~232에 명시된 개별 예약만 적용한다. 원행·취소·환불 다중도와 감사 이력을 보존하며 부분환불 일반 규칙 전체로 확대하지 않는다.
- 출처: `docs/specs/finance.md:231`, `docs/specs/finance.md:232`, `docs/specs/finance.md:236`

### RFND-070 · 여행 지출표 환불 행

*사용자 예외 · 결정 2026-11-13*

Google 분기 지출 붙여넣기에서는 환불 탭에 있는 행도 원결제 위치를 확인할 수 있으면 원결제 여행 또는 분기 기타비용 TSV에 별도 행으로 포함하고 원래 부호를 보존한다. 원결제 위치는 거래의 `display_tab_id`를 우선 사용하며, 여행 탭 환불은 여행 TSV에, 분기 기타비용 탭 환불은 분기 기타비용 TSV에 포함한다. 환불액을 원결제에 합산하거나 원행을 수정·상계하지 않는다.

- 범위: COST 화면의 환불 행 귀속은 ITEM-011에 따라 환불 탭에 남긴다. 이 규칙은 화면 행을 여행 또는 분기 기타비용 탭으로 이동하지 않고 Google 붙여넣기 출력만 정한다. 원결제 여행과 분기 기타비용 탭 모두 적용한다.
- 예: 8월 숙박 30만 원 결제와 9월 10만 원 환불은 원결제 여행 탭에 `+300,000`과 `-100,000` 두 행으로 출력한다.
- 출처: 소유자 결정 2026-11-13 (과거 Google 여행 탭 환불 행 선례 22건)
