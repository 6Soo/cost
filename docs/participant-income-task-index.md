# 참가자·수입 대조 작업 인덱스

> 작업 단위: 보험가입 명단 기반 참가자 확정과 수입 대조
> 갱신일: 2026-10-20 KST
> 현재 명세: [버전 1.0](participant-income-reconciliation-spec.md)

이 인덱스는 이 기능의 현재 요청과 실행 범위만 관리한다. 다른 독립 작업의 승인·진행 상태를 변경하지 않는다. 과거 ACTIVE 문서를 구현 지시로 읽지 않는다.

| 작업 ID | 요구사항 | 상태 | 근거 또는 다음 단계 |
| --- | --- | --- | --- |
| SPEC | 계획 및 명세 작성 | COMPLETE | 사용자 요구, 기존 Google 수입 경계, 전달·대조·예외·화면·검증 계획을 명세에 기록했다. |
| P0 | 구조화 명단 수신·참가자 저장 | IMPLEMENTED | `app/participant_roster.py`, `tools/ingest_participant_roster.py`, 커밋 `945c218`. 표적 테스트 `tests/card_pipeline/test_participant_roster.py` 통과. |
| P1 | 금액 없는 Google 이름 행 조회 | IMPLEMENTED | `app/google_authority.py` 이름 인덱스, 커밋 `650b730`. `tests/card_pipeline/test_google_authority.py` 58건 통과. |
| P2 | 수입 대조·연결·수동 결정 | IMPLEMENTED | `app/participant_income.py`, 커밋 `b2366f2`. `tests/card_pipeline/test_participant_income.py` 통과. |
| P3 | 관리자 참가자 대조 화면 | IMPLEMENTED | `webapp/participant_income_page.py`, 커밋 `a14a414`. `webapp/tests/test_participant_income.py` 통과. |
| P4 | 합성 통합 확인 | IMPLEMENTED | `tests/card_pipeline/test_participant_integration.py`, 커밋 `b94204c`. 수신→표시→수동연결→재수신→Google 변경 한 번 확인. |

구현은 승인된 범위 안에서 끝까지 수행했고 운영 배포·실제 명단 등록은 하지 않았다. Google 쓰기·수입 자동 기장·미납·완납 추정은 구현하지 않았다. 2026-10-20 Supervisor 검토로 지적된 명세 누락과 결함도 반영해 표적 검사로 닫았다.

2026-10-20 후속 요청으로 P0~P4의 실제 구현을 승인받았다. 구현 작업자는 OpenCode 1.19.3의 `opencode/minimax-m3.1-flash-free`(추론 high)로 실행했다. 앞선 Muse Spark·Space Bunny 호출은 반복하지 않았다. 표의 상태는 작업자가 착수·검증 근거에 맞춰 갱신했다. SPEC은 완료된 설계 근거로 유지한다. 운영 배포와 실제 고객 명단 등록은 이번 요청에 포함되지 않는다.

구현은 기존 COST 작업 공간에서 작업자 한 명이 담당한다. Supervisor는 요구 해석과 읽기 전용 검토를 맡고 같은 파일을 동시에 수정하지 않는다. 전달 자료는 코드·명세·합성 자료로 제한하며 기존 미커밋 아고다 변경은 수정·stage하지 않는다. 설계·구현 방법은 현재 승인 범위 안에서 결정하고 다시 승인을 요청하지 않는다.

### 구현 작업자 실행 결과

- Muse Spark 1.3 Free: Paseo 에이전트 `2b5cf5ce-58cd-4440-8024-f327d2ad1611`, OpenCode 모델 `opencode/muse-spark-1.3-contributor-free`, 추론 `high`로 위임했다. 실제 호출은 HTTP 410 `ModelDeprecated`로 실패했다. 기존 세션의 모델 설정 변경 후에도 이전 Muse 오류가 반환돼 대체 모델은 새 세션으로 실행했다.
- Space Bunny Free: Paseo 에이전트 `fc519dc8-d7af-42ce-8337-2efc0f905ded`, OpenCode 모델 `opencode/space-bunny-free`, 추론 `high`로 위임했다. 실제 호출은 HTTP 410 `ModelDeprecated`로 실패했다. 서버가 안내한 대체 ID는 `minimax-m3.1-flash-free`지만 실제 제공 목록과 사용 가능 여부는 미확인이다.
- 모델 목록에는 두 모델이 남아 있었으나 실제 호출은 모두 제공 중단을 반환했다. 구현 코드와 테스트는 실행되지 않았다. 명세 문제가 아닌 지정 모델의 사용 불가 상태이며, 대체 작업자 선택만 사용자에게 확인했다. P0~P4는 승인됐지만 미착수 상태다.
- 재개: 대체 작업자가 결정되면 실제 모델 목록과 비용·추론 옵션을 확인하고, 기존 COST 작업 공간에서 이 인덱스와 상세 명세 11절 P0부터 구현한다. 앞선 두 실패 호출을 반복하지 않는다. 운영 배포·실제 명단 등록은 계속 범위 밖이다.

### OpenCode 업데이트 후 재시도

사용자 후속 지시로 `opencode upgrade --method npm`을 실행했고 종료 코드 0과 `Upgrade complete`를 확인했다. `opencode --version`은 기존 `1.18.35`에서 `1.19.3`으로 바뀌었다. `opencode models opencode --refresh`도 종료 코드 0으로 완료됐다. 갱신한 목록에는 Muse Spark와 Space Bunny가 없고 `opencode/minimax-m3.1-flash-free`가 있다.

업데이트 후 두 지정 모델에 대해 파일 조회·도구 사용을 금지한 최소 응답 요청을 CLI로 각각 한 번 실행했다. 두 요청 모두 종료 코드 1과 `UnknownError / Unexpected server error`로 실패했으며, 앞선 HTTP 410과 같은 오류라고 단정하지 않는다. 재시도 오류 참조는 Muse `err_fcaf26bd`, Space Bunny `err_7b4f5f96`다. Paseo의 모델 목록 조회도 `Provider 'opencode' is not available`을 반환했다. 같은 시점 제공자 검사에서는 available로 표시돼 상태가 일치하지 않았다. Paseo 재시작이나 앱 복구는 수행하지 않았다. 지정 모델의 구현은 여전히 미착수이고 대체 모델은 임의 실행하지 않았다.

### 구현 실행 결과 (2026-10-20)

실행 경로: OpenCode 1.19.3, 모델 `opencode/minimax-m3.1-flash-free`, 추론 high, 작업 공간 `C:/AX/cost`, 착수 HEAD `a1efbda`. 앞선 Muse Spark·Space Bunny 실패 호출은 반복하지 않았다.

커밋(모두 `main`, 다른 작업의 아고다 변경 미포함):

| 커밋 | 내용 |
| --- | --- |
| `945c218` | P0 참가자 명단 수신·저장 (`app/participant_roster.py`, `tools/ingest_participant_roster.py`) |
| `650b730` | P1 Google 수입 이름 인덱스 (`app/google_authority.py`, `webapp/google_ledger_page.py`) |
| `b2366f2` | P2 대조·수동 결정 (`app/participant_income.py`) |
| `a14a414` | P3 관리자 전용 화면·API (`webapp/participant_income_page.py`, `webapp/ledger_board.py`, `webapp/access_control.py`) |
| `b94204c` | P4 합성 통합 확인 (`tests/card_pipeline/test_participant_integration.py`) |

구현한 경계:

- P0: `manifest.json`·`participants.json` 필드·타입·해시·페이지·경로 검증, 개인정보 필드 거부, 여행 연결 확인(`TRIP_MAPPING_REQUIRED` 보류), 참가 확정 저장, 부분 명단·판독 대기, 재수신 멱등성, 같은 배치 id 충돌(`SOURCE_ID_CONFLICT`), 이름 변경 정정 제안, 같은 사람의 항목 재사용, 명단 트랜잭션과 동시 등록.
- P1: 이름·닉네임이 있는 수입 행을 금액 집계와 분리된 비공개 이름 인덱스로 저장. 금액 행·합계·오류 플래그 계약은 그대로이고, 이름 인덱스가 없는 세대·비표준 탭·오래된 동기화는 누락 판정을 보류한다.
- P2: 유일한 이름 일치만 자동 연결하고 동명이인·복수입금은 `연결 확인 필요`로 남긴다. 수동 연결·해제·공동입금·정정·별칭·같은 사람 확인을 저장하고, 원문 지문이 바뀌면 그 연결만 `연결 확인 필요`로 되돌린다. 사용자가 해제한 행은 이름이 맞아도 다시 연결하지 않는다. 입금 행은 고유 원본 행을 한 번만 센다.
- P3: `/participants`, `/api/participants/state`, `/api/participants/link`, `/api/participants/unlink`, `/api/participants/participant`. 소유자 세션만 처리하고, 일반 열람자는 403, 익명 요청은 401로 거절한다. 기존 장부 화면·기존 API·XLSX에는 실명·참가 표시·원본 경로가 들어가지 않는다. 오래된 화면의 결정은 409 `STALE_RECONCILIATION`으로 거절한다.

실제로 실행한 검증(모두 변경 기능과 직접 인접 계약에 한정):

| 명령 | 결과 |
| --- | --- |
| `python -m pytest tests/card_pipeline/test_participant_roster.py -q` | 23 passed |
| `python -m pytest tests/card_pipeline/test_participant_income.py -q` | 19 passed |
| `python -m pytest tests/card_pipeline/test_participant_integration.py -q` | 1 passed |
| `python -m pytest tests/card_pipeline/test_google_authority.py -q -k participant` | 6 passed, 52 deselected |
| `python -m pytest tests/card_pipeline/test_google_authority.py -q` | 58 passed |
| `python -m pytest webapp/tests/test_participant_income.py -q` | 8 passed |
| `python -m pytest webapp/tests/test_access_control_phase7.py -q` | 47 passed |

기존 실패(변경과 무관): `webapp/tests/test_google_ledger_page.py` 23건, `webapp/tests/test_google_canonical_workflow.py` 5건, `webapp/tests/test_google_viewer_http.py` 6건은 기준 커밋 `945c218`을 별도 worktree로 체크아웃해 그대로 실패함을 확인했다. Google 장부 화면 경로가 이미 제거된 뒤 남은 테스트이며 이번 변경과 무관해 고치지 않았다.

의도적 생략과 이유:

- 전체 pytest·전체 브라우저 E2E·OTA 전수 대사·전체 회귀는 실행하지 않았다. 카드·OTA 연결과 회계 쓰기를 건드리지 않고, 위 표적 검사와 인접 통합 검사만으로 변경 범위를 확인했다.
- 운영 배포·운영 스키마 변경·운영 DB 확인·브라우저 E2E는 하지 않았다. 승인 범위가 구현까지이고 운영 적용은 별도 승인 단계다.
- 실명 명단 등록·실제 여행 연결·Google 쓰기는 하지 않았다. 실제 자료와 여행 참조가 필요하고 원본을 건드리지 않는 것이 이번 범위다.

실제 차단:

- 없음. 지정 모델 호출과 표적 테스트가 모두 정상 실행됐다.

### Supervisor 검토 반영 (2026-10-20, 같은 모델 작업자)

Supervisor가 초기 구현을 검토해 지적한 결함을 반영했다. 기능 확장이 아니라 원래 명세의 누락과 결함을 고친 것이고, 지적 항목은 모두 코드와 표적 검사로 닫았다.

| 지적 | 반영 |
| --- | --- |
| 같은 배치 재전달이 최초 결과와 개수를 바꾸고 이력을 다시 썼다 | 같은 지문의 재전달은 최초 결과·등록시각·개수를 그대로 돌려주고 항목과 감사 이력을 다시 쓰지 않는다(`945c218` 이후 보강). 보류→연결 전이만 따로 허용한다. |
| `PARSER_VERSION`이 두 번 정의돼 이름 인덱스를 만들지 못했다 | 정의를 하나로 정리해 실제 세대가 `quarter-expense-v2`다. 구버전 스냅샷도 같은 workbook 해시여도 다시 읽어 이름 인덱스를 만든다. |
| 수동 해제 결정을 전달해도 이름이 다시 연결됐다 | 명시적으로 해제한 쌍은 자동 연결하지 않고 기존 결정을 보존한다. |
| 쓰기에 지문·여행·ref 검증과 원자성이 없었다 | 모든 쓰기가 지문을 필수로 받고, 참가자의 현재 여행 소속·현재 정본에 있는 수입 행·실제 여행 대상을 확인한 뒤 한 트랜잭션으로 결정과 이력을 함께 남긴다. 지문은 수동 결정 revision을 포함한다. |
| 정본 선택을 수동 기록에만 의존했다 | 기존 `owner_payload` 정본 선택 계약을 재사용해 한 사본뿐인 여행도 연결된다. 원본 수입 행과 이름 인덱스를 고유 행 기준으로 합쳐 이름이 공란인 금액 행도 잃지 않는다. |
| 화면에서 임의 수입 행 연결·정정·별칭·동일인 확인이 없었다 | 참가자별 폼으로 임의 행 연결(대리·공동입금), 이름 정정, 여행 연결 수정, 별칭 확인, 같은 사람 확인, 서로 다른 사람 확인을 제공한다. 근거는 내부 상태 문자열 대신 설명으로 보여 준다. |
| 참가 확정 인원이 이름 연결 상태에 따라 줄었다 | 명단으로 확정된 활성 참가자 전체를 참가 인원으로 세고 대조 확인 대상은 따로 센다. 미연결 수입의 명시적 검토 결정을 저장·표시한다. |
| 문서를 완료로 표시했다 | 아래 검토 반영 뒤에만 완료로 갱신한다. |

이 반영으로 추가·보강한 커밋: `8f20e84`(재전달·파서 세대·지문·참가 확정 분리), `3a67c41`(쓰기 안전·여행 연결 수정·0원 표기·동명이인), `65af90c`(표적 검사), `6bf27f3`(여행 상세 수입 영역의 관리자 링크), `e47a6f6`(대조 실행 기록), `3512731`(대조 이력에 완료 여부 보존).

마지막 이력 저장 결함: 결정 뒤의 실제 대조 상태를 다시 계산해 이력으로 남기고, 명단 범위가
아니라 실제 명단 버전과 Google 세대를 기록한다. 이력 요약에는 인원 집계와 함께 완료 여부와
보류 이유를 보존하고, 같은 입력 재기록은 기존 완료 이력을 덮지 않는다. 변경 이력 경계의
검사 1개와 인접 검사 1개만 새로 실행했다: `python -m pytest
tests/card_pipeline/test_participant_income.py -q -k run_history` → 1 passed, `python -m pytest
webapp/tests/test_participant_income.py -q` → 27 passed. 나머지 통과 근거는 이전 결과를
재사용했다.

실제로 실행한 검증(변경 기능과 직접 인접 계약에 한정):

| 명령 | 결과 |
| --- | --- |
| `python -m pytest tests/card_pipeline/test_participant_roster.py -q` | 23 passed |
| `python -m pytest tests/card_pipeline/test_participant_income.py -q` | 25 passed |
| `python -m pytest tests/card_pipeline/test_participant_integration.py -q` | 1 passed |
| `python -m pytest tests/card_pipeline/test_google_authority.py -q` | 59 passed |
| `python -m pytest webapp/tests/test_participant_income.py -q` | 27 passed (합성 브라우저 흐름 1건 포함) |
| `python -m pytest webapp/tests/test_trip_google_income.py -q` | 16 passed |
| `python -m pytest webapp/tests/test_access_control_phase7.py -q` | 47 passed |

합성 브라우저 흐름은 소유자 세션으로 참가 대조 화면을 열어 이름만 있는 수입 행을 골라 연결하고, 결과가 `수동 연결`로 남는 것까지 한 번 확인했다. 전체 브라우저·전체 회귀는 반복하지 않았다.

재개점: 실명 명단을 등록하려면 `.local-archive/participant-rosters/<batch_id>/`에 `manifest.json`·`participants.json`·`sources/`를 놓고 `tools/ingest_participant_roster.py --batch-dir <경로> --db .local-archive/participant-rosters/participant.sqlite --mapping <google-tab-mapping.json>`을 실행한다. 여행 연결이 모호하면 `TRIP_MAPPING_REQUIRED`로 보류되고 참가 확정은 저장되지 않는다. 그다음 소유자 계정으로 `/participants?trip=<탭 id>`에서 대조를 확인한다.

## 변경 파일과 보호 범위

이 문서 작업의 파일은 이 인덱스, [상세 명세](participant-income-reconciliation-spec.md), [README](../README.md), [상위 목표 명세](target-workflow-google-authority.md)다. 원본 명단과 실명은 포함하지 않는다.

작업 시작 시 `main`의 HEAD는 `8aaf09c`였다. 기존 변경 `app/ota_portal.py`, `docs/session_handoff.md`와 미추적 `app/agoda_capture.py`, `docs/trip-booking-mail-investigation.md`, `tests/card_pipeline/test_agoda_capture.py`, `tools/ingest_agoda_aside.py`는 별도 작업으로 보존한다. 기존 변경은 이번 커밋에 포함하지 않는다.

문서 검증은 변경 diff, 상대 링크, 상태 선언과 개인정보 없는 합성 예시를 확인한다. 문서만 바꾸므로 코드 테스트·빌드·브라우저·운영 DB 조회·백업·배포·재시작은 수행하지 않는다. 실제 검사와 커밋 결과는 완료 보고와 Git 이력으로 확인한다.

후속 구현(P0~P4)에서 만든 파일은 `app/participant_roster.py`, `app/participant_income.py`, `webapp/participant_income_page.py`, `tools/ingest_participant_roster.py`, `tests/card_pipeline/test_participant_roster.py`, `tests/card_pipeline/test_participant_income.py`, `tests/card_pipeline/test_participant_integration.py`, `webapp/tests/test_participant_income.py`이고, 수정한 파일은 `app/google_authority.py`, `webapp/google_ledger_page.py`, `webapp/ledger_board.py`, `webapp/access_control.py`, `tests/card_pipeline/test_google_authority.py`, `README.md`, 이 문서와 상세 명세다. 위의 아고다 변경 파일은 이번 구현에서도 수정·stage하지 않았다.

## 세션 인수 기록

2026-10-20 Paseo 세션 `7356c450-1d14-43e9-bf90-b0c8d636faa1`의 사용자 요청과 활동 기록을 인수했다. 원래 요청은 계획·명세 작성이며, 이전 세션은 사용량 한도로 중단됐다. 남아 있던 문서 초안을 검토해 이 범위만 완료한다. 원본 첨부 사진은 이번 인수 과정에서 열람하지 않았고, 실제 명단 전사나 여행 연결을 완료했다고 주장하지 않는다.

코드 근거로 `app/google_authority.py`의 `_sum_block`이 유효한 정수 금액 행만 상세 자료에 넣는 동작과 `webapp/google_ledger_page.py`의 `owner_rows`가 그 자료를 사용하는 경로를 확인했다. `.local-archive`의 Git 제외 설정과 P1에서 사용할 기존 테스트 파일의 존재도 확인했다. 문서 검사는 이번 작업의 네 문서에 있는 상대 링크와 상태 선언, diff 형식으로 한정한다.

검증 결과: 문서 4개의 로컬 상대 링크 37개가 존재하며, SPEC은 COMPLETE이고 P0~P4는 PLANNED인 상태가 일치했다. 추적 문서의 `git diff --check`도 통과했다. 코드 테스트·빌드·운영 조회·배포는 문서 변경에 필요하지 않아 생략했다. 원래 요청에 남은 문서 작업은 없으며 구현 단계는 후속 요청 전까지 실행하지 않는다.

## 다음 정확한 시작점

구현(P0~P4)은 완료했다. 다음 단계는 승인 뒤에만 진행한다.

```powershell
Get-Content -Encoding UTF8 docs/participant-income-task-index.md
Get-Content -Encoding UTF8 docs/participant-income-reconciliation-spec.md
git status --short
```

실제 첨부 명단 등록에는 기존 Google 여행 참조와 전사 자료가 필요하다. 여행 참조가 없으면 해당 등록만 대기하고, 이미 만든 합성 구현 경로와는 분리한다. 운영 적용(배포·운영 스키마·운영 DB)을 시작하기 전에 복구 사본과 복원 확인을 먼저 수행한다.
