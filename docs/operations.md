## 2026-10-27 검수 지적 수정·모든 브랜치 통합·운영 배포 (#189/#190)

사용자 요청에 따라 [PR #189](https://github.com/6Soo/cost/pull/189)의 OTA 지연조회와 [PR #190](https://github.com/6Soo/cost/pull/190)의 검수 수정·통합 보완을 정상 병합하고 **`183d813301a4fcc4cab78d52a8d7e2ff2074be63`**로 한 번 배포했다. 통합 시점 원격 브랜치는 main만, 열린 PR0건이었다. 기존 미추적 CloudMail.gs와 사용자 작업 계획을 보존했다.

- **수정:** Google 수입 불일치·미검증 상태에서도 검색 요약에 전체/검색 결과 지출 금액·건수를 구별한다. 미검증 수입 금액·차액은 숨긴다. 콘솔 창 완전 차단 완료 주장은 `pythonw.exe` 설정 변경 완료·다음 예약 실행 수락 NOT_RUN으로 정정했다.
- **추가 브랜치 통합:** OTA 검토는 기본 접힘·펼칠 때 읽기 조회, 닫힌 동안 polling 중단, 직접 링크 자동 펼침. 재펼침 조회 재개와 summary 포커스가 초기 렌더를 막는 문제를 보완했다. 기존 카드 선택·미저장 미리보기·확정 보호 코드는 유지한다.
- **검사:** 요약9·인접 불일치 브라우저1·OTA 지연조회/선택 보존2·직접 링크2 통과. 인접 OTA 단위38개 통과·1실패, 브라우저 묶음의 기존 13실패(subtest 포함)는 변경 전 `main e7b66d1`에서도 동일하게 재현했다. 후보 상세 즉시 노출 가정·Windows 임시 DB 정리 실패를 새 회귀나 성공으로 보고하지 않는다. 세부 명령·결과는 [작업 기록](superpowers/plans/2026-10-27-review-fixes-integration.md)에 있다.
- **독립 검토:** Inkling Small Free high 읽기 전용 검토에서 수입 요약/완료 문구 및 추가 OTA 변경 모두 중요 미해결 지적 없음. 고객 원문·비밀값은 전달하지 않았다.
- **배포 보호:** Git 추적 **982개 blob 일치**, 이전 검증 릴리스 `84e602ee76f4b50a072e43520af3cd886cebb423` 및 기존 복원 검증 사본 보존. 작업·프로세스 SHA 일치, Board Running·단일 127.0.0.1:8751 리스너, health/ready **200**, 비인증 보호 API **401**. 2DB/13개 보호 표의 내용·스키마 해시는 전후 동일했다.
- **최소 운영 스모크:** 로그인 `/import` OTA 초기 접힘·API 요청0건, 펼침 후 API200·조회 완료 표시·다시 접힘 확인. 실제 여행 장부 검색에서 전체/검색 지출 구분 및 원래 화면 복귀 확인. 불일치/미검증 두 상태는 배포 릴리스 모듈을 직접 로드한 합성 입력으로 확인했으며 실제 고객 자료의 경고 상태를 만들지 않았다.
- **증거:** `D:/WebLedgerHost/releases/release-audit-183d813301a4fcc4cab78d52a8d7e2ff2074be63.json`, 같은 SHA의 `deploy-evidence-*.json`, `.local-archive/income-summary-fix-20261027/`의 보호 전후·기준 실패 비교·release-smoke.json·browser-smoke.json·배포 스크립트.

요청한 수정·브랜치 통합·배포는 COMPLETE. 전체 pytest/전체 E2E·추가 메일 수집·강제 재대사·금융/Google/원본 쓰기는 실행하지 않았다. 콘솔 창 다음 예약 실행 수락은 여전히 NOT_RUN이다. 이후 증빙 문서만 병합할 때 앱을 재배포하지 않는다.

## 2026-10-27 여행 장부 수입·지출 화면 통합·운영 배포 (#187)

[PR #187](https://github.com/6Soo/cost/pull/187)을 정상 병합하고 운영 **`84e602ee76f4b50a072e43520af3cd886cebb423`**로 배포했다. 이전 세션의 Gemini 3.8 Flash High 위임 구현 및 검증 결과를 인수하여 진행했다.

- **원인·수정:** 여행 장부 화면에서 분리되어 있던 Google 정본 수입 영역과 지출 영역의 시각 언어(테마 토큰, 타이포그래피, 패딩, 테두리)를 일원화했다.
  - 상단 요약 바(`#sum`)에 수입, 지출, 차액을 함께 통합 계산·표시하되, 수입 불일치(`numeric_gap`) 또는 미검증 시 가공의 차액을 조작하지 않고 정직하게 `수입 합계 차이 있음` 안내만 표시.
  - 지출 테이블 상단 및 카테고리 소계 직후 반복 삽입되던 중복 3중 열 헤더(`tbody.colhead`)를 CSS `display:none` 처리하여 시각적 중복을 제거하고 DOM 검증 계약은 보존.
  - 수입 테이블 하단에 `<tfoot>`을 배치하여 `수입 행 합계 ({N}건)` 및 총액을 행 데이터에 즉시 부착.
  - 불필요한 `<details class='income-detail'>` 중첩을 걷어내고 일관된 메타데이터 바(`.income-meta-bar`)로 평탄화.
  - 장부-행 불일치 발생 시 접힌 상세 안에 숨기지 않고 상단 `role='alert'` 배너로 즉시 노출.
- **검사:**
  - 수입 유닛 및 권한/검증 테스트: `webapp/tests/test_trip_google_income.py` 외 3개 파일 **34 passed (4.34s)**.
  - 브라우저 E2E 테스트: `webapp/tests/test_trip_google_income_browser.py` 외 1개 파일 (1280px 데스크톱 및 375px 모바일, 라이트/다크 모드 전체, 불일치 배너 회계 안전성 검증) **4 passed (10.85s)**.
- **배포 보호:**
  - 추적 파일 **980개 blob 일치**, 이전 운영 SHA `94c8e8c293d784da3886879ad024d3c5d12061a5`에서 교체.
  - `WebLedger-Board` Running, task/process SHA 일치, 127.0.0.1:8751 단일 loopback listener, `/healthz` **200**, `/readyz` **200**, 비인증 보호 API **401**.
  - 배포 전후 2DB/13개 보호 표 내용·스키마 해시 **완전 일치 (`unchanged: true`)**.
  - 근거: `D:/WebLedgerHost/releases/release-audit-84e602ee76f4b50a072e43520af3cd886cebb423.json`, `deploy-evidence-84e602ee76f4b50a072e43520af3cd886cebb423.json`.
- **운영 실제 화면 검증 COMPLETE:**
  - Aside를 통해 운영 대상 장부(`https://ledger.foresttour.kr/board?tab=trip-46d817cfb8c2`) 실시간 확인:
    - `#sum`: `수입 46,170,000원`, `지출 6,989,884원`, `차액 39,180,116원` (`수입 35건 · 지출 81건`) 정상 통합 노출.
    - 수입 헤더: `수입`, `정본 · 읽기 전용`, `수입 46,170,000원`.
    - 수입 테이블 하단 `tfoot`: `수입 행 합계 (35건) 46,170,000원` 즉시 부착 확인.
    - 지출 테이블 중복 열 헤더: `colheadDisp: 'none'` 확인.
- **콘솔 창 팝업 조치 및 메일 수집 로컬 의존성 진단:**
  - `WebLedger-MailCollect` 예약 작업의 실행 파일을 `python.exe`에서 `pythonw.exe`로 교체했다. 실행 파일 변경은 XML로 확인했으며 다음 예약 실행의 무창 동작·수집 성공 수락은 NOT_RUN (백업: `.local-archive/mail-console-hidden-20261027T211154/`).
  - Google Apps Script(`apps-script/GmailIngest.gs`)는 과거 `메일수집` 시트 탭 작성용이었으나 2026-07-22 지침으로 자동 수집이 OFF된 상태이며, 현재 운영은 DKIM/SPF 인증 헤더가 보존된 `format=full` 원문을 로컬 SQLite(`ota_store.db`)에 인덱싱하여 사용함. Drive를 통한 클라우드 비공개 원문 수집 초안(`apps-script/CloudMail.gs`)을 준비하고 인계함.

## 2026-10-27 항공권 검색 복구·열린 PR 전체 통합 (#184)

[PR #184](https://github.com/6Soo/cost/pull/184)을 정상 병합하고 운영 **`94c8e8c293d784da3886879ad024d3c5d12061a5`**로 배포했다. #172/#174/#176/#177/#179/#180/#183 모두 MERGED, 병합 직후 열린 PR0건이다. 이전 에이전트 `2b2ca7be-a0ee-402d-a9c8-84be15b392de`의 마지막 사용자 승인 범위를 이어서 수행했다.

- **항공권 장애:** 이름 검색이 전체 OTA/카드 대사의 최신 상태에 묶여 갱신 중 예약0건/자료 확인 불가를 표시했다. 인증 항공 메일 내용 지문·파서 버전으로 별도 비동기 색인을 구성하고, 최초 진입 예열·갱신 중 안내·최대60회/2초 재조회를 제공했다. 메일 변경·누락·파싱 실패 시 과거 자료를 최신으로 표시하지 않는다. 금융 결제 연결·참가자 확정 게이트는 별도로 유지했다.
- **운영 실제 수락 COMPLETE:** 메일 전용 generation1/key `a8521520ee69`의 최초 생성 **67.77초** 후 실제 이름 검색에서 **예약1건/여정2편**, **최초 메일 수신일 기준**, 확정 카드 연결 근거 미검증 안내를 확인했다. 같은 시각 전체 OTA 대사는 generation384 다음 갱신을 진행 중이었으므로 검색 분리를 실제로 확인했다. 로컬 읽기 전용 추출 **45.419초/예약210건**과 운영 최초 생성 시간을 구별하며 지속 응답 지연 통계로 확대하지 않는다. 데스크톱 테마 버튼1개·표시 정상. `/import`의 지출 정리/원결제 근거 표시·관련 없는 장부 복사 버튼 없음도 확인했다. 실제 카드 연결·참가자 확정·장부 실행은 하지 않았다.
- **통합 안전 보완:** #174의 카카오 동액 추론은 기존 사용자 금융 보호 계약에 따라 **읽기 전용 후보 표시**로 통합했다. 원승인번호 없이 금융 `refund_links`/`refund_group` 연결·상쇄에 넣지 않는다. 번호 근거1:N/외화 링크와 기존 요청 단위 캐시를 보존한다. #179의 원거래 ID/스키마 누락 fixture를 보완하고 수동 결정·보류·제외·충돌 보호를 확인했다. 기존 장부 귀속 전달은 명시적인 기존 지출 실행 경로이며 이번 운영에서 실행하지 않았다. #183의 데스크톱 버튼 숨김/중복 문제와44px 조건을 보완했다. #180의 CLI 엔진 import 실패가 false 진단으로 숨겨지지 않게 했다.
- **검사:** 보호/cleanup/테마/상세 지연로딩/귀속 **82 passed**, 항공권/예약일/분리색인/모바일/카카오/귀속 **27 passed**, 후속 변경 직접 영향 **6 passed (12 deselected)**, 참가자/기존 색인 **18 passed**. 겹치는 묶음이므로 고유 총합으로 합산하지 않는다. 초기 fixture 실패2건은 수정 후 통과. 없는 테스트 파일명 지정은 검사0건으로 구분한다. Paseo 스킬을 통한 Inkling Small Free high 독립 읽기 전용 검토: 중요 결함 없음. 전체 pytest/E2E·대량 재대사·실제 금융/Google/참가자 쓰기는 생략했다.
- **배포:** 979개 추적 파일 blob 일치. 최초 시도는 이전 운영 SHA를 `e393853`으로 지정해 `TASK_MISMATCH`에서 서버 교체 전 중단됐다. 실제 운영은 정상 검증된 #178 **`2f51cb208d411d1913546e9bdc16a3f319eaeb48`**이고 새 릴리스의 조상임을 확인해 이 SHA를 복구 기준으로 같은 공식 절차를 재실행했다. 작업/리스너 프로세스/표식 SHA 일치, Board Running·단일 loopback listener·health/ready200·비인증 보호API401. 기존 복원 검증 사본과 이전 릴리스를 보존하고 **2DB/13개 보호 표 내용·스키마 동일**을 확인했다. 추가 재시작·반복 스모크는 하지 않았다.

근거: `D:/WebLedgerHost/releases/release-audit-94c8e8c293d784da3886879ad024d3c5d12061a5.json`, 같은 SHA의 `deploy-evidence-*.json`, task before/after XML, `D:/WebLedgerHost/data/ota-review/flight-search.log`, `.local-archive/flight-search-integration-20261027/`의 보호 전후/측정/브라우저 요약. [현재 작업 기록](superpowers/plans/2026-10-27-flight-search-integration.md). 기존 사용자 미추적 계획 파일은 보존했다. 이후 증빙 문서만 병합하는 커밋은 운영 앱을 재배포하지 않는다.

## 2026-10-27 수입 내역 미확인 행 노출 제외 수정·운영 배포 (#178)

사용자 요청("미확인 행은 노출 안되도록 수정 및 배포")에 따라 구글 시트 템플릿의 빈 행으로 인해 수입 내역에 "날짜 미확인 | 이름 미확인 | 0원"이 반복 노출되던 문제를 수정하고 배포했다. [PR #178](https://github.com/6Soo/cost/pull/178)은 **`2f51cb208d411d1913546e9bdc16a3f319eaeb48`**로 정상 병합·운영 배포했다.

- **원인·수정:** 구글 시트 수입 탭 템플릿의 수식 빈 행들이 H열 수식 계산값 0원으로 파싱되어 `owner_rows`에 수집되었고, `trip_income_html`에서 날짜와 이름이 모두 비어있는 행이 "날짜 미확인 | 이름 미확인 | 0원"으로 렌더링됐다. `webapp/google_ledger_page.py`에 `is_unconfirmed_income_row`를 추가하여 날짜와 이름(닉네임 포함)이 모두 미확인인 행을 화면 표시(`visible_rows`)에서 제외했다. 날짜나 이름 중 하나라도 있는 실제 거래 행은 정상 노출된다.
- **회계 안전성:** 원본 스냅샷 데이터, DB, 구글 장부 쓰기는 전혀 없으며, 제외된 미확인 행은 금액이 0원이므로 장부 행 합계(`rows_total`)와 장부 집계(`sheet_total`) 대조 및 회계 검증(`numeric_gap`)에 영향이 없는 순수 표시 레벨의 읽기 전용 필터링이다.
- **표적 검사:** `webapp/tests/test_trip_google_income.py`에 미확인 행 판정 단위 테스트 및 수입 내역 렌더링 제외 검증을 추가하여 **19 passed (0.82s)**.
- **실운영 검증:** 실제 운영 snapshot/rows 파일(`D:/WebLedgerHost/data/google-authority/`)을 로드하여 캡처 이미지의 대상 여행 탭(`trip-540c75b3d376`, 1030_닛코)에서 기존에 노출되던 미확인 행 9건이 깨끗하게 제거되고 유효 수입 3건(8월6일 이수원 외 2, 8월16일 박주연, 8월30일 이혜선/김현숙)과 총액 8,014,000원이 정상 렌더링됨을 엔드투엔드로 확인했다.
- **배포 보호:** 추적 파일 **968개 blob 일치**. 이전 운영 SHA `e3938533b4c5b5c770d4297e0989ba0d8a188358` 릴리스와 복원 검증 사본을 보존하고 Windows SHA 고정 절차로 교체했다. `WebLedger-Board` Running, task/process SHA 일치, 127.0.0.1:8751 단일 loopback listener, `/healthz` **200**, `/readyz` **200**, 비인증 보호 API **401**. 증거: `D:/WebLedgerHost/releases/release-audit-2f51cb208d411d1913546e9bdc16a3f319eaeb48.json`, `deploy-evidence-2f51cb208d411d1913546e9bdc16a3f319eaeb48.json` 및 task before/after XML.

## 2026-10-27 /import 진입 지연 후속 수정·배포 (#173)

사용자가 `/import` 진입에 15초가 걸렸다고 보고해 후속 수정했다. [PR #173](https://github.com/6Soo/cost/pull/173)은 **`e3938533b4c5b5c770d4297e0989ba0d8a188358`**로 정상 병합·운영 배포했다. 기존 UI/환불 기능은 재구현하지 않았다.

- **원인·수정:** 접힌 `card-review-detail`이 페이지 진입 즉시 규칙·자료 목록·전체 batch state를 조회하고 polling했다. 사용자에게 보이지 않는 규칙/자료/거래 조회는 상세를 펼칠 때 한 번 시작하고, 닫혀 있으면 batch polling을 멈춘다. 명시 `?batch=`와 `#preview`/`#ota-review` 바로가기는 계속 자동으로 펼쳐 로드한다. 전역 JS 상태와 업로드·기존 저장 핸들러는 유지했다.
- **서버 반복 계산:** 지출 목록 한 번 렌더링에서 원승인번호 전역 대조가 17회 수행됐다. 화면 요청 안에서만 전역 환불/개수 보호 결과를 재사용한다. 로컬 변경 횟수와 `PRAGMA data_version` 변경 시 재계산하며, 요청 밖의 저장 검증은 기존 경로를 사용한다. 동일 보관 입력 cProfile은 **3.302초 → 1.775초**, 전역 번호 스캔 **17회 → 1회**. 수정 전후 지출 목록 HTML **84,643바이트 완전 동일**(SHA256 `7bb84bd5cadce6ea525040b36763c67fb753bb48a08ab2beb75e0b103923aec1`).
- **검증:** 환불 공백/부분환불/외화쌍·navigation·환불 표시·환불 그룹 기장 보호 **93 passed**. 새 합성 브라우저 검사 **2 passed**(닫힌 상태 요청0·펼칠 때 GET2·재펼침 중복 시작 없음·명시 batch 바로가기). 기존 390px 카드 전체 내역→원행 상세 흐름 **1 passed**. 로컬/다른 연결의 변경 후 재계산·다음 요청 재계산·결과 사본 변경 격리를 검증했다. 초기 새 브라우저 검사2개 실패는 mock URL glob이 하위 `/rules`를 잡지 못한 것이어서 수정 후 해당2개만 재실행했다. 독립 Inkling Small Free high 읽기 전용 검토에서 중요 미해결 지적 없음. 전체 pytest/전체 재대사/미관련 E2E는 생략했다.
- **운영 측정:** 사용자 보고 15초는 재현하지 못했다. 배포 전 첫 관찰은 OTA 갱신 중 TTFB **2,058.1ms**, DOM **2,268.7ms**. 정상 generation379에서는 TTFB **4,082.3ms**, DOM **4,676.7ms**, load **4,817ms**였고, 이어 접힌 batch 조회가 **3,806.1ms**를 더 썼다. 배포 후 첫 화면 HTTP200·TTFB **1,447.8ms**, DOM **1,994ms**. 상세 closed/started=false·규칙/자료/batch 요청0, 별도 OTA 상태 GET만 확인했다. 실제 상세를 펼치자 규칙/자료/batch GET이 시작되고 batch model 로드가 완료됐으며 다시 닫았다. 배포 후는 **OTA 갱신 중 관찰값**이므로 앞선 정상 generation379와 동일 신선도 성능 비교로 확대하지 않는다. 같은 입력의 전후 개선 근거는 별도 cProfile과 HTML 동일성 비교다. 최초 15초 상황이 모두 해소됐다고 단정하지 않는다.
- **배포 보호:** 968개 추적 파일 blob 일치, 이전 운영 `52d829ba832316c65c5d01fd256e9c5bba855000`와 기존 검증된 백업/복원본 보존. task before/after XML·task/process SHA·단일 loopback listener 일치, health/ready200·비인증 보호 API401. 운영2DB/13개 보호 표의 내용/스키마 해시 동일. 금융·Google·참가자·고객 원본 쓰기 없음. 추가 재시작/대량 재처리 없음.

증거: `.local-archive/import-latency-20261027/`의 프로파일·동일 HTML 비교 스크립트·브라우저/보호 전후 JSON·배포 스크립트, `D:/WebLedgerHost/releases/release-audit-e3938533b4c5b5c770d4297e0989ba0d8a188358.json`과 `deploy-evidence-e3938533b4c5b5c770d4297e0989ba0d8a188358.json`. 지연 수정·배포는 COMPLETE. 같은 시점에 열린 #172 카카오 진단 PR은 이번 지연 작업과 별개여서 자동 병합하지 않았다. 원승인번호 없는 카카오11건의 증빙 경계는 유지한다.

## 2026-10-27 모든 브랜치 병합·운영 배포 완료 (#169/#170)

이전 Paseo `145e1d38-56f4-4a94-b7e9-5c65ac93460d`의 마지막 사용자 요청 **“모든 브랜치 병합 및 배포”**를 이어 수행했다. [PR #169](https://github.com/6Soo/cost/pull/169)는 `6c765a9a07f29fa0a920ef51b354f68b25a93244`, [PR #170](https://github.com/6Soo/cost/pull/170)는 **`52d829ba832316c65c5d01fd256e9c5bba855000`**로 정상 병합했다. 두 변경을 포함하는 후자를 운영에 한 번 배포했다. 열린 PR은 0개다. 남은 #165/#166 원격 참조는 이미 MERGED이며 #165 코드도 현재 main 대비 추가 diff가 없어 재통합하지 않았다. 기존 사용자 미추적 계획 파일은 보존했다.

- **환불:** 원승인번호의 ASCII 앞뒤 공백을 SQL/Python에서 동일하게 정규화했다. 탭/개행 처리 차이와 정규화 후 복수 원결제가 그룹 조회에 묶이는 문제를 추가 수정했다. 원결제 전역 유일성·동일 카드·정상 원문·1:N 합산·쓰기 없음은 유지한다. `test_refund_approval_padding`, `test_partial_refund`, `test_refund_foreign_pairs`, `test_cleanup_refund_display`, `test_refund_group_commit` **75 passed**. 운영 읽기 전용 transaction snapshot에서 기존 연결 **428건**은 추가/제거/내용 변경 모두 0이었다. 카카오 취소의 원승인번호 없는 **11건**은 여전히 미연결이며 이번 보완으로 처리됐다고 보고하지 않는다.
- **항공권:** 실제 DOM의 예약 요약·가는편/오는편 카드·공항/편명/시간 표시를 통합했다. 날짜 중복 표시로 모호해진 브라우저 선택자를 구체화했고 200% CSS zoom의 가로 넘침을 재현해 좁은 컨테이너의 세로 배치를 보완했다. 항공권 UI 계약/이름 검색/예약일/기존 참가자/디자인 다섯 파일 최초 실행은 **32 passed / 2 failed**. 수정된 최종 브라우저 검사와 UI 계약은 **2 passed**. 나머지 테마 실패는 변경 전 main과 현재 브랜치의 단독 실행 모두 **1 passed**로, 재현된 코드 결함으로 단정하지 않았다. 유효한 나머지 통과 근거를 재사용했다. CSS zoom의 scrollWidth 1px 반올림 허용과 실제 카드 우측 경계 검사를 함께 둔다.
- **독립 검토:** 프로필·앞선 두 무료 후보가 없어 승인된 Inkling Small Free high (`96b48270-52a4-4a39-899d-fbcbc4e5bbd9`)를 사용했다. 환불 정규화/중복 보호 및 최종 확대 CSS의 읽기 전용 검토 모두 중요 미해결 지적 없음. 고객 원문은 전달하지 않았다.
- **배포:** 추적 파일 **967개 blob 일치**. 이전 `b577e7f5f296de29138166a3617c81eb93f3e23e` 릴리스와 기존 검증된 백업/복원본 존재를 확인하고 기존 Windows SHA 고정 절차로 교체했다. task before/after XML 보존, task/process SHA 일치·단일 loopback listener·health/ready **200**·비인증 보호 API **401**. 2DB/13개 보호 표의 내용/스키마 해시는 배포 전후 동일했다.
- **화면:** 로그인 `/flight-passengers`와 새 렌더러 로드를 확인했다. 운영 렌더러에 브라우저 DOM 안에서만 합성 예약을 표시해 요약5개·여정2개·오는편1개·가로 넘침 없음·최초 수신일 기준·공항/편명·기존 카드/참가자 영역을 확인하고 합성 DOM을 제거했다. 이는 **합성 DOM 스모크**이며 실제 고객 이름 재검색 수락으로 확대하지 않는다. 실제 이름 검색은 이전 #163의 유효한 운영 근거를 재사용했다.

근거: `D:/WebLedgerHost/releases/release-audit-52d829ba832316c65c5d01fd256e9c5bba855000.json`, 같은 디렉터리의 `deploy-evidence-52d829ba832316c65c5d01fd256e9c5bba855000.json`, `.local-archive/merge-all-20261027/`의 보호 전후/읽기 전용 진단/배포 스크립트. 전체 pytest·전체 재대사·추가 서버 재시작·금융/Google/참가자 저장은 실행하지 않았다. 코드 통합·배포 요청은 COMPLETE이며 카카오 증빙 부재와 별도 Agoda 자동 추론 진단을 이번 요청의 완료로 대체하지 않는다.

## 2026-10-27 PR #167 카드결제검토 지연·카카오 잔여 진단

[PR #167](https://github.com/6Soo/cost/pull/167)은 **`b577e7f5f296de29138166a3617c81eb93f3e23e`**로 병합·운영 배포했다. 이전 세션 `d9040fc3-c1e4-4eed-825f-3e8c290780ca`는 진단 단계에서 중단됐고 완료 기능을 다시 만들지 않았다. 병합 중 들어온 #165의 OTA 미상 결제일 안내 문구와 #166 정책 문서도 포함하며, 해당 안내 경로의 보호 검사 1개를 추가로 통과했다. #166의 별도 Agoda 자동 추론 진단은 이 카카오/진입 지연 작업에서 완료했다고 주장하지 않는다.

- **병목·수정:** 20행 화면에서 전체 OTA 후보/제외 근거를 매번 펼쳐 제공자 대조 429,157회를 수행했다. 현재 페이지 카드 ID만 표시용으로 투영하고, `automatic_holds`는 `get_batch`가 읽은 원문 필드를 재사용해 행별 SQL을 제거했다. 같은 보관 OTA 입력의 cProfile은 **45.0초 → 5.3초**이며 운영 응답 시간과 별개다. 금융 판정·전체 배치 보호·원승인번호 1:N·실제 기장은 바꾸지 않았다.
- **카카오 잔여:** 지출 정리의 택시 11행 모두 미연결 취소다. 원승인번호가 비어 있고 취소 승인번호와 같은 카드의 구매도 없다. 보관 raw 16열에서도 괄호형 원승인번호를 찾지 못했다. 14일 동일 카드/가맹점 조회에서 10행은 동액 후보가 없고 1행은 후보 4개 중 동액 1개다. 이는 원결제 확정 근거가 아니다. 원결제 대응을 증명할 카드사 상세 또는 카카오T 자료가 필요한 **BLOCKED_EVIDENCE**이며 실제 처리 완료로 보고하지 않는다. 로그인 화면의 카카오 상세에서 원승인번호 부재와 취소 승인번호 단독 확정 불가 안내를 확인했다.
- **검사:** 표적 navigation/OTA 표시/환불/cleanup 계약 **81 passed**. 최종 원문 재사용 변경 후 관련 보호 **1+6 passed**, 원승인번호 부재 표시 **3 passed**, 병합된 OTA 안내 인접 검사 **1 passed**. 별도 화면 묶음은 **35 passed / 3 failed**이며 세 문구 기대값 실패는 변경 전 `3d73b9c` archive에서도 **3 failed**로 동일 재현했다. 독립 [Paseo 검토](../AGENTS.md)는 Inkling Small Free high로 수행했고 source 누락 우려를 원문 재사용으로 해소한 후 중요 미해결 지적 없음. 전체 pytest/E2E·대량 재대사·금융/Google 쓰기는 생략했다.
- **배포 보호:** 릴리스 **965개** 추적 파일의 Git blob 일치. 작업·프로세스·표식 SHA 일치, Board Running·단일 loopback listener·health/ready **200**, 비인증 보호 API **401**. 이전 `c02364f` 릴리스와 기존 복원 검증 사본을 보존했다. 운영 2DB/13개 보호 표 내용·스키마 해시는 배포 전후 동일하다. 증거는 `D:/WebLedgerHost/releases/release-audit-b577e7f5f296de29138166a3617c81eb93f3e23e.json`, 같은 SHA의 `deploy-evidence-*.json` 및 task before/after XML, `.local-archive/card-review-slow-20261027/protection-before/after.json`이다.
- **운영 속도 1차:** 변경 전 GET TTFB **12,411.6ms**, DOM **12,920.8ms**. 배포 후 메뉴 실제 클릭은 HTTP 200, TTFB **3,773.1ms**, DOM **4,055.9ms**, 클릭부터 자동화 관찰까지 **7,063ms**였다. 후자는 시작 시 OTA 갱신 중 상태이므로 동일 신선도에서의 전후 성능 수락으로 확대하지 않는다. 정상 갱신 후 신선한 자료 확인은 아직 대기다.
- **신선한 자료 수락 완료:** 정상 워커 갱신 후 generation **374**, 입력 키 `b9461b070b65`의 held=true / refreshing=false를 확인했다. 같은 로그인 메뉴를 클릭한 HTTP **200**, TTFB **3,136.3ms**, DOM **3,362.6ms**, 클릭부터 자동화 관찰까지 **7,085ms**였다. 화면 제목과 갱신 중 안내 없음도 확인했다. 앞선 시작 시 대기는 해소됐다. 전후 각 1회 관찰이고 서버 부하 통제 실험·평균/백분위가 아니며 자동화 관찰 시간을 실제 DOM 시간과 혼동하지 않는다. 이 검사를 위해 재시작·전체 재처리를 추가하지 않았다.

현재 실행 범위와 정확한 잔여 조건은 [작업 기록](superpowers/plans/2026-10-27-card-review-latency.md)에 유지한다. 실제 고객 카드·장부·Google·사용자 결정을 변경하지 않았다.

## 2026-10-27 PR #163 평탄화 항공 메일 누락 해결·환불 근거 표시 완결

코드 포함 main merge와 운영 릴리스는 **`c02364f47b64d66bebe8584a0e64b170e8e5633b`**이다([PR #163](https://github.com/6Soo/cost/pull/163)). 이후 문서 전용 main 커밋은 앱을 재배포하지 않는다. 이전 #155/#157 기능은 재구현하지 않았다.

- **원인·수정:** 보관 원본을 `mode=ro`/`query_only`로 읽어 인증된 Trip.com 평탄화 본문 4건을 확인했다. 기존 파서가 명시 예약번호·숫자 구간·성/이름 라벨을 읽지 못했다. `flight-evidence-v5-flat-layout`은 명시 라벨만 토큰화하고 시간·기종 오인을 막는다. 기존 인증·다중 예약번호·날짜/여정 충돌·취소·stale 경계는 유지한다. 같은 토큰화로 최초 수신일의 예약번호도 귀속한다. 수정 코드의 읽기 전용 원본 검사에서는 대상 예약 그룹 1개가 두 구간 완전·충돌 없음·취소 없음·FIRST_RECEIVED로 추출됐다. 고객 원문은 합성 fixture/문서/PR에 옮기지 않았다.
- **환불 표시:** 원승인번호 링크와 기존 `merchant_card_foreign_amount` 링크의 실제 근거 문구를 구별했다. 원결제 1:N 판정·금액·기장 엔진은 변경하지 않았다. 로그인 운영 `/import?cleanup_page=2`에서 근거 상세 두 단계를 펼쳐 **원승인번호 기준 원결제 확정 연결·취소/환불 2건**, 누적 환불액·순액 및 별도 환불 기록 상태가 표시되는 것을 확인했다. 운영 읽기 전용 링크 진단에서는 다중 환불 링크22건·외화 링크91건이 있었으나, 외화 링크는 미정리 목록에 없어 새 외화 문구의 실자료 UI 수락은 NOT_RUN이다. 그 문구는 합성 통합 테스트로 검증했다.
- **표적 검사:** `tests/card_pipeline/test_flight_evidence.py` **22 passed**; `webapp/tests/test_cleanup_refund_display.py` **19 passed**; 이름 검색·예약일 근거 두 파일 **18 passed**; `webapp/tests/test_guide_airfare_review.py`와 `tests/card_pipeline/test_guide_airfare_classify.py` **35 passed**. 파서가 가이드 항공료 근거에도 쓰이므로 해당 인접 보호만 추가했다. 합성 환불 DB dump 불변을 확인했다. 독립 읽기 전용 검토는 중요한 버그 없음(새 평탄화 테스트·환불 UI19개 실행 보고; 전체 파서 재실행 주장은 아님). 전체 회귀와 이미 유효한 다른 기능 검사는 의도적으로 생략했다.
- **배포:** 964/964 파일 대조·누락/추가/blob 불일치0. 기존 복원 검증의 DB 모든 테이블/열·원본 해시·review 결합 일치와 백업/복원본 존재를 재사용하고 이전 고정 SHA `9374770ca543fb9f6831b95b398b6c0d7d35b986`에서 교체했다. `WebLedger-Board` Running·작업/리스너 프로세스 SHA 일치·loopback listener1개·`/healthz`200·`/readyz`200·비인증 보호 API401. 근거: `D:/WebLedgerHost/releases/deploy-evidence-c02364f47b64d66bebe8584a0e64b170e8e5633b.json`.
- **항공권 운영 수락 COMPLETE:** 정상 파생 갱신 **432.51초** 후 generation **373**, parser **`flight-evidence-v5-flat-layout`**, passenger index/snapshot key 일치를 확인했다. 로그인 이름 검색이 **예약1건**을 반환하고 첨부 두 편명과 **최초 메일 수신일 기준**을 표시했다. 자동 당일 카드 조회는 **0/0건**, 오류 없음·결제 연결 미확정 안내였다. 0건을 미결제 판정이나 연결 확정으로 격상하지 않았다. 이전 색인은 최신으로 사용하지 않고 갱신 중 자료 확인 불가 안내를 유지했다. 강제 전체 재처리·추가 재시작·금융/참가자 저장 없이 정상 워커 갱신만 기다렸다.
- **보존·남은 경계:** 이 작업에서 고객 카드/결제 연결·참가자 확정·기장·Google·원본 쓰기는 하지 않았다. 정상 서비스의 파생 색인 갱신은 금융 쓰기와 구별한다. 실제 스마트폰 터치·검증 가능한 본창200% 수락은 외부 기기/제어 경계이며 합성 확대를 완료 증거로 대신하지 않는다. 이전 #152 Agoda 특정 날짜의 카드 화면도 로그인 전체 거래 검색에서 읽기 전용 확인했다. 대상 카드4건에 OTA 후보 문구0건으로 무관 예약의 제외 후보가 표시되지 않았다. 변경 전후 스크린샷 비교나 모든 OTA 예외의 포괄 수락을 주장하지 않는다. 기존 사용자 미추적 계획 파일을 보존했다. 코드 #163과 증빙 문서 PR을 정상 병합한 뒤 로컬·원격 브랜치는 main만 남기며 열린 PR0건을 확인한다.

---

## 2026-10-27 PR #155/#157 항공권 검색·다중 환불 UI 운영 반영

코드가 포함된 마지막 `main` merge SHA와 운영 런타임 SHA는 **`9374770ca543fb9f6831b95b398b6c0d7d35b986`**이다. 이후 PR #159 등 문서 전용 커밋으로 `main`이 전진했지만 실행 코드가 바뀌지 않아 운영 런타임은 이 SHA 그대로다. 이 릴리스는 PR [#155](https://github.com/6Soo/cost/pull/155)의 검증된 탑승객 이름 구성 요소 검색과 PR [#157](https://github.com/6Soo/cost/pull/157)의 원승인번호 기준 1:N 취소·환불 확정 표시를 포함한다. #157의 확정 링크 표시는 실제 장부 기록·환급 완료·보류 해제를 뜻하지 않는다. 중복 PR #156은 닫았으며 그 고유 부분환불 합성 시나리오는 #157 테스트에 옮겼다.

- 표적 검사 `python -m pytest webapp/tests/test_cleanup_refund_display.py tests/card_pipeline/test_partial_refund.py -q`: **47 passed**. 합성 거래 두 건 환불의 부분 합계와 전액 상쇄, 같은 `original_id`, 건수/합계/순액 UI 및 DB dump 불변을 확인했다. 항공권 이름 검색 검사는 PR #155 시점 **2 passed, 9 deselected**였다. 전체 회귀는 실행하지 않았다.
- 고정 릴리스 **964/964** 추적 파일 대조, 누락/추가/blob 불일치 0. 이전 운영 SHA `95c05343efe7695e915e42e8134b41ecc318d495`에서 교체했다. 복구 전제의 DB/열·원본 해시·복원 결합 검증과 백업/복원본 존재를 확인하고 기존 근거를 재사용했다. `WebLedger-Board` Running, 작업/프로세스 SHA 일치, loopback listener 1개, `/healthz` **200**, `/readyz` **200**, 비인증 보호 API **401**.
- 로그인 Aside에서 `/import` 소유자 화면이 표시됐다. 이번 1:N 문구는 화면 스냅샷에서 보이지 않아 실제 사례의 문구 표시 수락은 **NOT_CONFIRMED**다. 실제 환불/거래 상세를 펼치거나 원행·장부·Google을 변경하지 않았다.
- 항공권 검색은 앞선 SHA `95c0534` 운영 화면에서 읽기 전용으로 확인해 **검색 결과 없음 / 카드 0건**을 관측했다. 이후 배포된 현재 색인 generation 370은 `flight-evidence-v4-first-received`이며 스냅샷과 입력 키가 일치한다. 이미지의 두 구간 서명을 원문을 출력하지 않고 비교한 결과, 이 검증 색인에는 두 구간을 함께 가진 예약 그룹 자체가 없었다. 따라서 해당 화면 결과는 이름 토큰 부재뿐 아니라 대상 예약 근거 자체가 색인에 없음을 가리킨다. 메일이 미수집됐는지 파서가 누락했는지는 원본 확인 전에는 미확정이다. 검색 코드는 배포됐지만 첨부 항공권의 실제 결과 수락은 **PARTIAL**이다. 이 증거만으로 fuzzy matching이나 로마자 변환을 추가하지 않는다.
- PR #156은 부분환불 사례를 #157의 합성 테스트로 보존한 뒤 중복으로 닫았다. 로컬·원격 브랜치는 `main`만 남겼다. 삭제 전 refs bundle `.local-archive/branch-prune-20261027/followup-refs-before-main-only-20261027.bundle` 검증 완료, SHA-256 `C113C062EF2CBF40754A4963B9E84D3232AFBE9B25E664CED72E2D32B4FC4B07`. 기존 미추적 작업 계획 파일도 보존했다.

---

## 2026-10-27 PR #153 카카오 환불 후보 보강 운영 배포

PR [#153](https://github.com/6Soo/cost/pull/153)은 `a9626059893a02931926ca009f9d04226ffd7e60`에 `main` 병합되어 해당 SHA로 운영 배포됐다. 이 배포는 앞서 병합됐지만 아직 배포 전이던 #152의 Agoda 후보 표시 수정도 포함한다. #153은 같은 카드사·끝자리·14일 이내 원승인번호 일치 구매를 환불 화면의 검토 후보에 추가하고, 자동 금융 연결·장부 기록은 하지 않는다.

- release 963개 추적 파일 Git blob 대조: **불일치 0**. 기존 `cost-spec-deploy-20261026-evidence.json`의 복원 검증 및 live-state 보존 근거를 재사용했고, 기존 운영 SHA `4cd12adebad6ebcac110130803d35f589d1f8bb0`에서 고정 교체했다.
- `WebLedger-Board` 작업 인자와 loopback 프로세스가 새 SHA `a9626059893a02931926ca009f9d04226ffd7e60`로 일치하고 Running이다. `/healthz` **200**, `/readyz` **200**, 비인증 `/api/imports/ota` **401**.
- 로그인 상태 기존 브라우저에서 GET `/import` 후 지출 정리 화면이 표시됐다(환불 후보 패널 8개, 후보 행 26개). 이 화면에 새 원승인번호 문구는 보이지 않아 live UI에서 해당 교차 가맹점 사례가 표시됐다고 주장하지 않는다. 후보 표시 동작은 합성 테스트로 확인했다.
- #153 표적 테스트: **20 passed**, 인접 부분환불/환불 화면 보호: **35 passed**. #152 표적 묶음은 **26 passed, 2 failed**였으며, 실패한 `test_expense_cleanup.py` 두 검증은 기준 SHA `c71dbe5e0faef24fe517dcf082d6d5bcade18783`에서도 똑같이 재현됐다(**23 passed, 2 failed**). Agoda 후보 근거 테스트는 통과했고, 기준선에서 재현된 두 실패는 변경하지 않았다.
- 독립 리뷰 경로 두 곳은 인증/Windows 셸 시작 오류로 **NOT_RUN**이다. 사용자가 2026-10-27 병합·배포를 명시 지시해 진행했으며, 이를 독립 리뷰 통과로 기록하지 않는다. 운영 환불 연결·금융 장부·Google 쓰기는 수행하지 않았다.
- 사용자 요청에 따라 원격 비-main 브랜치 **53개**와 로컬 비-main 브랜치 **27개**를 정리해 `main`만 남겼다. 삭제 전 90 refs 전체를 `.local-archive/branch-prune-20261027/before-main-only.bundle`로 보존·검증했다(SHA-256 `39D87CC22029BBEB66C368FF8CD107C8341BBDD7EF4504FB18BB1AFF4DAF32CE`). PR #108은 충돌 중인 유일한 미병합 PR이었으며, 소스 브랜치 삭제 후 GitHub가 자동으로 닫았다. 별도 미추적 계획 파일은 보존했다.

---

## 2026-10-27 카드 거래의 무관한 Agoda 제외 후보 노출 수정 — 최초 병합 인계 당시 운영 배포 대기 (현재 상태는 위 기록)

PR [#152](https://github.com/6Soo/cost/pull/152) was merged to `main` as **`2762f0778c54babe54b17bc8414d49596c6f4bfc`**. It fixes the reverse-index display in `webapp/card_flow.py::_index_ota_display_candidates`: provider-only OTA rejected comparisons no longer appear against a card unless the OTA's actual `paid_on` and the card's `approval_date` are both present and same-day or within an already-approved date-lag policy. Stay dates are not treated as payment dates. The three new synthetic regressions cover missing payment date, unrelated date, and preserving same-day currency mismatch diagnostics. No matching, booking link, ledger, financial decision, or database behavior changed.

**Verification/release status:**

- GitHub commit status and PR workflow lookups returned no checks/workflow runs. No repository Actions workflow was found for this commit.
- At this initial handoff, Python/pytest had **not been run** and the last recorded production SHA was **`4cd12adebad6ebcac110130803d35f589d1f8bb0`**. The focused test and later release evidence are recorded in the newer first section above.
- At that point, the GitHub-only session could not access the Windows host, so deployment and owner-screen acceptance were pending. The current fixed-SHA release status is recorded above.
- No live data was changed in the initial handoff; the later owner-screen smoke was GET-only, and no card connection, ledger, or Google write occurred.

---

## 2026-10-27 미결 UI 통합·항공권 수신일·OTA 후보 읽기 수정

**현재 운영 SHA: `4cd12adebad6ebcac110130803d35f589d1f8bb0`**, [PR #149](https://github.com/6Soo/cost/pull/149). 앞선 #146은 #133/#138/#145의 UI·명시 예약일·환불 표시 변경을 통합했고, #147은 지출 상태 조회의 legacy 원본 대사를 제거했다. #148은 사용자 후속 승인에 따라 별도 예약일이 없는 같은 공급자/예약번호의 인증 메일 최초 수신일을 한국 날짜로 표시한다. 명시 날짜/날짜 충돌이 우선하고, 충돌·취소·stale·기존 연결의 자동 후보 차단은 유지한다. 화면은 **최초 메일 수신일 기준**으로 표시하며 공급사의 원본 생성일로 표현하지 않는다.

#148 배포 후 후보 GET 자체가 `_data()`로 원본을 다시 해석하는 대기가 드러나 이전 세션에서 `6b1b4fe`로 롤백했다. #149는 이 GET을 신선한 스냅샷/입력 지문 검사로 바꾸고, 준비 중이면 409 `OTA_SNAPSHOT_NOT_READY`와 재시도 안내를 반환한다. 실제 연결/확정·금융 보호·스키마는 바꾸지 않았다. 중단 직전 독립 검토와 동시 인수자의 추가 독립 검토에서 중요 미해결 사항 없음. 표적 후보 검사 **5 passed / 37 deselected (2.29s)**; 동시 인수자가 추가한 375px 키보드 재시도/GET-only 브라우저 검사 **1 passed / 3 deselected (5.72s)**의 유효한 근거를 재사용했다. 이전 통합·항공권 검사별 결과와 의도적 생략은 [실행 기록](superpowers/plans/2026-10-27-pending-work-release.md)에 보존한다.

릴리스 962개 추적 파일 Git blob 일치, 이전 릴리스와 검증된 복원 근거 보존, 작업/프로세스 SHA·단일 loopback listener·Board Running, health/ready 200·비인증 보호 API 401을 확인했다. 증거는 `D:/WebLedgerHost/releases/release-audit-4cd12adebad6ebcac110130803d35f589d1f8bb0.json`, `deploy-evidence-4cd12adebad6ebcac110130803d35f589d1f8bb0.json`과 같은 SHA의 task before/after XML이다. 운영 2DB/13개 보호 표 내용·스키마 해시는 최초 통합 전 기준선과 동일하다 (`.local-archive/pending-work-20261027/protection-after.json`). 실제 고객 연결/기장/배정·Google 쓰기는 실행하지 않았다.

실로그인 지출 정리에서 OTA 후보 펼침의 갱신 중 안내와 loading=false를 확인했고, 같은 후보 GET은 **665ms / 409 / OTA_SNAPSHOT_NOT_READY**로 응답했다. OTA 내역과 항공권 이름 검색 화면 이동도 성공했다. 보관 자료 읽기 전용 집계는 항공 예약 200개 중 수신일 근거 16개·UNKNOWN 184개이며 자동 후보 가능 건수와 같지 않다. 실제 기기 터치/브라우저 200% 확대는 외부 수락 대기이며 완료로 보고하지 않는다. 전체 회귀·전체 재대사 수동 실행·기존 통과 검사 반복은 생략했다.

**최초 수신일 실제 화면 수락 완료:** 정상 백그라운드 대사가 476.56초에 완료되고 2026-10-27 07:38:13 KST에 generation359 / `flight-evidence-v4-first-received` 색인이 게시됐다. 기존 Aside 소유자 탭에서 해당 색인의 취소/충돌 없는 수신일 근거 예약을 이름 하나로 검색했다. 예약 카드 1개, **최초 메일 수신일 기준** 표시 1개, 자동으로 펼친 날짜 필터 1개와 그 한국 날짜의 카드 원행 **9/9건**을 확인했다. 화면은 결제 연결을 확정하지 않는다고 명시한다. 고객 이름/예약번호/거래 원문을 Git·PR·증빙에 기록하지 않았고 선택/연결/기장은 하지 않았다. 앞선 이전 색인의 조회 차단은 정상 갱신으로 해소됐다.

신선한 색인 게시 후 지출 정리의 같은 OTA 후보 GET은 **200 / 2,473ms / 카드 후보 683행**으로 응답했다. 기존 후보 범위의 읽기 응답이며 정확 결제 수가 아니다. 지출 화면 클릭부터 관찰 완료까지 도구는 34.541초를 보고했으므로 API 시간과 화면 전환 시간을 혼동하거나 전체 화면 속도 수락으로 확대하지 않는다.

## 2026-10-27 페이지 전환 재개·프로세스 격리·실제 클릭 수락

**현재 운영 SHA: `a079700a8f513c91e87b8e2e2f54d8a2d2897748`**, PR [#143](https://github.com/6Soo/cost/pull/143). 사용량 한도로 중단된 Paseo `31f49529-12a2-494d-9fac-94bdf1090e90`의 미커밋 변경을 인수했다. 앞선 #141 장부 행 읽기 공유와 #142 지출 미리보기 여행 검증 재사용은 이미 병합됐고 인수 시 운영은 `13dcf7d`였다. 아래 과거 배포/미측정 표기는 해당 시점 이력이다.

시작 시 OTA 메일 해석이 HTTP 프로세스와 같은 Python 실행 잠금을 경쟁했다. 목록 원본 해석을 별도 자식 프로세스로 옮기고 board SQLite를 `mode=ro`/`query_only`/읽기 트랜잭션으로 열며 임시 교환 파일은 성공·시간 초과 시 정리한다. 중앙 대사 모드에서는 쓰이지 않는 legacy 예약 메일 색인 선행 생성을 생략한다. 저장 색인 코드 식별에 자식 모듈을 포함한다. 금융 판정·수동 결정·쓰기·권한·스키마 정책은 변경하지 않았다.

표적 검증 `python -m pytest webapp/tests/test_navigation_read_performance.py webapp/tests/test_ota_catalog.py webapp/tests/test_ota_booking_trip.py -q`: **41 passed in 11.48s**. 직접/자식 해석 결과·경고 일치, 합성 board/portal dump 불변, 시간 초과 자식 종료·교환 파일 정리를 포함한다. 테스트 종료 전에 snapshot 서비스를 종료하도록 fixture를 보완했다. 이후 코드 식별 목록/설명 수정에는 불필요한 재검사를 하지 않았다. 독립 읽기 전용 검토(Inkling Small Free, HEAD `f73226c`)는 Critical/Important 미해결 문제 없음이었다. 전체 pytest/E2E·전체 재대사·실제 고객 기장/배정·Google 쓰기는 수행하지 않았다.

배포 후 기존 Aside 탭에서 같은 메뉴를 실제 클릭하고 각 화면 제목·경로 및 Navigation Timing을 확인했다. 모두 HTTP 200이며 경로당 **1회 관찰**이다. 전환에는 자동화/관찰 대기가 포함되고 TTFB/DOM은 브라우저 측정이다. 최초 #139 이전과 호스트 부하·캐시가 같다는 통제 실험은 아니며, 카드 첫 클릭은 최초보다 느려 전체 화면의 일괄 개선을 주장하지 않는다.

| 메뉴 | 최초 전환 | 최종 전환 | 최종 TTFB | 최종 DOM 준비 |
| --- | ---: | ---: | ---: | ---: |
| 카드 전체 내역 | 1.440초 | 3.391초 | 1.681초 | 1.930초 |
| OTA 내역 | 16.795초 | 1.001초 | 0.494초 | 0.624초 |
| 영수증 처리 | 0.791초 | 0.613초 | 0.145초 | 0.260초 |
| 여행 장부 | 2.307초 | 2.269초 | 1.806초 | 1.911초 |
| 지출 정리 | 23.768초 | 2.616초 | 2.210초 | 2.328초 |

릴리스 957개 추적 파일의 Git blob이 모두 일치했다. 이전 `13dcf7d` 릴리스와 기존 검증된 백업/복원 경로를 보존했다. Board Running·단일 loopback listener·task/process/표식 SHA 일치, `/healthz`·`/readyz` 200 및 비인증 `/api/imports/ota` 401을 배포 시 한 번 확인했다. 근거는 `D:/WebLedgerHost/releases/deploy-evidence-a079700a8f513c91e87b8e2e2f54d8a2d2897748.json`, 같은 SHA의 `release-audit-*.json`과 `D:/WebLedgerHost/config/board-task-before/after-*.xml`이다. 운영 DB 2개의 카드·장부·사용자 결정·연결 등 13개 표 내용/스키마 해시는 배포 전후 동일하다. 원문 없는 측정 및 보호 근거는 `.local-archive/navigation-resume-20261027/browser-after.json`과 `protection-before/after.json`에 보존했다.

**현재 요청 범위 COMPLETE:** 중단된 최적화의 검토·병합·고정 SHA 배포·최소 운영 검사·다섯 메뉴 실제 클릭을 완료했다. 평균/백분위·모바일/200% 확대·기존 다른 PR 수락은 이번 검사 범위 밖이다. 이전 세션의 '배포 후 속도 미측정' 차단은 해소됐다. 무인 감시·전체 성능 최적화라는 새 과제로 확대하지 않는다.

## 2026-10-27 OTA 제공자 경계·금액 비교·전액 환불 보류 수정

PR [#135](https://github.com/6Soo/cost/pull/135)을 병합하고 **`909e4ad4ffc3ca4786d61a8b01686101406c79c7`**을 운영에 배포했다. 타사 OTA는 금액 비교 전에 제외하며 Trip의 무관 가맹점 허용 예외를 관련 표기/기존 승인 별칭으로 제한했다. 정확 매칭·후보 검색·날짜 없는 추론·예정 결제 검증에 같은 경계를 적용한다. 이미 확정한 수동/고정 관계와 명시 날짜 전체 카드 탐색은 보존한다. 화면은 카드 청구액과 OTA 원문 금액/통화를 함께 표시하고, 금액 불일치 비교를 유효 결제 후보로 집계하지 않는다. matcher 버전은 snapshot input key에 포함한다.

전액 환불 건은 이미 카드 원승인 연결과 순액 0이 확인됐지만 원결제의 자동 `trip_needed`가 묶음 기록을 막았다. 기존 환불 탭 정책에 맞춰 분류된 전액 상쇄 원결제의 자동 여행 보류만 제거했다. 원본/금액·스키마·기장 코드는 바꾸지 않았고 수동 보류·금융 오류·부분/초과 환불·불완전 batch 보호를 유지한다. 실제 운영 기장/배정/보류 해제/Google 쓰기는 실행하지 않았다. 원본 비교 상세는 Git 밖 `.local-archive/ota-provider-refund-20261027/readonly-diagnosis.json`에 있다. 해당 Trip 카드 원본에는 외화 금액/통화가 없어 임의 환산으로 정확 연결하지 않는다.

검증은 변경 범위에 한정했다. 새 provider/cleanup/refund 검사 36 passed; 인접 matching/refund 경계 149 passed와 구 정책의 Agoda→Trip 허용 fixture 1개 수정 후 focused 통과; cleanup/index 20 passed; backend/snapshot action 23 passed; 추가 provider/추론 34 passed; exact/예정 결제 35 passed와 예전 무관 Trip 허용 기대 2개 수정 후 해당 2 passed. 각각의 실행 결과이며 하나의 전체 회귀 통과로 합산하지 않는다. 독립 검토는 추론/예정 검증의 우회 경로를 발견했고 RED→GREEN 수정 후 중요 미해결 사항 없음으로 마쳤다. 전체 회귀·대량 재처리는 생략했다.

릴리스 추적 파일 953개가 Git blob과 모두 일치하고, Board Running·단일 loopback listener·task/process/표식 SHA 일치, health/ready 200·비인증 OTA API 401이었다. 이전 `f5eb44e` 릴리스, 작업 before/after XML과 검증된 복원 근거를 보존했다. 배포 증거는 `D:/WebLedgerHost/releases/deploy-evidence-909e4ad4ffc3ca4786d61a8b01686101406c79c7.json`, `release-audit-909e4ad4ffc3ca4786d61a8b01686101406c79c7.json`이다. 운영 카드·장부·사용자 결정·연결 등 DB 2개의 13개 표 내용/스키마 해시는 배포 전후 동일했다. 집계만 담은 결과는 `.local-archive/ota-provider-refund-20261027/protection-before.json`과 `protection-after.json`에 보존했다.

**화면 수락 PARTIAL:** 배포 전 기존 Aside 탭은 524 페이지였다. 배포 뒤 reload는 navigation timeout, 이어 읽기 전용 OTA GET 시도도 요청 전 `CDP command timeout: Page.enable`로 실패했다. 이를 서버 응답 실패나 화면 검증 성공으로 해석하지 않는다. 기존 로그에는 175~264초의 snapshot 계산 이력이 있었고 새 정책 배포 후 refresh 시작을 확인했다. 최종 로그인 화면/375px 및 새 세대의 실제 후보 표시는 `NOT_TESTED_TOOL_TIMEOUT`이다. 다음에는 Aside 연결이 응답할 때 `/import`의 Trip 타사 후보 제거·두 금액 표시와 전액 환불의 준비 상태만 확인한다. 실제 고객 기장이나 전체 재처리를 재개 명령으로 실행하지 않는다.

## 2026-10-27 환불 검토의 가맹점 원결제 비교

PR [#132](https://github.com/6Soo/cost/pull/132)을 병합하고 **`f5eb44ecfea39ed143cbbc9cf053ae75f87888c0`**을 운영에 배포했다. 미연결 환불에 같은 카드·가맹점의 선행 결제 후보를 날짜·금액·승인번호·기록 여부와 원문 링크로 표시한다. 금액이 다른 부분 환불 후보도 포함하고 카카오 택시의 가승인/선승인/실요금 표기 차이는 비교 검색에만 사용한다. 확정 연결과 검색 후보는 구별하며, 일반 항목/여행 보류 문구를 환불 설명에 반복하지 않는다. 가맹점 전체 검색 링크와 기본 펼침을 제공한다.

사용자가 지정한 환불 2건과 비교 결제 2건은 운영 DB를 `mode=ro`로 조사했다. 같은 날짜·카드·가맹점의 동일 금액 결제 후보와, 가승인 취소에 대응할 수 있는 금액이 다른 실제 결제를 찾았다. 후자는 원문이 미매입 취소여서 부분 환불로 단정하지 않는다. 원승인번호가 없는 상태에서 금융 연결·차감·기장·보류 해제는 하지 않았다. 상세 원문/식별자는 Git에 올리지 않고 `.local-archive/refund-merchant-20261027/readonly-diagnosis.json`에 보존했다.

표적 검사 `python -m pytest webapp/tests/test_cleanup_refund_display.py webapp/tests/test_expense_cleanup.py -q -k 'refund_display or merchant_comparison or refund_pair'`는 **8 passed, 24 deselected**였다. 기존 연결/기록 표시와 다른 카드·미래 결제 제외, 금액이 다른 가맹점 후보, 합성 DB 전체 dump 불변을 확인했다. 금융 matcher·쓰기·스키마는 변경하지 않았고 전체 회귀·대량 재처리는 생략했다. diff/조회 경계 검토와 Git whitespace 검사를 완료했다.

릴리스 추적 파일 951개 모두 Git blob과 일치한다. `WebLedger-Board` Running, loopback listener 1개 및 task/process/표식 SHA 일치, health/ready 200·비인증 OTA API 401을 확인했다. 기존 `31296e5` 릴리스와 검증된 복원 근거를 재사용·보존하고 Board 작업 action의 SHA만 변경했다. 근거는 `D:/WebLedgerHost/releases/deploy-evidence-f5eb44ecfea39ed143cbbc9cf053ae75f87888c0.json`, `release-audit-f5eb44ecfea39ed143cbbc9cf053ae75f87888c0.json` 및 같은 SHA의 before/after 작업 XML이다. 운영 DB/원본/Google 쓰기와 새 마이그레이션은 수행하지 않았다.

**화면 수락은 PARTIAL:** 로그인 Aside 브라우저 reload는 navigation timeout, 같은 탭의 범위를 좁힌 재관찰은 `CDP command timeout: Page.enable`이었다. 최종 화면/375px은 `NOT_TESTED_TOOL_TIMEOUT`이며 health 응답을 화면 수락으로 해석하지 않는다. 브라우저·앱 재시작/복구/재설치와 반복 스모크는 하지 않았다. 다음 작업은 Aside가 응답할 때 `/import`의 첫 두 환불 카드에 후보/원문/검색 링크가 보이는지, 375px에서 넘치지 않는지만 확인한다. 실제 금융 연결은 추가 원승인/이용 근거 확인 전 계속 미확정이다.

## 2026-10-26 일별 카드 조회·모바일 경계 후속 배포

**현재 운영 SHA는 `31296e5926e4a762aae29167f28c85d83317218b`다.** PR #129(`ea90b85`)는 항공권 상세의 직접 지정 날짜 필터와 owner 전용 `GET /api/cards/transactions/day`를 구현했다. 지정 날짜는 예약일/연결 근거로 확정하지 않는다. 읽기 전용 SQLite 트랜잭션에서 허용 필드·지문·총건수·커서 페이지를 계산하며, 원행 변경은 409로 거부한다. 취소/환불/중복/오류를 제외하지 않고 원행 여행 ID와 표시 여행 ID를 구분한다. 권위 있는 예약일이 없는 자동 후보 경로를 임의로 만들지 않았다.

PR #130(`31296e5`)은 운영 프레임에서 발견한 760px 직전의 메뉴 공백을 수정했다. 기존 CSS의 `max-width:759px`가 거짓인데 `width < 760px`는 참인 상태에서 메뉴가 숨겨졌다. 759.98px 근사 수정도 잔여 공백이 있다는 독립 검토 P2를 수용해 최종 7개 화면은 정확한 `@media(width < 760px)`를 사용한다. 업무 자바스크립트·쓰기 로직 변경은 없다.

검증 근거:

- 일별 데이터/API 표적 검사: `python -m pytest webapp/tests/test_card_transactions.py -q -k day_filter` 결과 3 passed. 1,005건 전수 페이지, 같은 금액/부호/보호 상태, DB bytes 불변, 날짜/커서, 401/403/no-store/409와 표시 여행 필드를 확인했다.
- 항공권 신규 UI: `-k manual_date_filter` 1 passed. 명시 날짜·원 날짜 유지·오류/표시 여행·변경 시 목록 제거를 확인했다. 인접 항공권 세 파일은 24 passed와 비동기 count 검사 1 failed였으며, 해당 검사를 실제 결과를 기다리는 expect로 고친 뒤 `-k browser_name_search`가 1 passed였다. 이후 제품 코드 변경은 추가 표시 여행 필드뿐이고 해당 신규 검사 4건은 다시 통과했다. 하나의 최종 전체 실행이 25 passed였다고 보고하지 않는다.
- 모바일 경계/인접 스크롤: `python -m pytest webapp/tests/test_mobile_breakpoint.py webapp/tests/test_ledger_design.py -q -k 'fractional_mobile or document_stays_in_viewport'` 결과 최종 3 passed, 5 subtests passed. CSSOM 범위 계약과 click/Escape 및 760px 경계를 확인했다. 헤드리스의 iframe 반올림과 운영 Windows의 미디어 쿼리 계산은 달라 실제 운영 재현을 별도 근거로 유지한다.
- 두 PR 및 후속 수정은 고정 커밋 독립 검토를 통과했다. 원본/Google/운영 DB 쓰기와 전체 회귀는 하지 않았다.

배포는 기존 SHA 고정 절차를 재사용했다. 릴리스 파일 951개 전부의 경로와 Git blob이 일치했고, `WebLedger-Board` Running, loopback listener 1개, task/process/표식 SHA 일치, health/ready 200 및 비인증 OTA API 401을 확인했다. 새 일별 API도 비인증 401이고, 로그인 브라우저의 명시 날짜 `2050-01-01` GET은 200/no-store/USER_DATE_FILTER/0건을 반환했다. 근거 파일은 `D:/WebLedgerHost/releases/deploy-evidence-31296e5926e4a762aae29167f28c85d83317218b.json`, `release-audit-31296e5926e4a762aae29167f28c85d83317218b.json` 및 해당 SHA의 before/after 작업 XML이다. 이전 `85f008b` 릴리스와 검증된 복원 근거는 보존했다.

이전 `/import` 관찰 timeout은 같은 탭 재관찰에서 해소됐다. `85f008b` 운영에서 카드 20개, 다크 body/nav(15,23,42), 카드/입력 배경(30,41,59), 입력 글자(248,250,252), 라이트 전환(248,250,252/흰 카드)을 확인했다. 이 색상 경로는 후속 코드에서 바뀌지 않아 재사용한다. 최종 `31296e5`의 항공권·오제 장부 운영 동일 출처 프레임 759px에서는 모바일 미디어/메뉴 표시, 닫힌 nav 오른쪽=0, 테마 버튼 1개·44×44·뷰포트 안, 가로 넘침=0을 확인했다. 집계만 있는 로컬 근거는 Aside 세션 `2026-10-26_KxP6GaY8qDFDZEPL/artifacts/cost-final-boundary-smoke.json`에 있다. 임시 프레임은 제거했다.

**남은 실제 의존성:** 본창/실기기의 모바일·터치 수락과 실제 브라우저 200% 확대는 미검증이다. Control+=도 전면 탭에서 viewport 1440/DPR 1.25를 바꾸지 못했으며 CSS zoom이나 운영 프레임으로 대체하지 않는다. 실제 예약 결과에서 날짜 필터를 여는 수락은 사용자에게 앱 안에서 조회를 요청했다. Aside가 개인자료 파일 읽기를 `Path escapes Project and session roots`로 차단했으므로 복사·다른 경로·별도 API로 우회하지 않았다. 해당 UI는 합성 검사와 실제 API 검사만 통과한 상태다.

권위 있는 예약일은 현재 파서/인덱스에 없고, 보존된 인증 항공권 메일 280건의 지원 명시 표기 집계에서도 0건이었다. 이는 모든 가능한 다른 표현까지 없다는 증명이 아니다. 원문·고객명·예약번호는 출력/복사하지 않았다. 검증된 예약일 원천이 제공되기 전 자동 동일 날짜 후보는 계속 보류한다. 개인정보·금융 보호를 줄여서 전체 완료로 판정하지 않는다.

## 2026-10-26 미결 UI 구현 및 통합 릴리스 (이전 배포)

**현재 운영 SHA: `85f008baddd9e6a181018b6b7d4bd1ffded9ea82`**. 후속 본문 테마 수정 PR #127도 배포됐다. 파일 949개 전부 Git blob 일치, 작업 Running, loopback listener 1개 및 프로세스 SHA 일치, health/ready 200과 비인증 OTA API 401을 확인했다. 근거는 `D:/WebLedgerHost/releases/deploy-evidence-85f008baddd9e6a181018b6b7d4bd1ffded9ea82.json`, `release-audit-85f008baddd9e6a181018b6b7d4bd1ffded9ea82.json`, `D:/WebLedgerHost/config/board-task-before/after-85f008baddd9e6a181018b6b7d4bd1ffded9ea82-attempt2.xml`이다.

후속 배포 뒤 `/import` 브라우저 reload 관찰은 navigation timeout, 같은 탭 재관찰은 `CDP command timeout: Page.enable`로 실패했다. 브라우저 탭 목록에는 같은 target과 지출 정리 제목이 남아 있다. 이 구체적인 이상에 한해서 추가한 loopback health GET은 200이었다. 런타임 장애나 화면 수락 성공 중 어느 쪽으로도 단정하지 않으며 **최종 SHA의 `/import` 실제 색상 스모크는 `NOT_TESTED_TOOL_TIMEOUT`**이다. 이전 검증된 `0a7c7a2` 릴리스와 작업 XML을 보존했고, 브라우저·앱 재시작/복구/재설치는 하지 않았다.

PR #117은 `db2bbdb`(스크롤), #119는 `e3fe461`(항공권 예약 확인), #126은 `0a7c7a2`(수동 테마)로 정상 병합했다. `0a7c7a2724659e5b6732a73b0a959f9773ab699f`를 운영에 배포해 작업·listener·릴리스 표식 SHA 일치, health/ready 200 및 비인증 OTA API 401을 확인했다. Git archive의 추적 파일 949개 전부를 Git blob과 비교해 차이가 없었다.

첫 배포 시도는 예약 작업을 중지해도 이전 Python listener가 남아 `OLD_LISTENER_STILL_RUNNING`으로 중단했고 기존 XML을 복원했다. 두 번째 시도는 그 listener의 포트·명령·생성 시각·이전 SHA를 재검증한 뒤 해당 서비스 프로세스만 종료하고 전환했다. 작업 XML은 릴리스 참조 두 곳만 변경했다. 기존 검증된 백업/복원 근거 `D:/WebLedgerHost/data/backups/cost-spec-deploy-20261026-evidence.json`과 이전 릴리스를 재사용·보존했다. 다른 작업과 브라우저 세션을 중지하거나 DB/Google/원본을 변경하지 않았다.

표적 검사는 스크롤 1 passed와 5 너비 subtests passed, 항공권 세 파일 24 passed, 테마 3건 및 셸 11건이 통과했다. 항공권 독립 리뷰에서 충돌 근거와 중복/파싱 오류/원본 충돌 카드의 연결 표시 누락을 발견해 RED 확인 후 수정·재검토했다. 권위 있는 예약일 필드는 원천에 없으므로 출발일·결제일·메일일을 대용하지 않는다. 테마가 본문에 헤더 행을 추가한 뒤 영향받는 스크롤 검사도 통과했다. 기존 전체 검사에서 기준 main에도 재현된 무관한 분기 그룹 실패는 다시 실행하거나 수정하지 않았다.

로그인된 Aside의 1440×900 CSS 뷰포트에서 항공권 새 화면, 아이콘 버튼 하나, 실제 다크/라이트 body/nav 색상과 페이지 간 유지, 카드 전체 내역과 지출 정리의 새 버튼을 확인했다. 합성 이름 조회는 배포 직후 자료 갱신 중에는 자료 없음, 갱신 완료 뒤에는 예약 없음 안내를 표시했다. 당시 OTA 읽기 전용 상태는 ready, stale=false, refreshing=false, 오류 없음이었다. 오제 본문은 마지막 위치 4304px에 도달했고 추가 휠 뒤에도 root scroll=0이었다. 수입 패널은 열리고 35행이 표시됐다. 볼드 후보는 0건이며 기존 지출 검증 보호를 해제하지 않았다. 고객 이름·예약번호·원문은 검증 결과에 출력하지 않았다.

이 운영 확인에서 지출 정리 본문이 고정 밝은 색인 결함을 발견했다. 후속 PR #127(`85f008baddd9e6a181018b6b7d4bd1ffded9ea82`)은 지출 정리의 본문·카드·입력창, 수입 장부의 표/설정, 수동 지출 입력창, 유지관리 경고의 CSS만 공통 토큰으로 연결한다. 실제 CSS 검사에 지출 정리·수입 장부·유지관리를 추가해 RED 후 GREEN을 확인했고, `python -m pytest webapp/tests/test_manual_theme.py webapp/tests/test_site_shell.py -q`는 14 passed였다. 독립 검토에서 중요 결함은 없었다. 합성 구조에 실제 CSS를 적용한 검사이므로 모든 실제 내부 요소를 검사했다고 확대 해석하지 않는다.

**남은 수락:** 운영 모바일 뷰포트 및 브라우저 200% 확대는 `NOT_TESTED`다. Aside의 `page.setViewportSize`는 지원되지 않았고 Control+Equal 입력 전후 실제 viewport/DPR도 같았다. 합성 다섯 너비/CSS zoom 검사를 실제 브라우저 확대 수락으로 대체하지 않는다. 전체 회귀·대량 재대사·DB/Google/원본 쓰기·불필요한 새 백업/복원·반복 전체 스모크는 하지 않았다.

## 2026-10-26 PR #120 사이드메뉴 스타일 런타임 확인

PR [#120](https://github.com/6Soo/cost/pull/120) 병합 SHA `78cf8b8ab2cb1078fc2a8f2b64761672efbfa73e`가 현재 운영 런타임에 반영된 상태임을 읽기 전용으로 확인했다. `WebLedger-Board` 작업 정의와 127.0.0.1:8751 listener의 실행 인자는 모두 `D:/WebLedgerHost/releases/78cf8b8ab2cb1078fc2a8f2b64761672efbfa73e` 및 `D:/WebLedgerHost/bin/launch_web_ledger.py`를 가리켰고, 릴리스의 `DEPLOYED_COMMIT`도 같은 SHA다. listener는 1개였으며 `/healthz`와 `/readyz`는 각각 200을 반환했다.

릴리스 파일 944개를 해당 Git SHA의 추적 경로 944개와 대조해 경로 차이가 없음을 확인했다. `webapp/ledger_design.py`, `webapp/site_shell.py`, 두 표적 테스트 파일, `tools/start_web_ledger_host.ps1`, `tools/launch_web_ledger.py`의 Git blob 해시가 모두 일치했다. 이 검증 세션은 예약 작업을 변경하거나 서비스를 재시작하지 않았다. 이 SHA에 해당하는 `board-task-before/after` XML은 호스트 설정에서 찾지 못했으므로 작업 정의 변경 이력은 `NOT_FOUND`로 남긴다.

PR #120의 표적 명령 `python -m pytest webapp/tests/test_site_shell.py webapp/tests/test_ledger_design.py -q`는 앞선 검증에서 34 passed, 2 subtests passed, 1 failed였다. 유일한 실패는 여행 그룹 기대값 4와 실제 2의 차이였고, 기준 `main`에서도 동일하게 재현되어 PR 변경으로 인한 실패가 아님을 확인했다. **운영 로그인 브라우저의 변경 화면 스모크는 `NOT_RUN`**이다. 현재 세션에 Aside 브라우저 연결이 없어 스타일 표시를 실제 로그인 화면에서 확인하지 않았다. health/ready 응답을 화면 수락으로 간주하지 않는다.

이번 확인은 로컬 HTTP GET, 작업 정의·프로세스 인자·릴리스 파일 읽기만 수행했다. 운영 DB, 카드 원본, Google 자료, 스케줄 작업과 보호 설정을 변경하지 않았다. 실제 운영 런타임 SHA는 현재 `78cf8b8`; `36f6cb3`은 이전 릴리스 이력이다.

## 2026-10-26 OTA 카드 후보 응답 최적화 배포

통합 커밋 `36f6cb32ac09805079e5ddb5641fe01032088fa7`를 `origin/main`에 일반 push하고 `D:/WebLedgerHost/releases/36f6cb32ac09805079e5ddb5641fe01032088fa7`로 배포했다. Git archive의 추적 파일 943개를 풀어 파일 수를 대조했고, `ota_payment_review.py`, 해당 표적 검사, 호스트 실행기, 런처, 장부 화면, 공통 디자인, 이 문서 등 핵심 파일 7개의 Git blob 해시가 일치했다. `DEPLOYED_COMMIT` 표식도 같은 SHA다. 기존 릴리스 `47264123835d1a576f17fa8d27148bddee69a3f0`는 복구 대상으로 보존했다.

`WebLedger-Board` 작업 XML은 이전·변경 후 파일을 `D:/WebLedgerHost/config/board-task-before-36f6cb32ac09805079e5ddb5641fe01032088fa7.xml` 및 `board-task-after-36f6cb32ac09805079e5ddb5641fe01032088fa7.xml`에 보존했다. 작업 정의와 127.0.0.1:8751 listener는 새 SHA를 가리키며 작업 상태는 Running이다. `/healthz`와 `/readyz`는 200, 비인증 `/api/imports/ota`는 401이다. `WebLedger-SourceRefresh`는 Running, `WebLedger-GoogleAuthority`와 `WebLedger-MailCollect`는 Ready다.

배포 전 복구 가능성은 기존 검증 증거 `D:/WebLedgerHost/data/backups/operational-20261025T173423505753Z/` 및 `cost-spec-deploy-20261026-evidence.json`을 재사용했다(DB 5개·보호 파일 59개, 별도 복원 비교 및 원본 불변 확인). 새 DB 복사·마이그레이션·Google 쓰기·가져오기·동기화는 없었다. OTA 화면의 로그인 브라우저 확인은 Aside의 기존 탭 연결이 응답하지 않고 새 탭이 빈 화면을 반환해 **NOT_RUN**이다. 이를 성공으로 처리하지 않으며 V21 전체 화면 수락은 계속 PARTIAL이다.

`webapp/tests/test_ota_payment_review.py` 표적 검사는 39 passed였고, `ota_payment_review.py` 및 테스트 파일의 `py_compile`은 오류 없이 완료됐다. OTA 응답 최적화 외의 사용자 화면 수락 및 `0630_오제` 과거 표시 실패 원인은 이 배포로 완료 처리하지 않는다.

# 현재 운영 상태

## 2026-10-26 COST UI 명세 구현 릴리스

PR [#114](https://github.com/6Soo/cost/pull/114)은 `a39fc1370218080f053657c687103033efbeead7` 기준으로 2026-10-25 UTC 17:33경(2026-10-26 KST 02:33경) 병합됐고, 런타임은 `47264123835d1a576f17fa8d27148bddee69a3f0` 릴리스에서 실행한다. 새 릴리스는 Git 아카이브에서 만들었으며 추적 파일 942개와 대조했고 핵심 애플리케이션 파일 7개의 Git blob 해시가 일치했다. `WebLedger-Board` 작업 정의의 원본 XML과 전환 후 XML을 복구 사본에 보존했다. 기존 릴리스 `d4c5934de07543e1c27232dbd53b297f2d8fa387`도 유지했다.

전환 전 복구 검증은 `D:/WebLedgerHost/data/backups/operational-20261025T173423505753Z/`에 보존하며 요약 결과는 `D:/WebLedgerHost/data/backups/cost-spec-deploy-20261026-evidence.json`에 있다. SQLite DB 5개와 보호 파일 59개를 복사해 별도 복원했고, 원본·복사본 표/열 상태, 파일 해시, 복원 바인딩이 모두 일치했다. 원본 상태는 검사 전후 동일했다. 비밀 파일 복사, 요청 재생, 서버 복원 시작, 실제 가져오기는 없었다. 백업 중 서비스를 중지하지 않았다.

전환 후 `WebLedger-Board` 작업은 Running이며 task action, 127.0.0.1:8751 listener의 프로세스 인자와 `DEPLOYED_COMMIT` 표식이 새 SHA와 일치했다. 로컬 `/healthz`와 `/readyz`는 각각 200, 비인증 `/api/imports/ota`는 401이었다. `WebLedger-SourceRefresh`는 Running, `WebLedger-GoogleAuthority`와 `WebLedger-MailCollect`는 Ready였다. Google 직접 쓰기와 운영 거래·장부 변경은 하지 않았다. PowerShell `Invoke-WebRequest`는 로컬 요청에서 NullReferenceException을 냈고, 같은 경로를 기본 `curl.exe`로 확인해 위 응답을 얻었다. 운영 터널 설정에서 hostname을 찾지 못해 외부 URL 확인은 하지 않았고, 로그인 상태 브라우저의 화면 수락도 확인하지 않았다.

운영 로그인 브라우저의 실제 화면별 UI 수락은 여전히 미검증이고 `0630_오제` 원인도 `ROOT_CAUSE_UNVERIFIED`다. 개발 큐와 현재 인계의 PARTIAL 상태를 완료로 해석하지 않는다.

## 2026-10-26 읽기 전용 런타임 재확인

운영 호스트의 실행 중인 `WebLedger-Board` 작업 인자와 8751 포트 listener는 모두 `D:/WebLedgerHost/releases/d4c5934de07543e1c27232dbd53b297f2d8fa387`를 가리켰고, 해당 release의 `DEPLOYED_COMMIT`도 같은 SHA였다. 따라서 아래 2026-10-25 기록의 `1fcbc1ee60809fd10c7764cd8f93aeaa3701a608`은 그 시점의 배포 기록이며, 2026-10-26 현장 runtime은 `d4c5934de07543e1c27232dbd53b297f2d8fa387`이다. 이번 재확인은 실행 경로와 표식만 읽었으며 health/ready, 로그인 브라우저, DB 내용은 확인하지 않았다.

## 2026-10-25 기록: 지출 정리 중앙 상태 표시 배포 완료

사용자의 병합·배포 추가 승인으로 [PR #100](https://github.com/6Soo/cost/pull/100)을 병합했다. **실제 runtime은 `1fcbc1ee60809fd10c7764cd8f93aeaa3701a608`**이며 `D:/WebLedgerHost/releases/1fcbc1ee60809fd10c7764cd8f93aeaa3701a608`에서 실행한다. 전환 시각은 2026-10-24 22:52 KST다. 이후 문서 전용 main 커밋은 재배포하지 않는다. 아래 이전 배포 절의 runtime은 당시 이력이다.

release 파일 925개를 archive와 대조했으며 launcher와 호스트 설정은 보존했다. 기존 표적 검사 46건의 유효한 근거를 재사용했다. 복구 근거는 `D:/WebLedgerHost/data/backups/expense-cleanup-20261024T225203/`의 `deployment.json`, `restore-evidence.json`, `protection-result.json`이다. DB 5개·보호 파일 59개를 백업하고 별도 복원해 비교했다. 배포 후 프로세스 생존 정보 외 기존 DB 표·schema와 보호 자료 보존 검사가 통과했다. 실제 고객 거래·기장·Google 쓰기는 0건이다.

배포 당시 외부 `/healthz`·`/readyz`는 200, 비인증 `/api/imports/ota`·`/import`는 401이었다. 초기 urllib 요청의 403·시간 초과 뒤 네이티브 curl로 확인한 최종 결과이며 초기 실패를 성공으로 바꾸어 해석하지 않는다. Aside의 기존 소유자 세션에서도 지출 정리 화면과 새 조회 안내, 중앙 근거 갱신 중 안내, 여행 권위 보류, 원결제 연결 안내를 확인했다. 버튼 제출·여행 변경·실제 참가자 저장은 하지 않았다. Board·SourceRefresh는 Running, MailCollect·GoogleAuthority는 Ready이며 모두 Enabled로 복구했다. 이 기록을 위해 검사·재시작을 반복하지 않았다.

표시 복구는 완료됐지만 A/B의 검증 결제 사건과 여행 권위, C 원결제의 여행 보류는 남아 있다. [거래별 진단](expense-cleanup-ota-diagnosis-20261024.md)을 따르며 배포를 미결 거래 처리 완료로 보고하지 않는다.

## 2026-10-24 보존된 Trip.com 예약 관측 추가

기존 Aside 직접 확인 원문 4건을 운영 OTA 근거 DB에 안전하게 추가했다. 이용 완료 숙박 2건과 취소 숙박 2건이며 카드 결제·환불 연결이나 장부 기장 완료를 뜻하지 않는다. 백업·별도 복원, 사본 시험, 기존 행과 관련 없는 표 보존, 반복 수집 무변경, 적용 직전 기준선 일치와 실제 추가 후 integrity 검사를 통과했다. 복구 경로는 `D:/WebLedgerHost/data/backups/trip-observations-20261024T175631/`, 로컬 결과는 `.local-archive/spec-completion/trip-observations-applied-result.json`이다. 이미 적용했으므로 추가 스크립트를 반복하지 않는다.

board 전체 상태와 기존 장부는 같고 Google 쓰기도 0건이다. MailCollect를 원래 Enabled/Ready로 복구했으며 코드 배포·서버 재시작은 하지 않았다. 사용자가 직접 로그인한 다음 메일함은 Aside 접근을 확인했다. 85,621원 카드 2건은 개별 결제 연결과 검증 여행 근거가 더 필요하며 환율 추정만으로 확정하지 않았다. 자세한 잔여 상태는 [현행 인계 0.11절](COST_V3_CURRENT_HANDOFF.md#011-2026-10-24-미결-사항-처리)을 따른다.

다음 메일에서 09-25 결제 완료 안내 2건의 예약번호·각 JPY 9,737을 기존 예약 2건과 대조했다. 첨부 영수증의 VISA 카드 끝자리는 미결 카드 2건 모두와 같았다. 개별 대응·원화 청구액·해당 숙박 기간의 검증 여행은 확인되지 않아 결제 확정 링크와 추가 기장을 만들지 않았다. 메일·영수증 원문은 로컬에만 보존하며 Git에는 올리지 않는다.

## 2026-10-24 항공권 운영 연결 보완

**최종 runtime은 `d9c5adcbd6d5bce52229a218535283e841567e5a`다.** [PR #96](https://github.com/6Soo/cost/pull/96)은 launcher의 명시 활성화·영구 DB, 화면 API의 기존 보호 토큰 기본값, 원본 식별자와 내용 지문이 포함된 최소 승객 색인을 연결했다. 후보 조회는 신선한 결과만 사용하고 기능을 꺼도 기존 연결 DB를 백업한다. 실제 참가자 선택·예약 정본·금융·Google 쓰기는 수행하지 않았다.

파일 921개 대조와 launcher 일치, DB 5개·보호 파일 59개 백업·별도 복원을 확인했다. `flight_passengers.enabled=true`만 허용한 설정 변경이며 다른 보호 상태는 같았다. 복구 경로 `D:/WebLedgerHost/data/backups/flight-host-20261024T165551/`에 기존 launcher/설정을 보존했다. health/ready 200·비인증 화면/후보/저장 경로 401이었으며 generation 253의 색인 v2와 snapshot key 및 항공 예약 근거 177건·승객 표기 67개의 최소 검증 필드를 확인했다. 실제 고객 연결 수나 로그인 화면 검증 결과로 해석하지 않는다.

후속 사용자 지시로 Aside의 기존 소유자 세션에서 항공권 후보 페이지의 실제 표시까지 확인했다. 새 비밀번호 조회·실제 참가자 선택·저장은 없었다. 당시 다음 메일 로그인 차단은 이후 사용자의 직접 로그인으로 해결됐다.

미결 지출 53건은 복사본에서 23건 재분류·기록 0이었다. 원문과 기존 회계는 보존됐지만 항목 공란이 늘어 운영에는 적용하지 않았다. [현행 인계 0.11절](COST_V3_CURRENT_HANDOFF.md#011-2026-10-24-미결-사항-처리)에 정확한 보호 사유와 사용자 인증/추가 근거 경계를 기록했다.

## 2026-10-24 미결 검사 수정과 OTA 통합 출처 보존

[PR #95](https://github.com/6Soo/cost/pull/95)를 main `56f1a976148df89fa25233af3fff55e27e643e49`로 병합하고 같은 SHA의 release에 배포했다. 통합 OTA 읽기에서 원래 포털 locator를 사용해 출처·관측 ID를 보존하며 파서 버전은 7이다. 명시 lineage 설정도 통합 후보 manifest에 유지한다. 카드 금액·사용자 확정·장부 쓰기·스키마는 변경하지 않았다.

archive와 release 파일 921개를 대조했다. 복구 근거 `D:/WebLedgerHost/data/backups/toyoko-reservation-20261024T164250/`에서 DB 5개·보호 파일 59개의 백업·별도 복원과 배포 후 보존을 확인했다. 새 실행 경로를 검증했고 외부 healthz/readyz 200·비인증 OTA/예약 관계 preview 401을 한 번 확인했다. Board·SourceRefresh는 Running, GoogleAuthority·MailCollect는 Ready이고 모두 Enabled다. 이후 문서만 변경하면 재배포하지 않는다.

기존 비브라우저 실패 7건을 원인별 수정해 표적 통과했다. 원문 충돌·동일 record ID의 다른 포털 분리 및 명시 lineage를 포함한 인접 검사도 통과했다. 카드 검색 브라우저 검사는 접힌 영역을 먼저 열도록 고쳤고 구문 검사와 이전 Aside 근거를 재사용했다. 전체 pytest와 Playwright는 실행하지 않았다.

실제 등록 여행 두 건의 참가자 API 응답은 각각 후보 0명·1명이며 HTTP 200과 최소 필드·revision·비공개 비캐시 응답을 확인했다. 실명·예약 식별자·토큰을 출력하거나 Git에 저장하지 않았고 실제 참가자 연결과 예약 정본 쓰기는 수행하지 않았다. 미결 거래의 후속 처리는 [현행 인계 0.11절](COST_V3_CURRENT_HANDOFF.md#011-2026-10-24-미결-사항-처리)을 따른다.

## 2026-10-24 토요코인 예약 관계 분리 운영 배포

**최종 운영 SHA는 `3a94dbe589b9f9fbb9cb2b36774c08b9bbb1cf24`다.** [PR #93](https://github.com/6Soo/cost/pull/93)은 아래 첫 배포에서 발견한 기본 검토의 무관한 과거 예약 노출을 한 조건으로 줄였다. 관계·후보가 없는 예약만 기본 검토에서 제외하며 중앙 결과·전체 예약 목록·확인된 관계와 취소·충돌 보류는 보존한다. 최종 release의 파일 921개를 archive와 대조했고 DB 5개·파일 59개의 백업·별도 복원 및 배포 후 상태 보존을 다시 검증했다. 최종 복구 근거는 `D:/WebLedgerHost/data/backups/toyoko-reservation-20261024T121451/`이며 최소 외부 health/ready 및 접근 보호 스모크가 통과했다. 이후 문서 전용 커밋은 이 운영 코드를 바꾸지 않는다.

[PR #92](https://github.com/6Soo/cost/pull/92)를 병합한 첫 배포는 `587db6316444f843b971a189e7523a5529f424b8`이었다. 실행 경로 `D:/WebLedgerHost/releases/587db6316444f843b971a189e7523a5529f424b8`과 Git archive 파일 921개를 대조했다. 아래는 첫 배포의 검증 이력이며 최종 SHA는 위 문단을 따른다.

예약 관계의 자동 추론과 사용자 확인을 결제 검증에서 분리했다. 사용자 확인은 별도 관계와 이력으로 저장하며, 기존 결제·그룹·예약 관계의 점유를 원자적으로 확인하고 자동 paid 대사의 재사용을 막는다. 근거 변경·소실은 기존 선택을 보존하며 재확인이 필요하다고 표시한다. 정상 카드 준비와 수동 여행을 보존하며 추론 예약번호를 Google 복사 F열에 넣지 않는다.

DB 5개와 보호 파일 59개의 백업·별도 복원 및 배포 후 보존 게이트가 통과했다. 근거는 `D:/WebLedgerHost/data/backups/toyoko-reservation-20261024T120518/`에 있다. 기존 DB 표·schema와 보호 파일은 같으며 생존 정보 rule_process_leases만 기존 게이트의 예외다. 운영 원행 재수입, 재기장, 금액 보정 및 Google 쓰기는 하지 않았다. Board와 MailCollect를 같은 release로 전환했고 보조 작업의 기존 실행·활성 상태를 복구했다.

외부 healthz·readyz는 200, 비인증 import·ota와 신규 예약 관계 preview 경로는 401이었다. 합성 Aside 화면에서 예약 관계만 1건 저장되고 결제 links는 0건, 카드 모든 열이 그대로인 것을 확인했다. 표적 105개 범위의 99개 통과와 공통 점유 초기화 오류 6개를 수정한 뒤 해당 6개 통과, 이후 UI 변경의 문법·통합 검사 통과를 재사용했다. 전체 pytest는 반복하지 않았고 전체 회귀 통과로 보고하지 않는다. 최신 재개 기준은 [현행 인계 0.10절](COST_V3_CURRENT_HANDOFF.md#010-2026-10-24-토요코인-예약-관계와-결제-검증-분리)이다.


## 2026-10-24 COST V3 통합 병합·운영 배포 완료

사용자 승인으로 [PR #91](https://github.com/6Soo/cost/pull/91)을 main `a3474a8f481590ed2189449c5d2113c7a2e933ff`에 병합하고 같은 커밋을 운영에 배포했다. PR #88·#89·#90도 MERGED 상태다. 기존 여행 우선배정·메뉴·Toyoko 후보·L1/L2 투영과 항공권 원본 변경/취소 보호, 지연 여행 이동의 최신 결정 보호를 포함한다.

운영 코드는 `D:/WebLedgerHost/releases/a3474a8f481590ed2189449c5d2113c7a2e933ff`다. archive의 파일 918개를 대조했으며, 사용자 `C:/AX/cost`의 미커밋 변경과 stash는 그대로 보존했다. Board 관리 작업과 실제 launcher가 새 release를 사용하는 것을 확인했다. MailCollect는 인증·인자·주기 그대로 working directory만 전환했고 실제 수집을 즉시 실행하지 않았다. SourceRefresh와 GoogleAuthority action은 바꾸지 않았다.

전환 전에 작성자를 잠시 멈추고 DB 5개·파일 59개의 백업과 별도 복원을 검증했다. 복구 binding과 원본 불변 검사는 통과했다. 배포 후 모든 DB 표·schema는 프로세스 생존 정보 `rule_process_leases`를 제외하고 같았고 원본·영수증·Google 읽기 자료·host config 해시도 같았다. 원장 재기장·운영 마이그레이션·Google 직접 쓰기는 수행하지 않았다. 근거는 `D:/WebLedgerHost/data/backups/spec-integration-20261024T095950/`의 restore-evidence.json, protection-result.json, deployment.json에 보존한다.

Board·SourceRefresh는 Running, MailCollect·GoogleAuthority는 Ready이며 모두 Enabled로 복구됐다. 8751 listener는 1개다. 외부 `/healthz`와 `/readyz`는 200, 비인증 `/import`·`/ota`·`/flight-passengers`는 401로 최소 스모크를 한 번 수행했다. 실제 고객 후보 payload·로그인된 운영 화면은 조회하지 않았다. 이후 문서 전용 main 커밋은 운영 코드 SHA와 구분한다.

병합 전 비브라우저 전체 회귀는 테스트가 공유 잠금을 우회해 DB connection을 직접 닫으면서 Windows 접근 위반으로 중단됐다. 테스트를 기존 `board.close()` 경계로 바꾼 `329b2ec`에서 해당 nodeid 1 passed를 확인했다. 비브라우저 실패 7개는 기준 `fe34048`에서도 동일하게 재현됐고 수정하지 않았다. 제외 설정이 놓친 기존 브라우저 검사 1개는 접힌 상세 영역을 열지 않은 채 링크를 기다렸다. 해당 렌더 분기·page·검사 파일은 기준과 같았고, Aside에서 실제 펼치기→전체 카드 검색→합성 3건 표시를 확인했다. 전체 회귀는 반복하지 않았으며 전체 통과로 보고하지 않는다. 기존 변경 기능별 표적 검사와 검토의 유효 근거를 재사용했다.

최신 실행·재개 기준은 [현행 인계 0.9절](COST_V3_CURRENT_HANDOFF.md#09-2026-10-24-사용자-승인-병합과-운영-배포-완료)이다. 아래 거래 건수와 과거 릴리스는 그 당시 기록이며 이번 배포로 재기장한 결과가 아니다.

## 2026-10-23 지출 정리 자동 처리 결과와 남은 근거 확인

운영 장부에 아고다 4건과 부킹닷컴 1건, 총 2,673,921원을 추가 기장했다. 5건 모두 원문 예약번호·카드 금액·검증된 여행과 일치하며 장부 날짜는 숙박 시작일이다. 원문, 기존 장부, 사용자 확정, 환불, 수동 고정과 학습 자료를 보존했다. Google 최종 장부 쓰기는 0건이다. 결과는 `.local-archive/targeted-checks/20261023-completed-stays-live-result.json`의 `PASS`로 확인했다.

현재 근거 확인 대상은 **161건**이며 항목 미분류 3건, 여행 근거 미확인 125건, 보호 대상 33건이다. 카드 장부 기록은 2,560건이고 전체 장부 행은 2,564개다. 기존 348건 중 확정 장부 121건을 재검토에서 제외했고, 카드 66건 4,951,218원을 실제 기장해 187건을 처리했다. 이전 장부 13건의 여행 보완은 이 건수에서 다시 차감하지 않는다.

최종 운영 릴리스는 `6bda111bdc3100480f989f8ccb02aeeaf8c2209a`다. 일괄 기장 후 필요 없는 화면 자료 재계산을 생략해 결과 응답을 지연시키던 경로도 수정했다. 개별 카드 입력의 기존 응답은 유지한다. 관련 표적 검사 3개가 통과했고, 기장 검증과 기록 구문이 바뀌지 않았음을 AST로 확인했다. 변경 파일은 2개이며 나머지 860개 파일은 동일하다. 관리 배포가 성공했고 복구 검증 자료는 `D:/WebLedgerHost/data/backups/v2-owner-ui-20261023T013850/`에 있다. 원래 코드 검사와 유효한 재현 결과는 재사용했고 전체 회귀는 실행하지 않았다.

기장 관리 스크립트는 5건 기장과 모든 보존 검사에 성공한 결과 파일을 저장한 뒤, 종료 정리의 `service.stop(timeout=30)`에서 `RuntimeError: OTA snapshot worker did not stop in time`으로 종료 코드 1을 반환했다. 기장 실패가 아니라 후처리 워커 대기 시간 초과이며 두 결과를 구분한다. 해당 스크립트는 이미 기록된 5건을 다시 처리하지 못하도록 보호하며 **재실행하지 않는다**. 원문 오류와 마지막 단계는 `20261023-completed-stays-live.txt`에 보존했다.

트립닷컴의 추가 예약 조회는 실제 예약용 이메일의 일회용 인증에서 부분 차단됐다. 사용자에게 Aside 예약 검색 화면에서 직접 인증을 완료하도록 요청했다. 채팅으로 전달받은 인증코드는 문서·파일·로그에 옮기거나 대신 입력하지 않는다. 인증 후 해당 예약의 실제 결제 금액·카드·이용기간을 수집하고 기존 메일과 대조하는 단계가 남았다. 나머지 161건을 모두 해결했다고 보고하지 않는다. Aside 대화형 REPL 세션은 `86472`, 예약 검색 페이지는 `https://kr.trip.com/passport/ordersearch?curr=KRW&locale=ko-KR`이며 자동 수집이 진행 중인 것은 아니다.

재개 시에는 위 결과 파일과 사용자 인증 완료 여부부터 확인한다. 기장 스크립트를 반복하지 않고 기존 Aside 세션의 예약 검색 결과를 읽는다. 기존 문서 미커밋 변경 두 개와 원문 자료는 보존한다. 아래 문단은 시간순 조사 이력이며 현재 운영 수치로 재해석하지 않는다.

## 2026-10-23 지출 정리 자동 처리 결과와 남은 근거 확인

348건을 사용자가 직접 분류하도록 넘기지 않는다. 이미 확정된 정상 미배정 장부 121건은 재검토 대상에서 제외했고, 카드 61건 2,277,297원을 실제 자동 기장했다. 기존 장부 13건은 금액과 날짜를 유지하면서 여행과 추론 근거만 보완했다. Google 최종 장부에는 쓰지 않았다.

운영 금융 변경은 `34ee817a58790abe5bcb13587f4052123c01dc9b`, 화면 개선은 `3cd0e1f5da720a5e34dc08a5333590791c65e0e0`이다. 관리 배포는 성공했고 복구 검증 자료는 `D:/WebLedgerHost/data/backups/v2-owner-ui-20261022T203407/`에 있다. 금융 동작 여섯 함수는 화면 개선 전후 AST가 동일하다. 직접 영향 표적 검사 54개와 화면 표적 검사가 통과했다. 전체 회귀와 이미 유효한 검사는 반복하지 않았다.

2026-10-23 읽기 전용 집계에서 남은 거래는 166건이다. 항목 미분류 3건, 여행 근거 미확인 130건, 보호 대상 33건이다. 보호 대상에는 취소 거래 26건이 포함된다. 이전 예상 136건과 27건은 실제 최신 집계로 대체한다. 장부 카드 기록은 2,555건이고 전체 장부 행은 2,559개다. 취소 거래에는 새 비용 항목 입력을 요구하지 않고 원결제 근거 확인을 표시한다.

원문과 기존 금융 필드 보존, 기존 여행 보완 13건, 신규 61건의 복사본 검증 일치, OTA와 검토 자료 보존 검사는 통과했다. 근거는 `.local-archive/targeted-checks/20261022-resolve-348-protection-after-post.json`과 `20261022-resolve-348-live-result.json`이다. 이 기장 스크립트를 다시 실행하지 않는다.

트립닷컴 미분류는 같은 날 같은 금액 85,621원 두 건과 1,345,388원 한 건이다. 전체 수신 메일을 해독해 검색한 결과 85,621원과 일치하는 금액 원문은 발견되지 않았다. 1,345,388원은 서로 다른 예약의 카드 사전승인과 취소 수수료 안내에서 확인됐다. 따라서 금액만으로 결제 완료와 예약 연결을 확정하지 않는다. 원문 검토 자료는 `20261023-trip-decoded-amount-hits.json`에 로컬 보존했다.

Aside로 트립닷컴에 접속해 로그인 창을 확인했다. 이메일과 계정 선택이 필요한 비로그인 상태이며 인증 우회나 임의 계정 선택은 하지 않았다. COST 화면 재확인은 탐색 시간 초과와 `CDP command timeout: Page.enable`로 실패했다. 배포 성공과 서버 상태 확인을 실제 브라우저 표시 성공으로 혼동하지 않는다. 공통 런타임 재시작은 하지 않는다.

다음 단계는 운영 OTA 스냅샷과 미해결 거래를 읽기 전용으로 대조해 연결 실패 사유를 집계하고, 기존 근거로 해결 가능한 경로를 좁혀 수정하는 것이다. 예약 이용일을 결제일로 만들지 않고, 실제 복수 결제와 취소·환불·사용자 결정을 보존한다. 브라우저 인증이 필요한 예약만 별도 차단으로 남기며 독립적인 로컬 분석과 구현을 계속한다.


## 2026-10-22 19:45 KST 기록 대기 제거와 자동 기장 반영

현재 운영 릴리스는 `2d062ec7e949ac20f59c4c904174a8a1a4351585`다. 기록 대기를 별도 상태로 남기지 않고, 전체 지출 자동 정리에서 분류·여행·원본·환불 보호 검사를 통과한 거래를 장부에 바로 반영한다. 관련 코드와 검사 3개 파일만 변경하고 운영 전용 브랜치에 push·관리 배포했다. 표적 검사 4개, 자바스크립트 문법 검사, 복사본 기장과 실제 기장 대조가 통과했다.

249건·16,916,631원을 실제 기장했다. 사전 검증과 실제 결과의 거래 ID·금액·날짜·항목·여행이 모두 일치한다. 정리할 지출은 **597건에서 348건**으로 줄었다. 화면에는 **항목 미분류 30건, 여행 미배정 310건, 보류·오류 8건**만 표시하며 기록 대기는 없다. 카드 장부 기록은 2,494건, 장부 행은 2,498행이다. Aside로 운영 화면의 새 건수와 `전체 지출 자동 정리` 버튼을 확인했다.

원문·금액·날짜·사용자 결정·규칙·보류·기존 장부 행·감사 이력·OTA·검토 DB의 보존 검사가 통과했다. Google 최종 장부에는 쓰지 않았다. 관리 배포 결과는 `OWNER_UI_DEPLOYMENT_PASS`, 복구 근거는 `D:/WebLedgerHost/data/backups/v2-owner-ui-20261022T193243/`다. 실행과 보호 근거는 `.local-archive/targeted-checks/20261022-no-wait-live-result.json` 및 `20261022-no-wait-protection-after-post.json`에 있다. 아래의 597건과 기록 대기 251건은 이전 운영 상태다.

## 2026-10-22 19:18 KST 지출 정리 개선 운영 반영과 일괄 자동분류

운영 릴리스는 `80b66b7a6ce8882bf78126ce20f4e4f75a0738a1`이다. 사용자가 승인한 가맹점 변형 자동분류, 사유별 집계, 중복 범위 버튼·행별 지시 입력 정리와 전체 미정리 카드 재분류를 분리 운영 브랜치에 push하고 관리 배포했다. 이전 릴리스의 847개 파일은 그대로이며 변경 범위는 관련 코드·검사 12개 파일이다. `OWNER_UI_DEPLOYMENT_PASS`, 복구 검증 DB 5개·원본 파일 56개, health/ready 및 로그인된 지출 정리 화면을 확인했다.

Aside REPL에서 `전체 자료 자동분류`를 한 번 실행했다. 분류 대상 기준 447건 중 실제 변경은 351건이며 항목 미분류가 **355건에서 34건으로 감소**했다. 사유별 현황은 **항목 미분류 34건, 여행 미배정 310건, 장부 기록 대기 251건, 보류·오류 2건**이다. 총 597건은 장부 미기록 카드 476건과 여행 미배정 장부 지출 121건의 합계여서 분류 후에도 유지된다. 새 장부 기록을 만들지 않았으며 기존 장부 2,249행과 카드 장부 기록 2,245건은 유지됐다. Google 최종 장부에는 쓰지 않았다.

원문 ID·금액·날짜·원문 필드, 대상 밖 사용자 결정·기존 배정·취소·환불·보류, 장부·규칙·결정 테이블 및 OTA·검토 DB의 동일성 검사를 통과했다. 배포 재시작 시 업무 DB의 유일한 차이는 프로세스 생존 정보를 기록하는 `rule_process_leases`였다. 운영 기준 직접 영향 표적 검사 24개가 통과했다. 처음의 넓은 검사 실행은 변경되지 않은 예약 색인 스레드와 기존 테스트의 DB 종료 경합으로 Windows access violation이 발생했고 통과로 처리하지 않았다. 기준 커밋 재실행을 주장하지 않으며 코드 동일성 비교와 분리한 표적 검사 결과를 구분한다.

복구 근거는 `D:/WebLedgerHost/data/backups/v2-owner-ui-20261022T191031/`, 실행·보호·집계 증거는 `.local-archive/targeted-checks/20261022-cleanup-protection-after-classify.json` 및 `20261022-live-cleanup-result.json`에 있다. 전체 미분류 잔여 34건과 기록 대기 251건은 새 장부로 자동 기장하지 않는다. 상세 상태와 재개 조건은 [인계 문서](session_handoff.md)의 첫 항목을 따른다. 아래 항목은 이전 운영 이력이다.

## 2026-10-22 07:39 KST 트립닷컴·부킹닷컴 결제 파서 운영 반영 완료

트립닷컴 예약 확정 메일 35건과 부킹닷컴 결제 영수증 4건에서 명시된 사전 결제 증거를 인식하도록 수정했다. 기존 파서와 수정 파서를 같은 운영 원본으로 비교한 결과, OTA 결제 이벤트 1,959건의 ID는 추가 0건·삭제 0건으로 유지됐고, 39건의 결제 해석만 `not_card_charge`에서 `paid_verified`로 바뀌었다. 변경된 39건은 인증 발신처, 원문 결제 금액, 취소·환불 표현, 같은 예약의 다른 결제 완료 이벤트를 검사했으며 문제가 없었다. 결제 상태가 확인됐다고 카드사 승인 거래의 자동 연결까지 확정한 것은 아니다.

트립닷컴 메일에 결제일이 없는 경우 날짜를 추정하지 않고 카드 자동 연결 대상에서 제외한다. 부킹닷컴은 명시적인 영수증 결제일과 금액을 읽고 별도 현장 세금은 온라인 결제액에서 제외하며, 서로 다른 결제일이 충돌하면 결제 완료로 승격하지 않는다. 표적 테스트는 개발 및 운영 분리 브랜치에서 각각 `5 passed`였다. 개발 커밋은 `2e2bcfb200a935bd8896dfcbfe5cfe49aef5ef51`, 운영 커밋과 릴리스는 `edf1ea9ac4e3945c1427ee522a3740bf82b4c88d`이다. 운영 분리 브랜치 `deploy/ota-unified-20261021`만 원격 push했고 개발 `main`은 push하지 않았다.

승인된 관리 배포 결과는 `OWNER_UI_DEPLOYMENT_PASS`이다. 복구 검증은 DB 5개·파일 56개가 통과했고, 운영 보호 테이블은 배포 전후 모든 행이 일치했다. OTA DB 무결성은 `ok`, Board는 `Running`, SourceRefresh는 `Ready`, `/healthz` 및 `/readyz`는 각각 HTTP 200이었다. 복구 증거는 `D:/WebLedgerHost/data/backups/v2-owner-ui-20261022T073227/`, 파서 대조 증거는 `.local-archive/ota-resolution-20261021/parser-release-verification-20261022.json`에 보관했다. 기존 장부 24건·7,188,006원은 재기장하지 않았고, 아고다 미해결 카드 27건·5,582,390원도 확정하지 않았다. Google 최종 장부에 자동으로 쓰지 않았다.

## 2026-10-22 06:40 KST 로그인 OTA 카드 대사 화면 점검

기존 로그인 Aside OTA 탭에서 예약 `1739952861`의 상세 화면을 직접 확인했다. 최초 화면은 `카드 대사 결과를 확인 중입니다`였으나, 페이지를 새로고침한 뒤에는 **`대사된 카드 결제가 없습니다`**로 바뀌었다. 운영 스냅샷 로그는 세대 193, 입력 지문 `94db56f065c5`, 2026-10-21 21:29 UTC 갱신 성공을 기록했으며, 21:40 UTC 점검에서도 `held=true`, `failed=false`, `refreshing=false`였다. 보존된 스냅샷의 결과 1,959개, 카드 연결 284개를 읽기 전용으로 확인했다. 따라서 해당 화면의 갱신 대기 상태는 현재 해소됐다. 아고다의 JPY 55,335 결제 완료 관측과 카드사 원행의 대사 완료는 서로 다른 증거이며, 실제 카드 연결은 확인되지 않았다. 이번 확인으로 새 비용을 기장하거나 결제 상태를 바꾸지 않았다.

트립닷컴·부킹닷컴은 앞서 반영한 파서·금액 형식·카드 투영 수정이 유효하며, 미확정 추가 승인·예약 변경 차액·완료 환불에는 개별 금융 증거가 더 필요하다. 아고다 미기록 27건·5,582,390원도 기존 재대사에서 후보 없음 13건, 후보 복수 14건으로 확인된 상태를 유지한다. 근거 없이 카드 거래를 예약에 연결하지 않았다. 코드 수정이나 새 운영 배포는 없었다.

## 2026-10-22 결제 완료 후속 증거 반영과 로그인 화면 확인

로그인된 운영 OTA 화면에서 예약 `1738955501`을 검색하고 상세 판단 화면의 **취소** 표시, 카드 대사 0건, 환불 완료로 표시하지 않는 것을 확인했다. 현재 통합 DB는 검증된 취소 메일에 따라 `reservation_status=cancelled`, `payment_status=failed`, `refund_status=none_displayed`다. 결제 실패 표시와 예약 취소를 서로 다른 상태로 유지한다.

예약 `1739952861`은 앞선 직접 수집(2026-10-21 02:55 UTC)에 `payment_status=failed`였지만, 별도로 보존된 **2026-10-21 12:14 UTC 아고다 결제 완료 원문**이 통합 DB에 누락돼 있었다. 원문에는 예약 확정, 결제 완료, JPY 55,335, 카드 끝자리 관측이 함께 있다. 기존 수집의 예약번호별 진입 증거와 해당 원문을 대조한 뒤 직접 관측 자료로 추가했고, 최신 `direct_facts()`는 `payment_status=paid`, 충돌 없음이다. 이는 **아고다 화면에서 결제가 완료됐다는 관측**이며, 카드사의 정산 완료나 실제 결제일을 만들어 확정한 결과는 아니다. 장부 기장은 실행하지 않았다.

추가 직전 통합 DB는 출처 1,661개, 증거 40,232개였고, 추가 후에는 출처 1,662개, 증거 40,233개다. 해당 시점에 기존 자동 수집으로 이전 체크포인트보다 근거 수가 늘어나 있었으므로 이전 보고의 38,886개와 직접 비교해 이번 변경 건수로 해석하지 않는다. 복구 DB `D:/WebLedgerHost/data/backups/ota-evidence-paid-1739952861-20261022.sqlite`와 원본의 테이블별 해시가 일치했고, 격리 적재·반복 적재·무결성 검사가 통과했다. 보고서는 `.local-archive/ota-resolution-20261021/remaining-details/paid-1739952861-ingest-result.json`에 남겼다. 로그인된 운영 OTA 목록에는 해당 예약이 검색됐으나 상세 페이지 재조회는 Aside의 `Runtime.evaluate` 시간 초과로 미완료다. 기존 배포를 반복하지 않았다.

## 2026-10-22 아고다 수집 완료와 예약 취소 운영 배포

아고다 직접 예약 수집은 **1,180/1,180건 완료, 실패 0건, 대기 0건**이다. 자동 후처리 `post-collection-finalization.json`은 `PASS`이며, 통합 OTA 증거 DB `D:/WebLedgerHost/data/ota-evidence.sqlite`에 직접 수집 출처 284개를 추가했다. 출처는 1,377개에서 1,661개, 예약 증거는 38,602개에서 38,886개로 증가했다. 적재 전 복구 사본은 `D:/WebLedgerHost/data/backups/ota-evidence-completed-20261022T054227.sqlite`, 최종 근거는 `.local-archive/ota-resolution-20261021/remaining-details/ingest-completed-20261022T054227.json`이다. 추가 장부 기장은 실행하지 않았다.

예약 `1738955501`은 이후 도착한 검증된 아고다 **취소 완료 메일**을 통합 DB에 반영했다. 현재 집계는 `reservation_status=cancelled`, `payment_status=failed`, `refund_status=none_displayed`, 충돌 없음이다. 취소와 결제 성공·환불 완료를 혼동하지 않는다. 본 수정은 `main`의 `9377a44`, 운영 분리 브랜치 `deploy/ota-unified-20261021`의 **`79e7c1cf53d4350e28f189731729af97ccdbf2d0`**에 있으며, 분리 브랜치만 원격에 push했다. `main`의 미배포 41개 커밋은 원격에 일괄 push하지 않았다.

운영 릴리스는 `79e7c1c`로 관리 배포됐다. 첫 시도는 백업 복구 검사에서 실패해 기존 `d418719`로 자동 복귀했다. 이어 같은 검사 단독 실행이 통과한 것을 확인한 뒤 다시 배포해 `OWNER_UI_DEPLOYMENT_PASS`를 받았다. 배포 결과는 `D:/WebLedgerHost/data/backups/v2-owner-ui-20261022T060549/`에 있으며, **DB 5개·파일 56개 복구 비교**, Board `Running`, 리스너 1개, `/healthz`·`/readyz` 200, 비로그인 OTA API 401을 확인했다. 운영 장부·사용자 확정 보호 테이블 16개의 모든 행이 배포 전과 동일하며, 운영 통합 DB 무결성은 `ok`이다. 분리 릴리스 표적 테스트는 **14 passed**였다. 로그인된 OTA 화면 이동은 Aside의 `Runtime.evaluate` 명령 시간 초과로 확인하지 못했다. 따라서 화면 검증은 후속 점검으로 남긴다.

기존 아고다 미해결 카드 48건 가운데 현재 기장이 확인된 것은 21건이고, **27건·5,582,390원은 여전히 미기록**이다. 이는 비용 확정액이 아니라 미해결 카드 원행 금액의 합계다. 13건은 대응 예약 후보가 없고 14건은 후보가 여럿이어서 새 확정 연결 근거가 없다. 27건은 근거 없이 기장하거나 여행에 배정하지 않는다. 트립닷컴·부킹닷컴의 추가 승인과 환불 완료도 개별 금융 원본이 확인된 건만 처리한다. 자세한 재조정 파일은 `.local-archive/ota-resolution-20261021/remaining-agoda-rechecked-20261022.json`이다.

## 2026-10-22 아고다 인증 복구 후 상세 수집 및 증거 증분 적재

아고다 로그인 세션이 복구되어 전용 Aside REPL 수집기 `tools/collect_agoda_aside.py`가 같은 작업 공간에서 실행 중이다. 04:43 KST 체크포인트 기준 대상 1,180건 중 완료 925건, 실패 0건, 대기 255건이다. 이후 수치는 `.local-archive/ota-resolution-20261021/remaining-details/collection-checkpoint.json`이 기준이며 별도의 중복 수집기를 실행하지 않는다. 기존 Python 프로세스 ID는 5612다.

완료된 상세 중 체크포인트로 검증한 896건을 통합 OTA 증거 DB `D:/WebLedgerHost/data/ota-evidence.sqlite`에 증분 반영했다. 새 직접 수집 출처 131건이 추가되어 `ota_sources` 1,245개에서 1,376개, `ota_booking_evidence` 37,124개에서 37,255개로 증가했다. 복구 사본 `D:/WebLedgerHost/data/backups/ota-evidence-completed-20261022T043706.sqlite`의 무결성과 전체 테이블 내용 비교를 검사했고, 실제 적재 결과는 `.local-archive/ota-resolution-20261021/remaining-details/ingest-completed-20261022T043706.json`에 기록했다. 금융 장부에는 쓰지 않았다.

재대사에서는 기존 아고다 미해결 카드 27건 중 추가 확정 연결 0건이었다. 완료된 직접 수집 근거를 기준으로 금액과 카드 끝자리가 모두 같은 예약 후보가 없는 거래는 9건, 후보가 둘 이상인 거래는 18건이다. 이 분포는 전체 수집이 끝나기 전의 읽기 전용 진단이므로 최종 연결로 승격하지 않는다. 기존에 기록된 아고다 21건과 트립닷컴 3건, 총 24건 7,188,006원을 보호한다. 장부 자동 추가 및 Google 최종 장부 자동 쓰기는 실행하지 않았다. 트립닷컴·부킹닷컴의 미해결 추가 승인과 완료 환불도 원본 확인 전까지 보류한다.

수집 종료 후 체크포인트·캡처 파일의 예약번호와 파싱 결과를 검증하고, 완료 건을 통합 DB에 증분 반영한다. 보존된 스크립트 `.local-archive/ota-resolution-20261021/remaining-details/sync_completed.py`는 체크포인트 완료 파일만 대상으로 백업과 복원 비교 후 적재한다. 이후 읽기 전용 `.local-archive/ota-resolution-20261021/reconcile_remaining_20261022.py`를 사용해 미해결 27건을 다시 확인하고, 확정 연결에 필요한 개별 금융 근거가 없으면 기장을 보류한다. 이 항목 이후 아래의 과거 기록에 있는 아고다 인증 차단과 672건 기준 숫자는 당시 상태다.

## 2026-10-22 트립닷컴 비정상 공급자 예약 조회 보호 배포

운영 릴리스 `d418719bb84e252eacfbac9f6a5256577e8a4029`를 분리 브랜치 `deploy/ota-unified-20261021`에 push하고 관리 배포했다. main 구현 커밋은 `d9f07b7`이다. 기존 릴리스 `44ed59b`와 비교해 예약 조회 코드 1개만 변경하고 합성 표적 테스트 1개를 추가했다. 이전 릴리스의 나머지 파일 918개 해시가 같고, 변경 코드와 테스트 파일은 검사한 Git 작업본과 일치한다. 배포 결과 `OWNER_UI_DEPLOYMENT_PASS`, Board `Running`, SourceRefresh `Ready`, 로컬 health/ready 각각 200이다. 운영 배포 복구 증거 `D:/WebLedgerHost/data/backups/v2-owner-ui-20261022T032307/restore-evidence.json`에서 운영 DB 5개·파일 56개의 복원 비교, 원본 불변 및 검토 연결 동등성을 확인했다. 백업 당시 장부 행은 2,249개였다.

통합 OTA 증거 DB에 남은 잘못된 공급자 표기 7건을 예약 판단 목록의 자동 배정 대상에서 보류하고 경고로 집계한다. 정상 `trip` 예약과 예약번호가 같아도 잘못된 기간과 설명을 합치지 않는다. 원본 예약·증거·카드·장부 기록과 사용자 결정은 변경하지 않았다. `unknown` 공급자의 기존 병합 동작은 유지한다. 분리 릴리스에서 `tests/card_pipeline/test_ota_catalog_invalid_provider.py` 표적 테스트가 1건 통과했고, 앞선 운영 DB 읽기 전용 검증에서 비정상 공급자 7건이 조회 결과에서 제외됨을 확인했다. 전체 회귀, 전체 OTA 재수집, 기존 24건 재기장은 의도적으로 재실행하지 않았다.

추가 아고다 상세 수집은 2026-10-22 현재 Aside에 네이버 스마트플레이스 탭만 있고 인증된 전용 아고다 탭이 없어 중단 상태다. 잔여 아고다 27건(정확한 결제 대응 근거 없음 13건, 후보 복수 14건)과 트립닷컴·부킹닷컴의 추가 결제·완료 환불 증거는 확보될 때 해당 거래만 재대사한다. 비정상 공급자 7건의 DB 식별자 자체는 원본 보존을 위해 변경하지 않았다. 사용자 Google 최종 장부 자동 쓰기는 수행하지 않았다.

## 2026-10-22 통합 OTA 증거 반영 및 운영 장부 24건 실제 기장

운영 장부 `D:/WebLedgerHost/data/board.sqlite`에 아고다 21건과 트립닷컴 3건, 총 24건 **7,188,006원**을 CardFlow의 기존 미리보기·기장 경로로 실제 기록했다. 작업 전 장부 2,225행 및 전기 2,221행에서 작업 후 장부 2,249행 및 전기 2,245행으로 증가했다. 해당 24건의 거래 ID·예약번호·금액·이용일을 실제 장부 행과 대조했다. 기존 장부·전기·사용자 결정·보류·여행 행을 보존했고, 카드 원본 필드와 같은 요청의 중복 기장 방지, DB 무결성을 확인했다. 원본에 없는 아고다 결제일은 만들지 않았다. 확인 보고서는 Git 제외 경로 `.local-archive/ota-resolution-20261021/live-recording-20261022.json`에 있다.

기장 전 복구 사본 `D:/WebLedgerHost/data/backups/ota-record-20261022T0230/`의 4개 운영 DB 복원 검사 근거를 확인했다. 사전 검사로 대상 24건의 분류 관련 필드가 바뀌었으나, 이 변경 외에는 백업과 일치함을 확인했고 카드 원본·금액·사용자 판단·기존 금융 행은 보호했다. 통합 OTA 증거 DB `D:/WebLedgerHost/data/ota-evidence.sqlite`에는 직접 캡처 672건 추가를 포함한 출처 1,152건, 원문 항목 3,036건, 예약 증거 34,341건, 메일 1,955건, 예약 식별자 2,809건이 저장돼 있다. 최종 Google 장부 자동 쓰기는 실행하지 않았다.

기존 아고다 미연결 조사 대상 48건 중 21건이 이번에 기록됐고 **27건이 남아 있다**. 13건은 해당 금액·카드에 대응하는 정확한 예약 근거가 없고, 14건은 여러 예약이 후보로 남는다. 새 근거 적용 후 재점검 결과는 `.local-archive/ota-resolution-20261021/remaining-agoda-rechecked-20261022.json`을 참조한다. 아고다 직접 수집은 상세 672건 완료, 35건 실패, 473건 대기 상태다. 현재 Aside에 전용 아고다 인증 탭이 없으므로 인증 세션 복구 전까지 추가 수집을 중단했다. 실패 35건은 취소 탭 선택 문제 24건, 상세 예약번호 확인 실패 9건, 페이지 연결 오류 2건이다.

트립닷컴·부킹닷컴의 변경 예약 추가 청구와 취소·환불 금액은 개별 결제 승인 또는 실제 환불 완료 증거가 확인된 경우에만 기장한다. 통합 예약 식별자 표에서 트립닷컴 메일 이름이 공급자 필드로 들어간 비정상 행 7건을 추가 발견했다. 그중 6건은 정상 `trip` 예약번호와 중복돼, 기존 증거를 보존한 상태로 공급자 이름 정규화·중복 증거 처리 검토가 필요하다. 현재 운영 DB의 해당 행을 임의로 합치거나 삭제하지 않았다. 정확한 카드·예약 대응 증거가 없는 경우는 보류한다.

이번 작업은 운영 DB의 정상 기장 절차를 실행한 작업이다. 추적 중인 애플리케이션 코드와 운영 릴리스 `44ed59b`를 변경하거나 재배포하지 않았다. 보호 대상 직접 확인으로 작업을 검증했으며 전체 회귀·OTA 전체 재수집·브라우저 반복 검증은 수행하지 않았다.

## 2026-10-21 미완결 원인 수정과 실제 자료 반영

운영 릴리스는 `d26a160f14a84ff1d33e93f7dcebd8f46e80734f`이며 분리 브랜치 `deploy/ota-unified-20261021`에 push했다. main의 이번 코드 커밋은 `65192c3`, `f95dfba`, `52f6d9d`다. 다른 미배포 기능을 포함하지 않았다. 단일 OTA 근거 DB는 계속 `D:/WebLedgerHost/data/ota-evidence.sqlite`다. 아래 이전 기록의 미해결 집계와 미기장 상태는 당시 결과이며 이 항목으로 바로잡는다.

주요 원인은 제공 자료의 미반영과 서로 다른 파서·화면 경로의 불일치였다. 보관된 하나 승인 원본에서 기존 범위와 겹치지 않는 7월 21일~10월 4일 358행을 운영 검토 DB에 추가했다. 승인번호가 서로 다른 트립닷컴 90,121원 두 거래도 포함한다. 원본은 보존했고 원본 해시·행 번호·검증된 카드사 출처를 변환 CSV에 남겼다. 복사 DB의 반복 가져오기는 추가 0행, 충돌 0건이었고 실제 운영 추가 전후 기존 77개 테이블의 모든 기존 행이 유지됐다. 새 배치 전체를 자동 기장하지 않았다.

부킹닷컴 외화 금액의 올바른 천 단위 쉼표를 정확 비교하며 원문은 바꾸지 않는다. 인증된 같은 공급자·예약번호의 확정 기간을 결제 이벤트에 보완하고, 기간 충돌은 보류한다. 카드사 표기·취소·환불 요청·변경 총액을 따로 결합한다. 환불 요청을 완료 환불로, 변경 총액을 새 결제로 만들지 않는다. 기존 금융 이벤트 1,668개의 ID·금액·통화·결제일·금융 출처 ID를 보존했다.

사용자가 승인한 아고다 일반 규칙은 전체 자료에서 정확 금액과 카드 끝자리가 서로 유일하고, 검증된 직접 결제·이용기간 근거가 있으며 취소·충돌·기존 결정·보류가 없을 때만 결제일 없는 추론 연결을 허용한다. 고정 예약번호 예외가 아니다. 실제 결제일은 빈값이며 화면에 추론 연결이라고 표시한다. 기존 연결 300개를 보존하고 12건을 새로 추론 연결했다. 과거 대상 213건 중 163건은 이미 장부에 있었다. 실제 자동 연결 대상 48건 중 남은 36건은 정확 금액·카드 근거 없음 22건, 복수 후보 14건이다. 대상 전체를 결제일 부족으로 설명하지 않는다.

코어에서 연결된 트립닷컴 두 건이 예약 화면에서 누락되는 결함을 실제 Aside로 재현해 수정했다. 예약 화면은 신선한 코어 결과를 읽어 기존 연결을 보완한다. 기존 화면 연결 313개가 유지되며 코어의 추가 38개를 포함해 351개를 표시할 수 있다. 카드 중복 점유·보류·충돌은 추가하지 않는다. 반복 거래 순서 배정은 개별 결제 근거 미확인으로 표시하고 정확 연결로 승격하지 않는다. 코어 결과가 아직 준비되지 않으면 대사 확인 중으로 표시하며 결과 세대와 신선도가 바뀌면 목록 캐시도 갱신한다. 이 투영은 읽기 전용이며 자동 기장 범위를 늘리지 않는다.

기존 사용자 캐시 기장 규칙으로 아고다캐시 전액 22,500원 비용 1건을 실제 장부에 기록했다. 이용일은 원문 체크인 날짜이며 검증된 여행에 배정했다. 복사 DB에서 동일 요청 반복 시 비용이 늘지 않는 것을 확인했고 운영 사본 복원·기존 보호 행 보존을 검증했다. 기존 캐시 비용 2건과 Google 최종 장부는 그대로다.

관련 표적 검사만 실행했다. 외화 형식 12건, 메일 맥락 6건, 추론 21건, 금융 인접 4건, 화면 보호 3건, 기존 정확 연결·보고서 17건, 추론 표시 1건과 코어 표시·충돌 보호 2건이 통과했다. 실패한 합성 fixture의 계약과 실제 순서 배정 코드명을 확인해 해당 검사만 수정·재실행했다. 전체 pytest·전체 브라우저 검사·Google 쓰기는 수행하지 않았다. 릴리스 파일은 검사한 코드 및 Git blob과 일치했다. 관리 배포는 `OWNER_UI_DEPLOYMENT_PASS`, health/ready 200이며 DB 5개·파일 56개 사본의 모든 테이블·열·원본 해시 복원 검증을 통과했다. 최신 복원 증거는 `D:/WebLedgerHost/data/backups/v2-owner-ui-20261021T163716/restore-evidence.json`이다.

실제 Aside 예약 화면에서 트립닷컴 카드 표와 순서 배정 설명을 확인했다. 페이지 이동은 30초 대기 오류가 있었으나 후속 전체 스냅샷에서 완료 화면을 확인했다. 최초 로딩 속도 검증 통과로 해석하지 않는다. 아고다 추론 표시도 직전 릴리스에서 실제 화면 확인을 마쳤다. 최종 보호 테이블의 모든 행은 하나 358행·캐시 1건 반영 후 배포 전 기준선과 정확히 같았다. 근거는 `post-deploy-protected.json`과 로컬 화면 캡처다.

예약별 개인정보가 있는 근거와 원본은 Git 제외 경로 `.local-archive/ota-resolution-20261021/`에 보존한다. 실제 원본 반영, 추론, 캐시 기장, 기존 연결·금융 필드 비교와 배포 근거는 각각 `hana-live-import.json`, `final-audit-summary.json`, `cash-live-record.json`, `core-display-audit.json`, `display-release-gate.json`에서 확인한다. 남은 36건은 금액·카드·예약의 개별 대응 근거가 확인돼야 하며, 결제일·승인번호를 만들어 연결하지 않는다. 트립닷컴 취소·변경 사례의 요청 환불과 추가 차액은 완료 환불·개별 추가 결제 근거가 없어 별도 보류한다.

## 2026-10-21 최종 적재와 파서 버전 2 운영 반영

단일 OTA DB 전환과 우선 수집 큐 실행은 COMPLETE다. 운영 릴리스는 `0a88cb7f63c6515c760ed0cb25b5d76dde9fae02`이며 `deploy/ota-unified-20261021`에 push했다. main의 다른 미배포 기능은 포함하지 않았다. 모든 등록 OTA의 메일·직접 수집·참고 원문은 `D:/WebLedgerHost/data/ota-evidence.sqlite`에서 읽는다. 상시 메일 수집도 이 DB에 추가한다. 아래 이전 실행 기록의 수치는 당시 기준이다.

아고다 관측 목록 40페이지·예약 1,550건과 우선 상세 370건을 적재했다. 상세 큐는 완료 370·실패 0·잔여 0이다. 상세의 예약 상태는 투숙 완료 224·확정 21·취소 125건이다. 결제 관측은 카드 근거 있음 199·카드 정보 없는 완료 표시 6·현장 결제 35·캐시 전용 3·결제 실패 2·취소 예약의 결제 상태 미확인 125건이다. 실제 결제일은 370건 모두 화면에 없어 빈값을 유지했다. 이 상세 수집 완료를 계정의 모든 예약 상세 수집 완료로 확대 해석하지 않는다.

최종 메일은 원래 Gmail ID 기준 1,932개다. 실제 Aside 조사에서 발견한 부킹닷컴 확정 메일 1개는 기존 읽기 권한으로 원본을 다시 확보했다. 이전 예정 안내는 과거 근거로 보존하며 새 결제 완료로 만들지 않았다. 실제 예약 화면에서 기존 카드와 복구한 이용기간에 따른 여행 표시가 확인됐다.

현장 결제·캐시 사용·취소·환불 예정·카드 정보 없는 결제 표시·결제 거부를 구분한다. 파서 버전 1의 원문과 해석을 보존하고 버전 2를 추가했다. 기존 결제 이벤트 1,468개의 ID와 금액·날짜·근거가 동일했다. 새 메일 출처 한 곳의 추가로 전역 출처 목록만 늘었다. 실제 전체 캡처를 반복 적재한 전후 모든 테이블 행 내용 해시도 일치했다.

대상 카드 213건의 읽기 전용 진단은 COMPLETE다. 138건은 결제일 부족, 75건은 정확 금액·카드 관측 부족으로 추가 연결을 보류했다. 기존 장부 행 163개와 사용자 보호 결정 32개를 유지했다. 새 연결을 억지로 만들지 않았다. 캐시 사용 3건 중 2건은 기존 비용이 정확히 있었고, 나머지 22,500원은 근거와 미기장 비용 미리보기를 로컬에 보존했다. 이번 근거 통합에서는 장부에 새로 쓰지 않았다.

관리 배포는 `OWNER_UI_DEPLOYMENT_PASS`, health/ready 200이었다. 복구·복원 검증은 DB 5개·파일 56개를 포함했다. 최종 자료 적재는 별도 복구 사본의 모든 행 일치를 확인한 뒤 하나의 트랜잭션으로 수행했다. 최종 실제 화면 조회까지 마친 뒤 Board 보호 테이블 10개와 OTA 검토 테이블 6개의 모든 행이 동일했다. 관련 신규 표적 검사와 분리 릴리스의 영향 검사 4개가 통과했다. 전체 pytest·전체 브라우저 검사·Google 쓰기는 범위 밖이므로 수행하지 않았다. 화면 재계산에는 탐색 대기 시간이 초과되는 지연이 있었으나 후속 전체 스냅샷에서 완료 화면을 확인했다.

원문과 최종 근거는 `.local-archive/ota-unified-20261020/`의 `final-sync-report.json`, `final-source-protection.json`, `post-final-protected.json`, `target-card-reconciliation.json`, `final-runtime-evidence.json`, `capture-quality.json`에 있다. 배포 복원 근거는 `D:/WebLedgerHost/data/backups/v2-owner-ui-20261021T122304/restore-evidence.json`, 적재 전 사본은 `D:/WebLedgerHost/data/backups/ota-unified-20261021/pre-final-captures-20261021T1228.sqlite`다. 개인정보가 있는 원문과 예약별 상세는 Git에 넣지 않는다.

아고다 결제 거부 2건은 화면에 **10월 21일 21:43 전** 결제 완료 안내가 있었다. 실제 대상은 로컬 `payment-failures.json`에 기록했다. 결제·카드 변경은 실행하지 않았다. 미연결 카드의 실제 결제일·카드 원본 보완과 [트립닷컴·부킹닷컴 조사](trip-booking-mail-investigation.md)의 개별 제품 결함 수정은 이 저장소 전환 완료와 구분한다.

## 2026-10-21 모든 OTA 자료의 단일 DB 전환

운영 코드는 `35ea07f59b681e53ed718bd5a7ff81da611d74e6`이며 단일 근거 DB는 `D:/WebLedgerHost/data/ota-evidence.sqlite`다. `ota-sources.json`의 `unified_database`로 메일·포털·참고 자료를 모두 이 DB에서 읽는다. 메일 폴더 5곳·포털 DB 11개·참고 문서 53개의 원문과 이력을 보존했고 원래 파일은 삭제하거나 이동하지 않았다. 상시 메일 수집기도 같은 DB에 추가 적재하도록 연결했다.

최초 실제 이전에서 메일 1,921개·기존 결제 이벤트 1,464개의 전체 내용과 ID, 출처 목록·참고 결과가 일치했다. 밤사이 새 메일을 포함해 1,927개를 반영한 뒤 기존 결제 이벤트 1,468개의 내용·ID도 유지됐다. 동일 입력 반복 적재의 모든 테이블 행 해시와 무손실 압축 전후의 논리 내용이 일치했다. 아고다 목록 40페이지·예약 1,550건과 상세 표본을 추가했다. 계정이 다른 색인 행을 합친 숫자를 실물 예약 총수로 보고하지 않는다.

첫 후보 `a13cc86`의 실화면 확인에서 별도 예정일 대사 읽기 경로의 어댑터 누락을 발견해 기존 manifest로 되돌렸다. 해당 경로·상태 충돌 근거를 보완하고, 결제일 없는 새 관측이 기존 검증된 연결을 대체하지 않도록 한 뒤 현재 후보로 다시 전환했다. 실제 격리 카드 자료의 기존 연결 300개가 모두 같았고 새 출처 오류가 없었다. 예정일 조회용 42,594행은 보존 원문에서 복구했으며 기존 테이블의 모든 행은 그대로였다.

현재 후보는 운영 기준 `f5e27d3`에서 이번 변경만 분리한 `deploy/ota-unified-20261021` 브랜치이며 GitHub에 push했다. 다른 참가자 기능의 미배포 변경을 포함하지 않았다. 관련 표적 검사, Git 릴리스 파일 일치, 운영 DB 4개·파일 56개 복구 사본과 복원 검증, 관리 배포 `OWNER_UI_DEPLOYMENT_PASS`와 health/ready 200을 확인했다. 단일 근거 DB도 별도 사본·행 해시 일치를 검증했으며 이후 운영 백업 대상에 포함되도록 했다.

최종 활성화 뒤 실제 예약 판단 화면에서 기존 부킹닷컴 카드 연결이 표시되는 것을 확인했다. Aside의 reload는 30초 탐색 대기 오류를 냈으나 후속 전체 스냅샷에서 완료된 화면과 카드 표가 확인됐다. 첫 재계산의 지연을 정상 속도 검증으로 보고하지 않는다. 원문 거래·장부·사용자 확정·보류·여행·수동 분류와 OTA 검토 저장소의 모든 보호 대상 행은 활성화 전후 동일했다. Google 쓰기·전체 pytest·전체 브라우저 검사는 하지 않았다.

실제 원문과 이전·반복 적재·압축·예정일 보완·카드 연결·운영 사본·활성화·최종 보호 결과는 Git 제외 경로 `.local-archive/ota-unified-20261020/`와 운영 `backups/ota-unified-20261021/`, `backups/v2-owner-ui-20261021T112018/`에 있다. 아고다 전체 우선 예약 상세 수집과 새 현장 결제·캐시·취소 양식의 후속 해석은 진행 중이며 완료로 표시하지 않는다. 최신 범위는 [단일 OTA DB 기록](ota-unified-store.md)을 따른다.


## 2026-10-20 예약 자료 미연결 안내 수정

운영 릴리스는 `f5e27d3a06ad010656dd43f8d01af2ccc42cb5b5`다. 지출 정리에서 카드 거래와 연결된 OTA 예약이 검토 목록에 없으면 표시되던 부정확한 안내를 수정했다. 이제 현재 연결된 자료가 없다는 사실, 예약 확인서의 예약번호·이용기간 확인, 카드 결제일만으로 여행을 정할 수 없다는 점을 표시한다. 전체 예약 자료 조사 완료나 예약 자체의 부재를 뜻하지 않는다. 예약 연결·여행 배정·회계 쓰기 로직과 운영 거래는 수정하지 않았다.

합성 격리 DB에서 수정 전 실패를 재현하고 표적 테스트 1개가 수정 후 통과했다. 조회 전후 거래 전체 필드도 동일했다. 전체 회귀는 안내 문구만 변경해 생략했다. diff 검사와 릴리스 파일의 Git 객체 일치 검사를 통과하고 main에 push한 뒤 기존 배포 절차로 반영했다. 백업·복원 근거 `D:/WebLedgerHost/data/backups/v2-owner-ui-20261020T154914/restore-evidence.json`에서 DB 4개·파일 55개, 운영 원본 불변·복원된 검토 연결 일치를 확인했다. 배포 결과 `OWNER_UI_DEPLOYMENT_PASS`, 배포 중 로컬 health/ready 각각 200, Board·SourceRefresh Running을 확인했다. 후속 PowerShell 요청에서 health 200, 비로그인 `/import` 401, Board Running·SourceRefresh Ready를 확인했다. Python HTTP 요청은 시간 초과됐으나 PowerShell 요청은 정상 응답했다. Aside 브라우저는 빈 상태만 반환하고 새 탭이 유지되지 않아 로그인된 실제 화면의 문구는 확인하지 못했다. 재개 시 정상 로그인 브라우저에서 지출 정리의 아고다 상세 검토 안내만 읽기 전용으로 확인하면 된다.

## 2026-10-19 아고다 자연어 분류 규칙 운영 반영

현재 실행 중인 코드 릴리스는 `d90bef2e8370c4bca065328dc0df64df7a24616e`다. `origin/main`에 push한 뒤 고정 릴리스로 배포했으며 `OWNER_UI_DEPLOYMENT_PASS`, 로컬 `/healthz`와 `/readyz` 각각 200, `WebLedger-Board`와 `WebLedger-SourceRefresh` 모두 Running을 확인했다. 배포 전 릴리스는 `e59cb1c0a7deaab46bdf4d8a4025341fcf47564b`이며 운영 복구 스크립트가 이전 작업 등록 상태를 확인했다.

아고다 가맹점을 보고 있을 때 `아고다 결제는 숙박비로 분류하고, 예약 이용기간으로 여행을 찾아줘` 같은 복합 지시의 비용 항목 부분을 기존 동일 가맹점 분류 제안으로 처리한다. 예약 이용기간에 따른 새 자동 여행 배정은 구현하지 않았고, 복수 여행 시 미배정을 요구해 기존 사용자 승인 규칙과 충돌하면 제안에 안내한다. 실제 비용 항목 변경은 미리보기 후 별도 승인을 요구하며 여행 배정·기존 결정·원문·보류·환불 보호는 그대로 유지한다. 규칙 저장 뒤 자동 기록 권한 거절을 규칙 저장 실패로 오인하지 않도록 안내를 고쳤다.

직접 영향 표적 검사 5개가 통과했고 `git diff --check`와 릴리스의 Git 객체 일치 검사를 통과했다. 더 넓은 브라우저 테스트 묶음은 실패가 나타나 중단해 전체 통과라고 주장하지 않으며, 변경하지 않은 경로의 전체 재검증은 생략했다. 운영 백업·복원 근거는 `D:/WebLedgerHost/data/backups/v2-owner-ui-20261019T013938/restore-evidence.json`으로 DB 4개·파일 55개, 원본 불변·복원된 검토 연결 일치가 참이다. 실제 운영 카드 승인·장부 기록 요청은 수행하지 않았다. 로그인된 운영 `/import` 화면을 읽기 전용으로 확인한 결과 정리 대상 263건, 화면에 표시된 카드 20건, 제안 입력 20개, 펼칠 수 있는 상세 검토 20개였다. 과거의 483건 화면과 같은 시점의 수치로 비교하지 않는다.

## 2026-10-18 지출 정리 카드형 UI 운영 확인

현재 배포된 코드 릴리스는 `e59cb1c0a7deaab46bdf4d8a4025341fcf47564b`다. 지출 정리의 각 거래에 거래 검토 카드, 금액, 상태 배지, 자연어 규칙 제안 입력, 별도 승인 미리보기, 펼치는 상세 검토, 기존 여행 수정 기능을 표시한다. 제안 API는 읽기 전용이며 실제 분류 변경은 사용자가 별도 승인한 뒤에만 적용한다. 보류·원본 충돌·파싱 오류 거래는 이 제안 입력 경로에서 제외한다. 자연어 여행 배정 규칙의 자동 적용은 이번 범위에 포함되지 않았으며 여행 수정은 기존 검토 경로를 쓴다.

표적 UI·브라우저 검사와 390px 합성 Chromium 테스트가 통과한 뒤 `e59cb1c`를 `origin/main`에 push하고 운영 배포했다. 배포 시 `OWNER_UI_DEPLOYMENT_PASS`, 공개 health/ready 각각 200 및 Board·SourceRefresh Running을 확인했다. 백업·복원 근거 `D:/WebLedgerHost/data/backups/v2-owner-ui-20261018T120126/restore-evidence.json`은 DB 4개·파일 54개, 원본 불변·DB 구조·파일 해시·복원된 검토 연결 일치가 모두 참이며 실제 거래 재실행이나 데이터 변경을 수행하지 않았다.

2026-10-18 로그인된 운영 데스크톱 화면 `https://ledger.foresttour.kr/import`에서 새 카드와 규칙 제안 입력·버튼이 실제 표시되는 것을 확인했다. 화면은 전체 263건, 페이지의 카드 20건을 표시했다. 첫 카드의 `상세 검토`를 펼쳐 예약 근거 안내·여행 선택·비용 항목·`여행 수정` 버튼이 표시됨을 확인했다. 이 검증 중 승인·여행 저장 등 운영 쓰기 동작은 실행하지 않았다. 데스크톱 문서 폭은 1425px, 뷰포트는 1440px이었고, 실제 운영 모바일 기기 화면 확인은 하지 않았다. 별도 표적 검사가 이미 통과했으므로 전체 회귀와 운영 데이터 재수집은 반복하지 않았다. 이하 절은 과거 운영 기록이다.

## 2026-10-13 카드 다음 행동과 자동 기록 UX 완료

마지막 표시 문구도 `350b6ba`로 수정해 예약이 수집됐다고 단정하지 않고 필요한 예약번호·이용일을 안내한다. 운영 `b3c6432`의 마지막 백업·복원은 `D:/WebLedgerHost/data/backups/v2-owner-ui-20261013T102132/restore-evidence.json`에 보존한다. 문구 표적 검사 1 passed이며 공개 health/ready 200이다. 신규 전기 17행의 금액도 각각 원문과 일치함을 추가 확인했다. 실제 예약 연결 영역으로 이동은 확인했으나 직전 스냅샷을 표시 중이었고 해당 후보는 관찰되지 않아 실제 후보 강조·예약 연결 확정은 검증하지 않았다. 이 데이터 의존성을 해결한 것으로 표시하지 않는다.

현재 운영 SHA는 `b3c6432bd39c34a9f3c61e07ac32144317b7d326`다. 사용자 요청의 분류 후 불필요한 기록 단계를 제거했다. 소유자 화면의 자동 처리 요청과 답변 저장에서 조건이 갖춰진 거래를 기존 미리보기·원자적 기록 경로로 반영한다. 항목·여행 또는 분기 목적지·원본·중복·일정·사용자 보류·OTA 연결·환불 보호를 유지하며 Google에는 쓰지 않는다. 자동 기록은 사용자 확정 여부를 그대로 유지하고 게시된 행에도 원래 분류 상태·근거와 자동 이력을 남긴다. 기존 수동 API의 보호와 호환성을 유지하되 화면의 수동 전체/환불 기록 버튼은 숨겼다.

카드 목록은 ‘여행 지정’, ‘비용 항목 선택’, ‘예약 연결 확인’, ‘환불 기록 확인’, ‘장부 보기’와 개별 이유를 표시한다. 링크에는 거래 ID를 넣고 해당 수정창·연결된 환불·기존 예약 결제 연결 영역으로 이동한다. 조회 API는 쓰지 않으며 소유자·CSRF 검사는 서버에서 수행한다. 예약 후보 강조는 선택만 보조하며 라디오 선택이나 연결 확정을 자동으로 하지 않는다.

운영 확인에서 89,891원에 표시되던 환불 오류는 파일 전체 자동 처리 실패가 각 거래의 이유로 덮인 것이었다. 보류한 환불 묶음 때문에 관련 없는 정상 거래까지 멈추던 자동 경로를 분리했고, 자동 기록에서는 새로 기록할 거래만 환불 구성 검사를 받는다. 새 환불 쌍의 전체 검증·원자성은 유지한다. 실제 두 건의 개별 문제는 예약과 카드 결제 연결 미확정이다. 최종 카드 목록에서 둘 다 ‘예약 연결 확인’과 구체적 이유가 표시되고 자동 처리 오류는 0건이다. 두 건은 기존 보호에 따라 기록하지 않았다.

최종 운영에서 정상 거래 17건이 자동 기록돼 내부 장부가 736행에서 753행으로 늘었다. 기존 transactions·board_rows·ledger_entries·review_decisions·transaction_review_holds·transaction_company_exclusions의 모든 기존 행은 배포 전과 동일하다. 신규 장부 17행과 신규 전기 17행의 거래 ID 집합이 일치하고 각 금액이 원문과 일치한다. 원문 거래·사용자 확정·보류·제외 자료의 신규/변경은 없다. 근거는 `.local-archive/card-next-action-20261013/protected-after.json`에 보존한다.

검사는 자동 기록·다음 행동·모바일·기존 수동 계약·부분 환불·권한 묶음 43 passed / 3 subtests, 소유자 거부 추가 1 passed, 원문·자동 이력·롤백 표적 검사와 UI 영향 검사 통과다. 마지막 파일 내 보류 묶음 분리·환불 원자성·롤백·기존 환불 계약은 36 passed다. 변경된 모바일 이동 경로와 실제 보류 사유 우선순위도 표적 검사로 통과했다. 한 번 통과한 범위를 변경 없이 전체 재실행하지 않았으며 전체 회귀·OTA 전수 대사·Google 쓰기는 수행하지 않았다.

첫 운영 자동 요청의 sqlite3.InterfaceError는 공유 연결의 자동 처리 잠금 범위를 보완한 뒤 재현되지 않았다. 계속 요청 시 원래 임시 작업 공간이 이미 정리돼 있었으나 완료 코드는 commit/push와 고정 release에 보존됐다. 현재 운영에 추가돼 있던 `1ce47f6`의 읽기 공유·권위 자료 캐시·liveness·OTA 실패 재시도 조절을 그대로 통합해 보존했으며 과거 성능 작업을 재실행하지 않았다.

마지막 배포는 `D:/WebLedgerHost/data/backups/v2-owner-ui-20261013T101210/restore-evidence.json`의 DB 4개·파일 51개 복원 비교·원본 불변·검토 연결 동등성을 통과하고 `OWNER_UI_DEPLOYMENT_PASS`로 완료했다. 공개 health/ready 200, Board·SourceRefresh Running이다. 실제 로그인 카드 화면에서 다음 행동·오류 없음·가로 넘침 없음을 확인했다. 모바일 화면 근거는 합성 Chromium 390px 검사이며 운영 브라우저를 모바일이라고 주장하지 않는다.

핵심 구현 `9da6610`, 공유 연결 잠금 `f76cf24`, 구체 사유 `8aaaa6a`, 거래 초점 `dc3ef6c`, 파일 내 묶음 분리 `4c15472`, 운영 `b9dbb95`, 통합 `4864c70`을 PR #85에 push했다. 후보와 백업·보호 증거는 `.local-archive/card-next-action-20261013/` 및 관련 후속 폴더에 보존한다. 아래 절은 이전 기록이다.

## 2026-10-13 전액 환불 탭과 과거 내역 제외

현재 운영 SHA는 `6615ebfedfffb9cb04c8a6c36a473f0a4c6efdb7`다. 소계 0원인 전액 환불만 읽기 전용 환불 탭에 모았으며 실제 107쌍·219행 모두 순액 0원을 확인했다. 원승인번호로 연결된 환불과 같은 카드·승인번호의 유일한 원결제를 확인한 취소만 묶는다. 부분 환불은 환불 탭에서 제외하고 기존 여행에 원결제·환불과 잔액을 유지한다. 이미 기록된 전액 환불은 같은 여행에 모든 구성원이 기록되고 저장 금액 합계도 0일 때만 여행 목록에서 표시를 옮긴다. 장부·Google·원본 거래·확정·보류·환불 연결 자료는 쓰지 않았다.

2025년과 2026년 1분기의 완료 자료를 내부 보존한다는 기존 규칙이 새 카드·OTA 목록에 누락돼 미배정으로 노출됐던 표시 문제를 수정했다. 카드 거래일과 OTA 이용기간을 각각 적용하며 미배정 집계·월 필터에서도 제외한다. 날짜 불명확·기간 충돌·기준일 이후까지 이어지는 예약은 유지한다. 운영 확인에서 `2026-01-11T00:00:00` 형태의 종료일 때문에 1월 예약 한 건이 남아 있는 것을 재현했으며 시간 포함 날짜 파싱을 수정해 운영 재확인에서 1분기 월 필터와 1월 이용 행이 없음을 확인했다. 이용일·결제일 원문은 변경하지 않았다.

검사는 최초 59 passed / 13 failed였다. OTA 기간 필드 참조 오류와 과거 기간을 조회하던 정렬 테스트, 이전 화면 정리의 오래된 기대값을 수정해 해당 범위 15 passed로 해소했다. 이후 환불·카드·모바일 표적 검사는 12 passed / 3 subtests, 여행에 남는 부분 환불 잔액 검사 1 passed, 시간 포함 이용일과 환불 모바일 표시 검사 2 passed다. 다른 작업의 미배포 영수증 코드는 배포에 섞지 않았다. 전체 회귀·OTA 전수 대사·Google 쓰기·운영 거래 기록은 수행하지 않았다.

백업·복원 검증은 `D:/WebLedgerHost/data/backups/v2-owner-ui-20261013T032425/restore-evidence.json`과 날짜 수정 후 `D:/WebLedgerHost/data/backups/v2-owner-ui-20261013T032758/restore-evidence.json`에서 각각 DB 4개·파일 51개·전체 테이블/칼럼·원본 해시·검토 연결 동등성을 통과했다. 배포 전후 board_rows·ledger_entries·transactions·review_decisions·transaction_review_holds·transaction_company_exclusions의 전체 행 해시가 동일하다. 공개 health/ready 200, Board·SourceRefresh Running이다. 실제 카드 50행에서 과거 거래·과거 월 없음과 가로 넘침 없음을 확인했다. OTA 재시작 직후 첫 읽기는 브라우저 도구 15초 제한을 넘었으며 요청 완료 후 해당 경로만 확인했다. 잘못된 `/api/cards`는 목록 API가 아니므로 검증 근거에서 제외했다.

부분 환불 원결제 중 현재 검토기간의 여행 미지정 자료는 14건이다. 공통 경비·분기 비용·기존 사용자 확정이 포함돼 이를 임의 여행에 배정하지 않았다. 여행 비용에 해당하는 자료의 실제 이용기간 또는 사용자가 지정할 여행이 필요하다. 전액 환불 탭과 기존 여행의 부분 환불 유지, 과거 자료 표시 수정은 COMPLETE이며 이 14건의 새로운 여행 지정은 PARTIAL이다.

구현 `b0d9732`와 날짜 수정 `9ff42cd`, 운영 `6615ebf`, 통합 `a3ac3e9`를 PR #85에 push했다. 후보와 보호 비교 근거는 `.local-archive/refund-tab-history-20261013/`와 `.local-archive/refund-tab-datefix-20261013/`에 보존한다. 아래 절은 이전 기록이다.

## 2026-10-13 남은 화면 설명 정리

현재 운영 SHA는 `b0ed01745d766cd9a290b92fd1cb50fbdc9e2bb0`다. 출력 화면의 중복 집계와 양식 구현 설명을 제거하고, 미확정 거래 포함 안내는 짧게 유지했다. Google 장부의 정상 기술 상태 목록은 숨기고 실패·오래된 동기화는 한국어 경고로 표시한다. 원본 검토의 반복 설명을 제거했으며, 실제 연결된 규칙 초안 버튼의 잘못된 ‘합성 턴’ 표시를 없앴다. 저장·반영·출력·권한·금액·사용자 결정·환불·OTA 연결 로직은 변경하지 않았다. 영수증 환산 기준과 외부 전송 동의는 필요한 업무 안내이므로 유지했고, 다른 작업의 미배포 영수증 코드를 배포에 섞지 않았다.

출력 담당자 보호·Google 장부·규칙 브라우저·원본 검토 브라우저 검사에서 91 passed / 2 subtests, 오래된 기대값 2건 실패였다. Google 오류 표시 기대값과 기존 두 스크립트의 개수 검사를 수정했으며, Google 실패 안내·출력 폼·규칙 확인의 표적 3 passed와 원본 텍스트 주입 검사 1 passed로 해당 실패를 해소했다. 통과한 검사를 반복하지 않았다. 전체 회귀·운영 거래 쓰기·OTA 전수 대사·Google 재수집은 표시 변경에 필요하지 않아 생략했다.

배포 전 `D:/WebLedgerHost/data/backups/v2-owner-ui-20261013T030622/restore-evidence.json`에서 DB 4개·파일 51개의 복원 비교, 원본 불변, 검토 연결 동등성을 확인했다. 배포 결과는 `OWNER_UI_DEPLOYMENT_PASS`이며 Board·SourceRefresh가 Running이다. 공개 주소의 기본 명령줄 요청은 403으로 차단됐고, 로그인 브라우저 health/ready는 모두 200이다. 정상 사용자 에이전트를 지정한 비로그인 카드 API는 401이다. 실제 출력 페이지는 선택 항목 41개·출력 폼 유지·중복 설명 삭제·가로 넘침 없음을 확인했다. 실제 Google 장부 59행에서 정상 기술 상태 목록 제거와 가로 넘침 없음을 확인했다. 운영 데이터 기록은 수행하지 않았다.

구현 `caa1673`, 운영 `b0ed017`, 통합 `9160749`를 PR #85에 push했다. 후보와 준비 스크립트는 `.local-archive/ui-cleanup-followup-20261013/`에 보존한다. 아래 절은 이전 기록이다.

## 2026-10-13 수입 중복·지출 배경·설명 정리

현재 운영 SHA는 `b4e1ec120976ce892454b358c3dfff05fad5eebc`다. Google 여행 수입은 ‘수입’으로 통일하고, 별도 COST 수입 행이 없으면 데스크톱·모바일의 빈 수입 0원·빈 목록 영역을 렌더링하지 않는다. 실제 기존 수입 행은 보존한다. 모바일 지출 버튼의 기본 배경을 투명하게 하고 브라우저 기본 버튼 모양을 해제했다. 선택 표시·키보드·행 편집 동작은 유지한다.

OTA·카드 목록과 예약 명단 연결의 장문 설명, Google 연결 설정의 반복 설명, 검토 메모의 미연결 자동처리 문구를 제거했다. 공통 화면의 고정 카드 흐름·OCR·사진 도움말을 제거하며, 스크립트·오류·보류·원본 값·외부 전송 동의 문구는 보존한다. 홈에는 설정되지 않은 영수증·Google 기능의 자리표시자를 만들지 않고 사용할 수 있는 메뉴만 표시한다. 저장 준비 중인 비활성 편집 버튼도 표시하지 않는다. 실제 수기 지출·OCR·규칙·복사·권한 관리 기능과 데이터는 삭제하지 않았다. 다른 작업의 미배포 영수증 코드도 이번 배포에 섞지 않았다.

관련 표적 검사 84 passed / 8 subtests다. 모바일 320px·390px 합성 검사에서 단일 Google 수입 영역, 총액·이름 표시 유지와 지출 투명 배경을 확인했다. 필터·행 원본·예약 연결·설정·편집 경로도 검증했다. 전체 회귀·OTA 전수 대사·Google 재수집·운영 시험 기록은 표시 변경에 필요하지 않아 생략했다.

배포 전 `D:/WebLedgerHost/data/backups/v2-owner-ui-20261013T005531/restore-evidence.json`의 DB 4개·파일 51개 복원 비교와 원본 불변을 통과했다. 공개 health/ready 200, 비로그인 카드 API 401, Board·SourceRefresh Running이다. 로그인된 운영 장부에서 Google 제목 ‘수입’, 빈 COST 수입 없음, 지출 262행과 수기 지출 버튼 유지·가로 넘침 없음을 확인했다. 실제 OTA 50행에서 장문 설명 삭제를 확인했다. 운영 브라우저는 데스크톱이며 모바일 근거는 합성 검사로 구분한다.

구현 `c863197`, 운영 `b4e1ec1`, 통합 `e1de16a`를 PR #85에 push했다. 후보·스모크·합성 캡처는 `.local-archive/ui-cleanup-20261013/`에 보존한다. 아래 절은 이전 기록이다.

## 2026-10-13 내역 기본 오름차순 정렬

현재 운영 SHA는 `23e8b9354b54109e2d8b15e81c5cb04d8ccdf181`다. OTA·전체 카드·카드 검토·여행 장부·Google 수입/지출 상세의 표시를 날짜 오름차순으로 맞췄다. 날짜 불명확 행은 뒤에 둔다. 카드 검토 초기화도 오름차순을 유지한다. 기존 내림차순 선택·월 필터·검색·페이지 이동은 유지하며 명시적인 사용자 정렬 선택을 덮지 않는다. 장부 지출은 날짜를 먼저 정렬하고 같은 날짜 안에서 기존 비용 분류 순서를 유지한다. 저장 순서·원문·금액·확정·TSV·Google 원본은 변경하지 않았다.

표적 묶음은 65 passed / 4 subtests와 선택 표시 때문에 버튼을 찾지 못한 브라우저 하위 실패 5건이었다. 두 검사의 선택자를 고친 후 해당 2 passed / 5 subtests로 통과했다. 통과 범위를 반복하거나 합산하지 않았다. 전체 회귀·OTA 전수 대사·운영 거래 기록·Google 재수집은 이번 표시 변경에 필요하지 않아 생략했다.

배포 전 `D:/WebLedgerHost/data/backups/v2-owner-ui-20261013T004038/restore-evidence.json`에서 DB 4개·파일 51개의 복원 비교와 원본 불변을 확인했다. 공개 health/ready 200, 비로그인 카드 API 401, Board·SourceRefresh Running이다. 로그인된 운영 카드 첫 50행과 OTA API 첫 50행의 날짜 오름차순을 확인했다. 최초 결합 브라우저 확인은 OTA 읽기 중 도구 15초 제한을 넘었고, 해당 요청 완료를 확인한 뒤 캐시가 준비된 OTA 경로만 확인해 200·오름차순을 검증했다. 서버 재시작이나 수집을 반복하지 않았다.

구현 `832275a`, 운영 `23e8b93`, 통합 `4d83f56`을 PR #85에 push했다. 후보·스모크·합성 캡처는 `.local-archive/sort-ascending-20261013/`에 보존한다. 아래 절의 운영 SHA는 이전 기록이다.

## 2026-10-13 분기 기타비용 연결과 모바일 수입표

현재 운영 SHA는 `68b0fee8f38c67c13cd43ed4227d32760e9c0479`다. 기존 Google 파서가 날짜로 시작하는 여행 탭만 읽어 분기 탭을 제외했던 누락을 수정했다. `1~4분기_기타비용`을 지출 전용 장부로 읽으며 여행·수입 탭으로 만들지 않는다. 실제 메인의 `3분기_기타비용`은 2026년·지출 7열·합계 검증을 통과했다. 보관 1분기는 구형 양식이라 복사할 수 없다. 2·4분기 탭은 현재 자료에 없다.

분기 비용의 복사 목적지는 원문 날짜의 연도·분기로 계산하되 원래 여행 배정·확정·금액은 유지한다. 원본 탭의 연도·양식·정본 선택·신선도·합계가 모두 맞아야 복사를 허용한다. 보류·취소·중복·다른 여행 거래를 섞지 않는다. 전체 카드 표에서는 여행 외 분기 비용을 ‘미배정’ 대신 실제 분기명으로 표시한다. 운영 171건의 목적지는 3분기 151건, 2분기 15건, 4분기 5건이며 이는 복사 가능한 최종 행 수가 아니다. 추가 미리보기 보호를 통과한 행만 복사한다. 기존 미배정 일반 복사에 분기 비용을 넣지 않는다.

모바일 수입표는 날짜·이름/닉네임·총액 세 열이다. 날짜는 `4월6일`처럼 표시하고 명시 기간은 양 끝을 유지한다. 이름이 있으면 이름만, 비어 있으면 닉네임을 표시한다. 모바일에서는 예약금·잔금·추가금 열을 숨기되 데스크톱과 원본에는 유지한다. 각 표시 항목에 아이콘을 넣고 큰 총액이 잘리지 않게 했다. 원본 행·Google 셀은 변경하지 않았다.

표적 결과는 Google 파서·분기·기존 복사·카드 목록·수입·인접 배치 75 passed / 2 subtests, 모바일·카드 검토·서명 HTTP 22 passed / 41 subtests, 분기 클립보드 브라우저·Google 페이지 36 passed다. 범위가 겹치므로 합산하지 않는다. 320px·390px 합성 브라우저에서 날짜 기간·이름 우선·닉네임 대체·54,840,000원 총액·아이콘·가로 넘침 없음을 확인했다. 합성 분기 복사에서 3분기만 7열로 복사, 4분기 거부, 원본·결정 동일과 장부 미기록을 확인했다. 전체 회귀·OTA 전수 대사·실제 운영 시험 기록은 필요하지 않아 생략했다.

배포 전 복구 근거는 `D:/WebLedgerHost/data/backups/v2-owner-ui-20261013T001228/restore-evidence.json`이다. DB 4개·파일 51개의 복원 비교와 원본 불변을 통과했다. Google 정기 읽기 작업을 같은 새 release로 연결하고 읽기 전용 동기화 1회를 성공했다. 파서 버전 변경으로 기존 내용 해시가 같아도 새 분기 탭을 한 번 재파싱한다. 공개 health/ready 200, 비로그인 카드 API 401, Board·SourceRefresh Running과 GoogleAuthority Ready를 확인했다.

실제 로그인된 운영 브라우저에서 새 날짜·통합 이름·총액과 잘림 없음을 확인했다. 리사이즈 도구는 390 성공을 반환했지만 실제 viewport는 1280이어서 이를 운영 모바일 검증으로 보고하지 않는다. 모바일 근거는 합성 Chromium 검사다. 후보·배포·스모크·합성 캡처는 `.local-archive/quarter-mobile-20261013/`에 보존한다. 구현 `4b0c8e7`, 운영 `68b0fee`, 통합 `6e27bef`를 PR #85에 push했다. 아래 절은 이전 운영 기록이다.

## 2026-10-12 세션 인수 후 카드 검토·수입 표시 반영

현재 운영 SHA는 `adaa50ba27af532a7522ba9e47f6a0b89fdcbca6`다. 이전 `92d1627` 위에 검증한 화면 변경만 적용했다. 카드 검토는 접이식 자료 선택, 상태 건수, 검색·월·항목 필터, 거래일·금액 정렬과 OTA 아이콘을 제공한다. 필터 상태에서는 전체 묶음 기록을 막고 전체 미리보기 확인을 요구한다. 기존 수정·여행 배정·규칙·환불·복사 계약은 유지한다.

빈 COST 수입 합계·차액은 숨기고 Google에서 읽은 여행 수입을 유지한다. 실제 COST 수입 행은 보존한다. 수입·지출 원본 상세는 선택된 메인 또는 보관 Google 장부의 실제 여행 시트로 연결한다. Google 원본·공유 권한·운영 DB 스키마는 변경하지 않았다.

최초 인접 묶음은 24 passed / 4 subtests와 화면 변경에 따른 기대값 오류 2건이었다. 두 기대값 수정 후 해당 2 passed / 2 subtests, 최종 표적 검사 5 passed / 2 subtests다. 범위가 겹치므로 합산하지 않는다. 전체 회귀·OTA 전수 대사·운영 거래 확정은 생략했다. 실제 로그인 운영 화면과 Google 새 탭 이동은 미검증이며 합성 검사·링크 검증과 구분한다.

배포 전 `D:/WebLedgerHost/data/backups/v2-owner-ui-20261012T220642/restore-evidence.json`의 백업·복원 검증을 통과했다. localhost health/ready와 공개 health/ready 200, 비로그인 import 401, Board·SourceRefresh Running을 확인했다. [인수 기록](session-takeover-20261012.md)에 구현·배포·이전 미완료 범위를 구분했다. 아래 절의 운영 SHA는 과거 기록이다.

## 2026-10-12 COST V2 운영 반영

현재 운영 SHA는 `124b33734456819c670c20ff01548385a1a0cebd`다. 공통 메뉴를 정리하고 여행 목록의 COST 수입 0원 표시를 날짜로 바꿨다. 실제 Google 수입은 여행 상세의 Google 장부 영역에서 확인하며 미연결·미검증과 실제 0원을 구분한다. OTA에는 예약 상태·여행 배정 아이콘과 기간 경고·빈 화면 안내를 추가했다. 실제 owner 390px OTA에서 새 메뉴·상태 표시·0원 badge 제거·가로 넘침 없음을 확인했고 기존 Board와 SourceRefresh는 실행 중이다. 회계 데이터·스키마·Google 원본은 변경하지 않았다. 합성 브라우저와 표적 검사 근거 및 미배정 원인 집계는 [체크포인트](autonomous-cycle-checkpoint.md#현재-운영-반영-2026-10-12)를 따른다.

카드 3820의 2026-09-19~09-24 싱가포르 배정 예외를 `eca52c89fed7ff291977bb126bd4bd6b85997bcf`로 운영 반영했다. 사용자 지시를 일정 근거로 보존하고 `0919_0924_싱가포르` 여행을 추가해 미확정 사용내역 13건을 배정했다. 분기 기타비용보다 이 예외를 우선하며 자동 확정·장부 기록·Google 쓰기는 하지 않는다. 격리 복구 사본에서 대상 원본 필드·대상 밖 거래·보호 테이블 보존과 반복 분류를 확인했다. 새 표적 8 passed, 기존 분기 규칙·사용자 일정 인접 11 passed다. 운영 백업·복원 근거는 `D:/WebLedgerHost/data/backups/v2-owner-ui-20261012T165635/restore-evidence.json`, 적용·복구 근거는 `D:/WebLedgerHost/data/backups/singapore-exception-20261012T075647961050Z/result.json`이다. 스키마 변경 없이 기존 호스트·수집기를 유지했다.

이전 메뉴 통합 배포는 `56867150de2db90a3f4e0152a685f2d1c50466c3`다. OTA 메뉴를 ‘OTA 내역’ 하나로 합치고 페이지 안에서 ‘전체 예약·여행 미배정’을 전환한다. 카드 메뉴·제목·진입 링크는 ‘카드 내역’으로 통일했다. 카드 검토의 동적 아이콘 따옴표와 환불 버튼 문자열 오류를 고쳐 스크립트 실행을 복구했고, 모바일 홈 작업 메뉴는 짧게 표시해 여행 목록 공간을 확보했다. 저장·회계·스키마 변경은 없다.

OTA 메뉴에 `/ota` 전체 내역과 `/ota?state=unassigned` 미배정 내역을 추가했다. owner만 등록된 OTA 예약 DB와 메일을 읽기 전용으로 조회하며, 같은 제공자의 같은 예약번호는 한 건으로 표시한다. 취소·결제 예정 예약도 제외하지 않는다. 미배정은 저장된 예약·장부의 여행 연결이 없는 상태이며 카드 결제 대사 여부와 다르다. 검색, 이용일 정렬·월별 조회, OTA별 필터, 50건 페이지 이동과 공통 사이드 메뉴를 지원한다. 조회 API는 `/api/ota`다. 원본·분류·회계 확정·스키마를 변경하지 않는다. 카드 검토용 XLSX는 OTA DB로 읽지 않으며, 여러 메일 폴더의 내용 해시 기반 파싱 캐시를 재사용하고 예약 목록에서 결제 재대사를 수행하지 않는다.

전체 카드 내역의 거래일 헤더에서 정렬 방향과 조회 월을 선택할 수 있다. 카드·상태 필터도 해당 헤더에 배치했으며 선택 즉시 적용한다. 검색 조건과 페이지 이동 조건을 유지하고 모바일에서도 사용할 수 있다. DB를 변경하지 않는 조회 기능이다.

공통 사이드 메뉴를 운영 반영했다. 카드 검토·전체 카드·영수증·Google 장부·예약 연결·여행·계정 화면에서 메뉴를 유지하며 PC에서는 고정하고 모바일에서는 접는다. 현재 메뉴를 표시하고 메뉴 스크롤과 최근 여행 선택을 복구한다. 실제 운영 390px 메뉴 이동과 health/ready 200을 확인했으며 DB·스키마는 변경하지 않았다.

OTA 목록의 최초 배포는 `374cebc1fba2594111d1d55801cceb3c37db8aa8`였다. 현재 운영 SHA는 이 절 첫 문단을 따른다. main 병합이나 인프라 이전은 하지 않았다. 실제 로그인·화면 접근·Google 읽기, 로컬 OCR·AI, 백업·스키마 적용 및 부분 구현의 최신 근거는 [자율 개발 체크포인트](autonomous-cycle-checkpoint.md#현재-운영-반영-2026-10-12)를 따른다. 추가 월 비용은 0원이다.

‘예약 명단·여행 연결’은 예약 명단을 COST 여행에 연결·적용하는 메뉴이며 카드 대사·수입 확정과 다르다. 여행 장부의 ‘Google 수입내역’에서 연결 설정을 열면 현재 COST 여행이 선택된다. 사용자 승인 후 이름·일정이 단일하게 일치하는 운영 여행 19개를 자동 연결했다. 중복·사본·연도 충돌은 수동 확인 대상으로 남긴다. 같은 여행의 Google 탭을 직접 선택해 연결을 수정할 수도 있다. Google 수입을 COST 수입으로 복제하거나 Google 원본을 변경하지 않는다.

전체 카드 내역은 `/cards`이며 홈·카드 검토 화면·장부 업무 메뉴에서 접근한다. owner만 DB의 모든 카드 거래를 읽기 전용으로 조회한다. 기간 제한 없이 취소·환불·중복·회사 제외 거래도 포함한다. 50건씩 페이지 이동, 검색·카드·분류 상태 필터와 원래 업로드 검토 화면 이동을 지원한다. 원본 금액은 확정 지출 합계와 다르므로 이 화면에서 비용 합계를 만들지 않는다.

현재 `WebLedger-Board`의 고정 release 경로를 사용한다. 아래 과거 운영 SHA와 원본 checkout용 재시작 절차를 최신 배포에 그대로 적용하지 않는다. Google ADC 연결은 미완료이며 현재는 명시적인 기존 public export 방식이다. 실제 고객 자료나 공개 권한을 변경하지 않았다.

이하 날짜별 항목은 과거 운영 기록이다.

## 2026-10-10 입력 → 검토·규칙 → 출력 한 사이클 마감 (PR #53)

- 입력: 웹 카드 업로드가 `.xls`(이진), `.xlsx`, `.csv`를 받는다. `.xls`는 xlrd로 첫 시트를 읽고, 원본 셀을 보존하며, 같은 파일·같은 거래는 중복 기록하지 않는다. 승인내역 파일(매입일 없음)은 거부한다.
- 검토: 보드에서 "예외 처리(이 건만)"와 "규칙 변경(반복)"을 고르고, 규칙 화면의 "내 수정 내용으로 규칙 초안 만들기"가 가맹점 조건의 결정적 초안을 만든다. 영향 미리보기 후 `apply_existing`/`apply_future`를 골라 명시적으로 적용한다. 사용자 확정 값은 덮어쓰지 않는다.
- 출력: 보드에 보이는 값 그대로 XLSX로 나가며 장부 행은 변하지 않는다.
- 운영 의존성: 운영 venv에 `xlrd==2.0.2`가 필요하다(`D:\WebLedgerHost\config
untime-requirements.lock.txt`에 반영).
- 검증: 합성 자료 격리 E2E(브라우저 1440 포함)와 운영 읽기 스모크, 실제 장부 export 대조, 보호 기준선 게이트(278건 동일)를 수행했다. 전체 회귀는 다시 돌리지 않았다.

## 2026-10-10 reservation 여행 정본 동기화 수정과 master data 큐

**원인과 수정**: reservation 동기화가 게시판의 글 최대 5개를 차례로 upsert해 마지막 보조 글이 여행 제목·날짜를 덮었다(1115: 원글 1번 `11월15(일)~17`을 보조 글 3·6번의 `11.18~20` 언급이 덮음). reservation PR #15(`18f7a3c`)가 `pickOriginalPost`로 고른 원글만 정본(title/dates/leader/code)을 갱신하게 했다. 보조 글은 `cafe_tours` 증거로만 남고 순서에 무관하다. 원글을 못 읽으면 기존 정본을 유지하고 `tours.source_status`를 `main_unavailable`/`main_unresolved`로 남긴다(다른 글로 대체하지 않음).

**1115 정상화**: 카페 원본에서 원글(1번, 댓글 20)이 `11월15(일)~17/…`이고 파싱 결과가 2026-11-15~17임을 확인한 뒤, 정식 공개 경로 `refresh-tour?fldid=fOzD`로 갱신했다(직접 SQL 없음). reservation 날짜 11/15~11/17 = COST 11/15~11/17이고 정본 글 번호가 3→1로 돌아왔다. 날짜 불일치는 1건→0건이다.

**브리지 커버리지**: fldid 15→16건(날짜까지 일치), 코드 0, 충돌 0, 날짜 불일치 1→0, 연결 불가 24(변화 없음). 연결 불가 24건의 분류(진단 전용, `tools/guide_bridge_report.py`): 원천 없음 14(4~6월 등 reservation 목록에 없는 여행과 다른 계절의 같은 지역), 수동 코드 필요 8(날짜가 정확히 같은 reservation 여행이 하나뿐), 날짜 충돌 1(0924 야마구치: reservation 9/24–9/26, COST 9/24–9/27), 모호 1(10월_도고), 안정 키 복구 가능 0. COST 여행은 워크북 시트 기반이라 카페 원글 키를 갖고 있지 않다. 이전 시도에서 "날짜 충돌 5"로 보였던 4건은 같은 지역의 다른 계절 여행이 걸린 것이었다.

**master data 큐**: reservation 관리자에 `대장 항공권 정보 확인 필요`(`대장 관리` 맨 위)와 `여행 코드 입력 필요`(`투어 관리` 맨 위)가 있다. 읽기는 변경 0이고 저장은 명시 동작뿐이며 변경은 감사 테이블(`guide_flight_name_audit`, `tour_code_audit`)에 남는다. 코드 값을 제안하거나 자동 입력하지 않는다.

**운영 현황**: 대장 13명 중 항공권 영문명 등록 0·후보 유일 1·후보 없음 12. 여행 127건 모두 코드 없음(안전 후보 0). 스냅샷 세대 10(`0e391b2e417e`, authority fresh `0f56c2eb144a`)은 reservation 변경 후 자동으로 재평가됐다(약 9초). 매칭된 항공료 27건 모두 `HOLD_GUIDE_IDENTITY_UNCONFIRMED`, 장부 736행·73,998,707원, 보류 15, 확정 28 그대로. 보호 기준선은 현재 데이터에서 다시 계산해 277+1=278, 변경·누락·중복·수동 덮어쓰기 0이다.


## 2026-10-10 authority 신선도 쓰기 보호와 master data 입력 구조

**쓰기 보호**: COST PR #47(`0607c68`)과 후속 PR이 reservation authority를 fresh / degraded / unavailable로 나눈다. 화면 유예(`GRACE_SECONDS`=600초)와 쓰기 신선도(`WRITE_FRESH_SECONDS`=90초)는 별개 상수다. degraded·unavailable·90초 초과 상태에서는 새 대장 항공권 규칙을 만들지 않고, `guide_airfare_evidence`로 분류된 미확정 행은 미리보기·확정 시 서버 보류로 막힌다(미리보기는 같은 보류로 다시 계산되어 PREVIEW_STALE). 신선도 상태는 스냅샷 입력 지문과 스냅샷 메타데이터(`authority`: state·digest 앞 12자·오류 코드, 이름 없음)에 들어간다. reservation 호출은 계속 스냅샷 워커에서만 하며 요청 경로 호출은 0이다.

**reservation master data**: PR #13(`fd1c7c7`)이 대장 항공권 영문명 후보(실명이 정확히 같은 과거 예약·고객 자료, 관리자 화면 전용·자동 반영 없음), 명시 여행 코드 수집·보고·backfill, `GET /api/internal/master-data-report`(개수만)를 추가했다. 동기화는 모집글에 `MMDD_지역`/`YYYYMMDD_지역` 코드가 정확히 하나 있을 때만 빈 `tours.code`를 채운다.

**운영 현황(읽기 전용)**: 활성 대장 13명 중 영문명 등록 0, 후보 유일 1, 후보 다수 0, 후보 없음 12. 후보는 자동 승격하지 않았다. 여행 127건은 모두 코드가 없고 모집글 제목에도 명시 코드가 없어 안전 후보 0, 모호 0, 코드 없음 127이라 backfill 대상이 없다. 코드는 COST 여행 코드를 보고 거꾸로 만들지 않았다.

**브리지 커버리지**: COST authoritative 여행 40건 중 fldid로 연결 15건(날짜까지 일치), 코드로 연결 0건, 날짜 불일치 1건, 충돌 0건, 안정 키 없음 24건. 이전과 같다. 코드 입력이 채워지면 코드 브리지가 열린다.

**1115 날짜 불일치**: COST 등록은 원글(`fOzD/1`, 제목 `11월15(일)~17/…`, 댓글 8, 상태 `schedule_conflict`)이고 reservation 여행 행은 같은 게시판의 다른 글 제목 `11.17 흔한 단풍구경인 줄 알았는데..`과 날짜 11/18–11/20으로 덮여 있다. 동기화가 게시판 글 최대 5개를 차례로 반영하면서 마지막 글이 제목·날짜를 덮는 구조 때문으로 보이며, 날짜를 한쪽에 맞추지 않고 HOLD를 유지한다. 해소하려면 reservation 관리자에서 날짜를 원글 기준으로 수기 확정하거나 동기화가 원글만 제목·날짜를 갱신하도록 고쳐야 한다.

**결과**: 스냅샷 세대 8(`b7121e419c4b`, 약 113초), 매칭된 항공료 27건 모두 `HOLD_GUIDE_IDENTITY_UNCONFIRMED`(authority fresh), 장부 736행·73,998,707원, 보류 15건, 확정 28건 그대로. 보호 기준선은 현재 데이터에서 다시 계산해 277+1=278, 변경·누락·중복·수동 덮어쓰기 0이다.


## 2026-10-10 reservation guide authority 전환

**원칙**: 대장 신원과 담당 여행은 reservation, 여행 일정의 회계 authority와 비용 귀속은 COST다. COST는 reservation 내부 API를 읽기 전용으로만 쓴다.

**reservation**: PR #11(`b507bef`)이 `guides.flight_name_en`(항공권 영문명), 관리자 화면 입력란, `GET /api/internal/guides`, `GET /api/internal/tours`의 `leader_guide_id`·`include_past=1`을 추가했다. PR #12(`dfae839`)는 읽기 전용 두 라우트에만 통하는 `COST_INTERNAL_API_TOKEN`을 허용한다. 운영 배포 후 비인증 401, 인증 200이며 응답에는 id·닉네임·실명·영문명·상태만 있다.

**토큰**: Vercel Secret은 CLI로 읽을 수 없어 기존 `INTERNAL_API_TOKEN`은 건드리지 않았다. COST 전용 토큰을 새로 만들어 Vercel 운영 환경(민감 값)과 `D:\WebLedgerHost\secrets\reservation-internal-token.txt`(Git 밖)에 같은 값으로 두었다. 환경 변수 `RESERVATION_INTERNAL_API_TOKEN` 또는 `..._FILE`로 바꿀 수 있고 기본 주소는 `https://reserve.foresttour.kr`(`RESERVATION_INTERNAL_BASE_URL`)다. 토큰은 로그·스냅샷·예외에 쓰지 않는다.

**COST**: PR #45(`e05bde5`) 반영 후 PID 38140, 리스너 1개, `/healthz`·`/readyz` 200, 비로그인 루트 401, OTA authority 유지, DB 무결성 ok. 반영 전 백업은 `D:\WebLedgerHost\backups\pre-reservation-authority-20261010`이다. reservation 호출은 스냅샷 워커(지문 확인)에서만 하고 결과를 메모리에 캐시한다. 마지막 정상 값은 10분 유예 후 만료되며 그 뒤에는 `HOLD_GUIDE_AUTHORITY_UNAVAILABLE`로 fail-closed다. 미리보기·확정·분류 요청은 reservation을 호출하지 않는다.

**운영 자료(읽기 전용 집계)**: 대장 13명(모두 active, 실명 4명, 항공권 영문명 0명). 여행 127건 중 `code`는 전부 비어 있고 대장 연결 109건, 날짜 완비 97건. COST 여행 40건 중 reserve 등록 16건은 fldid로 연결되며 15건이 날짜까지 정확히 일치하고 1건(`1115_…`)은 두 시스템의 날짜가 달라 HOLD 대상이다. 등록이 없는 24건은 안정 키가 없어 브리지하지 않는다.

**결과**: 스냅샷 세대 7(`d152b1a41081`, 약 112초). 매칭된 항공료 27건은 모두 `HOLD_GUIDE_IDENTITY_UNCONFIRMED`이고 장부 736행·73,998,707원, 보류 15건은 그대로다. 보호 기준선은 게이트가 다시 계산해 277+1=278, 변경·누락·중복·수동 덮어쓰기 0이다.


## 2026-10-10 대장·가이드 항공권 귀속 반영

**반영**: main `dc3ddce`(PR #43)를 운영 checkout에 `--ff-only`로 맞추고 `tools/restart_real_review_host.ps1`로 재시작했다. 반영 전 `D:\WebLedgerHost\backups\pre-guide-airfare-20261010`에 장부·review DB·스냅샷·card-flow 설정을 백업했다. PID 48992→48280, 리스너 하나, `/healthz`·`/readyz` 200, 비로그인 루트 401, OTA authority 유지, DB 무결성 ok다.

**스냅샷**: 입력 지문에 대장 신원·여행 권위·파서·공항표 상태가 들어가 지문이 바뀌었고(`a72327cd6a14`→`53a838f8e2c8`) 스냅샷 세대 6이 약 86초 만에 만들어졌다. 새 프로세스의 스냅샷 워커는 첫 로그인 요청 때 시작한다.

**결과**: 매칭된 항공료 27건은 전부 `HOLD_GUIDE_IDENTITY_UNCONFIRMED`이며 장부 736행·73,998,707원, 보류 15건은 그대로다. 보호 기준선은 게이트가 현재 데이터에서 다시 계산해 277+1=278, 변경·누락·중복·수동 덮어쓰기 0이다. 스냅샷 파일에는 탑승자 이름이 없다.

**운영자 설정**:
- (폐기) `guide-identities.json`은 더 이상 읽지 않는다. 대장 항공권 영문명은 reservation 관리자 화면의 `대장 관리`에서 등록한다.
- `config/guide-airfare-airports.json`(또는 `WEBLEDGER_GUIDE_AIRPORTS`): 공항과 여행지 이름의 대응과 `max_gap_days`. 여행 탭의 destination 값과 정확히 같은 이름만 쓴다.

## 2026-10-10 OTA 검토 스냅샷과 authority 활성화

**launcher drift**: 운영 `D:\WebLedgerHost\bin\launch_web_ledger.py`를 저장소 `tools/launch_web_ledger.py`와 같은 파일로 맞췄다. 차이는 `ota_mail_dir` 블록 두 줄뿐이었고 운영 설정에는 이 키가 없어 동작 변화는 없다. 이전 파일은 `launch_web_ledger.before-drift-fix-20261010.py`로 보관한다.

**요청 경로 분리**: `/api/imports/ota` GET은 OTA 대사를 계산하지 않는다. 마지막으로 확인된 스냅샷과 상태(`loading`, `ready`, `refreshing`, `error`)를 돌려준다. 재계산은 워커 한 개가 하고, 입력 지문이 바뀔 때만 실행한다. 지문은 소스 파일 내용 해시(크기·시각 기준 아님), 거래 원장, 검토 DB, 매칭 설정 기본값이다. 스냅샷은 `D:\WebLedgerHost\data\ota-review\ota-snapshot.json`에 원자적으로 저장되어 재시작 뒤 바로 불러온다. 쓰기 요청 뒤에는 새로고침을 요청하고 최대 3초 기다린다.

**성능(실제 데이터)**: 콜드 재계산 약 62초(워커에서 실행, 프로세스당 한 번). 같은 프로세스 웜 재계산 약 5.8초(이전 웜 약 37초). 메일 파싱은 메일 내용 지문이 같으면 재사용한다. 요청 중 계산은 0이다. 상세 지문 확인을 포함한 GET은 약 1.5초다. 콜드 시작 중에도 `healthz`는 200이었다.

**결과 동등성**: 같은 소스와 같은 데이터에서 이전 코드와 새 코드의 스냅샷 JSON이 바이트 단위로 같다(606,277바이트, 보류 101건).

**authority 가드**: 스냅샷이 없으면 OTA 카드 전부를 보류한다. 스냅샷이 오래되면 새 자동 연결을 믿지 않고, 기존 수동·정확 연결만 유지한다.

**화면**: 1440×900과 390×844(같은 출처 iframe, 실제 CSS 뷰포트 390×844) 모두 가로 넘침 0, 보류 101건, 카드 행 1,027개, 줄어든 버튼 0개. 로딩 중에는 안내를 보이고, 준비되면 한 번 그린다. 고르는 중인 항목이 있으면 자동 갱신을 미룬다.

**shadow gate(현재 기준)**: 2026-10-09의 200건 기준은 재사용하지 않았다. 현재 레거시 정확 연결 277건과 수동 연결 1건을 기대값으로 삼았다. 결과는 기대 278건 중 같음 278건, 변경 0, 누락 0, 중복 0, 수동 덮어쓰기 0, DB 변화 0이다. 신규 자동 연결은 4건이며 모두 `approved_trip_flight_delta`다. 유일한 후보이고 정확 연결과 겹치지 않는다. 그중 `68ca3ad3`(노리쿠라 원거래)과 `306ea544`는 이미 장부에 기록된 행이라 장부는 바뀌지 않는다. `cb9f03e7`(964,400원)과 `a77c71ff`(1,081,000원)는 미기록 상태이며, authority에서는 사용자가 기록할 때 기록 가능해진다.

**authority OFF/ON(같은 스냅샷)**: 기록 가능 행은 1,097에서 875로 줄었다. 새로 보류된 OTA 카드는 170건이고, 비-OTA 행 변화는 0이다. 카드 검토의 배치 미리보기는 288건에서 203건이 됐다. 기록 버튼은 누르지 않았다.

**운영 상태**: `card-flow.json`의 `ota_review.mode`를 `authority`로 설정하고 재시작했다. 이전 설정은 `card-flow.before-authority-20261010.json`에 있다. 장부는 736행, 합계 73,998,707원으로 변하지 않았다. 중복은 0이고, 사용자 결정 28건과 보류 15건도 그대로다.

**남은 항목**: OTA 미리보기와 확정 요청(`/api/imports/ota/preview`, `/confirm`)은 아직 요청 안에서 `_data()`를 동기 호출한다. 콜드 상태에서는 수십 초가 걸릴 수 있다. 이 경로도 스냅샷을 쓰도록 바꾸는 것이 다음 과제다. 또 스냅샷 워커는 테스트가 끝날 때 멈추지 않아 임시 DB 정리가 실패할 수 있다.

## 2026-10-10 쌍 전용 기록과 실제 부분 환불 기록, OTA 검토 중단(이전 기록)

> 아래 "OTA 검토 중단"과 "현재 상태"는 위 섹션에서 해소되었다. 이력으로만 남긴다.

**쌍 전용 기록(PR #29, 752652c)**: 환불 쌍은 원거래 id로만 요청한다. 서버가 DB에서 묶음(원거래 + 같은 승인번호의 취소 행)을 다시 계산하고, 미리보기는 그 묶음 행만 골라 묶음 전용 digest를 만든다. 묶음 밖 행은 기록되지 않는다. 전체 미기록은 원자적 기록, 전체 기록은 no-op, 일부 기록은 `REFUND_PAIR_PARTIALLY_BOOKED`, 묶음 누락과 막힌 묶음은 `REFUND_GROUP_INCOMPLETE`로 거부한다. 엔드포인트는 `POST /api/imports/{batch}/refund-groups/{original}/commit`이다. 배치 전체 기록은 그대로 남아 있다.

**실제 부분 환불 기록**: 원거래 1056200(30058735)과 취소 행 40739306(−760,200원)을 묶음 버튼으로 한 번 기록했다. 순액 296,000원, 여행 0801_노리쿠라(`trip-ef85af8d7a42`, 사용자 결정 rev 5). 장부는 734행·73,702,707원에서 736행·73,998,707원으로 바뀌었다. 기록은 원거래와 환불 각 1건이고, 중복 0, 기록 이벤트 `ledger.refund_linked` 1건, 원금 불변, 보류 15건과 사용자 결정 28건은 그대로다.

**OTA 검토 UI 중단**: `card-flow.json`에 `ota_review`(isolated) 블록을 넣고 launcher가 이를 읽도록 했다(PR #30). 검토 DB 사본은 `D:\WebLedgerHost\data\ota-review\ota-review.sqlite`이며 기존 pilot 수동 연결 1건, 제안 1건, 요청 1건을 보존했다. 그러나 OTA 검토 목록(`/api/imports/ota`)을 열면 서버 CPU가 60초에 약 75초 늘고 요청을 취소해도 계산이 계속돼 `healthz`가 응답하지 않았다. 설정을 `legacy`로 되돌리고 재시작해 해소했다. 이 목록 계산이 OTA 검토 UI의 차단 요인이다. 목록 계산을 요청 범위로 줄이고, 취소 가능하게 하고, 캐시해야 한다.

**현재 상태**: 운영 모드 `legacy`, `WEBLEDGER_OTA_AUTHORITY` 미설정. OTA 검토 UI 2개 뷰포트 검증, shadow gate 재측정, authority 전환은 하지 않았다. 배포된 `D:\WebLedgerHost\bin\launch_web_ledger.py`에는 OTA 설정 블록만 외과적으로 추가했고(백업 `launch_web_ledger.before-ota-review-20261010.py`), 설정 파일 백업은 `card-flow.before-ota-review-20261010.json`이다.

## 2026-10-10 카드 자료 화면 부하 원인과 부분 환불 중단 지점

**원인**: `/import`를 열면 첫 자료(973행)가 자동 선택되고, 페이지가 2초마다 그 상세 상태를 요청했다. 상세 상태 한 번마다 OTA 대사가 두 번 계산됐고, 매번 연결된 메일·포털·참조 파일 450여 개의 내용 해시를 다시 읽었다. 거래 지문이 바뀌면 메일 파싱과 포털 대조까지 전부 다시 계산했다(콜드 약 41초). 폴링은 이전 요청이 끝나기를 기다리지 않아 요청이 쌓였다.

**수정(PR #27, 결과 의미 불변)**: 한 상세 조회 안에서 대사를 한 번만 계산하고, 계산은 단일 잠금으로 직렬화하며 DB 잠금 밖에서 한다. 메일 파싱·추출·숙박 영수증 사실은 자료 내용 지문이 같으면 재사용한다. 포털 대조의 중복 루프를 줄였다. 브라우저 폴링은 이전 요청 완료 뒤 대기하고 응답이 느리면 간격을 늘린다. 내용 해시 검사와 지문 비교는 그대로다.

**측정(운영 규모 복사본, 운영 OTA 소스 연결)**: 대사 결과 JSON은 캐시 경로와 기준 경로가 콜드·웜 모두 동일(803,504바이트). 웜 재계산 41초 → 3초. 상세 상태 반복 요청 2.4초 → 1.2초(내용 해시 잔존). 운영 `/import` 한 번: 첫 로드는 콜드 계산으로 CPU 약 27초, 이후 탭을 열어 둔 상태에서 CPU는 약 20초마다 한 번 3.5초 안팎의 상세 요청만 나가고 나머지는 유휴, `healthz` 200.

**부분 환불 상태**: 원거래 보류 `refund_pending`은 해제했고, 같은 저장에서 여행을 0801_노리쿠라(`trip-ef85af8d7a42`)로 지정했다(사용자 결정 rev 5, 근거는 rev 2 배정과 지시서). 환불 행(−760,200원)은 아직 기록되지 않았다. 장부 기록 버튼은 자료 전체의 미리본 288건을 한 번에 기록하므로, 쌍만 기록하는 경로가 없어 기록하지 않았다. 장부는 734행, 합계 73,702,707원으로 그대로다. 쌍만 기록하는 경로가 필요하다.

**보류 상태**: OTA 검토 UI 확인과 shadow gate 재측정은 부분 환불 기록 뒤로 미뤘다. `WEBLEDGER_OTA_AUTHORITY`는 설정하지 않았고 운영 모드는 `legacy`다.

## 2026-10-10 환불 묶음 기록 계약과 실제 부분 환불 보류

**환불 묶음 계약**: 원거래와 같은 승인번호의 모든 취소 행을 한 묶음으로 본다(`app/partial_refund.py`의 `refund_group`). 묶음 전체가 미기록이면 함께 기록하고, 전체가 기록돼 있으면 no-op이다. 일부만 기록된 상태는 미리보기에서 보류하고(`refund_pair_partially_booked`), commit은 `REFUND_PAIR_PARTIALLY_BOOKED`로 거부한다(기록 0, projection 0). 묶음 밖 행 때문에 일부만 기록될 상황은 `REFUND_GROUP_INCOMPLETE`로 거부한다. 묶음 조회는 DB 기준이라 원거래가 이미 기록돼 미리보기에서 빠진 경우도 놓치지 않는다. 원거래 금액은 고치지 않는다.

**환불 링크 조회 성능**: `refund_links`가 환불 행마다 테이블을 두 번 훑어 실제 DB(6,037행)에서 4.9초 걸렸다. 후보 행을 한 번에 가져와 묶는 방식으로 바꿨고 결과는 기존과 같다(337건, 0.053초). 카드 화면의 미리보기가 이 조회를 반복하므로 서버 부하의 한 원인이었다.

**실제 부분 환불(원승인 30058735, 원결제 1,056,200원, 취소 −760,200원, 순액 296,000원)**: 아직 기록하지 않았다. 원거래에는 사용자 보류 `refund_pending`이 남아 있고 정상 로그인 UI에서 해제·미리보기·기록을 하지 않았다. 해제 전에 `/import` 카드 자료 화면이 서버 응답을 멈추는 현상이 두 차례 발생해 중단했다. 원인은 아직 확인하지 못했다.

**운영 상태(2026-10-10 측정)**: 코드 `2d4ccac`, 재시작 후 PID 32088, 리스너 1개, `healthz` 200, 보호 경로 401. 장부 734행, 합계 73,702,707원, 보류 16건, 사용자 결정 27건, 무결성 ok. 백업은 `board-before-refund-commit-20261010.sqlite`다.

**OTA authority**: 활성화하지 않았다. 카드 화면 검증을 끝내지 못해 `legacy`를 유지한다.

## 2026-10-10 PR #22 운영 반영과 재시작

부분 환불 연결과 OTA authority guard를 포함한 PR #22를 main에 병합했다. 최종 main/운영 코드 SHA는 `d8f8b22fa32b900adbdb921133a0d86068d7e8d8`이다. 통합 feature revision에서 전체 회귀를 한 번 실행해 **2516 passed / 3 skipped / 2400 subtests passed, 실패 0**으로 종료했다. skip 3건은 비공개 Agoda 산출물 2건 부재와 Windows의 chmod 기반 읽기 전용 검사 제약이며, 실패를 skip으로 바꾼 것이 아니다.

운영 반영 전에 `D:/WebLedgerHost/backups/board-before-main-sync-20261010.sqlite` 복구 사본을 만들고 SQLite 무결성과 장부 734행을 확인했다. `C:/AX/cost`를 main으로 동기화한 뒤 보호 파일 4개는 그대로 보존했다. `tools/restart_real_review_host.ps1`로 재시작했고 리스너는 `127.0.0.1:8751` 하나, PID는 9384에서 36740으로 바뀌었다. 재시작 후 `/healthz`와 `/readyz`는 200, 비로그인 보호 루트는 401, DB 무결성은 ok다.

OTA authority는 **활성화하지 않았다**. 운영은 기본 `legacy` 모드이고, 읽기 전용 shadow gate만 통과한 상태다. authority를 켜면 OTA 미확정 카드의 장부 보류 판정이 바뀌므로, 실제 OTA 검토 화면과 모바일/데스크톱 UI를 확인한 뒤 별도 전환한다.

aside의 기존 Google 세션으로 정상 로그인 경로를 따라 운영 장부에 들어가 장부 734건, 카드 자료 2,384건, 확인 필요 471건, 분류대기 238건을 확인했다. 비밀번호·쿠키 조작이나 인증 우회는 하지 않았다. 부분 환불 화면, OTA 검토 화면, 390×844 및 1440×900 레이아웃은 아직 운영 로그인 UI에서 최종 확인하지 않았다.

## 2026-10-09 부분 환불 연결, OTA authority 모드, 일정 근거 조사

**부분 환불**: 취소 행의 `original_approval_number`로 같은 발급사·카드의 원결제를 유일하게 찾아 연결한다(`app/partial_refund.py`, 스키마 변경 없음). 미리보기는 원결제와 환불을 한 쌍으로 판정한다. 환불에 항목·구분·여행이 비어 있으면 원거래에서 이어받고, 서로 다르거나 환불 합계가 원결제를 넘거나 한쪽이 보류면 둘 다 보류한다. 원본 금액은 고치지 않고 순액을 파생값(`refund_link`)으로 보여 준다. commit은 한쪽만 기록되면 전체를 되돌린다. 연결 근거는 `change_log`의 `ledger.refund_linked`에 남긴다. 실제 사례(원결제 1,056,200원, 환불 −760,200원)는 운영 DB 사본에서 확인했다. 현재는 원거래의 사용자 보류가 있어 두 행 모두 보류이고, 보류를 해제한 가정에서는 한 번에 기록돼 순액 296,000원이 된다. 운영 DB의 보류는 해제하지 않았고 기록도 하지 않았다. 64,814원은 카드 원장에 같은 날 전액 취소(승인 41909645)가 있어 순액 0원의 `full` 연결이다.

**OTA authority**: `legacy`(기본), `isolated`(`WEBLEDGER_OTA_REVIEW_MODE=isolated`와 절대 경로 `WEBLEDGER_OTA_REVIEW_DB`), `authority`(isolated에 `WEBLEDGER_OTA_AUTHORITY=authority` 추가)를 구분한다. authority에서는 OTA-first 연결이 확정되지 않은 OTA 카드 거래를 장부 미리보기에서 보류한다. 읽기 실패는 보류가 아니라 오류로 남아 기록을 막는다. 전환 전 `tools/ota_shadow_gate.py`가 운영 자료를 읽기 전용으로 비교한다. 2026-10-09 측정 결과는 exact 200건 모두 동일, 변경·누락·중복·수동 덮어쓰기 0, 장부 734행·사용자 결정 27건·보류 16건 유지, 신규 자동 연결 4건(모두 승인된 Trip.com 항공 차액)이다. 이 gate는 통과했지만 운영 환경에 authority를 켰는지는 아래 "운영 반영" 항목을 따른다.

**일정 근거**: 26Q1 보관 워크북의 "사본" 시트 11개(에히메~아키타)는 날짜가 현재 일정과 같지만 일정 권위로 승격하지 않는 비권위 보강 근거로만 기록했다(`.local-archive/pending-docs-20261008/drive-corroborating-evidence-20261009.json`, 워크북 sha256 `4d073fba…72c2`). 일정 차단 926건은 그대로다. 도고는 최신 `아슬란` 워크북(10월 8일, 42시트)에 시트가 없다. 야쿠시마(`1127_야쿠시마_`), 몽골(`0712_몽골`), 8월 북해도(`0813_북해도`)는 시트가 있으나 제목·헤더에 종료일이 없고 항공편 문구의 날짜뿐이라 추정하지 않는다. 확인한 Drive 질의는 이름·본문 `에히메`, `야쿠시마`, `도고`, `몽골`, `아슬란`, `숲길따라 감성여행`이다.

**Agoda**: 146,018원은 OTA 이벤트가 결제 확인(이용 8/27~8/29)이고 카드와 정확 연결되지만 이용 완료·취소 완료 근거가 없어 사용자 보류를 유지한다. 64,814원 카드 거래는 같은 날 동일 승인번호의 전액 취소 쌍으로 확인되어 카드 회계상 순액 0원이다. 이는 해당 카드 거래의 비용 상태를 확정하는 근거이지 과거 proposed OTA 예약 연결 자체를 확정하는 근거는 아니다. 연결 후보였던 96,842원은 별개의 8/23 결제다.

## 2026-10-09 일정 원본 Drive 재조사와 권위 결정

읽기 전용 Google Drive 연결로 최신 일정 원본과 보관 워크북을 다시 조사했다. 보관 워크북 `(주) 숲길따라 감성여행_아슬란_26Q1`에서 에히메·교토·나가센도·아오모리·오사카·알펜루트·부산·6월 북해도·레분토&리시리·묘코·아키타 11개 시트를 찾았고, 각 시트 제목의 시작·종료일은 기존 권위 기록과 일치했다. 내려받은 보관 워크북의 SHA-256은 `4d073fba4a95c10fb9a821ae98e3880a1781c1c9291a627220dcebaa953f72c2`다.

이 11개 시트는 이름이 모두 사본으로 끝나는 보관 자료이고 최신 운영 원본보다 오래된 자료이므로 **일정 authority로 승격하지 않는다**. 최신 원본 우선 원칙을 유지하며, 이 자료는 historical corroborating evidence로만 보존한다. 따라서 이 11개 자료만으로 일정 검증 차단 또는 장부 기록 차단을 해제하지 않는다. 도고와 야쿠시마는 해당 보관 워크북과 추가 Drive 검색에서도 명시 일정 시트를 찾지 못했다. 몽골과 8월 북해도의 종료일도 아직 authoritative source로 확인하지 못했으므로 추정하지 않는다. Drive에는 쓰지 않았고 읽기 전용 연결만 사용했다.

## 2026-10-09 국민 해외 매입 안전 신규분 가져오기와 신규 거래 분류

국민 해외 매입 764행을 카드 끝자리·승인일·통화·외화 금액·가맹점 첫 토큰·총청구액으로 기존 거래와 대조했다. 모든 행에서 결제원금과 수수료의 합이 총청구액이다. 기존 거래는 총청구액으로 저장돼 있다. 중복 후보 그룹 442개는 모두 신규 행 수와 기존 거래 수가 같아 일대일로 대응한다. 결과는 기존과 동일 464건(복수 후보 34건 포함), 신규 227건, 취소 70건, 현금서비스 등 특수 3건이다. 신규 227건만 부분 CSV로 복구 사본에서 검증한 뒤 운영에 가져왔다(충돌 0, 재수신 동일, 기존 거래 변경 0, 장부 734행 그대로). 복구 사본은 `D:/WebLedgerHost/backups/board-before-kb-overseas-safe-new-20261009.sqlite`다. 전체 해외 파일은 다시 가져오지 않는다. 중복 464건이 신규로 들어가기 때문이다. 취소 70건과 특수 3건은 가져오지 않았다.

신규 국내 482건과 해외 227건은 복구 사본(`board-before-classify-new-20261009.sqlite`) 확보 후 앱의 분류 함수로 처리했다. 709건 중 자동 분류 331건, 사용자 검토 필요 377건(예약 근거 필요 250, 여행지 보류 126, 기타 1), 보존 1건이다. 대상 밖 거래 변경 0, 사용자 확정 설정 0, 장부 기록 0이다.
## 2026-10-09 국민 국내 매입 가져오기와 코드 병합

보존 국민 국내 매입 XLS를 변환한 CSV(1,016행)를 운영 DB에 가져왔다. 가져오기 전에 `D:/WebLedgerHost/backups/board-before-kb-domestic-acquired-20261009.sqlite`에 복구 사본을 만들고 무결성을 확인했다. 결과는 신규 482건, 승인번호가 같은 기존 거래 534건, 충돌 0건, 미해결 0건이다. 기존 거래 5,328건의 변경은 0건이고 장부 734행은 그대로다. 같은 파일을 다시 받아도 전체 테이블이 동일했다. 변경된 테이블은 `transactions`, `import_batches`, `import_batch_rows`, `change_log` 네 개다. 신규 482건은 모두 분류 검토 대기이며 장부에 기록하지 않았다. 해외 매입 764행은 승인번호 없는 기존 거래 481건과 겹칠 수 있어 가져오지 않았다.

항공권 부분 환불 760,200원의 취소 전표(원승인번호 30058735, 카드 끝자리 3820, 매입일 2026-08-03)가 운영에 들어왔다. 원결제 1,056,200원과 원승인번호가 같다. 사용자 보류는 해제하지 않았고 잔여 이용 비용 296,000원과 환불 부분의 분리·전기도 수행하지 않았다.

기존 미커밋 변경은 `feature/pending-docs-and-fixes-20261009`로 커밋해 OTA-first, Trip.com 항공료 보정(PR #15)과 함께 main에 병합했다(PR #16, `0e2b822`). 병합 결과의 표적 검증은 367 passed, 72 subtests다. 운영 체크아웃 `C:/AX/cost`는 위 브랜치에 있고 코드는 `33fdbbe` 기준이며(이후 문서 동기화 커밋만 추가) main과의 코드 차이는 OTA-first 격리 모듈·설정과 `WEBLEDGER_OTA_REVIEW_MODE=isolated`일 때만 동작하는 연결 코드(`webapp/card_flow.py`, `app/ledger.py`의 `additional_holds`)다. 이 환경 변수가 없으면 기존 동작과 같다. main 코드로 운영 데이터를 읽기 전용 검사한 결과는 정상(`ok = True`)이었다. 운영 서버는 재시작하지 않았고 `/healthz`, `/readyz`는 200이다. OTA-first를 운영 matcher로 바꾸는 코드 경로는 아직 없다.

## 2026-10-09 격리 OTA review pilot

운영 자료를 읽기 전용으로 사용하는 별도 로컬 pilot에서 대표 HOLD 8건을 검토하고, 사용자가 허용한 순서 배정 사례 1건의 수동 연결과 미승인 proposal 1건을 운영 DB 밖의 review DB에 저장했다. 활성 규칙과 frozen group은 0건이다. 기존 정확 연결은 200/200 동일했고 장부 734행, 운영 테이블·schema·사용자 결정·기존 보류·원본 파일과 DB 지문은 모두 같았다. production authority와 production 프로세스는 변경하지 않았다. 실제 검증, 합성 검사와 dry-run의 범위는 [pilot 실행 기록](ota-first-isolated-review-pilot.md)을 따른다.

## 2026-10-08 OTA 자료 통합

운영 데이터 폴더의 `ota-sources.json`에 메일 디렉터리 5곳, 포털 데이터베이스 11개, 과거 조사와 예약 후보 문서 53개를 등록했다. 메일 원문은 중복을 제외하면 1,670건이다. 포털 사본은 예약 근거를 개별 비교했으며 모두 기존 원본과 같거나 그 일부였다. 원본을 옮기거나 삭제하지 않고 함께 조회한다.

현재 대조는 `app/ota_sources.py`에서 등록 목록을 읽고, `app/ota_mail.py`와 `app/ota_portal.py`에서 전체 자료를 함께 판단한다. 같은 메일 ID의 다른 본문은 충돌로 처리한다. 포털은 데이터베이스마다 따로 연결하지 않고 전체 예약과 카드 거래의 일대일 관계를 확인한다. 결제 예정과 실제 결제, 예약 확정과 이용 완료를 구분한다. 과거 조사 문서는 참고 자료이며 결제 또는 여행 배정 권위로 자동 승격하지 않는다.

등록 목록과 자료 내용의 해시가 바뀌면 캐시를 다시 계산한다. 명시 등록한 자료를 읽지 못하면 오류를 표시하고 새 OTA 분류와 권위 메타데이터 사용을 막는다. 미연결 표시에는 결제 근거 미검증, 결제 예정, 같은 카드 예약 후보와 금액 불일치, 기간 미확인, 예약 충돌과 거래 모호성을 구분한다. 자료 경로와 고객 원문은 화면에 출력하지 않는다.

운영 읽기 전용 대조에서 기존 정확 연결 198건을 모두 보존했고, 과거 포털 결제 표현에서 누락됐던 2건을 추가로 확인해 전체 기간의 정확 연결은 200건이다. 현재 검토 기간의 OTA 결제 375건은 정확 연결 178건, 비용 항목 후보 20건, 미연결 177건으로 구분한다. 미연결을 모두 해결한 것으로 보고하지 않는다.

146,018원 거래에는 예약 근거가 표시된다. 이는 실제 이용 완료를 뜻하지 않으며 기존 사용자 보류는 유지한다. 64,814원의 과거 후보는 96,842원 및 결제 예정 자료와 맞지 않아 확정 연결하지 않는다. 재수집이나 사용자에게 같은 자료를 다시 요청하지 않고 보존 자료와 차이를 먼저 확인한다.

표적 검증 결과는 `158 passed, 41 subtests passed in 29.69s`다. 등록 목록 적용 전에는 운영 데이터베이스의 전체 75개 테이블이 사본과 같았다. 서버 재시작 후에는 프로세스 실행 이력인 `rule_process_leases`만 추가·갱신됐고 나머지 74개 테이블과 스키마는 같았다. 같은 대조 요청의 결과도 동일했다. 기존 장부 734건과 사용자 확정·보류·원본 금액·날짜·ID는 유지했다. 코드와 등록 목록을 운영에 적용하고 상태 경로를 확인했으며 실제 로그인 브라우저 검증과 구분한다. 상세 근거는 `.local-archive/ota-integration-20261008/`에 보존한다.

OTA 자료 통합은 2026-10-08 확인 기준이다. 이 문서는 현재 상태를 설명한다. 과거 작업의 실행 순서와 수치는 [과거 운영 기록](history/operations-through-20261007.md)에 보존했다.

## 정본과 실행

배포 설정의 `WEBLEDGER_DATA_ROOT`는 지속 디스크에 마운트된 절대 경로를 지정한다. Linux의 예시는 `/srv/web-ledger/data`이며, 현재 Windows 운영 데이터 루트는 `D:/WebLedgerHost/data`다. 상대 경로·임시 디렉터리·소스 체크아웃 안 경로는 운영에서 거부된다. 이 안내는 기존 실행 설정을 설명하며 데이터 경로나 실행 설정을 변경하지 않는다.

운영 정본은 `D:/WebLedgerHost/data/board.sqlite`다. `board_rows`는 현재 장부, `ledger_entries`는 최초 기록 영수증이다. 원본·일정 근거·운영 설정·비밀값은 저장소 밖 또는 Git 제외 로컬 경로에 보존한다. 운영 실행기는 `D:/WebLedgerHost/bin/launch_web_ledger.py`, 코드 경로는 `C:/AX/cost`다. 장부는 `127.0.0.1:8751`에서 응답하고 공개 주소는 [운영 장부](https://ledger.foresttour.kr/)다.

사용자는 0원 문제의 필요한 운영 조치와 미결 작업 진행을 승인했고, 일정 정리는 최신 일정 원본을 기준으로 하라고 지정했다. 재부팅·앱 복구·재설치는 수행하지 않았다. 기존 사용자 보류 해제나 자료가 없는 일정 생성까지 승인된 것으로 해석하지 않는다.

## 현재 자료

| 항목 | 확인 결과 |
| --- | ---: |
| 원본 거래 | 6,037건 |
| 완료 기간 내부 보존 | 3,653건 |
| 현재 검토 기간 거래 | 2,384건 |
| 가져온 카드 파일 | 7개 |
| 기록된 장부 | 734건 |
| 기록된 순액 | 73,702,707원 |
| 여행 탭에 기록 | 496건 |
| 분류대기 장부에 기록 | 238건 |
| 여행 탭 | 40개 |
| 일정 권위 검증 통과 | 25개 |
| 일정 확인 필요 | 15개 |
| 남은 일정 검증 차단 거래 | 926건 |
| 기존 취소·환불·사용자 보류 | 16건 |
| 현재 추가 기록 가능 거래 | 0건 |

분류대기 장부의 238건은 이미 기록된 행이며 카드 미기록 942건과 구분한다. 모든 여행의 0원이 해소된 것은 아니다. 최신 여행 원본에 없는 과거 시트와 명시 기간이 부족한 여행은 별도로 남아 있다.

## 완료한 수정과 반영

- 승인번호가 같은 결제와 취소를 같은 거래로 판정해 전체 기록을 되돌리던 오류를 수정했다. 거래 ID를 먼저 확인하고, ID가 없는 과거 장부 행은 카드사·카드·승인번호·일자·부호 있는 금액·거래 종류를 함께 비교한다.
- API ready와 홈 집계는 `recordable_rows()`의 고유 거래·blocked·already_booked 제외 기준을 공유한다.
- 출력 화면과 출력 작업 조회는 기존 importer 생성과 스키마 쓰기 없이 읽는다.
- 여행 목록은 기존 금액이 수입 합계라는 사실과 미기록 거래가 포함되지 않는다는 안내를 표시한다.
- OTA 예약번호·이용기간·출처 digest는 미리보기와 최신 확인을 거쳐 장부 행에 전달한다.
- 검증된 복구 사본에서 먼저 수행한 뒤 운영에 615건, 순액 54,802,879원을 기록했다.
- 최신 일정 원본의 날짜가 기존 일정과 정확히 같은 여행 6개는 원본 경로와 digest를 갱신했다. 이름·일자·사용자 결정은 변경하지 않았다. 추가 119건, 순액 18,899,828원을 기록했다.

6개 여행은 야마가타·세토우치·야마구치·오제·가루이자와·도쿄다. 최신 워크북의 명시 연도와 시작·종료일을 개별 확인했다. 시트가 없는 여행을 과거 사본으로 복원하지 않았다.

## 원본 보호와 반복 실행

최초 반영에서 원본 거래 5,328건의 모든 필드를 비교했다. 기록된 행의 기존 확정 상태 변경 외 금액·날짜·ID·원문은 동일했다. 변경 대상 외 68개 테이블과 스키마도 동일했다. 같은 기록 요청을 재실행한 뒤 변경 대상 6개 테이블의 전체 행 해시가 동일했다.

최신 일정 반영에서도 기존 장부 615건과 원본 5,328건을 개별 비교했다. 일정 6개의 근거 digest와 revision·이력만 갱신했고 기간은 동일했다. 변경 대상 외 66개 테이블과 스키마가 동일했고, 같은 기록 요청 재실행 뒤 변경 대상 8개 테이블의 전체 행 해시가 동일했다. DB 무결성과 외래 키 검사를 통과했다.

## 남은 자료의 조사 결과

최신 일정 원본에는 과거 여행 시트 13개가 없었다. 이후 읽기 전용 Drive 재조사에서 그중 11개(에히메·교토·나가센도·아오모리·오사카·알펜루트·부산·6월 북해도·레분토&리시리·묘코·아키타)를 보관용 26Q1 워크북에서 찾았지만, 모두 사본 자료이므로 일정 authority로 승격하지 않았다. 도고·야쿠시마는 추가 Drive 검색에서도 명시 시트를 찾지 못했다. 몽골·8월 북해도는 명시 종료일의 authoritative source가 아직 없다. 따라서 일정 검증 차단 926건을 이 보관 자료만으로 해제하지 않는다. 상세 여행별 내역은 [미결 목록](session_handoff.md)을 따른다.

국민 국내 매입 원본에서 항공권 부분 취소 760,200원 한 건을 찾았다. 카드 끝자리·원승인번호·원승인일이 보류 중인 원결제 1,056,200원 한 건과 일치하며 취소 매입일은 2026-08-03이다. 차액은 296,000원이다. 이 취소 원행은 2026-10-09에 운영으로 가져왔다(위 첫 절). 보류 해제와 환불 분리는 남아 있으며, 은행 현금 환급 완료라고 표시하지 않는다.

Agoda는 기존 메일과 전수조사 자료를 다시 읽었다. 146,018원 예약은 카드 끝자리·포털 실제 결제액·군산 08-27~08-29 기간이 일치한다. 8월 22일 포털은 예약 확정과 결제 성공을 표시하지만 실제 이용 완료를 증명하지 않으며, 6월 11일 메일의 50% 위약금·73,009원 환불 안내도 취소 완료가 아니다. 기존 사용자 보류를 유지한다. 64,814원은 카드 원장에서 같은 날 동일 승인번호의 전액 취소 쌍으로 확인되어 카드 회계상 순액 0원이다. 다만 과거 OTA 예약 연결은 proposed였고, 포털 후보 96,842원은 별개의 8월 23일 결제이므로 카드 전액 취소 확인을 특정 OTA 예약 연결의 확정으로 승격하지 않는다.

보존 국민 XLS 1,016개 국내 행은 변환 CSV로 가져왔다(2026-10-09). 해외 764행은 카드 끝자리·승인일·통화·외화 금액·가맹점 첫 토큰·총청구액과 원금+수수료 관계를 사용해 다시 대조했다. 기존과 동일 464건, 안전 신규 227건, 취소 70건, 현금서비스 등 특수 3건으로 구분했고 안전 신규 227건만 복구 사본 검증 뒤 운영에 가져왔다. 전체 해외 원본을 다시 가져오지 않으며 취소 70건과 특수 3건은 자동 비용 처리하지 않는다. 현행 웹 업로드는 바이너리 XLS를 직접 지원하지 않는다. 카드 무인 로그인과 실제 로그인 브라우저 확인도 완료로 표시하지 않는다.

## 검증과 증거

카드 흐름·브라우저 검사는 격리와 통합 저장소에서 각각 52개 및 하위 검사 41개가 통과했다. 호스팅·출력 HTTP·운영 검사 묶음은 격리에서 91개 및 하위 검사 26개, 통합 저장소에서 같은 91개 및 하위 검사 26개가 통과했다. 전체 회귀를 새로 반복하지 않았다.

이전 통합 전체 회귀는 `2222 passed, 2 failed, 3 skipped, 2384 subtests passed`로 종료됐다. 두 실패는 수입 label 변경을 반영하지 않은 화면 기대값과 기존 루트 DB 존재에 의존한 호스팅 테스트다. 그 실행을 현재 전체 통과 결과로 표시하지 않는다. 출력 spy 검사의 별도 표적 실행에서 배경 worker가 importer를 생성하는 오탐도 발견해 테스트 격리를 보완했다. 기존 worker가 필요한 업로드 검사는 유지하고 해당 출력 검사만 worker 없이 실행한다.

복구 사본·개별 비교·미리보기·반복 실행 증거는 로컬에 보존한다.

- 최초 기록: `.local-archive/zero-amount-20261007/post-20261007-224740/`
- 최신 일정과 추가 기록: `.local-archive/pending-docs-20261008/latest-schedule/`
- 일정·보류·메일·포털 조사: `.local-archive/pending-docs-20261008/`
- 이전 전체 회귀: `.local-archive/partial-fixes-20261007/full-regression.log`

현재 상태·비로그인 보호와 운영 데이터 렌더러는 확인하지만 로그인된 실제 브라우저 확인과 미검증 외부 연결을 완료로 보고하지 않는다.

### 이번 실행의 최종 확인

`python -m pytest -q webapp/tests/test_ops_hosting_bind.py webapp/tests/test_verify_lightweight_runtime.py webapp/tests/test_ledger_board.py`는 **91 passed, 26 subtests passed**, 26.40초로 통과했다. 기존 화면 문구 기대값 수정은 앞선 109개 통과 묶음의 실제 브라우저 검사에서 확인했다. 그 실행은 출력 spy 한 건이 실패했으므로 전체 통과로 표시하지 않으며 수정 뒤 위 묶음으로 다시 확인했다.

`python tools/verify_lightweight_runtime.py`는 성공 종료했다. DB 정본 일치와 무결성, 공개 healthz·readyz 200 및 비로그인 import·api/imports 401을 확인했다. 전체 운영 검사 수행 완료는 참이고 일정 검증 완료는 거짓이다. 일정 25개는 유효하며 15개는 대기 중인 상태로 각각 보고한다. 운영 데이터 렌더러에서도 여행 12개 탭의 496건과 분류대기 238건, 표시 합계를 확인했다. 내부·공개 healthz·readyz는 200이며 비로그인 import는 401이다. 실제 로그인 브라우저 확인은 포함하지 않는다. 실행 증거는 `runtime-verification.json`과 `latest-schedule/runtime-after.json`에 보존했다.


## 2026-10-11 KB 3채널 승인 증거 경로 배포

PR #56 (`2807e6a`)를 main에 병합하고 `tools/restart_real_review_host.ps1`로 운영 호스트를 재시작했다. 새 프로세스는 PID 32796이며 8751 리스너는 하나다. `/healthz`와 `/readyz`는 200, 비인증 루트는 401이다.

재시작 전 복구 사본 `D:/WebLedgerHost/backups/pre-kb-three-channel-20261011/`를 만들었다. 장부 DB 74개 표와 OTA 검토 DB 6개 표의 행 수가 사본과 같고 두 사본의 `quick_check`는 `ok`다.

운영 장부 DB에는 승인 증거용 빈 표 두 개만 생성됐다. 승인 행은 0이며 거래 6,037건, 장부 736행·73,998,707원, 사용자 확정 28건, 환불 보류 15건, 접수 묶음 7건은 유지됐다. OTA 검토 DB의 기존 연결 1건, 제안 1건, 요청 1건도 유지됐다. 실제 KB 3채널 대사는 격리 복사본에서만 했고 운영 DB에는 KB 행을 넣지 않았다.
## 2026-10-27 페이지 전환 지연 진단·읽기 경로 최적화

PR [#139](https://github.com/6Soo/cost/pull/139)을 병합하고 **`a08cb815aa54be08a8361892a6fec3802aed616b`**을 운영에 배포했다. Aside REPL에서 실제 메뉴 링크를 클릭한 배포 전 측정은 다음과 같다. 각 경로 1회 관찰이며 평균/백분위가 아니다.

| 페이지 | 전환 | 서버 TTFB | DOM 준비 |
| --- | ---: | ---: | ---: |
| 카드 전체 내역 | 1.440초 | 0.919초 | 1.071초 |
| OTA 내역 | 16.795초 | 16.359초 | 16.502초 |
| 영수증 처리 | 0.791초 | 0.269초 | 0.440초 |
| 여행 장부 | 2.307초 | 1.855초 | 1.961초 |
| 지출 정리 | 23.768초 | 23.232초 | 23.486초 |

원인은 거래마다 반복한 장부 projection 집계, 환불 표시마다 반복한 연결/보류 조회, 중앙 snapshot이 없을 때 OTA GET에서 실행한 legacy 전체 대사, 시작 시 index 생성과 JSON 저장까지 유지한 목록 잠금, 예약마다 반복한 동일 여행 경계 계산이었다. 요청 내 projection/환불 근거를 재사용하고 OTA 목록은 갱신 중/이전 자료 표시와 비동기 갱신을 사용한다. detail/write는 최신 검증을 유지하고 중앙 snapshot이 준비되지 않으면 pending으로 표시한다. index 생성·디스크 I/O는 짧은 publication 잠금 밖에서 실행한다. 기존 HTTP DB 잠금과 금융 판정/쓰기 정책은 보존했다.

같은 로컬 원본 사본의 지출 정리 profile은 10.812→2.092초, projection 조회 1,374→2회였고 비동기 OTA foreground는 0.723초였다. 이는 운영 브라우저 전환 수치가 아니다. 표적 RED/GREEN 검사, catalog/booking 31 passed, 최종 performance/catalog 19 passed, 동시 생성/저장·stale·저장 실패 선택 6 passed, 금융 projection/중복/기존 장부 선택 18 passed 및 8 subtests passed를 확인했다. 구 expense 문구 assertion 하나는 기준 `cb7c575`에서도 실패하여 범위 밖으로 보존했다. 실행별 결과를 전체 회귀 통과로 합산하지 않는다. 독립 검토의 디스크 I/O 잠금 지적을 수정한 뒤 후속 검토에서 미해결 사항이 없었다. 전체 pytest/E2E·운영 재대사·기장·배정·Google 쓰기는 수행하지 않았다.

릴리스 956개 추적 파일의 Git blob이 모두 일치했다. 기존 `909e4ad` 릴리스와 검증된 복원 근거를 보존하고 task action SHA만 바꿨다. task/process/표식 SHA 일치, Board Running·단일 loopback listener, health/ready 200·비인증 OTA API 401을 확인했다. 증거는 `D:/WebLedgerHost/releases/deploy-evidence-a08cb815aa54be08a8361892a6fec3802aed616b.json`과 `release-audit-a08cb815aa54be08a8361892a6fec3802aed616b.json`, 같은 SHA의 작업 before/after XML이다. DB 2개의 관련 13개 표 내용/스키마 해시는 배포 전후 동일했다. 고객 원문이 없는 보호 집계와 profiles는 Git 밖 `.local-archive/navigation-20261027/`에 보존했다.

**화면 수락 PARTIAL:** 기존 Aside COST target은 배포 후 사라져 새 탭을 열었다. openTab 직후 빈 주소/본문, 명시 이동의 `Page.navigate` timeout 이후 실제 지출 정리 화면과 메뉴를 snapshot으로 확인했다. 이어 다섯 메뉴 클릭 측정은 첫 동작의 `Runtime.evaluate` timeout으로 중단돼 **배포 후 전환/TTFB 수치는 NOT_MEASURED**다. 도구 timeout을 서버 지연이나 성능 개선 완료로 해석하지 않는다. 별도 공개 health GET은 200이었다. 브라우저/앱 복구·재설치·불필요한 재배포는 하지 않았다. 다음은 Aside가 동작할 때 동일 다섯 메뉴 1회 클릭과 TTFB 비교만 수행한다. 이미 통과한 검사·보호 hash·스모크를 반복하지 않는다.
