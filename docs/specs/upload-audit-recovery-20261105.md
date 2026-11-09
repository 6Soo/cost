# 카드 업로드 후속 처리 오류 — 2026-11-05

- 요청: 12개 파일 접수 후 로그인 만료/후속 처리 오류가 표시된 화면의 문제 해결.
- 변경: 장부 행의 첫 감사 기록 여부를 projection revision 대신 실제 stream으로 판단한다. 기존 금액·날짜·원본·ID·수동 교정·감사 체인 검증은 유지한다. 401과 403을 구분하고 접수된 파일의 재업로드가 불필요함을 알린다.
- 원인 근거: 운영 DB를 읽기 전용으로 열고 메모리/로컬 격리 사본에서 재현했다. classify → sync_ledger_rows → save → append 경계에서 최초 stream의 correct 기록이 ChainViolation으로 거부됐다. 운영 DB 쓰기 없이 수정 사본의 classify/auto_record 통과를 확인했다.
- 회귀 검사: 수정 전 새 검사 2건 실패(분리 감사 DB는 ledger_pending, 통합 DB는 ChainViolation), 수정 후 통과. 연속 교정·멱등 재시도·금융 원본 불변·manual override 불변·체인 검증을 함께 검사한다. 초기 표적 검사 36 passed, 44 subtests passed, skip 0.
- 로그인: 현재 인증 GET 상태/상세 조회는 200이다. 화면의 과거 401/403 발생 원인은 현재 재현되지 않았으므로 모두 서버 인증 결함이었다고 단정하지 않는다. 만료 시 재로그인·체크포인트 유지, 권한 부족 시 소유자 계정 안내를 유지한다.
- 완료 조건: 영향 QA와 호스팅 CI 통과, PR 정상 병합, 공식 고정 SHA 배포 및 보호 API/테이블 확인. 실제 금융 대량 재처리나 Google 쓰기는 코드 배포에 포함하지 않는다.
- 실행 근거: `C:/AX/cost-upload-fix/.local-archive/` 및 `C:/AX/cost/.local-archive/upload-fix-20261105/`. 고객 원문은 보고서/Git에 포함하지 않는다.

## 최종 수락

| 대상 | 상태 | 실제 근거 |
| --- | --- | --- |
| 감사 최초 기록 오류 | COMPLETE | 회귀2건 red→green, 격리 운영 사본 classify/auto_record 성공; 운영 재처리는 미실행 |
| 인증 안내/접수 보존 | COMPLETE | 401/403 분리·기존 인증 화면 새 코드 확인, 저장 상세200·없는 작업404; 과거 인증 오류 원인은 미확정 |
| 영향 검증/정상 병합 | COMPLETE | Windows401 passed·33 subtests·skip0·필수 브라우저 누락0, CI41889472534 성공, PR633 병합 |
| 고정 SHA 배포/보호 확인 | COMPLETE | 운영2e911f3f, 1329 blobs 일치·task/processSHA·health/ready200·보호API401·보호13표 동일; 전환 후 누락 근거를 재시작 없이 복구 |
| 접수 파일 현황 | COMPLETE | 12개 모두 저장/배치 classified·파싱 오류0, 원본 충돌7행 needs_review 보존; 재업로드 불필요 |
| 인증 운영 읽기 수락 | COMPLETE | Ego2 main/새인증안내/상세327행/가로넘침0, TaskSpace 종료 |

- 실제 고객 업로드·운영 대량 재처리·Google 쓰기·실기기 검증은 미실행이며 위 완료에 포함하지 않는다. 기존 원본 충돌7행의 해소는 이 오류 수정의 완료 조건이 아니다.
- 이 요청 미결0·다음 기능 명령 없음. 후속은 문서 기록이며 코드 재검사/배포/재시작하지 않는다. [운영 상세](../history/operations-20261028-20261107.md#2026-11-05-카드-업로드-후속-처리-오류).
