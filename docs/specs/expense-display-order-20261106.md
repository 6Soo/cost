# 여행 장부 지출 표시 정렬 (2026-11-06)

현재 요청: 지출을 항공료 → 숙박비 → 나머지로 묶고 숙박비는 이용 시작일 오름차순으로 표시한다.

- 대상: 여행 장부 PC 표·모바일 목록과 자동 새로고침 조각. 기존 항공/숙박 항목 이름 판정을 재사용한다.
- 숙박 이용일: 화면 표시와 동일한 저장 service_period 또는 기존 카드 예약 근거를 사용한다. 잘못된 날짜·역전·기존 허용 기간 초과·날짜 없음은 숙박 그룹 끝에 둔다. 동률은 입력 순서 유지. 결제일로 이용일을 추정하지 않는다.
- 화면의 Google 대조 정렬 뒤에 최종 그룹 정렬을 적용한다. 항공료 및 나머지는 기존 내부 순서를 유지한다. 기존 Google 대조 관계·표시와 합계는 유지한다.
- 복사/TSV에 쓰는 `_selected_rows`의 기존 순서와 저장 원행은 보존한다. 금융·분류·여행 배정·환불·Google/원본 쓰기 없음.

목적/변경 동작/직접 영향은 위 범위다. 종료 조건은 표적 검사·영향 QA·독립 검토·PC/모바일 전후 확인·CI 성공·정상 병합 및 공식 코드 배포 후 최소 스모크다.

검증 진행:

- 표적 `python -m pytest webapp/tests/test_ledger_display_updates.py webapp/tests/test_expense_amount_group_board.py -q`: 13 passed. 잘못된/누락 날짜·동률·예약 근거 보완·배열 불변·Google 대조가 있는 full/live PC/모바일·복사 순서 보존 포함.
- 독립 Luna medium 코드 검토: 도입 결함 없음, 범위 한정 승인. 리뷰어는 런타임 미실행. 승인된 선행 무료 모델 3개는 실제 목록에 없었다.
- 실제 better-interface/layout/ui/typography/colors/accessibility/writing 스킬을 읽어 적용했다. 행의 DOM/시각 순서 일치와 기존 표시/조작 보존을 검토했다. 별도 interface-review 스킬은 사용 가능 목록·로컬 경로에 없어 실행했다고 주장하지 않는다. 독립 코드 검토와 실제 브라우저 검증으로 가능한 범위를 진행한다.
- 영향 QA·브라우저·CI·배포: **요청 범위 COMPLETE.** Windows 영향280passed+43subtests·skip0·필수브라우저6개 전건 실행·compile 통과, PR702 CI42162001819/main CI42162367681 SUCCESS. 운영 `2dd1b1605eb7122ebb630d1cff4b0596f157c3bc`에서 PC1440/모바일390px의 항공→숙박→나머지, 관측된 숙박 시작일/날짜 미상 마지막 순서·넘침0을 확인했다. 관측 숙박 시작일은 같은 날이므로 여러 시작일/연도 경계는 표적 합성 검사 근거와 구분한다. 각 화면의 기존 Google 대조 내부 순서는 유지하며 전체 행 ID 배열의 PC/모바일 동일성은 요구하지 않는다. 보호13표·금액·복사 원행 쓰기 없음. 상세는 [현재 상태](../session_handoff.md)와 [운영 기록](../operations.md)에 기록한다.
- 비공개 로컬 증거: `C:/AX/cost/.local-archive/expense-order-20261106/`. 합성 자료만 저장소에 사용한다. 물리 기기·수동 스크린리더 미검증.
- 기존 workspace의 미커밋 user_action_queue 및 미추적 로그를 보존하기 위해 최신 origin/main에서 격리 worktree를 사용했다. 해당 사용자 변경은 이 PR에 포함하지 않는다.
