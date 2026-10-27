# COST — 현재 세션 인수 (2026-10-27)

> **검수 지적 수정·전체 브랜치 통합·배포 COMPLETE (#189/#190):** 운영 **`183d813301a4fcc4cab78d52a8d7e2ff2074be63`**. 수입 불일치/미검증 검색에서 전체·검색 지출 구분, 콘솔 완전 차단 주장을 후속 예약 실행 NOT_RUN으로 정정. 추가된 OTA 지연조회 브랜치 통합 및 재펼침/summary 포커스 보완. 표적14개 통과, 인접 기존 실패는 기준 main에서도 동일 재현. 982blob 일치·health/ready200·보호API401·2DB/13개 표 동일. 운영 `/import` 접힘·API0건/펼침200, 장부 검색 요약 확인. 미추적 CloudMail.gs·사용자 계획 보존. 상세는 [운영 기록](operations.md) 첫 절과 [작업 기록](superpowers/plans/2026-10-27-review-fixes-integration.md). 이후 문서 전용 병합은 앱 재배포 불필요.

> **여행 장부 수입·지출 통합 완료 및 콘솔 창 비노출 설정 변경 (#187):** [PR #187](https://github.com/6Soo/cost/pull/187) 정상 병합 및 운영 **`84e602ee76f4b50a072e43520af3cd886cebb423`** 배포 완료. 수입/지출 공통 테마 언어, 상단 요약 바(`#sum`) 수입·지출·차액 통합, 중복 지출 헤더(`tbody.colhead`) 제거, 수입 하단 `<tfoot>` 행 합계 밀착, 중첩 details 제거 및 메타데이터 바 평탄화. 운영 실제 장부(`trip-46d817cfb8c2`) 실시간 확인 완료(수입 35건 46,170,000원 / 지출 81건 6,989,884원 / 차액 39,180,116원). 980blob 일치·health/ready 200·보호API 401·2DB/13개 보호 표 동일. `WebLedger-MailCollect` 예약 작업 `pythonw.exe` 전환 완료. 다음 예약 실행의 무창 동작·수집 성공 수락은 NOT_RUN. Apps Script 클라우드 수집 전환 초안(`apps-script/CloudMail.gs`) 보존. [운영 기록](operations.md) 첫 절.

> **항공권 장애·전체 PR 통합 COMPLETE:** #184로 #172/#174/#176/#177/#179/#180/#183을 통합, 운영 **`94c8e8c293d784da3886879ad024d3c5d12061a5`** 배포. 금융 대사와 독립된 항공 메일 색인·최초 갱신 안내/재조회. 전체 OTA 대사가 갱신 중인 상태에서 실제 이름 검색 예약1건/여정2편/최초 메일 수신일 표시를 확인했다. 카카오 동액 추론은 후보 표시만 하며 금융 연결·상쇄로 승격하지 않는다. health/ready200·보호API401·979blob 일치·2DB/13개 보호 표 동일. 실제 이전 운영 #178의 `2f51cb2`를 검증해 복구 기준으로 사용했다. 표적 검사/검토·열린PR0건·세부 근거는 [운영 기록](operations.md) 첫 절과 [현재 작업](superpowers/plans/2026-10-27-flight-search-integration.md). 기존 미추적 계획 파일은 보존한다. 실제 장부/Google/참가자 쓰기는 실행하지 않았다.

> **/import 15초 보고 후속 COMPLETE:** #173을 병합·운영 **`e3938533b4c5b5c770d4297e0989ba0d8a188358`** 배포. 접힌 상세의 자료/규칙/거래 조회를 펼칠 때로 미루고 닫힌 batch polling을 중단했다. 화면 요청 안에서만 환불 전역 대조를 재사용한다. 동일 입력 렌더3.302→1.775초·지출 HTML 동일·표적93+브라우저2+인접1 통과. 배포 직후 OTA 갱신 중 TTFB1.448초·DOM1.994초·닫힌 상세 요청0·펼침 정상, health/ready200·보호API401·2DB/13개 표 동일. 15초 상황 자체는 재현하지 못했고 fresh 전후 수치로 확대하지 않는다. [운영 기록](operations.md) 첫 절. 별도 #172와 카카오 증빙 경계는 남긴다.

> **모든 브랜치 병합·배포 요청 COMPLETE:** #169 환불 공백/중복 보호와 #170 항공권 카드 UI를 정상 병합하고 운영 **`52d829ba832316c65c5d01fd256e9c5bba855000`**로 배포했다. 열린 PR 0개, 967개 blob 일치, health/ready200·보호API401·2DB/13개 보호 표 동일. 환불75개 및 영향받는 항공권 검사·검토·로그인 합성 DOM 스모크 근거는 [운영 기록](operations.md) 첫 절. 카카오 원승인번호 없는 11건은 여전히 증빙 차단이며 별도 Agoda 진단은 실행하지 않았다. 과거 계획의 미완료 표기를 새 작업으로 자동 실행하지 않는다.

> **카카오/진입 지연 최신 인수:** PR #167 운영 `b577e7f` 배포. [운영 기록](operations.md) 첫 절과 [현재 작업](superpowers/plans/2026-10-27-card-review-latency.md)을 따른다. 카카오 잔여 11건은 원승인번호/원결제 대응 증빙 부재로 실제 처리 차단. generation374 신선한 자료에서 메뉴 HTTP200·TTFB3.14초·DOM3.36초 수락 완료. 별도 #166 Agoda 자동화 진단은 이 작업에서 수행하지 않았다.

> **현재 재개:** #163 항공권 파서·환불 문구 수정은 병합·운영 배포됐다. [현재 미결표](COST_PENDING_WORK_AND_FLIGHT_BOOKING_DATE_20261027.md)와 [운영 근거](operations.md) 첫 절을 우선한다. 아래2026-10-24 SHA와 상태는 역사적 이력이다. 기존 사용자 미추적 계획 파일은 보존한다. 실제 장부/원본/Google 쓰기는 수행하지 않았다.

> **최신 재개 상태는 [COST V3 CURRENT HANDOFF](COST_V3_CURRENT_HANDOFF.md)가 우선합니다.** 이 파일은 짧은 세션 안내이며 이전 장문의 세션/운영 기록은 [2026-10-23 보관 전문](archive/ota-legacy-20261023/session_handoff.md)에 보존했습니다. 이전 TODO를 자동 재실행하지 마세요.

## 지금 반드시 읽을 문서

1. [**COST V3 최신 단일 재개 문서**](COST_V3_CURRENT_HANDOFF.md) — 0.11절의 미결 처리 상태와 실제 운영 SHA·복구·검사 근거를 따른다. 0.10절 이전은 이전 단계 기록이다.
2. [COST V3 단일 구현 진입점](COST_V3_START_HERE.md) — 가장 높은 목표 정책 권위, 단계별 작업 범위, 현재 코드와 운영 상태 구분.
3. [OTA–카드 정책 A 통합 구현](ota-card-reconciliation-policy-a-v3.md) — R0 진단부터 R6 전환까지.
4. [V3 사용자 수정·AI 대화·탑승자 명세](cost-v3-inference-ai-passenger-nm-test-architecture.md) — OTA 링크와 여행 A→B·학습은 독립.
5. [운영 상태 증거](operations.md) — 당시 실제 릴리스·검증, 최신 라이브 상태는 다시 확인.
6. [사용자 확정 회계 규칙](reconciliation-rules.md) 및 [Google 최종 정본 계약](target-workflow-google-authority.md).

## 현재 병합·운영 상태 (2026-10-24)

- 최신 운영은 [PR #96](https://github.com/6Soo/cost/pull/96)의 `d9c5adcbd6d5bce52229a218535283e841567e5a`다. PR #95의 출처 보존·기존 실패 7건 수정에 더해 항공권 host 설정·보호 토큰·신선한 최소 원본 색인을 연결했다. 실제 참가자 최소 읽기와 생성된 색인을 확인했다. 지출 복사본은 23건 처리·기록 0으로 실제 장부 변경 없이 53건을 보존했다. 사용자 인증과 개별 근거가 필요한 재개 위치는 현행 인계 0.11절을 따른다. 아래 토요코인·PR #91은 이전 배포 이력이다.

- 최신 승인 작업인 토요코인 예약 관계·결제 검증 분리는 [PR #92](https://github.com/6Soo/cost/pull/92)와 기본 검토 표시 보완 [PR #93](https://github.com/6Soo/cost/pull/93)으로 병합·배포했다. 최종 운영 SHA는 `3a94dbe589b9f9fbb9cb2b36774c08b9bbb1cf24`다. 최신 재개·검증 근거는 [CURRENT HANDOFF 0.10절](COST_V3_CURRENT_HANDOFF.md#010-2026-10-24-토요코인-예약-관계와-결제-검증-분리)을 우선한다. 아래 PR #91 내용은 이전 배포 이력이다.

- 사용자 승인으로 [PR #91](https://github.com/6Soo/cost/pull/91)을 main `a3474a8`에 병합하고 같은 커밋의 별도 릴리스를 운영에 배포했다. PR #88·#89·#90도 MERGED다. 개발·운영 근거는 [CURRENT HANDOFF 0.9절](COST_V3_CURRENT_HANDOFF.md#09-2026-10-24-사용자-승인-병합과-운영-배포-완료)을 따른다.
- 완료된 기존 기능을 재구현하거나 유효한 전체 검사를 반복하지 않는다.
- DB 5개·파일 59개의 백업·복원과 배포 후 보존을 확인했다. health/ready는 200, 비인증 import·OTA·항공권 경로는 401이다. 사용자 main의 미커밋 파일과 stash는 보존했고 Google 쓰기·실고객 후보 조회는 하지 않았다.
- 전체 회귀는 테스트의 직접 DB close 경합으로 중단돼 전체 통과가 아니다. teardown 수정의 표적 검사 1 passed와 기준선 동일 실패 7건, Aside의 실제 카드 검색 경로 확인을 구분해 기록했다. 완료된 작업이나 기존 운영 점검을 자동 재실행하지 않는다.

## 이전 세션 기록 (2026-10-23 당시 상태)

- **단일 정확한 재개 큐:** [CURRENT HANDOFF §3](COST_V3_CURRENT_HANDOFF.md#3-미완료미검증-작업-큐-재개-우선순위). 아래 문장 대신 최신 Git/CI/배포와 동 문서의 우선순위를 따른다.
- **COST 주요 코드 기준 커밋:** 0bd6e93 (이후 문서 전용 커밋 추가). R0~R6·N:M·R5-B COST 어댑터 및 합성 종단 테스트까지 개발 반영됐다고 보고됐다. COST 운영 호스트에 V3 전체 배포됐는지는 확인되지 않았다.
- **Reservation:** PR #22는 2026-10-23 cc4e325로 main 병합 및 **Vercel Production READY** 확인. 사용자 요청에 따른 배포. 참가자 후보 API의 실제 운영 비밀설정 및 인증·원본 조회 성공은 별도 미검증.
- **CI:** Reservation cc4e325 Actions run 39936103139의 smoke는 PASS, unit은 FAIL. 기존 masterDataQueue 기준선 실패와 동일 원인인지 CI 로그로 확인하고 실제 버그면 수정해야 한다.
- **남은 단계:** (P0) Reservation unit 실패 원인 분석 및 필요한 수정, (P1) 사용자 권한 경계의 읽기 전용 운영 토큰·실연동 검증, (P2) COST 실제 운영 V3 SHA/신규 필수 갭 확인. R6 안전 복구 fallback은 의도적으로 유지.
- **안전:** 금융 중복·환불·원본 충돌, 수동 links/여행 배정, 기장 결과·원본, 개인정보 최소화, Google 직접 쓰기 금지, 단일 writer, 기존 로컬 미커밋·미추적 파일을 보존한다.
- **지난 운영 이력:** [operations.md](operations.md) 및 [cleanup-resolution-20261023.md](cleanup-resolution-20261023.md)의 그 시점 숫자/기장 결과를 새 작업으로 재실행하지 않는다.

`docs/archive/`, `docs/history/`, 과거 `ota-first-*`, 오래된 자율 실행 계획과 보관된 회고는 이 날짜의 제품 목표가 아니며 **현재 구현을 지시하는 문서가 아닙니다.**
