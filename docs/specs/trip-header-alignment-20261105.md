# 여행 상단 버튼 정렬 교정 (2026-11-05)

상태: IMPLEMENTED — 운영 미반영, 검증·리뷰 진행 중.

목적: 첨부 화면에서 여행 관리만 아래로 내려간 문제를 수정한다. 변경 동작은 여행 헤더 펼침 버튼의 바깥 여백 제거이며 직접 영향은 `/board`의 여행 관리 열기/닫기다. 금융·Google·원본·API·DB 업무 쓰기는 변경하지 않는다. 종료 조건은 정렬/키보드/반응형 확인, 독립 리뷰, CI 정상 병합과 검증 SHA 운영 반영이다.

원인: 공통 `summary.site-action`의 `margin:8px 0`가 여행 상단에도 적용됐다. 브라우저 1440px에서 마감/예약/출력 top68px, 여행 관리 top76px로 8px 차이를 재현했다. 기존 헤더 검사는 문구·노출만 확인해 이 차이를 검출하지 않았다. 최초 도입/배포 당시 전체 검증 과정을 이번 조사로 단정하지 않는다.

수정: `trip_management_ui.py`의 `.trip-settings>summary`에 `margin:0`을 지정한다. 공통 펼침 버튼의 여백·테마·native details 동작은 유지한다.

검증: 새 geometry 회귀는 수정 전 320/390/760/1440px 모두 8px 차이로 실패했고 수정 후 1 passed + 4 subtests passed다. 높이 동등성, 가로 넘침, Enter로 열기/닫기, 정보 저장 버튼 접근을 확인했다. 초기 합성 fixture의 requests 테이블 누락은 테스트 안에서 기존 schema와 같은 빈 테이블을 생성해 해결했다. 고객 데이터는 사용하지 않는다.

로컬 증거: `.local-archive/trip-header-align-20261105/`의 before/after PNG, browser-results.json. `better-interface`, better-layout/ui/typography/colors/accessibility/writing 지침을 읽어 대상 영역에 적용했다. 별도 interface-review 진행 중. 실제 스크린리더·실기기 검증은 미실행이다.
