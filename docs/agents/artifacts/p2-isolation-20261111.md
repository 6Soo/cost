# D1 — Windows P2 격리 실측 (2026-11-11)

## 후속 결정 — 현재 실행 기준

2026-11-11 Fable은 아래 조사 결과를 근거로 **도구 없는 어댑터**를 승인했다. 샌드박스 복구는 선행 작업에서 제외한다. Worker가 사건·관련 원문·규칙·스키마를 프롬프트/stdin으로 넣고, 빈 임시 cwd의 직접 `codex exec --sandbox read-only`·승인 `never`·스키마 JSON 호출을 기본으로 쓴다. Paseo·Claude는 같은 도구 비허용 조건의 완료가 검증된 경우에만 사용한다. 검증된 대체가 없으면 한도 해제까지 대기한다.

안전 근거는 **도구 실행 불가와 코드의 스키마·후보·신선도·금융 보호 검증**이다. 아래 실측을 OS 격리 성공으로 바꿔 해석하지 않는다. 프롬프트 상한·근거 절단 표시·허용된 추가 조회 최대 2회·실제 예약 Worker 합성 검증을 D2~D5에서 구현·확인한다. 현재 이 보고서만 통합하며 `tools/probe_p2_isolation.py`는 통합하지 않는다. D5 합성 검증과 첫 약 50건 결과는 아직 미완료다. 정본은 [SPEC §6](../../SPEC.md#6-서버-밖-p2-일괄-판정)이다.

이하의 BLOCKED와 권고는 **위 결정 전 조사 당시의 판정**이며 원래 측정 근거를 보존한다.

## 범위와 재개 대조

- 원요청: 중간 관리자 `4facbe77-dee0-4fd5-a64e-579343160d00` 로그의 D.1 및 D1 전달 메시지. 합성 사건 폴더에서 Paseo `codex/gpt-6.1-sol`, `claude/opus`, 직접 `codex exec --sandbox read-only`의 외부 읽기·쓰기·loopback 및 schema/JSON/timeout 종료 확인.
- 인계 `85d364c03652a5b6223ea5fc0196686f3581fd4534708711641b11762f84c54a`를 실제 파일과 대조했다. 이전 세션은 probe 초안 작성 뒤 사용량 제한으로 중단. 저장된 실측 결과와 보고서는 없었다. 이전의 시작 오류 설명은 이번 실행에서 재확인한다.
- 소유 파일은 이 보고서와 `tools/probe_p2_isolation.py`뿐. 운영·실고객·비밀·운영 포트·설치·과금·배포·SPEC 수정·업무 위임은 범위 밖이다.
- `stdin=DEVNULL` 및 숨김 자식 프로세스는 비대화형 CLI 측정이다. 실제 Task Scheduler 배치 로그온 토큰과 동일하다고 주장하지 않는다.

## 결론과 요구사항별 상태

**조사 실행은 끝냈으나 격리 수락은 BLOCKED다. 현재 측정으로 고객 원문을 실행할 기본 경로를 선정할 수 없다.** 바깥 읽기가 성공했다고 실측한 모델 경로도, OS가 바깥 읽기·쓰기·네트워크를 모두 차단했다고 실측한 모델 경로도 없다. 시작 실패와 권한 대기는 격리 성공이 아니다. 첫 50건 등 고객 원문 실행은 진행하지 않는다.

| 요구사항 | 상태 | 실제 근거 |
| --- | --- | --- |
| 세 지정 경로의 합성 호출 | COMPLETE | 각 1회 실행. 아래 명령·종료 코드·시간·반환 형식 기록 |
| 바깥 읽기·쓰기·loopback 강제 차단 검증 | BLOCKED | 지정 모델 경로에서 probe 본문이 실행되지 않음. OS 경계의 유효성 미확인 |
| 직접 Codex / Paseo Codex schema·JSON 종료 | COMPLETE | 각 최종 응답을 설치된 `jsonschema.validate`로 검증 |
| Paseo Claude schema 완료 | BLOCKED | PowerShell 권한 대기. waiter가 `OUTPUT_SCHEMA_FAILED` 반환, JSON 응답 없음 |
| waiter와 실제 실행 종료 구분 | COMPLETE | waiter 종료 뒤 Claude가 계속 running인 사실 확인. 소유 ID만 stop 후 idle 확인 |
| 실제 예약 작업 로그온 맥락 | NOT_MEASURED | Task Scheduler 실행/배치 로그온을 하지 않음. 숨김·stdin 차단 결과로 대체 주장하지 않음 |
| §6.6 추천안 | COMPLETE | 아래 초안. SPEC는 수정하지 않음 |
| 통합 품질 게이트·완료 커밋 | 별도 기록 | 문서 끝의 최종 체크포인트 참조 |

## 환경과 실측

- 2026-11-11 KST, Windows 11 Pro `10.0.26200`, Codex CLI `0.160.0`, Claude Code `2.1.322`.
- Paseo 프로필은 0개. `inspect_provider`에서 확인한 안전 모드 `codex:auto`, `claude:default`를 사용했다. Codex Paseo의 실제 thinking은 `low`, 직접 실행은 `medium`이었다. `full-access`/`bypassPermissions`는 사용하지 않았다.
- 모든 사건은 Python `tempfile.mkdtemp`로 만든 새 폴더. 운영·레포·고객 파일을 probe 입력에 넣지 않았다. 임시 loopback listener는 OS가 고른 포트를 사용했고 운영 포트 8751·8752·8790을 제외했다.
- 관측은 파일 내용·신규 파일·loopback 수신 횟수와 명령 로그를 함께 봤다. 모델이 말한 `executed=false`만으로 결과를 정하지 않았다.

| 경로 | CLI exit / 시간(초) | 실행된 것과 실제 오류 | 외부 읽기·쓰기·네트워크 |
| --- | --- | --- | --- |
| 대조군 PowerShell | 0 / 1.799 | probe 본문 정상 실행, 안쪽 case 읽기 및 안쪽 쓰기도 성공 | 바깥 marker 출력, 덮어쓰기·신규 파일 생성, loopback 수신 1회 모두 성공. probe 유효성 확인 |
| native 기본 read-only | 1 / 0.236 | `windows sandbox failed: CryptUnprotectData failed: 2148073483` | 본문 미실행. 판정 불가 |
| 직접 `codex exec` read-only/never | 0 / 15.419 | 도구의 `CreateProcess ... rejected: blocked by policy`; 최종 `executed=false` | 본문 미실행. OS 차단의 증거 아님 |
| Paseo `codex/gpt-6.1-sol`, auto | 0 / 20.962 | 실제 Shell 요청 뒤 `Failed to create unified exec process: CryptUnprotectData failed: 2148073483`; 최종 `executed=false` | 본문 미실행. OS 차단의 증거 아님 |
| Paseo `claude/opus`, default | 1 / 43.718 | 35s waiter 설정. `OUTPUT_SCHEMA_FAILED: Timed out waiting for structured output`. 별도 inspect에서 PowerShell 권한 대기 확인 | `Read`로 안쪽 probe.ps1은 읽었으나 본문 미실행. OS 차단의 증거 아님 |
| native MXC read-only, 추가 진단 | 1 / 3.355 | PowerShell의 `AuthorizationManager 검사에 실패했습니다`, `UnauthorizedAccess` | 본문 출력 없음. 개별 파일·네트워크 차단 판정 불가 |

모델 경로 3개의 관측값은 모두 바깥 marker 출력 없음·바깥 덮어쓰기/신규 파일 없음·안쪽 신규 파일 없음·loopback 연결 0회였다. 실행되지 않은 명령에서 이 값들은 경계 통과를 의미하지 않는다. 실제 인터넷 목적지는 요청하지 않았고 loopback만 측정했다. loopback의 결과만으로 전체 네트워크 정책을 검증했다고도 주장하지 않는다.

MXC 최초 실행은 CP949 오류 출력 처리 때문에 Python 콘솔 출력이 실패했다. `run.json`은 먼저 저장되어 있었다. probe에 원시 stdout/stderr 바이트 보존, UTF-8/CP949 구분 및 UTF-8 콘솔 출력을 추가한 뒤 모델 없는 MXC만 한 번 재확인했다. 위 표는 재확인 결과다. 앞선 모델 호출을 반복하지 않았다. 이전 세션이 언급한 `unelevated`는 이번 연속 작업에서 실행하지 않았으며 해결 경로로 선정하지 않았다.

## 비대화형 출력과 종료

- 직접 Codex의 `--json`은 **JSONL 이벤트 5개**였다. 마지막 `item.completed`의 `agent_message.text`를 JSON으로 파싱해 schema를 검증했다. CLI 전체 stdout을 JSON 객체 하나로 파싱하면 안 된다. `turn.completed`와 exit 0도 확인했다.
- Paseo Codex의 `--output-schema ... --json` stdout은 **최종 JSON 객체 하나**였다. schema 검증 통과, 실제 agent `idle`/`activeTurn=null` 확인. stdout에 agent ID가 없으므로 stderr의 생성 workspace와 정확한 cwd로 ID를 회수했다.
- Claude의 waiter는 exit 1을 반환한 뒤에도 agent가 `running`, `activeTurn=foreground-turn-1`, `pendingPermissions=[PowerShell]` 상태였다. CLI 대기 제한은 에이전트 취소가 아니다. 실행 시간 43.718초는 provider 준비 등도 포함하며 35초를 정확한 전체 실행 상한으로 삼을 수 없다.
- `paseo stop 74c00c55-0496-4fbb-b11d-e6a5f9ad9fbc --json`의 `stoppedCount=1` 뒤 `idle`, `activeTurn=null`, `pendingPermissions=[]`를 확인했다. 권한을 승인하거나 설정을 바꾸지 않았다.
- 직접 프로세스 트리 종료도 별도 합성 Python 부모+자식 sleep(20초)로 검사했다. `bounded(..., timeout=5)`가 5.769초에 타임아웃 처리했고 `tasklist /FI "PID eq <소유 자식 PID>"`로 자식 부재를 확인했다. **Paseo 데몬 소유 agent에는 이 프로세스 트리 종료만으로 충분하지 않다.** 기존 `app/connected_agent_provider.py::_run_bounded` 재사용만으로는 이 종료 조건을 충족하지 않는다.

## 재현 명령과 증거 위치

아래는 이번에 실행한 명령이다. 모델 경로를 다시 실행하지 않고 남긴 증거를 먼저 검토한다. Python 도구 exit 0은 측정 저장을 뜻하며, 실제 CLI exit는 `run.json.exit_code`다.

```powershell
python tools/probe_p2_isolation.py --route baseline
python tools/probe_p2_isolation.py --route native-default
python tools/probe_p2_isolation.py --route codex-exec --timeout 120
python tools/probe_p2_isolation.py --route paseo-codex --wait-timeout 45s --timeout 75
python tools/probe_p2_isolation.py --route paseo-claude --wait-timeout 35s --timeout 60
python tools/probe_p2_isolation.py --route native-mxc
python -m py_compile tools/probe_p2_isolation.py
```

도구의 `argv`에 실제 절대 실행 파일·옵션·합성 프롬프트를 저장했다. 직접 Codex는 `--ignore-user-config --ignore-rules --ephemeral --skip-git-repo-check`, `web_search=disabled`, `project_doc_max_bytes=0`, `features.multi_agent=false`를 명시했다. 따라서 이 결과가 운영 계정의 저장된 설정과 똑같은 조건이라고 주장하지 않는다. 승인·샌드박스는 각각 `never`/`read-only`였다. Paseo는 설치된 `.cmd` 래퍼와 같은 번들 runner를 인자 배열로 실행해 Windows 셸의 JSON·여러 줄 인자 변형을 피했다.

증거의 공통 루트는 `C:/Users/kkokk/AppData/Local/Temp/`다. 각 폴더에 `run.json`, `stdout.txt`, `stderr.txt`, `verification.json`(schema 검증 결과 및 SHA-256)을 보존했다. 임시 폴더이므로 영구 보존은 보장하지 않는다.

| 경로 | 폴더 | run.json SHA-256 |
| --- | --- | --- |
| 대조군(최종 도구) | `cost-p2-isolation-nslk7ilm` | `8d0a3f6864475b3c2c11ca58982cda964e5c43993d264a3bf6ec50849319f272` |
| native 기본 | `cost-p2-isolation-gskiglha` | `cdf4067fc1173db968e248896925e6ee9becd0fec72edfa5562b8d0ffb19661e` |
| 직접 Codex | `cost-p2-isolation-d8wx2xso` | `a04d0898952384e0c64a70a4461f4dcd158a0d49e673197af18335474de0bf79` |
| Paseo Codex | `cost-p2-isolation-_4ynxx0x` | `182e3b1c7b11c77eb12c4f3bc930028b99cce37cd808072f3991abf42b4e5b5e` |
| Paseo Claude | `cost-p2-isolation-y84v979p` | `776f882b8dfbb4681cc1a58ce25986dc777a9555c9cbb14b973a1edad2cae545` |
| MXC 재확인 | `cost-p2-isolation-91_vv75z` | `525ebbf49c04d5d702edb17e009fea3660fff1bec9493dc6a7821bb0d9bbf073` |

Paseo 두 폴더에는 `paseo-log.txt`도 저장했다. 초기 stdout 디코딩에서 한글 일부가 손실되어, Codex의 정확한 한국어 notes는 이 로그로 대조했다. `cost-p2-isolation-bounded-f1gv97e2/bounded-control.json`에는 프로세스 트리 종료 대조 실험을 저장했다. 최종 도구는 `stdout.bin`, `stderr.bin` 원시 바이트도 보존한다.

임시 workspace는 공식 archive로 정리했고 합성 디렉터리는 보존했다(`removedDirectory=false`). 기존 worktree·사용자 파일·stash를 삭제하지 않았다.

| probe | agent ID | workspace ID | 정리 확인 |
| --- | --- | --- | --- |
| Codex | `052adf6d-87fb-49b2-bd1b-bd2d19e7bd39` | `wks_d37c39b03d434368` | idle 확인 후 archive |
| Claude | `74c00c55-0496-4fbb-b11d-e6a5f9ad9fbc` | `wks_a9834eaa4100c57e` | 소유 agent stop → idle 확인 → archive |

## §6.6 개정 추천안 — 관리자에게 올릴 내용

현재 문구의 "막히지 않으면 직접 호출의 읽기 전용 샌드박스를 기본으로 바꾼다"는 제거하고 다음으로 대체할 것을 권한다. 직접 `read-only`도 수락된 격리 경로가 아니므로 자동 대체하면 안 된다.

> 고객 원문 P2는 사건 자료 읽기만 허용하고, 사건 자료 밖의 업무·사용자 파일 읽기, 모든 쓰기, 도구·자식 프로세스의 네트워크를 런타임 경계로 제한한 경로에서만 실행한다. 실행에 필요한 시스템 파일·런타임은 별도 최소 허용 목록으로 둔다. `cwd`, 프롬프트, 도구 권한 질문, `read-only`라는 모드명만으로 수락하지 않는다. 실제 Worker 계정과 예약 작업 로그온 맥락에서 안쪽 읽기 성공 및 합성 바깥 읽기·쓰기·네트워크의 강제 거부를 확인하고, 활성 설정·CLI 버전·근거를 남긴다. 시작 실패·권한 대기·검사 미실행이면 고객 원문 큐를 실행하지 않고 P1과 독립 구현은 계속한다. 직접 호출과 대체 모델도 같은 조건으로 검사한다. Paseo 타임아웃 시 해당 실행의 agent ID를 회수해 명시적으로 취소하고 종료를 확인한다.

필요한 다음 범위/결정은 다음과 같다. 이번 조사에서 환경을 수정하거나 비용을 발생시키지는 않았다.

1. 현재 계정의 기본 sandbox DPAPI 시작 오류를 담당 운영 세션에서 진단·복구할 범위를 정한다. 원인은 오류 코드 이상으로 확인하지 않았고 `.sandbox-secrets`/인증 자료를 읽지 않았다. 복구 뒤 읽기 허용 범위·쓰기 거부·네트워크 거부를 **각각** 다시 검사해야 한다.
2. 현 장치의 MXC를 사용할 경우 현재 AuthorizationManager 실패 원인과 실제 권한 프로필 지원 버전을 확인한다. 고객 원문 실행을 위해 `unelevated`, `full-access`, 권한 우회로 낮추지 않는다. 격리 환경을 새로 설치·구성해야 하면 별도 승인 범위다.
3. 대안은 사건 내용만 Worker가 읽어 전달하고 로컬 파일·셸·MCP 등 모델 도구 자체를 제공하지 않는 어댑터다. 파일 탐색을 요구하는 §6.1~6.3의 동작 변경이며 **이번에 구현·수락한 경로가 아니다**. 이 대안을 선택하면 도구 제거를 런타임에서 강제하는 설계와 합성 검증을 따로 승인·수행한다.
4. 이후 실제 예약 작업의 로그온 종류·환경·종료까지 실측한다. 현재의 숨김 프로세스+stdin 차단을 예약 작업 성공으로 승격하지 않는다. 읽기 도구와 셸·자식 프로세스 양쪽의 경계를 검사해야 한다.

## 문서 근거

- [OpenAI Windows sandbox](https://learn.chatgpt.com/docs/windows/windows-sandbox): permission profile이 파일·네트워크 범위를 결정한다. `unelevated`는 denied-read 미지원이고 네트워크 격리가 더 약하다. 문서는 현재 버전 안내이며 설치 버전에 그대로 적용된다고 가정하지 않는다.
- [OpenAI Permissions](https://learn.chatgpt.com/docs/permissions): `:read-only`는 local command의 읽기 전용 조건이다. 읽기 범위와 네트워크는 프로필에서 별도로 정한다. 따라서 명칭 자체가 사건 폴더 외부 읽기 금지의 근거가 되지 않는다.
- 명세 [§6.6](../../SPEC.md#66-기록과-검증)의 `read-only` 대체 경로 역시 사건 폴더 밖 읽기 금지를 별도로 실측해야 한다.

## 최종 체크포인트

- 구현 변경은 합성 조사 도구 하나뿐이며 운영 코드·SPEC·규칙집·DB·배포를 변경하지 않았다. 지정 파일 소유권에 따라 공유 `session_handoff.md` 대신 이 절에 인계 근거를 둔다.
- 표적 검증: 최종 baseline 실행, `py_compile`, JSONL 5개 파싱 및 최종 JSON schema 검증 2건, 소유 프로세스 트리 timeout 검사, Claude stop 후 idle 확인, workspace 2개 archive 완료.
- 조사 도구 완료 커밋: `5ffc135fcd0c4c365213db08e6893fdee72a1f9c`. 이 보고서의 커밋은 `git log -1 --format=%H -- docs/agents/artifacts/p2-isolation-20261111.md`로 확인한다. 통합은 두 커밋을 함께 검토한다.
- `python tools/run_quality_checks.py --base origin/main --run`은 **미통과**: `{"status":"ERROR","reason":"UNKNOWN_IMPACT:1"}`. 신규 `tools/probe_p2_isolation.py`가 영향 매핑에 없어서 검사 계획 단계에서 중단됐고 pytest는 실행되지 않았다. 0건을 통과로 계산하지 않았다. 영향 매핑은 배정된 파일 소유권 밖이므로 임의 수정하지 않았다. 통합 담당자의 조사 도구 분류/검증 검토가 남는다.
- `python tools/check_tracked_data.py --mode base --base origin/main --json`은 exit 0, blocked 0·삭제 0. 이 검사는 metadata-only이며 내용 보안 검사의 대체가 아니다. 합성 입력·도구·보고서 diff를 별도로 확인했다. 문서의 로컬 링크도 확인한다.
- 운영 코드 테스트·브라우저·배포·운영 DB 조회는 수행하지 않았다. 제품 기능을 바꾸지 않는 조사 범위다. 추가 모델 호출은 필요 없다.
- 남은 일: 고객 원문 경로의 격리 수락 및 실제 예약 작업 실측. 관리자에게 위 오류 복구/대안 설계 범위를 올린다. 재개 시 기존 증거부터 검토하고, 새 범위가 정해지기 전 고객 원문을 실행하지 않는다.
