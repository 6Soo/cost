# 다중 카드 파일 접수·백그라운드 분류 UX (2026-11-04)

## 요청과 종료 조건

여러 파일의 접수가 앞선 파일의 분류 완료를 기다리지 않게 한다. 전체 접수 후 다른 페이지로 이동할 수 있다고 안내하고, 복귀 시 파일별 처리 상태를 복구한다. 기존 원본·중복·환불·수동 교정·권한 보호는 유지한다. 배포와 최소 운영 확인까지가 종료 조건이다.

## 구현

- `POST /api/imports/upload-batch`는 multipart의 모든 파일을 먼저 검증·저장하고 기존 durable completion 작업을 등록한 뒤 분류 worker를 시작한다. 금융 쓰기는 기존 `store_lock`으로 직렬화한다. 파일별 검증 오류는 다른 파일 접수를 막지 않는다. 동일 내용은 기존 배치/작업을 재사용한다.
- 단일 파일 API와 개별 파일 20MiB 제한을 유지한다. 일괄 요청은 최대 100개/100MiB이며 클라이언트는 전체 파일 합계 99MiB 이하만 전송한다.
- 접수 응답 즉시 모든 작업 ID를 저장하고 버튼/파일 선택을 활성화한다. 서버 전송 중에는 페이지 유지, 접수 후에는 다른 페이지 이동 가능·백그라운드 분류 계속을 안내한다. 복귀 시 기존 작업을 병렬 조회하며 새 업로드를 막지 않는다.
- 실제 운영 파일 업로드·재분류·여행 배정·Google 쓰기·스키마 변경은 수행하지 않았다.

## 실제 검증과 상태

- 구현/합성 기능 검증 완료, PR [#627](https://github.com/6Soo/cost/pull/627). 파일 전송 및 원본 검사에 필요한 시간까지 0초라고 보장하지 않는다.
- 표적 13 passed. signed bulk 권한 1 passed/4 subtests. 분류를 정지시킨 실제 합성 HTTP 서버에 오류 파일+정상 12개+동일 파일 재업로드를 전송해 정상 12개 접수와 중복 배치 재사용을 확인했다. 최종 notice 변경 후 JS queue 6 passed.
- ego-browser TaskSpace48에서 합성 12개 접수→다른 페이지→업로드 복귀·12개 상태 복구·업로드 버튼 활성·가로 넘침 없음 확인, 작업 공간 종료. 합성 fetch를 사용했으므로 운영 처리 성능·운영 고객 업로드 수락과 구분한다.
- Windows 영향 QA 시작 SHA `e6d97d8f9a07562cca10fb4eac0a5a5f5a104987`: 496 passed/97 subtests, 2 failed, skip0. 실패를 통과로 처리하지 않는다. 실패 2건은 기준 `a912182991739917fcdd961dc04a7234c32f9b08`에서도 재현됐다. 인증 페이지는 현재 HTML 로그인 화면을 JSON으로 파싱하는 기대값 실패이며, OTA signed catalog는 기존 upload jobs 모듈 뒤 실행할 때 total0/기대1로 실패한다. 단독 OTA 검사는 기준에서 통과해 순서 의존성이 있다.
- 근거: Git 제외 `.local-archive/upload-background-20261104/`의 `candidate/quality-artifacts/`, `baseline-failures.xml`, `baseline-order-full.xml`, `browser-05.mjs`, `browser-resumed.png`, `checkpoint.json`.
- 현재 범위 밖 기존 실패 수정 여부는 사용자에게 질문했다. 호스팅 CI 녹색·정상 병합·검증된 SHA 배포는 아직 미완료이며 배포 성공으로 보고하지 않는다. 기존 운영 `f680e7e0b8b6ce6d98cdc30949fa0e2e6d63f99f`를 보존한다.

## 다음 단계

기존 실패 수정 범위에 대한 답변과 PR CI 결과를 확인한다. 허용된 범위에서 검사를 통과한 후 main 병합→공식 단일 작성자 배포→health/ready·보호 API·영향 업로드 화면 읽기·보호13표 확인→SHA 기록을 수행한다. 테스트 제외나 skip으로 녹색을 만들지 않는다.
