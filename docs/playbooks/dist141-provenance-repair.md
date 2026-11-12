# dist141 자동 판정 출처 정정

정책은 [PROC-014](../policy/process.md)와 [LINK-108](../policy/link.md)이다. 이 절차는 운영 반영 승인을 대신하지 않는다. 현재 PR은 검수까지만 수행한다.

`tools/repair_dist141_provenance.py`는 기존 requests·review_decisions로 식별한 원결정 revision만 정정한다. 이후 결정·수동 override·원본 충돌은 보존한다. 이미 자동 출처인 행도 일치하는 원결정 이력의 잘못된 수동 보호를 해제하며 현재 자동 출처를 유지한다. 열린 분기는 기존 P1 재판정, 닫힌 분기는 귀속·항목 유지와 감사 기록의 `CLOSED_QUARTER_REVIEW_REQUIRED` 표시다. 원결정 이력은 수정·삭제하지 않는다.

다음은 배포 후 헤드가 사용할 정확한 PowerShell 명령이다. 먼저 정식 snapshot을 갱신하여 LINK-108이 포함된 새 근거 게시를 확인한다. 미리보기는 읽기 전용 운영 연결을 메모리에 복제하여 계산하고 집계만 출력한다. 운영 쓰기는 기존 오프라인 백업·복원 검증 게이트를 통과해야 한다. 신선 백업/복원 증거의 위치를 아래 `backup-restore.json`으로 정하고 기존 [백업 복원 도구](../../tools/verify_operational_backup_restore.py)로 생성한다. writer 중지·운영 전환은 배포 담당 세션이 수행한다.

```powershell
python tools/repair_dist141_provenance.py --host-root D:/WebLedgerHost --request-id dist141-provenance-20261112 --report D:/WebLedgerHost/data/backups/ota-portal-20261112-collection-private/forest-portal/link108-provenance/preview.json
$repairPlan = Get-Content -LiteralPath D:/WebLedgerHost/data/backups/ota-portal-20261112-collection-private/forest-portal/link108-provenance/preview.json -Encoding UTF8 | ConvertFrom-Json
python tools/repair_dist141_provenance.py --host-root D:/WebLedgerHost --request-id dist141-provenance-20261112 --apply --expected-digest $repairPlan.digest --backup-evidence D:/WebLedgerHost/data/backups/ota-portal-20261112-collection-private/forest-portal/link108-provenance/backup-restore.json --report D:/WebLedgerHost/data/backups/ota-portal-20261112-collection-private/forest-portal/link108-provenance/apply.json
```

재판정은 같은 원자적 `--apply` 안에서 대상 열린 분기 행에만 수행하므로 전체 재판정 명령을 추가 실행하지 않는다. 미리보기 이후 입력·revision·여행·근거가 바뀌면 새 미리보기가 필요하다. 전체 요청 ID는 멱등 키이며 같은 요청의 재실행은 변경하지 않는다. 실행 전후 원문·금액·금융 연결과 실제 수동 교정을 비교하고, 이후 담당이 정식 snapshot 재계산 및 기존 동일 화면 기준 경고 수를 측정한다.

원복은 같은 요청의 감사 기록에 저장한 변경 전 값과 현재 변경 후 값을 대조한다. 이후 편집이 있으면 일괄 원복을 거부한다. 원복도 신선 백업·복원 검증과 운영 반영 권한이 필요하다. revision과 감사 이력은 되돌려 지우지 않고 증가시킨다.

```powershell
python tools/repair_dist141_provenance.py --host-root D:/WebLedgerHost --request-id dist141-provenance-20261112 --restore --report D:/WebLedgerHost/data/backups/ota-portal-20261112-collection-private/forest-portal/link108-provenance/restore-preview.json
$restorePlan = Get-Content -LiteralPath D:/WebLedgerHost/data/backups/ota-portal-20261112-collection-private/forest-portal/link108-provenance/restore-preview.json -Encoding UTF8 | ConvertFrom-Json
python tools/repair_dist141_provenance.py --host-root D:/WebLedgerHost --request-id dist141-provenance-20261112 --restore --apply --expected-digest $restorePlan.digest --backup-evidence D:/WebLedgerHost/data/backups/ota-portal-20261112-collection-private/forest-portal/link108-provenance/backup-restore.json
```
