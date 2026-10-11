# 자율 개발 체크포인트

## 현재 운영 반영: 2026-10-12

- 운영 배포 SHA는 `de684eb67afc8c9b0fdfef39431113eb03bdcab7`다. PR #85의 `integration/cost-final`에서 개발했고 main은 병합하지 않았다. 이후 문서 전용 커밋은 운영 코드와 구분한다.
- 기존 주소 `https://ledger.foresttour.kr`, Windows PC, Cloudflare Tunnel, `127.0.0.1:8751`, 데이터 루트 `D:/WebLedgerHost/data`를 유지한다. `WebLedger-Board`는 `D:/WebLedgerHost/releases/<배포 SHA>/tools/start_web_ledger_host.ps1`에 고정됐다. 운영 원본 `C:/AX/cost`는 갱신하거나 초기화하지 않았다. 예전 `restart_real_review_host.ps1`로 원본 checkout에 되돌리지 말고 현재 예약 작업의 고정 경로를 사용한다.
- 새 기능: 설치돼 있던 Windows 일본어·한국어 OCR을 영수증 사진과 연결했다. 글자와 제한된 날짜·일본어 합계 제안만 제공하고 사용자 확정 없이 비용을 만들지 않는다. 기존 localhost:8088 AI는 결정론적 해석이 실패할 때 사용자 문장만 받아 규칙 초안을 제안한다. 향후 반복 규칙은 기존 규칙 저장 화면에서 별도 확인한다. Google 여행 연결과 viewer 허용·철회 화면을 추가했다. 기존 여행 권한과 정본 검사를 우회하지 않는다.
- 모바일 장부 작업 메뉴를 접이식 여행 탐색 영역으로 옮겨 첫 거래가 화면 아래로 밀리던 문제를 수정했다. 실제 사이트 375px 영수증·Google, 390px 카드·장부, 데스크톱 약 1440px 장부에서 가로 넘침 없는 접근을 확인했다. 실기기 검증은 아니다. 운영 거래를 새로 확정하거나 영수증을 실제 DB에 시험 등록하지 않았다.
- 실제 owner Google OIDC 세션, 공개 주소 health/ready 200, 비로그인 카드 API 401 및 Google API 403을 확인했다. 실제 viewer 계정의 로그인 완주는 아직 검증하지 않았다. 합성 세션 검사와 구분한다.
- 실제 Google 메인·보관 읽기는 기존 공개 링크 XLSX 방식으로 성공했다. ADC 환경변수·기본 credential·refresh token은 없었다. ADC 성공이라고 보고하지 않는다. `WebLedger-GoogleAuthority`는 매시 정각 KST, 중복 실행 금지, 읽기 전용 public 모드로 등록했고 수동 시작 1회 결과 0을 확인했다. 이 작업은 동기화 코드가 같은 `2a330ca` release에 고정돼 있다. 기존 `WebLedger-SourceRefresh`의 300초 수집 주기를 유지한다. Google 원본·공유권한은 변경하지 않았다.
- 운영 백업·복원 증거: `D:/WebLedgerHost/data/backups/v2-deploy-20261012T004430/restore-evidence.json`. DB 4개와 설정·영수증·Google 세대 파일 33개를 복원해 비교했다. 비밀 파일은 기존 위치에 보존했고 이 묶음에는 복사하지 않았다. 격리 복원본 스키마 리허설 후 운영에는 `transaction_company_exclusions`만 통제된 트랜잭션으로 추가했다. 원래 77개 테이블 중 재시작 lease 행 추가 외 원본 행 지문은 동일했다. 첫 시도는 백업의 빈 WAL sidecar 때문에 마이그레이션 전에 차단됐고 기존 서비스로 복귀했다. 백업 대상만 DELETE 모드로 바꾸는 수정 후 성공했다.
- 전체 검사 1회: 시작 `a2075d66dbc031cdfe80a331d5e66e8fbd524ebd`, 종료 `fdd5308d5bb9542975498d69af42604b3c4504c2`, **23 failed / 3203 passed / 3 skipped / 2431 subtests**. 최종 SHA 전체 통과 기록이 아니다. 원인은 모바일 거래 위치와 생산 모드 거부 검사의 환경변수 누출이었다. 제품 보호 조건은 유지했다. 실패 영역의 순서 있는 후속 검사 112 passed / 53 subtests와 누락 import 수정 후 해당 검사 1 passed로 해결했다.
- 추가 표적 근거: 영수증 50 passed / 15 subtests, 규칙 33 passed / 1 skipped / 12 subtests, 실제 로컬 AI 관련 4 passed, 백업·리허설 16 passed. Google 설정·매핑·페이지·서명 HTTP 묶음은 62 passed / 35 subtests와 신규 검사의 CSS 문자열 기대 1건 실패였다. DOM 요소 존재로 기대를 바로잡고 설정 화면 최종 배치 후 신규 실제 브라우저 포함 2 passed다. 중복 범위는 합산하지 않는다. 과거 3107 passed 기준선은 과거 SHA의 증거로만 보존한다.
- 사용자 원본 dirty 5개(`tools/verify_lightweight_runtime.py`, `edit_card_flow.py`, 두 pending-card-evidence patch, SQLite checkpoint JSON)와 stash `fbb1226e4659e4a2b75216cd556b51687db7d73e`를 보존했다. 테스트가 바꾼 추적 화면 캡처 2개만 `.local-archive/deploy-regression-20261012`에 보관하고 원래 추적 버전으로 돌렸다.
- 후속 구현 `de684eb`: 원화 영수증 통화 선택 → 금액 수정 → 여행 배정 → 확정 → 새로고침 → 실제 7열 클립보드 복사를 합성 Chromium 390px에서 완주했다. KRW 원금은 환산하지 않고 `total_original`에 보존하며 `total_jpy`는 null이다. 늦게 들어온 국내 법인카드는 현금 영수증 복사를 차단하고, 증빙으로 연결하면 추가 비용을 만들지 않는다. 기존 JPY 자료는 읽기·TSV로 재작성하지 않는다. 기존 영수증·후보와 신규 원화 검사 58 passed / 15 subtests, 최종 원화·무결성·서명 HTTP 39 passed / 35 subtests다.
- 원화 반영 직전 새 백업 `D:/WebLedgerHost/data/backups/v2-owner-ui-20261012T010720/restore-evidence.json`에서 DB 4개와 파일 34개의 복원·원본 불변·설정 연결 비교가 통과했다. DB DDL은 추가하지 않았다. 실제 사이트 375px에서 통화 선택·원화 안내·OCR 버튼·ready 200을 확인했다. 운영에 합성 영수증을 기록하지 않았다. 원화 후보가 저장된 이후에는 KRW를 읽지 못하는 이전 release로 단순 코드 롤백하지 말고 호환 코드를 유지해야 한다. 복구를 이유로 새 사용자 기록을 덮지 않는다.
- 남은 실제 기능 범위: PDF 입력과 자동 복수 영역 분리는 미구현이다. 일본어·한국어 OCR은 글자를 읽지만 지급처·통화·결제수단·영역을 모두 자동으로 확정하지 않는다. 사진 OCR은 전체 사진을 읽으며 영역별 자동 OCR이라고 표시하지 않는다. 실제 ADC와 viewer 계정 검증, 실제 모바일 단말 검증은 외부 자원이 필요하다. 실제 회계 top3 공개는 비활성이고 별도 게시 승인이 필요하다.
- 다음 구현 시작점: `tools/windows_receipt_ocr.ps1`, `app/local_receipt_ocr.py`, `webapp/receipt_review.py`에서 Windows 기본 PDF 렌더링 지원을 격리 합성 자료로 확인하고 원본 보존·페이지별 사진 후보 연결을 구현한다. 자동 복수 영역 추출은 별도 작업이다. 운영을 이전 원본 경로로 재시작하지 않는다.

이하 항목은 이전 실행 기록이며 위 운영 배포 상태를 덮지 않는다.

## 현재 작업: 기본 업무 화면과 모바일 UI

- 시작 HEAD `457b03b2a40e7888440e8b7e1f3558a6dc53ca49`. 이번 구현은 홈·장부 업무 메뉴, 로컬 수입과 Google 정본 구분, 모바일 Google·영수증 화면, 인증 상태의 바이너리 업로드, 확정 일정의 불필요한 XLSX 서비스 의존성 제거다. 최신 SHA는 PR #85와 Git을 따른다.
- 실제 Chromium 375·390·1440px에서 여행 선택·영수증 진입·입력 버튼 배치·Google 수입/순수익 표시를 검사했다. 장부 모바일 및 홈 인접 검사 7 passed / 10 subtests, 수입 안내 후속 3 passed / 3 subtests, Google 표적 50 passed / 3 subtests, 일정 원본 인접 20 passed / 10 subtests, 영수증 및 무결성 74 passed / 15 subtests. 범위가 겹치므로 합산하지 않는다.
- 인증을 켜면 사진과 XLSX를 폼으로 먼저 해석해 422로 거부하던 실제 결함을 수정했다. 서명 쿠키의 사진·XLSX 후속 2 passed / 7 subtests에서 owner 성공, viewer·익명 차단, CSRF 및 원화 금액 보존을 확인했다.
- Google 동기화 자료가 없거나 손상된 경우 HTML에는 다시 확인 화면, API에는 기존 503 JSON을 유지한다. 신규 브라우저 복구 검사는 통과했다. 기존 HTML의 JSON 기대 검사 1건은 새 화면 계약과 API 오류 코드 보존을 함께 확인하도록 수정했고 후속 1 passed다.
- 합성 미리보기: `python -m tools.run_synthetic_preview --port 8795`, `http://127.0.0.1:8795/preview`. 임시 DB·합성 일정/Google 자료만 사용하고 외부 서비스·운영 환경변수를 사용하지 않는다. 종료하면 예시 입력도 삭제된다. 신규 실제 브라우저 검사 1 passed: 카드 확정·7열 복사 → 사진 업로드·수동 확정·중복 복사 경고 → Google 정본 선택·수입 900,000원/순수익 780,000원. 인증·일정 검증을 테스트 대역으로 바꾸지 않았다.
- 실제 미리보기에서 수동 등록 여행이 홈에 나타나지 않던 문제도 수정했다. 출발 예정 여행이 없으면 활성 여행을 `등록된 여행`으로 표시한다. 홈 여행 선택부터 위 업무까지 완주한 신규 검사와 기존 홈 인접 검사 2개가 3 passed다. 일정 상태나 거래를 변경하지 않는다.
- 운영 사이트 읽기 요청은 Cloudflare 403으로 거부됐다. 로그인 뒤 화면과 실행 SHA는 미확인이다. 문서상 운영 코드 경로 `C:/AX/cost`는 현재 `main`의 `8472729`이며 통합 worktree와 다르다. 운영 코드를 반영하지 않았다. 실제 Google/OIDC 인증·OCR 추론은 완료로 표시하지 않는다.
- 다음 작업: 미리보기에서 사용자 화면을 확인한 뒤 운영 반영 승인을 받으면 배포 대상 SHA·운영 연결 설정과 DB 요구사항을 점검한다. 그 전에는 운영 배포·DB·Google 원본 변경 없이 재현된 기본 업무 장애만 수정한다. 전체 회귀는 이번 UI 작업에서 실행하지 않았다.

## 2026-10-11 운영 인수 위험 해소

- 시작 HEAD `e3feb4ce7a648674648d2614a754e8da46d85f41`, 브랜치 `integration/cost-final`. 코드·검사 커밋 8개: `79231b5`, `bc2d437`, `335071e`, `2fed028`, `85a3a2c`, `d0034dc`, `1f0f8ab`, `fddf635`. 이후 기록 SHA는 Git과 PR #85를 따른다.
- 시작 실패: 접근제어·OIDC·예약 동기화 초기화 실패에서 워커·소켓·DB·전역 바인딩을 정리한다. 포트 충돌·워커 시작 실패는 기존 저장소 바인딩을 교체하지 않는다. 예상하지 못한 초기화·파일 I/O 오류는 원문 대신 고정 코드로 종료한다.
- DB 종료를 추가한 구현의 경합도 검사했다. 진행 중인 쓰기보다 먼저 DB를 닫는 문제를 확인해 요청 잠금으로 보완했다. 현재 쓰기는 완료한 뒤 연결을 닫고 대기 요청은 `503 SERVER_STOPPING`으로 거부한다. 합성 SQLite에서 실제 트랜잭션의 보존을 확인했다. 실제 운영 서버 재시작 검증은 아니다.
- Windows 실행기는 상속된 예약 동기화 활성 값을 지우고 이번 설정 파일의 명시적 opt-in만 사용한다. 운영 실행이나 스케줄러 활성화는 하지 않았다.
- 상대 데이터 루트를 먼저 절대 경로로 바꿔 검사를 우회하던 문제를 수정했다. 영수증·Google 스냅샷·비공개 행 파일도 두 운영 실행기에서 상대·임시·소스 체크아웃 내부 경로를 거부한다. 선택 기능을 새로 켜거나 기존 파일을 이동하지 않는다.
- Google: 실제 ADC 내보내기 어댑터에 합성 인증·전송을 주입했다. 손상된 XLSX의 마지막 정상 행 보존, 다른 원본 정상 갱신, 지연 후 복구, 읽기 전용 scope·리다이렉트 금지·응답 정리·원문 비노출을 확인했다. 실제 Google 인증 성공 증거는 아니다.
- 캐시: 실제 서명 쿠키 HTTP에서 owner·viewer·익명의 Google·영수증 HTML/API 허용·거부 응답에 `no-store`를 확인했다. 이미 사용자에게 전달된 자료를 원격 삭제한다는 뜻은 아니다.

검사 결과는 범위가 겹치므로 합산하지 않는다.

| 실제 검사 범위 | 결과 |
| --- | --- |
| `test_runtime_lifecycle.py`, `test_cp949_startup.py`, `test_schema_gate.py` | 초기 정리 수정에서 20 passed |
| `test_runtime_lifecycle.py`, `test_platform_start.py` | 서버 생성 실패 수정에서 33 passed |
| `test_runtime_lifecycle.py`, `test_batch_concurrency.py` | 종료 중 쓰기 보존 수정에서 12 passed |
| `test_signed_session_http.py` | 요청 경계 수정 후 8 passed / 28 subtests. 이후 신규 `-k never_cache`는 1 passed |
| `test_google_authority.py -k adc_corrupt_xlsx` | 1 passed |
| `test_launch_ota_review.py`, `test_schema_gate.py` | 설정 활성화 수정에서 21 passed |
| `test_ops_safety.py -k 'relative_data_root_is or direct_config_refuses or ConfiguredRoot'` | 7 passed |
| `test_ops_hosting_bind.py::DurableDataRootIsNotInsideTheCheckout`, `::TheEntryPointRefusesCleanly` | 10 passed / 4 subtests |
| `test_runtime_lifecycle.py -k 'optional or path_refusal'` | 12 passed |
| `test_runtime_lifecycle.py -k data_root_io_failure` | 실패 재현 후 수정, 1 passed |
| cp949 고정 문자열·운영 합성 세션 거부·운영 OIDC 합성 바인딩 거부 | 3 passed |

- 실패는 위 코드 수정으로 해소했다. 신규 캐시 검사의 초기 잘못된 상태 코드 기대값은 기존 계약(익명 Google 403, viewer 영수증 404)에 맞췄다. 보호 조건을 삭제하지 않았다. 전체 pytest와 기존 6개 브라우저 완주는 재실행하지 않았으며 이전 근거를 최신 HEAD 전체 통과로 바꾸지 않는다.
- `tools/rehearse_cost_schema.py --help`로 `--source-copy`, `--expected-sha256`, `--confirm-isolated-copy`, `--check-only`를 확인했다. 승인된 실제 사본 경로가 지정되지 않아 실제 사본 검증은 하지 않았다. 기존 합성 리허설·원자성·WAL·복구 검사를 재사용한다. 백업 래퍼는 프로세스 중단·재시작이 있어 실행하지 않았다.
- ADC 기본 파일·지정 파일과 현재 필수 OIDC 설정이 없는 것을 값 비노출로 확인했다. 승인된 시험 자격증명, 승인된 복구 사본, 기존 회계 정책 결정, 운영 반영 승인은 HOLD다. CODE READY는 위 수정·비운영 검증 범위이며 INTEGRATION VERIFIED·OPERATIONAL VERIFIED로 상향하지 않는다.
- 다음 시작: `git -C C:/AX/cost-integration status --short`. 사본 제공 시 위 CLI 옵션과 승인 해시로 읽기 전용 진단을 진행한다. 시험 계정 제공 시 OIDC·ADC 실제 읽기와 철회·만료를 검증한다. 병합·배포가 승인되면 그 게이트에서 시작 SHA와 종료 HEAD를 기록해 필요한 전체 회귀를 실행한다.

## 2026-10-11 최종 업무 흐름 브라우저 검증

- 시작 HEAD: `1b3edbd5d5b308f50922b4fd3619c4bacf92d188`. 코드·검사 커밋은 `753e861`, `97819e5`이며 이후 기록 커밋은 Git과 PR #85를 따른다.
- 제품 수정: 영수증 후보 수정 화면의 결제수단을 현금·개인카드·법인카드로 표시한다. 저장값과 금액 계산은 유지한다. 기존 화면의 영문 코드 노출을 재현한 뒤 수정했다.
- 실제 Chromium, loopback HTTP, 임시 DB·합성 파일을 사용한 375px 검사 7개가 최종적으로 통과했다. 아래 결과는 서로 겹치는 재실행을 합산한 수치가 아니다.

| 흐름 | 실제 화면 조작과 저장 결과 |
| --- | --- |
| 카드 | CSV 업로드·분류 → 항목·여행·설명 입력 → 확정 → 새로고침 → 7열 클립보드 복사. 원본 37,000원과 사용자 확정을 DB에서 확인했다. 복사가 COST 장부 쓰기를 만들지 않는다. |
| 영수증 | PNG 업로드 → 영역 등록 → 여행·금액 수정 → 확정 → TSV 복사. 별도 검사에서 결제수단 변경 시 확정을 해제하고 재확정·새로고침 후 값을 보존한다. 나중에 수집된 동일 카드 근거가 있으면 복사를 보류하고 클립보드와 영수증 원본 파일을 유지한다. |
| 회사 경비 | 자연어 제외 제안 → 실제 저장 후 응답 유실 → 같은 요청 재시도 → 새로고침 → 제외 취소 → 새로고침. 두 제외 요청이 같고 거래 원본이 보존되는 것을 확인했다. |
| 부분환불 | 실제 합성 카드 XLSX 업로드 → 원결제 확정 → 같은 파일 재업로드 → 환불 쌍 기록 → 새로고침 → TSV 복사. 원결제 1,000,000원과 환불 -700,000원을 각각 보존하며 장부 2행·순액 300,000원, TSV 2행을 확인했다. |
| Google 정본 | 합성 메인·보관 스냅샷 → owner의 archive 선택 → viewer 상세 → 권한 철회 후 같은 URL에서 404. 비공개 행이 거부 화면에 남지 않는다. 브라우저 역할은 합성 주입이며 실제 로그인 성공 증거가 아니다. |
| 자연어 승인 | 제안 → 승인 DB 저장 후 응답 유실 → 동일 request_id로 재시도 → 결정 이력 1건 → 새로고침 후 화면·DB의 확정값 확인. |

실제 실행 명령과 결과:

- `python -m pytest webapp/tests/test_card_google_copy.py webapp/tests/test_receipt_review.py webapp/tests/test_company_exclusion_http.py webapp/tests/test_google_canonical_workflow.py webapp/tests/test_rule_review.py -k 375 -q --tb=short`: 처음 3 passed / 2 failed. 실패는 새 검사의 금액 기대값 오류와 JavaScript 불리언·숫자 엄격 비교 오류였다. 아래 표적 재실행으로 모두 수정 확인했다.
- `python -m pytest webapp/tests/test_card_google_copy.py webapp/tests/test_rule_review.py -k 375 -q --tb=short`: 2 passed.
- `python -m pytest webapp/tests/test_card_google_copy.py -k mobile_375_partial -q --tb=short`: 1 passed.
- `python -m pytest webapp/tests/test_receipt_review.py -k payment_review_and_late_card -q --tb=short`: 결제수단 표시 assertion 실패를 먼저 확인했다. 표시 수정 뒤 새 검사의 존재하지 않는 confirmed 필드를 실제 payee/category 계약으로 고쳤고 최종 1 passed.
- `python -m pytest webapp/tests/test_receipt_review.py -k mobile_375_photo -q --tb=short`: 표시 수정 후 1 passed.
- `git diff --check`: 통과. 기존 390px·1440px 브라우저, 서명 쿠키 HTTP, 회계 원자성·환불·중복 보호 검사는 기존 증거를 재사용했다. 변경은 표시 문구와 검사이므로 전체 pytest는 실행하지 않았다. 과거 전체 회귀를 최신 HEAD의 통과로 표시하지 않는다.

운영 경계와 다음 시작점:

- 승인된 실제 복구 사본이 없어 `tools/rehearse_cost_schema.py --check-only` 실측은 HOLD다. 운영 원본 DB를 열지 않았다. 실제 ADC/OIDC 인증, OCR 엔진, 운영 배포·병합은 실행하지 않았다.
- 실계정·실제 Google 연동·OCR 추론은 브라우저 완주에 포함하지 않는다. 회사 제외의 확정·기록 거래 정책과 중복 의심 영수증 인정 정책은 기존 HOLD를 유지한다.
- 다음에는 승인된 복구 사본이 제공되면 `docs/schema-rehearsal.md`의 필수 인자를 확인해 `--check-only`를 실행한다. 별도 비운영 계정이 제공되면 OIDC·ADC와 실제 여행 매핑을 검증한다. 운영 반영 승인 후에만 병합·배포 게이트를 실행한다.
- 사용자 `C:/AX/cost`의 dirty 1개, 미추적 4개, stash `fbb1226e4659e4a2b75216cd556b51687db7d73e` 목록을 보존했다. 내용 해시까지 비교한 것은 아니다.

## 2026-10-11 최대 구현 실행 — 후속 수정

- 출발점은 `1eec6d7d39f78c1456524b5c09050978afeaf10a`이며 브랜치는 `integration/cost-final`이다. 구현 커밋 20개를 추가했고 코드 HEAD는 `f052fcaee7d300c1aaefbf0e99171f381aa423cf`다. 이후 기록 커밋의 SHA는 Git과 PR #85를 따른다. 제품·테스트 15개 파일을 변경했다.
- 영수증: 미저장 금액·여행으로 확정하거나 미저장 검토값 대신 저장값을 복사하는 경로를 막았다. 화면의 후보 지문을 쓰기 시 비교하며, 마지막 저장과 정확히 같은 재시도만 결과를 재사용한다. 기존 버전 없는 내부 호출은 호환한다. 저장·복사 중 입력과 중복 요청을 잠그고 실패 후 복구한다. 한 행의 저장은 다른 행과 영역 입력을 지우지 않으며, 사진·영역 등록 전에는 미저장 검토를 보호한다.
- 파일: 사진은 임시 파일 완성 후 교체하고 기존 사진의 내용과 ID가 다르면 제공·재등록을 거부한다. 파일 교체 실패·JSON 오류·잘못된 레코드 구조는 원본을 초기화하지 않고 안전한 503으로 처리한다. 비정상 HTTP 응답은 원문 대신 재로그인·저장 여부 확인을 안내한다.
- 카드·영수증 복사는 이력 읽기 차단 시 중복 위험을 확인받은 뒤 진행한다. TSV는 보류·오류 사본도 중복 ID의 근거로 사용하며 카드 어댑터도 그 근거를 제거하지 않는다. 무관한 행과 기존 보류 사유는 유지한다.
- 자연어 승인: 여행·설명·검토 전 분류·상호를 지문에 포함했다. 별도 DB 연결의 변경은 쓰기 트랜잭션 안에서도 원본 상태와 비교한다. 환불 미리보기의 상속값과 원본을 구분하며 중간 충돌은 앞선 결정과 요청 기록까지 롤백한다.
- Google 동기화: 손상된 재시도 상태는 원본 조회 전에 거부하고 마지막 정상 스냅샷을 보존한다. 잠금 초기화 실패 시 핸들을 닫고 파일 접근 오류는 안전한 코드로 반환한다. 잘못된 시간·크기 제한값은 파일 생성 전에 거부한다.

실제 검사 근거는 아래와 같다. 범위가 겹치므로 합산하지 않는다.

| 실제 명령 또는 범위 | 결과와 적용 시점 |
| --- | --- |
| `python -m pytest webapp/tests/test_receipt_review.py webapp/tests/test_receipt_integrity.py tests/card_pipeline/test_receipt_candidates.py -q --tb=short` | 공통 파일 오류 처리 변경에서 75 passed / 12 subtests. 뒤의 레코드 구조 검사 변경은 해당 HTTP 표적 5 passed와 `test_receipt_integrity.py` 24 passed로 검증했다. |
| `python -m pytest tests/card_pipeline/test_google_tsv.py tests/card_pipeline/test_receipt_candidates.py tests/card_pipeline/test_company_expense_integration.py webapp/tests/test_card_google_copy.py -q --tb=short` | TSV 공통 수정에서 47 passed / 4 subtests. 뒤의 어댑터 수정은 어댑터·회사 제외 통합 12 passed로 검증했다. |
| `python -m pytest tests/card_pipeline/test_sync_schedule.py tests/card_pipeline/test_google_adc_export.py -q --tb=short` | 재시도 상태 변경에서 36 passed. 뒤의 잠금 경로 11 passed, 안전한 파일 오류 1 passed, 제한값·기존 CLI 경로 9 passed를 별도로 확인했다. |
| `python -m pytest webapp/tests/test_rule_review.py tests/card_pipeline/test_rule_proposals.py -q --tb=short` | 지문 수정에서 45 passed / 12 subtests. 쓰기 경합 변경은 규칙·DB 동시성 30 passed / 12 subtests와 중간 롤백 1 passed로 확인했다. 마지막 원본·미리보기 구분은 관련 HTTP 7 passed와 DB 동시성 3 passed로 확인했다. |

- 전체 pytest는 실행하지 않았다. 아래 3107 passed / 3 skipped / 2456 subtests 기준선은 과거 SHA의 근거로 유지한다. 이번 HEAD 전체 회귀 통과를 뜻하지 않는다. 모든 신규 결함은 실패 재현 후 수정했고 보호 assertion을 약화하지 않았다.
- 사용자 작업 트리의 수정 1개·미추적 4개와 기존 stash 목록은 시작·후속 확인에서 같았고 건드리지 않았다. 운영 DB·Google 원본·공유 설정·스케줄러·main·배포 설정은 변경하지 않았다. 생성한 임시 worktree나 에이전트는 없다.
- 다음 첫 명령은 `git -C C:/AX/cost-integration status --short`다. 독립적인 새 결함 근거가 없다면 통과 검사를 반복하지 않는다. 실제 인수의 다음 세 단계는 승인된 복구 사본의 `tools/rehearse_cost_schema.py --source-copy <승인된 사본> --confirm-isolated-copy --check-only`, 승인된 ADC/OIDC 계정의 읽기·만료·철회 검증, main 병합 또는 운영 배포가 승인됐을 때 시작 SHA와 종료 HEAD를 기록하는 전체 회귀다. 현재는 해당 운영 승인·자원이 없어 HOLD다. OCR 엔진과 기록·확정 거래 제외 정책도 기존 HOLD를 유지한다.

## 2026-10-11 검증 정책 변경

- [AGENTS.md](../AGENTS.md#검증-최소화재검증-금지-작업-우선-원칙)에 표적·인접 통합 검사 중심 정책과 전체 회귀의 실행 조건을 반영했다. 기능 완료나 커밋 누적을 이유로 전체 회귀를 반복하지 않는다.
- 아래 **3107 passed / 3 skipped / 2456 subtests passed**는 과거 기준선으로 보존한다. 새 HEAD의 전체 회귀 통과를 뜻하지 않는다. 이번 변경은 작업 규칙 문서뿐이므로 diff와 링크만 검토하고 코드 테스트는 실행하지 않는다.
- 작업 브랜치는 `integration/cost-final`이며 정책 변경 전 HEAD는 `ccf6352fc22f12d9f579bcc08d0e6d2dce9959d7`다. 정확한 최신 SHA는 Git과 PR #85를 따른다. 다음 코드 작업은 실제 결함의 영향 범위부터 정하고 관련 표적 검사만 실행한다. 운영 HOLD는 해제하지 않는다.

## 2026-10-11 COST V2 통합 안정화

- 작업 브랜치는 `integration/cost-final`이며 시작 HEAD는 `bcb1f514629a8f4d3402c977ebaba9b3d8bff29e`다. 코드 커밋 9개를 작성했다. 현재 코드 HEAD는 `4e74f43`이며 문서 이후의 정확한 SHA는 PR과 Git을 따른다.
- 새 결함 수정: 이전 자료의 조회·자동 갱신·업로드·규칙 제안·장부 확정·회사 제외 응답이 최신 안내를 덮는 문제, 저장 뒤 조회 실패를 전체 롤백으로 잘못 알리는 문제, 응답 유실 후 승인·답변 재시도의 요청 번호가 달라지는 문제, 클립보드 복사 뒤 이력 저장 실패를 복사 실패로 알리는 문제를 수정했다. 운영 환경에서 합성 세션 어댑터를 연결할 수 있던 경로도 DB 접근 전에 거부한다.
- 실제 표적 근거: 카드·규칙·제외·카드 HTTP·회사 제외 통합 88 passed / 55 subtests; 후속 제안 오류 1 passed; 운영 실행·스키마 게이트 인접 83 passed / 16 subtests; 답변 재시도와 핵심 카드 브라우저 23 passed / 6 subtests; 복사 영향 8 passed; 장부 확정 응답 2 passed; 마지막 회사 제외 HTTP·통합 12 passed와 카드 핵심 브라우저 9 passed / 2 subtests. 범위와 시점이 겹치므로 합산하지 않는다.
- 이후 환불 묶음 경로 5 passed와 늦은 환불 요청 브라우저 1 passed, 규칙 저장 후 재분류·조회 실패 2 passed, 정상 규칙 편집·모바일 흐름 2 passed도 통과했다. 후속 오류만 한정해 검증했고 기대값이나 회계 보호를 약화하지 않았다.
- 같은 자료에서 새 답변을 저장한 뒤 이전 자동 갱신 오류가 성공 안내를 덮는 문제도 재현했다. 요청 시작 당시 화면 버전까지 비교하도록 수정한 후 조회·자동 갱신 브라우저 4 passed / 4 subtests를 확인했다.
- 대표 실제 명령: `python -m pytest webapp/tests/test_card_google_copy.py webapp/tests/test_rule_review.py webapp/tests/test_company_exclusion_http.py webapp/tests/test_card_flow.py tests/card_pipeline/test_company_expense_integration.py -q --tb=short` → 88 passed / 55 subtests; `python -m pytest webapp/tests/test_platform_start.py webapp/tests/test_ops_hosting_bind.py webapp/tests/test_cp949_startup.py tests/card_pipeline/test_schema_gate.py -q --tb=short` → 83 passed / 16 subtests; `python -m pytest webapp/tests/test_refund_group_commit.py -q --tb=short` → 5 passed.
- 전체 회귀는 코드 `ae8c056`에서 `python -m pytest -q --tb=short`로 한 번 시작해 **3107 passed, 3 skipped, 2456 subtests passed, 실패 0**, 1689.47초, 종료 코드 0으로 끝났다. 로그는 `C:/AX/cost-v2-regression-20261011.log`다. 실행 중 추가한 운영 인증 차단·답변 재시도·복사 이력·확정/제외/환불 선택 가드·규칙 저장·같은 자료의 자동 갱신 경합은 위 후속 표적으로 검증했다. 전체 회귀 수집 이후 추가한 테스트를 전체 결과에 포함했다고 주장하지 않으며 최종 HEAD 전체 회귀를 다시 수집하지 않았다. 건너뜀 3개는 비공개 Agoda 자료 의존 2개와 Windows chmod 권한 재현 1개다.

| 검토 범위 | 확인한 안전 경계와 인수 조건 |
| --- | --- |
| 운영 스키마와 진입점 | `Procfile`은 `run_candidate.py --environment production`을 사용한다. Windows 실행기는 `tools/launch_web_ledger.py`를 사용한다. 두 경로는 카드 스키마 `require`와 읽기 전용 사전 검사를 강제한다. 개발용 직접 서버는 운영 진입점으로 사용하지 않는다. 운영에 복사된 실행기 파일도 배포 전에 승인된 절차로 대조해야 한다. |
| 리허설과 복구 | 합성 검사와 기존 통과 근거에서 잘못된 DB, 원본 지문, 자동 증가 이력, WAL 복사 경쟁, 반복 적용, 호출자 트랜잭션과 실패 롤백을 확인했다. `--check-only`는 복제본에도 마이그레이션하지 않는다. 게이트는 다른 장부 모듈의 모든 DDL을 승인하지 않는다. 실제 복구 사본·복원·재시작은 미실행이다. |
| 원본·제외·환불·장부 | 원본 거래와 사용자 결정은 제외로 바꾸지 않는다. 기록·확정·환불 보호와 늦은 환불 보류를 유지한다. 저장 후 상태 읽기 실패는 저장 결과와 구분하며 같은 요청을 재실행해 중복 결정·장부 행을 만들지 않는다. |
| Google 인증·권한 | 지정 원본만 ADC 읽기를 허용하고 리다이렉트·공개 폴백을 거부한다. 초기 인증 실패와 부분 장애도 정상 스냅샷을 보존하면서 stale로 표시한다. 403의 알려진 요청 한도와 접근 거절을 구분한다. viewer 상세는 현재 권한·여행 매핑·선택 정본을 모두 요구한다. HTML·JSON은 `no-store`다. |
| 영수증·TSV | 카드 연결 근거·원문 금액·JPY 환산 조건·행별 보류·7열 순서를 유지한다. 복사 이력 쓰기 실패도 실제 클립보드 성공을 취소로 표시하지 않는다. 복사는 Google 기록 완료가 아니다. |
| 스케줄·파일·데모 | 동기화는 OS 잠금과 실패 지연을 사용하며 현재/이전 세대만 참조한다. 정리 대상은 형식과 메타데이터가 일치하는 생성 파일로 제한한다. 스케줄 예시는 비활성이고 익명 데모는 합성 플래그가 있는 입력만 허용한다. |

- 검토는 main 대비 변경 파일 64개 목록을 분류하고 위 고위험 제품 경로와 연결 테스트를 중심으로 수행했다. 이번 변경은 제품 코드 4개, 테스트 6개, 이 문서에 한정된다. 기술적으로 코드 통합 검토 후보이며 발견된 미해결 테스트 실패는 없다. 최종 코드 이후 문서만 변경했고 코드 검사를 추가하지 않았다. 테스트·문서 변경을 운영 실측 완료로 해석하지 않는다. main 병합과 운영 인수 완료는 여전히 승인되지 않았다.
- HOLD: 검증된 실제 복구 사본의 읽기 전용 진단·복원 리허설과 운영 DB 변경 승인, 실제 ADC/OIDC 계정·여행별 매핑 확인, 기록·확정 거래 제외 및 중복 의심 영수증 정책, 승인된 OCR 엔진, 운영 배포·스케줄·Render 승인이다. Google의 기존 링크 공유 제한은 인증 전환 검증과 별도 권한 승인이 필요하다.
- 사용자 `C:/AX/cost`의 변경 1개·미추적 4개와 stash `fbb1226e4659e4a2b75216cd556b51687db7d73e`를 보존했다. 운영 DB·Google 원본·공유 설정·스케줄·main은 변경하지 않았다.
- 회귀가 생성한 OTA 화면 캡처 두 개는 `.local-archive/regression-v2-20261011-192337`에 보관하고 해당 추적 파일만 실행 전 HEAD 상태로 복구했다. GitHub Actions와 등록된 deployments는 게시 전 각각 0개였으며 배포 설정을 변경하지 않았다.
- 다음 첫 명령은 `git -C C:/AX/cost-integration status --short`다. 이어 PR #85의 HEAD를 비교하고 새 실패 근거가 있을 때만 관련 표적을 재개한다. 운영 인수는 승인된 복구 사본 경로가 제공된 뒤 `tools/rehearse_cost_schema.py --source-copy <승인된 사본 경로> --confirm-isolated-copy --check-only` 진단부터 진행한다. 현재 운영 원본에 연결하지 않는다. 독립적인 새 결함은 이번 검토에서 더 재현하지 못했으며 완료한 검사를 관성적으로 반복하지 않는다.

## 2026-10-11 실제 Windows 저장소 후속 개발

- 후속 수정: 보류 영수증의 원문 통화 표시, 잘못된 TSV ID·증빙·날짜의 행별 보류, 승인·답변 저장 응답의 이전 자료 복귀 방지, 같은 자료의 오래된 거래·제외 버전 거부를 추가했다. 이 문서 커밋까지 이번 실행의 신규 커밋은 19개다. 최신 HEAD는 PR #85와 `git rev-parse HEAD`를 따른다.
- 추가 실제 검사: TSV·카드 어댑터·회사 제외 통합·영수증 무결성 47 passed; 통화 표시 4 passed; 승인 후 선택 유지·기존 모바일/데스크톱 규칙 작업 3 passed; 카드 복사·규칙 인접 25 passed / 12 subtests; 핵심 업로드·답변·기록·출력 브라우저 9 passed / 2 subtests; 마지막 거래·제외 버전 가드의 카드 복사·핵심 브라우저 19 passed / 2 subtests. 새 실패는 재현 후 수정했고 미해결 테스트 실패는 없다. 검사 범위가 겹치므로 합산하지 않는다.
- 다음 첫 명령: `git -C C:/AX/cost-integration status --short`. 통과한 검사를 반복하지 않는다. 독립적인 후속 검토가 필요하면 `webapp/card_flow.py`의 비동기 오류 상태 표시부터 조사하고, 새 재현이 있을 때만 수정한다. 운영 인수검증은 승인된 복구 사본의 `tools/rehearse_cost_schema.py --check-only` 진단과 실제 ADC/OIDC 계정 확인으로 이어간다. 원본 운영 DB와 Google 원본은 여전히 HOLD다.

- 작업 위치: `C:/AX/cost-integration`, 브랜치 `integration/cost-final`. 출발점 `b9ef086`, 중간 점검 코드 `a392d4e`까지 신규 커밋 12개였으며 이후 작업은 위 후속 수정에 기록했다. 정확한 최신 HEAD는 `git rev-parse HEAD`와 PR #85에서 확인한다.
- 스키마: 잘못된 board 모양과 복사 중 WAL 생성 거부, 자동 증가 이력 보존, 반복 리허설, 오류 코드만 출력, `--check-only` 진단을 구현했다. 운영 실행기 두 경로는 카드 스키마를 읽기 전용으로 사전 확인하고 이후 Store도 `require` 정책을 강제한다. 개발 기본 생성은 유지하며 운영 원본에는 연결하지 않았다.
- ADC: 초기 인증 실패도 마지막 정상 행을 유지하면서 stale 상태를 게시한다. 영구 토큰 갱신 실패·일시 장애·403 요청 한도를 구분하고 응답 정리 오류가 비밀을 노출하지 않도록 수정했다. 부분 장애와 복구를 실제 세대 파일로 검사했다.
- 영수증: 카드에 연결된 원래 식별 근거를 유지해 상호·날짜 수정이나 카드 일시 소실 후 현금 재계상을 거부한다. 보류 입력과 이미지 영역을 보존하고 늦은 카드 연결의 보류를 이력으로 옮긴다. 반복 수정은 확인과 이력을 중복 변경하지 않는다.
- UI: 바뀐 선택과 맞지 않는 규칙 제안·카드 자료·자동 갱신 응답을 버린다. 카드 복사의 중복 클릭과 오래된 자료의 클립보드 쓰기를 막고 영수증 복사 중 여행 선택을 잠근다. 오류·빈 결과 후 입력과 버튼은 복구한다.
- 실제 검사: 시작 표적 29 passed; 초기 스키마·리허설 13 passed; Store 영향 카드 파이프라인·카드 웹·실행기 인접 708 passed / 39 subtests; 게이트 9 passed와 이후 WAL 동시성 1 passed; ADC·정본·스케줄 66 passed와 추가 부분 장애 복구 1 passed; 마지막 ADC 13 passed; 마지막 리허설 13 passed; 실행기 71 passed / 16 subtests; 영수증 무결성·브라우저 49 passed / 12 subtests; 규칙 HTTP·브라우저 15 passed / 12 subtests; 최신 카드·영수증 복사 브라우저 37 passed / 12 subtests. 중간 겹치는 범위는 합산하지 않는다. 새 재현 실패는 수정했으며 남은 실패는 없다.
- 과거 전체 회귀 3035 passed / 3 skipped / 2452 subtests는 `189b804` 시점 증거다. 영향 없는 전체 회귀·OTA 재대사·운영 스모크를 반복하지 않았다. 최신 HEAD 전체 회귀로 주장하지 않는다.
- 사용자 `C:/AX/cost`의 변경 1개·미추적 4개와 stash `fbb1226e4659e4a2b75216cd556b51687db7d73e`를 확인하고 보존했다. 실제 SQLite·운영 설정·Google 원본·공유권한·스케줄러·main은 변경하지 않았다.
- HOLD: 검증된 실제 복구 사본과 운영 마이그레이션 승인, 실제 ADC/OIDC 계정과 여행별 매핑 확인, 기록·확정 거래 제외 및 중복 의심 영수증 정책, 승인된 OCR 엔진, 운영 배포·스케줄 활성화·Render 이전 승인.
- 통화 표시와 TSV 입력 형식 검토는 위 후속 수정으로 처리했다. 따옴표의 Google 붙여넣기 해석을 추정해 TSV 규격을 다시 작성하지 않았다. 실제 Google 붙여넣기는 이 세션에서 수행하지 않았다.

## 2026-10-11 후속 세션 — 안전한 추가 구현

- 최신 통합 작업은 **PR #85 / integration/cost-final**에 계속 커밋했다. 정확한 원격 HEAD는 GitHub PR에서 다시 확인한다. handoff/session-20261011-cost는 문서용 별도 브랜치다.
- **DB 리허설 신규 구현:** tools/rehearse_cost_schema.py + tests/card_pipeline/test_schema_rehearsal.py + docs/schema-rehearsal.md. **검증된 복구 사본**을 별도 임시 파일로 복제한 뒤 Store DDL을 적용하고 입력 파일 불변, 과거 스키마/행 지문 불변, 회사 제외 테이블 설치를 검사한다. 빈·잘못된 DB, WAL, 해시 불일치 등은 거부한다. 실제 운영 DB 연결/변경은 없음.
- **Google 인증 읽기 선택형 구현:** app/google_adc_export.py + tests/card_pipeline/test_google_adc_export.py, tools/google_authority_sync.py의 --google-auth adc. 허용된 메인/보관 파일만 Google Drive API의 읽기 전용 내보내기를 사용하고, 외부 리다이렉트·무인증 폴백을 하지 않는다. 운영 자격증명은 설정·실행하지 않았다.
- **합성 시험:** 이 세션의 별도 격리 Python 하네스(실제 repo 전체가 아닌 핵심 Store 계약 대역)에서 schema rehearsal 7개, Google 인증 adapter 7개가 통과했다. Google 계정 인증 실측, PR HEAD의 실제 저장소 pytest와 전체 회귀는 **실행하지 않음**. 이전 전체 회귀 3035 passed는 기존 HEAD 근거만이다.
- **실제 Google 읽기 전용 실측:** 연결된 Google Drive에서 보관 26개/메인 43개 탭, 양식_rev의 수입·지출 B:H 헤더·합계 수식과 실제 여행 3개 탭 헤더를 확인했다. 계정/파일 권한은 변경하지 않았다. 현재 양 원본에 **anyone/reader, allowFileDiscovery=false**가 있어 링크 보유자 열람 위험이 확인됐다. 자세한 상태는 docs/google-authority-sync-readiness.md 9절 참고. 제한 전 인증형 읽기와 사업 권한 승인이 필수다.
- **Windows 환경:** 이 세션 도구에서는 C:/AX/cost 및 C:/AX/cost-integration에 접근할 수 없으므로 로컬 dirty·stash·운영 프로세스는 현재 상태 재검증 불가. 접근하거나 변경한 적 없다. 사용자/운영 파일 삭제, main 병합, 서버 재시작, 스케줄러 활성화, 운영 DB 마이그레이션, Google 원본 수정, 외부 실정보 공개는 수행하지 않았다.
- **다음 실제 코드 검증 명령:** 격리 worktree에서 HEAD/dirty 확인 후 `python -m pytest tests/card_pipeline/test_schema_rehearsal.py tests/card_pipeline/test_google_adc_export.py tests/card_pipeline/test_sync_schedule.py -q --tb=short`로 새 코드와 인접 경로를 한 번 검증한다. 추가 결함이 있으면 표적 수정. 그 다음 승인된 복구본 스키마 리허설·실제 ADC/장부 접근 실험만 별도 승인과 함께 수행한다.


- 작업 위치는 `C:/AX/cost-integration`, 브랜치는 `integration/cost-final`이며 해당 기록 시점의 코드 HEAD는 `a6cd496`이었습니다. 정확한 HEAD와 미커밋 상태는 `git status --short`와 `git rev-parse HEAD`로 확인합니다. 사용자 작업 위치 `C:/AX/cost`의 변경과 미추적 `webledger.work.operator.sqlite.checkpoint.json`은 보존하며 게시하지 않습니다.
- 이번 요청에서 viewer의 여행 권한과 선택된 정본 source를 함께 검사하도록 수정했습니다. 정본 미선택, 선택되지 않은 사본, 선택된 사본 소실, 철회 후 직접 상세 URL은 거부합니다. owner는 남은 사본을 명시적으로 다시 선택할 수 있습니다.
- `Store` 생성의 자동 DDL을 저장점으로 묶어 중간 실패 전체 롤백과 호출자 트랜잭션 보존을 구현했습니다. 첫 `CardFlow` 조회도 선택된 DB의 신규 테이블 생성 시점일 수 있습니다. 운영 DB에는 연결하거나 적용하지 않았습니다.
- 회사 경비 제외 통합 테스트는 미리보기·확정·TSV·되돌리기·원문과 사용자 결정 보존·환불 보호·DB 오류 후 동일 요청 재시도를 검증합니다. 제외 후 별도 파일의 환불 도착도 단독 기록과 TSV를 차단합니다.
- 표적 검증은 스키마와 카드 인접 경로 96 passed / 39 subtests passed, 첫 CardFlow 생성 1 passed, 정본·서명 HTTP 경로 52 passed / 28 subtests passed, 회사 제외 통합 4 passed와 추가 환불 1 passed입니다. 시점과 범위가 다르므로 합산하지 않습니다.
- 전체 회귀는 `189b804`에서 `python -m pytest -q --tb=short`로 시작해 3035 passed, 3 skipped, 2452 subtests passed, 실패 0으로 끝났습니다. 실행 시간은 1328.21초이며 로그는 `C:/AX/cost-full-regression-20261011.log`에 있습니다. 건너뜀은 과거 비공개 Agoda 자료 의존 검사 2건과 Windows chmod 권한 재현 검사 1건입니다. 실행 중 추가한 사본 소실 수정과 환불 테스트는 위의 별도 표적 결과로 검증했습니다. 변경되지 않은 전체 범위를 다시 실행하지 않았습니다.
- 전체 회귀가 생성한 OTA 화면 캡처는 `.local-archive/regression-20261011`에 보관하고 추적 파일은 실행 전 상태로 복원했습니다. 사용자 작업 트리는 보존했습니다. main 대비 변경은 54개 파일입니다.
- 이번 코드 작업은 세 커밋 `189b804`, `5dc47cf`, `a6cd496`입니다. PR #85의 최신 SHA와 결과는 GitHub 본문에 기록합니다. 문서 커밋이 추가되므로 정확한 최종 HEAD는 `git rev-parse HEAD`로 확인합니다.
- 다음 세션의 첫 명령은 `git -C C:/AX/cost-integration status --short`입니다. 새로운 결함 근거 또는 아래 운영 승인에 따라 재개하며, 현재 통과한 검사를 이유 없이 반복하지 않습니다. 운영 승인 전 수행할 독립 코드 결함은 이번 범위에서 더 발견하지 못했습니다.
- 남은 운영 HOLD는 main 병합, 배포·재시작, 자동 스키마 생성을 포함한 운영 DB 변경 승인과 복구 사본 검증, 실제 계정·여행 매핑 검증입니다. 이미 기록·확정된 거래의 신규 제외 정책과 별도 영수증으로 인정할 중복 의심 후보 정책도 별도 결정이 필요합니다. 승인된 로컬 OCR 엔진이 없어 수동 입력을 유지합니다. 실제 Google 원본 쓰기와 외부 OCR 전송은 수행하지 않습니다.
