# 검수 지적 수정·모든 브랜치 통합·배포

사용자 현재 승인: Paseo `4b30b36d-8542-49d1-9708-206d30d49ade` 검수 지적 수정 후 모든 브랜치 통합 및 운영 배포. 기존 미추적 CloudMail.gs와 작업 계획은 보존한다. 금융/Google/원본 쓰기·마이그레이션은 범위에 없다.

## 변경 및 검증

- 수입 불일치·미검증 시 검색 요약에 전체/검색 지출 금액과 건수를 구별한다. 미검증 수입 금액·차액은 표시하지 않는다. 비검색 표시를 유지한다.
- 콘솔 창 완전 차단 주장을 `pythonw.exe` 전환 완료·다음 예약 실행 수락 NOT_RUN으로 정정한다. 메일 수집을 추가 실행하지 않는다.
- 시작 시 원격 main만 있었으나 진행 중 `fix/lazy-ota-expense-review-20261027` / PR #189가 추가됐다. 고유 커밋 `3051892`, `d0795f7`, `30e0ab9`를 통합했다. OTA 검토는 닫힌 상태에서 조회하지 않으며 펼칠 때만 읽는다. 닫았다 다시 펼칠 때 조회 재개와 summary 포커스 때문에 초기 렌더가 보류되는 문제를 추가 보완했다. 기존 선택·미리보기·확정 보호 코드는 유지한다.
- `test_income_summary_display.py`: **9 passed**.
- `test_trip_google_income_browser.py -k discrepancy`: **1 passed, 2 deselected**.
- 새 OTA 지연조회 계약/브라우저 검사: 계약·닫힘·열기·재열기·선택 보존 **2 passed**; 직접 링크 두 종류는 테스트 응답의 UTF-8 헤더 누락을 고친 뒤 **2 passed, 2 deselected**. 변경 없는 통과 검사는 반복하지 않았다.
- `test_ota_payment_review.py`: **38 passed, 1 failed**. 실패는 Windows 임시 DB 정리 잠금이며 기준 main의 해당 검사에서도 **1 failed**로 재현했다.
- `test_ota_payment_review_browser.py`: **5 passed, 10 failed**(subtest 포함). 기준 main은 **3 passed, 동일 10 failed**. 추가 통과2개는 새 지연조회 검사다. 실패는 기존 후보 상세의 즉시 노출 가정 및 임시 DB 정리 문제이며 수정 범위로 확대하지 않았다.
- `test_ota_preview_race_browser.py` + `test_ota_matching_defaults_browser.py`: **2 passed, 3 failed**; 기준 main도 **2 passed, 동일 3 failed**. 기존 접힌 예약 근거의 가시성 기대에서 실패한다. 이번 지연조회 동작에 맞춰 테스트의 최상위 OTA 영역만 명시적으로 연다.

## 실행 상태

**COMPLETE:** #189/#190 정상 병합·운영 SHA `183d813301a4fcc4cab78d52a8d7e2ff2074be63` 한 번 배포. 982개 blob 일치, 작업/프로세스 SHA 일치·단일 loopback listener·health/ready200·보호API401·13개 보호 표 전후 동일. 이전 운영 SHA `84e602ee76f4b50a072e43520af3cd886cebb423`와 기존 복원 검증 사본을 보존했다. 운영 `/import` 초기 접힘/API0건·펼침200·재접힘, 장부 검색 전체/결과 지출 구분과 원래 화면 복귀 확인. 두 경고 상태는 배포된 모듈의 합성 입력으로 검증했다. 전체 pytest/전체 E2E·금융 재대사·메일 수집·Google 쓰기는 실행하지 않았다. 콘솔 다음 예약 실행 수락은 NOT_RUN 유지. 문서 증빙 후속 PR은 앱 재배포 없이 통합한다.

로컬 증거: `.local-archive/income-summary-fix-20261027/`의 기준 main archive·실패 비교 로그·고정 릴리스 생성/검증·배포/보호 스크립트.
