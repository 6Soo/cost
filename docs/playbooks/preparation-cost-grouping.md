# 일반 준비기간 추론 귀속 정리

정책은 [TRIP-043](../policy/trip.md)·[DATE-040](../policy/date.md)와 [PROC-004](../policy/process.md)다. 일반 fallback만 제거한다. 준비 숙박 특례(TRIP-042·DATE-039), 명시된 사용자 예외, 예약 이용기간, 수동 교정, 환불의 원결제 따르기는 유지한다. 이 작업의 병합·배포·운영 반영은 헤드 담당이다.

대상은 0630 포함 열린 여행에 붙은 코드 추론 출처(`inference`·`code_inference`·`auto_inferred`) 행 중 `다음 여행 준비기간 · ` 근거가 명확한 경우다. 근거 불명확·수동 이력·여행 귀속/예약을 지정하는 활성 규칙·예약 근거(충돌/복수 후보 포함)·이용일을 포함하는 여행·닫힌 카드 기간·금융 보호·거래/장부/화면 투영 불일치는 사유별로 보존한다. 범위 밖 행과 카드 원문·금액·부호·ID·금융 표는 불변이다. 정식 환불 묶음은 모든 구성원이 동일 자격을 충족할 때만 원결제의 결제일 분기로 함께 이동한다.

`repair_closed_period_grouping.py`와 같은 미리보기/digest/신선 백업/감사 원복 구조를 사용하고 요청·감사 이름공간은 분리한다. 미리보기는 읽기만 한다. 반영 후 같은 요청은 소스를 다시 계산하지 않는 `REPLAYED`, 이동0·실행변경0이다. 기존 장부·화면 행만 동기화하고 새 행·Google 쓰기를 만들지 않는다.

운영에서 Board·SourceRefresh writer를 멈추는 반영은 호출 세션과 분리된 프로세스로 실행하고 `finally`에서 Board 시작·route resume·Worker 시작을 수행한다. Gateway는 유지한다. 승인된 배포 담당이 신선 백업·복원 검증 후 검증된 릴리스의 Python으로 실행한다.

```powershell
$prepEvidence = 'D:/WebLedgerHost/data/backups/no-preparation-cost-20261112'
New-Item -ItemType Directory -Path $prepEvidence -Force | Out-Null
python tools/verify_operational_backup_restore.py --evidence-out "$prepEvidence/backup-restore.json"
if ($LASTEXITCODE -ne 0) { throw 'BACKUP_RESTORE_FAILED' }
python tools/repair_preparation_cost_grouping.py --host-root D:/WebLedgerHost --request-id no-preparation-cost-20261112 --report "$prepEvidence/preview.json"
if ($LASTEXITCODE -ne 0) { throw 'PREVIEW_FAILED' }
$prepPlan = Get-Content -LiteralPath "$prepEvidence/preview.json" -Encoding UTF8 | ConvertFrom-Json
python tools/repair_preparation_cost_grouping.py --host-root D:/WebLedgerHost --request-id no-preparation-cost-20261112 --apply --expected-digest $prepPlan.digest --backup-evidence "$prepEvidence/backup-restore.json" --report "$prepEvidence/applied.json"
if ($LASTEXITCODE -ne 0) { throw 'APPLY_FAILED' }
python tools/repair_preparation_cost_grouping.py --host-root D:/WebLedgerHost --request-id no-preparation-cost-20261112 --report "$prepEvidence/replay.json"
```

원복은 다시 신선 백업을 만든 후 `--restore` 미리보기의 digest로 실행한다. 이후 사용자 편집·금융 보호 변경·다른 수정이 있으면 원복을 거부한다. 감사 이력과 revision은 남기고 귀속·항목·근거·투영은 변경 전으로 복원한다.

```powershell
python tools/verify_operational_backup_restore.py --evidence-out "$prepEvidence/restore-backup.json"
if ($LASTEXITCODE -ne 0) { throw 'BACKUP_RESTORE_FAILED' }
python tools/repair_preparation_cost_grouping.py --host-root D:/WebLedgerHost --request-id no-preparation-cost-20261112 --restore --report "$prepEvidence/restore-preview.json"
$prepRestore = Get-Content -LiteralPath "$prepEvidence/restore-preview.json" -Encoding UTF8 | ConvertFrom-Json
python tools/repair_preparation_cost_grouping.py --host-root D:/WebLedgerHost --request-id no-preparation-cost-20261112 --restore --apply --expected-digest $prepRestore.digest --backup-evidence "$prepEvidence/restore-backup.json" --report "$prepEvidence/restored.json"
```

사본은 `--isolated-copy`로만 writer 정지 확인을 생략할 수 있다. 신선 백업·복원 동등·파일 분리 확인은 그대로 필요하며 운영 DB·동일 파일·하드링크는 거부한다. 사본 예행의 집계와 금액을 제외한 영향 순위는 후속 검증 기록을 따른다.
