# Suite 3 기준 비교 원인 및 조정 (2026-11-13)

PR #842 독립 검수의 G4 후보 중 앞서 보류한 12개 사례를 합성 fixture로 다시 대조했다. 최초 실패 원인을 커밋 이력과 병합된 PR 근거까지 연결했고, 승인된 동작 변화만 테스트 비교에서 명시적으로 수용했다. 고객 데이터·운영 DB·운영 포트는 사용하지 않았다. 골든 파일이나 생성 스크립트는 없고, 테스트가 과거 Git revision을 직접 불러 비교한다.

## 확인한 차이와 원인

| 차이 | 최초 원인 | 승인 근거 | 판정 및 비교 범위 |
|---|---|---|---|
| 정리 화면의 `classification`·빈 사유 키 | `4ef19b67` (`feat: retire card action queue in favor of destinations`, PR #737)에서 사람이 답하는 작업함과 과거 사유 taxonomy를 폐지. 현 `REASON_LABELS`는 `evidence`·`finance`만 지원 | PR #737은 P3 작업 큐 폐지와 목적지 화면 전환을 승인 | 의도된 UI 계약 변화. 옛 렌더러에만 역사적 synthetic 라벨을 주입해 옛 화면의 행 모집단·HTML·SELECT 횟수를 계속 비교한다. 새 렌더러 출력으로 기대값을 대체하지 않는다. |
| `reconsider=True`의 예약 근거·digest 차이 | `8bc945ff` (`fix: correct recorded automatic trips from booking service periods`)에서 명시적 재검토 중 자동 추론 행에 검증된 예약 서비스기간 근거를 적용 | 해당 커밋은 자동 기록 행도 예약 근거로 교정하고 그 근거를 classification basis로 남김. 수동/과거 이력 보호 분기는 유지 | 의도된 근거 문자열 변경. 전체 target, summary, 그 외 필드는 옛 계획과 비교하고, 해당 basis 변경에 따른 digest 변경과 반복 호출 결정성을 확인한다. `history=True` 사례는 무조정 전체 비교다. |
| 재사용 계획의 분기 종착지·digest 차이 | `fe7c97a7` (`fix: end generic preparation costs in the payment quarter`, PR #819) | PR #819 및 PROC-004: 기간 밖 일반 준비 비용은 결제일 기준 분기 기타비용으로 종결하고 일반 준비기간 추론을 폐지 | 의도된 귀속·근거 변경. `unclassified`에서 `quarter:Y:Q`로 바뀌는 대상 필드만 승인된 값으로 변환해 비교한다. 다른 target 필드와 summary는 옛 결과와 계속 비교하며, digest 변경 및 반복 호출 결정성을 확인한다. |

## 사례별 처리

| # | 합성 사례 | 확인된 변경 | 처리 |
|---:|---|---|---|
| 1 | cleanup `[all-1]` | 과거 `classification` 라벨 제거로 옛 렌더러 `KeyError` 발생 | PR #737 근거를 반영한 옛 라벨 주입 후 모집단·HTML·조회 수 비교 유지 |
| 2 | cleanup `[all-2]` | 빈 사유 키의 과거 라벨 제거로 옛 렌더러 `KeyError` 발생 | 동일 |
| 3 | cleanup `[all-3]` | 과거 `classification` 라벨 제거로 옛 렌더러 `KeyError` 발생 | 동일 |
| 4 | cleanup `[classification-1]` | 과거 `classification` 라벨 제거로 옛 렌더러 `KeyError` 발생 | 동일 |
| 5 | cleanup `[evidence-1]` | 해당 사유 모집단에 포함된 옛 `classification` 항목 라벨 누락 | 동일 |
| 6 | cleanup `[finance-1]` | 해당 사유 모집단에 포함된 옛 `classification` 항목 라벨 누락 | 동일 |
| 7 | cleanup `[manual-2]` | 빈 사유 키의 과거 라벨 제거로 옛 렌더러 `KeyError` 발생 | 동일 |
| 8 | cleanup `[invalid-1]` | 과거 `classification` 라벨 제거로 옛 렌더러 `KeyError` 발생 | 동일 |
| 9 | automatic plan (`reconsider=True`, 선택 안 함, 이력 없음) | 예약 근거 basis 반영 및 digest 변화 | basis만 승인 근거로 조정, 나머지 전체 비교 |
| 10 | automatic plan (`reconsider=True`, 선택함, 이력 없음) | 예약 근거 basis 반영 및 digest 변화 | basis만 승인 근거로 조정, 나머지 전체 비교 |
| 11 | reused plan (`reconsider=False`) | 기간 밖 일반 비용이 결제일 분기 기타비용으로 종결 | PROC-004 귀속·근거 필드만 조정, 나머지 전체 비교 |
| 12 | reused plan (`reconsider=True`) | 기간 밖 일반 비용이 결제일 분기 기타비용으로 종결 | PROC-004 귀속·근거 필드만 조정, 나머지 전체 비교 |

## 검증

- 합성 fixture 표적 검사: `python -m pytest webapp/tests/test_cleanup_refactor.py webapp/tests/test_automatic_plan_refactor.py webapp/tests/test_classification_trip_reuse.py -q -ra` — **19 passed**.
- cleanup 과거 renderer는 역사적 라벨을 옛 renderer namespace에서만 사용한다. 실제 화면 코드와 금융 데이터는 수정하지 않았다.
- 계획 비교 보정은 승인된 basis/분기 fallback 값만 바꿔 대조한다. target ID 집합, 나머지 target 값, summary, 안정적 반복 결과 및 DB 무변경 검증을 유지한다.
- 앞선 PR #845 상태: 12 failed / 7 passed. 이번 변경은 기준 자료 생성/복사 0건, 설명된 비교 계약 조정 12건이다.
- 필수 영향 검사: `python tools/run_quality_checks.py --base origin/main --run` — **PASSED**, 136 passed / 0 skip, compile 통과. 실제 실행 대상 8개 테스트 파일; 데이터 guard 통과.

PR #845를 원인 분석 및 테스트 비교 수정 PR로 갱신한다. 병합하지 않는다.
