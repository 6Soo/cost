# 카드 업로드 조회기간 구현·검증 기록

기준: [PR #479](https://github.com/6Soo/cost/pull/479)의 [금융 명세](finance.md). 최신 사용자 요청은 열린 PR의 미구현을 ANUS Free Auto 두 개에 위임해 구현하고 계속 진행하는 것이다. 당시 #477은 구현된 UI 변경이라 새 개발 대상이 아니었고, 이후 생긴 #484는 이번 범위에 추가하지 않았다.

## 현재 상태

- IMPLEMENTED / RELEASE_PENDING: ANUS Free Auto 두 명의 저장·계산 및 UI/API 결과를 주세션이 인수·교정·통합했다. 최초 완료 보고의 결함은 실제 검사로 재현해 수정했으며 보고 자체를 수락 근거로 쓰지 않았다.
- 구현 `52498478`, 비동기 업로드 보존 통합 `b2daa1ef`. 시작 SHA `f1e6453d`, 최신 코드 통합 기준 `699eb8ed`.
- 기존 업로드 이력·변경 로그만 사용한다. 생성자·조회 GET·기능 저장 모두 DDL이 없고 기존 require-schema 계약을 변경하지 않는다. 과거 거래로 조회 확인을 역산하지 않는다.
- 운영 배포·실제 자료 업로드/재처리·Google 쓰기는 아직 미실행이다. 호스트 작성권은 선행 배포 담당자가 해제했으며 검증 SHA를 직렬 배포한다.
- 기존 `C:/AX/cost`의 사용자·병행 변경을 보존하고 `feat/card-upload-coverage-20261102` 격리 작업 공간만 사용한다.

## 수락 조건과 실제 근거

| 조건 | 상태 | 검증 근거 |
| --- | --- | --- |
| 1. 거래가 드문 조회기간 | PASS | sparse_transactions: 거래일 범위와 독립된 양끝 포함 구간 |
| 2. 거래일과 조회기간 분리 | PASS | merchant_dates / existing_transactions: 거래·가맹점 날짜로 확인 생성 금지 |
| 3. 증빙 있는 0건 조회 | PASS | zero_transactions 및 실제 signed HTTP 0건 업로드→소유자 확인→조회 |
| 4. 공백 계산 | PASS | intervals_merge / management_start / requested_window: 중간·후속 공백, 관리 시작·기준일 경계 |
| 5. 카드·기준 격리 | PASS | 다른 발급사/마스크/기준 격리, 끝4만 있으면 파일별 격리; 클라이언트 ID 위조 거부 |
| 6. 멱등·부분 실패·재조회 | PASS | 동일 원본·재확인 무변경, 실패 파일 뒤에도 기존 성공 증빙 유지; async 결과에 파일별 증빙 |
| 7. 과거 비소급 | PASS | 기존 거래만 있는 DB의 조회 확인 기록 0 |
| 8. 기존 화면 연동 | PASS | ego 합성 320/390/1440px 넘침0, 두 파일 중 첫 파일에만 저장, 44px 버튼, HTML 삽입0, CSRF 전달 |
| 9. 보호 불변 | PASS | signed HTTP 로그인/소유자/CSRF, 원본 해시 검증, change_log 외 모든 표 불변, schema/OTA exact/refund 보호 검사 |

## 검사와 한계

- 최신 main 통합 후: `python -m pytest tests/card_pipeline/test_card_upload_coverage.py tests/card_pipeline/test_card_upload_coverage_review.py webapp/tests/test_card_upload_coverage_api.py webapp/tests/test_card_upload_coverage_ui.py webapp/tests/test_card_upload_jobs.py webapp/tests/test_signed_session_http.py -k 'coverage or upload or job' -q` → **52 passed, 13 deselected, 7 subtests passed**.
- 인접 보호: `python -m pytest tests/card_pipeline/test_schema_gate.py tests/card_pipeline/test_ota_exact_gate.py tests/card_pipeline/test_partial_refund.py tests/test_upload_double_auto_record.py webapp/tests/test_card_upload_controls.py webapp/tests/test_upload_response_summary_ui.py -q` → **62 passed, 1 failed**. 실패는 `test_upload_queue_continues_after_failure_and_preserves_each_outcome`가 새 탭 UI의 업로드 탭을 열지 않아 숨긴 버튼 클릭에서 30초 시간 초과한다. 변경 전 `699eb8ed`의 `page()`로 같은 검사를 실행해 동일 실패를 재현했다. 실패를 통과로 세지 않으며 범위 밖 테스트 수정은 하지 않았다.
- 실행들은 중복이 있으므로 합산 전체 회귀 수치로 쓰지 않는다. `git diff --check` PASS. 전체 회귀·실기기·실제 고객 파일 업로드는 미실행이다.
- ego-browser와 ui-ux-pro-max의 폼 라벨·인접 메시지·44px 터치·반응형 지침을 적용했다. 최종 TaskSpace19 종료. 로컬 `.local-archive/card-upload-coverage-20261102/browser-evidence.json`에 합성 요청·폭별 검사 저장. 검사 후 부가 snapshot의 selector 오류는 refs 방식으로 복구하고 정상 종료했다.
- 메타데이터는 지원하는 명시 조회조건만 제안한다. 파싱 오류·제한 조회·부분 다운로드·중복 조회조건 충돌·행/메타데이터 카드 불일치·식별 누락 행은 사용자 확인으로 승격하지 않는다. 끝4만 식별된 파일은 다른 파일과 합치지 않는다.
- 과거 기록 자동 보정·금융 분류·여행 배정·환불 확정·Google 최종 장부 쓰기는 이 기능의 효과가 아니다. 코드 배포는 운영 DB나 원본 변경을 포함하지 않는다.

## 다음 실행

구현 PR 검토·main 정상 병합 → 검증 코드 동일성 확인 → 선행 운영 SHA `699eb8ed6b2c796b1da7841e4605db7c0ef38fc2`를 복구점으로 코드 전용 배포 → health/ready·보호 API·호스트 합성 영향 경로·보호13표 비교 → 운영 SHA와 현재 상태 기록.
