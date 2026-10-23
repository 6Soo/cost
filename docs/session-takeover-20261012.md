# COST 세션 인수 기록

> **2026-10-12 과거 세션 검증/배포 이력**. 당시 `integration/cost-final` 언급과 세션 인수 TODO는 현재 V3 구현 지시가 아니다. 후속 개발은 [단일 진입점](COST_V3_START_HERE.md) 및 [최신 인계](session_handoff.md)로 이동한다.


인수 대상은 `f49a35a1-aabd-4917-bc3c-1b6906211ffe`다. 사용량 한도로 중단됐고 실행 중인 턴은 없었다. 전체 대화의 사용자 지시, 최근 활동, 미커밋 테스트와 현재 운영 release를 확인했다.

| 요구 | 상태 | 실제 결과 |
| --- | --- | --- |
| 기존 세션 인수 | COMPLETE | 같은 integration 브랜치의 미완료 테스트를 이어 구현했다. |
| 카드 검토 개선 | COMPLETE | 자료 선택 접기, 상태별 건수, 검색·월·항목 필터, 날짜·금액 정렬, OTA·분류 아이콘과 조건 유지·거래 수정 경로를 구현했다. |
| 수입 중복 표시 정리 | COMPLETE | 빈 COST 수입·차액을 숨기고 Google 수입과 실제 COST 수입 행은 유지했다. |
| Google 원본 직접 링크 | COMPLETE | 선택된 메인·보관 파일과 실제 시트명을 사용한다. 실제 계정의 새 탭 이동은 미검증이다. |
| 운영 반영 | COMPLETE | 백업·복원 후 `adaa50ba27af532a7522ba9e47f6a0b89fdcbca6` 배포, 공개 health/ready 200, 비로그인 import 401, 서버·수집기 Running이다. |

구현 `873797fa0140cf59879a174e9d2829655b440f24`, 운영 `adaa50ba27af532a7522ba9e47f6a0b89fdcbca6`, 통합 `f778c5b`를 PR #85에 push했다. 기존 운영 위에 이번 표시 변경만 적용했고 main과 사용자 checkout의 dirty·미추적 파일은 유지했다.

기존 기록 API는 전체 묶음을 처리하므로 필터 조회 중에는 기록 버튼을 잠갔다. 합성 검사에서 거래 ID·원본 해시·금액·날짜·가맹점 보존과 장부 미기록을 확인했다. 운영 원본 전수 비교를 수행했다는 의미는 아니다.

검사는 카드 검토 초기 1 passed / 2 subtests, Google·장부·카드 인접 묶음 24 passed / 4 subtests와 기대값 오류 2건, 오류 수정 후 해당 2 passed / 2 subtests, 최종 변경 5 passed / 2 subtests다. 결과를 합산하지 않는다. 전체 회귀·전체 OTA 대사·운영 시험 기록·실제 고객 메시지 발송은 표시 변경에 필요하지 않아 생략했다. 실제 운영 로그인 화면과 실제 Google 링크 이동은 미검증이다.

백업·복원과 전환 근거는 `D:/WebLedgerHost/data/backups/v2-owner-ui-20261012T220642/restore-evidence.json`과 `deployment.json`이다. 후보·스모크·인수 사본은 `C:/AX/cost/.local-archive/card-review-takeover-20261012/`에 있다. 추가 비용·Google 쓰기·스키마 변경은 없다.

별도 예약 알림톡 수정은 reservation PR #18 `0a66d6e`, OPEN·운영 미반영 상태로 유지한다. 기존 검사 11개·타입 검사 근거를 반복하지 않았다. 이전 PDF 입력·자동 영수증 분리·실제 ADC·viewer 검증·Render 이전의 미완료 기록을 이번 카드 화면 요청의 완료로 바꾸지 않는다.

다음 상태 확인은 `git -C C:/AX/cost status --short`와 WebLedger-Board 예약 작업의 release 경로 조회로 시작한다. 후속 코드 작업은 PR #85의 `integration/cost-final` 최신 HEAD에서 수행한다. 관련 변경이 없으면 이번 통과 검사를 반복하지 않는다.
