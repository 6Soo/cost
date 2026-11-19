# M6 단일 장부 테이블 통합 — 공통 계약

이 문서는 병렬 작업자 전원이 따르는 **불변 계약**이다. 이 문서를 바꾸려면 별도 승인을 받는다.

## 목표

`transactions`(원본) · `ledger_entries`(기장 기록) · `board_rows`(화면 장부)를 **단일 정본 테이블 `ledger`** 로 통합한다.

현재 문제(2026-11-17 실측):
- `ledger_entries` ↔ `board_rows`는 1:1이지만 **쓰기 코드가 분리**되어 있어 drift 286건
- 화면용 `board_rows`만 고치면 `ledger_entries`·`transactions`는 안 따라감 (11월 호남 15건)
- 세 테이블을 각자 읽는 SELECT 206 + 178곳

## 근거 — 데이터로 확인한 사실

운영 `board.sqlite` 읽기 전용 실측(2026-11-18):
- `transactions` 7,349 / `ledger_entries` 3,374 / `board_rows` 3,378
- `ledger_entries` 중복 `transaction_id` **0건**
- `board_rows` 카드 행 중복 `row_id` **0건**
- `board_rows` payload의 `display_tab_id` ↔ 컬럼 불일치 **0건**
- 카드 행 3,374 ↔ `ledger_entries` 3,374 → **정확히 1:1**
- 카드 아닌 `board_rows` 4건(수기 캐시 지출)은 `ledger_entries` 대응 없음

→ 통합 가능. 단 `transactions`는 **원본 보존**이므로 흡수하지 않고 유지한다.

## 대상 스키마

`app/db.py`의 `SCHEMA_SQL`에 새 테이블을 추가한다. 기존 `board_rows`·`ledger_entries`는 **읽기 호환 뷰**로 남긴다(단계적 전환).

```sql
CREATE TABLE IF NOT EXISTS ledger (
    entry_id            TEXT PRIMARY KEY,      -- 기존 row_id 그대로 (card-<txid>, man-*, etc)
    transaction_id      TEXT,                  -- 카드 거래면 transactions 참조, 수기면 NULL
    entry_kind          TEXT NOT NULL,         -- expense | income
    item                TEXT NOT NULL DEFAULT '',
    description         TEXT NOT NULL DEFAULT '',
    amount_krw          INTEGER,
    occurred_on         TEXT NOT NULL DEFAULT '',
    display_tab_id      TEXT,                  -- NULL = 미분류
    trip_id             TEXT NOT NULL DEFAULT '',
    service_period      TEXT NOT NULL DEFAULT '',
    reservation_no      TEXT NOT NULL DEFAULT '',
    evidence_type       TEXT NOT NULL DEFAULT '',
    source_kind         TEXT NOT NULL DEFAULT '',
    source_event_id     TEXT NOT NULL DEFAULT '',
    source_fact_digest  TEXT NOT NULL DEFAULT '',
    source_merchant     TEXT NOT NULL DEFAULT '',
    source_issuer       TEXT NOT NULL DEFAULT '',
    source_card_last4   TEXT NOT NULL DEFAULT '',
    source_approval_number TEXT NOT NULL DEFAULT '',
    source_approval_date   TEXT NOT NULL DEFAULT '',
    source_posting_date    TEXT NOT NULL DEFAULT '',
    source_local_amount    TEXT NOT NULL DEFAULT '',
    source_currency        TEXT NOT NULL DEFAULT '',
    event_kind             TEXT NOT NULL DEFAULT '',
    classification_state   TEXT NOT NULL DEFAULT '',
    classification_source  TEXT NOT NULL DEFAULT '',
    classification_basis   TEXT NOT NULL DEFAULT '',
    confirmed_by           TEXT NOT NULL DEFAULT '',
    memo                   TEXT NOT NULL DEFAULT '',
    operator_note          TEXT NOT NULL DEFAULT '',
    revision               INTEGER NOT NULL DEFAULT 1,
    committed_at           TEXT,               -- 기장 시각(구 ledger_entries.committed_at)
    batch_id               TEXT NOT NULL DEFAULT '',
    created_at             TEXT NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_ledger_transaction
    ON ledger(transaction_id) WHERE transaction_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_ledger_display_tab ON ledger(display_tab_id);
```

### 불변 규칙

1. **`entry_id`는 기존 `row_id`를 그대로 쓴다.** 새 ID를 만들지 않는다.
2. **`transactions`는 원본으로 남는다.** 읽기·쓰기 코드가 계속 참조한다. 흡수·삭제 금지.
3. **`display_tab_id`가 유일한 귀속 정본이다.** `trip_id`는 호환용으로만 유지하고 새 쓰기에서는 `display_tab_id`와 같게 채운다.
4. **금액·부호·원문·ID·`source_hash`는 절대 바꾸지 않는다.**
5. **PROC-072**: 완료 기간 자료는 `ledger`에 **저장하되** 판정 변형으로 구분한다. 별도 "수정금지" 상태 플래그를 만들지 않는다. 화면은 표시 여부만 결정한다(단위 5).
6. 기존 `board_rows`·`ledger_entries`는 **삭제하지 않는다.** 뷰로 전환하고 데이터는 보존한다.

## 병렬 분할 — 파일 소유권

각 단위는 **아래 파일만** 수정한다. 다른 단위의 파일을 건드리면 충돌로 간주한다.

| 단위 | 소유 파일 | 병렬 가능 |
| --- | --- | --- |
| **U1 스키마·뷰·이관** | `app/db.py`, `webapp/ledger_store_schema.py`, `tools/migrate_to_ledger.py`(신규), `tests/card_pipeline/test_ledger_schema.py`(신규) | 선행 필수 |
| **U2 저장소 읽기 경로** | `webapp/ledger_store.py`, `webapp/ledger_store_records.py` | U1 후 |
| **U3 쓰기 경로** | `app/ledger.py`, `app/quarter_tab.py`, `webapp/card_flow.py` | U1 후 |
| **U4 교정·재판정** | `app/automatic_classification.py`, `app/classification_correction.py`, `app/decision_provenance.py`, `app/closed_period_repair.py`, `app/bulk_confirmation_repair.py`, `app/card_hana_duplicate_repair.py`, `webapp/booking_period_rejudge.py` | U1 후 |
| **U5 표시·집계·도구** | `webapp/ledger_board.py`, `webapp/live_sync.py`, `webapp/card_catalog.py`, `webapp/refund_tab.py`, `webapp/card_cleanup_queries.py`, `webapp/card_completion_worker.py`, `webapp/autonomous_cleanup_worker.py`, `webapp/refund_cleanup_action.py`, `webapp/ota_catalog.py`, `webapp/receipt_ledger.py`, `webapp/trip_flight_read.py`, `webapp/ota_payment_review.py`, `webapp/ledger_design.py`, `app/expense_bulk_maintenance.py`, `app/card_export_profiles.py`, `app/company_expenses.py`, `app/classify.py`, `app/ota_exact.py`, `app/trip_correction_review.py`, `tools/*` | U1 후 |

**U2~U5는 서로 겹치지 않으므로 4개 동시 실행 가능.**

## 검증 기준

각 단위는 자기 검사를 통과해야 한다.

```powershell
# 영향 기반 (해당 단위 파일만)
python tools/run_quality_checks.py --base origin/main --run
```

공통 수락 조건:
- `skip` 0, known failure 외 실패 0
- `schema_differences == []` (기존 `test_ledger_store_schema.py` 골든 갱신 포함)
- 이관 후 대조: `ledger` 행 수 == 기존 `board_rows` + 카드 외 행, `transaction_id` 중복 0
- 금액 합계 불변: 여행별 `sum(amount_krw)` 이관 전후 동일

## 하지 않는 것

- 운영 DB 직접 쓰기 (이관은 사본에서 예행, 적용은 별도 승인)
- 원격 브랜치 push·강제 push
- `transactions` 삭제·스키마 변경
- 기존 `board_rows`·`ledger_entries` 데이터 삭제
- M6 전제(Python 퇴역)를 앞당기는 작업
