# 영수증 Paseo 통합 검증 기록

실행 기준은 [승인 설계](../../design/receipt-paseo-workflow-20261116.md)의 A1~A15다. 감독이 작업자 코드 통합 후 직접 실행한 근거만 통과로 기록한다. 실제 고객 자료·운영 DB·운영 포트·Google 쓰기는 사용하지 않는다.

## 기준선

- 기준 SHA: `7b0a37ef`(구현 전 명세).
- `python -m pytest tests/card_pipeline/test_receipt_candidates.py webapp/tests/test_receipt_drafts.py webapp/tests/test_receipt_integrity.py webapp/tests/test_receipt_partial.py -q --junitxml=.local-archive/receipt-paseo-implementation-20261116/baseline-receipt.xml`
- 실제 결과: **41 passed, skip 0**, 5.44초. 새 기능이나 실제 Paseo 호출을 검증한 결과는 아니다.

## 감독 검증표

| 기준 | 감독이 확인할 경계 | 현재 근거 |
| --- | --- | --- |
| A1, A13 | 실제 데몬 목록·인증/구독/사진/도구 제한, 연결 실패와 비승인 모델 차단 | 구현 중. available만으로 통과하지 않음 |
| A2 | 고정 지시·사진 native 첨부·빠른 ID 반환·결과 회수 | 구현 중. 합성 실제 승인 구독 호출 필요 |
| A3 | provider 탐색·복귀·재로딩으로 실행하지 않음 | UI 통합 후 브라우저 요청 기록 검사 예정 |
| A4, A5 | 브라우저 호출 없이 완료 저장, 서버 재시작·장시간 보존, 실행 ID 저장 전 유실 대조 | worker/HTTP 통합 후 합성 검사 예정 |
| A6 | 성공·실패·0건 사진을 같은 묶음에서 개별 보존 | 통합 후 합성 검사 예정 |
| A7 | 입력/초점 보존·다른 탭 revision 충돌 | UI/HTTP 통합 후 검사 예정 |
| A8, A14 | 사진·영역·후보 대응, 초기 미선택, 선택 건수, 데스크톱1440·모바일390·확대·키보드 | ego-browser 합성 수락 예정 |
| A9 | 장부 커밋 후 응답 유실·workflow 갱신 전 장애·새 request ID 재전송에도 중복 없음 | 장부/작업 저장소 통합 후 장애 주입 검사 예정 |
| A10 | 기존 법인카드 증빙만 연결, 원본/수동 교정/환불/닫힌 기간 보호, JPY10·KRW 정확 | 표적 회귀와 신규 합성 검사 예정 |
| A11 | 선택 일부 무효·stale revision·트랜잭션 도중 오류 때 전체 rollback | 장부 통합 후 장애 주입 검사 예정 |
| A12 | 소유자·CSRF·HTTP method·임의 원본 거부, 실행 전 서버 재검증 | HTTP 통합 후 거부 검사 예정 |
| A15 | 기존 JSON·draft 읽기 실패 시 초기화 금지, 사용자 자료·원본 불변 | 기준선41 통과. 통합 후 같은 표적 회귀 필요 |

## 아직 완료가 아닌 항목

작업자 개별 통과 보고는 감독 통과를 대신하지 않는다. 통합 전이므로 신규 기능·브라우저·실제 native 사진 처리·영향 게이트·최종 SHA 독립 검수를 통과했다고 주장하지 않는다. 운영 실행 계정의 연결 확인과 배포는 별도 운영 작업이다.
