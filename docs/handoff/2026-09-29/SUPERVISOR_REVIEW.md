# 최종 감독 검토 기록

이 파일은 부모 감독자의 검토 근거다. 작업 배정과 진척의 단일 출처는 Sol이 관리하는 `docs/WEB_LEDGER_IMPLEMENTATION_LOG.md`의 작업표다. 이 기록은 완료 판정이나 별도 작업 지시가 아니다.

## 최종 로컬 검토 — 2026-09-29

최종 Sol 검토에서 로컬 구현은 수용됐다. 요청별 저장소 결속과 서버별 SQLite 접근
직렬화가 현재 구조에 맞는 최소 수정이며, 추가 로컬 기능이나 필수 회귀 검사는
남지 않았다는 판정이다.

- 새 서버 저장소 격리 회귀 2개: 5회 모두 통과
- 관련 묶음: 5회 모두 `91 passed`
- 전체 `webapp/tests`: `1033 passed, 1 skipped, 139 subtests passed in 449.58s`
- `compileall`: 통과
- `git diff --check`: 통과

외부 Railway 설정과 실제 배포, 비밀값 주입, 운영 DB 보호·백업, Google OIDC
callback, Reservation API, 실제 AI 연결과 등급, 실물 모바일과 Excel 출력은 외부
증거가 필요한 별도 조건이다. 이 조건을 확인하기 전에는 운영 전환 완료로 표시하지
않는다. 현재 판정은 **로컬 구현 완료, 외부 운영 조건 대기**다.

## 관리 세션 실행과 복구

- 사용자 후속 지시: Sol Web을 실제 호출하고 부모가 최종 감독자로 남아 완료까지 진행한다.
- 2026-09-29 제공 목록에서 provider `codex`, model `chatgpt-web/gpt-5.6-sol`을 확인했다. 프로필 목록은 비어 있었다.
- 최초 관리 세션 `aca7bddc-b174-4b43-b296-a64d94a765b7`는 위 모델, 추론 `high`로 실행됐으나 remote compact 도중 연결 종료 오류가 났다. 같은 세션 재시도도 동일 오류로 종료됐다.
- 오류 원문: `Error running remote compact task: stream disconnected before completion: ChatGPT did not complete the context handoff. Retry the task.`
- 복구 관리 세션 `afe8152b-f066-4236-8673-925f49a9fa76`는 동일 모델과 설정으로 생성했다. 출력당 100줄·6000자 제한, 전체 구현 로그와 전체 에이전트 대화 재독 금지를 전달했다. 읽기 도구 실행과 초기 응답을 확인했지만 구현 분할·결과 수용 완료는 아직 확인하지 않았다.
- 기존 SpaceBunny `36982862-21d6-4f6b-b51c-921d4c981881`를 중단하거나 새 지시로 덮어쓰지 않았다. 코드 변경은 해당 작업자의 작업이므로 부모가 수정하지 않는다.

## 최종 수용 시 확인할 증거 범위

격리 준비 중 관측: `C:\Users\kkokk\.paseo\worktrees\28lt5mey\muse-audit-fixes-20260929`는 기준 `5c1db3366334b3c467e7be7318d2608597534d42`에서 만들어졌다. 생성 직후에는 미커밋 `WEB_LEDGER_AGENT_OPERATIONS.md`가 없고 AGENTS 진입점도 이전 인계를 가리켰다. 위임 전에 최신 규칙을 명시 프롬프트나 제한된 문서 복사로 전달했는지 확인한다. 이는 준비 도중 관측이며 실제 위임 누락이 확정됐다는 뜻은 아니다.

다음은 기존 검사를 읽어 확인한 범위의 한계다. 기존의 다른 행동 검사로 이미 증명됐는지 먼저 대조하며, 자동으로 새 구현·전체 재검사를 추가하지 않는다.

| 근거 | 실제로 확인하는 범위 | 넓은 완료 주장에 추가로 필요한 근거 |
|---|---|---|
| `test_ops_safety.py`의 `test_every_ops_command_that_opens_a_store_passes_seed_demo_false` | `LedgerStore` 호출에 `seed_demo` 키워드가 존재하는지 | 값이 실제로 false이며 읽기 명령이 누락 DB 생성·스키마 변경 같은 부작용을 내지 않는지. 기존 행동 검사 우선 대조 |
| `test_platform_start.py`의 `test_the_entry_point_refuses_to_seed_outside_local_synthetic` | 시작 코드의 특정 문자열 존재 | 실제 운영 시작 경로에서 데모 자료가 생성되지 않는 실행 근거 |
| `test_space_guard.py`의 `test_two_writers_do_not_both_spend_the_same_free_bytes` | 같은 프로세스에서 중첩된 예약의 합산과 해제 | 별도 프로세스 경합까지 검증됐다는 주장은 불가. 실제 배포의 작성자·프로세스 범위를 확인하고 그 범위에 맞춰 판정 |
| 구현 기록의 과거 `887 passed` | 당시 혼합 작업 트리의 실행 보고 | 최신 통합 후보의 파일 목록·코드 digest와 결속된 검증 결과. 변경 없는 전체 검사 반복은 불필요 |

저장공간 부족, 복구 대상 보호, PORT 해석, 인증 없는 health·ready 경로의 기존 행동 검사도 존재한다. 위 제한만으로 해당 기능 전체가 실패했다고 단정하지 않는다. 최종 결과 회수 후 실제 요구사항과 근거를 대조해야 한다.

## 추가 합성 재현: 읽기 점검이 스키마를 생성함

2026-09-29 부모가 임시 DB에 `sentinel` 테이블 하나와 합성 문자열만 넣고 `python -m webapp.cli ops health`를 실행했다. 데이터 루트·DB·출력·증빙·원천 환경 경로를 모두 전용 임시 디렉터리로 지정했다.

- 앱 명령 종료 코드: `0`.
- 실행 전 테이블: `1`개. 실행 후 테이블: `32`개.
- `board_rows`가 새로 생성됐으며 DB 바이트 SHA-256이 바뀌었다.
- 따라서 불완전한 DB를 읽기 점검하는 과정이 스키마를 생성하고 성공으로 보고하는 경로가 재현됐다. 운영 원본은 사용하지 않았다.
- 재현 도우미의 임시 파일 정리는 열린 SQLite 연결 때문에 실패했다. 프로세스 종료 뒤 정확한 경로를 검사하고 삭제하는 명령도 자동 정책에서 차단됐다. 임시 폴더 `C:\Users\kkokk\AppData\Local\Temp\cost-supervisor-ro-uh46tud0`는 남아 있으며 정리 완료로 보고하지 않는다. 앱 종료 코드와 도우미 정리 오류를 구분한다.

Sol은 기존 감사의 읽기 전용 ops 항목에 이 재현을 연결하고 담당 구현자에게 필요한 수정만 배정한다. 부모는 코드를 수정하지 않았다. 전체 앱 검사나 운영 연결 검증은 실행하지 않았다.

## 추가 합성 재현: 예약 가져오기가 없는 DB를 생성함

기존 테스트의 합성 `raw_snapshot(1800000000000, [person()])`을 임시 JSON으로 만들고, 존재하지 않는 임시 `absent.sqlite`를 지정해 `python tools/import_reservation_access.py --input <합성 JSON> --db <없는 DB>`를 실행했다.

- 종료 코드 `0`, 표준 오류 없음, 없던 DB가 생성됨.
- 최신 인계의 예약 가져오기 missing DB 거부 요구사항과 다르다. CLI의 다른 예약 동기화 경로를 검증해도 이 독립 도구의 안전성을 대신 증명하지 못한다.
- 이번 재현의 임시 폴더는 정상 정리됐다. 실제 예약·사용자 자료는 사용하지 않았다.

현재 판정: **읽기 점검의 스키마 쓰기와 예약 가져오기의 missing DB 생성이 재현됨. 전체 완료 미검증**.

## 2026-09-29 후속 통합 검증

health 수정과 예약 안전성 수정은 서로 겹치지 않는 writer 범위에서 순서대로 통합했다. 예약 Muse의 커밋 `395f7a3`은 Sol의 짧은 통합 검토에서 수용되었다. Sol은 예약 수정 전에 추가 변경이 필요 없고, 통합 뒤 관련 검사 묶음 한 번이면 충분하다고 판단했다.

부모가 현재 작업트리에서 다음 묶음을 직접 실행했다.

```text
python -m pytest webapp/tests/test_reservation_access_sync.py webapp/tests/test_reservation_audit_fixes.py webapp/tests/test_ops_surfaces.py webapp/tests/test_ops_safety.py webapp/tests/test_health_readonly_regression.py -q -p no:cacheprovider
75 passed, 1 skipped in 69.64s
```

추가로 예약 전용 검사 29개를 격리 작업공간에서 다시 실행해 `29 passed in 15.50s`를 확인했고, 변경 파일의 `compileall`과 `git diff --check`도 통과했다. 전체 suite는 아직 실행하지 않았다.

SpaceBunny의 웹 서버 진단은 코드 변경 없이 종료됐다. 유효한 소형 계측에서는 요청 시작과 종료가 각각 8건이고 store 불일치와 종료 뒤 요청이 0건이었지만, 계측이 실행 시점을 바꿔 대상 flaky를 재현하지 못했다. Sol은 추가 반복과 수정 없이 두 flaky를 별도 잔여 위험으로 보류하고, 검증되지 않은 `ledger_board.py` docstring 한 줄은 되돌리도록 결정했다.

현재 완료 판정은 전체 완료가 아니다. 예약 안전성 수정은 통합 검증을 마쳤지만 웹 서버 flaky 두 건의 원인은 미분리 상태이며, 최종 전체 architecture/integration review와 전체 suite는 이 잔여 위험을 반영한 뒤 수행한다.

최종 Sol 검토는 조건부 수용이었다. health와 예약 변경의 구조·범위·관련 검사 결과는 수용했지만, 웹 서버 두 flaky의 원인 미분리와 acceptance 미달, 최종 후보의 전체 suite 1회 미실행 때문에 전체 완료로 표시하지 않는다. 현재 phase는 로컬 예약·health 안전성 통합 완료, 웹 서버 flaky 두 건 보류, 최종 전체 회귀 전이다. 추가 targeted 검사는 지금 필요하지 않으며, 코드가 더 바뀌지 않는 후보가 확정된 뒤 전체 suite만 1회 실행한다.
