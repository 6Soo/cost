# 일괄 기록 배치 owner 확인 표시 정정

- 목적: 카드 기록 배치가 실제 사용자 결정 없이 화면 행에 찍은 `confirmed_by='owner'` 표시를 자동 출처(`automatic`)로 정정한다. 일괄이 아니라 개별로 찍힌 표시와 실제 사용자 결정은 보존한다. 거래·장부·금액·귀속·항목·출처·근거는 바꾸지 않는다.
- 실행 주체: 스크립트(`tools/repair_bulk_owner_confirmation.py`). 승인된 배포 담당이 실행한다.
- 주기: 소유자 결정(2026-11-13)에 따른 1회 정정. 같은 요청 재실행은 변경 없이 `REPLAYED`로 끝난다.
- 개정 이력: 2026-11-13 · 최초 작성 · 일괄 기록 배치 확인 표시 출처 정정(소유자 결정 2026-11-13) 도구 착수. 합성 검증 완료, 운영 반영·사본 예행은 미실행.

구조는 [dist141 자동 판정 출처 정정](dist141-provenance-repair.md)·[AI 분기 검수 교정 반영](ai-review-apply.md)과 같은 미리보기/digest/신선 백업/감사 원복 구조이며 요청·감사 이름공간은 분리한다(`bulk_confirmation_provenance`, `card.bulk_confirmation_provenance_corrected`, `card.bulk_confirmation_provenance_restored`).

## 입력

- `--host-root`(운영 호스트 폴더), `--year`·`--quarter`(정정 범위 분기, **2026년 3분기 이후만 허용**), `--min-batch`(일괄로 볼 최소 행 수, 기본 5), `--request-id`(멱등 키).
- 신선 백업·복원 검증 증거(`tools/verify_operational_backup_restore.py` 산출물, 1시간 이내). 반영 시에만 필요하다.
- Board·SourceRefresh writer 정지 상태(반영 시). Gateway는 유지한다.
- 별도 manifest는 없다. 대상은 아래 판단 기준이 운영 DB에서 직접 선정하며, 보고서에는 식별값·금액 없이 건수만 나온다.

## 판단 기준

범위는 [분기 검수 팩](../../tools/quarter_review/pack.py)과 같다. 카드 화면 행(`row_id`가 `card-<거래 ID>`, 지출 행) 중 거래의 현재 귀속(`display_tab_id`, 없으면 `trip_id`)이 지정 분기인 것 — 여행 탭이면 시작일이 그 분기이고 삭제·보관이 아닌 여행, 또는 탭이 `quarter:<year>:<quarter>`. 이 중 화면 payload의 `confirmed_by`가 `owner`인 행만 후보다.

보존 사유(사유별 건수만 집계, 식별값 없음):

- `MANUAL_OR_USER_EXCEPTION` — 수동 결정 기록(`closed_period.manual_ids`: 항목 또는 유효 여행이 있는 활성 `review_decisions`, `board_manual_overrides`), 거래 `decided_at`, 수동 출처(`user_decision`·`user_exception`·`owner_booking`·`manual`·`manual_hold`·`previous_decision`).
- `NO_STAMP_REVISION` — `board_revisions`에서 `confirmed_by`가 처음 `owner`가 된 revision(직전 payload가 `owner`가 아님; 처음부터 `owner`였던 행의 생성 revision 포함)을 찾지 못함.
- `NOT_RECORD_BATCH` — 그 revision이 기록 배치 형태가 아님(아래 근거).
- `INDIVIDUAL_STAMP` — 같은 "분"(`created_at` 앞 16자, UTC 원문 그대로)에 같은 형태로 `owner`를 찍은 카드 행 수가 **범위와 무관하게 DB 전체에서** `min_batch` 미만. 개별로 찍힌 표시는 실제 확인일 수 있으므로 보존한다.
- `SOURCE_PROTECTED` — 거래에 `duplicate_of`·`conflict_reason`·`parse_error`.
- `REVIEW_HOLD` / `COMPANY_EXCLUDED` — 검수 보류·회사 제외 표에 있는 행.

나머지가 정정 대상이다. 정정은 화면 행 payload의 `confirmed_by`만 `owner`→`automatic`으로 바꾼다. dist141 정정과 같이 확인 시각 등 짝 필드는 쓰지 않는다(카드 화면 payload에는 그런 짝 필드가 없고, dist141도 `confirmed_by`만 기록한다). `board_rows.revision`을 올리고 `board_revisions`에 기존 정리 도구와 같은 열 형태(`change_mode='rule_change'`, `actor='automatic'`, `event_id=''`, `client_request_id=request_id`)로 이력을 남긴다. `change_log`에 변경 전후 `confirmed_by`와 판정 근거(표시를 찍은 revision 번호·분·배치 크기), 변경 전후 전체 상태를 남기고 `requests`에 digest와 요약을 저장한다. 반영 전후 금융 상태(`closed_period_repair._financial_state`) 동일을 검사한다.

### 기록 배치 형태 판별 근거

실제 운영에서 표시를 찍은 revision은 전부 `change_mode='exception'` ∧ `actor='owner'` ∧ `kind='save'` ∧ `event_id` 빈 값 형태였다. 코드 근거:

- 기록 배치의 화면 행 생성은 `webapp/card_flow.py`의 `project()`다. `confirmed_by=('automatic' if entry.get('automatic_record') else 'owner')`로 기록 단계에서만 이 값을 찍고, 같은 트랜잭션에서 revision 1 이력을 `prev_json='{}'`, `event_id=''`, `change_mode='exception'`, `actor='owner'`(자동 기록이면 `automatic`), `kind='save'`(기본값), `client_request_id=row_id`로 넣는다. 배치 커밋은 단일 `utc_now()` 시각을 모든 행에 공유한다(`app/ledger.py`의 commit → `projection(dict(entry, ..., now=now))`). 그래서 일괄 기록은 같은 "분"에 몰린다.
- 사용자가 화면에서 직접 저장하는 경로는 `webapp/ledger_store.py`의 행 저장이다. 카드 행에서 바꿀 수 있는 필드는 `display_tab_id`·`item`·`description`·`operator_note`뿐이다(`webapp/ledger_store_change_validation.py`의 `CARD_EDITABLE`). **`confirmed_by`는 화면 저장으로 찍을 수 없다.** 화면 저장은 바뀐 필드를 `board_manual_overrides`에 남기므로 위 `MANUAL_OR_USER_EXCEPTION` 보존도 함께 걸린다.
- 사건(event) 기반 쓰기 경로는 `event_id`가 비어 있지 않고, 규칙 변경은 `change_mode='rule_change'`·`actor='automatic'`이다. 둘 다 기록 배치 형태와 다르다.

따라서 형태 검사 + 분당 배치 크기 검사는 사용자 직접 저장·사건 재생·규칙 변경과 기록 배치를 구분한다. 형태가 다르거나 같은 분에 찍힌 행이 `min_batch` 미만이면 보존한다.

## 단계

1. **백업 검증.** 신선 백업과 복원 동등을 확인한다. 실패하면 멈춘다(`BACKUP_RESTORE_FAILED`).
2. **미리보기.** 읽기 전용으로 대상·보존 사유·분별 배치·여행별 건수를 집계한다. 쓰기는 없다.
3. **반영.** 미리보기 digest와 백업 증거를 제시해야만 쓴다(`--apply --expected-digest --backup-evidence`). writer 정지 게이트를 통과해야 한다.
4. **재실행 확인.** 같은 요청을 다시 실행해 `REPLAYED`(변경 0)를 확인한다.
5. 필요하면 **원복.** 다시 신선 백업을 만든 뒤 `--restore` 미리보기 digest로 실행한다.

운영 반영은 호출 세션과 분리된 프로세스로 실행하고, writer 중지·운영 전환은 배포 담당 세션이 수행한다. 아래는 2026년 4분기 예시다.

```powershell
$repairEvidence = 'D:/WebLedgerHost/data/backups/bulk-owner-confirm-2026Q4'
New-Item -ItemType Directory -Path $repairEvidence -Force | Out-Null
python tools/verify_operational_backup_restore.py --evidence-out "$repairEvidence/backup-restore.json"
if ($LASTEXITCODE -ne 0) { throw 'BACKUP_RESTORE_FAILED' }
python tools/repair_bulk_owner_confirmation.py --host-root D:/WebLedgerHost --year 2026 --quarter 4 --request-id bulk-owner-confirm-2026Q4 --report "$repairEvidence/preview.json"
if ($LASTEXITCODE -ne 0) { throw 'PREVIEW_FAILED' }
$repairPlan = Get-Content -LiteralPath "$repairEvidence/preview.json" -Encoding UTF8 | ConvertFrom-Json
python tools/repair_bulk_owner_confirmation.py --host-root D:/WebLedgerHost --year 2026 --quarter 4 --request-id bulk-owner-confirm-2026Q4 --apply --expected-digest $repairPlan.digest --backup-evidence "$repairEvidence/backup-restore.json" --report "$repairEvidence/applied.json"
if ($LASTEXITCODE -ne 0) { throw 'APPLY_FAILED' }
python tools/repair_bulk_owner_confirmation.py --host-root D:/WebLedgerHost --year 2026 --quarter 4 --request-id bulk-owner-confirm-2026Q4 --report "$repairEvidence/replay.json"
```

원복은 다시 신선 백업을 만든 후 `--restore` 미리보기의 digest로 실행한다. 반영 뒤 해당 행이 바뀌었으면 원복을 거부한다(`BULK_CONFIRMATION_RESTORE_STALE`·`BULK_CONFIRMATION_RESTORE_FINANCIAL_STALE`). 감사 이력과 revision은 남기고 `confirmed_by`만 `owner`로 되돌린다.

```powershell
python tools/verify_operational_backup_restore.py --evidence-out "$repairEvidence/restore-backup.json"
if ($LASTEXITCODE -ne 0) { throw 'BACKUP_RESTORE_FAILED' }
python tools/repair_bulk_owner_confirmation.py --host-root D:/WebLedgerHost --request-id bulk-owner-confirm-2026Q4 --restore --report "$repairEvidence/restore-preview.json"
$repairRestore = Get-Content -LiteralPath "$repairEvidence/restore-preview.json" -Encoding UTF8 | ConvertFrom-Json
python tools/repair_bulk_owner_confirmation.py --host-root D:/WebLedgerHost --request-id bulk-owner-confirm-2026Q4 --restore --apply --expected-digest $repairRestore.digest --backup-evidence "$repairEvidence/restore-backup.json" --report "$repairEvidence/restored.json"
```

사본은 `--isolated-copy`로만 writer 정지 확인을 생략할 수 있다. 신선 백업·복원 동등·파일 분리 확인은 그대로 필요하며 운영 DB·동일 파일·하드링크는 거부한다.

## 출력

- `--report` 파일과 stdout JSON: `status`(PREVIEW/APPLIED/REPLAYED/FAILED), `digest`, `owner_stamped_rows`(범위 안 `owner` 표시 행 수), `to_correct`(정정 대상 수), `excluded`(사유별 보존 수), `stamp_minutes`(분 문자열·대상 건수·배치 크기), `trip_corrections`(여행 표시 이름과 정정 건수), `applied_this_run`.
- 감사 이력: `change_log`의 `card.bulk_confirmation_provenance_corrected`(변경 전후 `confirmed_by`·전체 상태·표시 revision의 분·배치 크기·금융 지문)·`card.bulk_confirmation_provenance_restored`, 요청 기록 `requests`의 `bulk_confirmation_provenance` 범위.
- 검증 방법: 재실행 `REPLAYED`·변경 0, 반영 전후 금융 지문 동일, 원복 후 변경 전 값 일치(revision·감사 이력은 증가·보존). 정정 뒤 AI 분기 검수 반영(`app/ai_review_repair.py`)이 같은 행을 더 이상 `PROJECTION_ATTRIBUTION_DISAGREEMENT`(화면 수동 확인 표기)로 제외하지 않는다.

## 실패했을 때

- `SCOPE_REQUIRED`·`INVALID_SCOPE`·`INVALID_MIN_BATCH` — 분기 인자가 없거나 2026년 3분기 이전이거나 `min_batch`가 1 미만이다. 인자를 고쳐 다시 미리보기한다. 쓰기는 없었다.
- `PREVIEW_AND_BACKUP_REQUIRED`·`BACKUP_RESTORE_NOT_VERIFIED`·`BACKUP_NOT_FRESH`·`BACKUP_SOURCE_CHANGED`·`WRITERS_NOT_OFFLINE` — 반영 게이트 미충족. 백업을 다시 만들고 writer를 멈춘 뒤 재시도한다. 쓰기는 없었다.
- `BULK_CONFIRMATION_PREVIEW_STALE` — 미리보기 뒤 행·여행·금융 상태가 바뀌었다. 다시 미리보기해 새 digest로 반영한다.
- `BULK_CONFIRMATION_REQUEST_CONFLICT` — 같은 요청 ID로 다른 내용이 이미 반영됐다. 요청 ID를 분리하거나 기존 반영을 확인한다.
- `BULK_CONFIRMATION_RESTORE_STALE`·`BULK_CONFIRMATION_RESTORE_FINANCIAL_STALE` — 반영 뒤 편집·금융 변경이 있어 원복을 거부한다. 이후 변경을 먼저 확인하고 필요하면 수동 교정 절차를 따른다. 강제 원복하지 않는다.
- `BULK_CONFIRMATION_FINANCIAL_CHANGED`·쓰기 중 오류 — 트랜잭션 전체가 롤백된다. 다시 미리보기부터 시작한다.
- 재시도 한도: 같은 실패 코드가 2회 반복되면 멈추고 헤드 담당에게 보고한다.

## 하지 않는 것

- 거래(`transactions`)·장부(`ledger_entries`)·카드 원문·금액·부호·ID·귀속·항목·출처·근거·금융 연결을 바꾸거나 지우지 않는다. 새 장부 행을 만들지 않는다.
- 실제 사용자 결정(수동 출처·`decided_at`·활성 검수 결정·화면 수동 덮어쓰기)과 개별로 찍힌 표시를 덮지 않는다. 보류·제외·중복·원본 충돌 보호를 풀지 않는다.
- Google 최종 장부에 쓰지 않는다. 여행은 Google 시트 탭에서만 생긴다.
- 고객 원문·식별값·금액을 Git·PR·보고서·stdout에 넣지 않는다.
- 운영 포트 8751·8752·8790을 미리보기·테스트에 쓰지 않는다. 시작하지 않은 프로세스를 종료하지 않는다.
- 인증 우회·강제 push·운영 DB 삭제·승인 없는 과금을 하지 않는다. 병합·배포는 헤드 담당만 한다.
