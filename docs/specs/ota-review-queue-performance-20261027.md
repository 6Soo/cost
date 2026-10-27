# OTA 검토 대기열·그룹화·페이지네이션·대사 성능 구현 명세

- 작성: 2026-10-27
- 상태: **SPEC_ONLY / TEST_NOT_RUN / NO_RUNTIME_CHANGE**
- 연결: [전면 리팩토링 마스터](refactor-master-20261027.md), [OTA 금융/정본 정책](ota.md), [운영 기록](../operations.md)
- 목적: 접힘/지연 조회는 이미 있는 기능이다. 이번 범위는 **과도한 미결 수 자체를 줄이고, 서버가 필요한 목록만 전달하며, 동일 예약의 다수 이벤트를 한 카드로 묶는 것**이다.

## 1. 확인된 현재 코드

- webapp/ota_payment_review.py::CoreOtaPaymentBackend.snapshot_from은 결과 전체를 순회해 HOLD, 수동 연결 변경, 예약 관계 등 조건별 이벤트를 화면용 holds에 담는다. 정상 MATCHED 전부를 보여주는 구조는 아니다.
- public_snapshot은 기본 응답에서 카드 후보 전체를 제외하고 events 배열은 전부 포함한다. cards_for_event와 GET /api/imports/ota/cards/<event_id>는 이미 별도 lazy 경로다.
- GET /api/imports/ota는 snapshot_service의 마지막 공개 스냅샷을 반환한다. 모든 이벤트를 서버에서 페이지네이션하는 계약은 확인되지 않았다.
- webapp/ota_payment_review.py::_transactions는 SELECT * FROM transactions를 호출한다. 실제 병목 여부는 프로파일링 전에는 단정하지 않는다.
- /import의 OTA 영역은 기존 #189/#190으로 기본 접힘, 펼칠 때 조회, 닫힌 동안 poll 중단; **이 기능을 다시 작성하지 않는다**.
- webapp/ota_snapshot.py는 배경 계산·상태·세대·last-good snapshot을 관리한다. 요청 경로에서 전체 reconciliation을 동기 실행하지 않는 기존 안전 경계를 유지한다.

## 2. 목표 화면과 큐

~~~text
OTA 결제 관리   [스냅샷 시각 / 최신성]
조치 필요 [N] | 원본/자동 재검증 대기 [N] | 근거 누락 [N] | 처리 완료 [N]
검색: 예약번호/공급자/허용된 가맹점 | 필터: 오류/보류 이유
[예약 그룹 카드 1: 결제/취소/환불 요약, 실제 사유] [상세 펼치기]
[예약 그룹 카드 2] ... 기본 20개
이전 / 다음
~~~

기본 화면은 needs_action 우선, 이벤트별 전체 장문 대신 상태·사유·후보 건수만 표시한다. 그룹 상세에서 이벤트 원형 ID, 결제/환불 유형과 날짜, 카드 후보(별도 GET), 원본 근거를 확인한다. 다른 화면 이동 지시 없이 현재 카드 내부에서 충분한 근거·허용된 처리 동작을 제공한다.

## 3. 독립 상태 축

반드시 별도로 보존:
- 금융 검증/환불·매입 상태
- OTA 원본 이벤트별 매칭 (MATCHED_AUTO/MATCHED_USER/HOLD_*/RESERVATION_ONLY 등 기존 코어 원본 상태)
- 예약 관계 확인
- 여행 귀속 및 비용 기록 준비
- Google 복사·확정 / 실제 환급 여부
- **큐 표시 상태**: needs_action / waiting_source / evidence_missing / auto_recheck / completed / historical

큐 상태는 UI projection으로 계산한다. completed는 코어가 현재 증빙으로 해결됐고 evidence_missing/changed/conflict 등 경고가 없을 때만 해당한다. RESERVATION_ONLY는 결제 완료가 아니다. 오래됐다는 이유만으로 historical이 금융 완료가 되는 것은 아니다.

큐 별 통계는 1개의 기본 큐에 속하는 **이벤트 수**와 **예약 그룹 수**를 따로 계산하고, 부가 원인 태그는 복수여도 괜찮다. 오류/refreshing/stale는 빈 결과나 완료 수로 위장하지 않는다.

## 4. 그룹 규칙

예약 그룹 키 우선순위: 공급자 정규화 + 검증된 예약번호 + source lineage. 예약번호가 없으면 동일한 정본 근거를 가진 경우에만 그룹화를 허용한다. 단순 이름·금액·근접 날짜만으로 그룹화 금지. 키 충돌/중복 예약번호 의심 시 분리 후 검토 상태로 둔다.

여러 charge, installment, cancellation, refund, amendment를 한 예약 카드 아래 **원본 이벤트 그대로** 나열한다. 개별 사건 금액, 통화, 실제 결제 상태를 보존한다. 서로 다른 통화를 임의 환산하거나 부분 환불을 완료로 표시하지 않는다. 전체 그룹 순액은 검증된 동일 통화 금액에 한하여 파생 표시하며 원본 값 쓰기 금지.

## 5. API 명세

### GET /api/imports/ota/summary

반환: snapshot_generation, generated_at, status (loading/ready/refreshing/error), stale, refreshing, counts_by_queue, count_unit(event/group), warning_count. summary는 스냅샷 작업 시 만들어 두며 GET마다 전수 집계하지 않는다.

### GET /api/imports/ota/events?queue=needs_action&limit=20&cursor=...&provider=...&q=...

- 기본 limit=20, 허용 1..100.
- items는 allowlist 기반 그룹/이벤트 요약만; 카드 후보 원문/메일 본문/민감 메타데이터는 포함하지 않는다.
- 필터는 정의된 enum·공급자·길이 제한된 예약번호/가맹점 검색어만 허용한다.
- total_count 및 next_cursor, 동일 세대 스냅샷 ID·시각·상태 포함.
- 서버 측 정렬은 priority + event relevant date(미상 명시) + unique id로 안정적이어야 한다.
- cursor는 불투명 토큰으로 필터 해시, 정렬키, generation을 바인딩. snapshot 세대/필터 불일치는 409 SNAPSHOT_CHANGED 등 명확한 오류로 반환해 새 첫 페이지를 요청한다.
- 단순 CSS 숨기기·클라이언트 전체 1000건 fetch 후 slice는 **요구사항 미달**이다.

기존 GET /api/imports/ota 사용자는 호출자 검색·계약 테스트 통과 전 조용히 바꾸지 않는다. 카드 후보 GET /cards/<event_id>, 진단·preview/confirm 경로와 인증/CSRF/리비전 보호를 유지한다.

## 6. 대사 자동 해결 정책

대사 owner는 app/ota_payments.py 기존 solver. UI에서 별도 매칭 알고리즘 금지. 자동 해결은 공급자별 근거 정책, 날짜/금액/통화/카드 정보, 원본 digest, 사용자 pin, 전역 후보 유일성 및 card occupancy를 보호한다. match/inferred/user-confirmed 의미를 구분한다.

우선 기준선 조사로 HOLD 상태를 유형별 집계한다: 날짜 미상, 카드 없음, 금액/통화 차이, 카드 중복·가맹점 alias, 예약 전용, 예약/결제 분리, 원본 변경·증빙 소실, 그룹 고정 충돌, 환불·원결제 연결. 빈도가 높고 안전한 규칙부터 작은 별도 PR로 해결한다.

Agoda 결제일 미상은 기존 app/ota_inference.py::unique_pairs를 우선 검증한다. 자동 후보가 하나라는 이유로 금융 확정하지 않는다. 가승인/환불은 사용자 승인된 카드 원장 규칙에 따르며 OTA 카드 추론 결과로 실제 환급을 선언하지 않는다.

## 7. DB·계산 성능

처음에는 관측만 한다:
- 전체 이벤트 수, 큐별/공급자별 이벤트 수와 그룹 수, 중복 표시 감소율
- OTA 원본 파싱 시간 / 카드 조회 시간·행수 / solver / snapshot projection / serialization
- /api/imports/ota 원본 payload bytes/p50/p95, 새 summary/events p50/p95
- browser DOM 노드·메모리·network waterfall / 모바일 스크롤
- SQL EXPLAIN QUERY PLAN 및 대량 후보 조회 비용

후속 단계:
1. 저장된 snapshot projection에서 큐/그룹/카운트를 미리 계산.
2. GET에서 특정 페이지 요약만 직렬화. 초기 화면은 20개 DOM 카드.
3. 실제 사용된 컬럼 확인 후 SELECT * 제거·실행계획 기반 인덱스 변경 검토.
4. 원본 digest/카드 입력 fingerprint/규칙 버전을 이용한 증분 재계산은 **global solver 동등성 테스트 이후에만** 사용. 새 카드 1개가 과거 예약의 유일 후보를 깨뜨릴 수 있으므로 영향받는 연결 성분 전체를 재계산한다. 규칙/대량 입력 변경·실패 시 full rebuild fallback.

스키마 변경은 additive migration, 읽기 전용 기준선, 복구 검증을 선행한다. 문서만으로 운영 DB 인덱스/데이터를 변경하지 않는다.

## 8. 수락 테스트 및 수치

- 합성 10k/100k OTA 이벤트 + 별도 대량 카드 규모에서 summary/list는 O(page size) 직렬화이며 전체 전송하지 않음.
- 첫 페이지 20개, 다음 페이지 중복/누락 0, snapshot generation 변경 시 409·안전 재조회.
- 그룹의 다중 결제·다중 환불·다중 통화·원본 충돌/예약번호 없음/다른 공급자 시나리오에서 금융 이벤트 내용 불변.
- MATCHED_USER 및 수동 관계/이미 장부 기록/점유 관계 보호, RESERVATION_ONLY≠결제 확정, unknown 날짜 생성 금지.
- 비인증 GET 보호, 확정 POST의 CSRF/request ID/revision/digest 회귀 유지.
- 모바일/데스크탑·다크/라이트·200% 확대·오류/로딩/빈 데이터/새로고침 동작 E2E.
- 운영 보존: 데이터 내용·스키마 해시, 단일 리스너, health/ready 200, 비인증 보호 API 401.
- **예비 성능 목표:** warm summary p95 ≤150ms, first-page events p95 ≤300ms, first-page payload ≤150KB. baseline 미실측이므로 목표 달성 여부는 구현 후 실제 기록으로 판단한다.

관련 재사용 테스트: webapp/tests/test_ota_payment_review.py, test_ota_payment_review_browser.py, test_ota_snapshot_service.py, test_ota_candidate_snapshot_read.py, test_ota_lazy_expense_review.py, test_ota_preview_race_browser.py, test_cleanup_ota_contract.py. 파일명만으로 테스트 커버리지가 충분하다고 가정하지 않는다.

## 9. 구현 순서 · 상태 체크

1. RF-001/기준선: 읽기 전용 집계·요청/갱신 비용 분리 측정.
2. 큐 분류 + summary projection + API + cursor pagination, 기존 route 호환.
3. UI 변경: 요약 통계, 기본 20건, 인라인 상세, 같은 페이지 카드 후보.
4. 예약번호 기반 안전한 그룹 projection.
5. 높은 빈도 보류 사유별 기존 solver 보강(별도 PR, 금융 회귀 필수).
6. DB/증분 계산 최적화(성능 근거가 있을 때만).
7. 표적/브라우저/성능/보호 테스트 → 병합 → SHA 고정 배포 → 실제 화면 수락.

**완료 게이트:** 전체 이벤트를 덜 보내는 것과 실제 보류를 안전하게 덜 발생시키는 것 **둘 다** 실측으로 확인. 항목을 삭제·노후 종료·숨김만으로 ‘자동 해결’이라고 보고하지 않는다.
