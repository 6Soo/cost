# 자율 개발 체크포인트

- 작업 위치는 `C:/AX/cost-integration`, 브랜치는 `integration/cost-final`입니다. 마지막 코드 커밋은 `c90db122668ac105ab78d6fb3dc7e20a7888bb6d`입니다. 문서 커밋을 포함한 정확한 HEAD는 `git rev-parse HEAD`로 확인합니다. `C:/AX/cost`의 사용자 변경은 보존했습니다.
- 영수증 재스캔과 수정 후 재확인, 카드와 영수증의 이중 복사 차단, 여행별 복사 경고, 자연어 일괄 승인의 동시 요청과 롤백, 회사 경비 제외와 되돌리기, Google 매핑과 권한 검증, 오래된 스냅샷의 확정 금액 차단을 커밋했습니다.
- 주요 검증은 관련 회계 경로 149 passed와 39 subtests passed, 영수증 경로 35 passed, 복사 브라우저 각 2 passed, 일괄 승인 HTTP와 재시도 10 passed입니다. 서로 겹치는 실행이므로 합산하지 않습니다. 기존 전체 회귀 결과를 다시 실행한 것으로 표시하지 않습니다.
- 서명 세션 테스트는 Luna 결과를 주 에이전트가 보완했습니다. 실제 임시 HTTP 서버의 로그인 시작·콜백·state 재사용·nonce 오류·쿠키 만료·변조·철회·비활성화와 신규 쓰기 경로 11개의 viewer·익명 거부를 검증했습니다. 최종 명령 `python -m pytest webapp/tests/test_signed_session_http.py -q`는 6 passed, 22 subtests passed입니다. 앞선 테스트 서버의 DB 경로 누락을 수정했습니다. 그 과정에서 열린 작업 폴더의 기본 로컬 DB와 미추적 `webledger.work.operator.sqlite.checkpoint.json`은 삭제하거나 게시하지 않습니다. 운영 DB 경로 환경 변수는 설정되어 있지 않았습니다.
- Google 정본 선택 UI와 viewer 상세 이동, 잘못된 영수증 입력 거부, 장기 동기화 장애와 재시도 상태의 잠금, 백업 파일 보존, 데모 캐시의 공개 필드 재검증을 추가했습니다. Google 단위·HTTP 인접 검사는 48 passed, 정본 선택 브라우저는 2 passed입니다. 최신 영수증 검사는 36 passed, 12 subtests passed이며, 동기화 지연 계산은 6 passed, CLI 잠금은 3 passed, 세대 파일 장애·보관은 8 passed, 데모는 16 passed입니다.
- OTA 카드 선택 뒤 늦은 미리보기 응답이 새 선택을 덮는 결함을 재현해 수정했습니다. 미리보기 응답 순서와 인접 브라우저 검사는 5 passed, 실제 코어 어댑터의 확인·승인·원본 보존 검사는 1 passed입니다. 과거의 모든 간헐 실패 원인을 해결했다고 주장하지 않습니다.
- JSON 쓰기 라우트의 최상위 자료형 오류는 400으로 거부합니다. 해당 표적 검사는 4 passed, 12 subtests passed입니다. 손상된 권한·매핑·정본 설정은 파일을 보존하고 503으로 거부합니다. 복구 후 viewer 조회도 다시 허용되는 것을 HTTP로 확인했습니다.
- 영수증은 카드 연결을 유지하면서 여행을 바꿀 수 있습니다. 금액과 결제수단의 실제 변경은 계속 차단합니다. 사진 등록의 중복 클릭·오류·재시도와 기존 두 화면 크기의 흐름은 3 passed입니다. 최근 사진 선택과 후보 원본 사진·영역 보존 관련 검사는 4 passed입니다. 중복 의심 후보도 입력값과 영역을 보류 이력에 보존하며 관련 검사 3개가 통과했습니다.
- 실제 `google-auth`의 RSA 검증을 외부 요청 없이 콜백에 연결했습니다. 정상 서명은 로그인되고 다른 키의 서명은 쿠키 발급·계정 변경 없이 거부됩니다. RSA와 nonce 표적 검사는 2 passed, 2 subtests passed입니다. 서명 쿠키의 권한 부여·목록·상세·철회 후 동시 조회 검사는 1 passed입니다. 새 설치용 `PyJWT[crypto]` 선언은 두 requirements 파일의 파싱과 목록 일치로 확인했으며 설치는 수행하지 않았습니다.
- 진행 중인 코드 수정은 없습니다. 다음 명령은 `git status --short`입니다. PR #85와 원격 HEAD를 읽기 전용으로 확인한 뒤, 새 결함 근거나 아래 승인 중 하나가 도착한 지점에서 개발을 재개합니다. 통과한 검증을 단순 최종 확인 목적으로 반복하지 않습니다.
- 남은 적용은 실제 계정·여행 매핑 검증, 운영 DB 마이그레이션과 복구 사본 검증, 이미 기록·확정된 거래의 신규 제외 정책, 별도 영수증으로 인정할 중복 의심 후보의 승인 정책입니다. 현재 PATH에서는 `tesseract`와 `ocrmypdf`를 찾지 못했습니다. 승인된 로컬 OCR 엔진이 준비되면 수동 입력 경로에 연결합니다. 외부 OCR 전송이나 설치는 수행하지 않았습니다.
- 운영 DB 마이그레이션, 운영 로그인과 실제 권한 검증, 배포와 재시작, 실제 Google 장부 쓰기, main 병합은 수행하지 않았습니다. 운영 적용은 별도 승인과 복구 사본 검증이 필요합니다.

최근 표적 명령은 다음과 같습니다. 시점별로 영향받는 범위만 실행했으며 합산하지 않습니다.

```powershell
python -m pytest webapp/tests/test_signed_session_http.py -q -k 'rsa_signature or wrong_nonce'
python -m pytest webapp/tests/test_signed_session_http.py -q -k signed_viewer_grant
python -m pytest webapp/tests/test_google_mapping_integrity.py -q -k corrupt_settings_over_http
python -m pytest webapp/tests/test_ota_preview_race_browser.py webapp/tests/test_ota_matching_defaults_browser.py -q
python -m pytest webapp/tests/test_ota_payment_review_browser.py -q -k real_core_adapter_store
python -m pytest tests/card_pipeline/test_google_authority.py -q -k 'generation or crash or failed_read_keeps_private'
python -m pytest tests/card_pipeline/test_google_demo.py webapp/tests/test_google_demo_page.py -q
python -m pytest webapp/tests/test_receipt_integrity.py webapp/tests/test_receipt_review.py -q -k 'possible_duplicate or second_photo or rescanned or same_photo'
```
