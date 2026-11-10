# Runtime catalog R0 (RF-005 / RF-109)

상태: R0 PARTIAL / 정적 후보 도구 / 일부 scheduler 참조 확인. RF-005 실제 릴리스·복구 계약 전체의 완료가 아니다.

`tools/runtime_dependency_catalog.py`는 Git 추적된 Python·PowerShell·cmd/bat·XML 소스 중 tools, app, webapp, tests와 알려진 루트 런처 후보만 정적으로 읽습니다. 모듈 import, 프로세스 실행, 스케줄러 조회, 운영 경로 탐색, 환경/시크릿 값 출력은 하지 않습니다. 출력은 JSON 또는 `--format summary`이며 출처는 파일 경로와 줄 번호만 포함합니다.

이 도구는 `TEST_FIXTURE`, `HISTORICAL`, `UNKNOWN`을 반환합니다. `ACTIVE_SAFE_READ`/`ACTIVE_WRITE_GUARDED` 승격은 실제 호출과 보호 근거가 검증된 이후의 작업입니다. R0에서는 주석·문자열·프로세스/쓰기 호출 표식만으로 ACTIVE를 부여하지 않습니다. 각 항목은 confidence와 근거 설명, 정적 참조 위치, OPEN_QUESTION을 제공합니다. 상대 import는 패키지와 import level을 기준으로 해결하며 parse/read 오류는 원문 없는 diagnostics와 exit2로 반환합니다. 참조 줄은 무표시로 절단하지 않습니다. script 경로 문자열은 추적 후보와 정확히 일치하는 경로만 찾으므로 동적·절대 경로 호출은 미확인입니다.

실행: `python tools/runtime_dependency_catalog.py --format summary`

검증: `python -m pytest tests/test_runtime_dependency_catalog.py -q` 8 passed. CLI summary는 추적 후보616개를 분류했고 exit0이었다. 상대 import·외부 root·주석/process marker의 ACTIVE 오분류 방지·원문 sentinel 비출력·읽기/구문 오류·참조 전체 보존을 합성 입력으로 확인했다. 실제 운영 호출 관계·권한 게이트는 확인하지 않았다.


## RF-005 / RF-109 운영 호출 경로 보완 (정적 소스 + 전달된 scheduler metadata, 2026-10-28)

이 절은 제한된 두 scheduler 상태를 별도 운영 메타데이터로 기록하고, 저장소 안에서 추적 가능한 실행·효과 경로를 정리한다. 원본 action 인자 전체, 환경값, 인증, 외부 호스트 코드, 고객 자료 및 DB는 이 문서 작업에서 열거나 출력하지 않았다. 메타데이터 표는 PR #213 배포 전 관찰이다. 이후 Supervisor가 확인한 최종 운영 SHA `44421df083f6eb7447bbfe4dc0ad10e4fb4039ca`, health/ready200·보호API401·보호13표 불변은 [운영 기록](../../operations.md)에 별도 보존했다. 문서 검수 때문에 운영 검사를 반복하지 않았다.

### 확인된 운영 메타데이터 (Supervisor가 읽기전용 확인해 전달)

| Scheduler | 전달된 확인 | 증거 범위 / 한계 |
|---|---|---|
| `WebLedger-Board` | 상태 `Running`; PowerShell action arguments가 `tools\start_web_ledger_host.ps1`를 참조; 기존 운영 SHA reference match는 `true` | Running 상태와 지정 스크립트·SHA reference match만 확인된 것으로 기록한다. 원문 arguments, credential file 및 runtime environment는 확인하지 않았다. 이 값만으로 child 프로세스·서비스 건강·최종 운영 SHA 또는 PR213 배포 완료를 증명하지 않는다. |
| `WebLedger-SourceRefresh` | 상태 `Running`; executable `powershell.exe`; working directory `C:\AX\cost`; arguments의 tracked filename이 `tools\watch_review_source.ps1`와 일치 | 상태·실행 파일·working directory·tracked filename 일치만 확인된 것으로 기록한다. 전체 arguments와 하위 프로세스 상태·실제 수집 결과는 확인하지 않았다. |

### Source-only 호출 및 효과 경로

| 경로 | 소스 근거와 정적으로 확인된 동작 | 보호 / 미확인 경계 |
|---|---|---|
| Board startup | `tools/start_web_ledger_host.ps1:485-535` builds the child plan; default board launcher is `tools/launch_web_ledger.py` (`:506-522`). `Start-HostChild` invokes planned executable/arguments via `Start-Process` with checkout working directory and board stdout/stderr logs (`:596-630`); `Watch-HostChildren` re-probes and restarts missing planned children (`:737-803`). Repository launcher `tools/launch_web_ledger.py:237-279` delegates production startup to `run_candidate.main`; `run_candidate.py:292-339` validates production configuration/readiness before binding, and `:349-389` binds runtime access, starts prewarm threads and the enabled Google trip-import worker, serves, then closes on shutdown. | The scheduler's exact runtime parameters are intentionally not repeated. `D:\WebLedgerHost\bin` launcher/deploy components are outside this repository and remain **OPEN_QUESTION**; source evidence does not establish their current contents or final target SHA. The planned source does not establish that every child is currently healthy. Startup may create/validate local config/data paths; no such path was accessed. |
| Source refresh worker | `tools/watch_review_source.ps1:1-13` sets the checkout working directory and invokes the virtualenv Python with `tools/refresh_review_source.py`; tracked filenames match the reported task metadata. The wrapper names config/master/bundle/source-config paths and bounded timeout/attempt/size/watch options in source; their contents were not read. `refresh_review_source.py:153-202,218-264,330-352` selects a bounded URL fetch (or explicit snapshot), reads the master input, then calls `review_refresh.collect_and_activate`; watch mode repeats after the interval. The source URL type is Google Sheets export (`:61-65,126-150`). | Source code proves code capability and configured path literals, not that the scheduled process loaded them or successfully fetched/activated. Logs are redirected by the wrapper (`watch_review_source.ps1:12`); no log was read. Network success and active source/config remain **OPEN_QUESTION**. |
| Refresh effects / activation | `review_refresh.collect_and_activate` holds `collector_lock`, compares active binding/config digest, performs a no-op check, stages and activates (`webapp/review_refresh.py:1179-1204`). Refresh writes an immutable review bundle and finally replaces the review config (`:904-930,1257-1280,1290-1342`); status is atomically written separately (`:1368-1399`). `refresh_review_source.py:271-286` records fixed status codes. | This traced path reads the workbook export and master CSV and writes review bundle/config/status artifacts. Its source explicitly states it does not write source files, decisions DB, or operational ledger (`webapp/review_refresh.py:38-39`). No direct financial ledger or Google final-ledger write occurs in this traced path; this does not prove behavior of external scheduler wrappers or unrelated workers. The Windows config replacement preserves DACL and uses a backup/restore-on-failure path (`:1257-1280`); activation checks bundle integrity and base config digest before replacement (`:1290-1342`). |
| Ops / backup and rollback boundary | `run_candidate.py:306-327` gates startup on safe bind, durable config and readiness. `webapp/ops.py:482-520` tests DB writability only on a temporary copy with transaction rollback; `:857-928` implements backup bundles, and `:1024-1166` restores to a separate target with verification. `build_deploy_manifest` is explicitly dry-run and records `applied: false` (`webapp/ops.py:1742-1796`). | These code paths describe safeguards and tooling, not proof that a particular scheduler/deployment invocation ran them. No live backup, restore, DB probe, deployment, or rollback was performed. `D:\WebLedgerHost\bin` and any external deployment/rollback wrapper remain external dependencies **OPEN_QUESTION**. |

### Scope status

The earlier scheduler/launcher question is **PARTIALLY RESOLVED** for the two metadata records above and the repository source chains shown here. Exact runtime arguments, full external D: drive launcher/deployment behavior, successful source-refresh execution and activated bundle/config remain unverified. Current release identity and deployment health have separate Supervisor evidence in the operations record. Source-only evidence does not justify promoting any catalog item to `ACTIVE_SAFE_READ` or `ACTIVE_WRITE_GUARDED`; no repository-wide dependency-completion claim is made.

검사 범위: document diff, links/paths and source references only. Do not run the runtime catalog, tests, build, browser, scheduler, host, deployment, or database checks for this document-only update.

남은 질문 (현재 범위에 맞게 갱신):
- External `D:\WebLedgerHost\bin` launcher/deploy/rollback code의 실제 대상과 보호 조건은 무엇인가?
- Scheduler가 전달된 tracked scripts를 현재 어떤 전체 arguments/environment로 실행하며, 해당 실행이 성공하고 어떤 child/bundle/config를 활성 상태로 만들었는가? (원문 인자·환경 비밀·고객 자료 없이 확인 가능한 최소 메타데이터 필요)
- PR #213의 최종 운영 SHA와 health는 운영 기록에서 확인됐다. SourceRefresh가 마지막으로 활성화한 bundle/config와 수집 결과는 이 문서의 수락 범위 밖이며 미확인이다.

기존 RF-005 도구 검증 기록(616 tracked candidate summary, 8 tests passed)은 해당 과거 검사 기록으로 유지한다. 이번 변경에서는 그 도구·테스트를 재실행하지 않았다.
