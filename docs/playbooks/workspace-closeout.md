# Paseo 작업공간 종료·정리 절차

- 목적: 완료·중단된 작업자의 에이전트와 worktree를 결과 보존 후 안전하게 archive해, 완료 표시만 남고 작업공간이 누적되는 일을 막는다.
- 실행 주체: 통합 감독. 작업자는 자신의 결과·커밋·미추적 파일을 보고하지만 다른 작업자의 workspace를 archive하지 않는다.
- 적용 범위: COST 저장소의 Paseo worktree와 해당 작업에 속한 preview·브라우저·도구 프로세스. 운영 서비스와 사용자가 만든 local workspace에는 적용하지 않는다.
- 개정 이력: 2026-11-16 · 완료 후 workspace가 남은 원인을 반영해 최초 작성.

## 종료 상태

작업자는 `DONE`을 보고할 수 있어도 workspace는 다음 세 상태 중 하나를 감독자가 확인할 때까지 열린 상태다.

| 상태 | 뜻 | 다음 행동 |
| --- | --- | --- |
| `ACTIVE` | 에이전트·preview·브라우저 또는 통합 검수가 사용 중 | 유지 |
| `DIRTY_PENDING_REVIEW` | 미커밋·미추적 파일·미통합 커밋이 있음 | 보존·대조 후 통합 또는 archive 보류 |
| `READY_TO_ARCHIVE` | 결과 보존, 통합, 프로세스·브라우저 소유권 확인 완료 | `archive_agent` 후 `archive_workspace` |

## 단계

1. 배정 시 manifest에 `agentId`, `workspaceId`, cwd, 브랜치, 소유 파일, 통합 대상, 표적 검사, 종료 상태를 기록한다. 서로 다른 작성자가 같은 파일을 소유하지 않게 한다.
2. 완료·오류·idle 알림을 받으면 `list_agents`와 `list_workspaces(includeBackground=true)`로 실제 상태를 다시 읽는다. 완료 알림만으로 archive하지 않는다.
3. worktree에서 다음을 확인한다.
   - `git status --short --branch`, `git log -1 --oneline`, 통합 브랜치와의 diff
   - 미추적 파일·체크포인트·stash·사용자 파일의 보존 여부
   - 작업자가 시작한 preview·테스트 서버·도구 프로세스와 브라우저 TaskSpace 소유권
4. 미커밋·미추적·미통합 결과가 있으면 `DIRTY_PENDING_REVIEW`로 남긴다. 필요한 경우 합성 자료와 체크포인트를 `.local-archive/<작업 ID>/`에 복사하고 SHA-256을 기록한다. 삭제·강제 reset·강제 push는 하지 않는다.
5. 통합 커밋과 표적 검사, 영향 기반 검사를 감독자가 직접 확인한다. 실패·0건·skip은 완료로 기록하지 않는다. UI는 지정된 모바일·데스크톱 검수 증거를 보존한다.
6. 작업자가 시작한 프로세스와 브라우저만 종료한다. 사용자가 제어 중인 TaskSpace나 다른 세션이 시작한 프로세스는 종료하지 않고 `EXTERNAL_OWNER`로 기록한다.
7. 결과가 보존되고 통합되었으며 외부 소유 자원이 없으면 상태를 `READY_TO_ARCHIVE`로 바꾼다. 먼저 `archive_agent`, 이어서 같은 `workspaceId`에 `archive_workspace`를 호출한다.
8. archive 뒤 `list_workspaces`와 파일시스템을 다시 확인한다. 남은 workspace·worktree·프로세스 ID를 종료 보고와 `docs/session_handoff.md`에 기록한다.

## 실패했을 때

- 미추적 또는 수정 파일이 있으면 archive하지 말고 `DIRTY_PENDING_REVIEW`로 둔다.
- 미통합 커밋이 있으면 통합 감독에게 전달하고, 통합 결과가 확인될 때까지 workspace를 보존한다.
- preview·브라우저가 사용자 또는 다른 세션 소유면 해당 소유자의 종료 신호를 기다린다.
- archive API가 실패하면 같은 workspace에 대한 반복 삭제를 하지 말고 오류와 다음 재개 명령을 체크포인트에 남긴다.
- 24시간 이상 `DONE`·`idle`인데 종료 상태가 없는 workspace는 감독자에게 알림을 만들되, dirty workspace를 자동 삭제하지 않는다.

## 출력·감사

작업별 체크포인트에 다음을 남긴다.

- 최종 통합 SHA와 표적·영향 검사 결과
- 보존한 bundle·체크포인트·미추적 파일의 경로와 해시
- archive한 agent/workspace ID와 시각
- 남은 외부 소유 자원과 정확한 정리 주체

완료 보고는 `READY_TO_ARCHIVE` 또는 `DIRTY_PENDING_REVIEW` 중 하나를 명시해야 하며, 단순히 에이전트가 완료됐다는 이유로 workspace 정리를 생략하지 않는다.

## 하지 않는 것

- 사용자가 시작하지 않은 프로세스·브라우저·workspace를 강제 종료하지 않는다.
- 고객 원문·비밀·운영 DB를 archive bundle이나 보고서에 복사하지 않는다.
- 미통합 작업을 완료로 표시하거나, 미추적 파일을 삭제해 clean 상태를 만들지 않는다.
