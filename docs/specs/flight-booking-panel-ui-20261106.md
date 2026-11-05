# 여행 항공권 예약 패널 UI 개선 (2026-11-06)

상태: IMPLEMENTED / 표적·브라우저 검증 완료 / 병합·운영 반영 대기.

## 요청과 종료 조건

- 목적: 사용자 첨부 화면의 과도한 세로 공간과 예약번호 중심 정보 위계, 목록과 선택 상세 간 거리 개선.
- 동작: 경로 → 출발일·인원 → 예약번호·배정 근거 순으로 전체 행을 선택할 수 있다. 선택 상태는 글자와 aria-pressed로 표시한다. 넓은 패널에서는 목록/상세가 나란히, 좁은 패널에서는 순서대로 배치된다.
- 직접 영향: `webapp/trip_flight_ui.py`, 직접 소비자 `webapp/ledger_design.py`의 여행별 예약 패널. 공통 CSS·API·DB·금액·원본·수동 배정·환불·Google 쓰기 변경 없음.
- 검증: 실제 공통 ledger CSS를 포함한 회귀 검사, 기존 조회/취소/자료갱신 검사, Ego 실제 렌더링, 독립 UI 리뷰, 영향 QA·CI 후 공식 단일 작성자 배포와 smoke.
- 종료: 아래 수락 항목 검증 및 병합/운영 SHA 기록. 기존 다른 에이전트 작업과 분리하기 위해 Paseo 관리 worktree 사용.

## 진단과 수락

| 요구사항 | 기존 문제 | 변경 및 실제 근거 | 상태 |
| --- | --- | --- | --- |
| 정보 구분 | 긴 예약번호가 경로보다 강조, 상세는 평문 나열 | 경로 우선 선택 행, 가는편/오는편과 메타 분리; 합성 데스크톱 전후 이미지 | COMPLETE |
| 선택·동선 | 선택된 예약을 목록에서 식별 불가, 상세가 목록 아래 | 전체 행 버튼·선택됨·aria-pressed, 760px 이상 패널의 병렬 배치 | COMPLETE |
| 반응형 | 넓은 화면에도 단일 열만 사용 | container query, 1363/680/390/320px 실제 CSS 포함 경계 테스트, Ego 390/320·200% CSS 확대 넘침 0 | COMPLETE |
| 접근성 | 제목만 클릭 가능 | 네이티브 버튼, Enter 선택·상세 region 포커스, 포커스 링, 고정44px 공통 버튼 규칙으로 인한 겹침 회귀 검사 | COMPLETE |
| 오류·빈 상태 | 성공 안내와 오류의 구분 필요 | 성공 알림만 시각적으로 숨김; 오류·빈 상태는 표시. UNAVAILABLE → 재시도 → 빈 상태 브라우저 회귀 검사 | COMPLETE |
| 보호·조회 동작 | 기존 업무 계약 보존 | lazy 조회·현재/취소 이력·SOURCE_CHANGED 갱신·textContent escaping·여행 권한 표적 검사 | COMPLETE |

## 검증 기록

- 구현 전 표적 38 passed, 추가 반응형 검사 포함 42 passed. 최종 브라우저 파일 8 passed (추가 UNAVAILABLE 회귀 포함).
- Ego TaskSpace41: 동일 1363×1016·390×844 전후 이미지, 320px, 다크·reduced motion, 200% CSS 확대. 자료는 모두 합성. `.local-archive/flight-ui-20261106/`에 비공개 증거 보존.
- 실제 계산한 일반/보조 텍스트 대비: light 17.85/7.58/7.24, dark 13.98/5.71/6.96. 모두 4.5 이상.
- 적용 스킬: better-interface/layout/ui/typography/colors/accessibility/writing, ui-ux-pro-max의 반응형 검색, ego-browser. 실제 interface-review 지침을 읽은 독립 Luna medium 검토에서 UNAVAILABLE 안내 숨김 MEDIUM을 발견·수정·재검토하여 잔여 HIGH/MEDIUM 0.
- 물리 모바일 기기, 수동 스크린리더, RTL/번역은 미검증. 화면 읽기/리뷰를 실제 동작 테스트로 대체 보고하지 않음.
- 독립 검토 무료 우선 후보 3개는 현재 모델 목록에 없어 승인된 다음 후보 Luna medium 사용. 새 과금 자원 생성 없음.

## 병합·운영

대기. 실제 QA·CI·SHA·공식 배포·보호13표·health/ready·보호 API와 영향 화면 smoke 후 갱신한다.
