# 2026-10-28 AGODA 전액 상쇄·카카오 환불 매칭 실제 코드 수정 기록

- 상태: **CODE_WRITTEN / TESTS_ADDED_NOT_EXECUTED / NOT_DEPLOYED / REAL_DB_NOT_VERIFIED**
- 사용자 요청: 같은 원결제·취소 625,280원 AGODA 카드가 5차 지시 뒤에도 각각 검토 목록에 남고, 카카오 원결제 미연결 10건이 계속 보류되는 문제를 실제 코드로 고친다.
- 원본 거래, 사용자 수동 결정, Google 장부, 환불의 실제 카드사 반환 사실을 임의로 변경하거나 창작하지 않는다.

## 확인된 원인과 정정

1. 기존 `app/ledger.py::preview`는 단일 `import_batch_rows.batch_id`에 속하는 거래만 불러오고, `_apply_refund_pairs`는 상대 거래가 다른 배치에 있으면 `refund_original_missing/refund_group_incomplete`로 보류했다. 그런데 `app/partial_refund.py::refund_links`는 양쪽이 서로 다른 배치여도 원승인번호·동일 카드가 확실하면 관계를 알아볼 수 있다. 이 때문에 **화면은 상쇄를 표시하지만 실제 원장 기록은 묶음 미완료로 차단될 수 있었다.**
2. `webapp/card_flow.py::automatic_holds`도 일부 묶음이 현재 배치 밖에 있으면 검토 보류를 만들었다. 검증된 전액 상쇄에도 이 규칙이 작동할 수 있었다.
3. 카카오 T 택시의 원결제가 카드사 자료에서 `유페이일반결제` 등으로 기록된 경우, 기존 조회 후보의 가맹점 패밀리 동일 조건에서 제외됐다. 조회 후보가 0건이라도 원결제가 정말 없는 것은 아니다.
4. **과거 배치가 자동 기록에서 배제된다는 이전 분석은 정정한다.** 최신 `app/auto_record_policy.py::batch_is_new`는 DB에 배치가 존재하는지만 확인한다. 배치 일자가 오래됐다는 이유로 막지 않는다.

## 실제 코드 변경

- `app/ledger.py` + `app/__init__.py`:
  - 명시적으로 `include_verified_full_refunds=True`인 **automatic_record 전용** 미리보기·기장 경로에만, 원승인번호 등 기존 판정기로 확인된 `full/net_krw=0` 원결제·취소 전체 묶음을 다른 배치에서도 읽도록 확장한다.
  - 기존 일반 배치 검토/수동 그룹 commit 계약은 변하지 않는다. 금융 근거가 약한 `inferred=True`는 확장하지 않는다.
  - 두 원행이 함께 미리보기/동일 트랜잭션으로 기장되어야 성공. 금액은 원문 부호로 각각 남고 합계가 0원이다. 기록된 행은 기존 `_cleanup_card_where`의 `ledger_entries` 검사로 다시 미기록 목록에 등장하지 않는다.
  - 출처 배치가 다른 환불 원행은 각자 실제 `source_batch_id`와 함께 감사·게시하도록 한다. 미리보기 digest에 외부 출처 배치 ID를 포함해 바뀐 출처를 재검증한다.
- `webapp/card_flow.py`: 기존 owner 승인 `expense_bulk_maintenance` → `reclassify_cleanup`의 자동기장에 위 플래그를 사용한다. 검증된 전액 상쇄에 한해서 일반적인 임시 `classification_needed/trip_needed` 보류를 정리하되 원본 오류·중복·수동 보류·OTA 금융 보호는 유지한다. 과거 배치 정책에 관한 부정확한 주석을 고쳤다.
- `webapp/card_refund_query.py` + `webapp/card_evidence_ui.py`: 카카오T 취소의 **같은 카드·14일 이내** `유페이` 일반결제·택시 관련 명칭을 기존 원결제 비교 후보에 포함한다. 카카오페이·선물·주차·대리·다른 카드/기간은 후보에서 제외한다. 화면에 **결제중계 후보·미확정**임을 명확히 표시한다.
- `webapp/tests/test_verified_cross_batch_refunds.py`: (1) 다른 배치 원결제+취소 원자 기록/개별 배치/합계 0/재기록 0, (2) 일반 preview 무변경, (3) 추론/수동 보류 시 기록 0, (4) 실제 CardFlow 자동경로, (5) 카카오 유페이 가맹점 비교 후보만 표시하는 테스트를 추가했다.

## 완료 게이트 / 아직 해결됐다고 말할 수 없는 부분

1. **먼저 테스트 실행:** `python -m pytest -q webapp/tests/test_verified_cross_batch_refunds.py webapp/tests/test_cleanup_refund_display.py webapp/tests/test_refund_inference_runtime.py tests/card_pipeline/test_partial_refund.py`. 실제 결과를 기록하기 전 테스트 통과로 보고 금지.
2. 기존 환불 group/원본 중복/원승인번호/사용자 결정·환불 보류 범위의 인접 테스트 통과. Windows 운영 쓰기자·외부 작업자와 파일 소유권 충돌 점검.
3. **실제 데이터 운영 수락:** 승인된 SHA 배포·별도 복원 가능한 백업·13개 보호 테이블 전후 동일성 확인 후 검증된 AGODA 2026-09-22 +625,280/-625,280 두 원행의 기존 승인번호·각 import_batch·분류/보류/기장 상태 읽기 전용 조회. 해당 건에 대해 owner가 유지관리 미리보기·적용을 명시적으로 승인하고 0원/2행/상태표시/재실행 0을 확인. 금융 원본·Google 직접 수정 금지.
4. **카카오 10건 완결은 아님.** 실제 원승인번호가 없는 거래는 유페이 후보가 나와도 금융 연결이 확정된 게 아니다. 10건 각각 원승인번호/중복·충돌/부분취소/다른 날짜·카드 누락을 확인하고 실제 issuer 자료 또는 사용자 명시적 검토 결과를 받아야 한다. 조회 개선을 `39/39 확정`이라고 보고 금지.
5. PR 병합과 운영 SHA 배포는 별개다. 운영 DB 또는 UI에서 직접 검증하기 전에는 **AGODA가 화면에서 사라졌다/카카오가 모두 매칭됐다**고 말하면 안 된다.

참조: [금융 분류 정본](finance.md), [미결·운영 인계](../session_handoff.md), [운영 기록](../operations.md).
