# 여행 장부 항공 이용일 누락 수정 (2026-11-05)

상태: COMPLETE / PR #686 병합·고정 SHA 운영 배포 및 인증 PC/모바일 수락 완료.

- 목적: 예약·탑승자 근거가 있어도 장부 이용일 열이 비는 결함을 수정한다.
- 원인: `ledger_design._table_html`이 숙박비에만 이용일을 출력했다. 항공 탑승자 조회와 숙박 기간 보완이 분리돼 항공 여정 날짜는 표시되지 않았다. 모바일 카드에도 이용일 출력이 없었다.
- 변경 동작: 항공료·항공권은 저장 이용기간을 우선하고, 공란이면 저장 예약번호에 대응하는 fresh 항공/OTA 스냅샷의 출발 날짜를 중복 없이 표시한다. 왕복·다구간은 실제 출발일 목록이며 숙박 일수로 표현하지 않는다. 근거 부족은 `이용일 미확인`이다.
- 직접 영향: 여행 장부 PC 이용일 열, 모바일 지출 카드. 기존 숙박 날짜는 재사용하며 모바일에도 표시한다. 분류·금액·결제일·여행 귀속·원본·Google·예약/금융 관계 쓰기와 마이그레이션은 없다.
- 보호: 명시 수동 공란·입력값 우선, stale·충돌·취소·미완성 날짜와 출처 없는 근거는 사용하지 않는다. 설명에만 적힌 번호를 저장 예약 관계로 승격하지 않는다.
- 필요한 검증: 합성 연결/미연결·수동·stale·취소·달력 오류·편도·왕복·연도 경계와 원본 불변, PC/모바일 실제 렌더링 및 영향 QA, 독립 UI 리뷰.
- 종료 조건: 검증된 PR main 병합, 공식 단일 작성자 코드 배포, health/ready·보호 API·13표 불변 및 인증 장부 이용일 수락.

## 실제 근거

- 표적: `python -m pytest webapp/tests/test_ledger_flight_dates.py webapp/tests/test_ledger_stay_evidence.py webapp/tests/test_ledger_spend_detail.py webapp/tests/test_ledger_display_updates.py -q` — 99 passed.
- `ego-browser` TaskSpace32: 인증 운영 원인 재현 및 합성 변경 전후 1440/390/320px, 긴 다구간·미확인 상태·키보드 focus·가로 넘침0 확인. 운영 스크린샷·고객 근거는 비공개 `.local-archive/flight-service-dates-20261105/`에만 보존한다.
- 실제 적용 스킬: ego-browser, better-interface/accessibility/layout/writing/typography/colors/ui, ui-ux-pro-max. UI Pro Max의 표 처리 결과는 모바일 카드 기존 구조 유지에만 참고했다. `interface-review` 독립 Luna 검토: 조치 가능한 결함 없음, 합성17건 통과, 브라우저는 주 에이전트 담당. 추가 수동 검토에서 모바일 미확인 라벨 중복을 발견·수정하고 재검증했다.
- 미검증: 물리 기기·수동 스크린리더·번역/RTL. 독립 리뷰의 브라우저 미실행을 브라우저 수락으로 간주하지 않는다.

최종 QA/PR/배포 근거는 [현재 상태](../session_handoff.md)와 [운영 기록](../operations.md)에 기록한다.

## 최종 수락

- 운영 SHA `bd75f63f380d7bcd0e4424ade74fb1360cfe541e`, Windows 영향303 passed+64 subtests·skip0·필수브라우저19전건실행. PR/main CI 성공, 보호13표 불변·health/ready200·보호API401.
- 연결 항공료에 `06.30 · 07.04`를 PC/모바일로 확인했다. 설명에만 예약번호가 있고 저장 연결이 없는2행은 미확인을 유지했다. 배포 직후 예약 근거 워밍 중에는 미확인으로 표시되며 fresh 근거가 준비된 뒤 날짜가 표시된다.
- 원본·예약/환불/금융 관계·금액·분류·여행·Google 변경0. 상세 배포 및 검사 증거는 현재 상태와 운영 기록의 2026-11-05 항공 이용일 항목을 따른다.

- **2026-11-10 변경([#775](https://github.com/6Soo/cost/pull/775)):** 화면 표시 근거는 fresh 세대만이 아니라 마지막 완결 세대(`current.data` 존재)를 재계산·재시도 중에도 사용한다. 재계산이 5–9분 걸리고 자주 재시도돼 검증된 날짜가 화면에서 사라졌기 때문이다. 쓰기·연결·금융 경로는 계속 fresh를 요구한다. 재기동 직후 첫 완결 세대 전에는 여전히 미확인으로 보인다.
