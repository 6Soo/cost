# 백엔드 프로세스 정리 (2026-11-09)

로컬 PC가 처리하는 WebLedger 백엔드의 상주 프로세스와 반복 생성 프로세스를 줄인다. 금융·원본·Google 쓰기 경로와 배포 보호 경계는 바꾸지 않는다.

## 조사 결과 (2026-11-09 운영)

- 상주 16개: Board 7(작업 소유자 → 콘솔 숨김 래퍼 → PowerShell 감독자 → venv 실행기+Python, 로컬 입구 실행기+Python), Gateway 2, 보험 명단 동기화 2, 원본 갱신 4(래퍼 → PowerShell → 실행기+Python), cloudflared 1.
- Windows venv의 `Scripts\python.exe`는 기본 인터프리터를 두 번째 프로세스로 띄우는 실행기라 Python 프로세스가 항상 둘씩 생겼다. 자식(`sys.executable`)도 같았다.
- OTA 대사 자식은 한 번에 4~12분(p50 255초) 걸리고, 11/05 이후 실패 62건 중 40건이 실행 중 입력 변경(`SOURCE_CHANGED_DURING_RECONCILIATION`)이었다. 결과를 버린 뒤 1초 만에 다시 시작해 같은 입력 폭주 안에서 반복됐다.
- 원본 갱신 작업은 릴리스가 아니라 개발 작업 폴더 `C:\AX\cost`에서 실행됐고, 2026-11-09 재부팅 뒤 종료 코드 1로 멈춘 채 재시작되지 않았다. 상주 작업들은 각자 다른 릴리스(f7ff4ec4, f05f599d, d96f0880, 35a6263b)에 고정돼 배포가 Board만 바꿨다.
- PC 전체 프로세스 증가의 대부분은 COST가 아니라 Paseo 플러그인(pr-radar의 `gh` 반복 실행, Accounts의 계정별 `codex app-server`)과 에이전트 대기 루프였다. 플러그인 수정은 각 플러그인 저장소에 있다.

## 변경

1. `app/python_launch.py`: venv 실행기 대신 기본 인터프리터를 `__PYVENV_LAUNCHER__`와 함께 시작해 같은 venv를 한 프로세스로 쓴다. Python은 시작 시 이 변수를 지우므로 그 아래 자식에게 전파되지 않는다. OTA 대사·카탈로그 자식이 이것을 쓴다.
2. `webapp/ota_snapshot.py`: 실행 중 입력 변경 첫 번째는 즉시 재시도(기존 계약). 연속 두 번째부터는 입력이 30초(최대 300초까지 배증) 멈춘 뒤 시작한다. 성공하면 초기화되고, 최초 생성은 기다리지 않는다.
3. Board: `start_web_ledger_host.ps1`가 venv 인터프리터에게 기본 인터프리터를 물어 Board·입구를 각각 한 프로세스로 띄운다(호스트 스크립트는 이름 없는 파일을 읽지 않는 계약 유지). 작업 소유자(`webledger_windows_lifecycle.py --log`)가 로그와 콘솔 숨김을 직접 맡아 `windowless_command.pyw` 프로세스가 빠진다. 배포 전환은 새 소유자가 `--log`를 지원할 때만 변환하고, 지원하지 않는 릴리스로 되돌릴 때는 래퍼를 복원한다.
4. `tools/webledger_worker.py` + `WebLedger-Worker` 작업: 보험 명단(60초)·원본 갱신(300초) 감시는 같은 프로세스의 스레드로, 메일 수집·Google 권한 동기화(매시간)는 기존 인터프리터의 자식으로 실행한다. 작업 하나가 죽어도 다른 작업은 계속되고, 감시 작업은 60초부터 최대 15분 간격으로 다시 시작한다. 워커는 kill-on-close Job 안에 있어 중지 시 자식도 함께 끝난다. 단일 인스턴스 mutex를 쓴다. 연속 배포 전환이 워커도 같은 SHA로 옮기고, 실패하면 이전 작업 정의로 되돌린다.
5. Gateway는 표준 라이브러리만 쓰므로 기본 `pythonw.exe` 한 프로세스로 실행한다.

## 유지한 것과 이유

- PowerShell 감독자와 로컬 입구(56069)는 남긴다. 배포 전환이 감독자를 `start_web_ledger_host.ps1` 명령줄로 식별하고, 후보(Prepared) 역할을 `-DisableEntry`로 구분하기 때문이다. 이를 바꾸려면 배포 역할 식별을 다시 설계해야 해서 이번 범위에서 제외했다.
- 기존 네 작업(COST-InsuranceRosterSync, WebLedger-SourceRefresh, WebLedger-MailCollect, WebLedger-GoogleAuthority)은 삭제하지 않고 비활성화한다.

## 적용과 되돌리기 (호스트)

```powershell
# 미리보기: 현재 작업 정의에서 만든 워커 설정과 변경 대상만 출력
powershell -File D:\WebLedgerHost\releases\<SHA>\tools\install_webledger_worker.ps1
# 적용: 작업 XML을 D:\WebLedgerHost\logs\worker-install에 먼저 저장
powershell -File D:\WebLedgerHost\releases\<SHA>\tools\install_webledger_worker.ps1 -Apply
# 되돌리기: 저장한 XML로 다섯 작업을 복원하고 워커 작업을 지움
powershell -File D:\WebLedgerHost\releases\<SHA>\tools\install_webledger_worker.ps1 -Rollback
```

설정 `D:\WebLedgerHost\config\worker.json`은 호스트 파일이다(경로·자격 증명 위치). `release:<경로>` 인수는 워커가 실행 중인 릴리스 안의 파일이다.

## 검증 기준

- 상주: 소유자·PowerShell·Board·입구·cloudflared + Gateway 1 + Worker 1 = 7(이전 16).
- 재시작·배포 후 Board/Gateway/Worker가 같은 경로에서 실행되고 health/ready 200, 보호 API 401, 보호 13표 불변.
- 워커 로그 `D:\WebLedgerHost\logs\webledger-worker.log`에 네 작업의 `start`와 정상 주기가 남는다.
