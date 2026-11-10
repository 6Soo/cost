# 웹 액션 버튼 조사·정리 — 2026-11-02

현재 사용자 요청: 글자만 나열된 액션을 웹 전체에서 조사하고, 불필요한 진입점은 제거하며 필요한 액션은 아이콘과 글자가 있는 버튼으로 정리한다.

## 조사 범위와 판단

- 정적 조사: Python 화면 생성 모듈 30개의 button 162곳·summary 54곳·a 176곳. 이는 소스 템플릿 출현 수이며, 실제 거래 수나 사용자별 화면 버튼 수가 아니다. 공통 JS 및 비동기 화면 생성 경로도 확인했다.
- 실제 인증 화면: 홈, 여행 장부, 지출 정리, 카드 전체 내역, OTA, 영수증, 여행 관리, 예약 명단 연결, 항공권 조회, 계정 관리. 보조 화면의 실제 검증 결과는 아래 근거에 따로 기록한다.
- 행의 가맹점명·여행명·개인명 같은 데이터 링크, 탭, 숫자 페이지 선택, 해/초승달 테마 버튼은 역할을 유지한다. 로그인 화면의 Google 로고+문구 버튼은 이미 적절한 버튼이며 인증 화면에 업무 메뉴를 주입하지 않는다. JSON·다운로드·404 응답은 UI 화면으로 계산하지 않는다.

| 화면·액션 | 판단·결과 |
| --- | --- |
| 지출 정리의 별도 전체 카드 검색 링크 | 카드 전체 내역 메뉴와 중복되므로 제거. 기존 검색 URL과 근거 화면의 검색 경로는 유지 |
| 카드 파일 추가·자료별 상세 검토 | `카드 자료 관리`로 간결하게 표시 |
| 저장된 자료 선택·업로드·규칙 수정 | 필요한 기능이므로 유지하고 아이콘·테두리·펼침 표시 제공 |
| 카드·OTA 검색·필터·이전/다음 | 유지하고 일관된 액션 표시, 원래 이름과 필터 값 유지 |
| 영수증 등록·인식·묶기·복사 | 유지. 처리 권한·확인 절차·잠금 상태는 원래 경로 사용 |
| 참가자·예약 연결·관리·교정 | 기능 유지. 실제 쓰기를 호출하지 않고 합성 자료로 상호작용 검증 |
| 저장·수정·취소·되돌리기·출력 | 원래 핸들러·폼·href를 유지하며 버튼 표시 개선 |
| 이미 아이콘이 있는 액션 | 아이콘을 중복 추가하지 않음 |
| 버튼을 포함한 복합 펼침 메뉴 | 바깥 summary까지 이중 프레임이 되지 않도록 제외 |
| 보험 명단 행의 펼침 메뉴 | 행 안의 기존 조작·높이를 유지하도록 공통 장식에서 제외. 별도 수입 행 회귀로 검증 |

## 구현과 보호 경계

공통 site shell에서 초기 HTML과 비동기 교체된 액션을 처리한다. 기존 `ui_icons` 도형을 재사용하며 추가 패키지·외부 요청은 없다. 장식 아이콘은 텍스트 없는 CSS pseudo-element로 표시하여 접근 가능한 이름, textContent, 자식 노드, 이벤트 대상 구조를 바꾸지 않는다. 모바일의 일반 액션은 최소 44px, PC는 최소 36px이며 테마 토큰과 키보드 focus 표시를 사용한다.

분류·여행 배정·금융 링크·원본·Google 최종 장부·스키마 쓰기는 없다. 금액·날짜·ID·수동 교정·CSRF·권한·확인 절차를 변경하지 않는다. 기존 사용자 미커밋/미추적 변경을 보존하고 전용 Git index와 archive 후보에서 이번 변경만 커밋·검증했다.

## 검증·운영 근거

- 최초 공통 화면 표적 35 passed/기존 실패 1 deselected. 기존 카드 필터 검사는 과거 `확인 필요/needs_review` 값을 기대하나 현재 코드는 `처리 필요/review`를 사용하며, 변경 전 배포 752eff0c에서도 같은 3개 subtest 실패를 재현했다. 이를 새 기능 통과로 계산하지 않는다.
- 복합 버튼 후속 9 passed/동일 기존 실패 1 deselected. 동적 추가·라벨 갱신·기존 SVG 중복 방지·비활성 버튼·Enter/Space·320/390/1440px·라이트/다크 포함.
- 인증 운영 9개 주요 화면 × 320/390/1440px × 라이트/다크에서 가로 넘침 0·공통 처리 대상의 스타일 누락 0. 지출 정리는 추가로 아이콘·실제 높이·중복 링크 제거·키보드 펼침을 확인했다. 실제 쓰기 버튼은 누르지 않았다.
- PR493 공통 구현 `697eb8f064e1bccccc07276d943958260c68f06f`, PR495 복합 보정 `a0a4d08770f1cc1b7646d93ac8dedebba3e29a54`. 최종 통합 배포 SHA와 보험 행 검증은 완료 기록에 기재한다.
- 통합 전 첫 배포는 1,256 blobs 불일치0·health/ready200·보호 API401/403·금융 보호13표 불변 PASS. 이후 다른 승인 작업의 업로드 릴리스61188520을 보존해 후속을 통합했다. 보정 단독 배포 시도는 다른 전환 중 listener 부재로 사전 중단되어 전환하지 않았다. 이후 서버/gate 작성자는 하나로 조정했다.
- 별도 전체 DB 백업·복원·전체 회귀·실기기는 UI 한정 변경으로 미실행. 이전 검증 릴리스와 예약 작업 XML 복구점을 유지한다.

로컬 근거: `.local-archive/button-ux-20261102/`의 source-inventory·live-route-audit·live-site-audit·live-secondary·live-import·검사 XML·review·release/deploy evidence. 실제 화면 캡처는 Git 제외 로컬에만 보존한다.

## 완료 기록

- COMPLETE — 전역 조사, 중복 진입점 제거, 공통 아이콘 버튼·비동기 처리, 복합 메뉴·보험 행 보호와 최종 시각 보정을 병합·배포했다. PR493·495·497·503. 최종 검증/운영 SHA `959c139c850b9f86d570cca2b7cc7d2842737db2`, main 정상 병합 `05755753b4a2fcd81447e91dacd10d594f66b2dc`.
- 직전 검증 운영 `3b72d0e541f271241ffaa647862f132699a35a8b`의 기업카드 검색·비동기 업로드·읽기 최적화를 보존했다. PR503의 차이는 JS/CSS/버튼 회귀 테스트 3개 파일뿐이다. 기존 SVG/img가 있는 summary는 기존 표시를 유지하며, 보험가입내역 패널은 아이콘과 기존 외곽선 하나를 사용한다.
- 정확한 최종 후보의 표적 검사 **36 passed**, 기존 실패 1 deselected. 보험 행 별도 회귀 25 passed. 변경 전 752eff0c에서도 동일한 낡은 상태 필터 기대의 3 subtest 실패를 재현했다. 이를 통과로 계산하지 않았다.
- 최종 배포 1,263 Git blobs 불일치0, task/process 고정 SHA·단일 loopback·health/ready200·보호API401/403·금융 보호13표 내용/스키마 불변 PASS. 원본/분류/여행배정/Google/스키마 쓰기0. 근거 `polish-evidence/deploy-evidence.json`.
- 마지막 보정 후 인증 운영 지출 정리1440/390/320px: 중복 검색 제거, 액션 아이콘, 모바일44px, 가로 넘침0, Enter/Space, 기존 SVG/복합 summary의 이중프레임0 PASS. 실제 여행 장부 보험 패널1440/390px: 헤더 border0/margin0·아이콘 유지, 보험행 summary의 공통장식0, 가로 넘침0 PASS. 근거 `polish-live.json`. 마지막 캡처는 탐색 패널이 가려 전체 시각 수락 근거로 계산하지 않았다. TaskSpace17 정상 finish 완료. 이전 전체 화면·테마 감사와 최종 보정 검증을 구분한다.
- 보조 화면인 `/import?scope=all`, 항공권 참가자 후보, 환불 탭은 320/390/1440px에서 가로 넘침0을 확인했다. case없는 `/rules`는 정상404 안내, `/access/me`는 JSON, 폐지된 `/google-ledger`는 업무 UI가 아니므로 화면 수락으로 세지 않는다.
- 기존 `/export` GET은 변경 전15초·후속45초에도 로딩이 지연되어 실제 화면 수락을 하지 못했다. 출력 액션의 소스·공통 처리 경로는 조사했으며 성능 담당에게 단서를 전달했다. 출력 화면 운영 수락은 이 완료 보고에서 제외하며 출력 성능 해결을 주장하지 않는다.
- 이전 세션의 마지막 배포 명령은 계정 한도 종료 직후 정상 완료됐고, 후속 세션은 실제 증거와 예약 작업SHA를 확인해 중복 배포하지 않았다. 단일작성자 조정에 Paseo 스킬(레포 밖 `~/.agents/skills/paseo/SKILL.md`)을 사용했다. 후속 작성권 해제 통지 완료. 문서 전용 후속에는 테스트·빌드·DB점검·재배포·재시작을 하지 않는다.


## 정적 조사 목록

소스 템플릿 출현 수다. 실제 운영 화면 수와 구별하며 별도 비교 서버 pages.py도 포함한다.

| 소스 | button | summary | a |
| --- | ---: | ---: | ---: |
| [webapp/board_learning_dialog.py](../../../webapp/board_learning_dialog.py) | 12 | 0 | 5 |
| [webapp/board_render_helpers.py](../../../webapp/board_render_helpers.py) | 4 | 0 | 9 |
| [webapp/card_catalog.py](../../../webapp/card_catalog.py) | 3 | 1 | 5 |
| [webapp/card_cleanup_ui.py](../../../webapp/card_cleanup_ui.py) | 3 | 4 | 5 |
| [webapp/card_evidence_ui.py](../../../webapp/card_evidence_ui.py) | 0 | 6 | 2 |
| [webapp/card_flow.py](../../../webapp/card_flow.py) | 23 | 12 | 10 |
| [webapp/cards_all.py](../../../webapp/cards_all.py) | 2 | 0 | 11 |
| [webapp/expense_amount_group_ui.py](../../../webapp/expense_amount_group_ui.py) | 2 | 1 | 0 |
| [webapp/expense_bulk_maintenance.py](../../../webapp/expense_bulk_maintenance.py) | 2 | 0 | 1 |
| [webapp/flight_passenger_page.py](../../../webapp/flight_passenger_page.py) | 3 | 0 | 0 |
| [webapp/google_ledger_page.py](../../../webapp/google_ledger_page.py) | 6 | 2 | 7 |
| [webapp/insurance_income_match_page.py](../../../webapp/insurance_income_match_page.py) | 3 | 0 | 0 |
| [webapp/ledger_board.py](../../../webapp/ledger_board.py) | 24 | 3 | 44 |
| [webapp/ledger_design.py](../../../webapp/ledger_design.py) | 11 | 3 | 37 |
| [webapp/ota_catalog.py](../../../webapp/ota_catalog.py) | 5 | 1 | 11 |
| [webapp/ota_payment_review.py](../../../webapp/ota_payment_review.py) | 17 | 8 | 0 |
| [webapp/pages.py](../../../webapp/pages.py) | 1 | 0 | 7 |
| [webapp/participant_income_page.py](../../../webapp/participant_income_page.py) | 9 | 0 | 4 |
| [webapp/participant_trip_panel.py](../../../webapp/participant_trip_panel.py) | 8 | 4 | 7 |
| [webapp/provisional_trip_review.py](../../../webapp/provisional_trip_review.py) | 3 | 1 | 0 |
| [webapp/receipt_review.py](../../../webapp/receipt_review.py) | 10 | 4 | 4 |
| [webapp/refund_tab.py](../../../webapp/refund_tab.py) | 0 | 1 | 1 |
| [webapp/refund_tab_ui.py](../../../webapp/refund_tab_ui.py) | 0 | 0 | 2 |
| [webapp/reserve_link_ui.py](../../../webapp/reserve_link_ui.py) | 4 | 0 | 2 |
| [webapp/review_ui.py](../../../webapp/review_ui.py) | 2 | 0 | 0 |
| [webapp/site_shell.py](../../../webapp/site_shell.py) | 2 | 0 | 0 |
| [webapp/site_theme.py](../../../webapp/site_theme.py) | 1 | 0 | 0 |
| [webapp/social_preview.py](../../../webapp/social_preview.py) | 0 | 0 | 1 |
| [webapp/trip_flight_ui.py](../../../webapp/trip_flight_ui.py) | 2 | 1 | 0 |
| [webapp/trip_workflow.py](../../../webapp/trip_workflow.py) | 0 | 2 | 1 |
