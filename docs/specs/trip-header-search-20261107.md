# 여행 장부 작성일·담당자·본문 검색 정리

상태: **PARTIAL — 구현·로컬 영향 QA·브라우저·독립 리뷰 완료, CI 계정 제한으로 병합·운영 배포 차단**.

## 승인 범위와 구현

사용자 요청은 “작성일 항목 삭제 / 담당자는 날짜 오른쪽 위로 / 여행 탭 내 검색 메뉴 전체 삭제”이며 후속 답변 **“본문 검색 영역만 삭제”**를 우선한다.

| 요구사항 | 구현 및 근거 | 상태 |
|---|---|---|
| 작성일 표시·입력 제거 | 여행 헤더 및 여행 내 관리 폼의 `prepared_on` 입력 제거. 저장 값·기존 API 유지 | 구현·합성 화면 확인 |
| 담당자 위치 | 제목 행의 오른쪽, 날짜 위에 배치. 모바일 줄바꿈·긴 이름 허용 | 구현·합성 화면 확인 |
| 본문 검색만 제거 | 실제 여행의 검색창·수입/지출 필터·검색/초기화 버튼 제거. 사이드바 여행 검색·기존 q/kind URL·다른 탭 검색·모바일 메뉴 유지 | 구현·합성 화면 확인 |
| 병합·운영 수락 | [PR #724](https://github.com/6Soo/cost/pull/724) 열림. 호스팅 CI 녹색 이후만 병합 | BLOCKED_CI_ACCOUNT_BILLING |

최초 구현 커밋 `4eb6f3c622895edfa1f225241440fa344bdac5a1`. 이후 최신 main을 정상 병합하고 기존 UI 테스트를 현재 계약에 맞췄다. 제품 코드의 범위는 `ledger_design.py`, `trip_management_ui.py`, `ledger_design.css`의 표시 변경이다. 금융 금액·원본/ID·분류·환불·여행 배정·Google·스키마 변경은 없다.

최종 코드·테스트 SHA `1912c6a91f5fbcf9ddefe9b1e39321ac552791f9`. `python tools/run_quality_checks.py --base origin/main --run`의 고정 base `b01d36a39dbc1b51b272d3e94b049ed35a498453`: **PASSED, 420 passed·105 subtests passed·skip0·필수 브라우저31개 전건실행·누락0·컴파일 통과**. 표적/인접 장부·예약·메뉴와 OTA exact/부분환불/Google TSV/권한/여행 보호를 검사했다. 후속 문서는 앱 코드가 같으므로 이 검사를 반복하지 않는다.

## 검증 근거와 한계

- Ego TaskSpace67: 1440/760/390/320px, 다크모드, 긴 이름720px. 작성일·작성일 입력·본문 검색 없음, 사이드바 검색 유지, 담당자가 날짜 위, 가로 넘침0. 메뉴 키보드 열기/Escape/포커스 복귀 확인. 다크 담당자 텍스트의 실제 배경 대비 `5.7053:1`.
- 최초 전후 스크린샷이 동일한 후보 화면인 문제를 발견했다. 이를 전후 변화의 근거로 쓰지 않고, 별도 합성 baseline `ed4c14d0`와 후보 `4eb6f3c6`의 동일1440/390px 화면을 다시 확보했다. `verified-comparison.json`: 작성일 true→false, 본문 검색1→0, 사이드바 검색1→1, 넘침0 유지.
- 독립 `interface-review`와 `better-*` 후속 검토: Approve, 새 HIGH/MEDIUM 없음. 테스트 수정은 실제 접기/펼치기, 저장·revision·draft 보호·행 이동·기존 URL·예약 링크·모바일 수기 입력 동선을 유지한다. 영수증 fixture는 origin storage를 사용할 수 있는 주소로 열며 현재 통합 PDF/이미지 파일 입력을 검사한다.
- 초기 호스팅 CI42368367339: 26 failed, 402 passed, 95 subtests. 제거된 검색행을 구분자로 사용하던 검사를 수정하고, 기존 6열/순서/펼친 상세 입력/옛 수기 입력 위치 등 오래된 기대를 실제 제품 계약에 맞게 교정했다. 기존 baseline `ed4c14d0`에서도 해당 장부 검사23실패를 재현했다. 실패를 skip/제외해 통과시키지 않는다. 교정 중 중단한 QA는 통과 근거가 아니다.
- 물리기기·수동 스크린리더·200% 확대·번역/RTL은 미검증. 합성 화면을 인증 운영 수락으로 표현하지 않는다.
- 비공개 증거: `C:/AX/cost/.local-archive/trip-header-20261107/`의 `verified-*.png`, `verified-comparison.json`, `resume-browser.json`, `browser-results.json`, `independent-review.md`, `baseline-legacy.xml`, `ci-failed.log`, `ci-billing-block.json`, `checkpoint.md`. 고객 원문/화면은 Git에 포함하지 않는다.
- 최종 QA: 같은 폴더의 `final-impact-summary.json`, `final-impact.xml`, `final-impact.log`. 최종 테스트 전후 제품 동작 변경은 없으며, 최신 테스트 수정은 감독자 읽기 검토로 범위/의미를 확인했다. 독립 UI 리뷰 범위와 실제 최종 QA SHA를 구분한다.

## 실제 병합·배포 차단

[CI42369790657](https://github.com/6Soo/cost/actions/runs/42369790657)은 runner0·steps0으로 시작되지 않았다. GitHub annotation은 최근 계정 결제 실패 또는 사용 한도 증액 필요를 명시한다. 기존 CI 실패와 구분하며 녹색으로 간주하지 않는다. 과금 변경·CI 우회·강제 병합·운영 재배포는 하지 않았다.

계정 소유자의 GitHub Billing & plans 조치가 필요하다. 해소 후 최신 PR head의 실패한 CI를 재실행하고 SUCCESS 확인 → 정상 main 병합 → main CI 및 검증 SHA 확인 → 공식 단일 작성자 배포/보호13표/health·ready·보호API·영향 화면 스모크 순서로 재개한다. 실행 직전 현재 호스트 SHA와 동시 배포 여부를 새로 확인하며 과거 `PreviousSha`를 재사용하지 않는다.
