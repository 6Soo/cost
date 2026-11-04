# 카드 업로드 후속 처리 오류 — 2026-11-05

- 요청: 12개 파일 접수 후 로그인 만료/후속 처리 오류가 표시된 화면의 문제 해결.
- 변경: 장부 행의 첫 감사 기록 여부를 projection revision 대신 실제 stream으로 판단한다. 기존 금액·날짜·원본·ID·수동 교정·감사 체인 검증은 유지한다. 401과 403을 구분하고 접수된 파일의 재업로드가 불필요함을 알린다.
- 원인 근거: 운영 DB를 읽기 전용으로 열고 메모리/로컬 격리 사본에서 재현했다. classify → sync_ledger_rows → save → append 경계에서 최초 stream의 correct 기록이 ChainViolation으로 거부됐다. 운영 DB 쓰기 없이 수정 사본의 classify/auto_record 통과를 확인했다.
- 회귀 검사: 수정 전 새 검사 2건 실패(분리 감사 DB는 ledger_pending, 통합 DB는 ChainViolation), 수정 후 통과. 연속 교정·멱등 재시도·금융 원본 불변·manual override 불변·체인 검증을 함께 검사한다. 초기 표적 검사 36 passed, 44 subtests passed, skip 0.
- 로그인: 현재 인증 GET 상태/상세 조회는 200이다. 화면의 과거 401/403 발생 원인은 현재 재현되지 않았으므로 모두 서버 인증 결함이었다고 단정하지 않는다. 만료 시 재로그인·체크포인트 유지, 권한 부족 시 소유자 계정 안내를 유지한다.
- 완료 조건: 영향 QA와 호스팅 CI 통과, PR 정상 병합, 공식 고정 SHA 배포 및 보호 API/테이블 확인. 실제 금융 대량 재처리나 Google 쓰기는 코드 배포에 포함하지 않는다.
- 실행 근거: `C:/AX/cost-upload-fix/.local-archive/` 및 `C:/AX/cost/.local-archive/upload-fix-20261105/`. 고객 원문은 보고서/Git에 포함하지 않는다.
