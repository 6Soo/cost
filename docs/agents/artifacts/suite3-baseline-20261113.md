# Suite 3 기준 자료 재생성 판정 (2026-11-13)

PR #842 독립 검수의 G4 후보 12건을 요청된 조건에 따라 합성 fixture로 재실행했다. 결과는 12 failed / 7 passed. 고객 데이터·운영 DB·운영 포트를 사용하지 않았다. 기준 자료 생성 스크립트는 이 세 테스트에 없다. 각 테스트가 Git 이력의 기존 구현을 직접 불러와 비교한다.

## 건별 판정

| # | 테스트 건 | 과거 기준/생성 경로 | 관측된 차이 | 승인 근거 대조 | 처리 |
|---:|---|---|---|---|---|
| 1 | `test_cleanup_refactor` `[all-1]` | `55e304ad:webapp/card_flow.py`에서 AST로 `render_expense_cleanup`, `_cleanup_counts` 추출 | 과거 renderer가 현재 데이터의 `classification` 사유 키에서 `KeyError`를 내어 HTML/행 목록 비교 불가 | P3 #737은 사용자 확인 큐 폐지를 승인했지만 이 실패의 taxonomy key 변환 및 성능 동등성은 입증하지 않음 | 보류 |
| 2 | `test_cleanup_refactor` `[all-2]` | 동일 | 과거 renderer가 빈 사유 키에서 `KeyError` | #737의 큐 폐지로 설명 가능한지 불충분. 빈 키를 새 정답으로 정규화할 승인 근거 없음 | 보류 |
| 3 | `test_cleanup_refactor` `[all-3]` | 동일 | `classification` 키 `KeyError`; 화면 행/읽기 수 비교 불가 | #737은 renderer의 동등성을 새 결과로 대체하도록 승인하지 않음 | 보류 |
| 4 | `test_cleanup_refactor` `[classification-1]` | 동일 | `classification` 키 `KeyError` | taxonomy 변경의 승인 PR/규칙 ID가 실패를 정확히 설명하는지 확인되지 않음 | 보류 |
| 5 | `test_cleanup_refactor` `[evidence-1]` | 동일 | `classification` 키 `KeyError` | 위와 같음; 차이를 항목별 대조할 actual/expected 결과 자체가 없음 | 보류 |
| 6 | `test_cleanup_refactor` `[finance-1]` | 동일 | `classification` 키 `KeyError` | 위와 같음 | 보류 |
| 7 | `test_cleanup_refactor` `[manual-2]` | 동일 | 빈 사유 키 `KeyError` | 위와 같음; 빈 키 처리 변경을 승인된 계약으로 단정할 수 없음 | 보류 |
| 8 | `test_cleanup_refactor` `[invalid-1]` | 동일 | `classification` 키 `KeyError` | 위와 같음 | 보류 |
| 9 | `test_automatic_plan_refactor` (`reconsider=True`, 미선택; 합성 수동 이력 없음) | `55e304ad:app/automatic_classification.py`를 로드해 동일 합성 DB에서 plan/digest 비교 | `targets` 일부와 digest가 다름. 이 케이스는 `reconsider=True`에서 실패하고 `reconsider=False` 대응례는 통과 | PROC-004는 기간 없는 항목의 분기 종착지를 설명할 수 있지만 수동 이력이 포함된 전체 target 차이까지 설명한다는 증거가 부족함. 전체 차이 대조 완료 전 갱신 보류 | 보류 |
| 10 | `test_automatic_plan_refactor` (`reconsider=True`, 선택; 합성 수동 이력 없음) | 동일 | `targets` 일부와 digest가 다름 | PROC-004만으로 선택된 수동 이력 계획의 모든 필드 변화를 설명하지 못함 | 보류 |
| 11 | `test_classification_trip_reuse` (`reconsider=False`) | `tools.benchmark_expense_performance.baseline('114af50d')`; 그 revision의 `app/provisional_assignment.py` 및 `app/automatic_classification.py` 로드 | 현재 plan은 `quarter:2026:4`/기타비용으로 끝나지만 과거 구현은 `unclassified`/빈 탭을 냄; digest도 다름 | 결제일 분기 종착지는 DECISION_POLICY §3.2(6), PROC-004로 설명됨. 그러나 계획 전체의 차이를 필드별로 확정하는 안전한 기준 산출기가 확인되지 않아 대량 재기준선은 보류 | 보류 |
| 12 | `test_classification_trip_reuse` (`reconsider=True`) | 동일 | 위와 같은 종착지·plan/digest 차이 | PROC-004가 관측된 귀속 차이를 설명하지만 전체 구조 차이의 항목별 확인은 미완료 | 보류 |

## 검증과 제한

- 실행 명령: `python -m pytest webapp/tests/test_cleanup_refactor.py webapp/tests/test_automatic_plan_refactor.py webapp/tests/test_classification_trip_reuse.py -q -ra`
- 결과: **12 failed / 7 passed**, 30.38초. cleanup 8건은 과거 renderer의 `KeyError`로 비교 전에 실패. 계획 비교 4건 중 2건은 `reconsider=True` 전체 계획 비교, 2건은 재사용 계획 사례다. 자동 계획 실패 사례의 `history`는 모두 false다.
- 이전 첫 시도는 잘못된 `web/tests/...` 경로로 실패했고 테스트를 실행하지 않았다.
- 자동 계획 두 테스트의 `reconsider=True` 합성 설정에서 관측된 텍스트 차이는 현재 `기타비용` 대 과거 “기간 추론 0일” 근거다. PROC-004와 맞는 부분이지만 그것만으로 모든 digest 필드 변경을 설명한다고 간주하지 않았다.
- 기준 자료는 하나도 갱신하지 않았다. 현재 구현 결과를 골든으로 복사하거나 과거 renderer/계획을 우회하는 shim도 두지 않았다. 차이 항목을 완전 비교할 수 있는 독립 기준 절차와 승인된 변경 연결이 확인되면 재검토한다.
- 영향 기반 품질 검사 결과는 PR 설명에 기재한다. 이 PR은 artifact 기록만 포함하며 운영 코드는 변경하지 않는다.
