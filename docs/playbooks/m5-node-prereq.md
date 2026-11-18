# M5 보조 노드 사전조건 점검

- 목적: 보조 노드(로컬 PC의 P2 실행기) 운영을 시작하기 전에, **클라우드 없이 지금 검증할 수 있는 것**과 **제공자 결정 뒤에만 되는 것**을 구분하고 그 경계를 매번 같은 방식으로 확인한다.
- 실행 주체: 개발자·에이전트(스크립트 `rehearse.py`). 판단 단계 없음.
- 주기: M5 후보가 바뀔 때, 제공자를 결정하기 전, 그리고 실제 클라우드·노드를 붙이기 직전.
- 개정 이력: 2026-11-18 최초 작성(origin/main `d2debf38`, 합성 2-프로세스 예행 근거).

이 절차서는 **합성 검증 절차**다. 실제 클라우드·과금·원문 국외 이전은 [통합 명세](../SPEC.md) §11.3·§14#10 소유자 결정 뒤의 별도 절차이며 이 문서의 범위가 아니다. 예행 원본은 `.local-archive/m5-prereq-20261118/`(Git 제외)에 있고, 이 문서는 재현 가능한 절차만 담는다.

## 입력

- Rust 도구체인(`rustc 1.100.0`). `cargo build -p costcore`가 되는 상태.
- Python 3.14와 저장소 의존성. `pytest`·`cryptography`가 설치돼 있어야 한다(TLS 검사가 쓴다).
- 읽을 코드: `core/crates/core/src/jobs/mod.rs`(큐 전이), `tools/m5_runtime.py`(전송·서버·노드), `tools/m5_p2_adapter.py`(P2 실행), `tools/m5_backup.py`(백업).
- **예약 포트 8751·8752·8790은 어떤 경우에도 쓰지 않는다.** 큐는 `port: 0`, 보드는 OS가 준 임의 포트를 쓴다.
- 운영 DB·`D:/WebLedgerHost`·공유 체크아웃 `C:/AX/cost`를 열지 않는다. 합성 스크래치만.

## 단계

1. **바이너리 빌드.** `cargo build --manifest-path core/Cargo.toml -p costcore`.
   성공 판단: `core/target/debug/costcore.exe`가 생기고 `costcore --version`이 rc0.
2. **합성 코어·스냅숏 준비.** `rehearse.py`가 `migrate`로 `core.sqlite`를 만들고, `p2 prepare`/`validate`로 digest 결속을 확인한 뒤, 합성 원문 1개로 `m5_backup.create_snapshot`을 만든다.
   성공 판단: prepare→validate가 같은 답을 돌려주고 스냅숏 `snapshot_id`가 나온다.
3. **서버+보드 기동.** `costcore server --config server.json`. `server.json`은 `port: 0`, `bind: 127.0.0.1`, `web_args`에 `--port <임의> --data-root <스크래치> --no-worker --environment local-synthetic --synthetic-sessions`.
   성공 판단: 서버 stdout 첫 줄 `{"ok":true,"queue_port":N}`. 두 포트가 예약 포트가 아님. `/readyz` 200.
4. **인증 조회 경로 확인.** 스크래치 `board.sqlite`에 `AccessStore.ensure_owner("syn-owner")`로 합성 소유자 하나를 만든다(운영 로그인 아님). `X-Synthetic-User` 헤더로 `/api/plush/bootstrap`.
   성공 판단: bootstrap 200, `role: owner`.
5. **PC-off 모사 — 노드 사망.** `runner: codex`에 느린 대체 실행 파일을 물려 노드를 띄우고, `leased`+`attempts=1`이 관측되면 내가 띄운 노드 트리를 `taskkill /T /F`로 죽인다.
   성공 판단: 사망 직후 `jobs` 행이 `leased`로 남아 있다(임대는 서버 DB 소유).
6. **PC-off 구간 조회·P1.** 노드가 전부 죽은 상태에서 `/readyz`·`bootstrap`을 다시 부르고, `owner: server-p1, kinds: ["p1_publish"]`로 P1을 임대·완료한다.
   성공 판단: 두 응답 200, P1 `succeeded` (P2 적체와 무관하게 먼저 나감).
7. **만료·재시도 — 실제 시계로.** `runner: replay` 노드를 띄우고 임대 만료를 기다린다(설계 임대 300초 + 첫 재시도 지연). 시간을 조작하지 않는다.
   성공 판단: 만료 전 `claimed:0` 반복 → 회수 후 `claimed:1 succeeded:1`, 최종 `attempts=2`이고 결과가 리플레이 답변과 같다.
8. **정확히 1회.** 같은 `dedupe_key`로 다시 적재하고 노드를 `--once`로 한 번 더 돌린다.
   성공 판단: 재적재가 **같은 job_id**, `attempts`·`result_json` 불변.
9. **PC-off 적재 후 재개.** 정지 상태에서 새 P2를 적재(`queued` 유지), 노드 `--once`로 완료.
   성공 판단: `succeeded attempts=1`, 재실행에서 추가 반영 0.
10. **역방향 백업.** 노드 `backup_destination`에 세대가 생기고 `complete:true`.
    성공 판단: `verify_snapshot` id가 원본과 같고, 복원 core `PRAGMA integrity_check=ok`, 원문 바이트 일치.

## 판단 기준

| 관찰 | 해석 | 할 일 |
| --- | --- | --- |
| 첫 백업이 `PUBLISH_FAILED`, 다음 회차 `ok:true` | Windows `os.rename` 일시 경합. 상태는 갱신되지 않으므로 재시도가 따라잡음 | 정상 범위. **반복**되면 같은 폴더 잔여 stage 이름만 확인(삭제 금지) |
| 노드 강제 종료 뒤 `p2 --operation codex` 자식이 남음 | 상위가 죽어도 자식은 끝까지 돈다. 결과는 미전송 → 만료 후 재실행 | 중복 반영은 없으나 **제공자 호출 1회 추가**. 비용 상한 계산에 포함 |
| 만료 회수가 300초보다 길다 | 정상. 다음 claim 때 회수되므로 회수 시점은 claim 주기(노드 15초)에 묶인다 | 조작하지 말고 실제 값을 기록 |
| `hold` 노드가 `claimed:0`을 반복 | 아직 임대 유효(만료 전) | 기다린다. not_before를 손으로 고치지 않는다(예행 원칙) |
| 예약 포트가 보임 | 구성 실패 | 즉시 중단. `port`/`web_args`를 임의값으로 |

## 출력

- `run/driver.log`: 시간순 관측 로그(사람이 읽는 원본).
- `run/summary.json`: 포트·job id·만료 경과 초 요약.
- `run/staging/`: 합성 `core.sqlite`·스냅숏·토큰·원문·노드 백업 세대.
- 검증 방법: 위 10단계의 "성공 판단"을 로그 줄과 `jobs`/`budgets` 표 값으로 대조한다(요약만 보고 판정하지 않는다).

## 실패했을 때

- **빌드 실패**: `cargo build` 출력 확인 후 재시도. 도구체인 문제면 멈춘다.
- **`CORE_SCHEMA_MISMATCH`**: 합성 `core.sqlite`를 `migrate`로 새로 만든다(구버전 파일은 거부가 정상).
- **`NODE_HTTPS_REQUIRED`/`NODE_CONNECTION_FAILED`**: `allow_loopback_http`가 `true`인지, 서버가 실제로 떴는지 확인.
- **만료 회수가 15분 안에 안 옴**: 노드 프로세스가 살아 있는지, `claim`을 실제로 부르는지 로그로 확인. 손으로 `lease_until`을 고치지 않는다(그러면 검증이 아니다).
- 재시도 한도: 같은 단계 2회까지. 그 뒤에는 원인을 기록하고 소유자·감독 세션에 넘긴다.

## 하지 않는 것

- 실제 클라우드·계정·유료 계약·원문 외부 전송. **로컬 프로세스만.**
- 예약 포트 8751·8752·8790 사용.
- 운영 DB·`D:/WebLedgerHost`·공유 체크아웃 접근.
- 실제 모델 호출(어댑터는 리플레이 합성 답변으로).
- 내가 띄우지 않은 프로세스 종료. 정리는 `taskkill /T /F /PID <내 PID>`로 내 트리만.
- 제품 코드·테스트 수정, push·PR·배포. 검증에서 나온 결함은 코드를 고치지 말고 규칙집 사례·운영 판독 항목으로 올린다.
