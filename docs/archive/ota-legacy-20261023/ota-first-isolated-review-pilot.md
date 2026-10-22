# Isolated OTA review pilot 실행 기록

## 2026-10-09 실제 실행 결과

기준 코드는 `main`의 `90296d69180e40266e8b553ea36d595c4ef66af6`이며 시작 시 원격 `origin/main`과 같았다. 운영 DB를 SQLite `mode=ro`와 `PRAGMA query_only=ON`으로 열고, 저장은 저장소 밖의 새 로컬 전용 pilot SQLite에만 수행했다. 운영 checkout과 production 프로세스는 갱신하지 않았다.

시작 기준은 정확 연결 200건, HOLD 183건, 장부 734행이다. 업무 테이블은 74개이며 SQLite 시스템 테이블을 포함하면 75개다. 기존 사용자 결정은 27건, 기존 review hold는 16건이었다. 원본과 manifest를 포함한 파일 963개의 digest, 모든 테이블의 행 digest, schema digest와 DB 파일 지문을 로컬에 보존했다. 원문과 거래 식별자, SQLite 파일, 화면 캡처는 Git에 포함하지 않는다.

대표 HOLD 8건을 선정했다. `HOLD_NO_CARD` 4건은 같은 결제일 카드 목록과 수동 검토를 확인하기 위해, `HOLD_DATE_UNKNOWN` 4건은 날짜가 없을 때 후보를 만들지 않는지 확인하기 위해 골랐다. 이번 실제 결과에는 다른 HOLD 유형이 없어 사례를 만들지 않았다. 390×844와 1440×900의 실제 Chromium 화면에서 날짜가 있는 각 사례의 카드 32행을 모두 표시했고, 날짜 미확인 사례는 카드 0행이었다. 두 화면의 가로 넘침과 JavaScript 오류는 0이었다.

격리 loopback HTTP 프로세스에서 기존 `render_import_section`, OTA `dispatch`와 실제 `CoreOtaPaymentBackend`를 실행했다. 운영 서버 전체를 시작한 것이 아니며 운영 장부 쓰기 경로와 worker는 연결하지 않았다. 대표 사례의 필터만 적용하고 카드 후보를 merchant나 금액으로 줄이지 않았다.

사용자가 앞서 허용한 동일 조건 거래의 승인번호 순서 배정 사례 1건을 실제 core backend의 preview와 confirm 경로로 저장했다. 개별 결제 증빙으로 두 거래를 구분했다고 주장하지 않는다. 별도 review DB의 manual link는 1건, proposal은 1건, active rule과 frozen group은 각각 0건이다. 새 backend와 화면 재조회에서 수동 연결과 proposal이 유지됐고, 검토 화면은 8건에서 7건으로 줄었다. 전체 읽기 전용 계산의 남은 HOLD는 182건이며 운영 HOLD와 운영 authority는 변경하지 않았다.

실제 이미 점유된 카드의 preview와 confirm은 서버에서 모두 거부했다. 실제 운영 거래의 `duplicate_of`, `parse_error`, `conflict_reason` 행은 각각 0건이므로 세 상태를 실제 자료로 검증했다고 표현하지 않는다. 각 상태의 표시·선택 비활성·서버 거부는 합성 회귀에서 검증했다. 실제 full/partial group 사례도 이번 표본에 없어 frozen group을 생성하지 않았다.

proposal은 provider·숙박 항목·가맹점·카드사·카드 끝자리·KRW charge·차액 0원·날짜 차이 0일로 제한된다. 메모리에서만 승인 표시를 주어 dry-run한 결과, 범위에 들어오는 HOLD event는 16건이고 기존 수동 연결 외에 새 자동 연결은 1건이었다. 범위에 들어온 16건 모두를 연결하는 규칙이 아니다. 기존 exact 변경과 중복 카드 배정은 0건이며 실제 규칙 활성화는 수행하지 않았다. 동일 날짜·동일 금액 거래의 개별 대응은 결제 원문만으로 증명되지 않을 수 있으므로 이 분석을 실제 연결 정답의 증명으로 해석하지 않는다.

기존 exact 200건의 OTA event identity, provider, booking, transaction ID와 evidence digest를 직접 비교해 200/200 동일, 변경 0, 누락 0을 확인했다. 각 카드 source hash도 로컬 pair 기록에 보존했다. 수동 연결 재조회는 성공했고 중복 카드 배정과 기존 exact 재사용은 0건이다.

검증 로그와 원본 비교 근거는 저장소 밖의 `C:/AX/ota-review-pilot-local-20261009`에만 보존한다. 이 경로의 review DB와 자료는 로컬 운영 증거이며 배포하거나 commit하지 않는다.

수동 저장과 dry-run 뒤에도 업무 테이블의 전체 행 digest, schema, 사용자 결정, 기존 hold, 장부 734행, 운영 DB 파일 지문과 원본 963개 파일 digest가 모두 같았다. 운영 DB 변경과 원본 변경은 0건이다. 별도 review DB에만 링크 1건과 미승인 제안 1건이 남는다. production authority 전환과 production 재시작은 수행하지 않았다.

OTA 관련 검사 254개와 하위 검사 4개가 통과했다. 새 격리 DB 수명주기 검사와 최종 변경된 UI·서버 검사 묶음은 34개와 하위 검사 4개가 통과했다. 기존 브라우저 fixture의 정확 금액 후보는 새 부분 묶음 보호 경계에 들어가 수동 선택이 차단됐으므로, 수동 연결·이번 건만·규칙 승인 검사의 fixture를 서로 다른 카드 힌트와 확인 가능한 금액 차이 사례로 바꿨다. 부분 묶음 보호 assertion을 약화하지 않았으며 오래된 점유 사유 기대값 두 개만 현재 식별자와 맞췄다.

저장소에는 기존 typecheck 설정이나 frontend build 명령이 없다. 저장소 밖에 mypy를 설치해 변경된 테스트 파일 3개를 `--check-untyped-defs --follow-imports=skip --ignore-missing-imports`로 검사했다. 이 검사는 변경된 테스트 코드의 검사이며 전체 production 코드의 타입 검사로 주장하지 않는다. Python production 실행 경로는 `compileall`로 컴파일했고 생성물은 저장소 밖에 두었다. 별도 frontend production bundle은 사용하는 구조가 아니다.

전체 기존 검증 명령 `python -m pytest -q -ra`의 결과는 **2426 passed / 3 skipped / 2386 subtests passed**, 종료 코드 0, 소요 시간 1211.78초다. skip은 기존 비공개 Agoda 자료 부재 2건과 Windows 파일 권한 제약 1건이다. 새 수명주기 검사는 전체 검사 수집 시작 뒤 추가했으므로 위 전체 건수에는 포함하지 않고 별도로 통과한 최종 targeted 34건에 포함했다. 변경된 테스트 파일 3개의 mypy 검사, Python 실행 코드 `compileall`, `git diff --check`도 종료 코드 0으로 통과했다. 테스트와 문서 외 제품 코드, 설정, 운영 데이터는 변경하지 않았다.

pilot의 저장·재조회·기존 정확 연결 보존과 운영 데이터 불변 검증은 완료했다. 실제 자료에 없는 세 오류 상태와 group의 실제 확인은 실행했다고 주장하지 않는다. 미승인 proposal 1건은 그대로 남겨 두며 다음 사용자 응답 없이 활성화하거나 나머지 HOLD를 처리하지 않는다.

## 2026-10-08 최초 Git 병합 기록

이 절은 최초 병합 당시의 기록이다. 이후 OTA 매칭 기본 규칙이 main에 병합됐으며 이번 pilot 기준은 위의 `90296d69180e40266e8b553ea36d595c4ef66af6`이다. 아래의 실행 금지 범위와 이전 검사 수치는 당시 단계에만 해당하며 2026-10-09의 실제 pilot 결과를 대신하지 않는다.

2026-10-08에 검토를 통과한 `feature/ota-first-review-20261008`의 `ba1c12b4773ad23af55e4f4cb49d6ac35d099b68`을 기존 main `37bd457341d68185d533a243eada64162537f943`에서 fast-forward로 병합했습니다. 병합 당시 feature는 3 commits ahead / 0 behind였고 충돌은 없었습니다. 추가 코드는 수정하지 않았으며 추가 테스트도 실행하지 않았습니다. 이 계획 문서만 별도 커밋합니다.

Git main 병합은 운영 배포나 OTA-first authority 전환을 뜻하지 않습니다. 운영 체크아웃 `C:/AX/cost`는 기존 `37bd457341d68185d533a243eada64162537f943`에 detached HEAD로 고정하고 미커밋 변경과 사용자 파일을 보존합니다. main Git 작업은 기존 격리 worktree `C:/AX/cost-ota-first-review-20261008`에서 진행합니다. 운영 재시작, 운영 DB 쓰기, review DB 생성, OTA 재대사, source refresh, reclassification은 이번 단계에서 실행하지 않습니다.

기존 수치와 검증을 재사용합니다. 아래 수치는 이번 단계에서 다시 실행한 결과가 아닙니다.

- 실제 OTA payment: 383건, matched: 200건, HOLD: 183건입니다.
- 기존 exact 200건은 동일 카드에 고정됐고 duplicate assignment는 0건입니다.
- 기존 ledger rows 734건과 사용자 확정, 보류, 원본을 보존했습니다.
- 기존 core/UI targeted는 84 passed입니다.
- merge safety targeted는 7 passed / 2 subtests passed입니다.
- full regression은 2394 passed / 1 known unrelated doc failure / 3 skipped / 2398 subtests passed입니다. 해당 문서는 복구했고 해당 test만 1 passed로 확인했습니다. 전체 회귀는 반복하지 않습니다.

상세 기록은 [기존 검증 보고서](../../../docs/ota-first-verification-report.md)를 따릅니다. 보고서의 main과 검토 브랜치 상태는 병합 전 기록이며, 이번 병합의 경계는 이 문서를 따릅니다.

## 다음 단계의 목적과 시작 조건

아래는 최초 pilot 계획과 보호 조건이다. 2026-10-09 사용자의 실행 지시에 따라 별도 pilot 프로세스와 review DB를 만들고 위 실행 결과를 확인했다. OTA-first를 production authority로 전환하지 않았다.

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
