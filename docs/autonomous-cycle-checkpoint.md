# 자율 개발 체크포인트

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
