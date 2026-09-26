# 2026-09-08 세션 인계 — 전체 흐름 점검과 Reserve Max 수정

상태는 `PARTIAL_HANDOFF`다. 로컬 코드 개선과 운영 회계자료의 확정을 구분한다. 기존 v15 워크북·v5 초안·shadow를 최종 장부로 승격하지 않았다.

2026-09-25 웹 장부 작업의 시작점은 [구현자 전달문](../../IMPLEMENTATION_PROMPT_WEB_LEDGER_APP.md)과 [구현 검토 7절](../../WEB_LEDGER_IMPLEMENTATION_REVIEW.md)이다. 기능 명세와 무료 선행 시험안은 정리됐으나 코드 수정·실제 배포 완료를 뜻하지 않는다. 당시 검토 결함은 수정 증거가 제출되기 전까지 남긴다. 최신 명세 인계는 저장소 `LOG.md`의 2026-09-25 블록을 따른다. 아래 파이프라인 인계의 PARTIAL 상태와 검증값은 과거 범위 그대로 보존한다.

이 인계 작성 당시 사용자 요청의 시작점은 [Reserve 저장 일정 재개](RESERVATION_RESUME.md)다.
그 직전의 코드 변경과 검증은 [멱등 실행 추가 인계](IDEMPOTENCY_UPDATE.md)에 있다.
아래 집계·검증 manifest는 첫 점검 완료 시점의 스냅샷이며, 이후 코드까지 같은 해시라는 뜻은 아니다.

먼저 [전체 점검과 개선 설계](../../PIPELINE_REVIEW_2026-09-07.md)를 읽는다. 직전 인계는 [2026-09-01 인계와 이후 정정](../2026-09-01/README.md)이다. 이번 실측과 충돌하는 이전 집계, 업로드 우선 지시, 로그 삭제를 승격 조건으로 삼는 설명은 현재 실행 근거로 사용하지 않는다.

## 구현한 변경

- `tools/pipeline_audit.py`, `config/pipeline_inventory.json`: 입력 파일을 바꾸지 않는 통합 진단을 추가했다. 진입점·보존 산출물, SQLite 구조·집계, 감사 해시, 중복 결제, 차변·대변 균형, 후보의 전기 상태를 검사한다. 입력 변경과 누락은 성공으로 처리하지 않는다. 진단은 업무 정확성이나 전기 권한을 승인하는 도구가 아니며 `release_eligible=false`를 유지한다.
- `tools/build_agoda_journal_shadow_v5_ota.py`: 음수와 0원을 양수 구매로 바꾸지 않고 독립 취소·환불 근거가 필요하다는 오류로 중단한다. 엄격한 정수 금액, 결제 식별자, 실제 원천 예약번호, 감사 파일의 최종 DB 해시·행수·부호 있는 합계·입력 DB 해시를 확인한다. 검증된 임시 출력만 새 파일로 생성하며 기존 파일과 끊어진 심볼릭 링크를 덮어쓰지 않는다. 두 번째 출력 생성 실패 시 이번 실행이 만든 첫 번째 출력만 되돌린다. 생성 시각은 실제 UTC 시각을 기록한다.
- `ledger/domain/direct_verified_ota_lodging.py`: 명시 `exclusive_service_end` 일정의 `ends_on`에 원천 종료일을 그대로 보존한다. 숙박의 마지막 밤을 나타내는 `last_service_on` 계산은 유지한다.
- 새 테스트는 합성 자료를 사용한다. 구현 에이전트는 실제 원장·예약·메일에 접근하지 않았다. 코디네이터가 저장소에 반영한 뒤 실제 보존 산출물을 읽기 전용으로 점검했다.

SQLite 입력 옆에 `-wal`, `-shm`, `-journal`이 있으면 봉인된 파일로 간주하지 않는다. 원본 DB와 이 부속 파일을 고치거나 체크포인트를 실행해 검증을 강제로 통과시키지 않는다. 부속 파일은 내용을 읽지 않고 메타데이터만 비교한다. 봉인된 DB는 `mode=ro&immutable=1`과 `query_only`로 열어, 닫힌 WAL DB를 읽으면서 부속 파일이 새로 생기는 문제도 막는다.

## 재현 명령

PowerShell에서 저장소 루트를 사용한다.

```powershell
python -m tools.pipeline_audit --root . --inventory config/pipeline_inventory.json
python -m pytest ledger/tests/test_pipeline_audit.py ledger/tests/test_agoda_journal_shadow_v5_ota.py -q
python -m pytest ledger/tests/test_direct_trip_schedule_authority.py ledger/tests/test_direct_ota_reservation_authority.py ledger/tests/test_direct_accounting_shadow.py webapp/tests -q
```

진단 종료 코드는 `0=검사 항목 통과`, `1=확인된 오류`, `2=미검증·누락 또는 설정 오류`다. `ok`인 단계도 파일 존재·구조 등 실제 실행한 검사 범위만 통과했다는 뜻이다. 외부 Apps Script는 실행하지 않고 `skipped`로 기록한다. `--output`을 쓸 때는 저장소 안의 아직 없는 상대 경로를 지정한다. 기존 진단 결과를 덮어쓸 수 없다.

보존된 초안을 새 shadow 빌더에 넣으면 `v5_audit_database_sha256_missing`으로 중단하는 것이 현재의 올바른 결과다. 초안 감사표에 현재 해시만 사후 기입해 통과시키지 말고, 검증된 원천부터 같은 실행으로 다시 만들어야 한다.

## 검증과 보존 자료

최종 통합 실행은 **102 passed, 1 failed, 16 skipped, 경고 0건**이다. `python -W error`로 실행했으며 [최종 테스트 기록](targeted-tests-final.xml)에 보존했다. 아래 항목별 통과 수를 합한 결과다. 앞선 `targeted-tests.xml`은 Windows 출력 디코딩 경고가 발생했던 실행의 기록이므로 최종 판정에는 사용하지 않는다.

- 일정·OTA 권위·기존 회계 shadow·webapp 검사: **53 passed, 1 failed**. 실패는 수정 전에도 발생한 `test_two_explicit_overlapping_periods_are_ambiguous`다. 테스트를 삭제하거나 기대값을 바꾸지 않았다.
- 통합 진단의 새 합성 검사: **17 passed**. 실제 초안·shadow 열 구조, 감사 해시 별칭 충돌, 중복 결제, 입력 변경, 파일 보존, 경로 제한을 검사한다.
- 새 v5 shadow 검사: **30 passed**. 음수·금액 형 변환·감사 누락·변조·입력 변경·예약번호·출력 충돌·실패 복구·SQLite 부속 파일·실제 생성 시각을 검사한다.
- 기존 검증 숙박·구조화 숙박 검사: **2 passed, 16 skipped**. 8개는 기존 authority pin 재기준 설정 조건, 8개는 staged evidence 부재로 건너뛰었다. 통과 수에 포함하지 않는다.
- 수정 전 전체 테스트는 824개를 수집했다. 전체 실행은 45초 제한으로 `test_domain_ledger.py::test_change_log_is_idempotent_and_rebuilds_current_state`에서 종료되어 전체 통과를 확인하지 못했다.
- 실제 보존 초안을 사용한 생성 거부 검사에서 위 해시 누락 오류를 확인했고 출력은 생기지 않았다. DB 4개와 워크북 1개의 SHA-256은 검사 전후 같았다.
- Python 363개 파일과 Apps Script 5개 파일의 문법 검사를 통과했다. Apps Script의 원격 실행이나 업무 결과를 검증한 것은 아니다.

[통합 진단 결과](pipeline-audit.json)는 **10단계 중 구조 검사 통과 7, 오류 1, 미검증 1, 외부 실행 생략 1**을 기록했다. 종료 코드는 `1`이다. 후보 감사 해시 불일치, 초안 해시 누락, 외부 단계 생략을 구분한다. 기존 shadow 단계의 구조 검사 `ok`는 아래 금액 부호 오류가 해결되었다는 뜻이 아니다.

최종 테스트와 입력·구현 파일의 해시는 [검증 manifest](validation-manifest.json)에 기록한다. 워크북은 행수·합계·헤더를 읽었으며, 수식 재계산과 시각 양식 검증까지 완료한 것으로 표시하지 않는다.

## 현재 데이터의 판단

| 항목 | 읽기 전용 실측 | 의미 |
|---|---:|---|
| 전체 결제 | 5,328행, 708,722,467원 | v15 워크북의 행수·합계와 일치 |
| 후보 관계 | 104개, 모두 `proposed` | 확정 관계가 아님 |
| OTA 초안 | 113행, 27,879,494원 | 현재 원천 DB와 감사 계보가 불일치 |
| 초안 음수 | 11행, −5,207,800원 | 별도 취소·환불 경로가 필요 |
| 기존 shadow | 113묶음, 226줄, 차변·대변 각 38,295,094원 | 음수의 절댓값 변환으로 원래 합계보다 10,415,600원 큼 |
| 통합 예약 | 1,236행 | 원천·관계 검증을 대신하지 않음 |

DB의 구조 무결성이 `ok`여도 위 회계·계보 문제는 남는다. v15의 실제 예약번호·증빙 종류·이용기간·여행 귀속은 빌더의 추론을 제거하고 검증된 판정에서 다시 투영해야 한다.

## 남은 조건과 다음 구현 순서

1. 일반 일정 충돌 보류와 8월 29일 확인된 레분토·유럽 선택 사례의 적용 범위를 명시 계약으로 정리한다. 승인된 사례를 임의의 겹치는 모든 일정으로 확대하지 않는다.
2. 원천 manifest를 고정하고 후보 관계를 정식 OTA 검증 경로에서 재현한다. `proposed`·`held`를 `bound_unique` 또는 전기 권위로 자동 승격하지 않는다.
3. 같은 검증 결과로 워크북을 생성한다. 사용자 지정 양식은 `매출자료 양식_rev`이며, C열은 지출 항목이다. 미확인 예약번호와 숙박·렌트의 실제 이용기간은 공란으로 둔다.
4. Apps Script의 결제일+7일 분류, 주간 보고의 `_C` 탭 의존, 입금 동기화의 MMDD·지역 매칭을 검증된 실행·안정 여행 ID 소비 방식으로 바꾼다. 운영 배포와 트리거는 별도 대조한다.

Google Workspace의 계정 상태와 Sheets 읽기를 실제 호출했다. 이 세션의 커넥터는 업무 계정 credentials 파일이 없어 읽기에 실패했다. 다른 앱이나 세션 전체가 불가능하다고 일반화하지 않는다. 인증 복구나 외부 전기는 이번 로컬 수정에 포함하지 않았으며, 메일 발송·배포·장부 쓰기를 실행하지 않았다.

`C:\AX\AGENTS.md`는 재개 후 확인 시 존재하지 않았다. 과거 백업으로 전역 규칙을 임의 복원하지 않았다. 외부 로그 삭제는 이번 작업과 무관하며, 자료 보존이나 전기 허용의 선행 조건이 아니다.

## 모델과 작업 관리

사용자의 최신 지시에 따라 구현은 Paseo의 `codex/gpt-reserve`, `thinkingOptionId=max`로 수행했다. 실제 에이전트 상태에서 모델과 적용된 추론 설정을 확인했으며 [설정 확인 기록](implementation-agents.json)에 보존했다.

| 작업 | 에이전트 ID |
|---|---|
| 통합 진단 | `7f996b5e-cc3a-400e-b3ea-653a4fcf61a5` |
| shadow 보완 | `2006c45d-9b80-464a-b9ad-c7bed588f19d` |
| 일정 종료일 | `dff43cab-f84a-4163-bf46-667ddc530c8d` |

구현 명세와 필요한 코드만 전용 임시 작업공간에 전달하고, 검토에서 발견한 누락만 같은 에이전트에 보완 요청했다. 작업 중인 에이전트에 새 프롬프트를 보내 중단시키지 않았으며 완료 알림은 코디네이터가 통합했다. 반환된 `lastUsage`는 마지막 호출의 값이므로 세션 전체 토큰 합계로 보고하지 않는다. Sol이나 AGY가 검토를 완료했다고 주장하지 않는다.
