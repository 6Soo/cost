# M5 일일 역방향 백업 상태 해석

`tools/m5_backup.py`의 `pull_snapshot`이 남기는 상태를 운영자가 어떻게 읽고 대응하는지 요약한다. 전체 안내와 예행 근거는 작업 폴더 안에만 둔다(Git 제외).

- 전체 안내(예행 근거와 함께): `.local-archive/m5-backup-rehearsal-20261118/M5-BACKUP-OPERATIONS.md`
- 예행 증거: 같은 폴더의 `RESULT.md`, `run/*.json`

## 핵심 규칙

- `complete=true`일 때만 "그날까지 누락 없이 누적"이라 말한다. `last_success_at_utc` 하나로 정상을 결론내지 않는다.
- `gap_days`는 이번 실행 직전 빈 구간, `missed_days_total`은 아직 남은 모든 구간의 합. 다음 성공이 `gap_days`를 0으로 되돌려도 `missed_days_total`은 남는다.
- `state_reset_count`는 상태 파일이 무효였던 횟수이며 **9에서 멈춘다**. 정상화 뒤에도 줄지 않으므로 `complete`는 계속 false다. 9에 닿으면 새 실패 구분은 카운터로 안 되므로 NTP·상태 이력을 직접 확인한다.
- `state_reset_reason`: `corrupt`·`unreadable`·`rejected`(#1001 통계와 같은 어휘).

## 대응 요약

| 관찰 | 할 일 |
| --- | --- |
| `GENERATION_DATE_INVALID` | 잘못된 세대 디렉터리 이름을 찾아 **이름만 격리**(`Rename-Item`), 삭제 금지, 재실행 |
| `rejected` 반복 | ① 노드·서버 UTC 차이(허용 5분) ② `last_success_at_utc`가 미래인지 ③ `reset-counter.json` |
| `PULL_FAILED` 등 | 상태는 갱신되지 않으므로 원인 확인 후 재실행. 기존 세대는 보존된다 |

## 미검증

실제 클라우드 스냅숏·실제 PC 꺼짐·운영 원문 복원은 제공자 결정 전이라 실행하지 않았다.
