# 코어 1차 전환 — P1 자동 분류 작성자를 Python에서 Rust로

- 목적: P1 자동 분류의 판정 열 작성자를 Python `automatic_classification.apply`에서 Rust `costcore apply`로 바꾼다. 같은 DB에 쓰는 작성자는 하나다.
- 실행 주체: 운영 담당 세션(한 세션). 소유자 승인 지점은 아래 표시.
- 주기: 전환 1회. 전환 뒤 배포 창(하루 1~2회)마다 대조.
- 개정 이력: 2026-11-14 · 1차 부분 신설(U11) · 근거 설계 `docs/design/m3-core.md` §3.3·§7 U11. 2026-11-14 · 2차(연결) 부분 신설(그림자 `costcore shadow-links`와 절차, 쓰기 전환 코드는 아직 없음).

- 상태: 합성 DB 시험(T4)과 단위 시험까지만 확인했다. 운영 DB·운영 사본에서는 실행하지 않았다. 아래 단계는 전환 시점에 처음 수행한다.

## 전환이 바꾸는 것과 바꾸지 않는 것

- 바꾸는 것: P1 자동 분류 `apply`의 작성자 하나. 스위치는 운영 `card-flow.json`의 `classification_writer` 키(`rust`만 Rust, 키 없음·`python`은 Python. 기본 Python)이며, 런처와 Worker가 이를 프로세스 환경 변수 `WEBLEDGER_CLASSIFICATION_WRITER`로 옮긴다. 시험·수동 실행은 환경 변수를 직접 쓴다.
- 바꾸지 않는 것: 환불 연결 입력(Python 어댑터 `links`), 환불 묶음 기록, 인증 API 교정 경로(수동·P2·AI 검수 교정), 원천 열. Rust는 금액·부호·ID·원문 열을 쓰지 못한다(`store::write_columns::Write`가 허용 목록에서만 문장을 만든다).
- Rust 쓰기 순서: `BEGIN IMMEDIATE` → 계획 재생성·digest 대조(다르면 `CLASSIFICATION_PREVIEW_STALE`) → 목표마다 `core.sqlite`의 `decisions`(+`decision_history`)에 Decision 저장 → **저장된 행에서** 화면 열 도출 → `transactions`·`ledger_entries`·`board_rows`·`board_revisions`·`change_log` 쓰기. 두 파일은 `ATTACH` 한 트랜잭션이다. 운영 `board.sqlite`는 WAL, `core.sqlite`는 롤백 저널이라 파일별로 커밋되고 **board가 먼저** 커밋된다. 두 커밋 사이에 중단되면 화면 열은 채워졌는데 `decisions`가 없는 거래가 남는다(아래 "실패와 복구"). 같은 입력으로 다시 실행하면 쓰기는 0건이다.
- 게시하지 않는 것: `Protected`·`Preserved` 판정의 목표(귀속 불가, 완료 기간 등)와, 저장된 판정에서 도출한 화면 열이 계획 값과 다른 목표. 출력 `skipped_unjudged`·`skipped_mismatch`로 센다. **Python은 귀속 불가 행에 `unclassified`를 쓰지만 Rust는 쓰지 않는다**: 이 차이는 의도이며, 실데이터 그림자에서 나오면 운영 담당이 `core/known-diffs.txt`에 근거와 함께 올린다(C1 측정 때 결정).
- 이용기간: 판정에 이용기간(`service_period`)을 저장한다(`decisions.service_period_json`, 읽기 인터페이스 `store::decisions::stored_period`, Python `app.core_writer.stored_service_period`). **1차 전환 뒤 장부 화면·붙여넣기 묶음·장부 복사·시트 대사는 저장된 이용기간을 읽고, 렌더 시점에 다시 계산하지 않는다.** **전환 선행 조건: `app.core_writer`가 Python 다리 `periods` 출력을 `costcore apply`의 `context.periods`로 넘기도록 배선됨 — 충족(PR #898).** `automatic_classification.apply`가 작성자 rust일 때 `core_writer.periods_for`로 근거를 만들어 넘긴다. 근거 생성은 OTA 대조(운영 자료에서 약 10분)를 입력 키(`ota_payment_review.current_input_key`에서 apply가 쓰는 판정 열과 `revision`을 뺀 값)·수동 이용기간 덮어쓰기·다리 열 목록이 같으면 건너뛰므로 apply 자신의 쓰기로는 캐시가 깨지지 않고, 장부 화면이 읽는 `ota-snapshot.json`은 디스크에 이벤트·카드 원자료가 없어 재사용할 수 없다. 캐시가 비었을 때의 근거 생성은 `complete_scope`에서 보드 잠금 밖에서 먼저 하고(잠금 안에서는 만들어 둔 근거를 넘기기만 한다), 근거 생성은 모든 주 경로에서 보드 잠금·쓰기 트랜잭션 진입 전에 한다: `CardFlow.classify`, `CardFlow.auto_record`, `reclassify_cleanup`(미리보기 제외), `CardCompletionWorker.sweep_once`(후보가 있을 때만)가 `core_writer.prepared`로 근거와 키를 먼저 만들고, 잠금 안의 `complete_scope`·`correct_recorded_booking_periods`는 `core_writer.run_with_periods`로 키만 다시 비교한다(다르면 한 번 재생성, 그래도 다르면 `CLASSIFICATION_PREVIEW_STALE`). 아직 올리지 않은 호출 경로(예: `ota_catalog._reclassify`, 자율 정리 워커)는 각자 잠금 밖에서 만들거나 apply 안에서 만든다. `CardFlow.auto_record`는 rust 작성자일 때 분류(`_classify`)를 `BEGIN IMMEDIATE` 앞에서 하고 기록·투영만 트랜잭션 안에서 한다(Rust apply는 자체 트랜잭션이라 안에서 못 돌고, python 작성자는 분류부터 투영까지 한 트랜잭션 그대로). `tools/complete_card_classification.py`는 rust 작성자에서 쓸 수 없다(python 작성자로만 실행). `core.sqlite` 옆 `period-facts.json`의 파생 사실을 재사용하며, Rust는 근거 digest가 바뀐 거래만 재판정한다. 근거를 만들지 못하면 apply는 실패한다(전부 "모름"으로 쓰지 않는다). 첫 apply는 OTA 대조 때문에 오래 걸릴 수 있다. `--backfill-decisions`는 Python이 분류한 모든 행 중 화면 열이 계획과 같은 행의 `decisions`를 채우므로 출력 `backfilled` 건수가 매우 클 수 있다(첫 실행은 정상).
- 전환 선행 조건: cleanup worker도 잠금 밖 근거 생성·잠금 안 키 비교(이 PR) — `_prepare_sweep`이 `periods_with_key`를 두 잠금 밖에서 만들고, 잠금 안에서 `periods_key`가 같을 때만 `apply(..., periods=...)`를 부른다. 다르면 잠금을 놓고 1회 재생성하며, 그래도 다르면 `CLASSIFICATION_PREVIEW_STALE`로 그 작업만 실패한다(apply 미호출). 작성자가 python이면 근거를 만들지 않는다. `correct_recorded_booking_periods`와 `complete_card_classification`은 #910에서 `run_with_periods`로 바뀌었다. `rule_review.approve`는 `pipeline.store.lock`(웹 경로에서는 `board._lock`과 같은 객체)을 쥔 채 저장 뒤 갱신(`saved_state`→`classify`)까지 하던 것을 갱신만 잠금 밖으로 옮겼다(저장·재생 판정은 잠금 안, 근거 생성은 `prepared`가 잠금 밖; `apply`는 저장 트랜잭션 밖이라 `CORE_WRITER_IN_TRANSACTION`은 나지 않는다). 같은 방식이 아직 없는 호출처: `tools/complete_card_classification.py`(CLI, 웹 잠금 없음).

## 환불 짝 스위치 사용법(확정)

- 설정: 운영 `card-flow.json`의 `costcore_bin`(1차와 같음)과 `"links_producer": "rust"`(런처·Worker가 `WEBLEDGER_COSTCORE_BIN`·`WEBLEDGER_LINKS_PRODUCER`로 옮김). 키가 없거나 `rust`가 아니면 Python 그대로다(코어 호출 0). 되돌림은 키를 제거하거나 `python`으로 두고 재시작이다.
- 동작: `app/partial_refund._analyse`가 `costcore links refund --db <board>`(읽기 전용)를 부르고, `refund_links`·`refund_group`·`refund_original_links`·`count_held_cancellations`·`kakao_refund_candidates`·`partial_group_exclusion`·`refund_review_originals`가 모두 그 한 결과를 쓴다. 호출처(약 20곳)는 바뀌지 않는다.
- 캐시(프로세스 메모리): 키 = (DB 파일, costcore 파일 상태와 `--version`, `config/refund-pairing.json` 해시, 짝 도출이 읽는 16개 원열의 내용 해시·행 수·최대 rowid). `revision`은 판정 개정이라 `duplicate_of`·`conflict_reason`·`parse_error` 같은 원천 변경을 놓치므로 키로 쓰지 않는다. 분류 열(`item` 등) 변경은 키를 움직이지 않는다. 키가 다르면 재계산한다.
- 실패는 오류다(조용한 Python 대체 없음). 코드: `CORE_LINKS_NOT_CONFIGURED`(바이너리 변수 없음)·`CORE_LINKS_NEEDS_FILE_DATABASE`(파일 DB 아님)·`CORE_LINKS_UNCOMMITTED_ROWS`(이 연결의 미커밋 변경이 짝 입력을 바꿨는데 Rust는 파일만 읽음 — 커밋 뒤 부르거나, 쓰기 트랜잭션 안에서 판정해야 하는 경로만 `uncommitted_rows()`로 감싼다)·`CORE_LINKS_ORIGINAL_NOT_LINKED`(Rust가 연결하지 않은 원결제의 제외 사유 요청)·`CORE_LINKS_DB_CHANGING`(계산 중 두 번 연속 원행이 바뀜)·costcore 오류 코드.
- **쓰기 트랜잭션 안의 짝 계산(전환 차단 2건 해소)**: `costcore links refund --rows-stdin`은 `--db` 없이 표준 입력의 원행 JSON(짝 입력 16개 열, rowid 순서)으로 같은 도출을 한다. Python은 `core_links.uncommitted_rows()` 블록 안에서만, 이 연결의 짝 입력이 커밋된 파일과 다를 때 그 행을 stdin으로 보낸다(같으면 파일을 읽는다). 블록 밖의 미커밋 변경은 그대로 `CORE_LINKS_UNCOMMITTED_ROWS`다. 읽기만 감싸므로 트랜잭션·롤백은 바뀌지 않는다(카드 업로드 파일 단위 롤백, 수리 도구 사후 검사 뒤 롤백 유지). 결과는 같은 행에 대한 Python 도출과 같다(`tests/test_core_links_switch.py`, 실제 바이너리 `tests/card_pipeline/test_hana_supersede_rust_links.py`, Rust `shadow_links_cli`). 적용 지점: `app/card_hana_duplicate_repair.py`의 `_refund_reason`(`review._persist` 해외 원천 대체 분기와 수리 도구 공유)·`_financial_state`(`apply`/`restore` 사후 검사). 미커밋 행의 고객 원문은 stdin으로만 가고 디스크에 남지 않는다.
- 트랜잭션 안에서 짝 함수를 부르는 호출처(점검 목록): 위 두 곳(`_refund_reason`, `_financial_state`). 그 밖의 호출처는 `rust` 전체 시험(2026-11-15, 브라우저 시험 제외)에서 `CORE_LINKS_UNCOMMITTED_ROWS`가 나지 않았다 — 결과는 PR 본문 참고. `:memory:` DB를 쓰는 시험은 `CORE_LINKS_NEEDS_FILE_DATABASE`로 실패하는 것이 정상이다(운영은 파일 DB).
- 비용: `--rows-stdin`은 행마다 호출되는 해외 원천 대체 분기에서 호출당 원행 전체 JSON을 보낸다(Python 도출도 트랜잭션 안에서는 매번 재계산이라 같은 규모). 운영 사본에서 걸리는 시간은 아직 측정하지 않았다(운영 담당 측정).
- C1 확인 항목: 날짜가 `YYYY-MM-DD`가 아닌 원행(`approval_date`·`posting_date`)이면 Rust가 완료 기간(2025·2026Q1) 제외를 빠뜨릴 수 있다. 사본에서 날짜 형식 밖 원행 수를 확인하고, 있으면 그림자 차이로 드러나는지 본다.
- 시험: `python -m pytest tests/test_core_links_switch.py`(대역 바이너리). 실제 바이너리 대조는 `costcore_bin` 표식이 붙은 시험이고, `tools/run_quality_checks.py`가 표식 있는 파일이 선택되면 `cargo build --release -p costcore`(빌드 실패는 검사 실패)를 하고 `COSTCORE_TEST_BIN`을 넣어 돌린다(CI도 같은 도구). 수동 실행은 `COSTCORE_TEST_BIN=<costcore 경로>`를 주고 같은 명령.

## 입력(시작 조건)

1. U9·U10·U11 병합, 운영 배포가 `core` 빌드(`costcore`)를 포함.
2. C1: 신선 사본 1개에서 실데이터 그림자 B↔C 목록 밖 차이 0. C2: 평가 사례 Rust ≥ Python, Python 정답 중 Rust 오답 0. (운영 담당이 측정, 구현자·검수자는 다시 재지 않는다.)
3. 경로 `D:/WebLedgerHost/data/core.sqlite`가 있고 `costcore` 이관이 최신 버전이다. 만들기·이관은 `costcore migrate --core D:/WebLedgerHost/data/core.sqlite` 한 줄이며(출력 `{ok, created, from_version, to_version}`, 멱등), 플래그 전환 전에 실행한다.
   - 운영 core.sqlite 생성은 소유자 승인 ① 뒤에 한다(생성 순간부터 #906 범위 백업에 core 포함 강제).

## 단계

공통 주의: 배포·반영 창 동안 그림자 분석·자료 생성·전체 검사 등 무거운 작업을 돌리지 않고, Worker의 mail-collect는 창 동안 멈춘다(OTA 근거 재기록 수정 전까지 특히).

1. **소유자 승인 지점 ①** — C1·C2 측정 결과와 이 절차를 소유자(정책 수준 결정)가 승인한다. 승인 없이 2단계로 가지 않는다.
2. **C3 신선 백업·복원 확인**: `board.sqlite`와 `core.sqlite`를 신선 백업하고 복원 확인(`SPEC.md:383`). 백업은 `D:/WebLedgerHost/data/backups/`. 복원 확인 전에 진행하지 않는다.
3. **되돌림 예행**(C3): 2단계에서 복원 확인한 **사본 두 벌**(`rehearsal-a`, `rehearsal-b`; 운영 파일이 아니다)에서 Rust와 Python을 각각 한 번 실행한다. 둘 다 `ok`(오류 없음)여야 하고 운영 DB·운영 포트는 쓰지 않는다. PowerShell, 레포 루트에서:

   ```powershell
   $h = 'D:/WebLedgerHost/data/backups/c3-rehearsal'          # 보호 경로(Git 밖). 사본 board 두 벌과 core 사본을 둔다
   $a = "$h/rehearsal-a.sqlite"; $b = "$h/rehearsal-b.sqlite"; $core = "$h/core-rehearsal.sqlite"
   # (가) 사본 a의 미리보기 digest (Python 다리 plan, 읽기 전용; 사본 b는 a와 같은 파일이라 같은 digest)
   $digest = ('{"db":"' + $a + '"}' | python -I tools/core_bridge/cli.py plan | ConvertFrom-Json).result.digest
   # (나) Rust 작성자: 사본 a에 한 번. 출력의 written·skipped_mismatch를 기록한다(skipped_mismatch는 0이어야 한다)
   '{}' | core/target/release/costcore apply --db $a --core $core --digest $digest --host-root D:/WebLedgerHost
   # (다) Python 작성자: 사본 b에 한 번(변수 WEBLEDGER_CLASSIFICATION_WRITER 미설정). 같은 미리보기 digest를 쓴다
   '{}' | Set-Content "$h/opts.json"
   python -I core/crates/cli/tests/t4_python.py apply $b "$h/opts.json" (Get-Date).ToUniversalTime().ToString('yyyy-MM-ddTHH:mm:ss+00:00')
   # (라) 같은 입력 재실행은 쓰기 0: 사본 a에서 digest를 새로 만들어 (나)를 다시 하면 written=0
   $d2 = ('{"db":"' + $a + '"}' | python -I tools/core_bridge/cli.py plan | ConvertFrom-Json).result.digest
   '{}' | core/target/release/costcore apply --db $a --core $core --digest $d2 --host-root D:/WebLedgerHost
   ```

   확인: (나)·(다)가 성공하고 (라)가 `"written":0`이면 예행 통과. `rehearsal-a`와 `rehearsal-b`의 `transactions` 판정 열이 같은지(안내된 의도 차이 제외, `skipped_unjudged` 행) 대조해 기록한다. 예행 사본은 7일 뒤 정리한다.
4. **소유자 승인 지점 ②** — 전환 실행 승인(배포 창과 되돌림 담당 확인).
5. **플래그 전환**: 먼저 `costcore migrate --core D:/WebLedgerHost/data/core.sqlite`를 실행한다(운영 core.sqlite 생성은 소유자 승인 ① 뒤, 생성 순간부터 #906 범위 백업에 core 포함 강제). 그다음 운영 `D:/WebLedgerHost/config/card-flow.json`(BOM 허용, 런처와 Worker가 같은 함수로 읽음)에 `"classification_writer": "rust"`, `"costcore_bin": "<절대 경로>"`, `"core_db": "D:/WebLedgerHost/data/core.sqlite"`를 추가하고 서비스(Board와 Worker)를 재시작한다. 런처와 Worker가 이 키로 해당 프로세스(와 하위 프로세스) 환경에만 변수를 걸며, 사용자·시스템 전역 변수는 쓰지 않는다. `rust`인데 `costcore_bin`·`core_db`가 없거나 파일이 없거나 `core_db`가 데이터 루트 밖이면 시작을 거부한다(`CORE_SWITCH_BIN`·`CORE_SWITCH_DB`·`CORE_SWITCH_DB_ROOT`, Worker는 `WORKER_` 접두). 키가 없으면 Python 그대로다. **전환은 설정 수정과 재시작이라 배포 도구의 readyz 확인·자동 롤백이 적용되지 않는다. 런처가 거부하면 Board가 재시작에 계속 실패해 공개 장부가 내려간다.** 그래서 재시작 **전**에 `python -I D:/WebLedgerHost/releases/<SHA>/app/core_switch_config.py --check --host-root D:/WebLedgerHost`를 실행해 `ok`를 확인한다(런처와 같은 방식으로 card-flow.json을 읽고 같은 검증을 환경을 건드리지 않고 돌린다). `refused [코드]`면 재시작하지 않고 고친다. 재시작 뒤 거부로 내려갔다면 `card-flow.json`의 `classification_writer`·`links_producer`·`costcore_bin`·`core_db` 키를 제거하고 다시 재시작해 복구한다. rust 작성자가 설정된 동안 수동 도구 `tools/complete_card_classification.py --apply`와 `tools/review_card_inference.py --apply`는 `CORE_WRITER_MANUAL_APPLY_REFUSED`로 거부된다(작성자 혼합 방지). 같은 레포의 다른 세션에 배포 전후를 알린다. 이 순간부터 Python 자동 분류 쓰기는 꺼진다.
6. **첫 배포 창 대조**: ① A↔C: `transactions` 판정 열과 `core.sqlite` `decisions`가 일치. ② B↔C: `costcore shadow`를 신선 사본에 돌려 목록 밖 차이 0. ③ 작성자 확인: 해당 창의 `change_log` `kind='card.automatic_classification'` 기록 중 `json_extract(detail_json,'$.writer')`가 `'costcore'`인 것이 Rust 작성분이고 Python 작성분은 이 키가 없다(NULL). 창 안의 기록이 모두 `'costcore'`여야 한다(표식은 이 변경을 배포한 릴리스부터 붙는다. 그 전 기록은 구분되지 않는다). ④ 운영에서 apply마다 `D:/WebLedgerHost/data/core-apply-runs/latest.json`에 `latest`(마지막 실행)와 `recent`(최근 50건)가 남는다: 시각·digest·`written`·`skipped_mismatch`·`skipped_unjudged`·`backfilled`·`seconds`(거래 ID·원문 없음). 창 안의 모든 항목에서 `skipped_mismatch` = 0이어야 한다. 사본에 직접 돌린 `costcore apply`는 출력의 `skipped_mismatch`를 본다.
7. **차이가 1건이라도 나오면**: 즉시 `card-flow.json`의 `classification_writer` 키를 제거하거나 `"python"`으로 바꾸고 재시작해 Python으로 되돌린다. Rust가 쓴 행은 지우지 않는다(수동 교정 우선·이력 보존). 원인을 고친 뒤 C1~C3을 다시 잰다. 되돌린 사실과 원인을 `docs/operations.md`에 적는다.
8. 전환 뒤 매일 6단계의 ①②를 돌린다(Python 판정·연결 코드 퇴역 때까지).

## OTA 연결 스위치 사용법(`costcore links ota`)

- 스위치는 환불 짝과 같은 `WEBLEDGER_LINKS_PRODUCER`(`rust`만 Rust, 미설정·그 밖의 값은 Python. **기본 Python, 비용 0**)와 `WEBLEDGER_COSTCORE_BIN`이다. 어댑터는 `app/core_ota_links.py`이며 환불 어댑터와 별도 모듈이다. 스위치 판정(`selected`)과 변수 이름은 `app/core_links.py` 하나이고 `app/core_ota_links.py`가 그것을 가져다 쓴다.
- **릴리스 폴더에 `config/ota-matching-defaults.json`이 있어야 한다.** Rust는 `WEBLEDGER_OTA_MATCHING_DEFAULTS` 덮어쓰기를 읽지 않고 `--repo-root`(릴리스 폴더)의 이 파일만 읽는다. 덮어쓰기를 쓰는 환경은 `rust`로 전환하기 전에 같은 내용을 릴리스 폴더 파일에 반영한다.
- 풀이 결과는 개수가 이벤트 수와 같고 이벤트 ID가 겹치지 않아야 한다(어기면 `CORE_LINKS_RESULT_COUNT`·`CORE_LINKS_DUPLICATE_RESULT`로 실패, 폴백 없음).
- 바뀌는 곳은 `webapp/ota_payment_review._data`의 풀이기 호출 한 곳이다. 입력 조립(이벤트·카드·수동 연결·규칙·고정 그룹)과 결과 후처리는 그대로 Python이다. `rust`이면 같은 입력을 `costcore links ota --input - --repo-root <레포>`의 표준 입력으로 넘기고(고객 원문이 디스크에 남지 않는다), 돌려받은 연결 칸을 원 이벤트 위에 덧씌워 Python 풀이기와 같은 결과를 만든다.
- 실패는 폴백이 없다: 바이너리 미설정·종료 코드 0이 아님·응답 없음·미지의 이벤트·중복 이벤트 ID는 `RuntimeError`(`CORE_LINKS_*`)로 끝난다.
- 같은 변수가 `app/ota_review.py`의 검토 저장소 풀이(`OtaReviewStore`)에는 아직 닿지 않는다. 그 호출은 Python이다(후속).
- 입력 포착(`ota-input`)은 스위치가 켜져 있어도 Python 풀이기 호출 지점에서 멈춘다(포착이 환경 변수를 잠시 끈다).
- 사본 대조는 6단계 ②③과 같다. 실행 중 한 번 더 확인하려면 포착 파일을 `costcore links ota --input "$h/ota-input.json" --repo-root .`에 넣어 결과를 본다(연결 칸만 나오지만 사유·후보에 거래 정보가 있을 수 있으니 출력을 파일·PR에 붙이지 않는다).

## 실패와 복구

- `CLASSIFICATION_PREVIEW_STALE`: 미리보기 이후 데이터가 바뀜. 새 미리보기를 만든다(Python과 같은 동작).
- `CORE_WRITER_NOT_CONFIGURED`·`CORE_SCHEMA_MISMATCH`: 설정·이관 문제. 변수를 지워 Python으로 복귀한 뒤 고친다.
- `CORE_WRITER_IN_TRANSACTION`: 호출 경로가 이미 쓰기 트랜잭션 안에서 `apply`를 부른다. 그 경로는 아직 Rust 작성자로 못 바꾼다. 변수를 지워 복귀하고 호출 경로를 고친다(전환 전 미해결이면 전환 불가).
- 프로세스가 두 커밋 사이에 죽음: 운영 board는 WAL, core는 롤백 저널이고 board가 먼저 커밋된다. 결과는 **화면 열은 채워졌고 `decisions`가 없는 거래**다. 그 거래는 더 이상 계획의 목표가 아니라서 그냥 다시 실행해도 채워지지 않는다. 복구 두 가지 중 하나: ① 새 미리보기 digest를 만들어 `costcore apply ... --backfill-decisions`를 실행한다. 화면 열이 계획과 같고 `decisions`가 없는 거래에 판정만 저장하며 board는 건드리지 않는다(출력 `backfilled`). ② 작성자를 Python으로 되돌린다(`card-flow.json`의 `classification_writer` 키 제거 또는 `python`, 재시작). 6단계 A↔C 대조가 이 상태를 찾아낸다.

---

# 코어 2차 전환 — 연결 생산자(환불 짝·OTA↔카드 연결)를 Python에서 Rust로

- 목적: 환불 짝 도출(`app.partial_refund`)과 OTA↔카드 연결 풀이(`app.ota_payments.match_ota_payment_events`)의 계산 주체를 Python에서 Rust(`cost-core::links`)로 바꾼다. 같은 결과를 두 곳에서 만들지 않는다.
- 실행 주체: 운영 담당 세션(한 세션). 소유자 승인 지점은 아래 표시. 전환 1회, 이후 배포 창마다 대조.
- 개정 이력: 2026-11-14 · 2차 부분 신설 · 근거 설계 `docs/design/m3-core.md` §3.3·§7 U12~U14. 2026-11-14 · 환불 짝 쓰기 전환 코드와 스위치 이름 확정.
- 상태: **환불 짝 스위치 코드가 있다(기본 Python, opus 검수 대상). OTA 연결 스위치와 `ledger.py` 묶음 판정 배선은 아직 없다.** 합성 골든·합성 DB 시험까지만 확인했고 운영 DB·운영 사본에서는 실행하지 않았다. 1차 전환이 먼저 끝나 있어야 한다.

## 전환이 바꾸는 것과 바꾸지 않는 것

- 현재 Python 경로: 환불 짝은 저장하지 않고 호출마다 `transactions` 원행에서 도출한다(`refund_links` 호출처 약 20곳: `app/ledger.py`·`app/automatic_classification.py`·`webapp/card_flow.py`·`webapp/card_catalog.py` 등). 묶음 기록의 판정(`_apply_refund_pairs`·`_check_refund_groups`·`scope_group`)은 `app/ledger.py`. OTA 연결은 `webapp/ota_payment_review._data`가 이벤트·카드·수동 연결·규칙·고정 그룹을 모아 풀이기를 부르고, 결과를 `ota-snapshot.json`(`webapp/ota_snapshot.py`)과 OTA 저장소 연결로 낸다.
- 바꾸는 것: 위 두 계산의 생산자. 스위치는 새 환경 변수 `WEBLEDGER_LINKS_PRODUCER`(`rust`만 Rust, 미설정·그 밖의 값은 Python. **기본 Python**). 1차의 `WEBLEDGER_CLASSIFICATION_WRITER`와 독립이며, 한 변수를 바꿔도 다른 쪽 작성자는 바뀌지 않는다. 변수 이름은 확정이다(`app/core_links.py`). 운영에서는 `card-flow.json`의 `links_producer` 키가 이를 설정한다.
- 바꾸지 않는 것: 원천 열(금액·부호·ID·원문), 수동 교정·수동 OTA 연결(항상 우선), 인증 API, Google 장부 쓰기 없음. **보호 불변**: 중복·환불 짝·초과 환불(순잔액 음수)·원본 충돌 보호를 풀지 않는다(`links::refund`의 `clean`·`held`·`exclusion`이 Python과 같은 규칙으로 막는다). 한 카드는 두 연결에 점유되지 않고 기존 수동 연결은 바뀌지 않는다(`links::ota`, 속성 시험).
- 환불 묶음 기록(`ledger.py`의 기록 판정)과 OTA 저장소·스냅숏 쓰기는 Python이 계속 한다. Rust는 계산 결과(연결·묶음 범위·판정 코드)를 돌려줄 뿐 DB·스냅숏 파일을 쓰지 않는다. 따라서 1차와 달리 두 DB 사이 커밋 순서 문제는 없다.
- 의도된 차이: 아직 확인된 것 없음. 실데이터 그림자에서 나오면 운영 담당이 `core/known-diffs.txt`에 연결 유형 키(`B-C|refund_link|full|added` 형식)로 근거와 함께 올린다. 시험·판정 그림자·연결 그림자가 한 파일을 공유한다(연결 키는 연결 그림자만, 판정 키는 판정 그림자만 판정에 쓴다).

## 입력(시작 조건)

1. 쓰기 전환 PR 병합과 운영 배포(`costcore` 빌드 포함). 1차 전환 완료.
2. **C1**: 신선 사본 1개에서 `costcore shadow-links` 목록 밖 차이 0. 환불 짝은 사본 DB로, OTA 연결은 풀이기 입력 파일(`--ota-input`)로 잰다. **OTA C1은 입력 포착 도구(`python -I tools/core_bridge/cli.py ota-input`, 6단계 ②)로 입력 파일을 만든 뒤 잴 수 있다(측정 가능).** 같은 신선 사본에서 `costcore shadow`(판정)도 목록 밖 차이 0이어야 한다.
3. **C2**: 평가 사례 Rust ≥ Python, Python 정답 중 Rust 오답 0(1차와 같은 측정, 연결을 Rust로 쓴 판정 기준).
4. **C3**: 신선 백업·복원 확인과 스위치 되돌림 예행(아래 3단계).
5. 측정은 운영 담당이 한다(구현자·검수자는 다시 재지 않는다).

## 단계

공통 주의: 배포·반영 창 동안 그림자·자료 생성·전체 검사 등 무거운 작업을 돌리지 않고, Worker의 mail-collect는 창 동안 멈춘다. 운영 포트(8751·8752·8790)는 시험에 쓰지 않는다.

1. **소유자 승인 지점 ①** — C1·C2 측정 결과와 이 절차(환불 짝·OTA 연결을 함께 바꾸는지 하나씩 바꾸는지 포함)를 소유자가 승인한다. 승인 없이 2단계로 가지 않는다.
2. **C3 신선 백업·복원 확인**: `board.sqlite`와 `core.sqlite`를 신선 백업하고 복원 확인(`SPEC.md:383`). 백업은 `D:/WebLedgerHost/data/backups/`.
3. **되돌림 예행**(C3): 복원 확인한 사본(운영 파일이 아니다)에서 변수 미설정(Python)과 `rust` 두 번 실행해 둘 다 오류 없이 끝나고 연결 결과가 같은지 확인한 뒤, 변수를 지워 다시 Python 결과로 돌아오는지 본다. 연결 결과 대조는 아래 4단계 ②의 명령을 사본에 쓴다. 쓰기 전환 PR이 사본 실행 방법을 정한다(운영 DB·포트를 쓰지 않는다).
4. **소유자 승인 지점 ②** — 전환 실행 승인(배포 창과 되돌림 담당 확인).
5. **스위치 전환**: 운영 `card-flow.json`에 `"links_producer": "rust"`를 추가하고(`costcore_bin`은 1차에서 설정됨) 서비스를 재시작한다. 같은 레포의 다른 세션에 배포 전후를 알린다. 이 순간부터 연결 계산은 Rust가 한다.
6. **첫 배포 창 대조**(PowerShell, 레포 루트, 신선 사본에서):

   ```powershell
   $h = 'D:/WebLedgerHost/data/backups/c1-links'   # 보호 경로(Git 밖)
   $copy = "$h/fresh-copy.sqlite"                   # 2단계에서 복원 확인한 신선 사본(운영 파일이 아니다)
   # ① 환불 짝(사본 DB만으로 잰다. OTA 연결은 ②③)
   core/target/release/costcore shadow-links --db $copy --private-out "$h/links-details-$(Get-Date -Format yyyyMMddHHmm).jsonl" --host-root D:/WebLedgerHost
   # ② OTA 풀이기 입력 포착(읽기 전용). 사본 3개(board·ota-evidence·ota-review)는 2단계의 신선 사본이며 운영 파일이 아니다.
   #    출력은 고객 원문(가맹점·예약 정보)을 담으므로 D:/WebLedgerHost/data/backups/ 아래 보호 경로에만 쓴다(레포 안·그 밖은 거부, 기존 파일 덮어쓰지 않음).
   $req = @{ db = $copy; ota_evidence = "$h/ota-evidence-copy.sqlite"; review_db = "$h/ota-review-copy.sqlite"; host_root = 'D:/WebLedgerHost'; out = "$h/ota-input.json" } | ConvertTo-Json -Compress
   $req | python -I tools/core_bridge/cli.py ota-input     # 응답은 건수와 sha256뿐. DB_IS_LIVE·OUT_INSIDE_REPO·OUT_NOT_PROTECTED·OUT_EXISTS는 실패
   # ③ OTA 연결 대조: ①과 같은 명령에 --ota-input "$h/ota-input.json"을 더해 다시 돌린다(환불 짝과 한 번에 잰다)
   core/target/release/costcore shadow-links --db $copy --ota-input "$h/ota-input.json" --private-out "$h/links-details-$(Get-Date -Format yyyyMMddHHmm).jsonl" --host-root D:/WebLedgerHost
   # ④ 판정(1차와 같은 대조)
   core/target/release/costcore shadow --db $copy --host-root D:/WebLedgerHost
   ```

   확인: 종료 코드 0, `status`가 `PASS`, `unlisted`가 비어 있음, `refund.python`과 `refund.rust` 건수가 같음. 공개 출력에는 유형 키와 건수만 나오고 거래·이벤트 ID는 `--private-out` 파일에만 쓴다. 1차의 A↔C 대조(`transactions` 판정 열과 `decisions`)도 함께 한다.
7. **차이가 1건이라도 나오면**: 즉시 `links_producer` 키를 제거하거나 `"python"`으로 바꾸고 재시작해 Python으로 되돌린다. 연결은 저장하지 않고 Python이 원행에서 다시 도출하므로 되돌림에 데이터 복구가 필요 없다. 이미 Rust 연결로 기록된 묶음 행은 지우지 않는다(수동 교정 우선·이력 보존). 원인을 고친 뒤 C1~C3을 다시 잰다. 되돌린 사실과 원인을 `docs/operations.md`에 적는다.
8. 전환 뒤 매일 6단계를 돌린다(Python 연결 코드 퇴역 때까지).

## 전환 전 확인 사항(2026-11-15)

- **읽기 스냅숏 경합**: `BEGIN`으로 연 읽기 연결의 스냅숏이 낡은 뒤 다른 연결이 짝 입력을 커밋하면 `rust`는 `CORE_LINKS_UNCOMMITTED_ROWS`로 실패했다(Python은 영향 없음). 이제 `card_transactions.list_for_day`·`sheets_export.build_workbook`·`partial_refund.read_only_scope`(워커·화면 렌더)·`PRAGMA query_only=ON` 연결은 스냅숏이 보는 행을 stdin으로 보내 답한다. `partial_refund.read_only_scope()` 안에서는 쓰기 트랜잭션의 미커밋 행도 거부되지 않고 stdin으로 처리된다(읽기 전용 표시 범위라는 호출 규약에 기댄다). 그 밖의 쓰기 트랜잭션은 `uncommitted_rows()` 없이는 거부한다.
- **비용**: 하나 대체 분기(스냅숏 행이 파일과 다를 때)는 호출마다 `transactions` 전체를 JSON으로 stdin에 보낸다(행 수에 비례). 운영 사본 크기에서의 실측은 운영 담당이 6단계 대조와 함께 잰다(구현자는 재지 않았다).

- **전환 전 확인 완료 목록**(`WEBLEDGER_LINKS_PRODUCER=rust`, 브라우저 제외 전체 시험 560개 파일, 2026-11-15 `7c76adde` + 이 PR). Python 기준 대조에서 rust에서만 실패한 시험 310건(33개 파일)을 분류했다. **제품 결함은 위 읽기 스냅숏 경합 1건뿐이었고 고쳤다.** 나머지는 시험 구조 문제이며 운영 DB(전체 보드 스키마·파일 DB)에는 해당하지 않는다.
  - 파일 DB가 없는 연결(`:memory:`): **운영 경로에 있었다.** `webapp/expense_bulk_maintenance._clone_store`(일괄 정리 미리보기·적용 선행 검사, HTTP 라우트)와 `tools/complete_card_classification.py` 미리보기(`:memory:` 사본)가 환불 짝 함수를 불러 rust에서 `CORE_LINKS_NEEDS_FILE_DATABASE`로 실패했다(라우트 503). 고쳤다: 파일이 없는 연결은 그 연결의 행을 `--rows-stdin`으로 보내 답한다(Python과 같은 결과, 시험 추가). 이 항목은 시험 구조 문제가 아니다. 남은 `:memory:` 시험(`test_partial_refund`·`test_refund_inference_runtime`·`test_refund_foreign_pairs`·`test_quarter_review_eval_*`·`test_cleanup_query_equivalence`)은 이 수정으로 통과하거나, Python 내부 `_settings`를 monkeypatch해 설정을 바꾸는 시험(`test_refund_foreign_pairs::test_the_rule_can_be_switched_off`)이다. `test_partial_refund::test_committed_refund_analysis_is_reused_until_a_write_or_another_commit`은 호출 수 관찰이 아니라 `STORE_ERROR`(Pipeline 스키마만 있는 파일 DB)로 실패하므로 아래 최소 스키마 항목에 속한다. 재확인 근거: `app`·`webapp`·`tools`(시험 제외)에서 `:memory:` 연결 생성처는 `expense_bulk_maintenance`, `complete_card_classification`(둘 다 위에서 처리), `app/db.py:262`(스키마 기준 비교, 환불 짝 호출 없음), `tools/benchmark_ota_queue.py`(벤치, 환불 짝 호출 없음), `tools/repair_dist141_provenance.py:91`·`tools/review_card_inference.py:65`·`tools/p2_rules/rehearsal.py`·`tools/quarter_review/eval_cases.py`(오프라인 예행 도구, 환불 짝을 부를 수 있으나 위 수정으로 해결)뿐이다.
  - 최소 스키마 시험 DB(`transactions`만 있어 `costcore links refund --db`가 보드 보조 테이블을 못 읽어 `STORE_ERROR`): `test_card_transactions`·`test_cards_all*`·`test_card_issuer_search`·`test_card_upload_reconciliation`·`test_pipeline`·`test_card_refund_destination`·`test_card_stage_metrics`, `test_partial_refund::test_committed_refund_analysis_is_reused_until_a_write_or_another_commit`(Pipeline 스키마만 있는 파일 DB) 등. 운영 보드는 전체 스키마. 후속 후보: 환불 짝 경로가 `transactions`만 읽도록 좁히면 최소 스키마 시험도 통과하고 분기 비용도 줄어든다(Rust 변경이라 이 PR에서 하지 않음).
  - Python 풀이기를 stub으로 관찰하는 OTA 시험(Rust OTA 풀이기는 stub 결제를 보지 않음): `test_core_bridge_ota_input`·`test_ota_payment_review`·`test_ota_snapshot_actions`·`test_toyoko_reconciliation` 27건. OTA 동등성은 `costcore shadow-links --ota-input`(C1)이 잰다.
  - 부하 시간 초과 1건: `test_continuous_deployment`(PowerShell 하위 실행, Idle 우선순위). 환불 짝과 무관.
  - Python 기준에서도 실패한 것은 기존 known 목록 또는 부하·브라우저 시험이다(Python 재실행 6건이 known 밖이었으나 같은 부하 시간 초과·브라우저 시험 성격).
  - 시험 `test_hana_repair_cli_apply_on_verified_isolated_copy`는 외부 실행 차단을 costcore 호출만 허용하도록 좁혔다(기대값 불변).

## 실패와 복구

- `PYTHON_BRIDGE_FAILED:*`·`ENVELOPE_MISMATCH`: 다리 실행 실패. 그림자는 PASS도 FAIL도 아니라 오류로 끝난다. 원인을 고쳐 다시 돌린다(전환 전이면 전환하지 않는다).
- `DB_IS_LIVE`: 사본이 아닌 운영 DB 경로. 신선 사본으로 다시 한다(운영 DB는 읽지 않는다). 시각을 보존하는 복사(`robocopy /COPY:DAT`)로 만든 사본은 `DB_IS_LIVE`로 거부되니 sqlite backup API로 사본을 만든다.
- `PRIVATE_PATH_REJECTED`: `--private-out`이 보호 경로(`D:/WebLedgerHost/data/backups/`) 밖. 경로를 고친다.
- `KNOWN_DIFFS_INVALID`: `core/known-diffs.txt`에 중복·형식 밖 줄. 줄을 고친다.
- 전환 뒤 스위치 `rust`에서 Rust 연결 계산이 실패하면 호출 경로가 오류를 낸다(조용히 Python으로 대체하지 않는다). 변수를 지워 Python으로 복귀한 뒤 원인을 고친다.
