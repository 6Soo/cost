# 카드 수입 뒤 증분 P2 1층

- 목적: 열린 분기에서 코드가 포괄 항목으로 정한 새 가맹점만 제안·교정하고 반복 결과를 P1 데이터 규칙으로 등록한다. 기준은 [SPEC §6](../SPEC.md), [판정 규칙집](../DECISION_POLICY.md).
- 실행 주체·주기: 구독 Codex `gpt-6.1-sol`과 기존 소유자 인증 API. 카드 가져오기 뒤 하루 1회는 아래 예약 작업 제안의 주기이며 등록 완료를 뜻하지 않는다. 개발 당시 검증은 dry-run까지였고, 이후 첫 실제 실행은 제안 전용으로 모델 1회 성공·제안 4건·반영 0을 기록했다([실행 근거](../history/operations-through-20261113.md#2026-11-13-2200-창--db848712-배포booking-132건증분-p2-첫-실행)). 실제 반영과 예약 등록 여부는 최신 [현재 상태](../session_handoff.md)·[운영 기록](../operations.md)에서 확인한다.
- 개정: 2026-11-12 증분 진입점 추가, 2026-11-13 검사 보강·운영 dry-run, 같은 날 검수 수정(규칙 제외 판정·잠금 자동 복구·규칙 등록 기본 꺼짐). 서버 배포·Worker 변경 없음.

## 입력과 실행

검수된 checkout, 기존 Python 환경, `D:/WebLedgerHost/data/board.sqlite`, 같은 Windows 사용자의 Codex 구독 로그인이 필요하다. 저널 `D:/WebLedgerHost/data/p2-incremental.json`은 실행 전 백업에서 당시 선택 코드로 재현한 585묶음/1,258행과 보존 집계가 일치하여 초기화했다(원제안 파일은 과거 정리 때 삭제됨). 초기화 도구는 기존 파일을 덮지 않는다. 복원 시 기존 저널을 우선 사용하고 원문을 Git에 넣지 않는다.

1. `python -m tools.p2_batch.run_incremental --dry-run`으로 집계한다. `status=success`, `calls=0`, `applied_rows=0`, `registered_rules=0`을 확인한다. 대상0이면 모델·API 호출 없이 종료한다.
2. 헤드가 실제 실행을 승인하면 ego-browser에서 이 작업 전용 TaskSpace 하나를 만들고 같은 공간과 Page를 재사용한다. 소유자 로그인과 `[data-csrf]`가 있는 장부 페이지를 확인한다. 비공개 `D:/WebLedgerHost/data/p2-api.json`에 `{"task_space":공간번호,"page":"p1","origin":"실제 HTTPS 장부 origin"}`을 둔다. 쿠키·암호를 추출하지 않는다. 로그인 만료·공간 제어 상실은 실패로 남기고 인증을 인계한다.
3. 먼저 제안만 필요하면 `python -m tools.p2_batch.run_incremental --propose-only --max-merchants 30 --max-calls 1`. 실제 반영은 `python -m tools.p2_batch.run_incremental --api-config D:/WebLedgerHost/data/p2-api.json --max-merchants 30 --max-calls 1`. 읽기 전용 인증 사전 검사 후 새 묶음 최대30개를 모델 최대1회로 판정한다. 제안 전용 결과가 남아 있으면 모델0회로 먼저 재개한다. **항목 교정과 규칙 등록은 따로 승인한다.** 규칙 등록은 기본 꺼짐이며, 헤드가 등록까지 승인한 실행에서만 끝에 `--register-rules`를 붙인다. 예약 작업 명령에는 이 옵션이 없다.
4. 실행별 대상·호출·성공/실패·반영·등록 수는 비공개 저널의 `runs`에서 확인한다. 미리보기/반영 요청은 최대50행, 열린 분기·항목만이며 `allow_recorded_ai`는 기존 서버 경로에서 적용한다. 수동·금융·원문·revision 충돌은 중단한다. 새 테이블·Google 쓰기·새 장부 기록 없음. 제외 판정은 그 가맹점 이름을 명시한 무조건 규칙이 구체 항목을 정한 경우뿐이다. `*`·패턴·국가/기간 조건 규칙과 포괄 항목을 정한 규칙은 제외 사유가 아니다.

## 자동 실행 연결 제안

별도 Windows 예약 작업(권장): 하루1회, 수입 뒤 새 대상만 처리하며 대상0이면 종료한다. 서버 배포 없이 적용 가능하고 로그인된 Windows 세션·ego·Codex가 필요하다.
Worker 주기 작업에 한 줄 추가: 수입 직후 실행 순서가 정확하지만 서버 변경·배포가 필요하므로 이번에는 제안만 한다.
예약 작업은 최대24시간 지연이 있고, Worker 연결은 코드 결합과 운영 검증 부담이 늘어난다. 이번 결과에는 등록 스크립트만 포함한다.

헤드는 먼저 아래 명령의 `-WhatIf`를 검토한 뒤 같은 명령에서 해당 인자를 빼 등록한다. `$repo`는 검수된 이 PR checkout의 절대 경로, `$pythonExe`는 `Get-Command python`의 실제 실행 경로다. 기존 이름이 있으면 중단하며 Worker 설정은 바꾸지 않는다.

```powershell
& "$repo/tools/p2_batch/register_incremental_task.ps1" -Checkout $repo -Python $pythonExe -ApiConfig D:/WebLedgerHost/data/p2-api.json -At '23:30' -WhatIf
```

## 중단과 복구

한도·혼잡·형식·인증 오류는 실패로 기록하고 다음 실행까지 멈춘다. 같은 명령으로 재개하면 검증된 제안을 재사용하고 저장한 request_id/digest를 재전송해 중복 반영을 막는다. Claude 전환·보호 우회·진행 상태 삭제는 하지 않는다. 잠금 파일에는 작성 PID·시작 시각이 적히며, PID가 죽었거나 2시간을 넘은 잠금은 `STALE_LOCK_RECOVERED` 실패 기록 후 자동 인수한다. 살아 있는 최근 잠금은 거부하므로 담당자가 임의로 지우지 않는다. 원문/수동 교정은 항상 보존하며 변경 전 값은 저널과 서버 변경 이력에 있다. 대량 반영으로 상한을 늘리려면 SPEC §13의 신선 백업·복원 확인을 먼저 수행한다.

검증 근거와 현재 집계는 [현재 상태](../session_handoff.md)의 증분 P2 절을 따른다. 2026-11-13 운영 dry-run 근거(집계만)는 `D:/WebLedgerHost/data/backups/p2-incremental-20261113/dry-run.json`·`dry-run-evidence.json`, 검수 수정 뒤 재실행은 `dry-run-v2.json`·`dry-run-v2-evidence.json`에 있다. 개발 시 합성 테스트와 영향 검사를 수행했고 실제 모델 호출·운영 API 쓰기·예약 등록은 수행하지 않았다.
