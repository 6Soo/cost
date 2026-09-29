# 2026-09-29 웹 장부 세션 인계

상태: `LOCAL_COMPLETE_EXTERNAL_PENDING`

> 후속 사용자 결정 `D-WEB-AGENT-002`: GPT 5.6 Sol Web이 관리·감독·지시하고 Muse Spark 1.3 Free와 SpaceBunny Free가 구현·환경설정을 격리 병렬로 맡는다. [운영 명세](../../WEB_LEDGER_AGENT_OPERATIONS.md)를 적용한다. 아래 SpaceBunny 전담·Muse 감사 전용·새 구현자 금지는 당시 기록이며 이 결정으로 대체된다. 실행 중 SpaceBunny는 보존하고 작성 범위가 겹치지 않을 때만 Muse 작업을 배정한다. 이번 명세 개정에서 에이전트를 실제로 재구성하지 않았다.

이 문서는 2026-09-29 세션에서 진행한 웹 장부 구현, 병렬 감사, 호스팅 준비, 인증 문제 확인, 사용자 결정, 에이전트 운용 상태를 다음 세션에 넘기기 위한 최신 인계다. 이전 `docs/handoff/2026-09-27/README.md`의 내용을 대체하지 않고 그 뒤에 이어지는 최신 상태만 기록한다.

## 1. 사용자 목표와 확정 지시

- `C:\AX\cost` 웹 장부 프로젝트를 실제 운영 전환 직전까지 완성한다.
- 로컬에서 닫을 수 있는 구현, 감사, 검증, 문서 작업은 외부 조건과 분리해서 끝까지 진행한다.
- 단일 작성자는 SpaceBunny를 유지한다.
  - agent id: `36982862-21d6-4f6b-b51c-921d4c981881`
  - model: `opencode/space-bunny-free`
- SpaceBunny가 `running`이면 추가 지시를 보내지 않는다.
- 병렬 감사에는 Muse Spark 1.3 Free를 사용할 수 있다.
- 병렬 에이전트 결과는 반드시 전량 회수하고 통합한 뒤 정리한다.
- 단순 실행 중, idle, 정상 재개 같은 상태 알림을 사용자에게 반복하지 않는다.
- 사용자에게 알려야 하는 상태는 permission, error, 사용자 판단이 필요한 큰 변화, 또는 로컬 작업 전체 완료다.
- green test 한 번만으로 완료 판정하지 않는다. requirement별 증거가 필요하다.
- 이번 세션 동안에는 commit, push, deploy를 금지한 운용 규칙이 있었으나, 세션 종료 시 사용자가 명시적으로 `지금까지의 세션 내용 모두 문서화하고 git push`를 지시했다. 따라서 이 인계 스냅샷은 그 명시 지시에 따라 commit과 push 대상으로 삼는다.
- SpaceBunny는 세션 이동 뒤에도 그대로 유지한다. 중단, archive, 새 prompt 전송을 하지 않는다.

## 2. 세션 중 주요 진행 흐름

### 로컬 구현과 검증

SpaceBunny가 기존 Phase 1~9 구현을 이어서 접근 제어, 운영 도구, 세션 세대, 로그아웃, 예약 접근 동기화, OIDC, 저장공간 보호, 운영 시작 경로, 안전 검사 관련 파일을 계속 수정했다.

세션 중 보고된 이전 검증값에는 다음 값이 있었다.

- `465 passed, 21 subtests passed in 194.71s`
- 이후 OIDC 관련 작업 시 `887 passed, 128 subtests passed in 425.51s`
- 같은 887 결과가 여러 번 반복됐다는 기록이 2026-09-27 handoff에 추가됐다.

다만 Muse 명세 감사에서 문서마다 숫자가 다르게 적힌 문제가 확인됐다. 다음 세션에서는 현재 작업 트리 기준으로 전체 suite를 다시 실행해 최신 단일 수치로 통일해야 한다.

### 접근 제어 관련 작업

이전 SpaceBunny 결과에서 확인된 주요 수정:

- 계정 `session_generation`과 `cache_namespace`를 실제 세션 검증에 연결했다.
- 연결 해제와 비활성화 시 세대를 증가시켜 이전 세션을 `SESSION_STALE` 401로 막는다.
- `/access/logout`을 추가했다.
- 승인과 철회 경합에서 상태 판정 순서를 고쳐 철회된 신청에 잘못된 사람 연결 오류가 먼저 나오는 문제를 수정했다.
- 행을 다른 여행으로 옮긴 뒤 새 여행 권한이 즉시 적용되는 경로를 검증했다.

### Google OIDC와 Railway 준비

세션 동안 Railway 계정과 Google 로그인 흐름을 실제로 시도했고, 중간에 `토큰 교환이 거절됐어요 (HTTP 400)`가 발생했다. 이후 사용자는 Google 로그인을 완료했다고 알렸다.

현재 저장소에는 OIDC와 운영 진입 관련 변경이 존재한다.

- `webapp/google_oidc.py`
- `run_candidate.py`
- `Procfile`
- 루트 `requirements.txt`
- `webapp/requirements.txt`
- `webapp/tests/test_google_oidc.py`
- `webapp/tests/test_platform_start.py`

실제 Railway 배포는 이번 세션에서 하지 않았다.

## 3. Muse 병렬 감사 결과

총 5개 읽기 전용 감사 에이전트를 병렬로 돌렸다. 직전까지 Railway 감사 회수가 늦어 병렬 결과 수렴이 불완전했으나, 세션 말미에 5개 모두 결과를 회수했고 Muse 에이전트 5개는 archive했다.

### 3.1 Spec Gap Audit

agent: `3023f5d1-10cc-4c9b-bd36-ef9e4ee8c84a`

주요 결과:

- 문서마다 전체 테스트 수치가 서로 달랐다.
- 기준 commit으로 `1486a37`과 `99041a4`가 혼재했다.
- handoff의 `PARTIAL_HANDOFF`와 구현 문서의 완료 표현이 충돌했다.
- `webapp/tests/test_ledger_design.py::test_a_waiting_row_moves_to_a_trip_from_the_list`는 과거 반복 실행에서 flaky 가능성이 있었다.
- 실제 카드와 은행 포맷은 합성 프로필 기준만 증명됐다.
- 390px 검증은 Chromium simulation이며 실제 휴대폰 실기 검증은 아니다.
- 한글 `\\uXXXX` literal 문제는 현재 검사에서 0건이었다.

### 3.2 Storage Guard Audit

agent: `3da34c8b-f0b9-4256-bd83-8d18b930e9d5`

주요 결과:

- `reserve_save_space`를 거치지 않는 쓰기 경로가 다수 있었다.
- `reserve_export_space`가 실제 manifest의 `income_rows`와 `expense_rows`를 제대로 계산하지 못할 수 있었다.
- `publish_workbook`가 공간 확보 전에 디렉터리를 만드는 문제가 있었다.
- 검사와 실제 write 사이에 원자성이 없었다.
- `disk_usage` 관측 실패 정책이 쓰기 경로와 ops 검사에서 달랐다.
- 경계값, 동시 경쟁, 실제 출력 크기 추정 검증이 부족했다.

### 3.3 DB Migration Audit

agent: `990a7e86-aad7-4c38-b640-9e976ae312af`

주요 결과:

- 읽기 전용 ops 일부가 `LedgerStore(seed_demo=True)`로 없는 DB를 만들거나 demo row를 넣을 수 있는 위험이 있었다.
- dry-run에서 디렉터리 생성 부작용 가능성이 있었다.
- readiness gate의 `required=false` 의미가 실제 exit code와 어긋날 수 있었다.
- migration rehearsal의 stale snapshot, 고정 comparison id, work dir 오염 위험이 있었다.
- backup business digest가 없는 legacy 묶음의 restore 검증이 약했다.
- restore 대상 non-empty 혼합, copy 후 hash 확인, WAL/SHM 정책이 필요했다.
- 예약 apply 시 missing DB 자동 생성은 막아야 한다.

### 3.4 Reservation Audit

agent: `190fb9b9-7eaa-4bc1-9359-520282598439`

주요 결과:

- 빈 snapshot이나 크게 줄어든 snapshot이 전체 사용자 해지로 해석되지 않도록 large-drop guard와 명시 override가 필요하다.
- 같은 revision인데 digest가 다르면 conflict로 거절해야 한다.
- assignment의 trip code가 실제 존재하는지 검증해야 한다.
- `tools/import_reservation_access.py`에 입력 검증, missing DB 거절, backup, rehearsal, structured error가 필요하다.
- sync 시도 감사 로그가 필요하다.
- SQLite busy와 timeout 정책이 필요하다.
- display name 길이와 제어 문자 정책, disambiguator 빈 문자열 덮어쓰기 방지가 필요하다.
- importer traceback 대신 구조화 JSON 오류가 필요하다.

### 3.5 Railway Hosting Audit

agent: `09b6225f-e018-48cb-ae33-d75b825e00e7`

주요 결과:

- 루트 `requirements.txt`에는 `google-auth`, `PyJWT`, `requests`가 있으나 `webapp/requirements.txt`와 설치 경로가 맞는지 확인이 필요하다.
- Railway 동적 `PORT`를 코드가 직접 읽지 않으므로 시작 명령에서 `--port $PORT` 연결이 필요하다.
- Python 버전 고정 파일과 Railway 전용 배포 설정 파일이 부족했다.
- `/healthz`, `/readyz` 같은 인증 없는 HTTP health 경로가 없었다.
- production `/board`는 인증 때문에 Railway healthcheck 대상으로 부적합하다.
- `webapp/ops.py:build_deploy_manifest` 기본 command가 `python -m webapp.cli serve`인데 `--snapshot`이 없어 그대로 실행할 수 없었다.
- `webapp/ledger_board.py` 직접 기동은 `seed_demo=True`와 상대 DB 기본값 때문에 production 진입점으로 쓰면 안 된다.
- Railway persistent volume과 `WEBLEDGER_DATA_ROOT` 연결 절차가 문서화돼야 한다.
- Google callback은 `{PUBLIC_BASE_URL}/auth/callback`이다.
- production fail-closed 방향은 대체로 구현돼 있다.

## 4. 외부 조건

다음은 로컬 구현과 분리해서 관리한다.

- `HOSTING-RESOURCE`
- `GOOGLE-OIDC-CLIENT`
- `RESERVATION-API`
- `PRODUCTION-DB`
- `PAID-RESOURCE`
- `DEPLOY`

이번 세션에서 실제 운영 DB, 실고객 자료, 실제 provider credential, 유료 외부 자원, 실제 production deploy는 사용하지 않았다.

## 5. 에이전트 상태

### SpaceBunny

- id: `36982862-21d6-4f6b-b51c-921d4c981881`
- provider: `opencode`
- model: `opencode/space-bunny-free`
- 세션 종료 직전 상태: `running`
- mode: `build`
- pending permission: 없음
- 사용자 지시: 그대로 유지

다음 세션에서는 먼저 Paseo로 상태를 확인한다.

- `running`이면 추가 prompt를 보내지 않는다.
- `idle` 또는 `finished`이면 Muse 감사 finding과 현재 코드의 1:1 대조가 끝난 뒤 미반영 항목만 같은 agent에 이어서 보낸다.
- 새 구현자를 만들지 않는다.

### Muse 감사 에이전트

5개 모두 결과 회수 후 archive 완료다. 다시 사용할 필요가 있으면 새 읽기 전용 감사 목적일 때만 생성하고, 결과를 전량 회수한 뒤 정리한다.

## 6. 세션 말미 작업 트리 스냅샷

세션 이동 직전 `git status`에서 다음 변경이 있었다.

수정:

- `docs/IMPLEMENTATION_PROMPT_WEB_LEDGER_APP.md`
- `docs/WEB_LEDGER_IMPLEMENTATION_LOG.md`
- `docs/handoff/2026-09-27/README.md`
- `run_candidate.py`
- `webapp/access_control.py`
- `webapp/card_import.py`
- `webapp/cli.py`
- `webapp/ledger_board.py`
- `webapp/ledger_store.py`
- `webapp/ops.py`
- `webapp/requirements.txt`
- `webapp/sheets_export.py`
- `webapp/tests/test_access_control_phase7.py`
- `webapp/tests/test_ops_hosting_bind.py`

새 파일:

- `Procfile`
- `requirements.txt`
- `ledger/domain/reservation_access_snapshot.py`
- `tools/import_reservation_access.py`
- `webapp/google_oidc.py`
- `webapp/space_guard.py`
- `webapp/tests/test_google_oidc.py`
- `webapp/tests/test_ops_safety.py`
- `webapp/tests/test_ops_surfaces.py`
- `webapp/tests/test_platform_start.py`
- `webapp/tests/test_reservation_access_sync.py`
- `webapp/tests/test_space_guard.py`

세션 시작 기준 HEAD는 `99041a4`였고 `origin/main`도 같은 위치였다.

## 7. 다음 세션에서 바로 할 일

1. SpaceBunny 상태를 확인한다. running이면 건드리지 않는다.
2. 현재 작업 트리와 이 인계 문서를 기준으로 SpaceBunny가 끝낸 변경을 읽는다.
3. Muse 5개 감사 finding을 파일과 테스트 기준으로 1:1 대조한다.
4. 미반영 finding만 같은 SpaceBunny에 `background=true`, `notifyOnFinish=false`로 이어서 맡긴다.
5. targeted test를 먼저 실행한다.
6. flaky 의심 테스트를 반복 실행한다.
7. 관련 ops, reservation, storage, migration test를 실행한다.
8. `py_compile`을 실행한다.
9. 전체 `webapp/tests`를 실행한다.
10. skip 이유와 flaky 여부를 확인한다.
11. 문서의 테스트 수치, 기준 commit, 완료 상태 표현을 하나로 통일한다.
12. Railway 실제 배포 전에는 PORT, health endpoint, persistent volume, OIDC callback, production entrypoint, demo seed 차단을 requirement별로 확인한다.

## 8. 완료 판정 기준

다음이 모두 충족되기 전에는 전체 프로젝트 완료로 보지 않는다.

- Muse 감사에서 나온 로컬 finding이 코드 또는 명시적 비적용 근거로 모두 닫혀 있다.
- 전체 테스트 최신 수치가 문서 한 곳에 일관되게 기록돼 있다.
- flaky 의심 테스트가 반복 검증됐다.
- 읽기 전용 ops가 DB나 파일을 만들지 않는다.
- 모든 중요한 쓰기 경로가 저장공간 보호를 거친다.
- 예약 snapshot의 빈 값, 대규모 감소, revision 충돌, unknown trip을 fail-closed로 처리한다.
- Railway 시작 경로가 production 전용 안전 진입점을 사용한다.
- healthcheck가 인증과 분리돼 있다.
- persistent volume이 `WEBLEDGER_DATA_ROOT`와 연결돼 있다.
- Google OIDC callback과 provider 설정이 실제 배포 주소와 일치한다.
- 외부 조건은 로컬 완료와 분리해서 명시돼 있다.

이 문서는 세션 이동용 최신 인계다. 다음 세션에서는 `docs/handoff/2026-09-29/README.md`를 가장 먼저 읽는다.

## 9. 최신 최종 판정 — 2026-09-29

웹 서버 잔여 문제는 두 원인으로 확인하고 수정했다. 서버마다 모듈 전역 저장소를
공유하던 문제는 요청별 `ContextVar` 결속으로 고쳤고, 하나의 SQLite 연결을 여러
요청 스레드가 동시에 사용하던 문제는 서버별 `RLock`으로 `do_GET`과 `do_POST`의
처리 구간을 직렬화해 고쳤다. 소켓을 읽는 전체 요청 처리에는 잠금을 걸지 않아
silent preconnect 대응인 `ThreadingHTTPServer` 동작은 유지했다.

변경 파일은 `webapp/ledger_board.py`와
`webapp/tests/test_ledger_server_store_isolation.py`다. 두 서버 저장소 격리와 한
서버 동시 요청 회귀 묶음은 각각 5회 모두 통과했고, 관련 기존 검사 묶음도 5회
모두 `91 passed`였다. 최종 전체 검사는 다음과 같다.

```text
python -m pytest webapp/tests -q -p no:cacheprovider --timeout=300
1033 passed, 1 skipped, 139 subtests passed in 449.58s
```

Sol의 최종 architecture/integration review는 로컬 구현을 수용했으며 추가로 닫아야
할 로컬 기능은 없다고 판정했다. 실제 Railway 설정·비밀값 주입·운영 DB와 백업·실제
Google OIDC callback·예약 API·AI 연결·배포 후 smoke·실물 모바일과 Excel 출력은
실제 외부 증거가 필요한 조건으로 남겨 둔다. 따라서 로컬 프로젝트는 완료 상태이고,
외부 운영 전환은 별도 조건 대기 상태다.

Sol의 외부 조건 검토 결과, `run_candidate.py`가 Railway의 `PORT`를 직접 읽으므로
`Procfile`에 `--port $PORT`를 덧붙일 필요가 없다. 별도 `railway.toml`도 필수는
아니다. Railway에서 로컬 검증 환경과 같은 Python 버전을 고정하려면 서비스 변수
`RAILPACK_PYTHON_VERSION=3.12.10`을 설정하면 된다.

외부 단계에서 받아야 할 입력은 Railway 프로젝트·서비스·persistent volume과 경로,
Google OAuth client ID·secret·callback·최초 owner 식별자, 예약 API endpoint·인증·
payload 형식, 실제 기준 자료와 운영 DB 이관 승인, 필요할 때의 비용 승인, 그리고
readiness 통과 뒤 실제 배포 승인이다. 이 입력과 배포 후 smoke 증거가 없으므로
전체 상태는 계속 `LOCAL_COMPLETE_EXTERNAL_PENDING`이다.

### 10. Aside CLI와 실제 Railway 상태 점검 — 2026-09-29

Aside CLI에서 기본 계정을 `u1`로 바꾸고 기본 모델을 `aside/glm-5.3-flash`로
설정했다. 이 설정으로 Railway를 읽기 전용 점검했다.

- Railway 프로젝트 `stellar-possibility`와 서비스 `empowering-encouragement`가
  이미 존재하고 온라인 상태다.
- 공개 주소는 `https://empowering-encouragement-production-e5b6.up.railway.app`이고,
  persistent volume은 `/data`에 연결되어 있으며 크기는 500MB다.
- 현재 배포 식별자는 `c88fba3b`이고 CLI 배포다. 시작 명령은
  `python run_candidate.py --port $PORT --host 0.0.0.0 --behind-proxy --environment production`이다.
  GitHub 원천 연결은 없다.
- `/auth/state`는 OIDC 설정과 `google-auth` 연결을 확인했지만
  `owner_google_sub_present=false`와 `owner_bootstrap_configured=false`다.
  `/healthz`와 `/readyz`는 현재 배포에서 인증 요구로 응답했고, 로그인 뒤
  `/access/me`는 viewer 상태였다.
- 직접 설정된 변수 이름은 `WEBLEDGER_DATA_ROOT`, `WEBLEDGER_GOOGLE_CLIENT_ID`,
  `WEBLEDGER_GOOGLE_CLIENT_SECRET`, `WEBLEDGER_PUBLIC_BASE_URL`,
  `WEBLEDGER_SESSION_SECRET` 다섯 개다. 값은 기록하지 않았다.

현재 로컬 HEAD `08ab403`과 운영 배포의 동일 원천 해시는 확인되지 않았고, 운영에는
owner 식별자·예약 API·실제 운영 DB 이관 증거가 없다. 배포 요금 잔액이 제한된 상태라
최신 코드 재배포와 변수 변경은 별도 실행 단계로 남긴다.

### 11. 사용자 자료 사용과 초기 접근 범위

- 최초 관리자는 사용자가 확인한 `kkokkohero6@gmail.com` Google 계정으로 둔다.
  실제 설정값은 이메일이 아니라 Google ID token의 `sub` 식별자다.
- 실제 예약 API가 확인되지 않았으므로 초기 운영은 관리자 전용으로 연다. 이 상태에서는
  별도 예약 API 없이 장부 자료를 검증할 수 있고, 직원별 조회가 필요해질 때 예약
  snapshot 연동을 추가한다.
- 최신 Google Sheets 내보내기인 `ledger/data/ledger_latest.xlsx`를 기준 장부로 사용하고,
  `ledger/data/classified_v14.csv`, `ledger/master_ledger.csv`, 일정 권위 자료는 검산과
  누락 확인에만 사용한다. 같은 내용을 두 원천에서 합산하지 않는다.
- 운영 이관은 원천 해시를 기록한 한 번의 import와 백업 검증으로 진행한다. 현재 Railway의
  합성 자료는 실제 자료와 섞지 않고 먼저 보존한다.
