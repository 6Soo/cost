# OTA 매칭 규칙 기본 설정

2026-10-08 대화에서 직접 선택한 규칙과, 남은 질문에 추천값을 선택하라는 사용자 지시를 기록한다. 이후 실제 사례를 보며 변경할 수 있다.

이 문서는 규칙 설정의 기준이다. 현재 실행 코드와 운영 규칙 저장소에 모두 적용됐다는 뜻은 아니다. 이번 작업은 격리 worktree의 코드와 합성 테스트, 이 문서만 변경한다. 운영 DB와 실제 검토 DB는 변경하지 않는다. 기존 정확 연결 200건과 장부 734건의 보존 경계 및 production authority 전환 금지를 유지한다.

## 사용자가 직접 선택한 규칙

- 실제 결제 완료 또는 실제 환불 완료 근거가 있는 금전 이벤트만 카드 매칭 대상으로 삼는다. 예약 확정, 예정 결제, 환불 예정은 실제 결제로 승격하지 않는다.
- 같은 예약의 복수 결제와 환불은 각각 별도 이벤트로 보존한다. 취소 안내만으로 환불 이벤트를 만들거나 원 결제를 지우지 않는다.
- OTA 결제일과 카드 승인일을 비교한다. 매입일은 참고 정보다. 결제일이 없으면 카드 후보를 표시하지 않고 날짜 근거부터 확인한다.
- 승인한 업체별 날짜 차이만 허용하며, 빠름과 늦음의 방향도 지킨다. 검토 화면은 당일 및 승인한 방향과 범위 안의 모든 카드 거래를 표시한다.
- OTA 카드 끝자리가 있으면 반드시 일치해야 한다. 카드사 정보도 있으면 카드사와 끝자리를 모두 확인한다. 동일 끝자리의 여러 카드사가 후보이고 OTA 카드사를 모르면 HOLD로 둔다.
- OTA 카드 끝자리가 없으면 날짜, 정확 금액, 유일 후보, 업체 근거와 사용자 승인 merchant alias를 요구한다. 아래 동일 거래 묶음의 명시적 예외는 따로 적용한다.
- 승인한 merchant alias는 해당 OTA 업체 전체 상품에 적용한다. 이것만으로 비용 항목이나 여행을 정하지 않는다.
- 양쪽의 비교 가능한 승인번호가 있으면 일치해야 한다. 카드 끝자리, 승인번호, 날짜, 금액이 모두 맞으면 merchant 표기가 달라도 연결을 허용한다.
- 메일과 포털의 같은 결제 근거가 충돌하면 한쪽을 임의로 우선하지 않고 HOLD로 둔다.
- 외화는 원문 통화와 외화 금액을 정확히 비교한다. 외화가 같으면 원화 청구액 차이만으로 연결을 막지 않는다.
- 환불은 카드 취소·환불 방향 거래에만 연결한다. 원 결제와 환불을 서로 섞지 않는다.
- 실제 결제 근거가 있으나 카드 거래가 없으면 HOLD_NO_CARD로 유지한다. 새 카드 거래가 들어오면 관련 HOLD만 다시 대조한다.
- 수동 연결과 이미 확정된 배정은 근거가 바뀌어도 유지한다. 차이 또는 근거 변경 경고를 표시하고 사용자 확인 후 수정한다.

## Trip.com 항공권 차액

- 항공권 결제에만 적용한다. 숙박, 다른 상품, 환불에는 적용하지 않는다.
- 카드 청구액이 OTA 결제액보다 1,000원부터 10,000원까지 적은 경우를 허용한다.
- 차액은 정확히 1,000원 단위여야 한다. 허용 차액은 -1000, -2000, -3000, -4000, -5000, -6000, -7000, -8000, -9000, -10000원이다.
- 행사 기간과 결제수단 제한 없이 재사용한다. 나머지 카드, 날짜, 통화, 방향, 충돌 검사 조건은 충족해야 한다.
- 실제 할인 원인이 확인됐다고 표시하지 않는다. 사용자 승인 Trip.com 항공권 차액 규칙으로 표시한다.
- 정확 금액 연결을 먼저 배정하고 남은 거래에만 차액 규칙을 적용한다.
- 그 밖의 고정 차액 또는 할인율과 한도 규칙은 검증 가능한 근거와 승인한 조건 안에서만 적용한다. 포인트 적립은 청구액 할인으로 취급하지 않는다.

## 동일 거래 묶음

- 서로 다른 금액을 임의로 합산하는 방식이 아니다. 동일 날짜, 동일 금액 또는 승인 차액, 동일 통화, 동일 업체, 동일 상품 종류, 동일 카드와 동일 거래 방향의 반복 결제를 묶는다.
- 업체, 상품 종류, 카드사와 카드 끝자리, 결제와 환불 방향이 다르면 묶음을 분리한다. 이용기간이 달라도 묶을 수 있지만 예약별 이용기간은 따로 보존한다.
- 카드 끝자리가 없는 OTA도 나머지 동일 묶음 근거와 승인 alias가 충분하고 카드 후보가 하나의 카드로 한정되면 포함한다. 원본의 빈 카드 끝자리는 채워 넣지 않는다.
- 조건과 건수가 같으면 자동 완전 묶음 연결을 허용한다. 승인된 차액과 방향 있는 날짜 차이 규칙도 묶음에 적용한다.
- 건수가 다르면 특정 예약이나 카드를 임의로 고르지 않고 부분 대응 수량을 기록한다. OTA 3건과 카드 2건은 2건 대응, OTA 1건 미해결로 표시한다. OTA 2건과 카드 3건은 2건 대응, 카드 1건 미해결로 표시한다.
- 부분 묶음의 개별 여행 및 장부 배정은 구분 근거가 확보될 때까지 보류한다. 묶음에 포함된 카드는 다른 연결에 중복 사용하지 않는다.
- 부족한 카드가 추가되어 완전 묶음이 되면 다른 연결과 충돌하지 않는 범위에서 자동 전환한다. 기존 확정 연결은 유지한다.
- 완전 묶음에서 근거로 구분할 수 없는 개별 대응은 OTA 예약번호와 카드 승인번호 오름차순으로 배정한다. 예약번호가 같으면 OTA 이벤트 ID, 승인번호가 없거나 같으면 원본 카드 거래 ID 오름차순으로 보완한다.
- 위 정렬 대응은 사용자 승인 순서 배정으로 표시한다. 개별 결제 근거가 확인된 정확 연결로 표시하지 않는다. 각 예약의 검증된 이용기간을 사용한다.
- 나중에 실제 개별 대응이 확인돼 순서 배정과 다르면 기존 배정을 유지하고 차이를 표시하며 사용자 확인 후 변경한다.

## 남은 질문에 선택한 추천 기본값

아래 값은 이번 사용자 지시에 따라 선택한 추천 설정이다. 과거에 직접 답변한 사실로 표시하지 않는다.

- 메일과 포털의 중복 결제 증거는 공통 결제 식별값이나 명시 출처 연결 근거가 있을 때만 합친다. 같은 예약, 날짜, 금액, 카드라는 이유만으로 합치지 않는다.
- OTA 내부 결제 ID와 카드 승인번호는 서로 다른 식별 체계일 수 있다. 같은 의미와 체계로 검증된 값만 비교한다. 비교 불가능한 서로 다른 ID를 단순 문자열 비교해 충돌로 판정하지 않는다.
- 카드 점유는 전체 연결과 묶음에 걸쳐 확인한다. 기존 정확 연결과 사용자 연결은 우선 보존하고, 이미 다른 연결에 쓰인 카드의 재사용은 차단한다.
- duplicate_of, parse_error, conflict_reason이 있는 카드도 검토 화면에 표시하되 선택과 자동 배정에서 제외한다. 서버에서도 같은 조건을 검사한다.
- 후보 정렬이나 화면 표시만으로 자동 연결하지 않는다. 승인 규칙 적용 후에도 여러 서로 다른 묶음 구성이 가능하면 HOLD로 둔다.
- 할인율 규칙은 업체, 상품, 결제수단, 적용 기간, 최소 결제액, 할인율, 한도, 원 단위 계산 방식이 확인된 경우에만 제안한다. 부족한 조건을 임의로 채우지 않는다. Trip.com 항공권의 명시 차액 규칙은 위 별도 조건을 따른다.
- 새 수동 연결은 해당 연결만 저장하고 규칙은 제안 상태로 둔다. 이번 기본값 선택은 아직 발생하지 않은 모든 제안을 승인한 것으로 취급하지 않는다.
- 제안은 이번 건만, 규칙 저장, 조건 수정으로 답한다. 이번 건만은 이후 거래에 적용하지 않는다. 비활성 또는 철회 규칙은 승인 이력이 있어도 적용하지 않는다.
- 제안 질문은 확인된 차액과 날짜 차이, 카드, 업체, 상품, 적용 범위를 보여 준다. 할인 원인이나 결제수단을 추측해 사실로 적지 않는다.
- 원본 날짜, 금액, 통화, 거래 ID, 예약번호, 이용기간은 규칙으로 바꾸지 않는다. 자료 읽기 실패와 근거 부재를 구분하고 불완전한 자료로 신규 자동 연결하지 않는다.
- 새로운 자료나 새 규칙으로 사용자 확정, 보류, 기존 장부를 자동 변경하지 않는다. 미리보기의 근거가 바뀌면 다시 확인하게 한다.
- 규칙 변경은 버전과 변경 이유를 남긴다. 기존 확정에 소급 적용하지 않고, 미해결 및 이후 이벤트에 우선 적용한다.

## 실행 상태

2026-10-08 구현이 격리 worktree에 반영됐다. 기본 설정은 `config/ota-matching-defaults.json`에 두고 `app/ota_matching_defaults.py`가 설정을 읽는다. 업체 전체 merchant alias와 좁은 승인 규칙을 분리했다. Trip.com 항공권 차액 기본값은 카드 금액이 OTA보다 1,000원부터 10,000원까지 적고 1,000원 단위인 실제 결제에만 적용한다. 할인 원인을 확인한 사실로 표시하지 않는다. 정확 금액 후보를 먼저 평가한다.

매칭은 실제 결제 완료 또는 환불 완료 근거, OTA 결제일, 거래 방향, 통화 금액, 카드 끝자리와 카드사, 비교 가능한 같은 체계의 승인번호, 승인된 날짜 방향과 범위를 검사한다. 날짜 차이는 카드 승인일에서 OTA 결제일을 뺀 부호 있는 값으로 저장한다. 결제일이 없으면 카드 후보를 반환하지 않는다. 기존 연결은 전체 거래에서 먼저 점유시킨다. 자료 읽기 오류와 상충 근거는 새 자동 연결을 차단한다.

반복 거래는 provider, 상품, 결제 유형, 날짜, 금액 또는 승인 차액, 통화로 먼저 분리하고, 실제 카드 후보의 발급사·끝자리·방향별로 다시 나눈다. 금액을 임의 합산하지 않는다. 부분 묶음은 양쪽 건수와 ID 전체를 보존하고 개별 연결·장부 배정을 차단한다. OTA 2건과 카드 1건의 기존 HOLD_AMBIGUOUS 상태도 유지하면서 2:1 건수, 대응 수와 카드 예약을 표시한다. 건수가 같으면 예약 번호와 OTA 이벤트 ID, 승인번호와 카드 거래 ID 순으로 정렬해 사용자 승인 순서 배정으로 표시한다. 동일 최적해가 여러 개인 단건 전역 배정은 임의로 고르지 않고 HOLD한다. 개별 결제 근거와 구분하고 예약별 이용 기간은 그대로 보존한다.

기존 확정 링크와 frozen 그룹 카드 ID는 이벤트 원문이 현재 입력에 없거나 그룹 조건이 바뀌어도 전체 자동 후보, 수동 연결, 장부 후보에서 계속 점유한다. frozen 그룹은 이벤트·카드 전체 자료와 후보 edge의 지문도 고정한다. 매핑 카드가 현재 후보여도 evidence 지문이나 후보 edge가 달라지면 정상 연결로 표시하지 않고 재확인 경고와 HOLD를 유지한다.

기존 분리 검토 저장소 흐름을 사용한다. 새 연결만 저장하고, 규칙 제안은 사용자가 승인하기 전까지 비활성으로 둔다. 이번 건만 처리는 이후 거래에 적용하지 않는다. 합성 pin 검증은 200개 및 734개 기존 연결 크기 각각에서 연결 ID와 원문 금액이 유지되는지만 확인했다.

### 추가 acceptance 전의 이전 targeted 결과

- 후속 관련 파일 targeted 명령: `python -m pytest tests/card_pipeline/test_ota_matching_defaults.py tests/card_pipeline/test_ota_review.py tests/card_pipeline/test_ota_payments.py tests/card_pipeline/test_review_holds.py webapp/tests/test_ota_payment_review.py webapp/tests/test_card_flow.py -q`
- 결과: 171 passed, 37 subtests passed.
- 합성 Chromium 브라우저에서 390×844와 1440×900 화면을 확인했다. 후속 추가 acceptance의 최신 브라우저 결과는 아래 검증 섹션을 따른다.
- 임시 SQLite 저장소에서 요청 재시도 멱등성, 요청 ID 재사용 충돌, 바뀐 순서의 명시적 재확인, GET 조회의 무기록을 확인한다. 장부 경계는 부분 묶음 hold가 preview·commit과 projection 호출 차단까지 이어지는지 합성 검사한다.
- Python 문법, 설정 JSON과 `git diff --check`가 통과했다.

### 미검증

- 운영 DB·운영 규칙 저장소 반영, production authority 전환, 재대사, 재분류, 장부 기록, 재시작과 자료 새로고침은 수행하지 않았다.
- 실제 200건 정확 연결과 장부 734건의 운영 parity를 다시 실행하지 않았다. 위 검사는 합성 입력만 사용했으며 운영 숫자를 새 검증 결과로 주장하지 않는다.
- 모든 OTA 원천에서 카드사와 승인번호 체계가 제공되는지는 검증하지 않았다. 비교 체계를 확인할 수 없는 ID는 서로 비교하지 않는다.

## 2026-10-08 검토 보완 반영

| 검토 계약 | 상태 | 코드와 검증 |
|---|---|---|
| 날짜 범위의 양쪽 부호와 중간 날짜 전체 표시 | 구현·합성 검증 | `same_date_cards`가 승인된 signed lag 범위의 날짜를 전부 표시한다. |
| signed lag의 저장소·API·화면 계약 | 구현·합성 검증 | core, 질문 생성기, UI와 API parser가 -7부터 +7까지 같은 계약을 쓴다. 음수 approve/edit를 실제 localhost HTTP 테스트로 확인한다. |
| 부분 묶음 전역 카드 예약과 장부 차단 | 구현·합성 검증 | 예약 ID가 전체 검토 snapshot, 수동 선택 API, 카드 흐름 preview·commit hold로 전달된다. 합성 장부에서 ready 0, projection 0회, ledger row 0건을 확인한다. |
| 카드 정보가 없는 반복 거래와 부분 건수 | 구현·합성 검증 | 반복 signature에서 OTA 카드 필드를 제외한다. 부분 건수와 양쪽 ID 전체를 보존하고, 동일 카드 조건을 만족하는지 검사한다. |
| 정확 금액 우선 전체 배정 | 구현·합성 검증 | 승인된 모든 edge를 유지하고 전체 배정에서 exact edge를 우선한다. exact와 할인 허용액이 경쟁하는 반복 사례를 확인한다. |
| 그룹과 singleton 후보의 전역 충돌 | 구현·합성 검증 | 겹치는 카드 후보를 사전 검사해 그룹 입력 순서와 무관하게 충돌 전체를 HOLD한다. |
| frozen 순서와 재확인 | 구현·합성 검증 | 분리 SQLite 저장소에 그룹 ID, 매핑, 정렬 근거, 승인자와 버전을 저장한다. GET은 쓰지 않는다. 재시도는 멱등이며 본문이 다른 request ID 재사용은 거부한다. 변경된 완전 그룹은 확인 전 HOLD하고 새 제안 확인 후에만 교체한다. |
| 장부 차단 경계 | 구현·합성 검증 | 화면 문구뿐 아니라 preview·commit의 hold projection과 web adapter 연결을 확인한다. |
| payment ID와 issuer 모호성 | 구현·합성 검증 | 같은 명시 scheme을 가진 payment ID만 비교한다. issuer 미상에서 같은 끝자리의 복수 issuer 후보는 HOLD한다. |
| provider·issuer 별칭 | 구현·합성 검증 | `AGODA.COM`은 승인 출처·버전이 있는 명시 record다. 이전 정적 alias는 사용자 승인으로 승격하지 않는다. 동적 별칭은 화면과 HTTP API에서 명시 승인 후 저장·적용한다. |
| 할인율·한도와 원 단위 계산 | 구현·합성 검증 | 좁은 규칙에 할인율, 한도, 최소액, 반올림 방식, 결제수단과 기간을 요구한다. 확인되지 않은 행사 값은 활성화하지 않는다. 기본 활성 할인은 승인된 Trip.com 항공 charge 단계 차액뿐이다. |

### 총괄 재현 회귀

- `test_stable_group_tiebreak_uses_approval_order_after_booking_order`: 예약 A의 e1을 승인번호 A인 카드 z에, 예약 B의 e2를 승인번호 Z인 카드 a에 연결한다.
- `test_card_claimed_by_an_absent_linked_event_is_excluded_from_repeated_group`: 없는 기존 이벤트가 점유한 카드 a를 제외한다. 두 새 이벤트와 남은 카드 b는 2:1 HOLD_AMBIGUOUS이며 대응 건수 1과 b 예약을 보존한다.
- `test_repeated_events_with_distinct_known_cards_form_separate_groups`: 끝자리 2042인 e1은 카드 a, 9999인 e2는 카드 b에 각각 연결한다.
- `test_equal_optimum_singleton_candidates_across_signatures_hold_as_a_component`: 서로 다른 항목의 단건 후보가 같은 최적 배정을 만들면 모든 연관 이벤트와 카드 후보를 HOLD한다.
- frozen 그룹의 source 누락·signature 변경·후보 edge 변경 테스트는 고정 카드 예약과 재확인 경고를 확인한다. review adapter 테스트는 source가 사라진 pin 카드도 수동 선택과 장부 preview·commit에서 막는지 확인한다.

### 남은 제한

- 고정 그룹에 건수 차이를 만드는 카드나 OTA 이벤트가 추가되면 계속 HOLD한다. 완전한 일대일 제안이 생기기 전에는 새 배정을 확정할 수 없다.
- 여러 OTA 업체의 임의 행사 조건을 자동으로 찾거나 활성화하지 않는다. 사용자가 출처와 조건을 승인한 할인 규칙만 저장할 수 있다.
- 운영 데이터의 payment ID scheme, merchant와 issuer 분포는 확인하지 않았다. 운영 parity와 실제 자료 검증은 미실행 상태다.



## 추가 acceptance 계약 및 검증 상태

- 날짜 규칙은 `date_lag_min_days`와 `date_lag_max_days`를 함께 저장하며 양 끝을 포함한다. -1부터 +2까지면 -1, 0, +1, +2일을 후보로 표시하고 -2와 +3일은 제외한다. 기존 `date_lag_days`는 양수면 0부터, 음수면 해당 일수부터 0까지의 범위로 읽는다. 새 범위와 기존 scalar를 한 규칙에 함께 저장하지 않는다.
- 부분 그룹의 후보 카드 점유는 화면과 API 요청 처리 중에만 유지한다. 부분 그룹은 검토 저장소의 영구 allocation이나 개별 link로 저장하지 않는다. 저장 거부 뒤 합성 데이터베이스에 관련 row가 없어야 한다. 전체 그룹을 사용자가 확인하면 하나의 고정 그룹 allocation으로 저장하고 그 카드 전부를 다른 그룹의 자동·수동 후보에서 막는다.
- 카드 끝자리가 없는 이벤트는 자동 반복 그룹에 일반화하지 않는다. 실제 대응은 별도 사용자 확인 경로로 저장할 수 있으며, 원문에 없는 카드 힌트를 만들지 않는다.
- 승인된 차액 조건은 만족하는 event-card edge에만 적용한다. exact와 차액 후보를 구분하고, 서로 다른 업체·상품·사용자 규칙 조건을 한 범위로 넓히지 않는다. 제안 승인 전 활성 규칙 수는 0이다. 승인 뒤에도 업체, 상품, merchant, 카드, 적용 날짜, 통화, 환불 여부와 단계 금액의 승인 범위를 벗어난 거래에는 재사용하지 않는다.
- 합성 보존 검사는 synthetic 200개 연결과 수동 연결 snapshot의 ID, 원문 금액, 날짜, 근거 원문을 비교한다. overwrite 수는 0이어야 한다. 이 검사는 운영 200건 parity를 다시 실행한 결과가 아니다.

### 이번 추가 acceptance 실행 결과

아래 명령은 추가 조건에 필요한 targeted subset만 실행했다. 전체 회귀는 실행하지 않았다.

| acceptance | 관찰 테스트 | 실행 결과 |
|---|---|---|
| 1 | `test_acceptance_01_partial_group_is_temporary_and_never_written_to_allocation_store` | HTTP/API targeted 묶음 통과 |
| 2, 3 | `test_acceptance_02_03_full_group_confirmation_persists_one_group_and_blocks_all_card_reuse` | HTTP/API targeted 묶음 통과 |
| 4, 5, 8 | `test_acceptance_04_05_signed_lag_range_round_trips_over_http_sqlite_and_matcher` | 승인 전 활성 규칙 0, -1..+2 SQLite 저장과 매처 적용 확인 |
| 6 | `test_acceptance_06_blank_hint_group_needs_ui_confirmation_and_persists_only_the_confirmed_mapping`; `test_acceptance_06_blank_card_hint_requires_confirmation_then_stores_actual_group` | HTTP/API와 매처 targeted 명령 통과 |
| 7, 9 | `test_acceptance_07_approved_delta_is_limited_to_its_full_edge_scope`; `test_acceptance_07_item_scoped_rule_exposes_exact_and_delta_edges_separately`; `test_acceptance_07_saved_delta_rules_keep_exact_and_delta_edges_in_their_own_scope` | 매처와 저장소 targeted 명령 통과 |
| 10 | `test_acceptance_10_refresh_never_overwrites_two_hundred_manual_source_snapshots` | 합성 200개, snapshot overwrite 0 확인 |
| 화면 | `test_synthetic_browser_group_candidates_disabled_proposal_and_overflow`; `test_synthetic_browser_submits_signed_lag_range_without_legacy_scalar` | Chromium 합성 브라우저에서 390x844와 1440x900 검증 통과 |

- `python -m pytest tests/card_pipeline/test_ota_matching_defaults.py -k 'acceptance_04 or acceptance_06 or acceptance_07 or acceptance_10 or group_signature_ignores_missing_ota_card_facts' -q` — 6 passed, 37 deselected.
- `python -m pytest tests/card_pipeline/test_ota_review.py::test_acceptance_07_saved_delta_rules_keep_exact_and_delta_edges_in_their_own_scope -q` — 1 passed.
- `python -m pytest webapp/tests/test_ota_payment_review.py -k 'acceptance_01 or acceptance_02_03 or acceptance_04_05 or acceptance_06' -q` — 4 passed, 26 deselected.
- `python -m pytest webapp/tests/test_ota_matching_defaults_browser.py -k 'signed_lag_range or group_candidates_disabled_proposal_and_overflow' -q` — 3 passed, 1 deselected.
- 총 14개 targeted 테스트가 통과했다. 합성 입력과 임시 SQLite 결과이며 운영 자료나 운영 parity를 검증하지 않는다.

## 실제 운영 자료 읽기 전용 parity — 2026-10-08

합성 acceptance 이후 현재 feature 코드로 운영 자료를 읽기 전용 대조했다. 기존 exact pair의 OTA 이벤트 ID, provider, booking_ref, transaction_id, source/evidence digest와 카드 source_hash를 개별 비교했다.

- 기존 실제 exact 200건 중 200건 모두 동일 이벤트와 카드 거래로 유지됐다. 변경 0, 누락 0, 근거 또는 카드 원문 해시 차이 0이다.
- 카드 중복 배정 0, 사용자 확정·수동 연결 overwrite 0, 기존 exact 카드 재사용 0, 기존 1:1 exact의 묶음 전환 0이다.
- 전체 이벤트 1,304건, actual payment 383건, matched 200건, HOLD 183건이다. 새 auto match 0건, 새 그룹 연결·후보 0건이다. HOLD는 카드 없음 124건, 결제일 미확인 59건으로 계산됐다.
- 운영 전체 테이블 75개와 schema를 실행 전후 비교했다. 변경 0이며 장부 734건을 유지했다. 등록·보존 원본 파일 963개와 운영 코드, 보호 사용자 파일도 변경 0이다.
- SQLite 연결은 mode=ro와 query_only로 제한했고 쓰기 연결을 실행 중 거부하도록 했다. review DB·폴더 생성 0, 운영 자료 폴더의 새 파일 0이다. 새 결과를 운영에 저장하지 않았다.
- 운영 재시작, source refresh, 재수집, 재분류, production authority 전환을 수행하지 않았다. 기존 targeted 14 passed 결과를 재사용했고 추가 테스트·전체 회귀는 실행하지 않았다.

상세 pair 비교와 계산 결과는 `C:/AX/cost/.local-archive/ota-defaults-parity-20261008/`에만 보존한다. 실제 예약·거래 식별자와 원문 자료는 Git에 포함하지 않는다. 앞선 미검증 항목 중 운영 parity는 이 단계에서 확인했으며, 운영 배포와 실제 검토 저장은 여전히 미실행이다.

## Trip.com 항공료 표기와 정확 가맹점 보정 — 2026-10-09

기존에 승인된 Trip.com 항공 차액 규칙이 실제 운영 표기를 놓치고 있어 설정 두 곳만 보정했다. 새 -4,000원 전용 규칙은 만들지 않았다.

- `trip_flight_charge_delta.item_values`에 `항공료`를 추가했다. 기존 `항공`, `항공권`, `flight`, `airfare`는 그대로 유지한다. 항목 동의어 보정이며 새 할인 규칙이 아니다.
- `provider_merchant_alias_records.trip`에 정확 문자열 `대표_카카오페이-트립닷컴`을 `approved`, version 2, source `user-approved-trip-airfare-exact-descriptor-2026-10-09`로 추가했다.
- 기존 `trip.com`, `trip.com korea` alias는 candidate 그대로 둔다. 넓은 `트립닷컴`은 승인하지 않았다. 사전 dry-run에서 넓은 별칭은 후보 40건과 HOLD_AMBIGUOUS 2건, 묶음 관련 HOLD 19건을 만들어 영향 범위가 크다고 판단했다.
- OTA 원천에 카드 끝자리가 없으면 미확인으로 유지한다. 카드 측 후보의 끝자리를 OTA 사실로 승격하지 않는다.

### 검증

- 직접 관련 targeted: `python -m pytest -q tests/card_pipeline/test_trip_airfare_descriptor.py tests/card_pipeline/test_ota_matching_defaults.py` — 77 passed. 전체 회귀는 실행하지 않았다.
- 새 테스트(`test_trip_airfare_descriptor.py`)는 `항공료` 포함 5개 항목값, 정확 alias의 버전·출처, 다른 Trip.com 표기의 승인 비상속, -1,000~-10,000원 1,000원 단위 유지와 범위 밖 HOLD, 숙박·환불·다른 업체 비적용, 정확 금액 우선, 복수 후보 HOLD, 기존 exact 카드 재사용 금지, OTA 카드 끝자리 미생성을 합성 입력으로 확인한다.
- 운영 읽기 전용 parity(변경된 실제 설정으로 계산, 운영 DB·review DB 해시 전후 동일):

| 항목 | 결과 |
|---|---|
| 기존 exact 200건 변경 / 누락 | 0 / 0 |
| 카드 중복 배정 | 0 |
| 수동 연결 overwrite | 0 |
| 신규 MATCHED_AUTO | 3 (모두 Trip.com 항공료, 날짜 차이 0일, 차액 -4,000원, 후보 1개, OTA 카드 끝자리 미확인) |
| HOLD | 182 → 179 (HOLD_NO_CARD 120, HOLD_DATE_UNKNOWN 59) |
| 신규 HOLD_AMBIGUOUS / 신규 그룹 연결 | 0 / 0 |
| 다른 할인 차액의 신규 연결 | 0 |

- 신규 3건은 모두 기존 `approved_trip_flight_delta` 규칙으로 연결됐다. 같은 날짜 카드 거래를 전부 대조했고 기존 exact·수동 카드와의 충돌은 없었다.
- 운영 DB 쓰기, review DB 쓰기, production authority 전환, 재시작은 수행하지 않았다.
