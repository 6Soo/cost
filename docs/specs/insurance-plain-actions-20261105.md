# 보험 명단 텍스트 동작·행 높이 복구

상태: **COMPLETE — 구현·표적 검사·브라우저·독립 리뷰·영향 QA·병합·운영 배포 완료**.

최신 사용자 요청은 보험 명단 열의 파란 강조와 박스를 제거하고 버튼 기능만 유지하며 행 높이를 복구하는 것이다. 이전 [버튼 통일](insurance-button-ui-consistency-20261105.md)의 44px/테두리 외형 결정은 이번 요청으로 대체한다. 금융·원본·Google·참가자 연결 데이터/API는 변경하지 않는다.

| 진단 | 위치·재현 | 영향·심각도 | 수정·검증 |
| --- | --- | --- | --- |
| 보험 버튼이 행 높이와 강조를 증가시킴 | `webapp/static/css/ledger_design.css` 보험 셀의 44px 최소 버튼·45px 셀·모바일 57px 셀 | 표 정보 밀도·인접 상태와 일관성 저하, MEDIUM | 공통 텍스트색·투명 배경·테두리/여백 0, 24px 최소 타깃, 기본 셀 36px |

| 요구사항 | 상태 | 실제 근거 |
| --- | --- | --- |
| 파란 강조·테두리 박스 제거 | COMPLETE | 연결/미연결/후보의 computed color가 셀과 같음, border 0·transparent, hover 밑줄 |
| 행 높이 복구 | COMPLETE | 합성 실제 렌더: 데스크톱 45→36px, 모바일 전체 행 93→72px, 환불완료 포함 동일 높이 |
| 연결·상세 동작 유지 | COMPLETE | 기존 native button/summary·JS 보존, 표적 22 passed, Enter 열기/닫기·포커스 확인 |
| 반응형·접근성 | COMPLETE (검사 범위 한정) | Ego35의 320/390/720/1440px × light/dark, 200% CSS 확대, 긴 이름 줄바꿈·가로 넘침 없음, 실제 대비 양 테마 17.06:1 |
| 독립 UI 리뷰 | COMPLETE | Luna medium `4b76899e-c79c-4a27-ab60-9b0b78741bad`, interface-review 정적 Approve, introduced/regression HIGH/MEDIUM 없음 |
| 영향 QA·CI·병합 | COMPLETE | Windows 208 passed +36 subtests, skip0·필수 브라우저20 전건·compile 통과. PR689 CI42036622325 SUCCESS, 병합 a88257a8 |
| 운영 배포 | COMPLETE | 운영6a6095bd, 1,414 blobs 불일치0·runtimeSHA 일치·health/ready200·보호API401·보호13표 불변 |

`better-interface`, `better-layout`, `better-ui`, `better-typography`, `better-colors`, `better-accessibility`, `better-writing`을 읽어 기존 시스템 안에서 적용했다. `ui-ux-pro-max`의 compact table target size 검색은 웹 WCAG 24px 최소 타깃을 확인했다. 독립 리뷰는 정적 범위이며 실제 렌더링은 주 작업자가 `ego-browser`로 검증했다. 실제 스크린리더·물리 기기·axe·브라우저 자체 200% 확대는 미검증(CSS zoom=2 검증과 구분).

구현 SHA `8a206b7c8f9d9a95c7a0f5c2b36eebed740bbb52`, 기준 `4c2e9656f4674a378da6dda6369697b4f4793f10`. 증거는 `C:/AX/cost/.local-archive/insurance-plain-20261105/`의 before/after PNG, browser-results.json, stress-results.json에 보존한다. 고객 원문은 사용하지 않았다. 동시 root 작성으로 실제 격리가 필요해 기존 변경을 보존하고 별도 worktree에서 영향 QA/PR을 진행한다.

## 병합·운영 근거

- [PR #689](https://github.com/6Soo/cost/pull/689)의 head `455cb52cf794763746c806435e0908e6fb19464a`, 병합 `a88257a8be9a34bda94e2967074eb548231fd7ec`. PR CI [42036622325](https://github.com/6Soo/cost/actions/runs/42036622325) SUCCESS. a882 push CI는 후속 문서 병합에 의해 취소됐으며 통과로 기록하지 않는다. 후속 main `6a6095bdf3ede9f16d5c6d075d35ef6ee1a011df`는 a882와 Markdown 3개만 다르고, 해당 [CI42037790866](https://github.com/6Soo/cost/actions/runs/42037790866)는 SUCCESS다. 보험 CSS/test blob은 Windows 검증8a206b7c와 동일하다.
- 2026-11-05 22:43 KST 공식 `deploy_verified_release.ps1 -Apply`로 이전 `ae64bd19c29f6a5347212f53c25408f870e283ac`에서 `6a6095bdf3ede9f16d5c6d075d35ef6ee1a011df`로 단일 작성자 전환했다. 1,414 tracked blobs 불일치0·runtime/task SHA 일치·loopback listener1·Gateway8790→8751·health/ready200·보호API3개401·보호13표 전후 불변. 금융 apply NOT_RUN, Google/원본/연결 데이터·스키마·재처리 없음. 기존 검증 릴리스를 보존했고 code-only 변경에 별도 전체 DB 백업/복원은 수행하지 않았다.
- 증거: 로컬 동일 폴더의 run-summary.json/junit.xml/pytest.log/interface-review.md/release-audit.json/deploy-evidence.json, 호스트 `D:/WebLedgerHost/releases/deploy-evidence-6a6095bdf3ede9f16d5c6d075d35ef6ee1a011df.json`. 실제 인증 운영 수입표의 추가 재탐색은 미실행이며, 합성 렌더와 배포 blob 검증으로 구분한다.
- 구현·운영 미결0, 다음 기능 명령 없음. 이 후속 기록은 문서 전용이며 재배포/재시작하지 않는다. 원래 사용자 변경과 병렬 여행 헤더/작업함 작업은 보존한다.
