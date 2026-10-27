# 여행 장부 수입·지출 화면 통합

## 현재 승인·범위

사용자는 카카오/Agoda 환불 PR의 실제 해결 여부를 묻고, 첨부 화면의 불필요한 상세 영역·분리된 수입/지출·수입표와 떨어진 총계·디자인 불일치를 Gemini 3.8 high에 위임해 구현하도록 요청했다. 현재 작업은 이 화면의 읽기 전용 표시 개선과 환불 상태 진단이며, 과거 미결 목록 전체 재실행이나 금융 자동 확정 권한을 만들지 않는다.

- 구현 에이전트: Paseo `252ea264-97d0-4b86-9d64-c51daaf75987`, 제공 모델 `antigravity/gemini-3.8-flash-high`. 사용자 모델 지시가 기본 무료 후보 순서보다 우선한다. 원문 이미지·고객 자료를 전달하지 않고 화면 구조를 합성 설명으로 전달했다.
- 소유 파일: `webapp/google_ledger_page.py`, `webapp/ledger_design.py`, 해당 합성 테스트는 위임 에이전트만 작성한다. 주 에이전트는 진단·문서·검토·병합·배포를 맡는다. 기존 사용자 미추적 계획 파일과 stash를 보존한다.
- 변경 목표: 수입/지출 공통 시각 체계, 표 가까이 붙는 합계와 검증 경고, 불필요한 상세 접기 제거, 지출 중복 헤더 제거. 원본/대조 링크와 동기화 정보는 접근 가능하게 유지한다.
- 보존 경계: 금액·실거래 행·환불·수동 결정·권한·원본을 변경하지 않는다. 수입 행합계와 시트 집계의 차이/검증 미완료를 숨기지 않는다. Google 수입을 SQLite 수입 행으로 복제하지 않고 허위 회계 확정/차액을 만들지 않는다.
- 검증: 변경된 수입/장부 렌더링 표적 테스트와 필요한 375px/1280px·라이트/다크 합성 브라우저 검사. 전체 pytest/전체 E2E는 실행하지 않는다. 내용 검토 후 정상 PR 병합·SHA 고정 배포·health/ready·해당 화면 최소 스모크·증거 기록까지 기존 자동 배포 승인을 적용한다.

## 환불 읽기 전용 진단 (2026-10-27)

`mode=ro`/`query_only`/일관된 읽기 트랜잭션에서 현재 엔진을 조회했다. 실제 연결/장부를 쓰지 않았고 `total_changes=0`이다. 비식별 근거는 `.local-archive/unified-trip-ledger-20261027/refund-diagnosis.json`에 보존한다.

| 항목 | 현재 근거 | 상태 |
|---|---|---|
| 카카오 PR | #169 번호 공백·보호 보완, #172 진단, #174 동액 추론은 #184에서 후보 표시만 허용해 병합·배포 | PR 존재/운영 반영 |
| 카카오 취소 | 39건 중 금융 연결28건, 미연결11건 모두 원승인번호 없음. 후보 표시1건 | 미연결11건 해결 아님 |
| Agoda #176 | 기존 원결제·환불 연결을 원결제 화면에도 표시. 새 매칭 알고리즘 수정 아님 | 표시 보완 반영 |
| Agoda 625,280원 쌍 | 취소1건/금융 연결1건/순액0원1건 | 연결·상쇄 근거 있음, 실제 환급/장부 완료와 별개 |
| Agoda 전체 | 취소76건/금융 연결73건/미연결3건 | 일부 근거 미확인 |
| Agoda 미연결3건 | 모두 원승인번호 없음. 2건은 외화 금액은 있지만 같은 카드의 동일 외화 금액·통화 구매0건, 1건은 외화 금액도 없음 | 현행 매칭 근거 부족. 임의 연결/정산 확정 금지 |

## 실행 상태

- **구현 완료:** Gemini 3.8 Flash High 위임 구현 완료 (`webapp/google_ledger_page.py`, `webapp/ledger_design.py`, `webapp/tests/test_trip_google_income.py`, `webapp/tests/test_trip_google_income_browser.py`).
  - 상단 요약 바(`#sum`) 수입·지출·차액 통합 렌더링 및 불일치 시 허위 차액 미표시.
  - 지출 테이블 중복 열 헤더(`tbody.colhead`) display:none 처리.
  - 수입 테이블 하단 행 합계 `<tfoot>` 즉시 부착.
  - `<details class='income-detail'>` 중첩을 평탄화하여 `.income-meta-bar`로 정리.
- **표적 검사 통과:**
  - 수입 유닛 및 권한/검증 테스트: `python -m pytest webapp/tests/test_trip_google_income.py webapp/tests/test_income_summary_display.py webapp/tests/test_ledger_display_updates.py webapp/tests/test_mobile_income.py` -> **34 passed (4.34s)**
  - 브라우저 E2E 테스트(Playwright 375px/1280px Light/Dark, 불일치 경고): `python -m pytest webapp/tests/test_trip_google_income_browser.py webapp/tests/test_ledger_display_browser.py` -> **4 passed (10.85s)**
- **진행 단계:** **COMPLETE**. PR #187 정상 병합 및 운영 `84e602ee76f4b50a072e43520af3cd886cebb423` 배포 완료. 980개 blob 일치, health/ready 200, 보호 API 401, 2DB/13개 보호 표 해시 동일 (`unchanged: true`). 운영 실시간 화면 (`trip-46d817cfb8c2`) 수입 35건(46,170,000원)·지출 81건(6,989,884원)·차액(39,180,116원) 상단 바 통합, tfoot 부착, 중복 지출 헤더 제거 확인 완료.

## 추가 사용자 요청: 콘솔 창 비노출

사용자는 로컬 COST 스크립트 창을 보이지 않게 하라고 추가 지시했다. 21:09:25에 시작한 `WebLedger-MailCollect`의 `python.exe -m app.mail_collect`와 같은 시각·실행 파일 제목의 Windows Terminal 창을 확인했다. 조치 시점에는 수집 프로세스와 창이 자연 종료돼 별도 숨김/강제 종료는 하지 않았다. 다음 실행부터 창이 뜨지 않도록 같은 설치 디렉터리의 `pythonw.exe`로 예약 작업 실행 파일만 교체했다. XML 비교에서 실행 파일 외 인자·작업 디렉터리·트리거·설정은 모두 동일함을 확인했다. 작업 재시작/추가 메일 수집/원본 변경은 하지 않았으며, 다음 예약 실행 자체는 NOT_RUN이다. 현재 보이는 터미널 창이 없음을 확인했다. 복원 가능한 작업 XML 전후와 근거는 `.local-archive/mail-console-hidden-20261027T211154/`에 보존했다.
