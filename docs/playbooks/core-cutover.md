# 코어 1차 전환 — P1 자동 분류 작성자를 Python에서 Rust로

- 목적: P1 자동 분류의 판정 열 작성자를 Python `automatic_classification.apply`에서 Rust `costcore apply`로 바꾼다. 같은 DB에 쓰는 작성자는 하나다.
- 실행 주체: 운영 담당 세션(한 세션). 소유자 승인 지점은 아래 표시.
- 주기: 전환 1회. 전환 뒤 배포 창(하루 1~2회)마다 대조.
- 개정 이력: 2026-11-14 · 1차 부분 신설(U11) · 근거 설계 `docs/design/m3-core.md` §3.3·§7 U11. 2차(연결) 부분은 U14가 아래에 더한다.

- 상태: 합성 DB 시험(T4)과 단위 시험까지만 확인했다. 운영 DB·운영 사본에서는 실행하지 않았다. 아래 단계는 전환 시점에 처음 수행한다.

## 전환이 바꾸는 것과 바꾸지 않는 것

- 바꾸는 것: P1 자동 분류 `apply`의 작성자 하나. 스위치는 환경 변수 `WEBLEDGER_CLASSIFICATION_WRITER`(`rust`만 Rust, 미설정·그 밖의 값은 Python. 기본 Python).
- 바꾸지 않는 것: 환불 연결 입력(Python 어댑터 `links`), 환불 묶음 기록, 인증 API 교정 경로(수동·P2·AI 검수 교정), 원천 열. Rust는 금액·부호·ID·원문 열을 쓰지 못한다(`store::write_columns::Write`가 허용 목록에서만 문장을 만든다).
- Rust 쓰기 순서: `BEGIN IMMEDIATE` → 계획 재생성·digest 대조(다르면 `CLASSIFICATION_PREVIEW_STALE`) → 목표마다 `core.sqlite`의 `decisions`(+`decision_history`)에 Decision 저장 → **저장된 행에서** 화면 열 도출 → `transactions`·`ledger_entries`·`board_rows`·`board_revisions`·`change_log` 쓰기. 두 파일은 `ATTACH` 한 트랜잭션이다. 운영 `board.sqlite`는 WAL, `core.sqlite`는 롤백 저널이라 파일별로 커밋되고 **board가 먼저** 커밋된다. 두 커밋 사이에 중단되면 화면 열은 채워졌는데 `decisions`가 없는 거래가 남는다(아래 "실패와 복구"). 같은 입력으로 다시 실행하면 쓰기는 0건이다.
- 게시하지 않는 것: `Protected`·`Preserved` 판정의 목표(귀속 불가, 완료 기간 등)와, 저장된 판정에서 도출한 화면 열이 계획 값과 다른 목표. 출력 `skipped_unjudged`·`skipped_mismatch`로 센다. **Python은 귀속 불가 행에 `unclassified`를 쓰지만 Rust는 쓰지 않는다**: 이 차이는 의도이며, 실데이터 그림자에서 나오면 운영 담당이 `core/known-diffs.txt`에 근거와 함께 올린다(C1 측정 때 결정).
- 이용기간: 판정에 이용기간(`service_period`)을 저장한다(`decisions.service_period_json`, 읽기 인터페이스 `store::decision_store::stored_service_period`, Python `app.core_writer.stored_service_period`). **1차 전환 뒤 장부 화면·붙여넣기 묶음·장부 복사·시트 대사는 저장된 이용기간을 읽고, 렌더 시점에 다시 계산하지 않는다.** 이 읽기 전환은 `feat/m3-service-period-in-decision-20261114`가 병합된 뒤 배선한다. 아래 3단계 전에 두 변경이 모두 병합되어 있어야 하며, 병합 전에는 이 항목을 "미충족"으로 보고 전환하지 않는다.

## 입력(시작 조건)

1. U9·U10·U11 병합, 운영 배포가 `core` 빌드(`costcore`)를 포함.
2. C1: 신선 사본 1개에서 실데이터 그림자 B↔C 목록 밖 차이 0. C2: 평가 사례 Rust ≥ Python, Python 정답 중 Rust 오답 0. (운영 담당이 측정, 구현자·검수자는 다시 재지 않는다.)
3. 경로 `D:/WebLedgerHost/data/core.sqlite`가 있고 `costcore` 이관이 최신 버전이다.

## 단계

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
5. **플래그 전환**: 운영 환경에 `WEBLEDGER_COSTCORE_BIN`·`WEBLEDGER_CORE_DB`·`WEBLEDGER_CLASSIFICATION_WRITER=rust`를 설정하고 서비스를 재시작한다. 같은 레포의 다른 세션에 배포 전후를 알린다. 이 순간부터 Python 자동 분류 쓰기는 꺼진다.
6. **첫 배포 창 대조**: ① A↔C: `transactions` 판정 열과 `core.sqlite` `decisions`가 일치. ② B↔C: `costcore shadow`를 신선 사본에 돌려 목록 밖 차이 0. ③ 작성자 확인: 해당 창의 `change_log` `card.automatic_classification` 기록이 Rust 실행분뿐. ④ `costcore apply` 출력의 `skipped_mismatch` = 0.
7. **차이가 1건이라도 나오면**: 즉시 `WEBLEDGER_CLASSIFICATION_WRITER`를 지우고(또는 `python`) 재시작해 Python으로 되돌린다. Rust가 쓴 행은 지우지 않는다(수동 교정 우선·이력 보존). 원인을 고친 뒤 C1~C3을 다시 잰다. 되돌린 사실과 원인을 `docs/operations.md`에 적는다.
8. 전환 뒤 매일 6단계의 ①②를 돌린다(Python 판정·연결 코드 퇴역 때까지).

## 실패와 복구

- `CLASSIFICATION_PREVIEW_STALE`: 미리보기 이후 데이터가 바뀜. 새 미리보기를 만든다(Python과 같은 동작).
- `CORE_WRITER_NOT_CONFIGURED`·`CORE_SCHEMA_MISMATCH`: 설정·이관 문제. 변수를 지워 Python으로 복귀한 뒤 고친다.
- `CORE_WRITER_IN_TRANSACTION`: 호출 경로가 이미 쓰기 트랜잭션 안에서 `apply`를 부른다. 그 경로는 아직 Rust 작성자로 못 바꾼다. 변수를 지워 복귀하고 호출 경로를 고친다(전환 전 미해결이면 전환 불가).
- 프로세스가 두 커밋 사이에 죽음: 운영 board는 WAL, core는 롤백 저널이고 board가 먼저 커밋된다. 결과는 **화면 열은 채워졌고 `decisions`가 없는 거래**다. 그 거래는 더 이상 계획의 목표가 아니라서 그냥 다시 실행해도 채워지지 않는다. 복구 두 가지 중 하나: ① 새 미리보기 digest를 만들어 `costcore apply ... --backfill-decisions`를 실행한다. 화면 열이 계획과 같고 `decisions`가 없는 거래에 판정만 저장하며 board는 건드리지 않는다(출력 `backfilled`). ② 작성자를 Python으로 되돌린다(`WEBLEDGER_CLASSIFICATION_WRITER` 해제). 6단계 A↔C 대조가 이 상태를 찾아낸다.
