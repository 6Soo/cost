# OTA 근거 기존 중복 압축

- 목적: `ota-evidence.sqlite`에 #905 이전부터 쌓인 메일 근거 중복(같은 예약·메일·사실이 판마다 새 행)을 지워 파일을 줄인다. 읽기 결과는 바이트 단위로 같아야 한다.
- 실행 주체: 운영 담당 세션(한 세션), 배포 창에서. 도구는 `tools/compact_ota_evidence.py`.
- 주기: 1회. 이후 #905 작성자가 중복을 만들지 않는다.
- 개정 이력: 2026-11-15 · 신설 (A-2) · 도구와 사본 예행까지만 있고 운영 반영은 이 절차로.

## 도구가 하는 일

- `ota_booking_evidence`(메일 근거)는 (예약 키, entry_key, 사실 내용) 같은 그룹에서 rowid가 가장 작은 행만 남기고 지운다. `ota_reservation_observations`는 같은 원천 안에서 같은 기준을 쓴다. 직접·포털 근거와 그 밖의 표는 건드리지 않는다.
- 지워지는 행의 관측(판 범위·관측 시각·횟수)은 `ota_row_seen`의 남는 행으로 합쳐진다. 그 결과 "현재 판에서 관측된 행" 판정이 그대로다. 관측이 기록되지 않은 옛 행은 자기 판 관측 1회를 새로 기록하므로 `seen_count` 합은 `seen_rows_synthesized`만큼 늘고 그 밖에는 보존된다.
- `ota_raw_blobs`·`ota_messages`·`ota_raw_entries`·판·원천은 절대 쓰지 않는다.
- `--apply`는 한 트랜잭션(`BEGIN IMMEDIATE`)이다. 안에서 압축 전후의 `direct_facts`·`catalog_rows`·`build_ota_payment_events`·core_bridge `links`(kind=ota) 출력 해시와 고유 사실 수, `seen_count` 합 보존, 재계획 시 삭제 0을 대조하고 하나라도 다르면 롤백한다(`EQUIVALENCE_MISMATCH` 등). 쓰기 잠금을 못 잡으면 `WRITE_LOCK_NOT_ACQUIRED`로 끝난다(쓰기 0).
- 출력은 건수와 해시 앞자리뿐이다. 고객 원문·ID는 나오지 않는다.

## 순서 (PowerShell, 레포 릴리스 폴더에서)

1. **신선 범위 백업**: #906 도구로 `ota-evidence.sqlite`를 포함한 범위 백업과 복원 확인 증거를 만든다(1시간 이내여야 한다). 증거 파일 경로를 `$ev`에 둔다. 디스크 여유는 파일 크기의 약 2배(WAL과 VACUUM 임시 사본).
2. **window-guard**: 배포 창 가드로 Worker `mail-collect`(매시)와 `ota-evidence.sqlite`에 쓰는 모든 작업을 정지한다. 내가 시작하지 않은 프로세스를 종료하지 않는다. 같은 레포의 다른 세션에 알린다.
3. **예행**(쓰기 0): `python -I tools/compact_ota_evidence.py --db D:/WebLedgerHost/data/ota-evidence.sqlite --dry-run`. `rows_to_delete`, `distinct_facts`, `estimated_bytes_saved`를 확인한다.
4. **적용**: `python -I tools/compact_ota_evidence.py --db D:/WebLedgerHost/data/ota-evidence.sqlite --apply --backup-evidence $ev`. 백업 증거가 없거나 오래됐거나 `ota-evidence.sqlite`를 덮지 않으면 거부한다. 성공 출력에 `equivalence` = `equal`이 있어야 한다.
5. **VACUUM**(파일 크기 축소): `... --vacuum --backup-evidence $ev`(적용과 함께 `--apply --vacuum`도 된다). 시간은 사본 예행 수치로 창 길이를 잡는다. 실행 중 파일이 가득 쓰이므로 다른 쓰기는 모두 멈춘 상태여야 한다.
6. **대조**: `PRAGMA integrity_check`가 `ok`. 같은 명령을 `--dry-run`으로 다시 돌려 `rows_to_delete` = 0. 운영 OTA 재계산·장부 화면의 OTA 연결 수가 적용 전과 같은지 본다.
7. **재개**: window-guard를 풀고 Worker `mail-collect`를 다시 켠다. 다음 정시 수집이 새 행을 만들지 않는지(`ota_booking_evidence` 건수 불변) 확인한다.

## 실패와 되돌림

- 도구가 실패하면 롤백되어 DB는 적용 전 상태다. 코드와 이유를 보고 원인을 고친 뒤 같은 명령을 다시 실행해도 된다(멱등).
- 적용이 커밋된 뒤 문제를 발견하면 1단계의 백업에서 `ota-evidence.sqlite`를 복원한다. 원문 표는 쓰지 않으므로 필요하면 원문에서 재색인(`tools/reindex_reservation_observations.py`)도 가능하다.
- 프로세스가 도중에 죽으면 미커밋 트랜잭션은 SQLite가 버린다. VACUUM 도중 죽으면 원본 파일이 그대로 남는다.
