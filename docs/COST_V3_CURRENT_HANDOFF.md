# COST V3 — CURRENT HANDOFF / RESUME FROM GITHUB

> **기준시각:** 2026-10-23 KST. **이 문서는 COST V3 현행 작업 상태 및 다음 실행 큐의 단일 스냅샷이다.**
> 새 채팅·새 PC·다른 모델은 이전 대화를 재요구하지 말고 이 문서, [COST V3 진입점](COST_V3_START_HERE.md), [COST AGENTS](../AGENTS.md), 아래 두 저장소의 최신 원격 상태만으로 재개한다.
> 최신 사용자 승인 정책과 실제 코드·CI·배포 증거가 과거 요약보다 우선한다. 기준시각 이후의 커밋·배포·설정은 반드시 다시 조회한다.

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
| COST 앱 코드 기준 | [6Soo/cost main](https://github.com/6Soo/cost/commits/main) **0bd6e933ab** 이후 2026-10-23 인계용 문서 커밋 789ada8, 8cf8c4f, 895280d, ceba4f0 추가 | 앱 기능 변경 기준 SHA와 문서 최신 HEAD를 구분한다. **최신 HEAD는 시작 시 git fetch로 확인.** COST V3 전체가 운영 호스트에 배포됐다는 뜻이 아니다 |
| Reservation 앱 코드 기준 | [6Soo/reservation main](https://github.com/6Soo/reservation/commits/main) **cc4e325b9a**; 현 인계 연결만 추가한 문서 커밋 **dd734e0** 후속 | [PR #22](https://github.com/6Soo/reservation/pull/22) 2026-10-23 병합 완료. 새 문서 커밋은 별도 Vercel 빌드를 일으키므로 현재 상태를 다시 확인 |
| Reservation Vercel | [앱 코드 배포 dpl_2codsKnAfoYRM4cnLYquvkHnggDV](https://vercel.com/6soos-projects/reservation/2codsKnAfoYRM4cnLYquvkHnggDV) — target=production, state=READY, sha=cc4e325b9a. **문서-only dd734e0은 별도 production 자동 빌드가 시작돼 확인 당시 BUILDING** ([후속 배포](https://vercel.com/6soos-projects/reservation/Fovk7TKMasxHte5iQaAFGXKDMmah)) | 사용자가 기존 병합·배포를 지시했다. 인계 링크만 포함된 문서 수정도 자동 배포를 트리거했다. 다음 세션에서 최신 배포 결과 확인. API 인증·운영 DB 연결 성공은 미검증 |
| Reservation Actions | [main 병합 커밋 workflow](https://github.com/6Soo/reservation/actions/runs/39936103139): **smoke success / unit failure** | CI 전체 녹색 아님. unit의 정확한 실패 원인은 이 문서 작성 시 로그 전문으로 독립 확정하지 않음 |
| COST 배포 | [기존 운영 이력](operations.md)에 관리 호스트 배포·기장 기록 존재 | 운영 릴리스 SHA는 V3 Git main과 별개. V3 전체의 실제 운영 프로세스 SHA·기능 상태는 미검증 |
| 로컬 작업 공간 | 에이전트 보고상 COST 미추적 .claude/stop-gate/, reservation 사용자 미커밋 변경 보존 | GitHub에서 로컬 상태를 확인할 수 없음. 새 실행 시 로컬에서 재확인 필수 |

**수치 주의:** 과거 에이전트의 “94%”는 **17개 자체 정의 체크 중 16개 확인**이라는 추정 지표이며 독립적인 명세 전체 완료율·운영 준비율이 아니다. 저장소 구현·합성 종단 검증은 상당 부분 완료됐으나 실제 운영 기능 검증과 별도로 취급한다. 새 에이전트가 임의로 백분율을 다시 만들지 않는다.

### 실제 배포와 기능 동작의 구분

- PR #22의 Reservation **Production 배포는 READY**다. 과거 session_handoff의 “10/21 마지막 Production” 기록은 작성 당시 관측이며 지금의 최신 상태가 아니다.
- 운영 환경에 INTERNAL_API_TOKEN, TURSO_READONLY_AUTH_TOKEN, COST 쪽 RESERVATION_INTERNAL_BASE_URL과 내부 API 토큰 등이 올바르게 존재하는지는 **검증되지 않았다**. 배포 성공을 API 조회 성공으로 보고하지 않는다.
- GitHub Actions **unit이 실패**했다. 이전 에이전트는 tests/masterDataQueue.test.ts가 17개 중 1개 실패(기대 3/실제 2)하며 기준 main에서도 재현된다고 보고했지만, 현 병합 커밋의 unit 실패 원인과 동일한지는 **CI 로그로 다시 확인**한다.
- 실제 예약 참가자의 이름·신원·여행 데이터를 운영 조회하거나 외부 AI에 제공하지 않았다. 사용자 선택은 COST 내부 연결이며 **실제 탑승 확정/보험 명단 변경**이 아니다.

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

### P0 — 병합 커밋 GitHub Actions unit 실패 (실행 가능)

**상태: FAILED/원인 독립 미확정.** Reservation cc4e325의 workflow 39936103139에서 smoke=PASS, unit=FAIL. CI job 실패 로그를 조회하고 정확한 테스트/단계를 확정. 기존 에이전트가 지적한 masterDataQueue의 기대값 3/실제 2와 동일한 문제인지 검증. 영향 없는 기준선 실패라면 base와 head 양쪽 같은 명령/실패를 증거로 기록하고, 별도 명세에 어긋나는 실제 버그라면 원인·회귀 범위부터 고친다. 테스트 기대값만 임의로 2로 바꿔 녹색으로 만들지 않는다. 합당한 소규모 코드 수정은 Reservation AGENTS의 PII 스테이징 확인 후 커밋·Git 반영. 새 운영 배포가 수반되는 경우 범위를 확인하고 기존 사용자 승인 범위를 임의 확장하지 않는다.

**완료 증거:** 실패 원인, 기준선 여부, 변경 diff 또는 분리 판정, 해당 CI/표적 검증 링크. 'Preview READY'만으로 CI unit 실패를 무시하지 않는다.

### P1 — R5-B 실서비스 읽기 연동 안전성 검증 (실제 운영 설정 권한은 별도)

**상태: 코드 구현 COMPLETE / 운영 설정·실조회 UNVERIFIED.**

1. Vercel reservation의 Production cc4e325 READY 여부와 대상 도메인/환경을 재확인. 운영 환경변수의 **존재 여부만** 권한이 허용하면 점검하고 값은 출력·복사·로그하지 않는다.
2. Reservation의 내부 API: /api/internal/passenger-candidates?tourFldid=... ; 보호 Bearer 인증. 서버측 읽기 전용 전용 DB 클라이언트가 기존 getDb() schema 초기화·PII 마이그레이션을 사용하지 않는 구조임을 유지.
3. 필요한 설정 **Reservation**: INTERNAL_API_TOKEN(기존 내부 소비자 영향 검토), TURSO_READONLY_AUTH_TOKEN(해당 단일 DB read-only scope 필수), 선택 TURSO_READONLY_DATABASE_URL. **COST**: RESERVATION_INTERNAL_BASE_URL, RESERVATION_INTERNAL_API_TOKEN 또는 보호된 토큰 파일 경로(정확한 변수 이름은 webapp/reservation-passenger.env.example에서 재확인).
4. 변수 이름에 READONLY라고 적힌 것만으로 DB 권한을 증명하지 않는다. 운영 DB에 INSERT/CREATE를 시험하지 않는다. 격리 비운영 DB의 동일 권한 정책으로 조회 허용·쓰기 거부를 확인하거나 제공자 권한 표시를 검증한다.
5. 운영에서 사용자 승인 범위 내 **비파괴 읽기/비식별 결과 검증**: 비인가 요청 차단(401), 누락된 설정 실패 폐쇄(503), 승인된 범위의 tour 한 건에 한정된 최소 데이터, source_revision, 고객 ID/RRN/전화/여권 비노출, COST 후보 화면→사용자 확인→내부 저장/재조회→원본 변경 stale. 실제 고객명·토큰을 문서·채팅·CI artifact에 남기지 않는다.
6. 운영 비밀설정/인증 접근권이 없으면 **이 운영 단계만 BLOCKED**. 코드·테스트/CI 문제는 독립 진행. 실제 credentials를 요청하거나 채팅으로 붙여넣게 하지 않는다. 사용자가 Vercel 및 COST의 비밀 저장소에 직접 설정하도록 정확한 변수명과 권한 절차만 안내한다.

**완료 증거:** 실제 접근 대상 서비스 SHA/환경, 비밀값 없는 HTTP 상태/경로별 결과, 권한 범위·PII 최소화, 원본 변경 시 stale 및 사용자 확정 보존 여부. 읽기만 하고 운영 DB 변경 금지.

### P2 — COST V3 전역 실사용 갭 및 운영 배포 경계 (오해 방지)

**상태: 저장소 구현은 주요 기능 완료 / 실제 COST V3 운영 릴리스는 미확인.** 코드와 V3 핵심 사용자 수용 기준을 대조하여 **새로 확인된 필수 결함**만 수정한다. 운영 호스트 배포가 사용자의 명시 승인 범위인지 먼저 구분한다. Git main SHA만으로 운영 반영 완료라고 주장하지 않는다.

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
- Reservation Actions run 39936103139 unit 실패 세부 파악. tests/masterDataQueue.test.ts 기준선 차이 검증. 실제 버그라면 최소 수정+회귀 검사 및 적법한 Git 반영.
- Reservation 참가자 API를 실제 DB가 아니라 기존 합성 E2E/표적 테스트로 재확인하고, Production의 API가 인증/읽기권한/비밀설정 때문에 아직 막혔는지 **비밀값 없는 방식**으로 파악.
- 사용자 인증이 필요한 마지막 P1 단계만 차단하고 그 외 승인 구현을 수행. 결과를 이 인계 문서의 날짜·HEAD·테스트·실행 증거로 갱신.

표적 검사 예시 (로컬 의존성 설치와 실제 환경을 확인한 후):
- COST: python -m pytest webapp/tests/test_passenger_cross_repo_integration.py -q
- COST: python -m pytest webapp/tests/test_card_flow.py -q  (**과거 67개 통과 근거가 이번 변경에 의해 무효화됐을 때만**)
- Reservation: 실제 package.json의 test 실행기를 확인한 뒤 tests/passengerCandidateRoute.test.ts, tests/passengerCandidateSnapshot.test.ts 및 실패한 tests/masterDataQueue.test.ts만 실행.
- 문서만 고치면 diff·링크·표현 정합성만 확인하며 운영 서버 재시작·DB 조회·전체 테스트를 관성적으로 실행하지 않는다.

### 보고 계약

**구현 상태 / Git 반영 / CI / Preview / Production 배포 / 실제 운영 API 인증 / 실제 PII 보호 검증**을 분리해 보고한다. COMPLETE/FAILED/BLOCKED의 근거 URL·커밋·테스트를 남기고, 미완료를 성공으로 바꾸지 않는다. 한 단위 구현 후 다음 승인 항목으로 이동하되 실제 외부 자격증명이 필요한 단계에서는 사용자가 비밀 저장소에 입력할 정확한 항목만 요청한다.

> **인계 게시 변경 범위:** 이 문서 신설, COST docs/COST_V3_START_HERE.md · docs/session_handoff.md · AGENTS.md 진입점 교정, Reservation AGENTS.md에 COST 조건부 참조. **앱 소스/DB/비밀키/운영 토큰 내용은 수정하지 않음.** Reservation 문서 커밋 dd734e0이 Vercel 자동 Production 빌드를 시작했으므로 최신 배포 성공 여부를 재확인해야 한다.

## 7. 이 문서의 생명주기

- 사용자 승인 명세의 원칙은 [COST V3 진입점](COST_V3_START_HERE.md)과 두 세부 명세가 권위이며, **이 문서는 작업 진행 상태와 검증·재개 순서의 권위**다.
- 새 기능이 끝나면 이 문서의 P0~P3와 증거를 업데이트하고 완료 항목을 '재구현 금지'로 표시. 과거 전문과 운영 이력을 삭제하거나 숫자를 현재값처럼 재해석하지 않는다.
- 새 세션에서 이 문서가 오래됐다는 이유로 무조건 R0부터 다시 구현하지 않는다. 현재 Git 증거/테스트/로그로 먼저 비교한다.
