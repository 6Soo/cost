## 2026-11-05 여행 탭에서 마감·여행 관리 및 예약 연결 통합 — 완료

- COMPLETE — 사용자 “여행관리가 왜 여행 탭이 아니라 별도 메뉴로 존재해야하지? 예약명단 여행연결이란 메뉴가 왜 필요하지? -> 바로 진행해” 반영. [PR #642](https://github.com/6Soo/cost/pull/642), 머지 `465760ba7cbc23ab46fe61eaa20eb06999510c70`, 고정 운영 `465760ba7cbc23ab46fe61eaa20eb06999510c70`, 이전 운영 `73075112214a81151e07b54bb02a0615b9833b86`. [명세](specs/trip-context-management-20261105.md), [운영 기록](operations.md#2026-11-05-여행-탭에서-마감여행-관리-및-예약-연결-통합-완료).
- 마감 버튼 및 여행 관리(이름, 작성일, 담당자, 보관)를 각 여행 탭 헤더에 배치하고, 예약·참가자 여행 연결 프레임을 여행 화면 내에 통합하여 현재 여행의 맥락을 벗어나지 않고 작업을 완결할 수 있도록 개선. 사이드바의 독립 관리 메뉴 2종 제거(호환 URL 유지).
- 영향 QA 692 passed·88 subtests·skip 0, PR CI 41899301788 success.
- 운영 전환 완료: 1,338 blobs 일치, task/process SHA 일치, gateway 8790 → backend 8751 전환, healthz/readyz 200, 보호 API 401, 보호 13개 테이블 불변 PASS. 금융/원문/Google 쓰기 0.
- 근거: `C:/AX/cost/.local-archive/trip-context-deploy-20261105/` 및 호스트 `D:/WebLedgerHost/releases/deploy-evidence-465760ba7cbc23ab46fe61eaa20eb06999510c70.json`.

## 2026-11-05 자율 지출정리 선처리 신규 명세 — 구현 대기

- **SPEC_ONLY** — [자율 지출정리 관리자 명세](specs/autonomous-expense-cleanup-20261105.md)를 추가했다. 카드 업로드/권위 자료 갱신으로 신규 지출정리 건이 생길 때 기존 P1 처리→연결 AI P2 자동 호출→원인 묶음·코드 결함 재현/개선→최종 사용자 필수 예외만 노출하는 운영 루프를 구현하는 **신규 승인 범위**다. 현재 운영이 이를 무인 실행한다고 주장하지 않는다. 최신 #631의 허위 충돌108건 재현 방지, Google 읽기 전용/금융 보호와 CI·고정 SHA 배포 게이트를 수락 조건으로 명시했다. 문서만 추가했으므로 배포·재시작/금융 쓰기 없음. 이번 명세의 구현·운영 수락은 후속 작업 대상이다.

## 2026-11-05 제주항공·Traveloka 수집 누락 조치

- 코드 배포·운영 원문 반영 완료 — [PR #634](https://github.com/6Soo/cost/pull/634), 운영 `43907dd375bffa860a3415e2330082d12948e8fe`. [범위와 검증](specs/airline-mail-collection-20261105.md), [운영 기록](operations.md#2026-11-05-제주항공traveloka-항공권-ota-수집-보완).
- Traveloka 수집/항공 파서 누락과 제주항공 인증 경로 누락을 보완했다. 새 원문138건·기존3건 직접 수집 출처 추가, 제주128메일/102예약·Traveloka11메일/5예약 실제 저장소 파싱 확인. 기존 원문/스키마·금융 보호13표 불변, 금융/여행/Google 쓰기0.
- 영향509건/4 subtests/skip0·CI 성공,1333blobs·health/ready·보호API·task/processSHA PASS. 정기 MailCollect를 새 SHA/명시 owner-domain에 연결했다. 원격 클라우드 업로드/전환·새 메일 도착 후 후속 수집은 미실행/미관측이다.
- 인증 OTA 화면은 적재 후 색인 갱신 중이며 최종 읽기 수락 결과는 후속 기록을 따른다. workspace `C:/AX/cost-airline-20261105`, 비공개 체크포인트 `C:/AX/cost/.local-archive/airline-audit-20261105/checkpoint.md`. 기존 사용자 workspace/미추적 자료를 보존했다.

## 2026-11-05 카드 업로드 후속 처리 오류 — 완료

- COMPLETE — 사용자 “문제해결”, [PR #633](https://github.com/6Soo/cost/pull/633), 운영 `2e911f3f6fdb853f1635f720ea259f6191541008`, 이전 검증 `94ccd9b334220bc14b11b1c50decd7f13606fa92`. [실행 결과](specs/upload-audit-recovery-20261105.md). 최초 감사 기록 여부를 실제 stream으로 판단해 기존 장부 행의 후속 처리 실패를 수정했고 로그인 만료401/권한 부족403 안내를 구분했다.
- 업로드12개 모두 저장/배치 classified·파싱 오류0. 한 파일의7행은 기존 원본 충돌 보호로 needs_review를 유지한다. 재업로드 불필요. 과거 인증 오류 원인은 재현되지 않아 단정하지 않는다. 운영 자료 재처리·금융/여행/Google 업무 쓰기0.
- Windows 영향 QA401 passed·33 subtests·skip0·필수 브라우저 누락0, PR CI41889472534 success. 공식 연속 전환 PASS·1,329 blobs 일치·task/processSHA·health/ready200·보호API401·보호13표 내용/스키마 불변. 전환 후 사용량 제한으로 누락됐던 최종 근거는 successor가 실제 상태를 검사해 복구했으며 재배포/재시작하지 않았다.
- 기존 Ego2 인증 화면: 새401/403 코드·저장 상세200(327행, classified320/needs_review7)·없는 작업404·가로넘침0 수락 후 TaskSpace 종료. 실제 고객 업로드/운영 재처리/실기기 확인은 미실행. [운영 기록](operations.md#2026-11-05-카드-업로드-후속-처리-오류)과 `C:/AX/cost/.local-archive/upload-fix-20261105/`에 근거 보존. 이 오류 수정의 미결0·다음 기능 명령 없음. 문서 후속으로 재검사·재배포·재시작하지 않는다.

## 2026-11-05 지출 정리 거짓 원문 충돌 108건 교정 — 완료

- COMPLETE — 사용자 “지출필요건수가 많이 늘었는데 확인하고 코드 수정”. [명세/결과](specs/cleanup-export-conflicts-20261105.md), [PR #631](https://github.com/6Soo/cost/pull/631), 운영 `94ccd9b334220bc14b11b1c50decd7f13606fa92`. 기존CSV의 이용일 대체 매입일과 하나 이용내역의 명시 매입일을 충돌로 판단한108건을 원본 헤더·파일/행 해시로 검증했다. 명칭 차이14건은 동일 가맹점번호와 부분 명칭까지 대조한다.
- 미래 업로드는 기존 원행을 재사용하고, 이미 생긴108개 거짓 충돌은 원본/충돌 플래그·수동 결정·금융 기록을 수정하지 않고 지출 대기열의 중복 작업에서만 제외한다. 실제 금액/명시 날짜/가맹점 차이·모호 원결제·수동/보류/오류/기록 보호는 유지한다.
- 최종Windows 영향QA483 passed·42 subtests·skip0·필수 브라우저 누락0, CI41886588452 success, 검사157a8439와 병합 tree 동일. 배포본의 실제 trip_valid/운영 Google·일정 경로를 사용한 읽기 전용 집계와 목록이10건(금융6·기록4)으로 일치했다. 보호13표·health/ready·보호API 정상. [운영 상세](operations.md#2026-11-05-지출-정리-거짓-원문-충돌-108건-교정).
- 최초 배포 drain timeout은 이전 릴리스 유지/재개·보호13표 동일을 확인하고 연결 자연 종료 후 정상 재시도로 해소했다. 운영DB 교정/삭제·재분류·Google 업무 쓰기·마이그레이션0. Ego50 소실로 배포 후 인증 브라우저 화면/실제 업로드/실기기 확인은 미실행이다. 새 공간이나 다른 사용자 공간으로 우회하지 않았다. 코드/배포 미결0이며 다음 별도 요청을 기다린다. 문서 후속만으로 재배포하지 않는다.

## 2026-11-04 다중 파일 즉시 접수·백그라운드 분류 UX — 완료

- COMPLETE — [PR #627](https://github.com/6Soo/cost/pull/627), 운영 `804eac6023ddcddb90c7959b66fce970bb656ef2`. [요구사항별 결과](specs/card-upload-background-navigation-20261104.md). 여러 파일을 먼저 일괄 접수한 뒤 분류하고, 접수 직후 버튼 활성·페이지 이동 안내·복귀 시 상태 복구를 제공한다.
- 최종 Windows 영향 QA 498건 통과·skip0·필수 브라우저 누락0, [PR CI](https://github.com/6Soo/cost/actions/runs/41771130622) 성공. 최초 실패2건은 사용자 승인으로 HTML/JSON·PDF 응답 계약과 비동기 OTA 준비 대기로 수정했다. 테스트 제외/권한 약화 없이 red→green을 확인했다. 합성 ego12개 접수→이동→복귀12개 복구 PASS.
- 공식 단일 작성자 배포: 1326 blobs 일치·고정task/processSHA·health/ready200·보호API401·보호13표 불변. 코드 전용 전환이며 이전 검증 릴리스/task XML을 보존했다. 고객 업로드·재분류·금융/Google/원본/스키마 업무 쓰기0. 운영 화면 수락의 상세 범위와 증거는 [운영 기록](operations.md#2026-11-04-다중-파일-접수백그라운드-분류-ux)을 따른다.
- 근거 `.local-archive/upload-background-20261104/`. 요청 미결0·다음 기능 명령 없음. 문서 후속으로 재검사·재배포·재시작하지 않는다. 기존 사용자 변경/미추적 자료를 보존한다.

## 2026-11-04 항공권 누락·모바일 정보 밀도 개선 — 완료

- COMPLETE — 최신 사용자 3요청의 [실행 범위](specs/flight-coverage-mobile-density-20261104.md), [PR #626](https://github.com/6Soo/cost/pull/626), 운영 `96b978bfe7f161ccd9c9de090fd635c4b85a6a51`. 보관 메일 3,499건 읽기 대조로 시즈오카 4예약·5이름 표기를 확인했다. 기존 3예약의 대표 이름만 노출하던 경로와 제주항공 조회 누락을 수정했다. 이름 표기는 고유인원·유효 항공권 수를 확정하지 않으며 취소·충돌 경고를 유지한다.
- Google Flights 실제 결과와 Xero 공식 지출 기능/앱 예시 탐색을 반영해 여정 시간·도시·공항을 한 행에 모았다. 카드 버튼 장식 충돌·44px 미만 터치 영역, 모바일 필터 줄 나눔·중복 제목, 지출 0건 필터·반복 집계·중첩 틀도 수정했다.
- Windows 영향 QA590 passed·62 subtests·skip0·필수 브라우저 누락0, CI41769141167 success, 검사 `e31d392b`와 병합 tree 동일. 운영 검색 4예약·2명 그룹 1개·기존 경고 보존, 두 테마 및 390px 7경로 배치 수락. 보호13표·health/ready·보호API 정상. [배포 상세](operations.md#2026-11-04-항공권-누락모바일-정보-밀도-개선).
- 현재 승인 범위의 구현/배포 미결0. 금융/원본/여행/Google 업무 쓰기·재분류·마이그레이션0. 실기기·전체 메일 계정 탐색·모든 자료 조합은 미검증. 다른 checkout 변경과 미추적 자료 보존. 다음 별도 사용자 요청을 기다리며 과거 큐는 재개하지 않는다. 문서 후속은 재배포하지 않는다.

## 2026-11-04 FUKUTAKE·항공권 정보 우선순위/버튼 수정 — 완료

- COMPLETE — [PR #624](https://github.com/6Soo/cost/pull/624), 운영 `f680e7e0b8b6ce6d98cdc30949fa0e2e6d63f99f`. [요구사항별 결과](specs/expense-flight-priority-fix-20261104.md). FUKUTAKE 명시 항목 우선·환불 후보별 대기, 항공권 여정 우선·보조 상세 접기·오염 문장 배제·공통 장식과 전용 버튼 스타일 충돌을 수정했다.
- Windows 영향 QA573 passed·32 subtests·skip0·필수 브라우저 누락0, CI41764424619 success, 검사/병합 tree 동일. 공식 배포의 보호13표·health/ready·보호API 정상. 운영 시즈오카3건·모바일 여정/상세 버튼 수락, 지출 정리 FUKUTAKE4건(기존 불필요14건 제외) 확인.
- 이 요청의 코드/배포 미결0. 기존 실제 항목 일괄 재분류·금융/원본/Google 업무 쓰기는 수행하지 않았다. 실기기·모든 상태 조합은 미검증. [운영 근거](operations.md#2026-11-04-fukutake항공권-정보-우선순위버튼-수정). 문서 후속으로 재배포·재시작하지 않는다.

## 2026-11-04 항공권 날짜·행선지 검색 — 완료

- COMPLETE — [PR #622](https://github.com/6Soo/cost/pull/622), 운영 `8ce17a9a6d37ef4959b34811a3e5fa9469594f88`. 기존 검색창 하나에서 이름·여행 중 날짜·도시·공항 코드의 조합을 검색한다. [요구사항과 결과](specs/flight-route-date-search-20261104.md).
- Windows 영향 QA386 passed·16 subtests·skip0·필수 브라우저 누락0, CI41761912476 성공, 검사/병합 tree 동일. 공식 배포의 보호13표·health/ready·보호API 정상. 운영 `22일 시즈오카`3건·`fuk`8건 및 모바일390px 읽기 수락 완료.
- 이 요청의 미결0. 금융/원본/Google 업무 쓰기·실기기·모든 예약 조합은 미검증. [운영 근거](operations.md#2026-11-04-항공권-날짜행선지-검색). 문서 후속만으로 재배포·재시작하지 않는다.

## 2026-11-04 핵심 기능 중심 UI 축소 — 완료

- COMPLETE — [PR #620](https://github.com/6Soo/cost/pull/620) 병합·운영 `2663f08e9fd478adba52cba2218a5a528046aa81`. [최신 실행 범위](specs/core-ui-reduction-20261104.md)의 UIR01~08을 구현·검증·배포했다. 불필요한 문구/집계·중복 버튼을 제거하고 보조 기능을 접이식으로 이동했다.
- Windows 영향 QA 1,009 passed·121 subtests·skip 0, CI 성공, 검사 트리 동일. 보호13표·health/ready·보호API 통과. 운영 PC11경로/모바일6경로 읽기 수락. 상세 [운영 기록](operations.md#2026-11-04-핵심-기능-중심-ui-축소). 실기기·모든 상태 조합·실제 금융 저장은 미검증이다. 이 승인 범위의 구현/배포 미결0. 문서 후속만으로 코드 검사·재배포·재시작하지 않는다.

## 2026-11-04 PC 여행·항공권 버튼과 아이콘

- PC 1440×900의 여행 관리·여행 장부·항공권 화면과 주요 펼침 및 합성 예약·마감 상태를 점검했다. [PR #616](https://github.com/6Soo/cost/pull/616)에서 마감/해제와 항공권 메뉴 아이콘을 개선하고 운영 `7c0be270a6ef770973efd797be00a9922dbd9210`에 반영했다. 검사와 운영 증거는 [운영 기록](operations.md#2026-11-04-pc-여행항공권-버튼과-아이콘-점검)에 기록한다. 운영 상태 변경 실행과 모든 거래 조합은 확인하지 않았다.

## 2026-11-04 웹 UI/UX 점검 및 카드 검토 개선

- 운영 10개 주요 화면을 320/390/1440px에서 조회해 페이지 가로 넘침 0·테마 버튼 각 1개를 확인했고 지출 정리 4개 탭 전환을 확인했다. 실기기·실제 금융 저장 전체 시나리오 수락을 뜻하지 않는다.
- 카드 전체 내역의 작은 검토 링크를 [PR #614](https://github.com/6Soo/cost/pull/614)로 개선해 운영 `efaf49a319f25e4c40c9c18ae9b10d8c187fbb81`에 배포했다. 상세 테스트·배포 근거는 [운영 기록](operations.md#2026-11-04-카드-검토-모바일-터치-영역-개선). 추가로 발견한 검증된 결함은 없다. 전체 화면의 모든 과업과 실기기는 미검증이다.

## 2026-11-04 보험 후보·지출 편집 미배포 변경 배포

- [PR #612](https://github.com/6Soo/cost/pull/612) 보험 후보 문구·연결 참가자 제외와 [PR #609](https://github.com/6Soo/cost/pull/609) 지출 인라인 편집 밀도·모션 변경을 병합해 `fd7f7fb468486a5e006faa6202a56c277ca41ea2`로 배포했다. 가림 이름이 여러 명과 일치해 구별할 수 없으면 후보를 보존한다. 이전 운영 `3c00ebb4b83cfb7e3c4058a019f54b25b773ad3e`를 복구점으로 유지한다.
- 보험 Windows 영향 QA 277 passed, 지출 Windows 영향 QA 205 passed/27 subtests, 최종 병합 보험 화면 28 passed. 두 PR GitHub impact-checks PASS. PR #609 기존 CI의 숨겨진 구 메뉴 버튼 실패는 최신 main에서도 재현했고 현재 공통 메뉴 검사를 교정한 후 재검증했다. 실자료 화면·전체 회귀는 미실행이다.
- 1,313 blobs 일치, health/ready 200, 보호 API 및 board·참가자 API 익명 401, 보호 13표 내용·스키마 불변. 금융·여행·원본·Google 쓰기와 마이그레이션은 수행하지 않았다. 근거 `C:/AX/cost-flight-606/.local-archive/pending-release-20261104/` 및 `D:/WebLedgerHost/releases/deploy-evidence-fd7f7fb468486a5e006faa6202a56c277ca41ea2.json`. 문서 전용 PR #607·#567은 코드 배포 대상이 아니다.

## 2026-11-04 항공권 예약 화면 개편 배포

- PR #606 명세와 PR #610 구현을 병합하고 `3c00ebb4b83cfb7e3c4058a019f54b25b773ad3e`를 배포했다. 예약의 결제 확인을 통합하고 카드 날짜 목록·원행 상세를 같은 화면에서 읽는다. 동승객과 참가자 연결은 일반 예약 화면에서 제외한다. 이전 검증 릴리스는 `097d7dabe787816244ddf8df03eb759032f84672`다.
- Windows 영향 검사 268 passed/16 subtests, 카드·원행 인접 검사 51 passed, 수정된 테스트 1 passed, 최종 PR CI 41671733214 PASS. 최초 CI는 검색 결과 대기 경합으로 실패했고 수정 후 재실행했다. Ego 합성 검색→카드 목록→원행 상세→닫기와 쓰기 버튼 없음·넘침 없음 확인. 실자료 화면 수락과 전체 회귀는 미실행이다.
- 1,313 blobs 일치, health/ready 200, 보호 API 및 항공권·카드 날짜 경로 익명 401, 보호 13표 불변. 코드 전용이며 업무 데이터·Google 쓰기와 마이그레이션은 수행하지 않았다. 근거 `C:/AX/cost-flight-606/.local-archive/flight-focused-606-release/` 및 `D:/WebLedgerHost/releases/deploy-evidence-3c00ebb4b83cfb7e3c4058a019f54b25b773ad3e.json`.

## 2026-11-04 항공권 조회 갱신 안내 반복 — 완료

- COMPLETE — 사용자 이미지의 안내 반복을 진단하고 [PR #605](https://github.com/6Soo/cost/pull/605), 운영 `097d7dabe787816244ddf8df03eb759032f84672`에 수정했다. 첫 방문 시 색인 생성이 시작돼 운영에서 44.39초 걸렸고, 화면은 2초마다 안내를 다시 공지하며 버튼 재클릭으로 대기 횟수가 초기화됐다. 영구 갱신 실패나 원본 손실은 관측하지 않았다.
- 서버 시작 시 독립 항공권 색인을 사전 준비하며 조회마다 전체 메일 지문 검사를 강제로 깨우지 않는다. 자동 조회 대기 중 버튼/busy 상태와 같은 안내를 유지하고, 갱신 대기는 120초/60회·요청은 15초로 제한해 오류/지연 후 재시도할 수 있게 했다. 최신 원본 검증·수동/금융 연결 보호는 유지한다.
- 검증: Windows 영향 QA `50b355ba` 273 passed/16 subtests/skip0, 후속 테스트만 추가한 `a2a19334` 응답 지연 회귀1 passed·시작/진입점8 passed. PR CI41668924366은 최종 `a2a19334`의274 cases/skip0 PASS이며 병합 tree 동일. 1,312 blobs 일치·task/processSHA·health/ready200·보호API401·보호13표 내용/스키마 전후 불변.
- Ego34 운영 읽기 수락: 새 스크립트·같은 이름 예약2건·조회 약1.391초·버튼 복구/busy=false·가로넘침0. 이번 기동의 검증 캐시 복구는 첫 방문 전에0.9초 완료했으며, 새 원문 전체 파싱도 항상0.9초라는 뜻은 아니다. TaskSpace 종료. 금융/여행/Google/원본/스키마 업무 쓰기·재처리 없음. 이전 검증46339830/task XML 유지, 코드 배포이므로 전체DB백업/복원을 반복하지 않았다.
- 근거 `C:/AX/cost-deploy-qa-20261103/.local-archive/flight-refresh-20261104/` 및 [운영 기록](operations.md). 요청 미결0·다음 기능/배포 명령 없음. 문서 후속만으로 재배포·재시작하지 않는다.

## 2026-11-03 후속 main 운영 배포 완료

- COMPLETE — 사용자 “운영배포해”. 검증된 main `d26b43e9cc9f66ef89d2385d163b67ef7f04bba4`를 공식 배포기로 운영 반영했다. 이전 검증 SHA는 `33bf47e7dbc3788a6eeb4082ad120d221c8cabc7`이며 gateway8790→backend8752, paused=false, Board Running, Prepared 작업 없음이다.
- 후보 포트를 점유한 이전713 릴리스와 진입 서버, 중복33 준비 감독자는 SHA·PID·생성시각·부모 관계·역할·loopback 포트를 확인하고 두 배포 잠금 및 요청/writer drain 아래 정리했다. 정리 중 기존 운영 backend42372는 유지했고 현재33 진입 서버를 복구한 다음 공식 전환을 수행했다. 과거 “복구 미완료” 기록은 당시 상태이며 이번 배포의 차단 사유가 아니다.
- 검증: 1,312 Git blobs 불일치0·task/process SHA 일치·단일 backend listener·health/ready200·보호 API3개401·보호13표 내용/스키마 전후 불변. 전환 중 gateway 표본196요청 실패0/최대7.099초이며 전체 구간 무중단이나 무지연 보장을 뜻하지 않는다. Windows 최종 영향338 passed/4 subtests/skip0와 main CI41636631694 success 및 개별 변경 검증을 재사용했다.
- 여행 이동 이유는 사용자 결정대로 당분간 직접 입력을 사용한다. 새 모델 연결·거래 근거 전송·금융 재처리·Google 쓰기·마이그레이션은 수행하지 않았다. 메모리 영수증 인식 상태는 정상 재시작 시 만료되는 기존 계약이며 원본 이미지와 저장 장부를 보존했다. 이전 검증 릴리스/task XML을 복구 수단으로 유지했고 전체DB백업·복원은 반복하지 않았다.
- 근거 `C:/AX/cost/.local-archive/deploy-resume-20261103/`의 recovery-identities/recovery-result/release-audit/deploy-evidence/protection-before/protection-after/continuity 및 호스트 `D:/WebLedgerHost/releases/deploy-evidence-d26b43e9cc9f66ef89d2385d163b67ef7f04bba4.json`. 전체 미구현 조사는 전수완료 미입증이며 이번 배포 완료와 구분한다. 이 배포 요청의 미결0. 문서 후속으로 재배포·재시작하지 않는다.

## 2026-11-03 QA·UI/UX 기록 대조

- COMPLETE — 이번 요청의 문서 정합성 정리. [능동 QA 현재 판정](specs/autonomous-qa-20261102.md#2026-11-03-기록-대조-후-현재-판정)에 구현·합성 여정 완료와 운영 읽기 수락·서버 강제·효과 실측의 PARTIAL을 구분했다. 로컬 큐의 제한부 완료를 전체 업무 완료로 확대하지 않는다.
- 인라인 편집은 구현·합성 수락·당시 순차 배포 완료이며 운영 편집 흐름 수락은 미확인이다. [최신 명세](specs/inline-bulk-expense-edit-20261102.md)의 미배포 차단과 [전체 UX 감사](specs/full-ux-audit-20261101.md)의 미구현 문구를 교정했다. 아래 감독자/호스트 복구 미결은 별개로 유지하며 이번 정리는 현재 운영 정상화나 새 배포를 주장하지 않는다.
- 남은 확인: 운영 실제 예약 결과 링크 동선·인라인 편집 PC/모바일 읽기 수락, branch protection 강제 여부, 후속 결함률·업무 시간 실측. 실제 OTA 수집·환급·고객 거래 저장·Google 쓰기·실기기 수락은 수행했다고 기록하지 않는다.
- 검증: 기존 XML·배포 JSON·테스트/실행기 소스 대조, 이번 문서 diff·로컬 링크/절·상태 확인. 코드 테스트·브라우저·DB·빌드·재배포·재시작은 미실행이다. 문서 외 실행 명령 없음.

## 2026-11-03 연속 배포 감독자 보호 — 병합, 기존 운영 복구 미완료

- PARTIAL — [PR #585](https://github.com/6Soo/cost/pull/585) `b15710a6bd7e9cc60814a5cbb5141665dcbf2619` 병합. 정상 전환과 후보 준비 실패 시 감독자 신원을 검사하고, 중복·미확인 감독자를 임의 종료하지 않도록 보호한다. 입양된 백엔드와 포트를 열기 전의 후보도 합성 Windows 전환 검사에 포함했다. Windows 영향 QA 71 passed·skip 0, 표적 25 passed, PR CI `41613371942` 성공. 독립 합성 Windows 프로세스에서 불일치 신원 거절·일치 프로세스 종료를 확인했다.
- 현재 운영의 `33bf47e7`에는 준비용·정식 감독자가 각각 존재하고, 이전 `71340078` 프로세스가 8752와 현재 진입 포트 56069를 사용한다. 새 식별기를 운영에 **읽기 전용으로만** 적용했을 때 `SUPERVISOR_AMBIGUOUS`로 거절했다. 이 변경은 이미 남은 프로세스를 정리하지 않는다. 현재 Board task `33bf47e7`, gateway→8751이며 health/ready 200이다. PR #582/#583/#585 운영 반영은 미완료다.
- Windows `IsProcessInJob` 읽기 전용 확인에서 관련 감독자·백엔드·진입 프로세스가 Job Object에 속한다. 종료 정책과 핸들 소유를 확인하지 못했으므로 합성 프로세스 결과를 실제 프로세스 종료 안전성으로 확대하지 않는다. 어느 프로세스도 강제 종료하지 않았다. 동일한 작업 스케줄러/Job Object 구성을 격리해 프로세스 수명·진입 경로·요청 보존·실패 복구를 재현한 후에만 현재 포트 충돌을 해소하고 고정 SHA 배포를 재시도한다. 근거 `C:/AX/cost/.local-archive/completion-audit-20261103/checkpoint.md` 및 `C:/AX/cost/.local-archive/continuous-supervisor-test-20261103/`.

## 2026-11-03 Google 지출 대조·데모 동기화 — 병합, 배포 전환 실패

- PARTIAL — [PR #582](https://github.com/6Soo/cost/pull/582) 병합 `20eb4ca388db4b50403d5f5807fc0fe6aeaf308e`. 선택된 검증 Google 정본과 같은 여행의 지출을 표시용으로 비교하여 단서·복수 후보를 PC/모바일에 표시한다. 복사 중복 판정·금융 연결은 변경하지 않는다. Windows 영향 QA 184 passed·9 subtests·skip 0, PR CI `41608573778`·main CI `41609077615` 성공. 금융·수동 링크 등 별도 표적 67 passed. 인접 그룹 화면 fixture 1건 실패는 기준 `afd21ce2`에서도 동일 재현했다.
- PARTIAL — [PR #583](https://github.com/6Soo/cost/pull/583) 병합 `4b9aaca9d1c3ea1cc0673d4738cd1b9a2c89a9e8`. 명시적으로 활성화된 실제 데모에 한해 동일 정본의 정상 동기화 직후 익명 집계를 저장하고 조회와 갱신을 직렬화한다. 동기화 실패 시 마지막 정상 결과를 지연 표시한다. Windows 영향 QA 337 passed·skip 0, PR CI `41610189708`·main CI `41610428270` 성공. 실제 데모 공개 설정·고객 자료는 변경하지 않았다. 실제 자동 갱신에는 동기화 프로세스의 동일 snapshot 경로와 기존 공개 게이트 설정, 최초 개인정보 검수가 필요하다.
- 두 PR의 운영 배포는 **미완료**다. `20eb4ca3` 전환은 공식 배포기에서 `DEPLOYMENT_FAILED_VERIFY_PRIOR_RELEASE`로 실패했다. 현재 Board task `33bf47e7dbc3788a6eeb4082ad120d221c8cabc7`·gateway→8751·health/ready 200이며 보호 13표 전후 불변이다. 8752는 이전 검증 릴리스 `71340078` 프로세스가 점유하고, 그 트리의 진입 서버는 56069에서 실제 서비스 중이다. 정리 사전 검사는 살아 있는 자식/진입 listener를 발견해 동작 전에 중단했으며 프로세스 종료는 없었다.
- 원인 분석과 다음 단계: `switch_continuous_release.ps1`은 준비 포트 사용을 차단하고 기존 진입 서버 SHA가 직전 릴리스와 같아야 한다. 현 진입 서버는 그보다 오래된 `71340078`이다. windowless wrapper 자손의 수명과 재생성을 합성 Windows 테스트로 재현하고, 활동 중 작업·요청 보호와 실패 복구를 포함한 안전한 인계 절차를 검증한 후에만 배포한다. 8752를 강제로 비우거나 56069를 임의 종료하지 않는다. 최신 main `4b9aaca9` 릴리스는 1,312 blobs 불일치 0으로 준비했다. 근거 `C:/AX/cost/.local-archive/completion-audit-20261103/checkpoint.md`, `C:/AX/cost/.local-archive/google-display-candidates-20261103/` 및 두 작업 공간의 `quality-artifacts/`.

## 2026-11-03 항공권 개편·예약기간 교정·업로드 재시작 배포 — 완료

- COMPLETE — [PR #574](https://github.com/6Soo/cost/pull/574) (항공권 예약 조회 개편), [PR #578](https://github.com/6Soo/cost/pull/578) (기록된 자동 배정 예약 이용기간 교정), [PR #576](https://github.com/6Soo/cost/pull/576) (업로드 재시작 시 저장된 배치 링크 보존) 병합 및 고정 배포 `33bf47e7dbc3788a6eeb4082ad120d221c8cabc7`.
- 공식 `deploy_verified_release.ps1` 무중단 전환 성공: gateway8790→backend8751, 1,312 tracked blobs 불일치 0, listener 1, health/ready 200, 보호 API 401, 보호 13표 불변 PASS.
- 배포 중 업무 DB/Google/원본/스키마 쓰기 0, 금융 안전 게이트 통과. 호스트 및 로컬 검증 근거 보존.

## 2026-11-03 기록된 자동 배정 예약 이용기간 교정 — 완료

- COMPLETE — 사용자 “이용일 제대로 체크했는데 왜 엉뚱한곳에 배정됐지? 문제찾고수정” [PR #578](https://github.com/6Soo/cost/pull/578) 병합 `cc9d31cb`, 구현 `8bc945ff`·`d93ec632`, 사양 [기록된 자동 배정 예약 이용기간 교정](specs/recorded-booking-period-correction-20261103.md).
- 원인: 예약 확인 전 카드 결제일로 자동 추론 배정된 거래는 이후 새 예약 이용기간이 확인되어도 기존 자동 배정이 장부에 남아 화면/거래가 갱신되지 않았음. 수정: 명시 카드 재분류 시 유효한 예약 이용기간을 확인하면 기록된 자동 추론을 해당 이용기간의 실제 여행으로 원자적 교정. 수동 수정·owner 기장·검토 보류·환불 및 원결제 보호 유지.
- 문제 거래 1건(아고다 175,019원, 이용기간 10/13~10/14)을 `1002_영남`에서 `1010_도쿠시마`로 교정 완료. 단일 행 사본·원자 저장·교정 이력 보존, 거래/장부/화면 세 위치 일치, 금액·원본·날짜·ID 보존, 추가 반복 대상 0건 검증.
- 검증: Windows 영향 QA 373 passed·30 subtests·skip 0, PR 호스팅 CI 41596907545 성공, main 병합 CI 41597324430 성공. 운영 DB 읽기 전용 검증에서 세 투영 일치, 금융 보호 불변, 교정 이력 1건 재확인. 근거 `C:/AX/cost/.local-archive/stay-trip-fix-20261103/` 및 `D:/WebLedgerHost/data/backups/stay-period-single-20261103/`. 문서 후속만으로 재검사·재배포·서버 재시작하지 않는다.

## 2026-11-03 토요코인 수집·이용일 표시 점검 — 완료

- COMPLETE — [PR #575](https://github.com/6Soo/cost/pull/575) 병합·운영 `bcd4e5bf5fd4e51516f5a026f3c41308ad64e311`, 이전 검증 `d57675a512f3c1446d0d3c9d3966114637640220`. 토요코인 메일 파서에서 홈페이지/감사 인사말을 호텔 지점명으로 오인하던 결함(69건)을 수정하고(parser12), 동일 지점·숙박 시점의 예약 후보 이용기간이 모두 일치할 때 장부에 '예약 근거 추론'으로 읽기 전용 표시를 보완했다. 개별 예약번호·결제 검증은 승격하지 않으며 원본/금융/여행 배정/Google 쓰기 없음.
- 수집 점검 및 Google 재인증: 사용자 승인 하에 Ego 창에서 Google 계정(kkokkohero6@gmail.com) 재인증 완료 후 토큰 원자적 교정. Gmail 읽기 전용 조회(전체 986건, 기간 255건, 10/1 이후 44건) 누락 0건 확인. `WebLedger-MailCollect` 예약 작업 정상 완료(exit code 0, 100건 신규 메일 정상 수집).
- 검증 및 배포: 표적 106 passed, Windows 영향 QA 495 passed·13 subtests·skip0 및 PR CI 41594203986 성공. 1,309 blobs 불일치0·backend8751 단일 배포·health/ready 200·보호 API 401·보호 13표 불변 PASS. ego-browser 운영 UI 수락(`1002_영남` `tab=trip-86714d1ca408`)에서 10/2(1,445,900원) 및 10/3(68,000원) 토요코인 창원 행의 '10월 2일(금) ~ 10월 4일(일) · 2박 · 예약 근거 추론' 표시와 가로 넘침 없음(overflow: false) 확인. 근거: `.local-archive/toyoko-audit-20261103/` (`actual-display.json`, `live-pc.json`, `deploy-evidence.json`, `reauth-audit.json`, `review.json`) 및 [명세](specs/toyoko-collection-audit-20261103.md). 다음 기능 명령 없음.

## 2026-11-03 트립닷컴 날짜 중복·OTA 추론 출처 표기

- 구현·검증·병합·배포 COMPLETE: [PR #572](https://github.com/6Soo/cost/pull/572), 병합 `2c0616a27470e73c66b568cae80b639a95f0e1fd`, 합동 운영 `d57675a512f3c1446d0d3c9d3966114637640220`. 숙박 이용일 열과 정확히 같은 기간만 설명에서 생략한다. 이용일 미상·오류·다른 기간은 보존하며 원본/예약번호/메모/복사 내용은 변경하지 않는다. OTA 코드 matcher의 추론은 `코드 추론`으로 통일하고 기존 `AI 추론`은 구분한다.
- 고정 병합 SHA Windows 영향 QA478 passed·43 subtests·skip0(1007.24초), PR CI41592175031 및 main CI41592668337 성공. 초기 오래된 환불 비교 기준 실패2건은 기준 커밋에서도 재현했고, 승인된 변경 직전 기준으로 교정 후 비교6건 통과. 다른 작업의481검사와 합산하지 않는다.
- 단일 작성자650fe1e1의 공식 합동 배포: 1308 blobs 불일치0·runtime SHA·health/ready200·보호API401·보호13표 불변. 고객 원본/금융/Google/여행 자료 쓰기0. 실제 근거는 [운영 기록](operations.md) 및 `.local-archive/expense-date-inference-20261103/final-windows-quality/`다.
- 추가 운영 화면 수락 PARTIAL: Ego17/p1 첫 여행에서 인증 main·43행·`코드 추론`4건 확인. 뒤의 여행 이동은 navigation/evaluation timeout으로 미완료이며 같은 공간 reload·p2 복구도 응답하지 않았다. `body.textContent`의 잔여 구문2건은 숨은 원문/다른 상태 여부를 확인하지 못했으므로 가시 OTA 상태 잔존이라고 단정하지 않는다. 날짜의 실제 운영 전후 비교와 세 여행 전체 수락은 주장하지 않는다. Ego17/p1,p2는 오류 상태라 finish하지 않았다.
- 다음: 브라우저가 응답할 때 동일 Ego17의 현재 상태를 확인하고, 필요시 page reload 후 `.local-archive/expense-date-inference-20261103/browser13-after.mjs`를 현재 Page에 맞춰 실행해 추가 읽기 수락을 기록한다. 코드 검사·배포·데이터 교정을 반복하지 않는다. 공용 checkout의 다른 사용자 변경은 보존했다.

## 2026-11-03 제주항공 OTA·0909 제주 카드 제한 — 완료

- COMPLETE — [PR #566](https://github.com/6Soo/cost/pull/566) 병합·운영 `f1b1ff63b5eaefcbea914808f3022ec6044e3a1e`, 이전 검증 `35ec72b8cb0fe5547dfd80cef01772f6ab2b7e3b`. 제주항공 원문2건은 예약1건·결제2건·관측3건으로 집계하며 카드 원행을 중복 집계하지 않는다. `0909_제주`는4813만 자동 후보로 허용하고 다른 카드는 기존 규칙을 따른다. 기존 데이터 교정62건과 원문 적재는 재실행하지 않았다.
- Windows 영향QA573 passed·34 subtests·skip0 및 PR CI41578660810/main CI41579009582 성공. 1,307 blobs 불일치0·공식 단일 작성자 배포·gateway8790→backend8752·task/processSHA·health/ready200·보호API401·보호13표 불변 PASS. 배포 중 업무DB/Google/원본/스키마 쓰기0. 운영DB 읽기에서 제주4813 3건·타카드0을 재확인했다.
- 기존 Ego9 소실 후 사용자 승인으로 Ego13을 열었다. 카드 대사 generation663·색인 갱신 완료 후 인증 OTA 화면에서 예약1행·원결제311,600원/추가85,600원 카드2건·`0806_다테시나` 배정을 수락했다. 제주 여행 화면도 지출3건이다. 근거 `C:/AX/cost/.local-archive/jeju-resume-20261103/`의 `live-ota.json`, `live-jeju.json`, `canonical-jeju.json`과 [실행 기록](specs/jeju-ota-card-scope-20261103.md). Ego13 종료, 요청 미결0·다음 기능 명령 없음. 문서 후속만으로 재검사·재배포·서버 재시작하지 않는다.

## 2026-11-03 승인 배포 후속 — 게이트웨이·지출·영수증·보험 운영 반영

- COMPLETE — 사용자 “배포해”의 선행 검증 후보 `ac2eed1635bd8b807abdee2e6dbcd382ef969225`를 이전 검증 `a9b0617a132be8ea83328a8ac6a9345514efeffc`에서 배포했다. 이어 기존 승인된 보험 PR #558/#559의 `6d7c4f59834fa2f245d759ede54dba554e0741d3`, 후보 보기 PR #560의 `e75f0b9699bd87fe951ea307712258db974a8677`를 단일 작성자로 순차 배포했다. 아래 과거 정책 차단·운영 미배포 상태는 이 실제 배포 기록으로 대체한다. 지출 인라인/일괄 편집 및 영수증 PDF/영역 검토 코드도 포함된다.
- 이 배포 범위의 마지막 SHA는 `e75f0b9699bd87fe951ea307712258db974a8677`, gateway8790→backend8752였다. 각 단계 1,304 tracked blobs 불일치0·task/process SHA 일치·health/ready200·보호API401·보호13표 내용/스키마 불변. Board/Gateway/SourceRefresh Running, Prepared 임시 작업 정리. 코드 전용으로 이전 검증 릴리스/task XML을 보존하고 전체 자료 백업/복원을 반복하지 않았다. 금융·Google 최종 장부·원본·스키마 업무 쓰기와 재처리 없음. 이후 별도 여행 마감 PR #561 담당자가 `35ec72b8cb0fe5547dfd80cef01772f6ab2b7e3b`/8751로 정상 배포한 실제 deploy-evidence PASS를 관측했다. 이를 e75로 되돌리지 않으며 해당 기능 상세는 그 담당 기록을 따른다.
- 검증 근거 재사용: 선행 누적 영향 QA1,175 passed+96 subtests/skip0, 설치기 수정65 passed/skip0와 PR #563 CI41576154132 성공. 두 글자 이름 Windows/CI 각각465 passed+16 subtests/skip0, 후보 보기 Windows/CI 각각361 passed+25 subtests/skip0 및 main CI41574755063 성공. 서로 겹치는 검사 수는 합산하지 않는다.
- 재개 시 중단된 후보 준비 작업을 SHA/포트·두 배포 잠금으로 확인해 정리한 뒤 공식 배포기를 재실행했다. 선행 전환 연속 health/ready508요청 실패0. 인증 UI 수락 및 부팅 창 억제 후속은 별도 기록을 따른다. Ego4는 `task space not found`로 복구 실패하여 새 공간으로 우회하지 않았고, 보험 담당자는 기존 Ego6에서 읽기 수락을 담당한다. 실제 연결 저장·고객 업로드·Google 쓰기는 하지 않는다.
- 추가 실제 읽기 수락: 보험 담당 successor7a561492가 기존 Ego6에서 API200·규칙v3-two-character·대상1명 name_match/자동 이름 연결1개를 확인했다. 수입13행 전체 digest와 대상 날짜/금액은 보존됐다. 4개 영향 화면 인증main/가로넘침0, 글자 일치 없음 후보 모달9명 표시·닫기, 연결된 수입행 상세의 자동 이름 연결 문구를 확인했다. 이는 자동 대조 결과이며 사용자 수동 확정·실제 보험 가입 완료·금융 저장을 뜻하지 않는다. Gateway 다음 시작은 별도 창 억제 담당992b3fe4가 pythonw Execute-only로 변경했고 인수/작업 설정 불변·현재PID유지·재시작0·health/ready200을 확인했다.
- 창 억제 후속 COMPLETE — Board/SourceRefresh도 pythonw 래퍼 등록을 완료했다. Board 내부 실행 경로가 잘못 생성됐던 중간 결과는 폐기하고, 정확한 PowerShell 단일 경로로 교정한 `C:/AX/pc-manager/ops/startup-console-fix-20261103/board-repair-result.json` PASS를 최종 근거로 사용한다. 원래 인수·작업 디렉터리·XML 설정, 실행 프로세스·route 보존, 재시작0. `.local-archive/deploy-main-20261103/final-windowless-checkpoint.json`에 gateway8790/backend8751 health/ready200·보호API401·배포lock FREE 기록. 세 작업 모두 Running이며 다음 예약 시작의 창 억제 설정을 확인한 것으로, 재부팅 검증을 뜻하지 않는다.
- 근거: [운영 기록](operations.md)의 2026-11-03 순차 배포, 로컬 `.local-archive/deploy-main-20261103/`, `.local-archive/insurance-two-character-20261103/`, `.local-archive/insurance-no-match-20261103/`와 호스트 각 SHA의 deploy-evidence/continuous-switch JSON. 543/5d 사용량 오류 후 배포는 successor `36e9f713-4b6b-4c32-9857-14f6d93d9f9b`가 인수했다. 이 배포 요청의 미결0이며 다른 담당자의 후속 기능 작업은 포함하지 않는다. 문서 후속만으로 재배포·서버 재시작을 하지 않는다.

## 2026-11-03 지출 인라인·일괄 편집 후속 수락

- PARTIAL — [PR #555](https://github.com/6Soo/cost/pull/555) 병합 `c8ba18d50f003d0e1528d3068fd3dfa08575f636`, GitHub CI `41488569096` 통과. 단일 편집에서 바꾸지 않은 여행까지 수동 교정으로 고정하던 문제와 모바일 하단 바의 여행 선택기가 과도하게 줄어드는 문제를 수정했다. 기본 인라인·다중 편집은 PR #549를 유지한다. 후속 순차 배포로 운영 반영은 완료했으며 운영 편집 흐름 수락은 미확인이다.
- 코드 검사 SHA `0fe7c48da293f15d3f83e3d54fa6609bc758ded5`: 영향 QA 378 passed·55 subtests·skip 0. 후속 `572908f7`은 명세 상태 문서만 변경했고 문서 검사 통과. 로컬 근거 `C:/AX/cost-inline-acceptance/quality-artifacts/`, `.local-archive/inline-bulk-checkpoint-20261103.md`.
- 새 작업 공간 사용에 대한 사용자 승인 후 Ego78에서 합성 자료로 단일 항목/여행 저장→다중 선택→여행 일괄 저장과 항목 유지, 1440/390/320px·라이트/다크, Enter/Space/Shift/Escape, 미저장 입력 보존, 보호 실패와 두 탭 revision 충돌 시 선택·대상 유지를 확인했다. 거래처 열은 PC 634px(900px 화면에서는332px), 모바일 가로 넘침0, 수정 후 선택기 폭262/192px. 실기기·실제 금융 자료 쓰기·Google 쓰기·운영 수락은 미실행이다.
- 후속 `ac2eed1635bd8b807abdee2e6dbcd382ef969225` 순차 배포에 포함돼 배포는 완료했다. 당시 근거는 위 순차 배포 및 [운영 기록](operations.md)이다. 과거 설치 차단은 이 기능의 재배포 사유로 사용하지 않는다. 남은 항목은 인증 운영 PC·모바일에서 편집 열기·다중 선택·하단 바·입력 보존의 읽기 동선 수락이다. 실제 고객 거래 저장·Google 쓰기는 포함하지 않는다.

## 2026-11-02 영수증 PDF·영역 검토 — 병합, 운영 전환 대기

- PARTIAL — [PR #553](https://github.com/6Soo/cost/pull/553) 병합 `01a7b2321b1d53583a876076f8c1fa298d457aee`. PDF 원본 보존 및 페이지별 OCR, 영수증 영역 표시·교정, 겹치는 후보 중복 보호와 재분석 위치 대응을 구현했다. 영역을 알 수 없는 후보는 미지정으로 표시하고 기존 미지정 후보와 중복 가능성을 보수적으로 처리한다.
- 검증 head `e598c30177a63c28d71faccf721fe86ad18ecf3a`와 병합 트리는 동일하다. Windows 영향 QA와 호스팅 CI 각각 365 passed·30 subtests·skip 0, 합성 브라우저에서 영역 교정·무효 좌표 보존·재분석을 확인했고 실제 Windows OCR에 합성 PDF를 사용했다. 실제 고객 영수증과 외부 AI 추론은 검증하지 않았다. Windows OCR은 `WEBLEDGER_RECEIPT_OCR=windows` 설정이 필요하다.
- 운영 배포와 운영 수락은 아래 게이트웨이 정책 차단 해소 후 수행한다. 마지막으로 확인한 운영 SHA는 `a9b0617a132be8ea83328a8ac6a9345514efeffc`다. 지출 인라인·일괄 편집 [PR #549](https://github.com/6Soo/cost/pull/549)도 병합됐으나 운영 배포와 운영 화면 수락은 아직 남아 있다.

## 2026-11-02 개발·배포 중 502 방지 구조 — 운영 전환 차단

- PARTIAL — 사용자 “적용해” 범위의 [명세](specs/continuous-deployment-20261102.md)를 [PR #547](https://github.com/6Soo/cost/pull/547)로 구현·병합했다. 병합 `6207dd3092c40adb5f0ce0fafb687f0141c916c2`, 검사 트리 `7afec0f1`와 동일. 고정 게이트웨이·후보 준비·요청 drain·단일 자동 작성자·실패 복구를 구현했다.
- 영향 QA 257 passed·skip 0, 게이트웨이/합성 Windows 전환 10 passed(영향 QA에 포함), 기존 호스트 미결 재검사 1 passed. PR CI 41439813479·main CI 41440047572 성공. 배포 후보 1,300 tracked blobs 불일치 0, 보호 13표 사전 읽기 완료.
- `DEPLOY_BLOCKED_TOOL_POLICY` — 게이트웨이 설치를 포함한 셸 호출이 프로세스 생성 전에 자동 승인 검토에서 `blocked by policy`로 거부됐다. 세부 이유는 반환되지 않았다. 우회 실행하지 않았으며 설치·터널 전환·후보 기동·운영 배포는 미실행이다. 기존 운영 `a9b0617a132be8ea83328a8ac6a9345514efeffc` task Running, route 파일 없음, health/ready 200을 읽기 전용으로 재확인했다. 금융·Google·원본·스키마 업무 쓰기 없음. 보호표 사후 비교·전환 연속 요청 검사는 미실행이며 배포 성공으로 취급하지 않는다.
- 재개는 도구 정책 거부가 해소된 뒤만 가능하다. 단일 작성자·실제 운영 SHA를 다시 확인하고 `.local-archive/continuous-deploy-20261102/checkpoint.json`의 설치→고정 SHA 배포→연속 요청/보호 API/13표/작업·프로세스 SHA 검증을 수행한다. 명령과 근거는 [운영 기록](operations.md)에 있다. 사용자/타 작업의 workspace·미추적 파일을 보존했다.

## 2026-11-02 항공권 불일치 교정 및 배포

- 완료 — [PR #544](https://github.com/6Soo/cost/pull/544) 운영 `a9b0617a132be8ea83328a8ac6a9345514efeffc`. 인증 메일의 단일 출발·도착 라벨을 읽어 실제 여정일에 예약을 귀속한다. 대상 카드 1건은 원문과 여행 기간을 대조해 AI 추론으로 여행을 교정했고 거래·장부 양쪽 일치를 재확인했다. 자동 OTA 연결을 사용자 확정으로 취급하지 않았다.
- 표적 56건, 영향 QA 260건·skip 0 및 호스팅 CI 통과. SHA 파일 1,293개 일치, 백업·복원 검증, health/ready 200, 보호 API 및 보호 13표 불변. 색인 갱신 후 인증 운영 여행 화면에서 예약 1건과 출발일을 확인했다. [운영 기록](operations.md) 참조.

## 2026-11-02 카드 다중 업로드 대기 개선

- [PR #541](https://github.com/6Soo/cost/pull/541)을 운영 `828e56db310e41fab864410e2dacb7049ed503a3`에 배포했다. 파일 접수·상태 대기를 최대 4개 겹치고 선택 순서와 재시작 정보를 보존한다. 서버 접수·분류는 공유 잠금으로 직렬화되므로 실제 처리 시간 개선 폭은 미측정이다.
- 표적 7 passed, 영향 QA 207 passed·30 subtests, GitHub Actions 41431463759 통과. 운영 파일 1,293개 해시 일치, health/ready 200, 보호 API 및 보호 테이블 13개 불변. 인증 운영 업로드 화면 탭·버튼·변경 코드 및 가로 넘침 없음 확인. 실제 고객 업로드는 미실행. 근거 `.local-archive/autonomous-qa-20261102/upload-speed-release/deploy-evidence.json`.

## 2026-11-02 항공권 운영 화면 후속 확인

- 새 ego-browser 작업 공간에서 인증된 항공권 화면과 합성 이름의 예약 없음 응답·입력 유지·가로 넘침 없음을 확인했다. 실제 예약 결과의 새 탭 클릭은 수행하지 않았다. [운영 기록](operations.md)에 근거와 한계를 기록한다.
- 합성 홈→여행→실제 XLSX 다운로드 검사 [PR #538](https://github.com/6Soo/cost/pull/538)과 현행 업로드→분류→규칙→출력 검사 복구 [PR #539](https://github.com/6Soo/cost/pull/539)를 병합했다. 상세 범위와 검사 결과는 `.local-archive/autonomous-qa-20261102/continuation-queue-20261102.md`에 있다. 두 PR은 테스트 전용이며 운영 재배포하지 않았다.

## 2026-11-02 항공권 검색 복귀 개선

- [PR #536](https://github.com/6Soo/cost/pull/536)을 운영 `d878234c2ca90ab6c1362f7a007f284060562e88`에 반영했다. 합성 앱에서 항공권 검색→새 탭 카드 상세→여행 항공편 상세 및 원래 검색 유지 확인, 영향 QA 260 passed·16 subtests와 CI 및 배포 보호 검사 통과. 후속 인증 운영 화면 확인의 범위는 위와 [운영 기록](operations.md)을 따른다.
- 후속 #534/#535/#538/#539/#540으로 명시된 합성 여정과 항공 화면 읽기 수락을 보완했다. 실제 예약 결과 링크 동선·효과 지표 등은 [능동 QA 현재 판정](specs/autonomous-qa-20261102.md#2026-11-03-기록-대조-후-현재-판정)의 PARTIAL을 따른다. 아래 능동 QA 진행·미결 표기는 당시 이력이며 과거 테스트 실패·세션 차단을 현재 실행 큐로 사용하지 않는다. 실제 OTA 수집·환급·Google 장부 쓰기는 검증 완료로 주장하지 않는다.

## 2026-11-02 능동 QA 후속 여정 검증

- PARTIAL — 합성 모바일 카드 업로드→화면 분류→여행 장부 복사 [PR #530](https://github.com/6Soo/cost/pull/530), 영수증 교정·복사→원래 여행 복귀 [PR #531](https://github.com/6Soo/cost/pull/531), 합성 OTA 결제·환불·여행 보호 [PR #532](https://github.com/6Soo/cost/pull/532)을 검증 후 병합했다. #532의 OTA 보고서는 합성 주입이며 실제 수집 수락이 아니다. 테스트 전용 변경이라 운영 재배포는 하지 않았다.
- 운영은 `38d31b89a202d0b7da30bb1bf08f0bd2340b6c2a`, 현재 상세 검증·미결은 [능동 QA 기록](specs/autonomous-qa-20261102.md)과 `.local-archive/autonomous-qa-20261102/continuation-queue-20261102.md`에 있다. 전체 업무의 모든 조합을 완료로 주장하지 않는다.

## 2026-11-02 카드 자료 상태 보호 및 능동 QA 진행

- PARTIAL — [PR #528](https://github.com/6Soo/cost/pull/528)의 업로드 중 자료 전환 상태 보호와 카드 복사 검사 복구를 운영 `38d31b89a202d0b7da30bb1bf08f0bd2340b6c2a`에 반영했다. 영향 QA 227 passed·34 subtests·skip 0, 호스팅 CI 및 배포 보호 검사 통과. 인증 운영 화면 확인은 읽기 전용이다. [운영 기록](operations.md)을 따른다.
- 전체 승인 업무의 종단 간 수락은 여전히 미완료다. 일부 합성 모바일 분류는 UI 대신 API를 사용했다. 상세 근거와 남은 작업은 `.local-archive/autonomous-qa-20261102/continuation-queue-20261102.md`에 기록한다. 실제 금융·Google 장부 업무 쓰기는 하지 않았다.

## 2026-11-02 여행 정보 접근성 및 능동 QA 진행

- PARTIAL — [PR #523](https://github.com/6Soo/cost/pull/523)의 합성 브라우저 여행 정보 동시 수정 충돌 검사와 [PR #524](https://github.com/6Soo/cost/pull/524)의 세 입력 라벨 연결을 완료했다. 운영 `58557f389bde6e67d59f7de3041e0d96b9fd6942`, 영향 QA 423 passed·35 subtests·skip 0 및 인증 운영 화면 수락. [운영 기록](operations.md)을 따른다.
- 카드 복사 검사 복구와 전체 승인 업무의 종단 간 수락은 계속 진행 중이다. 현재 증거와 다음 작업은 `.local-archive/autonomous-qa-20261102/continuation-queue-20261102.md`에 기록한다. 실제 금융·Google 장부 업무 쓰기는 하지 않았다.

## 2026-11-02 능동 QA 계속 작업

- PARTIAL — [PR #521](https://github.com/6Soo/cost/pull/521)의 영수증·예약 연결 본문 랜드마크를 운영 `82d818fcb86d1059db1413749f54f042a239a87f`에 반영했다. 영향 QA 189 passed·15 subtests, 호스팅 검사 통과, 보호 13표 불변 및 인증 운영 두 화면 읽기 확인. [운영 기록](operations.md)을 따른다.
- 전체 업무 종단 간 수락은 미완료다. 카드 복사 테스트는 예전 카드 상세 버튼을 기대해 전체 모듈이 실패하며, 분기 복사와 여행 장부의 현재 경로로 보호 시나리오를 옮겨야 한다. 미완성 변경과 상세 재개 지점은 `.local-archive/autonomous-qa-20261102/continuation-queue-20261102.md`에 보존한다. 금융·Google 장부 운영 쓰기는 하지 않았다.

## 2026-11-02 저장 파일 상세 이동 및 재처리 안내

- COMPLETE — [PR #516](https://github.com/6Soo/cost/pull/516), 코드 `1bf142bd0b6c0cc07ae70ecf2b14679ee0e675e6`, 운영 `41c66b8b7e17b150391ad7898aed09956a472120`. 저장 파일 상세를 현재 페이지에서 불러오고, 원본 저장 후 처리 오류로 자동 재처리됨을 안내한다. 개별 파일의 오류 원인과 재처리 완료 여부는 확인하지 않았다.
- 검증: 표적 23건 통과, 영향 QA 230건·30 subtests 통과, skip 0, GitHub Actions 41399400683 통과. 배포 1,292 blobs 일치, health/ready 200, 보호 API 확인, 보호 13표 불변. 근거 `.local-archive/upload-detail-20261102/deploy-evidence.json`. 운영 인증 화면 수동 확인은 미실행. 다음 명령 없음.

## 2026-11-02 능동 감사·다중 업로드 운영 반영 및 미결

- PARTIAL — [실행 기록](specs/autonomous-qa-20261102.md)의 최근 PR30 분석, 발견 결함 개선, 영향 기반 QA와 다중 업로드 수정은 [PR #513](https://github.com/6Soo/cost/pull/513), [PR #514](https://github.com/6Soo/cost/pull/514)로 병합해 운영 `20da556e174c66570a856324c770e05ad422aa69`에 반영했다. 전체 업무 감사의 모든 end-to-end 수락과 배포 후 인증 화면 확인은 아직 완료로 표시하지 않는다.
- #513의 `ad72e131` PR 검사 825 passed/86 subtests, 정기 감사 704 passed/86 subtests. #514의 `7ed20a3c` 로컬·호스팅 영향 검사 각각 280 passed/30 subtests, skip·필수 브라우저 누락 0. 두 실행은 중복 대상이 있어 합산하지 않는다. 10개 파일 중 한 파일의 상태 확인이 실패해도 나머지를 계속 접수하고 파일별 결과·재개를 보존한다.
- 운영은 1,292개 blob 일치·task/process SHA·단일 listener·health/ready 200·보호 API 401/403·보호 13표 전후 불변 PASS. 직전 검증 릴리스 `a7aa8c7f` 복구점 유지. 금융/여행/Google/원본/스키마 업무 쓰기 0. 배포 후 ego TaskSpace 21은 `task space not found`로 인증 화면을 재사용하지 못했다. 새 공간으로 우회하지 않았으며, 인증된 운영 영향 화면 수락과 전체 승인 업무별 미검증 여정은 남아 있다.
- 다음: 기존 ego 작업 공간을 복구해 배포 후 운영 영향 화면을 읽기 전용으로 확인하고, `.local-archive/autonomous-qa-20261102/final-acceptance-review-v103.md`의 미검증 업무를 실제 수락 증거와 대조한다. 운영 근거는 `.local-archive/autonomous-qa-20261102/deploy-evidence.json`, 검사 근거는 GitHub Actions 41394660544·41394655458·41395391574 및 로컬 `final-qa-acceptance.json`. 문서 후속만으로 재배포·재시작하지 않는다.

## 2026-11-02 보험 연결 표시 간소화·미연결 연결 버튼 완료

- COMPLETE — 사용자 “일단 연결이 되면 크게 수정할 필요가 없는 부분이야. 버튼이 도드라지지않고 자연스럽게 글자위주로 변경하고, 미연결 부분을 버튼으로 만들어서 기능을 추가해.” [PR #505](https://github.com/6Soo/cost/pull/505), 구현 `447ebb16c4b97cdf8c865be1de7db7003a3466fc`, 병합·고정 배포 `c0d45b46b10726ea9ce660ba92c62f79e3e998f5`, 이전 검증 `ec2a37ab4c2b9a6d9e41a23de64e2b09869d0870`.
- 연결된 보험은 보조색 글자·작은 펼침 화살표로 표시하고 기존 상세/수정 경로를 유지한다. 미연결은 버튼으로 전환해 해당 수입을 미리 선택한 기존 보호 연결 폼을 열고 참가자 선택란으로 이동한다. 클릭만으로 저장하지 않으며 확인 후 연결한다. 연결 후보가 없으면 안내와 보험 명단 상세 경로를 제공한다.
- 검증: 표적87 passed/2 deselected, 최신 main 통합5 passed·JS 문법 PASS. ego-browser 합성320/390/1440px×밝음/어두움6건·키보드·실제 합성HTTP 연결/취소/확인·후보 없음 PASS. 합성 연결1→2, 취소 시1 유지, 원본 수입 불변. 운영 읽기 수락에서 정확한 수입 선택·참가자란 focus·폼 표시 PASS, 연결 글자400/테두리0·44px 터치 영역·행 높이 동일·가로 넘침0. 실제 운영 연결 저장은 누르지 않았다. 기존 보험 패널 header 테두리0·아이콘 및 workflow 공통 장식 제외도 확인했다.
- 배포1,269 blobs 불일치0·runtime SHA 검증·단일 listener·health/ready200·보호API401/403·금융보호13표 전후 불변 PASS. 이전 검증 릴리스/task 복구점 보존. 코드 전용으로 새 전체DB백업/복원은 반복하지 않았다. 금융/참가자 연결/Google/원본/스키마 쓰기0. 전체 회귀·실기기는 국소 UI 변경으로 미실행이다.
- 근거 `.local-archive/insurance-connect-action-20261102/`의 targeted/integrated XML·review/release-audit/deploy-evidence·browser-layout/browser-connect/browser-no-candidates·live-final.json·live-after.png·checkpoint.json. 재개 시 배포/운영 수락 근거를 대조하고 남은 문서만 완료했다. 해당 이름의 활성 ego TaskSpace 없음 확인. 기존 사용자/병행 변경을 보존하고 별도 index로 본 문구만 커밋한다. 요청 미결/차단0·다음 기능 명령 없음. 문서 후속으로 재검사·재배포·서버 재시작하지 않는다.

## 2026-11-02 카드 조회기간 증빙·미확인 구간 구현 완료

- COMPLETE — 열린 PR의 미구현을 ANUS Free Auto 2개에 위임하라는 요청의 대상 #479를 [PR510](https://github.com/6Soo/cost/pull/510)으로 구현·병합·배포했다. [수락9개·검사·한계](specs/card-upload-coverage-implementation-20261102.md). 원명세 #479도 병합됐다. 당시 #477은 이미 구현된 UI 변경이고 이후 #484는 이번 실행 범위가 아니다.
- 기존 업로드의 파일별 결과에서 조회 기준·기간·관리 시작일을 확인하고, 원본/카드 맥락과 연결한 조회 확인·미확인·재확인 구간을 표시한다. 거래 min/max 역산·과거 소급·끝4만 같은 파일 합치기를 금지하며 제한/부분/파싱/조회조건 충돌은 사용자 확인으로 승격하지 않는다. 기존 비동기 업로드·원행/수동/중복/환불/OTA 보호를 유지하고 기존 변경 로그만 사용해 스키마 변경이 없다.
- 최신 통합52 passed/7 subtests, 인접보호62 passed. 기존 업로드 UI fixture1 timeout은 변경 전699eb8ed의 page()로 동일 재현했으며 통과에 포함하지 않는다. ego 합성320/390/1440px 넘침0·44px·파일별 저장·CSRF·HTML 삽입0, 실제 signed HTTP의0건 업로드/소유자 확인/조회 PASS. 전체 회귀·실기기·실제 고객 업로드는 미실행이다.
- 운영 `a7aa8c7ff23af9574ccbf42301803687b788d64d`, 직전 검증 `699eb8ed6b2c796b1da7841e4605db7c0ef38fc2`. 검사/병합 트리 동일·1,282blobs 불일치0·task/processSHA·단일loopback8751·health/ready200·신규/기존 보호API401/403·금융보호13표 내용/스키마 불변 PASS. task 인수/SourceRefresh 상태와 이전 검증 릴리스/task XML 복구점 보존, 코드 전용이라 새 전체DB 백업/복원은 반복하지 않았다.
- 호스트venv 격리 합성의0건 증빙·공백·멱등·비변경 PASS. 인증ego 운영/import의 카드 업로드 탭/조회기간API200·390/1440px 넘침0·버튼44px 수락, 조회확인0/재확인0으로 과거 자동소급 없음 확인. TaskSpace19/20 정상 종료. 실제 금융/분류/여행/환불/Google/원본/스키마 쓰기0.
- 근거 `C:/AX/cost/.local-archive/card-upload-coverage-final-20261102/`의 checkpoint·browser-evidence·live-browser·deployed-smoke·review/release-audit·protection-before/after·deploy-evidence 및 호스트 동일SHA 감사 기록. 사용자·병행 변경·stash 보존. 요청 미결/차단0·다음 기능 명령 없음. 결과 문서 후속에는 재검사·재배포·서버 재시작을 하지 않는다.

## 2026-11-02 자동분류 성능 최적화·Python/Rust 실측 완료

- COMPLETE — 최신 인계·PR486 기반 성능 최적화 요청. [PR507](https://github.com/6Soo/cost/pull/507), 고정 운영 `699eb8ed6b2c796b1da7841e4605db7c0ef38fc2`, 이전 검증 `c0d45b46b10726ea9ce660ba92c62f79e3e998f5`. [측정·선택·한계 정본](specs/expense-performance-20261102.md).
- 계획 안에서 검증한 여행 기간을 재사용해 반복 정규화를 제거했다. 요청 간 캐시는 없으며 수동 교정·원본·중복·환불·OTA·최신 여행 권한을 보존한다. PR498 SQL/환불 개선은 재사용하고 중복 구현하지 않았다.
- 운영 읽기 전용 동일 입력 6,895행/유효64여행·Google 잔액 조건의 5회 중앙값: 기존 Python 2.612초 → 개선 Python 1.046초(59.9% 단축), Rust 혼합 0.998초. Rust 변환·호출 포함 후보 선택은 더 느렸고 전체 시간 이득도 조건별 일관되지 않아 Python 채택. 등록66여행 조건은 3.258→1.206초, Rust1.266초; 합성2,000행/70여행은 2.103→1.037초, Rust1.280초. 전체 결과/digest 동일·읽기 쓰기0.
- 메모리 약97MiB·조회13회는 개선되지 않았다. 런타임2모듈은755→759행/AST분기141→144로 소폭 증가했다. Rust는 실제 C ABI 구현·250난수 검증을 했으나 운영 DLL/도구체인·신규 의존성은 도입하지 않았다. 실업로드/적용·동시성/장기메모리/HTTP 개선율은 미측정이며 프로파일·합성·HTTP 수치를 합산하지 않는다.
- 표적79·금융/수동/원본/중복/환불 보호109 passed; 최신 UI통합37 passed는 중복 포함. 변경 후 재검증이 필요한 코드 차이는 없고 최종 병합 차이는 문서뿐이다. 전체 회귀는 국소 계산 재사용 변경으로 미실행. 배포1,275blobs 일치·task/processSHA·단일loopback·health/ready200·보호401/403·금융13표 내용/스키마 불변 PASS. 호스트venv 격리 합성80행/8여행 plan/render무쓰기·인증ego/import4탭200/넘침0 수락, TaskSpace16 종료.
- 근거 `.local-archive/expense-performance-20261102/` 비교JSON·검사XML·review/release-audit/deploy-evidence·deployed-smoke·browser-after. 이전 검증 릴리스/task XML 보존, 코드 전용이라 새 전체DB백업/복원은 반복하지 않았다. 운영 분류/여행/금융/환불/Google/원본/스키마 쓰기0. host/gate 작성권 해제 및 후속coverage 담당 통지. 이 요청 미결/차단0·다음 기능 명령 없음. 문서 후속은 재검사·재배포·재시작하지 않는다.

## 2026-11-02 지출 정리 가로 탭·전체 UI/UX 개선 완료

- COMPLETE — 사용자 “해당 메뉴들을 가로로 배치하면 하위메뉴로 두지 않아도될거같은데. 지출정리 페이지의 uiux전체를 개선해”. [PR #504](https://github.com/6Soo/cost/pull/504), 구현 `8feee6d9bde29d91b383bda62033072d282df84c`, 병합·고정 운영 `ec2a37ab4c2b9a6d9e41a23de64e2b09869d0870`, 이전 검증 `959c139c850b9f86d570cca2b7cc7d2842737db2`.
- 카드 자료 관리의 중첩 메뉴를 정리할 지출·저장된 자료·카드 업로드·분류 규칙의 최상위 가로 탭으로 전환했다. 상태 필터·PC 두 열/모바일 한 열 카드·파일 목록·업로드 영역·규칙 폼을 개선하고, 키보드 방향키/Home/End·선택 URL·새로고침·뒤로가기·편집값 유지를 지원한다. 업로드에서는 이전 파일 거래를 숨기며 재개 오류와 현재 업로드 결과를 표시한다. 기존 금융·수동·환불·업로드·CSRF 처리기를 재사용한다.
- 검증: 표적125 passed/기존3 failed는 변경 전 동일 재현, 보호39 passed, 최종 인접11 passed(중복 포함). ego-browser 합성320/390/768/1440px×4탭 가로배치·넘침0, 밝음/어두움·키보드/URL·업로드 재개·편집값 유지 수락. 추가375px·가로 화면·큰 글자 넘침0. 로그인된 운영 화면 네 탭 및390px 가로배치·넘침0 수락, TaskSpace14 정상 종료. 전체 회귀·실기기·실제 파일 업로드는 국소 화면 변경으로 미실행이다.
- 배포1,268 blobs 불일치0·검사/병합 tree 동일·task/process 고정SHA·단일loopback listener·health/ready200·보호API401/403·금융보호13표 전후 불변 PASS. 이전 검증 릴리스/task XML 복구점을 보존했으며 코드 전용으로 새 전체DB백업/복원은 반복하지 않았다. 실제 금융/분류/여행/환불/Google/원본/스키마 쓰기0.
- 근거 `.local-archive/expense-ux-20261102/`의 targeted/baseline/protection/final-adjacent XML·browser-results/browser-adjacent·live.json·review/release-audit/deploy-evidence/checkpoint. 사용자·병행 변경을 보존하고 별도index로 본 변경만 커밋했다. 요청 미결/차단0·다음 기능 명령 없음. 문서 후속만으로 재검사·재배포·재시작하지 않는다.

## 2026-11-02 웹 텍스트 액션 버튼 전역 정리 완료

- COMPLETE — [조사·판단·검증 범위](specs/action-buttons-audit-20261102.md). 중복 카드 검색 진입점 제거, 카드 자료 관리 제목 정리, 필요한 액션의 아이콘·테두리·focus·모바일44px·비동기 갱신 공통화. 데이터 링크·테마 아이콘·핸들러·권한 유지. 복합 메뉴 이중 테두리·보험행 높이 회귀 보정.
- PR493·495·497·503, 최종 검증/운영 `959c139c850b9f86d570cca2b7cc7d2842737db2`, main 병합 `05755753b4a2fcd81447e91dacd10d594f66b2dc`. 직전3b72d0e의 기업검색·업로드·PR498 읽기 개선 보존. 정확한 후보36 passed/기존실패1 deselected, 보험행 별도25 passed. 기존실패는 변경 전 재현.
- 기존 주요9화면×1440/390/320px×라이트/다크의 넘침/대상누락0. 최종보정 후 지출정리3폭의 아이콘·모바일44px·키보드·중복프레임0, 실제보험패널2폭의border0/margin0·아이콘·행공통장식0 PASS. 기존 출력화면 `/export` GET 지연으로 실제 화면 수락은 제외하며 소스조사만 완료. 전체 회귀·실기기 미실행.
- 1,263 Git blobs 일치·task/processSHA·단일loopback·health/ready200·보호401/403·금융13표 불변 PASS. 분류/배정/Google/원본/스키마 쓰기0. 근거 `.local-archive/button-ux-20261102/`의 source/live감사·polish-targeted.xml·polish-evidence·polish-live.json. TaskSpace17 정상finish, host/gate작성권 해제. 문서 후속은 재배포/재시작하지 않는다.

## 2026-11-02 카드 전체 내역 기업카드 검색 누락 수정 완료

- COMPLETE — 사용자 “처리가 됐는데 왜 기업카드 내역이 조회안되지?” 및 카드 전체 내역 화면이라는 답변. [PR #500](https://github.com/6Soo/cost/pull/500), 구현 `b89647cd8847d5e020f4dbb026568555b7ce4d09`, 운영 `3b72d0e541f271241ffaa647862f132699a35a8b`, 이전 검증 `114af50de6f1a28f19186d9b3cc35c89a92c1be4`.
- 원인 재현: 기업카드218행이 저장돼 있으나 기존 검색의 카드사명 누락으로 `기업`은 국민카드의 가맹점 일치1행만 조회됐다. 개별 카드 선택은 정상이며8972는145행이다. 조회 조건에 issuer/유효한 마스킹 끝4자리와 기업카드·기업은행·IBK 별칭을 추가했다. 가맹점 등 기존 문자/금액 검색은 유지하고 카드/기간/미배정과 교집합을 취한다. 화면 검색 안내도 갱신했다. 원본/금융/분류/여행/환불/Google 쓰기0.
- 검증66 passed/기존2 failed는 변경 전114af50d에서도 동일 재현 후 제외했다(미배정 목적지 판정·삭제된 안내문 계약). 통과에 포함하지 않는다. 발급사/끝4·별칭·무날짜 취소·월/연 합계·페이지 커서·SQL 삽입 문자·잘못 저장된PAN 끝자리 검색 차단·원본 불변 포함. 운영 DB 읽기 전용 비교에서 기업카드218행/3페이지·중복/누락0·월 합계 일치. 전체 회귀는 국소 읽기 조건 변경으로 미실행이다.
- 인증ego 운영 실제폼 조회: `기업카드` 검색218건·첫100행·기업4971/4985/8972만 표시·다음cursor 검색어 유지·390px 가로넘침0 수락. TaskSpace12 정상 종료. 기업 일반 검색은 기존 가맹점 문자 일치도 유지하므로 기업카드 전체를 보려면 `기업카드`/`IBK`로 검색한다.
- 배포1,263 blobs 불일치0·검사후보/배포코드동일(차이는기존결과문서뿐)·task/process 고정SHA·단일loopback listener·health/ready200·검색영향경로/보호API401/403·금융보호13표전후불변 PASS. 이전114af50d의성능·UI·업로드async를보존했다. 코드전용이라이전검증릴리스/task XML 복구점을보존하고새전체DB백업/복원은반복하지않았다. 실제자료재업로드·금융재처리·Google쓰기는하지않았다.
- 근거 `.local-archive/ibk-query-20261102/`의 state.json·targeted.xml·baseline-existing.xml·actual-query.json·live.json·review/release-audit/deploy-evidence/checkpoint. 사용자/타작업변경보존. 서버/gate쓰기종료를후속UI·최적화담당자에게통지했다. 이 요청미결/차단0·다음기능명령없음. 문서후속만으로검사/재배포/재시작하지않는다.

## 2026-11-02 지출 정리·환불 읽기 성능 최적화 완료

- COMPLETE — 사용자 “코드 살펴보면서 발견된 부분들을 최적화, 가능하면 Rust”. [성능·Rust 판단·재현 명세](specs/cleanup-read-performance-20261102.md), [PR #498](https://github.com/6Soo/cost/pull/498). 실행 병목2개인 취소 상관 OR 전체조회와 환불별 전체 구매 순회를 SQLite 문장별 IN집합·정확 발급사/끝4/금액 후보색인으로 교체했다. 원본/유일성/수동/중복/환불·NULL 의미를 유지한다. Rust는 주 병목이 네이티브SQL과탐색횟수이고 도구체인도없어 미도입했다.
- 동일 입력·전체결과·워밍후5회 중앙값: 운영 읽기 묶음2.235→0.514초(4.35배), 환불0.625→0.248초(2.52배),486링크전체·목록/건수동일·쓰기0. 합성5,000구매/500취소는38.80배/16.47배이며 운영/HTTP개선율과구별한다. 검사144+40+47 passed, 후속NULL4는40과중복이다. 전체회귀/실기기는국소읽기변경으로미실행.
- 구현 `c82d86b7`·검사 `2e3a6935`, main병합/고정운영 `114af50de6f1a28f19186d9b3cc35c89a92c1be4`, 이전검증 `e95a82392be716f488e1175d8ed621c2ac6cd8ec`. UI단일작성자handoff후직렬배포했고이전UI·비동기업로드코드를보존했다.1,262blobs불일치0·task/processSHA·단일loopback8751·health/ready200·보호API401/403·금융13표내용/스키마불변PASS. 이전검증릴리스/task복구점보존, 새전체DB백업/복원반복없음. 금융/분류/여행/장부/Google/원본/스키마쓰기0.
- 인증ego/import수락:총1·GAMSGO제외·원결제미연결아고다취소유지PASS,TaskSpace13종료. 준비중외부502는앞선UI전환중관측이며본배포후정상수락과구별한다. 근거 `.local-archive/read-performance-20261102/`의 profile/real-differential/synthetic-benchmark·검사XML·review/release-audit/deploy-evidence·browser-final·protection-before/after. 호스트작성권을후속담당자에게해제통지했고이후문서만처리한다. 이요청미결/차단0·다음기능명령없음. 사용자/타작성자변경보존·문서후속재배포없음.

## 2026-11-02 보험 연결 행 높이·과도한 버튼 테두리 회귀 수정 완료

- COMPLETE — 사용자 첨부의 연결 행만 높아지는 문제를 재현했다. 직전 국내여행 보험 대상 아님 PR488은 해당 연결 버튼을 변경하지 않았다. 이후 공통 버튼 장식 PR493이 `.participant-link-details > summary`에도 class·아이콘·상하8px margin을 부여해 연결60.4px/미연결·환불45px로 커진 것이 원인이다. 해당 summary만 공통 장식에서 제외하고 기존 chevron·focus·44px 터치 영역을 보존한다. PR495 복합 버튼 보호도 함께 유지한다.
- [PR #497](https://github.com/6Soo/cost/pull/497), 구현 `455384c0c07493880906a68ce5155e749922fe6b`, 병합·운영 `e95a82392be716f488e1175d8ed621c2ac6cd8ec`. 공통 버튼 담당65f011e가 직전 검증 운영 `61188520fe1758a18230bcdbf6563ee6cc70a1c0`에서 PR495+497을 통합해 단일 배포했다. 동시 host/gate 전환 없음.
- 검증: 실제 panel.render+site_shell 합성에서 초기·비동기 연결/미연결/환불 행을 비교,320/390/1440px×밝음/어두움6건 모두 같은 높이(PC45px/모바일 전체행93px),추가 margin0·가로 넘침0·키보드 펼침/접힘 PASS. Python 관련25 passed. 같은 조건의 브라우저 회귀 테스트를 추가했으며 본 작업의 실제 브라우저 실행은 ego-browser다. 인증 운영 화면의 연결 행과 미연결/환불 행 높이·장식 제거를 live-final.json에서 확인했다.
- 운영 SHA·health/ready·보호API 및 금융 보호13표 내용/스키마 불변은 host 동일SHA deploy-evidence와 배포 담당 근거를 사용한다. 금융/참가자 연결/Google/원본/스키마 쓰기0. 전체 회귀·실기기는 국소 장식 수정으로 미실행. 기존 미커밋 소스 보존,격리 archive/별도 index 사용.
- 근거 `.local-archive/insurance-row-regression-20261102/`의 browser-result.json·targeted.xml·live-final.json·checkpoint.json 및 호스트 동일SHA 배포 기록. 요청 미결/차단0·다음 기능 명령 없음. 문서 전용 후속 재배포/재시작 없음.

## 2026-11-02 카드 업로드 지연·실패 표시 수정 완료

- COMPLETE — 사용자 첨부 XLSX 처리 지연·연결 실패 개선. [PR #494](https://github.com/6Soo/cost/pull/494), 구현 `25d1bca9`·통합 검증 `e9ec14bd`, 운영 `61188520fe1758a18230bcdbf6563ee6cc70a1c0`, 이전 검증 `697eb8f064e1bccccc07276d943958260c68f06f`. [실행 계약](specs/card-upload-latency-20261102.md).
- UI 요청은 검증·원본 접수·내구 큐 저장 직후202를 반환하고 기존 분류→OTA 갱신→기록→전수 검증을 서버에서 직렬 실행한다. 소유자 전용 상태 조회는 금융DB/작성자 잠금을 사용하지 않는다. 진행 단계·경과 시간·연결 재시도·새로고침 재개·저장된 파일 링크를 제공하고, 저장 후 오류를 업로드 실패로 세지 않는다. 처리 중 새로고침에는 DB 없는 UI shell을 제공한다. 원문·수동 결정·중복·환불 보호 및 기존 동기 API를 유지하며 불필요한 중간 화면 조립2회를 제거했다. 총 분류/OTA 처리 시간이나 운영 개선 배수는 미측정이다.
- 검증: 최신 통합 트리 표적/보호82 passed. 느린 분류를 중지한 채202·상태GET·새로고침HTML 응답, 같은 파일 재접수·OTA 갱신 전후 기록·부분환불·수동 이동·내구 복구·전수 대조 포함. 별도 인접33·HTTP/UI5 passed는 중복을 포함하므로 합산하지 않는다. ego-browser 합성 새로고침/완료/접수 후 오류/상세 링크/390px 넘침0 수락. 전체 회귀·운영 실파일 재업로드는 미실행이며 금융 재처리를 하지 않았다.
- 첨부 원본은 읽기 전용 조사에서44행이 이미 저장되어 있었고43행 분류/내부 기록 완료·취소1행needs_review임을 확인했다. 특정 프록시 타임아웃 로그는 확보하지 않았다. 취소행 보호 유지, 재업로드·실제은행환급·Google 반영을 수행/확정하지 않았다. 인증 운영 화면에서 같은batch의44행과 새 async 코드·상태복구 함수 정상 표시 수락. TaskSpace8 정상 종료.
- 배포1,259 blobs 불일치0·검사/배포 트리 동일·task/process 고정SHA·단일loopback listener·health/ready200·새 상태API/화면401 및 기존보호API401/403·금융보호13표 전후 불변 PASS. 기존 task 인수와 SourceRefresh 상태 보존. 코드 전용으로 이전 검증 릴리스/task XML 복구점을 보존했으며 새 전체DB백업/복원은 반복하지 않았다. 실제 금융/분류/여행/Google/원본/스키마 쓰기0.
- 근거 `.local-archive/upload-speed-20261102/`의 merged-targeted.xml·final-adjacent.xml·saved-upload-state.json·live.json·review/release-audit/deploy-evidence/checkpoint. 사용자/타 작업 변경 보존. 후속UI 배포 담당자에게61188520 보존과 서버/게이트 쓰기 종료를 전달했다. 이 요청 미결·차단0·다음명령 없음. 문서 후속으로 재검사·재배포·재시작하지 않는다.

## 2026-11-02 분류 완료 거래의 반복 검토 요구 수정 완료

- COMPLETE — 사용자 첨부 GAMSGO 반복 검토 원인 수정. 구버전 `complete-card-inference-v1` 문구만 완료로 인정하던 지출 정리 SQL에 현재 여행 권한으로 검증한 저장 분류 완료 조건을 추가했다. 낮은 신뢰도/분류 출처와 무관하게 여행·항목이 완료되면 목록·필터·건수에서 재확인을 요구하지 않는다. 내부 장부 미기록은 분류 미완료로 간주하지 않는다. 원본 오류·보류·환불 후보·원결제 미연결은 보존한다. 권한이 상실된 여행은 다시 표시한다.
- PR #489·#491 정상 main 병합. 최종 구현·고정 운영 `859c3af426451ef2284bf436dcce9c3ccf9fe74b`, 병합 `b504526d`, 이전 검증 `b7c60927dddf110fe616699a07cf65ea5e8cdcea`. 검토 중 섞인 독립 제목 두 줄은 후속에서 기존 main 문구로 복구했고 workspace의 다른 작성자 변경은 보존했다. 과거 기기록 여행 전체를 매번 검증하지 않도록 미기록 후보만 검증한다.
- 검증: 최종 후보 지출 목록/필터/분류 완료·원본/수동보류·환불/원자 기록/유지보수 77 passed. 별도 소스 문구 계약 1 failed는 기준 main에서 동일 재현; 통과에 포함하지 않는다. 운영 DB 읽기 전용 대조 쓰기0. 전체 회귀·실기기는 국소 읽기 판정 변경으로 미실행이다.
- 실제 ego-browser 인증 GET 수락: 처리필요 2→1·분류배정0·결제환불1, GAMSGO 제외·원결제 미연결 아고다 취소 보존. 해당 취소의 동일 카드 원결제는 현재 수집 자료에서 찾지 못했으며 원결제 원본/참조가 필요하다. 가맹점명·소액만으로 링크나 환급 완료를 만들지 않았다. TaskSpace7 정상 종료.
- 배포 1,255 blobs 불일치0·검사 후보와 동일·task/process 고정SHA·단일loopback8751·health/ready200·보호API401/403·금융보호13표 내용/스키마 불변 PASS. 코드 전용이므로 이전 검증 릴리스/task 복구점 보존, 새 전체DB백업·복원은 반복하지 않았다. 금융/분류/여행/장부/Google/원본/스키마 쓰기0.
- 근거 `.local-archive/cleanup-root-20261102/`의 verified-final.xml·baseline-protection.xml·actual-readonly.json·browser-final.json·review/release-audit/deploy-evidence·protection-before/after. 요청된 코드 수정/배포 미결0·다음 기능 명령 없음. 아고다 미연결은 원결제 자료 의존이며 자동 연결/완료 처리하지 않는다. 문서 후속으로 재배포하지 않는다.

## 2026-11-02 국내여행 보험 대상 아님 UI 완료

- COMPLETE — 사용자 “국내여행은 보험을 가입하지 않기 때문에 보험명단이 없다” 및 제안 실행 승인. 기존 `trip_region()`의 destination 정확 일치 판별에서 KR인 실제 여행만 국내여행 배지·중립적인 “국내여행 · 보험 가입 대상 아님” 안내를 표시한다. 보험 명단 열/대조 패널/후보 비교를 숨기고 lazy 대조 요청을 생략한다. 해외·지역 미상은 기존 UI 유지, 지역명 목록 확대·여행/참가자/수동 연결 변경 없음.
- [PR #488](https://github.com/6Soo/cost/pull/488), 구현 `d6a4cfaeb7dc4eefcaaac991f8d55c0e5eb25a95`, 운영 `b7c60927dddf110fe616699a07cf65ea5e8cdcea`, 이전 검증 `752eff0c667ddd8e4e661ec6b069d2d8c49e85ad`. 관련 묶음93 passed/기존 코드 문자열 검사1 failed/2 deselected, 해당 검사를 실제 HTML 헤더 검사로 변경 후 개별1 passed. 신규 국내/해외/미상·삭제/중복 여행·소유자/열람 권한·조회 생략·수입/원본 불변 포함. 전체 회귀·실기기는 국소 표시 변경으로 미실행.
- ego-browser 합성3분류×320/390/1440px9건 PASS. 인증 운영 통영·야마가타 각각390/1440px4건 PASS: 통영은 배지/안내·보험 열/패널/후보 없음·자동 보험 요청0, 야마가타는 기존 보험 열/패널/후보 유지·자동 보험 요청1. 수입 표와 합계 유지·문서 가로 넘침0 확인. 합성 모바일 스크린샷의 배치도 확인했으며 운영 모바일 캡처에는 기존 탐색 서랍이 열려 있었으므로 전체 화면의 가림 없음까지 통과로 주장하지 않는다. 브라우저 작업 공간은 정상 종료.
- 배포1,254 blobs 불일치0·검사본/병합본 동일 tree·task/process 고정 SHA·단일loopback8751·health/ready200·보호API401/403·새 영향패널 비로그인401·금융보호13표 내용/스키마 불변 PASS. 기존 SourceRefresh 상태·전체 task 인수 보존. 코드 전용으로 기존 검증 릴리스·task XML 복구 수단을 보존하고 별도 전체DB백업/복원은 반복하지 않았다. 금융/분류/여행/참가자/Google/원본/스키마 쓰기0.
- 근거 `.local-archive/domestic-insurance-20261102/`의 targeted.xml·updated-contract.xml·browser-synthetic.json·review.json·release-audit.json·deploy-evidence.json·live-final.json·checkpoint.json. 공유 작업 트리의 기존 소스 변경을 보존하고 격리 archive 후보/독립 index로 커밋했다. 미결/차단0·다음 기능 명령 없음. 문서 후속 재배포/재시작 없음.

## 2026-11-02 PR458 후속 복잡성·기존20실패 정비 완료

- COMPLETE — 현재 사용자 승인 기능군을 [PR483](https://github.com/6Soo/cost/pull/483)·[PR486](https://github.com/6Soo/cost/pull/486)으로 통합·병합·배포했다. 원 구현 `c5ee972d`, 최종 검사 `d750ee7e`, 운영 `752eff0c667ddd8e4e661ec6b069d2d8c49e85ad`, 이전 검증 `46e00f8d4bcd5ca0c3f7d3cc7861eae6bfb45acb`. 검사/병합 트리 차이0. [승인 범위](specs/python-refactor-followup-20261102.md)·[비교/20건별 원인/한계](specs/python-refactor-followup-results-20261102.md).
- 자동분류의 보호·이력 복원·새 추론 책임을 분리하고 지출정리 중복 집계/취소 조회·행별 근거 조회/렌더 호출을 줄였다. OTA13·화면6·안내1은 현재 계약으로 검증했으며 HTML 충돌 입력 손실 실제 결함도 수정했다. 전체 계획/digest·HTML 동등성 및 조회 무쓰기 유지. 최신 상태/AI 출처·수동/원본/중복/환불/권한/원자성 보호를 보존했다.
- 같은 기능 기준 f1e6453d→최종: 실행83,809행 동일·분기21,674→21,670·100행 초과102→101·동일본문중복2→2·실행 import 동일. plan186/140→63/29행/분기, cleanup338/132→304/130. 전체 코드량·중복 사본·의존성 감소는 달성하지 않았다. 합성 SELECT58→35, 9회 순서교대148.30→133.46ms; 자동분류64.44→64.12ms로 사실상 동일. 이전 느린 표본과 운영 전체 성능 미측정을 결과 문서에 구분했다. Rust 도입 없음.
- 표적348 passed·ego-browser 합성 페이지/빈필터/390px/충돌 입력 보존·XSS PASS. 인접 권한/거절15 passed·3 failed/26 subtests는 기준 f1e6453d 동일 재현의 과거 drawer/내부ID 기대이며 기존20건/통과에 합산하지 않는다. 전체회귀·실기기·새 인증 운영UI 수락은 미실행. 배포본 호스트venv의 격리 합성 자동분류/cleanup/조회무쓰기 PASS.
- 운영1,252 blobs 불일치0·고정 task/processSHA·단일loopback8751·health/ready200·보호401/403·금융보호13표 내용/스키마 불변. 전체task 인수/ParticipantSyncConfig·SourceRefresh 상태 보존. 코드전용으로 이전 검증 릴리스/task XML을 복구점으로 남겼으며 새 전체DB백업/복원은 반복하지 않았다. 앞선55e304ad 배포는 중단돼 성공으로 기록하지 않으며 최종752eff0c에 통합했다. 금융/Google/여행/원본 쓰기·재처리·마이그레이션0.
- 근거 `.local-archive/refactor-followup-20261102/`의 verified-final/verified-structure·refusal-baseline·resume-browser-final·review/release-audit·protection-before/after·deploy-evidence·released-smoke 및 호스트 동일SHA 기록. 현재 요청의 필수 미결/차단0, 다음 기능 명령 없음. 추가 인접3실패는 보고된 기준 문제로 남기고 새 전체개발 큐를 만들지 않는다. 사용자/타작업 미커밋 변경 보존. 문서 후속으로 재배포/재시작하지 않는다.

## 2026-11-02 장부 숙박 이용일 표시 누락 수정 완료

- COMPLETE — 사용자 “왜 이용일 확인 필요로 되어있지? 조사해서 수정”. 기존 카드 장부 행의 빈 이용기간만 읽고 현재 OTA 검증 기간을 표시하지 않던 경로를 읽기 전용 투영으로 수정했다. [PR #482](https://github.com/6Soo/cost/pull/482), 구현·운영 `46e00f8d4bcd5ca0c3f7d3cc7861eae6bfb45acb`, 병합 `f1e6453dfa48edd8cdd02fbc4e01f1a79300f15b`, 이전 검증 `ce61fea6ca09546c838602c530308850b9cade30`. 병합 SHA에는 독립 PR481의 분류 변경이 함께 있어, main에 포함된 이번 검증 구현 커밋만 고정 배포했다.
- 검증: 표적42 passed·OTA 투영/동일 세대 신선도 보호12 passed, 실행 파일은 검사 후보와 모두 동일, Git diff check PASS. 저장 기간·수동 빈값·예약 충돌·stale·취소/환불·원본/중복 보호 유지. 전체 회귀·실기기는 국소 표시 변경으로 미실행.
- 인증 ego-browser 운영 수락: 재시작 뒤 OTA 대사 갱신 중에는 미확인 표시 유지, 정상 갱신 완료 뒤 실제 야마가타 장부의 문제4행이 각각6/26~28·7/5~7(2행)·6/28~29로 표시됨을 확인했다. 카드 날짜는 그대로다. 저장 대조 자료의4행 투영과 실제 신선한 운영 화면 수락을 구별한다. 개별 기간 근거가 없는 행은 날짜를 창작하지 않는다.
- 배포1,243 blobs 불일치0·task/process 고정 SHA·단일loopback8751·health/ready200·보호API401/403·금융보호13표 내용/스키마 불변 PASS. 코드 전용이므로 별도 전체DB백업/복원 대신 이전 검증 릴리스·task XML 복구점을 보존했다. 분류/여행/장부/Google/원본/스키마 쓰기0.
- 근거 `.local-archive/stay-date-20261102/`의 targeted.xml·protection-tests.xml·actual-projection.json·review.json·release-audit.json·deploy-evidence.json·live-final.json·resume-checkpoint.json. 사용자/타 작업 미커밋 변경 보존. 요청 미결/차단0·다음 기능 명령 없음. 문서 후속만으로 재배포/재시작하지 않는다.

## 2026-11-02 원본 상세 탭 이동·수동 Google 동기화 완료

- COMPLETE — 사용자 요청 2개를 [PR #478](https://github.com/6Soo/cost/pull/478)로 구현·병합·배포했다. 구현 `178b5b9558e0bf9f449ccfb1b6be8dae7d32d39c`, 운영 `ce61fea6ca09546c838602c530308850b9cade30`, 이전 검증 `6bfeee7b34d6eab551394b73d87bedfa29000bc1`. 원본 상세는 현재 여행 접근 권한·선택 사본·정확한 탭 제목을 확인하고 Google 읽기 전용 탭 색인에서 실제 gid를 찾아 새 창으로 연다. 장부 관리의 제거된 과거 페이지는 재활성화하지 않는다.
- 동기화는 실제 버튼이며 소유자/CSRF 확인 후 백그라운드 읽기 작업과 상태 조회를 연결했다. 기존 스케줄러와 같은 OS 잠금·실패 backoff·원자 세대 저장·이전 세대 보존을 사용한다. 실행 중 중복 클릭을 막고 진행/실패/재시도 표시, 성공 후 새로고침을 제공한다. 현재 운영 GoogleAuthority task의 public 읽기 모드와 일치하며 ADC 설정 지원도 유지한다. Google 최종 장부·금융 DB·분류·여행 교정·원본·스키마 쓰기는 없다. 승인된 실제 동기화로 로컬 Google 읽기 캐시만 갱신했다.
- 검증: 정확한 후보 트리 표적105 passed/기존 화면 문구 검사1 deselected, 스케줄/ADC 보호47 passed, JS 구문 PASS. 탐색 최초106 passed와 기존 문구 기대4 subtests 실패를 혼동하지 않는다. 기준 `a0f5d1edbe15467f5a530755bfbd07e3664187ca`에서도 같은4 실패 재현. 실제 HTTP worker/CSRF/완료 후 reload/실패 후 재시도/원본302 및 모바일390px 검사 포함. 전체 회귀·실기기는 범위가 제한되어 미실행이다.
- 배포:1241 blobs 불일치0, task/process 고정SHA·단일loopback8751·health/ready200·기존 보호API401·새 Google action API403, 금융보호13표 내용/스키마 불변 PASS. 첫 시도는 새API의 올바른 비로그인403을 점검 스크립트가401로 기대해 자동 이전 릴리스 복구; 점검 기대값만 수정 후 동일 코드 재배포 성공. 별도 전체DB백업/복원은 반복하지 않고 기존 검증 릴리스·task XML을 보존했다.
- 로그인된 ego-browser 운영 수락: 원본 버튼이 선택된 스프레드시트의 실제 `gid=1091731289`로 이동, 실제 동기화 클릭→진행/중복방지→성공 새로고침→시각03:00→03:58, 연결3개 소스 모두status=ok 확인. 재배포 전 화면의 이전CSRF는 거부됐고 최신 화면을 열어 성공한 근거를 구별한다. 금융 보호13표는 실제 동기화 뒤에도 불변이다. TaskSpace10은 결과 화면을 유지하고 종료했다.
- 근거 `.local-archive/ledger-sync-20261102/`의 checkpoint/candidate.xml/baseline.xml/protection.xml/review/release-audit/deploy-evidence/protection-before·after/browser-final.json 및 호스트 동일SHA 감사. 사용자/다른 작업의 미커밋 변경은 보존했다. 요청 미결·차단0, 다음 기능 명령 없음. 문서 후속만으로 재배포/재시작하지 않는다.

## 2026-11-02 보험 명단 행 간격·모바일 수입 표 조정 완료

- COMPLETE — 첨부 화면의 보험 명단 행 높이 차이를 CSS로 교정했다. 연결/미연결/환불완료 행은 PC45px, 모바일57px로 통일하고 펼침 화살표·hover·focus를 정리했다. 모바일 table/section의 기본 표 배치 때문에 각 수입 행이 전체 너비의 일부로 축소되던 문제와 합계 정렬도 수정했다. [PR #475](https://github.com/6Soo/cost/pull/475), 구현 `6f8b9a61`, 운영 SHA `6bfeee7b34d6eab551394b73d87bedfa29000bc1`, 이전 검증 `e448f34851cfaf122e4646585ea0a4c93589e37b`.
- 검증: 병합 트리와 동일한 후보의 수입/보험 연결 표적 50 passed/브라우저3 deselected. ego-browser 인증 운영 GET에서 PC1440·모바일390/320px의 동일 높이·행/표 너비 일치·합계 잘림0·가로 넘침0·마우스/키보드 펼침 PASS. TaskSpace8 정상 종료. 전체 회귀·실기기는 국소 CSS 변경으로 미실행. 분류/금융/수입/참가자/Google/원본/스키마 쓰기0.
- 배포: 1,237 Git blobs 불일치0·task/process 고정SHA·단일 loopback listener·health/ready200·보호5경로401·보호13표 내용/스키마 불변 PASS. 기존 task 인수/SourceRefresh 상태 보존. 코드 전용으로 새 전체DB백업/복원은 반복하지 않고 이전 검증 릴리스와 task XML 복구점을 보존했다. 근거 `.local-archive/insurance-density-20261102/`의 candidate-tests.xml·browser/live.json·release-audit/review/deploy-evidence 및 호스트 동일SHA 기록. 요청 미결/차단0·다음 명령 없음. 문서 후속은 재배포/재시작하지 않는다. 기존 사용자 미커밋 변경은 보존했다.

## 2026-11-02 기업·하나 다운로드 파일 업로드 오류 수정 완료

- COMPLETE — [PR #470](https://github.com/6Soo/cost/pull/470), 구현 `b289b96e`·보호 보완 `9efd2b08`, 고정 운영 SHA `e448f34851cfaf122e4646585ea0a4c93589e37b`. 기업 XLSX 비표준 스타일/잘못된 셀 범위, 하나 이용·해외 이용 XLS 헤더 인식 오류를 수정했다. 원본 바이트·원행·승인번호를 보존하고, 수수료/청구금액·부분취소를 해당 원문 열에서 읽는다. 없는 매입일은 공란이며 양쪽 명시 매입일·금액·가맹점·외화 충돌과 취소 다중성·수동 교정 보호를 유지한다.
- 검증: 병합 트리53 passed/14 deselected·권한/CSRF4 subtests. 실제 다운로드13개/1,254행 파싱·원본/원행 불변 PASS. 운영 DB의 격리 메모리 사본에서 기존6,851행·수동/장부/보류 불변, 정상 신규683·기존422·충돌149 보존·구매 앵커 중복0·재수신13개 멱등성을 확인했다. 충돌149건은 자동 해결하거나 운영 반영하지 않았다.
- ego-browser 합성3파일 업로드/파일별 상세 링크/HTTP200·동일파일 재수신 동일배치·PC/390px 넘침0, 인증 운영 업로드 화면 GET의 multiple·허용확장자·결과영역 PASS. 여행 자료 없는 합성 서버의 `분류 미완료`는 파싱 실패나 분류 완료로 보고하지 않는다. 실제 고객 파일의 운영 재업로드·분류/여행/장부/Google/원본/스키마 쓰기0. 전체 회귀/실기기는 미실행이다.
- 배포:1,237 blobs 불일치0·task/process 고정SHA·단일loopback·health/ready200·영향/보호4경로401·보호13표 내용/스키마 불변. 최초 전환은 다른 배포의 SHA 변경을 쓰기 전에 감지해 중단했고, 검증된 최신598bf14f를 복구 기준으로 재검사 후 전환했다. 기존 task 인수/SourceRefresh 상태 보존. 새전체DB백업/복원은 반복하지 않았으며 이전 검증 릴리스와 task XML을 보존했다. 근거 `C:/AX/cost/.local-archive/upload-format-20261102/`의 merged-targeted.xml·actual-after.json·actual-rehearsal.json·resume-browser-final.json·live-browser.json·review/release-audit/deploy-evidence 및 호스트 동일SHA 기록. 이 요청의 미결/차단0·다음명령 없음. 문서후속 재배포/재시작 없음.

## 2026-11-02 알펜루트 배정 표시 누락 교정 완료

- COMPLETE — 사용자 “왜 알펜루트로 배정안됐지?” 조사 결과 해당 10/24 거래는 이미 `1020_알펜루트`(10/20~24)의 현지경비로 자동 추론 배정됐고 내부 장부에는 미기록이었다. 지출 정리 카드가 저장된 여행·항목을 보여주지 않아 혼동을 일으켰다. 유효한 현재 여행과 항목을 카드 본문에 표시하며, 무효 여행·보류·금융 보호 판단은 유지한다. [PR #471](https://github.com/6Soo/cost/pull/471), 구현 `13c7a3ed`, 운영 SHA `598bf14f8bd0b70241c03e6a10968969a31b66a5`, 이전 검증 `13b02d22388383271db8f254cca2dfb6dbb30279`.
- 검증: 표적 35 passed/기존 문구 계약 실패 4건 deselected(기준 `9835a769` 동일 재현). 활성/무효 여행 표시·escaping·조회 무쓰기 포함. 병합 시 추가된 두 운영 문서 외 실행 코드는 검사본과 동일하다. 인증된 운영 화면에서 현재 여행·현지경비·장부 기록 가능 표시와 PC/모바일390px 넘침0을 확인했다. TaskSpace7 정상 종료. 전체 회귀·실기기는 국소 표시 변경으로 미실행이다.
- 배포: 1,234 Git blobs 불일치0·task/process 고정SHA·단일 loopback listener·health/ready200·영향/보호5경로401·보호13표 내용/스키마 불변 PASS. 기존 task 인수/SourceRefresh 상태 보존. 코드 전용으로 새 전체DB백업/복원은 반복하지 않고 이전 검증 릴리스와 task XML 복구점을 보존했다. 분류/여행/장부/Google/원본/스키마 쓰기0. 근거 `.local-archive/gamsgo-alpen-20261102/`의 baseline/targeted-final/candidate.xml·review/release-audit/deploy-evidence·browser-final.json 및 호스트 동일SHA 감사 기록. 이 질문과 표시 교정 미결/차단0·다음 명령 없음. 문서 후속은 재배포/재시작하지 않는다.

## 2026-11-02 OTA 근거 카드의 여행 복구 누락·출처 표시 수정 완료

- COMPLETE — [원인·수락 근거](specs/ota-missing-trip-completion-20261102.md). 업종만 분류되고 여행이 빈 정상 구매를 자동 작업자/기록 복구 SQL이 누락하던 경로를 공통 미완료 판정과 OTA 우선 복구로 수정했다. 구현 `2fcfafaf`, [PR #462](https://github.com/6Soo/cost/pull/462), 배포 `62bfa07b77e56716b141230f2bdfb4962cd91055`. 병합 릴리스60 passed, 기준 회귀2건 실패 재현, OTA/환불/권한11 passed 근거를 보존한다.
- 승인 단건은 신선한 Board 백업·별도 복원 동등성/무결성·사본 재실행0 후 자동처리 완료. `1015_오제 / 숙박비 / 9,906원` 내부기록1건, 원본/수동/기존 장부·금융 링크/다른 행/스키마 보존, Google 쓰기0. 이후 금융 보호용 decided를 수동 출처로 오인하던 표시도 구현 `9835a769`·[PR #466](https://github.com/6Soo/cost/pull/466)·운영 `13b02d22388383271db8f254cca2dfb6dbb30279`로 수정했다. 표시/읽기6 passed·보호13표 불변.
- 최종 task/process SHA·단일 loopback8751·health/ready200·OTA/카드 보호401 확인. 이전 인증 브라우저 GET의 여행/항목/기록완료/장부보기 수락과, 출처 수정 후 읽기 전용 운영 catalog의 `기록 완료 · 자동 추론`/추가 확인 불필요/내부기록1/남은후보0을 구별한다. 출처 수정 후 브라우저 재검사·전체 회귀·실기기는 미실행이다.
- 근거 `.local-archive/ota-trip-gap-20261102/`의 release/source-release-tests·backup-restore·activation-protection·source-label/deploy-evidence·source-live-projection·resume-runtime. 인계의8000번 미응답은 서비스 포트 확인이 아니었으며 현재13b02d22와 배포 근거가 일치해 재배포/재처리하지 않았다. 요청 미결/차단0·다음명령 없음. 문서 후속 재배포/재시작 없음. 다른 작업자의 미커밋 변경은 보존한다.

## 2026-11-02 항공권 예약 조회 오류·UIUX 개선 완료

- COMPLETE — 사용자 “문제수정 및 uiux개선”의 항공권 영역. [PR #465](https://github.com/6Soo/cost/pull/465), 구현 `cbc8e7a3`, 검증 배포 `5cf30d5c68ae626af9cf07d64aee425eb06467f7`. 선택 수동 여행 배정 테이블이 없는 정상 격리 저장소를 배정 없음으로 읽는다. 파일 누락·손상·부분 스키마는 계속 차단하며 GET 읽기 전용과 수동 배정 보호를 유지한다. 한국어 배정 상태, 예약 카드, 오류별 안내·재시도, 목록 갱신·페이지 이동, 상세 접힘과 긴 거래 설명 줄바꿈을 개선했다.
- 검증: 표적82 passed, 병합본 API/서명 권한26 passed, 원본 보호2 passed. 별도 실행82건 중 OTA catalog1건 실패는 단독 재검사1 passed로 구분한다. 합성 ego-browser의 목록/상세 재시도·generation 변경·빈 목록·페이지 이동·escaping, 320/390/1440px 두 테마·버튼44px·넘침0 근거를 보존했다. 실행 간 중복은 합산하지 않는다.
- 실제 인증 운영에서 세 여행 API200/빈 목록, 별도 예약이 있는 여행의 목록3건·확인 탑승객4명과 상세 여정·예약일 표시·접힘을 수락했다. PC1440/모바일390px 페이지/항공권 영역 넘침0·버튼44px 확인 후 기존 TaskSpace2를 정상 종료했다. 접힘 검사는 Chromium의 숨겨진 details 자식에 남는 레이아웃 크기 대신 실제 visibility로 확인했다. 전체 회귀·실기기 검사는 미실행이다.
- 배포: 1,233 blobs 일치·task/process 고정SHA·단일listener·health/ready200·영향/보호 API401·보호13표 불변 PASS. 직전 검증355a059b/task XML 복구점 보존, 코드 전용으로 새 전체DB 백업/복원은 반복하지 않았다. 후속 카드 표시 PR466의 실제 운영 `13b02d22388383271db8f254cca2dfb6dbb30279`에도 이번 수정이 포함됨을 ancestry·호스트 배포 근거·예약 실조회로 확인했다. 금융/분류/여행/Google/원본/스키마 쓰기0.
- 근거: `C:/AX/cost/.local-archive/flight-ux-20261102/`의 XML·browser.json·live-api.json·live-inventory.json·live-browser-final.json·review/deploy-evidence와 호스트 동일SHA 배포 기록. 원문/실명 캡처는 Git 제외 로컬에만 보존했다. 이 요청의 미결/차단0·다음 명령 없음. 병행 사용자 변경과 기존 workspace를 보존하며 문서 후속에는 재배포/재시작하지 않는다.

## 2026-11-02 첨부 카드8건 조사·취소 미배정 오표시 교정 완료

## 2026-11-02 수입 보험 명단 환불완료 표시 완료

- COMPLETE — 사용자 요청 두 항목 반영. [PR #464](https://github.com/6Soo/cost/pull/464), 구현 `0515370d`, 고정 운영 SHA `355a059ba5808151a8780409a09b06508427f2f3`, 이전 검증 `62bfa07b77e56716b141230f2bdfb4962cd91055`. 미연결의 `보험 미가입을 뜻하지 않음` 문구를 제거하고, 수입 행 총액이 0원 이하이면 보험 명단 열을 `환불완료`로 대체한다. 금액 미상은 환불완료로 추정하지 않는다. 최초 렌더·보험 비동기 로딩/성공/실패에서도 표시를 유지하며 기존 보험 연결·수입 원본/금액은 보존한다.
- 검증: 병합 트리와 동일한 후보에서 수입/보험 명단/연결·권한 보호 80 passed/브라우저 등 5 deselected. ego-browser 합성 0원·음수·양수 로딩/성공/실패 PASS. 인증된 운영 여행의 수입13행 중 0원1행 `환불완료`, 양수 행 오표시0·삭제 문구0을 확인하고 TaskSpace4를 정상 종료했다. 전체 회귀·실기기는 미실행(국소 표시 변경). 금융/참가자/Google/원본/스키마 쓰기0.
- 배포: 1,233 Git blobs 불일치0·검사본/병합본 트리 동일·task/process 고정SHA·단일 loopback listener·health/ready200·영향/보호4경로401·보호13표 내용/스키마 불변 PASS. 기존 task 인수/SourceRefresh 상태 보존. 코드 전용이므로 새 전체 DB 백업/복원은 반복하지 않았으며 이전 검증 릴리스/task XML 복구점을 보존했다. 근거 `.local-archive/income-refund-label-20261102/`의 targeted.xml·browser.json·live.json·review/release-audit/deploy-evidence 및 호스트 동일SHA 감사 기록. 이 요청의 미결/차단0, 다음 명령 없음. 후속 문서는 재배포/재시작하지 않는다.

- COMPLETE — [조사·8건별 근거](specs/eight-card-review-20261102.md), [PR461](https://github.com/6Soo/cost/pull/461). 구현 `c5f88337`, 운영 `efefafc43dd13134c61c85c9fd1d171c8523142c`. 저장된 취소·환불6건과 취소 확인 보류1건을 목록/상세/집계/미배정 필터/취소 정산 탭에서 일관되게 표시했다. 군산 Agoda146,018원의 명시 이용 확인 보류는 유지했다.395,000원 결제의 원승인 취소355,000원·순액40,000원 근거를 확인했으나 성격/환급을 창작하지 않았다.
- 병합본 표적65 passed/기준624ceec9 재현 기존실패2 deselected. 운영8건 읽기 대조·인증ego8건/상세/필터·모바일390px 넘침0 수락.1,232 blobs 일치·task/processSHA·단일listener·health/ready200·영향/보호4경로401·보호13표 내용/스키마 불변. SourceRefresh 및 기존task 인수 보존. 금융/분류/여행/보류/장부/Google/원본/스키마 쓰기0.
- 근거 `.local-archive/eight-card-review-20261102/`, 호스트 동일SHA release/deploy audit. 직전 검증d206cab7와task XML 복구점 보존, 코드 전용으로 새전체DB백업/복원 없음. 조사/표시교정 미결0·다음명령 없음. 실제 이용/은행 환급·현재Gmail 전체검색·전체회귀/실기기는 미확인이며 기존보호를 유지한다. 문서후속 재배포/재시작 없음. 병행 사용자/다른작업 변경은 별도 보존한다.

## 2026-11-02 브라우저 실행 규칙 ego-browser 전환

- COMPLETE — 사용자 “프로젝트 규칙에서 aside 관련 내용을 모두 ego로 수정”. [COST 지침](../AGENTS.md), 참조 정본 `C:/AX/agent-policy/AUTONOMOUS_EXECUTION.md`의 브라우저 절, [카드 다운로드](card_downloads.md), 금융·Google 인증·UI 검증의 실행 지시를 ego-browser로 변경했다. Windows UTF-8 `.mjs`·동일 TaskSpace 재사용을 명시하며 인증·원본·외부 쓰기 권한 경계는 유지한다. 과거 운영/인증 기록은 당시 증거로 보존하고 현재 실행 지시와 구분한다.
- 문서 diff·참조 경로·명령과 실제 스킬 API 일치만 확인한다. 이 변경에 따른 코드 테스트·빌드·운영 DB 확인·재배포·서버 재시작은 하지 않는다. 병행 코드 변경은 이 문서 변경에 포함하지 않는다.
- 당시 별도 업로드 오류는 원본 확보 전 미해결이었다. 후속 PR #470에서 실제13개 원본 재현·수정·격리 보호 검증·운영 코드 배포를 완료했다. 현재 상태는 이 문서 상단의 기업·하나 다운로드 업로드 완료 절과 로컬 `.local-archive/upload-format-20261102/checkpoint.json`을 따른다.

## 2026-11-01 모든 비용 준비기간·Python 기능군 리팩토링 완료

- COMPLETE — [PR458](https://github.com/6Soo/cost/pull/458), 운영 `d206cab71cf02843fcd38be5340cf3e04ff4d75f`. [실행 큐](specs/python-refactor-20261101.md) PY01~PY05 완료. [전수 조사·수치·재현·한계](specs/python-refactor-results-20261101.md). 숙박 외 모든 비용의 준비기간 추론을 공유하고 여행 후보/선택 조회·OTA 단계·CSV/원본·회사명·스냅샷/합계 읽기를 개선했다. 수동·원본·중복·환불·기존3820 예외를 유지했다.
- 실행 중복 사본6→2, OTA 진입434→10행, 실행 AST 분기21,376→21,356. 실행 코드량은98행 증가했으므로 전체 경량화로 보고하지 않는다. 합성 성능은 OTA3.67배·여행 커널2.25~31.4배·선택 조회237배이며 운영 전체 성능 측정은 아니다. Rust는 경계/빌드 비용을 정당화할 실측 필요가 없어 도입하지 않았다.
- 여행금융110·OTA120·입력34·권한은행84·스냅샷합계59 passed(중복), 준비기간17·작업자2 passed. 기존 OTA13·안내1·화면6 실패는 기준bc723cfa 동일 재현. 5DB/99파일 백업·격리 복원 게이트 후 1,227 blobs·task/processSHA·단일listener·health/ready200·영향/보호6경로401·코드 전환13표 불변 확인. 기존 task 인수/수집 상태를 복구했다.
- 기존 자동 작업자가 사용자 재요청 없이3건/29,186원을 분류·내부기록했고 원본/수동/기존 기록/금융 링크/다른 행/스키마 불변 검증 PASS. 취소 원결제1건 보호 유지·작업자 실패0·Google 쓰기0. 실제 환급/Google 반영 확정이 아니다. 상세 [운영 기록](operations.md), 로컬 `.local-archive/python-refactor-20261101/`. 승인 큐 미결/차단0·다음 실행 명령 없음. 전체 회귀·실기기·운영 부하 시험은 미실행이며 문서 후속 재배포 없음.

## 2026-11-01 카드 자동처리 재발 방지·운영 활성화 완료

- COMPLETE — “해당 문제 자체를 재발안하도록 수정해”. [PR455](https://github.com/6Soo/cost/pull/455)·[PR456](https://github.com/6Soo/cost/pull/456), 운영 `348357929d9e3eb248b357a19efecc28a5d5a29e`. [계약](specs/card-completion-recurrence-20261101.md). 접수 직후 정확한 작업 ID를 저장하고 서버가 요청 없이 재시도·재시작 재개한다. 분류 완료 뒤에는 저장된 근거를 보존하고 기록만 재개한다. 최대50건·백오프·소스 갱신 재평가·동일 작성자 잠금·원자/중복/수동/환불 보호, GET 읽기 전용을 유지한다. 과거 분류 완료 미기록 전체를 재처리하지 않는다.
- 표적60·보호52 passed(중복 포함), 최종 인접50 passed/Windows 임시 파일 잠금1건 재검사1 passed, 작업자13 모두 통과. 기존 lifecycle20 passed/1 실패는 기준242ef999에서 재현해 별도 기록했다. 운영 사본5건 평가·기록1/380,203원·정책 조건4유지·원본/수동/기존 장부/링크/다른 행 불변·재실행0 PASS. 운영5DB/99파일 백업/격리복원·전체 비교 게이트 후 `automatic_card_completion:true` 활성화, task 상태 복구 완료.
- 실제 **사용자 재요청 없이** 운영1건 자동 기록을 확인했고 최종 재시작 뒤 작업자 실패0·추가 중복 기록0이다. 1,218 blobs·task/processSHA·단일listener·health/ready200·영향/보호8경로401·코드 배포13표 불변, 데이터 활성화 전후 허용 범위 밖 변경0. Google/원본/인증/금융 링크/스키마 쓰기0. 상세·복구·초기 실패 교정은 [운영 기록](operations.md), 로컬 `.local-archive/card-completion-recurrence-20261101/`. 재발 방지 요청 미결/차단0·다음 명령 없음. 전체 회귀/실기기/새 UI 브라우저는 미실행이며 문서 후속 재배포 없음.

## 2026-11-01 Booking 카드 자동처리 누락 교정 완료

- COMPLETE — 사용자 스크린샷3건 자동처리 및 코드 수정. [PR #453](https://github.com/6Soo/cost/pull/453), 구현 `52f1050c`, 운영 `b4e7e2fb897b017667f94dde87119d36d6a7c0fc`. 과거 기본 분류의 `booking_evidence_needed` 등 미완료 구매를 소유자 자동 기록 요청에서 예약 근거 우선 분류·최종 추론 후 기록하도록 복구했다. GET/권한/원본·수동/환불/중복 보호와 현재 배치 범위를 유지하며 새 백그라운드 일괄 처리를 도입하지 않았다.
- 표적39 passed·예약/환불/복구23 passed(복구3중복). 운영3건은 수동/원본 오류·중복/보류 없이 미분류였고 현재 대사 결과에 예약 근거가 없어 기존3820 잔여 규칙으로2026년4분기 기타비용에 분류3·내부기록3(1,371,632원). 사본 리허설·호스트 복구 사본/무결성·원문/source/revision 보호·다른 행 불변·재실행0 검증. Google/예약·결제 링크/실제 환급 확정0.
- 1,215 blobs 일치·task/processSHA·단일listener·health/ready200·보호8경로401·코드 배포 전후13표 불변. 별도3건 교정 후 인증 운영 PC/모바일에서 기기록3·미분류 목록 제거·넘침0 수락. 상세/초기 실패 교정/복구 근거는 [운영 기록](operations.md), 로컬 `.local-archive/booking-auto-completion-20261101/`. 스크린샷3건 미결·차단0, 다음 실행 명령 없음. 다른 미결 전체 완료를 뜻하지 않으며 문서 후속 재배포 없음.

## 2026-11-01 카드 업로드 UI·여러 파일 처리 완료

- COMPLETE — 최신 요청 “1. UI 개선 / 2. 한번에 여러 파일 업로드 가능하게”. [PR #451](https://github.com/6Soo/cost/pull/451), 운영 SHA `10aee46d228a7bbab58e900ce268d1f7c116d874`. 여러 XLS/XLSX/CSV 선택·드롭·키보드 조작·선택 목록·순차 진행 표시·파일별 결과/상세 링크를 추가했다. 중간 업로드 실패 후 다음 파일을 처리하고 분류 미완료를 성공으로 표시하지 않는다. 기존 중복/수동/환불/권한 보호는 유지한다.
- 표적4 passed, 최종 키보드/드롭/큐2 passed(중복 검사), 기존 브라우저 진입/중복보호2 passed. 실제 합성 DB에서 정상→오류→중복3파일·거래1건·파일별 링크2개·PC1440/모바일390/320 넘침0 확인. 인증 운영 PC1440/모바일390 GET검수 PASS. 1,215 blobs 일치·task/processSHA·단일listener·health/ready200·영향/보호8경로401·보호13표 불변·SourceRefresh 유지. 실제 운영 업로드·금융/원본/Google/스키마 쓰기0. 전체 회귀/실기기는 미실행이다.
- 상세·초기 실패 교정·복구 근거는 [운영 기록](operations.md), 로컬 `.local-archive/card-multi-upload-20261101/`. 요청 미결·차단0, 다음 실행 명령 없음. 문서 후속으로 재배포하지 않는다.

## 2026-11-01 안드레 여행 장부 추가 완료

- COMPLETE — [PR447](https://github.com/6Soo/cost/pull/447), 구현 `93fb4182`, 운영 `35a6263b9cd876091ccadaae66fda8f056e0fe5c`. [명세](specs/andre-multi-owner-ledger-20261101.md). 김동언=안드레 원본을 아슬란과 분리하고 `1022_홍천`·`1031_양평`·`1105_용인`·`1107_강화`·`1111_철원`5개 여행과 원본 연결을 추가했다. 담당자 필터·이름 변경 후 원본 식별·수입/명단/지출 중복 읽기를 지원한다. 안드레 보관 원본은 없어 마감 미상이다.
- 실제 읽기3원본/70항목·운영 수입요약5개 PASS. 동일 원본의 기존65항목 금액/기간/마감/원본 차이0, 별도 DB 사본에서 신규5→재실행 신규0·기존 여행/지출 보존. 통합 UI59/2subtests·최종28/2subtests·저장보호34/8subtests·지출33·참조15·매핑26 passed는 중복 검사로 합산하지 않는다. 기존 안내1·폐기 라우트23/변형6 실패는 기준 `f05f599d` 재현이며 성공으로 표시하지 않는다.
- 1,213 blobs 일치·task/processSHA·단일listener·health/ready200·영향/보호 경로401·보호13표 불변. 기존 여행행/수동 mapping/스키마 보존. 직전 검증3d991339·task XML·원본 generation·SQLite 복구 사본/격리 전체 import 근거 보존. GoogleAuthority 같은 SHA 고정·실제 실행 LastTaskResult0/Ready, SourceRefresh·ParticipantSyncConfig 유지. 실제 쓰기는 신규 여행5/연결5·원본 snapshot이며 Google/카드재분류/금융/원문 쓰기0.
- Luna medium/ANUS Free Auto 병렬 실행 후 ANUS 오류를 취소·Luna로 인계했다. 보험·수입 UI PR448까지 통합했고 해당 담당자의 실제 인증 PC/모바일 검색·초기화 수락은 [별도 명세](specs/insurance-income-workflow-ux-20261101.md)에 있다. 안드레의 실제 인증 브라우저·전체 회귀·실기기는 미실행이다. 상세는 [운영 기록](operations.md), 로컬 근거 `.local-archive/andre-ledger-20261101/`. 현 요청 미결/차단0, 다음 실행 명령 없음. 후속 문서 전용 변경에는 재배포하지 않는다.

## 2026-11-01 보험 명단 열 가독성·모바일 배치 개선 완료

- COMPLETE — 최신 사용자 스크린샷의 보험 명단 열 UIUX 개선. [PR #442](https://github.com/6Soo/cost/pull/442), 구현 `62f75767`·`02c6779f`, 운영 SHA `89f09d9b457167ed0cc028181bdb77914d00ba52`. 말줄임을 해제하고 연결 이름·인원은 기본 표시, 연결 근거·개별 해제는 펼침으로 정리했다. 모바일은 수입 행 아래에 보험 상태를 넓게 표시한다. 접힌 패널의 연결 선택과 해제 확인창이 보이지 않던 문제도 수정했다. 기존 API·CSRF·fingerprint·확인 절차와 실제 데이터는 유지한다.
- 검증: 배포와 동일 tree의 참가자/보험 검사18 passed. 병행 수입 전체행 변경을 포함한 작업본의 인접 검사50 passed는 별도 근거이며 해당 병행 변경은 이 PR에서 제외했다. 최초 인접49 pass/1 paging 실패는 병행 수정 중 발생했고 최신 작업본에서 해소됐다. 합성 실제 ego-browser 320/390/844/1440, 밝은/어두운 테마·동작 줄이기·연결 근거 펼침·해제 취소·접힌 패널에서 연결 선택 통과. 보험 영역 기본57px·조작44px 이상·페이지 가로 넘침0. Aside 실행 파일 부재로 ego-browser를 사용했다. 전체 회귀·실기기는 미실행이다.
- 운영: 인증된 PC1440/모바일390에서 보험 상태20행·연결 펼침10행·버튼44px·문구 줄바꿈·페이지 가로 넘침0 확인(GET만). 검수/병합tree 동일·1,208 blobs 불일치0·task/process 고정SHA·단일loopback listener·health/ready200·영향/보호8경로401·보호13표 내용/스키마 불변·SourceRefresh 상태 보존. 금융/명단/Google/원본/스키마 쓰기0. 코드만 전환했으므로 전체DB 백업/복원은 반복하지 않았고 이전 검증 f05f599d와 task XML 복구점을 보존했다.
- 근거 `.local-archive/insurance-cell-ux-20261101/`의 exact-final.xml·targeted-final.xml·browser-evidence.json·live-browser.json·review.json·protection-before/after.json·deploy-evidence.json 및 호스트 동일SHA release/deploy audit. 이번 UI 요청 미결·차단0, 다음 명령 없음. 수입 전체행 병행 변경과 기존 미추적 파일·stash는 보존한다. 이 완료 기록은 문서 전용으로 재검사·재배포·서버 재시작하지 않는다.
## 2026-11-01 OTA 결제일 미상·M:N 연결 배포 완료

## 2026-11-01 카드 4850 이름 표기 교정

- COMPLETE — 사용자 최신 교정에 따라 4850은 `•••• 4850 김동언`으로 표시한다. ‘대장’은 카테고리이며 이름에 붙이지 않는다. 카드사·끝자리 기준 국내/해외 통합 조회는 유지하고 카테고리·금융 자료는 쓰지 않았다. [PR #439](https://github.com/6Soo/cost/pull/439), 구현 `684e00de`, 운영 SHA `5ba6955a9f2f72488e3996e07e39a15798a95a47`.
- 기존 통합 조회 합성 검사 1 passed, 운영 Python 배포본의 표시명·통합 필터·페이지 이동·원본 불변 smoke PASS. 1,206 Git blobs 불일치0, task/process SHA·단일 loopback listener·health/ready200·카드/OTA 보호 경로401·보호13표 불변·ParticipantDb 인수/수집 작업 상태 보존. 이전 검증 `eb1c408c`와 task 복구본 보존. 코드 전용 교체로 전체 데이터 백업/복원·전체 회귀·인증 운영 브라우저 검수는 수행하지 않았다. 근거 `.local-archive/card-label-correction-20261101/`. 남은 작업·차단 없음. 후속 문서 변경만으로 재배포하지 않는다.


- COMPLETE — 사용자 지적4건의 원인 조사·공통 수정·배포 OM01~OM05 완료. [명세·수락 근거](specs/ota-undated-many-to-many-20261101.md), [PR #435](https://github.com/6Soo/cost/pull/435)·[PR #438](https://github.com/6Soo/cost/pull/438), 구현 `1f070bb7`·`60cdacc2`, 운영 `eb1c408c1eac96f536b77f74bb489c54c024a63e`.
- 무날짜도 가맹점/확장명·정확 금액/통화·끝4 일치로 연결하며 조건 일치 관계를 M:N으로 보존한다. 카드 원행은 한 번만 집계하고 동일 예약의 관측을 결제 여러 건으로 더하지 않는다. 152,358원·395,000원은 기존에도 연결돼 있었으며 여행/환불 보류를 미연결로 설명한 오류와 취소 예약 카드 건수 누락을 바로잡았다.
- 정책312·인접 기장/환불90·최종 선택 보호2 passed 근거 재사용, 후속 게시 통합192 passed. 최초1131d2a0는 실제 갱신 실패 후f52e019a로 복귀했으며 최종 후보에서 수정·재수락했다. 배포본 전체 읽기 입력3,921이벤트/6,851카드에서5예약·6관측 관계 동일, 운영 ego-browser PC1440/모바일390×5예약 연결·무날짜/M:N/취소 표시·넘침0 수락. 기존 재현 실패6개는 통과에 포함하지 않으며 전체 회귀/실기기 미실행이다.
- 1,206 blobs 일치·task/processSHA·단일listener·health/ready200·보호API401·보호13표 불변. 기존ParticipantDb 유지, 이전f52e019a/task XML 복구점 보존. 원본/금융/여행/환불/기장/Google 쓰기·마이그레이션0. 코드전용이라 전체DB백업/복원 반복 없음. 미결0·다음 명령 없음. 로컬 근거 `.local-archive/ota-mn-policy-20261101/`; 문서만의 후속 병합에 재배포하지 않는다.

## 2026-11-01 전체 업무 UX 감사·개선 완료

- COMPLETE — 현재 사용자 요청의 UX01~UX10. [감사·업무 목적·전후 비교](specs/full-ux-audit-20261101.md), [124개 경로/206개 핸들러](specs/full-ux-route-inventory-20261101.md). [PR429](https://github.com/6Soo/cost/pull/429)·[PR430](https://github.com/6Soo/cost/pull/430)·[PR431](https://github.com/6Soo/cost/pull/431), 최종 운영 `9e0ff03c464e98373b5cd591a19a3885fcf9ccf4`. 여행 맥락 전달·검색/상태 조건·개별 편집 접기·영수증 묶기/해제·빈 버튼 잠금·출력 선택 도구·중복 홈/헤더/카드 설명·규칙 화면 복귀·404 Google 링크를 정리했다.
- 실제 동일 합성 시나리오의 영수증 진입2→1조작(여행 재선택1→0), 현재 여행 하나의 출력 준비3→1조작. 각각 화면 이동은1→1이다. `/review`의 기존 지출 정리 통합을 유지하고 원본/예약/명단/권한 조회는 근거 확인 목적이 있어 유지했다.
- 검사38 passed/9 subtests·영수증 보호5 passed·후속shell11 passed·Google 라우트회귀1 passed. 기존 보호91 passed/1 failed는 기준본에서도 동일 재현했고 통과로 세지 않았다. 최초142개 검사와 기준 재현의 기존 영수증 계약/화면 실패는 상세 문서에 남겼다. 전체 회귀·실기기는 미실행이다.
- 실제 ego-browser PC1440/모바일390에서 여행 검색·무결과·URL 유지, 합성 영수증 직접입력/묶기→복사→해제, 모바일 수기지출 저장→같은 여행 복귀를 확인했다. 운영 읽기 전용으로 영수증 여행선택/복귀·관리의현재여행·출력단일선택/선택0잠금·수기선택·항공권무결과와 보조 메뉴를 확인했다. 운영 저장·권한승인·명단연결·AI 전송·Google 쓰기0.
- 배포1,202 Git blobs 불일치0·검수/병합tree동일·task/process 고정SHA·단일loopback listener·health/ready200·기존 보호경로 및 영향7경로401·보호13표 내용/스키마 불변, 두 task Running. 코드 전용 전환으로 새 전체DB 백업/복원은 반복하지 않았고55e2612/76f33ab8 릴리스와 task XML 복구점을 보존했다. 실제 금융/분류/여행/원본/Google/스키마 쓰기0.
- 초기76f33ab8은 설정과 제거된 라우트를 혼동한 Google 링크 때문에 UX08 운영스모크에 실패했다. PR431에서 라우트 확인을 보강한 최종9e0ff03c로 수락했다. 첫 출력 로딩은 브라우저 기본15초 제한을 넘겼으나 로드완료를 확인하고 후속 흐름을 통과했다. 첫 추가 비인증 요청의 일시 시간초과는 별도 재확인에서 health/ready200·영향7경로401로 해소했다. 이를 새 성능 개선이나 첫 시도의 통과로 꾸미지 않는다.
- 근거: `C:/AX/cost/.local-archive/full-ux-audit-20261101/`의 검사XML·baseline비교·interaction-comparison·responsive/receipt/manual/trip-context/live-after-browser·affected-auth-smoke·review·protection-before/after·deploy-evidence, 호스트 동일SHA release/deploy audit. 고객 원문/실명 캡처는 Git 제외 로컬에만 보존한다. 현재 승인 범위 미결·차단0, 다음 명령 없음. 기존 `C:/AX/cost`의 사용자 변경은 보존했다. 이 후속은 문서 전용이므로 코드검사·재배포·재시작하지 않는다.

## 2026-10-31 여행 자동분류 중복 메뉴·완료 설명 제거

- COMPLETE — 최신 사용자 요청의 중복 메뉴와 불필요 문구를 정리했다. [PR #427](https://github.com/6Soo/cost/pull/427), 구현 `c05b5c95`, 운영 SHA `55e2612fc3c0a5e5229f59b31858219d5de12838`. `/import`의 별도 여행 자동분류 섹션과 “분류되면 완료입니다” 설명을 제거하고 저장 성공·규칙 저장·여행 없음 근거를 짧게 표시한다. 앞서 main에 병합된 전체 화면 설명 정리와 새 기능은 보존했다.
- 검증: 관련48개 + 중복 메뉴 부재/조회 DB 무쓰기1개 + CSRF를 보존한 독립 컴포넌트 브라우저1개, 총50개 통과. 화면 회귀9개 실패는 수정 전 main `6ac4af43`에서도 동일 재현했다. 업로드 버튼·페이지 선택·예약 근거·홈 건수 등 기존 실패를 통과로 세지 않았다. 독립 컴포넌트 테스트의 초기 CSRF 전달 누락은 수정 후 통과했다. 전체 회귀·운영 owner 브라우저·실기기 검사는 미실행이다.
- 배포: 검수/병합 tree 동일·1,199 Git blobs 불일치0·task/process 고정SHA·단일loopback listener·health/ready200·영향 `/import`와 보호 화면/API401·금융/사용자 보호13표 내용/스키마 불변. 코드만 전환했으며 이전 검증 `d2b4394634f9eab85c356291e909509560dac9eb`와 task XML 복구점 보존, 별도 DB 백업/복원·금융/분류/여행/Google/원본 쓰기·스키마 변경0.
- 근거: `.local-archive/copy-cleanup-continuation-20261031/`의 targeted/rerun/standalone-browser/baseline·review·protection-before/after·deploy-evidence, 호스트 동일 SHA release-audit/deploy-evidence. 현재 UI 요청의 미결·차단0, 다음 명령 없음. 이전 하나카드 무거래 판정 철회와 자료 수집 미결을 UI 완료로 처리하지 않는다. 문서 후속으로 재배포·재시작하지 않는다.

## 2026-10-31 수기지출 중복대조 메뉴를 여행 지출표로 통합

- COMPLETE — 사용자 “수기지출중복대조 이게 대체 뭘 하라는 메뉴인데? 왜 존재해야해?” 및 “진행해”에 따라 별도 화면/메뉴를 제거했다. [PR419](https://github.com/6Soo/cost/pull/419), 구현 `03c9ea06`, 배포 SHA `1897869876a210b2b859afb6546de97bbaa83ddc`.
- 여행 지출표의 각 행에 장부에 있음·복사 가능·중복 확인 필요를 표시하고 기존 복사 버튼에 복사 가능 건수/금액·제외 건수를 통합했다. 장부에 있는 거래/중복 후보/기존 보류는 복사에서 제외한다. Google 비교 실패 시 행별 비교 불가 표시를 반복하지 않고 표 아래 안내 한 곳과 비활성 복사 버튼으로 표시한다. 기존 대조 URL은 여행/검색 조건을 보존해 지출표 복사 영역으로 이동한다. 최신 원본 재검증·수동 연결·owner/CSRF·Google 최종 장부 쓰기 금지는 유지한다.
- 검증: 표적 UI/API/통합68 passed, 중복/연결 보호41 passed. 동시 병합 PR418 국내/해외 규칙을 포함한 최종 배포본 관련54 passed. 중복 실행을 합산하지 않는다. 모바일320/390/760/1280·두 테마·상태표시·원본불변·escaping 포함. 전체 회귀/실기기는 미실행이다.
- 배포:1198 Git blobs 일치·task/process 고정SHA·단일loopback listener·health/ready200·보호API401·보호13표 내용/스키마 불변 PASS. 직전 검증25cc2910 릴리스/task XML 복구점을 보존했다. 코드 전용 전환으로 새 전체DB 백업/복원은 반복하지 않았으며 실제 금융/분류/여행/원본/Google/스키마 쓰기0이다.
- 실제 인증 ego-browser 여행 화면에서 별도 대조 링크0·복사 영역1·가로넘침 없음·예전주소 이동을 확인했다. 해당 여행의 Google 비교 자료는 사용 불가여서 통합 안내1개와 복사 잠금을 확인했다. 실제 자료의 정상 비교/복사 성공을 확인한 것으로 꾸미지 않으며, 자료 무결성 문제 수정은 별도 담당 범위다. 브라우저 TaskSpace22는 종료했다.
- 근거: `C:/AX/cost/.local-archive/expense-dedup-integrated-20261031/`의 targeted/protection/merged XML·live-smoke·checkpoint와 `C:/AX/cost/.local-archive/deploy-1897869876a210b2b859afb6546de97bbaa83ddc/` 및 호스트 동일SHA release/deploy evidence. 기존 사용자 workspace 변경은 보존했다. 이번 메뉴 통합의 남은 작업/차단0, 다음 명령 없음. 후속 문서만으로 재검사·재배포·재시작하지 않는다.

## 2026-10-31 전액 환불 완료·일반 입력 요청 분리 배포

- COMPLETE — 사용자 환불쌍의 여행·비용 항목 요청 지적. 실제 인증 GET에서 해당 순액0원 환불쌍2건은 이미 기록 완료, 입력요청11건과 교집합0이었다. 최초 진단을 교정하고 화면에서 별개 거래임을 명확히 분리했다. [PR416](https://github.com/6Soo/cost/pull/416), 운영 `8ebb4d8b495631e18d8c2d5b37a10c12e8257082`.
- 검증된 전액 상쇄·모든 구성원 기기록·보류 없는 묶음만 `전액 환불 · 처리 완료` / `기록 완료 2건 · 추가 입력 없음`으로 따로 표시한다. 이 완료 카드의 여행·항목·비활성 기록 버튼을 제거하고 일반 거래 표/필터 건수에서 중복을 제외한다. 나머지는 `그 외 거래 처리 결과`로 표시한다. 부분환불·미기록·보류 묶음과 기존 금융 기록·원본·API·분류 규칙은 변경하지 않는다.
- 합성 Chromium390/1440에서 완료/부분/보류/미기록4사례 통과, 원본 DB무쓰기·가로넘침·JS오류 없음. 병합SHA에서 같은4사례를 재검증했다. 환불 연결/기록 보호36 passed, diff·metadata guard 차단0/삭제0. 전체 회귀/실기기는 미실행이다.
- 배포1196 blobs 일치·task/process SHA·단일loopback listener·health/ready200·보호API401·보호13표 불변 PASS. 복구점5cab519d와 task XML 보존, 코드만 바꿔 새 전체백업/복원은 반복하지 않았다. 실제 금융/연결/분류/명단/Google/스키마 쓰기0.
- 실제 로그인 ego-browser `/import`에서 완료 환불1묶음·입력컨트롤0·추가 입력 없음·그 외 거래11행·별도 수정요청11건·넘침 없음 확인. 사용자 확인용 결과 탭 유지. 근거 `C:/AX/cost/.local-archive/zero-refund-review-20261031/`, `deploy-8ebb4d8b495631e18d8c2d5b37a10c12e8257082/` 및 호스트 동일SHA deploy-evidence. 현재 요청 미결/차단0, 다음 명령 없음. 문서 후속은 재배포하지 않는다.

## 2026-10-31 상태만 표시되는 검토 UX 교정·배포 완료

- COMPLETE — 사용자 요청 “검토 필요로만 되어있고 아무것도 할 수 없는 UX 수정·모든 페이지 조사”를 수행했다. [화면별 조사](specs/actionable-review-ux-audit-20261031.md), [PR414](https://github.com/6Soo/cost/pull/414), 구현 `e24f91d`, 검증 통합 `e4a3869b27114fc1533316c9b61f414cbfab3e9f`, 병합·운영 `5cab519de4a7993017b787ad7bfa6d9d5546072c`. 검증/운영 tree 동일.
- 카드 검토 배지→해당 batch·transaction 편집 폼, 원본 상세 수정·중복 근거 링크, 미배정 검토 링크를 제공한다. OTA 그룹 조회 실패 후 버튼·클릭 핸들러를 보존하고 항공권 목록/상세 직접 재시도를 추가했다. 여행 일정 근거 표시·자료/장부 연결, 참가자 자료 누락·항공권 후보 없음에서 실제 확인 화면으로 이동하도록 했다. 나머지 페이지는 기존 폼·원본·설정·재조회 동선을 조사해 기록했다.
- 검증: 카드/모바일/읽기 경계79 passed, 인접142개 중141 passed·여행 관리 import 오류1건 발견 후 수정, 새 동작/해당 권한 재검증7 passed, 환불·분류 보호44 passed. 별도 실행 간 중복은 합산하지 않는다. 초기 합성 fixture의 Windows 열린 연결·schema 환경과 재시도 핸들러 문제도 수정했으며 초기 실패를 통과로 세지 않는다. Python compile·diff·data guard 차단0/삭제0, Ego 합성 화면 링크/넘침 확인과 호스트 릴리스 모듈 smoke PASS. 운영 owner 실자료 화면 전체·전체 회귀·실기기는 미실행이다.
- 배포1195 blobs 일치·task/process 고정SHA·단일loopback listener·health/ready200·OTA/카드상세 API·카드/여행/참가자/항공권 URL401·보호13표 내용/스키마 불변 PASS. 이전 검증 `29ecb215d63169e913e7f14a4959587436b68586`과 작업 XML 복구 수단을 보존했다. 코드 전용이라 새 전체 데이터 백업/복원은 반복하지 않았다. 금융/여행/분류/환불/명단/원본/Google 쓰기·마이그레이션0.
- 근거 `C:/AX/cost/.local-archive/actionable-ux-20261031/`의 검사 로그/XML·data-guard·review·release.zip·보호 전후·deploy-evidence 및 호스트 동일SHA release-audit/deploy-evidence. 기존 workspace의 사용자/다른 작업 변경을 보존했고 이번 초기 델타만 역패치해 중복 미커밋 수정을 제거했다. 현재 요청의 미결·차단0, 다음 기능 명령 없음. 문서 후속으로 재배포·재시작하지 않는다.

## 2026-10-31 예약 연결 UX 개선·운영 배포 완료

- COMPLETE — 사용자 식별자/연결 없음 반복·선택 취소 불가 개선과 즉시 배포 요청. [PR412](https://github.com/6Soo/cost/pull/412), 운영 `29ecb215d63169e913e7f14a4959587436b68586`, 검증 `31b0f4cbfcc6e604d001078be1eb428ab5107419`와 tree 동일. 예약자 이름·여행명 표시, 이름/예약 정보/연결 여행명 검색, 상태 필터, 10건 페이지 이동, 예약별 전체 연결 해제, 저장 전 변경 표시·취소를 제공한다. 기존 API·원본 식별자·저장/명단 적용 분리는 유지한다.
- 기존 운영 로딩 토큰 배치·업로드 진입 수정 `74325e69`가 main에 없음을 확인하고 정상 merge로 보존했다. 예약 UI 화면36 passed/38 subtests(초기34 통과, 변경 전 표시 기대1건 교정 후 재검사1 통과, 페이지 이동1 통과), 연결/권한 보호65 passed/26 subtests, 통합 표적6 passed. 정리 필터는 후보·기존 운영 각각1 passed. 탐색적 넓은 인접 검사2회는 실패 후 중단했고 통과로 계산하지 않는다. 첫 실패 `test_api_ready_matches_visible_recordable_count_before_and_after_booking`는 기존74325e69에서도 동일30초 버튼 대기 실패 재현, 나머지 탐색 실패는 이번 범위 밖 미검증이다. 전체 회귀·실기기 미실행.
- 배포1193 blobs 일치·task/process SHA·단일loopback listener·health/ready200·보호API401·보호13표 불변 PASS. 최초 배포 시도는 이전 SHA 불일치 게이트에서 쓰기 전 거부됐고, 실제 검증 운영18f3e747을 복구점으로 재확인해 전환했다. 코드만 변경하여 새 전체 백업/복원은 반복하지 않았다. 금융/예약 연결/명단/Google/스키마 쓰기0.
- 기존 로그인 ego-browser 실제 `/reserve-links`: 예약100행 모두 이름 표시·가시10행, 검색 무결과0행·안내, 다음2/10 페이지10행, 가로 넘침 없음 확인. 운영 저장·명단 적용은 누르지 않았다. 결과 탭은 사용자가 확인하도록 유지했다. 근거 `C:/AX/cost/.local-archive/reserve-link-ux-20261031/`와 `deploy-29ecb215d63169e913e7f14a4959587436b68586/`, 호스트 동일SHA deploy-evidence. 현재 요청의 미결·차단0, 다음 실행 명령 없음. 후속 문서만으로 재배포하지 않는다.

## 2026-10-31 보험 후보 버튼·로딩·여행 검토 동작 완료

- 최신 사용자 요청 3개 COMPLETE: [실행 계약](specs/insurance-trip-review-ux-20261031.md), [PR409](https://github.com/6Soo/cost/pull/409). 검증 코드 `db789b6cfa079dbce3cd29f848b1ca855f42d4e6`, 병합·운영 `1ecd2aa00d09f8bee7d9af7f09802cd506870c5c`, tree 동일. 보험 대조 진행 표시·25초 제한·재시도, 수입 행 후보/글자 일치 버튼의 비교 창과 전체 명단 대조 링크, 기본 펼침 여행 작업 3개와 별도 접힘 전체 자료 도구 4개를 제공한다. 수동 연결·Google 세대 보호는 유지한다.
- 합성 관련 검사64 passed, 마지막 JS 경로43 passed, 수동 연결 버튼 보호1 passed. 실행이 겹치므로 합산하지 않는다. 데스크톱·모바일 비교 창과 가로 넘침 없음 확인. 기존 실제 로그인 Ego 화면에서 첫 페이지20/20·다음12/12 대조, 후보 버튼14개, 비교 창 후보2행·동일 근거·닫기 후 원래 버튼 복귀, 여행별 작업3개·전체 도구 접힘·명단 쓰기 form0 확인.
- 이전 운영 브라우저 스크립트는 포인터 클릭 후 초기 포커스를 BODY로 관찰해 실패했다. 이를 통과로 바꾸지 않는다. 후속 실제 키보드 진입은 닫기 버튼 초기 포커스·Tab의 창 내부 이동·Escape와 닫기 실행·후보 버튼 포커스 복귀를 통과했다. Ego 작업 공간10은 정상 finish 완료. 전체 회귀·실기기/Safari 검수는 미실행이다.
- 배포1190 blobs 불일치0·고정 task/process SHA·단일 listener·health/ready200·보호 API401·보호13표 내용/스키마 불변. 이전 검증b99d01a7 릴리스/task 복구 수단 보존. 읽기 전용 코드 배포로 전체 백업/복원은 새로 반복하지 않았다. 금융·명단·원본·Google 쓰기/마이그레이션/스케줄 변경0. 이번 문서 후속은 재배포·재시작하지 않는다.
- 근거 `C:/AX/cost/.local-archive/insurance-actionable-20261031/`의 verified.xml·final-js.xml·manual-button-verified.xml·production-verified.json·production-keyboard-verified.json 및 `.local-archive/deploy-1ecd2aa00d09f8bee7d9af7f09802cd506870c5c/`. CORE-04의 최신 UI 요청 완료, CORE-08의 후보 비교 UI 완료이며 실제 확정 참가명단/등록 증빙 수락은 별도 외부 대기다. CORE-01 카드 수집/업로드 보류와 다른 기존 외부 자료·실기기 대기는 유지한다. 과거 경고 여행 확인 질문은 최신 3개 UI 요청을 막는 조건으로 사용하지 않는다. 완료 커밋·작업 공간 정리 결과·조건부 재개 지점은 같은 폴더 final.json에 기록한다.

## 2026-10-31 insurance source integration and inline panel recovery

- User approved proceeding with the earlier insurance linkage/panel/navigation findings. [PR405](https://github.com/6Soo/cost/pull/405), [PR406](https://github.com/6Soo/cost/pull/406) and [PR407](https://github.com/6Soo/cost/pull/407) merged normally. Final tested `54e9d04f479bce28cd55f49a142b4ac0107d7586`, runtime `b99d01a78d96e28352657c47f0a3030bba18832e`, trees identical. The earlier missing-store root error is fixed; missing confirmed identities/registration receipts are still independent facts.
- Existing masked insurance matching is now reused by the trip-income panel with explicit contract mapping or overlapping travel periods. It uses that participant view's consistent canonical income generation. Contract history and text-match/candidate statuses display without creating participants or a registration DB. Confirmed manual links retain precedence; partial/stale/capped evidence never becomes a no-match or confirmed identity. Async templates check the table generation before replacing cells.
- Missing-store responses now retain id=participant-trip-panel and load existing masked evidence automatically. The duplicate participant shortcut beside the income footer is removed. The trip-review insurance card opens the same inline panel; details and confirmed-participant management remain available in their relevant context. The column reads insurance roster, not a registration fact. No write forms are offered when the confirmed store is absent.
- Actual read-only data:12 existing contracts span13 period/mapping candidate trips. The sampled Oct15 trip has2 contracts/47 masked rows and33 normalized income inputs,19 text matches/11 candidate-review rows/17 unmatched rows. These are text observations, not verified identities, active policy or payment receipt. Final deployed render covers20/20 visible first-page and12/12 second-page cells, DB changes0, generation markers present and write forms0.
- Real authenticated Ego QA on817b6178 confirmed the generic error was gone, duplicate shortcut0 and write forms0, but exposed13/20 populated cells. PR407 corrected the date-order/source-order pagination mismatch. Final source-backed render and synthetic browser tests verify full coverage; authenticated production browser acceptance was not repeated after that fix. Ego task finished. Later legacy Aside inspection found no existing ledger tab, so no login or new authenticated session was attempted. Synthetic preview server was stopped.
- Verification evidence:60 integration tests,25 final focused checks,8 generation guard checks,17 paging/projection checks and an isolated manual-link browser check passed; phases overlap and must not be summed. An initial combined run had a new test API-signature error, corrected before accepted guard evidence; a transient localhost connection failure passed independently. Four old income-badge width/theme subfailures reproduce on baseline1f3729c0 and remain outside this change. No full regression or physical-device acceptance is claimed.
- Final deployment1190 blobs match, fixed task/processSHA, single listener, health/ready200, protected APIs including participant panel/masked review401 and13 protected table contents/schema unchanged. Prior verified817b6178 release/task rollback retained; no new full backup/restore for reversible read-only code/UI changes. No financial/source/participant/Google DB writes, schema migrations, source acquisition or scheduler changes.
- Evidence `C:/AX/cost/.local-archive/insurance-panel-integration-20261031/` actual-readonly.json, paging-actual.json, production-817-qa.json, verified/final-focused-verified/generation-guard-verified/paging-verified XML, screenshots and baseline-layout.xml; `.local-archive/deploy-b99d01a78d96e28352657c47f0a3030bba18832e/` and host sameSHA evidence. Queue/checkpoint preserve all8 CORE items: masked read-only integration is accepted; CORE-08's remaining external gate concerns actual confirmed roster/registration evidence only. Local final.json records final commits and official temporary workspace cleanup. PR402 remains a separate unmerged automation specification. Documentation followup does not repeat tests/deploy/restart.

## 2026-10-31 trip review icon-card design

- Latest user request: add icons to every trip-review button and improve the complete menu design. [PR403](https://github.com/6Soo/cost/pull/403) merged/deployed `6c4bb1cfbb08938dbe706f6d94c95e556e90bb42`; tested `c0326bf8fce17f37ba2a16c015ea1899de8bd947`, trees identical. Summary and all seven links reuse existing decorative SVGs. Fully clickable cards separate titles/statuses and use responsive3/2/1 columns, theme variables, visible keyboard focus and reduced-motion handling. Link destinations and source-derived states are preserved.
- Verification:12 focused workflow/source/closure/browser tests passed. Chromium320/390/759/760/1280 with light/dark, seven icons and44px targets accepted. Ego-browser synthetic desktop/light and mobile/dark screenshots visually inspected;320px200% no overflow and keyboard disclosure toggle accepted. The single Ego task space was finished. No physical-device or authenticated production owner-page acceptance is claimed.
- Deployment1189 blobs match, fixed task/processSHA, listener1, health/ready200, protectedAPI/affected-page401 and13 protected financial tables unchanged. Deployed synthetic render confirms seven cards/icons and scoped CSS. Verified priorf98e401f release/task rollback retained; no fresh full backup/restore for reversible UI-only changes. No financial/source/participant/Google or scheduler writes.
- Earlier user questions were investigated separately: configured insurance-review manifest exists, while the confirmed participant store resolved by deployed configuration is absent and defaults under the release when no persistent path is set. The unconfigured inline panel returns a section without the id required by the lazy client, causing its generic load-error message. This UI-only change does not create a DB, infer confirmed identities or fix that linkage. The lower panel is inline participant/income linking; trip review is an optional set of shortcuts to existing review screens. No added accounting workflow state.
- Evidence `C:/AX/cost/.local-archive/trip-review-design-20261031/` targeted.xml, preview screenshots, checkpoint and insurance-investigation.json; `.local-archive/deploy-6c4bb1cfbb08938dbe706f6d94c95e556e90bb42/` review/deploy/protection/affected-path-smoke. Queue/checkpoint preserve all8 CORE IDs and external gates; only CORE-04 received this newly requested presentation change. Local final.json records final commits and official workspace cleanup. PR402 automation specification is a separate open PR, not merged by this UI task. Documentation followup does not trigger redeploy/tests/restart.

## 2026-10-30 PR400 remaining implementation audit and card stage metrics

- Latest user request: implement all remaining code within CORE-01 through CORE-08. Reviewed current code rather than treating all blocked acceptance items as missing features. Existing card import/preflight, centralized OTA/refund matching, M:N Google comparison, source-derived trip closure, receipt OCR/payment/evidence/export, dual-source Google reader and participant ingestion/runtime verification are implemented. No duplicate workflow engine, fabricated input or new participant DB was created.
- Confirmed CORE-07 gap: card first-render/search measurements existed only as whole-page timings. [PR400](https://github.com/6Soo/cost/pull/400) now records db_connect, card_query, trip_labels and card_render in the existing bounded registry, scoped separately to first render/search. Query timings include connection setup/materialization; connection is a nested subset, not additive SQL CPU time. Exceptions propagate and scopes reset. No SQL, search values, source rows, paths or exception text are retained.
- Owner-only `GET /api/maintenance/request-metrics` returns process-window aggregates with no-store. Anonymous401 and staff403 occur before reading the registry. Initial/search/month/undated output and source DB bytes remain identical in tests. No UI controls, persisted workflow states or source/Google writes were added.
- Implementation `208eb6faa122c0b3929e22f6369f758986d6fada`, merged/deployed `f98e401fe9b2777e93c6342293d287af4b12804b`, trees identical. Focused6, adjacent126 and telemetry/isolated first-render24 tests passed; counts overlap and are not a full regression total. Eight changed Python files parse; diff check passed. Existing rendered output equivalence covers this instrumentation-only change; physical-device acceptance was not substituted.
- Deployment1189 blobs match; fixed task/process SHA, single loopback listener, health/ready200, protected APIs401 and protected13-table contents/schema unchanged. Verified1ce4fe6d release/task rollback retained. Code-only deployment did not repeat full data backup/restore or change the independently verified Google reader action58cfa0aa.
- Actual existing Aside login: initial/year, month and synthetic-search GETs all200; metrics GET200/no-store with10 aggregate groups. This proves deployed stage capture. Two initial render samples and one search sample are insufficient for representative production p95; physical Safari/Android and actual manual Google paste remain external acceptance.
- All8 code implementation items reviewed; no independent code gap remains. Overall CORE-01/02/03/05/07/08 acceptance retains the recorded real input/device/pause-release gates. CORE-04/06 are already accepted. The earlier47/62 comparison result is saved evidence, not a new source reread from this instrumentation change. Card collection/upload stays paused; financial/roster/source DB and Google writes0.
- Evidence: `C:/AX/cost/.local-archive/core-workflow-20261030/` code-gap-review.json and stage-*.xml; `.local-archive/deploy-f98e401fe9b2777e93c6342293d287af4b12804b/` review/deploy/protection/affected-path-smoke JSON; host sameSHA evidence. Temporary implementation worktree was recreated because the previous one had been archived; the original C:/AX/cost user edits remain untouched. Queue/checkpoint and final.json record authoritative paths and the actual workspace disposition. Documentation followup alone does not trigger new tests or deployment.

## 2026-10-30 17:38 Google reader acceptance and remaining comparison audit

- PR398 merged and deployed at `1ce4fe6dbe645c8e788b45e89b067cb15cb18bc3`, tested tree `f847dcf3ce3f2d1095c07641871f65cc8ee49766`. Read-only M:N comparison now includes archived COST trips; ordinary review/write lookup defaults remain unchanged. Deleted/ambiguous trips and Google source guards remain protected.
- CORE-06 is COMPLETE for the approved code, reader cutover and actual read: the latest all-proceed instruction authorized switching the GoogleAuthority action from4b4d10fb to58cfa0aa. Saved runtime result0 at16:55:17+09:00, main/archive both normal; execution times, authentication and task settings preserved. The older schedule approval wait below is superseded. Board now runs1ce4fe6d; the independently verified reader remains58cfa0aa.
- Recovered full audit:62 trips,47 comparable/15 unavailable, DB changes0,72.843s. Remaining source issues are12 nonstandard layouts and2 total/formula-range mismatches. One affected formula omits expense row76. The last unavailable trip is archived in COST and absent from the current resolved Google snapshot: after correcting its COST lookup, the precise guard is GOOGLE_TRIP_UNAVAILABLE. No success/count improvement is claimed; this is separate from the resolved global source outage.
- New verification:21 focused tests and35 adjacent reconciliation/projection/protection tests passed. Actual deployed read-only check confirms the missing Google trip remains unavailable, archive state unchanged and DB changes0. Deployment1188 blobs match, fixed task/process SHA, single listener, health/ready200, protected APIs and affected trip page401,13 protected tables unchanged. Code-only rollback uses the verified58cfa0aa release; no fresh full data backup or restore rehearsal was needed or claimed.
- CORE-04/06 independent implementation/read acceptance is complete. CORE-01 remains user-paused; CORE-02 needs original payment evidence; CORE-03 needs source formula/layout/absent-trip resolution and actual user manual paste followed by canonical read; CORE-05 needs authorized actual receipt input (configured=true is not proof of actual ingestion or store absence); CORE-07 needs physical devices, actual paste and representative performance evidence; CORE-08 needs authorized participant DB/registration receipt. No independent ready implementation remains; no Google/financial/roster/source writes or new collection were performed.
- Evidence: `C:/AX/cost/.local-archive/core-workflow-20261030/` reader-cutover JSON, remaining-source-issues.json, remaining-trip-diagnostic.json, archived-trip-recovered.json and archived-*.xml; `C:/AX/cost/.local-archive/deploy-1ce4fe6dbe645c8e788b45e89b067cb15cb18bc3/` review, release/deploy evidence and affected-path-smoke.json. Authoritative queue and run5570da1c checkpoint record all8 items and exact recheck triggers. Closed child results were checked against merged files and saved XML, then individually acknowledged; no retired owner was resumed.
- Next action is conditional: when the source owner fixes the affected Google formula/layout or restores the absent trip, let the normal reader refresh and rerun the existing read-only audit. Other tasks resume only on their recorded real input/device/pause-release trigger. Documentation followup does not require redeployment or tests.

## 2026-10-30 16:43 Google comparison incident recovery

- User reported all Google expense comparisons unavailable. Same actual source reproduced SOURCE_NOT_VERIFIED on both prior d0d73f8a and deployed58cfa0aa. Cause was the16:00 main-reader SOURCE_UNREACHABLE, not demonstrated code regression.
- Retried the existing scheduled readonly reader ONCE after its normal backoff expired; task result0, both main/archive normal with last_ok_at2026-10-30T16:43:03.212344+09:00. Schedule/runner unchanged. This supersedes the earlier current-failure observation, but does not activate PR395 generation optimization in the old scheduled runner.
- Authenticated actual recovered trip GET200:35 matched cells and0 unavailable. Another currently viewed trip remains unavailable for a REAL source formula gap: H47:H75 excludes amount row76; directly inspected workbook in memory, cached total differs from all expense rows. No Google source edit or validation bypass. Another trip has LAYOUT_NOT_STANDARD. These individual source issues must not be reported as an ongoing global outage.
- Evidence `.local-archive/core-workflow-20261030/google-recovery.json` and `sheet-range-diagnostic.json`; original values/names were not logged. No financial/roster/Google writes, server restart or redeploy. User edits the Google source formula/format, then the existing normal reader must refresh before rechecking those specific trips.

## 2026-10-30 CORE PR394/395 implementation and verified deployment

- Approved specification [PR394](https://github.com/6Soo/cost/pull/394) and implementation [PR395](https://github.com/6Soo/cost/pull/395) merged normally. Tested commit `6387b915deb22dc55cdefd45feac3e0415863163`, runtime SHA `58cfa0aa0949a1ad2d83ad691a64c9d7abae5b5e`; tested and merged trees identical.
- Existing trip page now has a collapsed review disclosure with seven existing navigation paths: card sources, holds, OTA/refunds, receipts, Google manual review, closure and insurance. Closure requires current archive evidence; unknown sources stay unknown. No new matcher, stored workflow state or Google writes.
- Google unchanged private rows reuse their generation while checked timestamps advance; previous distinct generation remains available for inflight readers. Per-request source reuse supports the existing GEMN audit; OTA coverage reuses existing provider policy scope. The scheduled Google reader is STILL pinned to old4b4d10fb with latest result1. No schedule switch or forced sync was executed; activation and actual recovery require the separate schedule gate.
- Targeted evidence: core34696 passed, workflow/receipt18 passed, protection134 passed, copy/trace84 passed, alias/refund84 passed, workflow-final12 passed. Counts overlap and must not be summed. Four obsolete copy fixtures and one alias fixture also failed on baseline; synthetic inputs were corrected to use canonical source/current matching rules without weakening financial protection. Full regression and physical Safari/Android acceptance were not run.
- Actual readonly evidence: eight import source blobs with no fingerprint mismatch;62 actual trips,47 comparable/15 unavailable and DB changes0. OTA audit3914 events,228 MATCHED_AUTO/3 MATCHED_USER are observed existing decisions; new approvals/owner-decision changes0. Between the two audits source events increased3909 to3914 and NOT_CARD_CHARGE1107 to1112; these are NOT same-input equivalence/performance evidence. Scoped audit took590.842sec; scoped/unscoped equivalence and fewer resolver calls were verified using identical synthetic input. Participant DB and actual receipt store remain absent.
- Deployment:1188 tracked blobs match; fixed task/process SHA, one loopback listener, health/ready200, protected APIs401,13 protected financial tables unchanged. Reversible code-only deployment used previous verified d0d73f8a release/task XML rollback; no new full backup/restore rehearsal was claimed. No financial/roster/source/Google writes, migrations or schedule cutover.
- Existing authenticated Aside trip page accepted: initially collapsed, expands to7 links, write forms0, no page overflow, real unavailable/unknown closure states and correct Google manual-review link. Five authenticated cards/all GETs all200:1527-2042ms, median1742ms. This includes network and is not production p95, internal phase or physical-device acceptance. ADB devices0.
- Evidence: `.local-archive/core-workflow-20261030/` XML, aggregate JSON, queue/checkpoint; `.local-archive/deploy-58cfa0aa0949a1ad2d83ad691a64c9d7abae5b5e/` and host deploy evidence. User pause on card collection/upload remains. Real Google manual paste, source payment proof, roster/registration receipt, actual receipt images and physical devices remain external gates. Verified artifacts are preserved before official temporary workspace archive; actual cleanup is recorded in final.json. Documentation-only followup does not trigger redeployment.

## 2026-10-30 최신 완료 — 참가자·수입 화면 복구와 열린 PR392

- **화면·읽기 동작·카드 PR 구현/검증/운영 COMPLETE:** 사용자 화면의 참가자·수입 대조 오류와 열린 [PR392](https://github.com/6Soo/cost/pull/392)를 함께 반영했다. 구현 `edf1b4ce3026b9e4401ae8f100eba10fa64b682b`, 운영 `d0d73f8aebed53674e2754dae665eb4dc30748ed`. [현재 변경 계약](specs/participant-income-mobile-recovery-20261030.md).
- 참가자 화면의 body 태그 누락으로 공통 셸/테마가 빠지던 원인을 고쳤다. 모바일 표는 열을 압축하지 않고 영역 안에서 가로 스크롤하며 페이지 가로 넘침을 막는다. 내부 오류 코드·참가 확정0명·원시 소수점 시각을 없애고 명단 연결 필요와 읽을 수 있는 수입을 구분한다. 합계의 미검증 표시는 유지한다.
- 별도 이름 인덱스가 없어도 일관된 Google 원본 수입 행을 읽는다. 인덱스가 완전하지 않으면 알려진 이름의 연결은 보존하되 후보 부재를 수입 없음·대조 완료로 확정하지 않는다. 참가 저장소가 없어도 실제 해당 여행15행을 표시하며 새 참가DB·참가 확정·수동 연결을 만들지 않는다. 보험 가림 글자 대조 링크를 제공한다. 실제 참가DB/명단 등록 미연결은 해결 완료로 꾸미지 않는다.
- PR392의 모바일 카드 목록은759px 이하2열 목록,760px 이상 기존 표다. 긴 금액의 폭 제한·가맹점/카드 간격·80px 이하 합성 행·숨긴 날짜 셀·확장 상세를 보완했다. 날짜 그룹·환불 링크·원본/금액·검색/필터·스피너/키보드는 유지한다.
- 검증: 관련 묶음81 passed/1 failed, 마지막 참가자 변경 후37 passed. 서로 겹쳐 합산하지 않는다. 전역 first_render p50 검사1건의 묶음 실패는 기준caea7b91에서도 동일 재현(58 passed/1 failed), 독립 검사는1 passed다. 기존 실패를 통과로 세지 않는다. Chromium320/375/390/430/759/760/1280·두 테마·200% 확대·owner/CSRF/지문·원본/금액·연결 보호를 확인했다. 전체 회귀·실기기/Safari는 미실행이다.
- 배포1181 blobs 불일치0·검수/병합tree 동일·task/process SHA·단일loopback listener·health/ready200·보호API401·보호13표 전후 불변. 데이터/스키마 쓰기가 없는 코드 배포로 전체 자료 백업은 새로 반복하지 않았으며, 직전 검증5ef006ed 릴리스와 task XML로 코드 복구 수단을 유지했다. 기존 switch의 code-only 경로를 사용했고 금융/원본/명단/Google 쓰기·마이그레이션0이다.
- 실제 기존 Aside 로그인 화면에서 참가자 페이지 셸/수입15행/원시 오류·잘못된0명 부재/쓰기form0/가로 넘침 없음, API200/no-store·configured=false·Google available=true·complete=false를 수락했다. 카드10월32행·표/펼침 버튼·페이지 가로 넘침 없음도 확인했다. 영향3경로 비인증401이다. 기존 Aside 연결이 복구돼 직전 세션의 브라우저 미실행 대기는 최신 화면 수락으로 대체한다.
- 근거: `.local-archive/participant-mobile-20261030/`의 verified·participant-final·baseline-timing·timing-recheck XML, readonly-check·live-smoke·final JSON 및 `.local-archive/deploy-d0d73f8aebed53674e2754dae665eb4dc30748ed/`·호스트 같은SHA 근거. 완료 임시 공간/브랜치는 문서 병합 후 공식 archive하고 final.json에 실제 결과를 기록한다. 사용자 기본 작업 사본·stash, 기존 실제 명단DB/영수증·원결제·메일 전환·실기기 외부 대기와 카드 수집/업로드 보류는 보존한다. 다음은 외부 명단/영수증이 확인될 때 기존 읽기 전용 진단이며 후속 문서만으로 재배포하지 않는다.

## 2026-10-30 최신 완료 — 지출 대조 안내·기본 정렬·보험 후보 보완

- 사용자 세 요청을 [PR389](https://github.com/6Soo/cost/pull/389)·[PR390](https://github.com/6Soo/cost/pull/390)으로 병합하고 운영 `5ef006edb00a1b955520a07023e6c3fd7eb005bd`에 고정 배포했다. [현재 실행 명세](specs/ledger-sort-insurance-followup-20261030.md). 이전509392e1의 상단 대조 요약/하단 상시 그룹 목록은 최신 요청에 따라 제거했다. 상태 버튼 클릭 때만 닫기/Escape 가능한 상세 창을 연다. 열린 상태에서899px로 줄였을 때 숨은modal이 남는 재현 실패도 PR390에서 교정해 모바일 전환 시 닫힌다.
- PC 지출 기본 순서는 건수 일치→부분 일치→미기록이며 각 일치 단계 안에서 첫 실제 Google 원본 행 번호순이다. 반복 금액 그룹의 원행을 임의1:1로 연결하지 않고 동률은 기존 순서를 보존한다. 검색·live fragment도 같은 표시 기준이며 복사/TSV 입력 순서·수입·원본·금액·금융 링크는 불변이다.
- 보험159행 중52행은 첫 글자/연속별표3개/끝 글자 형태다. 연속 가림 길이를 고정3글자로 비교하던 누락을 길이 미확인 후보로 보완했고, 기간 추정 범위 밖의 검증된 여행 후보를 별도로 표시한다. 명시적 여행 연결/선택은 검색 범위를 넓히지 않는다. PR389의 실제 읽기 전용·기존 Aside 인증 화면/API에서 단일 일치41 유지, 검토 후보20→70, 미일치98→48을 확인했다. 길이/여행 범위가 불확실한 후보를 동일인·가입·수령·단일 확정으로 승격하지 않는다.
- 표적78 passed 및 반응형 후속8 passed: 계산·원천/권한·signed HTTP·실제 Google 행 번호 보존·정렬/검색/새로고침·복사 순서 경계·Chromium899/900·보험320/390/760/1280·상세 창 열기/닫기. 실행이 겹쳐 합산하지 않는다. 최초 신규 합성 fixture의 occurred_on 누락1건은 보완하고 전체 표적 집합으로 재검증했다. 전체 회귀·실기기는 미실행이다.
- 1180 Git blobs 일치·검수/병합tree 동일·신선한 전체 백업/격리 복원·task/process SHA·단일loopback listener·health/ready200·보호API401·보호13표 전후 불변. 직전 PR389 운영c2b4531e의 실제 인증 지출/보험 화면·API 수락은 변경 없는 경로에 재사용했다. 최종 SHA 화면은 Aside Page.navigate/Page.enable 시간 초과 후 Aside 미실행 오류로 재수락하지 못했다. 반응형 변경은 합성8검사 근거다. 후속 PowerShell ready 요청도 한 번 시간 초과했으나 직접 curl loopback 재확인은 health/ready 모두200(각 약3ms)이었다. 원인은 미확정이며 재시작/롤백은 하지 않았다. 실제 금융/명단/Google/원본 쓰기0.
- PR390 최초 배포는 전체 백업 검증 실패로 중단·이전c2b4531e 복구 및health/ready200·보호13표 불변을 확인했다. 별도 무결성 및 작성자 중지 상태의 동일 전체 검증20 state checks/격리 복원은 통과했고, 보호 조건을 낮추지 않고 정상 배포를 재실행해 수락했다. 첫 실패를 성공으로 바꾸지 않으며 근본 원인은 미확정이다. `deployment-recovery.json`·`controlled-backup-result.json` 근거를 보존한다.
- 근거는 `.local-archive/ledger-sort-insurance-20261030/`의 progress·verified.xml·responsive.xml·diagnostic.json·live-smoke.json 및 `.local-archive/deploy-5ef006edb00a1b955520a07023e6c3fd7eb005bd/`다. 완료 임시 공간은 결과 커밋 보존 후 공식 archive하고 실제 결과를final.json에 기록한다. 기본 작업 사본의 기존 변경·stash·외부자료 대기·카드 수집/업로드 보류·Google 자동 쓰기 금지는 유지한다. 후속 문서만으로 재배포/재시작하지 않는다.

## 2026-10-30 최신 완료 — 열린 PR 개발·배포·작업공간 정리

- **GEMN-01~05·카드 UI·진단 도구 구현/병합/배포 COMPLETE:** [PR384](https://github.com/6Soo/cost/pull/384) 명세, [PR385](https://github.com/6Soo/cost/pull/385) 카드 원래 변경, [PR386](https://github.com/6Soo/cost/pull/386) 검증 통합, [PR387](https://github.com/6Soo/cost/pull/387) 실제 수락 후속. 운영 SHA `509392e1558e3df1c31ccdbd2dfe676f5498051b`; 첫 배포28853255의 비교 불가 요약/상세 버튼 문제를 최종 보완했다. [현재 실행 범위](specs/open-pr-development-execution-20261030.md).
- 실제 위임은 Luna low4개·ANUS free auto1개·OpenRouter free1개다. Luna 결과를 검수·통합했고 ANUS의 진단 영수증100KiB/배포 마커1KiB 제한은 읽는 동안 적용하며 초과 입력을 실패 처리한다. OpenRouter free 제공자 오류 후 남은 합성 테스트 초안을 보존해 감독자가 수정·검증했다. 유료 모델 대체나 작업자 운영 자료 접근은 없었다.
- 같은 실제 여행+signed 정수 KRW로 M:N 그룹을 계산한다. 반복 거래는 보존하고 같은 원본 projection만 검증 후 합친다.900px 이상 상태 열·양측 원행 목록을 표시하며899px 이하는 숨긴다. 검색과 관계없이 전체 여행 기준으로 집계한다. 비교 불가에는 확인 불가 문구·이유·마지막 성공 시각을 표시하고 작동하지 않는 상세 버튼을 만들지 않는다. Google·수입·복사/TSV·원본/금융/수동 연결 쓰기0.
- 검증은 GEMN74 passed, 카드32 passed, 최종 후속25 passed다. 서로 겹치는 실행을 합산하지 않는다. 인접 보호56 passed/10 failed 중10개는 기준fc1e2022에서도 동일 node 실패이며 통과에 포함하지 않는다. 전체 회귀·실기기는 미실행이다. 실제 로그인 Aside에서 정상 원천 요약(일치31·부분1·미기록5·Google전용13)과 상세 열림, 미검증 원천의 확인 불가 문구/상세 트리거0을 수락했다.
- 최종 릴리스1179 blobs 불일치0·새 전체 백업/별도 복원·task/process 고정 SHA·단일loopback listener·health/ready200·보호API401·보호13표 불변. 근거는 `.local-archive/open-pr-development-20261030/`의 queue·gemn-final.xml·followup.xml·baseline-comparison.json·live-smoke-final.json과 `.local-archive/deploy-509392e1558e3df1c31ccdbd2dfe676f5498051b/`다.
- 완료 작업자6개는 커밋 보존 후 공식 archive·디렉터리 제거했다. 통합 공간도 최종 문서 병합 후 같은 절차로 정리하며 결과는 로컬final.json에 남긴다. 사용자 기본 작업 사본38개 변경·stash는 보존한다. 이전 빈 폴더 Windows 점유는 활성workspace가 아니며 점유 해제 때만 재점검한다.
- Travel INS [PR2](https://github.com/6Soo/travel_ins/pull/2)는 현재main의e97138fa가 폐기한 웹앱/클라우드 구성을 되살리는 오래된 변경이라 병합·재배포하지 않았다. 실제 외부 자료·참가DB/영수증·원결제 증거·메일 전환·실기기 대기는 기존 `.local-archive/remaining-acceptance-20261030/final.json`대로 유지한다. 과거 미구현 표기를 새 개발로 재실행하지 않는다. 카드 수집/업로드 보류·Google 최종 장부 자동 쓰기 금지를 유지한다.

## 2026-10-30 최신 완료 — 마스킹 명단 수입 대조·임시 작업 정리

- **구현·병합·운영 COMPLETE:** [PR #382](https://github.com/6Soo/cost/pull/382), 운영 SHA `6338146ecfd0f48cd89aafb61c63f46a07e94f25`.84 표적검사 통과·검수/병합 tree 동일·1,167 blobs 불일치0·새 백업/별도 복원·task/process SHA·단일 loopback listener·health/ready200·보호API401·보호13표 불변. Board/SourceRefresh Running. 아래 과거 c9336e9 운영 표시는 이 기록으로 대체한다.
- 기존 로그인 Aside 탭의 실제 대조 화면과 API200/no-store/OK 확인:12계약159행, 단일 후보41·복수 후보20·일치 없음98·자료 부재0. 기존 Google 수입 이름/닉네임을 읽고 가림 글자·길이를 비교한 결과이며 동일인·보험가입·수령·참가자 등록을 확정하지 않는다. 실제 금융/명단/원본/Google 쓰기·마이그레이션0.
- 남았던 Travel INS 전달 브랜치도 현재 main과 충돌을 해결하고 증빙 부재 대기·실제 파일 identity 미검증 보호를 유지해 [PR #11](https://github.com/6Soo/travel_ins/pull/11)로 병합했다.28 합성검사·CI gates 통과, main 작업 사본 `e6b11c21d8dbb708e8ecad321a8ef904c3ce07e4` 반영. 보험 업무·실명단 전송은 재실행하지 않았다. 코어와 Travel INS 임시 workspace는 공식 archive·디렉터리 제거를 확인했다.
- 현재 통합 workspace도 문서 PR을 올린 뒤 공식 archive로 정리하며 실제 최종 목록은 `C:/AX/cost/.local-archive/masked-income-match-20261030/final.json`에 기록한다. 사용자 기본 작업 사본의 기존 변경·미추적 자료·stash와 사용 중 브랜치는 보존한다. 이전 UI의 빈 디렉터리1개는 재확인도 Windows 파일 점유로 삭제 실패했으며 활성 workspace/등록 worktree가 아니다. 알 수 없는 프로세스를 종료하지 않는다.
- 근거: 위 로컬 폴더의 `targeted.xml`, `live-smoke.json` 및 `.local-archive/deploy-6338146ecfd0f48cd89aafb61c63f46a07e94f25/`와 호스트 동일SHA deploy-evidence. 기존 외부 대기는 `.local-archive/remaining-acceptance-20261030/final.json`에 보존한다. 카드 수집/업로드 중지, 실제 참가자 DB/영수증·원결제·실기기·메일 전환 수락 경계를 유지한다. 후속 문서만으로 재검사·재배포·재시작하지 않는다.

## 2026-10-30 전체 미결 후속 구현·검수·운영 배포

- 사용자 “전체 미결건 위임해서 구현”에 따라 Luna low6명에게 현재 미결을 분리 배정했다. OTA 이용기간 우선/예약 배정 철회 출처, 메일 선택적 stored 집계 검증, 운영 읽기 전용 진단, 현행 공유 테마 검사 보완을 [PR #380](https://github.com/6Soo/cost/pull/380)으로 정상 병합했다. [실행·실제 대기 조건](specs/remaining-acceptance-20261030.md).
- 운영 SHA `c9336e978eca8ec60f8dccac50284700744f1eab`, 이전 검증 `dbead7d3b46e991f41a8ce6a39ff9bea8ae4c2e1`. 검수 tree=병합 tree, 메일/진단/테마63 passed·OTA/분류 교정/exact/manual/부분환불24 passed. 1,159 blobs 일치·새 백업/별도 복원·task/processSHA·health/ready200·보호API401·보호13표 불변 PASS. 실제 금융/명단/원문/Google 쓰기0. 코드·합성 수락과 실제 외부 수락을 구분한다.
- 실제 재확인: Drive readonly manifest는 메시지3,710/pending48/다음 페이지·query활성이어서 전환하지 않았다. 참가자 인증 API는200이나 configured=false/STORE_UNAVAILABLE이다. 금융 원결제 증거·실기기 수락은 여전히 미완료이며 카드 수집/업로드 보류를 유지한다. 실제 실행 wrapper의 절대 경로·유효 Microsoft 서명 및 지정 broad SID의 쓰기 허용 ACE0개를 확인했지만 전체 token 접근 수락으로 확대하지 않는다.
- 실제 인증 카드 GET1회씩은 초기27,432ms·합성 검색1,412ms였다. 추가 Luna low의 실제6,395건 분리 측정은 연결/함수 등록1,593ms·연도 쿼리21.7/19.5ms·결과 동일, 환불 그룹 약462ms였다. 최초 연도 목록16초와 전체 요청27초의 원인을 재현·입증하지 못해 의미를 바꾸는 최적화는 하지 않았다. 날짜 검증/캐시 최신성은 유지하며 실제 단계별 지연 근거가 생기면 해당 경로만 재검토한다. 실제 사용자 경로 운영 p95 수락은 미완료다. 완료7명 임시 workspace와 브랜치는 검토/기록 후 정리하며 UI 빈 디렉터리의 Windows handle만 별도 재확인한다. 사용자 원래 변경/stash는 미변경이다.
- 근거: root `.local-archive/remaining-acceptance-20261030/`의 queue·worker-review·postdeploy·deploy와 호스트 동일SHA deploy-evidence. 문서 후속만으로 재배포하지 않는다.

## 2026-10-30 임시 작업 통합·정리 후 현재 운영

- 사용자 지시로 미병합45 refs/90 commits를 실제 main과 대조하고 PR #378로 병합 이력을 연결했다. 61 exact patch와29 후속 대체 검토·보호 검사108 passed. 오래된 미배정 예외·환불 범위 확대·미구현 현황을 다시 적용하지 않았다. [검토 기록](branch-integration-audit-20261030.md).
- 운영 SHA `dbead7d3b46e991f41a8ce6a39ff9bea8ae4c2e1` 고정 배포 PASS:1,156 blobs 일치·백업/별도 복원·task/processSHA·health/ready200·보호API401·보호13표 불변. 실제 금융/분류/여행/원문/Google 적용0. 이전 외부 수락 미결·카드 수집/업로드 보류는 그대로다.
- 임시 브랜치는 병합 후 삭제하고 원격 main만 유지한다. 사용자 주 작업 폴더의 미커밋 변경과 stash는 변경하지 않았으므로 해당 작업 브랜치1개는 사용 중으로 남긴다. 완료 worktree3개와 마지막 통합 작업 공간을 정리하며 운영 검증 기록은 root `.local-archive/workspace-branch-cleanup-20261030/`에 이동한다. 문서 후속으로 재배포하지 않는다.

## 2026-10-30 미결 병렬 구현 및 카드·OTA 경량화 배포

- 사용자 “나머지 모든 미결사항 다수의 luna low에게 위임구현”과 “새로운 원격 pr 명세를 보고 구현에 추가하라”를 실행했다. Luna low 9명에게 분리 배정했고 [실행 인덱스](specs/all-pending-execution-20261030.md)에 [PR #370 명세](specs/lean-card-ota-core-20261030.md)의 R1~R5를 추가했다. 명세 PR #370 및 구현 [#371](https://github.com/6Soo/cost/pull/371), [#372](https://github.com/6Soo/cost/pull/372), [#373](https://github.com/6Soo/cost/pull/373), [#374](https://github.com/6Soo/cost/pull/374), [#375](https://github.com/6Soo/cost/pull/375)를 정상 병합했다. 기존 #366/#367은 통합 후 닫았다.
- 운영 SHA `10b95b802c879e83dd93d9030aa333f7f348cf38`, 이전 검증 SHA `d09596d0242416af2889b4a0514abd0509c60561`. 여행·분기 목적지와 저장 ID 충돌을 공유 읽기 판정으로 분리하고 카드 목록/상세·미배정 필터·업로드 완료에 연결했다. 충돌은 완료 차단으로 보존한다. OTA 제외 후보의 관련성은 코어 trace에서 계산해 UI 재판정을 제거했다. 유효하지 않은 OTA fact가 Gotogate 잔여 비용 항목을 덮지 못하게 했으며, 유효 근거 우선 동작과 수동 결정 보존은 기존 기능으로 검증했다.
- 클라우드 증거의 ID·실제 UTC 날짜·JSON 중복 키, 참가자 preflight/등록 영수증 수락 구분과 CLI 종료 코드, OTA 세대 불일치 보호, 수동 테마/문서 내부 스크롤을 보완했다. 실제 렌더·검색·Google loader·lock 대기 계측은 제한된 메타데이터만 보관한다. 환경 catalog는 정적 54/54 MATCH이며 실제 환경값을 읽지 않는다. R4의 합성 40행 측정에서 fingerprint 관련 조회가 5→3회로 감소했다. 운영 SLA·실 DB 성능 개선으로 해석하지 않는다.
- 통합 근거: 최종 main 보호 33 passed, R1 47 passed, R2 83 passed, R3 20 passed, R4 72 passed/28 subtests. 기존 미결 통합의 core/cloud/participant 115 passed, 분기/권한/fixture 67 passed/40 subtests, 계측/스냅샷/HTTP 40 passed, 실제 handler/mock Google 4 passed, 설정/UI 14 passed, audit 30 passed. 겹치는 실행을 합산하지 않는다. 원래 viewport 보호와 새 합성 검사가 통과했고 변경 CSS 자산 기준도 5 passed다.
- 배포 1,154 blobs 불일치0·새 백업/별도 복원·task/process SHA·단일 loopback listener·health/ready200·보호 API401·보호13표 전후 불변. 실제 Aside 인증 카드 화면에서 테마 버튼1개·문서 가로 overflow 없음·내부 분류 코드 비노출을 확인했다. 운영 금융/분류/여행/명단/Google 쓰기·원문 재처리0이며 기존 숲나들e 작업을 재실행하지 않았다. 근거는 통합 worktree `.local-archive/all-pending-luna-20261030/deploy/`와 같은 SHA의 호스트 deploy-evidence다.
- 남은 수락: PEND-04 실제 원격 manifest는 stored3710/pending48/complete=false라 전환하지 않았다. 참가자 실제 인증 API는200이나 configured=false/complete=false여서 실제 명단 DB·등록 영수증 수락은 미완료다. 원결제 원본 부재·카드 수집/업로드 보류·실기기 수락을 유지한다. R5 감사에서 안전하게 삭제할 제품 코드는 확인되지 않아 삭제하지 않았고, 외부 실행/권한의 UNKNOWN을 근거 없이 활성화하지 않았다. 기존 OTA 예약 검사 2건의 철회 출처·기간/독립 추론 기대는 별도 정책/fixture 검토로 남겨 통과라고 보고하지 않는다. R4의 전면 컨트롤러 축소와 R5의 문서 history 이동 전체가 끝났다고 주장하지 않는다. 실제 근거와 다음 동작은 queue/checkpoint에 기록한다.
- R4 후속 감사에서 기존 `ota_core_projection`과 `provisional_assignment` 위임을 확인했다. 남은 CardFlow 로직은 신선한 snapshot·예약 배정·메일/포털·선택 카드·기존 장부/보류/수동 결정을 조합하는 orchestration으로, 추가 안전한 중복 삭제는 확인되지 않았다. R5는 금융 명세에서 대체 사실이 명시된 [이전 잠정 귀속 명세](history/provisional-assignment-review-first-20261028.md) 한 건만 history로 이동하고 기존 경로에 호환 안내를 남겼다. 불명확한 제품 코드·다른 명세는 삭제/이동하지 않았다. 이 문서 후속은 재배포 대상이 아니다.

## 2026-10-29 카드 업로드 전수 대조 CUV 후속 검수

- 구현·합성검증 완료, 운영 수락은 PARTIAL. 통합 `781c524` 후 카드/발급사/종류·날짜·통화 경계의 중복 대조, 잘못된 날짜/미연결 중복 집계, XLSX 보안검사 실패 중단·자원 종료를 보완했다.
- 기존 100건 재업로드·70+30건·5,000행/재업로드, 수동 결정/원본 보호·원자 롤백/재시도·환불·OTA exact·권한 검증. 두 실행은 114 passed/1 deselected 및 62 passed이며 후자는 앞서 제외한 권한 검사도 포함한다. 중복 실행을 합산하지 않는다. Chromium 320/390/1280·키보드·HTML 이스케이프·빈 결과·금융 경고 수락.
- 근거: 통합 worktree `.local-archive/pr349-cuv-20261029/continuation.md`, `verification.xml`, `additional.xml`. 현재 승인 큐의 synthetic isolated only/no deployment/no production DB or Google writes 경계를 유지한다. main 병합·배포·운영 read-only/실카드 수락은 미실행이며 별도 범위 확대 전 실행하지 않는다. 원래 C:/AX/cost 사용자 변경은 보존했다.
# 현재 상태와 남은 일

## 2026-11-01 보험 수신 DB와 운영 웹 연결 복구

- COMPLETE — 최신 사용자 “보험 명단 왜 아직도 연결안됐어?”의 원인은 수신기와 운영 웹의 DB 경로 불일치였다. 수신기는 기존 고정 참가자 DB에 등록했지만, 웹은 SHA별 release 아래 기본 경로를 찾아 운영 API가 `configured=false`를 반환했다. 과거 로컬 등록 완료 보고는 운영 웹 연결의 근거가 아니었다.
- [PR #433](https://github.com/6Soo/cost/pull/433), 검수 `8adeae963289e137e59a6a580ebd4f1296fdb85d`, 운영 SHA `f52e019ad145eb0f7aaa21fde5ebb6d0c74fd958`. host runner의 `-ParticipantDb`를 실제 예약 작업에 명시하고 자식 프로세스 환경으로 전달한다. 이후 SHA 교체에도 같은 인수가 유지되며, 시작 실패 시 기존 task action으로 복구한다. 원본 복사·재등록·이름 기반 강제 연결은 하지 않았다.
- 검증: host 시작/복구63 passed·23 subtests, 참가자 runtime/통합/누락 저장소 복구12 passed, PowerShell 구문·staged 데이터 보호 통과. 검수/병합 tree 동일·1,202 Git blobs 불일치0, task/process 고정SHA·health/ready200·참가자 및 기존 보호 API401, 금융 보호13표와 참가자8표 내용/스키마 불변.
- 인증된 실제 운영 API에서 `0630_오제`31명·`1030_닛코`7명 모두 `configured=true`로 확인했다. 실제 여행 화면에서 명단 summary를 펼친 뒤 loaded=true·오류 없음. 처음에는 연결 후 autoLoad=0인 수동 펼침 화면을 자동 로딩으로 기다려30초 시간초과가 있었으며, 펼침 후 정상 수락했다. 이 경로 연결을 모든 참가자의 수입 수동 연결·보험사 신규 가입·실제 환급 확인으로 확대하지 않는다.
- 기존 `COST-InsuranceRosterSync`와 SourceRefresh Running, 60초 스캔 유지. Google·금융·참가자·원본·스키마 쓰기0. 코드/경로 설정만 전환해 새 전체DB 백업·복원은 반복하지 않고 기존 검증 릴리스와 task XML 복구점을 보존했다. 전체 회귀·실기기 검사는 미실행.
- 근거: `C:/AX/cost/.local-archive/continuation-20261101/`의 host-tests.xml·participant-tests.xml·review.json·production-after.json·participant-before/after.json·protection-before/after.json·deploy-evidence.json. 고객 원문은 Git 제외 로컬에만 보존한다. 명단 연결 요청의 미결0·다음 명령 없음. 별도 하나카드 다운로드는 과거 완전성 판정 철회·카드별 자료 미결을 유지하며, 이 연결 완료로 전체 카드 수집 완료를 선언하지 않는다.

## 2026-10-31 Google 지출 비교 오류·수기 추가 모달

- COMPLETE — 사용자 “구글장부 왜 비교불가? 오류수정해 / 수기지출추가는 모달창 뜨는 방식으로 변경”. [PR #424](https://github.com/6Soo/cost/pull/424), 구현 `c3b20b6`·`0a925cc`·`1e3863f`, 운영 고정 SHA `d2b4394634f9eab85c356291e909509560dac9eb`.
- 시트 합계 수식 범위가 개별 지출 행 전체를 포함하지 않는 표준 여행 2건 때문에 읽기 전용 금액/건수 비교까지 차단됐다. 원행 금액 검증과 행 합계의 snapshot `row_sum` 일치를 확인한 경우에만 개별 행 비교를 허용하고 합계 수식 경고를 표시한다. strict 신규 행 export·금융/환불/여행/수동 링크 보호는 유지한다. 비표준 양식은 구체적인 사유로 보류한다. 운영 readonly 대조: 비교 가능 47→49여행, 합계 경고2, 비표준12, DB changes0. 구형 양식 호환/Google 원본 수식 수정은 수행하지 않았다.
- 수기 지출 추가는 현재 여행을 선택한 native dialog다. 모바일·데스크톱 공통 폼, 검증 오류 입력/요청ID 유지, 저장 중 입력/중복 제출 방지, Escape/닫기·포커스 복원, 저장 후 현재 장부 새로고침. 기존 보호 API와 요청 재전송 방지를 재사용한다.
- 검증: 비교/표/export 통합37 passed, 최종 사유/UI14 passed, 최종 export22 passed, 추가 경고5 passed, 모달 browser1 passed/390·1280폭2 subtests, 권한9 passed, 수기 생성 보호2 passed. 중복 실행이 있어 합산 전체 회귀 수치가 아니다. 전체 회귀·배포 후 실제 owner 모달 저장은 미실행이며 합성 검사와 구별한다.
- 배포: Git blobs1199 불일치0·task/processSHA·loopback listener1·health/ready200·보호 API/장부/수기입력/수기POST 비인증401·보호13표 불변·Board/SourceRefresh Running. 호스트 Python 합성 모달/선택여행/음수저장/요청 재전송 PASS. 코드 전용 배포로 이전 검증 `05d09ce6c0791d7d5ea66414b6def94dcac8109a`와 task XML 복구점을 보존했다. 새 전체 백업·복원·운영 금융/Google/원본/스키마 쓰기0.
- 근거: `C:/AX/cost/.local-archive/google-comparison-manual-modal-20261031/`의 XML·runtime-readonly·checkpoint, `C:/AX/cost/.local-archive/deploy-d2b4394634f9eab85c356291e909509560dac9eb/`와 호스트 동일 SHA release-audit/deploy-evidence. 현재 승인 범위 미결/차단0, 다음 명령 없음. 후속 상태 문서만으로 검사·재배포·재시작하지 않는다.

## 2026-10-31 국내·해외 구분 여행 배정 완료

- COMPLETE — 최신 사용자 지시 “해외사용국가와 여행지는 일치할 필요 없어. 국내냐 해외냐만 구분해”를 반영했다. [PR #418](https://github.com/6Soo/cost/pull/418), 구현 `2b5fc5c4d702eb4e171980938afe5706e3693d4c`, 운영 배포 SHA `25cc29108cb44752b453832dca8e854747966558`. 해외 국가 코드가 달라도 국내·해외 구분과 검증된 여행 기간으로 배정한다. 국가 코드 없는 해외 통화 거래에도 적용하며 수동 배정·예약 이용기간·취소/환불·원본 보호 및 3820 국내 분기 비용 규칙을 유지한다.
- 검증: 여행/분류 표적 50 passed, 환불/대사/권한 보호 88 passed, 추가 규칙 호환·원자성·재실행 8 passed(중복 포함). 병합 tree가 검증 구현과 동일하다. 배포 파일 1,197개 Git blob 불일치0, task/process 고정 SHA·단일 loopback listener·health/ready200·보호API401·배포 전후 보호13표 불변을 확인했다. 이전 검증 `8ebb4d8b495631e18d8c2d5b37a10c12e8257082`를 보존했다. 코드만 전환하므로 전체 DB 백업/복원은 반복하지 않았다.
- 실제 자료 교정: 기존 보류 대상2건 중 10/24 거래1건을 `1020_알펜루트`에 AUTO_INFERRED로 배정했다. 여행 종료일 다음 날인10/25 거래는 그대로다. 메모리 사본 리허설·변경 전 값 로컬 보존·BEGIN IMMEDIATE 및 기존 원자 적용 경로로 처리했다. 원본/금액/ID·사용자 결정·금융/환불 링크·범위 밖 행/표·스키마 불변과 기존 감사 이력 보존/1건 추가, 재실행 대상0을 확인했다. 장부 추가·Google/은행 쓰기0이며 실제 환급을 확인한 것으로 기록하지 않는다.
- 초기 식별자 비교와 리허설의 감사 이력 순번 검증 오류는 실제 쓰기 전에 중단했다. 실제 tab ID와 표시 키를 분리하고 change_log 순번 증가만 허용한 최종 검사를 통과했다. 전체 회귀·실기기·인증 owner 화면 수락은 미실행이다. 영향 경로 `/cards`, `/import`, 카드 API 익명401 및 두 작업 Running을 확인했다.
- 근거: `C:/AX/cost/.local-archive/domestic-overseas-trip-20261031/`의 XML·preview-summary/applied/http-smoke JSON, `C:/AX/cost/.local-archive/deploy-25cc29108cb44752b453832dca8e854747966558/`, 호스트 동일 SHA release-audit/deploy-evidence. 복구용 변경 전 값은 `D:/WebLedgerHost/data/backups/domestic-overseas-trip-20261031/before.private.json`에만 보존했다. 기존 사용자 workspace 변경 보존. 현재 요청의 남은 작업·차단0, 다음 명령 없음. 후속 문서만으로 재배포/재시작하지 않는다. 다른 세션의 후속 PR은 이 작업의 새 실행 범위가 아니다.

## 2026-10-30 마스킹 보험 명단과 기존 수입 글자 대조

- 최신 사용자 지시는 마스킹 명단을 보관하는 데서 끝내지 않고 이미 입력된 수입 이름·닉네임과 글자를 대조하는 기능 구현이다. 기존 12계약159행을 읽고, 실제 여행의 연결/기간 후보와 소유자가 선택한 여행의 Google 수입 스냅샷을 비교한다. 별도 이름 인덱스가 없어도 같은 세대의 원본 수입 행을 사용한다.
- 구현·표적 검증·병합·운영 배포 COMPLETE(최상단 PR382 기록 참조). 별표 등 가림 문자 한 글자, 표시 글자/전체 글자 수, 유니코드·공백 정규화로 비교한다. 한 계약에서 같은 수입 행을 여러 명이 공유하거나 여러 행이 일치하면 복수 후보로 표시한다. 후보 보기 변경은 해당 행에만 적용하고 원본/신원/참가자/금융 링크를 쓰지 않는다.
- 실제 readonly preview: 12계약159행 중 단일 후보41·복수 후보20·일치 없음98·자료 부재0. 이는 글자 대조이며 동일인·가입·수령 완료 증명이 아니다. 원본 PDF·가입 사진을 웹에 제공하거나 Git에 추가하지 않는다.
- 실제 검증84 passed: 매칭/원본 수입 fallback/필터/세대·자료 부재, 실제 signed HTTP owner200·직원403·비로그인401·POST405·no-store, 오류 HTTP 상태·비밀 경로 비노출, 합성 Chromium320/390/760/1280과 후보 행 독립성, 참가자 패널·launcher opt-in·설정 목록 검사. 전체 회귀·실기기는 미실행이다.
- 근거: `C:/AX/cost/.local-archive/masked-income-match-20261030/targeted.xml`. 기존 전체 미결의 외부 자료·실기기·메일 전환·원결제 증거 대기는 `.local-archive/remaining-acceptance-20261030/final.json`에 유지하며 완료로 확대하지 않는다. 카드 수집/업로드 중지와 Google 최종 장부 자동 쓰기 금지를 유지한다.
- 코드·운영 검증 완료. 문서 반영과 공식 workspace 정리 결과는 최상단 및 로컬 `final.json`으로 이어진다. 기존 기본 작업 사본의 변경·미추적 파일·stash는 보존한다.

## 2026-10-30 숲나들e 일반 OTA 목록·정규 적재

- COMPLETE — 사용자 “숲나들e도 ota 공급자로 db에 정상 적재되고있나?”에 이은 “구현해” 범위를 [PR #368](https://github.com/6Soo/cost/pull/368)로 구현·정상 병합·고정 배포했다. 운영 SHA `d09596d0242416af2889b4a0514abd0509c60561`, 이전 검증 `241cd452abd6c4da4ac59b4f3d534e4e4b2177a6` 보존. [계약](specs/ota.md#2026-10-30-숲나들e-예약-관측의-정규-적재ota-목록).
- 기존에는 원문/예약 근거는 보관됐으나 일반 OTA 정규 예약 목록에는 없었다. 별도 관측 표에46건을 적재하고 일반 공급자 목록/상세에 포함했다. 현재 기간/일자 미확인16건(수집됨12·취소4), 과거30건 보존. 번호 없는 안내는 `원문 미제공`, 종료일 없는 안내는 미확인으로 표시하며 실제 예약번호·체크아웃을 창작하지 않는다. 같은 알림의 원문/적재 이중 노출과 서로 다른 알림의 후보 혼합을 막았다.
- 최종96 passed/2 subtests, 실제 사본 리허설·새 백업/별도 복원·원자 운영 적재 PASS. 원래 전 표/기존 관측 보존·재실행 쓰기0·금융 링크 추가0. 배포1,140 blobs 일치·task/process SHA·health/ready200·보호API401·보호13표 불변. 운영 읽기 검증은 DB쓰기0이며 수집 작업의 실행파일/인수/트리거/권한/설정과 원래 활성 상태를 보존하고 WorkingDirectory만 검증 릴리스로 전환했다. 새 메일 수집은 수동 실행하지 않았다.
- Aside 인증 API/일반 목록16개 고유 키·상세200·번호/종료일 미확인·내부 키 비노출을 확인했다. 기존 공급자 표기 오류7건 보류 경고는 남는다. 배포 후 중앙 금융 대사는 갱신을 마쳐 generation505·ready/fresh로 전환됐다. 목록의 이전 대조 대기 경고는 갱신 중인 캐시와 구분하며 이 적재를 금융 연결/환급/기장 완료로 보고하지 않는다. 전체 회귀/실기기 검사는 영향 밖이라 미실행.
- 근거: root `.local-archive/forest-provider-audit-20261030/`의 checkpoint·final-targeted.xml·rehearsal·applied·live-acceptance·mail-task-transition·auth-smoke와 `.local-archive/deploy-d09596d0242416af2889b4a0514abd0509c60561/`. 카드 업로드는 계속 사용자 보류이며 Google/금융/장부/수동/여행 귀속·기존 두 건 교정은 변경하지 않았다. 후속 문서는 재배포/재시작하지 않는다.

## 2026-10-30 수기 Google 지출 중복 방지 구현·운영 수락

- COMPLETE — 사용자 “pr열린거 다 구현해”의 [수기 중복 방지 명세](specs/sheet-manual-expense-dedup-20261029.md) SDD-01~07을 [PR #364](https://github.com/6Soo/cost/pull/364)로 구현·정상 병합·고정 배포했다. 운영 SHA `241cd452abd6c4da4ac59b4f3d534e4e4b2177a6`, 이전 검증 `bc02ea4a1fb15523e0fcfd9d92f9c5bed37d6b21`과 복구 사본 보존. 최신 두 건의 여행/항목 교정 코드·운영값을 보존했다.
- 여행 화면·카드 업로드의 복사는 최신 Google snapshot과 대조해 신규 지출만 TSV로 준비하고 수기 동일 거래의 연결은 로컬 메타데이터에 원자 저장한다. owner/CSRF·revision/CAS·요청 재시도·행 이동/삭제·점유·사용자 교정·환불·카드/금액/통화 충돌을 보호한다. 분기 기타비용은 기존 경로다. 내부 장부 기록과 Google 반영은 별개다.
- 합성 통합70 passed, 최신 main 결합47 passed, 최종 카드/여행/HTTP/실제 복사 JavaScript8 passed, UI21 passed와 stale-link replay1 passed, matcher26 passed. 실행 간 중복을 합산하지 않는다. 인접91 passed/5 failed 중 기존 브라우저 fixture의 두 실패 유형은 기준 `e149d82`에서 각각 동일 재현했다. Python/JavaScript 구문·diff·metadata guard 차단0/삭제0. 무관한 전체 회귀는 반복하지 않았다.
- 운영 DB를 `mode=ro`·`query_only`로 열어 여행61개를 검수했다.47개 원본 검증 가능, 수기 연결 후보121·신규2257·충돌193·원본 확인 불가3446건. 검증되지 않은14개 여행은 SOURCE_NOT_VERIFIED로 복사를 보류한다. 후보 판정이며 실제 Google 입력/환급 완료가 아니다. 운영 DB변경0·Google snapshot 파일 불변·실제 링크 메타데이터 저장0·Google 쓰기0.
- 배포1137 blobs 일치·새 백업/별도 복원·작업/프로세스SHA·단일loopback·health/ready200·보호13표 전후 불변. 새 대조 화면/API는 익명403. Aside 기존 owner 세션에서 정상 원본 API200·검증 불가 원본503과 화면·요약5개·페이지당50건·다음 페이지·320px overflow0을 확인했다. 실제 복사/링크 저장 POST는 운영에서 실행하지 않았다.
- PR #349는 #355의 구현·운영수락으로 대체돼 닫았고, #350 명세는 통합됐으며, #353의 오래된 현황은 [최신 현황](specs/card-and-sheet-reconciliation-status-20261029.md)으로 갱신 후 닫았다. 해당 열린 PR 승인 범위의 구현/수락/배포 미결0. 다른 세션의 새 숲나들e 적재 과제는 해당 세션 소유로 구분한다.
- 근거: 통합 worktree `.local-archive/open-pr-20261029/`의 XML·baseline XML·operating-readonly·review·release-audit·protection-before/after·deploy-evidence·auth-smoke·owner-ui-smoke 및 호스트 `D:/WebLedgerHost/releases/deploy-evidence-241cd452abd6c4da4ac59b4f3d534e4e4b2177a6.json`. root 사용자 변경·stash·미추적 자료 보존. 다음 실행 명령 없음. 후속 문서 변경만으로 검사·DB확인·재배포·서버재시작하지 않는다.

## 2026-10-30 이용일·OTA 분류 교정 및 운영 수락

- 최신 사용자 범위는 카드 업로드 보류와 두 오분류의 근거 확인·교정이다. 국민/하나 수집은 `DEFERRED_BY_USER`로 기록했으며 로그인·업로드를 재개하지 않는다. 과거 전체 큐를 새 작업으로 가져오지 않았다.
- COMPLETE — [PR #361](https://github.com/6Soo/cost/pull/361) 공급자 인식과 [PR #362](https://github.com/6Soo/cost/pull/362) 날짜/국가·예약 근거 우선 및 소수 자동분류 교정 경계를 검수·정상 병합했다. 운영 SHA `bc02ea4a1fb15523e0fcfd9d92f9c5bed37d6b21`.
- 실제 두 건은 한 DB 트랜잭션으로 거래·기존 장부·화면 행의 귀속을 함께 교정했다. 10월 국내 부산 사용은 5월 동명 여행에서 날짜/국가에 맞는 `1002_영남` 최선 후보로 추론 배정했다. Gotogate는 실제 Gmail 결제·확정 메일과 같은 주문의 첨부 영수증에서 이용기간을 확인해 `1103_아오모리` 항공료로 교정했다. 사용자의 개별 예약/환급 확인으로 기록하지 않았고 새 예약/카드 금융 링크를 만들지 않았다.
- 보관 메일 3,355건에 관련 언급 7건이 있었으나 해당 결제 근거는 찾지 못했다. 현재 Gmail에서 관련 결제·확정 메일을 찾았으며 영수증의 원화 합계와 왕복 이용기간을 대조했다. 보관 수집 범위의 누락을 메일 부재로 단정하지 않는다. 새로운 원문/첨부는 Git에 포함하지 않았고 전체 OTA 원천 적재를 실행하지 않았다.
- 검증: 결합 99 passed(공급자/교정/멱등성/부분실패 원복/P2/권위/3820/환불 경계), 배포본 호스트 Python 합성 3 PASS. 운영 사본 리허설과 실제 쓰기에서 전 표의 원본·금액·날짜·ID·기존 수동/금융/이력·범위 밖 행/스키마 불변을 확인했다. 새 장부행/Google/금융링크 쓰기 0, 재요청 추가 쓰기 0. 최초 사본 검증은 허용된 감사 append의 SQLite 카운터를 범위 밖 변경으로 취급해 거부됐고 실제 적용 없이 카운터 검증 범위를 교정한 후 통과했다.
- 배포 수락: 1,126 blobs 불일치 0·새 백업/별도 복원·task/process SHA·단일 listener·health/ready 200·보호 API 401·보호 13표 배포 전후 불변. 이후 실제 Aside 인증 카드 상세 GET 두 건 200·새 여행 표시·항공료·분기 표시 제거를 확인했다. Board/SourceRefresh Running. 전체 회귀/실기기 검사는 미실행이며 모든 과거 카드의 재분류를 완료했다고 확대하지 않는다.
- 근거: `.local-archive/classification-correction-20261030/`의 체크포인트·사본 미리보기·적용·XML, `.local-archive/deploy-bc02ea4a1fb15523e0fcfd9d92f9c5bed37d6b21/` 및 호스트 같은 SHA deploy-evidence. 운영 작성 점유를 감독자 Cost V67에 해제 통지했다. 현재 승인된 두 건/코드의 남은 작업 0. 후속 문서는 검사/배포/재시작을 반복하지 않는다.

## 2026-10-29 카드 업로드 전수 대조 운영 수락·배포

- COMPLETE — 사용자 “모든 명세가 구현되었나? 되었다면 운영수락”에 따라 최신 main의 P2 변경을 통합·검증하고 [PR #355](https://github.com/6Soo/cost/pull/355)를 정상 병합했다. 운영 SHA `a69c0ae7389789a65d2ed01f3028c0348f52eb1f`, 직전 검증 릴리스 `3860a822efe3a6f2d6c1349e824b193ac7309a7b` 및 복구 사본 보존. [명세](specs/card-upload-full-reconciliation-20261029.md)의 CUV-01~07 구현·격리/운영 읽기 전용 수락 완료이며 실제 은행 환급·Google 반영 완료와 구분한다.
- 운영 원본 대조 중 정상 XLSX 2개의 빈칸 `-` 4,120개를 수식으로 오인하는 결함을 발견해 `19f9edb`에서 교정했다. 하이픈 placeholder/음수 숫자를 허용하고 `=`, `+`, `@`, `-CMD` 등 수식 차단·XLSX scan fail-closed를 유지한다. 최신 main 통합 검사117 passed/fixture 의존 실패1은 전역 store fixture 복원으로 수정했고 관련 결합8 passed, placeholder/원천 대조27 passed를 확인했다. 유효한 나머지 통과 근거는 반복하지 않았다.
- 실카드 검증은 운영 DB mode=ro → 격리 메모리 백업에서 원본8개를 사전검사·동일 파일 재대조했다. 원천 행6,929(E=6,929/N=0/H=0/P=0), 파일 오류0, 복사본 원본/분류/금융 표 불변, 운영 connection total_changes=0. 분류 C=6,026/U=903, 취소 원결제 경고R=112는 실제 데이터 상태이며 금융 완료로 승격하지 않는다. 파일 간 겹침을 포함한 원천 행 집계이므로 고유 거래 수로 보고하지 않는다. 실제 운영 재업로드 POST·분류 재처리·Google/은행 쓰기0.
- 릴리스1,122 Git blobs 불일치0, 병합 코드 tree 일치·추가14파일 메타데이터 차단0/삭제0·새 백업/별도 복원 PASS. 공식 배포기를 통해 task/process SHA·단일 loopback listener·health/ready200·보호API401, 배포 및 인증 조회 전후 보호13표 불변, Board/SourceRefresh Running을 확인했다.
- 인증 Aside `/import`의 파일/업로드 컨트롤·50건 페이지/시스템 오류 코드와 저장 자료8개 API200을 확인했다. 익명 `/import`, `/api/imports`, `/api/imports/rules`, POST `/api/imports`는401이다. 모바일·두 테마·키보드/포커스는 최종 합성 브라우저5 passed 근거를 재사용했다. 실기기/Safari와 운영 재업로드·실제 금융 변경은 미실행이다. 대량 응답27.5MB/동기 처리라는 기존 성능 제한은 명세에 보존한다.
- 근거: 통합 worktree `.local-archive/cuv-operating-20261029/`의 acceptance-checkpoint·real-source-acceptance·review·release-audit·protection-before/after·deploy-evidence·upload-http-smoke·owner-ui-smoke 및 호스트 `D:/WebLedgerHost/releases/deploy-evidence-a69c0ae7389789a65d2ed01f3028c0348f52eb1f.json`. root 사용자 변경과 기존 workspace 보존. 해당 운영 수락 범위 남은 구현/배포0. 이 기록 후속은 문서 전용이며 재검사/백업/재배포/재시작하지 않는다.


## 2026-10-29 카드 업로드 명세 전체 구현 재대조 — Luna low 4명 병렬

- 최신 사용자 지시로 [카드 업로드 전수 대조 명세](specs/card-upload-full-reconciliation-20261029.md)의 구현을 재대조했다. 기존 구현·합성 완료 보고를 새 구현 전체의 종료 근거로 쓰지 않았다. 플러그인이 사용량 한도에 걸린 기존 4명을 successor로 인계했고, 실제 `gpt-6-luna / low` 4명의 구현 결과를 감독자가 검토·추가 교정·통합했다. 기존 사용자 workspace/작업·원본·수동 결정 보존.
- CUV-01~06 구현·합성 검증 COMPLETE. 파일 물리 행수/계정 식별, owner 업로드 권한, 카드 업로드만20MiB·다른 POST5MiB, 원천 저장 후503의 명시적 재시도, 원천 identity·감사 조회 인덱스, 최신 자동분류 완료, 실제 여행/원본 충돌 보호, 실패50건 페이지와 시스템 오류, 두 테마·모바일·키보드 포커스를 보완했다. 별도 회계 저장소/보고서 테이블/Google 최종 장부 쓰기 없음.
- 통합 구현 커밋 `1b76cd8`, `98570c6`, `9bdb7fc`, `dc10387`, `26412ff`, `28f332b`, `e0d686b`, `e963c04`, `23a32ca`. [Draft PR #355](https://github.com/6Soo/cost/pull/355)에 기존 브랜치로 통합한다. 문서·기존 정책 검사 교정은 후속 감독자 커밋에 포함한다.
- 검증: 대상/동시성/원본/수동/OTA exact/부분환불 통합80 passed; 이후 변경분 분류26 passed, API3 passed(이미 측정된10k 제외), 실제 signed HTTP인증1 passed/4 subtests, 최종 UI5 passed. 검사 간 중복이 있어 합산하지 않는다. 근거 `.local-archive/cuv-full-20261029/`의 XML·queue·supervision 및 버전 관리된 합성 측정 기록. 전체 회귀는 광범위 변경이 아니므로 미실행.
- 10,000행 실제 API dispatch 합성 측정: 최초21.230초(T/N=10,000), 재시도26.783초(E=10,000/N=0), 거래 수10,000 유지. 응답27,457,858바이트(compact JSON), 지속적 수치 진행률/50,000행 성능 보장은 미입증. 동기 처리 중 상태와 완료/오류·안전 재시도를 제공한다. 감사10,000건은0.654초/재실행0.476초·중복 감사0 확인.
- CUV-07 운영 수락 PARTIAL: 합성 검증은 완료, 운영 read-only·실카드·main 병합·배포는 현재 구현 작업에서 미실행이다. 실제 고객/운영 DB/Google 쓰기·서버 재시작 없음. 현 범위에서 남은 구현 없음. 운영 단계는 별도 범위로 상태를 보존한다.

## 2026-10-29 국민 매입 원본 수집·REPL 문서화·DB 입력 요청

- 현재 승인 범위는 국민 국내/해외 매입을 DB의 마지막 **이용일2026-10-01부터** 각 화면의 최신 허용일까지 수집하고 **중복 검증 후 운영 DB 가져오기까지**다. 사용자는 Aside Vault 저장 암호를 사용하고 방법도 기록하라고 명시했다. 초기 다운로드/검증까지라는 임시 범위는 최신 인터뷰 답변으로 대체됐다. 승인 내역/하나/기업카드 수집·신규 장부/Google 기록으로 확대하지 않는다.
- 절차 문서 작성 완료, 전체 경로 검증 미완료: [카드 다운로드 실행 안내](card_downloads.md)에 지속 REPL·현재 계정/탭 탐색·일반 모드 확인·공식 Vault API 단계·실제 실패와 재개 조건·국내/해외 다운로드 이벤트/원본 검증·포맷 간 중복 보호·DB 입력 게이트를 기록했다. 기존 금융 명세가 이 안내를 참조한다. 문서 전용 diff/링크/실제 경로/상태만 검사하며 코드 테스트/빌드/재배포/재시작은 하지 않는다.
- 수집/DB 입력 WAIT_SUPPORTED_VAULT_REPL: 국민 세션 만료·일반 브라우저·기업 인증서 선택을 확인했다. CLI1.26.1023.1115/데몬1.26.1029.43의 설치 코드에서 CLI REPL은 `incognito:true`를 고정하며 일반 창/저장 설정과 무관하게 `passwordManager`를 제외함을 확인했다. 저장 설정true로 만든 별도 REPL도 API가 없었다. 공개 MCP/CLI에 일반 agent REPL을 직접 선택하는 인자는 확인되지 않았다. 세션 플래그/설치 코드/권한 검사를 변경하지 않았다.
- 앞선 크레딧 차단 판단 정정: 설치 코드의 공식 `autofillItem` 경로에는 모델 호출이 없다. 일반 agent의 HTTP402 `Insufficient credits`는 모델 호출 실패이며 Vault 과금/암호 불일치/실제 자동입력 실패 증거가 아니다. 기본 계정/모델/Vault 정책은 변경하지 않았고 임시 CLI 세션 표시 설정은 기존false로 복구했다. 설치 코드 정적 분석과 실제 API 호출 성공을 구분한다.
- readonly 기준선: 국민3675건(국내1861/해외1814), 국내 마지막 이용일10-01/매입일10-02·해외 이용일09-30/매입일10-02. DB 쓰기0. 실제 로그인·조회 상한·다운로드·파싱·중복 검증·DB 가져오기는 미실행이다. 원본이 없으므로 새 백업/서비스 정지/자료 적용을 관성적으로 수행하지 않았다.
- 재개 조건은 지원되는 일반 세션의 직접 REPL/Vault 연결 또는 기존 승인 범위의 실행 가능한 agent 경로를 실제 확인하는 것이다. 같은402 호출·새 유료 모델/계정 전환·사용자가 거절한 수동 암호 요청을 반복하지 않는다. [실행 안내](card_downloads.md)의 공식 Vault 자동입력부터 재개한다. 정확한 로컬 세션/정적 근거/차단/다음 단계는 `.local-archive/kb-repl-download-20261029/checkpoint.json`에 남긴다. 별도 agent의 운영 배포와 조율했고 현재 DB/host 쓰기0이다. 실제 DB 입력 직전 다시 단일 작성자를 조율한다. 이전 P2 완료 작업은 재실행하지 않는다.

## 2026-10-29 사용자 지시 P2 카드 재진행·실제 적용

- COMPLETE — 사용자 “p2 재진행”에 따라 6,395건을 다시 점검하고 보호 대상57건을 제외한6,338건에 재검토 경로를 적용했다. [PR #357](https://github.com/6Soo/cost/pull/357), 구현 `7ecf023`, 운영 SHA `3860a822efe3a6f2d6c1349e824b193ac7309a7b`. 이전 classified 상태와 “유효 여행 없음” 사유를 재검토 면제로 쓰지 않는다. 항목/업종/서비스 용도·보관 예약 이용기간을 다시 대조하고, 사용자 결정/기기록 유효 귀속·검증 환불 상속을 우선했다. 근거의 원문·행 ID는 외부 모델이나 Git에 보내지 않았다.
- 실제 저장5,451건: 정상 결제 여행 미배정1,821→0, 항목 변경70건·여행/표시 귀속 변경2,047건(서로 중복3건), 근거만 갱신3,337건. 기존 자동 출처의 결과가 같으면 rule/card_category 출처를 유지했다. 예약 대조393건·유일 이용기간 근거183건, 그 근거가 있는 귀속 변경40건. 등록 자료 누락/읽기 오류0. 낮은 근거도 최선의 실제 여행으로 완료하고 추론·낮은 신뢰도·날짜 거리를 저장했다. 등록 여행은2026~2027년이며 미배정의2025년 거래1,420건을 포함해 처리했다. 변경 귀속 중 날짜 거리90일 초과670건은 강한 예약 근거가 확인된 실제 여행이라고 주장하지 않는다. 여행 생성·사용자 확인·금융 결제 연결을 창작하지 않았다.
- 실제 반영은 신선 백업/별도 복원→단일 작성자/서비스 정지→동일 원본/preview digest→복사본 결과/재실행0→원자 저장→사후 불변/재실행0→서비스 복구를 통과했다. 독립 readonly 감사에서 수동 결정/교정 이력이 있는559건의 전체 거래행 불변, 원본/금액/ID·금융 링크/보류/회사 제외/결정/override·스키마·기존 장부 행 수 불변을 확인했다. 새 장부 행·금융 링크·Google/은행 쓰기0. 보호57건은 새로운 사용자 승인 대기로 바꾸지 않았다.
- 검증: 분류/새P2/환불 원자성/부분환불76 passed, 추가 근거 캐시의 원본 변경 거부1 passed, compile·PowerShell 구문·diff·metadata guard 차단0/삭제0. 초반 읽기 전용 복사본2회는 재생 시 근거 문구가 달라져 실패했고 안정적인 근거 생성으로 교정한 뒤 실제 자료 복사본/운영 재실행0을 통과했다. 실패 단계의 운영 쓰기0. 전체 회귀·실기기·인증 owner 화면 수락은 미실행이다.
- 코드 배포: 검수 tree=merge tree·1113 Git blobs 일치·새 백업/별도 복원·task/processSHA·단일loopback listener·health/ready200·보호API401·보호13표 배포 전후 불변. 이는 뒤의 승인된 분류 쓰기와 구분한다. 자료 반영 후에도 health/ready200·카드/OTA API401·Board/SourceRefresh Running, 전체6395 classified·보호 제외 미분류/정상 결제 미배정0·최종 readonly 쓰기0 확인.
- 근거: `.local-archive/p2-rerun-20261029/`의 baseline/changes/checkpoint·XML·before/after/audit/runtime-after, `.local-archive/deploy-3860a822efe3a6f2d6c1349e824b193ac7309a7b/`, 호스트 동일SHA release/deploy audit와 `D:/WebLedgerHost/data/backups/card-classification-20261029T223551095/`의 backup-restore/preview/applied/repeat-preview. 원본 복구 사본과 파생 근거 캐시는 호스트 보호 경로에만 보존했다. 기존 공유 workspace·사용자 변경 보존. 현재 P2 재진행의 남은 작업/차단0, 다음 명령 없음. 문서 후속만으로 재검사/재배포/재처리하지 않는다.

## 2026-10-29 보존 분류 상태 제거

- COMPLETE — 사용자 “보존이라는 상태가 필요해? 필요없으면 제거해”에 따라 카드 업무 상태 `preserved`의 생성과 상태별 분류/조회/여행 검토/OTA 대사/취소 정산 제외 조건을 제거했다. [PR #354](https://github.com/6Soo/cost/pull/354), 구현 `a44c38c`, 운영 SHA `3c8c970da271b665feb99a89fad661b7399ef6d7`. 과거 상태와 미배정 사유만으로 일반 추론을 건너뛰지 않는다. 항목/여행은 일반 규칙을 적용하고 화면/전기 미리보기의 명시적 기간 필터는 유지한다. 원본·금액·ID·이력·사용자 결정·중복·환불·보류 보호를 유지한다.
- 운영 읽기 전용 확인: 전체6,395건 classified, preserved0·user_completed_period 출처0·조회 쓰기0. 변환할 기존 상태가 없어 마이그레이션·운영 재분류·금융/여행/Google 쓰기를 수행하지 않았다. 이번 상태 제거는 과거 개별 거래의 P2 근거 검토나 여행 귀속 재검토 완료를 뜻하지 않는다. 이전 “전체 classified이므로 P2 완료” 설명의 근거 한계를 유지한다.
- 검증: 초기 분류/과거/OTA/정리71 passed, 신규 조회 회귀 포함 최종 과거/분류54 passed, 추가 legacy/manual 환불3 passed. 인접 여행/카탈로그/규칙/항공/owner60 passed, CardFlow 표적16 passed/3 subtests, pipeline/부분환불/회사비용79 passed, 최종 환불 원자 기록12 passed, 취소 정산/환불UI9 passed. 실행 간 중복은 합산하지 않는다. OTA history 실패1건은 기준f96cd8f에서도 동일 재현했고 통과로 세지 않았다. Python compile·diff·staged metadata guard 차단0/삭제0. 전체 회귀·실기기/인증 owner 화면은 미실행이다.
- 배포: 검수 tree와 merge tree 동일·1112 Git blobs 불일치0·새 백업/별도 복원·task/process SHA·단일loopback listener·health/ready200·보호API/카드 summary/years401·보호13표 불변·Board/SourceRefresh Running. 호스트 venv의 합성 과거/legacy 분류·일반 추론 동일성·기간 필터·원본/금액/ID 불변·장부 쓰기0 확인. 최초 합성 도구의 잘못된 import는 public app.Pipeline으로 교정 후 통과했다. 존재하지 않는 과거 인계의 테스트 파일은 수집 실패로 남기고 실제 환불 검사로 검증했다.
- 근거: `.local-archive/remove-preserved-20261029/`의 checkpoint/XML/runtime_smoke/card-auth-smoke와 `.local-archive/deploy-3c8c970da271b665feb99a89fad661b7399ef6d7/`, 호스트 동일SHA release-audit/deploy-evidence. 기존 공유 workspace·사용자 변경 보존. 현재 상태 제거 요청의 남은 작업·차단0, 다음 명령 없음. 문서 후속만으로 재검사·재배포·재시작하지 않는다.

## 2026-10-29 보존 카드 분류 완료·지출 정리 목록 표시 수정·운영 배포

- COMPLETE — 과거 보존 카드 3,653건의 분류 완료와 지출 정리 조회 조건 보완을 완료했다. [PR #351](https://github.com/6Soo/cost/pull/351), 구현 `0f97623ad4b4e1d5b0e4776c67b8769b28a0a4d8`, 운영 SHA `f9b71d2f2b6a749fd6137855d7e4ff0582c68bbb`.
- 과거 유효 여행 기간 밖의 보존 거래는 현재/미래 여행으로 억지 배정하지 않고 `등록된 유효 여행 없음 · 비용 항목 분류 완료`로 보존 완료했다. 검증된 원결제의 분류를 상속한 환불 행도 재추론을 건너뛰도록 보호했다.
- 지출 정리(`_cleanup_card_where`) 조회에서 완료 정책(`complete-card-inference-v1`) 또는 원결제 상속(`refund_original`)으로 완료된 정상 분류 행을 제외했다. 항목 누락·구문 오류·충돌 사유·명시적 사용자 보류(`transaction_review_holds`)가 있는 거래는 정리 목록에 계속 표시한다.
- 검증: 표적 및 보호 테스트 37 passed (`test_card_cleanup_queries.py`, `test_automatic_classification_completion.py`, `test_refund_group_commit.py`), UI 9 passed (`test_card_cleanup_ui.py`). 실운영 DB(6,395건 전체 `classified`) 조회 검증 결과 정리 대상 카드 3,695→0건, 보류 4건 안전 보존 확인.
- 배포: 1,112 Git blobs 일치(불일치 0), 새 백업(`operational-20261029T122609435227Z`, `v2-owner-ui-20261029T212558`) 및 복원 검증(`restore-evidence.json`), task/process 고정 SHA 일치, 단일 loopback listener, health/ready 200, 보호 API 401, 보호 13개 테이블 내용/스키마 불변(`protection-after.json`). WebLedger-Board 및 WebLedger-SourceRefresh Running 정상 확인. 이전 검증 릴리스 `160f4cd93301b469183c6c243f98ab2a2ad2effc` 및 복구 사본 보존. 신규 금융/Google/은행 쓰기 0.
- 근거: `.local-archive/deploy-f9b71d2f2b6a749fd6137855d7e4ff0582c68bbb/`의 review.json, gate-before.json, protection-before.json, protection-after.json, deploy-evidence.json 및 `D:/WebLedgerHost/releases/deploy-evidence-f9b71d2f2b6a749fd6137855d7e4ff0582c68bbb.json`.

## 2026-10-29 전체 화면 내부 설명 정리·카드 행 정렬

- COMPLETE — 사용자 “모든 페이지 전체에 있는 이런 내부 문구 모두 삭제”와 직전 모바일 정렬 교정을 이어서 완료했다. [PR #343](https://github.com/6Soo/cost/pull/343)·[PR #347](https://github.com/6Soo/cost/pull/347), 문구 최종 검수 `ab4fa61e76eb220533fa07369b6ab5f35123fa09`, 운영 SHA `160f4cd93301b469183c6c243f98ab2a2ad2effc`.
- 카드 목록·지출 정리·장부 상세/원천 미리보기·여행·OTA·예약 연결·계정·항공권·영수증·검토 화면의 반복적인 원행/보존/읽기 전용/기장 분리 설명과 revision·digest 안내를 정리했다. 장부 저장 성공은 “저장했습니다”로 표시한다. 거래별 오류/보류·원본 정보·금융 상태·확인/전송 동의·hidden revision 및 동시 수정 보호는 유지한다. 모바일 가맹점 버튼의 공통44px 높이를 해제해 이름과 카드 정보를 붙이고 셀을 위로 정렬한다.
- 검증 archive: 카드/모바일28 passed(320/390/600/759/760/1280·두 테마·200% 확대·행64px 이하·이름/카드 간격3px 이하·가로 넘침/펼침/스피너). 화면 묶음130 passed/40 subtests, 보호 경계91 passed. 삭제한 설명을 요구하던 source/refund 검사는 새 계약으로 교정했고 source/refund/장부 인접76 passed. 이후 저장 문구/규칙 대화13개 검사는12+모바일 저장1 passed. 실행 간 중복이 있어 전체 합계로 세지 않는다.
- 기존 실패: 증거UI schema2건·OTA snapshot/정리3건(폭별 subcase 포함5)은 기준 `fa087d3` archive에서도 재현했다. 결합 fixture 순서로 발생한 cleanup/OTA4건은 독립 검사3 passed/2 subtests로 확인했다. 테스트 보호를 완화하지 않았고 기존 실패를 통과로 세지 않는다. 전체 회귀·운영 owner 화면·Safari/실기기 수락은 미실행이다.
- 배포: 변경 blobs 병합본 일치·1112 Git blobs 불일치0·호스트 Python 합성 원본 상세/이스케이프/마스킹/펼침/스피너/DB불변 PASS. 새 백업·별도 복원·task/process 고정SHA·단일loopback listener·health/ready200·보호API/카드/상세/규칙 URL401·보호13표 내용/스키마 불변·Board/SourceRefresh Running. 이전 검증 `297a5ef0f0a882314f65c0372492d4886e6e2820`과 복구 사본 보존. 실제 고객 금융/분류/여행/Google 쓰기·마이그레이션0.
- 근거: `.local-archive/internal-ui-copy-20261029/`의 checkpoint·검증 archive/XML·baseline-output 및 `.local-archive/deploy-160f4cd93301b469183c6c243f98ab2a2ad2effc/`와 호스트 동일 SHA release-audit/deploy-evidence. 기존 workspace 브랜치/사용자 변경/미추적 파일 보존. 현재 승인 범위의 미결·차단0, 다음 명령 없음. 후속 문서만으로 검사·재배포·재시작하지 않는다.

## 2026-10-29 최신 사용자 원칙 — P1 확대·P3 최소화

- 문서 반영 COMPLETE: P1 코드 자동처리 → P2 AI 추론 분류 → P3 사용자 개입. 목표는 P2/P3 처리·교정 사례를 검증 가능한 P1 규칙으로 축적하고 P3를 최대한 줄이는 것이다. 정본은 [P1/P2/P3 실행 원칙](specs/finance.md#p1-p2-p3-20261029), 에이전트 진입점은 AGENTS.md와 시작 안내다.
- 기존 자료·이전 답변·계산·추론으로 해결할 일을 사용자에게 넘기지 않는다. 사용자만 가진 필수 사실·권한·본질적 정책 결정만 구체적으로 묻는다. 승인된 업무 계약 안의 코드화·검증에 형식적 규칙별 승인을 추가하지 않는다. 반례·보호 검증 후 재사용하고 P2 추론을 사용자 답변으로 기록하지 않는다.
- 이번 변경 범위는 문서4개다. diff·링크/명시 앵커·상태 선언·실제 참조 경로를 확인한다. 코드 구현·과거 자료 재처리·운영 반영을 완료한 것으로 보고하지 않으며 코드 테스트/빌드/브라우저/운영 DB/백업/배포/재시작은 수행하지 않는다. 새 구현 큐를 과거 ACTIVE 문서에서 가져오지 않는다.

## 2026-10-29 남은20건 분류 정리·취소 정산 표시·운영 반영

- 분류/일반 지출정리/코드배포 COMPLETE, 실제 환급 확인은 별개다. 사용자는 기존22묶음 처리 후 남은20건도 처리하라고 지시했다. 잔액40,000원의 수수료 여부와152,358원의 실제 환급을 사용자에게 먼저 물은 것은 불필요했으며, 확인된 원행과 미확인 사실을 구분해 자율 처리하는 것으로 교정했다. 이를 사용자가 개별 환급을 확인한 것으로 기록하지 않았다.
- [PR #344](https://github.com/6Soo/cost/pull/344), 구현 `1a552ba`, 운영 SHA `297a5ef0f0a882314f65c0372492d4886e6e2820`. 환불 화면에 명시적으로 분류 검토된 미연결/비영점 취소 정산 목록을 추가했다. 기존 전액상쇄 묶음과 중복 표시하지 않고 원문 링크·검토 근거·미기록/실제 환급 구분·기존 금융 보류를 표시한다. 조회는 쓰지 않는다.
- 실제 반영: 정상 카드 결제1,345,388원1건만 기존 범위 제한 preview/commit/project 경로로 장부 기록했다. 원문이 미매입/취소인17건은 `취소·환불`/refunds로 분류하고 대응 원결제 미확인·장부 미기록을 명시했다. 취소 예약2건도 refunds로 분류하되 기존 cancelled 보류2건을 삭제하지 않았다.395,000원 원결제/355,000원 카드 취소의 잔액40,000원은 성격 미확인으로,152,358원은 대응 카드 환불 미확인으로 표시한다.19건의 새 장부/환불 링크·Google/은행 쓰기는0이다.
- 원문/금액/ID·기존 장부/사용자 변경·금융 보류/링크·스키마/범위 밖 표 보존,19건 분류는 기존 save_decisions_atomic로 원자 반영했다. note에는 에이전트 원문 검토와 사용자 개별 환급 확인 없음, 규칙 재사용 없음, 보류 유지 사실을 남겼다. 단건 장부와19건 분류를 하나의 전체 트랜잭션으로 처리했다고 주장하지 않는다. 동일 요청 분류 재생/단건 재실행 무쓰기 확인.
- settlement/read-only/escaping/기존refund-tab/inline21 passed. 빈DB 호환 검사를 교정한 최종 통과 근거다. merge tree 동일·metadata2파일 차단0/삭제0·1112 blobs 일치. 코드 배포 새 백업/별도 복원·task/processSHA·단일listener·health/ready200·보호API401·13표 불변. 자료 적용의 복구 사본 재사용 검사는 원본 상태 불일치로 거부됐으므로 새 백업/별도 복원 후 오프라인·동일 상태/digest 리허설과 실제 적용을 통과했다. 전체 회귀/실기기 검사는 미실행이다.
- 인증 Aside `/import`의 일반 지출정리20→0건과 `/board?tab=refunds`의 **취소 정산 확인 중19건**을 실제 확인했다. 이는19건의 원결제 연결·기장·실제 환급 완료를 뜻하지 않는다. 원결제/추가 카드 취소 등 새로운 증거가 들어오면 금융 보호를 다시 검증해 처리한다. 추가 사용자 사실 질문/승인 대기는 두지 않는다. Board/SourceRefresh Running·health/ready 정상 복구.
- 근거: `.local-archive/remaining20-20261029/`의 audit/ready-rehearsal/applied/checkpoint, `.local-archive/deploy-297a5ef0f0a882314f65c0372492d4886e6e2820/`, 호스트 동일SHA release/deploy audit 및 `D:/WebLedgerHost/data/backups/remaining20-20261029T191324616/`의 backup-restore/rehearsal/applied. 기존 사용자 workspace 변경 보존. 현재20건 분류·배포의 다음 명령 없음; 향후 금융 확인은 위 새 근거가 재검토 조건이다. 문서 후속으로 재검사/재배포/재시작하지 않는다.

## 2026-10-29 카드 모바일 5항목 — 구분선·폭·원본 상세·펼침·스피너

- 5항목 모두 COMPLETE — [PR #340](https://github.com/6Soo/cost/pull/340), 검증 구현 `78469c2c8102f7726d026faec39fbab08b7fa745`, 운영 SHA `6b63f78b8779c97a6f9066e03d0b26dc9803b721`. 행 구분선을 제거하고 모바일 최소380px/데스크톱560px을 없애 실제 가용 폭에 맞춘다. 긴 내용은 줄바꿈하며 표와 페이지 모두 가로 넘침이 없다. 행/가맹점 버튼은 별도 페이지 이동 대신 바로 아래 상세를 열고 닫는다. 로딩 스피너·실패/지연 안내·재시도·Enter/Space/Escape·aria-expanded/busy·텍스트 선택·기존 환불 링크를 보존했다. 기간/검색 제출 및 일반 링크 이동도 스피너로 표시하며 뒤로가기 복귀 시 해제한다.
- 장부행 전용 `card-…` 링크 때문에 원본만 있는 거래가 “없는 거래예요”로 표시되던 원인을 수정했다. `/api/cards/transactions/detail?id=…`는 원본 카드 고정 필드를 mode=ro·파라미터 SQL로 읽고 escaped HTML/no-store를 반환한다. 비로그인401·직원403을 원본 조회 전에 적용한다. 기존 장부 URL도 원본이 존재하면 소유자에게 읽기 전용 상세를 보여준다. 원본/금액/배정/분류/환불/Google/스키마는 쓰지 않는다.
- 정확한 통합 Git archive에서 카드·모바일·원본 상세·환불 목적지·조회 API·실제 HTTP 권한 86 passed, 별도 인접 환불12 passed. 320/390/600/759/760/1280·두 테마·200% 확대·열림 전후 표/페이지 가로 넘침 부재·행 경계0·대기 스피너·실패 후 재시도·원본 전후 dump 동일성·카드 마스킹/HTML escape·원본 전용 과거 URL 수락. 전체 회귀·인증 운영 owner 화면/실기기는 미실행이다.
- 병합 tree 동일·1111 Git blobs 불일치0·운영 Python 합성 smoke PASS. 별도 환불 세션의 승인된 작업이 종료된 뒤 새 보호 상태를 기록해 순차 배포했다. 새 백업/별도 복원·task/process 고정SHA·단일loopback listener·health/ready200·보호API 및 상세/카드 URL401·보호13표 내용/스키마 불변, Board/SourceRefresh Running. 이전 검증 릴리스와 복구 사본을 보존했다. 이 UI 작업에서 운영 금융/여행/분류/Google 쓰기·마이그레이션·재처리0이며 별도 세션의 금융 작업과 구분한다.
- 근거: `.local-archive/card-inline-details-20261029/`의 checkpoint/통합 archive/합성 이미지, `.local-archive/deploy-6b63f78b8779c97a6f9066e03d0b26dc9803b721/`의 review/runtime-smoke/auth-smoke/protection-before/protection-after/deploy-evidence 및 호스트 동일 SHA release-audit/deploy-evidence. 기존 사용자·다른 작업 변경/미추적 파일 보존. 현재 5항목의 남은 작업·차단0, 다음 명령 없음. 후속 문서만으로 검사·재배포·재시작하지 않는다.

## 2026-10-29 전액 상쇄 환불 22묶음 실제 기록·부분 기기록 오류 수정

- COMPLETE — 사용자는 읽기 전용 점검 후 실제 수정·운영배포를 지시했다. [PR #339](https://github.com/6Soo/cost/pull/339), 구현 `02cb163`, 운영 SHA `8b91aeb622106af38935dce49da4c10bb7ddc37e`. 검증된 전액상쇄 묶음에서 실제 장부가 있는 행의 파생 `existing_ledger` 보류만 제외한다. 빠진 반대편을 기록하며 장부 없는 legacy 투영·수동/금융 보류·원본/중복/초과환불·인증/CSRF 보호는 유지한다.
- inline/cross-batch/refund-inference 44 passed. 부분 기기록 양 방향과 legacy 보호 회귀를 포함한다. 새 요청 ID의 검증 성공 재생은 현재 계약대로 `applied=0`/금융행 불변으로 교정했다(종전 테스트 실패는 기준 main 재현). merge tree 동일·metadata2파일 차단0/삭제0·1110 Git blobs 일치. 코드 배포의 새 백업/별도 복원·task/processSHA·단일 loopback listener·health/ready200·보호API401·13표 불변을 확인했다. 전체 회귀/실기기 검사는 국소 서버 경로 변경으로 미실행이다.
- 실제 기록: 기존 점검의 현재 목록22묶음/46원행만 대상으로 전체 미기록20묶음과 일부 기기록2묶음의 빠진44행을 기존 commit/project 경로로 기록했다. 각 묶음은 원자 기록, 기존 장부행 불변·순액0·원본/금액/ID/사용자 결정·범위 밖 표/보존237묶음·스키마 보존 및 재요청 무쓰기를 확인했다. Google/은행 환급 쓰기는0이며 분류 전면 재처리는 하지 않았다.
- 새 백업/별도 복원·복사본44행 리허설·단일 작성자·동일 상태/preview digest 일치 후 실제 적용했다. 초기 리허설은 SQLite 자동증가 카운터를 범위 밖 표로 본 검증 오류로 실제 쓰기 전에 중단했고, 승인된 append 표의 카운터 증가만 허용하도록 고쳤다. 수정 후 리허설·실제 검증 모두 통과했다. 당시 서비스는 finally로 정상 복구했으며 실패를 성공으로 계산하지 않았다.
- 최종 readonly audit `total_changes=0`: 현재 지출정리 카드48→20행, 대상 전액상쇄28행/22묶음은0. 실제 인증 Aside `/import`에서도20건·미분류0·미배정0·보류오류19/기타검토1을 확인했다. 남은20건은 원결제 미연결/별도 금융·예약 보류 등 이번22묶음 밖이며 전체 대기열 완료로 보고하지 않는다. Board/SourceRefresh Running·health/ready 정상 복구.
- 근거: `.local-archive/refund-zero-audit-20261029/`의 audit/preflight/rehearsal/applied/after/checkpoint, `.local-archive/deploy-8b91aeb622106af38935dce49da4c10bb7ddc37e/`, 호스트 동일 SHA release-audit/deploy-evidence 및 `D:/WebLedgerHost/data/backups/refund-zero-20261029T185028294/`의 backup-restore/rehearsal/applied. 이전 검증5297a0d와 복구 사본 보존. 현재22묶음 승인 범위의 남은 구현/배포/자료반영·차단0, 다음 명령 없음. 후속 문서만으로 재검사/재배포/재시작하지 않는다.

## 2026-10-29 카드 목록 배정·분기·취소환불 문구 정리

- COMPLETE — [PR #336](https://github.com/6Soo/cost/pull/336), 구현 `e141289640e92409c3a9312c5f11bc991e4247b9`, 운영 SHA `5297a0daee012809f17dfb0d045283284f9b977e`. 카드 목록 열 제목을 `배정`으로 줄였다. 분기 배정은 내부 ID 대신 `2026년 3분기 기타비용`처럼 표시하며 내부 ID/title은 보존한다. 취소·환불 목록의 반복 부연 설명을 제거하고 기존 링크를 유지했다. 앞선 인계의 “quarter는 내부 ID이고 이미 분기로 표시” 설명은 카드 목록의 fallback 경로를 누락했으므로 이 기록으로 교정한다.
- 정확한 구현 archive의 카드·모바일·환불 목적지 34 passed. 320/390/600/759/760/1280·두 테마·200% 확대·행/환불 링크·원본 불변 검증 포함. merge tree 동일·1110 Git blobs 불일치0·운영 Python의 분기1~4/연도·배정 제목·환불 링크·원본 불변 smoke PASS. 인접 장부 UI 실패6건은 기준 main에서 재현해 범위 밖으로 유지했다. 결합 검사에서 분기 브라우저 임시 DB 정리 실패1건이 있었으나 기준 main 독립 실행에서는 통과했다. 전체 회귀·실제 owner 화면/실기기는 미실행이다.
- 새 백업/별도 복원·task/process 고정SHA·단일loopback listener·health/ready200·보호API401·금융/사용자13표 내용/스키마 불변 확인. Board/SourceRefresh Running. 이전 검증 `78cb6ad4a7ead4ecaff39671eb0a32090b4c8021` 보존. 실제 분류/금융/여행/Google 쓰기·마이그레이션·재처리0.
- 근거: `.local-archive/card-assignment-label-20261029/`의 checkpoint/baseline-failures 및 `.local-archive/deploy-5297a0daee012809f17dfb0d045283284f9b977e/`의 review/runtime-smoke/auth-smoke/protection-before/protection-after/deploy-evidence, 호스트 동일 SHA release-audit/deploy-evidence. 기존 사용자·다른 작업 변경과 미추적 자료 보존. 현재 요청의 남은 구현/배포·차단0, 다음 실행 명령 없음. 후속 문서만으로 테스트·재배포·재시작하지 않는다.

## 2026-10-29 카드 3820 자동분류 충돌 수정·운영 배포

- COMPLETE — [PR #335](https://github.com/6Soo/cost/pull/335), 수정 `dc2aaf3`, 운영 SHA `78cb6ad4a7ead4ecaff39671eb0a32090b4c8021`. 공통 자동분류에도 기존 3820 정책을 적용한다. 2026-09-19~24 유효한 싱가포르 여행 하나를 우선하고, 나머지 국내 매입은 거래일의 분기 기타비용으로 분류한다. 사용자 결정·완료 행과 해외/날짜 불명/취소·환불 보호를 유지한다.
- 정확한 배포 archive에서 자동분류 완료·3820 Singapore/residual/reconcile 38 passed. 운영 Python 합성 smoke 5개 PASS(2025년 거래→2025년 4분기 포함). 운영 venv에는 pytest가 없어 개발 Python으로 archive를 검사했다. 최초 stdin smoke는 PowerShell 한국어 전달 손실로 실패했으며 UTF-8 파일 실행으로 교정했다. 이전 인접 34 passed 근거는 재사용했고 전체 회귀·실제 owner UI·실자료 재분류는 미실행이다.
- 1110 Git blobs 불일치0·새 백업/별도 복원·task/process 고정 SHA·단일 loopback listener·health/ready200·OTA/환불/2025 카드 조회 비인증401·보호13표 내용/스키마 불변. Board/SourceRefresh Running. 이전 검증 `dccd3af6d12a52a3f9eb50a647979527ac5cc1f7`과 복구 사본 보존. 실제 분류/여행/금융/Google 쓰기·마이그레이션·대량 재처리0.
- 근거: `.local-archive/card3820-deployment-20261029/`의 checkpoint/runtime-smoke/auth-smoke, `.local-archive/deploy-78cb6ad4a7ead4ecaff39671eb0a32090b4c8021/`와 호스트 동일 SHA release-audit/deploy-evidence. 기존 사용자 변경·미추적 파일 보존. 현재 요청의 남은 구현/배포·차단0이며 다음 명령은 없다. 후속 문서만으로 검사·재배포·재시작하지 않는다.

## 2026-10-29 최신 요청 — 원승인번호 없는 취소·환불 쌍 인정

- 사용자 지시: 원승인번호는 취소·환불 쌍의 필수조건이 아니다. 동일 발급사·카드·가맹점·이용일·동액의 상호 유일 대응과 기존 카카오 계열/14일·외화 대응을 연결 완료로 인정한다. 자동 출처와 대조 근거를 표시하고 원승인번호 부재만으로 기록을 막지 않는다.
- 구현: 원화 유일 대응의 `inferred` 보류를 해제하고 승인번호와 독립된 대조 근거를 표시한다. 수동 보류 사유가 묶음 보류로 덮이지 않도록 보존한다. 원본·중복·후보 경합·점유·초과환불·불완전 묶음·원자 기록·재기록 보호를 유지한다. 양수 원행 없는 미매입 취소는 연결하지 않는다.
- COMPLETE — [PR #332](https://github.com/6Soo/cost/pull/332), 운영 SHA `dccd3af6d12a52a3f9eb50a647979527ac5cc1f7`. 검수 소스 `558712946f499a0b12a7523acd0d4faae15cdcbf`와 merge tree 동일. 핵심144·환불 UI/원자성/owner/cross-batch89·CardFlow3·카드 목적지6, 서로 다른 표적242 passed. 기존 baseline 비교2건 및 inline stale 기대1건은 기준d753f45에서도 실패해 제외했다. 전체 회귀·실제 owner 화면 수락은 미실행이다.
- 배포:1110 Git blobs 불일치0·새 백업/별도 복원·task/process SHA·단일loopback listener·health/ready200·보호API401·금융/사용자13표 내용/스키마 불변. 호스트 Python 배포본의 원승인번호 없는 유일 대응·조회 원본 불변·합성 원자 기록 smoke PASS. 이전 검증de2aada와 복구 사본을 보존한다. 실제 고객 DB 분류/기장·Google/은행 환급 쓰기·대량 재처리·스키마 변경0. 근거는 `.local-archive/refund-reference-optional-20261029/`와 `.local-archive/deploy-dccd3af6d12a52a3f9eb50a647979527ac5cc1f7/`, 호스트 동일SHA deploy-evidence/release-audit다. 구현/배포 남은 작업·차단0이며 후속 문서만으로 재배포·재시작하지 않는다. 다른 UI 병렬 변경은 보존했다.

## 2026-10-29 최신 요청 — 카드 행 상세·배지 제거·날짜와 폭 압축

- 현재 범위는 ‘원본 보존’ 표시 제거, 상세 버튼/열 제거 후 행 클릭으로 상세 이동, 셀 간격과 전체 폭 축소, 선택 기간과 중복되는 날짜 제거다. 날짜는 연도 조회 `3월 5일`, 월 조회 `5일`이며 시간은 붙이고 원본/title은 유지한다. 이전 원본 보존 배지·상세 열 유지 검사는 대체한다.
- COMPLETE — [PR #331](https://github.com/6Soo/cost/pull/331), 운영 `de2aada07320de57aee6935c7617f6d3102f017a`, 검수 소스 `4e8588a58eb262a2206fd5a7ce13a1bfe48f5292`와 merge tree 동일. 표4열·고정 열 폭·모바일 최소380px·셀5/4px, 중복 날짜 접두사 생략을 적용했다. 행의 날짜/금액/여행 셀 클릭은 기존 상세 URL로 이동하며 가맹점 이름의 실제 링크로 키보드/새 탭/JavaScript 없는 탐색을 유지한다. 환불 링크는 독립 동작하고 텍스트 선택 중에는 행 이동을 하지 않는다. 원본 보존은 내부 상태 그대로이며 배지만 제거한다.
- 최종 커밋 Git archive에서 카드/필터/환불 목적지/브라우저43 passed(동시 편집 중인 별도 금융 변경 제외).320/390/600/759/760/1280·두 테마·200% 확대·행 클릭/키보드·환불 독립 링크·텍스트 선택·날짜/title·원본 날짜 불변·표 폭 검증. 초기 신규 날짜 검사 의존성은 표준 re로 교정했다. compile/diff·metadata6파일 차단0/삭제0. 실제 인증 owner 화면/실기기·전체 회귀는 미실행이다.
- 1110 Git blobs 불일치0·새 전체 백업/별도 복원·task/processSHA·단일loopback listener·health/ready200·보호 API/연월/상세/환불URL401·금융/사용자13표 내용/스키마 불변. 배포본/호스트 Python의 단일 연월·4열/380px·배지/상세 열 부재·행 링크/스크립트·한국어 날짜/title·환불 링크·원행 불변 합성 smoke PASS. Board/SourceRefresh Running. 이전 검증 `537aa3bca7cec79debad4db92d67e94baa6934e6` 및 복구 사본 보존.
- 근거는 `.local-archive/card-row-navigation-20261029/`의 checkpoint/validation-source/runtime-smoke/auth-smoke와 합성 이미지·검증 archive, `.local-archive/deploy-de2aada07320de57aee6935c7617f6d3102f017a/`의 review/protection-before/protection-after/deploy-evidence, 호스트 동일 SHA release-audit/deploy-evidence다. 실제 DB/분류/금융/여행/Google 쓰기·스키마 변경0. 기존 사용자/다른 작업 변경 보존, 남은 구현/배포 작업·차단0. 후속 문서만의 변경에 검사/배포/재시작을 반복하지 않는다.

## 2026-10-29 최신 요청 — 카드 모바일 UI·연월 선택 통합

- 현재 승인 범위는 카드 전체 내역 모바일 개선과 누락됐던 월별 카드 제거·연월 선택 통합이다. 최신 교정은 **단일 거래 카드가 아닌 이전 표 방식 유지·내용 압축·간격 축소**다. 월 타일 유지와 모바일 세로 카드 검사는 이번 사용자 지시로 대체한다.
- COMPLETE — [PR #329](https://github.com/6Soo/cost/pull/329), 운영 SHA `537aa3bca7cec79debad4db92d67e94baa6934e6`, 검수 소스 `6f581aa3dd12e2a1797e24c8243068def6f77ae3`와 merge tree 동일. 월별 카드와 별도 연도 폼을 제거하고 단일 조회 기간 선택에 `2026년 전체 / 2026년 1월 …`을 제공한다. 기간 변경/검색 제출 시 카드·검색어·미배정 조건을 함께 보낸다. 연도 전체도 검색어 없이100건씩 즉시 조회하며 기존 year/month 링크·커서와 조회 API를 유지한다. 결과는 조회 조건 바로 아래에 나온다.
- 759px 이하도 실제 표/행/열 헤더를 유지한다. 최소 폭560px·셀 여백6/8px·글자12px·간격1.35, 이름 두 줄 압축·원문/title 보존·중복 날짜 그룹 숨김·표 내부 가로 스크롤을 적용했다. 부호/통화·여행/취소환불 상태·상세 링크와 검색/선택 입력16px·접이식 안내를 유지한다.
- 최신 표 구현의 카드/필터/환불 목적지/모바일42 passed. 실제 Chromium에서320/390/600/759/760/1280폭·두 테마·200% 확대·키보드 포커스에 의한 표 스크롤·긴 이름/title·환불 링크·행 높이110px 이하·페이지 가로 넘침 부재를 검증했다. 최종 합성 PNG는 `.local-archive/card-history-compact-table-20261029/`에 보존한다. 실제 인증 화면/실기기·전체 회귀는 미실행이다.
- 중간 릴리스 PR #328/`b933bdd84cf79d6c64e6f1d5093bc8b648865c7a`는 새 백업/별도 복원·1110 blobs 일치·health/ready200·보호API401·보호13표 불변으로 배포됐지만, 세로 카드이므로 최신 표 요청의 완료로 계산하지 않는다. 현재 표 구현을 검증 후 후속 배포한다.
- 최종 배포 수락:1110 Git blobs 불일치0·새 전체 백업/별도 복원·task/process SHA·단일 loopback listener·health/ready200·OTA/환불/연월 조회 URL 보호401·금융/사용자13표 내용/스키마 불변. 호스트 Python으로 실제 배포본의 압축 표 CSS·단일 연월 선택·연도/월 목록·월 타일 부재·환불 링크·원행 불변 합성 smoke PASS. Board/SourceRefresh Running. 이전 검증b933bdd 복구점과 백업 보존.
- 근거는 `.local-archive/deploy-537aa3bca7cec79debad4db92d67e94baa6934e6/`의 review/protection-before/protection-after/deploy-evidence, `.local-archive/card-history-compact-table-20261029/`의 checkpoint/runtime-smoke/auth-smoke와 호스트 동일 SHA release-audit/deploy-evidence다. 실제 DB/분류/여행/금융/Google 쓰기·재처리·스키마 변경0, 기존 사용자 변경 보존. 남은 구현/배포 작업·차단0. 후속 기록은 문서만 변경하므로 검사/배포/재시작을 반복하지 않는다.

## 2026-10-29 최신 승인 — 원본 보존·취소/환불 표시 교정

- 사용자 질문 후 “ㄱ”으로 승인한 표시 수정과 운영 배포 범위다. 카드 원행·분류·여행·금융/Google 값은 쓰지 않는다.
- COMPLETE — [PR #326](https://github.com/6Soo/cost/pull/326), 운영 SHA `558c55e445902ebf0cc7e9031f88bd25e88794f8`, 검수 소스 `b6b2e4b28d3fdf75fced1fc5f503b2cd7b51c18d`와 tree 동일. 기존 환불 연결의 순액 0원 묶음을 카드 목록의 여행 미배정보다 우선 표시하고 취소·환불 탭으로 연결한다. 동일 묶음은 미배정 필터/건수에서 제외한다. 보존 기간이라는 이유만으로 읽기 전용 환불 이력을 숨기지 않는다. 원본 보존의 의미와 실제 환급/장부 기록의 구분을 안내한다. 부분환불·초과환불·원본 충돌·원결제 중복의 기존 경계를 유지한다.
- 표적 카드 88 passed, 환불/원자 기록 보호 24 passed. 초기 결합 수집의 schema=require 설정과 환불 fixture 충돌은 pytest 프로세스를 분리해 해소했다. 전체 회귀·실제 owner 화면 수락은 미실행. `.local-archive/card-refund-destination-20261029/checkpoint.json`에 범위·검증·다음 단계를 기록했다.
- 배포 수락: 1,109 Git blobs 불일치0, 새 전체 백업·별도 복원, task/process 고정 SHA·단일 loopback listener·health/ready200·보호 API401·보호13표 내용/스키마 불변. 호스트 Python의 실제 배포본 합성 smoke에서 보존 기간 전액 상쇄 그룹·카드 링크·검색·미배정 필터/건수·원행 불변을 확인했다. 이전 검증 `9db468d42333979862b961fa26c822eb66260257` 복구점과 백업을 보존한다.
- 실제 금융/분류/여행/Google 쓰기·마이그레이션·재처리0. 기존 사용자 미커밋/미추적 파일 보존. 배포 근거는 `.local-archive/deploy-558c55e445902ebf0cc7e9031f88bd25e88794f8/` 및 호스트 동일 SHA deploy-evidence/release-audit, 영향 경로 근거는 `.local-archive/card-refund-destination-20261029/runtime-smoke.json`, `auth-smoke.json`이다. 남은 구현/배포 작업·차단0. 이 후속 문서만으로 테스트·재배포·재시작을 반복하지 않는다.

## 2026-10-29 최신 결정 — 개별 검토 재발 방지와 재개점

- 실행 정본은 [개별 거래 검토 실행 계약](specs/finance.md#review-execution-contract-20261029)과 AGENTS.md다. 근거로 결정 가능한 변경은 재승인 없이 처리한다. 소수 여행 이동은 변경 전 값·revision/이력으로 되돌리고, 별도 전체 백업·복원 리허설·서비스 중지를 기본 절차로 사용하지 않는다. 아래 토와다소2건의 백업/중지는 **실제로 수행했던 과도한 절차의 기록**이며 이후 단순 이동의 의무가 아니다.
- 완료: 기존 북큐슈 카드2건은 예약 연결·내부 장부 기록까지 반영됐다. 아오모리는 Google 현재1103(11/3~8)으로 통합했고 기존18개 장부/15개 화면행을 이동했다. 토와다소230,106원 및 추가2건920,509원은1103·숙박비 교정 완료다. **추가2건은 금융 링크/장부 추가 쓰기0**이며 예약 유지 여부를 사용자가 직접 확인한 것으로 쓰지 않는다. 메일 파서 수정은PR #322/운영9db468d로 완료됐다.
- 마지막 조회에서 아고다625,280원과-625,280원은 같은 카드의 원승인번호로 기존 전액취소 연결을 확인했다. 트립닷컴122,224원과-122,224원도 원승인번호가 일치했고 토요코인 대구 동성로10/4~5 예약·9/24 취소 메일을 확인했다. 둘 다 순액0이며 추가 사실 질문은 없다. **이번 확인은 읽기 전용이고 새 장부 기록은 하지 않았다.** 이 두 묶음을 새로 기장한 것으로 완료 처리하지 않는다.
- 다음은 기존53건 개별 검토의 나머지이며 전체 완료 건수를 새로 계산하지 않았다. 마지막 기준/확인 건은 로컬 `.local-archive/trip-candidate-review-20261029/next-item.json`에 보존했다. 기존 정상 연결·완료 교정은 재질문하지 않고, 실제 기록 여부와 남은 다음 거래를 구분해 진행한다. 이번 문서화는 코드/운영 데이터 변경 없이 문서 diff·링크·경로/상태만 확인하며 테스트·백업·재배포·서버 재시작을 하지 않는다.

## 2026-10-29 최신 결정 — 판단 가능한 변경의 재승인 불필요

- 사용자는 근거/규칙 부족으로 필수 사실을 묻는 것과 단순 변경 승인을 구분하며, 후자는 필요 없다고 지시했다. 기존 승인·데이터 안전 게이트 안에서 판단 가능한 분류/여행 교정은 바로 처리한다. 이 결정은 실제 예약 유지·환급 완료를 사용자 확인 사실로 만드는 권한이 아니다.
- 호텔 토와다소의 같은날 카드 원행·인증 예약 사전승인액이 일치하는 추가2건(합계920,509원)을11/7~8 숙박 기간과 현재 Google 여행에 따라1103_아오모리·숙박비로 교정했다. 개별 유지 여부를 확인받았다는 근거는 남기지 않았다. 새 백업·별도 복원·복사본 리허설·두 번째 건 실패 시 전체 롤백·동일 요청 재실행 불변 수락 후 Board/SourceRefresh를 정지하고 기존 atomic review 경로로 적용했다. 원본/금액/ID/범위 밖 행/스키마·기존 이력 보존. Google/환급/금융 링크/장부 추가 쓰기0. 근거 `.local-archive/towadaso-correction-20261029/` 및 `D:/WebLedgerHost/data/backups/towadaso-correction-20261029T045227214813Z/`. 전체53건 완료를 의미하지 않는다.

## 2026-10-29 최신 승인 — 아오모리 일정 변경 통합·예약 메일 누락 방지

- **통합 운영 적용 COMPLETE:** 사용자 확인으로 1104 아오모리는 1103으로 변경된 같은 여행이다. Google 활성 원본 metadata의 `1103_아오모리`(sheetId 514604255)와 B2:H3 제목을 직접 읽어 **2026-11-03~08**을 확인했다. 현재 원본에는 1104 탭이 없다. COST의 현재 1103 여행으로 이전 장부18건/6,425,040원·화면15행을 이동하고 이전 1104 여행은 삭제 없이 보관했다. 검토 중 취소 숙박 카드1건도 사용자 수동 결정으로1103에 교정했다. 실제 환급 완료·Google 반영을 창작하지 않았다.
- 새 백업/별도 복원·실패 주입 전체 롤백·복사본 리허설 후 Board/SourceRefresh를 정지해 단일 작성자로 같은 트랜잭션을 적용했다. 원본/금액/ID/범위 밖 행·기존 교정/감사 이력·전체 스키마 불변, 감사 체인·integrity_check PASS. Board/SourceRefresh 재개 및 health/ready200 확인. 고객 원문·과거 결정 삭제0, Google/환불/OTA 연결 쓰기0. 사전 검증과 실제 적용 근거는 호스트 `data/backups/aomori-merge-20261029T042712496764Z/`의 rehearsal/apply JSON과 복원 사본, 로컬 `.local-archive/aomori-merge-20261029/`다.
- **예약 메일 수정 COMPLETE:** PR #322 구현 `babd4df`·운영 `9db468d42333979862b961fa26c822eb66260257`. 온라인 사전 결제 문구가 없는 숙박도 예약 기간을 보존하고 사전승인액을 별도 필드로 읽는다. 같은 날·정확한 금액의 정상 카드 후보를 진단하며 사전승인만으로 실제 결제/환급/금융 연결을 확정하지 않는다. 수신 날짜가 잘못된 인증 취소 메일도 취소 사실·환불 요청을 보존한다. parser9로 기존 snapshot을 무효화한다. 표적105 passed, 인접 추론/상태/API82 passed, 최종 후보 조건 단순화10 passed. 원래 문제의 보관 메일2건도 readonly로 재확인해 사전승인액/이용기간·취소 추출을 수락했다. 검수/병합 tree 동일,1108 blobs 불일치0·새 전체 백업/별도 복원·task/processSHA·health/ready200·보호API401·보호13표 불변. 배포본/호스트 Python 합성 smoke PASS, 재기동 후 통합18건/6,425,040원·15행·대상카드 교정 유지, Board/SourceRefresh Running. 초기 합성 smoke의 PowerShell 파이프 한글 손실은 UTF-8 파일 실행으로 교정했다. 전체 회귀·인증 운영 화면은 미실행이며 실제 재처리/Google/환급 쓰기0. 근거 `.local-archive/trip-preauth-deploy-20261029/`와 호스트 동일SHA 배포 JSON. 기존53건 전체 완료를 의미하지 않으며 남은 개별 건은 사용자 검토 흐름으로 이어간다. 이 문서 후속 병합에는 재배포하지 않는다.

## 2026-10-29 동일일·동액 OTA 연결 및 사용자 확인 2건 반영

- **COMPLETE:** 사용자 최신 승인으로 동일 결제일·동일 통화 원문 금액이면 카드 끝자리/결제 ID/승인 별칭 없이도 연결한다. 명시된 카드·공급자 충돌/중복/오류/점유/부분 묶음 보호는 유지한다. 원문 외화액만 있는 사용자 확인 연결도 원화액을 창작하지 않고 저장한다. PR #320 구현 `2b2ea98`, main/운영 `f60e1a7225f834445491cab34f846622ec9ba120`, matcher version4. 관련214 passed + 별도 snapshot/authority32 passed, 보호13표 배포 전후 동일, health/ready200·보호 API401·1108 blobs 불일치0·새 백업/별도 복원 수락.
- **2건 실제 완료:** 사용자가 확인한 Trip 숙박 결제 2건만 기존 북큐슈 여행의 숙박비로 수동 교정·예약 연결·내부 장부 기록했다. 각 거래/장부행1개, 원문/ID/카드 끝자리·외화/원화 금액 보존·schema/범위 밖 행 불변을 복사본과 운영에서 검증했다. 동일 조건 2:2의 예약번호/승인번호 안정 순서 배정임을 근거에 기록했으며 개별 대응 독립 증거로 꾸미지 않았다. Google/은행 환급 쓰기0. 이는 기존53건 전체 완료가 아니다.
- **끝자리 조사:** 카드 원행에는 끝자리가 정상 존재한다. 해당 예약 메일은 VISA만 표시하며 마스킹 번호/끝자리 자체가 없고 보관된 예약 상세에도 없다. 파서 누락으로 보고하거나 예약 원문에 카드 끝자리를 역주입하지 않는다.
- 실제 근거: `D:/WebLedgerHost/releases/deploy-evidence-f60e1a7225f834445491cab34f846622ec9ba120.json`, `D:/WebLedgerHost/data/backups/trip-confirm-20261029T041040263786Z/`의 rehearsal/apply-evidence 및 보존/복원 사본. 로컬 복사본은 `.local-archive/ota-same-day-amount-20261029/`. 최초 복사본에서 검토 API의 부수적인 테이블 생성을 발견해 운영 미적용했고 기존 스키마 경로로 재검증했다. 최초 운영 시도의 DELETE journal 전환 잠금은 금융 데이터 원복 확인 후 기존 journal 유지로 해결했다. 최종 Board/SourceRefresh Running 및 인증 Aside 카드 화면의 대상2건/새 여행/끝자리 표시를 수락했다.
- 후속: 이 최신2건 범위는 완료다. 남은 개별 거래 검토는 사용자와 이어가며 과거 queue/완료 보고를 새 승인으로 확장하지 않는다. 이전 인계의 환불 `4fbff06` 로컬 커밋은 이번 PR에 포함하지 않았고 이 기록만으로 배포 완료를 주장하지 않는다. 후속 문서 변경은 재배포하지 않는다.

## 2026-10-29 최신 요청 — 카드 검색 결과·금액 검색·배치

- 현재 범위는 검색 0건 안내, 금액 검색, 월 선택 없는 즉시 결과, 좁은 화면 필터 배치의 네 항목이다. 과거 금융/환불·전체 미결 큐를 이번 변경에 포함하지 않는다.
- 네 요구사항 모두 COMPLETE — [PR #318](https://github.com/6Soo/cost/pull/318), 운영 SHA `0c285e14bb87d4a843d1860159cc2be35ed2aa8a`. 검수 소스 `2989613f9e837c02bd353d19135f1eb79da013d5`와 병합 tree가 동일하다. 검색어가 있고 월이 없으면 해당 연도의 날짜 있는 거래를 100건씩 표시한다. 0건도 검색어와 결과 영역을 표시한다. 월 선택 상태는 해당 월의 검색 범위를 유지하고 날짜 확인 필요 목록은 기존 별도 경계를 유지한다.
- 원화/외화 금액의 쉼표 유무와 승인번호를 검색하며, 검색 결과도 여행명·미배정 표시·카드 마스킹·필터/커서 보존 규칙을 따른다. 검색창에 금액 검색을 안내하고 모바일 필터를 세로 배치한다.
- 검증: cards_all_filters/cards_all/card_transactions 81 passed와 신규 browser 선택기 오류 1 failed 후, 페이지 안의 별도 여행 검색창과 구별하도록 선택기를 한정해 해당 browser 1 passed/25 deselected. 합성 Chromium에서 검색 제출→즉시 1건→0건, 긴 여행명, 320/390/760/1280폭과 기존 확대 검사를 확인했다. DB 원행 전후 동일·연도/카드/미배정/페이지 경계 검사를 포함하며 전체 회귀는 범위 밖이다.
- 기존 브랜치의 미병합 환불 커밋과 미커밋 card_flow/OTA browser 수정·사용자 미추적 파일은 보존한다. 이번 검색 PR에는 포함하지 않는다. diff/compile·metadata guard5파일 차단0/삭제0, 정상 main 병합·고정SHA 배포 완료. 1,107 Git blobs 불일치0, fresh backup/별도 복원, task/processSHA·단일loopback listener·health/ready200·보호API/검색URL401·보호13표 전후 불변, Board/SourceRefresh Running을 확인했다. 배포본/호스트 Python 합성 smoke도 금액/외화/승인번호·즉시/0건·HTML escape·원행 불변 PASS다. 초기 합성 smoke의 임시 SQLite 정리 잠금은 연결 종료를 보완해 해소했다. 실제 owner 인증 화면/물리기기 수락·전체 회귀는 미실행이며 금융/Google 쓰기·재처리·마이그레이션0이다. 근거는 `.local-archive/card-search-20261029/`의 review/runtime-smoke/auth-smoke/protection-before/protection-after/deploy-evidence JSON 및 호스트 동일SHA release-audit/deploy-evidence다. 남은 검색 작업·차단0. 후속 문서만의 병합에는 재배포하지 않는다.


## 2026-10-29 최신 승인 — 이미지의 프로젝트 전체 미결을 Luna low 병렬 구현

- **DEPLOYED — PR #316:** 검수 소스 `a6b73ae5c01403c0ff41ea133bf0a9cec5100b0e`와 운영 `1beba48bdd4f0aa20999326689d7c766c921c576`의 tree가 동일하다.1,107 blobs 불일치0, 새 전체 백업/별도 복원, task/process SHA, 단일 loopback listener, health/ready200, 참가자 state/trip-panel·OTA groups 등 보호 API401, 금융/사용자13표 내용·스키마 불변을 실제 확인했다. Board/SourceRefresh Running. 직전 검증9b190e9 복구점 보존. 실제 분류/금융 재처리·명단 실전송·Google 쓰기·메일 원문 다운로드·마이그레이션0. 아래 미배포/다음 배포 표기는 이 수락으로 대체한다.
- **남은 실자료 경계:** latest manifest 재확인 `2026-10-29T01:58:27Z`도3,710 stored/48 pending/다음 페이지 있음/미완료다. 전환 재확인 조건은 pending0·다음페이지 없음·query없음·유효 last_complete 및 실제 원문/복원/단일 작성자 게이트다. 현재 보험 구성의 참가DB 파일 부재·실제 웹 프로세스 DB 동일성/등록 영수증·운영 화면 수락은 미해결이며, 실제 등록 영수증과 현재 연결 DB가 확인되면 readonly 진단으로 재개한다. 외부 결제 증빙 없는 Kakao 금융 연결을 창작하지 않는다. 보험 가입·결제·실명단 전송은 별도 기존 권한을 유지한다.
- **완료 범위와 미완료 구분:** 보험 재개 계약, 참가자 진단/CLI 불일치 보호, 전체 메일 전환 gate, 여행권위3메서드 분리, OTA 공통 스타일, 실패 진단 도구의 이번 구현은 병합/배포됐다. 전체 백엔드·전체 화면·전체 회귀·실제 참가자/수입 수락 완료를 의미하지 않는다. 기준8cfe391에서도 재현한 browser11 실패는 통과로 계산하지 않으며 후속 검수 기록으로 남긴다. 정확한 운영 근거는 `.local-archive/deploy-1beba48bdd4f0aa20999326689d7c766c921c576/`의 review/protection-before/protection-after/deploy-evidence/affected-path-smoke JSON와 `D:/WebLedgerHost/releases/deploy-evidence-1beba48bdd4f0aa20999326689d7c766c921c576.json`. 이 기록만으로 테스트·DB 확인·재배포를 반복하지 않는다.

- **최신 검수 체크포인트:** COST PR #316, 구현 `7944826`·`5f8c0c9`·`d1dc436`·`6c3e1cc`·`7f055e8`. 아래 진행 중 표기는 이 체크포인트로 대체한다. 추가 browser session23926은 **30 passed / 11 failed / 18 subtests passed**로 종료했다. 격리 Git archive 기준 `8cfe391`의 카드/OTA browser도 동일 node/subcase **11 failed / 18 passed / 2 subtests passed**(323.72초)이며 shell/assets 12개를 포함하는 현행 묶음과 구별한다. 기존 실패를 pass로 숨기지 않는다. 폐기된 별도 기록 버튼·수동 질문·배치 선택/전체조회·예전 문구와 canonical snapshot 준비 문제는 기존 실패로 기록한다. 금융 보호는 그대로다.
- 진단 도구는 SUBFAILED별 중복 제거/건수 및 PowerShell UTF-16 redirect를 추가 처리하며 최종 **7 passed**다. 최종 참가자 schema/손상 영수증 검사는5 passed, OTA 검토 API39 passed다. 실제 근거 `.local-archive/wide-pending-20261029/validation.json`, `baseline-browser.txt`, `baseline-browser.xml`.
- 중단 WIP는 통합본과 구별하는 `refs/archive/20261029/wide-luna-*`로 보존했다. managed workspace6개 모두 clean/보존 참조 확인 후 공식 archive·디렉터리 제거 수락. 실제 증거 `workspace-preservation.json`. COST는 아직 미배포이며 다음은 최종 diff/guard→PR #316 정상 main 병합→검증 SHA 고정 배포다. Travel INS PR #10/main은 이미 병합 완료다. 현재 ready 구현을 실제 보험/명단·메일 전환·전체 리팩토링 완료로 확대하지 않는다.

- 사용자가 미결표를 제시한 뒤 다수 Luna low에게 바로 구현하라고 명시 지시했다. 범위를 자동분류/환불로만 축소하던 해석을 교정한다. 대상은 보험 전달/운영 DB 동일성/참가자·수입 수락 준비, 원결제 외부 근거, 클라우드 메일 전환, 백엔드 구조, 공통 디자인, 실패 원인 정리다. 이미 완료한 기능은 재사용한다. 실제 보험 가입·결제·명단 실전송·Google 쓰기·원문/운영DB 변경은 기존 승인·복원·단일 작성자 경계를 유지한다.
- Supervisor 브랜치 `feat/wide-pending-integration-20261029`, 기준 main `8cfe391`, 현재 운영 `9b190e9a70511581629f4378290220512358b48c`. 공통 문서·통합·PR·배포·운영 읽기 전용 수락은 Supervisor 단독 소유다. 이전 Luna 작업3개는 완료/공식 보관돼 재생성하지 않았으며, 아래는 새로 승인된 더 넓은 범위의 작업자다.

| 미결 / 기존 참조 | 실제 담당 | 상태·다음 검증 |
| --- | --- | --- |
| 보험 결제 재개→COST 계약 / COST-INS-02 | Travel INS `77ca711a-d0bc-4aac-a35e-a79697ab5544`, `wide-luna-insurance-20261029` | 코드/합성검증/병합 COMPLETE. 실제 pause→실제 finish_registration 경계 포함20 passed, PR #10 운영 작업 사본 main `ec2b73300fe1dbe8c62d958282c929ef3bd80f6a`. 실제 가입/전송0. |
| 웹/CLI 참가자 DB 동일성·참가자/수입 / COST-INS-01/03/05·PIR | COST `0f8fa7db-b66b-47a5-b132-843b665326a3`→Supervisor | 429 retry limit로 중단한 미완성 파일을 인계받아 기존 CLI를 깨뜨리는 기본 preview 변경은 불수락했다. 웹/CLI resolver 공유·명시 웹DB 불일치 차단·readonly schema/file identity/등록 영수증 대조를 구현, 참가자/수입/패널66 passed. 현재 Travel INS 구성의 참가DB 파일 부재를 실제 readonly 확인했고 COST archive/TravelINS local/호스트 data의 참가/roster SQLite 이름 탐색도0건이다. 과거14명 이력을 현재 운영 수락으로 인정하지 않는다. Aside openTab URL빈값·후속snapshot page null로 운영 화면 미수락. |
| 원결제 외부 근거 / PEND-01 | Supervisor | 실제 원본/명시 결제 증거가 없는 금융 연결은 창작 금지. 기존 진단 근거 재사용, 별도 외부 자료 경계 유지. 여행/항목 분류 완료와 구별. |
| 전체 메일 수집·전환 / PEND-04 | COST `59bcb9e4-d3d3-4b00-a4f8-8b393c61c00d`→Supervisor | 429 후 인계. 끊긴 원문 검증 본문을 복구하고 pending/페이지/빈 watermark가 있으면 batch/일반 apply 모두 거부한다. 전체 coverage/실제 manifest-entry digest/count 검증 CLI는 PREVIEW_VERIFIED일 뿐 운영 전환 승인이 아니다. 최신 readonly manifest `2026-10-29T01:25:29Z`:3,710 stored/48 pending/has_next_page=true/complete=false. 실제 원문 다운로드·쓰기·스케줄 전환0. 재확인 조건 pending0/다음페이지없음/query없음/last_complete존재. |
| 백엔드 구조 / RF-103의 여행 authority 경계 | COST `9ec3fe54-5fd2-4533-b394-66fd13857554`→Supervisor | 429 후 인계. 남은 self 참조 오류를 고치고 여행권위/소매/숙박3메서드를 별도 service로 추출, facade·기존 동적 callback 유지. 정규화 실행본문 AST3개 동일, 여행/자동분류23 passed. 전체 결정/worker/HTTP 수락과 구별한다. |
| 모바일·데스크톱 공통 디자인 / RF-201~205 | COST `c506be38-ddbe-4fa1-b729-ebebd4f14f1f`→Supervisor | `4f756a50` OTA 공통 토큰/44px/좁은폭/포커스 채택을 검수하고 중복 rule 제거. 실제 Chromium 합성4검사에서320/390/760/1440·light/dark·zoom1/2·키보드 수락. 추가 기존 shell/카드/OTA browser 묶음은 아래 실제 실행 세션으로 확인 중. 물리기기·실제 인증 화면 수락과 구별한다. |
| 실패 원인 정리 / RF-004 | COST `34abb032-959e-4998-8d15-cbdd9af81fac`→Supervisor | `aaa1ca0e`·`1ca4586`를 검수했다. 추가 실행은 모델 capacity로 중단돼 인계. 빈/collection-only 증거를 pass로 보고하던 parser와 parameter-ID 노출/건수 축소를 수정했다. 실제 CardFlow6 실패는 잘못된 제공자 fixture·요약API 전체카드 기대·request scope 캐시·금융증명 없는 취소/낡은 문구였으며 제품 금융 보호를 유지해 교정했다. CardFlow/OTA96 passed+28subtests, parser5 passed. 전체5천검사 실행/모든 known-failure 완료를 주장하지 않는다. |

- 결과 알림을 받아 실제 최종 파일·diff·표적 검사·원본/금융/권한 보호를 검수하고, 독립 ready 항목을 직렬 통합·정상 PR/main·검증 SHA 배포까지 이어간다. 완료·미검증·외부 의존·진짜 승인 필요를 각각 기록한다. 이전 자동분류 완료 보고는 프로젝트 전체 미결 완료가 아니다. 사용자의 기존 미추적 파일·stash·원래 workspace를 보존한다.
- 추가 실제 검사: 초기통합61 passed(인계 후 오류 복구), 최종 참가자66 passed, cloud/진단41 passed, entrypoint/검증gate33 passed, 환불/정확OTA/권한105 passed. 실행별 중복이 있어 합산하지 않는다. 신규 런타임9개 compile·AST3개 동일·staged guard16파일 차단0/삭제0. 현재 추가 browser 프로세스 session23926 진행 중이며 결과 전 통과로 보고하지 않는다. 최신 증거는 `.local-archive/wide-pending-20261029/`의 cloud-manifest-recheck·participant-default/configured-paths·participant-database-discovery 및 AST 검사다. 아직 COST 묶음은 미커밋/미배포이며 다음은 browser 결과 검수→guard/compile/link→commit/PR/main/고정 배포다.

## 2026-10-29 최신 요청 — Luna low 병렬 구현·통합

- 사용자가 다수 Luna low 구현 위임과 주 에이전트의 지휘를 명시 지시했다. 최신 자동분류/환불쌍 범위의 실제 미결을 확인해 수정하며 과거 RF 전체를 자동 재실행하지 않는다. PR #312의 실제 분류 적용 완료는 유지한다.
- `codex/gpt-6-luna`·`low` 실제 제공을 확인하고 독립 managed worktree 3개로 분리했다. 환불 재전송 `ed69722b-cabc-43f4-bdee-8d6948c05624`는 `app/ledger.py`와 focused tests, 입력 추론 `8e8f91af-96dc-402e-be91-a7a829fca781`는 `app/automatic_classification.py`·completion과 tests, 화면 완료 `2d619e80-8aec-4f60-a52e-590fd256bc35`는 review/evidence UI와 focused tests를 담당한다. 공통 `card_flow.py`·문서·PR·배포·실자료는 Supervisor 단독 작성이다. 재귀 위임·작업자 운영 접근 금지.
- **COMPLETE — 구현·통합·운영 배포:** 환불 최종 `9eb4910`의 정확한 요청 범위·잠금 내 성공 후 digest/실제 장부 fingerprint 검증을 수락했다. Supervisor가 부분 기기록 묶음의 완료 후 재전송·새 환불 멤버/명시 보류/여러 요청 반복 검사를 보완했다. 화면 `a727950`의 빈 이력=의도적 미배정 제거·환불 완료·금융 보류 분리를 수락하고 환불 선택값/미배정 필터·자동 추론 출처·사용자 보류 표시를 통합했다. 추가 OTA `8c9a0f7`도 같은 빈 이력·자동 추론 출처 규칙을 읽기 전용 투영에 적용한다. 실제 수동 여행·금융 연결·권한 보호는 유지한다.
- 추론의 잘못된 일괄 환불 탭 이동은 불수락했고 최종 `a1d2bc8`에서 기준 main 대비 diff0을 확인했다. 기존 추론18검사 통과 근거를 보존한다. 추론 감사는 COMPLETE이며 코드 변경이 없다. 해당 managed workspace는 clean·보존 참조 확인 후 공식 보관했다.
- 실제 검증: 통합 환불/부분환불/화면54 passed, 인접 자동기록/환불표시30 passed, 최종 화면/OTA출처17 passed(합성 browser 포함), OTA 권한·수동연결4 passed/35 deselected. 실행간 중복이 있어 전체 회귀로 합산하지 않는다. 변경 Python6개 compile·diff 검사 통과. 운영 금융 재처리·Google 쓰기·마이그레이션은 포함하지 않는다.
- [PR #314](https://github.com/6Soo/cost/pull/314) 정상 병합, 검수 소스 `cf3670606107c61a08e1e1232c35a3f23fcfbb73`와 운영 고정 `9b190e9a70511581629f4378290220512358b48c`의 tree 동일.1,098 Git blobs 불일치0, fresh 전체 백업·별도 복원, task/process 고정SHA·loopback listener1·health/ready200·보호13표 내용/스키마 불변으로 실제 배포 수락했다. 영향 trip-review GET·환불그룹 commit POST를 포함한 보호API는 비인증401이다. Board/SourceRefresh 모두 Running이며 이전 `a1b1dcaf21d5398ed3519a402191d0129173a6f7` 복구점 보존. 실제 금융 재처리·Google 쓰기·마이그레이션0.
- 근거는 `.local-archive/luna-followups-20261029/validation.json`, `.local-archive/deploy-9b190e9a70511581629f4378290220512358b48c/`의 review/protection-before/protection-after/deploy-evidence/affected-path-smoke JSON, 호스트 같은 SHA의 release-audit/deploy-evidence다. 정확한 재확인 명령은 `Get-Content -LiteralPath 'D:/WebLedgerHost/releases/deploy-evidence-9b190e9a70511581629f4378290220512358b48c.json' -Encoding UTF8`다.
- 현재 승인 범위의 구현·검증·배포 ready 항목과 실제 대기는 없다. 아래 과거 절의 기존 환불 재전송 baseline 실패는 이번 PR로 해소했다. 세 작업자의 최종 커밋·실제 clean·stash/사용 참조를 확인하고 `refs/archive/20261029/luna-*`로 보존한 뒤 managed workspace3개 모두 공식 보관·디렉터리 제거를 확인했다. 기존 사용자 미추적 파일·stash·원래 workspace는 보존했다. 결과 이벤트는 실제 검수 근거로 개별 ack한다. 이 후속 문서만으로 코드 테스트·운영DB 확인·백업·재배포·서버 재시작을 반복하지 않는다.

## 2026-10-29 최신 요청 — 미분류 카드 0건까지 공통 추론 적용

- 사용자가 근거 부족·오분류 가능성을 허용하고 에이전트가 공통 규칙을 코드로 만들어 현재 미분류 카드에 적용하라고 명시 승인했다. 개별 사례별 질문이나 추가 규칙 승인 대기를 두지 않는다. 실제 원본/금융 링크/사용자 결정 보존 및 백업·복원·단일 작성자 게이트는 유지한다. 정본은 [자동분류 완료 계약](specs/finance.md#자동분류-완료-계약-2026-10-29)이다.
- 최신 교정: 사용자가 미배정으로 정한 적이 없다고 명시했다. 203건을 이력/override 표시만으로 수동 미배정이라고 해석한 판단을 폐기했다. 실제 재대조 결과187건은 유효 여행 복원(현재 장부1·최근 저장31·기존 장부155),11건은 기존 환불 탭,5건은 새 여행 추론 대상이다. 원래 항목과 실제 유효 여행은 유지하며 빈 값에만 근거를 복원/추론한다. 결정/override 이력은 삭제하거나 새 사용자 선택으로 위조하지 않는다.
- 현재 구현: 업종/서비스 용도/해외 사용/기타경비 공통 기본값, 실제 여행 최선 후보·동률 해소, 검증된 원결제 항목/여행 상속, 과거 authority 상태 완료. 새 업로드에도 같은 마지막 분류 단계를 사용하며 메일 자료 장애를 비용 미분류 이유로 삼지 않는다. 기존 유효 장부 배정·항목·회사 제외·보류·원본 오류를 보호한다.
- **COMPLETE — 실제 운영 적용:** 미분류 구매195→0, 전체 방향 미분류226→0, 여행 미배정377→0. 분류/배정441건을 실제 DB에 원자 적용했고, 종전 제외203건도 전부 포함했다. 백업 원본과 실제 반영 후 자료를 다시 대조해203건의 기존 여행 복원187·환불 탭 복원11·새 추론5, 기존 항목/원본 불변을 확인했다. 원본/과거 결정/금융 링크 불변·새 장부 행0·Google0·재실행 변경0.
- 최신 정정 후 표적/금융/업로드/교정60 passed, 빈 기본값/이력 복원·금액/금융 링크 보호·원자성/재실행 포함. 추가 API/근거10 passed, 변경 Python8 compile·PowerShell parse0·문서 링크 누락0·metadata guard12파일 차단0/삭제0. 과거 전체 HTML의 `location.reload()` 금지 assertion은 해당 bulk 자동정리 컨트롤의 부재 검사로 좁혔다. 환불 API의 기존 새 요청+이전 digest 실패는 별도 기존 미결이며 금융 보호를 약화하지 않는다.
- [PR #312](https://github.com/6Soo/cost/pull/312) 정상 병합·운영 고정 SHA `a1b1dcaf21d5398ed3519a402191d0129173a6f7`. 검수 소스 `f11b447e8970934985bf4f953801edc078762d71`와 merge tree 동일,1,097blobs 불일치0. 코드 배포 전후 보호13표 동일. 이후 별도 새 백업/복원·정지된 단일 작성자·digest 일치·분류 적용·보호 검증·재실행0을 통과했다. 분류 테이블3개에는 승인된 항목/여행/상태 보완만 허용했고, 나머지 금융/사용자10표는 내용·스키마가 백업과 동일했다. Board/SourceRefresh Running·health/ready200·보호API401로 복구했다.
- 실제 적용 근거는 `D:/WebLedgerHost/data/backups/card-classification-20261029T040917088/`의 `backup-restore.json`, `preview.json`, `applied.json`, `repeat-preview.json`, `post-verification.json`, `financial-relations-verification.json`이다. 코드 배포 근거는 같은 SHA의 호스트 deploy-evidence/release-audit와 `.local-archive/deploy-a1b1dcaf21d5398ed3519a402191d0129173a6f7/`다. [운영 기록](operations.md#2026-10-29-pr-312-미분류-카드-자동추론과-203건-재분석실제-적용) 참조.
- 현재 사용자 승인 범위의 ready 항목과 실제 대기는 없다. 과거 RF 큐와 기존 환불 재전송 baseline 실패를 새 과제로 재실행하지 않는다. 사용자 미추적 파일·stash 보존. 정확한 증거 재확인 명령은 `Get-Content -LiteralPath 'D:/WebLedgerHost/data/backups/card-classification-20261029T040917088/post-verification.json' -Encoding UTF8`다. 문서 후속 병합으로 코드 테스트·운영 DB 확인·백업·재배포·서버 재시작을 반복하지 않는다.

## 2026-10-29 현재 사용자 요청 — 자동분류 완료와 환불쌍

- 현재 직접 승인 범위는 취소·환불 미분류 원인 수정·검증·배포, 사례 36건을 바탕으로 가맹점별 예외가 아닌 공통 규칙을 구현하는 것, 그리고 별도 확정/미확정 단계를 없애는 것이다. 최신 계약은 [금융 명세](specs/finance.md#자동분류-완료-계약-2026-10-29)다. 과거 RF/PA 큐 전체를 재실행하지 않는다. 새 승인 작업 ID는 만들지 않는다.
- 후속 담당 `16089281-ddee-44a0-8f5e-1572550ad28b`가 기존 `C:/AX/cost`를 재사용한다. 이전 부모에게 메시지·재개 없음. 인계 family의 자식/결과 이벤트는 0개이며 새 위임 없음. 기존 사용자 미추적 파일·stash는 보존한다.
- 인수 HEAD `68ef66b7b58b5733ca5532688fed893bc0cdc0fb`는 원격 main보다 3커밋 앞서며, `8ddee29` 환불쌍 분류 저장·`04a2958` 예약 여행 추론·`68ef66b` 답변 재사용 규칙이 이미 실제 고정 배포됐음을 호스트/local deploy-evidence에서 확인했다. 코드 배포를 36건 실자료 해결 완료로 해석하지 않는다.
- 구현·검증: 분류 완료 DTO/화면을 `CLASSIFIED`와 자동·수동 출처로 통합하고 추가 확정 요구를 제거했다. 분류가 이미 저장됐는데 내부 기록이 `NOT_RECORDED`이면 전체 API를 409로 반환하던 오류를 고쳐 `saved=true`·`classification_state=classified`와 별도 `ledger_recording=held`를 반환한다. 기록 보류 중에는 다른 거래의 재분류/자동 기록을 실행하지 않는다. 수동 결정·환불·원본·권한 보호는 유지한다.
- 실제 검사: 최초 표적39 passed/64 deselected, 환불·자동 기록·여행 통합62 passed/1 failed, 후속 변경의 자동 기록·교정21 passed, 결정 API·여행 이동·근거10 passed/84 deselected, OTA 권한/공개자료6 passed/33 deselected, 낮은 신뢰도 브라우저 교정1 passed. 최신 여행 화면 browser는21개 묶음에도 포함되며 별도 브라우저에서 분류 완료/추가 확인창 없음·4폭·확대 검증을 수행했다. 변경 Python9개 compile·diff·현재 로컬 문서 링크 누락0.
- 기존 실패: `test_refund_group_commit.py::RefundGroupCommitTests::test_group_route_books_only_the_pair_and_repeats_are_noops`의 새로운 요청 ID+이전 미리보기 재전송 오류는 변경 전 `68ef66b`에서 동일 `KeyError: result` 재현. 상속된 cleanup 검사도4 passed/1 failed이며 `test_bulk_classification_survives_booking_failure_without_changing_protected_data`의 전체 HTML `location.reload()` 부재 assertion이 같은 기준에서 재현됐다. 통과로 계산하거나 미리보기/금융 보호를 약화하지 않았다. 근거 `.local-archive/automatic-classification-20261029/baseline-refund-retry.txt`와 `baseline-cleanup-reload.txt`. 과거 브라우저 fixture의 숨겨진 배치·폐기된 수동 기록 버튼/문구는 현재 계약에 맞게 교정 후 통과했다.
- **COMPLETE — 코드·명세·승인된 배포:** [PR #310](https://github.com/6Soo/cost/pull/310), 구현 `a1b5af2da158d6016f62c150171a91e78599852c`, 운영 고정 `b75c37887c354255f0bf877eb8d1e47451c9684d`. fresh backup/별도 복원·1,092blobs 일치·task/process SHA·listener1·health/ready200·보호 API401·13표 내용/스키마 불변. 검수 소스와 merge tree 동일. Board/SourceRefresh 모두 Running. 배포본 순수 합성 smoke도 자동/수동 완료·출처·공개자료 제한 통과. 상세는 [운영 기록](operations.md#2026-10-29-pr-310-자동분류-완료환불쌍-저장-배포) 참조.
- **미실행 범위:**36건 일괄/개별 실제 저장·새 업무 규칙 활성화·Google 쓰기·마이그레이션 없음. 기존 업종·현지 사용 공통 규칙은 유지한다. 인증된 Aside COST 탭이 없어 운영 owner 실자료 UI 수락은 미실행이며 합성 browser 수락을 대신 실자료 완료로 표현하지 않는다. 코드 배포 완료를36건 실자료 완료로 확대하지 않는다.
- 현재 분류 완료/환불쌍 코드의 ready 항목은 남지 않았다. 신규 공통 규칙의 아직 논의되지 않은 업무 의미를 임의로 정하지 않는다. 사용자와 거래 사례에서 공통 조건·항목이 정해지면 그 범위의 규칙을 구현하고, 실자료 저장은 기존 원본/복구/단일 작성자 게이트로 처리한다. owner 화면 수락의 재확인 조건은 정상 인증된 COST 세션 확보이며 인증을 우회하지 않는다. 기존 실패2개는 현재 변경의 통과 근거와 별도 미결이다. 정확한 배포 증거 재확인 명령: `Get-Content -LiteralPath 'D:/WebLedgerHost/releases/deploy-evidence-b75c37887c354255f0bf877eb8d1e47451c9684d.json' -Encoding UTF8`. 문서 후속 병합만으로 재배포하지 않는다.

## 계정 전환 후 통합 검수 (2026-10-28)

후속 담당은 `a8dba9f3-3e50-4a26-b113-ab754767883e`다. 이전 담당에게 메시지를 보내거나 재개하지 않는다. 잠정 배정 최종 `494761842aa6da982133a8548edc660b9d11b65a`를 최신 main `9c7580d8d12e869dc23dee8f3f822033d28389d2`에 정상 통합했다. 통합본 새 화면·금융 보호 226 passed, 권한·환불·우선배정·OTA 페이지/스냅샷 227 passed, 변경 Python 12개 compile 및 diff 검사 통과. 선택기 미매핑0, metadata guard 차단0/삭제0. 실제 브라우저 검사는 합성 자료를 사용하며 운영 실자료 수락과 구별한다.

현재 운영은 PR #308의 검증된 `9ab2471f91b6b210ac79985a43e507743f5870d9`다. 정상 병합·검수 소스 일치·새 백업·별도 복원·고정 SHA 배포·health/ready·보호 API·보호13표 불변 확인을 완료했다. 실제 재배정·일괄 처리·보험 명단 전송·Google 쓰기·마이그레이션은 실행하지 않았다. PA-01 실자료 기준선과 PA-06 실자료 수락은 미측정이다. 기존 여섯 CardFlow 실패는 작업자 기준 `61211012`에서도 같은 node로 재현한 별도 기록이며 통과 수에 포함하지 않는다. 현재 병합·코드 배포 요청은 완료했으며 실자료 수락은 별도 경계로 유지한다.

기존 27개 큐는 과거 수락 경계를 보존한다. 새 managed run은 `07264b89-75e8-4748-9ab5-9f7ae4d3035a`, generation 2이며 checkpoint는 같은 run 디렉터리의 `checkpoint.json`이다. 운영 배포 결과는 아래 후속 기록을 우선한다.

기존 managed run 정본은 [리팩토링 마스터](specs/refactor-master-20261027.md)와 아래 27개 ID다. 이후 사용자가 명시 선택한 명세 대기 기능의 코드 구현·검증 배포 승인은 아래 최신 진행 기록에 추가한다. 과거 ACTIVE/READY 전체를 자동 재실행하지 않는다. 상세 과거 근거는 [보관 기록](history/product-and-handoffs.md#rf-generation5-queue-archive), 배포는 [운영 기록](operations.md)을 참조한다.

- runId: `e0197439-1c34-4348-a14d-7a870c3d69b5`.
- 이전 run Supervisor: `3cebc37b-17d7-4b47-9689-a2bf6f50a01c`, generation **5**. 현 담당은 위 후속 run/generation1이며 workspace는 `C:/AX/cost`다.
- 운영 확인 SHA: **c1bf76ce3e6e6973dc92e6a3e1c2a145c5e4e661**. 정상 배포·보호 검사 근거는 아래 최신 진행 기록과 운영 기록을 따른다. 실제 단일 환불 그룹 적용은 owner 인증 대기다.
- 사용자 작업 사본은 `C:/AX/cost`이며 사용자 미추적 파일·stash와 미수락 결과를 보존한다. 정리·통합 브랜치 근거는 `.local-archive/merge-cleanup-20261028/`에 기록한다.

## 승인 전체 ID와 실제 수락 경계

부분 추출의 병합을 전체 RF 완료로 승격하지 않는다. pending에도 기존 부분 구현은 있으며 완료 근거를 재사용한다. complete는 아래 두 PEND와 문서 정리 범위만이다.

| ID | 상태 | 검증된 범위 / 다음 경계 |
| --- | --- | --- |
| PEND-01 | blocked | 원결제 또는 명시 결제 증명 부재. 기존 진단 완료, 금융 연결을 창작하지 않는다. 아래 외부 자료 차단 참조. |
| PEND-02 | complete | 합성 browser3 passed와 운영 Aside 4조건·20행·넘침0의 확대/키보드/오류·재조회 수락. 물리적 모바일 검사는 아니다. |
| PEND-03 | complete | 클라우드 수집/가져오기 PR #256/d37b33c 및 전용 수집기 배포. 수집20/인증14·importer32/browser3 근거 재사용. 실제 전환은 PEND-04. |
| PEND-04 | blocked | 2026-10-28T14:35:59Z 기존 전용 Drive readonly 자격으로 manifest 재확인:3,710 stored/48 pending/has_next_page=true/complete=false. 원격 탐색 미완료로 전체 bounded preview 수락을 진행할 수 없다. 원문 다운로드/원격·로컬 원문/운영DB 쓰기0. 재확인 조건은 pending0·다음페이지없음·query없음·last_complete존재다. 근거 `.local-archive/merge-cleanup-20261028/cloud-manifest-recheck.json`. 코드/51검사 근거를 유지하며 실제 적재/작업전환의 별도 데이터 게이트는 확대하지 않는다. |
| RF-001 | running | 정적 호출 지도 `config/refactor-call-map.json`·도구 PR #294/main `8e479de` 병합, 경로 영향 매핑 PR #296/main `ba74ab8` 병합. 표적/선택기 18건 통과. RF-001 및 RF-101 통합 101 passed/3 subtests; 전체 gate는 12개 모듈에서 OTA `inferred_link` KeyError 1건으로 실패했고 기준 SHA `355eaea`에서도 같은 assertion 재현. 전체 Route→service→repository→table→external-effect와 권한 수락은 미완료. |
| RF-002 | pending | 좁은 OTA 읽기 계약은175c3a2에서 이미 채택됨을 확인, 중복 구현하지 않았다. helper 실행 AST 동일·golden/canonical27 passed·입력 불변. 전체 상태 소비 수락은 부분 완료. |
| RF-003 | complete | PR #307의 코드 패키지 경계와 PR #308의 화면 문구 제거·검증된 원결제/환불 원자 기록 경로를 병합·배포했다. 60개 합성 환불/정리 검사를 통과했고, 1,092 blobs·health/ready200·보호API401·보호13표 불변을 확인했다. 운영 SHA는 `9ab2471f91b6b210ac79985a43e507743f5870d9`이며 실제 금융/여행/Google 쓰기는 실행하지 않았다.
| RF-004 | running | Windows/Python3.14.7의 실제 pytest collection 5,255건(exit0)과 정적 환경 감사 오류0을 확인했다. 수집은 본문 실행과 구별하며 import/hook 실행 사실을 표시한다. audit의 명시적 --collect는 원문 stdout을 공개하지 않고 요약·해시만 남기며 실패/timeout을 통과로 처리하지 않는다. 표적24 passed. 전체 known-failure 분류와 간접 실DB 의존 감사는 남음. |
| RF-005 | complete | PR306의 공식 tools/deploy_verified_release.ps1로 b34a96a를 실제 배포했다. 기본PREVIEW실행0/명시적Apply·review/blob/검증이전릴리스/task/process/listener·fresh backup/별도복원·health/ready200·API401·보호13표불변을 확인했다.1090blobs일치, 이전c1bf76ce복구점보존. switch는 LF정규화외동일, 표적27passed·PS2parse. 호스트4예약task는 기존기동/동기화경로이며 오래된DB전환배포기를호출하지않음을 이름/인자명만으로확인했다. RF003의배포콘텐츠분류는독립미결이다. |
| RF-101 | complete | 입력 정규화 `9930b42`·동적 콜백 교정 `5f0ac83` 포함 PR #294/main `8e479de` 병합. 스토어 정규화·idempotency·audit·allocation·schema·records·change-validation·store·income_bank 및 RF-001 검사 101 passed/3 subtests; 호출 동적 재바인딩·SQL/audit/revision/idempotency 계약을 유지. |
| RF-102 | complete | 필요한 helper와 façade 분리는 최신 main에 이미 반영되어 있다. main SHA 355eaea 기준 HTTP/render/read/export/dialog 표적 49 passed. 임시 RF102 브랜치와의 유일한 소스 차이인 query fallback은 호출 타입 계약을 불필요하게 넓혀 채택하지 않았고 원본 브랜치는 증거 보존 후 정리한다. |
| RF-103 | running | 카드 근거·환불 query·OTA 투영·cleanup PR #261/#268/#269/#276 검수/병합/배포. 여행 authority/decision/background 전체 수락은 남음. |
| RF-104 | running | 중앙 대사·예약 그룹/페이지·증분 성능 기존 구현 재사용. 전체 consumer의 같은 세대/링크/trace 수락을 대조하고 solver를 재구현하지 않는다. |
| RF-105 | blocked | PR #295 `496cbbe` 운영 배포 완료. 1,051 tracked blobs 일치, task/process SHA 고정, listener 1개, health/ready 200, 보호 API 401, 새 백업·별도 복원 검증과 보호 13표 불변. owner 화면은 AUTH_REQUIRED로 승인된 단일 환불 그룹 적용 미실행. 실제 관측 그룹은 같은 import batch이므로 교차 배치 실행 증거로 표현하지 않는다. 환불/금융 표적 74 passed; 넓은 검사 실패 13건은 ba74ab8에서도 동일 node ID로 재현. PR #297 개별 그룹 UI/API는 e1a6c7b로 병합했으며 운영 배포 여부는 아래 최신 진행 기록을 따른다. |
| RF-106 | complete | PR #286의 공통 항공권 근거/검색 projection은322ef3f 및후속c1bf76ce에 배포됐다. source의(provider,booking_ref)→공통 collect→검색/guide/index 소비를 확인했고 추출 전후 핵심4파일 변경0. 보관 인증 근거210건의149질의·stale/cursor447건 읽기 전용 shadow가9f6eec7과동일, 원본/입력불변. 표적106 passed와 아래 수정browser2 passed, 최초수신일/index11 passed. 외부 예약 checkout 통합1 skip은 미실행으로 별도 보존하며 실제 사람/카드 연결을 수락한 것으로 표현하지 않는다. 명시일/최초수신일·시차·왕복·취소/변경·권한은 해당 표적으로 확인했다. |
| RF-107 | running | provider schema/masking PR #289/d1180f1 병합. 필수 signature·ConfigError 동일성·기존 순수/저장소/service AST 동일, Supervisor135 passed/105subtests. 전체 adapter 수렴은 남음. |
| RF-108 | pending | schema/additive/복원/snapshot 기존 기반 재사용. 쿼리 plan·P95·메모리 측정 후 최적화. 실제 DB migration은 별도 게이트. |
| RF-109 | running | runtime catalog 정적741후보(UNKNOWN379/TEST_FIXTURE359/HISTORICAL3) 확인. tools/cost_audit.py는 기존 환경·runtime·call-map·write-boundary·tracked-data 진단5개의 읽기 전용 공통 진입점이며 기본PREVIEW, 명시적 --run과 고정 인자만 허용한다. writer/collection/임의 인자 차단·종료코드 보존 포함 표적24 passed. 운영 호출·전체 guard 분류와 write CLI 수렴은 남음. |
| RF-201 | running | 자산 배포, geometry 단일 소유2559ef7 및 실제 CSS zoom/baseline 검사8798569 회수. 작업자 전체4 passed(99.88초), Supervisor 인접20 passed/1 deselected. native/standalone·8폭·양테마·CSS1/2배는 합성 수락이며 실기기 검사가 아니다. PR #290/322ef3f 배포. |
| RF-202 | running | 공통 셸 조립 PR #277/자산 PR #282 배포. URL/DOM·테마1개 보존. 전체 화면 수락과 구별한다. |
| RF-203 | running | 검토 문서 PR #265·guidance16검사·template byte 동일성 배포. 전체 폼/지출 컴포넌트 채택 수락은 남음. |
| RF-204 | running | 기존 OTA/환불/항공권 정보 구조 개선 재사용. 전체 동일 상태/인라인 근거/접근성 수락은 남음. |
| RF-205 | running | 기존 responsive/keyboard/theme 근거와 RF-201 합성 baseline matrix 재사용. 항공권의 낡은 OS색상전환 assertion1실패를 최신 단일 수동 아이콘 계약으로 교정하고 실제 예약/기존 참가자2화면×8폭·200%·키보드·수동선택 유지 browser2 passed. 초기106pass/1fail과 교정후2pass를 구별한다. 인증 운영 화면·실기기 포괄 수락은 미실행. |
| RF-301 | running | requirements 단일 생성/검증 PR #283/9f6eec7 배포. 선언5개 동일·기본 읽기·원자적 mirror.51검사+selector8. 환경/비밀/feature flag 전체 정리는 남음. |
| RF-302 | running | 기존 관측·OTA 성능 근거 재사용. 공통 request/snapshot/rule/fingerprint·단계 지연 및5경로 p50/p95/bytes/memory 전체 수락은 남음. |
| RF-303 | complete | PR #293 merged as 355eaea5c8476f153bc43ff5320b572f7fb27c4f. Fail-closed schema/selector validation, sanitized errors, preview/run separation and self-impact mapping accepted. Supervisor: 31 tests passed; preview PREVIEW with executed=[]; --run PASSED (guard blocked_count 0, py_compile, targeted pytest). Operating deploy is grouped after the remaining approved integrations. |
| RF-304 | complete | 단일 문서 진입점·승인27개 큐 압축/보관 PR #287/fc2e44b 병합, 새 상대링크 누락0. 새 한글 인코딩 손상은 UTF-8 파이프 bytes 검증 후 현재 큐/해당 운영 절/새 보관 기록에서 복구했다. 문서만으로 앱 검사/배포를 반복하지 않는다. |

## 현재 작성권

main PR·배포·공통 문서·COST 임시 공간 보관은 Supervisor `3cebc37b`만 담당한다. PA04/05/06 화면·승인 API는 `4c407a16`가 기존 assignment worktree의 단독 작성자다. 최신 main `61211012`를 정상 merge한 중간 53검사 통과 보고까지 수신했으며, 최종 browser·금융 보호 검수 결과는 아직 기다린다. cleanup 공간은 보존한다. 참가자·항공·OTA는 PR #300으로 병합·배포했고 공식 보관 결과는 아래 최신 기록을 따른다. 다른 저장소 보험 sender 코어 21검사는 실제 가입·명단 전달 승인이나 실행 근거가 아니다.

## 이전 작업자 인계 이력

다음 표는 종료·교체된 작업자의 과거 기록이며 재개 지시가 아니다. ANUS 이후 사용자 Luna 병렬 위임 결과도 회수했으며, 실제 quota로 유료 대체·작업자 반복 생성은 하지 않는다.

사용자 최신 지시는 **ANUS free(auto)** 위임이다. 기존 AGY의 완료 커밋/미커밋/작업공간을 보존해 재사용하고 실행 제공자만 사용자 지정으로 전환한다. 두 작업자의 실제 Individual quota reached(약2시간29분 후 reset)와 자동 continuation alias의 같은 오류를 확인해 반복 위임하지 않는다. 자동 복구로 실행된 Codex 현재 owner5319cc4c/ceed86f8을 중단한 뒤 Anus 작업자2명을 같은 workspace에 배정했다. 확인한 제공자 anus의 모델 ID는 anus/free(무료 자동 회전)이며 유료 대체·재위임·운영 접근은 금지했다. 작업자 재위임·push·PR·배포·운영/고객 원문 접근은 금지한다. 공통 문서/운영/인증/원문은 Supervisor만 작성하며 같은 파일/DB/외부 효과 작성자는 하나다.

| 실제 child agentId | worktree suffix / 현재 소유권 |
| --- | --- |
| `98cc885f-5d8c-4c99-8d5e-01ccfe57a6ea` | `cost-rf102-board`: 초기화 실패2회·error·activeTurn없음·clean. 새 변경 없음, 재개하지 않고 기존 결과 보존. |
| `e253fa73-485c-4e55-b87f-22f56208b323` (Anus) | `cost-rf101-store`: d1dfd42/3afc1d7 보존 결과 검수 후 RF001 tools/refactor_call_map.py·독립검사·비식별 config 구현. 기존 AGY/Codex 실행은 중단, 파일 보존. |
| `bce73f79-9de8-4f22-8c1e-04ab8ab6efd1` | `cost-rf103-evidence`: app/cloud_mail.py·합성 검사만으로 PEND04 bounded batch 구현. 원문/운영 실행 금지. |
| `9b367736-16e9-40c2-8516-21acec02ae32` (Anus) | `cost-rf201-assets`: tools/run_targeted_checks.py·독립검사 fail-open 교정. 기존 미커밋2파일을 보존해 이어간다. UI는 PR290 배포 완료라 재구현하지 않는다. |

worktree root는 `C:/Users/kkokk/.paseo/worktrees/28lt5mey/`다. 실행 중 child에 같은 과제를 다시 보내지 않는다. provider stream/초기화 오류는 로컬 실행 실패이며 외부 권한 차단으로 바꾸지 않는다. 완성 커밋은 실제 diff·검사를 대조해 회수한다.

## 배포와 검증 근거

- **322ef3f 고정 배포 완료**: PR #286 항공권/#288 변경 검증/#289 provider/#290 토큰·UTF-8 교정 포함.1,041 Git blob 일치·작업/프로세스SHA·단일loopback listener·health/ready200·보호API401·보호13표 불변. 이전9f6eec7 복구점과 검증된 복원 사본 보존. PEND04 원문 적재/작업 전환 미포함.

- 이전 운영 **9f6eec7**: PR #280~#285 포함. 이전 검증535b6dd3178758a5a442eb6a8e7b0d60517a5cb3 복구점 보존.1,034 Git blob 불일치0·작업/프로세스SHA·단일loopback listener·health/ready200·OTA 보호API401·보호13표 내용/스키마 불변. data guard base 차단0/삭제0. 기존 검증 백업/별도 복원 근거 재사용.
- 최근 Supervisor: HTTP98, 멱등성66/3subtests, requirements51, selector8, 항공권71, 변경 검증70/3subtests, provider135/105subtests, 토큰 인접20/1deselected. 단위는 pytest tests/subtests이며 서로 다른 실행 건수를 합산해 전체 회귀처럼 보고하지 않는다.
- 멱등성의145개 메서드 집합/SQL 동일·139개 AST 불변, 변경 검증은 _validate 외144개 AST 불변. 작업자 모듈별 실제 통과와 공개 baseline differential 근거를 재사용한다. 무관한 전체 회귀는 반복하지 않았다.
- 로컬 `.local-archive/refactor-parallel-20261028/`의 equivalence/review/protection JSON과 호스트 동일SHA release-audit/deploy-evidence가 근거다. 개인정보·원문·계정/폴더ID·인증값은 Git/보고서에 넣지 않는다.

## PEND-04 실제 게이트

[클라우드 전환 명세](specs/cloud-mail-cutover.md)의 기존 승인만 수행한다. 전용 프로젝트·사용자 직접 Apps Script/Drive 동의·callback·전용 ADC·Drive 소유자/비공개 확인은 완료했다. 재동의나 기존 인증 교체는 하지 않는다.

`cloud-backfill-state.json`에서3,704건/pending0/has_next_page=false/query=null/last_complete 존재로 초기 전체탐색 완료를 확인했다. last_complete는 탐색 시작 watermark이며 관측 완료시각과 다르다. 단일 반복기는 완료 후 정상 종료했다. Drive size294,501,933B 때문에 기존 무제한 읽기 preview를 중지했고 안전100MiB를 유지한 bounded batch 합성 보완 중이다.

기존 `WebLedger-MailCollect`는 직접 Gmail 수집/Ready이며 호스트 원문 적재·운영DB import·작업 전환은 미실행이다. 다음 순서:

1. 배치 코드/보호 검사를 통과하고 모든 batch preview의 내용 검증·전체 indexed=existing+new·enumeration_complete를 확인한다.
2. 기존 작업 XML/명령/상태 보존→직접 writer disabled/idle·동시쓰기0→신선한 원문/통합DB/보호DB 백업·별도 복원 동등성→보호13표 기준선.
3. 승인된 원문 append/import→기존 원문/헤더·금융/수동결정 불변→반복 appended0/DB 불변→COST/worker 새 원문 반영 수락.
4. 클라우드 후속 예약 실행1회와 Drive 전달 수락 후에만 Gmail 작업을 Drive 전달 전용으로 전환한다. 실패 시 검증된 이전 작업만 복원하고 원문은 보존한다.

로컬 준비 실행기는 `apply_verified_cloud_mail.py`, `verify_imported_cloud_source.py`, `cloud_relay_runner.py`다. 실제 single-writer/backup/restore 확인 없이 환경 문자열만 넣어 실행하지 않는다. Board가 Windows에 있으므로 완전한 로컬 의존 제거라고 보고하지 않는다. Board 릴리스와 원문 적재는 외부 효과를 직렬화한다.

## 외부 자료 차단과 범위 밖 보존

- **PEND-01 external_data**: 카카오39취소 중29연결/10미연결, Agoda76중73/3, Trip전체186중171/15. Trip15중12는 원승인번호가 있으나 DB/보관/추가 탐색에서 원결제를 찾지 못했다. 원결제 원본 또는 명시 결제 증명이 필요하다. 금융/원문/수동결정 쓰기0. `.local-archive/all-pending-20261028/refund-evidence-summary.json` 및 recovery summaries 근거 유지.
- **SPEC_ONLY, 실행 제외**: [오너 결정](specs/owner-product-decisions-20261028.md), [보험 참가자/수입](specs/participant-income-authority-and-drag-link-20261028.md), [잠정배정 검토](specs/provisional-assignment-review-first-20261028.md), [지출 상태 필터](specs/expense-cleanup-status-filter-actions-20261028.md), [여행 항공권](specs/trip-flight-booking-overview-20261028.md), [Travel INS 연동](specs/insurance-participant-integration-20261028.md). 과거 미구현 표기는 새 RF 기능 승인이 아니다.
- 별도 카드 전체 내역 과밀 개선 PR #273은 구현/배포 완료, 인증된 운영 화면 수락만 남은 이전 범위다. 과거 ALL/R0/R1은 보관 근거이며 새 큐가 아니다.
- 사용자 미추적 `apps-script/CloudMail.gs`, `docs/superpowers/`, `scratch/`, `webapp/tests/tmp71q0k16e/`, `webapp/tests/tmp_dfqgw61/`와 기존 stash/기존 workspace를 보존한다.

## 다음 실행과 인계

각 결과마다 해당 행/근거를 갱신하며 세션별 전체 큐 사본을 새로 만들지 않는다. 최신 사용자 결정이 과거 문서보다 우선한다. 고객 원본/수동결정 보존, 인증 우회·강제 push·자료 삭제·미승인 과금 금지, Google 최종 장부 읽기 전용을 유지한다.

공통 checkpoint: `C:/Users/kkokk/.paseo/paseo-accounts/work-runs/e0197439-1c34-4348-a14d-7a870c3d69b5/checkpoint.json`. Publisher: `.local-archive/refactor-parallel-20261028/publish_checkpoint.py`. 승인27개 ID·queue bytes SHA256·generation5 실제 agentId를 원자 갱신한다. family results-ack는 검수한 이벤트만 누적한다.

정확한 다음 행동: RF201 표적/차등 수락→직렬 PR/main·검수 묶음 고정 SHA 배포/health/auth/보호 최소 스모크. 동시에 반환 normalization/gate/batch의 실제 diff·표적 검사를 수행하고 PEND04 현재 원격 manifest 완료를 확인한 뒤 읽기 전체 preview 및 single-writer/복원 게이트를 준비한다. 준비된 독립 항목은 계속 진행한다.

<!-- integration-progress-start -->
## 2026-10-28 최신 병합·정리 진행

- 사용자 최신 지시로 검증된 PR·브랜치 통합과 운영 코드 배포를 진행한다. 금융 데이터 적용은 기존 단일 환불 그룹 승인과 정상 owner 인증 범위다.
- PR #297 `e1a6c7b`, RF 통합 PR #298 `fe12cf4`, 지출 필터 PR #299 `ad11701` 정상 병합. 환불 83개·인접 보호 38개, RF 통합 99개와 26 subtests, 최종 필터/환불 통합 21개를 각각 통과했다. 서로 다른 검사를 합산해 전체 회귀로 표현하지 않는다.
- 로컬 병합 브랜치 97개 정리, 원격 병합 브랜치 93. 모든 삭제 대상 커밋은 `refs/archive/20261028/`에 보존하고 main·사용 중 브랜치·stash는 보존한다.
- 별도 원본 이력인 로컬 6개·원격 명세 8개는 과거 버전을 main에 다시 합치지 않고 `refs/archive/20261028/historical/` 및 검증된 `historical-branches.bundle`에 보관했다. 미병합 이력을 병합 완료로 표현하지 않는다. 옛 rf102 통합 공간의 변경 문서 2개도 `450f626` checkpoint와 파일 사본으로 보존했다.
- 통합·사용 종료 작업 공간 11개 공식 보관 및 디렉터리 제거 확인. 정리 처리 중 0개. RF201의 최초 API 300초 시간 초과는 공식 CLI 재확인 후 디렉터리 제거까지 확인해 해소했다. 검증이 끝난 임시 baseline worktree 2개도 보관 참조를 남기고 정상 제거했다. 활성 작업 공간과 미커밋 자료는 보존한다.
- 운영 확인 SHA: `61211012a0bbd250ab5e5fa6b629e3af9e672324`. 후속 PR #300은 `61211012a0bbd250ab5e5fa6b629e3af9e672324`로 병합했으며 실제 배포 완료 여부는 호스트 deploy-evidence를 따른다. RF 사전 점검·공통 UI·검사 게이트는 검증된 하위 묶음이며 전체 RF 완료가 아니다.
- 다른 세션의 사용자 명시 선택인 “명세 대기 기능까지 모두 포함”이 질문 이벤트와 응답 전달 `ab4efea4-875b-400e-82ad-7e0aa69a5a69`로 확인됐다. 추가 기능의 코드 구현·정상 검증 배포에 적용하며 실제 금융/여행/명단/보험/Google 쓰기 게이트를 확대하지 않는다. 기존 managed run의 27개 ID는 유지하고 추가 명세 작업은 별도 작업자 근거와 대조한다.
- 로컬 근거: `.local-archive/merge-cleanup-20261028/`의 refs/workspaces/progress 기록. 금융 적용은 AUTH_REQUIRED로 미실행이다.
- 참가자·항공 bundle `43588d9`(항공 `0cd571f` 포함)와 OTA `53d25fe`는 PR #300으로 통합했다. 통합 347 passed/31 subtests·인접 34 passed·선택기 48 passed. 기존 signed-session 6건과 폐기 Google/고정 자산 기준 26건 실패는 main `ad117015`에서 동일 재현했으며 통과에 포함하지 않는다. 데이터 guard 차단0·선택기 미매핑0·변경 Python20개 컴파일·diff 검사 통과. 잠정 배정 PA UI/API는 기존 부모 `4c407a16`가 단독 작성하며 새 작업 공간·유료 모델 전환 없이 이어간다.
- PR #300 고정 SHA `61211012` 배포는 1,077 blobs 불일치0·fresh backup/별도 복원·task/process SHA·loopback listener1·health/ready200·보호 API401·보호13표 전후 불변으로 수락했다. 근거는 `D:/WebLedgerHost/releases/deploy-evidence-61211012a0bbd250ab5e5fa6b629e3af9e672324.json`이다. 문서 후속 병합만으로 재배포하지 않는다.
<!-- integration-progress-end -->

## 이전 GitHub 감사와 후속 확인

[18:30 구현 감사](specs/implementation-status-audit-20261028.md)와 [동일 화면 환불 복구 명세](specs/refund-inline-existing-repair-20261028.md)는 당시 코드·운영 차이를 남긴 기록이다. 이후 PR #297~#300 검수·배포 근거는 위 최신 진행 기록이 대체한다. 기존 거래 자동 소급처리나 단일 환불 그룹 실제 적용은 수행하지 않았으며, 원문 오류·수동 보류·승인번호 미확인 건은 보호한다. [제품 오너 결정](specs/owner-product-decisions-20261028.md)의 미완료 기능은 사용자 후속 명시 승인에 따라 단계별 구현 중이며 전부 완료된 것으로 표시하지 않는다.

## 2026-10-28 PR #302 잠정 여행 배정 검토 배포 완료

[PR #302](https://github.com/6Soo/cost/pull/302)은 `c1bf76ce3e6e6973dc92e6a3e1c2a145c5e4e661`로 정상 병합·고정 배포했다. owner의 잠정 배정 검토와 20건 페이지, 명시적 보류, 저장된 원본별 교정 제안의 재검증·승인을 추가했다. 수동 결정·환불·원본 보호와 기존 결정 API를 유지한다.

통합 검수는 새 화면/금융 보호 226 passed, 권한/환불/우선배정/OTA 페이지·스냅샷 227 passed다. 변경 Python12개 compile·diff 검사 통과, 선택기 미매핑0, metadata guard 차단0/삭제0. 기존 CardFlow6개 실패는 작업자의 기준61211012 재현 근거를 보존하며 통과 수에 포함하지 않는다. 합성 HTTP/브라우저의 수락을 운영 실자료·실기기 수락으로 표현하지 않는다.

1,084 Git blobs 일치, 새 백업·별도 복원 검증, 작업/프로세스SHA·loopback listener1·health/ready200·보호API401·보호13표 전후 불변을 확인했다. 추가된 trip-review/proposals/hold 경로도 익명401이다. 이전 검증61211012 복구점을 보존했다. 배포 근거는 `D:/WebLedgerHost/releases/deploy-evidence-c1bf76ce3e6e6973dc92e6a3e1c2a145c5e4e661.json`, 로컬 `.local-archive/merge-cleanup-20261028/deploy-c1bf76ce3e6e6973dc92e6a3e1c2a145c5e4e661/`다.

실제 금융/여행 재배정·대량 재처리·명단 전달/보험가입·Google 쓰기·마이그레이션은 실행하지 않았다. PA-01 실자료 기준선 및 PA-06 실자료 shadow/수락은 미측정으로 남긴다. 단일 환불 그룹 적용의 정상 owner 인증 대기는 유지한다. 최종 확인 시 열린 PR은0개다. 후속 문서만의 병합에는 재배포하지 않는다.
## 2026-10-31 웹 전체 불필요 안내 정리 완료

- COMPLETE — 사용자 “기록된 거래 / 총수입-지출 이런 불필요한 안내문구 웹 전체에서 삭제” 반영. [PR #420](https://github.com/6Soo/cost/pull/420)·[PR #423](https://github.com/6Soo/cost/pull/423), 구현 `f9ef9f3`·`1e79213`, 고정 배포 `05d09ce6c0791d7d5ea66414b6def94dcac8109a`.
- 장부 합계의 범위 안내·수입 계산식, 수입의 상시 회계 검증 안내, 카드 조회 도움말, 사이드바·예약 연결·여행 검토·항공권의 반복 조작 설명을 제거했다. 금액/필터/원본 링크·접근성 설명, 실제 합계 차이와 거래별 오류/미확인 상태는 유지한다. 앞선 [전체 화면 상태/행동 조사](specs/actionable-review-ux-audit-20261031.md)의 검토 링크·조회 재시도 수정은 PR #414/#415로 완료된 범위이며 재구현하지 않았다.
- 검증: 최신 통합 금액/수입/필터/자산/지출 중복 75 passed·3 subtests, 모바일/장부/예약 연결 browser 16 passed·6 subtests, 최신 통합 장부 browser 2 passed·4 subtests. 마지막 여행/항공권 검사 28 passed 후 삭제 문구를 요구하던 assertion을 교정해 나머지 1 passed. 실행 간 중복이 있어 합산 전체 회귀로 세지 않는다. 카드 첫 렌더 시간 하한 검사 1건은 기준본에서도 실패함을 재현했으며 통과에 포함하지 않는다. 전체 회귀·전체 운영 인증 화면·실기기 수락은 미실행이다.
- 배포: 1,198 Git blobs 일치·검사본과 배포본의 코드 동일(차이는 문서뿐)·task/process SHA·단일 loopback listener·health/ready200·보호 API 및 cards/all·board·reserve-links401·보호13표 내용/스키마 불변 PASS. 호스트 Python에서 안내 부재/금액/접근성/항공권 버튼 합성 smoke PASS. 코드 전용 전환으로 검증된 이전 `18978698` 릴리스/task XML 복구점을 보존했으며 새 전체 DB 백업·복원은 반복하지 않았다. 금융/분류/여행/Google/원본/스키마 쓰기0.
- 근거: `.local-archive/copy-cleanup-20261031/`의 merged-unit·merged-browser·browser-final·final-hints/corrected·review·runtime-smoke·protection-before/after·deploy-evidence와 호스트 동일 SHA release audit/evidence. 동시 작업자의 운영 종료 후 직렬 배포했고 후속 비교/모달 담당자에게 호스트 쓰기 종료를 통지했다. 기존 사용자 변경과 workspace/미추적 파일은 보존. 이 요청의 미결·차단0, 다음 명령 없음. 문서 후속 변경에는 검사·재배포·서버 재시작을 반복하지 않는다.
## 2026-11-03 두 글자 보험 이름 자동 연결 — 운영 완료

- COMPLETE — 사용자 “이름 두글자면 해당 정보만으로 확정하도록”. [PR #559](https://github.com/6Soo/cost/pull/559) 병합 `6d7c4f59834fa2f245d759ede54dba554e0741d3`. 두 글자 이름은 단일 가림 기호의 위치·길이가 일치하고 같은 여행에서 명단과 수입 후보가 양방향으로 유일하면 별도 확인 없이 자동 연결한다. 원본 이름·수입·금액과 중복 후보·수동 연결/해제·stale 보호를 유지한다.
- 검증 `efaddafb4c5abd23033b7f801af6a7d3a5dd6a7e`: Windows 독립 영향 QA와 PR CI 각각 465 passed·16 subtests·skip 0, 합성 표적 90 passed. PR CI `41573407903`, main CI `41573831949` 성공. 병합에 함께 포함된 PR #558의 CSS/공통 액션 변경은 추가 통합 1 passed. 후보 1,304 Git blobs 불일치 0·review PASS.
- 선행 차단 해소 후 배포 단일 작성자 V124가 `ac2eed16` → `6d7c4f59` → 후속 PR #560 포함 `e75f0b9699bd87fe951ea307712258db974a8677`을 직렬 배포했다. 두 배포 모두 1,304 blobs 불일치 0·task/process SHA·health/ready 200·보호 API 401·보호 13표 불변 PASS다. 해당 배포 완료 시 route 8752/paused false, gateway 8790이며 이전 검증 릴리스와 작업 XML을 보존했다. 이후 별도 PR #561의 `35ec72b8` 배포는 해당 담당자의 운영 기록을 따르며 이 수락은 e75 기준이다.
- 인증된 기존 ego TaskSpace 6/p1에서 최종 운영의 실제 대상이 `no_income`/연결 0건에서 `name_match`/`masked_name_match` 연결 1건으로 바뀐 것을 읽기 확인했다. 실제 수입 행의 `1명 연결`을 펼쳐 `자동 · 이름 글자 일치` 근거와 가로 넘침 0을 확인했다. 원수입 날짜·금액이 기존 조사와 일치하며 6d 배포 후와 e75 배포 후의 수입 13행 digest도 동일하다. 실제 보험 가입·입금 수령을 새로 확인한 것으로 확대하지 않는다. 작업 공간은 정상 종료했다.
- 근거: `C:/AX/cost/.local-archive/insurance-two-character-20261103/`의 checkpoint·review·release-audit·windows-qa·ci·acceptance-after.json 및 호스트 `D:/WebLedgerHost/releases/deploy-evidence-6d7c4f59834fa2f245d759ede54dba554e0741d3.json`, `deploy-evidence-e75f0b9699bd87fe951ea307712258db974a8677.json`. Google/원본/금융 쓰기·대량 재처리·전체 회귀는 수행하지 않았다. 이 요청 미결 0·다음 기능 명령 없음. 문서 후속에는 코드 검사·재배포·서버 재시작을 반복하지 않는다.
- 임시 QA worktree 정리는 경로/사본 해시 확인 후 삭제·정리를 시도하려던 셸 호출 자체가 자동 승인 검토에서 `blocked by policy`로 거부돼 보존했다. 세부 이유는 반환되지 않았다. 우회하지 않았으며 배포와 무관하다. 현재 `C:/AX/cost-two-character-qa-20261103`의 문서 후속 브랜치를 사용하고 공용 checkout의 다른 작업을 보존한다.
## 2026-11-04 넓은 화면 중앙 정렬

- COMPLETE — [PR #618](https://github.com/6Soo/cost/pull/618) 운영 `4758fe63386c10a3cf1f255e7448d3a21c55fdfe`. 홈·여행 관리의 공통 본문과 제목을 중앙에 모으고 영수증 본문을 중앙 정렬했다. 상세 검사·배포 근거는 [운영 기록](operations.md#2026-11-04-넓은-화면-본문-중앙-정렬). Windows 영향 QA 208 passed·27 subtests·skip 0, CI 성공, 운영 PC 7화면 읽기 확인. 실기기·모든 상태 조합은 미검증이다.
