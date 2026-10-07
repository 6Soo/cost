# Isolated OTA review pilot 계획

## 이번 Git 병합과 실행 경계

2026-10-08에 검토를 통과한 `feature/ota-first-review-20261008`의 `ba1c12b4773ad23af55e4f4cb49d6ac35d099b68`을 기존 main `37bd457341d68185d533a243eada64162537f943`에서 fast-forward로 병합했습니다. 병합 당시 feature는 3 commits ahead / 0 behind였고 충돌은 없었습니다. 추가 코드는 수정하지 않았으며 추가 테스트도 실행하지 않았습니다. 이 계획 문서만 별도 커밋합니다.

Git main 병합은 운영 배포나 OTA-first authority 전환을 뜻하지 않습니다. 운영 체크아웃 `C:/AX/cost`는 기존 `37bd457341d68185d533a243eada64162537f943`에 detached HEAD로 고정하고 미커밋 변경과 사용자 파일을 보존합니다. main Git 작업은 기존 격리 worktree `C:/AX/cost-ota-first-review-20261008`에서 진행합니다. 운영 재시작, 운영 DB 쓰기, review DB 생성, OTA 재대사, source refresh, reclassification은 이번 단계에서 실행하지 않습니다.

기존 수치와 검증을 재사용합니다. 아래 수치는 이번 단계에서 다시 실행한 결과가 아닙니다.

- 실제 OTA payment: 383건, matched: 200건, HOLD: 183건입니다.
- 기존 exact 200건은 동일 카드에 고정됐고 duplicate assignment는 0건입니다.
- 기존 ledger rows 734건과 사용자 확정, 보류, 원본을 보존했습니다.
- 기존 core/UI targeted는 84 passed입니다.
- merge safety targeted는 7 passed / 2 subtests passed입니다.
- full regression은 2394 passed / 1 known unrelated doc failure / 3 skipped / 2398 subtests passed입니다. 해당 문서는 복구했고 해당 test만 1 passed로 확인했습니다. 전체 회귀는 반복하지 않습니다.

상세 기록은 [기존 검증 보고서](ota-first-verification-report.md)를 따릅니다. 보고서의 main과 검토 브랜치 상태는 병합 전 기록이며, 이번 병합의 경계는 이 문서를 따릅니다.

## 다음 단계의 목적과 시작 조건

다음 단계는 사용자가 별도로 실행을 승인한 뒤 시작할 isolated OTA review pilot입니다. 현재는 계획만 기록했으며 pilot 프로세스와 review DB를 만들지 않았습니다. OTA-first를 production authority로 전환하지 않습니다.

기존 정확 연결 200건을 유지하고 HOLD 183건만 검토 대상으로 표시합니다. 운영 장부 DB는 읽기 전용으로 사용하고, 수동 연결과 proposal은 운영 장부와 분리된 pilot review DB에만 저장하는 경계를 먼저 확인합니다. pilot 환경 설정은 기존 `WEBLEDGER_OTA_REVIEW_MODE=isolated`와 별도 `WEBLEDGER_OTA_REVIEW_DB`를 사용합니다. 실제 경로와 접근 방식은 pilot 시작 전에 정하며, 이 문서에는 고객 자료나 비밀값을 넣지 않습니다.

pilot 시작 전에는 복구 사본과 읽기 전용 접근을 확인하고 기존 exact 링크, 사용자 확정, 보류, 전체 업무 테이블과 원본의 비교 기준을 로컬에 보존합니다. 원본을 재수집하거나 새 분류를 실행하지 않습니다. 합계만 같다는 이유로 보존을 판정하지 않습니다.

## 대표 HOLD 선택

처음에는 5~10건만 선택합니다. 목표는 가능한 경우 8건을 네 유형에서 고르게 고르는 것이며, 실제 사례 수에 맞춰 조정합니다. 현재 HOLD 전체는 카드 없음 90건, 날짜 미확인 59건, 모호 21건, 금액 불일치 13건입니다.

| 유형 | 초기 선택 목표 | 확인할 내용 |
| --- | ---: | --- |
| HOLD_NO_CARD | 2건 | 같은 날짜의 모든 카드 표시 또는 거래 없음 안내를 확인합니다. 적절한 거래가 없으면 연결하지 않습니다. |
| HOLD_DATE_UNKNOWN | 2건 | 결제일 미확인 안내와 선택 불가를 확인합니다. 날짜를 추정하거나 억지 연결하지 않습니다. |
| HOLD_AMBIGUOUS | 2건 | 후보를 숨기지 않고 표시하는지 확인하고, 사용자가 실제 거래를 확인한 경우에만 수동 연결합니다. |
| HOLD_AMOUNT_MISMATCH | 2건 | 미리 보기의 실제 부호 있는 차액과 사용자 확정을 확인합니다. 차액을 할인으로 단정하지 않습니다. |

수동 연결 후 실제 rule proposal을 확인할 수 있는 사례를 우선 포함합니다. 대표 사례에 중복·파싱 오류·거래 충돌 행이 있으면 표시와 선택 차단도 확인합니다. 실제 자료에 없는 유형을 만들기 위해 원본이나 거래를 수정하지 않습니다.

## pilot 확인 순서

1. 실제 UI의 HOLD queue가 183건인지 확인합니다. 기존 exact 200건이 같은 카드에 고정됐는지 별도로 확인하며, 서로 다른 집계인 과거 카드 미연결 177건과 혼동하지 않습니다.
2. 결제일이 있는 대표 OTA마다 같은 결제일의 모든 카드 거래가 표시되는지 확인합니다. merchant나 금액으로 숨기지 않습니다. 결제일이 없으면 설명만 확인합니다.
3. 이미 연결된 카드와 `duplicate_of`, `parse_error`, `conflict_reason`이 있는 카드는 표시되지만 선택할 수 없어야 합니다. 각각 연결 표시 또는 중복 거래, 파싱 오류, 거래 충돌 사유가 보여야 합니다. 정상 거래는 선택할 수 있어야 합니다.
4. 사용자가 선택한 카드의 preview에서 OTA 금액, 카드 금액, 실제 차액, 날짜, 거래 방향을 확인합니다. 사용자가 명시적으로 확정한 경우에만 분리 review DB에 수동 연결을 저장합니다.
5. 수동 연결 뒤 MATCHED_USER가 유지되고 proposal만 생성되는지 확인합니다. 사용자의 규칙 승인 전에는 active rule이 생성되면 안 됩니다. 에이전트는 proposal의 사실과 좁은 조건을 사용자에게 질문하며, 할인이나 날짜 차이의 원인을 단정하지 않습니다.
6. 사용자가 “이번 건만”을 선택한 사례는 이후 OTA에 규칙으로 적용되지 않는지 확인합니다. “규칙 저장”을 명시 승인한 사례만 좁은 동일 조건의 다음 OTA에 적용되는지 확인합니다. 맞는 후속 사례가 없으면 미확인으로 기록하며 거래를 만들어내지 않습니다.
7. 390×844와 1440×900에서 거래 목록, 선택 상태, 차액, 확정, proposal 상태와 가로 넘침을 확인합니다.
8. pilot 전후 기존 exact 링크와 카드 점유, 사용자 확정, 보류, 장부와 원본을 비교합니다. 기존 exact 재연결, 카드 중복 배정, 사용자 확정 덮어쓰기 또는 운영 데이터 변경이 발견되면 pilot을 중단하고 로컬 근거를 남깁니다.

## pilot 결과와 다음 결정

대표 사례별로 확인한 UI 동작, 사용자의 수동 선택과 답변, proposal 상태, 승인된 규칙의 범위, 이후 사례 적용 여부를 로컬에 기록합니다. 미확인 항목과 실제 검증한 결과를 구분하며 고객 원문과 실제 식별자는 Git에 넣지 않습니다.

pilot을 마쳐도 전체 HOLD를 일괄 처리하거나 production authority로 자동 전환하지 않습니다. 대표 5~10건의 결과를 사용자에게 보고한 뒤 나머지 검토와 별도 production cutover 여부를 결정합니다.
