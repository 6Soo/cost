# 항공권 검색: 여행별 그룹·탑승객 중심·행동 가능한 상세

상태: **구현·영향 QA·독립 리뷰·CI·운영 배포 완료**. PR #684 병합·운영 SHA `ae64bd19c29f6a5347212f53c25408f870e283ac`. 최신 사용자 요청은 상세 UX 교정, 탑승객 중심 제목, 배정 여행별 그룹이다. 이전 항공권 제안 전체를 새 작업으로 재실행하지 않는다.

## 목적과 동작

- 검색 결과를 기존 여행 배정에 따라 묶고 여행 제목·현재 표시 건수·여행 장부 링크를 표시한다. 예약의 주 제목은 탑승객, 날짜·행선지·취소/충돌은 보조 정보다. 같은 이름의 별도 예약과 원본 이름 표기는 임의 병합하지 않는다.
- 여행 장부의 `trip_flight_read` 읽기 모델을 재사용한다. 기존 수동 배정→검증된 카드 근거→출발일 추론 우선순위와 원본 충돌 보호를 유지한다. 조회가 배정을 저장하지 않는다. 미배정·귀속 충돌·배정 자료 읽기 실패를 구분한다.
- 페이지를 추가 조회하면 기존 여행 그룹에 합친다. 여행 이름·배정 근거가 바뀌면 revision이 달라져 오래된 다음 페이지를 거부한다. 기존 API 필드는 유지하고 표시용 여행 메타데이터만 추가한다.
- 충돌/취소 안내는 무엇이 불명확한지와 예약처 확인·예약번호 복사를 제공한다. 예약처는 고정된 공식 홈페이지 목록만 사용한다. 원본 상태를 해결한 것으로 꾸미지 않고 실예약/결제 완료와 구분한다. 복사 실패 시 직접 복사할 번호를 안내한다.
- 예약번호·예약일·예약처는 짧은 그리드에 표시한다. 카드 결제와 날짜 조회는 예약 근거 접기 밖에 둔다. 시간대가 없거나 충돌/취소/미검증이면 자동 날짜 조회를 막고 직접 날짜 선택은 유지한다. 닫힌 예약에서 불필요한 카드 조회를 하지 않는다. 날짜 조회에는 요청 제한시간·늦은 응답 보호와 재시도 안내가 있다.

## better-interface 진단

범위: `/flight-passengers` 검색→여행 그룹→탑승객 예약 펼침→여정/예약 사실→카드 조회·원행. Python HTML/DOM JS, 기존 shell 토큰·Pretendard·native details/form을 사용한다. AGENTS·UI 작업 명세·UI 정본과 기존 항공권/여행 읽기 모델을 확인했다.

| 심각도 | 소유 영역 | 위치(변경 전) | 재현·영향 | 수정 |
| --- | --- | --- | --- | --- |
| HIGH | writing | flight_passenger_page.py:302,352 | 자료 충돌/확인 불가만 말하고 원본 확인 방법이 없음 | 예약처 확인·번호 복사·구체적 확인 대상 |
| HIGH | layout/writing | flight_passenger_page.py:346–359 | 카드 조회가 예약 상세·날짜 접기에 중첩되고 날짜 직접 선택 안내와 입력이 분리됨 | 결제·직접 날짜 입력을 바로 노출, 상태 옆 재시도 |
| MEDIUM | layout | flight_passenger_page.py:383–394 | 같은 행선지 제목이 반복돼 사람·여행을 식별하기 어려움 | 배정 여행별 그룹과 탑승객 주 제목 |
| MEDIUM | layout/typography | flight_passenger_page.py:134–224 | 누적 CSS 덮어쓰기·과도한 공백·예약 사실이 여러 행으로 분산 | 대상 화면 CSS를 정리하고 3열/모바일2열 예약 요약 |

접근성은 native disclosure/form, 이름·44px 영역·focus·상태 알림·320px/텍스트 확대를 확인한다. typography는 rem/단위 없는 줄높이·이름 줄바꿈·숫자 정렬을 사용한다. colors는 기존 의미 토큰과 실제 렌더링 명암을 측정한다. UI polish는 기존 아이콘과 disclosure 표시를 재사용하며 새 모션을 추가하지 않는다. writing은 오류마다 실제 복구 행동을 대조한다.

## 검증과 경계

- 표적 74 passed: 수동 배정 우선·여행 제목 변경 시 오래된 페이지 차단·배정 자료 실패를 미배정으로 위장하지 않음·페이지 간 그룹 병합·탑승객 제목·원본 보존·날짜 직접 조회/자동 조회 보호·원행/권한 등. 변경 전 주 제목 회귀 red를 확인했다.
- ego-browser 동일 TaskSpace30에서 실제 shell/renderer를 합성 HTTP API로 연결했다. 같은 입력·390/1440px 수정 전후 캡처, state-machine 방식의 데이터 상태 전환, 긴 이름/320px/텍스트 확대 스트레스 및 키보드/테마/명암을 확인한다. 합성 자료만 사용하며 원본 고객 이미지·메일을 Git에 추가하지 않는다.
- 스킬: better-interface/layout/ui/typography/colors/accessibility/writing 원문과 필요한 참고 문서, ui-ux-pro-max의 error recovery 일치 결과를 사용한다. 최종 diff는 interface-review로 검토한다. `.local-archive/flight-passenger-ux-20261105/`에 합성 harness·캡처·JUnit·검사 결과·review·배포 근거를 보존한다.
- 금융·여행 배정·원본·Google·스키마 쓰기 없음. 배포에는 기존 단일 작성자·원본 보호·정확 SHA 게이트를 사용한다. 화면 개선은 예약 충돌의 실제 해결·실제 탑승·환급·Google 반영을 뜻하지 않는다.

## 최종 수락 및 정리

- 최종 코드 `c02244d2` Windows 영향 QA324passed+16subtests·skip0·필수browser누락0·compile PASS. PR CI42036009335와 main CI42036639901 SUCCESS. 200% 확대 Linux 실패와 독립 리뷰의 버튼 문구 잘림을 실제 container 폭에 맞춘 재배치 및 구체적 nowrap override로 교정한 뒤 재검증했다. 검사 제외·허용폭 확대 없음. 독립 최종 Approve.
- 운영 `ae64bd19` 고정 배포(이전bd75f63f),1413blobs mismatch0·runtimeSHA검증·단일listener8752·gateway8790·health/ready200·보호API401·보호13표 전후 불변. 인증된 항공권 페이지의 최종 검색/CSS 확인. 금융 apply NOT_RUN, Google/원본/여행 배정 쓰기 없음. [운영 기록](../../operations.md).
- 해당 임시 workspace의 미추적 QA3파일61,678bytes는 기본 폴더 `.local-archive/flight-passenger-ux-20261105/preserved-worktree/`에 SHA256 검증 보존했다. 이 문서 기록 병합 후 공식 archive와 병합 브랜치 정리 결과를 같은 로컬 checkpoint에 남긴다. 타 작업공간/사용자 변경/stash는 보존한다. 문서 기록을 위한 앱 재배포·재시작은 하지 않는다.
