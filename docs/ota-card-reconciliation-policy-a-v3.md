# COST V3 — OTA·카드 통합 대사 엔진: 사용자 확정 정책 A 구현 명세

> **문서 탐색·정책 충돌/현재 구현 여부:** 반드시 [COST V3 단일 개발 진입점](COST_V3_START_HERE.md)을 먼저 참조. 이 문서는 해당 기능의 세부 계약이며 과거 ETA/HOLD·운영 실측·아카이브 문서의 지시보다 2026-10-23 사용자 확정 정책을 우선한다.

> 2026-10-23 설계 확정. **상태: 구현·테스트·운영 배포 전.** 기존 [COST V3](cost-v3-inference-ai-passenger-nm-test-architecture.md) 정책을 보충한다. 변경 목표는 '양쪽 원본이 실제로 있으나 연결되지 않는' 사고를 줄이고 이유를 추적하는 것이다.  
> 이 명세는 무료 코딩 모델을 위한 구현 계약이다. 운영 데이터·사용자 확정·Google을 임의 수정하지 않는다. **Google 최종 장부 자동 쓰기는 금지**한다.

## 0. 사용자 확정 정책: OTA 링크와 카드 경비 기록 준비를 분리

**A 정책:** 카드 원본이 확정 매입이고 중복·원본 충돌·취소·환불 문제가 없다면 OTA 예약 연결이 불확실해도 **가장 개연성 높은 기존 여행에 자동 귀속**하고 **COST 내부 경비 기록 준비/미리보기**를 허용한다. AI는 이 거래가 어느 OTA 예약에 속하는지 추정해 후보로 보여 주며 나중에 사용자가 교정한다. **'기록 준비'는 새로운 무승인 SQLite 자동 쓰기나 Google 반영을 뜻하지 않는다.** 이미 운영에서 허용된 내부 기록 write path만 유지하고 기존 인증·revision·멱등성 검증을 수행한다.

각 거래는 아래 **독립 상태 축**을 가진다.

| 영역 | 허용 상태 | 권위 / 효과 |
| --- | --- | --- |
| 카드 금융 검증 | `ELIGIBLE / DUPLICATE / PARSE_CONFLICT / REFUND_UNRESOLVED / REVERSAL_UNRESOLVED / EXCLUDED / ALREADY_RECORDED` | 실제 매입 원본·원결제/환불·기존 장부 |
| OTA 링크 근거 | `EXACT / GROUP_RECONCILED / INFERRED / UNLINKED / CONFLICT` | 예약 또는 OTA 금전 사건과 카드의 관계만 |
| 여행 귀속 | `USER_ASSIGNED / AUTO_EVIDENCED / AUTO_INFERRED / NO_AUTHORIZED_TRIP` | 낮은 추론도 유효 여행이 있으면 귀속; 수동 이동 절대 우선 |
| 내부 경비 준비 | `READY_FOR_INTERNAL_SAVE / READY_ALREADY_SAVED / BLOCKED_FINANCIAL / NEEDS_AUTHORIZED_TRIP / EXCLUDED` | **카드 금융 검증을 중심으로** 결정 |
| Google 반영 | `NOT_COPIED / COPYABLE / POSTED_UNKNOWN / CONFIRMED_IN_GOOGLE` | 사용자 직접 붙여넣기, Google 읽기 전용 |

**핵심 불변조건:** `EXACT`/ `INFERRED`/ `UNLINKED`만 다른 동일 카드 거래는, 카드가 `ELIGIBLE`이고 여행이 정해졌다면 모두 `READY_FOR_INTERNAL_SAVE`를 반환한다. OTA 링크 미확정 자체가 비용 기록 보류 원인이 되지 않는다.

**보호:** 카드 원본 금액·통화·ID/중복·취소/환불·이미 기록된 비용·권한·Google은 무결성 우선. 아직 연결을 추정한 OTA 예약번호를 Google B:H 7열의 예약번호 F열에 **확정값으로 쓰지 않는다**. 사용자가 예약을 명시적으로 확정하지 않았다면 복사 출력에서는 해당 칸을 비우되 비용 1행은 유지. 사용자 여행 A→B 이동은 AI/새 매칭·재수집보다 우선한다. 새로운 OTA 실제 결제 근거만으로 카드 비용 행을 추가 생성하지 않는다.

## 1. 실제 코드에서 확인된 고장 가능 지점

| 코드 | 확인된 구조 | 필수 개선 |
| --- | --- | --- |
| `app/ota_payments.py::_eligible_cards` | 결제일이 없으면 즉시 빈 후보 | 후보 탐색은 `paid_on=None` 허용; 확정 수준에서 날짜 증거 미확인 표시 |
| `app/ota_payments.py::_portal_events` | `paid_today`, 결제 상태, 카드 끝4, 5개 근거 역할 등 조건을 충족하지 못하면 `continue`로 이벤트 제외 | 원본 관측별 `ExtractionOutcome`/다중 실패 사유 저장. 카드 비용을 새로 만들지는 않음 |
| `app/ota_portal.py::_read_records` vs `app/ota_payments.py` | 원본 DB별 동일 `record_id` 가능하지만 source ID `portal:record:{record_id}:payment:{payment_identity}`는 DB 계보를 생략 | `source_lineage_id`와 `payment_event_id` 분리, legacy crosswalk |
| `webapp/card_flow.py::_is_ota_row` | Trip/Agoda/Klook/Booking 문자열만 판정; NICE 결제대행사 승인 alias와 불일치 가능 | 승인된 config alias를 쓰는 중앙 provider resolver |
| `webapp/card_flow.py::_compute_ota_report` | `match_mail → extend_report → ota_exact.apply_gate` 호출 | legacy는 shadow 비교, 통합 코어가 유일한 대사 결과 제공 |
| `webapp/ota_payment_review.py::CoreOtaPaymentBackend._data` | legacy pin 복원 + 새 `match_ota_payment_events`로 별도 계산 | 사용자 결정/기존 링크 보존, 변경 원인 trace, 같은 run snapshot 사용 |
| `webapp/card_flow.py::_ota_group_holds_base` | OTA-first `authority`에서 미확정 카드에 `ota_authority_unresolved` hold | **OTA 홀드와 금융 hold 분리**, 정상 카드의 내부 준비 허용 |
| `app/ota_mail.py::extract_mail` | 메일 발송일 `sent_day`를 `paid_on`에 사용 | 실제 명시 결제일과 메일 발송일 프록시를 다른 날짜 semantics로 |
| `webapp/ota_snapshot.py` | 비동기 지문·마지막 성공 결과 | `run_id`, 카드/OTA 입력 지문, 계산 시각, freshness를 표시하고 stale 결과를 확정으로 오인 금지 |

**과거 근거:** 2026-10-08 읽기 전용 검증의 결제 사건 383건 중 정확 연결 200/카드 없음 90/결제일 불명 59/모호 21/금액 불일치 13. 카드 기준 미연결 177 중 금전 사건 증거 없음 145. 2026-10-16 보고의 기록된 OTA 552 중 283은 당시 신규 코어의 확정 근거가 없었다. **서로 다른 분모와 과거 스냅샷이며 현재 운영 상태/실제 오류 수를 뜻하지 않는다.**

## 2. 목표 구조 및 코드 소유권

```text
Agoda/Trip/Klook/Booking raw + verified mail + 카드 매입
            ↓              (raw evidence 불변)
    Source Registry / source lineage
            ↓
    ExtractionOutcome + Canonical Observations
            ↓
    Bidirectional Candidate Search (날짜 미상 허용)
            ↓
    Edge Evidence: MATCH / MISMATCH / UNKNOWN
            ↓
    기존 전역 Solver (1:1, 같은 금액 N:M, 점유, 수동 pins)
            ↓
    ReconciliationDecision + MatchTrace (유일 결과 계약)
              ↙                        ↘
    OTA 후보 정보                Card Financial Eligibility
              ↘                        ↙
              Trip Ranker + Manual Override
                             ↓
                 Independent Expense Readiness
                             ↓
                COST 내부 지출 준비 / B:H 미리보기
                             ↓
                     사용자 직접 Google 복사
```

모듈(제안; 경로는 만들기 전 레포 중복 존재 여부 확인):
- `app/reconcile/source_lineage.py`: source 계보/복사본/과거 ID 매핑.
- `app/reconcile/observations.py`: OTA/메일/카드 표준 DTO, `ExtractionOutcome`. 기존 파서 재사용.
- `app/reconcile/provider_alias.py`: 중앙 승인 alias 분류(`config/ota-matching-defaults.json` 재사용).
- `app/reconcile/candidates.py`: 날짜 누락에도 작동하는 순수 후보 검색.
- `app/reconcile/evidence.py`: hard conflict / unknown / positive corroboration.
- `app/reconcile/solver.py`: **기존 `app/ota_payments.py` 전역 matching 로직을 위임 또는 단계적 이전**, 재구현 금지.
- `app/reconcile/trace.py`: 관측 단계별 탈락 이력과 전체 감사.
- `app/reconcile/readiness.py`: 카드 금융 상태에 기반한 내부 준비 판정.
- `webapp/ota_payment_review.py`: 현 수동 `OtaReviewStore`와 snapshot/UI owner adapter.
- `webapp/card_flow.py`, `webapp/card_actions.py`: readiness 단일 결과 적용, OTA 미연결은 안내만.
- `tools/audit_ota_card_coverage.py`: 별도 권한 있는 운영 PC에서 실행하는 읽기 전용 감사.
- `config/test-impact-map.json`, `tools/select_targeted_tests.py`: 도메인별 표적 검사(기존 V3 문서의 구조 사용).

기존 DB·파일·API를 한 번에 전면 교체하지 않는다. **단일 writer, 순수 함수 중심, 하위 호환 adapter**로 순서대로 옮긴다.

## 3. ID·데이터 계약

### 3.1 source 관측과 실제 결제 사건을 구분

- `source_lineage_id`: 최초 수집/복원된 원본 증거의 계보; 경로가 바뀌어도 안정적. 복구 DB를 다른 실제 결제인 양 세지 않는다.
- `observation_id`: `(source_lineage_id, local_record_id, component_index, evidence_role, event_kind)`에서 안정 생성. DB A의 record=0과 DB B의 record=0은 서로 다른 관측.
- `payment_event_id`: 동일 제공자의 **검증된 실제 결제 ID/공통 binding**으로 여러 관측을 묶은 논리 사건. 원본 동일한 `record_id`/금액/날짜만으로 서로 다른 결제를 확정 병합하지 않는다.
- `card_transaction_id`: 기존 진짜 매입 원행. 동일 업로드 복사본은 `duplicate_of`로 배제.
- `legacy_ota_event_id → canonical_observation/payment_event_id` crosswalk를 보존. 기존 사용자 매칭·frozen group·기록된 장부 재연결 금지.
- 계보 판단 불충분한 backup/shadow 사본은 `POSSIBLE_SOURCE_COPY`로 진단; 둘 다 새로운 실결제라고 보지 않는다. 확정 불가능하면 수동 확인이나 기존 매핑 보존.

**현재** `config/ota-sources.production.json`에 11개의 Agoda draft/shadow/staging/backup DB가 등록돼 있음. **실운영 manifest도 동일하다고 가정 금지**. 운영에서 확인한 실제 파일별 역할 `authoritative_observation | signed_mail | historical_recovery | diagnostic_output`을 별도 관리. 과거 분석 산출물은 자동 신규 결제 생성의 권위가 아니다.

### 3.2 정규화된 관측 DTO

```json
{
  "schema_version":"recon-observation-v1",
  "observation_id":"opaque-stable",
  "source_lineage_id":"original-collection",
  "source_digest":"sha256-hex",
  "provider":"agoda",
  "booking_ref":"private-original-reference",
  "payment_event_id":null,
  "event_kind":"payment_claim",
  "payment_state":"paid_claimed",
  "amount":{"currency":"KRW","decimal_text":"120000"},
  "payment_date":{"value":null,"semantics":"missing","origin":"portal"},
  "card_hint":{"issuer":null,"last4":"8835"},
  "service_period":{"starts_on":"2026-09-25","ends_on":"2026-09-28"},
  "extraction":{"outcome":"EXTRACTED","reason_codes":[]}
}
```

`event_kind`: `reservation | payment_claim | paid_charge | refund_claim | completed_refund | scheduled_charge | card_posting`.  
`payment_date.semantics`: `explicit_charge | mail_sent_proxy | scheduled | observed_at_only | missing`. 출처의 관측일이나 숙박 체크인 날짜를 실제 카드 청구일로 합성 금지. 실제 카드 매입이 별도 입증된 **예정 결제**는 기존 사용자 승인 예외(날짜·금액·카드 일치 + 충돌 없음) 전용 평가로 처리.  
원화/외화 금액 비교는 `Decimal`로 유한값, 원화 실제 매입액을 OTA 환산값으로 덮지 않는다. 카드사/끝4 명시적 불일치, 통화·금액 모순, 구매/환불 방향 불일치는 hard blocker.

### 3.3 ExtractionOutcome: **원본을 읽었는데도 버린 이유**

원본 한 행을 읽을 때마다 `observation_id, parser_version, outcome, reason_codes, extracted_event_ids, source_digest`를 남긴다.

`outcome`은 `CHARGE_EXTRACTED | CLAIM_ONLY | RESERVATION_ONLY | SKIPPED | CONFLICT`.  
대표 사유 `REQUIRED_EVIDENCE_ROLE_MISSING, PAYMENT_COMPONENT_MISSING, PAYMENT_STATE_UNVERIFIED, CARD_HINT_MISSING, REFUND_CONFLICT, INVALID_PERIOD, AMOUNT_MISSING, MULTIPLE_BOOKING_REFS, UNSUPPORTED_MAIL_TEMPLATE`.

**중요:** 파서 결과가 `SKIPPED`라도 원본 자체는 감사 자료에 남는다. 그러나 이를 `paid_charge`로 승격시키거나 금액을 추측하지 않는다.

## 4. 후보 검색 / 매칭 / N:M 계약

### 4.1 후보 검색은 진단을 위해 넓히고, 확정은 별도

`search_candidates(observations, cards, policy)`는 pure function. 카드 결제일이 없거나 OTA 결제일이 없어도 다음 순서로 찾는다.

1. 동일 체계 결제/승인 ID, 카드사+끝4, 정확 통화·금액, 승인된 결제대행사 alias로 우선 필터.
2. `paid_on` 명시 시 기존 exact 날짜/외화 1일/승인 lag 규칙 우선. 불일치 후보는 진단/추정으로 남길 수 있지만 exact가 아님.
3. `paid_on` 미기록 시 정확 금액·통화·카드 끝4·업체 등의 조합으로 탐색; 날짜 `UNKNOWN` 상태. 기간 제약/확장 범위는 설정·인덱스로 제한하며 결제일 미상이 전체 기간 무제한 카테시안 곱이 되어서는 안 된다.
4. 승인된 alias를 중앙 `provider_alias`에서 해석: 기존 `나이스정보통신`, `트립닷컴(구)_NICE`, `AGODA_NICE-Agoda` 등 승인 레코드. 검증 없는 alias를 임의 승격 금지.
5. 결과를 `signals=[{field,result:MATCH|MISMATCH|UNKNOWN,source,policy_version}]`와 `hard_conflicts`, `candidate_rank`로 반환. 추정 점수를 실제 확률(예: 98%)로 표기 금지.

**절대 배제:** 본래 중복·파싱 오류 카드, 명시적 issuer/last4 불일치, 양쪽 통화·금액의 설명되지 않은 불일치, 구매↔환불 방향 모순, 서로 다른 명시적 동형 payment ID, 이미 다른 사용자 링크에 점유된 카드 자동 재사용.

`INFERRED`는 "가장 유력한 OTA 예약"이지 "그 예약에 실제 결제가 확정"이 아니다. `EXACT`는 검증된 금전 사건·카드 매입·충분한 배타 증거를 갖춘 경우만. 단독 카드가 유효하지만 OTA 근거를 못 찾으면 `UNLINKED`이고 역시 내부 준비 허용.

### 4.2 반복 결제와 분할 청구

- OTA 동액 사건 2, 실카드 동액 원행 2는 2:2 `GROUP_RECONCILED`. 원행 2건을 각각 한 번만 내부 비용에 포함; 개별 예약번호는 확정 근거가 없으면 복사에서 공란.
- OTA 2 : 카드 3, 또는 OTA 3 : 카드 2는 그룹 자체를 정확 완료라고 하지 않는다. 카드는 각자의 금융 상태가 `ELIGIBLE`이면 **개별 여행 우선배정/내부 준비 가능**; 그룹 연결은 추정/부분 상태.
- 카드 2개가 같은 파일 재업로드로 각각 두 번 들어오면 실제 4건이 아니다.
- 한 예약을 40,000+60,000으로 분할 결제한 1:N 사례는 원본 payment ID·분할 내역 등의 명시 증거가 있을 때 별도 모델. 금액 합계만으로 임의 병합하지 않는다.
- 환불·취소 N:M은 구매 대사와 별도 보호; 0원 소계/부분환불 이력/기존 frozen pins 유지. 이미 정리한 사용자의 그룹을 새 정렬로 조용히 바꾸지 않는다.
- PR #87의 동액 문자열 `30000`/`30000.00` Decimal 정규화 보완은 **main `f8ccd13`에 병합됐으나 표적 테스트 실행은 확인되지 않았다**. 새 작업은 main의 해당 구현을 기준으로 필요한 표적 테스트를 먼저 실행한다.

## 5. 금융 준비 순수 함수 / write path

```python
def evaluate_expense_readiness(card, financial, trip, existing_ledger, ota_resolution):
    if existing_ledger.contains_expense(card.transaction_id):
        return "READY_ALREADY_SAVED"  # 재삽입 금지
    if financial.state != "ELIGIBLE":
        return "BLOCKED_FINANCIAL"
    if trip.authoritative_trip_id is None:
        return "NEEDS_AUTHORIZED_TRIP"
    return "READY_FOR_INTERNAL_SAVE"  # OTA가 EXACT/INFERRED/UNLINKED여도 동일
```

경비 readiness 필수 **금융 검증**은 카드 중복/승인·매입 중복/원결제·부분취소·환불 누락/업로드 출처와 원본 금액/기록 중복 여부. OTA 스냅샷만 실패하거나 날짜가 없다는 이유로 정상 카드 준비를 막지 않음. 단, 카드 금융 상태 판단에 필요한 원본 자체를 못 읽었으면 유효하다고 가정하지 않는다.

기존 `webapp/card_flow.py::_ota_group_holds_base`를 무턱대고 삭제하지 않는다. `ota_authority_unresolved`(예약 근거 미확정만)과 `refund_pair_mismatch`, `row_flagged`, `group_reserved_by_conflict`(실제 금융 불확실)를 구분해 readiness에 전달한다. OTA 추정 그룹이 카드 **중복 점유/이중 기장**을 일으킬 수 있으면 금전 무결성 검사 우선. 기존 `LedgerStore.save` revision/idempotency/owner 경로, `board_manual_overrides` 보존. **신규 무승인 전기 루프 생성 금지**.

여행 후보가 둘 이상이면 사용자 승인 V3 순위대로 하나를 선택하고 `AUTO_INFERRED/low` 표시. 사용자 A→B 이동은 즉시 DB 저장·감사 남김, AI 실패/다음 대사에도 B 고정. 외부 Google은 자동 쓰지 않으며 Google B:H의 E열(예약번호)은 추정일 때 공란. 확정 원카드의 가맹점/비용항목/일자/금액은 기존 출력 계약대로.

## 6. Read-only P0 실운영 진단 우선

**첫 PR은 매칭/회계 동작 변경이 아니라 현황 진단만 구현한다.** 권한 있는 PC에서 다음 CLI를 실행하도록 구현:
`python tools/audit_ota_card_coverage.py --read-only --output-dir APPROVED_LOCAL_PATH`.

입력: 운영의 *실제 등록된* manifest, mail/portal 출처, 카드 원행/중복·환불 상태, 기존 user links/frozen pins, legacy exact 결과, 최신 snapshot generation/age, 승인된 alias/rules. SQLite는 `mode=ro` 또는 승인된 일관성 백업 스냅샷을 읽으며, 운영 DB/파일/캐시 생성·마이그레이션·예약/Google 쓰기 금지.

단계별 `observations_in/out`, `SKIPPED` 사유, 카드 원행 수, OTA 실제 결제 증거 수, 후보 수, claimed/pinned 충돌 수, stale 결과 수, readiness 변화를 **양방향** 집계.

필수 진단 코드:
```text
SOURCE_UNREGISTERED / SOURCE_MISSING / SOURCE_UNREADABLE
RAW_OBSERVATION_FOUND / POSSIBLE_SOURCE_COPY / SOURCE_ID_COLLISION
EXTRACTION_SKIPPED / PAYMENT_COMPONENT_MISSING / CARD_HINT_MISSING
PAYMENT_STATE_UNVERIFIED / PAID_DATE_MISSING / MAIL_DATE_ONLY
CARD_VALID / CARD_DUPLICATE / CARD_FINANCIAL_HOLD
CANDIDATE_FOUND / AMOUNT_MISMATCH / CURRENCY_MISMATCH / CARD_IDENTITY_MISMATCH
PROVIDER_ALIAS_MISSING / CANDIDATE_OCCUPIED / N_M_PARTIAL
LEGACY_NEW_CORE_DISAGREEMENT / SNAPSHOT_STALE / EXPENSE_READY
```

출력 로컬 전용 `coverage-summary.json`(provider별·단계별 집계), `unmatched-cases.jsonl`(카드/OTA 후보 근거·사유), `legacy-diff.jsonl`(구/신엔진 차이, 사용자 확정 충돌). 카드/고객 실명·실예약번호·원문 메일·카드번호 원문을 보고서·Git·무료 모델에 보내지 않는다. 외부에 공유할 비식별 식별자는 서버 비밀키로 pseudonymize(단순 짧은 예약번호 SHA 해시 금지). 단계별 실패 이유는 복수 저장하며 실제 금전 증거가 없는 예약도 원본 존재 상태는 집계. 전수 진단 실패/등록 소스 누락은 `INCOMPLETE_SOURCE_SET`으로 명시하고 새 매칭 승인 0.

최종 지표:
- `extraction_gap`: 원본 관측은 있는데 금전 이벤트가 생성되지 않은 수 + 이유.
- `candidate_recall_proxy`: 기존 후보 0이지만 새 후보 검색에서는 1개 이상 나온 수(정답 매칭률로 주장 금지).
- `legacy_divergence`: 기존 확정/추정과 신규 결과의 차이 수.
- `ready_lift`: 정상 카드인데 과거 OTA 홀드만으로 내부 비용 준비가 막혔던 건수.
- `duplicate_expense_delta=0`, `existing_owner_decisions_changed=0`은 필수.
- 기준 집계 분모는 카드 실원행, OTA 관측, OTA 검증된 결제 사건을 **각각 별도** 표기. 실제로 확인된 golden subset이 없으면 precision/recall 확률 추정 금지.

## 7. 저장/조회/API 제안

논리 테이블/기존 storage 매핑:
`evidence_sources(source_id, lineage_id, role, digest, revision, state)`;
`reconciliation_observations(observation_id, source_id, raw_local_id, event_kind, extraction_outcome, reasons, normalized_json)`;
`reconciliation_id_crosswalk(legacy_event_id, canonical_id, resolution_state)`;
`reconciliation_runs(run_id, source_digest, card_digest, policy_version, pin_digest, state, calculated_at)`;
`reconciliation_candidates(run_id, observation_id, card_transaction_id, signals_json, conflicts_json, rank)`;
`reconciliation_decisions(decision_id, run_id, card_transaction_id, observation_id?, group_id?, evidence_level, authority_source, revision)`.

**구현 시 기존 OtaReviewStore schema를 조사해 중복 테이블/중복 writer를 만들지 않는다.** run 단위 append-only trace와 최신 projection 구분. 카드/원본/사용자 override는 불변; `legacy_event_id` crosswalk가 확정되지 않으면 기존 링크는 유지하고 `MIGRATION_PENDING`.

API(경로는 기존 인증 router 조사 후 확정):
- `GET /api/imports/ota/diagnostics`: owner 전용, 집계·opaque ID·스냅샷 신선도; GET에서 대사 재실행/DB 변경 금지.
- `GET /api/imports/ota/diagnostics/{id}`: 개별 원본 존재/추출 결과/후보 근거/현재 카드 금융 상태/기존 링크.
- 기존 OTA `preview/confirm`은 `OtaReviewStore` 하나의 write path로. CSRF/owner/expected revision/evidence digest/idempotency/유일 카드 점유 확인.
- `GET /api/expenses/{card-id}/readiness`: 카드 금융/OTA/여행/Google 상태 독립 노출.
- 기존 V3 `PATCH /api/expense-assignments/{id}` 설계를 수동 여행 이동에 사용.
- 기존 `dialog_turn` 및 규칙 승인 모듈을 통해 사후 AI 1·2·3 답변, 추가질문, 범위 선택, 영향 preview, 명시 승인.

UI는 **카드 비용 상태 / OTA 연결 상태 / 여행 배정 상태**를 별도 표시. "예약 연결 안 됨"이란 이유만으로 거래를 숨기거나 미배정에 모으지 않는다. 예약번호가 불확실해도 거래가 실제 카드 매입이라는 사실은 그대로 나타낸다.

## 8. 단계별 PR 수행 절차 (각 단계 1개 책임)

| PR | 구현 | 인수 테스트/종료 조건 |
| --- | --- | --- |
| **R0** | 읽기 전용 `audit_ota_card_coverage.py`, 단계별 ExtractionOutcome·MatchTrace | 실제 원본을 바꾸지 않고 카드↔OTA 양방향 미매칭 사유를 집계, 쓰기 0 |
| **R1** | source lineage/관측 식별자/legacy crosswalk | 다른 DB의 동일 record=0 충돌 없음, 증명된 동일 결제 사본만 중복 제거, 기존 사용자 pin 유지 |
| **R2** | 결제일 미상 후보 검색 + 공통 merchant resolver | 날짜 없는 120,000원 Agoda+카드8835 후보 생성; 미확인 예약 확정 0 |
| **R3** | 기존 전역 solver를 유일 결과 계약으로 표준화 | 1:1, N:M, 점유, frozen group, legacy diff, 입력 순서 독립 |
| **R4** | A 정책 readiness + 여행 자동귀속 + UI | 정상 카드·OTA 미연결도 READY, 카드 중복/환불 BLOCK, Google 자동 쓰기 0 |
| **R5** | 여행 이동/OTA 사용자 연결 사후 AI 1·2·3 대화·승인 학습 | 사용자가 옮긴 B가 모델/재대사 오류 후에도 유지, 승인 규칙만 미래 적용 |
| **R6** | `off → shadow → read → enforce` 운영 전환 및 구 경로 축소 | 계보/원장/수동 결정 보존, rollback 가능, 마지막 비교 완료 |

첫 PR(R0)이 운영 데이터를 실제로 전수 분석하기 전에는 R1~R4가 오매칭을 몇 건 해결한다고 주장하지 않는다. R0 자체도 코드·합성 테스트와 읽기 전용 실제 실행 결과를 분리 보고한다.

## 9. 표적 회귀 테스트와 자동 선택

최소 실질 테스트(합성 fixtures만):
- `test_missing_paid_on_produces_candidate_not_exact`
- `test_portal_missing_paid_today_has_extraction_outcome`
- `test_cross_database_same_local_id_never_merges_distinct_payment`
- `test_verified_recovery_copy_does_not_duplicate_charge`
- `test_approved_nice_alias_is_shared_by_card_flow_and_core`
- `test_card_valid_without_ota_still_ready_for_internal_save`
- `test_card_duplicate_or_unresolved_refund_never_ready`
- `test_nm_two_by_two_keeps_two_expenses_and_unknown_booking_identity`
- `test_partial_nm_cards_can_be_ready_without_claiming_exact_match`
- `test_existing_manual_pin_survives_reconciliation_and_migration`
- `test_low_confidence_trip_assignment_is_real_assignment`
- `test_user_a_to_b_move_survives_refresh_and_model_failure`
- `test_unconfirmed_booking_ref_is_blank_in_google_preview`
- `test_reconciliation_has_no_google_write_path`
- `test_stale_snapshot_not_promoted_to_fresh_result`
- `test_read_only_audit_changes_zero_operational_bytes`

파일·모듈 단위로 표적 pytest + 직접 인접 계약만 실행. `config/test-impact-map.json`에서 변경 파일→검사 그룹을 선택하고 알려지지 않은 파일은 `UNKNOWN_IMPACT`를 보고해 관련 안전 계약 1회 추가. 환불/장부 쓰기/실 배포 경계 변경일 때만 더 넓은 보호 검사를 수행. 테스트 실행하지 않았으면 통과로 기재 금지.

## 10. 플래그·cutover·rollback

새 제안 환경변수(아직 구현되지 않음): `WEBLEDGER_RECONCILIATION_V2_MODE=off|shadow|read|enforce`.

- `off`: 현재 코드 그대로.
- `shadow`: 신규 후보·trace/READY 계산, 운영 장부·사용자 연결에 **반영 0**; 기존 결과와 diff.
- `read`: owner UI에서 신 결과/미매칭 원인/추정 예약을 표시, 기존 실제 쓰기 경계 유지.
- `enforce`: 수동 승인 후 중앙 대사 결과를 유일 참조; 독립 카드 금융 상태로 A 정책 내부 준비 적용, Google 자동 쓰기는 여전히 0.

전환 전: 현재 운영 manifest/카드 원본/미완료 환불/수동 link·frozen group/이미 기록된 `board_rows`·`ledger_entries` snapshot/해시, migration crosswalk, 복원 근거를 확보. cutoff 전후 카드 금액·원본 해시·사용자 변경 0, 허위 OTA 실제 결제 신설 0, 카드 중복 비용 0. rollback은 플래그와 이전 호환 저장 구조로 하며 기존 확정·대화 기록 삭제 금지.

### 현재 COST 코드의 중앙 결과와 복구 경로

`CardFlow._ota_report()`는 fresh OTA snapshot이 있으면 중앙 `app.ota_payments` 결과만 기존 카드 화면 계약으로 투영한다. legacy 메일·포털 matcher는 이 경로에서 실행하지 않는다. 계산 중 snapshot이 fresh로 바뀌면 앞서 만든 legacy 결과를 버리고 새 중앙 결과만 반환한다. 중앙 snapshot이 없거나 stale이면 기존 사용자의 결정과 복구 기능을 보존하기 위해 `_compute_ota_report()`를 안전한 복구 fallback으로 쓰며 응답의 `_reconciliation_authority`에 fallback 이유를 표시한다. `reclassify_cleanup()`의 직접 호출은 fallback 자료를 준비한 뒤 새 snapshot 계산을 요청하는 경로다.

이 fallback은 신규 중앙 snapshot의 결정을 덮지 않으며 진단 전용도 아니다. stale 상태에서의 제한된 복구 결정 경로다. 중앙 snapshot 생성·freshness 복구가 모든 지원 자료와 기존 수동 연결을 처리하고 stale 복구 검사가 통과하기 전에는 제거하지 않는다. `legacy_exact_bindings()`는 별도 감사 도구의 비교 진단 전용이며 웹 요청의 정본 결과에 연결하지 않는다.

**절대 금지:** Google 직접 쓰기, 실예약번호·카드 원문을 공개 무료 모델에 전송, paid_on/예약번호/한글이름 창작으로 금전 이벤트 확정, 원카드 비용 합산/분할 추정, 기존 수동 여행 B 덮어쓰기, 위임 모델에 운영 원본 제공, 무관한 전체 회귀 무한 반복.

## 11. 무료 코딩 모델 인수 지시

첫 번째 작업은 **R0, read-only 미매칭 전수 진단기 + 합성 테스트**다. `AGENTS.md`, 본 문서, `app/ota_payments.py`, `app/ota_mail.py`, `app/ota_portal.py`, `app/ota_exact.py`, `app/ota_review.py`, `webapp/ota_payment_review.py`, `webapp/card_flow.py`, `docs/ota-matching-terms.md`를 읽고 **이미 있는 기능을 재구현하지 않는다**. DISCOVER → CONTRACT → IMPLEMENT → TARGETED TEST → REVIEW → COMMIT/PR. 기능별 작은 PR로 후속 R1~R6 수행한다. 각 단계는 구현·검증·미검증을 분리해 보고하고 운영 변경은 별도 승인 없이 진행하지 않는다.
 


## 12. 구현 가능한 핵심 DB DDL 예시 (새 DB 또는 기존 review DB 재사용)

**DDL은 제안이며 실행 지시가 아니다.** 먼저 실제 `OtaReviewStore`의 schema, WAL/locking, user pin 저장 위치를 확인한다. 동일 개념 테이블이 있으면 아래 논리 스키마를 기존 테이블에 매핑한다. 운영 본 장부 테이블을 갈아엎지 않는다.

~~~sql
CREATE TABLE IF NOT EXISTS reconciliation_runs (
  run_id TEXT PRIMARY KEY,
  source_set_digest TEXT NOT NULL,
  card_set_digest TEXT NOT NULL,
  policy_version TEXT NOT NULL,
  pins_digest TEXT NOT NULL,
  status TEXT NOT NULL CHECK (status IN ('complete','incomplete','failed')),
  generated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS reconciliation_observations (
  observation_id TEXT PRIMARY KEY,
  source_lineage_id TEXT NOT NULL,
  source_record_id TEXT NOT NULL,
  source_digest TEXT NOT NULL,
  kind TEXT NOT NULL,
  parsed_facts_json TEXT NOT NULL,
  extraction_outcome TEXT NOT NULL,
  failure_codes_json TEXT NOT NULL,
  parser_version TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS reconciliation_candidate_edges (
  run_id TEXT NOT NULL,
  observation_id TEXT NOT NULL,
  card_transaction_id TEXT NOT NULL,
  tier TEXT NOT NULL,
  signals_json TEXT NOT NULL,
  blockers_json TEXT NOT NULL,
  rank INTEGER,
  PRIMARY KEY(run_id, observation_id, card_transaction_id)
);
CREATE TABLE IF NOT EXISTS reconciliation_id_crosswalk (
  legacy_event_id TEXT PRIMARY KEY,
  canonical_observation_id TEXT NOT NULL,
  resolution_status TEXT NOT NULL,
  migration_version TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS recon_edges_card
  ON reconciliation_candidate_edges(run_id, card_transaction_id);
~~~

- 저장 결정 `reconciliation_decisions`는 **기존 수동 link·group pins의 단일 writer를 재사용**하고, 계산 이력은 별도 append-only run/result projection으로 저장한다. 서로 다른 run이 한 카드에서 서로 다른 추정을 내더라도 사용자 확정을 수정하는 UPDATE는 없다.
- `source_digest`와 `source_lineage_id`는 다르다. digest가 같아도 출처 역할과 실제 금전 사건의 고유 증거를 확인하기 전에는 단일 charge 병합을 확정하지 않는다.
- 마이그레이션은 우선 테스트 fixture와 격리 DB만. 한 rollback에서 구 snapshot·구 manual pin을 온전히 읽을 수 있어야 한다.

## 13. 순수 함수 수준 의사코드와 단계별 실패 진단

~~~python
def explain_source(raw, parser):
    result = parser.extract_with_reasons(raw)
    # parse 실패를 예외 처리로 조용히 버리지 않고 observation에 남긴다.
    return ExtractionOutcome(
        source_id=raw.identity,
        outcome=result.kind,
        facts=result.facts,
        reason_codes=tuple(sorted(set(result.reasons))),
    )

def reconcile_v2(observations, card_rows, manual_links, group_pins, policy):
    normalized = normalize_sources_and_cards(observations, card_rows, policy)
    candidates = search_candidates(
        normalized.events, normalized.card_rows, policy,
        allow_missing_payment_day=True,  # 조회 가능, 정확 연결 확정과 별개
    )
    evaluated = evaluate_all_edges(candidates, policy)
    resolved = solve_using_existing_global_matcher(
        evaluated, manual_links=manual_links, group_pins=group_pins
    )
    return ReconciliationRun(
        decisions=resolved,
        candidate_edges=evaluated,
        trace=explain_pipeline(normalized, candidates, evaluated, resolved),
        source_digest=normalized.source_set_digest,
        policy_version=policy.version,
    )
~~~

**필수 실패 진단 예:** Agoda 원본 100건 → 관측 100건(그중 3건 원본 DB 계보 충돌) → 유효/불완전 payment claim 95건 → 실제 결제 증거 84건 → 카드 후보 72건 → 전역 solver에서 66건 대응. 이 숫자는 *가상의 단위 테스트 사례*이며 실운영 통계가 아니다. 추출에서 5건이 빠진 이유와 그 5건의 원본 ID는 감사에 남아야 한다.

## 14. API 응답 계약 예시와 화면

~~~json
{
  "card_transaction_id": "card:opaque",
  "financial_state": "ELIGIBLE",
  "ota_resolution": {
    "level": "INFERRED",
    "candidate_count": 1,
    "booking_ref_confirmed": false,
    "reason_codes": ["PAID_DATE_MISSING"],
    "evidence_signals": [
      {"kind": "amount", "result": "MATCH"},
      {"kind": "card_last4", "result": "MATCH"},
      {"kind": "payment_day", "result": "UNKNOWN"}
    ]
  },
  "trip_assignment": {
    "trip_id": "trip-existing",
    "authority": "AUTO_INFERRED",
    "confidence": "low",
    "user_override": false
  },
  "expense_preparation": {
    "state": "READY_FOR_INTERNAL_SAVE",
    "google_booking_ref_export": "",
    "google_write_permitted": false
  },
  "trace": {
    "run_id": "recon-run:opaque",
    "snapshot_state": "fresh",
    "source_set_digest": "sha256:...",
    "reconciliation_policy_version": "A-v1"
  }
}
~~~

모든 API는 기존 라우터의 owner 인증·CSRF·재조회 방지·rate 제한·필드 allowlist를 따른다. Trace 상세 API는 예약번호·실명·원본문서를 다른 역할이나 공개 API에 반환하지 않는다. 사용자 수동 재연결은 현 preview digest와 데이터 revision이 일치할 때만 저장; 브라우저에 오래된 근거가 남았으면 `409 STALE_EVIDENCE`를 돌리고 새 근거 검토만 요청한다. Google 저장 API는 만들지 않는다.

## 15. P0 실행 확인 순서

1. 코드/원본 역할·활성 환경변수·스키마를 **읽기 전용**으로 발견한다.
2. 합성 케이스 6개(결제일 미상, `paid_today` 누락, 다른 DB record=0, NICE alias, 2:2, 기존 수동 pin)로 진단 결과 생성.
3. 운영에서는 **승인된 읽기 전용 복제 스냅샷**과 안전한 로컬 출력 경로를 사용해 실제 coverage만 산출한다. 실제 운영 원본은 열람 전후 변경 0.
4. `coverage-summary.json`에서 **어디에서 이벤트를 버렸는지**, `unmatched-cases.jsonl`에서 **카드 존재↔OTA 원본 존재인데 후보 없음 사례**를 각 제공자별로 구분한다.
5. 상위 원인이 검증되면 R1~R4 순서로 작은 PR을 작성한다. 매칭률 개선 수치는 실제 P0 기준선 이후에만 제시한다.
