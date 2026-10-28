# OTA 검토 대기열·그룹화·페이지네이션·대사 성능 구현 명세

- 작성: 2026-10-27
- 상태: **IMPLEMENTED / DEPLOYED / RUNTIME_ACCEPTED（426세대）** — summary/페이지/인라인 상세·검증된 예약 그룹·조회 검사 제한을 배포하고 예비 API 성능 목표와 실제6경로를 수락했다. 미연결의 외부 결제 근거·실기기 전 화면 수락은 남아 있으며 그룹 축소를 보류 해결로 계산하지 않는다. 최신 SHA/검증/미결은 [현재 상태](../session_handoff.md)와 [운영 기록](../operations.md)이 우선한다. 아래 source baseline은 조사 당시 이력이다.
- 연결: [전면 리팩토링 마스터](refactor-master-20261027.md), [OTA 금융/정본 정책](ota.md), [운영 기록](../operations.md)
- 목적: 접힘/지연 조회는 이미 있는 기능이다. 이번 범위는 **과도한 미결 수 자체를 줄이고, 서버가 필요한 목록만 전달하며, 동일 예약의 다수 이벤트를 한 카드로 묶는 것**이다.

## 2026-10-28 최종 운영 수락

Board `9d5ddd5`의426세대 ready/fresh에서3,799사건→3,222그룹(577개/15.19% 표시 감소), 기존3,794건 금융 판정 보존을 확인했다. 최종 worker261.89초(기존396.43초 대비33.9% 감소), 인증 왕복20회 summary p95 134.04ms/842B·groups157.10ms/22,318B·events139.32ms/7,656B로 예비 목표를 충족했다. 첫/다음20그룹 중복0, 숲나들e4경로·Trip 그룹·Toyoko의6개 실제 화면과 테마1개, 화면 후 보호13표 불변을 수락했다. 이는 기장/환급/여행 저장이나 실기기·200% 전 화면 수락을 뜻하지 않는다. 실제 배포/검사와 미연결 외부 근거는 [운영 기록](../operations.md)에 기록했다. 아래 배포 전/미구현 표현은 조사 당시 이력이다.

## 2026-10-28 후속 구현과 배포 전 검증

`reservation_only`를 정상 근거 enum에 포함해 예약 관측의 잘못된 EVIDENCE_UNKNOWN 경고를 제거했다. 예약전용은 결제 완료가 아니다. 인증된 공급자 메일의 명시 예약 binding을 그룹화한 로컬 실제 입력은 3,794사건→3,218그룹(576개 감소)이며 기존 비숲나들e 금융 이벤트 필드는 동일하다. 실제 worker 세대의 수치는 배포 후 운영 기록에 남긴다.

프로파일에서 공급자 alias 배열 생성/정렬이 반복되는 것을 확인해 reconcile run 안에서만 descriptor 결과를 캐시한다. 중첩 scope는 재사용하고 종료/예외 시 해제하며 정책 객체 교체 때 무효화한다. 수동 고정/빈 입력 조기 반환은 정책 로드에 의존하지 않는다. 같은 실제 동결 입력의 30개 eligible 탐색+60개 후보 검색은 cProfile 기준 63.1642초→22.1710초, 후보·거부·카운트 전체가 동일했다. 이는 표본 계측이며 전체 worker 시간이나 API p95로 대신하지 않는다.

금융/환불/수동/권한/queue/snapshot 인접409 passed와 별도 PG·수집기·브라우저144 passed/4 subtests를 확인했다. 마지막 국소 보완 검사는 현재 상태에 기록한다. 실제 ready 세대·화면·summary/page p95·보호표는 정상 병합 및 고정 배포 후 검증한다.

후속 운영에서 summary/page/detail GET마다 worker를 깨워 478MB 원본 지문과 카드 원장을 반복 읽는 경로를 확인했다. 일반 읽기는 기존60초 검사 주기를 공유하고 최초 미검사 상태만 즉시 깨운다. 계산 중 읽기는 추가 검사를 예약하지 않는다. 명시 `request_check()`와 쓰기 직전 입력 키 검증은 즉시 실행을 유지한다. 조회 burst·주기 경계·명시 검사·세대 변경·snapshot/action/page/detail 보호89 passed로 확인했다.

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

## 10. 2026-10-28 source baseline (문서 조사만)

- 확인 범위: `webapp/ota_payment_review.py`의 `CoreOtaPaymentBackend.snapshot_from` (943-999), `snapshot_view` (1001-1003), `public_snapshot` (186-244), `dispatch` (2072-2125); `webapp/ota_snapshot.py`의 worker `check_now` (151-203), `view` (213-236), `held` (243-251), `action_context` (270-289); host caller `webapp/card_flow.py::dispatch` (1995-2023). 이 범위에서 `/api/imports/ota`는 현재 공개 snapshot GET이고 `/api/imports/ota/cards/<event_id>`는 인증된 개별 카드 후보 GET이다. 독립 `/summary`, `/events`, cursor pagination route는 `owns_route` (ota_payment_review.py:289-290)와 dispatch의 GET 분기 (2092-2125)에 없다. UI에 기존 `group_count`/`ota_group_ids`가 나타나지만 이는 matcher 결과의 카드 배정 그룹이지 queue 예약 그룹 API가 아니다. 따라서 본 명세의 summary/events/cursor projection은 아직 구현됐다고 볼 근거가 없다.
- worker가 input key를 확인하고 reconcile 함수는 worker thread에서만 호출하며, 성공 시 generation을 증가시켜 current에 publish한다 (ota_snapshot.py:109-113,151-203). 실패는 error를 기록하고 기존 last-good current를 보존한다. request `view()`는 계산하지 않고 loading/error/refreshing/ready와 stale/freshness/generation 메타데이터를 돌려준다 (213-236); action context는 in-memory data가 완전하고 fresh할 때만 준비된다 (270-289). 따라서 queue 분류는 이벤트 배열과 freshness envelope를 함께 받아야 하며 loading/error/stale/refreshing을 0건 완료로 집계하면 안 된다. `snapshot_from`는 결과 `status`, `reason`, `reservation_link`, `evidence_changed/missing`, candidate search 등을 합쳐 hold 이벤트를 만들고, 특히 `MATCHED_USER`의 증거 변경/누락과 `RESERVATION_ONLY`를 분리한다 (ota_payment_review.py:955-999). 공개 event allowlist는 `_EVENT_FIELDS` (27-40), 예약 관계는 상태 `INFERRED/USER_CONFIRMED/NEEDS_REVIEW/STALE`, amount 상태 `MATCH/UNKNOWN/MISMATCH` 및 typed fields만 허용하며 `payment_verified`를 항상 false로 고정한다 (71-97). public card rows는 별도 `_CARD_FIELDS`와 sanitization/selection-disable 규칙을 거친다 (41-56,186-244). raw source digest/ids는 public event allowlist에 포함되지 않아 현 projection만으로 source-lineage 기반 예약 그룹을 재구성할 수 없다.
- `group_count`, `ota_group_ids`, `card_group_ids`, `allocation_basis`는 allowlist에 있으나 payment solver의 allocation evidence다 (ota_payment_review.py:27-40; `app/ota_payments.py:1431-1456,1491-1603`). 여기에는 queue 예약 그룹용 검증된 예약번호 정규화·중복 충돌 판정 계약이 없으므로 이를 queue group key로 재사용하지 않는다. 추후 pure projection은 (a) 검증된 reservation identity/lineage 입력이 명시적으로 제공될 때만 그룹화하고, otherwise 각 event를 독립 단위로 세며, (b) event count와 group count를 따로 내고, (c) `RESERVATION_ONLY`는 예약 관계만으로 payment complete로 올리지 않고, (d) manual/exact link, original charge/refund/cancellation 보호 및 `evidence_changed/missing`을 보존하고, (e) unknown status/reason/evidence는 완료로 분류하지 않아야 한다. 현 source가 허용하는 reservation link status만으로는 결제 확정이 증명되지 않는다.
- 새 route/UI 연결 전 최소 후보는 side-effect 없는 `classify_event`와 `summarize_queue(events, freshness)` 순수 함수다. 입력은 public event allowlist shape와 worker freshness envelope; 출력은 분류별 event count, 검증 가능한 경우에만 group count, warning count 및 상태 메타데이터다. solver, store/DB, 카드 후보 materialization, 수동 승인/write authority에는 연결하지 않는다. `public_snapshot(include_cards=False)`가 기본 snapshot에서 cards를 비우고, `/cards/<id>` GET만 `cards_for_event`를 불러오므로 lazy candidate boundary는 이미 존재한다 (ota_payment_review.py:186-190,205-234,2092-2108; backend 1005-1028). Host GET은 기존 host access decision 뒤 card_flow를 거치며 (ledger_board.py:3972-4044), backend는 `raw is None`일 때 read-only factory를 선택한다 (card_flow.py:1995-2023; ota_payment_review.py:300-305). 기존 GET/auth와 lazy endpoint 계약을 유지한다. POST CSRF 및 action 경로는 별도 dispatch 분기 (2127-2177)이며 이 조사 범위의 변경 대상이 아니다.
- synthetic differential cases 및 기존 target 위치: `webapp/tests/test_ota_payment_review.py`의 snapshot projection/allowlist/lazy card tests (375-405,705-758,815-933,1357-1360,1566-1675); `webapp/tests/test_ota_snapshot_service.py`의 changed input, last-good after failure, stale, persisted snapshot tests (56-165); `webapp/tests/test_ota_payment_review_browser.py`의 group display/disabled and lazy-fetch examples (138-199,390-416); `tests/test_toyoko_reconciliation.py` reservation-only tests (file-level, source references also in `app/ota_payments.py:1663-1673`). New synthetic cases: known matched-auto/user with unchanged evidence; manual link with changed/missing evidence; hold conflict and unknown status/reason; reservation-only alone and alongside charge/refund/cancellation events; duplicate/missing/unvalidated reservation ref and absent lineage (must not merge); solver payment group IDs that differ from reservation group; zero events under ready vs loading/error/stale/refreshing; event count distinct from validated group count. Differentially compare old per-event status/reason and protected fields; no runtime/performance baseline numbers were collected here.
- 조사 한계: source review만으로 실제 scheduler/runtime 활성 상태, 현재 고객 데이터 분포, snapshot GET bytes/latency, eventual UI acceptance, 또는 예약번호의 전역 uniqueness를 판정하지 않는다. Supervisor의 별도 GET 집계 계측 전 성능 수치는 미확인이다. 이 절은 queue completion, 성능 개선, 실자료 수락 또는 전체 의존성 완료를 주장하지 않는다.

## 11. Pure projection 후속 source audit (2026-10-28, 구현 전)

- 이미 존재하는 `app/ota_queue_projection.py`를 재구현하지 않는다. `classify_event`/`summarize_queue`는 finite reason codes, unknown conservatism, freshness gate를 제공한다 (181-265). completion은 ready/fresh/enabled snapshot, known matched status/reason/evidence 및 개별 결제 조건을 요구하고 warning, inferred/group allocation, duplicate/missing identity면 completed가 아니다 (92-178). `coverage`는 필수 `canonical|public_subset`; summary는 event 수와 singleton fallback group 수를 분리하고, subset을 authoritative로 표시하지 않는다 (189-265). 예약 그룹 계약이 없어서 identity별 singleton fallback은 현재 의도된 안전 동작이다.
- 실제 연결 후보는 `webapp/ota_payment_review.py::reconcile_for` (1288-1328; worker callback은 `snapshot_service` 1485-1494)다. 여기서 이미 full `data.events`와 solver `results`를 확보한 채 `snapshot_from(data, include_cards=False)`로 public holds snapshot을 만든다. 해당 경계에서 canonical queue 분류는 **full solver results와 canonical source event를 ID로 결합한 뒤** 한 번 계산해 reconciled payload에 저장하는 형태가 가능해 보인다. 단, public `snapshot_from` 반환은 holds subset만 포함한다 (943-999); 이를 canonical 입력으로 넘기면 안 된다. 결과의 `reason/status/evidence`와 원본 event의 `evidence_changed/missing`을 명시적으로 결합하고, 현재 `_EVENT_FIELDS` sanitizer (27-40,186-204)를 통해 공개 허용된 event shape로 제한한 뒤 계산해야 한다. digest/source ids 등 내부 source lineage는 현재 event allowlist에 없으므로 queue group key로 노출하거나 임의 합성하지 않는다. 구체적인 precompute 위치/형태는 데이터 의미 및 callback 시그니처를 구현 전 확인할 미결 계약이다.
- Freshness는 generation 증가와 성공 시 current publish가 `_reconcile_fn` 반환 뒤 worker에서 이뤄진다 (ota_snapshot.py:177-203); 실패 시 prior current는 유지되고 error가 기록된다 (179-187). 따라서 precomputed canonical summary/page index는 같은 reconcile payload에 넣어야 last-good과 함께 원자적으로 세대 교체된다. `view()`는 request마다 계산 없이 current 및 freshness envelope를 반환한다 (213-236). GET summary는 오직 저장된 canonical summary를 읽어야 하며 모든 GET에서 `summarize_queue`/전수 집계 금지. 현재 persistence allowlist는 public/authority/results/links (ota_snapshot.py:294-322)이므로 새 precomputed 값의 disk persistence/restore 및 복원 snapshot freshness 의미를 결정해야 한다. persisted `data=None`은 action context에 불충분하다 (270-289); 공개 요약/페이지가 복원 public snapshot만으로 안전하게 제공 가능한지도 명시할 것.
- Page source는 canonical queue rows/index와 같은 generation이어야 한다. 최소 설계 후보는 canonical result와 allowlisted public event를 결합해 worker에서 안정 정렬된 compact page rows/index를 계산하고 저장, summary GET은 저장 summary만 반환, page GET은 그 저장 rows에서 한 페이지를 slice하는 것이다. 기존 `public`/holds는 진단·검토 UI용 projection이므로 canonical list와 혼용하지 않는다. cursor token은 적어도 generation + 정규화 filter + sort position(및 page size 정책)을 bind하고, malformed/다른 filter/세대 불일치 때의 400/409 계약, token signing/opacity, keyset tie-breaker, retention 및 persisted restart 시 cursor 유효기간은 미정이다. 현재 host `dispatch`는 `/api/imports/ota`와 cards/diagnostics만 읽기 분기에서 수용하며 신규 summary/page path는 404다 (ota_payment_review.py:2072-2125). 공개 snapshot GET과 같은 host auth gate를 유지하고, 기존 per-event cards lazy GET/auth를 그대로 둔다 (2092-2108; card_flow.py:1995-2023). POST CSRF, user/session, preview digest/revision, request-id 경계는 유지하며 읽기 paging이 action authority를 만들지 않는다 (dispatch:2127-2177).
- 다음 구현자의 최소 파일 범위는 `webapp/ota_payment_review.py`와 `webapp/ota_snapshot.py`의 worker reconcile payload/persistence/read-only GET 연결로 제한하는 안이다. `app/ota_queue_projection.py`, solver, DB schema/write policy, cards endpoint 및 UI는 수정 후보에 넣지 않는다. 다만 worker payload/persistence 실제 선택은 아래 미결 계약 해소 후 정한다. 필요한 synthetic 수락 검사: canonical full results와 holds subset이 다른 경우 summary/list는 full canonical counts/items, 기존 GET은 기존 holds 유지; source-event ID 중복·누락/unknown status/evidence는 완료·합치기 금지; reservation-only 및 refund/cancellation/manual/exact protections 유지; same generation에서 안정 cursor 페이지 연속·중복/누락 없음; generation 변경 및 filter mismatch cursor 거절(409/정의된 4xx); loading/error/stale/refreshing/disabled는 완료 건수로 나타나지 않음; summary/page GET은 snapshot read만 하고 classifier/summarizer 재호출 0회; per-event cards는 계속 lazy; POST auth/CSRF 경계 동일; disk restore와 failed refresh는 generation-consistent last-good summary/page를 보임. 기존 projection 단위 tests는 `tests/test_ota_queue_projection.py` (1-265); snapshot worker tests는 `webapp/tests/test_ota_snapshot_service.py` (56-165); route/sanitization/lazy/action tests는 `webapp/tests/test_ota_payment_review.py` (375-405,508-528,705-758,1357-1360,1566-1675) 및 browser lazy tests `webapp/tests/test_ota_payment_review_browser.py` (390-416)에서 보강 후보를 찾는다. 실행은 하지 않았다.
- 미결 구현 계약: full canonical event/result rows의 안전한 DTO shape와 join cardinality; summary/page payload을 persisted snapshot에 넣을지와 restart freshness/last-good 규칙; 허용 filter와 deterministic order; cursor opaque/signature 및 409 조건; public allowlist와 PII-minimal page fields; disabled/feature-flag 및 no-current 응답 envelope; summary warning/group count의 canonical 의미(현 pure 모듈은 singleton fallback만); request auth가 host에서 보장되는 exact path; page GET의 성능 수용 기준. 이 source audit만으로 route 연결, 성능 개선, 전체 기능 완료를 선언하지 않는다.

## 12. Queue API 후속 UI source audit (2026-10-28, UI 미연결)

- 현재 UI owner는 `webapp/ota_payment_review.py::render_import_section`의 HTML/CSS/JS (1711-2069)이며 `/import` 삽입은 `webapp/card_flow.py` OTA section renderer/caller source boundary다. 현재 `<details id="ota-review">` 접힘 root와 `#ota-events` renderer는 기존 `/api/imports/ota` 전체 holds GET을 render하고 (1810-1843,2033-2057), event diagnostics와 cards는 각각 펼칠 때 `/diagnostics/<id>`와 `/cards/<id>`를 lazy GET한다 (1874-1880,1943-1969). action preview/confirm, reservation preview/confirm, group confirm, proposal controls는 같은 renderer와 handlers 안에 있다 (1844-2015). root가 열려 있고 document visible일 때만 polling하며 닫으면 timer를 지운다 (2017-2067); 진행 중 선택을 polling render가 덮지 않도록 보류하는 보호도 있다 (2020-2057). 이 UX/경계 재사용이 가장 작은 UI 변경 지점이다.
- 현재 server `GET /api/imports/ota/summary`는 저장된 `queue_summary`를 sanitizer로 읽고, `/events`는 worker index의 page response를 내며 둘 다 `_request_user`를 요구한다 (ota_payment_review.py:2285-2404,2462-2498). event page limit 기본 20, 상한 100이며 queue/provider/q/cursor strict query parse와 `SNAPSHOT_NOT_READY`/cursor 409 응답이 이미 있다 (2165-2243,2463-2485). index는 queue/provider 정렬 위치에서 보통 page-size slice, q가 있으면 선택된 positions 선형 scan(O(n))이고 cursor는 generation/filter/limit/nonce를 HMAC bind하며 malformed/restart invalid cursor는 400, generation/filter 변경은 409다 (`app/ota_queue_paging.py:1-10,221-254,287-341`). UI는 기존 API를 새로 만들거나 full holds를 fetch 후 slice하지 말고 summary+현재 page만 받아야 한다.
- 중요 기능 gap: `/events` item sanitizer는 `ota_event_id, provider, booking_ref, event_type, paid_on, item, currency, amount, status`와 제한 merchant search value만 제공한다 (`webapp/ota_payment_review.py:1417-1436`; serializer `app/ota_queue_paging.py:257-284,332-341`). 기존 hold card는 `reason`, evidence changed/missing, service period/conflict, refund/reservation states/link, warning, candidate counts, payment/allocation and group evidence 등으로 근거·진단·manual/reservation/group UI를 만들고 `render_import_section` / `render`에서 직접 소비한다 (ota_payment_review.py:1813-1842). 요약 page DTO만으로 이 기존 form을 재사용할 수 없다. 기존 `/diagnostics/<id>`는 좁은 diagnostic projection이고 `/cards/<id>`는 후보 카드 rows이지 complete event DTO가 아니므로, 현재 source에는 page item click 후 기존 holds UI 수준의 단일-event detail을 가져오는 GET이 없다 (2407-2440,2499-2513; `_EVENT_FIELDS` 27-40). page-click 상세와 기존 actions를 살리려면 별도 `GET /api/imports/ota/events/<event_id>?generation=...` 최소계약이 필요하다: 같은 generation의 canonical event를 `_EVENT_FIELDS` 기반 sanitizer로 반환하되 source digest/raw mail/full transaction data는 금지, cards/candidate rows는 포함하지 않고 기존 `/cards/<id>` lazy fetch로 남김, authenticated GET, generation mismatch/stale/not-ready는 409, absent/nonqueue item은 404, response에는 event_id+generation 포함. detail lookup용 current generation index/storage와 missing current/restart behavior는 구현 전 확인할 계약이다. 전체 holds GET을 상세 대용으로 부르거나 client-side slicing은 금지한다.
- 권장 최소 구현 소유 범위는 `render_import_section` HTML/CSS/JS 한 파일(`webapp/ota_payment_review.py`)과 그 파일을 다루는 기존 UI test 파일뿐이다. 별도 detail route가 필요하다고 결정되면 server handler도 같은 파일에 얇게 추가하되 `ota_snapshot.py`/solver/index를 건드리지 않고 이미 준비된 page/detail backing boundary를 확인한다. UI flow: details open 시 summary GET + page 1 GET; queue/provider/q 변경은 debounce 후 cursor 초기화 및 page 1; next/previous는 opaque cursor만 전달; generation 변경/409는 cursor를 비우고 summary 및 page 1 재요청; summary loading/error/stale/refreshing/rechecking은 count를 authoritative complete로 표시하지 않는다. page rows에서 detail을 열 때만 같은 화면 inline detail GET, 그 뒤 기존 cards lazy endpoint와 existing POST action handlers를 쓴다. 닫힘 시 모든 poll/debounce 중지, 진행 중 unsaved selection 보호 유지. 기본 page 20개로 rendered event DOM 상한을 유지하며 후보 카드 전체 preload 금지.
- 화면은 기존 `--shell-*`/`--ota-*` token CSS, 단일 수동 해/초승달 shell theme을 그대로 사용하고 새 theme control/engine을 만들지 않는다 (ota_payment_review.py:1761-1792). mobile layout의 기존 single-column/breakpoint를 이어가고 200% zoom에서 filter/buttons/detail/forms의 reflow 및 keyboard/focus/empty/loading/error/409 reset 상태를 실제 브라우저에서 확인해야 한다. 소스만으로 이 수락은 확인 불가다.
- UI 수락 후보: `webapp/tests/test_ota_payment_review_browser.py`의 current render/lazy/interaction coverage (file references 41-416); route/paging fixtures `webapp/tests/test_ota_queue_pages.py` (121-254); summary freshness/read-only route `webapp/tests/test_ota_queue_summary.py` (194-345); existing card/detail lazy boundary `webapp/tests/test_ota_candidate_snapshot_read.py` (1-51). synthetic cases include exactly 20 DOM rows and next-page continuation; debounced q/provider changes discard old cursor; stale cursor 409 resets page; no full `/api/imports/ota` request from new queue screen; missing page fields load detail lazily; detail 409/404, card lazy GET and existing preview/confirm/session/CSRF behaviors unchanged; closing panel cancels polling; summary non-ready labels; mobile/200% browser review. Tests/browser/implementation were not run. Current evidence covers API and old UI separately; it does not show new summary/page UI wired, new detail GET present, 20 DOM cap, or performance/acceptance completion.

### Supervisor 기준선·최소 구현 경계

- 별도 인증 GET8회 측정은 공개목록1,072건·899,499B·같은세대1·cards map0, p50 205ms/표본p95 1,750ms였다. 측정 중 refreshing/stale이므로 ready/warm 성능이나 전체 정본 분포·server-only p95가 아니다. 알려진 status 집계/경고 개수와 bytes/time만 로컬 근거에 보존했고 고객 원문은 기록하지 않았다.
- `snapshot_from`의 공개목록은 holds/검토 subset이므로 전체 queue summary를 여기서 재구성하면 정상 matched 이벤트가 누락된다. 첫 구현은 route/UI와 연결하지 않는 순수 분류·summary다. 단일 이벤트는 allowlist와 호환되는 합쳐진 source/result shape를 받고, summary caller는 `canonical` 또는 `public_subset` coverage를 명시한다. subset·stale·loading/error/refreshing 통계는 authoritative 완료/전체 건수로 표시하지 않는다.
- 아직 검증된 예약 identity/lineage 그룹 입력 계약이 없으므로 예약번호·결제 solver group으로 합치지 않는다. 첫 구현의 group units는 이벤트별 singleton fallback임을 명시하고 event/group 단위를 별도로 센다. duplicate/missing identity와 unknown 상태/사유/근거를 경고 없이 completed로 올리지 않는다. 큐 completed는 대사 검토 범위이며 실제 기장·환급·여행 배정 완료를 뜻하지 않는다.
