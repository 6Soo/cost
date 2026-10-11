# 자율 개발 체크포인트

- 작업 위치는 `C:/AX/cost-integration`, 브랜치는 `integration/cost-final`입니다. 마지막 코드 커밋은 `fd49e2f21a4bd8e634e42b63ee55a51e25c6e23f`입니다. 문서 커밋을 포함한 정확한 HEAD는 `git rev-parse HEAD`로 확인합니다. `C:/AX/cost`의 사용자 변경은 보존했습니다.
- 영수증 재스캔과 수정 후 재확인, 카드와 영수증의 이중 복사 차단, 여행별 복사 경고, 자연어 일괄 승인의 동시 요청과 롤백, 회사 경비 제외와 되돌리기, Google 매핑과 권한 검증, 오래된 스냅샷의 확정 금액 차단을 커밋했습니다.
- 주요 검증은 관련 회계 경로 149 passed와 39 subtests passed, 영수증 경로 35 passed, 복사 브라우저 각 2 passed, 일괄 승인 HTTP와 재시도 10 passed입니다. 서로 겹치는 실행이므로 합산하지 않습니다. 기존 전체 회귀 결과를 다시 실행한 것으로 표시하지 않습니다.
- 서명 세션 테스트는 Luna 결과를 주 에이전트가 보완했습니다. 실제 임시 HTTP 서버의 로그인 시작·콜백·state 재사용·nonce 오류·쿠키 만료·변조·철회·비활성화와 신규 쓰기 경로 11개의 viewer·익명 거부를 검증했습니다. 최종 명령 `python -m pytest webapp/tests/test_signed_session_http.py -q`는 6 passed, 22 subtests passed입니다. 앞선 테스트 서버의 DB 경로 누락을 수정했습니다. 그 과정에서 열린 작업 폴더의 기본 로컬 DB와 미추적 `webledger.work.operator.sqlite.checkpoint.json`은 삭제하거나 게시하지 않습니다. 운영 DB 경로 환경 변수는 설정되어 있지 않았습니다.
- Google 정본 선택 UI와 viewer 상세 이동, 잘못된 영수증 입력 거부, 장기 동기화 장애와 재시도 상태의 잠금, 백업 파일 보존, 데모 캐시의 공개 필드 재검증을 추가했습니다. Google 단위·HTTP 인접 검사는 48 passed, 정본 선택 브라우저는 2 passed입니다. 최신 영수증 검사는 36 passed, 12 subtests passed이며, 동기화 지연 계산은 6 passed, CLI 잠금은 3 passed, 세대 파일 장애·보관은 8 passed, 데모는 16 passed입니다.
- OTA 카드 선택 뒤 늦은 미리보기 응답이 새 선택을 덮는 결함을 재현해 수정했습니다. 미리보기 응답 순서와 인접 브라우저 검사는 5 passed, 실제 코어 어댑터의 확인·승인·원본 보존 검사는 1 passed입니다. 과거의 모든 간헐 실패 원인을 해결했다고 주장하지 않습니다.
- 다음 명령은 `git status --short`입니다. 그다음 신규 JSON 쓰기 라우트의 잘못된 최상위 자료형 처리와 오류 응답을 조사합니다. 이미 통과한 위 검증은 영향이 생기지 않는 한 반복하지 않습니다.
- 독립 잔여 작업은 Google·자연어 JSON 입력 오류 처리 조사, 영수증 수동 입력의 오류 메시지 보완, 과거 OTA 간헐 실패의 남은 경로 확인입니다. 현재 PATH에서는 `tesseract`와 `ocrmypdf`를 찾지 못했습니다. 외부 OCR 전송이나 설치는 수행하지 않았습니다.
- 운영 DB 마이그레이션, 운영 로그인과 실제 권한 검증, 배포와 재시작, 실제 Google 장부 쓰기, main 병합은 수행하지 않았습니다. 운영 적용은 별도 승인과 복구 사본 검증이 필요합니다.
