# 코드와 규칙이 다른 곳

> [판정 규칙집](../DECISION_POLICY.md)의 규칙과 현재 코드가 다르게 동작하는 지점이다. 규칙이 정본이고 코드가 고칠 대상이다.
> 통합 명세 로드맵의 M2에서 P2 연결과 함께 정리한다. 별도 재현 근거를 적은 항목 외에는 코드를 읽어 찾은 것이며 실행해 재현한 것은 아니다.

| 규칙 | 주제 | 코드가 다르게 하는 점 |
| --- | --- | --- |
| SRC-045 / P2-SAME-TICK-20261112 | P2 메타데이터 캐시의 동일 tick 변경 | `app/p2_case.py`의 `_stamp`는 경로·크기·mtime·변경시각·inode를 사용한다. Windows에서 같은 tick 안에 동일 크기로 내용을 바꾸고 mtime을 복원하면 모든 메타데이터가 같을 수 있다(2026-11-12 합성300회 중70회 재현). 이 경우 캐시 무효화가 누락될 수 있으며 내용 지문/신뢰 버전의 보증과 같지 않다. 이번 #815는 관련 회귀 검사의 최초 ChangeTime만 과거로 결정화하고 기대값은 유지했다. 운영 읽기 예산·해싱·캐시 구현은 변경하지 않았으므로 이 한계는 미해결이다. 근거: `.local-archive/probe_change_time.py`, #815 건별 표. |
| PROC-012 | P2에 주는 자료 | app/ai_classification.py의 prepare()는 가맹점 이름과 원문 없이 날짜·국가·후보 여행만 넘긴다. M2에서 사건 폴더 방식으로 바꾼다. |
| PROC-013 | P2 실행 모델 | app/connected_agent_provider.py는 무료 OpenCode 모델만 허용한다. M2에서 실행기를 바꾼다. |
| TRIP-005 | Google 탭에 없는 기존 여행 | 운영 DB에 Google 연결이 없는 여행이 남아 있다. 합치기와 재판정은 M2에서 한다. |
| TRIP-006 | 검증된 여행 조건 | app/trip_selection.py:40의 canonical_trip_periods는 형식·플래그를 검사하며 종료일이 여전히 없는 마지막 여행도 사전에 남긴다. 이 helper만으로 Google 원본·digest·종료일 완전 검증을 충족했다고 볼 수 없다. |
| TRIP-NEW-20261112 / PROC-072 | 완료 기간 선행 제외 | 공통 closed_period 판별을 P1·재판정·P2·미분류 통과 검사에 연결하고, 기존 일반형 분기 탭으로 옮기는 감사·원복 CLI를 추가한다. 후속 결정의 환불 짝 전체 원자 이동과 금융 관계·보호 불변 검증을 포함한다. 운영 반영 전까지 기존 귀속은 남아 있으며 사본 예행 결과와 최종 검증은 session_handoff 맨 위 및 PR에 기록한다. |
| PROC-016 / REC-008 | 항목 교정과 여행 귀속 | app/classification_correction.py의 기존 장부 동기화는 항목만 교정하는 요청에서도 장부의 여행·표시 탭을 거래 값에 맞춘다. 귀속 불일치109건은 P2에서 제외했으며 자동 교정하지 않았다. 별도 후속 설계 대상이다. |
| TRIP-041 | 이용기간 여행 순위 | app/reconciliation.py:116의 stay_trip은 덮음/겹침/차액까지 동률이면 None을 반환한다. 이 내부 미선택 결과와 finance.md:88의 정상 카드 마지막 단계 일정·ID 선택은 계층을 구분해야 한다. 이번 읽기만으로 최종 사용자 화면에 대기가 남는다고 단정하지 않는다. |
| TRIP-042 | 준비 숙박 | app/reconciliation.py:106의 prep_trip 자체는 체크아웃 이후 가장 가까운 시작일만 확인하며 직전 여행 종료/밤 비중첩 조건은 함수 안에서 검사하지 않는다. 같은 시작일 후보가 여러 개면 None을 반환한다. 호출자와 마지막 카드 귀속 경로의 보완 여부는 이 입력으로 확정하지 않는다. |
| TRIP-049 | 묶음 여행과 예약 신원 | docs/history/ota-legacy.md:1246은 포털 _identical_group_matches가 묶음에 행별 예약번호를 붙이는 과거 구현 차이를 보고한다. 현재 코드 실행 여부를 재검증한 사실로 보지 않는다. |
| TRIP-053 / DATE-035 | 캐시·포인트 귀속 | 개정 규칙(ITEM-019 정렬)은 캐시·포인트를 카드와 같은 과정으로 귀속한다(복수 후보→PROC-021 동률, 부재→결제일 분기 기타비용). app/ota_cash_use.py cash_expense_rows는 복수 후보를 목적지로 좁히거나 unclassified로, 부재를 준비 숙박 또는 unclassified로 남긴다. |
| TRIP-079 | 분기 표시와 공유 판정 | lean-card-ota-core-20261030.md:17은 당시 completion_for_row/미배정 필터가 실여행 ID만 유효하게 취급할 수 있던 구현 차이를 지적한다. 이는 당시 진단이며 현재 코드의 미해결 결함으로 단정하지 않는다. |
| TRIP-089 | 결제일 미상과 여행 증거 | app/ota_inference.py:50과 config/ota-matching-defaults.json:57의 구형 Agoda 경로는 verified portal·상호 유일성·정확 끝자리/금액을 요구한다. 입력의 2026-11-01 M:N 최신 관계 계약을 이 구형 코드의 1:1 한도로 축소하지 않는다. 이 영역 입력만으로 새 M:N 경로 전체를 검증하지 않았다. |
| ITEM-002 | 날짜·금액 오류 보호 | app/classify.py:300은 파싱 오류에 needs_review/unreadable을 반환한다. 내부 오류 식별은 보호 규칙과 부합하나 사용자 대기 상태로 노출하면 안 된다. 입력만으로 화면 노출 여부는 입증되지 않는다. |
| ITEM-004 | 항목 공통 추론 순서 | app/classify.py:451은 규칙·패턴이 없으면 needs_review를 반환한다. 이는 중간 P1 결과이며 app/automatic_classification.py:356-394의 공통 항목·여행/분기 종결을 거치지 않으면 최신 계약과 다르다. 입력 코드만으로 전체 파이프라인 누락은 단정하지 않는다. |
| ITEM-007 | OTA 자료 부족 시 종결 | app/classify.py:446-449는 온라인·예약 가맹점에 booking_evidence_needed/needs_review를 반환한다. 뒤의 공통 종결 단계 없이 사용자 질문으로 끝내면 최신 정책과 다르며, 해당 반환만으로 최종 동작의 결함을 단정하지 않는다. |
| ITEM-019 | 캐시·포인트 지출의 귀속 | app/ota_cash_use.py는 이용일을 덮는 여행이 없거나 여럿이면 unclassified로 남긴다. |
| ITEM-029 | 스카이티켓 항공료 | app/classify.py:426-431은 항공료만 채우고 여행은 빈값·unclassified 기본 탭으로 반환한다. 항목은 최신 결정에 부합하며 후속 여행/분기 종결이 필요하다. 이 함수만으로 최종 미귀속 결함을 단정하지 않는다. |
| ITEM-059 | 실제 규칙 충돌 보호 | app/classify.py:384-387은 규칙 effects와 대상 여행 전체가 다르면 rule_conflict/needs_review와 사용자 확인 문구를 반환한다. 사용자 대기 UI로 노출하면 폐지 결정과 다르며 내부 충돌 보호는 유지 대상이다. |
| ITEM-060 | 같은 결론의 근거 문구 | app/classify.py:384는 effects 전체를 비교하므로 항목·여행이 같아도 description 등 부수 필드 차이로 충돌할 가능성이 있다. 입력에 담긴 일반 규칙 비교 코드와 추론 병합 경로의 적용 범위는 구분해야 하며 실제 재현 검사는 수행하지 않았다. |
| DATE-001 | 여행 생성·연도 원천 | app/google_authority.py:300은 제목 연도가 없으면 BASE_YEAR, 제목 종료일이 없으면 비용 행 기간의 최종 종료일을 읽는 것으로 추출됐다. 제목 원천과 다음 여행 전날 규칙 외의 fallback이어서 문서 규칙으로 승격하지 않는다. |
| DATE-044 | 공통 숙박기간의 제안 | tests/card_pipeline/test_same_day_lodging_group.py:59는 레거시 카드 수>예약 수이면 공통기간을 제공하지 않는다고 기대한다. 최신 문서는 건수 차이만으로 관계를 끊지 말라고 하므로, 관계는 유지하고 기간 제안 경로의 추가 제약으로 분리해 검토해야 한다. |
| LINK-002 | 연결의 기본 조건 | app/ota_inference.py와 config/ota-matching-defaults.json, tests/test_ota_inference.py에 Agoda 전용 "상호 유일" 조건이 남아 있다. 끝자리가 없고 결제일만 맞는 경우의 연결은 app/ota_payments.py에서 확인이 필요하다. docs/specs/ota-portal-browser-collection-20261110.md:32의 "상호 유일 추론에만 맡긴다"는 이 규칙으로 대체한다. |
| LINK-003 | M:N 관계 보존 | 레거시 app/ota_portal.py:326와 test_portal_identical_bookings.py:38의 동수량 제한은 구형 경로에 남아 있다. 관계 자체를 미연결로 돌리는 근거로 적용하지 말고 금융 배분과 분리해 재검토해야 한다. |
| DATE-029 / LINK-069 | 예정 자동결제 1:1 강제 | 개정 규칙은 예정 자동결제 예외에서 일대일/상호 유일을 요구하지 않는다(LINK-002·ITEM-080 M:N). app/ota_portal.py scheduled_card_date_matches는 카드→예약(len(options)!=1)과 예약→카드(len(rows_by_booking[booking])!=1) 양쪽 1:1만 통과시켜 M:N 묶음을 연결하지 않는다. |
| LINK-048 | 실제 여행 우선 귀속 | tests/card_pipeline/test_ota_inference.py:137은 여행 동률을 CONFLICT_REVIEW로 남긴다. 현재 정상 카드의 최선 여행/분기 목적지 판정과 내부 금융 잠금을 구분하고 사용자 분류 대기 상태로 쓰지 않아야 한다. |
| LINK-074 | 취소·정책·환불 구분 | tests/card_pipeline/test_airline_payment_mail.py:87은 항공사 취소 통지에서 기존 paid 근거를 evidence_conflict로 두고 검증을 중지한다. 일반 취소 예약의 이미 검증된 charge·관계 유지 규칙과 다르므로 신규 검증 중지와 과거 원결제/관계 삭제를 구분해야 한다. |
| RFND-008 | 카카오 택시 동액 연결 | app/partial_refund.py:317은 양쪽 상호에 카카오가 있으면 먼저 14일 후보를 만들고 :325에서 family 일치만 검사한다. 따라서 동일한 비택시 카카오 상호도 14일 연결될 수 있어, :278의 동일 상호는 당일·택시 변형만 14일이라는 설명보다 넓다. family가 다른 경쟁 후보도 collision에 먼저 포함돼 정상 연결을 보수적으로 막을 수 있다. |
