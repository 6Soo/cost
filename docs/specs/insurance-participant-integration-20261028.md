# COST 보험가입 명단 수신·참가자 대조·여행 탭 조회 개선 명세

- 작성일: 2026-10-28
- 상태: **SPEC_ONLY / CODE_NOT_CHANGED / TEST_NOT_RUN / RUNTIME_DB_NOT_VERIFIED**
- 협업 원천: `6Soo/travel_ins/docs/insurance-cost-handoff-remediation-20261028.md`
- 관련 정본: [참가자 기능](participants.md), [여행별 항공권 명세](trip-flight-booking-overview-20261028.md), [시작 문서](../COST_V3_START_HERE.md), [현재 상태](../session_handoff.md), [전면 리팩토링](refactor-master-20261027.md)
- 신규 사용자 지시 범위: 기존 Travel INS 보험가입 명단 전달을 정확히 인수하고, 향후 여행 탭의 참가자 조회와 연결할 수 있도록 **실제 코드·미결·검증 조건**을 문서에 반영. 이번 작업은 명세만이며 실제 보험 가입/결제/운영 DB 업데이트를 승인한 것이 아님.

## 1. 현재 구현 상태: 무엇이 이미 동작하는가

### 1.1 통합 시스템의 실제 동작

~~~text
Travel INS 사진/사용자 최종 명단
  → 보험사 STAI/Travelover에서 가입 (업무별 명시적 승인/증빙)
  → confirmed final-roster.json (이름 전용·민감정보 분리)
  → travel_ins/tools/build_cost_roster.py
    ├ manifest.json (roster_id, revision, trip_ref, scope, sources)
    └ participants.json (name, nickname, english_name, row IDs)
  → travel_ins/tools/send_cost_roster.py
    ├ Git 무시 로컬 COST archive만 허용
    ├ 원본 SHA·계약·SQLite 백업·잠금 확인
    └ subprocess: cost/tools/ingest_participant_roster.py
       → app/participant_roster.py::register_roster
          → .local-archive/participant-rosters/participant.sqlite
              → webapp/participant_income_page.py::build_state
                  → app/participant_income.py::reconcile
                     (기존 Google 수입 행과 읽기 전용 대조)
~~~

**HTTP API/클라우드 push가 아니라 같은 운영 환경에서 다른 저장소의 Python CLI를 실행하는 로컬 파일 기반 전달이다.**

| 코드 소유자 | 함수/파일 | 확인된 기능 | 검증되지 않은 것 |
| --- | --- | --- | --- |
| Travel INS | `tools/send_cost_roster.py` | 인수 파일 검증, 개인정보 필드 차단, 중복·백업·락·수신 subprocess, 영수증 | 현재 서비스 웹과 실제 DB 동일 여부 |
| COST | `app/participant_roster.py::validate_manifest / validate_participants` | allowlist, source hash, coverage, 여행 참조, 실명/영문명 필드 검증 | 보험사 실제 가입 결과 직접 조회 |
| COST | `tools/ingest_participant_roster.py` | `register_roster`를 참가자 SQLite에 실행 | 운영 Windows 자동 수행 여부 |
| COST | `app/participant_roster.py::register_roster` | 사용자 명단 등록, 배치 fingerprint/멱등성, pending, 충돌, 교정 제안, 감사 이벤트 | 모든 명단이 보험가입 완료에서 유래하는지 |
| COST | `app/participant_income.py::reconcile` | 명단 확정과 Google 수입 연결을 분리, 동명이인/결정·원본 변경 보호 | 수입 연결만으로 보험 효력/입금 완료 확정 불가 |
| COST | `webapp/participant_income_page.py` | owner 전용 `/participants` 및 `/api/participants/state` 조회, CSRF/화면 fingerprint 기반 연결 쓰기 | 여행 탭 내부 재사용 UI 미구현 |

### 1.2 수신 계약

- COST 수신: `schema_version=1` / `authority=owner_confirmed_insurance` / `roster_id` / `batch_id` / `revision`.
- `trip_ref.cost_trip_id`와 `trip_ref.google_trip_key` 둘 다 요구한다. `mapping_resolver`는 기존 Google 키로 얻은 여행 ID가 명세의 `cost_trip_id`와 **정확히 일치할 때에만** 참가자로 등록한다.
- 미매핑/불일치: `held` + `TRIP_MAPPING_REQUIRED`, 참가자 신규 확정 없음. 같은 배치/같은 내용 재전송은 보관된 결과를 재사용. 이름 변경은 기존 이름 덮기가 아닌 correction proposal.
- 입력 명단의 허용 필드: 이름, 영문명, 닉네임, source/page/row/증빙 해시 및 상태. **주민번호, 생년월일, 전화번호, 여권, 성별 등은 구조화 COST 명단에 전달하지 않는다.** 원본 사진에는 민감 정보가 있을 수 있어 기존 비공개 archive에만 접근 허용.
- `scope=partial`과 `scope=complete`은 다르다. `registered`는 배치 처리가 수신된 결과이고 `pending_items`, `conflict_items`, `corrections` 및 수입 미연결을 함께 확인해야 한다.
- `owner_confirmed_insurance`는 **COST에 전달된 가입 근거의 타입**이지 보험사 API에서 검증된 보험 효력 상태나 실제 입금 확인을 뜻하지 않는다.
- 결제/가입이 끝났다는 사용자 확인, 보험사 가입 완료 증빙, COST 참가자 등록, Google 수입 연결, 항공권 예약/실제 탑승은 각각 별개 상태.

## 2. 우선순위 P0: 실제 웹 참가자 DB 일치 검증 (COST-INS-01)

**근거:** COST 웹 `app.participant_roster.default_db_path()`는 기본적으로 `cost/.local-archive/participant-rosters/participant.sqlite`를 열지만 `WEBLEDGER_PARTICIPANT_DB` 환경변수로 재지정 가능. Travel INS 전달기의 기본값은 위 archive 경로이며 별도 `db` 설정도 존재한다. 실제 운영 프로세스 설정은 이번 GitHub 코드 점검만으로 확인할 수 없다.

### 구현 내용

1. 배포/운영 preflight에서 활성 COST 웹 프로세스의 참가자 DB 대상, COST `default_db_path()`, Travel INS 전달기 설정의 `db`와 `cost_root`를 개인정보·경로 자체 노출 없이 **같은 파일을 가리키는지** 확인한다.
2. 정확한 파일 동일성이 확인되지 않거나 DB가 준비되지 않았을 때 “COST에 실제 반영 완료”라고 보고하지 않는다. 코드에는 검증 가능한 `STORE_UNBOUND / DB_IDENTITY_UNVERIFIED` 등 상태코드를 분리한다.
3. 현재 `send_cost_roster.py`의 Git 무시 경로 검사, archive 밖 DB 거부, 회계 DB 오지정 방지, SQLite 일관 백업/복원, 단일 lock을 보호한다.
4. DB 점검은 읽기 전용. 실제 참가자 저장소 변경이 필요한 테스트는 격리된 합성·임시 DB로만 수행한다.

**완료 기준:** 영수증 `batch_id`, `google_trip_key`, `trip_id`, 등록 인원/보류/충돌 수가 웹이 참조하는 **같은 참가자 DB**의 합성/허가된 읽기 전용 조회 결과와 일치. 운영 권한·파일 경로 증빙 없이 PASS 금지.

## 3. 우선순위 P0: 발신 결제 재개 계약과 수신 영수증 검증 (COST-INS-02)

### 확인된 Travel INS 결함

`travel_ins/tools/payment_pause.py::resume_after_owner_reply`의 `finish_registration(owner_attested=True,...)` 호출은 현재 `travel_ins/tools/insurance_cost_flow.py::finish_registration(...,confirmation_reference,...)` 서명과 맞지 않는다. 이 경우 실제 호출은 `TypeError`가 발생하고 해당 작업 경로에서 COST 등록은 수행되지 않는다.

이는 **Travel INS가 소유하는 코드 결함**이다. COST 수신기를 중복 구현해서 우회하지 않는다.

### COST 측 협약

- 보험사 가입 완료 증빙/확인번호·확인된 인원 수·사용자 완료 확인 없이 들어온 배치를 보험 검증 완료로 판정하지 않는다. 수신 배치의 `authority` 문자열만으로 권한 증명으로 취급하지 않는다. 로컬 수신 트러스트 경계는 실제 host/user/파일 권한으로 통제한다.
- 전달기가 `status=registered` 영수증을 받아도 `batch_id`, `google_trip_key`, `trip_id`가 기대값과 일치하고 `pending_items/conflict_items/corrections`를 함께 검사한 후에만 최종 수락을 보고한다.
- `held`, `conflict`, `review_required`, 수신 파일 누락, 웹 DB 불일치, 원본 변경은 명시적으로 미완료/보류로 취급.
- 같은 `batch_id`/fingerprint 재시도 시 참가자 중복 0건, 바뀐 내용은 거절. 새 교정은 revision 증가와 기존 사용자 결정 보호.
- 네트워크 API가 없는 현재 로컬 전달기는 유지. 다른 호스트로 분리 운영할 계획이 생기면 **별도 인증·권한·암호화·재시도·멱등성 전송 설계**와 사용자 승인을 받기 전 HTTP 수신기를 공개하지 않는다.

## 4. 우선순위 P1: 여행 탭의 보험 명단 참가자 조회 (COST-INS-03)

### 4.1 목표 UX

앞서 설계한 여행별 항공권 조회 `trip-flight-booking-overview-20261028.md`와 연계한다.

~~~text
[여행명 | 일정 | 기존 수입/지출 요약]
[수입]                    기존 Google 정본 수입
[지출]                    기존 COST 비용
[항공권 예약 N건]         해당 여행의 항공권 예약, 출발 여행 귀속
[보험 명단 참가자 N명]    Travel INS에서 확인돼 수신된 인원
  ├ 명단 확정 N명 / 판독 검토 N명 / 원본 부분 명단 여부
  ├ 수입 이름 일치 N명 / 수입 미연결 N명 / 동명이인·수동 검토 N명
  └ [권한 있는 관리자만 상세 펼치기]
~~~

- 새 영역은 **예약 목록·회계 목록과 분리된 읽기 전용 view**다. 참가자 수는 보험 가입 완료 상태를 보장하지 않으며 수입 연결이 입금 완료를 의미하지도 않는다.
- 처음 화면은 현재 권한에 따라 숫자·원본 최신성·부분 명단 상태만 표시. 상세 명단은 사용자가 펼칠 때 지연 조회, 기본 페이지 20명. 데이터가 많다고 전체 이름/보험 원본을 DOM에 붙이지 않는다.
- 사용자를 다른 메뉴로 이동시켜야만 핵심 정보를 볼 수 있게 만들지 않는다. 그러나 **현재 `/participants`의 관리·수입 수동 연결/교정**은 owner 권한·기존 write flow만 사용하며 신규 탭에서 별도 쓰기 경로를 중복 구현하지 않는다.
- 현재 webapp/participant_income_page.py::dispatch는 **owner만 접근 가능한 명단 화면**이다. 여행 탭이 공개 열람/다른 역할에도 보이는 경우를 고려해, **기존과 동등하거나 더 엄격한 owner 권한** 없이 이름/상세/합성 숫자를 노출하지 않는다. 일반 사용자의 공개 여행 탭에는 영역을 숨기거나 접근 불가 상태로 표시한다.
- 보험 명단 인원과 항공권 PNR 승객 이름은 이름만 같아도 다른 사람일 수 있다. 기존 검증된 동일인 결정 없이 서로 매칭하거나 보험 완료로 표시하지 않는다.
- 단일 여행에 참가자가 여러 배치/수정본으로 들어오면 최신 revision과 item identity를 이용해 중복 표기를 방지한다. 여행 이동은 기존 별도 감사 write path로만 가능.

### 4.2 재사용 데이터/API

- `app/participant_roster.py::ParticipantStore.open_readonly / participants(trip_id) / batches()`와 `webapp/participant_income_page.py::build_state(trip_id)`의 출력을 **상황에 맞게 축약**해 사용하는 read projection을 만든다. 현재 `build_state`는 Google 대조까지 실행하므로, 여행 탭 요약 응답이 모든 Google 원본을 반복 읽어 느려지지 않도록 가벼운 참가자 수 쿼리를 우선 설계한다.
- 기존 `/api/participants/state?trip=<id>`는 owner 검사를 거치는 상세 API이다. 새 API를 도입한다면 해당 권한을 완화하지 않는다. 제안: `GET /api/trips/{tab_id}/insurance-participants?limit=20&cursor=...` (기존 라우트 구조 확인 후 최종 경로 고정).
- 응답: `trip_id, roster_scope, latest_revision, counts {confirmed, pending, conflict, correction_pending, linked_income, no_income, needs_check}, generated_at, source_available, items, next_cursor`. 숫자의 뜻을 일관되게 정의하고 개별 명단 출처·금액·본인확인은 기존 권한에 따라 제한.
- 조회 실패, DB 미구성, 매핑 보류, Google 수입 최신성 부족을 각각 구분. ‘명단 0명’과 ‘명단 DB 조회 실패’는 다른 화면 상태.
- 항공권 탭에서 사용한 공통 카드·배지·라이트/다크·모바일 200% 텍스트 확대 UX를 재사용. 권한 없는 빈 화면에 실명 포함 HTML을 미리 렌더링하지 않는다.

### 4.3 비용·회계 보호

- 여행 탭의 보험 참가자 행을 수입 또는 지출 표에 새 행으로 넣거나 Google B:H 복사 데이터로 변환하지 않는다.
- 참가자 원본은 별도 SQLite. 기존 카드 DB/OTA 매칭/여행 수입 액수/Google 시트에 자동 쓰지 않는다.
- 항공권 예약, 보험 명단, Google 수입을 단순 이름 일치만으로 하나의 확정 참가자로 병합하지 않는다.
- owner 승인/CSRF/화면 fingerprint·revision에 따른 참가자 수입 연결 변경 흐름은 기존 경로가 계속 단독 소유한다.

## 5. 우선순위 P1: 여행 매핑 계약 개선 (COST-INS-04)

- 기존 `mapping_resolver`는 Google 여행 키↔COST trip_id가 일치할 때만 참가자를 등록한다. 이 fail-closed는 유지한다.
- 매핑 JSON과 실시간 COST 여행 정본이 충돌하면 별도 실패 상태로 사전에 확인하고 보류한다. 운영 자료를 자동 생성하거나 Google 원본을 수정하지 않는다.
- 후속 리팩토링에서 Google authority의 검증된 active trip mapping을 하나의 read-only resolver로 묶어 독립 JSON 복제/구식 키 잔존 위험을 줄인다.
- 사용자 여행 변경·이름 교정·새 명단 revision은 기존 `participant_trip_remapped` 등 감사 이력을 유지한다.

## 6. 테스트와 운영 수락

| 테스트 범주 | 조건 |
| --- | --- |
| 인터페이스 테스트 | Travel INS `payment_pause.py` → 실제 `finish_registration` 시그니처, 확인번호/인원 불일치/취소 시 COST 쓰기 0 |
| 소스/전송 | 주민번호·생년월일·전화/여권·알 수 없는 키 거부, source SHA, row identity, coverage partial/complete, 금지 archive 차단 |
| 수신 DB | 같은 배치 재전송/잠금/백업/복원/웹 DB 같은 파일 검증, 등록 1회·중복 0·기존 사용자 수정 유지 |
| 여행 매핑 | Google 키/실제 여행 ID 불일치 `held`, 기존 여행 삭제/보관·오래된 키, 새 키 승인된 갱신 |
| 참가자 대조 | 참가 확정과 수입 연결 별개, Google 원장 읽기 전용, 동명이인·동일인·공동입금·수동 결정 |
| UI/인증 | `/participants` owner-only 보호, 비owner/익명 API 403, 다른 trip 파라미터 접근 보호, 이름/상태 렌더링 XSS·200%·모바일/다크 |
| 운영 | 실제 웹 프로세스 DB 동일성 읽기 전용 확인, 지정 여행의 배치 영수증과 화면 수 비교, 보호 회계 DB·Google 데이터 전후 무변경 |
| 성능 | 여행 상세 처음 열 때 보험 명단 원문 전체 조회/반복 Google 대사 금지, 상세 펼침 시에만 제한된 페이지 조회 |

재사용 테스트: `tests/card_pipeline/test_participant_roster.py`, `test_participant_income.py`, `test_participant_integration.py`, `webapp/tests/test_participant_income.py`. Travel INS 측 `tests/test_cost_handoff.py`, `test_cost_roster_adapter.py`, `test_insurance_cost_flow.py`, `test_payment_pause.py`를 함께 검증한다.

## 7. 단계별 실행 백로그

| ID | 소유 레포 | 작업 | 완료 게이트 | 상태 |
| --- | --- | --- | --- | --- |
| COST-INS-01 | COST+Travel INS 설정 | 운영 웹 DB와 CLI 수신 DB 동일성 preflight | 읽기 전용 실제 동일 파일 증빙 | **운영 미검증** |
| COST-INS-02 | Travel INS 우선 | payment_pause 함수 계약·가입확인 증빙·영수증 검사 | 실제 함수 계약 테스트 + 불완전 가입 전송 0 | **결함 확인, 미수정** |
| COST-INS-03 | COST | 여행 탭 보험 명단 요약·지연 상세·기존 owner 권한 재사용 | 수입/지출/항공권 데이터 불변 + UI/접근 검사 | **미구현** |
| COST-INS-04 | COST | 기존 매핑 검증 및 정본 resolver 수렴 | 매핑 충돌 자동 등록 0, 기존 배치/교정 보존 | **기존 fail-closed, 개선 미구현** |
| COST-INS-05 | 양쪽 | 통합 테스트/실자료 읽기 전용 수락 및 운영 상태 기록 | 합성 양끝 등록·조회 + 권한 + 배포 SHA | **미검증** |

### 7.1 에이전트가 반드시 구분할 것

- Travel INS `docs/WORK_INDEX.md` H3: **14명 수신 기록**은 과거 로컬 등록 이력이지 현 운영 웹 DB 동일성 또는 보험사 가입 완료의 독립 증빙이 아니다.
- COST 참가자 수신/수입 대조는 이미 구현돼 있으므로 새 독립 참가자 DB/매칭 엔진을 만들지 않는다.
- 새 기능은 실명 명단의 여행별 **안전한 조회와 전달 계약 복구**이지 보험사 결제 자동화/외부 공개 API 추가가 아니다.
- 문서만 업데이트했으면 `SPEC_ONLY`. 코드 작성/테스트/병합/운영 배포/실자료 수락을 각각 별도로 보고한다.

## 8. 인수 시 필수 체크

1. COST/Travel INS 최신 main과 작업 중 PR, 현재 Windows 실제 운영 SHA와 프로세스 설정 재확인.
2. 읽기 전용으로 운영 참가자 DB 파일 동일성 확인. 확인 불가시 최종 성공 판정 보류.
3. 먼저 Travel INS `payment_pause` 코드 계약 결함을 고치고 합성 end-to-end 테스트 통과.
4. 보험가입 확인번호, 사용자 명시적 승인, 인원/Excel/명단 일치 및 멱등 영수증 확인 단계 유지.
5. 다음으로 COST 여행 탭에 **기존 owner 권한을 유지하는** 참가자 read projection 추가. 별도의 새 영속 DB/금융 기장/Google 쓰기 금지.
6. 사용자 권한 범위 내에서만 실제 명단 수신/정정·배포. 운영 검증은 읽기 전용 원칙.
