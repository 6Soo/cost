# COST 여행 탭의 항공권 예약 조회 및 출발 여행 귀속 명세 v1.0

- 작성일: 2026-10-28
- 문서 상태: **SPEC_ONLY / 구현·테스트·배포 미실행**
- 대상 화면: 실제 여행 탭 /board?tab=<COST trip tab ID>
- 목적: 기존 여행 탭의 수입·지출은 그대로 두고, 해당 여행에 귀속된 항공권 예약/탑승객/왕복 여정을 추가 조회한다.
- 관련 정책: [현재 상태](../session_handoff.md), [여행·금융](finance.md), [항공권 UI](ui.md), [참가자](participants.md), [전면 리팩토링](refactor-master-20261027.md).

## 1. 제품 결정

**2026-10-28 사용자 신규 결정**

1. 항공권 예약은 가급적 실제 여행 하나에 귀속한다. 이미 회계분류에서 사용되는 검증된 예약/카드 → 여행 귀속이 있다면 이를 먼저 재사용한다.
2. 한 승객이 여러 여행을 연속 이용해 귀국일이 첫 번째 여행 종료일을 넘는 경우에도 **예약 전체를 첫 출발 여행에 귀속**한다. 귀국일/예약 메일 수신일/결제일로 여행을 재선택하지 않는다.
3. 여행 탭에서 **수입 + 지출 + 항공권 예약**을 함께 확인한다. 항공권은 별도 정보 영역이며 수입·지출 합계나 비용 장부의 새 행이 아니다.
4. 예약 1건의 편도·왕복·경유 구간과 승객이 여러 명이더라도 해당 예약의 귀속 여행은 1개다. 다른 여행에 구간을 쪼개 중복 표시하지 않는다.
5. 검증된 사용자 직접 예약 귀속, 카드/OTA 분류의 권위, 기존 확정 관계를 **읽기 전용 재사용**하며, 새 조회 기능으로 카드 금액·회계분류·여행 배정·Google 장부·참가자 확정을 수정하지 않는다.
6. 출발일 누락·여정 충돌·다중 후보 등 근거가 불충분한 경우에는 추론/확정/미해결을 구분한다. 존재하지 않는 여행을 만들거나 사용자 확정값을 덮지 않는다.

## 2. 대표 시나리오와 정확한 기준일

### A. 보통 왕복
- 실제 여행 A: 2026-11-07 ~ 2026-11-08
- 예약 출국: 11/07, 귀국: 11/08 → **여행 A에 예약 1건**.
- 가는편과 오는편은 여행 A 안의 동일한 상세 카드에서 확인.

### B. 두 여행 연속 참가 (반드시 통과)
- 여행 A: 2026-11-07 ~ 2026-11-08
- 여행 B: 2026-11-09 ~ 2026-11-10
- 한 승객의 동일 예약: 11/07 한국 출발 → 11/11 귀국
- **기대:** 여행 A의 항공권 예약 목록 1건, B에는 중복 없음. 귀국일 11/11은 A 종료일 밖이더라도 A 귀속 유지.
- 동일 승객이 여행 B를 위해 **별도 예약번호** 항공권을 갖는다면 별도 예약으로 각각 평가한다.

### C. 경유·다구간
- 최초 실제 가는편의 첫 segment 출발 현지 일자를 anchor_departure_date로 쓴다.
- 가는편/오는편 원문이 순서대로 기록되지 않은 경우 parser가 제공하는 leg label·날짜·공항 연쇄를 검증한다.
- 예약 전체의 귀속은 출발 여행 하나다. 뒤 구간이 다른 여행 날짜에 있어도 별도 여행에 자동 복제하지 않는다.
- 여러 승객의 예약에 서로 다른 구간이 존재하는 경우엔 증빙이 정확히 공통 예약임을 확인하고, 구간/승객별 여정 충돌이 확인되면 원본 검증 필요로 분리한다.

### D. 동률/경계
- 동일 출발일을 포함한 여행이 여러 개면 기존 확정 배정, 검증 카드/OTA 예약 연결, 여행 시작일 일치, 목적지/노선 증빙으로 구분한다.
- A 종료일과 B 시작일이 동일한 날이고 명확히 B의 출국편이면 B가 우선한다. 근거 없이 숫자상 앞선 여행을 고르지 않는다.
- 원본 Google 여행 기간에 종료일이 없다면 [finance.md](finance.md)의 검증된 연속기간 규칙을 그대로 사용한다.
- 여행 시작 전날 항공편이라도 기존 회계 귀속에 검증된 대응 예약이 있으면 해당 여행으로 귀속한다. 별도의 임의 ±N일 편의 규칙은 만들지 않는다.
- 여행 권위가 없거나 후보가 정말 동률이면 UNRESOLVED/CONFLICT로 표시. 자료가 확인된 예약 자체는 검색 가능한 미귀속 상태로 남긴다.

### E. 취소·변경
- 변경/취소 메일도 같은 공급자+예약번호의 source lineage로 묶고 원본 event ID/digest를 보존한다.
- 취소·환불과 실제 결제 상태는 별도. 취소된 예약은 기본 탑승 예정 수에 포함하지 않고 이력 탭에서 확인 가능.
- 최초 출발일이 변경되어 다른 여행을 가리키게 되면, 사용자 직접 확정 귀속을 조용히 덮지 않고 CONFLICT를 표시한다.

## 3. 현재 코드에서 확인한 재사용 지점 및 한계

| 위치 | 현재 역할 | 구현 계약 |
| --- | --- | --- |
| webapp/ledger_design.py: page, rows_region, _selected_rows | 실제 trip tab_id의 수입·지출 조회/렌더 | 기존 재무 합계, Google 지출 복사, 수입/지출 편집을 바꾸지 않고 세 번째 예약 영역 추가 |
| webapp/ledger_design.py: _is_trip_tab, _selected_trip | 실제 여행과 미분류/환불/분기 탭 구별 | 항공권 영역은 실제 권한 있는 여행에만 표시 |
| webapp/ota_payment_review.py: passenger_index_for / _passenger_index | 인증된 항공 메일 예약번호→승객, legs, source digests, 충돌/취소 상태 | worker가 검증한 인덱스를 읽는다. 페이지 열 때마다 전체 메일 파싱/대사 실행 금지 |
| app/flight_evidence.py: collect_flight_evidence, merge_booking_evidence | 공급자+예약번호로 메일 병합하고 날짜/구간/승객 추출 | 예약일 reserved_on과 실제 출발일을 구분. 최신 여정·원본 변경 계보 보존 |
| webapp/card_flow.py: _booking_trip_rules, _booking_trip_assignments, booking_trip, _booking_period_assignments | 사용자 예약 배정, 기존 카드/OTA 여행 귀속 | 검증된 공급자+booking_ref 연결이 있을 때만 항공 예약에 재사용. 카드의 가맹점명/동액만으로 PNR 추정 금지 |
| app/guide_airfare.py, webapp/guide_airfare_review.py | **가이드 항공료** 특수 귀속 및 예약 authority bridge | 가이드 전용 로직이 모든 고객 예약을 커버한다고 오해하지 않는다. 직접 연결이 검증될 때에만 보조 근거 |
| webapp/flight_passenger_page.py: _assignments_for | 예약 참가자 연결의 tour_id, evidence revision | 예약 시스템 tour_id는 COST 여행 tab_id가 아니다. 검증된 bridge 없이 혼용 금지 |
| ledger/data/trip_flight_links.json | 예약번호 보정/링크 자료 | URL·corrected_no 구조로 확인됐으며 여행 귀속 테이블이 아님 |

**지원 소스 범위에 대한 사실:** 현재 _passenger_index는 provider == trip (인증 Trip.com 항공 메일) 경로를 우선 색인한다. 사용자가 말한 ‘모든 항공권’은 제품 목표이지, 현재 코드가 전 공급자 예약을 이미 수집한다는 의미는 아니다. 단계 TF-001에서 다른 공급자 수집 경로와 실제 누락률을 확인하고 필요한 source adapter를 추가한다. 원본에 없는 항공권을 생성해서 숫자를 맞추지 않는다.

## 4. 제안 아키텍처 (기존 Python/SQLite/worker 유지)

1. app/trip_flight_assignment.py
   - pure resolver: 출발 기준일, 예약 키, 후보 여행, 사용자/회계 권위에 따른 결정; reason code/신뢰상태 반환.
   - DB, HTML, 원본 메일 재수집, 금융 거래 쓰기에 의존하지 않음.
2. webapp/trip_flight_read.py
   - 현재 snapshot/flight index의 read-only projection + 여행 authority와 기존 booking/card assignment 검증 조합.
   - source generation, rules revision, trip authority revision 기준 캐시 무효화.
   - 요청당 전체 카드 테이블 N+1 query 금지. 필요시 검증된 연결 맵을 한 번에 구성.
3. webapp/trip_flight_ui.py
   - 공통 design tokens, ui_icons, HTML escape, 카드/배지/빈 화면/오류/상세 그리기.
   - 금전/여행 귀속 결정 로직을 이 파일에서 새로 구현하지 않음.
4. webapp/ledger_design.py
   - 실제 여행 탭에 항공권 영역만 합성. 기존 rows_region 및 live-refresh 구조는 유지.

**영속 테이블을 새로 만들지 않는 1차 읽기 전용 구현**을 우선한다. 후속 사용자가 항공권 귀속을 직접 바꾸는 쓰기 UX를 승인하면 그때 기존 권한·revision·감사 write path를 사용하고 새 영속 스키마 필요성을 따로 검토한다.

## 5. 귀속 결정 우선순위

1. USER_CONFIRMED: 실제 공급자+예약번호와 함께 저장된 명시적 예약↔여행 결정이 있고 여행이 유효.
2. AUTHORITY_VERIFIED: 검증된 예약↔카드 또는 예약↔OTA 원본 relation에서 하나의 기존 회계 여행 tab_id를 얻은 경우. 카드 금액 근접성만으로 PNR에 연결 금지. 여러 카드가 서로 다른 여행에 귀속되면 CONFLICT.
3. VERIFIED_GUIDE_BRIDGE: 해당 예약이 가이드 항공료/예약 authority와 직접 일치하고 tour_id→COST tab_id 변환이 검증되는 경우에 한함.
4. AUTO_INFERRED: 첫 실제 출발일이 하나의 검증된 여행 기간에 포함되거나 더 강한 시작 여행/목적지 근거로 1개가 유일하게 결정된 경우.
5. UNRESOLVED / CONFLICT: 근거 누락, 모호성, 증빙 변경, 후보 0/다수.

**우선순위는 새 여행 분류를 돈 거래에 자동 저장한다는 뜻이 아니다.** 오직 항공권 예약 목록의 여행 projection이다. 명시적 사용자 결정과 계산된 첫 출발일이 다를 때 충돌 근거를 보이며, 변경 승인 없이 자동 overwrite하지 않는다.

### Projection DTO 예시 (모두 합성값)

~~~json
{
  "provider": "trip",
  "booking_key": "trip:SYNTHETIC-BOOKING",
  "booking_ref": "SYNTHETIC-BOOKING",
  "passengers": ["SAMPLE PASSENGER"],
  "outbound_departure_on": "2026-11-07",
  "legs": [
    {"label":"가는편","departure_on":"2026-11-07","segments":[{"departure_airport":"ICN","arrival_airport":"FUK","flight_number":"EX123","departure_time":"09:00","arrival_time":"10:30"}]},
    {"label":"오는편","departure_on":"2026-11-11","segments":[{"departure_airport":"FUK","arrival_airport":"ICN","flight_number":"EX124","departure_time":"18:00","arrival_time":"19:30"}]}
  ],
  "assigned_trip_tab_id": "synthetic-A",
  "assignment_status": "AUTO_INFERRED",
  "assignment_basis": "OUTBOUND_WITHIN_TRIP",
  "source_generation": "synthetic-generation",
  "evidence_status": "FRESH",
  "booking_status": "ACTIVE"
}
~~~

booking_key는 동일 번호를 쓰는 다른 공급자, 변경 메일, 반복 관측을 구분할 수 있게 provider·정규화 booking_ref·검증된 lineage를 사용한다. 유일 예약/실제 이름/실제 탑승 확정을 이 문서의 합성값으로 가정하지 않는다.

## 6. 화면 설계

### 6.1 여행 탭 UI

~~~text
[여행명 · 여행 기간]
[기존 수입 / 지출 / 차액 요약]
[수입 기록]            ← 현행 기능 유지
[지출 기록]            ← 현행 기능 유지
[항공권 예약 12건 · 검증된 탑승객 14명] [펼치기]
  11/07  ICN → FUK · 예약번호 요약 · 승객 2명
     [출발 여행 기준 자동 귀속] [예약 근거 확인]
  11/07  ICN → KIX · 예약번호 요약 · 승객 1명
     [기존 회계 귀속 확인]
  [이전] [다음] (기본 20개)
  선택한 예약 상세: 가는편/오는편/경유·승객·변경·취소 근거
~~~

- 항공권은 별도 section. Google 지출 복사·표 합계·회계 CSV/TSV에는 절대 포함하지 않는다.
- 최초 화면은 건수/상태만 출력하고, 상세 리스트는 **펼칠 때 지연 조회**한다. OTA 목록이 과다 렌더링됐던 문제를 반복하지 않음.
- 기본 목록 20건 / 서버 측 cursor pagination. 승객 다수는 ‘대표 이름 외 N명’이며 상세에만 전체 검증 이름.
- 예약번호·비행편·출발일·공항 경로·탑승객 수·귀속 근거와 취소/변경 상태를 우선 표시.
- 귀국일이 다른 여행의 기간에 있더라도 최초 출발 여행에만 예약을 기록한다. 상세에서 전체 왕복 일정 제공.
- 금융 kind=in/ex 검색과 항공권 검색을 분리하고, 조회 후 현재 여행 탭·필터 상태를 보존한다.
- 미분류/unclassified, refunds, 분기비용 등 비여행 탭에는 항공권 section을 자동 추가하지 않음.
- source stale, error, 0건을 별도 표시. 원본 조회 실패를 ‘예약 없음’으로 표시하지 않는다.
- 공통 ui_icons, theme tokens, 반응형 320~1440px, 200% zoom, keyboard 및 aria, escape/textContent를 재사용. 새 메뉴나 별도 디자인 시스템 생성 금지.

### 6.2 열람 권한

- owner 및 해당 여행 열람 권한이 있는 직원/담당자만 예약/승객 정보를 읽을 수 있다.
- 다른 tab_id를 URL에 넣어도 여행 권한 체크에서 거절.
- 기존 /api/flight-passengers/assign은 owner 전용 **쓰기 기능**이므로 이번 GET과 권한을 합치지 않는다.
- 예약 존재 ≠ 결제 완료 ≠ 실제 탑승 ≠ 보험 가입 ≠ 참가자 확정.

## 7. 조회 API(제안 경로)

GET /api/trips/{tab_id}/flight-bookings?limit=20&cursor=...&status=active

- 기존 Board 라우트의 URL·access control 구조 확인 후 최종 경로 선택.
- 실제 여행 tab_id/권한/보관 상태 검증을 먼저 수행.
- 응답: trip_tab_id, source_generation, generated_at, evidence_status, total_bookings, verified_passenger_count, items, next_cursor, has_conflicts.
- limit 기본 20, 최대 100. cursor는 세대·정렬키·필터와 결합. 갱신으로 cursor 세대가 달라진 경우 명확한 응답 후 첫 페이지 다시 조회.
- 정렬: 최초 출발일 → booking_key (고유 tie-break).
- 원문 메일, 개인 식별자의 불필요한 추가 항목, 전체 카드 번호, 외부 비밀값을 응답에 포함하지 않는다.
- 메일 파싱/전체 OTA 재대사는 GET에서 실행하지 않음. 기존 worker-published index만 읽기.
- 상세 GET은 같은 여행 영역의 expand/drawer에서 처리하고, 최초 화면에서 전체 여정·승객 리스트를 과도하게 로딩하지 않는다.

## 8. 테스트/수락 명세

### 8.1 핵심 합성 테스트

1. 여행 A(11/7~8), B(11/9~10), 출국 11/7·귀국 11/11 → A 1건, B 0건, 왕복 상세 모두 보존.
2. 별도 B 출국 11/9·귀국 11/13 → B 1건.
3. 동일 승객 두 여행 연속 참여해도 예약번호별 1건만 표시, 다른 여행에 복제 금지.
4. 경유 2~3개 segment, 원본 오는편/가는편 역순 → 최초 출발 leg 기준.
5. 예약일 5/4·카드 승인일 9/22·최초 출국 11/7 → 출발 여행에 귀속.
6. 사용자 확정 귀속과 출발 추론 충돌 → 확정 보존, 충돌 배지.
7. 다른 회계 카드 두 건이 같은 예약에 상충하는 trip_id → 자동 결정 안 함.
8. 같은 출발일을 포함하는 두 여행에서 출발 여행 시작일/목적지 검증; 여전히 동률이면 미해결.
9. 수동 여행 배정은 자동 재수집으로 덮어쓰지 않는다.
10. 취소/변경, stale/원본 누락, 날짜·예약번호·여정 충돌은 잘못된 탑승 예정 확정 없음.
11. 같은 공급자·예약번호 이메일 3개 → 예약 1건; 다른 공급자 같은 번호는 구분.
12. 여러 승객의 이름 중복/동명이인 → 이름만으로 승객 수를 거짓 합산하거나 다른 예약 병합 금지.
13. 공급자 미지원 → 실제 수집 범위와 누락 분리, 예약 창작 금지.

### 8.2 DB·HTTP·UI 회귀

- 현재 수입/지출 합계, 여행 필터, Google 복사 7열, 사용자 카드/장부 수정 동작 전후 동일.
- 조회만으로 카드 원장·board rows·flight_passenger_assignments·Google·참가자/보험 기록 변경 0.
- 비로그인·다른 여행 직원의 이름/예약 열람 차단; 인증 성공 owner/담당자.
- 스냅샷 generation 전환시 페이지 중복/누락 및 stale 처리 검증.
- 페이지 초기 열기에는 전체 항공권 메일 재파싱 또는 대사 실행 0회; 펼침시에만 목록 요청.
- 320/375/390/600/760/1024/1440px, 200% 줌, light/dark, 텍스트 긴 경우/접근성 스모크.
- 실제 운영 수락은 개인정보 비출력 read-only shadow로 연속여행, 귀국일 초과, 수동 우선, 취소, 데이터 커버리지 결과 대조.

### 8.3 구현 단계 / 에이전트 작업 ID

| 단계 | ID | 작업과 종료 게이트 |
| --- | --- | --- |
| 0 | TF-001 | 공급자별 항공 예약 coverage/기존 여행 연결 권위/날짜 누락/중복 실측(비식별·읽기 전용) |
| 1 | TF-002 | 기존 예약↔여행·회계 귀속 권위 맵/다중카드 충돌/수동 우선 테스트 |
| 2 | TF-003 | 최초 출발일과 연속 여행 단일 귀속 pure resolver + 합성 테스트 |
| 3 | TF-004 | 현재 worker index 기반 캐시/세대/읽기 전용 trip flight projection |
| 4 | TF-005 | 권한·pagination·요약/상세 API 및 동시 세대 테스트 |
| 5 | TF-006 | 여행 탭 세 번째 항공권 영역, 모바일/테마, 상세 drawer, 지연 로딩 |
| 6 | TF-007 | 실제 확인된 미지원 공급자만 필요한 파서 adapter 추가 |
| 7 | TF-008 | 국소/전체/브라우저/운영 read-only 수락 및 SHA 배포, 기존 DB 보호 해시 검사 |

## 9. 완료 판단과 금지 사항

- 기존 카드 분류, 항공권 참가자 확정, 지급/환불, Google 데이터, 여행 원본을 새 UI 때문에 재기장하거나 재귀속하지 않는다.
- 계약에서 알 수 없는 실제 승객/예약/여행 대응을 만들어 내지 않는다.
- 문서가 GitHub에 병합되어도 **기능 구현 완료가 아니다**.
- 후속 PR 보고: TF-ID, 변경 경로, 귀속 정책과 예외, 실제 테스트 명령/결과, 운영 SHA, 권한·개인정보 검증, 배포 여부.
- 상태: SPEC_ONLY → CODE_WRITTEN → TEST_PASSED → MERGED → DEPLOYED → REAL_DATA_ACCEPTED.
