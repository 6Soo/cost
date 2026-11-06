# 여행 헤더·본문 작업 배치 교정 (2026-11-05)

상태: COMPLETE — 최신 사용자 배치 구현·최종 영향 QA·독립 리뷰·병합·운영 배포 및 실제 화면 확인 완료.

## 최신 수락 계약

사용자 최종 답변: **헤더에는 XLSX 출력만, 나머지는 본문 작업 영역으로 이동.** 이전의 여행 관리 상단 통합 기록보다 이 답변을 우선한다. 헤더의 마감/여행 관리/예약·참가자를 모두 제거하고 본문 `여행 작업` 툴바에 이동한다. 기존 보험가입내역·여행 검토·수기 지출 추가와 같은 영역에서 사용하며 좁은 화면은 줄바꿈한다. 기능·권한·CSRF·revision·동일 여행 복귀·원본/금융/Google 보호를 유지한다.

## 원인과 수정

초기 첨부에는 `summary.site-action`의 margin8px 때문에 여행 관리가 다른 버튼보다 8px 내려가는 문제도 있었다. 정렬만 수정한 첫 범위는 사용자의 배치·구성 지시를 충족하지 않아 PR690을 초안으로 유지했다. 최종 답변으로 제품 요구를 확정해 배치까지 수정했다.

- `ledger_design.py`: `_head_html`에는 XLSX만 표시, `_trip_actions`로 기존 관리폼과 예약 링크를 이동. 기존 endpoint와 필드·기능을 재사용한다.
- `ledger_design.css`: 본문 툴바의 flex-wrap을 허용해 작은 화면에서 겹침 없이 배치한다.
- `trip_management_ui.py`: 펼침 버튼의 바깥 여백0을 유지한다.
- 회귀: 헤더 출력 전용, 본문 관리/예약 위치, 버튼 높이·정렬·넘침, 키보드 열닫, 예약 iframe과 여행 맥락을 실제 제품 서버에서 검사한다. 기존 툴바 검사는 줄바꿈과 이동된 직접 링크를 반영한다.

## 검증 근거

기존 정렬 변경2436f8ac는 308 passed·66 subtests·skip0, 필수브라우저30개 전건, CI42036855880 SUCCESS였다. 이는 최종 배치 변경의 검증을 대체하지 않는다. 병렬 root user_action_queue 미커밋 영향의 QA는 중단했고 사용자/타 작업 변경을 보존했다.

최종 배치 표적: 13 passed·9 subtests passed. 헤더/본문/마감·예약·권한·동일 여행 연결 검사를 포함한다. 추가 geometry2검사·4subtests도 통과했다. 최종 브라우저 증거는 `.local-archive/trip-header-align-20261105/placement-*.png`, `placement-results.json`; 이전 정렬 PNG와 결과도 별도 보존한다. 실고객 자료는 사용하지 않는다.

`better-interface`, better-layout/ui/typography/colors/accessibility/writing 및 ui-ux-pro-max 지침을 읽어 적용했다. 정렬 단계 리뷰와 별도로 최종 배치 변경의 독립 Luna interface-review를 다시 받아 Approve를 확인했다. 실제 스크린리더·실기기는 미검증이다.

## 작업·배포 경계

[PR690](https://github.com/6Soo/cost/pull/690)을 최신 범위로 갱신해 정상 병합했다. 선행 보험PR689와 항공PR684는 최신 main 병합으로 보존했고 해당 코드 재구현은 없다. 작업공간 `C:/AX/cost-trip-header-qa-20261105`, root는 타 작업 user_action_queue 변경을 보존하므로 수정하지 않는다. Ego TaskSpace36 재사용.

완료: 최종 영향QA → 독립 UI 리뷰 → PR CI 정상 병합 → 검증 main SHA 고정 공식 단일배포 → health/ready·보호API·보호13표·배치 경로 확인 → 운영 SHA 기록. 금융·Google·고객 원본·분류·여행 배정·환불 업무 쓰기와 마이그레이션은 수행하지 않는다.

## 최종 수락·배포 (2026-11-05 23:36 KST)

- 최종 제품 b4e3903c, 병합/운영 `5ede21297b93c648fb631c111b3150bcdc6df739`. PR CI42044031101와 main CI42044789877 SUCCESS. Windows 최종 영향 base8095d8ec 고정 387 passed+99subtests·skip0·필수browser29/compile PASS. 이전 인계 실행은 종료 근거가 없어 재실행했으며 합산하지 않는다. 병합 후 origin/main 기준 NO_CHANGES는 제품 검사 통과 근거가 아니다.
- 독립 최종 interface-review Approve, 테스트 위치 계약 갱신과 비동기 예약 패널 준비 대기4줄 보완 후에도 승인 유지. 합성8조건·키보드·200% 확인, 최종 UI는 승인 배치 그대로다.
- 공식 배포 이전6a6095bd→5ede2129, 1415 tracked blobs불일치0·runtime SHA검증·listener1·gateway8790→8752·health/ready200·보호API401·보호13표불변. financial_apply NOT_RUN. 공식 잠금 반납.
- 인증 운영1440/390px DOM에서 헤더XLSX단독/본문관리·마감·예약 및 overflow0·키보드열닫/포커스 확인. 1440px 운영 화면 시각 확인. 390px 운영 PNG는 리사이즈 직후 이전 프레임이 남아 시각 수락 근거로 제외한다. 390px 시각 검증은 합성 동일 크기 전후 화면이며 실제 물리기기·스크린리더는 미검증이다.
- 비공개 증거는 `.local-archive/trip-header-align-20261105/`의 placement-run-summary.json, placement-junit.xml, placement-final-quality.log, placement-interface-review.md, placement-results.json, production-browser.json 및 deploy-evidence.json. 호스트 동일SHA deploy-evidence도 보존한다. 고객 원문/화면 Git포함 없음.
- 현재 요청 미결0. root의 타 작업 미커밋 파일과 사용자 자료는 보존한다. 기록만의 후속 커밋으로 재배포하지 않는다.
