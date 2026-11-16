# 절차서

> 반복되는 작업을 **누가 해도 같은 결과가 나오게** 적어 두는 곳이다. 근거는 [통합 명세](../SPEC.md) §7(수집 스크립트), §11.4(P2 모델 교체).

## 왜 두는가

절차서는 반복 작업이 내려가는 길의 중간 단계다.

```
프론티어 모델이 직접 수행 → 절차서 → 스크립트(가능하면) 또는 무료 모델
```

- 절차가 고정되면 스크립트로 만든다. 스크립트가 된 작업의 절차서는 "스크립트가 깨졌을 때 고치는 법"으로 남긴다.
- 스크립트로 만들 수 없지만 판단이 단순한 작업만 무료 모델에 넘긴다.

## 현재 절차서

아래는 절차와 검증 범위 안내다. 최신 병합·배포·실행 상태는 [현재 상태](../session_handoff.md)와 [운영 기록](../operations.md)을 따른다.

| 작업 | 문서 | 상태 |
| --- | --- | --- |
| 카드 원본 수집 | [카드 원본 수집 안내](card-downloads.md)·[국민 수집기](kb-script-usage.md) | 국민·하나·IBK 수집기 구현·합성 검증. 실제 화면·선택자·다운로드 검증과 구분 |
| 카드사 3곳 로그인 자동화 | [카드 로그인 자동화](card-login-automation.md) | 모듈 착수·합성 검증. 라이브 검증은 사용자 자격 증명 등록 후 |
| OTA 포털 3곳 조회 | [직접 조회](ota-portal-collection.md)·[수집 스크립트](ota-script-usage.md) | 읽기 전용 수집. 자료 가져오기·운영 반영은 별도 절차 |
| 분기 검수 | [분기 검수](quarter-review.md) | AI 검수자(Fable 5.2 high) 수행. 사용자는 결과 확인·Google 붙여넣기만 |
| 코어 1차 전환(P1 작성자 Python→Rust) | [코어 1차 전환](core-cutover.md) | 운영 사본 C1·C2 재측정 통과. Python 유지, 재전환 승인 ① 대기 |
| OTA 근거 기존 중복 압축 | [OTA 근거 압축](ota-evidence-compaction.md) | 도구·사본 예행까지. 운영 반영은 운영 담당이 배포 창에서 |
| 영수증 사진 판독 | [영수증 사진 판독](receipt-reading.md) | Claude opus medium 및 Windows OCR→로컬 Paseo Qwen4 경로. #966의 Qwen4 경로는 병합·합성 검증까지이며 운영 배포 전 |
| Paseo 작업공간 종료·정리 | [작업공간 종료·정리](workspace-closeout.md) | 완료 알림·결과 보존·통합 검수 뒤 agent/workspace archive와 잔여 자원 재확인 |

새 절차서는 이 폴더에 `<작업이름>.md`로 만든다. 검증한 범위와 운영 실행 여부를 각 문서에 구분해 적는다.

## 절차서 한 건의 형식

```markdown
# <작업 이름>

- 목적: 이 작업이 끝나면 무엇이 생기는가
- 실행 주체: 스크립트 / 무료 모델 / 프론티어 모델
- 주기: 언제 도는가
- 개정 이력: 날짜 · 바꾼 것 · 이유

## 입력
필요한 자료, 로그인 상태, 시작 조건.

## 단계
1. 번호 매긴 단계. 단계마다 "무엇을 보고 성공으로 판단하는지"를 적는다.

## 판단 기준
갈림길마다 어떤 경우에 어느 쪽인지. 예시를 붙인다.

## 출력
파일 이름·위치·형식, 검증 방법(건수 대조, 해시 등).

## 실패했을 때
증상별로 멈출지, 다시 할지, 누구에게 넘길지. 재시도 한도.

## 하지 않는 것
이 작업에서 금지된 행동(로그인 우회, 쓰기 동작, 원문 출력 등).
```

## 쓰는 규칙

- 실제로 수행해 성공한 절차만 적는다. 해 보지 않은 단계를 추측으로 채우지 않는다.
- 고객 원문, 암호, 인증번호, 예약번호 같은 식별값을 적지 않는다.
- 사람이 해야 하는 단계(로그인, 인증번호 입력)는 숨기지 않고 "사람이 하는 단계"로 표시한다.
- 화면이나 내부 API가 바뀌어 절차가 깨지면 프론티어 모델이 고치고 개정 이력에 남긴다.

## 반영 창의 백업·복원 확인 범위

`python tools/verify_operational_backup_restore.py --scope board`(또는 `--scope board.sqlite core.sqlite`)는 이번 반영이 쓰는 DB만 전 행 직렬화·백업·복원 확인하고, 나머지 DB와 `source`·`evidence`·`exports` 폴더는 전후 지문(DB는 파일·WAL 해시, 폴더는 경로·크기·mtime)이 같은지만 확인한다. 바뀌면 `OUT_OF_SCOPE_INPUT_CHANGED_DURING_BACKUP`으로 실패한다. `--scope`를 주지 않으면 기존대로 전체다. 범위에는 판정 DB(`board.sqlite`)가 들어 있어야 한다. `data/core.sqlite`가 있으면 범위에 반드시 넣어야 하고(없으면 `BACKUP_SCOPE_MISSING_CORE_DB`), 전체 모드도 `core.sqlite`와 `period-facts.json`을 백업한다. 범위 증거는 `all_database_tables_and_columns_compared`·`source_files_hash_compared`가 False, `backup_scope_kind`가 `scoped`이고 `backup_scope`에 검증한 DB가 적힌다. `complete_card_classification`·`repair_bulk_owner_confirmation`의 백업 게이트는 쓰는 DB가 `backup_scope`에 있고 범위 밖이 불변이면 범위 증거도 받는다(`deploy_reserve_candidate`·`apply_ota_owner_answers`·`deploy_reserve_trips`는 전체 증거만 받는다). `backup_scope`가 없는 이전 형식 증거는 호스트에 `data/core.sqlite`가 있으면 core를 포함하지 않으므로 거부한다(새 형식 전체 증거 필요).

| 도구 | 쓰는 DB | 권장 범위 |
| --- | --- | --- |
| `apply_ai_quarter_review.py`, `repair_closed_period_grouping.py`, `repair_preparation_cost_grouping.py`, `repair_bulk_owner_confirmation.py` | `board.sqlite` | `--scope board` |
| `prepare_ota_review_holds.py`, `recover_history_rules.py`, `import_kb_card_download.py`, `refresh_card_categories.py` | `board.sqlite` | `--scope board` |
| `apply_ota_owner_answers.py`, `deploy_reserve_trips.py` | `board.sqlite` + `data/evidence` 폴더 | 전체(범위 지정 없음) |
| `complete_card_classification.py` | python 작성자: `board.sqlite` / rust 작성자(`WEBLEDGER_CLASSIFICATION_WRITER=rust`): `board.sqlite` + `core.sqlite` + `period-facts.json` | python: `--scope board` / rust: `--scope board.sqlite core.sqlite` |
| `repair_dist141_provenance.py` | `board.sqlite` (`ota-review.sqlite`는 읽기만) | `--scope board` |
| `deploy_lightweight.py` | `board.sqlite`, `board.operator.sqlite`, `real-review.sqlite` | 범위 지정 없음(전체) |

`apply_ota_owner_answers.py`·`deploy_reserve_trips.py`는 DB 밖에서 `data/evidence`에도 쓸 수 있으므로 범위 모드의 폴더 지문 비교에서 바뀌면 실패한다. 위 표대로 이 두 도구 창은 전체 모드를 쓰며, 두 도구의 백업 게이트도 범위 증거(`backup_scope_kind`가 `scoped`)를 거부하고 전체 증거만 받는다.

창당 백업 1회로 줄이는 것은, 그 한 번의 변경 전 백업이 창 전체 반영 범위를 덮고 중간 실패 복구까지 검증될 때만 허용한다. 코드는 바꾸지 않았고 도구별 백업 게이트(1시간 이내 증거)는 그대로 둔다.
