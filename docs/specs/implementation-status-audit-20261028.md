# 2026-10-28 18:30 KST 구현현황 감사 및 명세 차이 정리

> **이 문서는 기존 승인 27개 작업의 새 복제 큐가 아니다.** 현행 GitHub `main`, 운영 인계, 기능별 제품 계약을 비교하는 **시점 고정 감사 스냅샷 + 구현 전 확인 목록**이다. 이후 상태가 바뀌면 [현재 상태](../session_handoff.md)와 [운영 기록](../operations.md)이 최우선이다.
>
> - COST 확인 기준: `main 9c3a88b9ef0fd8a5afa81a88013339da5f820262`, 2026-10-28 18:23 KST 무렵 병합된 PR #291까지.
> - Travel INS 확인 기준: `main ae7339be3185441efbd579c1bf1787358c8819ef`, PR #8까지.
> - 위 시점 GitHub COST 미병합 PR **0건**, Travel INS 미병합 PR **#2(Render Blueprint)** 1건. 다른 로컬 작업자/worktree는 GitHub PR 숫자에서 보이지 않으므로 ‘작업 없음’을 의미하지 않는다.
> - 운영 상태: `docs/session_handoff.md`의 마지막 **실제로 검증된 Board SHA는 9f6eec7a66be1fae7ee4b8d761c5c4e81d070b1e**. 최신 `main 9c3a88b`와 다르며, #286~#291을 실제 운영에 설치했다고 확인하지 못했다. 문서 변경은 운영 배포가 아니다.
> - 검증 방식: GitHub 코드·트리·기능 명세·인계·PR 본문/병합 상태를 **정적 대조**. 이번 감사에서 pytest, 운영 브라우저, 운영 DB 및 보험사 가입을 새로 실행하지 않았다. PR에 기록된 테스트 결과는 **기존 검증 이력**으로 인용한다.
>
> **상태 정의**: `SPEC_ONLY`=명세, `CODE_MERGED`=main에 코드 있음, `TEST_EVIDENCE`=실행 근거 기록 존재, `OPERATIONS_VERIFIED`=실제 운영 SHA·보호·화면 확인, `NEEDS_EXTERNAL_EVIDENCE`=원본 없이는 금융 확정 불가. 하나를 다른 것으로 대체하지 않는다.

## A. 실제 구현된 기반과 후속 경계

| 작업 | main에서 확인된 구현/근거 | 아직 끝나지 않은 일과 다음 에이전트 지시 |
| --- | --- | --- |
| **RF-101 저장소** | `ledger_store_records/schema/allocation_validation/audit/idempotency/change_validation` 파일 분리. #285 멱등성, **#288 변경 검증** 병합. #288 PR 기록: Supervisor70 passed+3 subtests, SQL·공개 메서드/AST 동등. | `ledger_store.py`는 여전히 약 **6,209줄**. 전체 CRUD/스키마·감사 소유권·동적 입력 정규화/성능 수락 완료 아님. 파일 개수만으로 완성 판정 금지. |
| **RF-102 HTTP/보드** | `board_http_shapes/board_read_projection/board_export_helpers/board_render_helpers` 등 추출, #267/#278/#284 병합·일부 9f6eec7 운영 근거. | `ledger_board.py` 여전히 약 **5천 줄**. 세션/인증/라우팅/생명주기 전체 분리·운영 회귀 수락 필요. |
| **RF-103 카드 흐름** | `card_cleanup_ui/card_evidence_ui/card_ota_projection/card_refund_query` 분리, #261/#268/#269/#276 기반. `card_flow.py` 약 **3,153줄**. | 기존 범위는 분리된 UI/읽기 코드. **PIR/PA/ECF 신규 제품 기능이 이미 구현됐다는 뜻 아님**. 귀속·결정 단일 소유권/worker 전체 수락 필요. |
| **RF-106 항공권 기존 검색** | #286 병합, `webapp/flight_booking_projection.py` 분리. Supervisor71 passed·selector8 이력. 기존 탑승객 이름 검색과 관련 예약 읽기는 사용 가능. | **여행별 `trip_id` 항공권 목록**(TF-001~08)은 여전히 별도 SPEC_ONLY. 이름 검색 기능을 여행 탭 완료로 보고 금지. 최신 #286의 고정 운영 배포 여부는 별도 확인. |
| **RF-107 provider** | **#289 병합**, `provider_config_schema.py`로 순수 검증/마스킹 분리. Supervisor135 passed·105 subtests, 기존 인터페이스/AST 차등 근거. | 전체 외부 adapter 통일은 남았고 신규 운영 인증값·시크릿을 Git/PR에 쓰지 않음. |
| **RF-201/202 디자인·셸** | **#290 병합**, `site_shell.css` 공통 geometry·44px 터치, 테마/CSS baseline 합성 matrix, 기존 shell assets 분리. UI 자산은 `webapp/static/css/{ledger_design,site_shell,site_theme}.css`, `webapp/static/js/{ledger_design,site_shell,site_theme}.js`. | 전체 디자인 컴포넌트 도입/모든 화면 시각 통일 완료 아님. #290은 합성 desktop/mobile+CSS zoom 검사이고 **물리 기기 수락 아님**. |
| **RF-301 의존성** | #283, requirements 단일 검증/atomic mirror, Supervisor51 passed 이력. | 환경변수/secret/config/feature flag의 전면 통합은 남음. |
| **RF-304 문서** | #287 승인 작업 27개·현재 인계·역사 보관 통합. | 이 새 스냅샷은 **27개 실행 큐를 수정/확장하는 명령이 아님**. 새 제품 기능을 기존 RF 완료로 승격하지 않는다. |
| **OTA 큐/성능 기존 기능** | #250/#251에서 서버 페이지·그룹화·OTA 대사 성능 운영 수락: 3,799 사건→3,222 예약 그룹, 396.43→261.89초(기존 기록). | 외부 결제 근거 부족 건과 원결제 없는 환불은 실제 금융 미결. 그룹화/속도 개선을 금융 완료로 오인 금지. |
| **PEND-04 클라우드 메일** | **#291 병합**, 선택적 batch_size 1~100, preview offset, 16MiB/file·100MiB/call 한도, 전체 metadata 선검증, 미완료 batch apply 거부. PR 기록: supervisor51 passed. 전체 열거 3,704건·약281MiB는 기존 운영 인계 기록. | **코드 준비는 됐지만 실제 원문 batch 적재·단일 writer 전환·Gmail 예약 작업 변경은 미실행**. 기존 백업·별도 복원·보호 13개 표·writer idle 및 동시 쓰기 0 확인 뒤만 수행. 최신 main의 프로세스 배포도 별도. |
| **PEND-01 금융 외부 근거** | 마지막 읽기 전용 집계: 카카오 취소 39 중 29 연결/10 미연결, Agoda 76 중 73/3, Trip 취소 186 중 171/15. | **원결제 원본/명시 결제 증거 미확보**. 새로운 추론 배정 정책으로 원결제·실제 환불을 거짓 확정할 수 없다. `NEEDS_EXTERNAL_EVIDENCE` 유지. |
| **PEND-02/03** | 반응형 검수/클라우드 수집기 기반은 기존 인계에 `complete`로 기록됨. | 이미 완료한 검사를 새 작업으로 중복 실행하지 말고 운영 목적의 후속 컷오버만 분리. |

## B. 사용자가 새로 정한 제품 기능의 **코드 대조 결과**

| 제품 요구 / ID | 지금 실제 있는 것 | 코드에서 아직 보이지 않는 것 / 수정 명세 |
| --- | --- | --- |
| **PIR-01~06: 보험 확정 명단 × 수입 결합** | `app/participant_roster.py`의 참가자/원본/교정·`app/participant_income.py::reconcile/save_decision`의 수입 대조·owner 전용 `webapp/participant_income_page.py`. | `webapp/ledger_design.py`의 실제 여행 수입 화면에 **'보험 등록' 열/보험가입내역 영역이 없음**. `participant_income_page.py`의 dragstart/drop 구현도 확인되지 않음. **수입 → 보험가입내역 → 지출**과 실명↔닉네임 드래그/선택, 1:N/N:1, owner-only/감사/원본 불변은 [PIR 명세](participant-income-authority-and-drag-link-20261028.md)대로 신규 구현. 기존 참가자 저장 엔진을 다시 만들지 말 것. |
| **PA-01~06: 근거 적어도 여행 우선 잠정 배정** | 기존 `app/classify.py`는 inferred_assignment 및 사용자 결정 우선, `webapp/card_flow.py`에는 기존 여행 후보/OTA 근거가 있음. | `app/classify.py`에 `AUTO_PROVISIONAL` 공통 상태·단일 후보 ranker 확인되지 않음. **추론 UI와 유효 trip_id 동기화**, 대안 후보·검토/교정, 사후 교정 자료화는 [PA 명세](provisional-assignment-review-first-20261028.md)의 별도 정책 변경. 금융 카드↔예약 매칭을 낮은 근거만으로 확정하는 변경은 **금지**. |
| **ECF-01~04: 지출정리 상태 버튼** | `webapp/card_cleanup_ui.py`로 CSS/페이지 UI가 분리됨, `card_flow.py::render_expense_cleanup`은 기존 미정리 목록을 출력. | 현재 `card_cleanup_ui.py`의 `.cleanup-breakdown span`, `cleanup_page`만 있는 페이지 URL, `card_flow.py`의 `cleanup_reason` 부재를 직접 확인. **세 칩은 아직 실제 서버 필터가 아님**. 전체/미분류/미배정/보호/기타 검토의 배타적 count, GET 필터, 저장 후 재계산 명세를 그대로 구현. |
| **TF-001~08: 여행별 항공권** | 기존 항공권 이름 검색·확인 UI와 flight booking projection 구현/리팩토링됨. | `webapp/ledger_design.py`의 여행 탭에 직접 예약별 항공편 목록 없음. 첫 출발 여행 귀속·연속 여행 왕복 보존·Trip.com 우선, 같은 화면 검색/세대 보호는 [TF 명세](trip-flight-booking-overview-20261028.md) **신규 구현**. |
| **COST-INS-01~05 / TI-COST-01~05: 보험 수신 운영** | Travel INS `send_cost_roster.py`→COST `ingest_participant_roster.py` 로컬 CLI/별도 SQLite/수입 대조가 있음. | 실제 운영 웹 `WEBLEDGER_PARTICIPANT_DB`와 전송기가 동일 파일인지 **미검증**. Travel INS `payment_pause.py`는 `owner_attested` 미지원 인자를 넘기면서 필수 `confirmation_reference` 누락, 실제 함수 서명 불일치가 **2026-10-28 main에서도 그대로 확인됨**. 신규 보험 증빙 없는 우회 전송 금지. |
| **D-02 오래된 OTA** | 서버측 20건/예약 그룹·큐가 이미 운영됨. | **90일 경과 자동 감추기/완료/과거 이관 정책은 사용자 명시적 거절**. 새 잠정 배정은 여행 귀속에만 적용하고, waiting_source/evidence_missing/환불·원결제 미확인은 그대로 현재 검토에서 찾을 수 있어야 함. |

**반영된 제품 결정 D-01~05는 승인된 기획 정책이나, 인계에 명시된 별도 SPEC_ONLY 기능을 모두 곧바로 운영 작업으로 개시하라는 뜻은 아니다.** 리팩토링 RF와 파일 소유권을 먼저 맞추고, 후속 기능 PR 승인 범위를 구별한다.

## C. 기존 명세에서 최신화한 설계·수락 조건

### C-01 보험 수입 통합: 원본은 두 개, 화면은 하나

- **권위:** Travel INS 가입 완료 증빙이 검증된 보험 명단이 참가자의 확정 근거. Google 수입 원본은 입금 사실의 권위로 **독립 보존**.
- **업무 순서:** 입금이 닉네임으로 먼저 들어온 상태도 정상. 보험 명단이 나중에 도착하면 유일 이름 일치만 체크, 나머지는 owner drag/drop+동일 POST를 쓰는 모바일/키보드 선택으로 연결. 두 원본 행을 물리적으로 병합하거나 실명으로 원본 이름을 치환하지 않는다.
- **링크:** `participant_id ↔ income_ref` 다대다. 그룹 입금 금액을 자동 분할하지 않으며 ✓는 ‘보험가입 확정 참가자와의 연결’이지 여행비 완납 판정이 아니다.
- **여행 탭 배열:** **수입 → 보험가입내역 → 지출**. 항공권은 별도 접기 영역. 20건 서버 조회, owner 권한과 현재 Google/명단 fingerprint/revision 불변 검사 필수.
- **단계 경계:** PIR-01 데이터·권위 계약 → PIR-02 보험 열 read projection → PIR-03 명단 목록 → PIR-04 drag/선택 감사 write → PIR-05 alias/충돌 → PIR-06 QA. 이전 `COST-INS-03`의 ‘독립 보험 목록’을 추가 개발하지 말고 이 통합 명세로 대체한다.
- **실패 시:** DB 없는 상태/Google stale/부분 명단/가입 미증빙을 ‘0명·완료’로 오해하지 않는 오류/대기 상태. 개인정보는 서버에서 owner 인증 전 노출 금지.

### C-02 우선 잠정 배정: ‘빠른 여행 분류’와 ‘금융 확정’ 두 갈래

- **여행 귀속 단서**가 적더라도 유효한 우세 후보가 있다면 `AUTO_PROVISIONAL`로 저장/표시하고 **검토 필요**로 유지. 소수 근거에 따른 보류의 장기 누적을 줄이는 제품 목적.
- 여행 후보가 실제로 없거나 동일 우세도 동률이면 상위 후보 제시·검토. 임의 여행 생성/다른 여행 사용자 결정 자동 덮어쓰기 금지.
- **원결제·실제 환불·금융 지급 완료**는 기존 증빙과 중복·금액·통화/승인번호 게이트를 지켜야 한다. `AUTO_PROVISIONAL`은 대사 큐의 금융 완료 수에 더하지 않는다.
- 자동 귀속 비율뿐 아니라 owner의 오배정 교정률·원본 충돌·금융 보호 회귀를 측정. 새 조건을 공급자별로 끝없이 추가하기보다 **한 개 공통 후보 DTO+ranker**로 구현.
- 오래된 `evidence_missing/waiting_source`는 미해결 상태로 계속 검색/필터 가능하며, 시간만으로 자동 숨김·완료 금지.

### C-03 UI/개발 순서: 기존 리팩토링을 다시 만들지 않는다

1. **먼저 병합 근거 재활용**: #284 HTTP shape, #285/#288 장부, #286 flight projection, #289 provider schema, #290 shell tokens, #291 bounded mail. 해당 코드 다시 처음부터 복제하지 말 것.
2. RF-103/card_flow·RF-201/202/203 UI 소유권과 새 PIR/PA/ECF의 **같은 파일 충돌**을 확인해 한 파일당 단일 작성자. 작업 중인 로컬 에이전트에 중복 지시 금지.
3. 새 제품 UI는 기존 `participant_income.reconcile/save_decision`, `card_cleanup_ui`, `site_shell` 토큰을 사용하되 제품 정책(명단이 기준·잠정 배정)은 별도 회귀 테스트로 고정.
4. 각 PR은 **실제 수정 경로, 합성 테스트 명령/결과, 이전 기능과 비교, 최신 main·운영 SHA, 개인정보/금융 보호 경계**를 보고해야 한다.
5. 새 보험 통합·잠정 배정 등 제품 정책이 실제 코드에 들어오기 전까지 `SPEC_ONLY` 표기를 유지. 문구와 버튼 모양만 바꿨는데 기능 완료라 주장하는 것을 금지.

## D. 위험·미결·완료 조건

| 위험/미결 | 결정된 처리 |
| --- | --- |
| Travel INS payment_pause 오류 | 확인번호 수집/실제 함수 인터페이스 수정·합성 실함수 테스트와 증빙 없는 쓰기 0. Travel INS 소유, COST 수신기 중복 구현 금지. |
| 참가자 DB 서로 다른 파일 | 실제 웹 프로세스·로컬 CLI 읽기 전용 비교. 동일성 증명 전 `실제 운영 수락` 금지. |
| 기존 카드 지출 상태의 ‘보류·오류’ 숫자 | 현재 SQL의 기타 미기록을 protected로 분류하는 잔존 조건을 확인. `other_review` 분리/합계 검증 후 실제 필터 URL에 연결. |
| 높은 추론 문자만 보이고 여행이 미배정 | UI 문구가 아닌 실제 trip_id·display_tab_id·유효 여행 권위의 동일 decision 확인. 과거 감사·수동 잠금 보호. |
| Google 수입/보험 명단/항공권 이름이 다름 | 신원 증빙 없는 자동 동명이인 합치기 금지. owner 명시 연결·교정 기록. |
| 원결제 외부 증빙 누락 | 잠정 여행만 허용, 금융 HOLD 유지. 90일 규칙으로 지우거나 허위 완료 안 됨. |
| 배포 SHA와 최신 main 차이 | 배포는 Supervisor가 Windows writer/backup/restore/13표 보존/health/auth 확인 후 SHA 고정. 이번 문서 변경은 재배포 요구 아님. |
| 메일 전체 적재가 100MiB 초과 | #291 batch 코드 사용하되 미완료 apply·원문 덮어쓰기 금지. 단일 writer/복원 게이트 후 안전한 순서로 적용. |

### 이 감사의 완료 범위

- [x] 최신 양쪽 main·GitHub 열린 PR·COST 최근 #286~#291 코드/검증 이력 비교
- [x] 보험/수입, 카드/OTA, UI/항공권, 명단 발신 함수의 **핵심 코드 존재 여부 정적 확인**
- [x] 기존 인계 문서에서 **코드 병합과 운영 수락 상태 차이** 식별
- [x] D-01~05·PIR/PA/ECF/TF·TI-COST 문서 사이 우선 정책 정리
- [ ] 전체 pytest 신규 실행
- [ ] Windows 실제 웹/참가자 DB/메일 원문/운영 브라우저 검사
- [ ] 운영 배포 또는 사용자 실자료에 의한 최종 수락

**이 문서는 세션 시점의 검증 가능한 사실을 압축한 기록이며, 새로운 RF 실행 승인이나 금융 데이터 변경 지시가 아니다.**
