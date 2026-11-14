# 코어 1차 전환 — P1 자동 분류 작성자를 Python에서 Rust로

- 목적: P1 자동 분류의 판정 열 작성자를 Python `automatic_classification.apply`에서 Rust `costcore apply`로 바꾼다. 같은 DB에 쓰는 작성자는 하나다.
- 실행 주체: 운영 담당 세션(한 세션). 소유자 승인 지점은 아래 표시.
- 주기: 전환 1회. 전환 뒤 배포 창(하루 1~2회)마다 대조.
- 개정 이력: 2026-11-14 · 1차 부분 신설(U11) · 근거 설계 `docs/design/m3-core.md` §3.3·§7 U11. 2차(연결) 부분은 U14가 아래에 더한다.

- 상태: 합성 DB 시험(T4)과 단위 시험까지만 확인했다. 운영 DB·운영 사본에서는 실행하지 않았다. 아래 단계는 전환 시점에 처음 수행한다.

## 전환이 바꾸는 것과 바꾸지 않는 것

- 바꾸는 것: P1 자동 분류 `apply`의 작성자 하나. 스위치는 환경 변수 `WEBLEDGER_CLASSIFICATION_WRITER`(`rust`만 Rust, 미설정·그 밖의 값은 Python. 기본 Python).
- 바꾸지 않는 것: 환불 연결 입력(Python 어댑터 `links`), 환불 묶음 기록, 인증 API 교정 경로(수동·P2·AI 검수 교정), 원천 열. Rust는 금액·부호·ID·원문 열을 쓰지 못한다(`store::write_columns::Write`가 허용 목록에서만 문장을 만든다).
- Rust 쓰기 순서: `BEGIN IMMEDIATE` → 계획 재생성·digest 대조(다르면 `CLASSIFICATION_PREVIEW_STALE`) → 목표마다 `core.sqlite`의 `decisions`(+`decision_history`)에 Decision 저장 → **저장된 행에서** 화면 열 도출 → `transactions`·`ledger_entries`·`board_rows`·`board_revisions`·`change_log` 쓰기. 두 파일은 `ATTACH` 한 트랜잭션이다. WAL 모드에서는 파일별 원자성이라 커밋 사이 중단 시 `decisions`가 앞설 수 있으나, 같은 입력으로 다시 실행하면 화면 쪽만 채워진다(멱등, 다시 실행 시 쓰기 0건).
- 게시하지 않는 것: `Protected`·`Preserved` 판정의 목표(귀속 불가, 완료 기간 등)와, 저장된 판정에서 도출한 화면 열이 계획 값과 다른 목표. 출력 `skipped_unjudged`·`skipped_mismatch`로 센다. **Python은 귀속 불가 행에 `unclassified`를 쓰지만 Rust는 쓰지 않는다**: 이 차이는 의도이며, 실데이터 그림자에서 나오면 운영 담당이 `core/known-diffs.txt`에 근거와 함께 올린다(C1 측정 때 결정).
- 이용기간: 판정에 이용기간(`service_period`)을 저장한다(`decisions.service_period_json`, 읽기 인터페이스 `store::decision_store::stored_service_period`, Python `app.core_writer.stored_service_period`). **1차 전환 뒤 장부 화면·붙여넣기 묶음·장부 복사·시트 대사는 저장된 이용기간을 읽고, 렌더 시점에 다시 계산하지 않는다.** 이 읽기 전환은 `feat/m3-service-period-in-decision-20261114`가 병합된 뒤 배선한다. 아래 3단계 전에 두 변경이 모두 병합되어 있어야 하며, 병합 전에는 이 항목을 "미충족"으로 보고 전환하지 않는다.

## 입력(시작 조건)

1. U9·U10·U11 병합, 운영 배포가 `core` 빌드(`costcore`)를 포함.
2. C1: 신선 사본 1개에서 실데이터 그림자 B↔C 목록 밖 차이 0. C2: 평가 사례 Rust ≥ Python, Python 정답 중 Rust 오답 0. (운영 담당이 측정, 구현자·검수자는 다시 재지 않는다.)
3. 경로 `D:/WebLedgerHost/data/core.sqlite`가 있고 `costcore` 이관이 최신 버전이다.

## 단계

1. **소유자 승인 지점 ①** — C1·C2 측정 결과와 이 절차를 소유자(정책 수준 결정)가 승인한다. 승인 없이 2단계로 가지 않는다.
2. **C3 신선 백업·복원 확인**: `board.sqlite`와 `core.sqlite`를 신선 백업하고 복원 확인(`SPEC.md:383`). 백업은 `D:/WebLedgerHost/data/backups/`. 복원 확인 전에 진행하지 않는다.
3. **되돌림 예행**(C3): 같은 사본에서 `WEBLEDGER_CLASSIFICATION_WRITER=rust`로 `costcore apply`를 한 번, 변수를 지우고 Python `apply`를 한 번 실행해 둘 다 성공함을 확인한다. 운영 DB에서 하지 않는다.
4. **소유자 승인 지점 ②** — 전환 실행 승인(배포 창과 되돌림 담당 확인).
5. **플래그 전환**: 운영 환경에 `WEBLEDGER_COSTCORE_BIN`·`WEBLEDGER_CORE_DB`·`WEBLEDGER_CLASSIFICATION_WRITER=rust`를 설정하고 서비스를 재시작한다. 같은 레포의 다른 세션에 배포 전후를 알린다. 이 순간부터 Python 자동 분류 쓰기는 꺼진다.
6. **첫 배포 창 대조**: ① A↔C: `transactions` 판정 열과 `core.sqlite` `decisions`가 일치. ② B↔C: `costcore shadow`를 신선 사본에 돌려 목록 밖 차이 0. ③ 작성자 확인: 해당 창의 `change_log` `card.automatic_classification` 기록이 Rust 실행분뿐. ④ `costcore apply` 출력의 `skipped_mismatch` = 0.
7. **차이가 1건이라도 나오면**: 즉시 `WEBLEDGER_CLASSIFICATION_WRITER`를 지우고(또는 `python`) 재시작해 Python으로 되돌린다. Rust가 쓴 행은 지우지 않는다(수동 교정 우선·이력 보존). 원인을 고친 뒤 C1~C3을 다시 잰다. 되돌린 사실과 원인을 `docs/operations.md`에 적는다.
8. 전환 뒤 매일 6단계의 ①②를 돌린다(Python 판정·연결 코드 퇴역 때까지).

## 실패와 복구

- `CLASSIFICATION_PREVIEW_STALE`: 미리보기 이후 데이터가 바뀜. 새 미리보기를 만든다(Python과 같은 동작).
- `CORE_WRITER_NOT_CONFIGURED`·`CORE_SCHEMA_MISMATCH`: 설정·이관 문제. 변수를 지워 Python으로 복귀한 뒤 고친다.
- `CORE_WRITER_IN_TRANSACTION`: 호출 경로가 이미 쓰기 트랜잭션 안에서 `apply`를 부른다. 그 경로는 아직 Rust 작성자로 못 바꾼다. 변수를 지워 복귀하고 호출 경로를 고친다(전환 전 미해결이면 전환 불가).
- 프로세스가 커밋 사이에 죽음(WAL): 같은 입력으로 다시 실행한다.
