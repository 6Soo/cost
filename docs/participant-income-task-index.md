# 참가자·수입 대조 작업 인덱스

> 작업 단위: 보험가입 명단 기반 참가자 확정과 수입 대조
> 갱신일: 2026-10-20 KST
> 현재 명세: [버전 1.0](participant-income-reconciliation-spec.md)

이 인덱스는 이 기능의 현재 요청과 실행 범위만 관리한다. 다른 독립 작업의 승인·진행 상태를 변경하지 않는다. 과거 ACTIVE 문서를 구현 지시로 읽지 않는다.

| 작업 ID | 요구사항 | 상태 | 근거 또는 다음 단계 |
| --- | --- | --- | --- |
| SPEC | 계획 및 명세 작성 | COMPLETE | 사용자 요구, 기존 Google 수입 경계, 전달·대조·예외·화면·검증 계획을 명세에 기록했다. |
| P0 | 구조화 명단 수신·참가자 저장 | PLANNED | 구현 요청 전이다. 실제 DB에 기록하지 않았다. |
| P1 | 금액 없는 Google 이름 행 조회 | PLANNED | 현재 파서의 제외 경로를 확인했다. 코드 변경·검증은 미실행이다. |
| P2 | 수입 대조·연결·수동 결정 | PLANNED | 구현 요청 후 P0/P1 계약을 사용한다. |
| P3 | 관리자 참가자 대조 화면 | PLANNED | 기존 수입 화면의 읽기 경계와 권한을 유지한다. |
| P4 | 합성 통합 확인 | PLANNED | 구현된 경로만 한 번 검증한다. |

2026-10-20 후속 요청으로 P0~P4의 실제 구현을 승인받았다. 구현 작업자는 Muse Spark 1.3 Free이며 실패 시 Space Bunny Free로 전환한다. 표의 PLANNED는 아직 착수하지 않은 구현 항목을 뜻하며, 작업자가 착수·검증 근거에 맞춰 갱신한다. SPEC은 완료된 설계 근거로 유지한다. 운영 배포와 실제 고객 명단 등록은 이번 요청에 포함되지 않는다.

구현은 기존 COST 작업 공간에서 작업자 한 명이 담당한다. Supervisor는 요구 해석과 읽기 전용 검토를 맡고 같은 파일을 동시에 수정하지 않는다. 전달 자료는 코드·명세·합성 자료로 제한하며 기존 미커밋 아고다 변경은 수정·stage하지 않는다. 설계·구현 방법은 현재 승인 범위 안에서 결정하고 다시 승인을 요청하지 않는다.

### 구현 작업자 실행 결과

- Muse Spark 1.3 Free: Paseo 에이전트 `2b5cf5ce-58cd-4440-8024-f327d2ad1611`, OpenCode 모델 `opencode/muse-spark-1.3-contributor-free`, 추론 `high`로 위임했다. 실제 호출은 HTTP 410 `ModelDeprecated`로 실패했다. 기존 세션의 모델 설정 변경 후에도 이전 Muse 오류가 반환돼 대체 모델은 새 세션으로 실행했다.
- Space Bunny Free: Paseo 에이전트 `fc519dc8-d7af-42ce-8337-2efc0f905ded`, OpenCode 모델 `opencode/space-bunny-free`, 추론 `high`로 위임했다. 실제 호출은 HTTP 410 `ModelDeprecated`로 실패했다. 서버가 안내한 대체 ID는 `minimax-m3.1-flash-free`지만 실제 제공 목록과 사용 가능 여부는 미확인이다.
- 모델 목록에는 두 모델이 남아 있었으나 실제 호출은 모두 제공 중단을 반환했다. 구현 코드와 테스트는 실행되지 않았다. 명세 문제가 아닌 지정 모델의 사용 불가 상태이며, 대체 작업자 선택만 사용자에게 확인했다. P0~P4는 승인됐지만 미착수 상태다.
- 재개: 대체 작업자가 결정되면 실제 모델 목록과 비용·추론 옵션을 확인하고, 기존 COST 작업 공간에서 이 인덱스와 상세 명세 11절 P0부터 구현한다. 앞선 두 실패 호출을 반복하지 않는다. 운영 배포·실제 명단 등록은 계속 범위 밖이다.

## 변경 파일과 보호 범위

이번 문서 작업의 파일은 이 인덱스, [상세 명세](participant-income-reconciliation-spec.md), [README](../README.md), [상위 목표 명세](target-workflow-google-authority.md)다. 원본 명단과 실명은 포함하지 않는다.

작업 시작 시 `main`의 HEAD는 `8aaf09c`였다. 기존 변경 `app/ota_portal.py`, `docs/session_handoff.md`와 미추적 `app/agoda_capture.py`, `docs/trip-booking-mail-investigation.md`, `tests/card_pipeline/test_agoda_capture.py`, `tools/ingest_agoda_aside.py`는 별도 작업으로 보존한다. 기존 변경은 이번 커밋에 포함하지 않는다.

문서 검증은 변경 diff, 상대 링크, 상태 선언과 개인정보 없는 합성 예시를 확인한다. 문서만 바꾸므로 코드 테스트·빌드·브라우저·운영 DB 조회·백업·배포·재시작은 수행하지 않는다. 실제 검사와 커밋 결과는 완료 보고와 Git 이력으로 확인한다.

## 세션 인수 기록

2026-10-20 Paseo 세션 `7356c450-1d14-43e9-bf90-b0c8d636faa1`의 사용자 요청과 활동 기록을 인수했다. 원래 요청은 계획·명세 작성이며, 이전 세션은 사용량 한도로 중단됐다. 남아 있던 문서 초안을 검토해 이 범위만 완료한다. 원본 첨부 사진은 이번 인수 과정에서 열람하지 않았고, 실제 명단 전사나 여행 연결을 완료했다고 주장하지 않는다.

코드 근거로 `app/google_authority.py`의 `_sum_block`이 유효한 정수 금액 행만 상세 자료에 넣는 동작과 `webapp/google_ledger_page.py`의 `owner_rows`가 그 자료를 사용하는 경로를 확인했다. `.local-archive`의 Git 제외 설정과 P1에서 사용할 기존 테스트 파일의 존재도 확인했다. 문서 검사는 이번 작업의 네 문서에 있는 상대 링크와 상태 선언, diff 형식으로 한정한다.

검증 결과: 문서 4개의 로컬 상대 링크 37개가 존재하며, SPEC은 COMPLETE이고 P0~P4는 PLANNED인 상태가 일치했다. 추적 문서의 `git diff --check`도 통과했다. 코드 테스트·빌드·운영 조회·배포는 문서 변경에 필요하지 않아 생략했다. 원래 요청에 남은 문서 작업은 없으며 구현 단계는 후속 요청 전까지 실행하지 않는다.

## 다음 정확한 시작점

사용자가 구현을 요청하면 다음 읽기 명령으로 진입한다. 명세 11절의 P0부터 시작하고 첫 구현의 테스트는 새 명단 수신 경로로 한정한다.

```powershell
Get-Content -Encoding UTF8 docs/participant-income-task-index.md
Get-Content -Encoding UTF8 docs/participant-income-reconciliation-spec.md
git status --short
```

실제 첨부 명단 등록에는 기존 Google 여행 참조와 전사 자료가 필요하다. 여행 참조가 없으면 해당 등록만 대기하고, 합성 자료를 사용하는 독립 구현을 차단하지 않는다.
