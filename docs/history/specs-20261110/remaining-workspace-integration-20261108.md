# 남은 COST 작업공간 4곳 통합·정리 (2026-11-08)

상태: 변경 판정·구현·영향 검증 완료. 최종 SHA별 승인과 실제 병합은 해당 PR의 Final review 및 GitHub merge 기록, 작업공간 정리 결과는 비공개 실행 기록으로 확정한다. 운영 배포는 이번 범위에 없다.

## 승인 범위와 판정

사용자는 완료 작업 정리 후 남긴 4곳도 진행하도록 승인했다. 기존 main 기능을 보존하면서 미통합 변경을 검수하고, 유효한 차이만 통합한다. CI가 결제/한도로 시작하지 못한 경우에는 실제 Sol medium 이상 모델의 최종 SHA 검수 승인이 있어야 병합한다. 실제 테스트 실패를 예외로 통과시키지 않는다.

| 작업공간 | 기존 변경 | 처리 판정 |
| --- | --- | --- |
| root `269954f1` | 수입표 폭 및 초기 작업함 스냅샷 | 수입표는 #723으로 이미 반영. 초기 스냅샷은 현재 main의 요청 단위 스냅샷·엄격한 유효성 검사로 대체됨. 테이블 누락을 0건으로 표시하는 fallback은 현재 오류 계약과 충돌하므로 제외. 원래 커밋과 로그 보존 후 기본 main checkout으로 복귀 |
| card-coverage `67eb55c4` | `0856c6cb`/`792aa9f0` 카드 업로드·구 경로 통합 대안 | #713 통합 IA·#714 조회 최적화·#717 수집기간 검토로 대체됨. 예전 구현을 현재 코드에 덮지 않고 전체 복구 사본을 보존해 정리 |
| pr683 `f1f06242` 미커밋 | 오류 메뉴 문구/기대값 2파일 | 유효한 차이로 통합. 보이는 문구를 기존 접근성 이름과 같은 `내 확인 필요 수를 확인할 수 없음`으로 정리하고 문구 전용 줄바꿈 규칙 적용 |
| pr685 `4c2e9656` 미커밋 | 17개 tracked 변경·미추적 `card_upload_panel.py` | 더 오래된 CARD-IA 대안. 현재 main에 같은 페이지 업로드/수집 현황·결과·구 링크/권한 보호가 이미 구현됨. 전체 트리·patch·미추적 모듈 보존 후 정리 |

## 실제 변경과 보호

`ledger_design.py`의 오류 문구와 전용 class, `site_shell.css`의 해당 문구 줄바꿈, 기존 작업함 검사 기대값만 변경한다. 정상 건수·요청 스냅샷·자료 오류·상태 전이·owner/CSRF·금융/원본/중복/환불/OTA/Google 보호는 유지한다. 카드 대안의 SQL·구 worker·예전 UI 기대값을 현재 구현에 다시 넣지 않는다.

첫 문구 수정 `d6e99a4a`는 실제 영향 검사에서 1440px 사이드바 11px 넘침을 만들었다(1 failed·267 passed). 실패를 보존하고, 오류 문구에만 공유 메뉴 줄바꿈을 적용한 `ea80f7d90a3fda526e9f36d16adf725ac27fd29f`로 교정했다. 해당 실패 시나리오와 작업함 표적 검사는 14 passed·2 subtests passed였다.

## 검증 근거와 한계

- 최신 Windows 영향 QA: SHA `ea80f7d90a3fda526e9f36d16adf725ac27fd29f`, base `8d3b66d3978385fcde5808e06dbcde17606512de`. **298개 검사·skip0·필수 브라우저21개 전건실행·compile 통과**. 검사 대상은 run-summary.json/JUnit에 보존한다.
- 합성 ego TaskSpace70: 동일 크기의 before/after 1440/390/320px·light/dark 12장. 글꼴 로드와 메뉴 이동 완료 후 navX0·메뉴/페이지 넘침0·잘림 없음. PC 오류 문구만 두 줄로 표시한다.
- 키보드 포커스 표시와 Enter `/my-actions` 진입, 실제 queue 오류 renderer의 다시 불러오기 안내·zero=false 확인. CSS 200% 확대 두 테마 넘침0. 실측 문구 대비17.06:1.
- 초기 메뉴 이동 중 캡처와 로컬 MIME 오설정으로 실패한 recovery는 최종 수락 근거에서 제외하고 `verified-*` 및 `zoom-results.json`으로 교체했다.
- 실제 `better-interface`·`better-layout`·`better-ui`·`better-typography`·`better-colors`·`better-accessibility`·`better-writing` 적용. `interface-review` 스킬은 제공되지 않아 실행했다고 주장하지 않는다. 별도 실제 `gpt-6.1-sol / medium` 검수자가 제품 SHA `ea80f7d9`를 APPROVE했다. 문서 커밋 후 최종 SHA도 별도로 확인한다.
- 물리 기기·수동 스크린리더·번역/RTL·실제 OS 확대·인증된 운영 화면은 미검증이다. 합성 화면을 운영 수락으로 보고하지 않는다.

## 정리·보존·후속 범위

복구 bundle과 tar.gz의 파일별 SHA256을 검증한 뒤 세 임시 worktree와 완료 브랜치를 정리한다. Paseo가 관리하는 pr683은 공식 archive로 정리하고 root는 삭제하지 않으며 main checkout 하나로 유지한다. 이전/신규 QA·미추적 모듈·브라우저 스크립트·무시된 파일도 비공개 보관한다. 기존 stash 6개의 SHA를 그대로 보존한다. 오래된 card-coverage 합성 미리보기 프로세스 4개는 종료했다.

비공개 실행 기록: `C:/AX/cost/.local-archive/remaining-four-20261108/`의 decisions.md, preserved.json·각 tar.gz/manifest, refs-before.bundle, qa-red/qa-green, verified-browser-results.json·PNG, zoom-results.json, contrast.json, 독립 검수 및 최종 merge/summary. 고객 원문은 Git에 포함하지 않는다.

이번 요청에서 운영 배포·재시작·운영 DB/금융/원본/Google 쓰기는 실행하지 않는다. 과거 미배포 항목은 유지하며, 과거 후보 SHA를 현재 배포 지시로 사용하지 않는다. 이 정리 기록은 새 기능 개발 큐가 아니다.
