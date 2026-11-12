# 완료 기간 카드 정리

정책은 [PROC-072](../policy/process.md)다. 이 PR은 코드·사본 검증·독립 검수까지만 수행하며 병합·배포·운영 쓰기는 헤드가 한다.

카드 이용일·승인일, 없으면 매입일로 2025년·2026년 1분기 완료 자료를 식별한다. 기존 완료 기간 여행은 불변이다. 열린 여행의 정식 예약 연결·실제 이용기간 또는 실제 수동 교정은 예외로 보존한다. 수동 출처만 있고 실제 이력이 불명확한 경우, 금융 보호·거래/장부/화면 투영 불일치는 보수적으로 보존한다. 정식 환불 짝은 모든 구성원이 이동 자격을 충족할 때만 같은 요청에서 각자의 결제일 분기로 함께 이동한다. 미연결·표시용 추론·초과환불·한쪽 열린 결제·수동 교정·완료 여행·별도 보호는 묶음 전체를 보존한다. 식별·예외·제외 사유·여행별 행 수 변화는 집계만 출력한다. 2025년 목적지는 기존 일반형 `quarter:2025:N`, 항목은 `2025년 항목`이다. 2026년 1분기는 `quarter:2026:1`의 `분기 기타비용`이다.

운영 반영에는 **Board·SourceRefresh writer 정지와 신선 백업/복원 검증이 필요하다.** Gateway는 계속 실행할 수 있으며 휘발성 `config/ledger-gateway-status.json`만 백업 해시에서 제외한다. Gateway 설정 파일은 계속 검증한다. writer 중지는 승인된 배포 담당이 수행하며 아래 명령은 프로세스를 종료하지 않는다. 검증된 릴리스 디렉터리에서 해당 릴리스 Python으로 실행한다.

```powershell
$groupingEvidence = 'D:/WebLedgerHost/data/backups/closed-period-grouping-20261112'
New-Item -ItemType Directory -Path $groupingEvidence -Force | Out-Null
python tools/verify_operational_backup_restore.py --evidence-out "$groupingEvidence/backup-restore.json"
if ($LASTEXITCODE -ne 0) { throw 'BACKUP_RESTORE_FAILED' }
python tools/repair_closed_period_grouping.py --host-root D:/WebLedgerHost --request-id closed-period-grouping-20261112 --report "$groupingEvidence/preview.json"
if ($LASTEXITCODE -ne 0) { throw 'GROUPING_PREVIEW_FAILED' }
$groupingPlan = Get-Content -LiteralPath "$groupingEvidence/preview.json" -Encoding UTF8 | ConvertFrom-Json
python tools/repair_closed_period_grouping.py --host-root D:/WebLedgerHost --request-id closed-period-grouping-20261112 --apply --expected-digest $groupingPlan.digest --backup-evidence "$groupingEvidence/backup-restore.json" --report "$groupingEvidence/applied.json"
if ($LASTEXITCODE -ne 0) { throw 'GROUPING_APPLY_FAILED' }
python tools/repair_closed_period_grouping.py --host-root D:/WebLedgerHost --request-id closed-period-grouping-20261112 --report "$groupingEvidence/replay.json"
```

같은 요청 ID로 반영 후 다시 미리보기를 실행하면 소스를 재계산하지 않는 읽기 전용 `REPLAYED`, `to_move=0`, `applied_this_run=0`이다. 요청 ID를 재사용하면서 다른 digest를 주면 거부한다. 새 진단에는 새 요청 ID를 사용한다. 원본·금액·금융 관계·수동 교정 불변을 확인하고 정식 투영을 다시 게시한 뒤 writer를 복구한다.

원복은 새 백업을 만든 뒤 다음 순서로 실행한다. 이후 사용자 편집이나 다른 변경이 있으면 원복을 거부한다. 환불 연결·순액·상태 및 환불/검토 보호/회사 경비 제외 표 전체를 digest에 묶으므로, 무관한 거래의 금융 보호 변경도 보수적으로 원복을 거부할 수 있다. 원복은 변경 전 귀속·항목·투영을 복원하고 revision·감사 이력을 보존한다.

```powershell
python tools/verify_operational_backup_restore.py --evidence-out "$groupingEvidence/restore-backup.json"
if ($LASTEXITCODE -ne 0) { throw 'BACKUP_RESTORE_FAILED' }
python tools/repair_closed_period_grouping.py --host-root D:/WebLedgerHost --request-id closed-period-grouping-20261112 --restore --report "$groupingEvidence/restore-preview.json"
$groupingRestore = Get-Content -LiteralPath "$groupingEvidence/restore-preview.json" -Encoding UTF8 | ConvertFrom-Json
python tools/repair_closed_period_grouping.py --host-root D:/WebLedgerHost --request-id closed-period-grouping-20261112 --restore --apply --expected-digest $groupingRestore.digest --backup-evidence "$groupingEvidence/restore-backup.json" --report "$groupingEvidence/restored.json"
```

사본에서만 반영할 때는 `--isolated-copy`를 사용할 수 있다. 동일한 신선 백업/복원·DB 상태 게이트를 통과하고 운영 파일과 다른 실제 파일임을 확인한 경우에만 writer 정지 검사를 생략한다. 운영 DB 경로·같은 파일·하드링크에는 이 옵션을 사용할 수 없다.
