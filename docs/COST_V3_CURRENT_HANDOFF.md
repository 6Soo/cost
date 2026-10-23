# COST V3 — CURRENT HANDOFF / RESUME FROM GITHUB

> **기준시각:** 2026-10-23 KST. **이 문서는 COST V3 현행 작업 상태 및 다음 실행 큐의 단일 스냅샷이다.**
> 새 채팅·새 PC·다른 모델은 이전 대화를 재요구하지 말고 이 문서, [COST V3 진입점](COST_V3_START_HERE.md), [COST AGENTS](../AGENTS.md), 아래 두 저장소의 최신 원격 상태만으로 재개한다.
> 최신 사용자 승인 정책과 실제 코드·CI·배포 증거가 과거 요약보다 우선한다. 기준시각 이후의 커밋·배포·설정은 반드시 다시 조회한다.

## 0.1 2026-10-23 실행 갱신

- COST `main`과 `origin/main`은 `15cdccc5536bd3b4b6af97e595a12af49fcb8456`으로 같았다. 작업 트리의 기존 미추적 `.claude/stop-gate/`는 보존했다.
- 운영 코드 체크아웃 `C:\AX\cost`에서 보호 백업·별도 복원 검증을 실행했다. 데이터베이스 5개와 파일 59개의 비교, 원본 상태 불변, 복원 연결 일치를 확인했다. 실제 요청 재실행, 운영 자료 가져오기, 비밀 파일 복사는 하지 않았다.
- 호스트 작업 재시작 후 `127.0.0.1:8751/healthz`와 `/readyz`가 모두 정상 응답했다. 현재 코드는 승인된 `main` 체크아웃에서 제공된다. 자동화된 직접 재시작 스크립트는 예약 작업 인자 형식 검사에서 `SUPERVISOR_IDENTITY_UNVERIFIED`로 종료했지만, 보호 절차가 예약 작업을 다시 시작했고 서비스 정상 응답을 확인했다. 해당 검사 우회는 하지 않았다.
- 참가자 API에 COST의 기존 보호 토큰 파일을 사용해 합성 식별자 한 건만 읽기 요청했다. 응답은 `401 Unauthorized`였고 후보 자료는 반환되지 않았다. 이 파일은 Reservation의 현재 `INTERNAL_API_TOKEN`과 일치하지 않거나 더 이상 유효하지 않다. 토큰 값은 읽거나 출력하지 않았고 교체·발급도 하지 않았다. 따라서 COST↔Reservation 인증 읽기와 화면의 실제 원본 연결은 여전히 차단 상태다.
- 오래된 `deploy/ota-unified-20261021`은 최신 `main`과 통합하면 V3 코드·검사를 포함한 107개 경로에서 약 11,700줄을 삭제한다. 이 브랜치 병합은 중단했고 `main`에는 해당 삭제를 반영하지 않았다.
- **다음 작업:** 권한 있는 운영자가 COST의 `D:\WebLedgerHost\secrets\reservation-internal-token.txt`를 Reservation의 기존 내부 API 토큰과 안전한 비밀 채널로 맞춘 뒤, 값이 노출되지 않는 상태 코드만으로 인증된 읽기를 재검증한다. 토큰을 채팅·Git·로그에 붙이지 않는다.

## 0. 새 에이전트용 즉시 실행 계약

**목표:** OTA↔실제 카드 대사, 여행 우선 배정, 사용자 이동·AI 규칙 승인, 한/영 참가자 연결, N:M 그룹, 금융 중복·환불 보호, Google 수동 붙여넣기까지 **승인된 COST V3를 실사용 가능하게 마무리**한다. 코드가 이미 있는 기능을 재작성하지 않고 **남은 미검증 경계와 실제 결함**부터 해결한다. 조사만 하고 끝내지 않는다.

1. **가장 먼저:** 6Soo/cost와 6Soo/reservation의 origin/main, 작업 트리, 열린 PR, GitHub Actions, 실제 Vercel 대상 SHA를 조회한다. 원격 SHA를 고정값으로 믿지 않는다. 로컬 미커밋·미추적·stash, 사용 중인 worktree를 보존한다.
2. **읽기 순서:** 이 문서 → [COST V3 진입점](COST_V3_START_HERE.md) → [OTA A 정책](ota-card-reconciliation-policy-a-v3.md) → [추론/AI/참가자/N:M 명세](cost-v3-inference-ai-passenger-nm-test-architecture.md) → 해당 기능의 실제 소스와 검증. 필요할 때만 [Google 정본 계약](target-workflow-google-authority.md), [정본 회계 규칙](reconciliation-rules.md), [운영 이력](operations.md)을 읽는다.
3. **실행 흐름:** 승인 명세 기준 갭 확인 → 안전한 코드 구현 → 직접 영향 테스트 및 종단 검사 → diff/개인정보 확인 → 허용된 Git 반영 → 다음 실행 가능 항목. 작은 단위 완료나 최종 보고가 전체 종료 조건이 아니다.
4. **BLOCKED 판정:** 실제로 필요한 비밀정보/운영 권한만 차단한다. 그러한 권한 없이도 가능한 CI 원인 분석, 코드·계약 수정, 합성/Preview 검증, 문서 정리는 계속한다. 과금·운영 DB 변경·고객자료 전송을 자동 승인받은 것으로 간주하지 않는다.
5. **작업 큐와 종료:** 아래 P0/P1/P2를 근거로 재평가하라. 문서의 추정 구현률로 COMPLETE 처리하지 않는다. 이미 통과한 정확한 검사는 재사용한다. 승인 범위의 실행 가능한 항목이 정말 없으면 정확한 차단 조건을 남기고 종료한다. 무한 반복이나 임의 작업 발굴 금지.

## 1. 마지막 검증된 Git 및 배포 기준점

| 표면 | GitHub/플랫폼에서 확인한 사실 | 구분 |
| --- | --- | --- |
| COST 앱 코드 기준 | [6Soo/cost main](https://github.com/6Soo/cost/commits/main); V3 앱 코드 기준 **0bd6e933ab** | V3 앱 기준 뒤의 main 추가 커밋은 문서-only다. 운영 호스트 릴리스는 별개이며 main 전체 배포가 아니다. |
| Reservation 앱 코드 기준 | [6Soo/reservation main](https://github.com/6Soo/reservation/commits/main) **c315c17a0f** (2026-10-23 확인) | [PR #22](https://github.com/6Soo/reservation/pull/22) 참가자 API, [PR #23](https://github.com/6Soo/reservation/pull/23) KST 테스트 날짜 고정, [PR #24](https://github.com/6Soo/reservation/pull/24) 참가자 API 모든 응답의 비저장 캐시 정책 적용 |
| Reservation Vercel | [Production 배포 dpl_7dNPpkvC5sWHtkPGn8gWfAns6GU1](https://vercel.com/6soos-projects/reservation/7dNPpkvC5sWHtkPGn8gWfAns6GU1) — target=production, state=READY, sha=**c315c17a0f** | Turso Production Secret 반영을 위한 재배포와 PR #24 병합 자동 배포가 모두 READY. 최종 배포의 무인증 API 응답은 401, `no-store, private`, `Vary: Authorization` |
| Reservation Actions | [PR #23 workflow](https://github.com/6Soo/reservation/actions/runs/39939654895) 및 [PR #24 병합 커밋 workflow](https://github.com/6Soo/reservation/actions/runs/39945322228): **unit SUCCESS / smoke SUCCESS** | **P0 완료.** 이전 날짜 테스트 실패는 10/21 기준선(39639564867)에서도 발생한 테스트 날짜 고정 부재였다. PR #24의 캐시 오류 응답 수정 표적 검사와 전체 CI가 통과했다 |
| COST 배포 | [운영 이력](operations.md)의 마지막 기록 릴리스 **6bda111bdc**; GitHub `deploy/ota-unified-20261021` HEAD도 **6bda111bdc**로 확인 | 2026-10-23 비교 시 main 쪽 179커밋, 운영 쪽 25커밋 차이. 그 뒤 main 문서-only 커밋이 추가돼 앱 코드 차이는 그대로다. 현재 구동 중인 운영 프로세스 SHA·V3 실기능은 현 세션에서 미검증. **원격 단순 병합/일괄 배포 금지** |
| 로컬 작업 공간 | 에이전트 보고상 COST 미추적 .claude/stop-gate/, reservation 사용자 미커밋 변경 보존 | GitHub에서 로컬 상태를 확인할 수 없음. 새 실행 시 로컬에서 재확인 필수 |

**수치 주의:** 과거 에이전트의 “94%”는 **17개 자체 정의 체크 중 16개 확인**이라는 추정 지표이며 독립적인 명세 전체 완료율·운영 준비율이 아니다. 저장소 구현·합성 종단 검증은 상당 부분 완료됐으나 실제 운영 기능 검증과 별도로 취급한다. 새 에이전트가 임의로 백분율을 다시 만들지 않는다.

### 실제 배포와 기능 동작의 구분

- Reservation **최신 Production 배포(70b00859)는 READY**, [GitHub Actions unit/smoke](https://github.com/6Soo/reservation/actions/runs/39939654895)는 모두 PASS다. PR #22 및 dd734e0 배포 기록은 과거 관측으로 보존한다.
- 사용자 승인에 따라 Aside에서 Turso `6soo/reservation` 전용 읽기 토큰을 발급하고 Vercel Reservation의 **Production Secret**으로 `TURSO_READONLY_AUTH_TOKEN`과 `TURSO_READONLY_DATABASE_URL`을 저장했다. 제공자가 발급한 토큰의 권한 claim `a=ro`, 만료 `2026-12-22T11:01:37Z`를 확인했다. 기존 `INTERNAL_API_TOKEN`(Production/Preview)은 변경하지 않았다. 설정은 저장됐지만 새 배포가 필요하며 이번 설정 후 재배포는 실행하지 않았다. COST 쪽 BASE_URL/내부 토큰 일치와 실제 API 인증은 미검증이다.
- 과거 unit 실패는 로그에서 정확히 `tests/masterDataQueue.test.ts`의 기대 3/실제 2로 확인됐고, [PR #22 이전 기준선](https://github.com/6Soo/reservation/actions/runs/39639564867)에서도 같았다. GET route만 실제 오늘(KST)을 쓰고 test fixture는 2026-10-10 기준이라 2026-09-20 종료 여행이 실행일에 따라 30일 범위를 벗어난 것이 원인. [PR #23](https://github.com/6Soo/reservation/pull/23)에서 해당 테스트에만 Node 22 `t.mock.method(Date,'now',...)` 적용 후 CI 녹색.
- 실제 운영 API를 통한 참가자 검증은 미수행이다. 이전 Aside 시도에서 데이터 표가 잠시 열렸고 Block Reads가 잘못 켜졌으나 꺼짐으로 복원했다. 이번 설정 재시도에서는 데이터 표를 열지 않고 읽기·쓰기 차단 모두 꺼짐을 확인했으며 DB 행·스키마 수정이나 데이터 내보내기는 하지 않았다. 예약 원문을 문서에 복사하지 않는다. 사용자 선택은 COST 내부 연결이며 **실제 탑승 확정/보험 명단 변경**이 아니다.

## 2. 구현된 범위 — 우선 재사용할 근거

| 모듈 | 구현·테스트 근거(대표) | 여전히 구별할 사항 |
| --- | --- | --- |
| R0 진단/R1 계보·수동 pin 보존 | tools/audit_ota_card_coverage.py; 원본 재수집·저장소 재열기·crosswalk·중복 ID 표적 검증 | 실제 운영 전체 소스에 대한 전수 정확도 분석은 별도 작업 |
| R2 날짜 누락·후보 | OTA 날짜 없는 거래 후보와 merchant alias 및 카드 유효성 분리 | 미확정 예약번호를 확정값으로 올리지 않음 |
| R3 중앙 대사 | app/ota_payments.py, webapp/ota_snapshot.py, webapp/ota_payment_review.py, webapp/card_flow.py; COST 30b29fd 등에서 API/카드/귀속/준비 같은 발행 세대 종단 검증 | stale fallback은 복구용. 분류·재분류에서 구형 엔진이 중앙 정본을 덮지 못하도록 유지 |
| R4 금융 readiness | 실제 카드 원행 기준 경비 준비; COST cbc1c9a 120,000원 OTA 미확정→웹 저장→Google 복사 예약번호 공란. 중복·환불·원본 충돌 보류 | 실제 운영 장부 자동 대량 재기장 금지 |
| R5 사용자 이동·AI 학습 | 여행 A→B 즉시 수동 저장, 선택지 1/2/직접 답변3, 규칙 미리보기·승인·미래 거래 반영, 브라우저 합성 검증 | 모델 장애에도 사용자 배정 유지, 규칙은 승인 전 미적용 |
| R5-B 참가자 후보 | COST 58f569d owner 화면/HTTP adapter/SQLite 저장/재조회·stale 재확정; Reservation PR #22 API+snapshot; 양 저장소 실제 handler→HTTP→브라우저 합성 E2E 통과 보고 | Production READY이나 운영 토큰 인증/실자료 결과 미검증. 신원 자동 확정·실탑승 아님 |
| R6 레거시 소비 정리 | COST f52533e 대량 재분류 중앙 _ota_report, 268f7d8 stale fallback 경합 방지; 중앙 결정 권한 우선 | 오래된 스냅샷 복구용 fallback과 진단 전용 순수 비교 함수는 보존. 의미 없는 제거 금지 |
| N:M 그룹 | 2:2·2:3 그룹 제안, 결제일·금액/승인일·가맹점 증거 표시, 카드 원행 1건 1회 기록, 개별 대응 확정 금지 | 그룹 제안은 카드별 예약번호/이용기간/장부 날짜 확정의 근거가 아님 |

**검사 기록(에이전트 보고):** COST webapp/tests/test_card_flow.py 전체 67 tests + 28 subcases 통과; reservation API/snapshot 약 7개 표적 검사·TypeScript·ESLint 및 Preview 통과; 양 저장소 실제 합성 HTTP handler→COST adapter→owner browser→SQLite→stale 재확정 1개 통과. 이 문서 작성자는 해당 명령을 로컬에서 재실행하지 않았다. 최종 HEAD에서 변경 영향이 생긴 경우만 필요한 검사 재실행.

**직접 진입할 테스트:**
- COST: webapp/tests/test_passenger_cross_repo_integration.py, test_flight_passenger_page.py, test_card_flow.py, test_card_flow_browser.py, test_ota_payment_review_browser.py, test_cleanup_reclassification.py, test_targeted_test_selector.py (전부 webapp/tests 아래).
- Reservation: tests/passengerCandidateRoute.test.ts, tests/passengerCandidateSnapshot.test.ts, tests/masterDataQueue.test.ts, .github/workflows/smoke.yml.
- 구현 파일: COST webapp/flight_passenger_page.py, webapp/reservation-passenger.env.example, webapp/card_flow.py, webapp/ota_snapshot.py, webapp/ota_payment_review.py; Reservation src/app/api/internal/passenger-candidates/route.ts, src/lib/passengerCandidateRoute.ts, src/lib/passengerCandidateSnapshot.ts, src/lib/db.ts.

## 3. 미완료·미검증 작업 큐 (재개 우선순위)

### P0 — Reservation GitHub Actions unit 실패 복구 (**COMPLETE**)

**2026-10-23 실제 확인:** PR #22 이전 기준선 [workflow 39639564867](https://github.com/6Soo/reservation/actions/runs/39639564867)과 cc4e325/ dd734e0의 CI에서 동일한 `tests/masterDataQueue.test.ts` 기대 3/실제 2 실패를 로그로 확인했다. 테스트 fixture는 `TODAY='2026-10-10'`이지만 실제 GET route는 실행 시점의 KST 날짜를 계산해 2026-09-20 귀국 여행이 30일 조건에서 탈락했다. 운영 로직/기대 건수는 정상이고 테스트 실행 날짜 격리만 누락된 문제였다.

- [Reservation PR #23](https://github.com/6Soo/reservation/pull/23), squash main `70b00859e50a3239038f469ce1d07c006a9f78c5`: `tests/masterDataQueue.test.ts` **1파일**, +4/-1, scoped Date.now mock. 코드/DB/PII/.env 변경 없음.
- [main workflow 39939654895](https://github.com/6Soo/reservation/actions/runs/39939654895): **unit SUCCESS, smoke SUCCESS**. 반복 전체 테스트 불필요.
- [Production 수동 재배포](https://vercel.com/6soos-projects/reservation/36njAr5b7hTsGsZLgAFeHt96ZWzR): target=production, sha=70b00859, state=READY. 저장된 Production 설정을 적용했다. 후속 PR #24는 아래 현재 배포 항목에서 확인한다.
- [PR #24](https://github.com/6Soo/reservation/pull/24), squash main `c315c17a0fa3a0705530506345534e76d4004860`: 참가자 API의 200/400/401/404/503 응답을 `Cache-Control: no-store, private`, `Pragma: no-cache`, `Vary: Authorization`으로 통일. `tests/passengerCandidateRoute.test.ts`의 인증 실패·읽기 전용 설정 누락 응답 검사 추가.
- [PR #24 Preview](https://vercel.com/6soos-projects/reservation/5GAnS7yH31yD1VHTPvd2Az1W72C7): READY. Reservation 표적 Node 검사 3 passed, ESLint 통과, GitHub Actions unit/smoke 모두 SUCCESS.
- [현재 Production 배포](https://vercel.com/6soos-projects/reservation/7dNPpkvC5sWHtkPGn8gWfAns6GU1): target=production, sha=c315c17, state=READY. 무인증 요청 결과 `401`, `Cache-Control: no-store, private`, `Vary: Authorization`, 본문 `Unauthorized`. 후보 자료는 조회되지 않았다.
- **재개 규칙:** 같은 P0를 다시 구현·검사하지 않는다. 미래에 새로운 실패 로그/변경 SHA가 확인될 때만 새로운 영향 범위를 조사한다.

### P1 — R5-B 실서비스 읽기 연동 안전성 검증 (실제 운영 설정 권한은 별도)

**상태: 코드 구현 COMPLETE / Turso 설정 저장 COMPLETE / Production 배포 COMPLETE / 무인증 경계 검사 COMPLETE / 인증 읽기 FAILED(401) / 실제 후보 데이터 미검증.** 기존 기록에 따라 Turso 읽기 전용 권한과 Reservation 배포는 완료됐다. 2026-10-23 COST 호스트의 보호된 토큰 파일로 합성 식별자 한 건을 요청했지만 `401 Unauthorized`를 받았다. 후보 자료는 반환되지 않았고 토큰 원문은 출력하지 않았다. COST 측 기존 토큰이 Reservation의 현재 `INTERNAL_API_TOKEN`과 일치하는지 운영자가 비밀 저장소에서 확인해야 한다. 값이 다르거나 만료됐다면 두 서비스의 기존 승인 경계 안에서 안전하게 맞춘다. 인증된 실제 참가자 읽기·source revision·stale 재확정 흐름은 미검증이다.

1. Vercel reservation의 Production `c315c17` READY와 도메인/환경을 재확인했다. 운영 환경변수는 **이름·환경만** 확인하고 값은 출력·복사·로그하지 않는다.
2. Reservation의 내부 API: /api/internal/passenger-candidates?tourFldid=... ; 보호 Bearer 인증. 서버측 읽기 전용 전용 DB 클라이언트가 기존 getDb() schema 초기화·PII 마이그레이션을 사용하지 않는 구조임을 유지.
3. 필요한 설정 **Reservation**: INTERNAL_API_TOKEN(기존 내부 소비자 영향 검토), TURSO_READONLY_AUTH_TOKEN(해당 단일 DB read-only scope 필수), 선택 TURSO_READONLY_DATABASE_URL. **COST**: RESERVATION_INTERNAL_BASE_URL, RESERVATION_INTERNAL_API_TOKEN 또는 보호된 토큰 파일 경로(정확한 변수 이름은 webapp/reservation-passenger.env.example에서 재확인).
4. 변수 이름에 READONLY라고 적힌 것만으로 DB 권한을 증명하지 않는다. 운영 DB에 INSERT/CREATE를 시험하지 않는다. 격리 비운영 DB의 동일 권한 정책으로 조회 허용·쓰기 거부를 확인하거나 제공자 권한 표시를 검증한다.
5. 운영에서 사용자 승인 범위 내 **비파괴 읽기/비식별 결과 검증**: 비인가 요청 차단(401), 누락된 설정 실패 폐쇄(503), 승인된 범위의 tour 한 건에 한정된 최소 데이터, source_revision, 고객 ID/RRN/전화/여권 비노출, COST 후보 화면→사용자 확인→내부 저장/재조회→원본 변경 stale. 실제 고객명·토큰을 문서·채팅·CI artifact에 남기지 않는다.
6. 운영 비밀설정/인증 접근권이 없으면 **이 운영 단계만 BLOCKED**. 코드·테스트/CI 문제는 독립 진행. 실제 credentials를 요청하거나 채팅으로 붙여넣게 하지 않는다. 사용자가 Vercel 및 COST의 비밀 저장소에 직접 설정하도록 정확한 변수명과 권한 절차만 안내한다.

**완료 증거:** 실제 접근 대상 서비스 SHA/환경, 비밀값 없는 HTTP 상태/경로별 결과, 권한 범위·PII 최소화, 원본 변경 시 stale 및 사용자 확정 보존 여부. 읽기만 하고 운영 DB 변경 금지.

### P2 — COST V3 전역 실사용 갭 및 운영 배포 경계 (오해 방지)

**상태: COST `main` 코드 배포 COMPLETE / 호스트 health·ready COMPLETE / 참가자 API 인증 연결 BLOCKED.** 2026-10-23 승인된 운영 요청에 따라 `C:\AX\cost`의 `main=15cdccc5536bd3b4b6af97e595a12af49fcb8456`에서 보호 백업·별도 복원 검증 뒤 호스트 작업을 재시작했다. `/healthz`와 `/readyz`가 정상 응답했다. 구형 운영 브랜치는 V3 코드와 검사를 대량 삭제하므로 통합하지 않았다. 직접 재시작 스크립트가 예약 작업 인자 검사에서 실패했지만, wrapper가 예약 작업을 다시 시작했고 호스트 응답을 확인했다. 안전 검사를 우회하지 않았다. 실제 COST↔Reservation 인증 요청은 401이므로 후보 조회와 화면 연결의 운영 종단 동작은 확인되지 않았다. 운영 데이터와 Google에는 쓰지 않았다.

**보호할 실제 사용자 수용 기준:** 유효한 카드의 OTA 날짜/매칭 미확정→존재하는 실제 여행으로 추론 귀속→COST 내부 비용 준비→Google B:H 수동 복사 F 예약번호 공란; 중복·환불·원본 충돌은 비용 생성 금지; 2:2 그룹은 개별 예약 결제 동일시 금지/2:3 보류; 수동 여행 A→B 영구 우선; 승인 없는 AI 규칙 미적용; 참가자 한/영 후보는 사용자가 확인해야만 COST 연결, 원본 갱신 stale; 운영 Google 자동 쓰기 0. 필요한 실제 운영 시연에는 계정/운영 데이터 권한과 비파괴 범위를 먼저 확인한다.

**참고:** Google 정본 기반 전체 향후 제품 구상에는 별도 미확정 의사결정/선택 기능이 [목표 업무 명세](target-workflow-google-authority.md)에 있다. 이것을 'V3에서 이미 구현됐음'으로 표시하거나 새 승인 없이 자동 개발 큐에 넣지 않는다.

### P3 — 일부러 유지한 R6 복구 경로 (무작정 미완료 아님)

최신 중앙 정본이 존재하면 legacy가 결정을 덮지 못하고, stale/old snapshot 복구에는 fallback이 필요하므로 **남겨두는 것이 안전한 설계**다. 호출 그래프에 결정 권한을 우회하는 신규 실사용 경로가 확인되면 수정. 미사용 코드를 없애기 위해 기존 안전 경로를 제거하지 않는다.

### 별도 운영 문제 (본 V3 코드 재구현 작업과 구분)

[operations.md](operations.md) 및 [지출 정리 기록](cleanup-resolution-20261023.md)에는 과거 운영에서 근거 확인 대상 161건(항목 3, 여행 근거 125, 보호 33), 인증 대기 Trip.com 예약, 실제 장부 자동 기장 결과가 기록돼 있다. 이 수치는 **그 날짜의 운영 스냅샷**이며 V3 Git main 테스트와 다르다. 운영 후처리에서 오류를 반환한 **5건 자동 기장 스크립트는 실제 5건 기록에 성공했으므로 재실행 금지**. 자세한 복구 증거는 문서 내 로컬 경로를 참고하되 로컬 파일이 없으면 임의로 재생성·재기장하지 않는다. 인증코드·고객원본·취소 결제 근거는 외부로 전달하지 않는다.

## 4. 고정된 안전·업무 계약 (명세 전체를 읽지 않고도 보존)

- **실제 금융 원행이 비용의 원천**이다. OTA 예약만으로 카드 비용을 생성하거나 같은 카드 원행을 두 번 기록하지 않는다. 원본 충돌·중복·환불·취소 보호 우선.
- **여행은 Google 탭 기반 권위 있는 기존 여행만 사용**, 새 여행을 추론으로 생성하지 않는다. 신뢰 낮아도 유효 카드+후보 여행이면 AUTO_INFERRED 우선 귀속; 근거/불확실성 노출. 같은 조건 동률이면 검증된 수입-비용 차액 규칙. 사용자 고정 여행은 재분류·AI보다 상위.
- OTA 사용기간이 카드 승인일/OTA 결제일보다 우선인 조건을 지키고, 원문에 없는 예약번호·결제일·서비스 기간은 추정 확정하지 않는다.
- 카드 2실결제↔OTA 2실결제의 그룹 총량 일치는 개별 카드↔예약 ID 일치 증거가 아니다. 2:3은 개별 연결 미확정. 카드비용은 실거래당 1회.
- 항공권 영문 이름은 한글 예약자 후보를 보여 주되 자동 신원 병합, 고객 신설, 보험 입력, 실탑승 확정 금지. 개인정보 최소화, 비밀정보·고객 원본 외부 모델 전송 금지.
- **Google 최종 장부에 COST 자동 쓰기 금지.** COST 내부 기록/미리보기/복사가 Google 반영 완료라는 뜻이 아니다.
- 실제 운영 DB/고객정보 무단 변경 금지. 원본·사용자 확정·기존 수동 연결·기장 내역 보존. Git force-push 금지. 실제 운영 배포·새 유료 호출·공개는 별도 승인 범위를 따른다.
- COST와 Reservation의 기존 로컬 사용자 미커밋 변경을 보존. Reservation은 민감한 PII 저장소이며 자동 stage/add-all 및 무검토 push 금지.

## 5. 세션/로컬 도구 인계 (GitHub에 없는 상태를 허위 재생하지 말 것)

과거 개발 PC에 Paseo + Codex Stop hook이 연결됐다. hook은 로컬 TASK_QUEUE.json이 승인한 미완료 항목이 있을 때 한 턴 안에서 다음 작업을 선택하도록 시험됐고, 관련 합성 A→B→C 및 31개 검사가 통과했다고 보고됐다. **이 설정·큐·로그는 GitHub 정본이 아니다.** 새 PC/새 에이전트에서 자동으로 존재한다고 가정하지 않는다. 실제 로딩 여부를 확인하고, 없는 경우 **이 문서의 P0~P3를 공개 가능한 작업 큐로 재구성**하여 도구에 맞게 실행한다.

- 로컬 설정 참고 경로(해당 PC에 존재할 때만): C:\AX\agent-policy\local-backups\cost-continuation-20261023, COST 로컬 stop-gate.json/TASK_QUEUE.json, 미추적 .claude/stop-gate/.
- 이전 10분 반복 태스크 ID 5e75876d는 종료 단계에서 삭제 성공을 보고했다. schedule 조회는 'Schedule not found'를 반환했으므로 삭제 전후의 실행 로그와 상태를 새 환경에서 재확인한다. **재등록 금지**, 업무가 완료됐는데 스케줄이 다시 실행되면 공식 인터페이스에서 소유 관계를 확인하고 중지. Codex hook과 이벤트 기반 재개/Heartbeat를 중복 설치하지 않는다.
- GitHub 문서가 현재 작업의 재개 근거이므로 **이 채팅·로컬 파일·별도 기억 없이** 다음 에이전트가 P0/P1부터 시작할 수 있어야 한다. 비밀 토큰, 인증코드, 사용자 DB, 실제 개인정보는 GitHub에 기록하지 않는다.

## 6. 새 세션에서 바로 수행할 검증·작업 예시

시작 단계:
- COST와 reservation 각각의 원격 main, 작업트리, 배포된 Vercel Production commit, GitHub Actions 병합 커밋 결과 조회.
- **P0 완료:** Actions 39939654895 unit/smoke 모두 SUCCESS, PR #23 main 70b00859, Production READY. 새 실패 근거 없으면 재실행하지 않는다.
- **P1 설정·배포·무인증 경계 확인 완료 / 실연동 확인 대기:** Reservation Production의 두 `TURSO_READONLY_*` Secret 저장, `70b00859` 설정 적용 재배포, PR #24 수정이 포함된 `c315c17` 배포가 완료됐다. `a=ro`와 만료 `2026-12-22T11:01:37Z`를 확인했다. 무인증 API 요청은 401이고 오류 응답도 `no-store, private`다. COST의 별도 내부 API 주소·토큰이 Reservation의 `INTERNAL_API_TOKEN`과 맞는지, 인증 읽기·source revision·stale 재확정은 검증하지 않았다. 기존 DB 토큰과 COST의 `RESERVATION_INTERNAL_API_TOKEN`은 서로 다른 자격증명이다. 운영 DB 쓰기 시험은 하지 않는다.
- 사용자 인증이 필요한 마지막 P1 단계만 차단하고 그 외 승인 구현을 수행. 결과를 이 인계 문서의 날짜·HEAD·테스트·실행 증거로 갱신.

표적 검사 예시 (로컬 의존성 설치와 실제 환경을 확인한 후):
- COST: python -m pytest webapp/tests/test_passenger_cross_repo_integration.py -q
- COST: python -m pytest webapp/tests/test_card_flow.py -q  (**과거 67개 통과 근거가 이번 변경에 의해 무효화됐을 때만**)
- Reservation: 실제 package.json의 test 실행기를 확인한 뒤 tests/passengerCandidateRoute.test.ts, tests/passengerCandidateSnapshot.test.ts 및 실패한 tests/masterDataQueue.test.ts만 실행.
- 문서만 고치면 diff·링크·표현 정합성만 확인하며 운영 서버 재시작·DB 조회·전체 테스트를 관성적으로 실행하지 않는다.

### 보고 계약

**구현 상태 / Git 반영 / CI / Preview / Production 배포 / 실제 운영 API 인증 / 실제 PII 보호 검증**을 분리해 보고한다. COMPLETE/FAILED/BLOCKED의 근거 URL·커밋·테스트를 남기고, 미완료를 성공으로 바꾸지 않는다. 한 단위 구현 후 다음 승인 항목으로 이동하되 실제 외부 자격증명이 필요한 단계에서는 사용자가 비밀 저장소에 입력할 정확한 항목만 요청한다.

> **인계 게시 변경 범위:** 이 문서 신설, COST docs/COST_V3_START_HERE.md · docs/session_handoff.md · AGENTS.md 진입점 교정, Reservation AGENTS.md에 COST 조건부 참조. **앱 소스/DB/비밀키/운영 토큰 내용은 수정하지 않음.** Reservation 문서 커밋 dd734e0은 Vercel 자동 Production 배포를 시작해 최종 READY로 확인됐다. 다음 세션에서도 최신 배포와 실제 API 인증 여부는 다시 조회한다.

## 7. 이 문서의 생명주기

- 사용자 승인 명세의 원칙은 [COST V3 진입점](COST_V3_START_HERE.md)과 두 세부 명세가 권위이며, **이 문서는 작업 진행 상태와 검증·재개 순서의 권위**다.
- 새 기능이 끝나면 이 문서의 P0~P3와 증거를 업데이트하고 완료 항목을 '재구현 금지'로 표시. 과거 전문과 운영 이력을 삭제하거나 숫자를 현재값처럼 재해석하지 않는다.
- 새 세션에서 이 문서가 오래됐다는 이유로 무조건 R0부터 다시 구현하지 않는다. 현재 Git 증거/테스트/로그로 먼저 비교한다.
