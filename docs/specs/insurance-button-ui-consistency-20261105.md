# 보험 명단 버튼 UI 통일 (2026-11-05)

상태: **COMPLETE — 요청 화면 구현·독립 검토·병합·운영 배포 완료**. 기존 별도 모바일 배치 검사 실패는 아래에 구분한다.

- 범위: 첨부된 여행 수입표의 보험 명단 열. 연결·미연결·후보 확인에 공통 최소 높이 44px, 여백 6px/9px, 테두리, 모서리 8px, 글꼴·색상·상태 스타일을 적용했다. 공통 shell decorator가 미연결 버튼을 다시 장식하지 않도록 제외했다. 환불완료는 상태 텍스트로 유지했다.
- 구현 커밋 `3004a69edf7d3271d336c5192b62b3bb1a22b2d7`, [PR #682](https://github.com/6Soo/cost/pull/682), 병합/운영 SHA `1b8aafc06ef3d692b6f7e8f691bb16a755ab2263`. 금융 금액·원본·Google·참가자 연결 데이터/API·스키마 변경과 재처리는 없다.

## 진단·검증

| 요구사항 | 상태 | 근거 |
| --- | --- | --- |
| 버튼 외형 일관성 | COMPLETE | CSS 공통 규칙, computed height/padding/border/radius/font/color 비교 |
| 기존 동작·금융 보호 | COMPLETE | 표적 21 passed, Google/OTA exact/refund/access 보호 포함 영향 검사, 배포 전후 보호 13표 불변 |
| 모바일·테마·키보드 | COMPLETE | ego-browser 합성 화면 320/390/720/1440px × light/dark, Enter 상세 열기/닫기·visible focus, 동일 크기 before/after 보존 |
| 독립 UI 리뷰 | COMPLETE | 별도 Luna medium reviewer의 interface-review Approve; Introduced/Regression HIGH/MEDIUM 없음 |
| 코드 병합·배포 | COMPLETE | PR/main hosted CI 성공, 공식 단일 작성자 배포, runtime SHA 일치·smoke 성공 |

원인(MEDIUM)은 동일 열에서 미연결만 테두리 버튼이고 연결·후보 확인은 텍스트형인 불일치였다. 기존 구조와 토큰을 재사용하는 최소 변경으로 교정했다. `better-interface`, `better-layout`, `better-ui`, `better-typography`, `better-colors`, `better-accessibility`, `better-writing`, `ui-ux-pro-max`를 실제 읽어 적용했다. 변경 범위는 독립 리뷰에서 `interface-review`로 검토했다. 독립 리뷰는 소스/합성 preview를 확인했고 브라우저는 주 작업자가 실행했다.

렌더링 텍스트 대비는 light **4.90:1**, dark **8.11:1**이다. 화면 증거와 세부 coverage는 로컬 `.local-archive/button-ui-20261105/`의 `before-*.png`, `after-*.png`, `browser-results.json`, `interface-review.md`에 보존했다. 실제 고객 화면·고객 원문을 보고서나 Git에 넣지 않았다.

Windows 영향 QA는 `python tools/run_quality_checks.py --base origin/main --run`으로 실행했다. base `3499aed55a25add219fbe556a8210a68a0240140`, head `3004a69edf7d3271d336c5192b62b3bb1a22b2d7`: **209 passed, 36 subtests passed, 기존 실패 1, skip 0, 필수 브라우저 21개 전건 실행, compile 통과**. 총 결과는 `FAILED`이며 전체 통과로 기록하지 않는다. 유일 실패 `DesignScreenTests::test_one_trip_button_and_a_short_notice_at_390`은 첫 거래 top `852.765625`가 viewport `844`보다 작아야 한다는 기존 검사다. 변경 전 CSS/JS를 복원해 동일 값으로 재현했으므로 범위 밖 수정으로 확대하지 않았다. 테스트를 제외하지 않았다.

PR CI [42029891492](https://github.com/6Soo/cost/actions/runs/42029891492), main CI [42031450310](https://github.com/6Soo/cost/actions/runs/42031450310)는 SUCCESS다. 이번 main 배포에 포함되는 기존 카드 업로드 관리 코드도 별도 인접 검사 **24 passed**를 확인했다. 실제 스크린리더·axe와 요청 버튼 자체의 200% 확대 스트레스 출력은 미검증이며, 공통 shell 200% 비교 검사는 영향 QA에서 실행됐다.

## 운영 근거

- `deploy_verified_release.ps1 -Apply`로 이전 `aaa96c5c8eef567d76f8e6f9da28be2e5587642f`에서 `1b8aafc06ef3d692b6f7e8f691bb16a755ab2263`로 전환했다. 병렬 항공권 작업과 배포 단일 작성자를 조율했으며 완료 후 작성권과 잠금을 반납했다.
- 1,409 tracked blobs 불일치 0, task/process SHA 일치, 단일 loopback backend 8752, Gateway 8790→8752, paused false. health/ready 200·보호 API 3개 401·참가자 trip-panel/state 익명 401. 보호 13표 불변, 금융 apply `NOT_RUN`. 별도 전체 DB 백업/복원은 code-only 변경이므로 수행하지 않았고 이전 검증 릴리스를 보존했다.
- 배포 증거: `D:/WebLedgerHost/releases/deploy-evidence-1b8aafc06ef3d692b6f7e8f691bb16a755ab2263.json`, 로컬 `.local-archive/button-ui-20261105/deploy-evidence.json` 및 `release-audit.json`. 운영 시각 2026-11-05 22:05 KST.
- 이번 요청의 남은 구현·배포 작업 없음. 후속 문서 기록만으로 재배포하지 않는다. 기존 모바일 배치 검사 실패와 미검증 접근성 항목은 완료 사실에 포함하지 않는다.
