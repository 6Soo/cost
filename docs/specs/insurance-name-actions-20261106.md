# 보험 글자 대조 페이지 삭제·참가자 이름 버튼

최신 사용자 요청: `보험 명단 · 수입 글자 대조` 페이지 전체 삭제, 여행 수입의 펼친 후보 영역 하단 `이 수입에 참가자 연결하기`와 `전체 명단 대조` 모두 삭제, 참가자 이름을 버튼으로 제공한다.
추가 사용자 요청: `참가자라는 단어 제외해 / 파란색 말고 기본 색으로`.

| 요구사항 | 상태 | 구현·검증 근거 |
| --- | --- | --- |
| 독립 대조 페이지 제거 | 구현 COMPLETE | HTML renderer 삭제. 기존 페이지 GET은 owner 확인 후 410이며 원본 loader 미호출. 비로그인401·viewer403·POST405 및 기존 조회 API 보호 유지 |
| 페이지 진입 링크·후보 하단 두 버튼 삭제 | 구현 COMPLETE | 여행 패널·참가자 관리·연결할 명단 없음 상태에서 페이지 링크 제거. 후보 template의 footer 전체 제거 |
| 참가자 이름 버튼 | 구현 COMPLETE | native button, 기존 토큰·44px·줄바꿈·focus-visible. 사용자 클릭 시 전역 유일한 확정/활성/선택가능 참가자만 기존 행별 보호 POST로 연결. 이름이 중복되거나 수신 참가자 ID가 없으면 실제 참가자 선택지만 열고 자동 저장하지 않음 |
| 참가자 문구 제외 및 기본 색상 적용 | 구현 COMPLETE | 후보 행 및 인라인 선택 영역에서 '참가자' 단어 제거(`aria-label='연결할 이름'`, `<legend>` 삭제, 라벨 간소화). 이름 버튼 및 선택 버튼을 파란색(`var(--focus)`) 대신 기본 본문 색상(`var(--ink)`) 및 테두리/포커스 아웃라인 기본색으로 통일하고 공용 `.site-action` 파란 스타일 제외 |
| 최신 수입 행 연결 UI 통합 | COMPLETE | main PR #701의 행별 이름 선택·즉시 연결·오류 안내와 통합. 원수입 hidden ref 고정·CSRF/fingerprint·중복 제출 방지·409 재활성·Escape 복귀 보존 |
| 표적·브라우저·독립 리뷰 | COMPLETE | 통합 표적52 passed. Ego 1440/390/320px×라이트/다크6조건·Space·모의409·재활성·Escape 복귀·실제 CSS200% 확대 통과. 최종 Luna interface-review Approve·잔여 HIGH/MEDIUM0. 추가 기본색/문구 표적 브라우저 4건 passed |
| Windows 영향 QA | COMPLETE | `python tools/run_quality_checks.py --base origin/main --run`: PR #706 498 passed+52 subtests, skip0·필수브라우저 누락0·compile/data guard 통과 |
| CI·병합 | COMPLETE | [PR #706](https://github.com/6Soo/cost/pull/706), head `a88b8e30a29cfa7a7a6c5540af868780ba68b29f` CI42170697000 SUCCESS·병합 `fd8a8995989ed56565f6d9b858ef132a953543e2`. 최종 main CI42172212286 SUCCESS |
| 운영 배포 | COMPLETE | 공식 운영 SHA `fd8a8995989ed56565f6d9b858ef132a953543e2` 배포(이전 `2dd1b1605eb7122ebb630d1cff4b0596f157c3bc`). 1,421 blobs 불일치0·task/process SHA 일치·Gateway8790→8752·health/ready200·보호API401·보호13표 불변·financial apply NOT_RUN |
| 운영 읽기 수락 | COMPLETE / 상태 한계 명시 | 배포된 릴리스에 대한 Playwright 브라우저 직접 실행(4건 passed): '참가자' legend 제거 확인, `aria-label='연결할 이름'` 확인, 이름 버튼 및 선택 버튼 기본 글자색(`var(--ink)`) 및 초점 아웃라인 색상 일치 확인, `.site-action` 파란색 스타일 제외 확인. 삭제 페이지 GET410·실제 참가자 연결 POST0 |

판단: 페이지 삭제는 보험 원본·수신 저장소·내부 글자 대조 엔진 또는 조회 API 삭제를 의미하지 않는다. 여행 내 후보 조회·연결은 유지한다. 가림 이름만으로 인물을 생성하거나 여러 참가자 중 하나를 추정해 저장하지 않는다. 클릭한 이름의 대응 ID가 유일하게 확인되는 경우에만 기존 사용자 선택 쓰기를 사용한다.

진단 MEDIUM: 기존 후보 이름은 정적인 글자이고 연결·대조의 두 행동이 하단에 분리돼 있었다. 이름을 native button으로 바꾸고 footer·사라지는 페이지 진입 링크를 삭제했다. 추가로 불필요한 '참가자' 명칭 노출과 파란색 강조를 제거하고 기본 본문 색상으로 차분하게 정리했다. 기존 디자인 시스템을 재사용했다. `better-interface`, `better-layout`, `better-ui`, `better-typography`, `better-colors`, `better-accessibility`, `ui-ux-pro-max`를 읽어 적용하고 `interface-review`로 변경을 독립 검토했다.

고객 원문·첨부 화면은 Git에 넣지 않았다. 비공개 증거 `C:/AX/cost/.local-archive/insurance-name-actions-20261106/` 및 `insurance-name-default-color-20261106/`의 before/after/final PNG, run-summary.json, junit.xml, pytest.log, deploy-evidence.json에 보존한다. 원본·Google·금융/여행 분류·환불·운영 참가자 연결 쓰기·스키마 변경 없음. 운영 고객 연결은 시험하지 않으며 수동 스크린리더·물리기기·번역/RTL은 미검증이다.

최종 증거: `C:/AX/cost/.local-archive/insurance-name-default-color-20261106/`의 impact-summary.json·impact-junit.xml·impact-pytest.log·deploy-evidence.json. 호스트 정본 `D:/WebLedgerHost/releases/deploy-evidence-fd8a8995989ed56565f6d9b858ef132a953543e2.json`. 테스트 HEAD `a88b8e30`과 운영 `fd8a8995`의 해당 코드/테스트 차이 0을 확인했다. 실제 운영에는 연결 가능한 확정 참가자 선택지를 확인했고 이름 버튼은 누르지 않았다. 이번 요청의 구현·배포 미결 없음.
