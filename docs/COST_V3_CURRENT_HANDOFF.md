# COST V3 — CURRENT HANDOFF / RESUME FROM GITHUB

> **개발 상태 갱신:** 2026-10-24 KST, 아래 0.8절. 운영 기록은 각 검증 당시의 증거이며 이번 개발 후보가 운영에 적용됐다는 뜻이 아니다. **이 문서는 COST V3 현행 작업 상태 및 다음 실행 큐의 단일 스냅샷이다.**
> 새 채팅·새 PC·다른 모델은 이전 대화를 재요구하지 말고 이 문서, [COST V3 진입점](COST_V3_START_HERE.md), [COST AGENTS](../AGENTS.md), 아래 두 저장소의 최신 원격 상태만으로 재개한다.
> 최신 사용자 승인 정책과 실제 코드·CI·배포 증거가 과거 요약보다 우선한다. 기준시각 이후의 커밋·배포·설정은 반드시 다시 조회한다.

## 0.8 2026-10-24 개발 후보 인수와 후속 구현

현재 개발 후보는 [COST 초안 PR #91](https://github.com/6Soo/cost/pull/91)의 `integration/cost-v3-spec-completion` 브랜치다. 원격 main 기준은 `fe340481ed5783d23f678d6a3df542ae8e6ce437`이며 main 병합과 운영 배포는 이번 범위에 포함하지 않는다. 구현자는 사용자 최신 지시에 따라 GPT-6 Luna low로 전환했다. 이전 ANUS 무료 제공자는 실제 일일 한도 429로 중단됐으며 재시도하지 않았다.

| 작업 | 개발 상태와 실제 근거 |
| --- | --- |
| 원 세션 및 완료 하위 작업 인수 | 완료. COST [PR #88](https://github.com/6Soo/cost/pull/88) `9968963`, [#89](https://github.com/6Soo/cost/pull/89) `dbc23e4`, [#90](https://github.com/6Soo/cost/pull/90) `66ddf95`를 보존했다. 별도 [Travel INS PR #5](https://github.com/6Soo/travel_ins/pull/5) `d8d2639`와 기존 합성 17 passed도 인수했다. 모두 확인 당시 open이며 자동 병합하지 않았다. |
| T1a 통합 | `f86690b`. Toyoko 후보와 L1 상태·설명 helper의 충돌을 수동 통합했다. Toyoko 2·우선배정 3·관련 메일/예약 28·사용자 규칙 7 passed를 인수했다. 금융 solver·원장·snapshot·store 경계는 그대로이며 읽기 검토의 중대 지적은 없었다. |
| T1b L2 | `48e4c73`, `e443a25`, `d6401fc`. 이미 판정된 후보 선택을 순수 규칙 집계 helper로 분리했다. 실제 BASE 메서드 frozen fixture와 현재 wrapper의 출력·nets 호출·여행 유효성 호출·입력 불변성을 단일 nodeid에서 비교해 1 passed. 마지막 유효성 재확인과 None snapshot을 포함한다. 읽기 검토 잔여 지적 0. |
| T2 L3 | `f14b65e`. 두 자동 기록 호출을 유지하고 목적 주석만 추가했다. 실제 dispatch와 임시 SQLite의 표적 nodeid 1 passed. 첫 기록 1·후속 0 및 합성 hold 해제 첫 0·후속 1, 재업로드 멱등과 수동 이동 보존을 확인했다. 실제 모든 OTA 상태의 불필요성은 증명하지 못했으며 합성 hold 전환을 실제 OTA 정책 검증으로 보고하지 않는다. 별도 환불 fixture는 dispatch 환불 검사와 구분한다. |
| T3 항공권 G1~G4 | `fe97a1e`, `6591084`, `4901f06`, `3ac0ae2`. 권위 후보 이름의 공백·제한 역순 비교, 원본 내용 digest와 proposal 결속, 오래된 연결 보존·재확인, 정확한 승객 proposal별 연결, 취소·여정 충돌 확정 차단을 보완했다. 후속 영향 검사 10 passed, 예약 단위 경고 보완 2 passed, 조건부 취소 문장 보완 1 passed. 합성 Aside에서 저장→원본 변경→재확인→승객 없는 취소의 이력 보존을 확인했고 취소 경고만 추가 확인했다. |
| T4 지연 여행 이동 G5 | `4252690`. 저장된 요청의 transaction ID·originating revision과 현재 수동 결정·대상을 기존 공유 RLock 안에서 확인한다. 늦은 B 후처리와 학습은 superseded로 반환해 최신 C를 되돌리지 않는다. B→C→B에서도 옛 요청은 거부하며 최신 요청 재시도는 유지한다. 새 경합·기존 정상 API 이동·AI 초기화 실패의 표적 검사 3 passed. 독립 읽기 검토 잔여 지적 0. |

이 표의 코드와 검사는 개발 브랜치의 근거다. 운영 DB·실제 고객·Google·서비스 재시작·배포·운영 인증 재시험은 수행하지 않았다. 과거 정상 인증 404와 기존 CI·운영 증거는 그대로 재사용한다. 전체 디렉터리 검사를 시도한 이전 작업자는 중단했으며 잘린 출력은 전체 통과 근거로 인정하지 않는다.

이번 승인 개발 큐 T1~T4는 완료했다. 항공권은 `46e9977`에 충돌 없이 통합했다. merge 결과의 항공권 6개 파일은 검토받은 flight HEAD와 같고 CardFlow는 검토받은 통합 부모와 같다. 금융 solver·원장·분류·사용자 결정 저장·snapshot·store·Google 복사 파일은 f86690b와 바이트가 같아 기존 유효 검사를 반복하지 않았다. 최종 문서 커밋과 원격 HEAD는 PR #91에서 확인한다. 완료된 R0~R6와 기존 PR 작업을 재구현하지 않는다. L4 중앙 solver 추가 분해·legacy fallback 삭제·운영 cutover는 A 정책 16.9절의 별도 범위로 남긴다. 운영 실고객 참가자 조회는 별도 개인정보 접근 승인 전 수행하지 않는다. 전용 토큰 종류의 UNKNOWN은 정상 인증을 반복 검사할 이유가 아니다.

로컬 main의 미커밋 항공권 파일과 미추적 stop-gate 자료는 사용자 변경으로 보존했다. 새 세션은 위 브랜치와 PR의 실제 HEAD·상태를 확인하고 이 문서에서 미완료인 항목만 이어간다. 로컬 보고서나 과거 채팅이 없어도 원격 커밋·테스트 파일·PR로 재개할 수 있다.

## 0.1 2026-10-23 실행 갱신 (당시 기록 — 이후 검증은 0.3~0.5 참조)

- COST `main`과 `origin/main`은 `15cdccc5536bd3b4b6af97e595a12af49fcb8456`으로 같았다. 작업 트리의 기존 미추적 `.claude/stop-gate/`는 보존했다.
- 운영 코드 체크아웃 `C:\AX\cost`에서 보호 백업·별도 복원 검증을 실행했다. 데이터베이스 5개와 파일 59개의 비교, 원본 상태 불변, 복원 연결 일치를 확인했다. 실제 요청 재실행, 운영 자료 가져오기, 비밀 파일 복사는 하지 않았다.
- 호스트 작업 재시작 후 `127.0.0.1:8751/healthz`와 `/readyz`가 모두 정상 응답했다. 현재 코드는 승인된 `main` 체크아웃에서 제공된다. 자동화된 직접 재시작 스크립트는 예약 작업 인자 형식 검사에서 `SUPERVISOR_IDENTITY_UNVERIFIED`로 종료했지만, 보호 절차가 예약 작업을 다시 시작했고 서비스 정상 응답을 확인했다. 해당 검사 우회는 하지 않았다.
- 최신 `main`의 읽기 전용 런타임 검증은 `LIGHTWEIGHT_RUNTIME_VERIFIED`로 통과했다. DB 무결성 `ok`, 인증 없는 `/healthz`·`/readyz`는 200, `/import`·`/api/imports`는 401이었다. 여행 62개 중 20개는 검증됐고 42개는 일정 권위 확인 대기다. 원본 6,395건과 장부 행 2,564건은 조회만 했다. 근거 파일은 로컬 `.local-archive/lightweight-20261003/runtime-verification.json`에 있으며, 해당 파일은 Git에 추가하지 않는다.
- 참가자 API에 COST의 기존 보호 토큰 파일을 사용해 합성 식별자 한 건만 읽기 요청했다. 응답은 `401 Unauthorized`였고 후보 자료는 반환되지 않았다. 이 파일은 Reservation의 현재 `INTERNAL_API_TOKEN`과 일치하지 않거나 더 이상 유효하지 않다. 토큰 값은 읽거나 출력하지 않았고 교체·발급도 하지 않았다. 따라서 COST↔Reservation 인증 읽기와 화면의 실제 원본 연결은 여전히 차단 상태다.
- 오래된 `deploy/ota-unified-20261021`은 최신 `main`과 통합하면 V3 코드·검사를 포함한 107개 경로에서 약 11,700줄을 삭제한다. 이 브랜치 병합은 중단했고 `main`에는 해당 삭제를 반영하지 않았다.
- **당시 다음 작업(현재 폐기됨):** 보호 토큰과 내부 API의 인증 불일치를 조사해야 했다. 이후 0.3의 합성 404로 인증 통과가 확인됐다. **현재 인증 재시험·무조건 토큰 교체 금지.**

## 0.2 2026-10-23 추가 확인 — 참가자 전용 내부 토큰 인증 불일치 수정

- 기존 Reservation `src/lib/internalAuth.ts`는 `INTERNAL_API_TOKEN` 및 `COST_INTERNAL_API_TOKEN`을 모두 허용했으나 참가자 후보 라우트만 `INTERNAL_API_TOKEN`을 단독 비교하고 있었다. 이 불일치는 COST 호스트 파일에 정당한 COST 전용 토큰이 있어도 401을 만드는 **가능한 원인**이다. 호스트 실제 토큰 내용을 보지 않았으므로 유일한 실제 원인으로 확정하지 않는다.
- [Reservation PR #25](https://github.com/6Soo/reservation/pull/25) → `main` **3296255e07e0c654c41b48e347095c2aedd8443e**: 참가자 라우트가 공용 상수시간 내부 토큰 검증을 사용하도록 정렬. 무인증·미설정 fail-closed, DB 조회 전 401, `no-store, private`, auth 토큰 종류와 관계없이 동일한 후보 HMAC revision 유지. 바뀐 파일은 `src/lib/internalAuth.ts`, `src/lib/passengerCandidateRoute.ts`, `tests/passengerCandidateRoute.test.ts` 3개만.
- [Preview dpl_GVUxx8AKW5xoxxeK6nJsn6wydn2K](https://vercel.com/6soos-projects/reservation/GVUxx8AKW5xoxxeK6nJsn6wydn2K) READY, [main Actions run 39953733785](https://github.com/6Soo/reservation/actions/runs/39953733785) **unit 270/270 PASS, smoke PASS**, [Production dpl_DQGvxo765hwryWWURP2XFVDdXkkm](https://vercel.com/6soos-projects/reservation/DQGvxo765hwryWWURP2XFVDdXkkm) **READY**. 이 결과는 인증 로직/배포 검증이며 실제 운영 호스트의 인증 성공·실고객 읽기 성공 증거는 아니다.
- COST `webapp/reservation-passenger.env.example`을 `13705183` 문서 커밋으로 갱신: 호스트의 `RESERVATION_INTERNAL_API_TOKEN` 또는 보호된 파일은 **Reservation의 `COST_INTERNAL_API_TOKEN`(권장 COST 전용) 또는 기존 `INTERNAL_API_TOKEN`과 동일해야 한다**. `TURSO_READONLY_AUTH_TOKEN`은 Reservation DB에만 사용하며 호스트 내부 HTTP 토큰으로 사용 금지.
- **당시 P1 재개 지침(이후 0.3/0.4/0.5가 우선):** 보호된 COST 토큰과 Reservation 내부 토큰 중 무엇이 일치하는지 구별되지 않았다. 합성 404 인증 성공과 합성 브라우저 검증 이후에는 전용 토큰 일치 여부만 별도 확인하며, 인증 재시험이나 변경은 관성적으로 하지 않는다.

## 0.3 2026-10-23 후속 실행 — 합성 인증 요청 및 호스트 상태

- COST `origin/main`과 작업 디렉터리를 `1a094bbfec1ee06fcfe011969893e38836fee182`로 맞췄다. 직전 COST 커밋에서 `origin/main`까지는 handoff·진입점·환경 예시 문서만 포함한 3개 fast-forward 커밋이었으며, 앱 코드는 바뀌지 않았다. 기존 미추적 `.claude/stop-gate/`는 보존했다.
- Reservation `origin/main`은 `3296255e07e0c654c41b48e347095c2aedd8443e`로 원격 조회했고, 로컬 작업 디렉터리는 `da6a1e82...`의 별도 브랜치에서 사용자 수정 파일을 그대로 보존했다. 해당 디렉터리를 전환·수정하지 않았다.
- COST Windows 작업 `WebLedger-Board`는 `Running`이며 실행 인자는 승인된 `C:\AX\cost` 체크아웃을 가리킨다. 현재 `/healthz`와 `/readyz` 모두 200이다.
- `app/reservation_authority.py`의 토큰 순서는 환경변수 `RESERVATION_INTERNAL_API_TOKEN` → 환경변수 파일 경로 `RESERVATION_INTERNAL_API_TOKEN_FILE` → 호출자가 넘긴 보호 기본 파일이다. 현재 검증 프로세스와 사용자/시스템 환경에는 첫 번째 변수가 설정되지 않았고, 작업 정의에도 해당 변수를 인자로 지정하지 않았다. 보호 파일 경로에서만 인증값을 읽어 검증했으며 실제 실행 프로세스의 환경 메모리를 직접 덤프하지 않았다.
- 보호 파일 토큰으로 `https://reserve.foresttour.kr/api/internal/passenger-candidates`에 합성 여행 ID GET **1회**를 보냈고 응답은 **404**였다. 이는 PR #25의 Production 코드에서 인증을 통과했고 합성 여행이 없음을 뜻한다. 401이 아니므로 기존 보호 파일 값은 Reservation이 허용하는 두 내부 토큰 중 하나와 일치한다. Vercel 비밀값은 조회하지 않아 `COST_INTERNAL_API_TOKEN`과 `INTERNAL_API_TOKEN` 중 어느 이름의 값과 일치하는지는 구분하지 않았다. 인증 성공이 확인되어 별도 비밀값 변경은 하지 않았다.
- Reservation `3296255e`의 실제 코드 계약을 읽기 전용으로 검토했다. 응답은 `tour_id`, HMAC `source_revision`, 후보의 `kind`, 불투명 `reference_id`, 한글/영문 이름, 상태로 제한되며 고객 식별번호·연락처·결제/예약 원문은 응답에 없다. 저장된 이름 및 동반자 필드는 서버 내부에서만 복호화해 후보 최소 필드로 만든다. 응답은 `no-store, private`, `Pragma: no-cache`, `Vary: Authorization`을 지정하고 취소·삭제 상태를 제외한다. 인증 전에는 DB를 조회하지 않으며 데이터 접근/복호화 오류는 503으로 닫힌다.
- COST 표적 검사는 `python -m pytest webapp/tests/test_passenger_cross_repo_integration.py webapp/tests/test_flight_passenger_page.py -q`에서 **6 passed, 1 skipped**였다. 화면·저장·재조회·stale 재확정 단위 경계는 통과했다. 교차 저장소 브라우저 통합 검사는 Reservation 사용자 작업 디렉터리에 테스트 전용 `tests/fixtures/passengerCandidatesHttpFixture.ts`가 없어 skip됐다. 미커밋 Reservation 파일을 건드리지 않았다. 과거 handoff의 교차 저장소 합성 E2E 통과 보고는 이력으로 보존하되 이번 실행에서 재현했다고 간주하지 않는다.
- Reservation Production은 `3296255e`에서 `READY`, GitHub Actions run `39953733785`는 `main` SHA `3296255e`에서 `success`다. 이전에 확인된 같은 run의 unit 270/270 및 smoke 성공을 재사용했다.
- **남은 운영 P1:** 성공한 404는 COST 호스트의 보호 파일 값으로 API 인증이 된 증거이나, 두 Vercel 변수 중 구체적으로 어느 값과 일치하는지나 유효한 실제 여행의 후보 payload를 확인한 증거는 아니다. 개인정보 확인을 위해 실제 참가자 응답을 가져오지 않았다. 실제 고객 후보 데이터·source revision의 운영값과 원본 변경 뒤 stale 재확정은 승인된 비파괴 실데이터 검증이 아직 없다. Google, DB 쓰기, 비밀 변경, 배포는 수행하지 않았다.

## 0.4 2026-10-23 합성 교차 저장소 브라우저 재검증

- 0.3에서 사용한 Reservation 로컬 작업 브랜치에는 테스트 fixture가 없었지만, 원격 `main=3296255e`에는 `tests/fixtures/passengerCandidatesHttpFixture.ts`가 이미 포함돼 있었다. 사용자 변경을 보존하기 위해 main을 별도 격리 worktree로 열고 저장소의 원래 fixture를 수정 없이 사용했다.
- `COST_R5B_RESERVATION_ROOT=C:\AX\reservation-v3-synthetic-329` 설정으로 `python -m pytest webapp/tests/test_passenger_cross_repo_integration.py -q`를 실행해 **1 passed**를 확인했다. 실제 Reservation 핸들러 → HTTP → COST adapter → 브라우저 후보 선택 → COST SQLite 저장과 재조회 → 합성 원본 변경 → stale 표시 → 사용자 재확정 흐름이 통과했다. API 응답에 `source_revision`과 최소 후보 필드가 있고, 저장 결과에서 원본 예약 ID와 주민 식별번호 표본이 제외되는 검사도 통과했다.
- 격리 worktree에서 fixture를 바꿔 실행한 첫 시도는 원본 검증 근거로 쓰지 않았다. fixture를 `3296255e`의 원래 내용으로 복원한 후 성공 결과를 얻었다. 격리 worktree는 검사 후 제거했고 Reservation 사용자 작업 공간은 수정하지 않았다.
- 0.3의 **6 passed, 1 skipped**는 fixture가 없는 로컬 브랜치에서의 최초 기록이다. 원격 main의 공식 합성 fixture로 교차 저장소 브라우저 흐름을 재검증했다. 운영 실제 여행 후보 payload와 실자료 `source_revision`은 읽지 않았다. 따라서 P1 코드/합성 통합 검증은 완료했고, 운영 실자료 검증은 미수행으로 남는다.
## 0.5 2026-10-23 최신 재확인 — 합성 404 인증 성공 재사용·전용 토큰 일치 여부 미확인

- GitHub 원격 HEAD는 COST `678d97a617b19dd9618e2fb4cb40babd9b29f10d`, Reservation `3296255e07e0c654c41b48e347095c2aedd8443e`로 확인했다. Vercel Reservation Production의 **비밀값이 아닌 이름과 대상**만 조회해 `COST_INTERNAL_API_TOKEN`, `INTERNAL_API_TOKEN`, `TURSO_READONLY_AUTH_TOKEN`, `TURSO_READONLY_DATABASE_URL` 설정을 확인했다. 어떠한 secret 원문도 조회·복호화하지 않았다.
- **합성 운영 API의 404는 이미 인증 성공(0.3)을 증명한다.** 이번 검증에서는 호출하지 않았다. 합성 교차 저장소 브라우저 1 passed(0.4)도 재실행하지 않았다. 과거 401은 PR #25 이전 이력이다. 404로는 COST 보호 토큰이 전용 `COST_INTERNAL_API_TOKEN`인지 기존 `INTERNAL_API_TOKEN`인지 구별할 수 없다.
- **보안 운영자의 선택적 관리 점검:** 먼저 실제 실행 서비스의 COST 토큰 소스 우선순위(환경변수 `RESERVATION_INTERNAL_API_TOKEN` → `RESERVATION_INTERNAL_API_TOKEN_FILE` → 보호 기본 파일)를 확인한다. 승인된 비밀 관리 기능에서 두 저장소 값의 메모리 내 동등성만 비교하고, 외부 결과는 `dedicated_match=true/false/unknown`과 점검 시각만 남긴다. Vercel 저장된 Secret 값을 보호된 방식으로 확인할 수 없다면 `unknown`으로 남기고 비교를 강행하지 않는다. 값·해시·복사 파일을 채팅/콘솔/로그/Git/CI에 남기지 않는다.
- **비밀 변경 기본 금지:** 현재 인증은 성공한다. 전용 토큰 일치 여부가 unknown인 것만으로 토큰을 새로 만들거나 Vercel/호스트를 재배포하지 않는다. 불일치가 실제 확인되고 전용화 변경이 별도로 승인되면 기존 소비자를 보호하며 최소 Secret·호스트 설정만 동기화한다. 범용 `INTERNAL_API_TOKEN`은 무단 변경 금지.
- **남은 P1:** 운영 실제 여행 후보 payload, 실제 `source_revision`, 실데이터 원본 변경에 따른 stale 재확정은 개인정보 접근이 수반되므로 별도 승인 전 **UNVERIFIED/BLOCKED**. 운영 DB/Google 쓰기, 실제 고객자료 조회, 추가 합성 인증 요청, 작업 공간 변경 없음.


## 0.6 2026-10-23 최신 상태 — 실행 토큰 출처와 전용 토큰 비교

- COST 원격 `main`은 `d3b106c4654ed96b04db4bd47903488508e228e8`였고 로컬은 문서 변경을 fast-forward해 같은 기준에 맞췄다. 변경 전 COST 작업 공간의 기존 미추적 `.claude/stop-gate/`는 보존했다. Reservation 원격 `main`은 `3296255e07e0c654c41b48e347095c2aedd8443e`이며 기존 로컬 사용자 수정은 그대로 두었다.
- Vercel Reservation Production은 `dpl_DQGvxo765hwryWWURP2XFVDdXkkm`, `READY`, SHA `3296255e`로 재확인했다. 환경변수 메타데이터는 값 복호화 없이 조회했다. 전용 `COST_INTERNAL_API_TOKEN`은 Production 대상, 기존 `INTERNAL_API_TOKEN`은 Preview와 Production 대상이다. GitHub CI, 이전 합성 404, 브라우저 E2E는 요청대로 재실행하지 않았다.
- 실제 COST 작업 `WebLedger-Board`는 `Running`, 사용자 `kkokk`의 대화형 최고 권한으로 `C:\AX\cost\tools\start_web_ledger_host.ps1`를 실행한다. 작업 인자와 시작 스크립트에는 `RESERVATION_INTERNAL_API_TOKEN` 또는 `RESERVATION_INTERNAL_API_TOKEN_FILE` 지정이 없고, 두 변수 모두 현재 Process/User/Machine 환경에서 설정되지 않았다. `app/reservation_authority.py` 우선순위와 보호 파일 경로를 함께 대조하면 현재 구성은 `D:\WebLedgerHost\secrets\reservation-internal-token.txt` 기본 파일을 사용한다. 보호 파일 존재만 확인했으며 내용을 읽거나 복사하지 않았다. 별도 프로세스 환경 메모리를 덤프하지는 않았다.
- **전용 토큰 비교 결과: `UNKNOWN` (2026-10-23).** Vercel 연결에서 secret 복호화를 사용하지 않았고, COST 보호 파일 값과 Reservation `COST_INTERNAL_API_TOKEN`을 비교하는 승인된 양쪽 비밀 저장소의 메모리 비교 수단도 현재 제공되지 않는다. 이전 합성 404는 이 파일의 자격증명이 Reservation이 허용하는 두 변수 중 하나와 맞는다는 증거지만 전용 변수와의 일치 여부는 밝히지 않는다. 인증 장애나 `MISMATCH`로 판정하지 않는다.
- **운영자용 안전 절차:** 권한 있는 관리자가 승인된 비밀 관리 도구에서 두 값을 파일·클립보드·콘솔·로그·Git에 내보내지 않고 메모리에서만 비교한다. 관리 도구가 이 비교를 지원하지 않으면 `UNKNOWN`을 유지한다. 기록할 값은 `MATCH`, `MISMATCH`, `UNKNOWN` 중 하나와 점검 시각뿐이며 토큰·부분 문자열·길이·해시를 기록하지 않는다. `MISMATCH`가 실제 확인돼도 현재 서비스는 인증되므로 무조건 변경하지 않는다. 전용 토큰화가 별도 승인된 경우에만 기존 `INTERNAL_API_TOKEN` 소비자 영향을 검토하고 COST 전용 범위만 최소 변경한다.
- 이번 실행에서는 합성 요청, 운영 참가자 조회, 비밀값 변경, 서비스 재시작, 배포, CI/브라우저 검사를 수행하지 않았다. 이전의 합성 404 및 격리 합성 브라우저 1 passed가 현재 증거로 유지된다.
## 0.7 2026-10-23 종료 판정 정책 — 최신 사용자 지시

- 승인된 실행 가능 작업이 있으면 후속 프롬프트를 만들지 말고 현재 실행에서 직접 수행한다. 완료 보고는 자동 재개 신호가 아니다. 명시적 세션 인계, 새 독립 작업, 사용자 요청이 있을 때만 후속 프롬프트를 작성한다.
- 이미 통과한 검사·배포·인증은 새 결함 증거가 없으면 재실행하지 않는다. 종료 시 COMPLETE, BLOCKED, DEFERRED만 구분한다. `UNKNOWN`은 그 자체로 오류가 아니다.
- 현재 작업 상태: **COMPLETE** — Reservation 인증 코드와 Production 배포, 합성 API 404 인증 성공, 교차 저장소 브라우저 검증, COST 런타임 토큰 출처 확인. 기존의 통과 증거를 재사용하며 다시 호출하지 않는다.
- **DEFERRED** — COST 전용 토큰과 Reservation 전용 토큰의 값 일치 여부는 `UNKNOWN`이다. 실제 인증이 정상이며 현재 승인된 비밀 저장소 간 비노출 비교 수단이 없어 선택 점검으로 보류한다. 토큰·해시·부분 문자열을 만들거나 기록하지 않고, 불일치를 추정하지 않는다.
- **BLOCKED** — 운영 참가자 실자료와 실제 source revision을 조회하는 일은 별도 개인정보 접근 승인이 필요하다. 승인 전에는 조회하지 않는다.
- 로컬 `.claude/TASK_QUEUE.json`의 `R5B-LIVE-AUTH`는 위 완료 증거를 반영해 COMPLETE로 고쳤다. 과거 PR #25 전 401을 현재 차단 사유로 다시 선택하지 않는다. DEFERRED 점검은 실행 큐에 넣지 않는다. 기존 Stop hook과 보호 설정은 유지하며 삭제·우회하지 않는다.
- 실행 가능한 신규 승인 작업이나 결함 근거가 없으면 여기서 종료한다. 같은 차단을 재조사하거나 문서 갱신만을 후속 작업으로 만들지 않는다.
## 0. 새 에이전트용 즉시 실행 계약

**목표:** OTA↔실제 카드 대사, 여행 우선 배정, 사용자 이동·AI 규칙 승인, 한/영 참가자 연결, N:M 그룹, 금융 중복·환불 보호, Google 수동 붙여넣기까지 **승인된 COST V3를 실사용 가능하게 마무리**한다. 코드가 이미 있는 기능을 재작성하지 않고 **남은 미검증 경계와 실제 결함**부터 해결한다. 조사만 하고 끝내지 않는다.

1. **가장 먼저:** 6Soo/cost와 6Soo/reservation의 origin/main, 작업 트리, 열린 PR, GitHub Actions, 실제 Vercel 대상 SHA를 조회한다. 원격 SHA를 고정값으로 믿지 않는다. 로컬 미커밋·미추적·stash, 사용 중인 worktree를 보존한다.
2. **읽기 순서:** 이 문서 → [COST V3 진입점](COST_V3_START_HERE.md) → [OTA A 정책](ota-card-reconciliation-policy-a-v3.md) → [추론/AI/참가자/N:M 명세](cost-v3-inference-ai-passenger-nm-test-architecture.md) → 해당 기능의 실제 소스와 검증. 필요할 때만 [Google 정본 계약](target-workflow-google-authority.md), [정본 회계 규칙](reconciliation-rules.md), [운영 이력](operations.md)을 읽는다.
3. **실행 흐름:** 승인 명세 기준 갭 확인 → 안전한 코드 구현 → 직접 영향 테스트 및 종단 검사 → diff/개인정보 확인 → 허용된 Git 반영 → 다음 실행 가능 항목. 작은 단위 완료나 최종 보고가 전체 종료 조건이 아니다.
4. **BLOCKED 판정:** 실제로 필요한 비밀정보/운영 권한만 차단한다. 그러한 권한 없이도 가능한 CI 원인 분석, 코드·계약 수정, 합성/Preview 검증, 문서 정리는 계속한다. 과금·운영 DB 변경·고객자료 전송을 자동 승인받은 것으로 간주하지 않는다.
5. **작업 큐와 종료:** 아래 우선순위 표는 이 문서의 과거 상태 기록이다. 최신 개발 상태와 재개 기준은 0.8절을 따른다. 로컬 작업 큐는 필수 전제조건이 아니다. 완료 항목을 다시 선택하지 않고, DEFERRED 점검을 실행 큐에 올리지 않는다. 실행 가능한 승인 작업이 없으면 COMPLETE/BLOCKED/DEFERRED 상태를 기록하고 종료한다. 후속 프롬프트는 명시적 인계나 새 사용자 요청에만 작성한다.

## 1. 마지막 검증된 Git 및 배포 기준점

| 표면 | GitHub/플랫폼에서 확인한 사실 | 구분 |
| --- | --- | --- |
| COST 앱 코드 기준 | [6Soo/cost main](https://github.com/6Soo/cost/commits/main); V3 앱 코드 기준 **0bd6e933ab** | V3 앱 기준 뒤의 main 추가 커밋은 문서-only다. 운영 호스트 릴리스는 별개이며 main 전체 배포가 아니다. |
| Reservation 앱 코드 기준 | [6Soo/reservation main](https://github.com/6Soo/reservation/commits/main) **3296255e07** (2026-10-23 확인) | PR #22 참가자 API, PR #23 KST 테스트 날짜 고정, PR #24 오류 응답 캐시 방지, [PR #25](https://github.com/6Soo/reservation/pull/25) COST 전용 토큰 공통 인증 정합화 |
| Reservation Vercel | [Production dpl_DQGvxo765hwryWWURP2XFVDdXkkm](https://vercel.com/6soos-projects/reservation/DQGvxo765hwryWWURP2XFVDdXkkm) — target=production, state=READY, sha=**3296255e07** | PR #25 인증 정합화 배포 READY. c315c17 때의 무인증 401/no-store 검증은 이력이며, 새 호스트 인증 성공은 아직 미검증 |
| Reservation Actions | [PR #25 main workflow](https://github.com/6Soo/reservation/actions/runs/39953733785): **unit 270/270 SUCCESS, smoke SUCCESS** | **P0 완료 유지.** COST 전용 토큰 인증/기존 토큰 동등 응답/인가 실패 시 DB 미조회 회귀를 추가했으며 새 커밋 CI 통과 |
| COST 배포 | 운영 보고상 승인된 `main` 앱 코드가 `C:\AX\cost`에서 실행되고 `LIGHTWEIGHT_RUNTIME_VERIFIED`·health/ready 200 확인 | 구형 운영 릴리스 `6bda111`은 과거 이력. `deploy/ota-unified-20261021`의 자동 병합은 V3 대량 삭제를 유발하므로 금지. 외부 GitHub 연결만으로 Windows 프로세스를 직접 재검증하지 않음 |
| 로컬 작업 공간 | 에이전트 보고상 COST 미추적 .claude/stop-gate/, reservation 사용자 미커밋 변경 보존 | GitHub에서 로컬 상태를 확인할 수 없음. 새 실행 시 로컬에서 재확인 필수 |

**수치 주의:** 과거 에이전트의 “94%”는 **17개 자체 정의 체크 중 16개 확인**이라는 추정 지표이며 독립적인 명세 전체 완료율·운영 준비율이 아니다. 저장소 구현·합성 종단 검증은 상당 부분 완료됐으나 실제 운영 기능 검증과 별도로 취급한다. 새 에이전트가 임의로 백분율을 다시 만들지 않는다.

### 실제 배포와 기능 동작의 구분

- Reservation 최신 확인 Production은 `3296255e` [dpl_DQGvxo765hwryWWURP2XFVDdXkkm](https://vercel.com/6soos-projects/reservation/DQGvxo765hwryWWURP2XFVDdXkkm) READY, [main Actions unit 270/270·smoke](https://github.com/6Soo/reservation/actions/runs/39953733785) SUCCESS. 기존 `70b00859`는 과거 기록이다.
- 사용자 승인으로 Turso 읽기 전용 DB 자격증명 `TURSO_READONLY_AUTH_TOKEN`, `TURSO_READONLY_DATABASE_URL`이 Reservation Production에 저장됐고 제공자 권한 claim `a=ro`(기록상 만료 2026-12-22T11:01:37Z)를 검증했다. 이후 Production 재배포도 READY. COST 보호 토큰은 합성 tour 404로 인증 통과했으나 어떤 허용 토큰과 일치하는지는 미확인(0.3~0.5).
- 과거 unit 실패는 로그에서 정확히 `tests/masterDataQueue.test.ts`의 기대 3/실제 2로 확인됐고, [PR #22 이전 기준선](https://github.com/6Soo/reservation/actions/runs/39639564867)에서도 같았다. GET route만 실제 오늘(KST)을 쓰고 test fixture는 2026-10-10 기준이라 2026-09-20 종료 여행이 실행일에 따라 30일 범위를 벗어난 것이 원인. [PR #23](https://github.com/6Soo/reservation/pull/23)에서 해당 테스트에만 Node 22 `t.mock.method(Date,'now',...)` 적용 후 CI 녹색.
- 실제 운영 여행의 **참가자 후보 응답**은 개인정보 승인 없이 조회하지 않았다. 합성 없는 여행 ID로 404 인증 통과만 확인했다(0.3). 과거 데이터 표/권한 설정 점검 이력은 0.3 이전 당시 기록이며 운영 DB 행·스키마 변경/내보내기는 없었다. 선택은 COST 내부 연결일 뿐 실제 탑승·보험 확정이 아니다.

## 2. 구현된 범위 — 우선 재사용할 근거

| 모듈 | 구현·테스트 근거(대표) | 여전히 구별할 사항 |
| --- | --- | --- |
| R0 진단/R1 계보·수동 pin 보존 | tools/audit_ota_card_coverage.py; 원본 재수집·저장소 재열기·crosswalk·중복 ID 표적 검증 | 실제 운영 전체 소스에 대한 전수 정확도 분석은 별도 작업 |
| R2 날짜 누락·후보 | OTA 날짜 없는 거래 후보와 merchant alias 및 카드 유효성 분리 | 미확정 예약번호를 확정값으로 올리지 않음 |
| R3 중앙 대사 | app/ota_payments.py, webapp/ota_snapshot.py, webapp/ota_payment_review.py, webapp/card_flow.py; COST 30b29fd 등에서 API/카드/귀속/준비 같은 발행 세대 종단 검증 | stale fallback은 복구용. 분류·재분류에서 구형 엔진이 중앙 정본을 덮지 못하도록 유지 |
| R4 금융 readiness | 실제 카드 원행 기준 경비 준비; COST cbc1c9a 120,000원 OTA 미확정→웹 저장→Google 복사 예약번호 공란. 중복·환불·원본 충돌 보류 | 실제 운영 장부 자동 대량 재기장 금지 |
| R5 사용자 이동·AI 학습 | 여행 A→B 즉시 수동 저장, 선택지 1/2/직접 답변3, 규칙 미리보기·승인·미래 거래 반영, 브라우저 합성 검증 | 모델 장애에도 사용자 배정 유지, 규칙은 승인 전 미적용 |
| R5-B 참가자 후보 | COST owner 화면/HTTP adapter/SQLite 저장/재조회·stale 재확정; Reservation PR #22/#25; 원격 main 원본 fixture 기반 교차 저장소 합성 브라우저 `1 passed`(0.4) | Production READY, 합성 tour 404로 인증 통과. 전용/범용 어떤 토큰인지 UNKNOWN. 운영 실자료 후보·revision·stale는 미검증. 신원 자동 확정·실탑승 아님 |
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

**최신 상태(0.3~0.5): 코드 구현 COMPLETE / Turso readonly 설정·Production READY / 합성 운영 API 인증 PASS(404) / 원격 main 합성 브라우저 PASS(1) / 전용 vs 범용 토큰 일치 UNKNOWN / 실자료 후보·운영 revision UNVERIFIED.** 과거 401은 PR #25 이전 이력. 토큰 값을 조회하지 않았으며 승인 없이 비밀 변경하지 않는다. 운영 실제 후보 조회는 개인정보 접근 승인 전 수행하지 않는다.

1. Vercel Reservation의 현재 Production `3296255e` READY와 도메인/환경을 확인했다. 운영 환경변수는 **이름·대상 환경만** 확인하고 값은 출력·복사·로그하지 않는다. 과거 `c315c17` 배포는 기록으로 보존한다.
2. Reservation의 내부 API: /api/internal/passenger-candidates?tourFldid=... ; 보호 Bearer 인증. 서버측 읽기 전용 전용 DB 클라이언트가 기존 getDb() schema 초기화·PII 마이그레이션을 사용하지 않는 구조임을 유지.
3. 필요한 설정 **Reservation**: INTERNAL_API_TOKEN(기존 내부 소비자 영향 검토), TURSO_READONLY_AUTH_TOKEN(해당 단일 DB read-only scope 필수), 선택 TURSO_READONLY_DATABASE_URL. **COST**: RESERVATION_INTERNAL_BASE_URL, RESERVATION_INTERNAL_API_TOKEN 또는 보호된 토큰 파일 경로(정확한 변수 이름은 webapp/reservation-passenger.env.example에서 재확인).
4. 변수 이름에 READONLY라고 적힌 것만으로 DB 권한을 증명하지 않는다. 운영 DB에 INSERT/CREATE를 시험하지 않는다. 격리 비운영 DB의 동일 권한 정책으로 조회 허용·쓰기 거부를 확인하거나 제공자 권한 표시를 검증한다.
5. 운영에서 사용자 승인 범위 내 **비파괴 읽기/비식별 결과 검증**: 비인가 요청 차단(401), 누락된 설정 실패 폐쇄(503), 승인된 범위의 tour 한 건에 한정된 최소 데이터, source_revision, 고객 ID/RRN/전화/여권 비노출, COST 후보 화면→사용자 확인→내부 저장/재조회→원본 변경 stale. 실제 고객명·토큰을 문서·채팅·CI artifact에 남기지 않는다.
6. 운영 비밀설정/인증 접근권이 없으면 **이 운영 단계만 BLOCKED**. 코드·테스트/CI 문제는 독립 진행. 실제 credentials를 요청하거나 채팅으로 붙여넣게 하지 않는다. 사용자가 Vercel 및 COST의 비밀 저장소에 직접 설정하도록 정확한 변수명과 권한 절차만 안내한다.

**완료 증거:** 실제 접근 대상 서비스 SHA/환경, 비밀값 없는 HTTP 상태/경로별 결과, 권한 범위·PII 최소화, 원본 변경 시 stale 및 사용자 확정 보존 여부. 읽기만 하고 운영 DB 변경 금지.

### P2 — COST V3 전역 실사용 갭 및 운영 배포 경계 (오해 방지)

**최신 상태(0.3~0.5): COST `main` 앱 코드 운영 배포 COMPLETE / health·ready COMPLETE / 합성 운영 참가자 API 인증 PASS(404) / 운영 실자료 미검증.** 기존 보호 백업·복원 검증 후 승인된 메인 코드에서 서비스가 실행됐다. 초기 401은 PR #25 이전 이력이며 수정 후 합성 404를 확인했다. 운영 후보·실데이터 화면 종단 동작은 미검증이고 Google·운영 DB는 변경하지 않았다.

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

과거 개발 PC에 Paseo + Codex Stop hook이 연결됐다. hook은 로컬 TASK_QUEUE.json이 승인한 미완료 항목이 있을 때 한 턴 안에서 다음 작업을 선택하도록 시험됐고, 관련 합성 A→B→C 및 31개 검사가 통과했다고 보고됐다. **이 설정·큐·로그는 GitHub 정본이 아니다.** 새 PC/새 에이전트에서 자동으로 존재한다고 가정하거나 필수 자료로 요구하지 않는다. 현재 승인 작업은 0.8절과 최신 사용자 요청을 기준으로 판단하며, 과거 P0~P3를 새 실행 큐로 복원하지 않는다.

- 로컬 설정 참고 경로(해당 PC에 존재할 때만): C:\AX\agent-policy\local-backups\cost-continuation-20261023, COST 로컬 stop-gate.json/TASK_QUEUE.json, 미추적 .claude/stop-gate/.
- 이전 10분 반복 태스크 ID 5e75876d는 종료 단계에서 삭제 성공을 보고했다. schedule 조회는 'Schedule not found'를 반환했으므로 삭제 전후의 실행 로그와 상태를 새 환경에서 재확인한다. **재등록 금지**, 업무가 완료됐는데 스케줄이 다시 실행되면 공식 인터페이스에서 소유 관계를 확인하고 중지. Codex hook과 이벤트 기반 재개/Heartbeat를 중복 설치하지 않는다.
- GitHub 문서가 현재 작업의 재개 근거이므로 **이 채팅·로컬 파일·별도 기억 없이** 다음 에이전트가 0.8절에서 현재 상태와 남은 승인 범위를 판단할 수 있어야 한다. 완료된 P0/P1을 다시 시작하지 않는다. 비밀 토큰, 인증코드, 사용자 DB, 실제 개인정보는 GitHub에 기록하지 않는다.

## 6. 새 세션에서 바로 수행할 검증·작업 예시

시작 단계:
- 0.8절의 개발 브랜치·PR 실제 HEAD와 해당 작업트리부터 확인한다. 기존 CI·배포·운영 인증은 변경이나 실패 근거가 있을 때만 다시 확인하며 과거 시작 절차를 자동 실행하지 않는다.
- **P0 완료:** Actions 39939654895 unit/smoke 모두 SUCCESS, PR #23 main 70b00859, Production READY. 새 실패 근거 없으면 재실행하지 않는다.
- **P1 설정·배포·무인증 경계·합성 404 인증·원격 main 합성 브라우저 확인 완료 / 실자료 검증 별도 승인 대기:** Reservation Production의 `TURSO_READONLY_*` Secret 적용 및 PR #25 `3296255e` Production READY. 합성 API 요청 404로 인증 성공, 교차 저장소 원격 main fixture 브라우저 1 passed. 정확히 전용 `COST_INTERNAL_API_TOKEN`인지 범용 `INTERNAL_API_TOKEN`인지 미확인. 실운영 후보·revision·stale는 미검증이며 운영 DB 쓰기 금지.
- 실운영 개인정보 접근이 필요한 P1 검증만 별도 승인 대기 상태로 유지하고 나머지 승인 작업은 계속한다. 운영 토큰 변경/회전은 일치 불일치가 실제 확인되고 별도 승인된 경우에만 한다.

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
