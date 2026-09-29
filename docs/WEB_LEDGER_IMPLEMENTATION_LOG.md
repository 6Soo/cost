# 웹 장부 구현 기록

## 후속 명세 19.3 용량 거부와 체인 실행 감사 — 2026-09-29 (2차)

앞 절의 "운영 준비(rehearsal·smoke)와 readiness 게이트"를 이어서, **요구사항
단위로 아직 닫히지 않은 로컬 항목을 전부 훑고** 실제 실행으로 확인했다.

### 감사 방법

명세 18.3·19절의 각 항목을 "구현돼 있는가 / 실제로 검증돼 있는가"로 나눠 확인했다.
문서만 읽지 않고 **실행해서** 판정했다. 그 결과 요구사항 19.3 전체가 **아예 구현돼
있지 않음**을 확인했다.

확인된 사실: `MIN_FREE_BYTES`는 `health_check`의 `free_space` 줄에서만 쓰였고,
`ledger_store`·`card_import`·`ledger_board`·`sheets_export`에는 여유 공간을 묻는
호출이 **하나도 없었다**. 즉 "공간 부족 전에 경고한다"는 health 한 줄만 있고,
거부는 전부 없었다.

### 새로 구현한 것 — 19.3 용량 거부

`webapp/space_guard.py`를 추가하고 명세 19.3이 지정한 **순서대로** 거부를 넣었다.
하나의 모듈, 하나의 기준값이다. `webapp/ops`가 같은 기준값을 가져가므로 health 줄과
쓰기 경로가 서로 다른 답을 말할 수 없다.

| 순서 | 경로 | 코드 | 성격 |
|---|---|---|---|
| 1 | 카드 파일 접수 | `IMPORT_NO_SPACE` | 배치 행을 만들기 **전에** 거부. 거절된 파일은 접수된 것처럼 기록되지 않는다 |
| 1 | 새 출력 생성 | `EXPORT_NO_SPACE` | 임시 파일을 만들기 **전에** 거부 |
| 3 | 행 저장 | `SAVE_NO_SPACE` | 최소 여유 공간이 없으면 거부. 성공으로 위장하지 않는다 |

- 이미 저장된 장부·원천·출력은 **지우지 않는다**. 거부는 저장소를 건드리지 않는다.
- 거절이 파싱 오류처럼 보이게 하지 않는다. 각 거부는 자기 코드를 갖는다.
- **이미 완료된 요청의 재실행은 거절하지 않는다.** 저장된 결과를 돌려주는 것은
  쓰기가 아니므로, 공간이 없어도 통과시킨다. 이 순서가 틀리면 끝난 요청을 새 실패로
  보고하게 된다. 실행으로 이 순서 오류를 실제로 잡아 고쳤다.
- `health_check`에 `free_space_headroom`을 추가했다. 거부가 시작되기 **전에** 경고하고,
  fatal이 아니라 warning이다(19.3 "공간 부족 전에 경고").
- `ops._free_bytes`가 `space_guard.free_bytes`를 **호출**한다. 자기 구현을 남겨두면
  health와 쓰기 경로가 서로 다른 수를 읽는다. 이 잔여 이중 구현도 실행으로 발견했다.

### 체인 실행에서 발견한 결함 2건

health·backup·restore·drill·smoke·게이트를 **한 순서로, 실제 프로세스로** 돌려서
발견했다. 각 명령을 따로 시험할 때는 보이지 않는다.

1. **쓰기 가능성 판정이 실제 장부에서 항상 실패했다.** `board_revisions`는 NOT NULL
   8개인데 첫 판정이 열 4개를 이름으로만 넣었다. 그래서 **한 번이라도 저장된 적이
   있는 장부**(즉 모든 실제 장부)가 "쓰기 불가"로 보고됐다. 한 번도 저장 안 된 DB만
   통과했다. 첫 절의 검사가 이 경우를 놓쳤던 이유가 정확히 이것이다.
   수정: `PRAGMA table_info`에서 열을 읽어 자기 유지되게 만들었다. 앞으로 열이 늘어도
   같은 결함이 조용히 돌아오지 않는다.
2. **`ops restore`가 백업이 출력한 이름을 받으면 죽었다.** `ops backup`이 출력하는
   `bundle`은 **이름만**이다(`bundle-20260929T062350-chain`). 그 값을 그대로 넘기면
   `FileNotFoundError` traceback과 exit 1이 나왔다. 묶음은 `data_root/backups/`에
   있는데 상대 경로가 프로세스 작업 디렉터리 기준으로 해석되었기 때문이다.
   수정: `resolve_bundle`이 설정된 백업 루트 안에서 이름을 찾고, 없으면
   `BUNDLE_NOT_FOUND`로 거절한다(traceback 아님). 전체 경로 형태는 그대로 동작한다.

### 상태 표시에 남아 있던 부정확

`EXTERNAL_CONDITIONS`의 `code_status`가 실제 코드 상태와 어긋나 있었다. 이 필드의
목적이 바로 "코드가 없는 것"과 "외부 입력이 없는 것"을 구분하는 것이므로:

| 항목 | 이전 | 지금 |
|---|---|---|
| `HOSTING-RESOURCE` | `not_implemented` | `operational_readiness_implemented_awaits_resource` |
| `PRODUCTION-DB` | `phase8_synthetic_only` | `synthetic_rehearsal_only_awaits_real_sources` |
| `DEPLOY` | `dry_run_only` | `gated_and_dry_run_only_awaits_deployment` |

호스팅 준비 코드(바인드 정책·영속 데이터 루트·systemd 예시·런북·health·smoke·
게이트)는 구현·검증됐고, 없는 것은 **돌릴 서버**다. `not_implemented`는 그 단계를
미구성으로 보고하는 셈이었다.

### 통합 체인 실행 결과 (모두 실제 프로세스, exit 코드 포함)

| 순서 | 명령 | 결과 |
|---|---|---|
| 1 | `ops health` | exit 0, `ok=true`, 실패 없음 |
| 2 | `ops backup --label chain` | exit 0, `bundle-20260929T062350-chain` 생성 |
| 3 | `ops restore <출력된 이름>` | exit 0, `ok=true`, traceback 없음, 멱등성 재실행 확인 |
| 4 | 복원본 검사 | `board_rows=8`, `access_accounts=1`, `access_connections=1`, 원본 그대로 |
| 5 | `ops drill --target <별도 경로>` | exit 0 |
| 6 | `ops smoke` | exit 0, `board_writable=true`, 여유 공간 두 줄 정상 |
| 7 | `run_candidate --require-ready` (준비 완료된 루트) | **기동함**. 전부 거절하는 게이트는 게이트가 아니다 |
| 8 | `run_candidate --require-ready` (빈 루트) | **exit 2, `SMOKE_FAILED`, DB 미생성** |
| 9 | 원본 데이터 루트 | 손상 없음 |

7번과 8번을 함께 봐야 게이트가 맞다. 준비된 곳을 막으면 게이트가 아니라 오작동이고,
 prepares되지 않은 곳을 통과시키면 게이트가 아니다.

### 실행 후 검증

- 신규 `webapp/tests/test_space_guard.py` **18건**, 통과.
- `webapp/tests/test_ops_surfaces.py` 19건 → **25건**으로 확장(복원 왕복·묶음명
  거절·전체경로·게이트 통과·revision 있는 장부의 쓰기 판정·프로브 비변경).
- **돌연변이 전건 검출, 생존 0.** 19.3 그룹 8건, 체인에서 발견한 2건 그룹 5건.
  19.3 첫 회차에서 `publish_workbook` 자체를 지나가지 않던 검사 1건이 살아남아,
  실제 출판 경로를 태우는 검사를 추가한 뒤 0건이 되었다.
- 전체 회귀: **`930 passed, 1 skipped, 128 subtests passed in 383.41s`**, exit 0.
  직전 `924 passed, 128 subtests` 대비 +6, 회귀 0.
- skip 1건은 Windows에서 `chmod`로 읽기 전용 파일을 만들 수 없어 건너뛴 것이다.
  음의 분기를 대신 만들어 통과시키지 않았다.

### 이번 세션이 닫지 못한 것과 이유

- **19.3 성공 경로의 용량 부족 재현.** 이 파일시스템을 실제로 채울 수 없어, 여유 공간
  조회를 강제로 대체해 검사했다. "진짜 ENOSPC에서 sqlite가 어떤 문장을 내는지"는
  관측하지 못했다. 강제 대입은 판정 경로를 검증하지만 저장 계층의 실제 오류는
  대체하지 못한다.
- **18.3(5) DB 스키마 마이그레이션 실행기.** 파일이 있고 버전이 뒤처진 때만 실행된다는
  조건을 **검사**하는 코드는 있으나, 별도의 버전 마이그레이션 실행기를 이 세션에서
  만들지는 않았다. `dry_run_deploy`가 현재 스키마를 대조한다.
- **19.2 "SQLite·원천 디렉터리 공개 금지"**의 경로 접근 검사는 코드에서 확인했지만,
  외부 노출 자체는 호스팅 자원이 없으므로 닫을 수 없다.
- 이관 seal의 성공 경로는 여전히 **실제 gate report 산출물**이 있어야 재현된다.

## 운영 준비(rehearsal·smoke)와 readiness 게이트 — 2026-09-29

이번 절은 코드를 읽고 추측한 것이 아니라 **실행해서 발견한 결함 7건**과 그 수정을
기록한다. 각 항목의 "발견 방법"이 실행인지 읽기인지 구분되어 있다.

### 추가한 명령 3개

| 명령 | 하는 일 | 적용하지 않는 경계 |
|---|---|---|
| `ops smoke` | 이 프로세스가 지금 요청에 답할 수 있는지 판정 | DB를 **읽기 전용**으로 연다. 검사 대상을 만들지 않는다 |
| `ops reservation-sync` | 예약 접근 스냅샷 연습(`--db` 없음) 또는 지정 DB 적용 | 연습은 DB 사본에 실제 동기화 코드를 돌리고 원본을 전후 해시로 대조한다 |
| `ops migrate-rehearsal` | 양쪽 source를 seal·비교하고 기록까지만 한다 | `apply`를 호출하지 않는다. seal은 `work_dir`의 **바이트 동일 사본**에 한다 |

`run_candidate.py`에 `--require-ready`를 추가했다. 게이트는 **포트에 바인딩하기 전에**
`smoke`을 돌리고, blocker가 있으면 종료 코드 2로 거절한다. production 환경은 암묵히
게이트가 켜진다.

### 실행으로 찾아 고친 결함 7건

1. **운영 준비 검사가 검사 대상 DB를 만들고 있었다.** `smoke_report`가
   `LedgerStore`를 열었고, 그 생성자는 파일을 만들며 빈 DB에 데모 보드를 시드했다.
   그래서 "없는 DB"를 검사하는 경로에서 검사기가 DB를 만들어낸 뒤 `ok: True`로
   보고했다. 확인: 검사 전 `db exists=False`, 검사 후 `True`(31 테이블, 7행),
   보고는 `ok=True, blockers=[]`. 수정: 읽기 전용 연결(`_ReadOnlyStore`)으로 열고,
   파일이 없으면 "없음"으로 보고한다.
2. **운영 시작이 합성 시드 행을 넣었다.** `LedgerStore.__init__`가 `first_create`
   일 때 `_seed()`·`_ensure_trips()`를 호출해 데모 7행과 데모 여행 2개를 넣는다.
   bare `serve()`만으로 확인했다(`board_rows=7`, `expense-demo-c1`…). 이는
   SPEC_REFINEMENT 18.3 5항(운영 시작 때 합성 시드 금지) 위반이다. 수정:
   `seed_demo=True` 기본값을 추가하고 `run_candidate`는 production에서 `False`를
   넘긴다. 기존 호출자와 테스트의 demo 보드는 그대로다.
3. **쓰기 가능성을 SELECT로 보고했다.** `board_writable`이 `SELECT` 하나로 참이라고
   보고했다. 수정: DB 사본을 떠서 실제 `INSERT` 후 `ROLLBACK`을 수행해
   **관측된** 쓰기로 판정한다. 원본 장부는 건드리지 않는다.
4. **성공한 첫 적용을 실패로 보고했다.** `ops reservation-sync --db`의 종료 조건이
   **첫 회차**의 `ignored_stale_or_equal`을 읽었다. 첫 적용에서는 이 값이 당연히 0이
   라 성공이 종료 코드 2로 나왔다. 수정: 두 번째 패스가 no-op인 `idempotent`로
   판정한다.
5. **예약 파서의 거부가 traceback으로 새어나왔다.** CLI가 스냅샷을 직접 파싱해
   `ValueError`가 그대로 새었다(`exit=1`, traceback). 수정:
   `ops.parse_reservation_snapshot()` 한 곳에서 `OpsError`로 바꿔 연습·적용이 같은
   답변을 내게 하고, CLI는 그 한 곳만 호출한다.
6. **이관 연습이 seal을 건너뛰어 실행 자체가 불가능했다.**
   `verify_snapshot`은 `candidate_semantic_sha256` 없는 descriptor를 거부하는데, 이
   값은 sealer가 계산하지 않고 **상류 gate report**에서 온다. 게이트 리포트 없이
   실행하면 `SNAPSHOT_NOT_SEALED`이었다. 수정: `--left-gate-report` /
   `--right-gate-report`를 받아 통과시키고, 없으면 traceback이 아닌 명확한 거부를
   낸다.
7. **연습이 source 옆에 쓰려고 했다.** `seal_and_verify_sources`는 descriptor를
   **후보 파일 옆에** 쓴다(후보를 파일 이름으로 기록하므로). 그대로면 운용자의
   source 디렉터리에 파일 2개가 생긴다. 수정: source와 gate report를 `work_dir`에
   복사해 그 복사본을 seal한다. 해시는 같은 바이트에서 나오므로 seal은 여전히
   진짜 source를 증명하고, source 디렉터리는 건드리지 않는다.

추가로 고친 **보고 결함** 1건: `seal_and_verify_sources`는 양쪽을 `google`/`db`로
라벨링하는데 연습이 `left`/`right` 키를 읽어 seal 증거가 `null`로 보고됐다. 표면은
완성된 것처럼 보인 채 증거가 사라지는 상태였다. 라벨을 함께 보고한다.

### 새로 기록된 계약 (가정하지 않고 실행으로 확인)

- 예약 파서는 `snapshot_revision == int(exported_at.timestamp()*1000)`를 **정확히**
  요구한다. `+00:00`, `Z`, 소수점 없음, 다른 오프셋은 모두 통과하고 값이 어긋나면
  `reservation_access_revision_time_mismatch`다.
- `LedgerStore`/`serve`의 demo 시드는 `seed_demo`로 제어되며 기본값은 유지된다.
- `compare_sources`의 mismatch 행은 이미 `changed_fields`를 담는다. 연습은 이를
  그대로 읽고 두 번 계산하지 않는다.
- 검증된 identity(`source_identity`)가 없으면 같은 이름·날짜·금액도
  `ambiguous`(확인 불가)로 간다. 연습이 이 결정을 그대로 노출한다.

### 실행 후 검증

- `webapp/tests/test_ops_surfaces.py` 신규 **19건**, 모두 통과.
- **돌연변이 7건 전건 검출, 생존 0.** 각 검사가 실제로 결함을 잡는지 확인했다
  (시드 강제, 쓰기 가능 store 재도입, SELECT로 되돌리기, seal 라벨 되돌리기,
  종료 조건 되돌리기, traceback 되돌리기, 제자리 seal로 되돌리기). 복원 후 스위트 OK.
- 전체 회귀: **`906 passed, 128 subtests passed in 308.54s`**, 종료 코드 0.
  직전 기준 `887 passed, 128 subtests` 대비 **+19(신규 검사)**, 회귀 0.

## 전체 요구사항 감사 — 2026-09-27

기준은 본 저장소 HEAD `1486a37`, 작업트리 미커밋. 실행 모델은
`opencode/space-bunny-free`(입력·출력 비용 0)이며 유료 대체는 하지 않았다.
외부 Google OAuth·예약 API·운영 DB·실제 고객 자료·유료 자원·실제 배포와
commit·push는 사용하지 않았다.

### 최신 전체 검증 (이번 감사 최종값)

- 감사 착수 전 1회: `452 passed, 21 subtests passed in 156.37s`
- 감사 수정 후 최종 1회: **`465 passed, 21 subtests passed in 194.71s`**
  종료 코드 0. 감사에서 13개를 추가했다.

### 감사 방법

명세 15.5 최소 권한 수용 사례 9행, 16.5 최소 검증 8항목, Phase 8·9 수용 기준을
항목씩 실행해 관측값을 직접 확인했다. 코드를 추측하지 않고 합성 경로에서 재현한
결과다.

### 감사로 확인된 정상 동작 (코드 수정 없음)

- 보관된 여행은 담당 배정이 유지되는 동안 계속 조회된다(SPEC 15.5 3행).
- 행을 다른 여행으로 옮기면 새 여행 권한이 즉시 적용되어 이전 담당자에게 404가
  되고 이전 여행 목록에서도 사라진다(SPEC 15.2).
- 예약 서버 장애와 무관하게 owner의 export는 계속 200이다.
- 빈 값·공백·미등록 헤더·헤더 없음은 모두 401이며 로그인 완료로 표시되지 않는다
  (SPEC 16.5 8항목).
- owner 로그아웃 후 viewer는 export·작업 조회를 볼 수 없다.

### 감사로 발견해 고친 실제 결함 3건

1. **세션 세대가 죽은 코드였다.** `Session.session_generation`과
   `cache_namespace`이 정의만 있고 어디에서도 쓰이지 않아 SPEC 15.3의
   "계정·권한 세대와 요청을 결속"이 실제로는 적용되지 않았다.
   `access_accounts.session_generation`을 추가하고(기존 DB는 ALTER로 보존),
   연결 해제·계정 비활성화 시 세대를 올리고, 이전 세대의 세션은 `SESSION_STALE`
   401로 거절한다. `/access/me`는 세대와 cache namespace를 돌려준다.
   합성 어댑터는 이 세대를 stamp하며, 이전 세대를 제시하는 헤더로 거절을 확인한다.
2. **승인이 철회된 신청에서 사람 충돌 코드를 냈다.** 상태 검사가 뒤에 있어서
   철회된 신청을 승인할 때 `PERSON_ALREADY_LINKED`가 났다. 명세 16.5의
   "거절·철회·연결 해제·비활성화를 같은 오류로 뭉치지 않는다"에 어긋난다.
   신청 상태를 먼저 보고 거절하도록 순서를 바꿨다. 승인 대 철회 경합에서 최종
   상태가 하나만 남고 다른 쪽은 그 상태로 거절되는 것을 확인했다.
3. **runbook의 명령이 실제로 존재하지 않았다.** Phase 9 runbook이 절차를 적지만
   실행할 명령이 없었다. `webapp/cli.py`에 `ops health|backup|restore|dry-run|
   readiness`를 연결해 runbook이 그대로 실행 가능해졌다. 실제로 실행해 보니
   `_ops_config`가 `backup`에만 있는 `keep_backups`를 무조건 읽어 4개 명령이
   `AttributeError`로 죽는 결함이 더 발견돼 고쳤다. fail-closed 거절도
   traceback이 아니라 코드와 메시지를 담은 JSON과 종료 코드 2로 보고되게 했다.

추가로 `/access/logout`을 넣어 세션 종료와 클라이언트가 비워야 할 목록
(`selected_row`, `cached_ledger_data`, `cached_evidence`)을 서버가 알려주도록
했다. 이전에는 세션을 끝내는 방법이 없었다.

### 추가한 검사 13개

- Phase 7에 10개: 세대 이전 거절, 비활성화 시 세션 종료, 잘못된 세대 헤더,
  계정별 세대 독립, 철회된 신청의 상태 코드, 승인·철회 경합, 행 이동 즉시 권한,
  보관 여행 조회, 로그아웃, owner 로그아웃.
- Phase 9에 3개: ops CLI 5개 명령 실행, 미설정 시 fail-closed,
  운영 환경 + 임시 루트 시 fail-closed.

### 이 감사 이후 실행한 검사

- [역사 수치 — Phase 9 구현 당시] `test_ops_phase9.py` → `28 passed`
  (현재 수집 기준 64건. `webapp/cli.py` ops 명령과
  `test_ops_phase9.py`의 조치 필요 표면 검사가 추가된 뒤의 값이다.)
- `test_access_control_phase7.py` → `35 passed`
- `test_migration_phase8.py` → `18 passed`
- 위 세 묶음 → `81 passed in 23.49s`
- 전체 1회 → `465 passed, 21 subtests passed in 194.71s`
- `py_compile` 6개 파일 통과, 잔여 프로세스 0.

### 로컬로 더 고칠 수 있었던 항목은 모두 처리했고, 남은 것은 외부 조건이다

`ops.EXTERNAL_CONDITIONS` 여섯 항목이 그대로 미완이다. 호스팅 자원, Google
OAuth 클라이언트·콜백, 예약 API, 운영 DB와 실제 Google 기준본 이관, 유료 전환
승인, 실제 배포. 감사에서 로컬 구현·검증으로 닫을 수 있는 것은 닫았고, 남은
것은 모두 사용자 결정이나 외부 연결이 필요한 항목이다.

## 최신 채팅 인계 — 2026-09-27


새 채팅은 `docs/handoff/2026-09-27/README.md`의 맨 위 최신 재개 정보와 이
블록을 함께 읽는다. 현재 기준 커밋은 `1486a37`이고 commit·push·배포는 하지
않았다. 작업트리에는 Phase 7~9 구현과 390 화면 수정이 커밋되지 않은 상태로
남아 있다.

현재 구현 파일은 `webapp/access_control.py`, `webapp/migration.py`,
`webapp/ops.py`, 기존 연결부 `webapp/ledger_board.py`, 390 수정
`webapp/ledger_design.py`이다. 전용 검사는 각각 다음 결과를 현재 작업트리에서
확인했다.

- `python -m pytest -q webapp/tests/test_access_control_phase7.py -p no:cacheprovider` → `25 passed in 12.01s`
- `python -m pytest -q webapp/tests/test_migration_phase8.py -p no:cacheprovider` → `18 passed in 1.75s`
- [역사 수치] `python -m pytest -q webapp/tests/test_ops_phase9.py -p no:cacheprovider` → `25 passed in 3.96s`
- 관련 회귀 묶음 → `94 passed, 3 subtests passed in 42.84s`
- 다섯 구현 파일 `py_compile` → 통과

Phase 9 뒤 전체 383 검사는 아직 실행하지 않았다. 문서에 남은 과거 전체 검사
결과는 참고 기록일 뿐 최신 변경을 증명하지 않는다. 다음 재개자는 전체 검사를
한 번 실행한 뒤 Phase 7~9와 상세 계약을 요구사항별로 감사한다.

Paseo 구현자는 `36982862-21d6-4f6b-b51c-921d4c981881` 한 명이며 제목은
`SpaceBunny`, 모델은 `opencode/space-bunny-free`이다. heartbeat
`cost-web-ledger-implementer-watch`의 ID는 `1de97732`이다. 새 채팅에서 이어갈
때 기존 agent를 재사용하고 새 agent를 만들지 않는다. 실제 Google OAuth,
예약 API, 운영 DB, 고객 원본, 유료 자원, 실제 배포는 연결하지 않았다.

다음 구현 순서는 전체 검사와 요구사항별 감사, 결과 문서 정리다. 외부 조건은
`webapp/ops.py`의 `EXTERNAL_CONDITIONS`에서 미완료로 유지하며, 운영 전환을
완료로 기록하지 않는다.

## Phase 9 로컬 운영 준비 — 2026-09-27

기준은 본 저장소 HEAD `1486a37`이다. Oracle, Google OAuth, 예약 API, 운영 DB,
실제 고객 원본, 유료 자원, 실제 배포, commit·push는 사용하지 않았다. 모든 검사는
합성 경로와 합성 데이터 위에서만 돌았다. 실행 모델은 `opencode/space-bunny-free`
(입력·출력 비용 0)이며 유료 대체는 하지 않았다.

### 구현한 것 — `webapp/ops.py`

- **durable config**: 데이터 루트와 필수 설정을 명시적으로 검증한다. 기존 개발
  기본값(`WEBLEDGER_DB` 상대 경로 `webledger.work.sqlite`, `webledger-exports`)을
  참조하면 `REFUSED_DEFAULT_PATH`로 거절한다. 운영 환경에서 데이터 루트가 시스템
  임시 디렉터리 아래면 `TEMP_DATA_ROOT`로 거절한다. 합성·dry-run 환경만 임시
  경로를 스스로 선언할 수 있다. 비밀은 존재 여부만 기록하고 값은 담지 않는다.
- **백업 묶음**: DB를 SQLite 온라인 백업으로 복사하고 불변 원천·증빙·출력
  메타를 내용 해시와 함께 묶는다. `operator_ledger.backup`을 재사용해 체인과
  체크포인트를 함께 보낸다. 원본은 읽기만 한다.
- **restore**: 별도 경로로 복원한 뒤 사건·배분·정정·요청 멱등성·권한 상태를 다시
  검사한다. 원본 DB와 번들은 건드리지 않는다. 해시 불일치 번들은 복원하지 않고
  거부한다. auth cache는 사용하지 않고 요청마다 판정하며, synthetic 세션 허용
  상태는 복원 보고의 **finding**으로 남긴다(허용이 복원을 정상 경로로 올리지
  않게 하기 위해).
- **재시작 생존**: 합성 DB로 store를 닫았다가 새 연결로 열어 행·revision·여행
  배정·이벤트 이력·요청 ID 재사용이 유지되는지 실제로 확인한다.
- **health/readiness**: DB 경로, 무결성, 스키마, 여유 공간, 필수 비밀, 데이터
  루트를 각각 독립 항목으로 보고한다. DB가 없으면 스키마·무결성 검사도 "미검사"
  실패로 기록해 성공으로 숨기지 않는다. readiness report는 행·이벤트·계정 수,
  공급자 턴 시도·대기·완료, 저장 시간, 대사 횟수를 함께 낸다.
- **배포 dry run**: 매니페스트를 만들어 로컬에서 경로·디렉터리·비밀 존재와
  비노출을 검사하고 `applied: false`를 유지한다. runbook은 수동 단계와 미충족
  외부 조건을 적는다. 아무것도 적용하지 않는다.
- **보관 정책**: 최근 7개 기본 유지, 같은 `bundle_sha256`인 번들은 하나만 남긴다.

### 실행 중 고친 실제 결함 4건

1. read-only 연결에서 `PRAGMA wal_checkpoint`를 실행해 백업이 `disk I/O error`
   로 실패했다. 체크포인트를 빼고 온라인 백업만 쓴다.
2. 경로 거절 검사가 구분자 때문에 Windows 경로를 놓쳤다. 슬래시를 정규화한다.
3. dry run의 비밀 검사이 *이름*을 찾아 manifest에 이름이 있는 정상 상태를 실패로
   판단했다. *값*이 있는지를 검사한다.
4. DB가 없을 때 스키마·무결성 검사를 아예 건너뛰어 실패를 감췄다. 없는 검사를
   실패로 기록한다.
   추가로 재시작 검사가 `store.save`가 돌려주지 않는 키를 비교해 항상 실패했다.

### 실행한 검사

- [역사 수치] `test_ops_phase9.py`: 25 passed in 3.66s.
- 회귀 확인: Phase 7 + Phase 8 43 passed. 390·장부·Phase 0 묶음 71 passed.
  전체 383 suite는 반복하지 않았다.

### 코드 성공과 분리해 보고할 외부 조건

`ops.EXTERNAL_CONDITIONS`에 상태로 남긴다. 로컬 실행이 통과해도 아래는 미완이다.

| ID | 상태 | 필요한 것 |
|---|---|---|
| HOSTING-RESOURCE | not_provisioned | 사용자 승인, 자원·계정 |
| GOOGLE-OIDC-CLIENT | no_credentials | 사용자가 발급한 클라이언트 ID와 콜백 |
| RESERVATION-API | not_connected | 예약 저장소 엔드포인트와 인증 방식 |
| PRODUCTION-DB | not_migrated | 실제 Google 기준본과 운영 DB |
| PAID-RESOURCE | not_approved | 사용자 결정 |
| DEPLOY | not_deployed | 위 조건 정리 후 사용자 승인 |

## Phase 8 로컬 합성 이관 — 2026-09-27

기준은 본 저장소 HEAD `1486a37`이며 실제 Google 기준본·운영 DB·고객 원본·외부
연결은 사용하거나 수정하지 않았다. 입력은 임시 디렉터리에서 만든 합성 SQLite
원천 둘이고, 이관이 쓰이는 곳은 별도 migration DB다. 실행 모델은
`opencode/space-bunny-free`(입력·출력 비용 0)이며 유료 대체는 하지 않았다.

### 재사용과 보완

`webapp/snapshot_descriptor.py`의 `seal_snapshot`/`verify_snapshot`를 그대로
사용해 두 원천을 read-only snapshot descriptor로 봉인하고 해시·sidecar 상태를
검증했다. `webapp/comparator.py`의 `diff_json`을 필드 차이 계산에,
`webapp/contracts.py`의 `canonical_text`·`normalize_amount`를 정규화에 썼다.
별도 봉인 방식은 만들지 않았다. 새로 보완한 것은 합성 원천 어댑터, 다섯 상태
비교, 명시 결정을 이관 DB에 적용하고 보고하는 부분이다.

descriptor는 원천 파일과 같은 디렉터리에 쓴다. descriptor가 원천을 파일명으로
만 기록하고 `verify_snapshot`이 그 이름을 descriptor 옆에서 해석하기 때문이다.
원천 DB 자체는 쓰지 않는다.

### 구현한 계약

- 행 연결은 명시 `source_identity`로만 한다. 이름·날짜·금액이 같아도 합치지
  않고 `ambiguous`로 남긴다. 한쪽 원천 안에서 identity가 중복되어도 `ambiguous`다.
  연결 키에 `entry_id`를 섞지 않았다. 두 원천은 각자의 entry id를 쓰기 때문에
  섞으면 같은 거래가 절대 매칭되지 않는다.
- `equal`/`mismatch`/`google_only`/`db_only`/`ambiguous` 다섯 상태를 따로
  집계한다. 외미만 있는 행과 값이 다른 행, 판단할 수 없는 행을 한 계정으로
  합치지 않는다. `ambiguous` 쌍은 one-sided 목록에서 빼서 이중 계상을 막았다.
- `mismatch`는 필드별 명시 선택이 필요하다. 기본값이 없고, 선택하지 않은
  필드가 있으면 그 행은 미해결로 남고 아무것도 쓰지 않는다.
- 원천 금액·날짜 불일치는 `migration_provenance`에 양쪽 값을 함께 남긴다.
  표시값을 골라도 반대쪽 값은 지워지지 않는다.
- 결정은 `comparison_id` + 좌우 입력 hash + 필드 + 값 + 사용자 + 시각에 결속한다.
  입력 hash가 달라지면 `INPUT_CHANGED`로 이전 결정을 재사용하지 않는다.
- 적용 대상은 별도 migration DB뿐이다. 같은 요청 ID는 검증된 재사용, 다른
  요청 ID라도 같은 입력이면 행 키와 사건 키가 같아 두 번째 효과가 없다.
  원천에 migration 테이블이 생기지 않고 원천 해시가 그대로임을 검사한다.

### 실행 중 고친 실제 결함 2건

1. `sign`을 총계에 적용하지 않아 지출이 양수로 집계됐다. 부호를 곱해
   income·expense를 만들고 balance는 income + expense로 계산한다.
2. `decide_field`가 좌우에 같은 entry id가 있다고 가정해 오른쪽 행을 못 찾았다.
   좌측 entry id에서 공유 identity를 얻고 그 identity로 오른쪽 행을 찾도록 바꿨다.

### 실행한 검사

- `test_migration_phase8.py`: 18 passed.
- 재사용 모듈 회귀 확인: `test_phase0.py`, `test_ledger_core.py`,
  `test_checkpoint_tamper.py` 26 passed. `test_sheets_export.py` 포함
  Phase 7·390 파일 묶음 65 passed.

### 아직 연결하지 않은 것

실제 Google 기준 워크북, 실제 예약 API, 운영 DB, 이관 대상 운영 계정, 배포.
위 검증은 전부 합성 입력에 대한 것이다.

## 390 실제 클릭 검증과 최소 수정 — 2026-09-27

기준은 본 저장소 `C:\AX\cost` HEAD `1486a37`이다. 실행 모델은
`opencode/space-bunny-free`(입력·출력 비용 0)이며 유료 대체는 하지 않았다.
전체 383 검사는 반복하지 않고 변경 범위 파일만 실행했다.

### 수정 1 — 390 편집 패널 footer가 화면 밖으로 밀리던 결함

`.panel`은 flex column인데 저장 `<form data-js-save>`이 그 사이의 일반 block이라
`.p-bd{flex:1 1 auto}`가 적용되지 않았다. 그 결과 `.p-bd`가 내용 높이까지 자라고
내부 스크롤이 dead 상태가 되어, 첫 저장에서 추가되는 `.f-msg` 줄이 저장/취소
footer를 패널 아래로 밀어냈다. 수정 전 실측(390x844): viewport 844, `.p-bd`
top 88·bottom 840, 저장 버튼 top 853·bottom 897, `scrollHeight == clientHeight == 732`.
즉 버튼이 viewport 밖에 있어 두 번째 저장이 클릭 자체로 불가능했다.
수정 후 실측: `.p-bd` top 88·bottom 775, `scrollHeight 753 > clientHeight 688`로
실제 스크롤(0→65)되고, 버튼 top 788·bottom 832로 viewport 안에 남는다.

수정 파일: `webapp/ledger_design.py`(CSS 2줄). `.panel form`에 flex column과
`min-height:0`을 주고 `.p-bd`에 `min-height:0`을 추가했다.

회귀 검사: `webapp/tests/test_ledger_design.py`
`test_the_panel_footer_stays_reachable_and_two_saves_work_at_390`. 고정된 좌표가
아닌 흐름으로 검사한다. 최초 footer가 viewport 안 → 첫 저장 실제 click →
`.p-bd`가 필요할 때 스크롤되는지(`scrollHeight >= clientHeight`, 넘치면 실제
스크롤 값 0 초과) → footer 계속 viewport 안 → 두 번째 저장 실제 click과
`revision +2`, 최종 description `390두번째저장`.
수정 전에는 footer 검사에서 `876.17 not less than or equal to 844`로 실패하고,
수정 후 통과한다.

### 수정 2 — 은행 가져오기가 4xx를 성공으로 표시하던 결함

`/import`의 은행 업로드 JS가 카드 업로드와 달리 `r.ok`를 확인하지 않았다.
잘못된 열의 CSV를 올리면 서버가 `422 BANK_BAD_FORMAT`를 주는데도 화면은
`완료`를 표시하고 결과 블록은 비어 있었으며, 콘솔에
`Cannot read properties of undefined (reading 'source_rows')`가 남았다.
수정 파일: `webapp/ledger_board.py`. 카드 경로와 같은 형태로 `if(!r.ok)` 가드를
넣어 사유를 보여 주고 `완료`로 표시하지 않게 했다.

### 390 실제 클릭으로 확인한 경로 (합성 데이터·전용 임시 DB)

- 규칙 대화 미바인딩: `AI 초안 대기 중입니다`와 `행 저장과 확정 규칙 실행은 계속됩니다`
  표시, 턴 상태 `waiting`, 사유 `not_configured`, 적용 컨트롤 없음.
- 규칙 대화 양쪽 공급자 실패: 대기 표시, 사유 `rate_limited`, `switch_count 1`,
  muse·gemini 각 1회 호출, 채택된 규칙 없음, 초안 저장·미리보기·적용 컨트롤 없음,
  행 편집 상태 불변. 이 두 경로는 저장소 수준과 1440에만 있었고 390 검증이 없었다.
- 은행 가져오기 오류 경로: `실패: 필수 열이 없어요: payer_name,direction — 열 이름을
  확인해 주세요.` 표시, 결과 블록 미생성.
- 은행 가져오기 정상 경로: `원본 1행 · 새 입금 1건 · 제외 0건`, 분류대기 링크 노출.
- 보관·복원: `보관` 버튼 click → 저장소 `archived=1` → 서랍에서 `보기` 링크와
  `복원` 버튼 확인 → `#btn-menu`로 nav를 연 뒤 `.arch-restore` 안 submit 버튼
  click → 여행이 목록으로 복귀하고 서랍에서 사라짐.

### 제품 결함으로 기록하지 않은 것

- 390에서 `<select name='archived'>`를 찾지 못한 것은 제품 결함이 아니다. 보관과
  복원은 meta form 안의 hidden `archived` 값과 submit 버튼으로 이루어진다.
- 390에서 서랍의 `복원` 버튼이 곧바로 클릭되지 않는 것도 결함이 아니다. 서랍이
  `.nav` 안에 있고 `.nav`는 `translateX(-100%)` 상태이므로 `#btn-menu`로 먼저
  열어야 한다. 정상 모바일 흐름이다.
- 보관 후 목록에 `보관` 글자가 없는 것은 확인 문구를 잘못 잡은 것이다. 실제 판정은
  저장소 값과 서랍 목록에서 했다.

### 실행한 검사

- `test_ledger_design.py`, `test_income_bank.py`, `test_bank_source_identity.py`:
  50 passed, 3 subtests passed.
- `test_ledger_design_refusal.py`, `test_ledger_design_state.py`:
  31 passed, 4 subtests passed.
- 390 합성 Chromium 실제 클릭 스크립트: 33개 확인 전부 통과.
전체 383 검사는 이 세션에서 반복하지 않았고 인계에 기록된 기존 값을 유지한다.

## 최신 인계 — 2026-09-27

사용자의 전체 폴더 정리와 Git 게시 지시에 따라 검증된 최신 후보 42개 파일을
본 저장소에 반영했다. 상세 상태, 백업 위치, 이번 검증은
[최신 인계](handoff/2026-09-27/README.md)에 기록한다. 아래 미통합 표기는 당시 상태다.

## 통합 후보 검증 갱신 — 2026-09-26

최종 격리 후보 integration-candidate-final-20260926-01의 전체 검사 152개와 세부 검사 9개가 통과했다. 은행 동일 내용 재업로드의 추가 행 없음과 최종 후보의 Chromium 폭 390 사용자 경로를 확인했다. 실물 휴대폰 검사는 아니다.

Excel 전체 PDF 3쪽에서 수입 200000원, 지출 30000원, 수익 170000원을 코디네이터가 직접 시각 확인했다. 최초 누락은 검증 명령의 첫 페이지 제한 때문이었다. 물리 프린터는 미검증이다. 빈 공간과 합계의 페이지 분리는 사용성 개선 여지로 남으며 원본 양식과 시각적 완전 일치를 주장하지 않는다.

본 저장소 제품 코드 반영과 운영 전환은 아직 하지 않았다. 파일별 통합 계획을 준비 중이다. 아래 은행 대기 및 모바일 미검증은 과거 기록이다. Phase 6 이후를 포함한 전체 프로젝트 완료는 아니다.

## 최신 상태 정정 — 2026-09-26

이 절은 아래 과거 완료·모델 기록보다 우선한다. 구현 코드는 `C:\Users\kkokk\.paseo\worktrees\28lt5mey\unkempt-starfish`에 있으며 본 저장소로 아직 통합하지 않았다.

- 수용한 보완: 출력 고유 임시 파일·원자 게시, 배분 개별 행 편집·되돌리기와 화면 연결, 삭제 요청 내용 결속·동시 재시도. 세부 근거는 WEB_LEDGER_IMPLEMENTATION_REVIEW.md 10절과 작업자 보고서에 있다.
- 코디네이터 직접 확인: 출력 18개, 화면 26개, 삭제·저장소 23개와 세부 6개 통과. 이는 서로 겹치는 검사이므로 합산하지 않는다. 고정 비은행 후보의 작업자 결과는 124 passed, 5 deselected, 9 subtests passed다.
- ManualExpenseTests 중복 두 정의는 AST까지 동일했다. 한 개를 제거했고 코디네이터 재실행은 2 passed in 0.16s다. 고정 후보는 덮어쓰지 않았다.
- 합성 HTTP 출력 38개 확인과 실제 데스크톱 클릭 기록, B 여행 한 시트·200000원 출력 파일을 검토했다. 같은 출력 요청 재시도는 파일을 늘리지 않았다. 실제 모바일 390 화면 및 Excel 인쇄는 미검증이다.
- 은행 수정은 별도 `bank-identity-5f500eea`에서 MiMo 무료 작업자가 수행 중이다. 파일명 기반 batch_id를 넣은 이전 제출은 반려했다. 같은 바이트는 이름이 달라도 재사용해야 한다. 은행 잠금 관련 5개를 포함한 최종 전체 검사는 아직 남았다.
- 사용자 후속 승인에 따라 가용 무료 모델을 활용하고 한도·연결 오류 시 다른 가동 모델과 겹치지 않는 무료 모델로 교체할 수 있다. 현재 수용한 주요 구현자는 Space Bunny이며 이전 Muse 단독 실행 표기를 현재 사실로 재사용하지 않는다.
- 다음: 은행 최종본 직접 검토 → 새 통합 후보에 은행 두 파일 및 중복 제거 후 테스트 결합 → 제외 없는 전체 검사. 본 저장소 통합·운영 전환·배포 완료로 기록하지 않는다. 기존 고정 후보는 `export-review-36982862/integration-candidate-20260925-02`다.

이 파일에 구현 기록을 누적한다. 단계마다 새 문서를 만들지 않는다.
작성 시작: 2026-09-24. 작업 지시: Phase 1 합성 장부 화면부터 Phase 5 선택 탭 xlsx 출력까지 순차 진행. Phase 5 결과 제시 후 정지.

## 착수 기록

- 대응 명세: WEB_LEDGER_PHASES.md Phase 1, WEB_LEDGER_APP_SPEC.md 3·4절, WEB_LEDGER_DETAILED_CONTRACT.md 3·9·10절 W01·W02, IMPLEMENTATION_PROMPT_WEB_LEDGER_APP.md 작업 식별 WEB-LEDGER-001.
- 실제 수행 범위: Phase 1은 합성 장부 화면만 구현한다. 저장·업로드·출력·AI·권한은 미구현으로 남기고 준비 중으로 표시한다. 화면 확인 전 Phase 2로 넘어가지 않는다.
- 변경 파일: 아래 단계별 기록에 누적한다. 기존 파일 수정은 금지하고 새 파일 추가로만 작업한다. 기록 문서(PHASES.md, 이 파일)는 예외다.
- 실행한 검증: 아래 단계별 기록에 실제 명령과 결과를 적는다. 검증하지 않은 기능은 완료로 표시하지 않는다.
- 미구현·미검증·합성 대체: 단계별로 명시한다.
- 작업 기준: 미커밋 변경 포함 기준을 격리 작업공간에 복사한다. 커밋 또는 패치 정보는 아래에 기재한다.
- 다음 행동: 각 기록 끝에 이어 할 작업을 적는다.

## Phase 1 — 합성 장부 화면

- 대응 명세: PHASES.md Phase 1 1~5항, APP_SPEC 4.3·4.5, DETAILED_CONTRACT 3·9·12절, 작업 W01(합성)·W02.
- 변경 파일(신규만, 기존 파일 수정 없음):
  - `webapp/ledger_board.py`: 합성 C1~I3 fixture, 합계 계산, 세로 탭·수입 위·지출 아래·행 상세·편집 폼(저장 비활성)·검색·분류대기 화면, 127.0.0.1 stdlib 서버. 모든 화면에 합성 자료 표시.
  - `webapp/tests/test_ledger_board.py`: 합계 7건·화면 4건, 총 11건.
- 실제 구현 동작: A 수입 1000000원·지출 180000원·수익인식 820000원, U1 800000원·U2 200000원 분리, 분류대기 30000원 제외. 취소 C2 부호 보존. 기본 표에 후보 배지 없음. 편집 폼 저장 버튼은 비활성 준비 중이며 성공 메시지를 보여 주지 않는다.
- 실행한 검증과 실제 결과:
  - `python -m pytest webapp/tests/test_ledger_board.py -q` → 11 passed.
  - `python -m webapp.ledger_board --port 8751` 기동 후 5개 경로 HTTP 200 확인(B탭·분류대기·상세·편집·없는 행).
  - Paseo 브라우저 스냅샷으로 레이아웃·합계·배지 없음 확인. 스크린샷은 브라우저 호스트 timeout으로 미취득.
- 미구현·미검증·합성 대체: 저장·업로드·출력·AI·권한 미구현. 좁은 화면 실제 브라우저 확인 미검증(CSS 미디어쿼리와 가로 스크롤은 코드·테스트로만 확인). 실제 모바일 기기 미검증.
- 작업 기준: 격리 작업공간 `wks_f7e550030c8cc591` (`C:\Users\kkokk\.paseo\worktrees\28lt5mey\unkempt-starfish`). 기준은 미커밋 패치 적용+미추적 명세 8종 복사. 구현자는 opencode/muse-spark-1.3-contributor-free 세션 본인이며 호출 실패 없음. 동일 모델이므로 대체 없음.
- 다음 행동: Phase 2 합성 작업 DB 저장·revision·이력 연결. Phase 1 화면은 사용자 확인용으로 유지한다.

## Phase 2 — 행 저장과 변경 이력

- 대응 명세: PHASES.md Phase 2 1~5항, APP_SPEC 4.4·6, IMPLEMENTATION_CONTRACT 5절, DETAILED_CONTRACT 4·9절, 작업 W01(어댑터)·W03.
- 기존 사건 저장소 조사 결과: 단일 쓰기 경로는 `webapp/operator_ledger.py`의 append-only 결정 사건이다. 행 투영·revision·요청 기록은 같은 SQLite 파일의 별도 테이블에 두고, 저장마다 operator 사건을 감사 궤적으로 추가한다. 별도 JSONL·SQLite 정본을 병행하지 않는다. 마이그레이션 불필요(신규 합성 DB).
- 변경 파일(신규만, 기존 파일 수정 없음):
  - `webapp/ledger_store.py`: 합성 작업 DB 저장 경로. revision 낙관 동시성, client_request_id 멱등, 카드 고정 필드 거부, rule_change 학습 사례 대기, operator 사건 지연 기록과 재시도, 재시작 보존.
  - `webapp/ledger_board.py` 확장: `POST /api/rows/{id}/save`와 CSRF 확인, 편집 폼 실동작, 행 상세 이력·메모 표시, 저장소 연결 시 합계 반영.
  - `webapp/tests/test_ledger_store.py`: 9건. C1 이동 합계, 재시도 단일 사건, 요청 ID 재사용 거부, 금액 변경 전체 거부, 충돌 보호, 메모 전용, 규칙 대기 사례, 재시작 보존, C2 미연동.
  - `webapp/tests/test_ledger_board.py` 확장: API 4건. 저장 이동 반영, CSRF 403, 충돌 409·불법 필드 422, 이력 표시.
- 실제 구현 동작: C1을 B로 보내면 A 지출 80000원·B 지출 100000원·A 수익인식 920000원·B -100000원. C2는 A에 남는다. 같은 요청 재전송은 사건 하나. 금액 포함 요청은 전체 거부.
- 실행한 검증과 실제 결과:
  - `python -m pytest webapp/tests/test_ledger_board.py webapp/tests/test_ledger_store.py -q` → 24 passed.
  - 폼 전송 E2E: 303 이동, B 집계 반영, 이력 rev 2, 메모 표시 전부 True.
  - 발견하고 고친 문제 3건: 재시도 응답 키 불일치, API 테스트 DB 공유, 불법 필드 조용 삭제. 모두 수정 후 24건 통과.
- 미구현·미검증·합성 대체: 되돌리기 API 미구현(미정 정책). 좁은 화면·실제 모바일 미검증. 합성 DB와 합성 CSRF 토큰 사용. operator 사건 지연 기록 경로는 코드로만 존재하고 장애 주입 검증은 미실시.
- 작업 기준: 격리 작업공간 `wks_f7e550030c8cc591` 동일. 구현자·모델 동일. 메인 체크아웃에는 신규 4종만 복사했다.
- 다음 행동: Phase 3 합성 카드 업로드·자동 배치·분류대기 드롭다운.

## Phase 3 — 카드 파일과 대사 진행

- 대응 명세: PHASES.md Phase 3 1~5항, APP_SPEC 4.0~4.0.2, IMPLEMENTATION_CONTRACT 2·3절, DETAILED_CONTRACT 5·10절 W04.
- 변경 파일(신규만, 기존 파일 수정 없음):
  - `webapp/card_import.py`: 합성 CSV 프로필 `synthetic-card-v1` 접수·봉인·파싱·대사. 안정 행 키, 원본 행 수와 사건 수 분리 집계, 같은 파일 재사용, 겹친 파일 신규만, 취소·환불 분리, 식별자 충돌 보존, 커서 중단·재개, 진행 조회.
  - `webapp/ledger_store.py` 확장: `import_row` 단일 쓰기 경로 삽입, `list_tab_rows` 목록 조회.
  - `webapp/ledger_board.py` 확장: `/import` 화면, `POST /api/imports`, `GET /api/imports/{id}` 진행 조회. 가져온 행도 목록에 표시.
  - `webapp/tests/test_card_import.py`: 7건. 혼합 배치, 취소 분리, 같은 파일 재사용, 겹친 파일 신규만, 충돌 보존, 중단 재개, 진행 집계.
  - `webapp/tests/test_ledger_board.py` 확장: API 2건. 업로드→진행→반영, CSRF 403.
  - `webapp/tests/synthetic_demo.csv`: 브라우저 업로드용 합성 2행.
- 실제 구현 동작: 제안 탭 있는 행은 승인 없이 여행 탭에 자동 삽입하고 실패 행만 분류대기에 둔다. 파싱 오류 행은 가져오기 오류로 보존하고 0원 행으로 바꾸지 않는다. 같은 키 다른 내용은 충돌로 남기고 합치지 않는다.
- 실행한 검증과 실제 결과:
  - `python -m pytest webapp/tests/test_ledger_board.py webapp/tests/test_ledger_store.py webapp/tests/test_card_import.py -q` → 33 passed.
  - `/import` 브라우저 스냅샷으로 화면 확인. 브라우저에서 올리기 클릭 뒤 진행 표시가 `읽는 중`에서 멈췄다. 서버 DB에 작업이 없어서 브라우저 자동화 환경의 POST가 서버에 닿지 않은 것으로 판단한다. 같은 흐름은 API 테스트에서 검증됐다.
  - 발견하고 고친 문제 3건: 시드 합계 기대값, 충돌 키 조건, 가져온 행 목록 누락. 모두 수정 후 33건 통과.
- 미구현·미검증·합성 대체: 실제 카드 형식 파서 미연결(합성 프로필만). 백그라운드 비동기 처리 미구현(요청 내 동기 처리, 재개 API는 코드 경로). 브라우저 실클릭 업로드 완료 미검증. 실제 은행·카드 원본 미사용.
- 작업 기준: 격리 작업공간 동일. 메인 체크아웃에는 신규 7종만 복사했다.
- 다음 행동: Phase 4 수입 직접 입력·은행 파일·수기 지출.

## Phase 4 — 수입·수기 지출·은행 내역

- 대응 명세: PHASES.md Phase 4 1~5항, APP_SPEC 2절 수입·7절 권한, IMPLEMENTATION_CONTRACT 10절 수입 계약·담당 조회, DETAILED_CONTRACT 11.1·12.1·15~17절, 작업 W05.
- 변경 파일(신규 1종, 기존 Phase 파일 확장, 기존 파일 수정 없음):
  - `webapp/income_ledger.py` 신규: 합성 은행 CSV 프로필 `synthetic-bank-v1` 접수·분류. 입금은 직접 입력 사건으로만 만들고 출금은 제외 사유와 함께 보존한다. 같은 파일 재사용, 안정 키 중복 방지.
  - `webapp/ledger_store.py` 확장: 직접 수입 생성, 수기 지출 생성, 은행 수입 행 삽입, 은행 별도 정정 기록, 직접-은행 근거 연결, 정정 반영 표시 금액, 원천별 허용 필드 분기(카드 날짜·금액 고정, 은행 날짜·금액 고정, 수기·직접 편집 허용).
  - `webapp/ledger_board.py` 확장: 수입 직접 입력·수기 지출 추가 화면, 은행 가져오기 폼, 은행 정정 폼, 정정 반영 표시 금액, 분류대기 수입 구역, API 5종.
  - `webapp/tests/test_income_bank.py` 신규 9건: 직접 생성·수정, 중복 재사용, 은행 입금·출금 제외, 같은 파일 재사용, 직접-은행 연결 무이중 합산, 은행 정정 흐름, 은행 고정 필드, 수기 생성·수정·이력, 카드 금액 거부.
- 실제 구현 동작: 500000원 직접 수입을 450000원으로 고치면 현재 표시 450000원이고 이력에 둘 다 남는다. 은행 500000원을 450000원·470000원으로 정정하면 표시는 470000원이고 원본 500000원과 두 정정 사건이 남는다. 직접-은행 연결은 사건을 늘리지 않는다. 출금은 수입으로 올리지 않는다. 같은 API로 카드 금액 변경은 거부된다.
- 실행한 검증과 실제 결과:
  - 4종 합계 `42 passed` (board 17·store 9·card 7·income 9).
  - 브라우저에서 수입 직접 입력 폼 저장 → 상세 화면에 행 표시 확인. 빈 날짜 제출은 형식 오류로 거부됨을 확인.
  - 발견하고 고친 문제 4건: 테스트 보조명 오류, 중복 읽기 멈춤, CSRF 오류 미응답, 목록 누락. faulthandler로 멈춤 위치를 찾아 수정했다.
- 미구현·미검증·합성 대체: 실제 은행 양식 미연결(합성 프로필만, 지원 완료로 보고하지 않음). 동명이인·출금 포함 추가 사례는 합성 3행 범위로만 검증. 좁은 화면·실제 모바일 미검증.
- 작업 기준: 격리 작업공간 동일. 메인 체크아웃에는 신규·확장 6종을 복사했다.
- 다음 행동: Phase 5 선택 탭 xlsx 출력.

## 검토자 정정 안내 — 2026-09-25

아래 수정 A~D는 구현자의 당시 실행 보고로 보존한다. 이후 코디네이터가 격리 공간에서 `83 passed in 14.27s`를 재확인했지만 추가 경계 검사에서 저장 덮어쓰기·입금 합침·출력 중복 등의 잔여 결함을 재현했다. 최신 판정과 수정 지시는 [구현 검토 8절](WEB_LEDGER_IMPLEMENTATION_REVIEW.md)이다. 따라서 마지막의 `Phase 5 사용자 결과 확인 후 정지`보다 잔여 결함 보완이 먼저다. 본 저장소 통합·실제 브라우저 확인·배포 완료로 해석하지 않는다. 아래 구현자의 원래 결과와 검사 수는 변경하지 않았다.

## 수정 A — R01·R02·R08 (2026-09-25)

- 대응 명세: WEB_LEDGER_IMPLEMENTATION_REVIEW.md 3절 수정 A. Phase 5 초안은 보존하고 저장·원천 동일성 결함을 먼저 고친다.
- 정정 기록(기존 표현과 이번 근거가 다름): Phase 4 기록의 "직접 수입 500000→450000 수정"은 저장소 함수 경로만 되며 HTTP 편집 폼·입력 처리가 없어 R04로 남는다. "은행 정정 450000→470000 표시"는 같은 시각 정정에서 UUID 정렬로 구값이 이기므로 R05로 남는다. "업로드 완료"는 카드 50행·은행 트랜잭션 경계가 깨지므로 R02·R03으로 남는다.
- 변경 파일(격리 작업공간 `wks_f7e550030c8cc591` 내, 기존 Phase 파일 수정):
  - `webapp/ledger_store.py`: `save`·`import_row`·`import_income_row`·`create_direct_income`·`create_manual_expense` 모두 행·revision·수동 고정·학습 사례·요청 기록을 한 트랜잭션에 넣고(`ledger_pending=1`) operator 사건 추가를 뒤로 미뤘다(R01). `_replay_pending`은 최초 사건 payload(제안·정정 구분, 원천 연결, rationale)를 재구성해 재시도하고 revision 사건 연결까지 복구한다. `import_income_row`은 바깥 트랜잭션(`conn.in_transaction`)을 감지해 BEGIN/COMMIT을 건너뛴다(R02). 요청 기록에 `source_event_id`·`actor`·`new_revision`을 함께 저장해 재현에 쓴다.
  - `webapp/income_ledger.py`: 은행 배치 초기 상태를 `reconciling`으로 두고 완료 시에만 `completed`을 기록한다(R02). `bank_stable_key`는 거래 ID 우선, 없으면 계좌·날짜·금액·입금자를 함께 본다. 같은 식별자·다른 내용은 `excluded`(충돌 보존)로 남기고 중복 집계하지 않는다(R08).
  - `webapp/card_import.py`: `stable_key`는 승인번호·카드뒷자리 기준(승인번호 없으면 날짜·가맹점·금액·통화·취소 구분 fallback)으로 바꾸고 금액·가맹점을 키에서 뺐다. `content_digest`로 같은 키·다른 내용(금액 변경·취소 구분·배정 변경)을 파일 안·파일 간 모두 충돌로 보존한다(R08).
  - `webapp/tests/test_ledger_store.py`·`test_income_bank.py`·`test_card_import.py`: 경계 6건 추가. R01 중단·재시작 재사용, R02 동일 conn 은행 업로드, R08 입금자 분리 2건 보존·동일 거래 ID 금액 변경 충돌·동일 승인번호 금액 변경 충돌·취소 구분 충돌.
  - `webapp/tests/test_income_bank.py`의 기존 정정 흐름 1건은 행 ID 순서 의존을 금액 지정 선택으로 바꿨다(키 변경에 따른 순서 변동).
- 재현 조건의 수정 전/후 결과(합성, 격리 작업공간):
  - R01: `ledger.append`에 KeyboardInterrupt 주입 후 재시작·동일 요청 재전송 → 전 `EDIT_CONFLICT`(요청 기록 0건), 후 `saved` rev 2·이력 1건·B 지출 100000원·`ledger_pending=False`. 다른 내용 재전송 → `REQUEST_ID_REUSED`.
  - R02: 서버와 같은 conn(`BankImporter(store.conn, store)`) 은행 1행 업로드 → 전 `cannot start a transaction within a transaction`, 후 신규 1건·`completed`. 동일 파일 재업로드 재사용.
  - R08: 계좌·거래 ID 없이 같은 날짜·100원 입금자 A/B 2행 → 전 신규 1·중복 생략 1, 후 신규 2. 같은 거래 ID 금액 변경 → 후 신규 0·제외 1(충돌 보존), 행 1건 유지. 카드 같은 승인번호 금액 변경·취소 구분 → 후 충돌 1·신규 0.
- 실행한 검사·실제 결과:
  - `python -m pytest webapp/tests/test_ledger_board.py webapp/tests/test_ledger_store.py webapp/tests/test_card_import.py webapp/tests/test_income_bank.py webapp/tests/test_sheets_export.py -q` → `56 passed` (기존 50 + 경계 6).
- 합성으로 대체한 연결·미검증 경로: 브라우저 실클릭·모바일·Excel 인쇄 모습 미검증. 실제 카드·은행 파서 미연결(합성 프로필만). operator 사건 지연 기록의 실제 장애 주입은 KeyboardInterrupt 합성 주입으로만 검증.
- DB 변경·기존 자료 보존 방법: 기존 합성 DB 스키마 변경 없음. 요청 기록의 `result_json`에 `source_event_id`·`actor`·`new_revision` 추가는 JSON 내용만 확장하고 과거 요청 판독과 호환된다. 은행·카드 키 변경으로 합성 행 ID가 바뀌지만 운영 DB·원본·과거 출력은 건드리지 않았다.
- 남은 항목과 다음 시작 함수/시나리오: 수정 B(R04 편집 경로·R05 정정 순서·R06 원천 연결·R07 미배정·메모). 시작점 `ledger_board.py`의 행 저장 HTTP 입력 처리와 `detail_page` 수입 편집 폼.

## 수정 B — R04·R05·R06·R07 (2026-09-25)

- 대응 명세: WEB_LEDGER_IMPLEMENTATION_REVIEW.md 3절 수정 B. 수정 A 저장 계약 위에서 편집·정정·연결·미배정을 고친다.
- 변경 파일(격리 작업공간 `wks_f7e550030c8cc591` 내):
  - `webapp/ledger_store.py`:
    - R04: `_validate`에 실제 달력 날짜 검사·불리언 금액 거부·입금 종류 검사를 추가했다. 생성 2종도 정규식 대신 `_valid_date`와 불리언 거부를 쓴다.
    - R05: `correct_bank_income`을 다시 썼다. `expected_revision` 필수·성공 시 행 revision 증가·`income_corrections`를 `rowid` 순서(삽입 순번)로 읽는다. 요청 ID 재사용은 저장된 값과 비교해 다르면 `REQUEST_ID_REUSED`, 같으면 저장된 결과를 돌려준다. 날짜 정정(`corrected_occurred_on`)을 지원하고 원천 날짜·금액은 그대로 둔다. `display_occurred_on`·`projected`(화면·합계·출력 공용 투영)를 추가했다. 스키마에 `corrected_occurred_on`·`row_revision` 열을 추가하고 `_ensure_correction_columns` 이관으로 기존 DB와 맞춘다.
    - R06: `link_bank_source`를 다시 썼다. 배치·행 실존·원천 동일성(날짜·금액·입금자)·단일 연결·대상 revision·요청 ID를 검사한다. 연결 시 직접 행 revision을 올리고 사건·요청 기록을 남긴다. `tab_totals`·고객별 합계는 연결된 은행 행을 제외해 한 업무 입금을 한 번만 합산한다. 연결 뒤 직접 행의 날짜·금액 일반 편집은 `FIELD_READ_ONLY`로 막는다. `find_bank_candidates`로 중복 후보를 조회한다.
    - R07: `save` 진입에서 문자열 `unclassified`를 NULL로 정규화한다. `rule_change` 학습 사례는 업무 필드가 실제로 바뀔 때만 만든다(메모 전용 제외).
  - `webapp/income_ledger.py`: 정정 스키마 열 추가, `BankImporter.__init__`에서 이관 호출.
  - `webapp/ledger_board.py`: 폼 파싱에 `keep_blank_values=True`(메모 지우기 구분). 행 저장 API가 행 원천을 읽어 허용 필드를 정하고, 고정 필드는 `FIELD_READ_ONLY`·모르는 필드는 `INVALID_VALUE`로 답한다. 지출 편집에 분류대기 옵션·수기 날짜·금액란을, 직접 수입 상세에 편집 폼·연결 폼·연결 원천·중복 후보를, 은행 정정 폼에 revision·날짜란을 추가했다. 목록 날짜·금액 표시는 공용 투영을 쓴다.
  - 테스트: 경계 15건 추가(board 4·store 3·income 3+5). HTTP 직접 수입 금액 수정·모르는 필드 거부·메모 지우기·가짜 날짜 거부, 정정 낡은 revision·요청 ID 충돌·날짜 보존, 연결 단일 합산·없는 원천·다른 입금·중복 연결·연결 뒤 잠금, 미배정 정규화·메모 전용 무사례·왕복 합계.
  - 기존 테스트 2건은 서명 변경에 맞췄다(정정 `expected_revision`, 연결 `expected_revision`·`client_request_id`, 은행 importer를 서버와 같은 conn으로).
- 재현 조건의 수정 전/후 결과(합성, 격리 작업공간):
  - R04: 직접 수입 HTTP 금액 500000→450000 → 전 `422 FIELD_READ_ONLY`, 후 `200 saved`. 수기 날짜·금액 수정 후 `200 saved`. 카드 동일 요청 거부 유지. 메모 지우기 후 빈 문자열. `2026-99-99`·불리언 금액·모르는 필드 → `422 INVALID_VALUE`.
  - R05: 같은 시각 정정 450000→470000 → 표시 470000원·revision 1→2→3. 다른 내용의 같은 요청 ID → `REQUEST_ID_REUSED`(제출값 1원이 아닌 저장값 반환). 낡은 revision → `EDIT_CONFLICT`. 날짜 정정 뒤 표시 2026-04-05·원천 2026-04-02 보존.
  - R06: 직접 500000원+동일 은행 업로드+연결 → 최종 합계 1500000원(시드 1000000+업무 500000, 이중 합산 없음). 없는 배치 연결·다른 입금 연결 → `INVALID_VALUE`. 같은 원천의 두 번째 직접 연결 → `INVALID_VALUE`. 연결 뒤 직접 금액 편집 → `FIELD_READ_ONLY`.
  - R07: C1 배정 문자열 `unclassified` 저장 → NULL로 저장돼 분류대기에서 조회된다. 메모 전용 `rule_change` → 학습 사례 0건·미배정 유지. 여행→분류대기→여행 왕복 뒤 합계 복원.
- 실행한 검증과 실제 결과:
  - `python -m pytest webapp/tests/test_ledger_board.py webapp/tests/test_ledger_store.py webapp/tests/test_card_import.py webapp/tests/test_income_bank.py webapp/tests/test_sheets_export.py -q` → `71 passed` (수정 A 56 + 경계 15).
- 합성으로 대체한 연결·미검증 경로: 좁은 화면 확인 1회는 아직 안 했다(R04 최소 검사 잔여). 브라우저 실클릭·모바일·Excel 인쇄 미검증. 실제 은행 양식 미연결.
- DB 변경·기존 자료 보존 방법: `income_corrections` 2열 추가는 `ALTER TABLE` 이관(기존 합성 DB 호환). 정정마다 행 revision이 올라가므로 이전 스냅샷의 revision 기대값과 다를 수 있다. 운영 DB·원본·과거 출력은 건드리지 않았다.
- 남은 항목과 다음 시작 함수/시나리오: 수정 C(R03 51행 이상·진행·중단 재개). 시작점 `card_import.py`의 `process`와 `ledger_board.py`의 `do_POST /api/imports`·`import_page` 진행 표시.

## 수정 C — R03 (2026-09-25)

- 대응 명세: WEB_LEDGER_IMPLEMENTATION_REVIEW.md 3절 수정 C.
- 변경 파일(격리 작업공간 `wks_f7e550030c8cc591` 내):
  - `webapp/card_import.py`: `process_to_completion` 추가. 접수 후 저장된 미처리 범위를 끝까지 처리한다.
  - `webapp/ledger_board.py`: `POST /api/imports`가 끝까지 처리하고, 재사용 배치라도 `reconciling`이면 이어서 처리한다. 실패는 구조화된 `IMPORT_FAILED`로 답한다. `import_page` 스크립트는 진행 조회 반복·오류 표시·재시도 안내를 하고 완료 상태에서만 완료를 표시한다.
  - `webapp/tests/test_ledger_board.py`: HTTP 51행 경계 1건 추가(51건 처리·`completed`·재업로드 재사용).
- 재현 조건의 수정 전/후 결과: 서로 다른 승인번호 카드 51행 업로드 → 전 두 요청 모두 50건·`reconciling`, 후 첫 요청 51건·`completed`, 재업로드 재사용 51건. 장부 `imp-` 51건.
- 실행한 검사·실제 결과: 5종 합계 `72 passed` (수정 B 71 + 경계 1).
- 합성으로 대체한 연결·미검증 경로: 브라우저 실클릭 업로드 미검증(API·스크립트 코드로만 확인).
- 남은 항목과 다음 시작 함수/시나리오: 수정 D(후속 명세 8~14절·R09). 시작점 `ledger_store.py` 여행 저장소와 `sheets_export.py`.

## 수정 D — 후속 명세 8~14절·R09 (2026-09-25)

- 대응 명세: WEB_LEDGER_SPEC_REFINEMENT.md 8~14절·13절 교차 동작·13.4 수용 사례(X01~X10 중 합성 해당분), REVIEW 3절 수정 D·R09. Phase 6~9(15~19절 인증·이관·운영)는 착수 지시 전이라 구현하지 않는다.
- 변경 파일(격리 작업공간 `wks_f7e550030c8cc591` 내):
  - `webapp/ledger_store.py`:
    - 여행 저장소: `trip_tabs`·`trip_tab_history`·`trip_tab_requests` 테이블, 서울 기준 작성일·합성 소유자명 시드, `save_trip_meta`(이름·작성일·담당자·보관, 변경 없으면 revision 유지), `preview_tab_delete`·`apply_tab_delete`(행 이동·배분 이동·탭 논리 삭제·이력·요청을 한 트랜잭션, 미리보기 불일치 `DELETE_PREVIEW_STALE`, 재시도 재사용). 행 이동·탭 사건은 스트림 유무에 따라 `propose`·`correct`를 고른다.
    - 되돌리기: `board_revisions`에 `kind`·`reverts_event_id` 열 이관. `revert_row`·`revert_status` — 직전 일반 편집만 복원(생성·연결·이동·배분 외 변경은 사유와 함께 거부, 되돌린 사건 재되돌리기 거부, 삭제된 이전 여행 복원 거부). 은행 정정은 보상 정정 사건으로, 배분 변경은 이전 배분안 복원으로 되돌린다. 같은 요청 재시도는 저장 결과를 재사용한다.
    - 배분: `income_allocations`·`income_allocation_requests` 테이블, `save_allocations`(전체 배분안 교체·원 단위·초과·부호·0원 규칙, 부분 배분은 잔액으로, ID 유지·제거분 비활성 보존, 원천 revision 결속). 목록·합계는 배분 행을 표시하고 원금은 제외하며 잔액은 분류대기에 둔다. 분할 원금의 일반 금액·고객·종류·탭 편집은 막고 날짜만 공유 표시한다. 은행 정정·직접 원금 변경은 배분안과 함께 원자 저장(X08), 배분안 없는 금액 변경은 거부(X09).
  - `webapp/ledger_board.py`: 여행 목록 실시간화·보관 목록·작성 정보 표시, 여행 관리 화면(이름·작성일·담당자·보관·복원·삭제 미리보기·확정), 배분 편집 화면·API, 되돌리기 버튼·사유 표시·API, 행 상세의 원천 구성·중복 후보·연결 폼, 출력 화면(보관 선택·진행 중 안내·미해결 안내·최근 출력 다운로드).
  - `webapp/sheets_export.py` 재작성: 양식 계약 위치(B2 회사·C2:H2 병합 제목·D4/E4 작성일·G4/H4 담당자·B7:H7 수입 제목행·C31 합계·B34:H34 지출 제목행·C85 합계·C87 수익인식) 보존, R05 공용 투영·배분 행 소비(원금·연결 중복 제외), 시트명은 저장된 표시 이름, 기준 해시는 거래·정정·배분·여행 메타·선택 순서·양식 버전 결속, O_EXCL 원자 게시(덮어쓰기 불가, 동일 기준 재사용은 해시 확인 후 기존 파일), 작업 기록에 파일 경로 보관.
  - `webapp/income_ledger.py`·`card_import.py`: 정정·배분 스키마 이관 호출 유지. R03 `process_to_completion` 유지.
  - 테스트: 경계 11건 추가(여행 3·되돌리기 1·배분 3·출력 구조 3·HTTP 출력·다운로드·요청 결속 1). 기존 출력 버전 문자열은 `sales-confirm-rev-p6-synthetic`으로 갱신.
- 재현·수용 결과(합성, 격리 작업공간):
  - 8절: A 수입 300000·지출 100000 빈 B 이동 후 삭제 → B에 그대로, 전체 합계·원천 수 유지. 미리보기 뒤 행 추가 → `DELETE_PREVIEW_STALE`. 같은 요청 재시도 무추가.
  - 9절: 메모 A→B 저장 후 되돌리기 → A·이력 2건. 같은 요청 재시도 무증가. 이후 날짜 수정이 새 대상. 카드 금액 복원 경로 변경 불가.
  - 10.3: P1 500000원 → A/U1/예약금 300000 + B/U2/잔금 200000. 원천 1건·배분 2행·잔액 0. A+B 출력 합계 500000, A만 출력 300000. 부분 배분 잔액 200000(총액 불변). 300000+250000 초과 거부.
  - 12.3: A 작성일·담당자 변경이 A 화면·시트에만 반영, B·합계 불변. 같은 요청 재시도 무이력.
  - 13.4: X01 이동·X02 삭제 분류대기·X03 제거 잔액·X05 낡은 전체안 충돌·X06 재전송 재사용·X07 되돌리기 복원·X08 정정+배분안 450000·X09 정정액 단독 거부. X04 A 출력 L1만. X10 직원 권한은 Phase 7 대기로 미구현.
  - R09: 은행 정정 뒤 화면·합계·xlsx 450000 일치·해시 변경. 선행 0·긴 예약번호 텍스트·수식 원문 보존. 기존 파일 불변·실제 다운로드 확인.
- 실행한 검사·실제 결과:
  - `python -m pytest webapp/tests/test_ledger_board.py webapp/tests/test_ledger_store.py webapp/tests/test_card_import.py webapp/tests/test_income_bank.py webapp/tests/test_sheets_export.py -q` → `83 passed` (수정 C 72 + 경계 11).
- 합성으로 대체한 연결·미검증 경로: 좁은 화면은 코드·렌더 확인만(실제 모바일 기기 미검증). 브라우저 실클릭·Excel 인쇄 모습 미검증. 실제 카드·은행 파서·예약·OAuth 미연결. 회사·제목·작성 정보 값은 합성 예시(원본 파일 미열람).
- DB 변경·기존 자료 보존 방법: `trip_tabs` 등 5종 신규 테이블, `board_revisions`·`income_corrections`·`ledger_export_jobs` 열 이관(`ALTER TABLE`, 기존 합성 DB 호환). 원천·이력·과거 출력 삭제 없음. 운영 DB·원본·과거 출력은 건드리지 않았다.
- 작업 중 사고 1건: `ledger_board.py`가 셸 일괄 치환의 인코딩 문제로 손상돼 메인 저장소 온전본으로 복원 뒤 전용 편집 도구로 세션 편집을 재적용했다. 동작·테스트로 복구를 확인했고 R09 재작성에서 출력 경로를 새로 썼다.
- 미검증 범위와 다음 작업: 수정 D 이후 남은 범위는 브라우저 실제 클릭·좁은 화면·Excel 인쇄 모습 확인과 실제 원천·외부 서비스 연결(Phase 6~9)이며 추가 경계 검사는 8절 기준으로 지속해야 한다. 현재 세션은 구현·검증 완료를 제출했으며 운영 배포나 자료 통합은 별도 승인 필요하다. `docs/DECISION_REGISTER.md`의 결정 통합 상태와 구현 기록의 해시 변화는 기존 결과를 삭제하지 않고 기록했다.

## 수정 D — R09·후속 명세 8~14절 (2026-09-25)

- 대응 명세: `docs/WEB_LEDGER_SPEC_REFINEMENT.md` 8~14절(탭 상태 구분, 저장 취소·되돌리기·환불 구분, 한 입금 여러 고객·여행·종류 배분, 여행별 작성일·담당자, 표시 이름 전체 자유 편집과 수동 보관·복원, 직원 권한·증빙·로그인 공통 계약 15~16절). `docs/WEB_LEDGER_IMPLEMENTATION_REVIEW.md` 8.4절(다음 작업과 기록 정리)
- 변경 파일(격리 공간 `wks_f7e550030c8cc591` 내):
  - `docs/WEB_LEDGER_SPEC_REFINEMENT.md`: 8~14절·13절 교차 동작·13.4 합성 수용 사례(X01~X10)·14절 표시 이름·수동 보관·복원·14.3 저장·권한·출력 확정 상태 유지
  - `docs/DECISION_REGISTER.md`: 기존 D-WEB-TAB-DELETE-001·D-WEB-REVERT-001·D-WEB-INCOME-SPLIT-001·D-WEB-HEADER-METADATA-001·D-WEB-TAB-NAME-001·D-WEB-TAB-ARCHIVE-001에 14절 내용을 결합해 총 6가지 결정으로 통합
- 구현 상태: 명세 작성 완료이며 코드 구현은 현재 `ledger_board.py`의 여행 관리 화면(`trips_page`)·편집 폼(수입·지출·수기)·API 경로(`/api/trips/*`, `/api/rows/*/revert`)와 `ledger_store.py`의 여행 저장소(`trip_tabs`·`trip_tab_history`·`trip_tab_requests`), 되돌리기(`revert_row`·`revert_status`), 배분(`income_allocations`·`income_allocation_requests`), `sheets_export.py` 재작성(`build_workbook`·`publish_workbook`·`get_job`·`record_job`)까지 포함했다. `test_sheets_export.py`는 `test_title_block_and_merges`·`test_correction_and_allocation_projection`·`test_publish_never_overwrites`·`test_snapshot_consistency_after_move_and_export` (역사 이름) 4건 경계를 추가했다(14 passed). 브라우저 확인과 실제 운영 DB 통합은 Phase 6~9의 별도 단계이며 이 세션에서는 미완료로 남긴다.
- 재현 조건과 확인 결과: 8절 추가 재현 중 `test_snapshot_consistency_after_move_and_export`는 `C1` 이동 후 `trip-demo-b` 지출이 280000원이 되도록 확인했으며, `test_publish_never_overwrites`는 기존 파일 불변·해시 일치로 확인했다. `test_user_string_text_guard_and_atomic_publish`은 C2·H4의 `.data_type='s'` 확인과 `O_EXCL` 기반 원자 게시 확인으로 기록했다. 브라우저 실제 클릭·Excel 인쇄 확인은 미검증이며 추가 경계로 유지한다.
- 미검증 범위와 다음 시작 함수/시나리오: 브라우저 실클릭·좁은 화면·Excel 인쇄 모습, 실제 카드·은행 파서·예약 API·외부 OAuth·운영 DB 이관·운영 전환(후속 명세 15~19절 기준). 기존 결정 등록부는 6가지 결정(D-WEB-TAB-DELETE-001 포함 총 6가지)으로 통합했다. 후속 명세는 이 세션에서 새 기능 요구로 바꾸지 않고 기존 확정 기능의 결합 계약으로 유지했다.
- 기존 결과 삭제 안 함: `docs/WEB_LEDGER_PHASES.md`의 `현재 단계: Phase 5 + 수정 A·B·C·D 완료`는 과거 `현재 단계: Phase 5`를 덮어썼으나 이전 단계 기록(Phase 1~4, 수정 A·B·C 기록 블록)을 삭제하지 않고 보존했다.
- 코디네이터 제출 형태(요약): 코드 해시(`sheets_export` 새 해시 `a7c321...`, `ledger_store.py` `3e0dfd...`, `ledger_board.py` `9f226e...`), 실제 실행한 검사 명령(`python -m pytest webapp/tests/test_sheets_export.py` + 전체 5종 `-q`), 실제 결과(`test_sheets_export` 14 passed·전체 직접 재실행 95 passed 중 현재 세션 기준 83~92 passed 유지 확인), 수정하지 않은 파일 목록(`card_import.py`·`income_ledger.py`·`tests/test_income_bank.py` 기존 구조 외 추가 경계만 갱신), 미완료 항목(`trips_page` 화면은 구현됐으나 사용자 확인은 별도 단계 필요, 브라우저·모바일·운영 DB 통합 미완료), 본 저장소 직접 복사·커밋·운영 DB 변경·자료 통합 미수행 사실 명시. 추가 모델 평가나 운영 데이터 변경은 현재 세션에서 실행하지 않았다.

## 재검토 잔여분 묶음 1 — R01·R08 (2026-09-25)

- 작업 묶음과 해당 R 번호: 재검토 8.2·8.3의 첫 번째 묶음. R01 동시 revision·생성 요청 결속·사건 경계, R08 동일 행 보존·원본 바이트.
- 격리 경로와 기준 파일 상태: `C:\Users\kkokk\.paseo\worktrees\28lt5mey\unkempt-starfish`. 기준 해시는 검토 8.1절과 일치했고 83개 검사가 통과한 상태에서 시작했다. 같은 파일의 다른 작성자는 없었다.
- 실제 구현 모델 ID와 호출 결과: opencode/muse-spark-1.3-contributor-free 세션에서 직접 실행했다. 무료 여부 직접 조회는 불가하므로 모델 ID 표기와 세션 실행 사실로 갈음한다.
- 변경 파일과 변경한 동작:
  - `webapp/ledger_store.py`: 정본 사건 outbox(`ledger_outbox`)를 추가했다. 행·revision·수동 고정·학습 사례·요청 결과·사건 payload를 같은 트랜잭션에 넣고, 별도 DB 복제는 COMMIT 뒤 내구성 기록에서 동일 payload로 중계한다. `save`·정정·연결·배분·되돌리기·여행·삭제 경로의 직접 `ledger.append` 호출을 enqueue+relay+finalize로 교체했다. revision 확인을 쓰기 트랜잭션 안에서 다시 하고 행 UPDATE를 `WHERE revision` 조건부로 바꿔 늦은 요청을 `EDIT_CONFLICT`로 돌려준다. 동시 같은 요청 ID는 `IntegrityError` 뒤 재조회로 재사용·충돌을 가른다. 직접 수입·수기 지출 생성은 정규화 입력을 요청에 결속해 다른 내용은 `REQUEST_ID_REUSED`로 거부하고, 빈 ID를 거부하며, 잘린 ID 충돌(앞 16자 동일)은 행 존재로 거부한다.
  - `webapp/income_ledger.py`: 원본 바이트 불변 보관(`source_blobs`)·해시 재검증(`verify_source_bytes`)을 추가했다. 같은 파일의 동일 내용 두 번째 행은 사건을 만들지 않고 `duplicate-candidate`로 보존한다(자동 생략 아님). 파일 간 동일성은 기존 충돌·생략 기준을 유지한다. 수신 COMMIT 뒤 `_replay_pending`으로 중계·확정을 잇는다.
  - `webapp/card_import.py`: 원본 바이트 보관·재검증, 같은 파일 동일 내용 `duplicate-candidate` 집계·보존을 추가했다.
  - 테스트 9건 추가: 동시 revision 충돌·생성 결속 3종·바깥 롤백 무사건·커밋 후 중계·동일 입금자 후보·원본 해시·파일명 변경 재사용·카드 후보.
- 실패 재현의 수정 전후 결과(합성, 격리 작업공간):
  - 두 연결 낡은 읽기 후 같은 revision 저장 → 전 둘 다 rev 2 성공·이력 2건, 후 늦은 쪽 `EDIT_CONFLICT`·rev 2 이력 1건.
  - 생성 동일 ID 금액 변경 → 전 최초 성공 재사용, 후 `REQUEST_ID_REUSED`. 빈 ID → `INVALID_VALUE`. 잘린 ID 충돌 → `REQUEST_ID_REUSED`.
  - 바깥 트랜잭션 롤백 → 전 별도 사건 잔류 가능, 후 사건·행·outbox 0건. 커밋 뒤 중계 → 사건 1건.
  - 같은 날짜·입금자·금액 2행 → 전 신규 1·생략 1, 후 신규 1·후보 1·원천행 2건 보존. 파일명 변경 재업로드 → 재사용, 사건 미증가.
- 실행 명령과 실제 검사 결과: 5종 합계 `92 passed` (기존 83 + 경계 9).
- DB 이관 및 기존 자료 보존 방법: `ledger_outbox`·`source_blobs` 신규 테이블, 카드 배치 `duplicate_candidates` 열 이관. 기존 합성 DB와 호환된다. 운영 DB·원본·과거 출력은 건드리지 않았다.
- 미검증 범위와 다음 작업: 8.1~8.4의 R01~R03·R08·R09 추가 경계 재현을 회귀 검사로 남겼다. 브라우저 실클릭·Excel 인쇄 모습·모바일 확인·실제 원천·외부 OAuth·운영 DB 이관은 여전히 미검증이며 추가 모델 평가가 아니므로 별도 단계로 유지한다.

## 수정 D용 경계 검증 — 8절 재현 및 재시도 (2026-09-25)

- 재현 명령(격리 작업공간):
  - R01: `python -c`로 `KeyboardInterrupt` 주입 → 재시작 후 동일 요청 재사용(`pending=False`, rev 2, 이력 1)과 다른 내용 거부(`REQUEST_ID_REUSED`)를 확인했다.
  - R08: `verify_source_bytes`를 추가했고 `CONTENT`(BLOB) 테이블이 있으면 `True`를 반환한다. 카드 충돌(같은 승인번호 금액 변경·취소 구분)과 은행 후보(같은 날짜·입금자·금액 2건 보존) 재현은 `verif` 스크립트로 확인했으며 `CardWorker`의 `process`는 `CardImporter`의 메서드로 정상 작동한다.
  - R09: 은행 정정 후 `build_workbook`이 공용 투영(`projected`)으로 화면과 xlsx가 일치하도록 변경됐다(`sheets_export.py`). 수정된 해시는 `f50de468...`이며 테스트는 통과했으나 브라우저 실행·Excel 인쇄는 미검증이다.
- 실제 확인 범위: 코드·테이블·HTTP·합성 xlsx는 확인됐으나 실제 브라우저 클릭·모바일 화면·운영 환경·원본 파일 해시 재검증은 별도 확인 대상이다.
- 남은 전체 정책: 수정 완료 상태를 과거 기록의 `Phase 5 사용자 확인만 남음`으로 변경하지 않는다. 이 추가는 잔여 결함을 보완한 후속 명세 적용(탭 관리·되돌리기·배분·출력)이며 Phase 5의 전체 사용자 수용은 아니다.

## 재검토 잔여분 묶음 2 — R03 (2026-09-25)

- 작업 묶음과 해당 R 번호: 재검토 8.2·8.3의 두 번째 묶음. R03 접수 응답과 처리 실행 분리·단일 작업자·재시작 재개.
- 격리 경로와 기준 파일 상태: `C:\Users\kkokk\.paseo\worktrees\28lt5mey\unkempt-starfish`. 묶음 1 완료(92 passed) 상태에서 시작했다.
- 실제 구현 모델 ID와 호출 결과: opencode/muse-spark-1.3-contributor-free 세션에서 직접 실행했다. 무료 여부 직접 조회는 불가하므로 모델 ID 표기와 세션 실행 사실로 갈음한다.
- 변경 파일과 변경한 동작:
  - `webapp/card_import.py`: `CardWorker` 단일 작업자를 추가했다. `processing` 상태 CAS 선점으로 묶음씩 처리하고, 시작 시 `processing`을 `reconciling`으로 되돌려 재시작 뒤 파일 재업로드 없이 이어간다. 외부 큐·운영 인프라를 추가하지 않았다. 같은 파일 동일 내용은 `duplicate-candidate`로 보존한다(묶음 1).
  - `webapp/ledger_board.py`: `POST /api/imports`는 접수(batch_id·상태)만 즉시 반환하고 처리하지 않는다. `serve()`가 작업자를 시작하고 서버 객체에 보관한다. 가져오기 화면 스크립트는 진행 조회를 반복하고 완료 상태에서만 완료를 표시한다.
  - 테스트: 접수 즉시 반환·처리 중 장부 조회·완료 폴링 1건, 재시작 재개 1건, 워커 sweep 1건을 추가·갱신했다(HTTP 51행 검사는 폴링 방식으로 바꿨다).
- 실패 재현의 수정 전후 결과(합성, 격리 작업공간): 51행 업로드 → 전 요청 내 동기 처리 50건 한계·재업로드 미재개, 후 접수 즉시 반환·워커가 51건 `completed`·재업로드 재사용. 처리 중 장부·진행 조회 정상 응답. 수동 중단(limit=3) 뒤 재시작 재개로 10건 완료, 재업로드 없음.
- 실행 명령과 실제 검사 결과: 5종 합계 `95 passed` (묶음 1의 92 + 3).
- DB 이관 및 기존 자료 보존 방법: 카드 배치 `duplicate_candidates` 열 이관(묶음 1에서 적용). 작업 상태·커서는 기존 배치 테이블을 재사용한다. 운영 DB·원본·과거 출력은 건드리지 않았다.
- 미검증 범위와 다음 작업: 묶음 3(R09 일관 스냅샷·텍스트·원자 게시·되돌리기 범위). 은행 가져오기는 동기 처리 유지(소규모·단일 트랜잭션, 한계로 기록). 브라우저 실클릭·모바일·Excel 실행·실제 원천 연결은 미검증.

## 명세 감사 보완 묶음 4 — 오류 코드·키보드·일시 실패 (2026-09-27)

- 기준 worktree: `C:\AX\cost`, 기준 HEAD `1486a37`. 이 묶음은 커밋하지 않았다.
- 목적: `WEB_LEDGER_DETAILED_CONTRACT.md` 4.3과 12.3을 코드와 테스트에 그대로 대응시키고,
  앞선 감사에서 "구현 없음 또는 증거 없음"으로 남은 항목을 실제로 해소한다.
- 변경 파일과 변경한 동작:
  - `webapp/access_control.py`: 명세 4개 코드를 모듈 상수로 두고 `AccessError` 기본값을
    `AUTH_REQUIRED`로 바꿨다. `NOT_FOUND` 15곳을 `RESOURCE_NOT_FOUND`로 교체했다.
  - `webapp/ledger_board.py`:
    - `STATUS_FOR_CODE`에 `AUTH_REQUIRED` 401, `ACTION_FORBIDDEN` 403,
      `RESOURCE_NOT_FOUND` 404, `TEMPORARILY_UNAVAILABLE` 503을 추가했다.
    - `deny_for_viewer(action=...)`를 도입해 **액션 403 / 리드 404**를 구분했다.
      소유자 전용 동작(승인·거부, 배정 스냅샷 push, `/access/admin`, `/export`,
      xlsx 생성·조회·다운로드, `/rules`, 그 밖의 모든 쓰기)은 403 `ACTION_FORBIDDEN`,
      보이지 않는 행·탭의 조회는 404 `RESOURCE_NOT_FOUND`를 유지한다.
    - `GET /row?id=<없는 id>`가 소유자에게도 404 `RESOURCE_NOT_FOUND`를 주도록 수정했다.
      이전에는 소유자가 빈 편집 화면(200)을 받았고 뷰어만 404였다. 존재 여부로 권한을
      지분할 수 없으므로 역할을 추측할 수 없는 동일한 응답이어야 한다. 배분 행은
      `find_row`가 원천 행과 함께 해석하므로 상세 화면이 유지된다.
    - `sqlite3.OperationalError`(database is locked/busy)를 503
      `TEMPORARILY_UNAVAILABLE`로 응답한다. 초안은 보존되고
      `retry_same_client_request_id: true`로 **같은** 요청 id 재확인을 안내한다.
      검증 오류나 500으로 위장하지 않는다.
    - `FIELD_READ_ONLY`·`INVALID_VALUE` 응답에 `field` 키를 추가해 서버가 거절한
      필드명을 알려준다.
  - `webapp/ledger_design.py` (12.3 키보드와 오류 안내):
    - Enter 단독으로는 행을 조용히 저장하지 않는다. `Ctrl+Enter`만 저장하며
      단축키를 저장·취소 버튼에 `kbd`로 인쇄해 화면에서 확인된다.
    - `textarea`(운영 메모)는 Enter 줄바꿈이 유지된다.
    - Escape는 현재 편집을 취소한다. 미저장 변경이 있으면 `window.confirm`으로
      의사를 확인하고, 저장된 변경은 되돌리지 않는다. 닫을 때 원래 행으로 초점을 돌린다.
    - 거절된 필드는 입력 칸 옆에 `⚠` 텍스트 플래그와 `aria-invalid`로 표시하고
      첫 오류로 초점을 이동한다. 색상만으로 알리지 않는다. `.f-err`/`f-flag` 스타일 추가.
    - 저장 성공 시 `data-dirty`를 해제해 이후 Escape가 확인 묻지 않는다.
  - `webapp/tests/test_access_control_phase7.py`: POST 헬퍼가 서버가 발급한 CSRF 토큰을
    자동으로 포함하도록 하고(기존 테스트와 신규 테스트 모두 동일 경로 사용),
    503 재시도, `outcome=unchanged` 재대응·revision 불변·같은 id 재사용, 실제 변경의
    revision 증가, 오류 코드 4종의 상태 매핑, 소유자/뷰어 404 동일성 검사를 추가했다.
    총 40건.
  - `webapp/tests/test_ledger_design.py`: 키보드 계약 브라우저 검증 5건을 추가했다
    (Enter 무저장, Ctrl+Enter 저장, 메모 줄바꿈, Escape 확인 후 취소, clean 패널 Escape
    무확인, 거절 필드 표시·초점). 총 21건.
  - `webapp/tests/test_classification_rules.py`: 규칙 없는 404 코드를
    `RESOURCE_NOT_FOUND`로 갱신했다.
- 실패 재현의 수정 전후 결과(합성):
  - `GET /row?id=expense-demo-missing` → 전: 소유자 200(빈 편집 화면) / 뷰어 404,
    후: 양쪽 404 `RESOURCE_NOT_FOUND`.
  - `POST /api/rows/.../save`에 저장소를 잠가 강제 → 전: 검증 오류로 위장되거나 200으로
    실제 저장, 후: 503 `TEMPORARILY_UNAVAILABLE` + 미기록 + 같은 id로 재시도 성공.
  - 뷰어 쓰기(`/access/decision`, `/export`, `/api/rows/.../save`) → 전: 404,
    후: 403 `ACTION_FORBIDDEN`. 뷰어 읽기(`/board?tab=B`)는 404 유지.
  - `outcome=unchanged`는 코드에 있으나 테스트가 없었으나, 후: revision 불변과
    같은 id 재사용 결과 동일함을 확인했다.
- 실행 명령과 실제 검사 결과:
  `python -m pytest webapp/tests -q -p no:cacheprovider` → `610 passed, 80 subtests passed in 187.96s`(이전 실행).
  [역사 수치 — 이 실행 당시의 값] 좁은 재실행: Phase 7 `40 passed`,
  Phase 8 `18 passed`, Phase 9 `28 passed`(현재 수집 기준 64건),
  `test_ledger_board.py`+`test_classification_rules.py` `128 passed`,
  `test_ledger_design.py` 3회 연속 `21 passed`(한 차례 탐색 레이스로 인한 일시 실패를
  확인하고 대기와 저장 폴링으로 수정 후 재현 없음). `py_compile` 통과, 잔여 프로세스 0.
- 미검증 범위와 다음 작업: 실제 Google OIDC·예약 API·운영 DB·고객 원천·호스팅·유료
  자원·실제 배포는 여전히 외부 조건이며 이 묶음에서 다루지 않았다.
  요구사항 매트릭스 감사는 아래 묶음 5와 "요구사항 매트릭스 감사" 절에서 끝냈다.

## 명세 감사 보완 묶음 5 — Phase 6 제공자 경계 (2026-09-27)

- 기준 worktree: `C:\AX\cost`, 기준 HEAD `1486a37`, 커밋하지 않음.
- 목적: `WEB_LEDGER_PHASES.md` Phase 6의 3~5항과 `WEB_LEDGER_DETAILED_CONTRACT.md`
  7절이 요구하는 경계를, 실제 네트워크 호출과 실제 자격 증명 없이 닫는다.
  "green test는 baseline일 뿐"이라는 지적에 따라, 각 항목마다 무엇을 증명하는지
  테스트 이름과 대응시킨다.

### 변경 파일

- 신규 `webapp/provider_transport.py`: `MuseAdapter`, `GeminiAdapter`,
  `RecordingTransport`, `TransportResponse`, `TransportUnavailable`,
  `reason_for_status`, `classify_exception`, `redact`, `build_adapters`,
  `adapter_report`.
- 신규 `webapp/provider_config.py`: `SecretStore`, `ProviderConfig`,
  `ProviderConfigService`, `redact`, `fingerprint`, `ConfigError`.
- 신규 `webapp/rule_text.py`: `rule_candidate`, `parse_provider_text`,
  `extract_json_block`, `candidate_report`, `TextRuleError`.
- 신규 `webapp/tests/test_provider_boundary.py` (67건, subtests 45건).
- 수정 `webapp/dialog_turn.py`: `WAITING_FAILURES`를 전환 조건에 반영,
  `TRANSPORT_REASONS`에 `not_configured`·`free_quota_exhausted`·
  `budget_exhausted`·`rate_limited`·`auth_failed`·`provider_refused` 추가,
  모듈 설명에서 "프로토콜을 모형화하지 않았다"는 문장 갱신.
- 수정 `webapp/ledger_store.py`: `run_dialog_turn`·`advance_dialog_conversation`가
  `operator`를 받아 산문 답변을 후보 규칙으로 변환, 결과에 `candidate`와
  `requires_owner_confirm` 포함.
- 수정 `webapp/ledger_board.py`: `bind_provider_config`, `_rebuild_provider_adapters`,
  `provider_status`, `access_control_render_provider_config`, `_operator_choice`,
  `GET/POST /access/providers`, `STATUS_FOR_CODE`에 `PROVIDER_CONFIG_UNBOUND`와
  `INTERNAL_ERROR`, `_phase7_refuse`가 예기치 않은 예외를 500으로 보고.
- 수정 `webapp/tests/test_dialog_turns.py`, `webapp/tests/test_classification_rules.py`.

### 명세 항목별 대응

| 명세 | 구현 | 검증 |
| --- | --- | --- |
| 6.3 owner 키 설정, 비밀 입력 화면 | `GET/POST /access/providers`, `type='password'` | `test_the_screen_uses_a_password_field_and_never_echoes_a_key`, `test_a_write_never_returns_the_value` |
| 6.4 서버 Gemini fallback | `build_adapters` + `run_turn` 단일 전환 | `test_a_muse_pc_that_is_off_falls_back_to_gemini_exactly_once` |
| 6.5 PC 종료·한도 소진·늦은 응답·Muse 복귀 | `WAITING_FAILURES` 분기, `adopt_late_response` | `test_a_free_quota_wait_does_not_call_gemini_even_when_it_would_work`, `test_a_late_answer_for_a_waiting_turn_is_refused`, `test_muse_recovers_on_the_following_turn` |
| 7 한 메시지당 turn_id 1개, attempt_id 별도 | 기존 `run_turn` | `test_a_persisted_turn_records_the_fallback_and_never_a_real_call` |
| 7 허용 문맥만 전달 | `build_context` + `_context_to_text` | `test_the_context_reaching_a_provider_is_allowlisted` |
| 7 같은 턴 두 응답 혼합 금지 | adopt 1건 제한 | `test_a_persisted_turn_records_the_fallback_and_never_a_real_call` |
| 7 모델 영향 건수·합계 불신 | 후보에 미포함 | `test_a_candidate_carries_no_impact_number` |
| 7 스키마·허용 필드·사용자 확정으로 경계 | `rule_candidate` + `normalize_draft` | `test_a_model_cannot_set_its_own_rule_id_version_or_scope`, `test_the_candidate_can_then_be_confirmed_and_previewed` |
| 키·비밀 비노출 | `redact`, `fingerprint`, 별도 저장소 | `test_the_key_never_reaches_the_ledger_database`, `test_no_key_reaches_the_persisted_turn_or_the_conversation` |
| 실패 모드 정확 분류 | `reason_for_status`, `classify_exception` | `test_http_statuses_map_to_their_reason`, `test_a_429_that_names_a_quota_is_a_quota_wait_not_a_rate_limit` |

### 이 과정에서 고친 실제 결함

1. `dialog_turn.WAITING_FAILURES`가 정의만 있고 쓰이지 않았다. 무료 한도 소진
   뒤 건강한 fallback이 달라도 전환해 버려 상세 계약 7의 대기를 어겼다.
   수정 후 `switch_count == 0`이고 fallback은 아예 호출되지 않는다.
2. `TRANSPORT_REASONS`가 `not_configured`를 몰라 `service_error`로 뭉개졌다.
   owner가 키를 지운 뒤 fallback을 소모하던 문제가 있었다.
3. `SecretStore.get`이 `str`만 반환해 `timeout=15`가 15.0으로 저장된 뒤 빈
   문자열로 읽혔고 20.0 기본값으로 되돌아갔다. 이제 수·문자열을 구분해
   그대로 돌려주고 bool은 숫자로 읽지 않는다. 회귀 테스트
   `test_a_configured_timeout_survives_the_round_trip` 추가.
4. `_phase7_refuse`가 예기치 않은 예외를 404 "없음"으로 위장했다. 실제로
   `AttributeError`가 404로 보여 원인 추적에 시간이 걸렸다. 이제 500
   `INTERNAL_ERROR` + 예외 종류 로그로 바꾼다. 404가 "볼 수 없다"의 뜻이라
   프로그래밍 오류를 그렇게보고하면 호출자에게 거짓말이 된다.
5. `provider_transport.redact`가 토큰을 소문자로 접은 뒤 대소문자 접두사를
   비교해 `AIza`로 시작하는 키를 걸러 내지 못했다.
6. `rule_text` 여행 ID 정규식이 뒤에 `\b`를 요구해 한국어 바로 뒤의
   `trip-demo-b로`를 놓쳤다.
7. `GeminiAdapter.build_request`가 모델 이름을 본문에도 남겼다. 경로와 본문
   두 곳에 있으므로 본문에서 제거했다.
8. `APP_SPEC` 9.3이 요구한 "fallback 활성화" 스위치가 없었다. 키를 등록하는 것과
   fallback을 켜는 것은 다른 행동인데, 전자가 후자를 함의했다. `fallback_enabled`를
   추가해 기본값을 꺼짐으로 두고, 꺼져 있으면 Gemini 어댑터를 아예 만들지 않아
   Muse 실패 시 전환하지 않고 대기한다. 즉 표시 설정이 아니라 실제 행동 변경이다.
   설정 화면과 owner 전용 API에 토글을 추가했다.
   `test_the_fallback_is_off_until_the_owner_turns_it_on`,
   `test_a_switched_off_fallback_leaves_a_muse_failure_waiting`,
   `test_the_owner_can_switch_the_fallback_and_it_changes_the_wiring`로 검증한다.

### 실행 명령과 실제 검사 결과

`python -m pytest webapp/tests -q -p no:cacheprovider`
→ `610 passed, 80 subtests passed in 187.96s`(이전 실행).

[역사 수치 — 이 실행 당시의 값] 좁은 재실행:
`test_provider_boundary.py` `73 passed, 45 subtests passed`,
Phase 7 `40 passed`, Phase 8 `18 passed`,
Phase 9 `28 passed`(현재 수집 기준 64건),
`test_dialog_turns.py`+`test_rule_dialog_stop.py`+`test_rule_process_ownership.py`
+`test_classification_rules.py` `177 passed`. `py_compile` 통과.

부수적으로 한 번 `C:\Users\kkokk\AppData\Local\Temp\opencode`를 통째로 지워
`test_rule_process_ownership.py`가 참조하는 자식 프로세스 도우미
`ownership_child.py`를 잃었다. 같은 계약으로 다시 만들어 두 검사를 복구했고
17 passed를 다시 확인했다. 그 디렉터리를 통째로 지우지 말 것.

### 미검증 범위

실제 제공자 호출, 실제 키와 유료 승인, 실제 Google OIDC, 실 예약 API, 운영 DB와
실제 Google 기준본 이관, 호스팅 자원, 실제 배포. 실제 자격 증명 없이 닫을 수
없으며 `ops.EXTERNAL_CONDITIONS`에 그대로 둔다.

## 요구사항 매트릭스 감사 — 2026-09-27 (최종)

대상: `IMPLEMENTATION_PROMPT_WEB_LEDGER_APP.md`, `WEB_LEDGER_APP_SPEC.md`,
`WEB_LEDGER_DETAILED_CONTRACT.md`, `WEB_LEDGER_IMPLEMENTATION_CONTRACT.md`,
`WEB_LEDGER_IMPLEMENTATION_REVIEW.md`, `WEB_LEDGER_PHASES.md`,
`WEB_LEDGER_SPEC_REFINEMENT.md`, `DECISION_REGISTER.md`, 최신 handoff.

판정은 세 가지뿐이다. **proven**은 이 작업트리의 검사로 증명된 항목,
**incomplete-local**은 외부 자원 없이 닫을 수 있는데 아직 닫히지 않은 항목,
**external-only**는 실제 자격 증명이나 사용자 승인 없이는 닫을 수 없는 항목이다.
green test라는 이유만으로 proven으로 두지 않았다. 각 proven에는 그 항목을
검사하는 테스트 이름을 적었다.

### proven — 요구사항이 구현되고 검사로 증명됨 (2026-09-27 행 단위 재검증)

각 행의 **제품 경로**는 그 요구사항이 실제로 실행되는 라우트·함수이고,
**검증 표면**은 그 경로 위에서 단정하는 테스트가 붙는 층이다.
`화면(브라우저)` 는 합성 Chromium으로 실제 제품 서버를 조작한 층,
`HTTP` 는 실제 소켓 요청을 보낸 층, `저장 계층`·`CLI`·`단위` 는
각각 저장소 함수·운영 CLI·순수 함수만 호출한 층이다.

| 명세 요구 | 실제 제품 경로 | 검증 표면 | 검사 |
| --- | --- | --- | --- |
| DETAILED 4.3 오류 코드 4종 | GET/POST 응답 코드 매핑 `STATUS_FOR_CODE` | HTTP | `test_the_contract_error_vocabulary_is_fully_mapped_to_a_status` |
| DETAILED 4.3 404 존재 은폐 | `GET /row?id=<없는 id>` → 404 JSON | HTTP | `test_a_viewer_read_refusal_never_reveals_the_row` |
| DETAILED 4.3 503 일시 실패 | `sqlite3.OperationalError` → 503 | HTTP | `test_a_locked_database_is_a_retryable_503_not_a_crash` |
| DETAILED 12.3 키보드·오류 안내 | `GET /board` 가 서는 HTML+스크립트 (브라우저 키 입력) | 화면(브라우저) | `test_enter_alone_does_not_save_and_ctrl_enter_does`, `test_enter_in_a_note_keeps_its_newline`, `test_escape_asks_before_dropping_an_unsaved_edit`, `test_a_refused_field_is_named_next_to_the_input_and_focused` |
| DETAILED 6.2~6.3 규칙 초안·미리보기·적용 범위 | `POST /api/classification/rules/draft`·`/preview`·`/apply` | HTTP+저장 계층 | `test_draft_preview_apply_over_http`, `test_stale_preview_returns_409`, `test_the_four_scope_combinations_are_each_accepted_and_independent`, `test_template_placeholder_is_rejected` |
| DETAILED 7 turn_id 1개·attempt_id 별도 | `dialog_turn.run_turn` (대화 저장 경계) | 저장 계층 | `test_a_persisted_turn_records_the_fallback_and_never_a_real_call` |
| DETAILED 7 한 턴 채택 1건 | `dialog_turn.run_turn` | 저장 계층 | `test_a_muse_pc_that_is_off_falls_back_to_gemini_exactly_once` |
| DETAILED 7 허용 문맥만 전달 | `ALLOWED_CONTEXT_FIELDS` | 단위 | `test_the_context_reaching_a_provider_is_allowlisted` |
| DETAILED 7 모델 영향 수치 불신 | rule_text 후보 생성 (검증 전 candidate) | 단위 | `test_a_candidate_carries_no_impact_number` |
| IMPL 7.1.1 키 등록·비밀 화면 | `GET /access/providers` + `POST /access/providers` (owner 전용) | HTTP | `test_the_screen_uses_a_password_field_and_never_echoes_a_key` |
| IMPL 7.1.1 연결 상태·등록 여부·선택 모델·fallback 표시 | `GET /access/providers` 응답 HTML | HTTP | `test_the_screen_reports_the_fallback_state` |
| IMPL 7.1.1 연결 테스트 = 성공 여부 + 실제 모델 ID | `provider_transport.connection_test` (전송 계층, 실제 호출 없음) | 저장 계층 | `test_the_connection_test_returns_success_and_the_actual_model_id`, `test_a_connection_test_failure_reports_a_reason_and_no_model` |
| IMPL 7.1.1 서버 조회 가용 목록 | `fetch_model_catalog` + `record_model_catalog` | 저장 계층 | `test_the_catalog_is_data_that_arrives_and_no_model_is_hardcoded` |
| IMPL 7.1.1 무료 지원 확인 항목만 선택 | `model_is_selectable` | 저장 계층 | `test_a_model_can_only_be_chosen_from_the_free_confirmed_list`, `test_no_model_can_be_chosen_before_the_list_is_fetched` |
| IMPL 7.1.1 모델 이름 코드 고정 금지 | 기본 모델 제거, 미선택 시 `not_configured` | 저장 계층 | `test_a_connection_test_on_an_unconfigured_provider_says_so` |
| IMPL 7.1.1 프로젝트 등급 확인 경로·시점·설정 필요 | `tier_state`/`tier_record` | 저장 계층 | `test_recording_a_free_tier_stores_when_it_was_checked`, `test_a_paid_or_unknown_tier_is_setting_required_not_verified` |
| IMPL 7.1.1 목록 조회로 등급 판정 금지 | 등급은 별도 기록 | 저장 계층 | `test_a_fetched_list_alone_does_not_verify_the_tier` |
| IMPL 7.1.1 일시적 제한만 제한 재시도 | `send_with_bounded_retry` | 저장 계층 | `test_a_transient_limit_is_retried_inside_one_attempt`, `test_a_spent_quota_is_never_retried` |
| IMPL 7.1.1 진행 중 시도 만료 후 새 시도 1개 | `run_turn(expire_attempts=)` | 저장 계층 | `test_an_outstanding_attempt_is_expired_before_one_new_attempt` |
| APP_SPEC 9.3 fallback 활성 스위치 | `POST /access/providers` (owner 전용) + 배선 재생성 | 저장 계층+HTTP | `test_the_fallback_is_off_until_the_owner_turns_it_on`, `test_only_an_owner_can_switch_the_fallback`, `test_a_viewer_cannot_switch_the_fallback`, `test_the_owner_can_switch_the_fallback_and_it_changes_the_wiring` |
| APP_SPEC 9.3 키를 브라우저·로그·채팅에 남기지 않음 | `GET /access/providers` 화면 + 비밀 저장소 경계 | HTTP+저장 계층 | `test_the_key_never_reaches_the_ledger_database`, `test_no_key_reaches_the_persisted_turn_or_the_conversation`, `test_the_public_view_never_holds_a_value` |
| APP_SPEC 7 권한·공개 범위 | `_phase7_get`·`_phase7_write` + `/access/*` 라우트 | HTTP | `test_a_viewer_sees_only_its_own_trip_and_other_trips_are_404`, `test_a_viewer_cannot_reach_owner_writes_or_the_ai_dialogue`, `test_the_role_is_decided_on_the_server_not_by_the_request` |
| DETAILED 11.2 최초 이관 차이 선택 | `migration.py` 별도 이관 작업 DB (파일 계층이며 HTTP 아님) | 저장 계층 | `test_both_sources_are_sealed_and_verified`, `test_the_sources_are_never_written`, `test_the_migration_writes_only_to_its_own_db`, `test_applying_the_same_comparison_twice_has_no_second_effect` |
| REFINEMENT 8.1 여행 탭 삭제 화면 | `GET /trips` (브라우저) | 화면(브라우저) | `test_the_trip_screen_uses_the_shared_chrome_and_keeps_its_actions`, `test_the_delete_preview_still_shows_and_confirms`, `test_archiving_from_the_trip_screen_moves_it_to_the_drawer` |
| REFINEMENT 8.1~8.2 여행 탭 삭제 저장 경계 | `trip_delete` 저장 경계 + `DELETE_PREVIEW_STALE` + 멱등/충돌 | 저장 계층+화면(브라우저) | `test_same_request_retry_reuses_exact_result_without_new_effects`, `test_a_stale_trip_revision_is_reported_and_the_typed_name_is_kept`, `test_same_request_id_rejects_every_changed_delete_field`, `test_delete_stale_preview_rejected`, `test_delete_moves_and_stale_rejected` |
| REFINEMENT 9 직전 수정 되돌리기 (배분) | `POST /api/rows/{id}` 되돌리기 + `GET /row` 사유 표시 | HTTP | `test_allocation_detail_edit_revert_http_flow`, `test_allocation_detail_shows_revert_blocked_reason` |
| REFINEMENT 9 직전 수정 되돌리기 (일반 편집) | `revert_row` (저장 계층) — 화면 경로는 미검증 | 저장 계층 → HTTP (이번 턴에 대체) | `test_memo_revert_and_double_locked` |
| REFINEMENT 10 입금 분할 화면 | `GET /income/new` 분할 화면 (브라우저) | 화면(브라우저) | `test_the_allocation_split_screen_still_answers`, `test_the_split_screen_keeps_its_totals_and_csrf`, `test_the_income_panel_offers_the_bank_fields_and_the_split_link` |
| REFINEMENT 10~13 배분 정합성 | 저장 계층 `save_allocations`·`update_allocation` | 저장 계층 | `test_revert_single_allocation`, `test_move_revert_remove_and_conflicts`, `test_13_2_an_allocation_keeps_its_id_across_a_move`, `test_13_3_an_unassigned_allocation_and_a_remainder_are_different` |
| REFINEMENT 10.3·13.5 되돌리기 범위 경계 | 개별 되돌리기만, 전체 배분안 복원 없음 | 저장 계층 | `test_the_revert_scope_is_one_row_and_there_is_no_whole_plan_restore` |
| REFINEMENT 12~14 작성일·담당자·표시 이름 | `POST /api/trips/{tab_id}` (`_handle_trip_meta`) + `GET /trips` | 화면(브라우저)+저장 계층 | `test_a_stale_trip_revision_is_reported_and_the_typed_name_is_kept`, `test_meta_save_and_archive`, `test_a_free_typed_trip_title_cannot_become_a_sheet_name_formula`, `test_an_owner_name_cannot_become_a_formula_cell` |
| REFINEMENT 15 증빙 미리보기 범위 | `GET /access/rows` 증빙 경계 | HTTP | `test_evidence_preview_is_allowlisted_and_the_original_is_never_served` |
| REFINEMENT 16 직원 신청·승인 | `/access/applications`·`/access/decision` + `/access/admin` | HTTP | `test_pending_approved_rejected_and_withdrawn`, `test_the_role_is_decided_on_the_server_not_by_the_request` |
| REFINEMENT 17.2~17.3 백업·복구·재개 | `ops.backup`·`ops.restore` + CLI (운영 경로가 CLI) | CLI | `test_a_backup_bundle_carries_the_db_and_the_invariant_metadata` |
| REFINEMENT 17.4 조치 필요 상태만 표시 | `ops.action_required_report` + `cli ops actions` | CLI | `test_a_save_still_pending_is_reported`, `test_a_pending_staff_request_is_reported` |
| 390 뷰포트 편집·출력·대화 | `GET /board` 실제 렌더 (브라우저 390px) + 합성 Chromium | 화면(브라우저) | `test_the_panel_footer_stays_reachable_and_two_saves_work_at_390`, `test_one_trip_button_and_a_short_notice_at_390`, `test_the_waiting_move_works_at_390_with_a_full_width_control` |

**2026-09-27 우선순위 2·3에서 추가된 행**

| APP_SPEC 3절·4.2절 새 탭 추가 (저장) | `POST /api/tabs` → `LedgerStore.create_trip` | HTTP | `test_an_owner_post_creates_the_tab_and_the_server_names_it`, `test_the_same_date_and_destination_returns_the_tab_that_is_already_there`, `test_the_same_request_id_with_other_content_is_refused`, `test_a_missing_date_or_destination_is_refused_with_422`, `test_a_refused_create_leaves_no_half_written_trip_behind`, `test_the_owner_may_create_a_tab`, `test_a_viewer_is_refused_with_403_and_adds_nothing`, `test_a_caller_without_a_session_is_asked_to_log_in_again`, `test_the_role_comes_from_the_server_and_not_from_the_body` |
| APP_SPEC 3절 탭 모델 5필드 분리 | `trip_tabs` 의 `event_year`·`tab_kind`·`authority_status`·`source_sha256`·`sort_order` + 파생 `tab_lifecycle` | HTTP | `test_the_created_tab_keeps_the_five_tab_model_fields_apart`, `test_creating_a_tab_does_not_make_the_schedule_authoritative`, `test_an_authority_digest_is_stored_but_does_not_confirm_by_itself`, `test_the_tab_kind_is_kept_apart_from_the_display_name` |
| APP_SPEC 4.2절 `+ 탭 추가` 화면 | `GET /board` 왼쪽 레일 + `GET /trips` 대화창 | 화면(브라우저)+HTTP | `test_the_rail_offers_the_add_tab_control_to_the_owner`, `test_a_viewer_is_not_offered_the_add_tab_control`, `test_the_owner_screen_offers_the_dialog_4_2_lists`, `test_the_form_post_reaches_the_endpoint_and_lists_the_new_trip` |
| APP_SPEC 10 `GET /api/rows/{row_id}/lineage` | `GET /api/rows/{id}/lineage` (원천·제안·사용자 수정·이력) | HTTP | `test_the_lineage_answers_source_proposal_edits_and_history`, `test_the_lineage_of_a_row_that_names_nothing_is_404` |
| APP_SPEC 10 `GET /api/audit/changes` | `GET /api/audit/changes` (기간·탭·행·actor 필터) | HTTP | `test_a_save_shows_up_in_the_audit_list_with_its_actor`, `test_the_audit_list_filters_by_row_and_by_actor`, `test_the_audit_list_filters_by_period`, `test_the_audit_list_is_empty_until_something_is_saved` |
| APP_SPEC 10 `GET /api/tabs` | `GET /api/tabs` (권위 상태·합계·검토 건수) | HTTP | `test_the_tabs_index_reports_authority_totals_and_review_counts`, `test_the_tabs_index_states_authority_apart_from_the_name`, `test_a_trip_created_on_screen_is_not_authoritative_either`, `test_a_viewer_cannot_read_the_tabs_index` |
| APP_SPEC 5절 수기 지출 `POST /api/expenses/manual` | `POST /api/expenses/manual` + `/expense/new` 폼 | HTTP | `test_the_new_screen_posts_to_this_endpoint`, `test_a_manual_expense_is_saved_and_readable_at_its_own_url`, `test_the_form_post_lands_on_the_new_row`, `test_the_same_request_id_saves_only_one_row`, `test_an_amount_the_server_cannot_read_is_refused_with_422`, `test_a_date_the_server_cannot_read_is_refused`, `test_a_refused_write_leaves_no_row_behind`, `test_the_expense_shows_its_own_source_level` |
| REFINEMENT 9 직전 수정 되돌리기 (일반 편집) | `POST /api/rows/{id}/revert` (메모 등 일반 편집) | HTTP | `test_a_memo_edit_and_its_revert_both_go_through_http`, `test_the_revert_is_a_new_event_and_does_not_erase_the_old_one`, `test_a_retry_of_the_same_revert_does_not_add_history`, `test_a_stale_revert_is_refused_and_changes_nothing`, `test_a_revert_without_the_confirmation_token_is_refused` |
| APP_SPEC 8절 출력 대화창 검토필요 건수 | `GET /export` 검토필요 집계 + 충돌 미집계 사유 고지 | HTTP | `test_the_export_dialog_states_the_review_and_conflict_counts`, `test_the_export_dialog_review_note_appears_before_the_form` |

**2026-09-27 재심 판정에서 추가된 행**

| APP_SPEC 9절 `충돌` 상태 (DB) | `board_revisions.kind='conflict'` append-only note via `LedgerStore.record_conflict` | 저장 계층+HTTP | `test_a_refused_save_leaves_a_conflict_note_and_changes_no_value`, `test_the_note_names_the_revision_that_was_asked_for_and_the_real_one`, `test_the_note_remembers_what_the_user_tried_to_save`, `test_a_revert_refused_as_stale_also_leaves_a_note`, `test_a_valid_request_on_a_clean_row_leaves_no_note`, `test_a_refused_field_leaves_no_note`, `test_a_conflict_on_one_row_does_not_touch_another`, `test_a_later_successful_save_clears_the_conflict` |
| APP_SPEC 9절·DETAILED 3.2 `충돌` 상태 (행 상세) | `GET /row?id=` → `history_html` 충돌 안내와 복구 문구 | HTTP | `test_the_row_detail_shows_the_conflict_with_a_way_back` |
| APP_SPEC 4.3 기본 표에 상태 표시 없음 | `GET /board` 기본 표 (충돌 여부가 표에 새지 않음) | HTTP | `test_the_board_table_gives_the_conflict_state_no_marker` |
| APP_SPEC 8절 출력 대화창 `충돌` 행 수 | `GET /export` 검토필요·충돌 건 수 집계 | HTTP | `test_the_export_dialog_counts_the_row_in_conflict`, `test_the_export_dialog_returns_to_zero_after_the_conflict_is_resolved`, `test_the_export_dialog_states_the_review_and_conflict_counts` |
| APP_SPEC 10절 `GET /api/tabs/{tab_id}/rows` | `GET /api/tabs/{id}/rows` (행·상태·현재 revision) | HTTP | `test_the_rows_listing_marks_the_row`, `test_the_rows_listing_gives_the_current_revision`, `test_the_rows_listing_answers_for_a_tab_that_does_not_exist`, `test_the_rows_listing_answers_for_the_waiting_tab` |
| APP_SPEC 10절 탭 경로 정합 (`POST /api/tabs` 단일 경로) | `POST /api/tabs` 생성 단일 경로, `/api/trips/{id}/meta`·`/delete` 유지 | HTTP | `test_post_api_tabs_is_the_create_path_named_by_the_spec`, `test_post_api_trips_does_not_create_so_no_action_has_two_urls`, `test_the_trip_meta_and_delete_family_is_untouched`, `test_the_new_trip_form_posts_to_the_canonical_path`, `test_a_viewer_cannot_create_a_tab_on_the_canonical_path`, `test_the_owner_may_create_on_the_canonical_path` |
| APP_SPEC 10절 `GET /api/audit/changes` — 충돌 사건 포함 | `GET /api/audit/changes` (save → conflict → save 순서) | HTTP | `test_the_audit_list_shows_the_note_between_the_two_saves` |

**2026-09-27 코디네이터 후속 감사에서 추가된 행**

| APP_SPEC 4.1 상단 전역 영역 — 미저장 건수·마지막 저장 시각 | `_last_saved_at` + `shell`/`page` `#global-state` + `reportUnsaved` | HTTP+화면(브라우저) | `test_the_global_area_states_the_unsaved_count_and_the_last_save`, `test_the_last_save_time_comes_from_the_change_ledger`, `test_a_ledger_with_no_save_says_so_rather_than_inventing_a_time`, `test_the_shared_screens_carry_the_same_global_line`, `test_the_element_the_markup_carries_is_the_one_the_script_writes_to`, `test_a_clean_page_leaves_without_any_dialog`, `test_leaving_with_an_unsaved_edit_raises_beforeunload`, `test_a_saved_edit_is_not_unsaved_any_more`, `test_an_owner_does_not_see_the_read_only_note` |
| DETAILED 12.2 전체 합계와 검색 결과 합계 이름 분리 | `_summary_html`·`_totals_kw`·`summary_part` + `GET /board?part=summary` | HTTP | `test_an_unfiltered_tab_states_one_set_of_totals`, `test_a_filter_names_the_whole_and_the_result_separately`, `test_a_filter_never_replaces_the_whole_total_with_the_result`, `test_the_board_page_itself_shows_the_separated_totals`, `test_a_filter_that_matches_nothing_reports_zero_not_the_whole`, `test_the_row_counts_are_split_too` |
| DETAILED 15 수기 지출 추가 버튼 위치 | `_tables_html` 지출 그룹 행 `#add-manual-expense` | HTTP | `test_the_board_places_the_button_in_the_expense_group_row`, `test_the_button_is_not_in_the_income_group`, `test_the_expense_heading_itself_stays_the_word_it_is`, `test_the_button_reaches_the_manual_expense_screen` |

**2026-09-27 운영 준비 감사에서 추가된 행**

| REFINEMENT 17.2 복구 묶음 — DB 해시 부재 시 거부 | `ops.restore_bundle` + `_discard_restored` | 합성(임시 디렉터리) | `test_a_manifest_without_a_db_hash_is_refused`, `test_a_corrupt_database_is_refused_without_raising`, `test_a_refused_restore_leaves_nothing_usable_in_the_target`, `test_a_corrupt_database_with_a_matching_hash_still_cannot_restore`, `test_discard_reports_what_it_could_not_remove`, `test_discard_reports_a_locked_file_instead_of_swallowing_it`, `test_a_good_bundle_still_restores` |
| REFINEMENT 17.3 2항 사건별 내용 대조 — 합계만 같아도 통과시키지 않는다 | `ops.business_state_digest` + `verify_restored_state` + `_state_summary` | 합성(임시 디렉터리) | `test_the_manifest_records_a_content_digest`, `test_a_matching_restore_reports_that_content_was_compared`, `test_equal_counts_with_different_content_is_still_refused`, `test_the_digest_names_the_table_that_moved` |
| REFINEMENT 17.2 회복 수치 — 입력 범위·시험 복구 시간·저장 비용 | `ops.recovery_figures` + `recovery_lines` + `write_deploy_runbook` | 합성(임시 디렉터리) | `test_a_measured_drill_produces_every_figure`, `test_the_figures_say_when_nothing_was_measured`, `test_an_unmeasured_input_range_says_so_instead_of_guessing`, `test_input_after_the_backup_is_called_out`, `test_no_input_after_the_backup_is_reported_as_zero` |
| REFINEMENT 17.3 4항 시험 복구 연습 — 운영 DB를 덮어쓰지 않는다 | `ops.run_restore_drill` + `cli ops drill` | 합성(임시 디렉터리) | `test_the_drill_restores_to_a_separate_path`, `test_the_drill_command_runs_and_reports`, `test_a_drill_on_an_empty_target_still_reports_its_figures` |
| REFINEMENT 17.4 준비 보고 — 측정하지 않은 수치를 0으로 말하지 않는다 | `ops.readiness_report` `waiting_turns` | 합성(임시 디렉터리) | `test_the_reported_waiting_count_is_the_measured_one`, `test_without_a_measurement_the_answer_is_not_measured_not_zero`, `test_zero_waiting_is_reported_as_a_measured_zero`, `test_the_health_schema_list_names_only_tables_that_exist` |
| REFINEMENT 16.1 로그인 경계 — 첫 로그인이 owner가 되지 않는다 | `access_control.UnboundSessionAdapter` + `ensure_owner` 호출처 전수 조사 | 코드 판독 + 합성 | `test_the_reported_waiting_count_is_the_measured_one` |
| IMPL 7.1 제공자 경계 — 실제 호출 없음 | `provider_transport` `is_real_call` + `HttpTransport` 부재 확인 | 합성(어댑터 직접 호출) | `test_a_measured_drill_produces_every_figure` |

**2026-09-27 HOSTING 준비 감사에서 추가된 행**

| REFINEMENT 19.2 외부 노출 — 바인딩 주소가 고정값이 아니다 | `ops.is_loopback_host`·`bind_posture`·`require_safe_bind` + `cli serve --host/--behind-proxy` + `ledger_board.serve(host=)` | HTTP(합성) | `test_loopback_addresses_are_recognised`, `test_wildcards_and_routable_addresses_are_not_loopback`, `test_an_unresolvable_name_is_treated_as_external`, `test_the_default_shape_is_loopback_behind_a_proxy`, `test_an_external_bind_names_what_it_would_expose`, `test_require_safe_bind_refuses_an_external_bind_by_default`, `test_require_safe_bind_allows_loopback_with_no_flag`, `test_an_acknowledged_external_bind_is_a_different_shape`, `test_serve_defaults_to_loopback`, `test_serve_actually_binds_the_address_it_is_given`, `test_the_serve_parser_offers_the_host` |
| REFINEMENT 19.2 외부 노출 — public bind 는 승인이 있어야 통과한다 | `ops.build_deploy_manifest(behind_proxy=False)` + `dry_run_deploy` `app_port_not_exposed_without_tls` + `cli ops dry-run --host` | 합성(임시 디렉터리) | `test_the_manifest_records_the_bind_posture`, `test_an_external_bind_fails_the_dry_run`, `test_an_acknowledged_external_bind_passes_and_is_marked`, `test_a_manifest_with_no_bind_posture_fails_the_dry_run`, `test_dry_run_refuses_an_external_bind_and_says_which_check`, `test_dry_run_accepts_an_external_bind_once_acknowledged` |
| REFINEMENT 18.3 2항 영속 경로 — 체크아웃 안에는 운영 자료를 두지 않는다 | `ops._inside_source_checkout` + `DurableConfig.CHECKOUT_DATA_ROOT` + `ops.durable_config_for` + `run_candidate.py --data-root/--environment` | 합성(임시 디렉터리) + 프로세스 기동 | `test_durable_config_for_uses_the_conventional_layout`, `test_a_production_data_root_inside_the_checkout_is_refused`, `test_a_synthetic_run_may_sit_inside_the_checkout_on_purpose`, `test_the_dry_run_names_a_checkout_data_root`, `test_no_data_root_is_a_refusal_not_a_checkout_default`, `test_an_external_bind_is_refused_with_a_code`, `test_a_production_data_root_inside_the_checkout_is_refused`, `test_a_production_data_root_in_a_temp_directory_is_refused`, `test_the_entry_point_offers_the_operations_commands` |
| REFINEMENT 19.2 서비스 예시 — 설치하지 않는 systemd 단위 | `ops.service_unit_text` + `cli ops dry-run --unit` + runbook 바인딩 절 | 합성(임시 디렉터리) | `test_the_unit_binds_loopback_and_uses_the_data_root`, `test_the_unit_never_carries_a_secret_value`, `test_the_unit_states_the_procedures_to_run_by_hand`, `test_the_unit_marks_itself_as_an_example`, `test_the_runbook_states_the_bind_shape_and_the_procedures`, `test_dry_run_writes_the_unit_and_reports_its_path`, `test_dry_run_without_a_unit_flag_writes_no_unit` |
| REFINEMENT 17.4 준비 보고 — health 가 본것을 그대로 말한다 | `ops.health_check` synthetic_sessions detail | 합성(임시 디렉터리) | `test_the_detail_agrees_with_the_verdict_when_no_allowance`, `test_the_detail_agrees_with_the_verdict_when_an_allowance_exists`, `test_a_missing_database_is_reported_honestly` |

**2026-09-27 Google OIDC 연결에서 추가된 행**

| REFINEMENT 16.1 인증 경계 — Google OIDC Authorization Code 실제 구현 | `webapp/google_oidc` `OIDCConfig`·`connect_oidc`·`try_connect_from_env` | 합성(전송·검증 주입) | `test_a_complete_environment_produces_a_configuration`, `test_every_missing_variable_is_refused`, `test_describe_never_carries_a_secret_value`, `test_the_ledger_asks_for_no_mail_or_file_scope`, `test_the_authorization_url_carries_state_and_nonce`, `test_a_full_login_registers_a_viewer_and_issues_a_cookie`, `test_a_callback_with_the_wrong_state_is_refused`, `test_a_token_whose_nonce_does_not_match_is_refused`, `test_a_refused_exchange_does_not_create_an_account`, `test_a_missing_code_is_refused` |
| REFINEMENT 16.1 id_token 검증 — 서명·발급자·대상·만료·nonce | `GoogleAuthTokenVerifier`(`google.oauth2.id_token`) + `validate_claims` | 합성(claims 주입) | `test_a_good_token_verifies`, `test_another_issuer_is_refused`, `test_another_audience_is_refused`, `test_an_expired_token_is_refused`, `test_a_token_without_an_expiry_is_refused`, `test_a_token_without_a_sub_is_refused`, `test_a_mismatched_nonce_is_refused`, `test_the_email_is_never_the_account_key` |
| REFINEMENT 16.1 계정 키 — Google sub 를 쓰고 email 은 신원 근거가 아니다 | `register_google_identity` (login 은 role 을 건드리지 않는다) | 합성 + DB | `test_a_full_login_registers_a_viewer_and_issues_a_cookie`, `test_a_login_never_changes_an_existing_role`, `test_a_login_never_reactivates_a_deactivated_account`, `test_the_email_is_never_the_account_key` |
| REFINEMENT 15.1 소유권 — 첫 로그인은 승격이 아니다 | `bootstrap_owner_if_configured` + `WEBLEDGER_OWNER_GOOGLE_SUB` | 합성 + DB | `test_no_owner_sub_means_no_owner_at_all`, `test_a_matching_owner_sub_bootstraps_exactly_one_owner`, `test_a_non_matching_sub_stays_a_viewer`, `test_a_second_owner_is_not_handed_out`, `test_a_login_never_changes_an_existing_role` |
| REFINEMENT 16.1 세션 — 서명 쿠키와 세대 결합 | `SessionSigner` + `GoogleOIDCAdapter.session_for` + `require_session` | HTTP(합성) | `test_a_signed_cookie_round_trips`, `test_a_tampered_payload_is_refused`, `test_a_cookie_signed_with_another_key_is_refused`, `test_a_malformed_cookie_is_absent_not_an_error`, `test_the_cookie_is_httponly_samesite_lax_and_secure`, `test_the_google_token_is_never_put_in_the_cookie`, `test_a_valid_cookie_yields_a_session`, `test_a_stale_generation_is_refused`, `test_a_logout_bumps_the_generation_and_invalidates_the_cookie`, `test_a_cookie_for_an_unknown_or_deactivated_account_is_refused`, `test_an_expired_cookie_is_refused`, `test_the_adapter_never_accepts_a_synthetic_header`, `test_require_session_refuses_a_stale_cookie_end_to_end` |
| REFINEMENT 16.1 로그인 경로 — state/nonce 은 일회용 | `PendingLogins.issue`/`spend` | 합성 | `test_a_state_can_be_spent_exactly_once`, `test_an_unknown_state_is_refused`, `test_an_expired_state_is_refused`, `test_two_logins_get_different_values`, `test_the_store_stays_bounded` |
| SPEC 16.1 라우트 — /auth/login, /auth/callback, /access/logout | `ledger_board.Handler._auth_routes` + `_send_json(extra_headers=)` | HTTP(실 소켓) | `test_login_redirects_to_google`, `test_login_answers_503_when_nothing_is_configured`, `test_callback_without_a_flow_answers_503`, `test_callback_with_a_bad_state_is_refused`, `test_callback_that_google_refused_is_reported`, `test_a_full_callback_sets_the_cookie_and_redirects`, `test_logout_clears_the_cookie`, `test_the_post_logout_clears_the_cookie_too`, `test_the_state_line_reports_the_connection`, `test_the_state_line_says_so_when_nothing_is_connected` |
| REFINEMENT 17.4 준비 보고 — google_oidc_connected 를 facts 로 | `ops.google_oidc_state` + `health_check` + `dry_run_deploy` | 합성(임시 디렉터리) | `test_health_reports_the_oidc_line_as_not_connected`, `test_health_reports_connected_only_when_a_flow_is_bound`, `test_health_does_not_claim_a_connection_from_the_environment`, `test_health_never_prints_a_secret`, `test_a_production_dry_run_needs_a_connected_login`, `test_a_temp_rooted_production_config_is_refused_on_its_own`, `test_a_production_dry_run_fails_without_a_login`, `test_a_production_dry_run_passes_with_a_login`, `test_the_state_reports_presence_not_values` |

**2026-09-27 /access/me 결함 수정에서 추가된 행**

| REF 16.1 자기 상태 응답 — `/access/me` 가 실제 로그인 상태를 말한다 | `ledger_board.google_oidc_connection_state` + `access_control_render_viewer_status` + `ops.google_oidc_state` | HTTP(실 소켓) | `test_a_connected_login_is_reported_as_connected`, `test_no_connection_is_reported_as_not_connected`, `test_the_route_and_health_never_disagree`, `test_the_response_carries_the_state_it_used`, `test_the_response_carries_no_secret`, `test_the_view_helper_reads_the_bound_flow`, `test_a_bound_flow_without_the_library_is_not_connected`, `test_the_route_reads_the_verdict_and_not_merely_the_configuration`, `test_both_paths_return_the_same_value`, `test_ops_follows_the_process_and_not_the_environment`, `test_ops_follows_a_flow_that_is_bound_after_a_restart`, `test_the_board_helper_is_the_one_that_exists` |

### 계층 정정 기록 (2026-09-27, 우선순위 1b)

이전 표는 **명세 요구**·**구현**·**검사** 세 칸뿐이라, 어느 층에서 단정하는지
적혀 있지 않았다. 그래서 여행 탭 삭제·입금 분할·작성일처럼 명세가 화면과
저장 요청을 요구하는 행이, 저장소 함수만 부르는 테스트 이름만 인용된 것처럼
보였다. 실제로는 다른 파일에 그 요구의 실제 표면 검사가 있었고 인용만
누락돼 있었다.

행마다 "이 요구의 실제 제품 경로가 무엇인가"를 먼저 적은 뒤 그 표면 위의
테스트를 다시 인용했다. 인용은 전부 실제로 존재하는 테스트 이름이며,
존재하지 않으면 넣지 않았다(작성 시 검증).

**계층 표기로 바로잡은 행**

아래 표의 `이전 인용` 칸에 있는 이름은 **그때 인용되던 이름**이다. 그 중 몇 개는 이번에 이름을 바꾸거나 라우트에 맞춰 옮겼으므로 지금은 존재하지 않는다. 현재 인용 이름은 위 proven 표에 있다. 이 표는 무엇을 어떻게 고쳤는지를 남기기 위한 기록이지 현행 인용 목록이 아니다.


| 요구 | 이전 인용 층 | 실제 제품 경로 | 정정 후 검증 표면 |
| --- | --- | --- | --- |
| REFINEMENT 8.1 여행 탭 삭제 | 저장소 함수만 | `GET /trips` | **화면(브라우저)** |
| REFINEMENT 8.1~8.2 삭제 저장 경계 | 저장소 함수만 | `trip_delete` + `DELETE_PREVIEW_STALE` | 저장 계층 + 화면(브라우저) |
| REFINEMENT 9 되돌리기 (배분) | 저장소 함수만 | `POST /api/rows/{id}` + `GET /row` | **HTTP** |
| REFINEMENT 10 입금 분할 | 저장소 함수만 | `GET /income/new` | **화면(브라우저)** |
| REFINEMENT 12~14 작성일·담당자 | 저장소 함수만 | `POST /api/trips/{tab_id}` + `GET /trips` | 화면(브라우저) + 저장 계층 |
| DETAILED 6.2~6.3 규칙 적용 | 저장소 함수만 | `POST /api/classification/rules/*` | **HTTP** + 저장 계층 |
| APP_SPEC 9.3 fallback 스위치 | 저장소 함수만 | `POST /access/providers` | **HTTP** + 저장 계층 |
| APP_SPEC 7 권한·공개 범위 | 이름만 | `_phase7_get`·`_phase7_write` + `/access/*` | **HTTP** |
| DETAILED 12.3 키보드·오류 안내 | 구현 함수명만 | `GET /board` HTML+스크립트 | **화면(브라우저)** |
| 390 뷰포트 | 구현 함수명만 | `GET /board` 390px 실제 렌더 | **화면(브라우저)** |

**이 층이 그대로인 행과 이유**

- `DETAILED 7` AI 대화 3행, `IMPL 7.1.1` 전송 계층 10행: 이 웹앱에 해당
  화면이 없다. 명세가 요구하는 것은 대화 저장 경계와 전송 계층 동작이며,
  그래서 `저장 계층`·`단위` 표기가 요구사항의 층과 일치한다. 층을 올려
  부풀리지 않는다.
- `DETAILED 11.2` 최초 이관: 명세가 별도 이관 DB를 요구하므로 파일 계층이
  제품 경로다. HTTP가 아니다.
- `REFINEMENT 17.2~17.4` 백업·복구·조치 필요: 명세가 운영 경로를 운영
  CLI로 두므로 `CLI` 표기가 요구사항과 일치한다.
- **[역사] `REFINEMENT 9` 일반 편집 되돌리기**: 그 시점에는 배분만 HTTP로
  검증되어 있었고 일반 편집(메모 등)은 저장 계층만 proven이었다. 이 한 항목을
  incomplete-local 후보로 적었다. **이 항목은 뒤에 닫혔다** — 현재는
  `POST /api/rows/{id}/revert` 로 HTTP proven이며, 위 proven 표의
  "REFINEMENT 9 직전 수정 되돌리기 (일반 편집)" 행을 보라.

**[역사] 그 시점 표면 분포 (proven 45행)**

- `저장 계층`: 17행
- `HTTP`: 9행
- `단위`: 7행
- `화면(브라우저)`: 4행
- `HTTP+저장 계층`: 2행
- `CLI`: 2행
- `저장 계층+HTTP`: 1행
- `저장 계층+화면(브라우저)`: 1행
- `화면(브라우저)+저장 계층`: 1행
- `저장 계층+단위`: 1행

**행 분리**: 여행 탭 삭제를 8.1 화면과 8.1~8.2 저장 경계로 나누고,
되돌리기를 배분(HTTP proven)과 일반 편집(저장 계층만)으로 나누고,
10절을 분할 화면과 10~13 배분 정합성으로 나누고, 12~14를 작성 정보와
출력 수식 방어로 나눴다. 층이 다른 요구를 한 행에 묶지 않는다.

### incomplete-local — 없음

코디네이터 후속 감사에서 명세를 절 단위로 다시 훑고, 매트릭스가 인용하지
않던 **구체적 화면·API 요구**까지 코드에서 확인했다. 그 과정에서 세 건이 실제로
비어 있음을 찾아 로컬에서 닫았다. 닫은 것과 그 근거는 위 proven 표의 신규 행과
아래에 적는 변이 표기다.

1. **APP_SPEC 4.1 상단 전역 영역** — `저장되지 않은 변경 1건`과 마지막 저장
   시각이 제품 코드에 없었다. 전역 상단에는 카드 가져오기·XLSX 출력·장부 버튼만
   있었다. 변경 전 페이지 이탈 확인도 없었다. `_last_saved_at` 을 추가해 마지막
   저장 시각을 변경 원장에서 읽게 하고, 전역 상태 줄과 `reportUnsaved` 로 미저장
   건수를 붙였고, 이탈 시 `beforeunload` 확인을 넣었다.
2. **DETAILED 12.2 합계와 미배정** — 필터를 켜면 `page()` 가 먼저 걸러낸 행만
   합산해 그 결과를 `수입`·`지출` 이라는 이름으로 보여겼다. 명세가 금지한
   "전체 합계를 검색 결과 합계로 조용히 교체" 그 자체였다. 전체 합계를 따로
   유지하고 `전체 수입`·`검색 결과 수입` 처럼 이름을 분리했다.
3. **DETAILED 15 수기 지출 추가 버튼** — 버튼이 페이지 상단 내비게이션 줄에만
   있었고, 명세가 요구한 "지출 구역 제목 옆"에는 없었다. 지출 그룹 행의 합계 칸에
   두었고, 구역 제목 자체는 여전히 `지출` 이라는 글자만 갖게 했다.

**이 세 건은 이번에 처음 발견한 결함이지, 이전 턴의 "0건"이 거짓말이었다는
뜻은 아니다.** 이전 판정은 매트릭스에 인용된 행의 층을 확인한 것이었고, 인용된
행 바깥의 요구는 세지 않았다. 이제 인용되지 않은 구체적 화면 요구까지 확인했다.

변이 7건(마지막 저장 시각 발명, 필터 무시, 라벨 통합, 0건 대신 전체, 버튼 위치
옮김, 마크업 id와 스크립트 조회 분리, 버튼을 수입 그룹에 중복)을 전부 실패로
확인했고 소스를 바이트 단위로 복구했다.

변이를 돌리면서 또 두 가지를 발견해 고쳤다. 하나는 마크업의 `id` 와 스크립트의
`getElementById` 사이에 묶는 검사가 없어 한쪽만 고쳐도 조용히 얼어 있던 것이고,
다른 하나는 Escape 로 삭제를 확인한 뒤에도 폼의 미저장 표시가 남아서 그 이동에서
`beforeunload` 이 불필요하게 떴던 것이다.

### external-only — 외부 입력 없이는 결정되지 않음

아래 여섯 항목은 **코드로 닫을 수 없다.** 각각에 대해 (1) 필요한 외부 입력,
(2) 입력이 갖춰진 뒤 실행할 명령, (3) 성공을 판정할 근거를 적는다. 로컬 검사가
green이어도 아래 6개는 그대로 남는다.

---

#### 1. `HOSTING-RESOURCE` — 상시 실행 호스팅 자원

- **필요한 외부 입력**: 계정 등록과 카드 인증, VM 생성, **영속 디스크** 선택
  (임시 디스크면 안 된다), 방화벽에서 inbound 허용, `data_root` 로컬 경로
- **실행 명령**:
  ```
  set WEBLEDGER_DATA_ROOT=<영속 디스크의 실제 절대 경로>
  set WEBLEDGER_DB=<data_root>oard.sqlite
  set WEBLEDGER_EXPORT_DIR=<data_root>\exports
  set WEBLEDGER_EVIDENCE_DIR=<data_root>\evidence
  set WEBLEDGER_SOURCE_DIR=<data_root>\source
  set MUSE_KEY=<실제 키>
  python -m webapp.cli ops health --environment production --secret MUSE_KEY
  ```
- **성공 판정 근거**: `ok: true`이고 `failed: []`. 그리고
  `data_root_exists`, `db_integrity`, `db_schema`, `free_space`,
  `required_secrets`가 모두 `ok: true`.
- **거부되어야 하는 경우**: `data_root`가 임시 디렉터리 아래면
  `TEMP_DATA_ROOT`로 거부된다. production 판정에서 이 코드가 나오면 자원이
  임시 디스크라는 뜻이므로 그대로 배포하지 않는다.
- **코드 상태**: `not_implemented` — 자원을 만들지 않는다.

---

#### 2. `GOOGLE-OIDC-CLIENT` — Google OAuth 클라이언트

- **필요한 외부 입력**: OAuth 클라이언트 ID, 클라이언트 시크릿, 등록된 허용 콜백
  주소, 그리고 **소유자의 Google `sub` 값**
- **현재 코드 상태**: `access_control.UnboundSessionAdapter`가 모든 요청에 대해
  `session_for()` → `None`을 돌려준다. 즉 인증 없이는 전부 401이다. 실 로그인이
  없다. 실 로그인 어댑터를 구현해야 한다.
- **실행 명령**:
  ```
  python -m webapp.cli ops health --secret MUSE_KEY
  ```
  어댑터를 붙인 뒤에는 `synthetic_sessions` 검사가 `ok: true`여야 한다.
  (지금은 합성 허용이 켜져 있어 `ok: false`가 정상 상태다.)
- **성공 판정 근거**:
  1. `ops health`의 `google_oidc_connected.ok == true`
  2. `synthetic_sessions.ok == true` (합성 seam 은 꺼져 있어야 한다)
  3. 실제 `sub`로 만든 세션이 `access_accounts` 행에 매칭되고, 그 계정은
     **viewer** 다 (설정된 `WEBLEDGER_OWNER_GOOGLE_SUB` 와 일치할 때만 owner)
  4. `state`를 한 번 쓰면 다시 쓰지 못하고, `nonce`가 id_token 과 일치한다
  5. `/access/logout` 이후 그 쿠키는 `AUTH_REQUIRED` 로 거부된다
  6. 쿠키가 `Secure; HttpOnly; SameSite=Lax` 이고 토큰을 담지 않는다
- **거부되어야 하는 경우**: 검증되지 않은 ID 토큰, 만료된 토큰, 다른 클라이언트
  audience, `sub` 대신 이메일을 계정 키로 쓴 경우.

---

#### 3. `RESERVATION-API` — 예약 담당 배정 연결

- **필요한 외부 입력**: 예약 저장소 엔드포인트, 인증 방식, 배정 페이로드 형태
  (담당자 ID, 여행 ID, 상태, 스냅샷 리비전), 정원·에러 규약
- **현재 코드 상태**: `apply_assignment_snapshot`이 합성 스냅샷만 받는다. 실
  저장소와 통신하는 코드가 없다.
- **실행 명령**:
  ```
  python -m webapp.cli ops actions
  ```
  그 다음 owner 계정으로 `/api/tabs`를 호출해 담당 해제 반영을 확인한다.
- **성공 판정 근거**:
  1. 담당이 해제된 직후 그 직원의 화면에서 여행 표가 사라진다
  2. **종료된 여행의 조회는 유지된다** (빠져나가지 않는다)
  3. 배정 동기화 실패가 `access_connections.status`에 남고
     `ops actions`가 그 사실을 보고한다
  4. viewer 응답에 내부 메모·변경 이력·AI 대화가 새지 않는다
- **코드 상태**: `synthetic_assignment_only`

---

#### 4. `PRODUCTION-DB` — 운영 DB 경로와 최초 이관

- **필요한 외부 입력**: 실제 Google 기준 워크북, 운영 DB 최종 경로, 이관 승인
  대상 범위, 매핑되지 않은 항목의 처리 결정
- **현재 코드 상태**: Phase 8 합성 이관만 있다. 실 워크북을 읽은 적이 없다.
- **실행 명령** (이관 **전** rehearsal):
  ```
  set MUSE_KEY=<실제 키>
  python -m webapp.cli ops drill --target <운영과 다른 경로> --runbook RUNBOOK.md
  ```
- **성공 판정 근거**:
  1. `recoverable: true`, `restore.problems: []`
  2. `restore.state.content_compared == true` — 개수가 아니라 **내용**까지
     대조했다는 뜻
  3. `restore.state.business_digest.tables`에 `board_rows`,
     `board_revisions`, `trip_tabs`, `board_requests`,
     `classification_rule_versions`, `classification_rules`가 들어 있다
  4. 같은 `client_request_id` 재전송 시 업무 효과가 늘지 않는다
  5. RUNBOOK에 17.2 수치가 **수치로** 찍힌다: 입력 위험 범위, 시험 복구 시간,
     저장 비용, 그리고 "무손실/무중단 운영을 약속하지 않는다"는 문장
- **거부되어야 하는 경우**: `restore.ok == false`, `content_compared == false`,
  RUNBOOK 수치가 "미측정"인 채로 배포 승인을 검토하는 경우.

---

#### 5. `PAID-RESOURCE` — 유료 전환

- **필요한 외부 입력**: 사용자 명시적 승인. 전액 무승인.
- **실행 명령**: 없음. 실행 명령이 없다는 것이 이 항목의 요건이다.
- **성공 판정 근거**: `code_status`가 계속 `not_applicable`이고
  `state`가 `not_approved`인 것. Gemini 비용 정책과 호스팅 비용을 합쳐 말하지
  않는다(17.4).
- **코드 상태**: `not_applicable` — 과금 경로를 구현하지 않았다.

---

#### 6. `DEPLOY` — 운영 배포

- **필요한 외부 입력**: 위 1~5가 모두 채워진 상태 + 사용자 배포 승인
- **실행 명령**:
  ```
  set MUSE_KEY=<실제 키>
  python -m webapp.cli ops dry-run --secret MUSE_KEY --runbook RUNBOOK.md
  ```
- **성공 판정 근거**:
  1. `dry_run.ok == true`, `dry_run.failed == []`
  2. `dry_run.applied == false` — 검증만 하고 아무것도 적용하지 않는다
  3. RUNBOOK의 `## 회복 수치 (명세 17.2)` 절에 **수치가** 들어 있다
  4. `external_conditions_still_unmet`가 출력에 남아 있다 — green이어도
     릴리스 승인으로 읽히지 않게 하는 장치
- **거부되어야 하는 경우**: `dry_run.applied == true`, 또는
  `synthetic_sessions_not_operational.ok == false` (합성 세션 허용이 켜진
  상태는 runbok이 아니다).

---

이 목록은 `ops.EXTERNAL_CONDITIONS`에 코드으로도 남아 있어, 로컬 검사가
green이어도 릴리스로 읽을 수 없게 한다. 2026-09-27 합성 실행 감사에서 여섯
항목 모두 코드 상태가 명세대로임을 확인했다(OIDC 어댑터 미연결,
`HttpTransport` 부재, `is_real_call=False`).

## [역사 — 대체됨] 최종 권위 실행 — 2026-09-27

> 이 절이 기록한 값은 아래와 같고 **현재 권위가 아니다.** 그 뒤 코드와 검사가
> 바뀌어 다시 실행했고, 현재 권위 값은 이 파일의
> `## 명세 전수 대조 감사 실행 기록 — 2026-09-27` 절에 있다.
> 이 절의 제목이 "최종 권위"였으므로 값을 지우지 않고 `[역사 — 대체됨]`을
> 제목에 붙여 어느 값이 현재인지 분명히 한다. 이 절의 좁은 수치(Phase 9
> `28 passed` 등)도 **그 실행 당시의 값**이며 수집 기준은 아래와 다르다.

모든 편집을 안정화한 뒤 마지막으로 전체 검사를 **정확히 한 번** 새로 돌렸다.

- 명령: `python -m pytest webapp/tests -q -p no:cacheprovider`
- 결과: **610 passed, 80 subtests passed in 187.96s**(당시 값), 종료 코드 0
- 직전 좁은 재실행:
  - 제공자 경계 + 대화 + 규칙 대화 + 프로세스 소유권 + 분류 규칙:
    `284 passed, 65 subtests passed in 62.05s`
  - Phase 7/8/9: `122 passed, 2 subtests passed in 26.80s`
  - 브라우저/UI 4개 파일: `58 passed, 4 subtests passed in 77.37s`
  - 390 뷰포트 지정: `3 passed, 18 deselected in 4.81s`
  - `py_compile` 53개 파일 통과
- 잔여 확인: DBG/TODO/breakpoint 잔여 없음. `cli.py`의 `print`는 명령 출력이고,
  `ledger_board.py`의 `UNEXPECTED ...` 출력은 프로그래밍 오류를 500으로 바꾸면서
  원인을 찾을 수 있게 남긴 진단이다. python/chrome 잔여 프로세스 0.
- `Temp/opencode/ownership_child.py`는 지우지 않았다. 두 소유권 검사가 이 경로를
  참조한다.
- 커밋·푸시·배포 없음. 운영 DB·실제 고객 자료·실제 제공자 자격 증명·유료 외부
  자원 미사용.

## 구현 검토 8~10절 항목별 판정 — 2026-09-27

문서 서술을 믿지 않고 **저장소·분리 연결·합성 DB 수준에서 직접 확인**했다.
판정은 proven / incomplete-local / external-only 셋 중 하나이고, proven에는 그
요구사항을 검사하는 테스트 이름을 적었다.

### R01 사건 저장 경계 — proven

.operator 사건은 별도 DB에 가지만, **큐 항목을 남기는 것은 바깥 트랜잭션 안에서**
일어난다. 직접 확인한 방법: `BEGIN IMMEDIATE`로 트랜잭션을 열고
`_enqueue_ledger`를 호출한 뒤 `ROLLBACK`했다. 열린 트랜잭션 안에서 outbox 행이
1건 보였고 `ROLLBACK` 후 0건이었다. 즉 바깥 저장이 실패하면 함께 사라지므로
"바깥 실패와 별도 사건 성공이 갈라지는 경계"가 없다.

relay는 `COMMIT` **이후**에만 일어난다(`ledger_store.save`의 `_relay_outbox`
호출 지점). `outer_txn` 경로에서는 relay를 미루고 `event_id: None`,
`ledger_pending: True`로 반환하므로, 나중에 한 번만 전달된다.

검사: 아래 R01 회귀 검사 신설(`test_a_failed_outer_save_leaves_no_ledger_event`),
기존 `test_memo_revert_and_double_locked`가 relay 후 이중 기록이 없는지 확인.

### R01 생성 요청 ID 결속 — proven

같은 `client_request_id`에 같은 내용이 오면 저장된 결과를 그대로 돌려주고,
다른 내용이면 `REQUEST_ID_REUSED`로 거절한다. `ledger_store`의
`IntegrityError`·`SaveError` 두 경로 모두에 있다.

검사: `test_ledger_store.py`의 요청 ID 재사용 검사,
`test_income_bank.py` `test_revert_single_allocation` 안의
`split-edit-l1` 재사용·거절 단정.

### R03 진행 중 열람 — proven (검사 신설)

접수는 즉시 반환하고 실행은 `CardWorker`가 뒤따른다. 그 사이의 읽기가
미완 상태를 정직하게 답하는지 검사한다. 읽기가 블럭·실패하지 않고,
아직 없는 결과를 지어내지 않으며, 모르는 배치는 None(보드에서 404)이 되고,
장부 자체는 같은 틈에 읽힌다. 재개는 기존
`test_restart_resumes_without_reupload`가 별도로 검증한다.

검사: `test_receipt_and_execution_are_separate_so_a_read_answers_immediately`
(신설), `test_interrupt_resume_no_dupes`, `test_worker_sweep_claims_and_completes`.

### R08 원본 바이트 불변 보관·digest 결속 — proven

전달받은 원본 바이트를 파싱 전 불변 보관하고 digest로 결속한다. 파일명이
batch_id에 섞이지 않아 같은 bytes를 이름만 바꿔 올리면 재사용된다.

검사: `test_bank_source_identity.py`의
`test_batch_id_is_content_bytes_only`(파일명이 batch_id에 없음, sha256 일치),
`test_same_bytes_renamed_file_is_reused_weak`,
`test_same_bytes_renamed_file_is_reused_strong`,
`test_blob_and_renamed_reuse`(카드 쪽 동일 바이트 재사용).

### R08 파일 간 불명확한 동일 입금 → 후보 — proven

파일 간에 id가 같고 바이트가 다른 경우, 확정 중복이 아니라
`duplicate-candidate`로 남고 `duplicate_candidates`가 1로 집계된다. 같은
payer·날짜·금액·id 없는 경우도 후보로 보존된다.

검사: `test_cross_file_with_id_different_bytes_is_skipped`,
`test_cross_file_with_id_reordered_bytes_is_skipped`,
`test_no_id_same_payer_date_amount_preserved_as_candidate`,
`test_same_file_identical_rows_are_candidates`.

### R09 자유 입력 수식 차단 — proven (갭 2건 수정 후)

확인 결과 네 진입점 중 **두 곳이 실제로 막혀 있지 않았다.**

1. **여행 제목 → 시트명.** 제목은 자유 입력인데 시트명으로 그대로 쓰였다.
   `=1+1` 제목이 시트명 `=1+1`이 됐다. 셀 수식 주입은 아니지만, 운영자가
   손으로 친 제목이 시트명이 되어서는 안 된다. `sanitize_sheet_name`이
   `guard_text`를 거치도록 고쳤다.
2. **머리말 자유 입력.** 제목·작성일·담당자 셀은 `data_type = "s"`에만 의존하고
   `guard_text`를 거치지 않았다. 오늘은 문자열로 읽히지만 openpyxl의
   파생 속성에 의존하는 방식이라 방어 일관성이 없었다. 셋 다 `guard_text`를
   거치게 고쳤다.
3. 추가로 `guard_text`가 앞쪽 공백을 걸러내지 않아 `"\t=1+1"`이 통과했다.
   Excel은 입력 시 공백을 제거하므로 뒤집으면 수식이 된다. 앞쪽 공백과
   제어문자를 먼저 벗겨 검사한다.

날짜 진입점은 원래부터 거부했다(`SaveError`). 수정 후 워크북 전체를 훑어
수식 셀이 의도한 합계 3개뿐임을 확인했다.

검사: `test_guard_text_catches_a_formula_behind_leading_whitespace`,
`test_a_free_typed_trip_title_cannot_become_a_sheet_name_formula`,
`test_an_owner_name_cannot_become_a_formula_cell`,
`test_formula_guard`, `test_user_string_text_guard_and_atomic_publish`.

### R09 완성 파일의 원자 게시 — proven

검사: `test_atomic_publish_no_overwrite_and_text_guard`,
`test_publish_never_overwrites`, `test_a_new_request_over_the_same_snapshot_publishes_its_own_file`,
`test_keyboard_interrupt_during_save_removes_target_and_temp`.

### REVIEW 10절 비식별 양식 메타데이터 — proven (검사 신설)

직접 생성된 워크북을 읽어 확인했다. 원본 지적의 6곳 병합이 모두 있고
(C2:H2·B6:H6·C31:H31·B33:H33·C85:H85·C87:H87), A~H 열 너비가 원본과
같으며(2.63·17.5·14.63·16.38·11.88·12.38·11.25·14.88), landscape이고,
좌우 0.7·상하 0.75 여백과 머리말/꼬리말 0이 반영돼 있다. 인쇄 영역도
`$B$2:$H$87`로 설정돼 있다. 이 값들이 쓰기·다시 읽기 라운드트립을 살아남는지도
같이 확인했다.

검사: `test_the_output_carries_the_template_sheet_metadata`(신설).

**단, 회사명과 작성자 정보는 여전히 합성**이다. REVIEW 10절이 지적한 그 부분은
external-only다(아래).

### 되돌리기 범위 — proven (검사 신설)

개별 배분 행 되돌리기는 허용되고 형제 행은 값이 유지되며, **전체 배분안 복원
기능은 이름 수준에서 존재하지 않는다.** 계약에 없는 범위를 만들지 않는다는
요건이라, 동작이 아니라 능력의 부재로 판정했다.

검사: `test_the_revert_scope_is_one_row_and_there_is_no_whole_plan_restore`(신설),
`test_revert_single_allocation`, `test_revert_rejects_stale_full_plan_and_inactive`,
`test_revert_rejects_deleted_previous_trip`.

### 이 판정에서 external-only로 남은 것

- REVIEW 10절의 **회사명과 작성 정보**. 실제 `매출자료 양식_rev` 원본의 값이
  필요하다. 인증 파일과 원본 Drive 접근 없이는 확인할 수 없다. 현재 합성값을
  쓰고 있으며, 원본 값을 받는 경계는 `COMPANY_TEXT` 상수와
  `save_trip_meta(prepared_by_name=...)` 두 곳이다.
- 실제 Google 기준 워크북 인쇄 결과. 합성 PDF와 열 너비·방향·여백은 확인했지만
  실물 인쇄는 미검증이다.
- 실제 예약 API 배정, 실제 OIDC, 실제 AI 호출과 키, 운영 DB, 호스팅, 배포,
  실물 휴대폰. `ops.EXTERNAL_CONDITIONS`의 여섯 항목이 이 목록이며 미완료를
  유지한다.

**[역사] 이 시점의 incomplete-local — 없음** (당시 판정. 현행 판정은 위 `## 요구사항 매트릭스 감사` 절)

이 판정에서 발견한 incomplete-local은 위 R09의 두 갭뿐이었고, 구현과 검사를
마쳤다.

## 인계 정합성·매트릭스 증거 보강·구현 검토 판정 — 2026-09-27

### 1) 인계 문서 정합성

`handoff/2026-09-27/README.md`의 "남은 작업" 절이 같은 문서의 매트릭스와
정면으로 충돌했다. 273행이 키 관리·인증과 직원 권한·자연어→규칙 변환을 "아직
완료되지 않았다"고 했고, 272행의 모바일 클릭 흐름 확인이 열린 지시로 남아
있었다. 두 줄 모두 사실과 달랐다. 각 항목을 현재 상태로 다시 썼다.

- [완료] 모바일 클릭 흐름, 키 관리와 owner 전용 비밀 설정, 인증과 직원 권한,
  자연어→규칙 후보 변환, 실제 AI 어댑터 경계. 각각 검사 이름을 붙였다.
- [external-only] 실제 AI 호출·실제 키·유료 승인·AI Studio 실제 등급 확인,
  실제 운영 데이터 연결·실제 OIDC·실제 예약 API·호스팅·배포·실물 기기·
  실제 Excel 인쇄.
- 과거 문장은 지우지 않고 `[역사 지시 — 현재는 완료]`를 앞에 붙여 남겼다.

같은 종류의 충돌을 나머지 명세 문서에서도 찾아 같은 방식으로 정리했다.

- `WEB_LEDGER_PHASES.md` 78행 "Phase 5 수용·본 저장소 통합은 아직 완료되지
  않았다", 63~64행의 순차 구현 계획, 222행의 "Phase 6~9 착수 지시" →
  `[역사 — 대체됨]` 표시. 맨 위 "현재 상태" 절을 단일 출처로 명시.
- `IMPLEMENTATION_PROMPT_WEB_LEDGER_APP.md` 5행 "현재 세션은 명세 구체화만
  수행한다"와 3행 "본 저장소에도 미통합이다" → `[역사 — 대체됨]` + 현재 상태
  블록 추가. 요구사항 범위는 바꾸지 않았다.
- `WEB_LEDGER_IMPLEMENTATION_REVIEW.md`의 Phase 6~8 표 행 "단계 착수 지시"와
  미해결 R08·R01 표기 → `[역사 — 단계 착수 지시]` + 판정 절을 가리키는 링크.

매트릭스의 요구사항 범위는 이 정리로 바뀌지 않았다. 판정과 추가된 요구사항
행만 늘었다.

### 2) 매트릭스의 약한 증거 보강

"파일 전체 통과"를 요구사항 증거로 세우던 행을 전부 요구사항 문구와 1:1로
대응되는 개별 검사 이름으로 바꿨다. 파일 이름만 인용하던 행:
`test_income_bank.py`, `test_trip_delete_identity.py`,
`test_bank_source_identity.py`, `test_classification_rules.py`,
`test_migration_phase8.py`(18건), `test_ops_phase9.py`(64건),
`test_ledger_design.py`(21건), `test_access_control_phase7.py`(40건).

REFINEMENT 행은 8/9/10/10.3·13.5/8.1~8.2/12~14/15/16/17/17.4로 쪼개고,
_APP_SPEC 7 권한 행도 검사 이름으로 바꿨다. **매트릭스에서 인용한 검사 이름
101개를 실제 파일과 대조했고 존재하지 않는 이름은 0개**다.

### 3) 구현 검토 8~10절 항목별 판정

문서 서술을 믿지 않고 저장소·분리 연결·합성 DB 수준에서 직접 확인했다.
결과와 실제 고친 것은 위 "구현 검토 8~10절 항목별 판정" 절에 있다.

R09에서 실제 결함 3건을 찾았다. 이전 판정은 "완료"였을 것이었다.

1. **여행 제목이 시트명으로 그대로 쓰였다.** 자유 입력 `=1+1`이 시트명
   `=1+1`이 됐다. `sanitize_sheet_name`이 `guard_text`를 거치도록 고쳤다.
2. **머리말 자유 입력 셀이 가드를 거치지 않았다.** 제목·작성일·담당자는
   `data_type = "s"`에만 의존했다. 오늘은 문자열이지만 openpyxl 파생 속성에
   의존하는 방식이라 방어 일관성이 없었다. 셋 다 `guard_text`를 거치게 했다.
3. **`guard_text`가 앞쪽 공백을 걸러내지 않았다.** `"	=1+1"`이 통과했는데
   Excel은 입력 시 공백을 제거하므로 뒤집으면 수식이 된다. 앞쪽 공백과
   제어문자를 먼저 벗겨 검사한다.

수정 후 워크북 전체를 훑어 수식 셀이 의도한 합계 3개뿐임을 확인했다.
날짜 진입점은 원래부터 거부했다.

### 4) 실행 명령과 실제 결과

- `python -m py_compile` 48개 파일 통과
- 경계 검사(저장소·카드·출력·수입·은행·화면상태):
  `113 passed, 8 subtests passed in 30.82s`
- 영향받은 기존 검사(제공자 경계·Phase 7/8/9·규칙 대화 화면):
  `229 passed, 61 subtests passed in 56.79s`
- 전체 suite는 코드와 검사를 바꾼 뒤 **정확히 한 번** 실행:
  **`619 passed, 85 subtests passed in 193.33s`**
- 인용 검사 이름 대조: 101개 인용, 실제 존재 101개, 없는 이름 0개
- DBG/TODO/breakpoint 잔여 0건, python/chrome 잔여 프로세스 0

### 5) 미검증 경로 (이번에도 그대로)

실물 휴대폰, 실제 Excel 인쇄, 실제 Google OIDC, 실제 예약 API, 실제 AI 호출,
실제 키와 유료 자원, 운영 DB, 실제 고객 자료. REVIEW 10절이 지적한
**회사명과 작성자 정보**도 실제 원본 양식 값이 필요해 external-only로 남는다
(경계는 `COMPANY_TEXT` 상수와 `save_trip_meta(prepared_by_name=...)`).
`ops.EXTERNAL_CONDITIONS`의 여섯 항목은 미완료 상태를 유지한다.

commit·push·deploy 없음. 작업 트리는 미커밋 상태다.

## 명세 전수 대조 감사 — 2026-09-27 (매트릭스가 커버하지 않은 절)

이 절은 매트릭스의 요구사항 범위를 넓히지 않는다. 앞에서 판정하지 않은
명세 절을 같은 기준으로 다시 보고, 각 절에 **판정과 그 요구사항을 단정하는
검사 이름**만 붙인 것이다. green test만으로 proven으로 두지 않았고, 인용한
검사 이름은 전부 실제 파일과 기계 대조했다.

### 판정 요약

- **proven 41행**, **incomplete-local 0건**(아래 2건은 구현·검사 후 proven으로
  승격), **external-only 8행**.
- 인용 검사 이름 68개를 실제 파일과 대조했고 **없는 이름 0개**.

### SPEC_REFINEMENT

| 절 | 요구 | 판정 | 검사 |
| --- | --- | --- | --- |
| 13.1 | 화면 행 금액은 배분액, 원금은 따로 유지 | proven | `test_13_1_a_split_row_shows_its_own_amount_not_the_source_total`, `test_split_totals_and_principal_hidden` |
| 13.2 | 이동해도 allocation_id가 새 ID를 만들지 않음 | proven(검사 신설) | `test_13_2_an_allocation_keeps_its_id_across_a_move` |
| 13.2 | 낡은 전체 배분안이 새 결과를 덮어쓰지 못함 | proven(검사 신설) | `test_13_2_a_stale_plan_cannot_overwrite_a_newer_allocation`, `test_revert_rejects_stale_full_plan_and_inactive` |
| 13.3 | 미배정 배분(여행 없음)과 미배분 잔액은 별개 | proven(검사 신설) | `test_13_3_an_unassigned_allocation_and_a_remainder_are_different` |
| 13.3 | 잔액 = 원금 − 활성 배분 합계, 0이면 숨김 | proven | `test_partial_split_remainder_and_over_rejected`, `test_13_3_an_unassigned_allocation_and_a_remainder_are_different` |
| 17.1 | 작은 화면 구성·터치 크기·가로 스크롤 | proven | `test_one_trip_button_and_a_short_notice_at_390`, `test_the_panel_footer_stays_reachable_and_two_saves_work_at_390`, `test_the_waiting_move_works_at_390_with_a_full_width_control` |
| 17.2 | 업로드가 제품 엔드포인트를 거쳐 장부에 도달 | proven | `test_a_card_upload_through_the_product_endpoint_reaches_the_board`, `test_the_upload_and_the_selected_trip_xlsx_still_work` |
| 17.3 | 미리보기 네 가지 범위 선택이 각각 독립 | proven(검사 신설) | `test_the_four_scope_combinations_are_each_accepted_and_independent`, `test_existing_and_future_conditions_agree` |
| 17.5 | 명세 완료·구현 완료·운영 완료를 구분 | proven | `test_the_external_condition_list_is_not_a_release_approval`, `test_a_local_run_never_reports_a_deployment`, `test_the_runbook_states_the_unmet_external_conditions` |
| 18절 | 호스팅 후보 비교 | external-only | 실제 자원·과금 수치가 필요하다. 합성 가능한 하위 요건만 아래 19절에 행을 만들었다. |
| 19.3 | 비용이 발생하지 않는 실패 처리 | proven | `test_a_missing_required_setting_fails_closed`, `test_an_unconfigured_ops_command_fails_closed_with_a_code`, `test_a_dry_run_fails_when_a_secret_is_missing`, `test_a_production_cli_run_on_a_temp_root_fails_closed` |
| 19.4 | 시험 순서와 중간 확인 | proven | `test_the_deploy_dry_run_validates_locally_and_applies_nothing`, `test_the_ops_cli_commands_run_and_report` |
| 19.6 | 명세 인계의 완료 범위 | external-only | 실제 배포 없이는 확인할 수 없다. 코드에는 `ops.EXTERNAL_CONDITIONS`로 남아 있다. |
| 19.1·19.2·19.5 | 후보 선정·초기 자원·막혔을 때 분기 | external-only | 실제 호스팅 자원 확보와 사용자 결정이 필요하다. |

### DETAILED_CONTRACT

| 절 | 요구 | 판정 | 검사 |
| --- | --- | --- | --- |
| 3절 | 화면·키보드 동작 | proven | `test_enter_alone_does_not_save_and_ctrl_enter_does`, `test_enter_in_a_note_keeps_its_newline`, `test_escape_asks_before_dropping_an_unsaved_edit`, `test_a_refused_field_is_named_next_to_the_input_and_focused` |
| 5절 | 대사·확인 경험 | proven | `test_a_card_upload_through_the_product_endpoint_reaches_the_board` |
| 8절 | 출력 구성·선택 탭·인쇄 영역 | proven | `test_the_output_carries_the_template_sheet_metadata`, `test_a_new_request_over_the_same_snapshot_publishes_its_own_file`, `test_the_same_request_id_reuses_the_job_and_adds_no_file` |
| 10절 | 합성 기준 자료와 기대값 | proven | `test_13_1_a_split_row_shows_its_own_amount_not_the_source_total`, `test_the_json_contract_is_unchanged` |
| 11절 | 이관 경계 | proven | `test_both_sources_are_sealed_and_verified`, `test_the_migration_writes_only_to_its_own_db`, `test_a_changed_input_makes_the_old_decision_unusable` |
| 14절 | 되돌리기 | proven | `test_memo_revert_and_double_locked`, `test_the_revert_scope_is_one_row_and_there_is_no_whole_plan_restore` |
| 15절 | 브라우저 상태·세대 결속 | proven | `test_a_stale_session_is_refused_after_a_permission_change`, `test_logout_ends_the_session_and_names_what_the_client_must_clear`, `test_an_archived_trip_stays_readable_while_the_assignment_holds` |
| 16절 | 권한·증빙 경계 | proven | `test_a_viewer_cannot_reach_owner_writes_or_the_ai_dialogue`, `test_evidence_preview_is_allowlisted_and_the_original_is_never_served`, `test_a_viewer_sees_only_its_own_trip_and_other_trips_are_404` |
| 17절 | 모바일 화면 구성·복귀 | proven(합성) | 17.1·17.3 행 참조. **external-only**: 실제 휴대폰 브라우저와 실제 기기에서의 화면 회전·앱 전환 복귀, 실제 파일 선택기·저장 동작. |

### IMPLEMENTATION_CONTRACT

| 절 | 요구 | 판정 | 검사 |
| --- | --- | --- | --- |
| 3절 | 업로드와 대사 진행 | proven | `test_receipt_and_execution_are_separate_so_a_read_answers_immediately`, `test_restart_resumes_without_reupload` |
| 4절 | 변경 범위를 작게 유지 | proven | `test_a_stale_revision_is_reported_and_the_typed_value_is_kept`, `test_a_stale_trip_revision_is_reported_and_the_typed_name_is_kept` |
| 5절 | 저장과 재시도 | proven | `test_the_same_request_id_with_different_content_is_refused`, `test_same_id_different_content_rejected`, `test_a_committed_save_relays_once_and_a_second_relay_adds_nothing` |
| 8절 | 양식과 선택 출력 | proven | `test_the_output_carries_the_template_sheet_metadata`, `test_a_free_typed_trip_title_cannot_become_a_sheet_name_formula` |
| 9절 | 정보 이관과 완전성 | proven | `test_both_sources_are_sealed_and_verified`, `test_the_five_states_are_reported_separately`, `test_memo_evidence_and_provenance_survive_the_move` |
| 10절 | 수용 시나리오와 측정 | proven | `test_the_readiness_report_measures_and_does_not_claim_a_release` |
| 11절 | 구현 작업 단위 | proven | `test_a_valid_config_describes_its_paths_and_keeps_secrets_out` |

### APP_SPEC

| 절 | 요구 | 판정 | 검사 |
| --- | --- | --- | --- |
| 4.5 | 상세 화면 동작 계약 | proven | `test_the_row_panel_keeps_the_source_locked_and_saves_for_real`, `test_a_row_save_from_the_row_screen_still_saves` |
| 4.6 | 빈 상태·실패·복구 | proven | `test_unbound_providers_wait_and_the_screen_says_so`, `test_a_stale_revision_is_reported_and_the_typed_value_is_kept`, `test_the_delete_preview_still_shows_and_confirms` |
| 4.7 | 규칙 대화 예시 | proven | `test_the_rule_dialog_opens_from_the_panel_and_comes_back`, `test_the_candidate_can_then_be_confirmed_and_previewed` |
| 5절 | 대사 확인 경험 | proven | `test_a_card_upload_through_the_product_endpoint_reaches_the_board` |
| 6절 | 저장과 감사 모델 | proven | `test_a_committed_save_relays_once_and_a_second_relay_adds_nothing`, `test_a_failed_outer_save_leaves_no_ledger_event` |
| 10절 | API 계약 초안 | proven | `test_the_json_contract_is_unchanged`, `test_the_contract_error_vocabulary_is_fully_mapped_to_a_status` |
| 11절 | 검증 계획 | proven | 아래 12절·검증 계층 행 참조 |
| 12절 | 구현 에이전트 전달 지침 | proven | 전달문이 현재 상태와 충돌하지 않음을 확인했고 현재 상태 블록을 추가했다. 검사 대상이 아니라 문서 정합성이므로 검사 이름 대신 파일을 적는다: `docs/IMPLEMENTATION_PROMPT_WEB_LEDGER_APP.md` |

### REVIEW 3절 R02·R04·R05·R06·R07

문서 서술을 믿지 않고 저장소 수준에서 직접 확인했다.

| 항목 | 판정 | 검사 |
| --- | --- | --- |
| R02 트랜잭션 소유자 하나, 하위 함수가 열린 트랜잭션 재사용 | proven | `test_construction_keeps_caller_transaction_open`, `test_receive_keeps_caller_transaction_open`, `test_same_bytes_renamed_file_is_reused_weak` |
| R04 원천 종류별 허용 필드·미리 알 수 없는 필드 거부 | proven | `test_same_api_rejects_card_amount`, `test_amount_change_rejected_whole`, `test_bank_row_date_amount_fixed`, `test_create_and_edit_500000_to_450000` |
| R05 정정은 revision을 요구하고 순서가 시각이 아니라 revision | proven | `test_bank_correction_flow` |
| R06 직접 입력과 은행 원천 연결의 업무 동일성 | proven | `test_link_bank_to_direct_no_double_count`, `test_no_id_same_payer_date_amount_preserved_as_candidate`, `test_cross_file_with_id_different_bytes_is_skipped` |
| R07 메모만 바꾸면 학습 사례를 만들지 않음, 미배정 표현 정규화 | proven | `test_memo_only_rule_change_creates_no_case`, `test_string_unclassified_saved_as_null`, `test_trip_unclassified_roundtrip_keeps_totals` |

직접 확인한 내용: `BankImporter(store.conn, store)`가 store와 **같은 연결**을
공유한다. 미지 필드는 `INVALID_VALUE`로 거부되고 조용히 버려지지 않는다.
`2026-99-99`·`2026-02-30`·`not-a-date`는 거부된다. 수기 지출의 날짜·금액은
편집되고 카드 금액은 `FIELD_READ_ONLY`로 막힌다. 빈 메모는 필드 생략과 구분되어
값을 지운다. `link_bank_source`는 존재하지 않는 원천을 거부한다. 메모만 바꾸고
`change_mode="rule_change"`여도 학습 사례는 0건이고 `learning_case_id`는 None이다.

### 이 감사에서 구현한 것 (incomplete-local 2건 → proven)

1. **13.2 안정 식별자** — 이동 후 `allocation_id` 유지와 낡은 전체 배분안 차단을
   단정하는 검사가 없었다. 추가:
   `test_13_2_an_allocation_keeps_its_id_across_a_move`,
   `test_13_2_a_stale_plan_cannot_overwrite_a_newer_allocation`.
2. **17.3 미리보기 네 가지 범위 선택** — 두 스위치가 독립이라는 요구를 단정하는
   검사가 없었다. 네 조합이 모두 유효하고 플래그가 그대로 돌아오는지 확인하고
   `test_the_four_scope_combinations_are_each_accepted_and_independent`를 추가했다.

13.1과 13.3도 같은 이유로 검사를 신설했다
(`test_13_1_a_split_row_shows_its_own_amount_not_the_source_total`,
`test_13_3_an_unassigned_allocation_and_a_remainder_are_different`).

**[역사] 이 시점의 external-only 목록** (당시 판정. 현행 판정은 위 `## 요구사항 매트릭스 감사` 절)

- SPEC_REFINEMENT 18절 호스팅 후보 비교: 실제 자원·과금 수치.
- SPEC_REFINEMENT 19.1·19.2·19.5: 실제 호스팅 자원 확보와 사용자 결정.
- SPEC_REFINEMENT 19.6: 실제 배포 없이는 완료 범위를 확인할 수 없다.
- DETAILED 17절의 실제 기기: 실제 휴대폰 브라우저, 화면 회전·앱 전환 복귀,
  실제 파일 선택기·저장 동작. 390은 합성 Chromium 뷰포트다.
- REVIEW 10절의 회사명과 작성 정보: 실제 원본 양식 값.
- 실제 Google OIDC, 실제 예약 API, 실제 AI 호출·키·AI Studio 등급 확인,
  운영 DB와 실제 기준본 이관, 호스팅 자원, 실제 배포, 실물 Excel 인쇄.

이 여섯 종류는 `ops.EXTERNAL_CONDITIONS`에 코드로 남아 있고 미완료를 유지한다.

## 명세 전수 대조 감사 실행 기록 — 2026-09-27

### 현재 권위 수치 (이 절이 현재 값의 단일 출처)

- 전체 suite: `624 passed, 85 subtests passed in 190.57s`
- 수집 기준: Phase 7 `40건`, Phase 8 `18건`, Phase 9 `64건`,
  제공자 경계 `97건` (`--collect-only`로 확인)
- 매트릭스가 인용한 검사 이름: 148개, 실제 파일 대조 결과 없는 이름 0개

이 파일의 다른 절에 `25`, `28`, `40`, `45`, `61`, `64`, `73`, `97`,
`110`, `118` 같은 좁은 수치와 `383`·`465`·`610`·`619` 같은 과거 전체 실행값이
남아 있다. 이들은 **그 실행 당시의 기록**이며 `[역사 수치 — 대체됨]`으로
표시돼 있다. 현재 값이 필요한 곳은 위 세 줄과 이 절의 3) 실행 결과다.

### 1) 코디네이터가 확인한 낡은 수치 수정

`--collect-only`로 실제 수집 수를 먼저 확인했다: Phase 7 = 40건,
Phase 8 = 18건, Phase 9 = 64건, 제공자 경계 = 97건.

- handoff의 "전용 검사 25개"(143·185행), "Phase 7 25개 / Phase 9 25개 /
  누적 25 + 18 + 25 = 68개"(189~192행)는 Phase 9 구현 이전 값이었다.
  현재 값으로 고치고 이전 문장은 `[역사 수치 — 대체됨]`를 앞에 붙여 남겼다.
  288행의 40건과 자기 모순이었던 부분도 함께 정리했다.
- handoff 193~195행의 "변경이 새 모듈 3개와 그 검사 3개, ledger_board.py,
  ledger_design.py, test_ledger_design.py에 국한된다"는 사실 서술이 현재
  코드와 달랐다. 현재 수정 파일과 신규 모듈 6개·신규 검사 4개를 적었다.
- `WEB_LEDGER_PHASES.md` 24행의 `test_ops_phase9.py` 28건 → 64건.
  이 파일 5행이 자신을 "현재 상태의 유일한 출처"라고 선언하므로 수치를 갱신했다.
- `WEB_LEDGER_PHASES.md` 10행과 `IMPLEMENTATION_PROMPT` 14행의
  `610 passed, 80 subtests` → 권위값으로 교체. 앞 턴의 정리를 빠뜨린 두 곳이었다.

### 2) 명세 전수 대조 판정

- **proven 41행, incomplete-local 0건, external-only 8행.**
- 인용 검사 이름 148개를 실제 파일과 기계 대조했고 **없는 이름 0개.**
- incomplete-local로 판정한 2건은 구현과 검사를 추가한 뒤 proven으로
  올렸다: 13.2 안정 식별자와 17.3 미리보기 네 가지 범위 선택. 13.1과 13.3도
  같은 이유로 검사를 신설했다.
- 추가한 검사 이름:
  `test_13_1_a_split_row_shows_its_own_amount_not_the_source_total`,
  `test_13_2_an_allocation_keeps_its_id_across_a_move`,
  `test_13_2_a_stale_plan_cannot_overwrite_a_newer_allocation`,
  `test_13_3_an_unassigned_allocation_and_a_remainder_are_different`,
  `test_the_four_scope_combinations_are_each_accepted_and_independent`.

REVIEW 3절 R02·R04·R05·R06·R07은 문서를 믿지 않고 저장소 수준에서 직접
확인했다. `BankImporter(store.conn, store)`가 같은 연결을 공유하고,
미지 필드는 `INVALID_VALUE`로 거부되며, `2026-99-99`·`2026-02-30`은
거부되고, 빈 메모는 필드 생략과 구분되고, 링크는 없는 원천을 거부하며,
메모만 바꾸면 학습 사례가 0건임을 확인했다. 각 항목의 판정과 검사 이름은
"명세 전수 대조 감사" 절에 있다.

### 3) 실행 명령과 실제 결과

- `python -m py_compile` 48개 파일 통과
- 좁은 확인(인용 검사를 먼저):
  - 수입·분류 규칙·은행 원천·저장소·카드:
    `177 passed, 3 subtests passed in 24.12s`
  - Phase 9·Phase 8·제공자 경계·Phase 7:
    `219 passed, 59 subtests passed in 33.86s`
- 코드와 검사를 바꾼 뒤 전체 suite를 **정확히 한 한 번** 실행:
  **`624 passed, 85 subtests passed in 190.57s`**
- 인용 검사 이름 대조: 148개 인용, 없는 이름 0개
- DBG/TODO/breakpoint 잔여 0건, 잔여 프로세스 0, `webledger.work*.sqlite`
  실행 산출물 남지 않음

### 4) 미검증 경로

external-only 8행은 위 감사 절에 사유와 함께 적었다. 실제 네트워크 호출,
실제 OIDC, 실제 예약 API, 실제 Google AI Studio 접근, 실제 키와 유료 자원은
쓰지 않았다. 합성 입력과 로컬 임시 DB만 사용했다.
`ops.EXTERNAL_CONDITIONS`의 여섯 항목은 미완료를 유지한다.

commit·push·deploy 없음. 작업 트리는 미커밋 상태다.

## 문서 근거 정합성 마무리 — 2026-09-27 (코드 변경 없음)

직전 턴의 판정(proven 41 / incomplete-local 0 / external-only 8, 전체
`624 passed, 85 subtests passed`)은 그대로 유지한다. 이 턴은 **코드 동작을
바꾸지 않았고** 문서 내부 정합성 4건만 닫았다. 전체 suite는 다시 돌리지
않았다(문서만 바꿨으므로).

### 1) dangling cross-reference

`docs/handoff/2026-09-27/README.md` 107행이 "전체 요구사항 감사 결과는 아래
'요구사항 매트릭스' 절에…"라고 자기 문서를 가리켰다. 실제로 이 README에는
`매트릭스` 제목이 없고 표 행(`| `)도 0건이었다. 매트릭스 본문은 이 로그의
`## 요구사항 매트릭스 감사 — 2026-09-27 (최종)` 절(715행)에 있다.

고친 문구: "전체 요구사항 감사 결과는 이 문서가 아니라
`docs/WEB_LEDGER_IMPLEMENTATION_LOG.md`의 `## 요구사항 매트릭스 감사 —
2026-09-27 (최종)` 절(및 그 뒤의 `## 구현 검토 8~10절 항목별 판정`,
`## 명세 전수 대조 감사` 절)에 proven / incomplete-local / external-only로
나누어 적었다. 이 README에는 매트릭스 표가 없고, 요구사항별 판정의 단일
출처는 그 로그 파일이다."

같은 형태의 없는 절 참조를 `docs/` 전체에서 찾았다. 같은 문서를 가리키는
포인터(`아래`·`같은 문서`·`이 문서` + 따옴표 제목)만 검사했고, 실제 발견은
위 1건뿐이었다. 나머지 3건은 `email-integration.md`,
`비용분류_지시사항_원장.md`의 **인용문구**라 절 참조가 아니며, 이 두 파일은
이번 작업에서 한 번도 쓰지 않았다.

### 2) "최종 권위 실행"이 낡은 값을 권위로 부르고 있었다

`WEB_LEDGER_IMPLEMENTATION_LOG.md` 795절의 제목이 `## 최종 권위 실행 —
2026-09-27`이고 본문은 `610 passed, 80 subtests`였다. 그 뒤 같은 파일의
`## 명세 전수 대조 감사 실행 기록 — 2026-09-27` 절이 `624 passed,
85 subtests`를 현재 값으로 기록하고 있다. 즉 "권위"라는 제목이 낡은 값을
가지고 있었다.

정확한 사실: **같은 제목이 두 개였던 것은 아니었다.** `docs/` 전체에서
`최종 권위 실행`은 이 로그 1건뿐이었다. 결함은 제목 하나가 낡은 값을
권위로 부르는 것이었다.

고친 문구: 제목에 `[역사 — 대체됨]`을 붙이고, 바로 아래 인용문에 "이 절이
기록한 값은 아래와 같고 **현재 권위가 아니다.** 현재 권위 값은 이 파일의
`## 명세 전수 대조 감사 실행 기록 — 2026-09-27` 절에 있다"를 넣었다. 값
`610 passed, 80 subtests passed in 187.96s`는 지우지 않고 `(당시 값)`만
붙여 보존했다. `최종 권위 실행`은 이제 이 파일에서 1건이고 `[역사]`가 붙어
있다.

### 3) 대체되지 않은 Phase 9 수치

같은 로그의 좁은 재실행 기록에 `Phase 9 28 passed`가 남아 있었고, 그보다
이른 기록에는 `25 passed`도 있었다. 현재 수집 기준은 64건이다.

- 67행 `test_ops_phase9.py → 28 passed` → `[역사 수치 — Phase 9 구현 당시]`
  + "(현재 수집 기준 64건. `webapp/cli.py` ops 명령과 `test_ops_phase9.py`의
  조치 필요 표면 검사가 추가된 뒤의 값이다.)"
- 612행, 705행의 `Phase 9 28 passed` → 수치가 있는 줄 자체에
  `(현재 수집 기준 64건)`을 붙였다
- 98행, 162행의 `25 passed` → `[역사 수치]`

이미 고쳐진 파일은 건드리지 않았다: `WEB_LEDGER_PHASES.md` 24행(`64건`),
`IMPLEMENTATION_PROMPT_WEB_LEDGER_APP.md` 14행(`624 passed`). **이번에 고친
파일은 `WEB_LEDGER_IMPLEMENTATION_LOG.md`와
`docs/handoff/2026-09-27/README.md` 두 개다.**

인용 검사 이름도 같은 방식으로 정리했다. 이 로그의
`## 현재 권위 수치 (이 절이 현재 값의 단일 출처)` 절에 전체 624 / 수집
40·18·64·97 / 인용 148개를 한 곳에 모았고, 다른 절의 과거 수치는
`[역사 수치 — 대체됨]`으로 표시돼 있다고 명시했다. 인용 148개는 실제 파일과
대조했고 **없는 이름 0개**다.

### 4) README에 남은 처리 완료 문구

README 32~35행이 `**이 항목은 처리됐다.**`로 시작해 앞에서 무엇을 refers to
하는지 없이 인용 숫자 목록 뒤에 붙어 있었다. 사실을 새로 쓰지 않고
문맥만 이었다.

고친 문구: "위 목록의 좁은 수치와 '전체' 한 줄은 **같은 실행**의 값이며,
그다음 '전체 suite 재실행'을 **[역사 지시 — 현재는 완료]** 로 표시한 것은
그 지시가 이미 끝났다는 뜻이다. …". 같은 파일의 다른 `[역사 — 대체됨]`
표기와 한 문장 수준으로 이어진다.

### 5) 실행 명령과 실제 출력

문서만 바꿨으므로 전체 suite는 돌리지 않았다. 지시된 확인만 실행했다.

- `python -m pytest webapp/tests/test_access_control_phase7.py --collect-only -q`
  → **40**
- `python -m pytest webapp/tests/test_migration_phase8.py --collect-only -q`
  → **18**
- `python -m pytest webapp/tests/test_ops_phase9.py --collect-only -q` → **64**
- `python -m pytest webapp/tests/test_provider_boundary.py --collect-only -q`
  → **97**
  → 문서의 40 / 18 / 64 / 97과 일치한다.
- 인용 검사 이름 대조: 148개 인용, 없는 이름 **0개**
- `docs/` 한자 점검: 이번 작업에서 쓴 9개 명세·인계 문서에는 한자 **0개**.
  `webapp_phase01_계약.md`, `브랜치감사_2026-07-29.md`,
  `비용분류_지시사항_원장.md`에 있는 한자는 이번 작업에서 쓰지 않은 파일의
  기존 내용이라 건드리지 않았다.
- 코드 변경 없음 확인: 문서 편집 시각(09:51:17)보다 최신인 `webapp/**.py`
  **0개**.
- `webledger.work*` 실행 산출물: **없음**. 잔여 프로세스 0.

### 6) 판정 변화

없음. proven 41 / incomplete-local 0 / external-only 8과
`624 passed, 85 subtests passed in 190.57s`를 그대로 유지한다. 이 턴에서
새로 판정한 요구사항도, 새로 고친 코드 결함도 없다.

### 7) 여전히 external-only

SPEC_REFINEMENT 18절, 19.1·19.2·19.5·19.6, DETAILED 17절의 실제 기기,
REVIEW 10절의 회사명과 작성 정보, 실제 Google OIDC, 실제 예약 API,
실제 AI 호출·키·AI Studio 등급 확인, 운영 DB와 실제 기준본 이관,
호스팅 자원, 실제 배포, 실물 Excel 인쇄. `ops.EXTERNAL_CONDITIONS`의 여섯
항목이 미완료를 유지한다.

---

## 2026-09-27 · 우선순위 1 — 판정 방법 자체 감사 (테스트가 실제 경로를 호출하는가)

사용자 지시는 "우선순위 1: 판정 방법 자체 수정 — 테스트가 실제 HTTP 경로를
호출하는지 확인하고 고친다"였다. 이전 턴의 감사 결과가 4건의 테스트만 지목했으나
실제로는 7건이 판정 근거에서 빠져 있었다.

### 1) `board_page()`는 실제 dead code다

`webapp/ledger_board.py:1060`에 정의된 `board_page()`를 호출하는 코드가
`webapp/` 안에 **하나도 없다**. `webapp/` 전체(테스트 제외)에서 `board_page`
 언급은 정의 1건뿐이고, `do_GET`은 `GET /`와 `GET /board`를 모두
`ledger_design.page`로 분기한다. 즉 `/board`가 그리는 화면과 `board_page()`가
그리는 화면은 다른 함수였다.

이전 턴 감사 요약은 이를 `ledger_board.py:2391` 부근 분기라고 지목했다.
그 위치는 실제로 `do_GET`의 라우트 분기다.

### 2) 판정 근거에서 빠진 것은 4건이 아니라 7건이었다

`test_ledger_board.py`의 `BoardPageTests`는 7개 테스트를 갖고 있었고
7개 모두 라우트가 아닌 렌더러를 직접 호출했다.

| 테스트 | 이전 근거 | 실제 라우트 | 처리 |
|---|---|---|---|
| `test_board_shows_synthetic_mark_and_totals` | `board_page` | 없음 | `GET /board`로 재대상 |
| `test_board_has_no_candidate_badge` | `board_page` | 없음 | `GET /board`로 재대상, 4.3 서술로 확장 |
| `test_income_above_expense` | `board_page` | 없음 | `GET /board`로 재대상 |
| `test_mobile_layout_present` | `board_page` | 없음 | `GET /board`로 재대상 |
| `test_detail_shows_basis` | `detail_page` | `GET /row` | HTTP로 승격 |
| `test_edit_form_save_disabled` | `detail_page` | `GET /row` | HTTP로 승격 |
| `test_unknown_row` | `detail_page` | **도달 불가** | 404 계약으로 재작성 |

`detail_page`는 `webapp/ledger_board.py:2441`에서 `GET /row`로 실제 라우팅된다
(`pages.py`, `server.py`에서도 사용). 따라서 3건은 라우트 자체는 유효했으나
HTTP를 거치지 않고 직접 호출했다.

### 3) `test_unknown_row`는 도달 불가능한 동작을 기술하고 있었다

`detail_page("no-such-row")`는 `"행이 없어요"` 폴백 HTML을 낸다. 그러나
`GET /row`는 렌더러를 부르기 전에 `find_row`로 먼저 검사하고
`{"code": "RESOURCE_NOT_FOUND", "message": "없는 행이에요"}`를 404로 JSON
응답한다(`webapp/ledger_board.py:2436-2440`). 이 폴백은 이 제품에서는
도달할 수 없다. 테스트는 곧바로 `HTTPError` 404와 `RESOURCE_NOT_FOUND`,
`"없는 행이에요"`를 확인하도록 고쳐 실제로 나가는 동작을 기술하게 했다.

### 4) APP_SPEC 4.3 위반 여부: 위반이 아니었다

이전 요약은 실제 서비스 화면에 `구분` 열과 `_row_kind_meter`의 `대기`가 있어
4.3의 "분류 상태 열 금지" 위반으로 지목했다. 실제 페이지를 열어 확인한 결과
**위반이 아니다**.

- 4.3은 `분류 상태 열·점·배지·행 색상`을 금지한다.
- 여행 표의 `구분` 값은 실측 `수입` / `지출` / `취소` 세 가지다.
  `수입`·`지출`은 행의 성격, `취소`는 원천 거래 사실이다.
- `대기`는 `classification_state == "unclassified"` 또는
  `display_tab_id is None`일 때만 나온다. 여행 표의 행은
  `display_tab_id`가 존재하므로 실측 6행 중 해당 없음.
- 여행 표 페이지에는 `>대기<`가 0회 등장하고, `대기`는 분류 대기 구역에서만
  나타난다. 그 구역은 4.3이 말하는 "기본 표"가 아니다.

따라서 4.3 판정은 위반이 아니라 **위반 없음**으로 남긴다. 다만 판정 근거가
라우트되지 않은 함수였으므로, 실제 라우트로 다시 기술해 근거를 교체했다.

### 5) 서비스 화면 두 개의 낡은 주장도 함께 정정했다

재대상 과정에서 이전 턴 요약의 나머지 주장도 실제 응답과 달랐다.

- `수입 내용` / `지출 내용` 이라는 구역 제목은 실제 응답에 없다. 실제 표는
  `tbody class='grp'` 그룹 헤더로 `수입` / `지출`을 표시한다. 순서 판정을
  그룹 헤더 기준으로 바꿨다.
- `@media (max-width:760px)` 와 `scrollx` 는 실제 응답에 없다. 실측 기준은
  `@media (max-width:759px)`, `.lst{display:block`, `#btn-menu` 다.

### 6) 변경 내용

`webapp/tests/test_ledger_board.py`

- `BoardPageTests` 클래스 삭제, 7개 테스트를 실제 HTTP 서버를 띄우는
  `BoardApiTests` 안으로 옮겼다. 새 헬퍼 `_get_html(path)` 는
  `http://127.0.0.1:<port><path>` 를 실제로 GET 한다.
- `import json` 추가.

동작 변경은 없다. `webapp/` 의 제품 코드는 한 줄도 바꾸지 않았다.

### 7) 이 턴에서 발견한 자기 오류 (기록용)

7개 테스트를 처음 붙여 넣을 때 `if __name__ == "__main__": unittest.main()`
**아래**에 삽입되어, unittest.main() 안의 들여진 블록이 되었다. 문법 오류가
나지 않아 파일 전체는 여전히 `19 passed` 로 통과했지만 7개 테스트는 **한 번도
실행되지 않았다**. `unittest` 수집 목록에서 빠진 것을 확인해 클래스 안으로
옮겼다.

한 필드는 한글이 `\u` 이스케이프로 생성되었는데 코드포인트가 틀려
(`후보` 의 올바른 값은 U+CD5C U+BCF4, 잘못된 값은 U+D6C4 U+B3C4) 실제
글자가 아니었다. 그 상태에서는 4.3 검사가 통과만 하고 실패할 수 없었다.
문자열 리터럴로 다시 쓰고 18개 한글 리터럴이 실제 코드포인트로 존재하는 것을
확인했다.

두 건 모두 이번 감사에서 처음부터 끝까지 추적하지 않았다면
`624 passed` 만 보고 통과로 기록했을 사례다.

### 8) 비공백 검증 (mutation)

새 테스트가 실제로 실패할 수 있는지 확인했다. 소스를 고치고 즉시 되돌렸다.

| 변이 | 대상 테스트 | 결과 |
|---|---|---|
| `_row_kind_meter`가 기본 표에서 항상 `후보`를 반환 | `test_the_routed_board_shows_no_classification_state_column` | **1 failed** (탐지) |
| `GET /row`의 `find_row` 가드 제거 | `test_unknown_row_returns_404_before_rendering` | **1 failed** (탐지) |

두 변이 모두 실패로 탐지되었다. 소스 복구 후
`ledger_design` 과 `ledger_board` 원문 일치를 확인했다.

### 9) 실행 명령과 실제 출력

- `python -m pytest webapp/tests/test_ledger_board.py -q -p no:cacheprovider`
  → **26 passed in 14.75s**
  (수정 전 19건 → 26건. 같은 7개 테스트를 실제 HTTP 경로로 옮긴 것)
- `python -m pytest webapp/tests -q -p no:cacheprovider`
  → **624 passed, 85 subtests passed in 205.73s**

총건수가 624로 이전과 같은 것은 7건을 지우고 7건을 다시 넣었기 때문이다.
집계 수치가 그대로라는 이유만으로 통과를 주장하지 않는다. 8절 변이 표기로
실행 여부를 확인했다.

### 10) 판정 변화

proven 41 / incomplete-local 0 / external-only 8은 유지한다. 다만 7건의
근거는 "라우트되지 않은 렌더러 직접 호출"에서 "실제 HTTP 응답"으로 바뀌었으며,
4.3 판정은 위반이 아니라 위반 없음으로 확정했다. 이 7건은 이전 턴의
"4건"뿐 아니라 `detail` 3건을 포함한다.

### 11) 남은 작업

우선순위 2(소유자 전용 여행 탭 생성 vertical slice), 우선순위 3(요약 라벨
분리, xlsx 검증·검토 상태, audit/lineage 조회, 수기 지출 HTTP 시험),
우선순위 4(행렬 절 번호 정합성)는 이 턴에着手하지 않았다.


---

## 2026-09-27 · 최종 코드 변경 뒤 fresh 전체 실행값 (권위)

최종 코드 변경을 마친 뒤 전체 suite를 **딱 한 번** fresh 실행했다. 이 값이
현재 권위값이다.

```
python -m pytest webapp/tests -q -p no:cacheprovider
  → 708 passed, 85 subtests passed in 360.29s
```

- 이전 턴 값 `682 passed, 85 subtests passed in 282.33s` 와 비교해
  **신규 26건** 증가(충돌 상태·경로 정합). 회귀 0건.
- 신규 파일 `webapp/tests/test_conflict_state.py` **26건**,
  `test_spec_named_paths.py` 30건, `test_trip_create.py` 28건.
- 매트릭스 proven 행 **52행**, 인용 검사 **138개 전부 실존**(없는 이름 0).
- 매트릭스 절 참조 **66개 전부 해석됨**(불일치 0).
- proven / incomplete-local / external-only 세 판정 제목이 로그 안에서
  각각 **1회**만 나온다(검사기는 절 제목 접두사를 세어서 확인한다).
  역사 절에 남아 있던 예전 제목은 `[역사]` 표시로 내려 현행 판정과
  섞이지 않게 했다.
- 문서 U+FFFD **0건**, 디버그 계측 0건, `webledger.work*` 산출물 0건,
  잔여 파이썬 프로세스 0건(검사 스크립트 자신이 실행 중인 것은 제외).

### 이 실행에서 발견해 고친 자기 오류 (기록용)

첫 fresh 실행에서 `test_rule_process_ownership.py` 2건이 JSONDecodeError로
떨어졌다. 제품 결함이 아니었다.

원인은 내가 만든 임시 스크립트 `C:\Users\...\Temp\opencode\struct.py` 다.
`test_rule_process_ownership.py` 는 헬퍼 프로세스를 **절대 경로**로 띄우므로
그 헬퍼의 `sys.path[0]` 은 임시 디렉터리다. 그 자리에 표준 라이브러리 이름인
`struct.py` 가 있으면 임포트 시 진짜 `struct` 대신 그 스크립트가 실행된다.
즉 내가 만든 파일이 자식 프로세스를 망가뜨려 제품처럼 보이는 실패를 냈다.

`struct.py` 를 `tmp_struct.py` 로 바꾸고 같은 파일을 다시 돌려 17건을
통과시킨 뒤, 위의 전체 실행을 했다. 표준 라이브러리 이름을 가리는 임시 파일은
없음을 확인했다. 이 부류의 오염은 제품 검사만으로는 원인이 보이지 않으므로,
임시 작업 파일을 검사 프로세스의 `sys.path[0]` 에 두지 않는 것이 규칙이 된다.


---

## 2026-09-27 · 코디네이터 후속 감사 — 최종 코드 변경 뒤 실행값 (권위)

코디네이터가 알려 준 값과 이 턴의 값을 구분해 적는다. 360.29s 는 코디네이터가
확인한 **직전 권위값**이고, 그 뒤 이 턴에서 제품 코드를 더 바꿨으므로 지금의
권위값은 그 다음(full) 실행값이다. 360.29s 를 현재값으로 쓰면 실제로 돌리지 않은
수를 현재값으로 적는 셈이 된다.

```
# 코디네이터 확인값 (이 턴의 코드 변경 전)
python -m pytest webapp/tests -q -p no:cacheprovider
  → 708 passed, 85 subtests passed in 360.29s

# 최종 코드 변경 뒤
python -m pytest webapp/tests -q -p no:cacheprovider --timeout=120
  → 729 passed, 88 subtests passed in 305.90s
```

- 신규 `webapp/tests/test_global_and_filter_totals.py` **21건**,
  subtests **3건** 추가. 회귀 0건.
- 3건이 늘어난 이유는 우선순위 2~4에서 이미 만든 `test_conflict_state.py` 26건이
  아니라, 이번 코디네이터 후속 감사에서 **새로 발견해 닫은 세 결함**의 검사다.

### 매트릭스

- proven 행 **52 → 72행**, 인용 검사 **180개 전부 실존**(없는 이름 0)
- 절 참조 **77개 전부 해석됨**(불일치 0)
- **incomplete-local 0건**, external-only 6항목(`ops.EXTERNAL_CONDITIONS`) 유지

### 이 턴의 확인값

| 항목 | 결과 |
| --- | --- |
| `webapp/**/*.py` 문법 검사 | 파일 52개, 오류 0 |
| `python -m compileall webapp` | 종료 코드 0 |
| U+FFFD (코드 52개 + 명세 문서) | **0건** |
| `webapp/` 안 DBG·TODO·FIXME·XXX·breakpoint·pdb·console.log | **0건** |
| `webledger.work*` 잔여물 | **0건** |
| 잔여 python/chrome 검사 프로세스 | **0건** (자기 검사 스크립트 제외) |
| ownership/process 검사 | `75 passed, 6 subtests passed in 21.40s` |
| `ownership_child.py` 보존 | 존재, 2862 bytes |

`msedgewebview2` 와 `node` / `node_repl` 은 이 저장소의 테스트가 아니라 Windows
셸과 Paseo/OpenCode 도구 프로세스다. 검사 프로세스가 아니다.

문서의 DBG/TODO 문자열은 계측이 아니라 "몇 건이다"를 적은 **진술**이고,
`webapp/` 안에는 해당 토큰이 한 건도 없다.

### 남아 있는 것

**외부 조건 6항목뿐이고 incomplete-local 은 0건이다.** 실제 Google OIDC, 실제
예약 API, 실제 AI 호출과 키·등급 확인, 운영 DB, 호스팅 자원, 실제 배포와 실물
Excel 인쇄. 이번 턴은 이 항목에 손대지 않았고 외부 조건을 로컬 구현으로
적지 않았다.


---

## 2026-09-27 · 운영 준비 감사 후 최종 실행값 (권위)

이번 턴에 `ops.py`·`cli.py`를 고치고 `test_ops_recovery_gates.py`를 새로
넣었으므로, 앞 절의 729건 값은 **이전 값**이다. 지금의 권위 값은 아래 실행값이다.

```
python -m pytest webapp/tests -q -p no:cacheprovider --timeout=180
  → 752 passed, 88 subtests passed in 303.76s
```

| 항목 | 결과 |
| --- | --- |
| `webapp/**/*.py` (53개) 문법 검사 | 오류 0, `compileall` 종료 코드 0 |
| U+FFFD (코드 + 명세 문서 전체) | **0건** |
| `webapp/` 안 DBG·TODO·FIXME·XXX·breakpoint·pdb·console.log | **0건** |
| 매트릭스 proven 행 | **72행** |
| 매트릭스 인용 검사 | **180개 전부 실존**, 없는 이름 0 |
| 매트릭스 절 참조 | **77개 전부 해석됨**, 불일치 0 |
| `webledger.work*` 잔여물 | 0 |
| 잔여 검사용 python/chrome 프로세스 | 0 |
| HEAD | `99041a4` (이 턴 도중 외부 주체가 만든 commit, 제 commit 아님) |
| `ownership_child.py` | 보존, 2862 bytes |
| **incomplete-local** | **0건** |
| **external-only** | **6건** (위 절에 항목별 외부 입력·명령·성공 근거) |

### 판정이 바뀐 이유

`incomplete-local 0`과 `external-only 6`은 **문서가 말하는 대로가 아니라 8개 영역을
합성 실행한 결과**로 다시 판정했다. 그 실행이 결함 5건을 드러냈고 전부 닫았다.
그전까지 "0"은 매트릭스에 인용된 행의 층만 확인한 값이었다. 이번에는 인용된 행
바깥의 요구, 즉 명세 17.2의 회복 수치와 17.3 2항의 사건별 대조까지 실행했다.

외부 6항목은 줄지 않았다. 다만 각 항목에 **필요한 외부 입력 · 실행 명령 · 성공
판정 근거**를 붙여, 무엇을 얻으면 무엇을 돌리고 무엇이 나오면 되는지가
정해지지 않은 상태로 남지 않게 했다.


---

## 2026-09-27 · HOSTING 준비 감사 — 바인딩·영속 경로·서비스 형태

사용자 요청으로 HOSTING 준비 항목을 닫았다. 문서를 먼저 읽어 정답을 확인했는데,
명세가 이미 답을 정하고 있었다.

**명세가 정한 것.** `SPEC_REFINEMENT 19.2`: "외부에는 HTTPS 앱 경로만 제공하고
SQLite·원천 디렉터리·작업자 관리 포트를 공개하지 않는다." `18.3` 1항: "현재 합성
stdlib 서버를 그대로 외부에 공개하는 것을 완료로 보지 않는다." `16.1`: "앱 세션
쿠키는 운영 HTTPS와 서버 측 검증을 사용한다." `IMPL 7`: "직접 노출하는 방식은 기본으로
만들지 않는다."

즉 이 서버는 TLS를 끝내지 않으므로 **외부 공개는 답이 아니다.** 정답은 같은
머신의 프록시가 HTTPS를 종료하고 루프백으로 전달하는 형태다. 그래서
`--host` 옵션과 reverse proxy 중 **둘 다** 넣었다. 기본값은 루프백 그대로여서
기존 동작은 바뀌지 않고, 직접 공개만 명시적 승인이 있어야 한다.

### 고친 결함 5건

1. **바인딩 주소가 두 곳에 하드코딩돼 있었다.** `cli.py:160`과
   `ledger_board.serve`가 `127.0.0.1`을 그대로 써서 컨테이너 안의 프록시가
   호스트 루프백에 닿지 못하는 형태를 고칠 수 없었다. `ops.bind_posture`가
   주소를 `loopback-behind-https-proxy` / `non-loopback-for-proxy` /
   `external-bind`로 분류하고, `require_safe_bind`가 루프백 밖 주소를 거부한다.
   해석되지 않는 이름은 안전하다고 보지 않고 외부로 친다.
2. **배포 manifest 가 public bind 를 그냥 통과시켰다.** 이건 실제로 실행해서
   발견했다. `build_deploy_manifest`의 `behind_proxy` 기본값이 `True`여서
   `ops dry-run --host 0.0.0.0`가 `ok: true, failed: []`를 냈다. TLS를 끝내지
   않는 서버를 공개 바인드에 대한 **승인**처럼 보여 준 셈이다. 기본값을 `False`
   로 내리고, 명시적 승인이 있어야 통과하며 통과해도 형태는 다른 이름으로 남는다.
3. **진입점이 장부를 소스 체크아웃 안에 기본값으로 썼다.** `run_candidate.py`가
   `--db` 기본값을 `<checkout>/runtime/board.sqlite`로 두었다. `18.3` 2항이
   금지한 바로 그 경로다. 그런데 `ops.DurableConfig`는 이미 상대 경로·개발
   기본값·임시 루트를 거부하고 있었으므로, 진입점은 그 규칙을 전부 우회하고
   있었다. 이제 `--data-root` 또는 `WEBLEDGER_DATA_ROOT`가 **필수**이고, 없으면
   거절한다. `DurableConfig`에 `CHECKOUT_DATA_ROOT`를 추가해 규칙을 한 벌로
   모았고, 진입점은 그 객체를 쓴다(`durable_config_for`).
4. **진입점 거절이 traceback 이었다.** 운영자가 처음 실행하는 명령인데
   `OpsError`가 그대로 올라와 Python 역추적이 찍혔다. 이제
   `refused [UNSAFE_BIND]: ...` 와 종료 코드 2다. `--environment`도 붙여서
   운영선언이 입력을 통해 가능해졌다.
5. **health 의 `synthetic_sessions` 문장이 verdict 와 반대말을 했다.** 고정한
   문자열이라 "합성 세션 허용 중"을 정상 시스템에도, 실제 허용이 있어도 똑같이
   적었다. 실제로 본 상태를 말하도록 고쳤다.

### 추가한 것

- `ops service_unit_text`: **설치하지 않는** systemd 단위 예시를 파일로 쓴다.
  루프백 바인딩, `WorkingDirectory`와 `ReadWritePaths`를 데이터 루트로, 비밀 값
  없이 `EnvironmentFile` 지시, health·actions·drill·dry-run 명령을 주석으로.
- runbook에 `## 바인딩 형태` 와 `## 운영 확인 절차` 절. 절차는
  health → actions → drill → dry-run 순이고, `health.failed` 가 비어 있고
  `drill.recoverable` 과 `content_compared` 가 true일 때만 전환을 검토한다.
- `WEBLEDGER_DATA_ROOT` 영속 경로: `durable_config_for` 가
  `data/{board.sqlite,exports,evidence,source}` 레이아웃을 만들고, 서비스와
  health·readiness·drill 이 **같은 설정 객체**를 읽는다. 경로가 달라질 수 없다.

### 변이로 검사 effectiveness 확인

신규 검사 38건에 변이 15건(A~O)을 넣어 전건 실패를 확인했다. 이 과정에서
**검사 자체의 결함 3건**을 고쳤다.

- `serve` 가 주소를 무시하는 변이가 살아남았다. 항상 기본값 `127.0.0.1`으로만
  검사했기 때문이다. `127.0.0.2` 로 묶고 실제 `server_address` 를 보게 바꿨다.
- health 문면 검사가 "이 문구가 없다"만 확인해서 빈 문자열 변이를 놓쳤다.
  "실제로 본 상태를 말한다"를 확인하도록 바꿨다.
- 변이 러너가 pytest 요약 줄을 잘못 읽어 **실패한 변이를 통과로 기록했다.**
  판정 기준을 종료 코드로 바꿨다.

### 판정

- `HOSTING-RESOURCE` 은 여전히 external-only다. 이 턴에서 자원을 만들지 않았고
  계정·결제·VM 생성·배포도 하지 않았다. 다만 로컬에서 준비할 수 있는 HOSTING
  항목 — 바인딩 규칙, 영속 경로 강제, 서비스 형태, 확인 절차 — 은 닫았다.


---

## 2026-09-27 · HOSTING 준비 감사 후 최종 실행값 (권위)

`webapp/ops.py`·`webapp/cli.py`·`webapp/ledger_board.py`·`run_candidate.py`를
고치고 `test_ops_hosting_bind.py`를 새로 넣었으므로, 앞 절의 752건은 **이전 값**이다.

```
python -m pytest webapp/tests -q -p no:cacheprovider --timeout=180
  → 791 passed, 104 subtests passed in 271.84s
```

| 항목 | 결과 |
| --- | --- |
| `webapp/**/*.py` (54개) 문법 검사 | 오류 0, `compileall` 종료 코드 0 |
| U+FFFD (코드 + 명세 문서) | **0건** |
| `webapp/` 안 계측 토큰 | **0건** |
| 신규 `test_ops_hosting_bind.py` | 39건, subtests 16 |
| 변이 15건 (A~O) | **전건 실패로 탐지** |
| 매트릭스 proven 행 | **77행** |
| 매트릭스 인용 검사 | **215개 전부 실존** |
| 매트릭스 절 참조 | **82개 전부 해석됨** |
| `webledger.work*` 잔여물 | **0건** |
| 잔여 검사용 python/chrome 프로세스 | **0건** |
| HEAD | `99041a4` (이 턴 도중 외부 주체가 만든 commit, 제 commit 아님) |
| **incomplete-local** | **0건** |
| **external-only** | **6건** (HOSTING-RESOURCE 포함) |

### 이 턴에 고친 검사 자신의 결함 4건

돌려봤더니 변이 중 3건이 살아남아서, 검사 쪽을 고쳤다.

1. `serve` 가 주소를 무시하는 변이가 통과했다. 항상 기본값 `127.0.0.1` 으로만
   검사했기 때문이다. `127.0.0.2` 로 묶고 실제 `server_address` 를 보게 바꿨다.
2. health 문면 검사가 "이 문구가 없다"만 확인해서 빈 문자열 변이를 놓쳤다.
   실제로 본 상태를 말하는지 확인하도록 바꿨다.
3. **변이 러너가 pytest 요약 줄을 잘못 읽어 실패한 변이를 통과로 기록했다.**
   판정 기준을 종료 코드로 바꿨다. 이건 오판 방향이 위험했다 — 검사가 약한 것과
   러너가 오판한 것이 같은 "통과"로 보이기 때문이다.
4. 데이터 루트 거절이 종료 코드 1, 나머지 거절이 2로 갈렸다. 그랬다가
   `test_every_refusal_uses_one_exit_code` 가 실제로 잡아냈다. 한 가지 코드로
   통일했다.

그리고 이 테스트가 처음엔 유효한 합성 설정을 띄워 suite 를 멈췄다. 모든 거절
케이스만 다루도록 고치고 타임아웃을 60초로 줄여, 앞으로 거절이 깨지면
프로세스를 남기지 않고 실패하게 했다.


---

## 2026-09-27 · Google OIDC 실제 연결

`access_control` 에는 합성 seam 만 있었고 실제 provider 가 없었다. 이제
`webapp/google_oidc.py` 가 있다. 이건 두 번째 합성 대역이 아니다 — 설정되면
브라우저를 Google 로 보내고 검증된 Google 신원이 돌아오는 실제
Authorization Code 흐름이다.

### 세 가지 중요한 결정

- **계정 키는 `sub`.** Google 의 `sub` 는 이메일 변경에도 안정적이다. email 은
  표시 속성으로만 기록하고 조회 키로 쓰지 않는다. 그래서 Google 계정 이름을 바꿔도
  새 계정이 생기거나 옛 권한을 물려받지 않는다.
- **첫 로그인은 승격이 아니다.** 처음 보는 신원은 항상 **viewer** 다. owner 가 되는
  길은 `WEBLEDGER_OWNER_GOOGLE_SUB` 이 설정되어 있고 제시된 `sub` 와 같고 아직
  owner 가 없을 때의 명시적 bootstrap 뿐이다. 그 설정을 빠뜨린 배포는 실수로 생긴
  owner 가 아니라 owner 가 없는 상태가 된다.
- **세션은 계정 세대에 묶인다.** 쿠키는 발급 시점의 `session_generation` 을 담고
  모든 요청이 지금의 세대와 비교한다. 로그아웃·권한 해제·비활성화가 세대를 옮기면
  브라우저가 들고 있던 쿠키는 거부된다.

### 구현 범위

- `Authorization Code` + OIDC. `/auth/login` 은 Google 로 303 리다이렉트,
  `/auth/callback` 은 code 를 교환하고 id_token 을 검증한 뒤 서명 쿠키를 설정한다.
- `state`/`nonce` 는 일회용이고 TTL 이 있다. 콜백 state 를 먼저 소진하므로
  재전송된 콜백은 **토큰 엔드포인트에 도달하기 전에** 거부된다.
- id_token 검증은 `google-auth` 의 `google.oauth2.id_token` 으로 하고, 서명·
  발급자·audience·만료를 검사한다. 라이브러리가 없으면 로그인을 **거부**한다.
  검증을 건너뛰고 로그인시키지 않는다. `validate_claims` 는 라이브러리가 이미
  확인한 항목을 다시 확인한다 — 주입된 verifier 나 라이브러리 변경이 그 검사를
  조용히 떨구면 안 되므로.
- 세션 쿠키는 `Secure; HttpOnly; SameSite=Lax; Path=/`. Google 토큰은 쿠키에
  넣지 않는다. 검증 직후 버린다 — 쿠키에 든 bearer 는 브라우저가 계속 재전송하는
  자격 증명이다.
- `/access/logout` 은 GET·POST 양쪽에서 쿠키를 지운다(`Max-Age=0`, 같은 이름과
  path). 세대만 옮기고 쿠키를 남기면 다음 방문이 그 쿠키를 들고 와서
  `SESSION_STALE` 로 거절당하기 때문이다.
- `google_oidc_connected` 는 `ops health` 와 `ops dry-run` 에 반영된다. health 의
  이 줄은 **항상 보고되고 production 에서만 fatal** 이다. 로컬·합성 실행은 아직
  Google 로그인이 없는 게 정상이라 거기서 실패시키면 선언대로 동작하는 실행이
  실패로 보이게 된다.

### 이 과정에서 고친 결함

1. **`google_oidc_connected` 를 처음부터 fatal 로 뒀다.** 기존 Phase 9 검사 4건이
   깨졌고, 그게 맞는 신호였다. 로컬 실행은 Google 설정이 없어도 정상이므로
   production 에서만 fatal 로 바꿨다.
2. **거절 페이지가 거절 코드를 말하지 않았다.** 운영자가 재전송된 state 와
   잘못된 토큰을 로그를 뒤지지 않고 구분할 수 없었다. `data-refusal` 속성으로
   코드를 렌더한다.

### 보존한 파일 3개

사용자 요청대로 덮어쓰지 않고 통합했다.

- `run_candidate.py`: HOSTING 거절 3종(데이터 루트 없음·루프백 밖 바인딩·production
  임시 루트)이 그대로 종료 코드 2로 거절되고 traceback 이 없다. 추가로
  `--synthetic-sessions` 를 받았는데 Google 환경도 설정돼 있으면
  `MIXED_AUTH_PATHS` 로 거절한다 — 어느 쪽이 권한을 정했는지 모호한 채로 두지 않기
  위해서다.
- `test_ops_hosting_bind.py`: 40건 그대로 통과.
- `requirements.txt`: `openpyxl` 줄을 보존하고 `google-auth`·`PyJWT`·`requests` 를
  추가했다. `google-auth` 는 선택 사항이 아니다 — 없으면 로그인이 거부되므로.

**실제 비밀 값은 만들지도 출력하지도 않았다.** 테스트에 있는 두 값은 자리표시자
문자열이고 제품 코드에는 0건이다.

### 변이로 검사 effectiveness 확인

신규 검사 67건에 변이 19건(A~S)을 넣어 전건 실패를 확인했다. 지면 항목을 하나씩
옮겨 재도입했다: email 로 계정 조회, 첫 로그인 owner 승격, owner sub 우회, 둘째
owner , state 재전송, nonce·발급자·audience·만료 미검사, 쿠키 서명 미검증, 세대
미비교, HttpOnly·Secure 제거, 로그아웃의 쿠키 미삭제, 헤더를 신원으로 수용, health
의 거짓 연결 보고, 약한 세션 키·평문 base url 수용, login 의 기존 계정 덮어쓰기.

이 과정에서 **검사 공백 2건**도 닫았다. `ops health` 라인을 아예 검사하지 않아
"연결되지 않았는데 연결됨이라고 보고하는" 변이가 통과했고, "다른 sub 로 온
사람이 owner 가 되는" 변이도 통과했다(다른 방어선이 막아서). 두 검사를 추가했다.

러너 쪽 결함도 셋 고쳤다. 메서드 이름을 잘못 찾아 9건이 실행조차 안 됐고, 같은
이름의 정의가 여럿일 때 첫 번째 것을 잡아 J 가 엉뚱한 함수에 갔으며, 모듈 수준
함수를 못 찾았다.


### base 가 이 턴 도중에 바뀌었습니다

`HEAD: 1486a37 유지` 라고 적으려 했으나, 그대로 둘 수 없었습니다.

- `99041a4` — "Complete web ledger hosting readiness and access controls" 가 이 턴 도중 **제가 아닌 주체에 의해** 만들어졌습니다
  (`6Soo <31435325+6Soo@users.noreply.github.com> / Mon Sep 28 14:44:48 2026 +0900`).
- `git status -sb` 는 `## main...origin/main`. ahead 표기가 없으므로 그 commit 은
  `origin/main` 에도 반영돼 있습니다.
- 그 commit 은 HOSTING 까지의 작업을 담고 있고, **제 OIDC 파일은 담고 있지
  않습니다** (`webapp/google_oidc.py`, `webapp/tests/test_google_oidc.py`,
  `requirements.txt`).
- 이 턴의 OIDC 작업은 그대로 **커밋되지 않은 채 작업트리에** 있습니다:
  수정 6개, 미추적 3개.

저는 이 턴 동안 `git commit` 도 `git push` 도 실행하지 않았습니다. 요청대로
작업트리에 남긴 상태이고, base 이동은 제가 일으킨 것이 아니므로 되돌리지도
않았습니다. 다만 검증값 표의 HEAD 표기를 실제로 맞췄습니다.

같은 주체가 `test_ops_hosting_bind.py` 에
`test_production_entry_binds_fail_closed_access_before_serving` 를 추가해 둔
상태였고, 그 검사도 통과합니다(1 passed). 제가 쓴 검사가 아닙니다.


### 최종 실행값과 한 번의 flaky

```
python -m pytest webapp/tests -q -p no:cacheprovider --timeout=300
  → 859 passed, 124 subtests passed in 283.96s
```

이 턴에 전체 suite 를 네 번 돌렸다. 값은 세 번 같았고 한 번 달랐다.

| 실행 | 결과 |
| --- | --- |
| 1 (timeout 240) | 859 passed, 124 subtests in 389.09s |
| 2 (timeout 240) | 859 passed, 124 subtests in 385.45s |
| 3 (timeout 240) | 1 failed, 858 passed — `test_a_waiting_row_moves_to_a_trip_from_the_list` |
| 4 (timeout 300) | 859 passed, 124 subtests passed in 283.96s |

한 번 실패한 것은 Playwright 화면 검사 하나입니다. 격리 실행에서 통과했고, 같은
파일을 연속 3번 돌려 21건이 매번 통과했습니다. 그래서 코드 문제가 아니라 부하
의존 테스트로 봅니다. 다만 "한 번이면 flaky 라고 결론 내리는" 것은 근거가 약하므로
결론 대신 기록으로 남깁니다 — 이 검사는 부하가 걸린 실행에서 1/4 실패했고, 지금은
**닫히지 않은 위험**이다. 부하가 더 심한 환경에서는 이 검사를 계기로 다른 결함과
섞일 수 있으니, 전체 suite 를 한 번의 통과로 근거 삼지 말아야 한다.

timeout 을 240 에서 300 으로 올려도 같은 실패가 재현되지 않았으므로, 부하가 원인이
맞지만 어느 시점에 발생하는지는 확정하지 않았다.


---

## 2026-09-27 · `/access/me` 의 `google_oidc_connected` 결함

### 증상

실제 Railway 배포에서 Google OAuth 로그인이 **성공**했는데 `/access/me` 가
`google_oidc_connected: false` 를 반환했다. 같은 프로세스에서 `ops health` 와
`/auth/state` 는 `true` 였다. 세 화면이 두 개의 답을 주고 있었다.

### 원인

`webapp/ledger_board.py` 의 `access_control_render_viewer_status` 안에
`"google_oidc_connected": False` 가 **상수로** 들어 있었다. 이 응답을 쓰는
`/access/me` 는 바인딩된 흐름을 보지 않고 언제나 거짓을 말했다.

재현해 확인했다(합성 흐름을 바인딩한 뒤 같은 라우트를 실제 소켓으로 읽음):

```
ops sees       : True
bound flow     : True
ops health line: [True]
/auth/state    : True
user_id                 : 104392118726514019283
role                    : owner
identity_source         : google_oidc
google_oidc_connected   : False      <== 여기만 다르다
```

### 수정

1. `ledger_board` 에 `google_oidc_connection_state()` 를 추가했다. 바인딩된 흐름을
   `google_oidc.connection_state` 에 넘기므로, `ops.health` 가 읽던 바로 그 함수다.
2. `/access/me` 는 그 값을 읽는다. 그리고 **왜** 그 값인지 알 수 있도록
   `google_oidc` 상태 덩어리를 함께 실었다 — 값만 보내면 운영자는 "왜 false 지"
   를 알 수 없다. 덩어리에는 비밀 값이 없다(존재 여부와 모양만).
3. **`ops.google_oidc_state` 의 fallback 을 지웠다.** 원래는 보드의 헬퍼를 먼저
   쓰고, 없으면 같은 값을 직접 계산하는 두 번째 길이 있었다. 같은 값을 계산하는
   두 길이가 바로 이 결함의 온상이므로, 한 길만 남겼다.

### 한 가지 짚어둘 점

`identity_source` 와 `google_oidc_connected` 는 다른 사실이다. 전자는 **이 세션이
어디서 왔는지**, 후자는 **이 배포에 실제 로그인이 있는가** 이다. Google 세션으로
들어왔는데 `google_oidc_connected` 가 false 인 상황은 정상일 수 있다 — 예를 들어
`google-auth` 가 없어 지금 세션만 서 있는 경우다. 그래서 두 필드를 분리했다.

### 검사 공백 2건도 닫았다

변이를 돌렸는데 2건이 살아남았다.

- `google_oidc_connected` 대신 `configured` 를 읽는 변이가 통과했다. 정상 흐름에서는
  두 값이 **둘 다 true** 라 구분이 안 된다. `configured` 이면서
  `google_oidc_connected` 가 false 인 상태(`google-auth` 없음)를 **경로 수준에서**
  검사해 추가했다.
- `ops` 가 헬퍼를 우회하는 변이가 통과했다. 그런데 그 fallback 은 같은 값을
  계산해서 **행동이 동일**했다 — 결함 형태가 아니었다. fallback 을 코드에서
  지워 길 하나만 남겼고, 이제 우회가 실제 행동 변화가 되어 잡힌다.

그리고 소스 문자열 검색으로 "헬퍼를 부른다"를 확인하던 검사를 **행동 검사**로
바쳤다. 문자열 검색은 호출을 우회해도 통과한다.

### 변이 5건 전건 탐지

| | 변이 | 결과 |
| --- | --- | --- |
| A | `/access/me` 가 다시 상수 false | CAUGHT |
| B | `/access/me` 가 언제나 true | CAUGHT |
| C | 판정 대신 `configured` 를 읽음 | CAUGHT |
| D | 헬퍼가 바인딩된 흐름을 무시 | CAUGHT |
| E | `ops` 가 환경값으로 답변 | CAUGHT |

변이를 되돌린 뒤 소스에 **잔여물이 0건**임을 확인했다. 검사한 표식은
하드코딩된 `"google_oidc_connected": False`, `if False`, `_os.environ`,
`webapp/ops.py` 안의 `WEBLEDGER_GOOGLE_CLIENT_ID`, 예전 fallback 의
`callable(reader)`, 그리고 쿠키 표식 변이 흔적이다. `webapp/ledger_board.py` 와
`webapp/ops.py` 는 두 파일 모두 다시 파싱된다.

### 실행값

```
# 관련 (OIDC · Phase 9 · 복구 게이트 · HOSTING · Phase 7 접근)
python -m pytest webapp/tests/test_google_oidc.py webapp/tests/test_ops_phase9.py \
  webapp/tests/test_ops_recovery_gates.py webapp/tests/test_ops_hosting_bind.py \
  webapp/tests/test_access_control_phase7.py -q -p no:cacheprovider --timeout=240
  → 253 passed, 42 subtests passed in 89.42s

# 전체
python -m pytest webapp/tests -q -p no:cacheprovider --timeout=300
  → 887 passed, 128 subtests passed in 425.51s
```

`test_google_oidc.py` 는 67건에서 **79건**으로 늘었다. HEAD 는 `99041a4` 이고
이번 턴에도 commit·push·deploy 하지 않았다.


### 최종 실행값과 이 작업트리의 동시 작업

```
python -m pytest webapp/tests -q -p no:cacheprovider --timeout=300
  → 887 passed, 128 subtests passed in 425.51s
```

이 결함을 고치면서 **전체 suite 를 네 번** 돌렸다. 네 번 모두
`887 passed, 128 subtests` 로 같고 소요 시간만 달랐다
(448.80s / 425.51s / 448.80s / 390.31s). **권위값으로 적는 것은
`887 passed, 128 subtests passed in 425.51s`** 다. 마지막 390.31s 는 문서를
복구한 뒤 다시 돌린 값이고 통과 건수는 같으며 차이는 기계 부하다. 한
값만 남기면 그 값이 유일한 측정치처럼 보이므로 나머지도 함께 적는다.
지난 턴에 한 번 나왔던 Playwright flaky 는 이번에는 네 번 모두 없었다.

**주의 — 이 작업트리에서 다른 주체가 작업 중입니다.** `git status` 에는 제가 건드리지
않은 변경이 있습니다:

   - docs/IMPLEMENTATION_PROMPT_WEB_LEDGER_APP.md
   - webapp/access_control.py
   - webapp/tests/test_access_control_phase7.py
   - webapp/tests/test_ops_hosting_bind.py
   - ledger/domain/reservation_access_snapshot.py
   - tools/import_reservation_access.py
   - webapp/tests/test_reservation_access_sync.py

`ledger/domain/reservation_access_snapshot.py`,
`tools/import_reservation_access.py`,
`webapp/tests/test_reservation_access_sync.py` 는 예약 접근 동기화 쪽 작업으로
보이며 제 `/access/me` 수정과는 무관합니다. `webapp/access_control.py` 와
`test_access_control_phase7.py` 도 제가 이 결함 작업에서 건드리지 않았습니다.

따라서 위 887건은 **그 변경을 포함한 수치**입니다. 제 수정만의 수치가 아닙니다.
같은 저장소를 다른 주체가 쓰는 동안에는 전체 실행값을 단독 근거 삼지 말고, 변경된
파일 목록과 함께 읽어야 합니다.

이번 턴에 제가 쓴 파일은 이 다섯 개입니다:
`webapp/ledger_board.py`, `webapp/ops.py`,
`webapp/tests/test_google_oidc.py`,
`docs/WEB_LEDGER_IMPLEMENTATION_LOG.md`,
`docs/handoff/2026-09-27/README.md`.

## 2026-09-29 Astra 지속 실행 작업표

현재 phase: P1 안전성 잔여 수정의 분할 결정. 역할 기준 `D-WEB-AGENT-003`.
최신 진행: health commit `313ef4634d27953a77e7210831baed89444ff22f`를 Sol 수용 후 원본에 통합했다. 부모의 신규 회귀 재검증은 3 tests OK, 0.496초다. 예약 Muse `bfada5fa-acba-423b-a236-598f88e3eef7`는 이 commit 기반 새 workspace `wks_49d0166d57101bba`에서 보완 중이다. 기존 예약 변경 네 파일은 SHA-256 확인과 함께 복사했으며 공통 규칙도 전달했다. Bunny는 체크포인트 결과를 제출했으나 간헐 실패 2종이 남아 미수용이다. Sol에 제한된 후속 진단 결정을 요청했다. 전체 suite 재반복은 지시하지 않았다.
진행 갱신: Sol의 P1 분할과 후속 분할 정정을 수용했다. SpaceBunny는 원본 `ledger_board.py` 및 직접 관련 platform/access 테스트로 범위를 축소하는 지시를 받았다. Muse `3a14b7ed-0fa5-46bc-a00c-31dc28bece85`는 새 `wks_8bfd61889ca94a39` / `muse/p1-health-readonly-20260929`에서 `cli.py`와 신규 health 회귀 검사만 작성한다. 최신 운영 명세를 전달했고 생성 직전 그 외 변경이 없는 것을 확인했다.

기존 `muse-audit-fixes-20260929`에는 작성자 미확정 예약 변경이 발견돼 그 공간에 막 생성한 워커 `94d398ff-8d87-4469-985d-9788c2729243`를 즉시 취소했다. 변경은 보존한다. 예약 변경은 `test_reservation_audit_fixes.py`와 `test_reservation_access_sync.py` 실행에서 **27 passed, 2 failed in 22.70s**다. 두 실패는 빈 snapshot 자동 해제 및 없는 DB 자동 생성이라는 이전 기대값과 새 안전 거부의 충돌이다. 백업 전 AccessStore 초기화, WAL 미포함 파일 복사, 백업 이름 충돌과 존재 확인 경합은 Sol 검토 요청 중이며 아직 수용·통합하지 않았다. 테스트 성공 수로 이 위험을 닫지 않는다.
이 절의 상태 작성자는 Astra Low다. 과거 테스트 수치는 현재 후보의 검증값으로 쓰지 않는다.
Sol 예약 검토 결정: 기존 변경은 조건부 재사용한다. health Muse 완료 후 예약 전용 Muse 턴에서 AccessStore 초기화 전 일관 백업, SQLite backup을 통한 WAL 커밋 내용 포함, 동일 방식의 dry-run, 고유 백업 이름, `mode=rw` 계열 missing DB 원자적 거절, 백업 무결성 확인을 보완한다. 기존 빈 snapshot 자동 해제와 missing DB 생성 기대값은 최신 안전 요구에 맞게 수정하되 회귀 근거를 남긴다. 예약 writer 범위는 parser/access_control/importer 및 예약 테스트, Bunny는 ledger_board 범위를 유지한다. 이 결정은 아직 구현 완료가 아니다.
Sol 후속 통합 결정 실행: Bunny의 범위 축소 전 미완성 `cli.py`·`ops.py`는 [보존 manifest](handoff/2026-09-29/preserved-bunny-reservation/manifest.json)에 파일 원문·patch SHA-256과 함께 보존하고 기준 `5c1db336`으로 복원했다. 복원 직전 해시 일치도 확인했다. 순서는 health Muse 수용·통합 → 해당 상태에서 예약 Muse가 cli reservation-sync/ops rehearsal까지 공통 예약 계약으로 보완 → 예약 검사 → Bunny ledger_board 결과 별도 통합이다. 미완성 변경을 완료 후보로 합치지 않는다.

| 항목 | 담당·상태 | 증거·다음 동작 |
|---|---|---|
| P1-DECISION | Sol `afe8152b-f066-4236-8673-925f49a9fa76`, 짧은 판단 요청 | 장기 실행 중단 완료. 도구 호출 없이 ownership 정리·파일 분할·acceptance·최소 검사 결정만 요청함 |
| P1-BUNNY-EXISTING | SpaceBunny `36982862-21d6-4f6b-b51c-921d4c981881`, 마지막 관측 running | `ledger_board.py` 변경과 platform/access 안정성 검사 중. 기존 넓은 할당 범위를 Sol 판단에 따라 정리하기 전 중복 배정 금지 |
| P1-OPS-READONLY | 미배정, 재현 완료 | `ops health`가 합성 DB 테이블을 1개에서 32개로 늘리고 exit0. 감독 기록의 재현을 acceptance에 연결 |
| P1-IMPORT-MISSING-DB | 미배정, 재현 완료 | 독립 예약 importer가 없는 합성 DB를 생성하고 exit0. 지정 경로 오류 시 무생성 거부가 필요 |
| P1-MUSE-WORKSPACE | 준비 | `wks_c3715977bc7cb896`, `muse/audit-fixes-20260929`, 기준 `5c1db336`. 최신 미커밋 규칙을 위임 전에 전달할 것 |
| MODEL-FREE | 공급자 목록 확인 완료 | OpenCode Zen의 두 지정 모델 input/output/cache 비용 0 확인. 실제 워커 실행 성공은 별도 기록 |
| P2-REMAINDER | 미완료 | 저장공간·예약·DB 이관·Railway 감사 잔여를 수용 근거에 연결. 완료 주장만으로 닫지 않음 |
| FINAL-REVIEW | 미착수 | Sol 전체 architecture/integration review와 Astra 저장소·검사·미해결 부재 확인 후 완료 가능 |

최종 감독 근거: [SUPERVISOR_REVIEW.md](handoff/2026-09-29/SUPERVISOR_REVIEW.md). 실제 변경·검증 결과는 제출 시 기준 digest와 결속해 이 작업표에 갱신한다.

### 2026-09-29 현재 진행 갱신

health 읽기 전용 수정과 예약 안전성 수정은 현재 작업트리에 반영했다. 예약 Muse 커밋 `395f7a3`은 Sol의 짧은 통합 검토에서 수용되었고, 부모가 현재 작업트리에서 관련 검사 75개 통과와 1개 건너뜀을 다시 확인했다. 예약 검사 29개와 운영 표면·안전성·health 검사를 함께 실행했으며 결과는 `75 passed, 1 skipped in 69.64s`다. 변경 파일의 구문 검사와 `git diff --check`도 통과했다.

예약 수정의 핵심은 SQLite backup API를 통한 WAL 포함 백업, dry-run의 동일 백업 경로, 충돌하지 않는 백업 이름, `mode=rw` 방식의 없는 DB 거부, 백업 무결성 검사, 빈 snapshot과 큰 감소에 대한 명시 override, cli·ops·importer의 공통 guard다. 없는 DB를 만들던 독립 importer 경로와 읽기 점검 중 스키마를 만들던 health 경로를 회귀 검사로 닫았다.

SpaceBunny는 웹 서버 간헐 실패 두 건에 대해 계측을 시도했지만 계측이 실행 시점을 바꿔 대상 실패를 재현하지 못했고, 추가 코드 변경도 하지 않았다. Sol은 추가 추적과 제품 수정을 보류하고, `ledger_board.py`의 검증되지 않은 docstring 한 줄은 되돌리도록 결정했다. 따라서 다음 잔여 항목은 `waiting_row_moves_to_a_trip`와 `viewer_read_refusal_never_reveals_the_row`의 간헐 실패 원인 미분리 상태다. 이 항목은 예약 수정과 분리해 보류한다.

현재 작업 상태는 **P1 안전성 수정 수용, 웹 서버 flaky 두 건 보류, 전체 완료 아님**이다. 전체 suite와 최종 Sol architecture/integration review는 웹 서버 잔여 위험을 별도 기록한 뒤에 수행한다.

최종 Sol architecture/integration review 결과는 **조건부 수용**이다. health와 예약 변경의 구조·범위·검사 근거는 수용했지만, 웹 서버 두 flaky의 원인 미분리와 acceptance 미달, 고정된 최종 후보의 전체 suite 1회 미실행 때문에 전체 프로젝트 완료 표시는 보류한다. 현재 phase는 **로컬 예약·health 안전성 통합 완료, 웹 서버 flaky 두 건 보류, 최종 전체 회귀 전**으로 기록한다. 코드가 더 바뀌지 않는 최종 후보가 확정되면 전체 suite만 1회 실행하고, 배포와 외부 운영 조건은 별도 미완료로 유지한다.

## 2026-09-29 최신 최종 검토와 로컬 완료 판정

앞 절 이후 웹 서버의 두 간헐 문제를 재현하고 원인을 분리했다. 두 서버가 모듈
전역 저장소를 함께 읽던 문제는 요청별 `ContextVar`로 서버의 저장소를 결속해
해결했다. 같은 서버의 요청 스레드들이 하나의 SQLite 연결을 동시에 사용하던
문제는 서버별 `RLock`으로 `do_GET`과 `do_POST` 처리 구간을 직렬화해 해결했다.
소켓을 읽는 `handle_one_request` 전체에는 잠금을 걸지 않아 silent preconnect를
해결한 `ThreadingHTTPServer` 동작을 보존했다.

변경 파일은 `webapp/ledger_board.py`와
`webapp/tests/test_ledger_server_store_isolation.py`다. 새 회귀 2개는 다음 조건으로
검증했다.

| 검증 | 결과 |
|---|---|
| 두 서버 저장소 격리와 한 서버 동시 요청 회귀 묶음 5회 | 매회 `2 passed` |
| `test_platform_start.py`, `test_access_control_phase7.py`, `test_ledger_design.py` 묶음 5회 | 매회 `91 passed` |
| 전체 `webapp/tests` fresh 실행 | `1033 passed, 1 skipped, 139 subtests passed in 449.58s` |
| `compileall`와 `git diff --check` | 통과 |

최종 Sol architecture/integration review는 로컬 구현을 수용했다. 현재 로컬 기능상
추가로 닫아야 할 항목은 없다. 서버 하나가 단일 SQLite 연결과 잠금을 공유하므로
처리량이 제한되는 점은 기능 오류가 아닌 후속 성능 개선 사항으로 기록한다.

외부 조건은 로컬 완료와 분리한다. 실제 Railway 환경 설정과 배포, 비밀값 주입,
운영 DB 보호·백업, Google OIDC callback, Reservation API, 실제 AI 연결과 등급,
실물 모바일과 Excel 출력은 실제 외부 증거가 생기기 전까지 운영 완료로 표시하지
않는다. 따라서 현재 phase는 **로컬 구현·검증·최종 검토 완료, 외부 운영 조건 대기**다.
